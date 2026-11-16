#!/usr/bin/env python3
"""Builds the Skia checkout in ./skia (see fetch-skia.py) and packages it.

  build.py <os> <arch> [--tag TAG]
  build.py android <arm64|x64> --ndk <path>                         (or ANDROID_NDK_HOME)
  build.py wasm wasm32 --emscripten toolchains/emscripten-<band>     (see fetch-emscripten.py)
  build.py <ios|ios-simulator|tvos|tvos-simulator|maccatalyst> <arch> --no-archive   (see package-apple.py)

<os> is linux, macos, windows, android, wasm, or an Apple mobile slice (packaged by package-apple.py). The archive is release/skia-<TAG>-<platform>.tar.gz, where the
platform is <os>-<arch>, or wasm-emscripten-<version> for WebAssembly. It holds the headers (include, modules, src
and the third-party headers they use), the static libraries in out/Release-<platform>, that directory's args.gn and
defines.txt, and build-info.json.
"""

import argparse
import contextlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIA = ROOT / "skia"
ARTIFACTS = ROOT / "artifacts"
RELEASE = ROOT / "release"

ARCHES = {
    "linux": {"x64", "arm64"},
    "macos": {"x64", "arm64"},
    "windows": {"x64", "arm64"},
    "android": {"x64", "arm64"},
    "wasm": {"wasm32"},
    "ios": {"arm64"},
    "ios-simulator": {"arm64", "x64"},
    "tvos": {"arm64"},
    "tvos-simulator": {"arm64", "x64"},
    "maccatalyst": {"arm64", "x64"},
}

APPLE_MIN_VERSION = "15.0"

ANDROID_API = 24

# The module libraries. The "modules" group also builds CanvasKit when is_canvaskit is set (WebAssembly).
MODULE_TARGETS = [
    "modules/bentleyottmann:bentleyottmann", "modules/skottie:skottie", "modules/skparagraph:skparagraph",
    "modules/skshaper:skshaper", "modules/svg:svg",
]

# Libraries in the build: core, codecs, PDF, SVG, Skottie, paragraph, shaper and unicode (ICU and HarfBuzz),
# Ganesh and Graphite (Vulkan or Metal; no Dawn).
COMMON_ARGS = {
    "is_official_build": True,
    "is_debug": False,
    "skia_enable_tools": False,
    "skia_use_partition_alloc": False,
    "skia_enable_ganesh": True,
    "skia_enable_graphite": True,
    "skia_use_dawn": False,
    "skia_enable_pdf": True,
    "skia_enable_skottie": True,
    "skia_enable_svg": True,
    "skia_use_icu": True,
    "skia_use_harfbuzz": True,
    "skia_pdf_subset_harfbuzz": True,
    "skia_use_system_expat": False,
    "skia_use_system_harfbuzz": False,
    "skia_use_system_icu": False,
    "skia_use_system_libjpeg_turbo": False,
    "skia_use_system_libpng": False,
    "skia_use_system_libwebp": False,
    "skia_use_system_zlib": False,
}

# Targets whose defines a consumer compiles with (written to defines.txt).
DEFINE_TARGETS = [
    "//:skia", "//modules/skparagraph:skparagraph", "//modules/skottie:skottie", "//modules/svg:svg",
    "//modules/skshaper:skshaper", "//modules/skunicode:skunicode_icu",
]

DEFINE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(=\S*)?")

# Headers outside include/, modules/ and src/ that public headers include.
THIRD_PARTY_HEADERS = [
    "third_party/icu", "third_party/externals/icu/source/common", "third_party/externals/icu/source/i18n",
    "third_party/externals/harfbuzz/src", "third_party/externals/freetype/include", "third_party/externals/libpng",
    "third_party/externals/zlib", "third_party/externals/libwebp/src",
]


