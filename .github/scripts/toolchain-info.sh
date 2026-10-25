#!/usr/bin/env bash
set -euo pipefail
board=${1:?Expected board name}
flags=(-mthumb -mcpu=cortex-m3)
if [[ "$board" == mk3-stm32 ]]; then flags=(-mthumb -mcpu=cortex-m4 -mfloat-abi=hard); fi
test "$(arm-none-eabi-gcc -dumpfullversion)" = 13.5.0
arm-none-eabi-gcc --version
arm-none-eabi-ld --version | sed -n '1p' | grep -E ' 2\.47(\.20260726)?$'
cat /opt/gcc-13.5/share/source-version.txt
newlib_defines=$(printf '#include <newlib.h>\n' | arm-none-eabi-gcc "${flags[@]}" -dM -E -)
grep -Fx '#define __NEWLIB__ 4' <<< "$newlib_defines"
grep -Fx '#define __NEWLIB_MINOR__ 6' <<< "$newlib_defines"
grep -Fx '#define __NEWLIB_PATCHLEVEL__ 0' <<< "$newlib_defines"
grep -E '^#define _NEWLIB_VERSION ' <<< "$newlib_defines"
arm-none-eabi-gcc "${flags[@]}" -print-multi-directory
arm-none-eabi-gcc "${flags[@]}" -print-file-name=libc.a
arm-none-eabi-gcc "${flags[@]}" -print-libgcc-file-name
