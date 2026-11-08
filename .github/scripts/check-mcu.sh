#!/usr/bin/env bash
set -euo pipefail

# Shared with check-stm32.sh; this only runs on GitHub. Do not replace an actual
# compile/link with the presence of a flag somewhere in an unrelated log line.
check_mcu_commands() {
  python3 - "$@" <<'PY'
import json
from pathlib import Path
import re
import shlex
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check(board, lines):
    require(board in {'mk2', 'mk3', 'mk3-stm32'}, 'unknown board')
    obj = 'obj-' + board + '/'
    cpu = 'cortex-m4' if board == 'mk3-stm32' else 'cortex-m3'
    compiled = []
    overlays = []
    links = []
    for line in lines:
        if not re.match(r'^(?:[^\s]*/)?arm-none-eabi-gcc(?:\s|$)', line):
            continue
        argv = shlex.split(line)
        outputs = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg in ('-o', '--output')]
        if not outputs or not any(output.startswith(obj) for output in outputs):
            continue
        require(len(outputs) == 1, 'ambiguous compiler output')
        output = outputs[0]
        is_link = output == obj + 'sd2snes-intermediate.elf'
        c_inputs = [arg for arg in argv if arg.endswith('.c')]
        is_c = '-c' in argv and output.endswith('.o') and bool(c_inputs)
        if not (is_link or is_c):
            continue  # Assembler objects have their own source-derived flags.
        require([arg for arg in argv if arg.startswith('-mcpu=')] == ['-mcpu=' + cpu], 'wrong CPU')
        require('-mthumb' in argv, 'missing Thumb mode')
        if board == 'mk3-stm32':
            require([arg for arg in argv if arg.startswith('-mfloat-abi=')] == ['-mfloat-abi=hard'], 'wrong float ABI')
        else:
            require(not any(arg.startswith('-mfloat-abi=') and arg != '-mfloat-abi=soft' for arg in argv), 'wrong float ABI')
        require([arg for arg in argv if arg.startswith('--specs=')] == ['--specs=nano.specs'], 'missing/duplicate/unexpected specs')
        is_overlay = output.startswith((obj + 'ovl1/', obj + 'ovl2/'))
        lto = [arg for arg in argv if arg == '-fno-lto' or arg == '-flto' or arg.startswith('-flto=')]
        require(lto == ([] if is_overlay else ['-flto']), 'wrong LTO contract')
        require(not any(arg.startswith('-Wa,') for arg in argv), 'assembler listing would conflict with LTO output')
        if is_link:
            require('-c' not in argv and not c_inputs, 'resident link is not an object link')
            require(argv.count(obj + 'main.o') == 1, 'resident link omits/duplicates main object')
            for member in ('memcpy', 'memmove', 'memset'):
                require(argv.count(obj + 'libc_full/libc_a-' + member + '.o') == 1, 'resident link omits/duplicates full-newlib memory object')
            links.append(output)
        else:
            require(len(c_inputs) == 1, 'ambiguous C input')
            (overlays if is_overlay else compiled).append((c_inputs[0], output))
    require(len(links) == 1, 'need exactly one actual resident link')
    require(compiled.count(('main.c', obj + 'main.o')) == 1, 'need exactly one fresh main.c compilation')
    require(len({output for _, output in compiled + overlays}) == len(compiled + overlays), 'duplicate C object compilation')
    return {'board': board, 'residentCCompiles': len(compiled), 'overlayCCompiles': len(overlays),
            'residentLinks': len(links), 'nanoCompileAndLink': True, 'residentLto': True,
            'scope': 'actual command log only; object and library checks are separate'}


