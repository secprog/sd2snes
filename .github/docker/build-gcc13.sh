#!/usr/bin/env bash
set -euo pipefail

# Run only while preparing the toolchain image on a GitHub-hosted runner.
gcc_version=13.5.0
binutils_version=2.47
newlib_version=4.6.0.20260123
prefix=/opt/gcc-13.5
sysroot="$prefix/arm-none-eabi"
export PATH="$prefix/bin:$PATH"

# Keep long hosted preparation steps observable, and stop a stuck configure.
stage_pid=
monitor_pid=
stage_log=/tmp/toolchain-stage.log
on_exit() {
  local status=$?
  if [[ -n "$monitor_pid" ]]; then kill "$monitor_pid" 2>/dev/null || true; fi
  if ((status != 0)); then
    ps -eo pid,ppid,etime,time,pcpu,rss,args --sort=-pcpu | sed -n '1,20p'
    if [[ -f "$stage_log" ]]; then tail -120 "$stage_log"; fi
    while IFS= read -r log; do
      echo "=== $log ==="
      tail -100 "$log"
    done < <(find /tmp/gcc-build /tmp/newlib-build /tmp/newlib-nano-build -name config.log -printf '%T@ %p\n' 2>/dev/null \
      | sort -nr | sed -n '1,3p' | cut -d' ' -f2-)
  fi
  if [[ -n "$stage_pid" ]]; then kill "$stage_pid" 2>/dev/null || true; fi
  exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
run_stage() {
  local limit=$1
  shift
  printf '=== Running:'
  printf ' %q' "$@"
  printf ' ===\n'
  # Full make output would exceed BuildKit's 2 MiB step log limit, hiding
  # subsequent activity. Keep it in the container and stream bounded samples.
  timeout --kill-after=30s "$limit" "$@" > "$stage_log" 2>&1 &
  stage_pid=$!
  (
    while kill -0 "$stage_pid" 2>/dev/null; do
      sleep 60
      echo '=== Hosted toolchain preparation activity ==='
      ps -eo pid,ppid,etime,time,pcpu,rss,args --sort=-pcpu | sed -n '1,15p'
      tail -5 "$stage_log"
    done
  ) &
  monitor_pid=$!
  wait "$stage_pid"
  kill "$monitor_pid" 2>/dev/null || true
  wait "$monitor_pid" 2>/dev/null || true
  monitor_pid=
  stage_pid=
  tail -12 "$stage_log"
}

fetch_source() {
  local name=$1 url=$2 checksum=$3 algorithm=$4
  curl --fail --location --connect-timeout 20 --max-time 300 --retry 3 \
    "$url" --output "/tmp/$name.tar"
  echo "$checksum  /tmp/$name.tar" | "${algorithm}sum" --check
  mkdir -p "/tmp/$name-source" "/tmp/$name-build"
  tar -xf "/tmp/$name.tar" --strip-components=1 -C "/tmp/$name-source"
  mkdir -p "$prefix/share/licenses/$name"
  printf '%s\nSource: %s\n%s: %s\n' "$name" "$url" "$algorithm" "$checksum" \
    >> "$prefix/share/source-version.txt"
}

# Published GNU release checksum: https://gcc.gnu.org/ftp/binutils/releases/sha512.sum
fetch_source binutils \
  "https://gcc.gnu.org/ftp/binutils/releases/binutils-$binutils_version.tar.xz" \
  3126a1064374d8da40d4d70630c204ed1e75d542c447d53fca9778c7ceff095c28e9b445e15a313fef9729082d7966471ee6b5b715d479aa6d568528743e1d98 sha512
echo "=== Building binutils $binutils_version ==="
cd /tmp/binutils-build
CFLAGS='-O2 -g0' CXXFLAGS='-O2 -g0' /tmp/binutils-source/configure \
  --target=arm-none-eabi --prefix="$prefix" --with-sysroot="$sysroot" \
  --disable-nls --disable-werror --disable-shared --enable-plugins \
  --disable-gdb --disable-sim --disable-gprofng
run_stage 15m make -j2
run_stage 5m make install
install -m644 /tmp/binutils-source/COPYING* "$prefix/share/licenses/binutils/"
cd /
rm -rf /tmp/binutils-source /tmp/binutils-build /tmp/binutils.tar

# Checksum independently recorded by Buildroot's newlib 4.6 release update:
# https://lists.buildroot.org/pipermail/buildroot/2026-January/795658.html
fetch_source newlib \
  "https://sourceware.org/ftp/newlib/newlib-$newlib_version.tar.gz" \
  6ff27e3bf022666f43f7802255be680eeff722ac181b1725d21e2e8318604ee3 sha256
# GCC needs target headers at configure time to enable libc support in libgcc.
# Install newlib's generated headers before building any target runtime libraries.
mkdir -p "$sysroot/include"
cp -a /tmp/newlib-source/newlib/libc/include/. "$sysroot/include/"
test -r "$sysroot/include/stdio.h"

# Published GNU release checksum: https://gcc.gnu.org/pub/gcc/releases/gcc-13.5.0/sha512.sum
fetch_source gcc \
  "https://gcc.gnu.org/pub/gcc/releases/gcc-$gcc_version/gcc-$gcc_version.tar.xz" \
  709237ff8f10d46eb10cad53a71bdcacbd3d56f4559e9a5bb3323f743fdba78b7e505586135560b27e88320927a065ec4f5e45273d5504b542f67c7326eb683c sha512
# Retain the upstream ARM option canonicalization, but build only libraries
# used by this repository. Clear reuse rules referencing the omitted variants.
cat >> /tmp/gcc-source/gcc/config/arm/t-multilib <<'MULTILIB'

MULTILIB_REQUIRED = mthumb/march=armv6s-m/mfloat-abi=soft mthumb/march=armv7-m/mfloat-abi=soft mthumb/march=armv7e-m+fp/mfloat-abi=hard
MULTILIB_REUSE =
MULTILIB
printf 'Multilib scope: default, Cortex-M0+ soft, Cortex-M3 soft, Cortex-M4 hard\n' \
  >> "$prefix/share/source-version.txt"
echo "=== Building GCC $gcc_version (compiler) ==="
cd /tmp/gcc-build
CFLAGS='-O2 -g0' CXXFLAGS='-O2 -g0' /tmp/gcc-source/configure \
  --target=arm-none-eabi --prefix="$prefix" \
  --with-sysroot="$sysroot" --with-native-system-header-dir=/include \
  --with-as="$prefix/bin/arm-none-eabi-as" --with-ld="$prefix/bin/arm-none-eabi-ld" \
  --with-newlib --enable-languages=c --enable-lto \
  --enable-multilib --with-multilib-list=rmprofile \
  --disable-bootstrap --disable-nls --disable-shared --disable-threads \
  --disable-libssp --disable-libquadmath --disable-libgomp --disable-libatomic
run_stage 25m make -j2 all-gcc
grep -Eq '^inhibit_libc[[:space:]]*=[[:space:]]*false$' gcc/Makefile
run_stage 5m make install-gcc
arm-none-eabi-gcc -print-multi-lib
test "$(arm-none-eabi-gcc -print-multi-lib | wc -l)" -eq 4
test "$(arm-none-eabi-gcc -mthumb -mcpu=cortex-m0plus -print-multi-directory)" = thumb/v6-m/nofp
test "$(arm-none-eabi-gcc -mcpu=cortex-m0plus -print-multi-directory)" = thumb/v6-m/nofp
test "$(arm-none-eabi-gcc -mthumb -mcpu=cortex-m3 -print-multi-directory)" = thumb/v7-m/nofp
test "$(arm-none-eabi-gcc -mthumb -mcpu=cortex-m4 -mfloat-abi=hard -print-multi-directory)" = thumb/v7e-m+fp/hard

echo "=== Building newlib $newlib_version with GCC $gcc_version ==="
cd /tmp/newlib-build
CFLAGS_FOR_TARGET='-g0 -Os -ffunction-sections -fdata-sections' \
  /tmp/newlib-source/configure --target=arm-none-eabi --prefix="$prefix" \
  --enable-target-optspace \
  --enable-newlib-io-long-long --enable-newlib-register-fini \
  --disable-nls --disable-newlib-supplied-syscalls
run_stage 15m make -j2
run_stage 5m make install
test -r "$sysroot/include/newlib.h"
test -r "$sysroot/include/_newlib_version.h"
install -m644 /tmp/newlib-source/COPYING* "$prefix/share/licenses/newlib/"

# Keep full newlib, including the fast memcpy/memmove/memset used by src/Makefile.
# Nano is built from the SAME verified source into a separate prefix, following
# ARM's two-library installation model, never installed over the full library:
# https://github.com/ARM-software/toolchain-gnu-bare-metal/blob/master/build-toolchain.sh
# https://github.com/ARM-software/toolchain-gnu-bare-metal/blob/master/build-common.sh
find "$sysroot" -type f -print0 | sort -z | xargs -0 sha256sum \
  > "$prefix/share/newlib-full-before-nano.sha256"
nano_prefix=/tmp/newlib-nano-install
mkdir -p /tmp/newlib-nano-build "$nano_prefix"
echo "=== Building newlib-nano $newlib_version with GCC $gcc_version ==="
cd /tmp/newlib-nano-build
nano_options=(
  --target=arm-none-eabi --prefix="$nano_prefix" --enable-target-optspace
  --disable-newlib-supplied-syscalls --enable-newlib-reent-check-verify
  --enable-newlib-reent-small --enable-newlib-retargetable-locking
  --disable-newlib-fvwrite-in-streamio --disable-newlib-fseek-optimization
  --disable-newlib-wide-orient --enable-newlib-nano-malloc
  --disable-newlib-unbuf-stream-opt --enable-lite-exit
  --enable-newlib-global-atexit --enable-newlib-nano-formatted-io --disable-nls
)
printf 'newlib-nano: same newlib-%s verified source; CFLAGS_FOR_TARGET=-g0 -Os -ffunction-sections -fdata-sections\n' "$newlib_version" \
  >> "$prefix/share/source-version.txt"
printf 'newlib-nano configure: %s\n' "${nano_options[*]}" >> "$prefix/share/source-version.txt"
CFLAGS_FOR_TARGET='-g0 -Os -ffunction-sections -fdata-sections' \
  /tmp/newlib-source/configure "${nano_options[@]}"
run_stage 15m make -j2
run_stage 5m make install

# Do not infer or silently omit a multilib. These are the compiler's exact four
# installed variants; the later CPU lookups must resolve to their own directory.
nano_multilib_text=$(arm-none-eabi-gcc -print-multi-lib)
mapfile -t nano_multilibs <<< "$nano_multilib_text"
test "${#nano_multilibs[@]}" -eq 4
nano_dirs=()
for multilib in "${nano_multilibs[@]}"; do
  multi_dir=${multilib%%;*}
  case "$multi_dir" in .|thumb/v6-m/nofp|thumb/v7-m/nofp|thumb/v7e-m+fp/hard) ;; *) exit 1 ;; esac
  [[ " ${nano_dirs[*]} " != *" $multi_dir "* ]]
  nano_dirs+=("$multi_dir")
  src_dir="$nano_prefix/arm-none-eabi/lib/$multi_dir"
  dst_dir="$sysroot/lib/$multi_dir"
  test -d "$src_dir" && test -d "$dst_dir"
  for archive in libc libg librdimon; do
    test -s "$src_dir/$archive.a"
    test ! -e "$dst_dir/${archive}_nano.a"
    install -m644 "$src_dir/$archive.a" "$dst_dir/${archive}_nano.a"
    cmp -- "$src_dir/$archive.a" "$dst_dir/${archive}_nano.a"
  done
  # The full installation already supplies these exact release specs. Preserve
  # them; require both builds to agree instead of replacing full-library files.
  cmp -- "$src_dir/nano.specs" "$dst_dir/nano.specs"
  cmp -- /tmp/newlib-source/libgloss/arm/elf-nano.specs "$dst_dir/nano.specs"
