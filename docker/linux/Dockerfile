# Linux build image: Clang 20 with the gcc-11 libstdc++ on Ubuntu 20.04 (glibc 2.31).
# Archives built here link with code compiled by gcc-11 or Clang against the same libstdc++.
FROM ubuntu:20.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends software-properties-common gnupg ca-certificates curl git python3 \
 && add-apt-repository -y ppa:ubuntu-toolchain-r/test \
 && curl -fsSL https://apt.llvm.org/llvm-snapshot.gpg.key | apt-key add - \
 && echo "deb http://apt.llvm.org/focal/ llvm-toolchain-focal-20 main" > /etc/apt/sources.list.d/llvm.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends gcc-11 g++-11 clang-20 lld-20 llvm-20 binutils patch \
    libfontconfig1-dev libgl1-mesa-dev libegl1-mesa-dev libgles2-mesa-dev libx11-dev \
 && rm -rf /var/lib/apt/lists/*
ENV SKIA_BUILDER_CC=clang-20 SKIA_BUILDER_CXX=clang++-20 HOME=/tmp
