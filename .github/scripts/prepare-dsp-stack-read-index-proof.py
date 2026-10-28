#!/usr/bin/env python3
"""Prepare a source-pinned DSPx stack read-index proof for hosted runners."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "stack_case", Path(__file__).with_name("prepare-dsp-stack-case-experiment.py")
)
case = importlib.util.module_from_spec(spec)
spec.loader.exec_module(case)
ref = case.ref

# The discarded address bits must still propagate an unknown into the index,
# just as the original 8-bit subtraction does in the Yosys-X model. The
# second term is zero for every binary input; neither term adds state or clocks.
NARROW_INDEX = """wire ss_idx_discarded = ^{DP_ADDR[7:5], DP_ADDR[0]};
wire [3:0] ss_stk_idx = (DP_ADDR[4:1] - 4'hA)
                       + {3'b000, (ss_idx_discarded & ~ss_idx_discarded)};"""
SIMPLE_INDEX = "wire [3:0] ss_stk_idx = DP_ADDR[4:1] - 4'hA;"


def configured(text, defines):
    """Resolve the pinned file's known conditionals for a non-target audit."""
    active, parents, output = True, [], []
    for line in text.splitlines(True):
        directive = re.fullmatch(r"\s*`(ifdef|ifndef)\s+(\w+)\s*", line)
        if directive:
            kind, macro = directive.groups()
            if macro not in {"MK2", "MK3", "DEBUG", "DSP_COMP"}:
                raise SystemExit(f"Unreviewed preprocessor condition: {macro}")
            condition = (macro in defines) == (kind == "ifdef")
            parents.append((active, condition))
            active = active and condition
        elif line.strip() == "`else":
            parent, condition = parents[-1]
            active = parent and not condition
        elif line.strip() == "`endif":
            active, _ = parents.pop()
        elif active:
            output.append(line)
    if parents:
        raise SystemExit("Unbalanced configuration boundaries")
    return "".join(output)


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise SystemExit(f"Expected one occurrence of {before!r}")
    return text.replace(before, after, 1)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-stack-read-index-proof.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != ref.EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete DSP source blob: {blob}")
    original = raw.decode("utf-8")
    fragments = (
        ref.DECL, ref.PUSH, ref.OTHER_PUSH, ref.SCAN_READ, ref.RETURN,
        ref.RESTORE, ref.SCAN_INDEX, ref.WRITE_INDEX,
    )
    for fragment in fragments:
        case.unique(original, fragment)
    remainder = original
    for fragment in fragments:
        remainder = remainder.replace(fragment, "")
    if re.search(r"\bstack\b", ref.without_comments(remainder)):
        raise SystemExit("Unmodelled stack access, reset or initialization")
    if re.search(r"\bss_idx_discarded\b", ref.without_comments(original)):
        raise SystemExit("The proof helper name is already in use")
    push_context = (
        "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n"
        "`ifdef MK2\n    push_now <= 1'b0;\n" + ref.PUSH + "\n`endif\n"
    )
    case.unique(original, push_context)
    restore_context = re.search(
        r"  end else if\(RST & ss_frozen\) begin\n"
        r"    // savestate RESTORE.*?\n    if\(ss_wr\) begin\n"
        r"      if\(ss_wa >= 8'h34 && ss_wa <= 8'h53\) begin\n"
        + re.escape(ref.RESTORE) + r"\n      end else case\(ss_wa\)",
        original, flags=re.S,
    )
    if not restore_context:
        raise SystemExit("Original restore guard, range or priority context changed")
    case.unique(original, "`ifndef MK2\n" + ref.OTHER_PUSH + "\n`endif")

    wrapped = (
        "`ifdef MK2\n`ifdef DSP_COMP\n" + NARROW_INDEX
        + "\n`else\n" + ref.SCAN_INDEX + "\n`endif\n`else\n"
        + ref.SCAN_INDEX + "\n`endif"
    )
    candidate = replace_once(original, ref.SCAN_INDEX, wrapped)
    if candidate.replace(wrapped, ref.SCAN_INDEX, 1) != original:
        raise SystemExit("Source outside the read index did not recover exactly")
    configs = (
        set(), {"DEBUG"}, {"MK3"}, {"MK3", "DEBUG"}, {"MK2"},
        {"MK2", "DEBUG"}, {"DSP_COMP"}, {"DSP_COMP", "DEBUG"},
        {"MK3", "DSP_COMP"}, {"MK3", "DSP_COMP", "DEBUG"},
    )
    for defines in configs:
        before = re.sub(r"\s+", "", ref.without_comments(configured(original, defines)))
        after = re.sub(r"\s+", "", ref.without_comments(configured(candidate, defines)))
        if before != after:
            raise SystemExit(f"Non-target source changed under {sorted(defines)}")
    for defines in ({"MK2", "DSP_COMP"}, {"MK2", "DSP_COMP", "DEBUG"}):
        target = configured(candidate, defines)
        if target.count(NARROW_INDEX) != 1 or ref.SCAN_INDEX in target:
            raise SystemExit(f"Target source was not selected under {sorted(defines)}")

    # Model the complete original stack write boundary and both reads. The
    # proof-only SP=0 return guard is identical in both models; native RTL is
    # unchanged. The next-state audit checks all 176 actual stack Q/D bits.
    gold = ref.model(ref.DECL, case.stack_write(ref.RESTORE),
                     "stack[ss_stk_idx]", case.PROOF_RETURN, False)
    gate = replace_once(gold, ref.SCAN_INDEX, NARROW_INDEX)
    mutants = {
        "bad-read-offset": replace_once(gate, "DP_ADDR[4:1] - 4'hA", "DP_ADDR[4:1] - 4'hB"),
        "bad-read-slice": replace_once(gate, "DP_ADDR[4:1] - 4'hA", "DP_ADDR[5:2] - 4'hA"),
        "bad-lane": replace_once(gate, "if(ss_wa[0]) stack[ss_wstk_idx][10:8]",
                                  "if(~ss_wa[0]) stack[ss_wstk_idx][10:8]"),
        "bad-data": replace_once(gate, "stack[ss_wstk_idx][7:0]  <= ss_wd;",
                                  "stack[ss_wstk_idx][7:0]  <= ss_wd ^ 8'h01;"),
        "bad-freeze": replace_once(gate, "if(RST & ~ss_frozen)", "if(RST)"),
        "bad-return": replace_once(gate, case.PROOF_RETURN, "stack[regs_sp-4'd1]"),
        # Binary-equivalent mutants must each produce an X-state counterexample.
        "bad-x-simple": replace_once(gate, NARROW_INDEX, SIMPLE_INDEX),
        "bad-x-high": replace_once(gate, "^{DP_ADDR[7:5], DP_ADDR[0]}",
                                   "^{DP_ADDR[6:5], DP_ADDR[0]}"),
        "bad-x-low": replace_once(gate, "^{DP_ADDR[7:5], DP_ADDR[0]}",
                                  "^DP_ADDR[7:5]"),
        "bad-x-write-guard": replace_once(
            gate, "if(ss_wr) begin",
            "if(ss_wr & (ss_wd[0] | ~ss_wd[0])) begin"
        ),
        "bad-x-write-data": replace_once(
            gate, "stack[ss_wstk_idx][7:0]  <= ss_wd;",
            "stack[ss_wstk_idx][7:0]  <= ss_wd & {8{(pc[1] & pc[0]) | (~pc[1] & pc[0]) | ~pc[0]}};"
        ),
    }
    files = {
        "original-upd77c25.v": original,
        "candidate-upd77c25.v": candidate,
        "gold.v": gold,
        "gate.v": gate,
        **{name + ".v": text for name, text in mutants.items()},
    }
    output.mkdir(parents=True, exist_ok=True)
    sums = []
    for name, content in files.items():
        data = content.encode("utf-8")
        (output / name).write_bytes(data)
        sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(
            original.splitlines(True), candidate.splitlines(True),
            "original-upd77c25.v", "candidate-upd77c25.v"
        )), encoding="utf-8"
    )
    print(f"Pinned DSP blob {blob}; original source recovered exactly.")
    print("Ten non-target and two target configurations audited.")
    print("Prepared all 176 stack transitions, both reads and eleven negative controls.")
    print("No claim of mapped savings, native timing or hardware equivalence.")


if __name__ == "__main__":
    main()