def self_test():
    accepted = []
    for board in ('mk2', 'mk3', 'mk3-stm32'):
        obj = 'obj-' + board + '/'
        cpu = '-mcpu=cortex-m4 -mfloat-abi=hard' if board == 'mk3-stm32' else '-mcpu=cortex-m3'
        flags = '-mthumb ' + cpu + ' --specs=nano.specs'
        fastmem = ' '.join(obj + 'libc_full/libc_a-' + name + '.o' for name in ('memcpy', 'memmove', 'memset'))
        rows = ['arm-none-eabi-gcc -c ' + flags + ' -flto main.c -o ' + obj + 'main.o',
                'arm-none-eabi-gcc -c ' + flags + ' theme.c -o ' + obj + 'ovl1/theme.o',
                'arm-none-eabi-gcc ' + flags + ' -flto ' + obj + 'main.o ' + fastmem + ' --output ' + obj + 'sd2snes-intermediate.elf']
        check(board, rows)
        accepted.append(board)
        mutations = {
            'no_fresh_compile': rows[1:],
            'no_resident_link': rows[:-1],
            'duplicate_link': rows + [rows[-1]],
            'duplicate_object': rows + [rows[0]],
            'no_compile_lto': [rows[0].replace(' -flto', '')] + rows[1:],
            'no_link_lto': rows[:-1] + [rows[-1].replace(' -flto', '')],
            'disable_link_lto': rows[:-1] + [rows[-1] + ' -fno-lto'],
            'compile_full_headers': [rows[0].replace(' --specs=nano.specs', '')] + rows[1:],
            'link_full_library': rows[:-1] + [rows[-1].replace(' --specs=nano.specs', '')],
            'duplicate_specs': [rows[0] + ' --specs=nano.specs'] + rows[1:],
            'wrong_cpu': [rows[0].replace('-mcpu=', '-mcpu=cortex-m0plus -mcpu=')] + rows[1:],
            'no_thumb': [rows[0].replace(' -mthumb', '')] + rows[1:],
            'overlay_lto': [rows[0], rows[1] + ' -flto', rows[2]],
            'overlay_full_headers': [rows[0], rows[1].replace(' --specs=nano.specs', ''), rows[2]],
            'listing_collision': [rows[0] + ' -Wa,-adhlns=main.o'] + rows[1:],
            'wrong_float_abi': [rows[0] + ' -mfloat-abi=soft' if board == 'mk3-stm32' else rows[0] + ' -mfloat-abi=hard'] + rows[1:],
            'misleading_banner': ['log: -flto --specs=nano.specs'] + rows[1:],
        }
        for member in ('memcpy', 'memmove', 'memset'):
            mutations['omit_full_' + member] = rows[:-1] + [rows[-1].replace(' ' + obj + 'libc_full/libc_a-' + member + '.o', '')]
        for label, mutation in mutations.items():
            try:
                check(board, mutation)
            except (ValueError, IndexError):
                accepted.append(board + ':' + label)
            else:
                raise ValueError('negative control accepted: ' + board + ':' + label)
    return {'positiveControls': 3, 'negativeControls': len(accepted) - 3, 'controls': accepted,
            'scope': 'synthetic command-contract controls; not compilation or firmware qualification'}


try:
    if sys.argv[1:] == ['--self-test']:
        result = self_test()
    else:
        require(len(sys.argv) == 3, 'expected board and authentic build log')
        result = check(sys.argv[1], Path(sys.argv[2]).read_text(encoding='utf-8').splitlines())
    print(json.dumps(result, sort_keys=True))
except (OSError, ValueError, IndexError) as error:
    print(json.dumps({'accepted': False, 'error': str(error)}), file=sys.stderr)
    raise SystemExit(1)
PY
}

