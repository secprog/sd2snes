# Quartus 25.1 Lite and the matching Cyclone IV E device data.
# https://github.com/NikLeberg/container_builder/tree/main/quartus
FROM ghcr.io/nikleberg/quartus:25.1-cycloneiv@sha256:9e8453cc969caef8a484f2ddf352396bab90df3e88eaf49ad2c2414b58f5d7e5 AS devices
FROM ghcr.io/nikleberg/quartus:25.1@sha256:75f1830713e99d911c977252cf1925a120de0076cbd88a24c1c43a3c2990c9b5
USER root
COPY --from=devices /opt/quartus_lite/quartus/common/devinfo/cycloneive /opt/quartus_lite/quartus/common/devinfo/cycloneive
RUN apt-get update && apt-get install -y --no-install-recommends build-essential gawk \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT []
WORKDIR /work
