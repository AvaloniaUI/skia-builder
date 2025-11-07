#/bin/bash
set -x
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
cd ..

# Allow overriding the build container image:
#   SKIA_BUILD_IMAGE=myrepo/custom-image:tag ./scripts/build-linux.sh x64
IMAGE="${CLANG_BUILDER_IMAGE:-clang-cross-builder}"

docker run --rm -it \
    -u "$(id -u)":"$(id -g)" \
    -v "$(pwd)":"$(pwd)" \
    -w "$(pwd)" \
    "$IMAGE" \
    ./scripts/build.py linux "$@"