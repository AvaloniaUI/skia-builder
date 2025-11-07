#!/usr/bin/python3

import os
import json
import shutil
import subprocess
import sys


TARGET_OS_CANONICAL = {
    "linux": "linux",
    "mac": "macos",
    "macos": "macos",
    "darwin": "macos",
    "win": "windows",
    "windows": "windows",
}

def has_env_flag(name):
    return os.environ.get(name, "0") == "1"

def _format_scalar(value):
    # strings must be quoted and escaped, numbers/bools emitted as literals
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    # fallback to stringified-quoted
    return json.dumps(str(value))


def _format_list(lst):
    # produce multiline list with each element on its own indented line and a trailing comma
    if not lst:
        return "[]"
    parts = ["["]
    for item in lst:
        parts.append("    " + _format_scalar(item) + ",")
    parts.append("]")
    return "\n".join(parts)


def dict_to_gn(obj):
    lines = []
    for key, val in obj.items():
        if isinstance(val, (list, tuple)):
            formatted = _format_list(val)
            lines.append(f"{key} = {formatted}") 
        else:
            lines.append(f"{key} = {_format_scalar(val)}")
    # separate entries with a blank line to match example formatting
    return "\n\n".join(lines)

def write_file(path, content):
    with open(path, "w") as f:
        f.write(content)
        
def read_all_lines(path):
    with open(path, "r") as f:
        return f.readlines()

def copy_preserving_dir(root: str, file: str, src_dir: str, dest_dir: str):
    src_path = os.path.join(root, file)
    rel_path = os.path.relpath(src_path, src_dir)
    dest_path = os.path.join(dest_dir, rel_path)
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    shutil.copy2(src_path, dest_path)
    
def copy_extension(src_dir, dest_dir, extension):
    # Copy all files with the given extension from src_dir to dest_dir
    for root, dirs, files in os.walk(src_dir):
        for file in files:
            if file.endswith(extension):
                copy_preserving_dir(root, file, src_dir, dest_dir)

def copy_includes(src_dir, dest_dir):
    for root, dirs, files in os.walk(src_dir):
        for file in files:
            if file.endswith('.h'):
                copy_preserving_dir(root, file, src_dir, dest_dir)

def copy_headers():
    artifacts_dir = os.path.join("..", "artifacts", "headers")
    for skiaDir in ["include", "modules", "src"]:
        copy_includes(skiaDir, os.path.join(artifacts_dir, skiaDir))


def _ensure_arch_supported(target_os, arch):
    supported = {
        "linux": {"x64", "arm64", "arm"},
        "macos": {"x64", "arm64"},
        "windows": {"x64", "arm64"},
    }

    if arch not in supported.get(target_os, set()):
        raise ValueError(f"Unsupported architecture {arch} for {target_os}")


def collect_defines(path):
    lines = read_all_lines(path)
    defines = []
    for line in lines:
        line = line.strip()
        if line.startswith("defines = "):
            parts = line[len("defines = "):].strip().split()
            for part in parts:
                if part.startswith("-D"):
                    defines.append(part[2:])
            break
    return defines

def generate_skia_h(gn_dir):
    defines = collect_defines(os.path.join(gn_dir, "obj", "public_headers_warnings_check.ninja"))
    defines = [d for d in defines if d.startswith("SK_") or d.startswith("SKIA_")]
    
    define_directives = [f"#define {d.replace('=', ' ')}" for d in defines]
    skia_h = read_all_lines(os.path.join(gn_dir, "gen", "skia.h"))
    
    # insert lines from define_directives to skia_h before first line in skia_h that contains #include
    output_lines = []
    inserted = False
    for line in skia_h:
        if not inserted and line.strip().startswith("#include"):
            output_lines.extend(define_directives)
            output_lines.append("\n")
            inserted = True
        output_lines.append(line.strip())
    return "\n".join(output_lines)

def gen_linux(arch, self_contained, args):

    # normalize to LLVM-style arch names
    if arch == "x64":
        llvm_arch = "x86_64"
    elif arch == "arm64":
        llvm_arch = "aarch64"
    elif arch == "arm":
        llvm_arch = "armv7a"
    else:
        raise ValueError(f"Unsupported architecture: {arch}")

    llvm_target = llvm_arch + "-linux-gnu"
    
    args.update({
        "skia_use_vulkan": True,
        "skia_use_x11": False,
        "skia_use_system_freetype2": not self_contained,
        "cc": "clang",
        "cxx": "clang++",
        "target_os": "linux",
        "target_cpu": arch,
        "skia_use_icu": False,
        "skia_use_piex": True,
        "skia_use_sfntly": False,
        "skia_use_system_expat": False, # consider system (ABI seems to be stable)
        "skia_use_system_libjpeg_turbo": False,
        "skia_use_system_libpng": False,
        "skia_use_system_libwebp": False,
        "skia_use_system_zlib": False, # consider system  (ABI seems to be stable)
    })
    args["extra_cflags"].extend([
        "--target=" + llvm_target,
        "--sysroot=/sysroots/" + llvm_target
    ])
    args["extra_cflags_cc"].extend([
        "-stdlib=libc++"
    ])
    args["extra_ldflags"].extend([
        "--target=" + llvm_target, "--sysroot=/sysroots/" + llvm_target,
        "-rtlib=compiler-rt",
        "-stdlib=libc++",
        "-rtlib=compiler-rt",
        "-fuse-ld=lld",
        "-lc++",
        "-lc++abi",
        "-lunwind",
        "-lm",
        "-lc"
    ])
    

