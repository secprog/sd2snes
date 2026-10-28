#!/usr/bin/env python3
"""Prepare a source-pinned, runner-only DSPx event-write decoder proof.

This does not modify the checkout or run an FPGA build.  In particular, the
address module and main.v use distinct address state before startup settles.
The generated proof checks that distinction rather than assuming equality.
"""

import difflib
import hashlib
import re
import sys
from pathlib import Path


BLOBS = {
    "main.v": "cc6889c4f00f653b0df19184ec8c7d726df9d2c9",
    "address.v": "45b2d274419eb5b1db0315ffb91b3862bb61a506",
}
UNLOCK = """wire cc_unlocked = map_unlock | snescmd_unlock
                 | map_Ex_rd_unlock | map_Ex_wr_unlock
                 | map_Fx_rd_unlock | map_Fx_wr_unlock;"""
SELECT = """assign cc_sel = ~cc_unlocked
              & (EV_CC92
                ? ((SNES_ADDR[23:20] == 4'hC) | (SNES_ADDR[23:20] == 4'hE))
                : EV_PF94
                ? (((SNES_ADDR[23:20] == 4'h1) | (SNES_ADDR[23:20] == 4'h2)
                   |(SNES_ADDR[23:20] == 4'h9) | (SNES_ADDR[23:20] == 4'hA))
                  & (SNES_ADDR[15:13] == 3'b011))
                : 1'b0);"""
FAST_SIMPLE = """assign cc_wr_hit_fast = ~cc_unlocked
              & (EV_CC92
                ? (SNES_ADDR[23:20] == 4'hE)
                : EV_PF94
                ? (((SNES_ADDR[23:20] == 4'h2) | (SNES_ADDR[23:20] == 4'hA))
                  & (SNES_ADDR[15:13] == 3'b011))
                : 1'b0);"""
# Retain the X-valued contribution of the status-bank term.  It is zero for
# binary address bits, but must not be dropped from the component X proof.
FAST = FAST_SIMPLE.replace(
    "                : 1'b0);",
    "                : 1'b0)\n              | (cc_sel & SNES_ADDR[21] & ~SNES_ADDR[21]);",
    1,
)
GUARD_OPEN = "`ifdef MK2\n`ifdef DSP_COMP\n`ifndef DSP_LEAN\n"
GUARD_CLOSE = "`endif\n`endif\n`endif\n"
PORT = "  output cc_sel,            // event cart select/status register window\n"
PORT_ADD = GUARD_OPEN + "  output cc_wr_hit_fast,\n" + GUARD_CLOSE
DECL = "wire cc_sel;\n"
DECL_ADD = GUARD_OPEN + "wire cc_wr_hit_fast;\n" + GUARD_CLOSE
CONNECT = "  .cc_sel(cc_sel),\n"
CONNECT_ADD = GUARD_OPEN + "  .cc_wr_hit_fast(cc_wr_hit_fast),\n" + GUARD_CLOSE
HIT = "wire cc_wr_hit = cc_sel & SNES_ADDR[21];"
HIT_REPLACEMENT = """`ifdef MK2
`ifdef DSP_COMP
wire cc_wr_hit = cc_wr_hit_fast;
`else
wire cc_wr_hit = cc_sel & SNES_ADDR[21];
`endif
`else
wire cc_wr_hit = cc_sel & SNES_ADDR[21];
`endif"""
SHIFT_INIT = "reg [7:0] SNES_WRITEr = 8'b11111111;"
SHIFT_UPDATE = "SNES_WRITEr <= {SNES_WRITEr[6:0], SNES_WRITE_IN};"
STROBE = "wire SNES_WR_end = (SNES_WRITEr[6:1] == 6'b000001);"
ADDR_DECL = "reg [23:0] SNES_ADDRr [6:0];"
MAIN_ADDR = "wire [23:0] SNES_ADDR = (SNES_ADDRr[5] & SNES_ADDRr[4]);"
EARLY = "reg  [23:0] SNES_ADDR_early; always @(posedge CLK2) SNES_ADDR_early <= (SNES_ADDRr[3] & SNES_ADDRr[2]);"
LOCAL_ADDR = "reg [23:0] SNES_ADDR; always @(posedge CLK) SNES_ADDR <= SNES_ADDR_early;"
WRITE_COND = "end else if(SNES_WR_end & cc_wr_hit) begin"
START_COND = "if(SNES_WR_end & cc_wr_hit & (SNES_DATA == 8'h09)) begin"


def unique(text, token):
    if text.count(token) != 1:
        raise SystemExit(f"Expected one source fragment: {token!r}")


