#!/usr/bin/env python3
"""Prepare a hosted-only late-low-address stack decoder feasibility proof.

Never execute locally. The previous KEEP native candidate remains rejected.
All source, state, X, input, mapping and native timing gates remain mandatory.
"""

import difflib
import hashlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "reference", Path(__file__).with_name("prepare-dsp-stack-experiment.py"))
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)

HELPERS = """// Preserve both original procedural ancestor guards, including X handling.
(* LUT_MAP="yes" *)
module dsp_stack_run_permit(input reset_n, frozen, output reg permit);
always @* begin
  permit = 1'b0;
  if (reset_n & ~frozen) permit = 1'b1;
end
endmodule

(* LUT_MAP="yes" *)
module dsp_stack_restore_permit(input reset_n, frozen, output reg permit);
always @* begin
  permit = 1'b0;
  if (reset_n & ~frozen) begin
  end else if (reset_n & frozen) permit = 1'b1;
end
endmodule

// Byte lane and word qualification precede this four-input final gate.
(* LUT_MAP="yes" *)
module dsp_stack_late_join(
  input run_permit, push_selected, restore_permit, restore_selected,
  output write
);
assign write = (run_permit & push_selected) | (restore_permit & restore_selected);
endmodule

// Upper address bits and the strobe are qualified before the low bits.
module dsp_stack_restore_prefix #(parameter [4:0] UPPER = 5'd6)(
  input ss_wr, input [4:0] addr_hi, output reg selected
);
always @* begin
  selected = 1'b0;
  if (ss_wr) begin
    if (addr_hi == UPPER) selected = 1'b1;
  end
end
endmodule

// Four real inputs: one shared prefix and the three late address bits.
(* LUT_MAP="yes" *)
module dsp_stack_restore_suffix #(parameter [2:0] VALUE = 3'd0)(
  input prefix, input [2:0] addr_lo, output reg selected
);
always @* begin
  selected = 1'b0;
  if (prefix) begin
    if (addr_lo == VALUE) selected = 1'b1;
  end
end
endmodule

module dsp_stack_early_select #(parameter [3:0] WORD = 4'd0)(
  input push_now, restore_prefix, input [3:0] regs_sp,
  input [2:0] addr_lo,
  output reg push_selected, output restore_low, restore_high
);
localparam [7:0] LOW_ADDR = 8'h34 + {3'b0, WORD, 1'b0};
localparam [7:0] HIGH_ADDR = LOW_ADDR + 8'd1;
always @* begin
  push_selected = 1'b0;
  if (push_now) begin
    if (regs_sp == WORD) push_selected = 1'b1;
  end
end
dsp_stack_restore_suffix #(.VALUE(LOW_ADDR[2:0])) low_lane(
  .prefix(restore_prefix), .addr_lo(addr_lo), .selected(restore_low)
);
dsp_stack_restore_suffix #(.VALUE(HIGH_ADDR[2:0])) high_lane(
  .prefix(restore_prefix), .addr_lo(addr_lo), .selected(restore_high)
);
endmodule
"""
PROOF_RETURN = "(regs_sp == 4'd0) ? 11'bx : stack[regs_sp-1]"


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"Ambiguous replacement: {old!r}")
    return text.replace(old, new, 1)


def scoped(text):
    return "`ifdef MK2\n`ifdef DSP_COMP\n" + text + "\n`endif\n`endif"


def normalize(text):
    return re.sub(r"\s+", "", ref.without_comments(text))


