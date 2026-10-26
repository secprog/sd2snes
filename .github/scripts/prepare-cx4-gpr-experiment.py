#!/usr/bin/env python3
"""Generate a pinned, runner-only GPR experiment and its exact component models."""

import difflib
import hashlib
import re
import sys
from pathlib import Path


EXPECTED_BLOB = "6ebbf7cb5fe7ae90ad8ab82d433f41cb04e8eca7"
DECLARATION = "reg  [7:0] gpr [47:0];"
BUS_READ = "always @(posedge CLK) GPR_DOr <= gpr[ADDR[5:0]];"
CPU_READ = re.compile(
    r"\{gpr\[op_param\[3:0\]\*3\+2\],\s*"
    r"gpr\[op_param\[3:0\]\*3\+1\],\s*gpr\[op_param\[3:0\]\*3\]\}"
)
WRITE = """always @(posedge CLK) begin
  if(cx4_cpu_en & CPU_STATE == ST_CPU_2
          && (op == OP_ST || op == OP_SWP)
          && (op_param[7:4] == 4'h6)) begin
    gpr[op_param[3:0]*3+2] <= cpu_idb[23:16];
    gpr[op_param[3:0]*3+1] <= cpu_idb[15:8];
    gpr[op_param[3:0]*3] <= cpu_idb[7:0];
  end
  else if(GPR_WR_EN & (cx4_cpu_en | ss_frozen_r)) gpr[ADDR[5:0]] <= DI;
end"""

BANK_DECLARATION = """// Three byte lanes of the same sixteen 24-bit GPR words.
// Keep both read addresses and the original registered MMIO read latency.
reg [7:0] gpr_bank0 [15:0];
reg [7:0] gpr_bank1 [15:0];
reg [7:0] gpr_bank2 [15:0];
wire [4:0] gpr_bus_row = ADDR[5:0] / 6'd3;
wire [1:0] gpr_bus_lane = ADDR[5:0] % 6'd3;
wire [7:0] gpr_bus_data = (ADDR[5:0] < 6'd48)
    ? ((gpr_bus_lane == 2'd0) ? gpr_bank0[gpr_bus_row[3:0]]
     : (gpr_bus_lane == 2'd1) ? gpr_bank1[gpr_bus_row[3:0]]
                            : gpr_bank2[gpr_bus_row[3:0]])
    : 8'bxxxxxxxx; // Preserve the original out-of-range array read.
"""
BANK_BUS_READ = "always @(posedge CLK) GPR_DOr <= gpr_bus_data;"
BANK_CPU_READ = "{gpr_bank2[op_param[3:0]], gpr_bank1[op_param[3:0]], gpr_bank0[op_param[3:0]]}"
BANK_WRITE = """// One write address per bank; CPU writes retain priority over MMIO.
reg [3:0] gpr_waddr;
reg [23:0] gpr_wdata;
reg [2:0] gpr_we;
always @* begin
  gpr_waddr = op_param[3:0];
  gpr_wdata = cpu_idb;
  gpr_we = 3'b000;
  if(cx4_cpu_en & CPU_STATE == ST_CPU_2
          && (op == OP_ST || op == OP_SWP)
          && (op_param[7:4] == 4'h6)) begin
    gpr_we = 3'b111;
  end
  else if(GPR_WR_EN & (cx4_cpu_en | ss_frozen_r)) begin
    gpr_waddr = gpr_bus_row[3:0];
    gpr_wdata = {3{DI}};
    if(ADDR[5:0] < 6'd48) begin
      case(gpr_bus_lane)
        2'd0: gpr_we = 3'b001;
        2'd1: gpr_we = 3'b010;
        2'd2: gpr_we = 3'b100;
        default: gpr_we = 3'b000;
      endcase
    end
  end
end
always @(posedge CLK) begin
  if(gpr_we[0]) gpr_bank0[gpr_waddr] <= gpr_wdata[7:0];
  if(gpr_we[1]) gpr_bank1[gpr_waddr] <= gpr_wdata[15:8];
  if(gpr_we[2]) gpr_bank2[gpr_waddr] <= gpr_wdata[23:16];
end"""