done
mkdir -p "$sysroot/include/newlib-nano"
install -m644 "$nano_prefix/arm-none-eabi/include/newlib.h" "$sysroot/include/newlib-nano/newlib.h"
grep -Eq '^#define _WANT_REENT_SMALL 1$' "$sysroot/include/newlib-nano/newlib.h"
grep -Eq '^#define _NANO_MALLOC 1$' "$sysroot/include/newlib-nano/newlib.h"
grep -Eq '^#define _NANO_FORMATTED_IO 1$' "$sysroot/include/newlib-nano/newlib.h"
sha256sum --check "$prefix/share/newlib-full-before-nano.sha256" > "$prefix/share/newlib-full-preserved.txt"
find "$sysroot" -type f \( -name '*_nano.a' -o -name nano.specs -o -path '*/newlib-nano/newlib.h' \) -print0 \
  | sort -z | xargs -0 sha256sum > "$prefix/share/newlib-nano.sha256"

echo "=== Building GCC $gcc_version runtime libraries against newlib $newlib_version ==="
cd /tmp/gcc-build
run_stage 15m make -j2 all-target-libgcc
run_stage 5m make install-target-libgcc
test "$(arm-none-eabi-gcc -dumpfullversion)" = "$gcc_version"
arm-none-eabi-ld --version | sed -n '1p'

