#!/usr/bin/env bash
# GitHub-hosted native qualification only. Never skip fit or timing failures.
set -euo pipefail
case "$PROFILE" in fixed-mux-resub|lut4-resub|fixed-mux-area|lut4-area|fixed-mux|lut4) ;; *) exit 2 ;; esac
root=$PWD
experiment="$root/.ci-tools/gbc-remap"
native=$(find "$experiment/native" -name main_native.edf -print -quit)
native_dir=$(dirname "$native")
ip=$(dirname "$(find "$experiment/native" -name vram.ngc -print -quit)")
project="$root/verilog/sd2snes_gbc/sd2snes_gbc.xise"
map_options=$(xtclsh "$root/verilog/xilinx_scripts/xgenmapcmd.tcl" "$project")
par_options=$(xtclsh "$root/verilog/xilinx_scripts/xgenparcmd.tcl" "$project")
read -r -a map_args <<< "$map_options"
read -r -a par_args <<< "$par_options"

mkdir -p "$experiment/baseline" "$experiment/candidate"
cp "$experiment/reports/native-reconstructed.edf" "$experiment/baseline/main.edf"
cp "$experiment/reports/$PROFILE.edf" "$experiment/candidate/main.edf"
for variant in baseline candidate; do
  cd "$experiment/$variant"
  cp "$root/verilog/sd2snes_sgb/main.ucf" main.ucf
  # Our EDIF contains top-level ports and I/O buffers, but no explicit PAD
  # instances. UG628 requires -a for this third-party EDIF representation.
  ngdbuild -a -dd _ngo -sd "$ip" -nt timestamp -uc main.ucf -p xc3s400-4pq208 main.edf main.ngd
  map_status=0
  map -p xc3s400-4pq208 "${map_args[@]}" -o main_map.ncd main.ngd main.pcf || map_status=$?
  if [[ "$variant" == baseline ]]; then
    # The unchanged exported EDIF must reproduce the source NGC's resource
    # report. The current reference is over capacity, so Map:237 is expected.
    # Use the tools actually installed in the ISE image (gawk, not Python).
    resource_counts() {
      gawk -F: '
        BEGIN {
          n=split("Number of Slice Flip Flops|Number of 4 input LUTs|Total Number of 4 input LUTs|Number of bonded IOBs|Number of RAMB16s|Number of MULT18X18s|Number of DCMs", labels, "\\|")
          for(i=1;i<=n;i++) required[labels[i]]=1
        }
        {
          label=$1; gsub(/^[[:space:]]+|[[:space:]]+$/, "", label)
          if(label in required) {
            value=$2; sub(/^[[:space:]]+/, "", value)
            if(value !~ /^[0-9][0-9,]*([[:space:]]|$)/) exit 2
            sub(/[[:space:]].*$/, "", value); gsub(/,/, "", value)
            seen[label]++; counts[label]=value
          }
        }
        END {
          for(i=1;i<=n;i++) {
            if(seen[labels[i]] != 1) exit 2
            print labels[i] ": " counts[labels[i]]
          }
        }' "$1"
    }
    resource_counts "$native_dir/main_map.mrp" > reference-counts.txt
    resource_counts main_map.mrp > reconstructed-counts.txt
    diff -u reference-counts.txt reconstructed-counts.txt
    echo 'Native EDIF round-trip resource identity:'
    cat reconstructed-counts.txt
    if [[ "$map_status" != 0 ]]; then
      grep -q 'ERROR:Map:237' main_map.mrp
    fi
  elif [[ "$map_status" != 0 ]]; then
    exit "$map_status"
  fi
done

cd "$experiment/candidate"
par_status=0
par -w "${par_args[@]}" main_map.ncd main.ncd main.pcf || par_status=$?
trce_status=0
trce -v 10 -n 10 -u 10 -fastpaths main.ncd main.pcf -o main.twr || trce_status=$?
[[ "$par_status" == 0 && "$trce_status" == 0 ]]
grep -Eq 'Timing Score: 0 \(Setup: 0, Hold: 0' main.par
grep -Eq 'Timing errors: 0[[:space:]]+Score: 0' main.twr
xtclsh "$root/verilog/xilinx_scripts/xgenbitgenfile.tcl" "$project" main.ut
bitgen -f main.ut main.ncd
make -C "$root" host-tools
"$root/utils/rle" main.bit fpga_gbc.bit
sha256sum fpga_gbc.bit > "$experiment/reports/qualified-image.sha256"
