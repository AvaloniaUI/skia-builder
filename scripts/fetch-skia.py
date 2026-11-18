#!/usr/bin/env python3
"""Resolves a Skia version and prepares a checkout of it in ./skia.

  fetch-skia.py --ref 158 --resolve-only     prints the resolved version as JSON (no checkout)
  fetch-skia.py --ref 158 --os linux         checks out ./skia and syncs what a build for that OS needs

--ref is a milestone (158 means the tip of chrome/m158), a branch, a tag, or a full commit SHA.
"""

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIA = ROOT / "skia"

# The DEPS entries a build uses. Dawn, ANGLE, SwiftShader, V8, emsdk and the test tools are left out.
COMMON_DEPS = [
    "buildtools", "brotli", "delaunator-cpp", "dng_sdk", "expat", "freetype", "highway", "libjpeg-turbo", "libpng",
    "libwebp", "perfetto", "piex", "vulkanmemoryallocator", "vulkan-headers", "vulkan-utility-libraries", "wuffs", "zlib",
]
OS_DEPS = {"linux": [], "macos": [], "windows": ["d3d12allocator", "spirv-cross"], "android": [], "wasm": [],
           "ios": [], "tvos": [], "maccatalyst": []}


def run(args, cwd=None, env=None, capture=False):
    result = subprocess.run(args, cwd=cwd, env=env, check=True, text=True,
                            stdout=subprocess.PIPE if capture else None)
    return result.stdout if capture else None


def resolve(repository, ref):
    if re.fullmatch(r"[0-9a-f]{40}", ref):
        return ref
    name = f"chrome/m{ref}" if re.fullmatch(r"\d+", ref) else ref
    url = f"https://github.com/{repository}.git"
    out = run(["git", "ls-remote", url, f"refs/heads/{name}", f"refs/tags/{name}", f"refs/tags/{name}^{{}}"], capture=True)
    refs = dict(reversed(line.split("\t")) for line in out.splitlines() if line)
    for key in (f"refs/heads/{name}", f"refs/tags/{name}^{{}}", f"refs/tags/{name}"):
        if key in refs:
            return refs[key]
    sys.exit(f"{ref} is not a milestone, branch, tag or full commit SHA of {repository}")


def milestone_from(text):
    match = re.search(r"#define\s+SK_MILESTONE\s+(\d+)", text)
    if not match:
        sys.exit("SK_MILESTONE not found in include/core/SkMilestone.h")
    return int(match.group(1))


def remote_milestone(repository, sha):
    url = f"https://raw.githubusercontent.com/{repository}/{sha}/include/core/SkMilestone.h"
    with urllib.request.urlopen(url, timeout=60) as response:
        return milestone_from(response.read().decode())


def checkout(repository, sha):
    if (SKIA / ".git").exists():
        head = run(["git", "rev-parse", "HEAD"], cwd=SKIA, capture=True).strip()
        if head == sha:
            return
        shutil.rmtree(SKIA)
    SKIA.mkdir(parents=True)
    run(["git", "init", "-q"], cwd=SKIA)
    run(["git", "remote", "add", "origin", f"https://github.com/{repository}.git"], cwd=SKIA)
    run(["git", "fetch", "-q", "--depth", "1", "origin", sha], cwd=SKIA)
    run(["git", "checkout", "-q", "--detach", "FETCH_HEAD"], cwd=SKIA)


def sync(target_os):
    keep = set(COMMON_DEPS + OS_DEPS[target_os])
    lines = []
    for line in (SKIA / "DEPS").read_text().splitlines():
        match = re.match(r'\s*"([^"]+)"\s*:', line)
        if match:
            path = match.group(1)
            if path == "buildtools" or path.startswith("third_party/externals/"):
                if path.replace("third_party/externals/", "") not in keep:
                    continue
        lines.append(line)
    deps = SKIA / "DEPS.builder"
    deps.write_text("\n".join(lines) + "\n")
    env = dict(os.environ, GIT_SYNC_DEPS_PATH=str(deps), GIT_SYNC_DEPS_SKIP_EMSDK="1")
    run([sys.executable, "tools/git-sync-deps"], cwd=SKIA, env=env)
    run([sys.executable, "bin/fetch-gn"], cwd=SKIA)
    run([sys.executable, "bin/fetch-ninja"], cwd=SKIA)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repository", default="google/skia", help="GitHub repository of Skia (default google/skia)")
    parser.add_argument("--ref", required=True, help="milestone, branch, tag or full commit SHA")
    parser.add_argument("--os", choices=sorted(OS_DEPS), help="sync the dependencies of a build for this OS")
    parser.add_argument("--resolve-only", action="store_true", help="print the resolved version without a checkout")
    parser.add_argument("--github-output", action="store_true", help="also write the result to $GITHUB_OUTPUT")
    args = parser.parse_args()

    sha = resolve(args.repository, args.ref)
    if args.resolve_only:
        milestone = remote_milestone(args.repository, sha)
    else:
        checkout(args.repository, sha)
        milestone = milestone_from((SKIA / "include" / "core" / "SkMilestone.h").read_text())
        if args.os:
            sync(args.os)

    info = {"repository": args.repository, "ref": args.ref, "sha": sha, "milestone": milestone,
            "tag": f"m{milestone}-{sha[:10]}"}
    print(json.dumps(info, indent=2))
    if args.github_output and "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as out:
            for key, value in info.items():
                out.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
