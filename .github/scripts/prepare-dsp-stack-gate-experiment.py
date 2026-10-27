#!/usr/bin/env python3
"""Generate a runner-only stack write-gate candidate with unchanged storage."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


# Reuse the already audited source fragments, configuration reader and complete
# state/read observation model. Importing this file does not run its experiment.
spec = importlib.util.spec_from_file_location(
    "stack_reference", Path(__file__).with_name("prepare-dsp-stack-experiment.py"))
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)

HELPER = """// AMD UG627: one combinational LUT after the per-word decoders.
// Preserve the original frozen-versus-running choice without new state.
(* LUT_MAP="yes" *)
module dsp_stack_write_gate(
  input frozen, push_selected, restore_selected, lane,
  output we
);
assign we = (~frozen & push_selected) | (frozen & restore_selected & lane);
endmodule
"""


def factored_writes():
    parts = [
        "// Unchanged sixteen 11-bit words, CALL cycle and partial restore writes.\n",
        "wire [10:0] stack_push_data = pc + 1;\n",
        "wire [10:0] stack_write_data = ss_frozen ? {ss_wd[2:0], ss_wd} : stack_push_data;\n",
        "wire [15:0] stack_push_sel, stack_restore_sel, stack_low_we, stack_high_we;\n",
    ]
    for word in range(16):
        parts.append(
            f"assign stack_push_sel[{word}] = RST & push_now & (regs_sp == 4'd{word});\n"
            f"assign stack_restore_sel[{word}] = RST & ss_wr & (ss_wa[7:1] == 7'h{0x1a + word:02x});\n"
        )
        for lane, bit in (("low", "~ss_wa[0]"), ("high", "ss_wa[0]")):
            parts.append(
                f"dsp_stack_write_gate stack_{lane}_gate_{word}(\n"
                f"  .frozen(ss_frozen), .push_selected(stack_push_sel[{word}]),\n"
                f"  .restore_selected(stack_restore_sel[{word}]), .lane({bit}),\n"
                f"  .we(stack_{lane}_we[{word}])\n"
                ");\n"
            )
        parts.append(
            "always @(posedge CLK) begin\n"
            f"  if(stack_low_we[{word}]) stack[{word}][7:0] <= stack_write_data[7:0];\n"
            f"  if(stack_high_we[{word}]) stack[{word}][10:8] <= stack_write_data[10:8];\n"
            "end\n"
        )
    return "".join(parts)


def main():
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != ref.EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete DSP source blob: {blob}")
    original = raw.decode("utf-8")
    fragments = (ref.DECL, ref.PUSH, ref.OTHER_PUSH, ref.SCAN_READ, ref.RETURN,
                 ref.RESTORE, ref.SCAN_INDEX, ref.WRITE_INDEX)
    for fragment in fragments:
        if original.count(fragment) != 1:
            raise SystemExit(f"Stack access boundary changed: {fragment}")
    remainder = original
    for fragment in fragments:
        remainder = remainder.replace(fragment, "")
    if re.search(r"\bstack\b", ref.without_comments(remainder)):
        raise SystemExit("Unmodelled stack access, initializer or reset")
    push_context = ("always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n"
                    "`ifdef MK2\n    push_now <= 1'b0;\n" + ref.PUSH + "\n`endif\n")
    if original.count(push_context) != 1:
        raise SystemExit("The MkII CALL clock/enable/priority context changed")
    restore_context = re.search(
        r"  end else if\(RST & ss_frozen\) begin\n"
        r"    // savestate RESTORE.*?\n    if\(ss_wr\) begin\n"
        r"      if\(ss_wa >= 8'h34 && ss_wa <= 8'h53\) begin\n"
        + re.escape(ref.RESTORE) + r"\n      end else case\(ss_wa\)", original, flags=re.S)
    if not restore_context:
        raise SystemExit("The stack restore clock/enable/range/priority context changed")
    if original.count("`ifndef MK2\n" + ref.OTHER_PUSH + "\n`endif") != 1:
        raise SystemExit("The non-MkII CALL write boundary changed")

    write = factored_writes()
    insert = "\n`ifdef MK2\n" + write + "`endif"
    wrapped_restore = "`ifndef MK2\n" + ref.RESTORE + "\n`endif"
    helper = "\n`ifdef MK2\n" + HELPER + "`endif\n"
    candidate = original.replace(ref.PUSH + "\n", "")
    candidate = candidate.replace(ref.RESTORE, wrapped_restore)
    candidate = candidate.replace(ref.WRITE_INDEX, ref.WRITE_INDEX + insert) + helper

    # Recover every original byte, including declarations, read expressions and
    # other registers' transitions, after undoing precisely these three edits.
    recovered = candidate.removesuffix(helper)
    recovered = recovered.replace(ref.WRITE_INDEX + insert, ref.WRITE_INDEX)
    recovered = recovered.replace(wrapped_restore, ref.RESTORE)
    recovered = recovered.replace(push_context.replace(ref.PUSH + "\n", ""), push_context)
    if recovered != original:
        raise SystemExit("Source outside the audited stack writes changed")
    for defines in ({"MK3"}, {"MK3", "DEBUG"}, set(), {"DEBUG"}):
        before = re.sub(r"\s+", "", ref.without_comments(ref.configured(original, defines)))
        after = re.sub(r"\s+", "", ref.without_comments(ref.configured(candidate, defines)))
        if before != after:
            raise SystemExit(f"Non-MkII source changed under {sorted(defines)}")

    gold_write = ("always @(posedge CLK) begin\n"
                  "  if(RST & ~ss_frozen) begin\n" + ref.PUSH + "\n"
                  "  end else if(RST & ss_frozen) begin\n"
                  "    if(ss_wr) begin\n"
                  "      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n"
                  + ref.RESTORE + "\n      end\n    end\n  end\nend")
    gold = ref.model(ref.DECL, gold_write, "stack[ss_stk_idx]", "stack[regs_sp-1]", False)
    gate = ref.model(ref.DECL, write, "stack[ss_stk_idx]", "stack[regs_sp-1]", False) + HELPER
    bad_data = gate.replace("<= stack_write_data[7:0];", "<= stack_write_data[7:0] ^ 8'h01;", 1)
    bad_freeze = gate.replace("(~frozen & push_selected)", "push_selected", 1)
    bad_wrap = gate.replace("stack[regs_sp-1]", "stack[regs_sp-4'd1]", 1)
    if any(mutant == gate for mutant in (bad_data, bad_freeze, bad_wrap)):
        raise SystemExit("A required negative-control mutation was not applied")
    output.mkdir(parents=True, exist_ok=True)
    files = {
        "original-upd77c25.v": original, "candidate-upd77c25.v": candidate,
        "gold.v": gold, "gate.v": gate, "bad-data.v": bad_data,
        "bad-freeze.v": bad_freeze, "bad-wrap.v": bad_wrap,
    }
    hashes = []
    for name, text in files.items():
        data = text.encode("utf-8")
        (output / name).write_bytes(data)
        hashes.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(hashes), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-upd77c25.v", "candidate-upd77c25.v")), encoding="utf-8")
    print(f"Verified DSP blob {blob}; all stack accesses and parent conditions accounted for.")
    print("Source outside stack writes recovered byte for byte; all four non-MkII configurations unchanged.")
    print("Generated factored write gates with unchanged 176-bit storage, two reads and three negative controls.")


if __name__ == "__main__":
    main()
