#!/usr/bin/env python3
"""Combines the staged slices of an Apple mobile platform into XCFrameworks and packages them (macOS only).

  package-apple.py <ios|tvos|maccatalyst> [--tag TAG]
  package-apple.py <ios|tvos|maccatalyst> --list-slices

Build the slices first with build.py --no-archive:
  ios          ios arm64, ios-simulator arm64, ios-simulator x64
  tvos         tvos arm64, tvos-simulator arm64, tvos-simulator x64
  maccatalyst  maccatalyst arm64, maccatalyst x64

Each static library becomes <name>.xcframework with a device slice and a simulator slice (or one Mac Catalyst slice):
the arm64e architecture that Skia adds to arm64 builds is removed, and the arm64 and x64 libraries of a slice are
combined with lipo. The archive is release/skia-<TAG>-<platform>.tar.gz: the headers, the XCFrameworks in
out/Release-<platform>, each slice's args.gn and defines.txt in out/Release-<platform>/<slice>-<arch>, and
build-info.json.
"""

import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import tarfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIA = ROOT / "skia"
ARTIFACTS = ROOT / "artifacts"
RELEASE = ROOT / "release"

SLICES = {
    "ios": [("ios", ["arm64"]), ("ios-simulator", ["arm64", "x64"])],
    "tvos": [("tvos", ["arm64"]), ("tvos-simulator", ["arm64", "x64"])],
    "maccatalyst": [("maccatalyst", ["arm64", "x64"])],
}


def run(args, capture=False):
    print("+ " + " ".join(str(a) for a in args), flush=True)
    result = subprocess.run([str(a) for a in args], check=True, text=True, stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else None


def thin(library, dest):
    """Copies a static library without its arm64e architecture."""
    archs = run(["lipo", "-archs", library], capture=True).split()
    if "arm64e" in archs and len(archs) > 1:
        run(["lipo", library, "-remove", "arm64e", "-output", dest])
    else:
        shutil.copy2(library, dest)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("platform", choices=sorted(SLICES))
    parser.add_argument("--tag", help="release tag (m<milestone>-<sha10>); read from the checkout when omitted")
    parser.add_argument("--list-slices", action="store_true", help="print the slices to build (<os> <arch> per line)")
    args = parser.parse_args()
    if args.list_slices:
        for slice_os, archs in SLICES[args.platform]:
            for arch in archs:
                print(slice_os, arch)
        return

    sha = run(["git", "-C", SKIA, "rev-parse", "HEAD"], capture=True).strip()
    milestone = next(int(l.split()[2]) for l in (SKIA / "include/core/SkMilestone.h").read_text().splitlines()
                     if l.startswith("#define SK_MILESTONE"))
    tag = args.tag or f"m{milestone}-{sha[:10]}"
    name = f"skia-{tag}-{args.platform}"
    config = f"Release-{args.platform}"
    stage = ARTIFACTS / name
    work = ARTIFACTS / f"{name}.slices"
    for d in (stage, work):
        if d.exists():
            shutil.rmtree(d)
    out = stage / "out" / config
    out.mkdir(parents=True)

    slices = {}
    libraries = None
    for slice_os, archs in SLICES[args.platform]:
        for arch in archs:
            slice_stage = ARTIFACTS / f"skia-{tag}-{slice_os}-{arch}"
            if not (slice_stage / "build-info.json").exists():
                sys.exit(f"Missing slice {slice_stage}: run build.py {slice_os} {arch} --no-archive --tag {tag}")
            info = json.loads((slice_stage / "build-info.json").read_text())
            slices[f"{slice_os}-{arch}"] = {"args": info["args"], "defines": info["defines"],
                                             "libraries": info["libraries"]}
            names = set(info["libraries"])
            if libraries is None:
                libraries = names
                for part in ("include", "modules", "src", "third_party", "licenses"):
                    if (slice_stage / part).exists():
                        shutil.copytree(slice_stage / part, stage / part)
            elif names != libraries:
                sys.exit(f"{slice_os}-{arch} has different libraries: {sorted(names ^ libraries)}")
            slice_out = slice_stage / "out" / f"Release-{slice_os}-{arch}"
            (out / f"{slice_os}-{arch}").mkdir()
            for meta in ("args.gn", "defines.txt"):
                shutil.copy2(slice_out / meta, out / f"{slice_os}-{arch}" / meta)

    frameworks = []
    for library in sorted(libraries):
        inputs = []
        for slice_os, archs in SLICES[args.platform]:
            slice_dir = work / slice_os
            slice_dir.mkdir(parents=True, exist_ok=True)
            thinned = []
            for arch in archs:
                source = ARTIFACTS / f"skia-{tag}-{slice_os}-{arch}" / "out" / f"Release-{slice_os}-{arch}" / library
                dest = slice_dir / f"{arch}-{library}"
                thin(source, dest)
                thinned.append(dest)
            combined = slice_dir / library
            if len(thinned) > 1:
                run(["lipo", "-create", *thinned, "-output", combined])
            else:
                shutil.move(thinned[0], combined)
            inputs += ["-library", combined]
        framework = out / (library.removeprefix("lib").removesuffix(".a") + ".xcframework")
        run(["xcodebuild", "-create-xcframework", *inputs, "-output", framework])
        frameworks.append(framework.name)
    shutil.rmtree(work)

    first = next(iter(slices.values()))
    (out / "defines.txt").write_text("".join(f"-D{d}\n" for d in first["defines"]))
    info = {
        "tag": tag,
        "sha": sha,
        "milestone": milestone,
        "platform": args.platform,
        "config": config,
        "xcframeworks": frameworks,
        "slices": slices,
    }
    (stage / "build-info.json").write_text(json.dumps(info, indent=2) + "\n")

    RELEASE.mkdir(exist_ok=True)
    archive = RELEASE / f"{name}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(stage, arcname=name)
    print(f"Wrote {archive} ({archive.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
