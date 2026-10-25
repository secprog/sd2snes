FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac AS gcc-builder
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgmp-dev libmpfr-dev libmpc-dev libisl-dev zlib1g-dev libzstd-dev \
    bison flex texinfo curl ca-certificates xz-utils \
    && rm -rf /var/lib/apt/lists/*
COPY build-gcc13.sh /tmp/build-gcc13.sh
RUN bash /tmp/build-gcc13.sh

FROM ubuntu:24.04@sha256:68ee22004a9109b44973313b02ff7b1de250f1de0f5ecb628d73f579aaff33ac
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgmp10 libmpfr6 libmpc3 libisl23 zlib1g libzstd1 \
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
COPY --from=gcc-builder /opt/gcc-13.5 /opt/gcc-13.5
ENV PATH=/opt/gcc-13.5/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
RUN test "$(arm-none-eabi-gcc -dumpfullversion)" = 13.5.0
WORKDIR /work
