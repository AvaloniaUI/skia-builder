#!/usr/bin/env bash
# Builds Skia for Linux in docker/linux/Dockerfile: scripts/build-linux.sh <x64|arm64> [build.py options]
# Run scripts/fetch-skia.py --ref <version> --os linux first. The image builds for the host architecture;
# another architecture runs under emulation.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCH="${1:?usage: build-linux.sh <x64|arm64> [build.py options]}"
shift
case "$ARCH" in
  x64) PLATFORM=linux/amd64 ;;
  arm64) PLATFORM=linux/arm64 ;;
  *) echo "Unknown architecture $ARCH" >&2; exit 2 ;;
esac
IMAGE="${SKIA_BUILDER_IMAGE:-skia-builder-linux:$ARCH}"
if [ -z "${SKIA_BUILDER_IMAGE:-}" ]; then
  docker build --platform "$PLATFORM" -t "$IMAGE" "$ROOT/docker/linux"
fi
docker run --rm --platform "$PLATFORM" -u "$(id -u):$(id -g)" -v "$ROOT:$ROOT" -w "$ROOT" \
  -e SKIA_BUILDER_REPOSITORY "$IMAGE" python3 scripts/build.py linux "$ARCH" "$@"
