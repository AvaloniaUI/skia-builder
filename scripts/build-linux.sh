#/bin/bash
set -x
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd $SCRIPT_DIR
cd ..

IMAGE=clang-builder:latest
docker run --rm -it \
    -u $(id -u):$(id -g) \
    -v "$(pwd)":"$(pwd)" \
    -w "$(pwd)" \
    "$IMAGE" \
    ./scripts/build.py linux "$@"