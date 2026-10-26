#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

case "${1:-}" in
  mk2)
    # The container exports ISE's environment without the removed EDK/PlanAhead.
    target=fpga-mk2
    if [[ -n "${2:-}" ]]; then
      [[ "$2" =~ ^[a-z0-9_]+$ ]]
      target="verilog/sd2snes_$2/fpga_$2.bit"
    fi
    make -j2 "$target" HOST=LINUX XILINX_ENV= IGNORE_TIMING=0
    ;;
  mk3)
    target=fpga-mk3
    if [[ -n "${2:-}" ]]; then
      [[ "$2" =~ ^[a-z0-9_]+$ ]]
      target="verilog/sd2snes_$2/fpga_$2.bi3"
    fi
    make -j2 "$target" HOST=LINUX INTEL_BIN=/opt/quartus_lite/quartus/bin IGNORE_TIMING=0
    ;;
  firmware)
    case "${2:-all}" in
      all) make all FPGA_PREBUILT=1 ;;
      mk2|mk3|mk3-stm32)
        # Menus and the matching FPGA artifact are downloaded by the workflow.
        bash .github/scripts/check-mcu.sh "$2"
        make release "RELEASE_BOARD=$2" FPGA_PREBUILT=1
        python3 .github/scripts/check-fpga-manifest.py package "$2" release/v*/*.zip
        ;;
      *) exit 2 ;;
    esac
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
    echo "Usage: $0 {mk2|mk3} [core] | firmware [mk2|mk3|mk3-stm32] | menus" >&2
    exit 2
    ;;
esac
