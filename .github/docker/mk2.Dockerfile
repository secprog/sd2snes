# The upstream image packages ISE 14.7 from AMD's preinstalled Linux VM.
# https://github.com/vmunoz82/ise14 documents its runtime configuration.
FROM fbelavenuto/xilinxise:14.7@sha256:aa1c78a9964bd85c90b1336606476bed50b2a466c403badfc7df1e5f1a2ae29b AS vendor
USER root
COPY trim-ise.sh /tmp/trim-ise.sh
RUN bash /tmp/trim-ise.sh

FROM ubuntu:20.04@sha256:8feb4d8ca5354def3d8fce243717141ce31e2c428701f6682bd2fafe15388214
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc make gawk util-linux openjdk-11-jre-headless \
    libncurses5 libtinfo5 lib32stdc++6 lib32z1 \
    libsm6 libxi6 libxrender1 libxrandr2 libxtst6 libxext6 \
    libfreetype6 libfontconfig1 libglib2.0-0 libusb-1.0-0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=vendor /opt/Xilinx /opt/Xilinx
# CoreGen's bundled JVM cannot run reliably on current Linux kernels.
RUN find /opt/Xilinx/14.7/ISE_DS -type f -name java -exec ln -sf /usr/bin/java {} \; \
    && for dir in /opt/Xilinx/14.7/ISE_DS/ISE/lib/lin64 /opt/Xilinx/14.7/ISE_DS/common/lib/lin64; do \
         rm -f "$dir"/libstdc++.so*; \
         ln -s /usr/lib/x86_64-linux-gnu/libstdc++.so.6 "$dir/libstdc++.so.6"; \
       done
ENV XILINX=/opt/Xilinx/14.7/ISE_DS/ISE \
    XILINXD_LICENSE_FILE=/opt/Xilinx/Xilinx.lic \
    LD_LIBRARY_PATH=/opt/Xilinx/14.7/ISE_DS/ISE/lib/lin64:/opt/Xilinx/14.7/ISE_DS/common/lib/lin64 \
    PATH=/opt/Xilinx/14.7/ISE_DS/ISE/bin/lin64:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
WORKDIR /work