def writes():
    lines = [
        '(* KEEP="TRUE" *) wire stack_late_run, stack_late_restore;',
        '(* KEEP="TRUE" *) wire [15:0] stack_early_push, stack_early_low, stack_early_high;',
        '(* KEEP="TRUE" *) wire [4:0] stack_restore_prefix;',
        "wire [15:0] stack_late_low, stack_late_high;",
        "wire [10:0] stack_late_push_data = pc + 1;",
        "wire [10:0] stack_late_data = stack_late_run ? stack_late_push_data : {ss_wd[2:0], ss_wd};",
        "dsp_stack_run_permit run_permit(.reset_n(RST), .frozen(ss_frozen), .permit(stack_late_run));",
        "dsp_stack_restore_permit restore_permit(.reset_n(RST), .frozen(ss_frozen), .permit(stack_late_restore));",
    ]
    for group in range(5):
        lines += [
            f"dsp_stack_restore_prefix #(.UPPER(5'd{6 + group})) restore_prefix_{group}(",
            "  .ss_wr(ss_wr), .addr_hi(ss_wa[7:3]),",
            f"  .selected(stack_restore_prefix[{group}])",
            ");",
        ]
    for word in range(16):
        lines += [
            f"dsp_stack_early_select #(.WORD(4'd{word})) early_select_{word}(",
            "  .push_now(push_now), .regs_sp(regs_sp), .addr_lo(ss_wa[2:0]),",
            f"  .restore_prefix(stack_restore_prefix[{((0x34 + 2 * word) >> 3) - 6}]),",
            f"  .push_selected(stack_early_push[{word}]),",
            f"  .restore_low(stack_early_low[{word}]), .restore_high(stack_early_high[{word}])",
            ");",
        ]
        for lane in ("low", "high"):
            lines += [
                f"dsp_stack_late_join late_{lane}_{word}(",
                f"  .run_permit(stack_late_run), .push_selected(stack_early_push[{word}]),",
                f"  .restore_permit(stack_late_restore), .restore_selected(stack_early_{lane}[{word}]),",
                f"  .write(stack_late_{lane}[{word}])",
                ");",
            ]
        lines += [
            "always @(posedge CLK) begin",
            f"  if (stack_late_low[{word}]) stack[{word}][7:0] <= stack_late_data[7:0];",
            f"  if (stack_late_high[{word}]) stack[{word}][10:8] <= stack_late_data[10:8];",
            "end",
        ]
    return "\n".join(lines) + "\n"


