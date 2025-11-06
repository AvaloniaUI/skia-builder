# Skia Builder


This repository contains tools and scripts to build a static version of Skia library in a form that can be referenced
from a regular CMake or Makefile project.

For Linux it uses our cross-compilation Docker image based on Clang 20 with various sysroots

## Building

### Initial preparations and Skia version

1) point `skia` submodule to the version of skia you need to build
2) add `depot_tools` to your shell's PATH
3) run `python3 tools/git-sync-deps

### Headers

Run `./scripts/build.py headers`

### Linux

Run `./scripts/build-linux.sh <arch>`, where `arch` is `x64`, `arm64` or `all`

### macOS & Windows

Run `./scripts/build.py <os> <arch> [--self-contained] [--debug]`, where:

- `<os>` is `macos`, `darwin`, `mac`, `windows`, or `win`
- `<arch>` is `x64`, `arm64`, or `all`
- `--debug` produces a debug build (defaults to release)

## Usage

The scripts will produce a Skia build with static libraries in `artifacts/<os>_<arch>` with `skia.h` specific for that
skia configuration. Skia headers extracted from Skia are in `artifacts/headers`. You need to include both of those in 
your include search path.

When linking your application, link with the static libraries from `artifacts/<os>_<arch>` (you might want to use `--Wl,--start-group` and `--Wl,--end-group` around those to resolve any circular dependencies).
