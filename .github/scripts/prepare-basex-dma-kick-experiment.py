#!/usr/bin/env python3
"""Prepare a pinned, runner-only basex DMA kick-decode experiment."""

import difflib
import hashlib
import re
import sys
from pathlib import Path


BLOBS = {
    "main.v": "2bd168af3e0254a6c985ff7cd5b0413afafab0a9",
    "dma.v": "00dde5ec7e35baf936df5b696a0a7501039ebc84",
    "address.v": "36ce9a5c17fc80b9ddda1d869f0d75a4fb52356c",
    "config.vh": "1a9a6a14b8b08eb6e931ce2320326e913aa8000e",
}
ORIGINAL_KICK = "wire op_kick = reg_we_rising & enable & (reg_addr == 4'd9) & reg_data_in[0];"
FAST_EXPR = (
    "MCU_DMA_ACTIVE ? (MCU_DMA_WE & (MCU_DMA_ADDR == 4'd9) & MCU_DMA_DATA[0]) "
    ": (dma_enable & SNES_WR_end & (SNES_ADDR[3:0] == 4'd9) & DMA_SNES_DATA_IN[0])"
)
FAST_DECL = """`ifdef MK2
`ifdef BASE_EXT
// The original 1-bit net is implicit at the address-module port. XST requires
// it to be declared before it is used in this continuous expression.
wire dma_enable;
// Runner-only experiment: decode the selected DMA trigger before the mux.
wire DMA_OP_KICK_FAST = """ + FAST_EXPR + ";\n`endif\n`endif"
FAST_PORT = """`ifdef MK2
`ifdef BASE_EXT
  .op_kick_fast(DMA_OP_KICK_FAST),
`endif
`endif"""
DMA_PORT = """`ifdef MK2
`ifdef BASE_EXT
  input op_kick_fast,
`endif
`endif"""
DMA_KICK = """`ifdef MK2
`ifdef BASE_EXT
wire op_kick = op_kick_fast;
`else
""" + ORIGINAL_KICK + "\n`endif\n`else\n" + ORIGINAL_KICK + "\n`endif"


def unique(text, fragment):
    count = text.count(fragment)
    if count != 1:
        raise SystemExit(f"Expected one occurrence, found {count}: {fragment!r}")


def read_pinned(path):
    raw = path.read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != BLOBS[path.name]:
        raise SystemExit(f"Unexpected {path.name} Git blob: {actual}")
    return raw.decode("utf-8")


def configured(text, defines):
    known = {"MK2", "MK3", "BASE_EXT", "BOOTLEG", "MK2_DEBUG"}
    active, stack, result = True, [], []
    for line in text.splitlines(True):
        match = re.fullmatch(r"\s*`(ifdef|ifndef)\s+(\w+)\s*", line)
        if match:
            kind, macro = match.groups()
            if macro not in known:
                raise SystemExit(f"Unreviewed preprocessor condition {macro}")
            cond = (macro in defines) == (kind == "ifdef")
            stack.append((active, cond))
            active = active and cond
        elif line.strip() == "`else":
            if not stack:
                raise SystemExit("Unbalanced else")
            parent, cond = stack[-1]
            active = parent and not cond
        elif line.strip() == "`endif":
            if not stack:
                raise SystemExit("Unbalanced endif")
            active, _ = stack.pop()
        elif active:
            result.append(line)
    if stack:
        raise SystemExit("Unbalanced conditionals")
    return "".join(result)


def compact(text):
    return re.sub(r"\s+", "", text)


def dma_instance(main):
    token = "dma snes_dma ("
    unique(main, token)
    start = main.index(token)
    end = main.index("\n);", start) + len("\n);")
    return main[start:end]


def port_value(instance, name):
    values = re.findall(r"\." + re.escape(name) + r"\(([^()]*)\)", instance)
    if len(values) != 1:
        raise SystemExit(f"Expected one DMA port {name}: {values}")
    return values[0]


