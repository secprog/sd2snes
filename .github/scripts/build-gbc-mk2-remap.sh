#!/usr/bin/env bash
# Reproduce the user-selected implementation on the hosted FPGA runner.
set -euo pipefail
[[ "${GITHUB_ACTIONS:-}" == true ]]
root=$PWD
experiment="$root/.ci-tools/gbc-remap"
mkdir -p "$experiment/native" "$experiment/reports"
for name in main.ngc main_native.edf main_map.mrp vram.ngc oam.ngc snescmd_buf.ngc; do
  test -s "verilog/sd2snes_gbc/$name"
  cp "verilog/sd2snes_gbc/$name" "$experiment/native/$name"
done
git rev-parse HEAD > "$experiment/reports/source-commit.txt"
sha256sum "$experiment/native/"* > "$experiment/reports/native-files.sha256"
export PROFILE=gate-lut4-delay-satlut PLACEMENT_SEED=11 MAP_DUPLICATION=project
export PAR_CONTINUE=false MAP_CONTINUE=false IGNORE_TIMING=1
python3 .github/scripts/check-gbc-xst-remap.py \
  "$experiment/native/main_native.edf" "$experiment/reports" "$PROFILE"
docker run --rm --user 0:0 --mac-address 08:00:27:68:c9:35 \
  --volume "$root:/work" --workdir /work \
  --env PROFILE --env PLACEMENT_SEED --env MAP_DUPLICATION \
  --env PAR_CONTINUE --env MAP_CONTINUE --env IGNORE_TIMING \
  --entrypoint /bin/bash sd2snes-ci:mk2 \
  .github/scripts/implement-gbc-remap.sh 2>&1 | tee "$experiment/reports/implementation.log"
cp "$experiment/candidate/fpga_gbc.bit" verilog/sd2snes_gbc/fpga_gbc.bit
