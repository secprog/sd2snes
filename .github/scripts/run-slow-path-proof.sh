#!/usr/bin/env bash
# Run ONLY on a GitHub-hosted runner; retain all actual proof models and witnesses.
set -euo pipefail
test "${GITHUB_ACTIONS:-}" = true
family="$1"
output="$2"
case "$family" in
  dsp) top=status_model ;;
  basex) top=address_model ;;
  *) exit 2 ;;
esac
cd "$output"
sha256sum --check SHA256SUMS
mapfile -t variants < <(python3 -c 'import json; print("\n".join(json.load(open("variants.json"))))')
test "${variants[0]}" = gold
test "${variants[1]}" = gate
for variant in "${variants[@]}"; do
  mkdir "$variant"
  cp "$variant.v" "$variant/model.v"
  (
    cd "$variant"
    name=gate
    if [[ "$variant" == gold ]]; then name=gold; fi
    if [[ "$family" == dsp ]]; then
      yosys -l preparation.log -p "read_verilog -sv -formal model.v; hierarchy -check -top $top; flatten; proc -ifx -noopt; check -assert; dffunmap; setundef -undriven -undef; opt_clean; check -assert; write_json state.json"
      python3 "$GITHUB_WORKSPACE/.github/scripts/cut-dsp-status-state.py" state.json transition.json "$name" | tee state-audit.log
      yosys -l state-view.log -p "read_json transition.json; hierarchy -check -top $name; sat -verify -enable_undef -prove state_view_ok 1 -show-inputs -show state_view_ok -timeout 180"
      grep -F 'SAT proof finished - no model found: SUCCESS!' state-view.log
      if [[ "$variant" == gold ]]; then
        result=0
        yosys -l state-view-mutant.log -p 'read_json state-view-mutant.json; hierarchy -check -top gold; sat -verify -enable_undef -set-def-inputs -prove state_view_ok 1 -show-inputs -show state_view_ok -dump_json state-view-mutant-counterexample.json -timeout 180' || result=$?
        test "$result" -ne 0
        grep -F 'SAT proof finished - model found: FAIL!' state-view-mutant.log
        test -s state-view-mutant-counterexample.json
      fi
    else
      yosys -l preparation.log -p "read_verilog -sv -formal model.v; hierarchy -check -top $top; flatten; proc -ifx -noopt; check -assert; setundef -undriven -undef; opt_clean; check -assert; rename $top $name; write_json transition.json"
      python3 - "$name" <<'PY'
import json, sys
m = json.load(open('transition.json'))['modules']
assert set(m) == {sys.argv[1]}
m = m[sys.argv[1]]
assert m['ports']['SRAM_SNES_ADDR']['direction'] == 'output'
assert len(m['ports']['SRAM_SNES_ADDR']['bits']) == 24
for net in m['netnames'].values():
    assert 'init' not in net.get('attributes', {})
for cell in m['cells'].values():
    kind = cell['type']
    assert kind.startswith('$') and kind not in ('$ff', '$anyseq', '$anyconst', '$assume')
    assert not any(word in kind.lower() for word in ('dff', 'latch', 'mem'))
    assert 'CLK' not in cell['connections']
print('Full 24-bit combinational address model: no state, init, blackbox or assumption')
PY
    fi
  )
done
for mode in binary xstate; do
  input_flags=''
  if [[ "$mode" == binary ]]; then input_flags='-set-def-inputs'; fi
  for variant in "${variants[@]:1}"; do
    if [[ "$mode" == xstate && "$variant" != gate && "$variant" != bad-x-* ]]; then continue; fi
    cat > "$variant/prove-$mode.ys" <<YOSYS
read_json ../gold/transition.json
read_json transition.json
miter -equiv -make_assert -make_outputs -make_outcmp gold gate miter
hierarchy -check -top miter
flatten -wb
hierarchy -check -top miter
opt_clean
check -assert
write_json miter-$mode.json
sat -verify -enable_undef $input_flags -prove-asserts -show-inputs -show-outputs -dump_json counterexample-$mode.json -timeout 300
YOSYS
    result=0
    (cd "$variant" && yosys -l "proof-$mode.log" -s "prove-$mode.ys") || result=$?
    test -s "$variant/miter-$mode.json"
    if [[ "$variant" == gate || ( "$variant" == bad-x-* && "$mode" == binary ) ]]; then
      test "$result" -eq 0
      grep -F 'SAT proof finished - no model found: SUCCESS!' "$variant/proof-$mode.log"
    else
      test "$result" -ne 0
      grep -F 'SAT proof finished - model found: FAIL!' "$variant/proof-$mode.log"
      test -s "$variant/counterexample-$mode.json"
    fi
  done
done
sha256sum --check SHA256SUMS
printf '%s\n' "$family: strict binary and unrestricted Yosys-X component proof and actual negative controls passed. Independent source/state/miter/witness review required. No FPGA mapping, timing, integration or hardware result." | tee verified.txt
