#!/usr/bin/env python3
"""Prepare a source-pinned, runner-only basex write-strobe retiming proof."""

import difflib
import hashlib
import re
import sys
from pathlib import Path


SOURCE_BLOBS = {
    "main.v": "2bd168af3e0254a6c985ff7cd5b0413afafab0a9",
    "cheat.v": "dfc2f4fe2dc21fdd07da735fa1cd57a7aa6f4f3f",
    "bsx.v": "3ca70f4901a5fefef1576bae144060462b4c4254",
}
SHIFT_INIT = "reg [7:0] SNES_WRITEr = 8'b11111111;"
SHIFT_UPDATE = "SNES_WRITEr <= {SNES_WRITEr[6:0], SNES_WRITE_IN};"
SHIFT_BLOCK = """always @(posedge CLK2) begin
  SNES_PULSEr <= {SNES_PULSEr[6:0], SNES_PULSE_IN};
  SNES_PARDr <= {SNES_PARDr[6:0], SNES_PARD_IN};
  SNES_PAWRr <= {SNES_PAWRr[6:0], SNES_PAWR_IN};
  SNES_READr <= {SNES_READr[6:0], SNES_READ_IN};
  SNES_WRITEr <= {SNES_WRITEr[6:0], SNES_WRITE_IN};"""
ORIGINAL_STROBE = "wire SNES_WR_end = (SNES_WRITEr[6:1] == 6'b000001);"
RETIME_BLOCK = """`ifdef MK2
`ifdef BASE_EXT
// Diagnostic only: compare the old shift state at this same clock edge.
// This flag must equal the original strobe after every edge and at power-up.
reg SNES_WR_end_fast = 1'b0;
always @(posedge CLK2) SNES_WR_end_fast <= (SNES_WRITEr[5:0] == 6'b000001);
`endif
`endif"""
GUARDED_PORT = """`ifdef MK2
`ifdef BASE_EXT
  .{port}(SNES_WR_end_fast),
`else
  .{port}(SNES_WR_end),
`endif
`else
  .{port}(SNES_WR_end),
`endif"""


def read_pinned(path):
    raw = path.read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if actual != SOURCE_BLOBS[path.name]:
        raise SystemExit(f"Unexpected {path.name} Git blob {actual}")
    return raw.decode("utf-8")


def unique(text, fragment):
    if text.count(fragment) != 1:
        raise SystemExit(f"Expected one exact source fragment: {fragment!r}")


def instance(text, module, name):
    start_token = f"{module} {name}("
    unique(text, start_token)
    start = text.index(start_token)
    end = text.index("\n);", start) + len("\n);")
    return text[start:end]


def port_value(text, module, name, port):
    item = instance(text, module, name)
    values = re.findall(r"\." + re.escape(port) + r"\(([^()]*)\)", item)
    if len(values) != 1:
        raise SystemExit(f"Expected one {name}.{port} connection: {values}")
    return values[0]


def replace_instance_port(text, module, name, port, replacement):
    original = instance(text, module, name)
    old = f"  .{port}(SNES_WR_end),"
    unique(original, old)
    return text.replace(original, original.replace(old, replacement, 1), 1)


def configured(text, defines):
    """Resolve the pinned main.v's known conditional forms, preserving content."""
    known = {"MK2", "MK3", "BASE_EXT", "BOOTLEG", "MK2_DEBUG"}
    active, stack, result = True, [], []
    for line in text.splitlines(True):
        match = re.fullmatch(r"\s*`(ifdef|ifndef)\s+(\w+)\s*", line)
        if match:
            kind, macro = match.groups()
            if macro not in known:
                raise SystemExit(f"Unreviewed preprocessor condition: {macro}")
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
        raise SystemExit("Unbalanced source conditionals")
    return "".join(result)


def compact(text):
    return re.sub(r"\s+", "", text)


