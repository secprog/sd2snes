#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

board=${1:?Expected mk2, mk3 or mk3-stm32}
case "$board" in
  mk3-stm32)
    exec bash .github/scripts/check-stm32.sh
    ;;
  mk2|mk3) ;;
  *) exit 2 ;;
esac

arm-none-eabi-gcc --version
dpkg-query -W gcc-arm-none-eabi libnewlib-arm-none-eabi binutils-arm-none-eabi
make host-tools
make -C src "CONFIG=config-$board" V=1 2>&1 | tee "$board-build.log"
if [[ "$board" == mk3 ]] && grep -Eq -- '(^|[[:space:]])-flto([=[:space:]]|$)' "$board-build.log"; then
  echo 'MkIII LPC must be built without LTO.' >&2
  exit 1
fi
arm-none-eabi-size -A "src/obj-$board/sd2snes.elf"
