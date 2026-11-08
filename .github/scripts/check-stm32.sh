#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
source .github/scripts/check-mcu.sh

{
  bash .github/scripts/toolchain-info.sh mk3-stm32
  sha256sum verilog/sd2snes_mini/fpga_mini.bi3
} | tee stm32-toolchain.log

make host-tools
set +e
make -C src CONFIG=config-mk3-stm32 V=1 2>&1 | tee stm32-build.log
build_statuses=("${PIPESTATUS[@]}")
build_status=${build_statuses[0]}
tee_status=${build_statuses[1]}
printf 'STM32 make exit=%s log capture exit=%s\n' "$build_status" "$tee_status"
set -e

report_stm32_build() {
  local flash_end flash_used
  if [[ -f src/obj-mk3-stm32/sd2snes-intermediate.elf ]]; then
    arm-none-eabi-size -A src/obj-mk3-stm32/sd2snes-intermediate.elf || return $?
    arm-none-eabi-nm --print-size --size-sort src/obj-mk3-stm32/sd2snes-intermediate.elf | tail -40 || return $?
    flash_end=$(arm-none-eabi-nm src/obj-mk3-stm32/sd2snes-intermediate.elf | awk '$3 == "__data_load_end" { print $1 }') || return $?
    [[ "$flash_end" =~ ^[0-9A-Fa-f]+$ ]] || return 1
    flash_used=$((16#$flash_end - 0x0800c200))
    echo "STM32 flash including initialized data: $flash_used / 212480 bytes ($((212480 - flash_used)) bytes free)"
  fi
  if [[ -f src/obj-mk3-stm32/sd2snes.map ]]; then
    sed -n '1,90p' src/obj-mk3-stm32/sd2snes.map || return $?
    grep -E '^\.(text|rodata|data)[[:space:]]|__data_load_(start|end)' src/obj-mk3-stm32/sd2snes.map || return $?
  fi
  return 0
}
# Retain failure diagnostics, but a diagnostic error must never hide make's exit.
set +e
report_stm32_build
diagnostic_status=$?
set -e
printf 'STM32 diagnostics exit=%s\n' "$diagnostic_status"
if ((build_status != 0)); then exit "$build_status"; fi
if ((tee_status != 0)); then exit "$tee_status"; fi
if ((diagnostic_status != 0)); then exit "$diagnostic_status"; fi
verify_mcu_build mk3-stm32 stm32-build.log