PORTS = """module gpr_model(
  input CLK,
  input [12:0] ADDR,
  input [7:0] DI,
  input cx4_cpu_en,
  input [5:0] CPU_STATE,
  input [4:0] op,
  input [7:0] op_param,
  input [23:0] cpu_idb,
  input GPR_WR_EN,
  input ss_frozen_r,
  output [23:0] cpu_read,
  output [391:0] state
);
reg [7:0] GPR_DOr;
"""


def model(parameters, declaration, bus_read, cpu_read, write, banked):
    # All 384 storage bits and the existing 8-bit registered bus output are
    # exposed in canonical byte order. These ports exist only in proof inputs.
    state = []
    for byte in range(48):
        word = f"gpr_bank{byte % 3}[{byte // 3}]" if banked else f"gpr[{byte}]"
        state.append(f"assign state[{byte * 8} +: 8] = {word};\n")
    state.append("assign state[391:384] = GPR_DOr;\n")
    return (
        PORTS + parameters + declaration + "\n" + bus_read + "\n" + write + "\n"
        + f"assign cpu_read = {cpu_read};\n" + "".join(state) + "endmodule\n"
    )


def main():
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != EXPECTED_BLOB:
        raise SystemExit(f"Unexpected CX4 source blob: {blob}")
    original = raw.decode("utf-8")
    for fragment in (DECLARATION, BUS_READ, WRITE):
        if original.count(fragment) != 1:
            raise SystemExit("Original GPR declaration/read/write boundary changed")
    reads = CPU_READ.findall(original)
    if len(reads) != 3:
        raise SystemExit("Expected exactly three identical CPU GPR read expressions")
    remainder = original.replace(DECLARATION, "").replace(BUS_READ, "").replace(WRITE, "")
    remainder = CPU_READ.sub("", remainder)
    remainder = re.sub(r"/\*.*?\*/|//[^\n]*", "", remainder, flags=re.S)
    if re.search(r"\bgpr\b", remainder):
        raise SystemExit("Found an unmodelled GPR access")
    # GPR_DOr is neither reset nor initialized elsewhere in the pinned source.
    if len(re.findall(r"\bGPR_DOr\b", remainder)) != 2:
        raise SystemExit("Registered bus output has an unexpected use or driver")
    parameters = ""
    for name in ("ST_CPU_2", "OP_ST", "OP_SWP"):
        matches = re.findall(rf"^parameter {name}\s*=.*;$", original, flags=re.M)
        if len(matches) != 1:
            raise SystemExit(f"Unexpected parameter definition: {name}")
        parameters += matches[0] + "\n"

    candidate = original.replace(DECLARATION, BANK_DECLARATION).replace(BUS_READ, BANK_BUS_READ)
    candidate = CPU_READ.sub(BANK_CPU_READ, candidate).replace(WRITE, BANK_WRITE)
    gold = model(parameters, DECLARATION, BUS_READ, reads[0], WRITE, False)
    gate = model(parameters, BANK_DECLARATION, BANK_BUS_READ, BANK_CPU_READ, BANK_WRITE, True)
    bad_data = gate.replace("<= gpr_wdata[7:0];", "<= gpr_wdata[7:0] ^ 8'h01;", 1)
    bad_priority = gate.replace("else if(GPR_WR_EN", "if(GPR_WR_EN", 1)
    if bad_data == gate or bad_priority == gate:
        raise SystemExit("A required negative-control mutation was not applied")

    output.mkdir(parents=True, exist_ok=True)
    files = {
        "original-cx4.v": original, "candidate-cx4.v": candidate,
        "gold.v": gold, "gate.v": gate,
        "bad-data.v": bad_data, "bad-priority.v": bad_priority,
    }
    hashes = []
    for name, text in files.items():
        data = text.encode("utf-8")
        (output / name).write_bytes(data)
        hashes.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(hashes), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-cx4.v", "candidate-cx4.v")), encoding="utf-8"
    )
    print(f"Verified CX4 blob {blob}; modelled all GPR accesses and bus-output state.")
    print("Generated runner-only candidate and two deliberate errors; production RTL is unchanged.")


if __name__ == "__main__":
    main()
