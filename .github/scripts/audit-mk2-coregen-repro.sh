#!/usr/bin/env bash
# Hosted-only experiment: compare original/repeated/rewritten CoreGen inputs.
# Equal bytes are evidence only for the generated files in this experiment.
set -euo pipefail

case "$CORE" in
  basex) ip_parent=sd2snes_base; ips=(dac_buf msu_databuf snescmd_buf) ;;
  dspx) ip_parent=sd2snes_dsp; ips=(dac_buf msu_databuf snescmd_buf upd77c25_datram upd77c25_datrom upd77c25_pgmrom) ;;
  *) echo "Unexpected core: $CORE" >&2; exit 2 ;;
esac
test "$ip_parent" = "$SOURCE"
test "$(git rev-parse HEAD)" = "$GITHUB_SHA"
test "$(git rev-parse HEAD:verilog)" = 4e50365f59f38217b67c5126276873a29be737d5
test "$(git hash-object --no-filters ".github/actions/prepare-build-image/action.yml")" = ac2a66fc24d4a15658b666cdc5f5db7964df4c3b
test "$(git hash-object --no-filters "verilog/sd2snes_$CORE/sd2snes_$CORE.xise")" = "$PROJECT_BLOB"
test "$(git hash-object --no-filters "verilog/$SOURCE/main.ucf")" = "$UCF_BLOB"
git diff --exit-code -- verilog .github/actions/prepare-build-image/action.yml
git diff --cached --exit-code -- verilog .github/actions/prepare-build-image/action.yml
image_id=$(docker image inspect sd2snes-ci:mk2 --format '{{.Id}}')
test "$image_id" = sha256:5e3bbb00649997abca8843b1d82d8529eda99a0f2868d37ad9777e0ad5fd50e8

audit="$RUNNER_TEMP/coregen-repro"
mkdir -p "$audit"
{
  printf 'Checkout: %s\nCore: %s\nVerilog tree: %s\n' "$GITHUB_SHA" "$CORE" "$(git rev-parse HEAD:verilog)"
  printf 'Project: %s\nUCF: %s\nISE image ID: %s\n' "$PROJECT_BLOB" "$UCF_BLOB" "$image_id"
  printf 'A1/A2 start from fresh tracked files; B starts from A1 post-CoreGen tracked files without A1 untracked products.\n'
  printf 'All samples run at the same container path /work. No FPGA timing analysis is performed.\n'
} | tee "$audit/identity.txt"

# Hash every tracked Verilog file, not just the expected CoreGen rewrites.
manifest() {
  python3 - "$GITHUB_WORKSPACE" "$1" "$2" <<'PY'
import hashlib, json, subprocess, sys
from pathlib import Path
workspace, sample, output = map(Path, sys.argv[1:])
raw = subprocess.check_output(['git', 'ls-files', '-z', '--', 'verilog'], cwd=workspace)
paths = [p.decode('utf-8') for p in raw.split(b'\0') if p]
result = {}
for name in paths:
    path = sample / name
    if not path.is_file() or path.is_symlink():
        raise SystemExit(f'Missing or non-regular tracked file: {name}')
    result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
output.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
PY
}

for sample in a1 a2 b; do
  mkdir -p "$audit/sample-$sample"
  git archive "$GITHUB_SHA" verilog | tar -xf - -C "$audit/sample-$sample"
  manifest "$audit/sample-$sample" "$audit/$sample-archive.json"
done
cmp "$audit/a1-archive.json" "$audit/a2-archive.json"
cmp "$audit/a1-archive.json" "$audit/b-archive.json"

capture_ip_files() {
  local root="$1" destination="$2" ip
  local dir="$root/verilog/$SOURCE/ip/mk2"
  mkdir -p "$destination"
  cp "$dir/coregen.cgc" "$destination/"
  for ip in "${ips[@]}"; do
    cp "$dir/$ip.xco" "$dir/$ip.xise" "$dir/$ip.v" "$destination/"
  done
}

