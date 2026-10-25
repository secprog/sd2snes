#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

{
  arm-none-eabi-gcc --version
  dpkg-query -W gcc-arm-none-eabi libnewlib-arm-none-eabi binutils-arm-none-eabi
  arm-none-eabi-gcc -mthumb -mcpu=cortex-m4 -mfloat-abi=hard -print-multi-directory
  arm-none-eabi-gcc -mthumb -mcpu=cortex-m4 -mfloat-abi=hard -print-file-name=libc.a
  sha256sum verilog/sd2snes_mini/fpga_mini.bi3
} | tee stm32-toolchain.log

make host-tools
set +e
make -C src CONFIG=config-mk3-stm32 V=1 2>&1 | tee stm32-build.log
build_status=${PIPESTATUS[0]}
set -e

if grep -Eq -- '(^|[[:space:]])-flto([=[:space:]]|$)' stm32-build.log; then
  echo 'STM32 must be built without LTO.' >&2
  exit 1
fi
if [[ -f src/obj-mk3-stm32/sd2snes-intermediate.elf ]]; then
  arm-none-eabi-size -A src/obj-mk3-stm32/sd2snes-intermediate.elf
  arm-none-eabi-nm --print-size --size-sort src/obj-mk3-stm32/sd2snes-intermediate.elf | tail -40
fi
if [[ -f src/obj-mk3-stm32/sd2snes.map ]]; then
  sed -n '1,90p' src/obj-mk3-stm32/sd2snes.map
  grep -E '^\.(text|rodata|data)[[:space:]]|__data_load_(start|end)' src/obj-mk3-stm32/sd2snes.map
fi
exit "$build_status"
