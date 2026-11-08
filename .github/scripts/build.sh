#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/../.."

# Explicit release builds may opt out of timing thresholds. Tool failures
# still propagate from the original make recipes in either mode.
ignore_timing=${IGNORE_TIMING:-0}
case "$ignore_timing" in
  0|1) ;;
  *) echo "IGNORE_TIMING must be exactly 0 or 1" >&2; exit 2 ;;
esac

case "${1:-}" in
  mk2)
    # The container exports ISE's environment without the removed EDK/PlanAhead.
    target=fpga-mk2
    if [[ -n "${2:-}" ]]; then
      [[ "$2" =~ ^[a-z0-9_]+$ ]]
      target="verilog/sd2snes_$2/fpga_$2.bit"
    fi
    make -j2 "$target" HOST=LINUX XILINX_ENV= IGNORE_TIMING="$ignore_timing"
    ;;
  mk3)
    target=fpga-mk3
    if [[ -n "${2:-}" ]]; then
      [[ "$2" =~ ^[a-z0-9_]+$ ]]
      target="verilog/sd2snes_$2/fpga_$2.bi3"
    fi
    make -j2 "$target" HOST=LINUX INTEL_BIN=/opt/quartus_lite/quartus/bin IGNORE_TIMING="$ignore_timing"
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
    # MkII's new Atari core requires this separate ca65/ld65 SNES player.
    # Rebuild it from the checkout; never reuse an untracked misc/ binary.
    make -C snes/atari clean
    sha256sum --check /opt/cc65/share/provenance/tools.sha256
    {
      cat /opt/cc65/share/provenance/source-commit.txt
      /opt/cc65/bin/ca65 --version
      /opt/cc65/bin/ld65 --version
      cat /opt/cc65/share/provenance/tools.sha256
    } > snes/atari/toolchain.log 2>&1
    make -C snes/atari all CA65=/opt/cc65/bin/ca65 LD65=/opt/cc65/bin/ld65 \
      2>&1 | tee snes/atari/build.log
    test "$(stat -c %s misc/atari_snes.bin)" = 32768
    sha256sum snes/atari/Makefile snes/atari/atari_snes.s \
      snes/atari/font_txt.inc snes/atari/lorom.cfg \
      snes/atari/fix_snes_checksum.py misc/atari_snes.bin \
      > snes/atari/source-output.sha256
    # The original MkIII NES/SMS/GBC/a26 cores also need matching SNES players.
    # Their separate source Makefiles retain the normal device configuration.
    mkdir -p snes/players/toolchains/asar snes/players/toolchains/cc65
    cp /opt/asar/share/provenance/* snes/players/toolchains/asar/
    cp /opt/cc65/share/provenance/* snes/players/toolchains/cc65/
    sha256sum --check /opt/asar/share/provenance/tools.sha256
    {
      cat /opt/asar/share/provenance/source-commit.txt
      /opt/asar/bin/asar --version
      cat /opt/asar/share/provenance/tools.sha256
      sha256sum /usr/local/bin/snescom /usr/local/bin/sneslink
    } > snes/players/toolchain.log 2>&1
    git -c safe.directory="$PWD" ls-files -z -- snes/nes snes/sms snes/gbc snes/a26 \
      | LC_ALL=C sort -z | xargs -0 sha256sum > snes/players/source-before.sha256
    {
      make -C snes/nes clean
      make -C snes/nes all NES_PERF=0
      for player in sms gbc a26; do
        make -C "snes/$player" clean
        make -C "snes/$player" all ASAR=/opt/asar/bin/asar
      done
    } 2>&1 | tee snes/players/build.log
    for player in nes sms gbc a26; do
      test "$(stat -c %s "misc/${player}_snes.bin")" = 32768
    done
    sha256sum --check snes/players/source-before.sha256 \
      > snes/players/source-check.log
    cat snes/players/source-before.sha256 > snes/players/source-output.sha256
    sha256sum misc/nes_snes.bin misc/nes_snes.map misc/sms_snes.bin \
      misc/gbc_snes.bin misc/a26_snes.bin >> snes/players/source-output.sha256
    # cgb_boot.bin awaits separate collection and acceptance against the unchanged
    # firmware CRC/size contract; its absence still blocks MkIII packaging.
    exit "$menu_text_status"
    ;;
  *)
    echo "Usage: $0 {mk2|mk3} [core] | firmware [mk2|mk3|mk3-stm32] | menus" >&2
    exit 2
    ;;
esac