def read_pinned(path):
    data = path.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if blob != BLOBS[path.name]:
        raise SystemExit(f"Unexpected {path.name} blob: {blob}")
    return data.decode("utf-8")


def configured(text, initial):
    """Resolve only the pinned files' known conditionals and local DSP_LEAN."""
    known = {"MK2", "MK3", "MK2_DEBUG", "DSP_COMP", "DSP_LEAN"}
    defines = set(initial)
    active, stack, output = True, [], []
    for line in text.splitlines(True):
        match = re.fullmatch(r"\s*`(ifdef|ifndef)\s+(\w+)\s*", line)
        if match:
            kind, macro = match.groups()
            if macro not in known:
                raise SystemExit(f"Unexpected condition: {macro}")
            cond = (macro in defines) == (kind == "ifdef")
            stack.append((active, cond))
            active = active and cond
        elif line.strip() == "`else":
            if not stack:
                raise SystemExit("Unmatched else")
            parent, cond = stack[-1]
            active = parent and not cond
        elif line.strip() == "`endif":
            if not stack:
                raise SystemExit("Unmatched endif")
            active, _ = stack.pop()
        elif re.fullmatch(r"\s*`define\s+DSP_LEAN\s*", line):
            if active:
                defines.add("DSP_LEAN")
        elif re.match(r"\s*`(?:elsif|undef)\b", line):
            raise SystemExit(f"Unexpected directive: {line.strip()}")
        elif active:
            output.append(line)
    if stack:
        raise SystemExit("Unbalanced conditionals")
    return "".join(output)


def boundary_model(name, variant, alignment, fast_assignment=FAST):
    # In aligned mode main's bit is the same actual 3-valued address bit.
    # Quiet mode leaves the two address states independent and forces only
    # the startup strobe to its separately proved value of zero.
    if alignment not in ("aligned", "quiet", "unaligned"):
        raise SystemExit("Unknown projection")
    main_bit = "SNES_ADDR[21]" if alignment == "aligned" else "main_addr21"
    strobe = "1'b0" if alignment == "quiet" else "write_strobe"
    fast = fast_assignment.replace("assign cc_wr_hit_fast", "wire cc_wr_hit_fast", 1)
    hit = "cc_sel & main_addr_bit" if variant == "gold" else "cc_wr_hit_fast"
    return f"""module {name}(
  input [23:0] address_bits, input main_addr21, input [15:0] featurebits,
  input map_unlock, snescmd_unlock, map_Ex_rd_unlock, map_Ex_wr_unlock,
  input map_Fx_rd_unlock, map_Fx_wr_unlock, input write_strobe,
  input [7:0] SNES_DATA, output cc_sel_output, write_enable, timer_start
);
wire [23:0] SNES_ADDR = address_bits;
wire main_addr_bit = {main_bit};
wire EV_CC92 = featurebits[14];
wire EV_PF94 = featurebits[15];
wire cc_sel;
{UNLOCK}
{SELECT}
{fast}
wire cc_wr_hit = {hit};
wire SNES_WR_end = {strobe};
assign cc_sel_output = cc_sel;
assign write_enable = SNES_WR_end & cc_wr_hit;
assign timer_start = SNES_WR_end & cc_wr_hit & (SNES_DATA == 8'h09);
endmodule
"""