def wire_value(text, name):
    values = re.findall(r"\bwire\s+" + re.escape(name) + r"\s*=\s*([^;]+);", text)
    if len(values) != 1:
        raise SystemExit(f"Expected one wire {name}: {values}")
    return values[0]


def projection(name, main, dma, target):
    instance = dma_instance(main)
    ports = {port: port_value(instance, port) for port in
             ("clkin", "reset", "enable", "reg_addr", "reg_data_in", "reg_we_rising")}
    expected = {
        "clkin": "CLK2", "reset": "SNES_reset_strobe",
        "enable": "MCU_DMA_ACTIVE | dma_enable",
        "reg_addr": "MCU_DMA_ACTIVE ? MCU_DMA_ADDR : SNES_ADDR[3:0]",
        "reg_data_in": "MCU_DMA_ACTIVE ? MCU_DMA_DATA : DMA_SNES_DATA_IN",
        "reg_we_rising": "MCU_DMA_ACTIVE ? MCU_DMA_WE : SNES_WR_end",
    }
    if ports != expected:
        raise SystemExit(f"Unexpected original DMA interface: {ports}")
    kick = wire_value(dma, "op_kick")
    if target:
        fast = wire_value(main, "DMA_OP_KICK_FAST")
        fast_port = port_value(instance, "op_kick_fast")
        if kick != "op_kick_fast":
            raise SystemExit("Candidate op_kick does not use its new input")
        extra = f"wire DMA_OP_KICK_FAST = {fast};\nwire op_kick_fast = {fast_port};\n"
    else:
        if kick != ORIGINAL_KICK.removeprefix("wire op_kick = ").removesuffix(";"):
            raise SystemExit("Unexpected original DMA kick expression")
        extra = ""
    return f"""module {name}(
  input MCU_DMA_ACTIVE, MCU_DMA_WE, dma_enable, SNES_WR_end,
  input [3:0] MCU_DMA_ADDR, input [7:0] MCU_DMA_DATA,
  input [23:0] SNES_ADDR, input [7:0] DMA_SNES_DATA_IN,
  output out_enable, output [3:0] out_addr, output [7:0] out_data,
  output out_we, output out_kick
);
wire enable = {ports['enable']};
wire [3:0] reg_addr = {ports['reg_addr']};
wire [7:0] reg_data_in = {ports['reg_data_in']};
wire reg_we_rising = {ports['reg_we_rising']};
{extra}wire op_kick = {kick};
assign out_enable = enable;
assign out_addr = reg_addr;
assign out_data = reg_data_in;
assign out_we = reg_we_rising;
assign out_kick = op_kick;
endmodule
"""


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-basex-dma-kick-experiment.py SOURCE_DIR OUTPUT_DIR")
    source_dir, output = map(Path, sys.argv[1:])
    original_main, original_dma, address, config = (
        read_pinned(source_dir / name) for name in ("main.v", "dma.v", "address.v", "config.vh")
    )
    for text, fragment in ((original_main, "dma snes_dma ("),
                           (original_main, "  .clkin(CLK2),"),
                           (original_dma, "module dma(\n"),
                           (original_dma, ORIGINAL_KICK)):
        if fragment == "  .clkin(CLK2),":
            unique(dma_instance(text), fragment)
        else:
            unique(text, fragment)
    if re.search(r"\b(?:DMA_OP_KICK_FAST|op_kick_fast)\b", original_main + original_dma):
        raise SystemExit("Fast kick names already exist")
    if re.search(r"(?m)^\s*(?:wire|reg|input|output|inout)\b[^;\n]*\bdma_enable\b", original_main):
        raise SystemExit("The expected implicit DMA enable already has an explicit declaration")
    if "`default_nettype" in original_main or "`default_nettype" in config:
        raise SystemExit("Unexpected nettype directive in pinned main or config")
    unique(original_main, ".dma_enable(dma_enable),")
    unique(address, "  output dma_enable,")
    unique(address, "assign dma_enable = ")
    # One declaration, two real consumers, and one explanatory comment.
    if len(re.findall(r"\bop_kick\b", original_dma)) != 4:
        raise SystemExit("Unexpected number of op_kick occurrences")
    for consumer in ("if (op_kick && (state != ST_IDLE))", "else if (op_kick)"):
        unique(original_dma, consumer)
    original_instance = dma_instance(original_main)
    candidate_instance = original_instance.replace("  .clkin(CLK2),", FAST_PORT + "\n  .clkin(CLK2),", 1)
    candidate_main = original_main.replace(original_instance, candidate_instance, 1)
    candidate_main = candidate_main.replace("dma snes_dma (", FAST_DECL + "\n\ndma snes_dma (", 1)
    candidate_dma = original_dma.replace("module dma(\n", "module dma(\n" + DMA_PORT + "\n", 1)
    candidate_dma = candidate_dma.replace(ORIGINAL_KICK, DMA_KICK, 1)
    if candidate_main.replace(FAST_DECL + "\n\n", "", 1).replace(FAST_PORT + "\n", "", 1) != original_main:
        raise SystemExit("Candidate main has unexpected changes")
    if candidate_dma.replace(DMA_PORT + "\n", "", 1).replace(DMA_KICK, ORIGINAL_KICK, 1) != original_dma:
        raise SystemExit("Candidate DMA has unexpected changes")

    for defines in (set(), {"MK2"}, {"MK3"}, {"MK3", "BASE_EXT"},
                    {"MK2", "BOOTLEG"}, {"MK2", "MK2_DEBUG"}):
        for old, new in ((original_main, candidate_main), (original_dma, candidate_dma)):
            if compact(configured(old, defines)) != compact(configured(new, defines)):
                raise SystemExit(f"Non-target configuration changed: {sorted(defines)}")
    target = {"MK2", "BASE_EXT"}
    gold = projection("gold", configured(original_main, target), configured(original_dma, target), False)
    gate_main = configured(candidate_main, target)
    gate_dma = configured(candidate_dma, target)
    gate = projection("gate", gate_main, gate_dma, True)
    mutations = {
        "bad-mcu-address": ("(MCU_DMA_ADDR == 4'd9)", "(MCU_DMA_ADDR == 4'd8)"),
        "bad-snes-enable": ("dma_enable & SNES_WR_end", "SNES_WR_end"),
        "bad-data-bit": ("MCU_DMA_DATA[0]", "MCU_DMA_DATA[1]"),
        "bad-selection": ("wire DMA_OP_KICK_FAST = MCU_DMA_ACTIVE ?", "wire DMA_OP_KICK_FAST = !MCU_DMA_ACTIVE ?"),
        "bad-port": (".op_kick_fast(DMA_OP_KICK_FAST)", ".op_kick_fast(~DMA_OP_KICK_FAST)"),
    }
    files = {"original-main.v": original_main, "original-dma.v": original_dma,
             "candidate-main.v": candidate_main, "candidate-dma.v": candidate_dma,
             "gold.v": gold, "gate.v": gate}
    for mutation, (before, after) in mutations.items():
        unique(gate_main, before)
        mutant = gate_main.replace(before, after, 1)
        files[mutation + ".v"] = projection("gate", mutant, gate_dma, True)
    output.mkdir(parents=True, exist_ok=True)
    sums = []
    for name, content in files.items():
        data = content.encode("utf-8")
        (output / name).write_bytes(data)
        sums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(sums), encoding="utf-8")
    diffs = []
    for name, old, new in (("main", original_main, candidate_main), ("dma", original_dma, candidate_dma)):
        diffs.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                        f"original-{name}.v", f"candidate-{name}.v"))
    (output / "candidate.diff").write_text("".join(diffs), encoding="utf-8")
    print("Pinned complete main, DMA, address and config blobs; candidate recovers both changed originals exactly.")
    print("Original DMA enable is implicitly connected to the pinned 1-bit address-module output; candidate declares that same net explicitly.")
    print("Six non-target configurations audited; projected actual DMA ports and kick expressions.")
    print("Five mutated source expressions require genuine counterexamples; no assumptions about timing.")


if __name__ == "__main__":
    main()
