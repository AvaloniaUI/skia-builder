#!/usr/bin/env python3
"""Builds the Skia checkout in ./skia (see fetch-skia.py) and packages it.

  build.py <os> <arch> [--tag TAG]

<os> is linux, macos or windows; <arch> is x64 or arm64. The archive is release/skia-<TAG>-<os>-<arch>.tar.gz.
It holds the headers (include, modules, src and the third-party headers they use), the static libraries in
out/Release-<os>-<arch>, that directory's args.gn and defines.txt, and build-info.json.
"""

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIA = ROOT / "skia"
ARTIFACTS = ROOT / "artifacts"
RELEASE = ROOT / "release"

ARCHES = {"linux": {"x64", "arm64"}, "macos": {"x64", "arm64"}, "windows": {"x64", "arm64"}}

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
    "skia_use_system_freetype2": False,
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
            if line and not line.split("=")[0].endswith("_IMPLEMENTATION") and not line.startswith("U_"):
                found.add(line)
    return sorted(found)


def copy_headers(src, dest):
    for path in src.rglob("*"):
        if path.suffix in (".h", ".hpp", ".inc") and path.is_file():
            target = dest / path.relative_to(SKIA)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("os", choices=sorted(ARCHES))
    parser.add_argument("arch", choices=["x64", "arm64"])
    parser.add_argument("--tag", help="release tag (m<milestone>-<sha10>); read from the checkout when omitted")
    parser.add_argument("--skip-build", action="store_true", help="package an existing build")
    args = parser.parse_args()
    if not (SKIA / "BUILD.gn").exists():
        sys.exit("No Skia checkout in ./skia: run scripts/fetch-skia.py first")

    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=SKIA, check=True, text=True, capture_output=True).stdout.strip()
    milestone = next(int(l.split()[2]) for l in (SKIA / "include/core/SkMilestone.h").read_text().splitlines()
                     if l.startswith("#define SK_MILESTONE"))
    tag = args.tag or f"m{milestone}-{sha[:10]}"
    config = f"Release-{args.os}-{args.arch}"
    out_dir = SKIA / "out" / config

    gn_args = dict(COMMON_ARGS)
    gn_args.update({"linux": linux_args, "macos": macos_args, "windows": windows_args}[args.os](args.arch))
    if not args.skip_build:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "args.gn").write_text("".join(f"{k} = {gn_value(v)}\n" for k, v in gn_args.items()))
        run([tool("gn"), "gen", str(out_dir)])
        run([tool("ninja"), "-C", str(out_dir), "skia", "modules"])

    name = f"skia-{tag}-{args.os}-{args.arch}"
    stage = ARTIFACTS / name
    if stage.exists():
        shutil.rmtree(stage)
    for part in ["include", "modules", "src"] + THIRD_PARTY_HEADERS:
        if (SKIA / part).exists():
            copy_headers(SKIA / part, stage)
    lib_dir = stage / "out" / config
    lib_dir.mkdir(parents=True)
    libs = sorted(p for p in out_dir.iterdir() if p.suffix in (".a", ".lib"))
    if not libs:
        sys.exit(f"No static libraries in {out_dir}")
    for lib in libs:
        shutil.copy2(lib, lib_dir / lib.name)
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
        "config": config,
        "args": gn_args,
        "defines": found,
        "libraries": [lib.name for lib in libs],
    }
    (stage / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")

    RELEASE.mkdir(exist_ok=True)
    archive = RELEASE / f"{name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(stage, arcname=name)
    print(f"Wrote {archive} ({archive.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
