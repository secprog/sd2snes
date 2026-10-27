#!/usr/bin/env python3
"""Prepare a source-pinned, runner-only stack write predecode experiment."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


def load_reference():
    spec = importlib.util.spec_from_file_location(
        "stack_reference", Path(__file__).with_name("prepare-dsp-stack-experiment.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ref = load_reference()
WRITE_CAPTURE = """reg       ss_wr; initial ss_wr = 1'b0;
reg [7:0] ss_wa;
reg [7:0] ss_wd;
always @(posedge CLK) begin
  ss_wr <= ss_regwin & reg_we_rising;
  ss_wa <= DP_ADDR[7:0];
  ss_wd <= DI;
end"""
SELECTOR_INIT = "16'h0000"
PROOF_RETURN = "(regs_sp == 4'd0) ? 11'bx : stack[regs_sp-1]"


def unique(text, fragment):
    if text.count(fragment) != 1:
        raise SystemExit(f"Expected exactly one source fragment: {fragment!r}")


def selector_expr(address, write, word):
    return f"({write}) & ({address}[7:1] == 7'h{0x1a + word:02x})"


def selector_block():
    lines = ["// Diagnostic only: predecode the already registered restore transaction.",
             f"reg [15:0] ss_stack_sel = {SELECTOR_INIT};",
             "always @(posedge CLK) begin"]
    for word in range(16):
        value = selector_expr("DP_ADDR", "ss_regwin & reg_we_rising", word)
        lines.append(f"  ss_stack_sel[{word}] <= {value};")
    lines.append("end")
    return "\n".join(lines)


def stack_block():
    lines = ["// Diagnostic only: the original CALL/restore writes, per word."]
    for word in range(16):
        lines += [
            "always @(posedge CLK) begin",
            f"  if(RST & ~ss_frozen & push_now & (regs_sp == 4'd{word}))",
            f"    stack[{word}] <= pc + 1;",
            f"  else if(RST & ss_frozen & ss_stack_sel[{word}]) begin",
            f"    if(ss_wa[0]) stack[{word}][10:8] <= ss_wd[2:0];",
            f"    else stack[{word}][7:0] <= ss_wd;",
            "  end",
            "end",
        ]
    return "\n".join(lines)


def selector_models(original, new_selector):
    wr_match = re.search(r"(?m)^\s*ss_wr <= ([^;]+);", original)
    wa_match = re.search(r"(?m)^\s*ss_wa <= ([^;]+);", original)
    init_match = re.search(r"initial ss_wr = ([^;]+);", original)
    sel_init = re.search(r"reg \[15:0\] ss_stack_sel = ([^;]+);", new_selector)
    if not all((wr_match, wa_match, init_match, sel_init)):
        raise SystemExit("Missing source-derived write/selector initialization or transition")
    candidate_next = []
    for word in range(16):
        match = re.search(rf"(?m)^\s*ss_stack_sel\[{word}\] <= ([^;]+);", new_selector)
        if not match:
            raise SystemExit(f"Missing selector update for {word}")
        candidate_next.append(match.group(1))
    ports = """(input ss_regwin, reg_we_rising, input [10:0] DP_ADDR,
  input [7:0] initial_wa, output [15:0] next_sel, initial_sel);
