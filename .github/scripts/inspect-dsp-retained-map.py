#!/usr/bin/env python3
"""Collect bounded, raw XDL evidence from one retained DSPx mapped design.

This is an inspection aid, not a timing check or a proof of logical connectivity.
All checks and fixtures run on the hosted runner.
"""

import re
import sys
from pathlib import Path


TARGETS = (
    "snes_dspx/stack<1>_9",
    "snes_dspx/stack<8>_6",
    "snes_dspx/stack<8>_7",
    "snes_dspx/stack<9>_3",
    "snes_dspx/stack<9>_6",
)
INDEX_NAMES = re.compile(r"ss_wstk_idx|ss_stk_idx")
PIN = re.compile(r'\b(outpin|inpin)\s+"([^"\n]+)"\s+([A-Za-z0-9_]+)')
INPUT_PINS = {f"{lut}{i}" for lut in "FG" for i in range(1, 5)} | {
    "BX", "BY", "CIN", "FXINA", "FXINB", "CE", "SR"
}


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


def bind(instances, name):
    pattern = re.compile(r'(?<!\S)FF[XY]:' + re.escape(name) + r':#FF(?=\s|$)')
    hits = [comp for comp, statement in instances.items() if pattern.search(statement)]
    if len(hits) != 1:
        raise ValueError(f"Expected exactly one FF instance for {name}, found {hits}")
    return hits[0]


def net_pins(statement):
    return PIN.findall(statement)


def ce_for(nets, comp):
    hits = [(name, statement) for name, statement in nets.items()
            if ("inpin", comp, "CE") in net_pins(statement)]
    if len(hits) != 1:
        raise ValueError(f"Expected exactly one CE net for {comp}, found {len(hits)}")
    return hits[0]


def fixture_checks():
    fixture = '''
inst "comp" "SLICEL", placed R1C1 SLICE_X1Y1,
  cfg " FFX:snes_dspx/stack<1>_9:#FF FFY:snes_dspx/stack<8>_6:#FF ";
inst "drive" "SLICEL", placed R1C2 SLICE_X1Y2, cfg " F:logic:#LUT:D=A1 ";
net "ce", outpin "drive" X, inpin "comp" CE;
'''
    instances, nets = parse(fixture)
    if bind(instances, TARGETS[0]) != "comp" or bind(instances, TARGETS[1]) != "comp":
        raise ValueError("Shared-component positive fixture failed")
    if ce_for(nets, "comp")[0] != "ce":
        raise ValueError("CE positive fixture failed")
    negatives = (
        lambda: bind(instances, "snes_dspx/missing"),
        lambda: bind({**instances, "duplicate": instances["comp"]}, TARGETS[0]),
        lambda: bind({"lut": 'inst "lut" "SLICEL", cfg " F:snes_dspx/stack<1>_9:#LUT:D=A1 ";'}, TARGETS[0]),
        lambda: ce_for(nets, "missing"),
        lambda: ce_for({**nets, "other": nets["ce"]}, "comp"),
        lambda: parse('inst "broken" "SLICEL", cfg " F:X:#LUT:D=A1 "'),
    )
    for number, control in enumerate(negatives, 1):
        try:
            control()
        except ValueError:
            print(f"Rejected synthetic negative fixture {number}")
        else:
            raise ValueError(f"Synthetic negative fixture {number} was accepted")
    print("Accepted shared-component and CE synthetic positive fixtures")


def inspect(path):
    text = Path(path).read_text(encoding="utf-8", errors="strict")
    instances, nets = parse(text)
    if len(instances) < 100 or len(nets) < 100:
        raise ValueError("Mapped design unexpectedly small")
    if "cc_wr_hit_fast" not in text:
        raise ValueError("Expected event-write mapped identity missing")
    print("Retained failed event-write candidate only; this is not the original baseline.")
    print("Mapped, not routed, NCD. Bounded physical adjacency is not logical or timing proof.")
    print(f"Parsed {len(instances)} instance statements and {len(nets)} net statements")
    selected_instances, selected_nets = set(), set()
    frontier = set()
    for target in TARGETS:
        comp = bind(instances, target)
        net_name, net = ce_for(nets, comp)
        drivers = [(name, pin) for kind, name, pin in net_pins(net) if kind == "outpin"]
        if len(drivers) != 1 or drivers[0][0] not in instances:
            raise ValueError(f"Ambiguous or missing CE driver for {target}: {drivers}")
        print(f"Target {target}: COMP {comp}; CE net {net_name}; driver {drivers[0]}")
        selected_instances.add(comp)
        selected_nets.add(net_name)
        frontier.add(drivers[0][0])
    for depth in range(3):
        selected_instances.update(frontier)
        following = set()
        for name, statement in nets.items():
            pins = net_pins(statement)
            if any(kind == "inpin" and comp in frontier and pin in INPUT_PINS
                   for kind, comp, pin in pins):
                selected_nets.add(name)
                following.update(comp for kind, comp, _ in pins
                                 if kind == "outpin" and comp in instances)
        print(f"Predecessor depth {depth}: {len(frontier)} components")
        frontier = following - selected_instances
    index_instances = {name for name, statement in instances.items() if INDEX_NAMES.search(statement)}
    index_nets = {name for name, statement in nets.items() if INDEX_NAMES.search(statement)}
    selected_instances.update(index_instances)
    selected_nets.update(index_nets)
    print(f"Exact index-name matches: {len(index_instances)} instance statements, {len(index_nets)} net statements")
    print("A missing source name does not establish that its logic was removed.")
    print("Predecessor traversal follows specified physical input pins only; it is not exhaustive.")
    if len(selected_instances) > 300 or len(selected_nets) > 500:
        raise ValueError("Bounded excerpt is too large; no truncated result accepted")
    records = [instances[name] for name in sorted(selected_instances)]
    records += [nets[name] for name in sorted(selected_nets)]
    if sum(len(record) for record in records) > 3_000_000:
        raise ValueError("Bounded excerpt exceeds 3 MB; no truncated result accepted")
    for record in records:
        print("\n" + record)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: inspect-dsp-retained-map.py XDL|--self-check")
    fixture_checks()
    if sys.argv[1] != "--self-check":
        inspect(sys.argv[1])
