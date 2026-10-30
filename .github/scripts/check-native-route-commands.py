#!/usr/bin/env python3
"""Check one original route recipe, separating its console header bound to the same-run TWR command.

This is a command-count gate only. Native exits, PAR0/TRACE0 and all input gates
remain independently mandatory. Run controls and this checker only on hosted CI.
"""

import json
import re
import shlex
import sys
from pathlib import Path

BIN = "/opt/Xilinx/14.7/ISE_DS/ISE/bin/lin64/"
TRACE_ARGS = ["-v", "10", "-n", "10", "-u", "10", "-fastpaths", "main.ncd", "main.pcf", "-o", "main.twr"]
TOOLS = re.compile(r"^\s*(/\S*/(par|trce|coregen|xst|ngdbuild|map|bitgen))(?=\s|$)")
MENTION = re.compile(r'/\S*/(?:par|trce|coregen|xst|ngdbuild|map|bitgen)(?=[\s\'"]|$)')


def console_header_from_twr(twr):
    lines = twr.splitlines()
    separator = "-" * 80
    if len(lines) < 17 or lines[0] != separator or lines[1] != "Release 14.7 Trace  (lin64)":
        raise ValueError("Missing authentic ISE14.7 TRACE header")
    end = next((i for i, line in enumerate(lines[1:], 1) if line == separator), None)
    if end is None or end != 16:
        raise ValueError("Incomplete or unexpected TRACE header boundary")
    args = shlex.split(" ".join(lines[4:6]))
    if args != [BIN + "unwrapped/trce"] + TRACE_ARGS:
        raise ValueError("TRACE header arguments differ from original recipe")
    if lines[7] != "Design file:              main.ncd" or lines[8] != "Physical constraint file: main.pcf":
        raise ValueError("TRACE header input files differ")
    if not lines[9].startswith("Device,package,speed:     xc3s400,pq208,-4 "):
        raise ValueError("TRACE header device differs")
    device = lines[9].replace("Device,package,speed:     xc3s400,pq208,-4 ",
                              "Device,speed:             xc3s400,-4 ", 1)
    console = [separator, lines[1], lines[2], "", lines[4], lines[5], "", "",
               lines[7], lines[8], device,
               "Report level:             verbose report, limited to 10 items per constraint",
               "                          unconstrained path report, limited to 10 items",
               separator]
    return "\n".join(console)


def check_text(route, twr, seed):
    if seed not in (46, 68):
        raise ValueError("Unexpected explicitly selected seed")
    header = console_header_from_twr(twr)
    if route.count(header) != 1:
        raise ValueError("Missing or repeated authentic console TRACE command header")
    without_header = route.replace(header, "", 1)
    expected = {
        "par": ["-w", "-ol", "high", "-xe", "c", "-t", str(seed), "main_map.ncd", "main.ncd", "main.pcf"],
        "trce": TRACE_ARGS,
    }
    observed = {"par": [], "trce": []}
    for line in without_header.splitlines():
        match = TOOLS.match(line)
        if not match:
            if MENTION.search(line):
                raise ValueError("Unclassified possible tool invocation outside exact console header")
            continue
        executable, tool = match.groups()
        if tool not in observed:
            raise ValueError("Unexpected generation/synthesis/MAP/bitgen during route continuation")
        if executable != BIN + tool:
            raise ValueError("Unexplained wrapped/unwrapped or foreign tool invocation")
        parts = line.split(" || ")
        if len(parts) != 2 or parts[1] != tool + "_status=$?; " + chr(92):
            raise ValueError("Unexpected recipe status handler or inline command")
        args = shlex.split(parts[0].strip())
        if args != [executable] + expected[tool]:
            raise ValueError(f"Unexpected {tool} recipe arguments")
        observed[tool].append(line)
    if any(len(commands) != 1 for commands in observed.values()):
        raise ValueError("Missing or repeated original PAR/TRACE recipe")
    return {"original_par_recipes": 1, "original_trace_recipes": 1,
            "same_run_trace_command_headers": 1, "seed": seed,
            "timing_pass_inferred": False, "commands": observed}


if __name__ == "__main__":
    route, twr, seed = sys.argv[1:]
    print(json.dumps(check_text(Path(route).read_text(encoding="utf-8", errors="strict"),
                               Path(twr).read_text(encoding="utf-8", errors="strict"), int(seed)), indent=2))
