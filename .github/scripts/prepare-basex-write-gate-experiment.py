#!/usr/bin/env python3
"""Prepare a pinned, runner-only cheat write-enable factoring experiment."""

import difflib
import hashlib
import re
import sys
from pathlib import Path


EXPECTED_BLOB = "dfc2f4fe2dc21fdd07da735fa1cd57a7aa6f4f3f"
DECL = """reg [23:0] cheat_addr[5:0];
reg [7:0] cheat_data[5:0];"""
WRITES = """        cheat_addr[pgm_idx] <= pgm_in[31:8];
        cheat_data[pgm_idx] <= pgm_in[7:0];"""
STROBE = "wire snescmd_wr_strobe = snescmd_enable & SNES_wr_strobe;"
PROGRAM = """always @(posedge clk) begin
  if(SNES_reset_strobe) begin
    snescmd_unlock_disable_strobe <= 1'b0;
  end else begin
    snescmd_unlock_disable_strobe <= 1'b0;
    if(snescmd_unlock & snescmd_wr_strobe) begin
      if((SNES_ADDR[10:9] == 2'b01) && (~|SNES_ADDR[8:0])) begin
        case(SNES_DATA)
          8'h82: cheat_enable <= 1;
          8'h83: cheat_enable <= 0;
          8'h84: {nmi_enable, irq_enable} <= 2'b00;
        endcase
      end else if(SNES_ADDR[10:0] == 11'h3fd) begin
        snescmd_unlock_disable_strobe <= 1'b1;
      end
    end else if(pgm_we) begin
      if(pgm_idx < 6) begin
""" + WRITES + """
      end else if(pgm_idx == 6) begin // set rom patch enable
        cheat_enable_mask <= pgm_in[5:0];
      end else if(pgm_idx == 7) begin // set/reset global enable / hooks
      // pgm_in[15:8] are reset bit flags
      // pgm_in[7:0] are set bit flags
        {savestate_enable, wram_present, buttons_enable, holdoff_enable, irq_enable, nmi_enable, cheat_enable}
         <= ({savestate_enable, wram_present, buttons_enable, holdoff_enable, irq_enable, nmi_enable, cheat_enable}
          & ~pgm_in[14:8])
          | pgm_in[6:0];
      end
    end
  end
end"""
HELPER = """// AMD UG627: keep the late command-priority gate in one LUT.
// This is purely combinational; it adds no storage or clock latency.
(* LUT_MAP="yes" *)
module cheat_pgm_gate(
  input selected, unlock, enabled, strobe,
  output we
);
assign we = selected & ~(unlock & enabled & strobe);
endmodule
"""
PORTS = """module cheat_programming_model(
  input CLK, SNES_reset_strobe, snescmd_unlock, snescmd_enable, SNES_wr_strobe,
  input pgm_we,
  input [2:0] pgm_idx,
  input [31:0] pgm_in,
  output [191:0] state
);
wire clk = CLK;
"""


