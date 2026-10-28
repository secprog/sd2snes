#!/usr/bin/env python3
"""Prepare a source-pinned, runner-only DSP stack restore decoder comparison."""

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

# Proof-only guard for Yosys memory lowering: the native source's original
# unsized subtraction and return expression remain byte-identical.
PROOF_RETURN = "(regs_sp == 4'd0) ? 11'bx : stack[regs_sp-1]"


def unique(text, fragment):
    if text.count(fragment) != 1:
        raise SystemExit(f"Expected one occurrence of {fragment!r}")


def restore_case():
    lines = ["        case(ss_wa[7:1])"]
    for word in range(16):
        lines.extend([
            f"          7'h{0x1a + word:02x}: begin",
            f"            if(ss_wa[0]) stack[{word}][10:8] <= ss_wd[2:0];",
            f"            else stack[{word}][7:0] <= ss_wd;",
            "          end",
        ])
    lines.extend(["          default: begin end", "        endcase"])
    return "\n".join(lines)


def stack_write(restore):
    return (
        "always @(posedge CLK) begin\n"
        "  if(RST & ~ss_frozen) begin\n" + ref.PUSH + "\n"
        "  end else if(RST & ss_frozen) begin\n"
        "    if(ss_wr) begin\n"
        "      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n"
        + restore + "\n      end\n    end\n  end\nend"
    )


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-stack-case-experiment.py SOURCE OUTPUT_DIR")
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
        unique(original, fragment)
    remainder = original
    for fragment in fragments:
        remainder = remainder.replace(fragment, "")
    if re.search(r"\bstack\b", ref.without_comments(remainder)):
        raise SystemExit("Unmodelled stack access, reset or initialization")
    push_context = (
        "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n"
        "`ifdef MK2\n    push_now <= 1'b0;\n" + ref.PUSH + "\n`endif\n"
    )
    unique(original, push_context)
    restore_context = re.search(
        r"  end else if\(RST & ss_frozen\) begin\n"
        r"    // savestate RESTORE.*?\n    if\(ss_wr\) begin\n"
        r"      if\(ss_wa >= 8'h34 && ss_wa <= 8'h53\) begin\n"
        + re.escape(ref.RESTORE) + r"\n      end else case\(ss_wa\)",
        original, flags=re.S,
    )
    if not restore_context:
        raise SystemExit("Original restore guard, range or priority context changed")
    unique(original, "`ifndef MK2\n" + ref.OTHER_PUSH + "\n`endif")

    case = restore_case()
    wrapped = "`ifdef MK2\n" + case + "\n`else\n" + ref.RESTORE + "\n`endif"
    candidate = original.replace(ref.RESTORE, wrapped, 1)
    if candidate.replace(wrapped, ref.RESTORE, 1) != original:
        raise SystemExit("Source outside the restore assignments did not recover exactly")
    for defines in ({"MK3"}, {"MK3", "DEBUG"}, set(), {"DEBUG"}):
        before = re.sub(r"\s+", "", ref.without_comments(ref.configured(original, defines)))
        after = re.sub(r"\s+", "", ref.without_comments(ref.configured(candidate, defines)))
        if before != after:
            raise SystemExit(f"Non-MkII source changed under {sorted(defines)}")

    # The original outer reset/freeze/write/range guards remain in BOTH models.
    gold = ref.model(ref.DECL, stack_write(ref.RESTORE), "stack[ss_stk_idx]", PROOF_RETURN, False)
    gate = ref.model(ref.DECL, stack_write(case), "stack[ss_stk_idx]", PROOF_RETURN, False)
    mutants = {
        "bad-address": (gate, "7'h1a: begin", "7'h19: begin"),
        "bad-lane": (gate, "if(ss_wa[0]) stack[0][10:8]", "if(~ss_wa[0]) stack[0][10:8]"),
        "bad-data": (gate, "stack[0][7:0] <= ss_wd;", "stack[0][7:0] <= ss_wd ^ 8'h01;"),
        "bad-freeze": (gate, "if(RST & ~ss_frozen)", "if(RST)"),
        "bad-return": (gate, PROOF_RETURN, "stack[regs_sp-4'd1]"),
        # Binary-equivalent control which becomes X-sensitive when data is X.
        "bad-x": (gate, "if(ss_wr) begin", "if(ss_wr & (ss_wd[0] | ~ss_wd[0])) begin"),
    }
    files = {
        "original-upd77c25.v": original,
        "candidate-upd77c25.v": candidate,
        "gold.v": gold,
        "gate.v": gate,
    }
    for name, (text, before, after) in mutants.items():
        unique(text, before)
        files[name + ".v"] = text.replace(before, after, 1)
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
        )), encoding="utf-8",
    )
    print(f"Pinned DSP blob {blob}; original source recovered and four non-MkII configurations audited.")
    print("Prepared the original guards, all 176 stack bits, both reads and six negative controls.")
    print("Native push, return, clock, range and write-enable expressions are unchanged.")


if __name__ == "__main__":
    main()
