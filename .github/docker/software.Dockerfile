FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS gcc-builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgmp-dev libmpfr-dev libmpc-dev libisl-dev zlib1g-dev libzstd-dev \
    bison flex texinfo curl ca-certificates xz-utils \
    && rm -rf /var/lib/apt/lists/*
COPY build-gcc13.sh /tmp/build-gcc13.sh
RUN bash /tmp/build-gcc13.sh

FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS cc65-builder
ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# The MkII Atari SNES player uses ca65/ld65, independently of the menu's
# snescom assembler. Pin the official V2.19 source commit, not a moving tag.
# Upstream V2.19 reports V2.18; preserve that authentic source version.
RUN git init /tmp/cc65 \
    && git -C /tmp/cc65 remote add origin https://github.com/cc65/cc65.git \
    && GIT_TERMINAL_PROMPT=0 git -C /tmp/cc65 fetch --depth=1 origin 555282497c3ecf8b313d87d5973093af19c35bd5 \
    && git -C /tmp/cc65 checkout --detach FETCH_HEAD \
    && test "$(git -C /tmp/cc65 rev-parse HEAD)" = 555282497c3ecf8b313d87d5973093af19c35bd5 \
    && mkdir -p /opt/cc65/share/provenance \
    && gcc --version > /opt/cc65/share/provenance/host-compiler-version.txt \
    && git -C /tmp/cc65 show -s --format=fuller HEAD > /opt/cc65/share/provenance/source-commit.txt \
    && (cd /tmp/cc65 && git ls-files -z | LC_ALL=C sort -z | xargs -0 sha256sum) > /opt/cc65/share/provenance/source.sha256 \
    && make -C /tmp/cc65/src -j2 ca65 ld65 PREFIX=/opt/cc65 'BUILD_ID=Git 555282497c3ecf8b313d87d5973093af19c35bd5' \
    && install -Dm755 /tmp/cc65/bin/ca65 /opt/cc65/bin/ca65 \
    && install -Dm755 /tmp/cc65/bin/ld65 /opt/cc65/bin/ld65 \
    && install -Dm644 /tmp/cc65/LICENSE /opt/cc65/share/licenses/cc65/LICENSE \
    && /opt/cc65/bin/ca65 --version 2> /opt/cc65/share/provenance/ca65-version.txt \
    && /opt/cc65/bin/ld65 --version 2> /opt/cc65/share/provenance/ld65-version.txt \
    && test "$(cat /opt/cc65/share/provenance/ca65-version.txt)" = 'ca65 V2.18 - Git 555282497c3ecf8b313d87d5973093af19c35bd5' \
    && test "$(cat /opt/cc65/share/provenance/ld65-version.txt)" = 'ld65 V2.18 - Git 555282497c3ecf8b313d87d5973093af19c35bd5' \
    && sha256sum /opt/cc65/bin/ca65 /opt/cc65/bin/ld65 > /opt/cc65/share/provenance/tools.sha256 \
    && git -C /tmp/cc65 diff --exit-code HEAD -- \
    && (cd /tmp/cc65 && sha256sum --check /opt/cc65/share/provenance/source.sha256)

FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS asar-builder
ENV DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
# Existing MkIII SMS, GBC and a26 players use the SNES assembler Asar.
# Keep it separate from the menu's snescom and MkII Atari's cc65 toolchains.
RUN git init /tmp/asar \
    && git -C /tmp/asar remote add origin https://github.com/RPGHacker/asar.git \
    && GIT_TERMINAL_PROMPT=0 git -C /tmp/asar fetch --depth=1 origin 6a6dbdaed8cb773e583052ce4f66375bd896c3a1 \
    && git -C /tmp/asar checkout --detach FETCH_HEAD \
    && test "$(git -C /tmp/asar rev-parse HEAD)" = 6a6dbdaed8cb773e583052ce4f66375bd896c3a1 \
    && mkdir -p /opt/asar/share/provenance \
    && g++ --version > /opt/asar/share/provenance/host-compiler-version.txt \
    && cmake --version > /opt/asar/share/provenance/cmake-version.txt \
    && git -C /tmp/asar show -s --format=fuller HEAD > /opt/asar/share/provenance/source-commit.txt \
    && (cd /tmp/asar && git ls-files -z | LC_ALL=C sort -z | xargs -0 sha256sum) > /opt/asar/share/provenance/source.sha256 \
    && cmake -S /tmp/asar/src -B /tmp/asar-build -DCMAKE_BUILD_TYPE=Release \
       -DCMAKE_INSTALL_PREFIX=/opt/asar -DASAR_GEN_EXE=ON -DASAR_GEN_DLL=OFF \
       -DASAR_GEN_LIB=OFF -DASAR_GEN_EXE_TEST=OFF -DASAR_GEN_DLL_TEST=OFF \
    && cmake --build /tmp/asar-build --target asar-standalone --parallel 2 \
    && cmake --install /tmp/asar-build \
    && install -Dm644 /tmp/asar/LICENSE /opt/asar/share/licenses/asar/LICENSE \
    && install -Dm644 /tmp/asar/license-lgpl.txt /opt/asar/share/licenses/asar/license-lgpl.txt \
    && install -Dm644 /tmp/asar/license-gpl.txt /opt/asar/share/licenses/asar/license-gpl.txt \
    && /opt/asar/bin/asar --version > /opt/asar/share/provenance/asar-version.txt \
    && printf '%s\n' 'Asar 1.91, originally developed by Alcaro, maintained by Asar devs.' \
       'Source code: https://github.com/RPGHacker/asar' '' > /tmp/asar-version.expected \
    && cmp /tmp/asar-version.expected /opt/asar/share/provenance/asar-version.txt \
    && sha256sum /opt/asar/bin/asar > /opt/asar/share/provenance/tools.sha256 \
    && git -C /tmp/asar diff --exit-code HEAD -- \
    && (cd /tmp/asar && sha256sum --check /opt/asar/share/provenance/source.sha256)

FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgmp10 libmpfr6 libmpc3 libisl23 zlib1g libzstd1 \
    libboost-dev gawk python3 zip curl ca-certificates xz-utils git \
    && rm -rf /var/lib/apt/lists/*
COPY snescom.tar.xz /tmp/snescom.tar.xz
RUN echo '7caade189572d4463c281b48d1bc68b5f9f7070c40b02e220565a6b48b18ae2a  /tmp/snescom.tar.xz' | sha256sum --check \
    && mkdir /tmp/snescom \
    && tar -xJf /tmp/snescom.tar.xz --strip-components=1 -C /tmp/snescom \
    && make -C /tmp/snescom -j2 \
    && make -C /tmp/snescom install \
    && install -Dm644 /tmp/snescom/COPYING /usr/local/share/licenses/snescom/COPYING \
    && rm -rf /tmp/snescom /tmp/snescom.tar.xz
COPY --from=gcc-builder /opt/gcc-13.5 /opt/gcc-13.5
COPY --from=cc65-builder /opt/cc65 /opt/cc65
COPY --from=asar-builder /opt/asar /opt/asar
ENV PATH=/opt/gcc-13.5/bin:/opt/cc65/bin:/opt/asar/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
RUN test "$(arm-none-eabi-gcc -dumpfullversion)" = 13.5.0
RUN sha256sum --check /opt/cc65/share/provenance/tools.sha256 \
    && test "$(ca65 --version 2>&1)" = 'ca65 V2.18 - Git 555282497c3ecf8b313d87d5973093af19c35bd5' \
    && test "$(ld65 --version 2>&1)" = 'ld65 V2.18 - Git 555282497c3ecf8b313d87d5973093af19c35bd5'
RUN sha256sum --check /opt/asar/share/provenance/tools.sha256 \
    && /opt/asar/bin/asar --version > /tmp/asar-version.actual \
    && cmp /opt/asar/share/provenance/asar-version.txt /tmp/asar-version.actual \
    && rm /tmp/asar-version.actual
WORKDIR /work