def without_comments(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def factored_writes():
    parts = [
        "// Same six programming words and original reset/command priority.\n",
        "wire cheat_pgm_allowed = pgm_we & ~SNES_reset_strobe;\n",
        "wire [5:0] cheat_pgm_selected, cheat_pgm_write;\n",
    ]
    for word in range(6):
        parts.append(
            f"assign cheat_pgm_selected[{word}] = cheat_pgm_allowed & (pgm_idx == 3'd{word});\n"
            f"cheat_pgm_gate pgm_gate_{word}(\n"
            f"  .selected(cheat_pgm_selected[{word}]), .unlock(snescmd_unlock),\n"
            f"  .enabled(snescmd_enable), .strobe(SNES_wr_strobe), .we(cheat_pgm_write[{word}])\n"
            ");\n"
            "always @(posedge clk) begin\n"
            f"  if(cheat_pgm_write[{word}]) begin\n"
            f"    cheat_addr[{word}] <= pgm_in[31:8];\n"
            f"    cheat_data[{word}] <= pgm_in[7:0];\n"
            "  end\n"
            "end\n"
        )
    return "".join(parts)


def model(write, helper=""):
    observations = "".join(
        f"assign state[{word * 32} +: 32] = {{cheat_addr[{word}], cheat_data[{word}]}};\n"
        for word in range(6)
    )
    return PORTS + DECL + "\n" + STROBE + "\n" + write + "\n" + observations + "endmodule\n" + helper


def main():
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete cheat source blob: {blob}")
    original = raw.decode("utf-8")
    for fragment in (DECL, WRITES, STROBE, PROGRAM):
        if original.count(fragment) != 1:
            raise SystemExit(f"Programming source boundary changed: {fragment}")
    directives = re.findall(r"^\s*`(\w+)", original, flags=re.M)
    if directives != ["timescale"]:
        raise SystemExit(f"Unreviewed preprocessor directives: {directives}")
    if len(re.findall(r"^\s*module\b", original, flags=re.M)) != 1:
        raise SystemExit("Expected the pinned standalone cheat module")

    # These are every original storage reference: declarations, the two writes
    # above, six address comparisons and six data reads. No hidden reset/init.
    remainder = without_comments(original.replace(DECL, "").replace(WRITES, ""))
    for name in ("cheat_addr", "cheat_data"):
        accesses = re.findall(r"\b" + name + r"\[([^\]]+)\]", remainder)
        if sorted(accesses) != [str(i) for i in range(6)]:
            raise SystemExit(f"Unmodelled {name} access: {accesses}")
        if re.search(r"\b" + name + r"\b", re.sub(r"\b" + name + r"\[[^\]]+\]", "", remainder)):
            raise SystemExit(f"Unmodelled {name} declaration or access")

    write = factored_writes()
    empty_write = "        // Array writes use the identical priority in the LUT gates below."
    candidate = original.replace(WRITES, empty_write)
    candidate = candidate.replace(
        PROGRAM.replace(WRITES, empty_write),
        PROGRAM.replace(WRITES, empty_write) + "\n\n" + write,
    )
    candidate += "\n" + HELPER
    # Removing the new gates and restoring just the two old assignments must
    # recover the COMPLETE source byte for byte, including every read expression.
    recovered = candidate.removesuffix("\n" + HELPER).replace("\n\n" + write, "")
    recovered = recovered.replace(empty_write, WRITES)
    if recovered != original:
        raise SystemExit("The candidate changed source outside the audited array writes")

    # Projection of PROGRAM onto its only two array assignments. The full
    # original block above fixes the reset, command and programming ancestors.
    gold_write = """always @(posedge clk) begin
  if(SNES_reset_strobe) begin
  end else begin
    if(snescmd_unlock & snescmd_wr_strobe) begin
    end else if(pgm_we) begin
      if(pgm_idx < 6) begin
""" + WRITES + """
      end
    end
  end
end"""
    gold = model(gold_write)
    gate = model(write, HELPER)
    bad_data = gate.replace("cheat_data[0] <= pgm_in[7:0];", "cheat_data[0] <= pgm_in[7:0] ^ 8'h01;", 1)
    bad_priority = gate.replace("selected & ~(unlock & enabled & strobe)", "selected", 1)
    bad_reset = gate.replace("pgm_we & ~SNES_reset_strobe", "pgm_we", 1)
    if any(mutant == gate for mutant in (bad_data, bad_priority, bad_reset)):
        raise SystemExit("A required negative-control mutation was not applied")
    files = {
        "original-cheat.v": original, "candidate-cheat.v": candidate,
        "gold.v": gold, "gate.v": gate, "bad-data.v": bad_data,
        "bad-priority.v": bad_priority, "bad-reset.v": bad_reset,
    }
    output.mkdir(parents=True, exist_ok=True)
    hashes = []
    for name, text in files.items():
        data = text.encode("utf-8")
        (output / name).write_bytes(data)
        hashes.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(hashes), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-cheat.v", "candidate-cheat.v")), encoding="utf-8")
    print(f"Verified complete cheat source blob {blob}; all array accesses accounted for.")
    print("All other source, declarations and reads are byte-identical.")
    print("Generated 192-bit storage transition models and three negative controls.")
    print("Native LUT mapping and timing remain unproven; production RTL is untouched.")


if __name__ == "__main__":
    main()