def linux_args(arch):
    cc = os.environ.get("SKIA_BUILDER_CC", "clang-20")
    cxx = os.environ.get("SKIA_BUILDER_CXX", "clang++-20")
    args = {
        "target_os": "linux",
        "target_cpu": arch,
        "cc": cc,
        "cxx": cxx,
        "skia_use_vulkan": True,
        "skia_use_system_freetype2": False,
        "extra_cflags": ["-ffunction-sections", "-fdata-sections"],
        "extra_cflags_cc": ["-fno-exceptions", "-fno-rtti"],
    }
    if arch == "arm64":
        args.update({"skia_gl_standard": "gles", "skia_use_egl": True})
        args["extra_cflags"].append("-mno-outline-atomics")
    return args


def macos_args(arch):
    return {
        "target_os": "mac",
        "target_cpu": arch,
        "skia_use_metal": True,
        "skia_use_vulkan": False,
        "extra_cflags": ["-ffunction-sections", "-fdata-sections", "-DHAVE_ARC4RANDOM_BUF"],
        "extra_cflags_cc": ["-fno-exceptions", "-fno-rtti"],
    }


def windows_args(arch):
    return {
        "target_os": "win",
        "target_cpu": arch,
        "clang_win": os.environ.get("SKIA_BUILDER_CLANG_WIN", "C:/Program Files/LLVM"),
        "skia_use_vulkan": True,
        "skia_use_direct3d": True,
        "skia_use_dng_sdk": True,
        "skia_enable_fontmgr_win_gdi": False,
        "extra_cflags": ["/MT", "/EHsc", "/Z7", "/guard:cf", "/Gy", "/Gw", "-D_HAS_AUTO_PTR_ETC=1"],
        "extra_cflags_cc": ["/GR-"],
        "extra_ldflags": ["/DEBUG:FULL", "/DEBUGTYPE:CV,FIXUP", "/guard:cf"],
    }


def android_args(arch, ndk):
    return {
        "target_os": "android",
        "target_cpu": arch,
        "ndk": ndk,
        "ndk_api": ANDROID_API,
        "skia_use_vulkan": True,
        "skia_use_system_freetype2": False,
        "extra_cflags": ["-ffunction-sections", "-fdata-sections"],
        "extra_cflags_cc": ["-fno-exceptions", "-fno-rtti"],
    }


def wasm_args(emsdk_dir):
    # is_canvaskit selects Skia's plain wasm configuration: no forced -pthread and no emsdk sysroot or activation,
    # so the objects link into single-threaded hosts with the toolchain's own system libraries.
    return {
        "target_os": "wasm",
        "target_cpu": "wasm",
        "is_canvaskit": True,
        "skia_emsdk_dir": emsdk_dir,
        "skia_enable_graphite": False,
        "skia_use_webgl": True,
        "skia_use_webgpu": False,
        "skia_use_vulkan": False,
        "skia_use_angle": False,
        "skia_use_fontconfig": False,
        "skia_use_freetype": True,
        "skia_use_system_freetype2": False,
        "skia_use_expat": True,
        "skia_use_libwebp_encode": True,
        "skia_use_piex": False,
        "skia_use_dng_sdk": False,
        "skia_use_lua": False,
        # .NET links WebAssembly apps with WebAssembly exception handling (-fwasm-exceptions), so setjmp and longjmp
        # use it too; Emscripten's JavaScript longjmp is not linked there.
        "extra_cflags": ["-msimd128", "-sSUPPORT_LONGJMP=wasm", "-ffunction-sections", "-fdata-sections"],
        "extra_cflags_cc": ["-fno-exceptions", "-fno-rtti"],
    }


