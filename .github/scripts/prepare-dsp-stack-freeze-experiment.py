#!/usr/bin/env python3
"""Prepare a runner-only DSP stack-local freeze replica and two proofs."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


def load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ref = load_module("stack_reference", "prepare-dsp-stack-experiment.py")
freeze = load_module("freeze_reference", "prepare-dsp-freeze-replica-experiment.py")
REPLICA = (freeze.REPLICA.replace("ss_core_frozen", "ss_stack_frozen")
           .replace("main core's freeze load", "stack's freeze load"))
# The native source retains its exact original return expression. This explicit
# proof-only X models the original unsized SP-1 out-of-range read at SP=0;
# Yosys 0.33 otherwise narrows mem2reg dynamic read indices when lowering.
PROOF_RETURN = "(regs_sp == 4'd0) ? 11'bx : stack[regs_sp-1]"


def unique(text, fragment):
    if text.count(fragment) != 1:
        raise SystemExit(f"Expected exactly one source fragment: {fragment!r}")


def stack_write(frozen_name):
    return ("always @(posedge CLK) begin\n"
            f"  if(RST & ~{frozen_name}) begin\n" + ref.PUSH + "\n"
            f"  end else if(RST & {frozen_name}) begin\n"
            "    if(ss_wr) begin\n"
            "      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n"
            + ref.RESTORE + "\n      end\n    end\n  end\nend")


def replica_projection(replica):
    body = replica.split("always @(posedge CLK) begin\n", 1)[1].split("\nend\n`endif", 1)[0]
    body = body.replace("ss_stack_frozen <=", "next_frozen =")
    if "ss_stack_frozen <=" in body:
        raise SystemExit("Unprojected replica assignment")
    return "always @* begin\n  next_frozen = ss_frozen;\n" + body + "\nend"


def freeze_model(name, block, init):
    return f"""module {name}(
  input RST, ss_halt_eff, ss_boundary, ss_frozen,
  input [7:0] ss_wait, output reg next_frozen, output initial_frozen
);
assign initial_frozen = {init};
{block}
endmodule
"""


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-stack-freeze-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != ref.EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete DSP source blob: {blob}")
    original = raw.decode("utf-8")
    fragments = (ref.DECL, ref.PUSH, ref.OTHER_PUSH, ref.SCAN_READ, ref.RETURN,
                 ref.RESTORE, ref.SCAN_INDEX, ref.WRITE_INDEX,
                 freeze.FREEZE_DECL, freeze.WAIT_DECL, freeze.FREEZE_BLOCK)
    for fragment in fragments:
        unique(original, fragment)
    if re.search(r"\bss_stack_frozen\b", ref.without_comments(original)):
        raise SystemExit("Stack freeze identifier already exists")
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
        + re.escape(ref.RESTORE) + r"\n      end else case\(ss_wa\)", original, flags=re.S)
    if not restore_context:
        raise SystemExit("Original restore guard/range/priority context changed")
    unique(original, "`ifndef MK2\n" + ref.OTHER_PUSH + "\n`endif")
    unique(original, "reg  ss_frozen; initial ss_frozen = 1'b0;")
    unique(REPLICA, "reg ss_stack_frozen; initial ss_stack_frozen = 1'b0;")

    stack_block = stack_write("ss_stack_frozen")
    insert = "\n`ifdef MK2\n" + stack_block + "\n`endif"
    wrapped_restore = "`ifndef MK2\n" + ref.RESTORE + "\n`endif"
    candidate = original.replace(freeze.FREEZE_BLOCK, freeze.FREEZE_BLOCK + "\n" + REPLICA, 1)
    candidate = candidate.replace(ref.PUSH + "\n", "", 1)
    candidate = candidate.replace(ref.RESTORE, wrapped_restore, 1)
    candidate = candidate.replace(ref.WRITE_INDEX, ref.WRITE_INDEX + insert, 1)

    recovered = candidate.replace(freeze.FREEZE_BLOCK + "\n" + REPLICA, freeze.FREEZE_BLOCK, 1)
    recovered = recovered.replace(ref.WRITE_INDEX + insert, ref.WRITE_INDEX, 1)
    recovered = recovered.replace(wrapped_restore, ref.RESTORE, 1)
    recovered = recovered.replace(push_context.replace(ref.PUSH + "\n", ""), push_context, 1)
    if recovered != original:
        raise SystemExit("Source outside the stack writes and freeze replica changed")
    for defines in ({"MK3"}, {"MK3", "DEBUG"}, set(), {"DEBUG"}):
        before = re.sub(r"\s+", "", ref.without_comments(ref.configured(original, defines)))
        after = re.sub(r"\s+", "", ref.without_comments(ref.configured(candidate, defines)))
        if before != after:
            raise SystemExit(f"Non-MkII source changed under {sorted(defines)}")

    # With the separately proved equality invariant, all 176 storage D/Q bits
    # and both reads must match for every binary common state and input.
    gold_write = stack_write("ss_frozen")
    gate_write = stack_block.replace("ss_stack_frozen", "ss_frozen")
    gold_stack = ref.model(ref.DECL, gold_write, "stack[ss_stk_idx]", PROOF_RETURN, False)
    gate_stack = ref.model(ref.DECL, gate_write, "stack[ss_stk_idx]", PROOF_RETURN, False)
    bad_data = gate_stack.replace("stack[ss_wstk_idx][7:0]  <= ss_wd;",
                                  "stack[ss_wstk_idx][7:0]  <= ss_wd ^ 8'h01;", 1)
    bad_freeze = gate_stack.replace("if(RST & ~ss_frozen)", "if(RST)", 1)
    bad_wrap = gate_stack.replace(PROOF_RETURN, "stack[regs_sp-4'd1]", 1)
    if any(mutant == gate_stack for mutant in (bad_data, bad_freeze, bad_wrap)):
        raise SystemExit("A stack negative control was not generated")

    original_init = re.search(r"initial ss_frozen = ([^;]+);", original).group(1)
    replica_init = re.search(r"initial ss_stack_frozen = ([^;]+);", REPLICA).group(1)
    gold_freeze = freeze_model("gold", freeze.comb_original(), original_init)
    gate_freeze = freeze_model("gate", replica_projection(REPLICA), replica_init)
    bad_reset = gate_freeze.replace("if(~RST | ~ss_halt_eff)", "if(~RST & ~ss_halt_eff)", 1)
    bad_boundary = gate_freeze.replace("(ss_boundary | (&ss_wait))", "(ss_boundary & (&ss_wait))", 1)
    bad_init = gate_freeze.replace("assign initial_frozen = 1'b0;", "assign initial_frozen = 1'b1;", 1)
    if any(mutant == gate_freeze for mutant in (bad_reset, bad_boundary, bad_init)):
        raise SystemExit("A freeze negative control was not generated")

    files = {
        "original-upd77c25.v": original, "candidate-upd77c25.v": candidate,
        "stack-gold.v": gold_stack, "stack-gate.v": gate_stack,
        "stack-bad-data.v": bad_data, "stack-bad-freeze.v": bad_freeze,
        "stack-bad-wrap.v": bad_wrap, "freeze-gold.v": gold_freeze,
        "freeze-gate.v": gate_freeze, "freeze-bad-reset.v": bad_reset,
        "freeze-bad-boundary.v": bad_boundary, "freeze-bad-init.v": bad_init,
    }
    output.mkdir(parents=True, exist_ok=True)
    checksums = []
    for name, content in files.items():
        data = content.encode("utf-8")
        (output / name).write_bytes(data)
        checksums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-upd77c25.v", "candidate-upd77c25.v")), encoding="utf-8")
    print(f"Pinned DSP blob {blob}; all original stack references and parent guards audited.")
    print("Original source recovered exactly; four non-MkII configurations unchanged.")
    print("Prepared all 176 stack bits, two reads, freeze invariant and six negative controls.")
    print("Native return-read source stays byte-identical; proof-only X preserves the SP=0 bound.")


if __name__ == "__main__":
    main()
