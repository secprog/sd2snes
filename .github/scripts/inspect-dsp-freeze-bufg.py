#!/usr/bin/env python3
"""Inspect a mapped DSPx freeze buffer; this is not a timing proof."""

import re
import sys
from pathlib import Path


PIN = re.compile(r'\b(outpin|inpin)\s+"([^"\n]+)"\s+([A-Za-z0-9_]+)')
FREEZE = "snes_dspx/ss_frozen"
BUFFER = "dspx_freeze_bufg"


def parse(text):
    starts = re.findall(r'(?m)^\s*(inst|net)\s+"', text)
    statements = re.findall(r'(?ms)^\s*(?:inst|net)\s+".*?;', text)
    if not starts or len(starts) != len(statements):
        raise ValueError("Missing or incomplete XDL statements")
    instances, nets = {}, {}
    for statement in statements:
        head = re.match(r'\s*(inst|net)\s+"([^"\n]+)"', statement)
        if not head:
            raise ValueError("Unrecognized XDL statement")
        kind, name = head.groups()
        target = instances if kind == "inst" else nets
        if name in target:
            raise ValueError(f"Duplicate {kind}: {name}")
        target[name] = statement.strip()
    return instances, nets


def inspect(text, minimum=100):
    instances, nets = parse(text)
    if len(instances) < minimum or len(nets) < minimum:
        raise ValueError("Mapped design unexpectedly small")
    buf = [(name, stmt) for name, stmt in instances.items()
           if BUFFER in name and re.match(r'inst\s+"[^"]+"\s+"BUFGMUX"', stmt)]
    if len(buf) != 1 or not re.search(r'\bplaced\s+\S+\s+BUFGMUX\S+', buf[0][1]):
        raise ValueError("Named placed BUFGMUX is missing or ambiguous")
    buf_name, buf_stmt = buf[0]
    ff_pattern = re.compile(r'(?<!\S)FF([XY]):' + re.escape(FREEZE) + r':#FF(?=\s|$)')
    ff_hits = [(name, stmt, match.group(1)) for name, stmt in instances.items()
               for match in ff_pattern.finditer(stmt)]
    if len(ff_hits) != 1:
        raise ValueError("Named freeze FF is missing or ambiguous")
    ff_name, ff_stmt, slot = ff_hits[0]
    if not re.search(r'(?<!\S)FF' + slot + r'_INIT_ATTR::INIT0(?=\s|$)', ff_stmt):
        raise ValueError("Mapped freeze FF is missing INIT0")
    ff_outpin = slot + "Q"
    input_nets = []
    output_nets = []
    clock_nets = []
    for name, stmt in nets.items():
        pins = PIN.findall(stmt)
        if ("inpin", ff_name, "CLK") in pins:
            clock_nets.append((name, stmt, pins))
        if ("outpin", ff_name, ff_outpin) in pins and any(
            kind == "inpin" and comp == buf_name and pin in {"I0", "I1"}
            for kind, comp, pin in pins
        ):
            input_nets.append((name, stmt))
        if ("outpin", buf_name, "O") in pins:
            output_nets.append((name, stmt, pins))
    if len(input_nets) != 1 or len(output_nets) != 1:
        raise ValueError("Freeze FF to BUFG or BUFG output net is missing or ambiguous")
    if [(comp, pin) for kind, comp, pin in PIN.findall(input_nets[0][1])
        if kind == "outpin"] != [(ff_name, ff_outpin)]:
        raise ValueError("The BUFG input net has an unexpected driver")
    if len(clock_nets) != 1 or clock_nets[0][0] != "CLK2" or [
        (comp, pin) for kind, comp, pin in clock_nets[0][2] if kind == "outpin"
    ] != [("CLK2_BUFG", "O")]:
        raise ValueError("Freeze FF is not visibly clocked by the original CLK2 buffer")
    out_name, out_stmt, pins = output_nets[0]
    if not re.search(r'ss_frozen_global|dspx_freeze_bufg', out_name):
        raise ValueError("Named buffer output net is missing; mapping inconclusive")
    drivers = [(comp, pin) for kind, comp, pin in pins if kind == "outpin"]
    loads = [(comp, pin) for kind, comp, pin in pins if kind == "inpin"]
    if drivers != [(buf_name, "O")] or not loads:
        raise ValueError("Unexpected buffer-output driver or empty load list")
    clocks = [(comp, pin) for comp, pin in loads
              if pin.upper() in {"C", "CK"} or pin.upper().startswith("CLK")]
    if clocks:
        raise ValueError(f"Buffer output drives clock pins: {clocks!r}")
    selected = [ff_stmt, buf_stmt, input_nets[0][1], out_stmt, clock_nets[0][1]]
    if sum(len(item) for item in selected) > 1_000_000:
        raise ValueError("Mapped evidence exceeds the bounded report size")
    print(f"Parsed {len(instances)} instances and {len(nets)} nets.")
    print(f"INIT0 freeze FF {ff_name} on CLK2, {ff_outpin} drives BUFGMUX {buf_name}; "
          f"output net {out_name} has {len(loads)} non-clock input pins.")
    print("This is candidate mapped connectivity, not routed timing or sequential equivalence.")
    for item in selected:
        print("\n" + item)