def apple_args(slice_os, arch):
    """iOS, tvOS and Mac Catalyst slices: Metal only (Ganesh and Graphite)."""
    simulator = slice_os.endswith("-simulator")
    platform = slice_os.removesuffix("-simulator")
    args = {
        "target_cpu": arch,
        "ios_use_simulator": simulator,
        "skia_use_metal": True,
        "skia_use_gl": False,
        "skia_use_vulkan": False,
        "extra_cflags": ["-ffunction-sections", "-fdata-sections", "-DHAVE_ARC4RANDOM_BUF"],
        "extra_cflags_cc": ["-fno-exceptions", "-fno-rtti"],
        "extra_asmflags": [],
        "extra_ldflags": [],
    }
    if platform == "ios":
        args.update({"target_os": "ios", "ios_min_target": APPLE_MIN_VERSION})
        return args
    if platform == "tvos":
        # ios_min_target always emits -miphoneos-version-min, so the tvOS version is passed directly.
        version = f"-mtvos{'-simulator' if simulator else ''}-version-min={APPLE_MIN_VERSION}"
        args["target_os"] = "tvos"
    else:
        # Mac Catalyst: an iOS build against the macOS SDK with the macabi triple and the SDK's iOSSupport tree.
        sdk = subprocess.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"], check=True, text=True,
                             capture_output=True).stdout.strip()
        triple = f"{'arm64' if arch == 'arm64' else 'x86_64'}-apple-ios{APPLE_MIN_VERSION}-macabi"
        args.update({"target_os": "ios", "xcode_sysroot": sdk})
        args["extra_cflags"] += ["-isystem", f"{sdk}/System/iOSSupport/usr/include",
                                 "-iframework", f"{sdk}/System/iOSSupport/System/Library/Frameworks"]
        version = f"--target={triple}"
    for key in ("extra_cflags", "extra_asmflags", "extra_ldflags"):
        args[key].append(version)
    return args


# WebAssembly builds keep ICU's version suffix on symbol names (ubrk_open_78), so Skia's ICU does not clash with the
# .NET runtime's ICU, which is linked into the same module without suffixes.
ICU_RENAMING = [
    ("third_party/icu/BUILD.gn", '"U_DISABLE_RENAMING=1",', '"U_DISABLE_RENAMING=0",'),
    ("modules/skunicode/BUILD.gn", 'defines += [ "U_DISABLE_RENAMING=1" ]', 'defines += [ "U_DISABLE_RENAMING=0" ]'),
]


@contextlib.contextmanager
def icu_renaming():
    """Applies ICU_RENAMING to the checkout for the duration of a build."""
    originals = {}
    try:
        for path, old, new in ICU_RENAMING:
            file = SKIA / path
            originals.setdefault(file, file.read_text())
            current = file.read_text()
            if old not in current:
                sys.exit(f"{path} no longer contains {old}")
            file.write_text(current.replace(old, new))
        yield
    finally:
        for file, text in originals.items():
            file.write_text(text)


def wasm_setjmp_shim(emsdk_dir, out_dir):
    """Builds libwasm_setjmp.a when the toolchain's compiler-rt lacks __wasm_setjmp (see scripts/wasm/wasm_setjmp.c)."""
    emscripten = pathlib.Path(emsdk_dir) / "upstream" / "emscripten"
    llvm = pathlib.Path(os.environ["DOTNET_EMSCRIPTEN_LLVM_ROOT"]) if "DOTNET_EMSCRIPTEN_LLVM_ROOT" in os.environ else None
    nm = str(llvm / "llvm-nm") if llvm else "llvm-nm"
    lib_dir = pathlib.Path(os.environ["EM_CACHE"]) / "sysroot" / "lib" / "wasm32-emscripten"
    # compiler-rt is libcompiler_rt*.a up to Emscripten 3, libclang_rt.builtins*.a later.
    runtimes = sorted(lib_dir.glob("libcompiler_rt*.a")) + sorted(lib_dir.glob("libclang_rt.builtins*.a"))
    if not runtimes:
        sys.exit(f"No compiler-rt library in {lib_dir}")
    symbols = subprocess.run([nm, str(runtimes[0])], check=True, text=True, capture_output=True).stdout
    shim = out_dir / "libwasm_setjmp.a"
    if " T __wasm_setjmp\n" in symbols:
        shim.unlink(missing_ok=True)
        return False
    obj = out_dir / "wasm_setjmp.o"
    run([str(emscripten / "emcc"), "-O3", "-msimd128", "-c", str(ROOT / "scripts" / "wasm" / "wasm_setjmp.c"), "-o", str(obj)])
    shim.unlink(missing_ok=True)
    run([str(emscripten / "emar"), "rcs", str(shim), str(obj)])
    return True


