# Skia Builder

Builds static Skia libraries and publishes them as GitHub releases.

## Releases

Run the **Build Skia** workflow (Actions → Build Skia → Run workflow) with a Skia version:

- a milestone, such as `158`: the tip of the `chrome/m158` branch at the time of the run,
- a branch or tag,
- a full commit SHA.

The workflow resolves the version to a commit and builds Linux, Windows, macOS and Android for x64 and arm64, iOS,
tvOS and Mac Catalyst as XCFrameworks, and WebAssembly once for each Emscripten version listed below. When every build succeeds, it publishes the release
`m<milestone>-<sha10>` (for example `m158-707e33875f`). A run fails if that release exists.

Each release has:

| Asset | Content |
|---|---|
| `skia-<tag>-<os>-<arch>.tar.gz` | Headers (`include`, `modules`, `src` and the third-party headers they use), the license files of Skia and each dependency in `licenses/<name>/`, the static libraries in `out/Release-<os>-<arch>`, its `args.gn` and `defines.txt`, and `build-info.json` (arguments, defines, toolchain). |
| `skia-<tag>-<ios\|tvos\|maccatalyst>.tar.gz` | The headers, an `.xcframework` per library in `out/Release-<platform>` (device and simulator slices; Mac Catalyst arm64 and x86_64), each slice's `args.gn` and `defines.txt`, and `build-info.json`. |
| `skia-<tag>-wasm-emscripten-<version>.tar.gz` | The same for WebAssembly, built with that Emscripten version; the libraries are in `out/Release-wasm-emscripten-<version>`. |
| `SHA256SUMS` | The SHA-256 of each archive. |
| `manifest.json` | The commit, milestone and each archive by RID (`linux-x64`, `osx-arm64`, `win-x64`, `android-arm64`, `ios`, `browser-wasm-emscripten-3.1.56`, ...) with its size and SHA-256. |

## Builds

All builds are Release builds (`is_official_build`) with Skia's core, codecs, PDF, SVG, Skottie, skshaper (the
primitive shaper, and CoreText on Apple platforms), Ganesh and Graphite. HarfBuzz and ICU are not built: there is no
skparagraph, skunicode or HarfBuzz shaper, and PDF documents embed whole fonts.

| OS | Compiler | GPU backends |
|---|---|---|
| Linux | Clang 20 with the gcc-11 libstdc++, on Ubuntu 20.04 (glibc 2.31) | GL, Vulkan; arm64 uses GLES and EGL |
| Windows | clang-cl, static CRT (`/MT`) | GL, Vulkan, Direct3D |
| macOS | Xcode Clang | GL, Metal |
| Android | NDK r27d Clang, API level 24, the NDK's libc++ | GLES, Vulkan |
| iOS, tvOS | Xcode Clang, iOS and tvOS 15.0; device arm64, simulator arm64 and x86_64 | Metal |
| Mac Catalyst | Xcode Clang, iOS 15.0 on Mac (`-macabi`), arm64 and x86_64 | Metal |
| WebAssembly | Emscripten of a .NET SDK's wasm-tools workload, wasm SIMD (`-msimd128`), no threads | WebGL 2 |

Graphite uses Vulkan, Direct3D or Metal; Dawn is not built, so WebAssembly has no Graphite. The iOS, tvOS and Mac
Catalyst libraries contain arm64 without arm64e (Skia compiles both; `package-apple.py` removes arm64e).

### WebAssembly and Emscripten versions

A WebAssembly static library links only with the Emscripten version that compiled it, so each archive is built once
per version. The workflow builds for each .NET SDK band in its `wasm` matrix, with the Emscripten packs that band's
wasm-tools workload installs (`Microsoft.NET.Workload.Emscripten.Current.Manifest-<band>` on NuGet):

| .NET SDK band | Emscripten |
|---|---|
| 10.0.100 | 3.1.56 |
| 11.0.100 | 6.0.3 |

To add a band, add it to the `wasm` matrix. The archives are compiled as single-threaded objects; hosts that enable
WebAssembly threads need a separate build.

The archives link into .NET WebAssembly apps with the runtime's defaults:

- `setjmp` and `longjmp` use WebAssembly exception handling (`-sSUPPORT_LONGJMP=wasm`), as .NET links with
  `-fwasm-exceptions`. .NET 11 and later bands link with the standard exception handling instructions
  (`-sWASM_LEGACY_EXCEPTIONS=0`), earlier bands with the legacy ones; a module cannot mix them, so the archives of each
  band use that band's instructions. `build.py` checks the libraries for the other kind and records
  `toolchain.standardExceptions` in `build-info.json`.

The 10.0.100 packs pair a clang that lowers `setjmp` to `__wasm_setjmp` and `__wasm_setjmp_test` (LLVM 19) with
Emscripten 3.1.56 system libraries that define only the older `saveSetjmp`. When the toolchain's compiler-rt lacks
`__wasm_setjmp`, `build.py` adds `libwasm_setjmp.a` (`scripts/wasm/wasm_setjmp.c`, the two functions as Emscripten
3.1.57 defines them) to the archive and sets `toolchain.setjmpShim` in `build-info.json`. Link it with the other
libraries; libpng, FreeType and the PNG and JPEG codecs use `setjmp`.

## Building locally

You need Python 3 and Git. Linux builds also need Docker, Android builds an Android NDK. WebAssembly builds run on
a Linux x64 host with the toolchain that `fetch-emscripten.py` downloads.

```sh
python3 scripts/fetch-skia.py --ref 158 --resolve-only    # the commit and tag a version resolves to
python3 scripts/fetch-skia.py --ref 158 --os linux        # check out ./skia and sync what the build uses
scripts/build-linux.sh x64                                # Linux, in docker/linux/Dockerfile
python3 scripts/build.py macos arm64                      # macOS or Windows, on that OS
python3 scripts/fetch-skia.py --ref 158 --os android
python3 scripts/build.py android arm64 --ndk <ndk>         # or ANDROID_NDK_HOME
python3 scripts/fetch-skia.py --ref 158 --os ios           # iOS, tvOS or Mac Catalyst, on a Mac
python3 scripts/package-apple.py ios --list-slices | while read -r slice arch; do
  python3 scripts/build.py "$slice" "$arch" --no-archive
done
python3 scripts/package-apple.py ios                      # the XCFrameworks and the archive
python3 scripts/fetch-skia.py --ref 158 --os wasm
python3 scripts/fetch-emscripten.py --sdk-band 10.0.100   # toolchains/emscripten-10.0.100
python3 scripts/build.py wasm wasm32 --emscripten toolchains/emscripten-10.0.100
```

`fetch-skia.py` gets `gn` and `ninja` with Skia's `bin/fetch-gn` and `bin/fetch-ninja`. The archive is written to
`release/`, the build to `skia/out/Release-<os>-<arch>`.
