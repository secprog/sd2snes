#!/usr/bin/env python3
"""Generate a pinned MkII-only stack banking experiment and exact state models.

Run only on the hosted runner. The repository's production RTL is not edited.
"""

import difflib
import hashlib
import re
import sys
from pathlib import Path


EXPECTED_BLOB = "ba14f5b6dd198fbb5645f005fb3784890beec2c4"
DECL = "reg [10:0] stack [15:0];"
PUSH = "    if(push_now) stack[regs_sp] <= pc + 1;"
OTHER_PUSH = "                stack[regs_sp] <= pc + 1;"
SCAN_READ = "wire [10:0] ss_stk  = stack[ss_stk_idx];"
RETURN = "              pc <= stack[regs_sp-1];"
RESTORE = """        if(ss_wa[0]) stack[ss_wstk_idx][10:8] <= ss_wd[2:0];
        else         stack[ss_wstk_idx][7:0]  <= ss_wd;"""
SCAN_INDEX = "wire [3:0] ss_stk_idx = (DP_ADDR[7:0] - 8'h34) >> 1;"
WRITE_INDEX = "wire [3:0] ss_wstk_idx = (ss_wa - 8'h34) >> 1;"
BANK_DECL = """reg [7:0] stack_low [15:0];
reg [2:0] stack_high [15:0];"""
BANK_WRITE = """// The same CALL/restore writes, with one write address per byte lane.
// No clocked control or read-output stages are added.
wire stack_push = RST & ~ss_frozen & push_now;
wire stack_restore = RST & ss_frozen & ss_wr
    & (ss_wa >= 8'h34 && ss_wa <= 8'h53);
wire [3:0] stack_waddr = stack_push ? regs_sp : ss_wstk_idx;
wire [10:0] stack_push_data = pc + 1;
wire [10:0] stack_wdata = stack_push ? stack_push_data : {ss_wd[2:0], ss_wd};
wire stack_low_we = stack_push | (stack_restore & ~ss_wa[0]);
wire stack_high_we = stack_push | (stack_restore & ss_wa[0]);
always @(posedge CLK) begin
  if(stack_low_we) stack_low[stack_waddr] <= stack_wdata[7:0];
  if(stack_high_we) stack_high[stack_waddr] <= stack_wdata[10:8];
end"""
BANK_SCAN = "{stack_high[ss_stk_idx], stack_low[ss_stk_idx]}"
# Keep the original unsized subtraction: in particular, do not wrap SP=0 to 15.
BANK_RETURN = "{stack_high[regs_sp-1], stack_low[regs_sp-1]}"
PORTS = """module stack_model(
  input CLK, RST, ss_frozen, push_now, ss_wr,
  input [10:0] pc, DP_ADDR,
  input [3:0] regs_sp,
  input [7:0] ss_wa, ss_wd,
  output [10:0] scan_read, return_read,
  output [175:0] state
);
"""


