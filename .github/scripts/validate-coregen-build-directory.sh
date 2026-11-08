#!/usr/bin/env bash
# Run exclusively inside the pinned ISE container on a GitHub-hosted runner.
set -euo pipefail

case "$FAMILY" in
  base) primary=basex; variants=(base basex bootleg atari); ips=(dac_buf msu_databuf snescmd_buf) ;;
  dsp) primary=dspx; variants=(dsp dspx); ips=(dac_buf msu_databuf snescmd_buf upd77c25_datram upd77c25_datrom upd77c25_pgmrom) ;;
  *) exit 2 ;;
esac
source="verilog/sd2snes_$FAMILY/ip/mk2"
build="$source/build"
test -f "$source/coregen.cgc"
test ! -e "$build"
targets=()
for ip in "${ips[@]}"; do
  test -f "$source/$ip.xco"
  test ! -e "$source/$ip.ngc"
  targets+=("../sd2snes_$FAMILY/ip/mk2/build/$ip.ngc")
done

# Real generation from the exact patched recipe. Failure is never restored,
# reclassified or suppressed; the workflow retains changes before its strict gate.
# Exercise the new Atari consumer as the first creator of its sole shared IP,
# then require the original base family to reuse that product unchanged.
if [[ "$FAMILY" == base ]]; then
  make -C verilog/sd2snes_atari HOST=LINUX XILINX_ENV= \
    ../sd2snes_base/ip/mk2/build/snescmd_buf.ngc
  test -s "$build/snescmd_buf.ngc" && test -s "$build/snescmd_buf.v"
  sha256sum "$build/snescmd_buf.ngc" "$build/snescmd_buf.v" > /report/atari-first-snescmd.sha256
  stat --printf '%n %s %y\n' "$build/snescmd_buf.ngc" "$build/snescmd_buf.v" > /report/atari-first-snescmd.stat
fi
make -C "verilog/sd2snes_$primary" -j2 HOST=LINUX XILINX_ENV= "${targets[@]}"
if [[ "$FAMILY" == base ]]; then
  sha256sum "$build/snescmd_buf.ngc" "$build/snescmd_buf.v" > /report/atari-after-basex-snescmd.sha256
  stat --printf '%n %s %y\n' "$build/snescmd_buf.ngc" "$build/snescmd_buf.v" > /report/atari-after-basex-snescmd.stat
  cmp /report/atari-first-snescmd.sha256 /report/atari-after-basex-snescmd.sha256
  cmp /report/atari-first-snescmd.stat /report/atari-after-basex-snescmd.stat
fi
for ip in "${ips[@]}"; do
  test -s "$build/$ip.ngc"
  test -s "$build/$ip.v"
  test ! -e "$source/$ip.ngc"
done
find "$build" -type f -print0 | sort -z | xargs -0 sha256sum > /report/generated-products.sha256
find "$build" -type f -print0 | sort -z | xargs -0 stat --printf '%n %s %y\n' > /report/generated-products.stat

# Parent and sibling variants consume these same products without regeneration.
# main.prj only writes a source list; no FPGA synthesis/implementation is invoked.
for variant in "${variants[@]}"; do
  variant_ips=("${ips[@]}")
  # Atari borrows only this one original base IP; all base products stay frozen.
  if [[ "$variant" == atari ]]; then variant_ips=(snescmd_buf); fi
  make -C "verilog/sd2snes_$variant" -j2 HOST=LINUX XILINX_ENV= main.prj 2>&1 | tee "/report/$variant-reuse.log"
  cp -- "verilog/sd2snes_$variant/main.prj" "/report/$variant.prj"
  for ip in "${variant_ips[@]}"; do
    if test "$variant" = "$FAMILY"; then prefix=ip/mk2/build; else prefix="../sd2snes_$FAMILY/ip/mk2/build"; fi
    test "$(grep -Fxc "verilog work \"$prefix/$ip.v\"" "/report/$variant.prj")" = 1
  done
  test "$(grep -c '/ip/mk2/.*\.v\|"ip/mk2/.*\.v' "/report/$variant.prj")" = "${#variant_ips[@]}"
  if grep -Fq 'Generating implementation netlist' "/report/$variant-reuse.log"; then
    printf 'Unexpected IP regeneration while checking %s reuse.\n' "$variant" >&2
    exit 1
  fi
  find "$build" -type f -print0 | sort -z | xargs -0 sha256sum > "/report/$variant-products.sha256"
  find "$build" -type f -print0 | sort -z | xargs -0 stat --printf '%n %s %y\n' > "/report/$variant-products.stat"
  cmp /report/generated-products.sha256 "/report/$variant-products.sha256"
  cmp /report/generated-products.stat "/report/$variant-products.stat"
  test ! -e "verilog/sd2snes_$variant/main.ngc"
  test ! -e "verilog/sd2snes_$variant/main_map.ncd"
  test ! -e "verilog/sd2snes_$variant/main.ncd"
  test ! -e "verilog/sd2snes_$variant/main.par"
  test ! -e "verilog/sd2snes_$variant/main.twr"
  printf 'Verified %s source-list paths and unchanged shared products.\n' "$variant"
done
printf 'Verified all %s %s original IP outputs and shared consumers. No FPGA timing result.\n' "${#ips[@]}" "$FAMILY"
