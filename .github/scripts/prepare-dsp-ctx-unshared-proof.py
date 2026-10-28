#!/usr/bin/env python3
"""Prepare a source-pinned, runner-only DSPx context address experiment."""

import difflib
import hashlib
import re
import sys
from pathlib import Path


CTX_BLOB = "fe297129d4e089b3c79d78eb0f9025c4276c93fd"
MAIN_BLOB = "cc6889c4f00f653b0df19184ec8c7d726df9d2c9"
TICK = chr(96)
PORTS = [
    ("IS_WRAM", 1), ("IS_WRAM_SHADOW", 1), ("IS_WRAM_BANK", 1),
    ("IS_VRAM", 1), ("IS_CGRAM", 1), ("IS_OAM", 1),
    ("IS_PPUREG", 1), ("IS_CPUREG", 1), ("IS_MISC", 1),
    ("IS_GAMEPAD_WRITE", 1), ("IS_APU", 1), ("IS_APU_RAM_r", 1),
    ("SNES_ADDR", 24), ("SNES_PA", 8), ("WRAM_ADDR", 24),
    ("r2115", 8), ("VRAM_ADDR", 16), ("CGRAM_ADDR", 9),
    ("OAM_ADDR", 10), ("APU_ADDR", 16),
]
EXTRA = [
    ("ADDR_Q", 24), ("DATA_Q", 16), ("REQ_Q", 1), ("WORD_Q", 1),
    ("BUS_RDY", 1), ("DATA_SINGLE_IN", 8), ("rBG", 8), ("rM7", 8),
    ("IS_BG_DOUBLE", 1), ("IS_M7_DOUBLE", 1),
]
OUTPUTS = [
    ("out_sram_addr", 24), ("out_addr_d", 24), ("out_data_d", 16),
    ("out_req_d", 1), ("out_word_d", 1), ("out_is_write", 1),
    ("out_bus_wrq", 1), ("out_rom_addr", 24), ("out_rom_data", 16),
    ("out_rom_word", 1),
]
CONSUMER = """always @(posedge clkin) begin
  if (IS_WRITE) begin
    REQ <= 1;
    ADDR[23:0] <= SRAM_SNES_ADDR[23:0];
    DATA[15:0] <= { DATA_SINGLE_IN, (IS_BG_DOUBLE ? rBG : IS_M7_DOUBLE ? rM7 : DATA_SINGLE_IN) };
    WORD <= IS_WORD;
  end
  else begin
    REQ <= 0;
  end
end"""


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"Unexpected source or mutation boundary: {old!r}")
    return text.replace(old, new, 1)


def normalize(text):
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    return re.sub(r"\s+", "", text)


def configured(text, initial_defines):
    """Select only the known directives in the pinned original and candidate."""
    defines = set(initial_defines)
    active, stack, output = True, [], []
    allowed = {"MK2", "MK3", "DSP_COMP", "CTX_APU_ENABLE"}
    for line in text.splitlines(True):
        match = re.fullmatch(r"\s*" + TICK + r"(ifdef|ifndef)\s+(\w+)\s*", line)
        if match:
            kind, macro = match.groups()
            if macro not in allowed:
                raise SystemExit(f"Unreviewed conditional macro: {macro}")
            condition = (macro in defines) == (kind == "ifdef")
            stack.append((active, condition))
            active = active and condition
        elif line.strip() == TICK + "else":
            if not stack:
                raise SystemExit("Unmatched else")
            parent, condition = stack[-1]
            active = parent and not condition
        elif line.strip() == TICK + "endif":
            if not stack:
                raise SystemExit("Unmatched endif")
            active, _ = stack.pop()
        elif re.fullmatch(r"\s*" + TICK + r"define\s+CTX_APU_ENABLE\s*", line):
            if active:
                defines.add("CTX_APU_ENABLE")
        elif re.match(r"\s*" + TICK + r"(?:elsif|undef|define)\b", line):
            raise SystemExit(f"Unreviewed directive: {line.strip()}")
        elif active:
            output.append(line)
    if stack:
        raise SystemExit("Unbalanced preprocessor directives")
    return "".join(output)