def without_comments(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def configured(text, defines):
    """Resolve only the pinned file's known ifdef forms for the non-MkII audit."""
    active, parents, output = True, [], []
    for line in text.splitlines(True):
        directive = re.fullmatch(r"\s*`(ifdef|ifndef)\s+(\w+)\s*", line)
        if directive:
            kind, macro = directive.groups()
            if macro not in {"MK2", "MK3", "DEBUG"}:
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


def model(declaration, write, scan_read, return_read, banked):
    state = []
    for word in range(16):
        value = f"{{stack_high[{word}], stack_low[{word}]}}" if banked else f"stack[{word}]"
        state.append(f"assign state[{word * 11} +: 11] = {value};\n")
    return (PORTS + declaration + "\n" + SCAN_INDEX + "\n" + WRITE_INDEX + "\n"
            + write + "\n" + f"assign scan_read = {scan_read};\n"
            + f"assign return_read = {return_read};\n" + "".join(state) + "endmodule\n")


def main():
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != EXPECTED_BLOB:
        raise SystemExit(f"Unexpected DSP source blob: {blob}")
    original = raw.decode("utf-8")
    fragments = (DECL, PUSH, OTHER_PUSH, SCAN_READ, RETURN, RESTORE, SCAN_INDEX, WRITE_INDEX)
    for fragment in fragments:
        if original.count(fragment) != 1:
            raise SystemExit(f"Stack access boundary changed: {fragment}")
    remainder = original
    for fragment in fragments:
        remainder = remainder.replace(fragment, "")
    if re.search(r"\bstack\b", without_comments(remainder)):
        raise SystemExit("Unmodelled stack access, initializer or reset")

    # Validate the source control context, not merely the isolated assignments.
    push_context = ("always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n"
                    "`ifdef MK2\n    push_now <= 1'b0;\n" + PUSH + "\n`endif\n")
    if original.count(push_context) != 1:
        raise SystemExit("The MkII CALL clock/enable/priority context changed")
    restore_context = re.search(
        r"  end else if\(RST & ss_frozen\) begin\n"
        r"    // savestate RESTORE.*?\n    if\(ss_wr\) begin\n"
        r"      if\(ss_wa >= 8'h34 && ss_wa <= 8'h53\) begin\n"
        + re.escape(RESTORE) + r"\n      end else case\(ss_wa\)", original, flags=re.S)
    if not restore_context:
        raise SystemExit("The stack restore clock/enable/range/priority context changed")
    if original.count("`ifndef MK2\n" + OTHER_PUSH + "\n`endif") != 1:
        raise SystemExit("The non-MkII CALL write boundary changed")

    candidate = original.replace(DECL, "`ifdef MK2\n" + BANK_DECL + "\n`else\n" + DECL + "\n`endif")
    candidate = candidate.replace(PUSH + "\n", "")
    candidate = candidate.replace(
        SCAN_READ, "`ifdef MK2\nwire [10:0] ss_stk = " + BANK_SCAN + ";\n`else\n" + SCAN_READ + "\n`endif")
    candidate = candidate.replace(
        RETURN, "`ifdef MK2\n              pc <= " + BANK_RETURN + ";\n`else\n" + RETURN + "\n`endif")
    candidate = candidate.replace(RESTORE, "`ifndef MK2\n" + RESTORE + "\n`endif")
    candidate = candidate.replace(WRITE_INDEX, WRITE_INDEX + "\n`ifdef MK2\n" + BANK_WRITE + "\n`endif")

    # The entire non-MkII source must remain identical after branch selection,
    # apart from comments/whitespace. No inference about untouched paths is used.
    for defines in ({"MK3"}, {"MK3", "DEBUG"}, set(), {"DEBUG"}):
        before = re.sub(r"\s+", "", without_comments(configured(original, defines)))
        after = re.sub(r"\s+", "", without_comments(configured(candidate, defines)))
        if before != after:
            raise SystemExit(f"Non-MkII source changed under {sorted(defines)}")

    # Exact original assignments and their validated parent conditions.
    gold_write = ("always @(posedge CLK) begin\n"
                  "  if(RST & ~ss_frozen) begin\n" + PUSH + "\n"
                  "  end else if(RST & ss_frozen) begin\n"
                  "    if(ss_wr) begin\n"
                  "      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n"
                  + RESTORE + "\n      end\n    end\n  end\nend")
    gold = model(DECL, gold_write, "stack[ss_stk_idx]", "stack[regs_sp-1]", False)
    gate = model(BANK_DECL, BANK_WRITE, BANK_SCAN, BANK_RETURN, True)
    bad_data = gate.replace("<= stack_wdata[7:0];", "<= stack_wdata[7:0] ^ 8'h01;", 1)
    bad_freeze = gate.replace("RST & ~ss_frozen & push_now", "RST & push_now", 1)
    bad_wrap = gate.replace("regs_sp-1", "regs_sp-4'd1")
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
    print("Non-MkII source unchanged in all four audited configurations.")
    print("Generated runner-only candidate; all 176 state bits, two reads and three negative controls.")


if __name__ == "__main__":
    main()