def controls():
    fixture = '''
inst "freeze_comp" "SLICEL", placed R1C1 SLICE_X1Y1, cfg " FFX:snes_dspx/ss_frozen:#FF FFX_INIT_ATTR::INIT0 ";
inst "snes_dspx/dspx_freeze_bufg" "BUFGMUX", placed R1C1 BUFGMUX0, cfg "";
inst "consumer" "SLICEL", placed R1C2 SLICE_X1Y2, cfg "";
inst "CLK2_BUFG" "BUFGMUX", placed R1C3 BUFGMUX1, cfg "";
net "freeze_q", outpin "freeze_comp" XQ, inpin "snes_dspx/dspx_freeze_bufg" I0;
net "snes_dspx/ss_frozen_global", outpin "snes_dspx/dspx_freeze_bufg" O, inpin "consumer" F1;
net "CLK2", outpin "CLK2_BUFG" O, inpin "freeze_comp" CLK;
'''
    inspect(fixture, minimum=1)
    negatives = (
        fixture.replace('"BUFGMUX", placed', '"SLICEL", placed'),
        fixture.replace('placed R1C1 BUFGMUX0', 'unplaced'),
        fixture.replace('FFX:snes_dspx/ss_frozen:#FF', 'FFY:snes_dspx/ss_frozen:#FF'),
        fixture.replace('FFX_INIT_ATTR::INIT0', 'FFX_INIT_ATTR::INIT1'),
        fixture.replace('net "CLK2"', 'net "OTHER_CLK"'),
        fixture.replace('inpin "snes_dspx/dspx_freeze_bufg" I0', 'inpin "consumer" F2'),
        fixture.replace('outpin "freeze_comp" XQ,', 'outpin "freeze_comp" XQ, outpin "consumer" X,'),
        fixture.replace('outpin "snes_dspx/dspx_freeze_bufg" O', 'outpin "consumer" X'),
        fixture.replace('inpin "consumer" F1', 'inpin "consumer" CLK'),
        fixture.replace('inpin "consumer" F1', ''),
        fixture.replace('net "snes_dspx/ss_frozen_global"', 'net "unnamed"'),
        fixture + '\ninst "broken" "SLICEL", cfg "',
        fixture + '\n' + fixture.splitlines()[2],
    )
    for number, negative in enumerate(negatives, 1):
        try:
            inspect(negative, minimum=1)
        except ValueError:
            print(f"Rejected synthetic negative fixture {number}")
        else:
            raise ValueError(f"Synthetic negative fixture {number} was accepted")
    print("All synthetic parser controls passed; they are not timing evidence.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: inspect-dsp-freeze-bufg.py XDL|--self-check")
    controls()
    if sys.argv[1] != "--self-check":
        inspect(Path(sys.argv[1]).read_text(encoding="utf-8", errors="strict"))