def declaration(direction, item, reg=False):
    name, width = item
    variable = " reg" if reg else ""
    size = "" if width == 1 else f" [{width - 1}:0]"
    return f"{direction}{variable}{size} {name}"


def helper(expr):
    ports = ",\n  ".join(declaration("input", p) for p in PORTS)
    return ('(* resource_sharing = "no" *)\n'
            "module dspx_ctx_addr_unshared(\n  " + ports
            + ",\n  output wire [23:0] SRAM_SNES_ADDR\n);\n"
            + expr + "\nendmodule\n")


def instance():
    bindings = ",\n  ".join(f".{name}({name})" for name, _ in PORTS)
    return ("dspx_ctx_addr_unshared ctx_addr_unshared (\n  " + bindings
            + ",\n  .SRAM_SNES_ADDR(SRAM_SNES_ADDR)\n);")


def model(name, expr, addr_fragment, helpers="", mutation=None):
    inputs = ",\n  ".join(declaration("input", p) for p in PORTS + EXTRA)
    outputs = ",\n  ".join(declaration("output", p, p[0].endswith("_d")) for p in OUTPUTS)
    update = """always @* begin
  out_addr_d = ADDR_Q;
  out_data_d = DATA_Q;
  out_word_d = WORD_Q;
  if (IS_WRITE) begin
    out_req_d = 1'b1;
    out_addr_d = SRAM_SNES_ADDR;
    out_data_d = {DATA_SINGLE_IN, (IS_BG_DOUBLE ? rBG : IS_M7_DOUBLE ? rM7 : DATA_SINGLE_IN)};
    out_word_d = IS_WORD;
  end else begin
    out_req_d = 1'b0;
  end
end"""
    if mutation == "bad-write":
        update = once(update, "if (IS_WRITE)", "if (!IS_WRITE)")
    elif mutation == "bad-hold":
        update = once(update, "out_addr_d = ADDR_Q;", "out_addr_d = 24'h0;")
    elif mutation == "bad-data-priority":
        update = once(update, "IS_BG_DOUBLE ? rBG : IS_M7_DOUBLE ? rM7",
                      "IS_M7_DOUBLE ? rM7 : IS_BG_DOUBLE ? rBG")
    elif mutation == "bad-word":
        update = once(update, "out_word_d = IS_WORD;", "out_word_d = ~IS_WORD;")
    elif mutation == "bad-x-word":
        update = once(update, "out_word_d = IS_WORD;",
                      "out_word_d = IS_WORD & (SNES_ADDR[22] | ~SNES_ADDR[22]);")
    elif mutation is not None:
        raise SystemExit(f"Unknown update mutant: {mutation}")
    return (f"module {name}(\n  " + inputs + ",\n  " + outputs + "\n);\n"
            "wire [23:0] SRAM_SNES_ADDR;\n"
            + addr_fragment + "\n" + expr + "\n"
            "assign out_sram_addr = SRAM_SNES_ADDR;\n"
            "assign out_is_write = IS_WRITE;\n" + update + "\n"
            "assign out_bus_wrq = REQ_Q & BUS_RDY;\n"
            "assign out_rom_addr = ADDR_Q;\n"
            "assign out_rom_data = DATA_Q;\n"
            "assign out_rom_word = WORD_Q;\n"
            "endmodule\n" + helpers)


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: prepare-dsp-ctx-unshared-proof.py CTX MAIN OUTPUT_DIR")
    ctx_path, main_path, output = map(Path, sys.argv[1:])
    ctx_data, main_data = ctx_path.read_bytes(), main_path.read_bytes()
    if blob(ctx_data) != CTX_BLOB or blob(main_data) != MAIN_BLOB:
        raise SystemExit(f"Unexpected source blobs: {blob(ctx_data)} {blob(main_data)}")
    ctx = ctx_data.decode("utf-8")
    top = main_data.decode("utf-8")
    if top.count("ctx snes_ctx (") != 1:
        raise SystemExit("Unexpected context instance in DSP top")
    clean = re.sub(r"/\*.*?\*/|//[^\n]*", "", ctx, flags=re.S)
    if re.search(r"\bmodule\s+dspx_ctx_addr_unshared\b", clean):
        raise SystemExit("Helper name already exists in context source")
    if len(re.findall(r"\bSRAM_SNES_ADDR\b", clean)) != 3:
        raise SystemExit("Unexpected address declaration, driver or consumer count")
    match = re.search(r"assign SRAM_SNES_ADDR\[23:0\] = IS_WRAM\b.*?;", ctx, re.S)
    if not match:
        raise SystemExit("Original SRAM address expression not found")
    original_expr = match.group()
    consumer_start = "always @(posedge clkin) begin\n  if (IS_WRITE) begin"
    if ctx.count(consumer_start) != 1:
        raise SystemExit("Unexpected address consumer block")
    start = ctx.index(consumer_start)
    end = ctx.index("\nend\n\n// assign outputs", start) + len("\nend")
    if normalize(ctx[start:end]) != normalize(CONSUMER):
        raise SystemExit("Address consumer differs from the projected transition")
    write = "assign IS_WRITE = IS_WRAM | IS_VRAM | IS_CGRAM | IS_OAM | IS_APU | IS_PPUREG | IS_CPUREG | IS_MISC;"
    word = "assign IS_WORD = IS_PPUREG;"
    for expected in (
        write, word, "initial REQ = 1'b0;", "initial ADDR = 24'h0;",
        "initial DATA = 16'h0000;", "initial WORD = 0;",
        "assign BUS_WRQ = REQ & BUS_RDY;",
        "assign ROM_ADDR[23:0] = ADDR[23:0];",
        "assign ROM_DATA[15:0] = DATA[15:0];",
        "assign ROM_WORD_ENABLE = WORD;",
    ):
        if ctx.count(expected) != 1:
            raise SystemExit(f"Unexpected context state/output boundary: {expected}")
    if len(re.findall(r"\bassign\s+IS_WRITE\s*=", clean)) != 1:
        raise SystemExit("Unexpected write-enable driver count")
    declaration_checks = (
        "input [23:0] SNES_ADDR", "input [7:0] SNES_PA", "reg [23:0] WRAM_ADDR;",
        "reg [7:0] r2115;", "reg [15:0] VRAM_ADDR;", "reg [8:0] CGRAM_ADDR;",
        "reg [9:0] OAM_ADDR;", "reg [15:0] APU_ADDR;",
    )
    for expected in declaration_checks:
        if ctx.count(expected) != 1:
            raise SystemExit(f"Unexpected address-input declaration: {expected}")
    bindings, module = instance(), helper(original_expr)
    wrapped = (TICK + "ifdef MK2\n" + TICK + "ifdef DSP_COMP\n" + bindings + "\n"
               + TICK + "else\n" + original_expr + "\n" + TICK + "endif\n"
               + TICK + "else\n" + original_expr + "\n" + TICK + "endif")
    helper_block = (TICK + "ifdef MK2\n" + TICK + "ifdef DSP_COMP\n" + module
                    + TICK + "endif\n" + TICK + "endif\n")
    candidate = once(ctx, original_expr, wrapped) + helper_block
    recovered = once(candidate.removesuffix(helper_block), wrapped, original_expr)
    if recovered != ctx:
        raise SystemExit("Candidate does not recover exact original source")
    for defines in (set(), {"MK3"}, {"MK2"}, {"DSP_COMP"}, {"MK3", "DSP_COMP"},
                    {"CTX_APU_ENABLE"}, {"MK2", "CTX_APU_ENABLE"},
                    {"DSP_COMP", "CTX_APU_ENABLE"}, {"MK3", "CTX_APU_ENABLE"},
                    {"MK3", "DSP_COMP", "CTX_APU_ENABLE"}):
        if configured(ctx, defines) != configured(candidate, defines):
            raise SystemExit(f"Non-target source changed under {sorted(defines)}")
    for defines in ({"MK2", "DSP_COMP"}, {"MK2", "DSP_COMP", "MK3"}):
        expected = once(configured(ctx, defines), original_expr, bindings) + module
        if configured(candidate, defines) != expected:
            raise SystemExit(f"Unexpected target source under {sorted(defines)}")
    addr_mutations = {
        "bad-priority": (".IS_WRAM(IS_WRAM)", ".IS_WRAM(IS_VRAM)"),
        "bad-wram": (".WRAM_ADDR(WRAM_ADDR)", ".WRAM_ADDR(WRAM_ADDR ^ 24'h1)"),
        "bad-vram": (".VRAM_ADDR(VRAM_ADDR)", ".VRAM_ADDR(VRAM_ADDR ^ 16'h1)"),
        "bad-cgram": (".CGRAM_ADDR(CGRAM_ADDR)", ".CGRAM_ADDR(CGRAM_ADDR ^ 9'h1)"),
        "bad-oam": (".OAM_ADDR(OAM_ADDR)", ".OAM_ADDR(OAM_ADDR ^ 10'h1)"),
        "bad-ppu": (".SNES_PA(SNES_PA)", ".SNES_PA(SNES_PA ^ 8'h1)"),
        "bad-cpu": (".SNES_ADDR(SNES_ADDR)", ".SNES_ADDR(SNES_ADDR ^ 24'h1)"),
        "bad-misc": (".IS_GAMEPAD_WRITE(IS_GAMEPAD_WRITE)", ".IS_GAMEPAD_WRITE(~IS_GAMEPAD_WRITE)"),
        "bad-apu": (".APU_ADDR(APU_ADDR)", ".APU_ADDR(APU_ADDR ^ 16'h1)"),
        "bad-x-address": (".SNES_ADDR(SNES_ADDR)",
                          ".SNES_ADDR({SNES_ADDR[23:1], SNES_ADDR[0] & (SNES_ADDR[23] | ~SNES_ADDR[23])})"),
    }
    projected = "wire IS_WRITE;\nwire IS_WORD;\n" + write + "\n" + word
    files = {
        "original-ctx.v": ctx,
        "candidate-ctx.v": candidate,
        "candidate.diff": "".join(difflib.unified_diff(ctx.splitlines(True), candidate.splitlines(True),
                                                         fromfile="original-ctx.v", tofile="candidate-ctx.v")),
        "gold.v": model("gold", projected, original_expr),
        "gate.v": model("gate", projected, bindings, module),
    }
    for name, (before, after) in addr_mutations.items():
        files[name + ".v"] = model("gate", projected, once(bindings, before, after), module)
    for name in ("bad-write", "bad-hold", "bad-data-priority", "bad-word", "bad-x-word"):
        files[name + ".v"] = model("gate", projected, bindings, module, name)
    output.mkdir(parents=True, exist_ok=True)
    checksums = []
    for name, content in files.items():
        data = content.encode("utf-8")
        (output / name).write_bytes(data)
        checksums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    print(f"Original ctx blob: {blob(ctx_data)}")
    print(f"Original DSP main blob: {blob(main_data)}")
    print(f"Candidate ctx blob: {blob(candidate.encode('utf-8'))}")
    print(f"Candidate ctx SHA256: {hashlib.sha256(candidate.encode('utf-8')).hexdigest()}")
    print("Exact recovery, ten non-target and two target configurations verified.")
    print("Address expression and full captured-write transition projected from pinned source.")
    print("DATA_SINGLE_IN and all existing state are common cutpoints; no FPGA timing is claimed.")


if __name__ == "__main__":
    main()
