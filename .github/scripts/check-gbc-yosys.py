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

version = subprocess.check_output(["yosys", "-V"], text=True)
(report / "tool-version.txt").write_text(version)
# ABC9 is unsupported for LUT4 families in the hosted Yosys version. Compare
# its documented LUT4-only mapper instead; the ordinary flow allows LUT8s
# which are later decomposed into physical LUT4s and MUXF primitives.
summaries = {}
for name, options in (("lut4", "-nowidelut"),
                      ("lut4-no-carry", "-nowidelut -nocarry")):
    target = report / name
    target.mkdir(exist_ok=True)
    commands = ["read_verilog -lib " + " ".join(map(quoted, wrappers)),
                "read_verilog -sv -DMK2 -I" + quoted(core) + " " + " ".join(map(quoted, sources)),
                "synth_xilinx -top main -family xc3s -flatten -ise " + options
                + " -edif " + quoted(target / "main.edf"),
                "check -assert", "stat -tech xilinx",
                "write_json " + quoted(target / "main.json")]
    script = target / "synthesis.ys"
    script.write_text("\n".join(commands) + "\n")
    subprocess.run(["yosys", "-l", str(target / "synthesis.log"), "-s", str(script)],
                   cwd=core, check=True)
    design = json.loads((target / "main.json").read_text())
    cells = Counter(cell["type"] for cell in design["modules"]["main"]["cells"].values())
    if {ip_name: cells[ip_name] for ip_name in ip} != {"vram": 2, "snescmd_buf": 1, "oam": 1}:
        raise RuntimeError("CoreGen instance count changed; cannot compare RAM use")
    summary = {"tool": version.strip(), "options": options,
               "cells": dict(sorted(cells.items())),
               # Do not use stat's generic LC estimate as a Spartan-3 fit claim.
               "lut1_through_lut4_primitives": sum(cells[f"LUT{n}"] for n in range(1, 5)),
               "coregen_block_rams_not_in_cell_list": 10,
               "limitations": "Mapping diagnostic only. LUT primitives exclude RAM/SRL LUTs and INV placement cost. CoreGen wrappers are black boxes; two VRAMs use eight RAMB16s, OAM and SNESCMD use one each. No native mapping, timing, netlist equivalence or console qualification."}
    (target / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    summaries[name] = summary
(report / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
print(json.dumps(summaries, indent=2))