for cpu in cortex-m0plus cortex-m3 cortex-m4; do
  flags=(-mthumb "-mcpu=$cpu")
  if [[ "$cpu" == cortex-m4 ]]; then flags+=(-mfloat-abi=hard); fi
  arm-none-eabi-gcc "${flags[@]}" -print-multi-directory
  multi_dir=$(arm-none-eabi-gcc "${flags[@]}" -print-multi-directory)
  library=$(realpath "$(arm-none-eabi-gcc "${flags[@]}" -print-file-name=libc.a)")
  [[ "$library" == "$sysroot/lib/$multi_dir/libc.a" ]]
  test -s "$library"
  for member in memcpy memmove memset; do
    arm-none-eabi-ar t "$library" | grep -Fx "libc_a-$member.o"
  done
  for archive in libc_nano libg_nano librdimon_nano; do
    nano_library=$(realpath "$(arm-none-eabi-gcc "${flags[@]}" -print-file-name="$archive.a")")
    [[ "$nano_library" == "$sysroot/lib/$multi_dir/$archive.a" ]]
    test -s "$nano_library"
  done
  nano_specs=$(realpath "$(arm-none-eabi-gcc "${flags[@]}" -print-file-name=nano.specs)")
  [[ "$nano_specs" == "$sysroot/lib/$multi_dir/nano.specs" ]]
  cmp -- /tmp/newlib-source/libgloss/arm/elf-nano.specs "$nano_specs"
  nano_defines=$(printf '#include <newlib.h>\n' | arm-none-eabi-gcc "${flags[@]}" --specs=nano.specs -dM -E -)
  for macro in _WANT_REENT_SMALL _NANO_MALLOC _NANO_FORMATTED_IO; do
    grep -Fx "#define $macro 1" <<< "$nano_defines"
  done
  grep -Fx '#define __NEWLIB__ 4' <<< "$nano_defines"
  grep -Fx '#define __NEWLIB_MINOR__ 6' <<< "$nano_defines"
  grep -Fx '#define __NEWLIB_PATCHLEVEL__ 0' <<< "$nano_defines"
  runtime=$(realpath "$(arm-none-eabi-gcc "${flags[@]}" -print-libgcc-file-name)")
  [[ "$runtime" == "$prefix/"*"/13.5.0/"* ]]
  test -r "$runtime"
done
install -m644 /tmp/gcc-source/COPYING3 /tmp/gcc-source/COPYING.RUNTIME "$prefix/share/licenses/gcc/"
cd /
rm -rf /tmp/gcc-source /tmp/gcc-build /tmp/gcc.tar /tmp/newlib-source /tmp/newlib-build /tmp/newlib.tar /tmp/newlib-nano-build /tmp/newlib-nano-install
