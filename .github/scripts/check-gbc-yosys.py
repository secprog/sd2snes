"""Hosted, opt-in area experiment. Does not replace ISE or publish a bitstream."""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
core = root / "verilog/sd2snes_gbc"
report = Path(sys.argv[1]).resolve()
report.mkdir(parents=True, exist_ok=True)
makefile = (core / "Makefile").read_text()
rtl = re.search(r"^VSRC = (.+)$", makefile, re.M)[1].split()
ip = re.search(r"^COMMON_IP = (.+)$", makefile, re.M)[1].split()
if set(ip) != {"vram", "snescmd_buf", "oam"}:
    raise RuntimeError("CoreGen inventory changed; review block-RAM accounting")
sources = [core / name for name in rtl]
wrappers = [core.parent / "sd2snes_sgb/ip/mk2" / (name + ".v") for name in ip]
for source in sources + wrappers:
    if not source.is_file():
        raise FileNotFoundError(source)

def quoted(path):
    return '"' + str(path) + '"'

commands = ["read_verilog -lib " + " ".join(map(quoted, wrappers)),
            "read_verilog -sv -DMK2 -I" + quoted(core) + " " + " ".join(map(quoted, sources)),
            "synth_xilinx -top main -family xc3s -flatten -edif " + quoted(report / "main.edf"),
            "check -assert", "stat -tech xilinx",
            "write_json " + quoted(report / "main.json")]
script = report / "synthesis.ys"
script.write_text("\n".join(commands) + "\n")
version = subprocess.check_output(["yosys", "-V"], text=True)
(report / "tool-version.txt").write_text(version)
subprocess.run(["yosys", "-l", str(report / "synthesis.log"), "-s", str(script)],
               cwd=core, check=True)
design = json.loads((report / "main.json").read_text())
cells = Counter(cell["type"] for cell in design["modules"]["main"]["cells"].values())
if {name: cells[name] for name in ip} != {"vram": 2, "snescmd_buf": 1, "oam": 1}:
    raise RuntimeError("CoreGen instance count changed; cannot compare RAM use")
summary = {"tool": version.strip(), "cells": dict(sorted(cells.items())),
           "coregen_block_rams_not_in_cell_list": 10,
           "limitations": "Mapping estimate only. CoreGen wrappers are black boxes; two VRAMs use eight RAMB16s, OAM and SNESCMD use one each. No native mapping, timing, netlist equivalence or console qualification."}
(report / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