def pipeline_model(name):
    # These are direct 24-bit projections of the checked source assignments.
    # No initial value is imposed on address state.  The only initial value is
    # the actual initialized write shift register from main.v.
    return f"""module {name}(
  input [23:0] r2, r3, r4, r5, early_addr, local_addr,
  input SNES_WRITE_IN,
  output first_relation_ok, next_relation_ok, initial_quiet, first_quiet
);
wire [23:0] next_r3 = r2;
wire [23:0] next_r4 = r3;
wire [23:0] next_r5 = r4;
wire [23:0] next_early = (r3 & r2);
wire [23:0] next_local = early_addr;
wire [23:0] next_main = (next_r5 & next_r4);
wire pre_relation = (early_addr === (r4 & r3));
assign first_relation_ok = (next_early === (next_r4 & next_r3));
assign next_relation_ok = pre_relation ? (next_local === next_main) : 1'b1;
localparam [7:0] initial_write = 8'b11111111;
wire [7:0] first_write = {{initial_write[6:0], SNES_WRITE_IN}};
assign initial_quiet = ((initial_write[6:1] == 6'b000001) === 1'b0);
assign first_quiet = ((first_write[6:1] == 6'b000001) === 1'b0);
endmodule
"""


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-event-write-proof.py SOURCE_DIR OUTPUT_DIR")
    source_dir, output = map(Path, sys.argv[1:])
    unique(FAST_SIMPLE, "                : 1'b0);")
    if FAST == FAST_SIMPLE:
        raise SystemExit("X-sensitive status-bank correction was not added")
    main_source = read_pinned(source_dir / "main.v")
    address = read_pinned(source_dir / "address.v")
    for fragment in (PORT, UNLOCK, SELECT, LOCAL_ADDR, "  FEAT_CC92 = 14,",
                     "  FEAT_PF94 = 15", "wire EV_CC92 = featurebits[FEAT_CC92];",
                     "wire EV_PF94 = featurebits[FEAT_PF94];"):
        unique(address, fragment)
    for fragment in (DECL, CONNECT, HIT, SHIFT_INIT, SHIFT_UPDATE, STROBE,
                     ADDR_DECL, MAIN_ADDR, EARLY, WRITE_COND, START_COND):
        unique(main_source, fragment)
    unique(main_source, "address snes_addr(")
    instance = main_source.split("address snes_addr(", 1)[1].split("\n);", 1)[0]
    for fragment in ("  .CLK(CLK2),", "  .SNES_ADDR_early(SNES_ADDR_early),",
                     "  .featurebits(featurebits),", "  .cc_sel(cc_sel),",
                     "  .map_unlock(map_unlock),", "  .snescmd_unlock(snescmd_unlock),",
                     "  .map_Ex_rd_unlock(map_Ex_rd_unlock_r),",
                     "  .map_Ex_wr_unlock(map_Ex_wr_unlock_r),",
                     "  .map_Fx_rd_unlock(map_Fx_rd_unlock_r),",
                     "  .map_Fx_wr_unlock(map_Fx_wr_unlock_r),"):
        unique(instance, fragment)
    shift_start = "always @(posedge CLK2) begin\n  SNES_PULSEr <= {SNES_PULSEr[6:0], SNES_PULSE_IN};"
    unique(main_source, shift_start)
    shift_block = main_source.split(shift_start, 1)[1].split("\nend", 1)[0]
    unique(shift_block, SHIFT_UPDATE)
    for index in (3, 4, 5):
        update = f"SNES_ADDRr[{index}] <= SNES_ADDRr[{index - 1}];"
        unique(main_source, update)
        unique(shift_block, update)
    unique(main_source, "always @(posedge CLK2) begin\n  if(SNES_reset_strobe) begin\n    CC_DR <= 8'h00;\n  " + WRITE_COND)
    unique(main_source, "always @(posedge CLK2) begin\n  " + START_COND)
    clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", main_source, flags=re.S)
    if len(re.findall(r"\bcc_wr_hit\b", clean)) != 3:
        raise SystemExit("Unexpected event-write consumers")
    if "cc_wr_hit_fast" in main_source or "cc_wr_hit_fast" in address:
        raise SystemExit("Fast hit name already exists")

    new_address = address.replace(PORT, PORT + PORT_ADD, 1)
    new_address = new_address.replace(SELECT + "\n", SELECT + "\n" + GUARD_OPEN + FAST + "\n" + GUARD_CLOSE, 1)
    new_main = main_source.replace(DECL, DECL + DECL_ADD, 1)
    new_main = new_main.replace(CONNECT, CONNECT + CONNECT_ADD, 1)
    new_main = new_main.replace(HIT, HIT_REPLACEMENT, 1)
    if new_address.replace(PORT + PORT_ADD, PORT, 1).replace(
        SELECT + "\n" + GUARD_OPEN + FAST + "\n" + GUARD_CLOSE, SELECT + "\n", 1
    ) != address:
        raise SystemExit("Address source recovery failed")
    if new_main.replace(DECL + DECL_ADD, DECL, 1).replace(
        CONNECT + CONNECT_ADD, CONNECT, 1
    ).replace(HIT_REPLACEMENT, HIT, 1) != main_source:
        raise SystemExit("Main source recovery failed")
    for defines in (set(), {"MK2"}, {"MK3"}, {"MK3", "DSP_COMP"},
                    {"DSP_LEAN"}, {"MK3", "DSP_LEAN"}, {"MK2", "DSP_COMP", "DSP_LEAN"},
                    {"MK2", "MK2_DEBUG"}):
        for name, old, new in (("main", main_source, new_main), ("address", address, new_address)):
            old_selected, new_selected = configured(old, defines), configured(new, defines)
            if old_selected != new_selected:
                print("".join(difflib.unified_diff(old_selected.splitlines(True),
                                                   new_selected.splitlines(True),
                                                   f"original-{name}", f"candidate-{name}")))
                raise SystemExit(f"Non-target {name} source changed: {sorted(defines)}")
    target_main = configured(new_main, {"MK2", "DSP_COMP"})
    target_address = configured(new_address, {"MK2", "DSP_COMP"})
    for token in ("  .cc_wr_hit_fast(cc_wr_hit_fast),", "wire cc_wr_hit = cc_wr_hit_fast;"):
        unique(target_main, token)
    for token in ("  output cc_wr_hit_fast,", FAST):
        unique(target_address, token)

    gold = boundary_model("gold", "gold", "aligned")
    gate = boundary_model("gate", "gate", "aligned")
    mutations = {
        "bad-cc-bank": ("? (SNES_ADDR[23:20] == 4'hE)", "? (SNES_ADDR[23:20] == 4'hF)"),
        "bad-pf-bank": ("== 4'h2) | (SNES_ADDR[23:20] == 4'hA", "== 4'h3) | (SNES_ADDR[23:20] == 4'hA"),
        "bad-offset": ("& (SNES_ADDR[15:13] == 3'b011))\n                : 1'b0)\n              | (cc_sel", "& (SNES_ADDR[15:13] == 3'b010))\n                : 1'b0)\n              | (cc_sel"),
        "bad-priority": ("wire cc_wr_hit_fast = ~cc_unlocked\n              & (EV_CC92", "wire cc_wr_hit_fast = ~cc_unlocked\n              & (EV_PF94"),
        "bad-unlock": ("wire cc_wr_hit_fast = ~cc_unlocked", "wire cc_wr_hit_fast = 1'b1"),
        "bad-strobe": ("assign write_enable = SNES_WR_end & cc_wr_hit;", "assign write_enable = ~SNES_WR_end & cc_wr_hit;"),
        "bad-x": ("assign timer_start = SNES_WR_end & cc_wr_hit & (SNES_DATA == 8'h09);",
                  "assign timer_start = SNES_WR_end & cc_wr_hit & (SNES_DATA == 8'h09) & (SNES_ADDR[0] | ~SNES_ADDR[0]);"),
    }
    pipe_gold = pipeline_model("gold")
    pipe_gate = pipeline_model("gate")
    pipe_mutations = {
        "pipe-bad-early": ("wire [23:0] next_early = (r3 & r2);", "wire [23:0] next_early = (r4 & r2);"),
        "pipe-bad-local": ("wire [23:0] next_local = early_addr;", "wire [23:0] next_local = r5;"),
        "pipe-bad-init": ("initial_write = 8'b11111111;", "initial_write = 8'b00000010;"),
        "pipe-bad-x": ("assign first_relation_ok = (next_early === (next_r4 & next_r3));",
                       "assign first_relation_ok = (next_early === (next_r4 & next_r3)) & (r2[0] | ~r2[0]);"),
    }
    quiet_gate = boundary_model("gate", "gate", "quiet")
    files = {
        "original-main.v": main_source, "candidate-main.v": new_main,
        "original-address.v": address, "candidate-address.v": new_address,
        "gold.v": gold, "gate.v": gate,
        "old-simple.v": boundary_model("gate", "gate", "aligned", FAST_SIMPLE),
        "quiet-gold.v": boundary_model("gold", "gold", "quiet"),
        "quiet-gate.v": quiet_gate,
        "unaligned-gold.v": boundary_model("gold", "gold", "unaligned"),
        "unaligned-gate.v": boundary_model("gate", "gate", "unaligned"),
        "pipe-gold.v": pipe_gold, "pipe-gate.v": pipe_gate,
    }
    for name, (old, new) in mutations.items():
        unique(gate, old)
        files[name + ".v"] = gate.replace(old, new, 1)
    for name, (old, new) in pipe_mutations.items():
        unique(pipe_gate, old)
        files[name + ".v"] = pipe_gate.replace(old, new, 1)
    unique(quiet_gate, "wire SNES_WR_end = 1'b0;")
    files["quiet-bad.v"] = quiet_gate.replace("wire SNES_WR_end = 1'b0;", "wire SNES_WR_end = 1'b1;", 1)
    output.mkdir(parents=True, exist_ok=True)
    checksums = []
    for name, content in files.items():
        data = content.encode("utf-8")
        (output / name).write_bytes(data)
        checksums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    diffs = []
    for name, before, after in (("main", main_source, new_main), ("address", address, new_address)):
        diffs.extend(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                          f"original-{name}.v", f"candidate-{name}.v"))
    (output / "candidate.diff").write_text("".join(diffs), encoding="utf-8")
    print("Pinned main/address, registered address and strobe source, consumers and CLK2 binding.")
    print("Exact inverse recovery and eight non-target configurations checked.")
    print("Prepared aligned, independent-startup, unaligned-negative and pipeline-invariant projections.")


if __name__ == "__main__":
    main()