def gn_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(gn_value(v) for v in value) + "]"
    return json.dumps(value)


def tool(name):
    """gn is in bin/ (bin/fetch-gn), ninja in third_party/ninja/ (bin/fetch-ninja)."""
    for folder in (SKIA / "bin", SKIA / "third_party" / name):
        for candidate in (folder / (name + ".exe"), folder / name):
            if candidate.exists():
                return str(candidate)
    sys.exit(f"{name} not found: run scripts/fetch-skia.py")


def run(args, capture=False):
    print("+ " + " ".join(args), flush=True)
    result = subprocess.run(args, cwd=SKIA, check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else None


def defines(out_dir):
    found = set()
    for target in DEFINE_TARGETS:
        try:
            text = run([tool("gn"), "desc", str(out_dir), target, "defines"], capture=True)
        except subprocess.CalledProcessError:
            continue
        for line in text.splitlines():
            line = line.strip()
            # gn desc also prints warnings to stdout; keep only NAME or NAME=VALUE.
            if not DEFINE.fullmatch(line):
                continue
            if not line.split("=")[0].endswith("_IMPLEMENTATION") and not line.startswith("U_"):
                found.add(line)
    return sorted(found)


LICENSE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE)S?([._-][\w.-]*)?", re.IGNORECASE)


def copy_licenses(stage):
    """Skia's LICENSE in licenses/skia/, and the license files of each fetched dependency in licenses/<name>/."""
    sources = [("skia", SKIA)] + sorted((d.name, d) for d in (SKIA / "third_party" / "externals").iterdir() if d.is_dir())
    for name, src in sources:
        files = [f for f in src.iterdir() if f.is_file() and LICENSE_FILE.fullmatch(f.name) and f.suffix not in (".cfg", ".html")]
        for f in files:
            (stage / "licenses" / name).mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, stage / "licenses" / name / f.name)


