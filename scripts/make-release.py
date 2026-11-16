#!/usr/bin/env python3
"""Writes SHA256SUMS, manifest.json and the release notes for the archives in a directory.

  make-release.py <dir> --tag TAG --repository REPO --sha SHA --milestone N --ref REF

manifest.json lists each archive by RID (linux-x64, windows-arm64, android-arm64, ...) with its name, size and
SHA-256. WebAssembly archives are keyed browser-wasm-emscripten-<version>: a static library links only with the
Emscripten version that built it.
"""

import argparse
import hashlib
import json
import pathlib
import re
import sys

RIDS = {"linux": "linux", "macos": "osx", "windows": "win", "android": "android"}


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dir", type=pathlib.Path)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--milestone", type=int, required=True)
    parser.add_argument("--ref", required=True)
    args = parser.parse_args()

    archives = sorted(args.dir.glob(f"skia-{args.tag}-*.tar.gz"))
    if not archives:
        sys.exit(f"No skia-{args.tag}-*.tar.gz in {args.dir}")
    assets = {}
    sums = []
    for archive in archives:
        prefix = f"skia-{re.escape(args.tag)}-"
        native = re.fullmatch(prefix + r"(linux|macos|windows|android)-(x64|arm64)\.tar\.gz", archive.name)
        wasm = re.fullmatch(prefix + r"wasm-emscripten-([0-9][0-9.]*[0-9])\.tar\.gz", archive.name)
        if not native and not wasm:
            sys.exit(f"Unexpected archive name {archive.name}")
        digest = sha256(archive)
        sums.append(f"{digest}  {archive.name}")
        entry = {"name": archive.name, "size": archive.stat().st_size, "sha256": digest}
        if native:
            assets[f"{RIDS[native.group(1)]}-{native.group(2)}"] = entry
        else:
            assets[f"browser-wasm-emscripten-{wasm.group(1)}"] = dict(entry, emscripten=wasm.group(1))

    manifest = {"tag": args.tag, "repository": args.repository, "sha": args.sha, "milestone": args.milestone,
                "ref": args.ref, "assets": assets}
    (args.dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (args.dir / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    notes = [
        f"Skia milestone {args.milestone}, [{args.repository}@{args.sha[:10]}]"
        f"(https://github.com/{args.repository}/commit/{args.sha}), requested as `{args.ref}`.",
        "",
        "| RID | Archive | Size |",
        "|---|---|---|",
    ]
    notes += [f"| {rid} | `{a['name']}` | {a['size'] / 1e6:.1f} MB |" for rid, a in assets.items()]
    (args.dir / "release-notes.md").write_text("\n".join(notes) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
