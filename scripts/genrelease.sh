#!/bin/bash
set -x
set -e
git submodule status skia
SKIA_COMMIT=`git submodule status skia|awk '{print $1}'|sed 's/-//'`
echo "Build for commit https://github.com/google/skia/commit/$SKIA_COMMIT" > release.txt  
# include GitHub Actions run number (fallback to 'local' when not set)
RUN_NUMBER="${GITHUB_RUN_NUMBER:-local}"
echo "RELEASE_ID=sk_${SKIA_COMMIT}_${RUN_NUMBER}" >> $GITHUB_ENV

mkdir release skia_sdk
mv artifacts/*/* skia_sdk

tar -czf release/skia_sdk.tar.gz skia_sdk
