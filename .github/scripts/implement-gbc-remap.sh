#!/usr/bin/env bash
# GitHub-hosted native qualification only. Never skip fit or timing failures.
set -euo pipefail
case "$PROFILE" in gate-lut4-satlut-delay|gate-lut4-satlut-delay4|gate-lut4-delay-satlut|gate-lut4-critical-satlut|compare-lut4-sat|gate-lut4-sat|gate-lut4-sat-area|gate-lut4-sat2|gate-lut4-sat4|gate-lut4-sat8|gate-lut4-choices|gate-lut4-satlut|gate-lut4-satlut2|gate-lut4-satlut128|gate-lut4-satlut-reverse|fixed-mux-sat|compare-sat|lut4-sat|fixed-mux-resub|lut4-resub|fixed-mux-area|lut4-area|fixed-mux|lut4) ;; *) exit 2 ;; esac
root=$PWD
experiment="$root/.ci-tools/gbc-remap"
native=$(find "$experiment/native" -name main_native.edf -print -quit)
native_dir=$(dirname "$native")
ip=$(dirname "$(find "$experiment/native" -name vram.ngc -print -quit)")
project="$root/verilog/sd2snes_gbc/sd2snes_gbc.xise"
xtclsh "$root/.github/scripts/gbc-remap-options.tcl" "$root" "$experiment/reports"
read -r -a map_args < "$experiment/reports/map.options"
read -r -a par_args < "$experiment/reports/par.options"
candidate_args=("${map_args[@]}")
candidate_par_args=("${par_args[@]}")
# UG628 documents cost tables 1..100 for Spartan-3 MAP and PAR. Explore only
# physical placement; the native round trip retains the project options.
seed=${PLACEMENT_SEED:-3}
[[ "$seed" =~ ^([1-9]|[1-9][0-9]|100)$ ]]
changed=0
for i in "${!candidate_args[@]}"; do
  if [[ "${candidate_args[$i]}" == -t ]]; then
    candidate_args[$((i+1))]=$seed
    changed=$((changed+1))
  fi
done
[[ "$changed" == 1 ]]
changed=0
for i in "${!candidate_par_args[@]}"; do
  if [[ "${candidate_par_args[$i]}" == -t ]]; then
    candidate_par_args[$((i+1))]=$seed
    changed=$((changed+1))
  fi
done
[[ "$changed" == 1 ]]
case "${PAR_CONTINUE:-false}" in
  false) ;;
  true)
    # UG628: -xe c continues recovery when normal extra effort would stop.
    # This is still bounded by the hosted job timeout and every STA gate.
    changed=0
    for i in "${!candidate_par_args[@]}"; do
      if [[ "${candidate_par_args[$i]}" == -xe ]]; then
        [[ "${candidate_par_args[$((i+1))]}" == n ]]
        candidate_par_args[$((i+1))]=c
        changed=$((changed+1))
      fi
    done
    [[ "$changed" == 1 ]]
    ;;
  *) exit 2 ;;
esac
case "${MAP_CONTINUE:-false}" in
  false) ;;
  true)
    # With -timing, Spartan-3 placement happens in MAP, not PAR (UG628).
    changed=0
    for i in "${!candidate_args[@]}"; do
      if [[ "${candidate_args[$i]}" == -xe ]]; then
        [[ "${candidate_args[$((i+1))]}" == n ]]
        candidate_args[$((i+1))]=c
        changed=$((changed+1))
      fi
    done
    [[ "$changed" == 1 ]]
    ;;
  *) exit 2 ;;
esac
case "${MAP_DUPLICATION:-project}" in
  project) ;;
  off)
    changed=0
    for i in "${!candidate_args[@]}"; do
      if [[ "${candidate_args[$i]}" == -register_duplication ]]; then
        [[ "${candidate_args[$((i+1))]}" == on ]]
        candidate_args[$((i+1))]=off
        changed=$((changed+1))
      fi
    done
    [[ "$changed" == 1 ]]
    ;;
  *) exit 2 ;;
esac
# Keep diagnostics that show what packing/physical synthesis actually changed.
# The unchanged reconstruction must still use the exact native project options.
candidate_args+=(-detail)
printf '%s\n' "${candidate_args[*]}" > "$experiment/reports/candidate-map.options"
printf '%s\n' "${candidate_par_args[*]}" > "$experiment/reports/candidate-par.options"
printf 'MAP options: %s\n' "${map_args[*]}"
printf 'PAR options: %s\n' "${par_args[*]}"
printf 'Candidate MAP options: %s\n' "${candidate_args[*]}"
printf 'Candidate PAR options: %s\n' "${candidate_par_args[*]}"

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
  if [[ "$variant" == baseline ]]; then
    map -p xc3s400-4pq208 "${map_args[@]}" -o main_map.ncd main.ngd main.pcf || map_status=$?
  else
    map -p xc3s400-4pq208 "${candidate_args[@]}" -o main_map.ncd main.ngd main.pcf || map_status=$?
  fi
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
par -w "${candidate_par_args[@]}" main_map.ncd main.ncd main.pcf || par_status=$?
trce_status=0
trce -v 1 -n 400 -u 10 -fastpaths main.ncd main.pcf -o main.twr || trce_status=$?
[[ "$par_status" == 0 && "$trce_status" == 0 ]]
grep -Eq 'Timing Score: 0 \(Setup: 0, Hold: 0' main.par
grep -Eq 'Timing errors: 0[[:space:]]+Score: 0' main.twr
xtclsh "$root/verilog/xilinx_scripts/xgenbitgenfile.tcl" "$project" "$experiment/candidate/main.ut"
bitgen -f main.ut main.ncd
make -C "$root" host-tools
"$root/utils/rle" main.bit fpga_gbc.bit
sha256sum fpga_gbc.bit > "$experiment/reports/qualified-image.sha256"
