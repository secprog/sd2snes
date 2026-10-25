#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

case "${1:-}" in
  mk2)
    # The container exports ISE's environment without the removed EDK/PlanAhead.
    make -j2 fpga-mk2 HOST=LINUX XILINX_ENV=
    ;;
  mk3)
    make -j2 fpga-mk3 HOST=LINUX INTEL_BIN=/opt/quartus_lite/quartus/bin
    ;;
  firmware)
    make all FPGA_PREBUILT=1
    ;;
  menus)
    make -C snes menu.bin m3nu.bin map
    menu_text_status=0
    python3 .github/scripts/check-menu-languages.py || menu_text_status=$?
    make -C snes all
    python3 .github/scripts/check-onboarding-demos.py
    exit "$menu_text_status"
    ;;
  *)
    echo "Usage: $0 {mk2|mk3|firmware|menus}" >&2
    exit 2
    ;;
esac