def gen_macos(arch, self_contained, args):
    _ensure_arch_supported("macos", arch)

    args.update({
        "skia_use_vulkan": False,
        "skia_use_metal": True,
        "target_os": "mac",
        "target_cpu": arch,
        "skia_use_icu": False,
        "skia_use_piex": True,
        "skia_use_system_expat": False,
        "skia_use_system_libjpeg_turbo": False,
        "skia_use_system_libpng": False,
        "skia_use_system_libwebp": False,
        "skia_use_system_zlib": False,
    })

    args["extra_cflags"].extend([
        "-DSKIA_C_DLL",
        "-DHAVE_ARC4RANDOM_BUF",
        "-stdlib=libc++",
    ])
    args["extra_ldflags"].extend([
        "-stdlib=libc++",
    ])


def gen_windows(arch, self_contained, args):
    _ensure_arch_supported("windows", arch)

    args.update({
        "skia_use_vulkan": True,
        "target_os": "win",
        "target_cpu": arch,
        "clang_win" : "C:/Program Files/LLVM",
        "skia_enable_fontmgr_win_gdi": False,
        "skia_use_dng_sdk": True,
        "skia_use_icu": False,
        "skia_use_piex": True,
        "skia_use_sfntly": False,
        "skia_use_system_expat": False,
        "skia_use_system_libjpeg_turbo": False,
        "skia_use_system_libpng": False,
        "skia_use_system_libwebp": False,
        "skia_use_system_zlib": False,
        "skia_use_direct3d": True,
    })

    mt_flag = "/MTd" if args.get("is_debug") else "/MT"
    args["extra_cflags"].extend([
        mt_flag,
        "/EHsc",
        "/Z7",
        "/guard:cf",
        "-D_HAS_AUTO_PTR_ETC=1",
    ])
    args["extra_ldflags"].extend([
        "/DEBUG:FULL",
        "/DEBUGTYPE:CV,FIXUP",
        "/guard:cf",
    ])

def build_target(target_os, arch, self_contained, debug):
    output_name = f"{target_os}_{arch}"
    if debug:
        output_name += "_debug"
    gn_dir = os.path.join("out", output_name)
    artifacts_dir = os.path.join("..", "artifacts", output_name)
    
    canonical_os = TARGET_OS_CANONICAL.get(target_os)
    if canonical_os is None:
        print(f"Unsupported target OS: {target_os}", file=sys.stderr)
        sys.exit(1)

    _ensure_arch_supported(canonical_os, arch)

    args = {
        "is_debug": debug,
        "is_official_build": not debug,
        "extra_asmflags": [],
        "skia_enable_tools": False,
        "extra_cflags": ["-ffunction-sections", "-fdata-sections", "-fno-rtti"],
        "extra_cflags_c": [],
        "extra_cflags_cc": [],
        "extra_ldflags": [],
        "skia_enable_skottie": True,
        "skia_use_harfbuzz": False,        
    }

    if canonical_os == "linux":
        gen_linux(arch, self_contained, args)
    elif canonical_os == "macos":
        gen_macos(arch, self_contained, args)
    elif canonical_os == "windows":
        gen_windows(arch, self_contained, args)
    else:
        print(f"Unsupported target OS: {canonical_os}", file=sys.stderr)
        sys.exit(1)
        
    os.makedirs(gn_dir, exist_ok=True)
    
    write_file(os.path.join(gn_dir, "args.gn"), dict_to_gn(args))
    
    if not has_env_flag("DEBUG_SKIP_BUILD"):
        # On Windows, prefer the gn.bat inside depot_tools to ensure batch wrapper is used.
        if os.name == "nt" or sys.platform.startswith("win"):
            gn_cmd = "../depot_tools/gn.bat"
        else:
            gn_cmd = "gn"
        subprocess.run([gn_cmd, 'gen', gn_dir], check = True)
        subprocess.run(['ninja', '-C', gn_dir], check = True)


    # recursively clear artifacts dir
    if os.path.exists(artifacts_dir):
        shutil.rmtree(artifacts_dir)

    os.makedirs(artifacts_dir, exist_ok=True)
    
    # Copy .a files from gn_dir to artifacts_dir/lib
    lib_dir = os.path.join(artifacts_dir, "lib")
    os.makedirs(lib_dir, exist_ok=True)
    copy_extension(gn_dir, lib_dir, ".a")
    copy_extension(gn_dir, lib_dir, ".lib")
    
    write_file(os.path.join(artifacts_dir, "skia.h"), generate_skia_h(gn_dir))
    if has_env_flag("SKIA_BUILDER_SAVE_SPACE"):
        shutil.rmtree(gn_dir)
    
def main():
    argv = sys.argv[1:]

    os.chdir("skia")
    
    if argv[0] == "headers":
        copy_headers()
        sys.exit(0)
    
    if len(argv) < 2:
        print(f"Usage: ", file=sys.stderr)
        print(f"{sys.argv[0]} <os> <arch> [--self-contained]", file=sys.stderr)
        print(f"{sys.argv[0]} headers", file=sys.stderr)
        sys.exit(2)
        
    target_os = argv[0]
    arch = argv[1]
    args = argv[2:]
    self_contained = "--self-contained" in args
    debug = "--debug" in args

    # prepend ./depot_tools to PATH
    os.environ["PATH"] = DEPOT_TOOLS_PATH + os.pathsep + os.environ.get("PATH", "")



    if arch == "all":
        for a in ["x64", "arm64"]:
            build_target(target_os, a, self_contained, debug)
    else:        
        build_target(target_os, arch, self_contained, debug)

if __name__ == "__main__":
    main()
