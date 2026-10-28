#!/usr/bin/env python3
"""Prepare a source-pinned, runner-only stack clock-enable mapping trial."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "stack_reference", Path(__file__).with_name("prepare-dsp-stack-experiment.py")
)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)

ATTRIBUTE = '(* use_clock_enable = "no" *)\n'
PROOF_RETURN = "(regs_sp == 4'd0) ? 11'bx : stack[regs_sp-1]"


def unique(text, fragment):
    if text.count(fragment) != 1:
        raise SystemExit(f"Expected one occurrence of {fragment!r}")


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-stack-ce-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != ref.EXPECTED_BLOB:
        raise SystemExit(f"Unexpected DSP source blob: {blob}")
    original = raw.decode("utf-8")
    fragments = (ref.DECL, ref.PUSH, ref.OTHER_PUSH, ref.SCAN_READ, ref.RETURN,
                 ref.RESTORE, ref.SCAN_INDEX, ref.WRITE_INDEX)
    for fragment in fragments:
        unique(original, fragment)
    remainder = original
    for fragment in fragments:
        remainder = remainder.replace(fragment, "")
    if re.search(r"\bstack\b", ref.without_comments(remainder)):
        raise SystemExit("Unmodelled stack access, reset or initialization")
    push_context = ("always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n"
                    "`ifdef MK2\n    push_now <= 1'b0;\n" + ref.PUSH + "\n`endif\n")
    unique(original, push_context)
    restore_context = re.search(
        r"  end else if\(RST & ss_frozen\) begin\n"
        r"    // savestate RESTORE.*?\n    if\(ss_wr\) begin\n"
        r"      if\(ss_wa >= 8'h34 && ss_wa <= 8'h53\) begin\n"
        + re.escape(ref.RESTORE) + r"\n      end else case\(ss_wa\)",
        original, flags=re.S,
    )
    if not restore_context:
        raise SystemExit("Original restore guard, range or priority changed")
    unique(original, "`ifndef MK2\n" + ref.OTHER_PUSH + "\n`endif")

    wrapped = "`ifdef MK2\n" + ATTRIBUTE + "`endif\n" + ref.DECL
    candidate = original.replace(ref.DECL, wrapped, 1)
    if candidate.replace(wrapped, ref.DECL, 1) != original:
        raise SystemExit("Source outside the one synthesis attribute changed")
    for defines in ({"MK3"}, {"MK3", "DEBUG"}, set(), {"DEBUG"}):
        before = re.sub(r"\s+", "", ref.without_comments(ref.configured(original, defines)))
        after = re.sub(r"\s+", "", ref.without_comments(ref.configured(candidate, defines)))
        if before != after:
            raise SystemExit(f"Non-MkII source changed under {sorted(defines)}")

    write = ("always @(posedge CLK) begin\n"
             "  if(RST & ~ss_frozen) begin\n" + ref.PUSH + "\n"
             "  end else if(RST & ss_frozen) begin\n"
             "    if(ss_wr) begin\n"
             "      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n"
             + ref.RESTORE + "\n      end\n    end\n  end\nend")
    gold = ref.model(ref.DECL, write, "stack[ss_stk_idx]", PROOF_RETURN, False)
    gate = ref.model(ATTRIBUTE + ref.DECL, write, "stack[ss_stk_idx]", PROOF_RETURN, False)
    mutants = {
        "bad-address": ("stack[ss_wstk_idx][7:0]", "stack[ss_wstk_idx ^ 4'b0001][7:0]"),
        "bad-lane": ("if(ss_wa[0]) stack[ss_wstk_idx][10:8]", "if(~ss_wa[0]) stack[ss_wstk_idx][10:8]"),
        "bad-data": ("stack[ss_wstk_idx][7:0]  <= ss_wd;", "stack[ss_wstk_idx][7:0]  <= ss_wd ^ 8'h01;"),
        "bad-freeze": ("if(RST & ~ss_frozen)", "if(RST)"),
        "bad-return": (PROOF_RETURN, "stack[regs_sp-4'd1]"),
        "bad-x": ("if(ss_wr) begin", "if(ss_wr & (ss_wd[0] | ~ss_wd[0])) begin"),
        "bad-x-data": ("stack[ss_wstk_idx][7:0]  <= ss_wd;",
                       "stack[ss_wstk_idx][7:0]  <= ss_wd & {8{(pc[1] & pc[0]) | (~pc[1] & pc[0]) | ~pc[0]}};"),
    }
    files = {"original-upd77c25.v": original, "candidate-upd77c25.v": candidate,
             "gold.v": gold, "gate.v": gate}
    for name, (before, after) in mutants.items():
        unique(gate, before)
        files[name + ".v"] = gate.replace(before, after, 1)
    output.mkdir(parents=True, exist_ok=True)
    sums = []
    for name, content in files.items():
        data = content.encode("utf-8")
        (output / name).write_bytes(data)
        sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-upd77c25.v", "candidate-upd77c25.v")),
        encoding="utf-8")
    print(f"Pinned DSP blob {blob}; source recovered and four non-MkII configurations audited.")
    print("One MkII stack mapping attribute; no clock, state, cycle, guard or source logic changes.")
    print("Prepared 176 stack transitions, both reads and seven negative controls.")


if __name__ == "__main__":
    main()
