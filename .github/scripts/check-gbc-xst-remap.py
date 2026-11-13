"""Hosted logic-remapping diagnostic, preserving XST's RAM/FF/carry boundaries.

This deliberately emits no FPGA image. The native artifact and its provenance
remain the reference; a successful logic proof is not a place/route result.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
netlist = Path(sys.argv[1]).resolve()
report = Path(sys.argv[2]).resolve()
report.mkdir(parents=True, exist_ok=True)


def run(name, commands):
    script = report / (name + ".ys")
    script.write_text("\n".join(commands) + "\n")
    subprocess.run(["yosys", "-l", str(report / (name + ".log")), "-s", str(script)],
                   check=True, timeout=300)


def quote(path):
    return '"' + str(path) + '"'


wrappers = [root / "verilog/sd2snes_sgb/ip/mk2" / (n + ".v")
            for n in ("vram", "snescmd_buf", "oam")]
# BUFGP is the legacy combined input/clock buffer used by XST. It is a fixed
# boundary in this experiment; no clock primitive is remapped or simulated.
extra = report / "legacy.v"
extra.write_text("(* blackbox *) module BUFGP(input I, output O); endmodule\n")
run("read", ["read_verilog -lib +/xilinx/cells_sim.v +/xilinx/cells_xtra.v",
             "read_verilog -lib " + " ".join(map(quote, wrappers + [extra])),
             "read_verilog " + quote(netlist), "hierarchy -top main",
             "blackbox =A:whitebox",
             "write_json " + quote(report / "native.json")])
native = json.loads((report / "native.json").read_text())["modules"]["main"]
native_counts = Counter(c["type"] for c in native["cells"].values())
summaries = {}
for profile, remap_mux, abc_width in (("fixed-mux", False, "4"),
                                      ("lut4", True, "4"),
                                      ("wide-lut", True, "4:8")):
    logic_types = {"LUT1", "LUT2", "LUT3", "LUT4", "INV"}
    if remap_mux:
        logic_types |= {"MUXF5", "MUXF6", "MUXF7", "MUXF8"}
    logic = [c for c in native["cells"].values() if c["type"] in logic_types]
    driven = {bit for c in logic for bit in c["connections"]["O"] if isinstance(bit, int)}
    used = {bit for c in logic for port, bits in c["connections"].items() if port != "O"
            for bit in bits if isinstance(bit, int)}
    boundary = {bit for c in native["cells"].values() if c["type"] not in logic_types
                for bits in c["connections"].values() for bit in bits if isinstance(bit, int)}
    boundary |= {bit for port in native["ports"].values() for bit in port["bits"]
                 if isinstance(bit, int)}
    constants = {bit: str(int(c["type"] == "VCC")) for c in native["cells"].values()
                 if c["type"] in ("VCC", "GND") for bits in c["connections"].values()
                 for bit in bits if isinstance(bit, int)}
    inputs, outputs = sorted(used - driven - constants.keys()), sorted(driven & boundary)
    all_bits = sorted(driven | used)

    def signal(bit):
        return "n" + str(bit) if isinstance(bit, int) else "1'b" + bit

    lines = [f"module gbc_logic(input [{len(inputs)-1}:0] i, output [{len(outputs)-1}:0] o);"]
    lines += ["wire " + ",".join(signal(b) for b in all_bits) + ";"]
    lines += [f"assign {signal(bit)}=i[{idx}];" for idx, bit in enumerate(inputs)]
    lines += [f"assign o[{idx}]={signal(bit)};" for idx, bit in enumerate(outputs)]
    lines += [f"assign {signal(bit)}=1'b{value};" for bit, value in constants.items() if bit in used]
    for c in logic:
        ports = {p: signal(bits[0]) for p, bits in c["connections"].items()}
        if c["type"].startswith("LUT"):
            width = int(c["type"][3:])
            init = c["parameters"]["INIT"]
            address = "{" + ",".join(ports["I" + str(n)] for n in reversed(range(width))) + "}"
            expression = f"({len(init)}'b{init} >> {address})"
        elif c["type"] == "INV":
            expression = "~" + ports["I"]
        else:
            expression = f"{ports['S']} ? {ports['I1']} : {ports['I0']}"
        lines.append(f"assign {ports['O']}={expression};")
    lines.append("endmodule")
    source = report / (profile + ".v")
    source.write_text("\n".join(lines) + "\n")
    # Compare at every fixed-macro input and top-level output. Sequential
    # state, carry chains, memories, clocking and I/O stay outside these cones.
    run(profile, ["read_verilog " + quote(source), "hierarchy -top gbc_logic",
                  "proc", "flatten", "opt", "techmap", "opt",
                  "design -save reference", "abc -lut " + abc_width, "clean",
                  "design -save mapped", "rename gbc_logic gate",
                  "design -copy-from reference -as gold gbc_logic",
                  "equiv_make gold gate equiv", "hierarchy -top equiv",
                  "equiv_simple", "equiv_status -assert",
                  "design -load mapped",
                  "techmap -map +/xilinx/lut_map.v -D LUT_WIDTH=4", "clean",
                  "write_json " + quote(report / (profile + ".json"))])
    result = json.loads((report / (profile + ".json")).read_text())["modules"]["gbc_logic"]
    cells = Counter(c["type"] for c in result["cells"].values())
    fixed = Counter(c["type"] for c in native["cells"].values() if c["type"] not in logic_types)
    summaries[profile] = {
        "native_sha256": hashlib.sha256(netlist.read_bytes()).hexdigest(),
        "native_cells": dict(sorted(native_counts.items())),
        "remapped_cells": dict(sorted(cells.items())),
        "fixed_cells": dict(sorted(fixed.items())),
        "combinational_equivalence": "proved at every fixed-macro input and top-level output",
        "limitations": "Diagnostic only; fixed macro boundaries, no native placement/timing or console validation.",
    }
    (report / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
print(json.dumps(summaries, indent=2))
