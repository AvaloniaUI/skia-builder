#!/usr/bin/env python3
"""Downloads the Emscripten toolchain that a .NET SDK band's wasm-tools workload links with.

  fetch-emscripten.py --sdk-band 10.0.100 [--manifest-version 10.0.115]

The .NET Emscripten workload manifest (Microsoft.NET.Workload.Emscripten.Current.Manifest-<band>) names the
Emscripten Sdk, Node and Cache packs of that band. This script downloads their linux-x64 packs from NuGet into
toolchains/emscripten-<band>/ and writes toolchain.json there: the Emscripten version, the manifest version and the
environment emcc needs. Static libraries built with this toolchain link into .NET browser-wasm apps of that band.
"""

import argparse
import io
import json
import os
import pathlib
import sys
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
NUGET = "https://api.nuget.org/v3-flatcontainer"
PACKS = ("Sdk", "Node", "Cache")


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "skia-builder"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return response.read()


def latest_version(package):
    versions = json.loads(get(f"{NUGET}/{package.lower()}/index.json"))["versions"]
    return versions[-1]


def nupkg(package, version):
    pid = package.lower()
    return zipfile.ZipFile(io.BytesIO(get(f"{NUGET}/{pid}/{version}/{pid}.{version}.nupkg")))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sdk-band", required=True, help=".NET SDK feature band, for example 10.0.100")
    parser.add_argument("--manifest-version", help="workload manifest version (default: the newest on NuGet)")
    args = parser.parse_args()

    manifest_id = f"Microsoft.NET.Workload.Emscripten.Current.Manifest-{args.sdk_band}"
    manifest_version = args.manifest_version or latest_version(manifest_id)
    with nupkg(manifest_id, manifest_version) as z:
        manifest = json.loads(z.read("data/WorkloadManifest.json"))

    dest = ROOT / "toolchains" / f"emscripten-{args.sdk_band}"
    stamp = dest / "toolchain.json"
    if stamp.exists() and json.loads(stamp.read_text()).get("manifestVersion") == manifest_version:
        print(stamp.read_text())
        return

    packs = {}
    for name in PACKS:
        key = next((k for k in manifest["packs"] if k.startswith(f"Microsoft.NET.Runtime.Emscripten.{name}.")), None)
        if key is None:
            sys.exit(f"{manifest_id} {manifest_version} has no Emscripten {name} pack")
        entry = manifest["packs"][key]
        package = entry.get("alias-to", {}).get("linux-x64")
        if package is None:
            sys.exit(f"{key} has no linux-x64 pack")
        packs[name] = (package, entry["version"])

    for name, (package, version) in packs.items():
        target = dest / name
        print(f"Downloading {package} {version}", file=sys.stderr)
        with nupkg(package, version) as z:
            z.extractall(target)
        for path in target.rglob("*"):
            if path.is_file() and (path.parent.name == "bin" or path.suffix in ("", ".py")):
                path.chmod(path.stat().st_mode | 0o755)

    emscripten = dest / "Sdk" / "tools" / "emscripten"
    version = (emscripten / "emscripten-version.txt").read_text().strip().strip('"')
    cache = dest / "Cache" / "tools" / "emscripten" / "cache"
    # Skia compiles with --sysroot=$skia_emsdk_dir/upstream/emscripten/cache/sysroot (an emsdk layout); the packs keep
    # the cache in the Cache pack, which EM_CACHE also names.
    cache_link = emscripten / "cache"
    if cache_link.is_symlink() or cache_link.exists():
        cache_link.unlink()
    cache_link.symlink_to(os.path.relpath(cache, emscripten))
    # Skia's wasm toolchain runs $skia_emsdk_dir/upstream/emscripten/emcc.
    link = dest / "emsdk" / "upstream" / "emscripten"
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(os.path.relpath(emscripten, link.parent))

    info = {
        "sdkBand": args.sdk_band,
        "manifest": manifest_id,
        "manifestVersion": manifest_version,
        "emscripten": version,
        "packs": {name: f"{package} {version_}" for name, (package, version_) in packs.items()},
        "emsdkDir": str(dest / "emsdk"),
        "environment": {
            "DOTNET_EMSCRIPTEN_LLVM_ROOT": str(dest / "Sdk" / "tools" / "bin"),
            "DOTNET_EMSCRIPTEN_BINARYEN_ROOT": str(dest / "Sdk" / "tools"),
            "DOTNET_EMSCRIPTEN_NODE_JS": str(dest / "Node" / "tools" / "bin" / "node"),
            "EM_CACHE": str(cache),
        },
    }
    stamp.write_text(json.dumps(info, indent=2) + "\n")
    print(stamp.read_text())


if __name__ == "__main__":
    main()
