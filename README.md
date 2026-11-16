# Skia Builder

Builds static Skia libraries and publishes them as GitHub releases.

## Releases

Run the **Build Skia** workflow (Actions → Build Skia → Run workflow) with a Skia version:

- a milestone, such as `158`: the tip of the `chrome/m158` branch at the time of the run,
- a branch or tag,
- a full commit SHA.

The workflow resolves the version to a commit and builds Linux, Windows and macOS for x64 and arm64. When every
build succeeds, it publishes the release `m<milestone>-<sha10>` (for example `m158-707e33875f`). A run fails if that
release exists.

Each release has:

| Asset | Content |
|---|---|
| `skia-<tag>-<os>-<arch>.tar.gz` | Headers (`include`, `modules`, `src` and the third-party headers they use), the static libraries in `out/Release-<os>-<arch>`, its `args.gn` and `defines.txt`, and `build-info.json`. |
| `SHA256SUMS` | The SHA-256 of each archive. |
| `manifest.json` | The commit, milestone and each archive by RID (`linux-x64`, `osx-arm64`, `win-x64`, ...) with its size and SHA-256. |

## Builds

All builds are Release builds (`is_official_build`) with Skia's core, codecs, PDF, SVG, Skottie, skparagraph,
skshaper and skunicode (ICU and HarfBuzz, built from Skia's third-party sources), Ganesh and Graphite.

| OS | Compiler | GPU backends |
|---|---|---|
| Linux | Clang 20 with the gcc-11 libstdc++, on Ubuntu 20.04 (glibc 2.31) | GL, Vulkan; arm64 uses GLES and EGL |
| Windows | clang-cl, static CRT (`/MT`) | GL, Vulkan, Direct3D |
| macOS | Xcode Clang | GL, Metal |

Graphite uses Vulkan, Direct3D or Metal; Dawn is not built.

## Building locally

You need Python 3 and Git. Linux builds also need Docker.

```sh
python3 scripts/fetch-skia.py --ref 158 --resolve-only    # the commit and tag a version resolves to
python3 scripts/fetch-skia.py --ref 158 --os linux        # check out ./skia and sync what the build uses
scripts/build-linux.sh x64                                # Linux, in docker/linux/Dockerfile
python3 scripts/build.py macos arm64                      # macOS or Windows, on that OS
```

`fetch-skia.py` gets `gn` and `ninja` with Skia's `bin/fetch-gn` and `bin/fetch-ninja`. The archive is written to
`release/`, the build to `skia/out/Release-<os>-<arch>`.