def projected_model(name, source, source_init, source_shift, source_decode, fast_init, fast_next):
    """Project the exact source expressions onto the strobe boundary.

    In the gate model, fast_q equals the original decode as the induction
    hypothesis. The next-state and initial outputs prove that this invariant
    is established on configuration and preserved for every binary shift
    state and input. Both actual bound consumer inputs are compared.
    """
    cheat = port_value(source, "cheat", "snes_cheat", "SNES_wr_strobe")
    bsx = port_value(source, "bsx", "snes_bsx", "reg_we_rising")
    if cheat not in ("SNES_WR_end", "SNES_WR_end_fast") or bsx not in (
        "SNES_WR_end", "SNES_WR_end_fast"
    ):
        raise SystemExit(f"Unexpected consumer binding: {cheat}, {bsx}")
    next_decode = source_decode.replace("SNES_WRITEr", "next_write")
    init_decode = source_decode.replace("SNES_WRITEr", "initial_write")
    current_cheat = cheat
    current_bsx = bsx
    next_cheat = "next_fast" if cheat == "SNES_WR_end_fast" else "next_decode"
    next_bsx = "next_fast" if bsx == "SNES_WR_end_fast" else "next_decode"
    init_cheat = "initial_fast" if cheat == "SNES_WR_end_fast" else "initial_decode"
    init_bsx = "initial_fast" if bsx == "SNES_WR_end_fast" else "initial_decode"
    return f"""module {name}(
  input [7:0] SNES_WRITEr, input SNES_WRITE_IN,
  output [7:0] next_write, output current_cheat, current_bsx,
  output next_cheat, next_bsx, initial_cheat, initial_bsx
);
localparam [7:0] initial_write = {source_init};
wire SNES_WR_end = {source_decode};
// This is the inductive equality premise for the separate register's current Q.
wire SNES_WR_end_fast = SNES_WR_end;
assign next_write = {source_shift};
wire next_decode = {next_decode};
wire initial_decode = {init_decode};
wire next_fast = {fast_next};
wire initial_fast = {fast_init};
assign current_cheat = {current_cheat};
assign current_bsx = {current_bsx};
assign next_cheat = {next_cheat};
assign next_bsx = {next_bsx};
assign initial_cheat = {init_cheat};
assign initial_bsx = {init_bsx};
endmodule
"""


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-basex-strobe-experiment.py SOURCE_DIR OUTPUT_DIR")
    source_dir, output = map(Path, sys.argv[1:])
    original, cheat_source, bsx_source = (
        read_pinned(source_dir / name) for name in ("main.v", "cheat.v", "bsx.v")
    )
    for fragment in (SHIFT_INIT, SHIFT_UPDATE, SHIFT_BLOCK, ORIGINAL_STROBE):
        unique(original, fragment)
    if re.search(r"\bSNES_WR_end_fast\b", original):
        raise SystemExit("Fast-strobe name is already used")
    if original.count("SNES_WRITEr <=") != 1:
        raise SystemExit("Unexpected write-shift assignment")
    for module, name, clk_port in (("cheat", "snes_cheat", "clk"), ("bsx", "snes_bsx", "clkin")):
        if port_value(original, module, name, clk_port) != "CLK2":
            raise SystemExit(f"Unexpected {name} clock")
    if port_value(original, "cheat", "snes_cheat", "SNES_wr_strobe") != "SNES_WR_end":
        raise SystemExit("Unexpected original cheat strobe")
    if port_value(original, "bsx", "snes_bsx", "reg_we_rising") != "SNES_WR_end":
        raise SystemExit("Unexpected original BSX strobe")
    # The two source blobs were manually reviewed: all strobe-dependent effects
    # in these components are in posedge clk/clkin blocks. Fail closed on drift.
    if len(re.findall(r"\bSNES_wr_strobe\b", cheat_source)) != 3:
        raise SystemExit("Unexpected direct cheat-strobe references")
    if len(re.findall(r"\bsnescmd_wr_strobe\b", cheat_source)) != 4:
        raise SystemExit("Unexpected derived cheat-strobe references")
    if len(re.findall(r"\breg_we_rising\b", bsx_source)) != 4:
        raise SystemExit("Unexpected BSX-strobe references")

    candidate = original.replace(ORIGINAL_STROBE, ORIGINAL_STROBE + "\n" + RETIME_BLOCK, 1)
    for module, name, port in (("cheat", "snes_cheat", "SNES_wr_strobe"), ("bsx", "snes_bsx", "reg_we_rising")):
        candidate = replace_instance_port(candidate, module, name, port, GUARDED_PORT.format(port=port))
    recovered = candidate.replace(ORIGINAL_STROBE + "\n" + RETIME_BLOCK, ORIGINAL_STROBE, 1)
    for module, name, port in (("cheat", "snes_cheat", "SNES_wr_strobe"), ("bsx", "snes_bsx", "reg_we_rising")):
        fragment = GUARDED_PORT.format(port=port)
        unique(instance(recovered, module, name), fragment)
        recovered = recovered.replace(fragment, f"  .{port}(SNES_WR_end),", 1)
    if recovered != original:
        raise SystemExit("Candidate changed source outside the reviewed register and two ports")

    non_targets = (set(), {"MK2"}, {"MK3"}, {"MK3", "BASE_EXT"},
                   {"MK2", "BOOTLEG"}, {"MK2", "MK2_DEBUG"})
    for defines in non_targets:
        if compact(configured(original, defines)) != compact(configured(candidate, defines)):
            raise SystemExit(f"Non-target configuration changed: {sorted(defines)}")
    target_original = configured(original, {"MK2", "BASE_EXT"})
    target_candidate = configured(candidate, {"MK2", "BASE_EXT"})
    for module, name, port in (("cheat", "snes_cheat", "SNES_wr_strobe"), ("bsx", "snes_bsx", "reg_we_rising")):
        if port_value(target_candidate, module, name, port) != "SNES_WR_end_fast":
            raise SystemExit(f"Candidate does not connect {name}.{port}")

    source_init = SHIFT_INIT.split(" = ", 1)[1].removesuffix(";")
    source_shift = SHIFT_UPDATE.split(" <= ", 1)[1].removesuffix(";")
    source_decode = ORIGINAL_STROBE.split(" = ", 1)[1].removesuffix(";")
    init_match = re.search(r"reg SNES_WR_end_fast = ([^;]+);", target_candidate)
    next_match = re.search(r"always @\(posedge CLK2\) SNES_WR_end_fast <= ([^;]+);", target_candidate)
    if not init_match or not next_match:
        raise SystemExit("Fast register initialization or transition not found")
    fast_init, fast_next = init_match.group(1), next_match.group(1)
    gold = projected_model("gold", target_original, source_init, source_shift, source_decode, fast_init, fast_next)
    gate = projected_model("gate", target_candidate, source_init, source_shift, source_decode, fast_init, fast_next)
    mutations = {
        "bad-index": ("wire next_fast = (SNES_WRITEr[5:0]", "wire next_fast = (SNES_WRITEr[6:1]"),
        "bad-init": ("wire initial_fast = 1'b0;", "wire initial_fast = 1'b1;"),
        "bad-polarity": ("wire next_fast = (", "wire next_fast = ~("),
        "bad-consumer": ("assign current_cheat = SNES_WR_end_fast;", "assign current_cheat = ~SNES_WR_end_fast;"),
    }
    files = {"original-main.v": original, "candidate-main.v": candidate, "gold.v": gold, "gate.v": gate}
    for name, (before, after) in mutations.items():
        unique(gate, before)
        files[name + ".v"] = gate.replace(before, after, 1)
    output.mkdir(parents=True, exist_ok=True)
    checksums = []
    for name, content in files.items():
        data = content.encode("utf-8")
        (output / name).write_bytes(data)
        checksums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-main.v", "candidate-main.v")), encoding="utf-8")
    print("Pinned main, cheat and BSX source blobs; reviewed consumers share CLK2.")
    print("Candidate recovers exact original source and preserves six non-target configurations.")
    print("Prepared initialized-state and universal binary transition projections with four mutations.")
    print("This component boundary proof does not establish hardware behavior or native timing.")


if __name__ == "__main__":
    main()
