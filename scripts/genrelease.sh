#!/bin/bash
set -x
set -e
git submodule status skia
SKIA_COMMIT=`git submodule status skia|awk '{print $1}'|sed 's/-//'`
echo "Build for commit https://github.com/google/skia/commit/$SKIA_COMMIT" > release.txt  
# include GitHub Actions run number (fallback to 'local' when not set)
RUN_NUMBER="${GITHUB_RUN_NUMBER:-local}"
RELEASE_IDENTIFIER="sk_${SKIA_COMMIT}_${RUN_NUMBER}"
echo "RELEASE_ID=${RELEASE_IDENTIFIER}" >> $GITHUB_ENV

mkdir release skia_sdk
mv artifacts/*/* skia_sdk

echo -n ${RELEASE_IDENTIFIER} > skia_sdk/RELEASE_ID.txt
tar -czf release/skia_sdk.tar.gz skia_sdk
echo -n `cat /tmp/wat.c|md5sum|awk '{print $1}' ` > release/skia_sdk.tar.gz.md5sum