#!/usr/bin/env python3
"""Writes SHA256SUMS, manifest.json and the release notes for the archives in a directory.

  make-release.py <dir> --tag TAG --repository REPO --sha SHA --milestone N --ref REF

manifest.json lists each archive by RID (linux-x64, windows-arm64, ...) with its name, size and SHA-256.
"""

import argparse
import hashlib
import json
import pathlib
import re
import sys

RIDS = {"linux": "linux", "macos": "osx", "windows": "win"}


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
        match = re.fullmatch(rf"skia-{re.escape(args.tag)}-(linux|macos|windows)-(x64|arm64)\.tar\.gz", archive.name)
        if not match:
            sys.exit(f"Unexpected archive name {archive.name}")
        digest = sha256(archive)
        sums.append(f"{digest}  {archive.name}")
        assets[f"{RIDS[match.group(1)]}-{match.group(2)}"] = {
            "name": archive.name, "size": archive.stat().st_size, "sha256": digest}

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