verify_mcu_build() {
  local board=$1 build_log=$2 objdir="src/obj-$1"
  local multidir library member nano_library nano_specs
  local flags=(-mthumb -mcpu=cortex-m3)
  if [[ "$board" == mk3-stm32 ]]; then flags=(-mthumb -mcpu=cortex-m4 -mfloat-abi=hard); fi
  check_mcu_commands "$board" "$build_log" | tee "$board-command-contract.log"
  test -s "$objdir/main.o" && test -s "$objdir/sd2snes.elf"
  arm-none-eabi-readelf --wide --sections "$objdir/main.o" > "$board-main-sections.log"
  grep -F '.gnu.lto_' "$board-main-sections.log"
  arm-none-eabi-readelf --wide --sections "$objdir/sd2snes.elf" > "$board-elf-sections.log"
  grep -E '[[:space:]]\.fwhdr[[:space:]]' "$board-elf-sections.log"
  if grep -F '.gnu.lto_' "$board-elf-sections.log"; then
    echo 'Final firmware retains unlinked LTO sections.' >&2
    return 1
  fi
  # Debug links can consume libg_nano (the identical libc archive) first.
  grep -E 'lib(c|g)_nano\.a\([^)]+' "$objdir/sd2snes.map" > "$board-nano-members.log"
  if grep -E '(^|[/[:space:]])lib(c|g)\.a\(' "$objdir/sd2snes.map"; then
    echo 'Resident firmware pulled an unselected full-newlib archive member.' >&2
    return 1
  fi
  multidir=$(arm-none-eabi-gcc "${flags[@]}" -print-multi-directory)
  case "$board:$multidir" in mk2:thumb/v7-m/nofp|mk3:thumb/v7-m/nofp|mk3-stm32:thumb/v7e-m+fp/hard) ;; *) return 1 ;; esac
  library=$(realpath "$(arm-none-eabi-gcc "${flags[@]}" -print-file-name=libc.a)")
  [[ "$library" == "/opt/gcc-13.5/arm-none-eabi/lib/$multidir/libc.a" ]]
  nano_specs=$(realpath "$(arm-none-eabi-gcc "${flags[@]}" -print-file-name=nano.specs)")
  [[ "$nano_specs" == "/opt/gcc-13.5/arm-none-eabi/lib/$multidir/nano.specs" ]]
  for member in memcpy memmove memset; do
    test -s "$objdir/libc_full/libc_a-$member.o"
    arm-none-eabi-ar p "$library" "libc_a-$member.o" | cmp - "$objdir/libc_full/libc_a-$member.o"
  done
  for member in libc_nano libg_nano; do
    nano_library=$(realpath "$(arm-none-eabi-gcc "${flags[@]}" -print-file-name="$member.a")")
    [[ "$nano_library" == "/opt/gcc-13.5/arm-none-eabi/lib/$multidir/$member.a" ]]
    test -s "$nano_library"
  done
  # Both names are installed; whichever is actually consumed must have the
  # selected multilib path. The map's earlier member check excludes bare LOADs.
  # The hard-float multilib contains a literal '+'. Match that path literally
  # within rows already checked above for actual, nonempty archive members.
  grep -F -e "/$multidir/libc_nano.a(" -e "/$multidir/libg_nano.a(" \
    "$board-nano-members.log" > "$board-selected-nano-members.log"
  if grep -vF "/$multidir/" "$board-nano-members.log"; then
    echo 'Resident firmware pulled a nano archive outside the selected multilib.' >&2
    return 1
  fi
  sha256sum --check /opt/gcc-13.5/share/newlib-nano.sha256 > "$board-nano-integrity.log"
  sha256sum --check /opt/gcc-13.5/share/newlib-full-before-nano.sha256 > "$board-full-newlib-integrity.log"
  arm-none-eabi-size -A "$objdir/sd2snes.elf"
}

# Allow the STM32 wrapper to reuse this exact validation without re-entering it.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then return 0; fi
cd "$(dirname "$0")/../.."
if [[ "${1:-}" == --self-test ]]; then check_mcu_commands --self-test; exit 0; fi
board=${1:?Expected mk2, mk3 or mk3-stm32}
case "$board" in
  mk3-stm32) exec bash .github/scripts/check-stm32.sh ;;
  mk2|mk3) ;;
  *) exit 2 ;;
esac
bash .github/scripts/toolchain-info.sh "$board"
make host-tools
set +e
make -C src "CONFIG=config-$board" V=1 2>&1 | tee "$board-build.log"
build_statuses=("${PIPESTATUS[@]}")
set -e
printf '%s make exit=%s log capture exit=%s\n' "$board" "${build_statuses[0]}" "${build_statuses[1]}"
if ((build_statuses[0] != 0)); then exit "${build_statuses[0]}"; fi
if ((build_statuses[1] != 0)); then exit "${build_statuses[1]}"; fi
verify_mcu_build "$board" "$board-build.log"