def copy_headers(src, dest):
    for path in src.rglob("*"):
        if path.suffix in (".h", ".hpp", ".inc") and path.is_file():
            target = dest / path.relative_to(SKIA)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("os", choices=sorted(ARCHES))
    parser.add_argument("arch", choices=["x64", "arm64", "wasm32"])
    parser.add_argument("--tag", help="release tag (m<milestone>-<sha10>); read from the checkout when omitted")
    parser.add_argument("--skip-build", action="store_true", help="package an existing build")
    parser.add_argument("--ndk", default=os.environ.get("ANDROID_NDK_HOME") or os.environ.get("ANDROID_NDK_ROOT"),
                        help="Android NDK (default: ANDROID_NDK_HOME or ANDROID_NDK_ROOT)")
    parser.add_argument("--emscripten", type=pathlib.Path, help="toolchain directory written by fetch-emscripten.py")
    parser.add_argument("--no-archive", action="store_true", help="stage the slice in artifacts/ without a tar.gz")
    args = parser.parse_args()
    if args.arch not in ARCHES[args.os]:
        sys.exit(f"{args.os} builds {', '.join(sorted(ARCHES[args.os]))}")
    if not (SKIA / "BUILD.gn").exists():
        sys.exit("No Skia checkout in ./skia: run scripts/fetch-skia.py first")

    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SKIA, check=True, text=True, capture_output=True).stdout.strip()
    milestone = next(int(l.split()[2]) for l in (SKIA / "include/core/SkMilestone.h").read_text().splitlines()
                     if l.startswith("#define SK_MILESTONE"))
    tag = args.tag or f"m{milestone}-{sha[:10]}"

    toolchain = {}
    gn_args = dict(COMMON_ARGS)
    targets = ["skia", "modules"]
    platform = f"{args.os}-{args.arch}"
    if args.os == "android":
        if not args.ndk or not pathlib.Path(args.ndk).is_dir():
            sys.exit("The Android build needs an NDK: pass --ndk or set ANDROID_NDK_HOME")
        ndk = str(pathlib.Path(args.ndk).resolve())
        gn_args.update(android_args(args.arch, ndk))
        props = pathlib.Path(ndk, "source.properties").read_text()
        revision = next((l.split("=", 1)[1].strip() for l in props.splitlines() if l.startswith("Pkg.Revision")), "")
        toolchain = {"ndk": revision, "androidApi": ANDROID_API}
    elif args.os == "wasm":
        if args.emscripten is None:
            sys.exit("The WebAssembly build needs --emscripten (a directory written by fetch-emscripten.py)")
        toolchain = json.loads((args.emscripten / "toolchain.json").read_text())
        os.environ.update(toolchain.pop("environment"))
        gn_args.update(wasm_args(toolchain.pop("emsdkDir")))
        targets = ["skia"] + MODULE_TARGETS
        platform = f"wasm-emscripten-{toolchain['emscripten']}"
    elif args.os in ("ios", "ios-simulator", "tvos", "tvos-simulator", "maccatalyst"):
        gn_args.update(apple_args(args.os, args.arch))
        toolchain = {"minimumOS": APPLE_MIN_VERSION}
    else:
        gn_args.update({"linux": linux_args, "macos": macos_args, "windows": windows_args}[args.os](args.arch))
    config = f"Release-{platform}"
    out_dir = SKIA / "out" / config
    if not args.skip_build:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "args.gn").write_text("".join(f"{k} = {gn_value(v)}\n" for k, v in gn_args.items()))
        with icu_renaming() if args.os == "wasm" else contextlib.nullcontext():
            run([tool("gn"), "gen", str(out_dir)])
            run([tool("ninja"), "-C", str(out_dir)] + targets)
    if args.os == "wasm":
        toolchain["setjmpShim"] = wasm_setjmp_shim(gn_args["skia_emsdk_dir"], out_dir)
        toolchain["icuRenaming"] = True

    name = f"skia-{tag}-{platform}"
    stage = ARTIFACTS / name
    if stage.exists():
        shutil.rmtree(stage)
    for part in ["include", "modules", "src"] + THIRD_PARTY_HEADERS:
        if (SKIA / part).exists():
            copy_headers(SKIA / part, stage)
    copy_licenses(stage)
    lib_dir = stage / "out" / config
    lib_dir.mkdir(parents=True)
    libs = sorted(p for p in out_dir.iterdir() if p.suffix in (".a", ".lib"))
    if not libs:
        sys.exit(f"No static libraries in {out_dir}")
    for lib in libs:
        shutil.copy2(lib, lib_dir / lib.name)
    # Windows builds load ICU's data at run time from icudtl.dat next to the executable or library (SkLoadICU).
    if (out_dir / "icudtl.dat").exists():
        shutil.copy2(out_dir / "icudtl.dat", lib_dir / "icudtl.dat")
    shutil.copy2(out_dir / "args.gn", lib_dir / "args.gn")
    found = defines(out_dir)
    (lib_dir / "defines.txt").write_text("".join(f"-D{d}\n" for d in found))
    info = {
        "tag": tag,
        "repository": os.environ.get("SKIA_BUILDER_REPOSITORY", "google/skia"),
        "sha": sha,
        "milestone": milestone,
        "os": args.os,
        "arch": args.arch,
        "platform": platform,
        "config": config,
        "toolchain": toolchain,
        "args": gn_args,
        "defines": found,
        "libraries": [lib.name for lib in libs],
    }
    (stage / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")
    if args.no_archive:
        print(f"Staged {stage}")
        return

    RELEASE.mkdir(exist_ok=True)
    archive = RELEASE / f"{name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(stage, arcname=name)
    print(f"Wrote {archive} ({archive.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