def main():
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    if blob(raw) != ref.EXPECTED_BLOB:
        raise SystemExit("Original complete DSP source pin changed")
    original = raw.decode("utf-8")
    headers = {
        "dsp": (source.parent / "config.vh", "1a9a6a14b8b08eb6e931ce2320326e913aa8000e"),
        "dspx": (source.parent.parent / "sd2snes_dspx" / "config.vh", "4cf8aa3111a5bf103065cded5fb77fdfc39ee239"),
    }
    for path, expected in headers.values():
        if blob(path.read_bytes()) != expected:
            raise SystemExit("Actual preprocessing header pin changed")
    if original.count('`include "config.vh"') != 1:
        raise SystemExit("Unexpected source include boundary")
    fragments = (ref.DECL, ref.PUSH, ref.OTHER_PUSH, ref.SCAN_READ,
                 ref.RETURN, ref.RESTORE, ref.SCAN_INDEX, ref.WRITE_INDEX)
    remainder = original
    for fragment in fragments:
        remainder = once(remainder, fragment, "")
    if re.search(r"\bstack\b", ref.without_comments(remainder)):
        raise SystemExit("Unmodelled stack access, declaration or initialization")
    if re.search(r"\b(?:stack_late_|stack_early_|stack_restore_|dsp_stack_)", original):
        raise SystemExit("New identifiers collide with the original source")
    push_context = ("always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n"
                    "`ifdef MK2\n    push_now <= 1'b0;\n" + ref.PUSH + "\n`endif\n")
    if original.count(push_context) != 1:
        raise SystemExit("Original CALL clock, ancestors or priority changed")
    restore_context = re.search(
        r"  end else if\(RST & ss_frozen\) begin\n"
        r"    // savestate RESTORE.*?\n    if\(ss_wr\) begin\n"
        r"      if\(ss_wa >= 8'h34 && ss_wa <= 8'h53\) begin\n"
        + re.escape(ref.RESTORE) + r"\n      end else case\(ss_wa\)", original, flags=re.S)
    if not restore_context:
        raise SystemExit("Original restore clock, ancestors or priority changed")
    if original.count("`ifndef MK2\n" + ref.OTHER_PUSH + "\n`endif") != 1:
        raise SystemExit("Non-MkII CALL boundary changed")

    write = writes()
    # Retain the original two writes verbatim in every non-target configuration.
    push = "`ifdef DSP_COMP\n    // Target stack writes are below.\n`else\n" + ref.PUSH + "\n`endif"
    restore = ("`ifdef MK2\n`ifdef DSP_COMP\n        // Target stack writes are below.\n"
               "`else\n" + ref.RESTORE + "\n`endif\n`else\n" + ref.RESTORE + "\n`endif")
    index = ref.WRITE_INDEX + "\n" + scoped(write)
    suffix = "\n" + scoped(HELPERS) + "\n"
    candidate = once(original, ref.PUSH, push)
    candidate = once(candidate, ref.RESTORE, restore)
    candidate = once(candidate, ref.WRITE_INDEX, index) + suffix
    if blob(candidate.encode()) != "80050b8015d47cbf4eb25c6fd8c14aa78c378790" or hashlib.sha256(candidate.encode()).hexdigest() != "b536c4ab74015b76751d0544e48cce23a458b70b2e0e34f101bdd18421907d4a":
        raise SystemExit("Complete candidate differs from independently prepared source pin")
    recovered = candidate.removesuffix(suffix)
    recovered = once(recovered, index, ref.WRITE_INDEX)
    recovered = once(recovered, restore, ref.RESTORE)
    recovered = once(recovered, push, ref.PUSH)
    if recovered != original or ref.RETURN not in candidate:
        raise SystemExit("Complete original source inverse or unchanged native return failed")

    gold_write = """always @(posedge CLK) begin
  if(RST & ~ss_frozen) begin
""" + ref.PUSH + """
  end else if(RST & ss_frozen) begin
    if(ss_wr) begin
      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin
""" + ref.RESTORE + """
      end
    end
  end
end"""
    # Explicit SP=0 X is proof-only in BOTH models; native expression is untouched.
    gold = ref.model(ref.DECL, gold_write, "stack[ss_stk_idx]", PROOF_RETURN, False)
    gate = ref.model(ref.DECL, write, "stack[ss_stk_idx]", PROOF_RETURN, False) + HELPERS
    mutants = {
        "bad-data": ("stack[0][7:0] <= stack_late_data[7:0];", "stack[0][7:0] <= stack_late_data[7:0] ^ 8'h01;"),
        "bad-run": ("if (reset_n & ~frozen) permit = 1'b1;", "if (reset_n) permit = 1'b1;"),
        "bad-restore": ("else if (reset_n & frozen) permit = 1'b1;", "else if (reset_n & ~frozen) permit = 1'b1;"),
        "bad-reset": ("if (reset_n & ~frozen) permit = 1'b1;", "if (~frozen) permit = 1'b1;"),
        "bad-push": ("if (push_now) begin", "if (1'b1) begin"),
        "bad-strobe": ("if (ss_wr) begin", "if (1'b1) begin"),
        "bad-lane": ("#(.VALUE(LOW_ADDR[2:0])) low_lane", "#(.VALUE(HIGH_ADDR[2:0])) low_lane"),
        "bad-prefix": ("#(.UPPER(5'd6)) restore_prefix_0", "#(.UPPER(5'd7)) restore_prefix_0"),
        "bad-word": ("#(.WORD(4'd0)) early_select_0", "#(.WORD(4'd1)) early_select_0"),
        "bad-return": (PROOF_RETURN, "stack[regs_sp-4'd1]"),
        "bad-x-call-data": ("stack_late_push_data = pc + 1;", "stack_late_push_data = (pc + 1) ^ {11{ss_wa[0] ^ ss_wa[0]}};"),
        "bad-x-restore-data": (" : {ss_wd[2:0], ss_wd};", " : ({ss_wd[2:0], ss_wd} ^ {11{pc[0] ^ pc[0]}});"),
        # The first casex control lowered to exact $eqx under proc -ifx.
        # A strict !==0 guard deliberately writes on an unknown comparison.
        "bad-x-address": (
            """always @* begin
  selected = 1'b0;
  if (prefix) begin
    if (addr_lo == VALUE) selected = 1'b1;
  end
end""",
            """always @* begin
  selected = 1'b0;
  if (prefix) begin
    if ((addr_lo == VALUE) !== 1'b0) selected = 1'b1;
  end
end""",
        ),
        "bad-x-write-mask": ("assign write = (run_permit & push_selected) | (restore_permit & restore_selected);", "assign write = ((run_permit & push_selected) | (restore_permit & restore_selected)) ^ (ss_unused ^ ss_unused);"),
    }
    files = {"original-upd77c25.v": original, "candidate-upd77c25.v": candidate,
             "gold.v": gold, "gate.v": gate}
    for name, (before, after) in mutants.items():
        if name == "bad-x-write-mask":
            # Route an existing arbitrary data bit through the mutated helper.
            mutant = gate.replace("input run_permit, push_selected, restore_permit, restore_selected,",
                                  "input run_permit, push_selected, restore_permit, restore_selected, ss_unused,")
            mutant = mutant.replace("  .run_permit(stack_late_run),", "  .ss_unused(ss_wd[0]), .run_permit(stack_late_run),")
            if mutant.count(".ss_unused(ss_wd[0])") != 32:
                raise SystemExit("X-mask control did not bind every actual final helper")
            files[name + ".v"] = once(mutant, before, after)
        else:
            files[name + ".v"] = once(gate, before, after)
    output.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (output / name).write_text(text, encoding="utf-8")
    for name, (path, _) in headers.items():
        (output / f"original-{name}-config.vh").write_bytes(path.read_bytes())

    configurations = (
        ("none", []), ("debug", ["DEBUG"]), ("mk3", ["MK3"]),
        ("mk3-debug", ["MK3", "DEBUG"]), ("mk2", ["MK2"]),
        ("mk2-debug", ["MK2", "DEBUG"]), ("dsp", ["DSP_COMP"]),
        ("dsp-debug", ["DSP_COMP", "DEBUG"]), ("mk3-dsp", ["MK3", "DSP_COMP"]),
        ("mk3-dsp-debug", ["MK3", "DSP_COMP", "DEBUG"]),
        ("mk2-dsp", ["MK2", "DSP_COMP"]), ("mk2-dsp-debug", ["MK2", "DSP_COMP", "DEBUG"]),
    )
    audit = []
    for name, defines in configurations:
        target = "MK2" in defines and "DSP_COMP" in defines
        header, header_blob = headers["dspx" if target else "dsp"]
        selected = []
        for version in ("original", "candidate"):
            dest = output / f"pp-{name}-{version}.v"
            subprocess.run(["iverilog", "-g2012", "-E", "-I", str(header.parent.resolve())]
                           + ["-D" + d for d in defines]
                           + ["-o", str(dest), str(output / f"{version}-upd77c25.v")], check=True)
            selected.append(dest.read_text(encoding="utf-8"))
        if not all(text.strip() for text in selected):
            raise SystemExit("Empty preprocessing output")
        if not target and normalize(selected[0]) != normalize(selected[1]):
            raise SystemExit(f"Non-target configuration changed: {name}")
        if target:
            if selected[1].count(write) != 1 or selected[1].count(HELPERS) != 1:
                raise SystemExit("Incorrect target selection")
            after = selected[1].replace(write, "", 1).replace(HELPERS, "", 1)
            before = once(once(selected[0], ref.PUSH, ""), ref.RESTORE, "")
            if normalize(after) != normalize(before):
                raise SystemExit("Target preprocessing changed more than the two stack writes")
        audit.append(f"{name}: {'target replacements verified' if target else 'non-target token identity'}; header {header_blob}\n")
    (output / "preprocessing.txt").write_text("".join(audit), encoding="utf-8")
    (output / "candidate.diff").write_text("".join(difflib.unified_diff(
        original.splitlines(True), candidate.splitlines(True), "original-upd77c25.v", "candidate-upd77c25.v")), encoding="utf-8")
    (output / "late-low-generator.py.txt").write_bytes(Path(__file__).read_bytes())
    (output / "late-low-audit.txt").write_text("Evidence: rejected KEEP native run40973904498 reports ss_wa2/1 to stack9_7 through two early decoder LUTs and the final CE LUT.\nHypothesis: keep five upper-address/strobe prefixes; each restore lane then uses only prefix plus ss_wa[2:0] in a LUT_MAP module before the original kept final join.\nNo new clock, state, cycle, data or read expression; ten non-target and two actual target preprocessing configurations remain mandatory.\nHigh address and strobe paths may gain depth; capacity, recognition, actual pin/mux mapping, routing and all endpoint timing remain unproved.\nThis differs from rejected original-guard case decoding: no dynamic write-index or full-range comparator in the target early restore helper, with explicit kept prefix and four-input suffix boundaries.\nAll rejected trials remain rejected. No PAR/TRACE dispatch is authorized by this proof workflow.\nStrict all176 next-state/both-read binary and unrestricted-X proofs, sixteen actual Q/D state audits, swapped-Q and ten binary/four binary-equivalent-X negative controls are mandatory.\nAll tracked SHA/index and staged inputs must remain exact. Native input/PCF480ps/PAR0/TRACE0/integration gates remain mandatory for any later consideration.\nAMD UG627 pp72-74,245-247,298,345-346; Yosys0.33 proc -ifx -noopt and strict miter/sat semantics.\n", encoding="utf-8")
    (output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(output.iterdir()) if path.is_file() and path.name != "SHA256SUMS"), encoding="utf-8")
    print(f"Pinned original blob {blob(raw)}; runner-only candidate blob {blob(candidate.encode())}.")
    print("Exact inverse, unchanged native return and actual preprocessing: ten non-target/two target configurations.")
    print("Unchanged 176 stack state bits and both reads; shared upper-address/strobe prefixes and four-input late low-address qualifiers.")
    print("Feasibility proof only: no native mapping, timing, generated-input integrity or hardware result implied.")


if __name__ == "__main__":
    main()
