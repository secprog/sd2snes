#!/usr/bin/env bash
set -euo pipefail

ise_root=/opt/Xilinx/14.7/ISE_DS
test -x "$ise_root/ISE/bin/lin64/coregen"
test -f /opt/Xilinx/Xilinx.lic

# Keep CoreGen, its IP libraries, Tcl scripts, and both binary architectures:
# clean checkouts regenerate .ngc files from the repository's .xco files.
rm -rf "$ise_root/EDK" "$ise_root/PlanAhead" \
  "$ise_root/ISE/sysgen" "$ise_root/ISE/secureip" \
  "$ise_root/ISE/smartmodel" "$ise_root/ISE/doc" "$ise_root/ISE/ISEexamples"

# Spartan-3 also uses data from the older Virtex families; leave those intact.
for family in virtex4 virtex5 virtex6 virtex6l virtex7 virtex7l \
  kintex7 kintex7l artix7 artix7l zynq spartan6 spartan6l spartan3a \
  spartan3adsp spartan3e qvirtex4 qvirtex5 qvirtex6 qvirtex6l qrvirtex4 \
  qrvirtex5 qspartan6 qspartan6l aspartan3a aspartan3adsp aspartan3e \
  aspartan6 akintex7 aartix7 azynq qartix7 qkintex7 qkintex7l qzynq; do
  rm -rf "$ise_root/ISE/$family"
done

du -sh /opt/Xilinx
