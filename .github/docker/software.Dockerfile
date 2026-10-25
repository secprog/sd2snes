FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc-arm-none-eabi=15:13.2.rel1-2 \
    binutils-arm-none-eabi=2.42-1ubuntu1+23 \
    libnewlib-arm-none-eabi=4.4.0.20231231-2 \
    libboost-dev gawk python3 zip curl ca-certificates xz-utils \
    && rm -rf /var/lib/apt/lists/*
RUN curl -4 --http1.1 --fail --location --connect-timeout 20 --max-time 180 --retry 3 \
      https://bisqwit.iki.fi/src/arch/snescom-1.8.1.1.tar.xz -o /tmp/snescom.tar.xz \
    && echo '7caade189572d4463c281b48d1bc68b5f9f7070c40b02e220565a6b48b18ae2a  /tmp/snescom.tar.xz' | sha256sum --check \
    && mkdir /tmp/snescom \
    && tar -xJf /tmp/snescom.tar.xz --strip-components=1 -C /tmp/snescom \
    && make -C /tmp/snescom -j2 \
    && make -C /tmp/snescom install \
    && install -Dm644 /tmp/snescom/COPYING /usr/local/share/licenses/snescom/COPYING \
    && rm -rf /tmp/snescom /tmp/snescom.tar.xz
WORKDIR /work