generate() {
  local sample="$1" root="$audit/sample-$1" dir ip expected count
  dir="$root/verilog/$SOURCE/ip/mk2"
  capture_ip_files "$root" "$audit/$sample-inputs"
  manifest "$root" "$audit/$sample-before.json"
  for ip in "${ips[@]}"; do test ! -e "$dir/$ip.ngc"; done
  docker run --rm --user 0:0 --mac-address 08:00:27:68:c9:35 --env CORE \
    --volume "$root:/work" --workdir "/work/verilog/sd2snes_$CORE" \
    --entrypoint /bin/bash sd2snes-ci:mk2 -c '
      set -euo pipefail
      case "$CORE" in
        basex) ip_parent=sd2snes_base; ips=(dac_buf msu_databuf snescmd_buf) ;;
        dspx) ip_parent=sd2snes_dsp; ips=(dac_buf msu_databuf snescmd_buf upd77c25_datram upd77c25_datrom upd77c25_pgmrom) ;;
        *) exit 2 ;;
      esac
      dir="../$ip_parent/ip/mk2"
      targets=()
      for ip in "${ips[@]}"; do
        test -f "$dir/$ip.xco"
        test ! -e "$dir/$ip.ngc"
        targets+=("$dir/$ip.ngc")
      done
      make -j2 HOST=LINUX XILINX_ENV= "${targets[@]}"
      for ip in "${ips[@]}"; do test -s "$dir/$ip.ngc"; done
    ' 2>&1 | tee "$audit/$sample-coregen.log"
  for ip in "${ips[@]}"; do
    expected="coregen -p ../$SOURCE/ip/mk2 -b ../$SOURCE/ip/mk2/$ip.xco -r"
    count=$(grep -F -c -- "$expected" "$audit/$sample-coregen.log" || true)
    test "$count" = 1
  done
  manifest "$root" "$audit/$sample-after.json"
  capture_ip_files "$root" "$audit/$sample-outputs"
  for ip in "${ips[@]}"; do cp "$dir/$ip.ngc" "$audit/$sample-outputs/"; done
}

generate a1
generate a2
cmp "$audit/a1-before.json" "$audit/a2-before.json"

# Require that only the expected tracked files were rewritten in each clean
# generation.  This records the changes; it does not classify them as benign.
for sample in a1 a2; do
  python3 - "$audit/$sample-before.json" "$audit/$sample-after.json" "$SOURCE" "${ips[@]}" <<'PY' | tee "$audit/$sample-tracked-changes.txt"
import json, sys
from pathlib import Path
before = json.loads(Path(sys.argv[1]).read_text())
after = json.loads(Path(sys.argv[2]).read_text())
if before.keys() != after.keys():
    raise SystemExit('Tracked path set changed')
changed = {p for p in before if before[p] != after[p]}
root = f'verilog/{sys.argv[3]}/ip/mk2/'
expected = {root + 'coregen.cgc'}
expected.update(root + ip + ext for ip in sys.argv[4:] for ext in ('.xco', '.xise'))
for path in sorted(changed):
    print(f'{path}: {before[path]} -> {after[path]}')
if changed != expected:
    raise SystemExit(f'Unexpected tracked rewrites: missing={sorted(expected-changed)}, extra={sorted(changed-expected)}')
PY
done

# B receives exactly A1's post-generation tracked inputs but no generated NGC
# or other untracked output.  Verify the whole tracked tree before generating.
b_dir="$audit/sample-b/verilog/$SOURCE/ip/mk2"
a_dir="$audit/sample-a1/verilog/$SOURCE/ip/mk2"
cp "$a_dir/coregen.cgc" "$b_dir/coregen.cgc"
for ip in "${ips[@]}"; do
  cp "$a_dir/$ip.xco" "$a_dir/$ip.xise" "$b_dir/"
done
manifest "$audit/sample-b" "$audit/b-updated-input.json"
cmp "$audit/a1-after.json" "$audit/b-updated-input.json"
generate b
cmp "$audit/b-updated-input.json" "$audit/b-before.json"

# Report exact binary comparisons, not inferred logical or timing equivalence.
for ip in "${ips[@]}"; do
  for sample in a1 a2 b; do
    sha256sum "$audit/$sample-outputs/$ip.ngc"
  done
  if cmp -s "$audit/a1-outputs/$ip.ngc" "$audit/a2-outputs/$ip.ngc"; then
    printf '%s original repeat: byte-identical\n' "$ip"
  else
    printf '%s original repeat: DIFFERENT bytes\n' "$ip"
  fi
  if cmp -s "$audit/a1-outputs/$ip.ngc" "$audit/b-outputs/$ip.ngc"; then
    printf '%s original vs rewritten inputs: byte-identical\n' "$ip"
  else
    printf '%s original vs rewritten inputs: DIFFERENT bytes\n' "$ip"
  fi
done | tee "$audit/netlist-comparison.txt"

# A deliberately changed copy must be rejected by the byte comparator.
first=${ips[0]}
cmp -s "$audit/a1-outputs/$first.ngc" "$audit/a1-outputs/$first.ngc"
cp "$audit/a1-outputs/$first.ngc" "$audit/negative-control.ngc"
printf '\001' >> "$audit/negative-control.ngc"
if cmp -s "$audit/a1-outputs/$first.ngc" "$audit/negative-control.ngc"; then
  echo 'Byte comparison failed its changed-file control' >&2
  exit 1
fi
rm "$audit/negative-control.ngc"
printf '%s\n' 'Byte comparator accepted the same file and rejected an intentionally changed copy.' | tee "$audit/comparison-control.txt"
printf '%s\n' 'No historical NGCs, whole-FPGA timing, electrical behavior or gate waiver are established by this audit.'