"""
    gold = "module gold" + ports
    gold += f"wire next_wr = {wr_match.group(1)};\nwire [7:0] next_wa = {wa_match.group(1)};\n"
    for word in range(16):
        gold += (f"assign next_sel[{word}] = " + selector_expr("next_wa", "next_wr", word) + ";\n")
        gold += (f"assign initial_sel[{word}] = "
                 + selector_expr("initial_wa", init_match.group(1), word) + ";\n")
    gold += "endmodule\n"
    gate = "module gate" + ports
    gate += f"assign initial_sel = {sel_init.group(1)};\n"
    for word, expr in enumerate(candidate_next):
        gate += f"assign next_sel[{word}] = {expr};\n"
    gate += "endmodule\n"
    return gold, gate


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-stack-predecode-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != ref.EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete DSP source blob: {blob}")
    original = raw.decode("utf-8")
    fragments = (ref.DECL, ref.PUSH, ref.OTHER_PUSH, ref.SCAN_READ, ref.RETURN,
                 ref.RESTORE, ref.SCAN_INDEX, ref.WRITE_INDEX, WRITE_CAPTURE)
    for fragment in fragments:
        unique(original, fragment)
    remainder = original
    for fragment in fragments:
        remainder = remainder.replace(fragment, "")
    if re.search(r"\bstack\b", ref.without_comments(remainder)):
        raise SystemExit("Unmodelled stack access, reset or initialization")
    if re.search(r"\bss_stack_sel\b", ref.without_comments(original)):
        raise SystemExit("Selector identifier already exists")
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

    selectors = selector_block()
    writes = stack_block()
    new_capture = WRITE_CAPTURE + "\n" + selectors
    insert = "\n`ifdef MK2\n" + writes + "\n`endif"
    wrapped_restore = "`ifndef MK2\n" + ref.RESTORE + "\n`endif"
    candidate = original.replace(WRITE_CAPTURE, new_capture, 1)
    candidate = candidate.replace(ref.PUSH + "\n", "", 1)
    candidate = candidate.replace(ref.RESTORE, wrapped_restore, 1)
    candidate = candidate.replace(ref.WRITE_INDEX, ref.WRITE_INDEX + insert, 1)

    recovered = candidate.replace(new_capture, WRITE_CAPTURE, 1)
    recovered = recovered.replace(ref.WRITE_INDEX + insert, ref.WRITE_INDEX, 1)
    recovered = recovered.replace(wrapped_restore, ref.RESTORE, 1)
    recovered = recovered.replace(push_context.replace(ref.PUSH + "\n", ""), push_context, 1)
    if recovered != original:
        raise SystemExit("Source outside the selector and stack writes changed")
    for defines in ({"MK3"}, {"MK3", "DEBUG"}, set(), {"DEBUG"}):
        before = re.sub(r"\s+", "", ref.without_comments(ref.configured(original, defines)))
        after = re.sub(r"\s+", "", ref.without_comments(ref.configured(candidate, defines)))
        if before != after:
            raise SystemExit(f"Non-MkII source changed under {sorted(defines)}")

    # The selector invariant is proved separately from the actual capture
    # expressions and explicit initial values, then substituted into the stack
    # boundary. Both models retain the proof-only original SP=0 read X.
    selector_gold, selector_gate = selector_models(original, selectors)
    projected_write = writes
    for word in range(16):
        target = f"ss_stack_sel[{word}]"
        unique(projected_write, target)
        projected_write = projected_write.replace(target, selector_expr("ss_wa", "ss_wr", word), 1)
    gold_write = ("always @(posedge CLK) begin\n"
                  "  if(RST & ~ss_frozen) begin\n" + ref.PUSH + "\n"
                  "  end else if(RST & ss_frozen) begin\n"
                  "    if(ss_wr) begin\n"
                  "      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n"
                  + ref.RESTORE + "\n      end\n    end\n  end\nend")
    gold_stack = ref.model(ref.DECL, gold_write, "stack[ss_stk_idx]", PROOF_RETURN, False)
    gate_stack = ref.model(ref.DECL, projected_write, "stack[ss_stk_idx]", PROOF_RETURN, False)
    mutants = {
        "stack-bad-data": (gate_stack, "stack[0][7:0] <= ss_wd;", "stack[0][7:0] <= ss_wd ^ 8'h01;"),
        "stack-bad-freeze": (gate_stack, "RST & ~ss_frozen & push_now", "RST & push_now"),
        "stack-bad-lane": (gate_stack, "if(ss_wa[0]) stack[0][10:8]", "if(~ss_wa[0]) stack[0][10:8]"),
        "stack-bad-wrap": (gate_stack, PROOF_RETURN, "stack[regs_sp-4'd1]"),
        "selector-bad-address": (selector_gate, "DP_ADDR[7:1] == 7'h1a", "DP_ADDR[7:1] == 7'h1b"),
        "selector-bad-enable": (selector_gate, "ss_regwin & reg_we_rising", "reg_we_rising"),
        "selector-bad-init": (selector_gate, "assign initial_sel = 16'h0000;", "assign initial_sel = 16'h0001;"),
    }
    files = {"original-upd77c25.v": original, "candidate-upd77c25.v": candidate,
             "stack-gold.v": gold_stack, "stack-gate.v": gate_stack,
             "selector-gold.v": selector_gold, "selector-gate.v": selector_gate}
    for name, (text, before, after) in mutants.items():
        if name == "stack-bad-freeze":
            if text.count(before) != 16:
                raise SystemExit("Expected one push freeze guard per word")
        elif name == "selector-bad-enable":
            if text.count(before) != 16:
                raise SystemExit("Expected one sampled enable per selector")
        else:
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
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-upd77c25.v", "candidate-upd77c25.v")), encoding="utf-8")
    print(f"Pinned DSP blob {blob}; exact source recovery and four non-MkII configurations audited.")
    print("Prepared selector init/transition invariant, 176 stack bits, both reads and seven negative controls.")
    print("Native return-read source unchanged; explicit proof-only X preserves the original SP=0 bound.")


if __name__ == "__main__":
    main()
