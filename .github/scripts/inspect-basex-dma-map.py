#!/usr/bin/env python3
"""Hosted-only bounded physical evidence from a retained failed basex map.

This is neither the original baseline nor a routed or timing-passing design.
Names and physical predecessor layers do not prove an entire logical cone.
"""
import importlib.util
import re
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "retained_xdl", Path(__file__).with_name("inspect-dsp-retained-map.py")
)
xdl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xdl)

TARGETS = (
    "snes_dma/pending",
    "snes_dma/overrun_r",
    "snes_dma/shadow_src_11",
    "snes_dma/shadow_dst_11",
    "snes_dma/shadow_len_11",
)
OBSERVED = re.compile(
    r"^(?:MCU_DMA_ACTIVE|snes_dma/(?:op_kick[^/]*|pending_not[^/]*|"
    r"shadow_(?:src|dst|len)_not[^/]*|N31))$"
)


def bind(instances, target):
    pattern = re.compile(r"(?<!\S)FF([XY]):" + re.escape(target) + r":#FF(?=\s|$)")
    hits = [(comp, match.group(1)) for comp, statement in instances.items()
            for match in pattern.finditer(statement)]
    if len(hits) != 1:
        raise ValueError(f"Expected one exact FF binding for {target}: {hits}")
    return hits[0]


def driver(instances, statement):
    pins = [(comp, pin) for kind, comp, pin in xdl.net_pins(statement)
            if kind == "outpin"]
    if len(pins) != 1 or pins[0][0] not in instances:
        raise ValueError(f"Missing or ambiguous physical driver: {pins}")
    return pins[0]


def controls():
    xdl.fixture_checks()
    fixture = (
        'inst "shared" "SLICEL", placed R1C1 SLICE_X1Y1, cfg " '
        'FFX:snes_dma/pending:#FF FFY:snes_dma/overrun_r:#FF ";\n'
        'inst "drive" "SLICEL", placed R1C2 SLICE_X1Y2, cfg " F:logic:#LUT:D=A1 ";\n'
        'net "ce", outpin "drive" X, inpin "shared" CE;\n'
    )
    instances, nets = xdl.parse(fixture)
    if [bind(instances, t) for t in TARGETS[:2]] != [("shared", "X"), ("shared", "Y")]:
        raise ValueError("Shared-COMP distinct-FF positive failed")
    if driver(instances, nets["ce"]) != ("drive", "X"):
        raise ValueError("Driver positive failed")
    negatives = {
        "missing FF": lambda: bind(instances, TARGETS[2]),
        "duplicate FF across COMPs": lambda: bind({**instances, "other": instances["shared"]}, TARGETS[0]),
        "duplicate FF within COMP": lambda: bind({"shared": instances["shared"].replace(TARGETS[1], TARGETS[0])}, TARGETS[0]),
        "LUT is not FF": lambda: bind({"drive": instances["drive"].replace("logic", TARGETS[0])}, TARGETS[0]),
        "missing driver": lambda: driver(instances, nets["ce"].replace('outpin "drive" X,', "")),
        "duplicate driver": lambda: driver(instances, nets["ce"].replace(";", ', outpin "shared" Y;')),
        "unknown driver": lambda: driver({"shared": instances["shared"]}, nets["ce"]),
    }
    for name, control in negatives.items():
        try:
            control()
        except ValueError:
            print(f"Rejected synthetic DMA binding control: {name}")
        else:
            raise ValueError(f"Accepted invalid synthetic control: {name}")
    print("Synthetic controls are parser checks, never actual design evidence.")


def inspect(path):
    if path.stat().st_size > 32_000_000:
        raise ValueError("Full XDL exceeds 32 MB input bound")
    text = path.read_text(encoding="utf-8", errors="strict")
    if not re.search(r"\bxc3s400pq208-4\b", text):
        raise ValueError("Expected xc3s400pq208-4 identity missing")
    instances, nets = xdl.parse(text)
    if len(instances) < 100 or len(nets) < 100:
        raise ValueError("Unexpectedly small full mapped design")
    print("FAILED late-priority candidate 40860299285; NOT original baseline or routed timing.")
    print(f"Parsed {len(instances)} complete instances/{len(nets)} complete nets")
    selected, selected_nets, frontier, errors = set(), set(), set(), []
    for target in TARGETS:
        try:
            comp, slot = bind(instances, target)
            selected.add(comp)
            ce_name, ce_statement = xdl.ce_for(nets, comp)
            ce_driver = driver(instances, ce_statement)
            selected_nets.add(ce_name)
            frontier.add(ce_driver[0])
            print(f"Actual target {target}: COMP={comp}, slot=FF{slot}, CE={ce_name}, driver={ce_driver}")
        except ValueError as error:
            errors.append(f"{target}: {error}")
    observed = sorted(name for name in nets if OBSERVED.fullmatch(name))
    print(f"Observed candidate control-net names: {observed!r}; no baseline correspondence inferred")
    for name in observed:
        selected_nets.add(name)
        try:
            frontier.add(driver(instances, nets[name])[0])
        except ValueError as error:
            errors.append(f"{name}: {error}")
    for depth in range(3):
        print(f"Physical predecessor layer {depth}: {len(frontier)} COMPs")
        selected.update(frontier)
        following = set()
        for name, statement in nets.items():
            pins = xdl.net_pins(statement)
            if any(kind == "inpin" and comp in frontier and pin in xdl.INPUT_PINS
                   for kind, comp, pin in pins):
                selected_nets.add(name)
                try:
                    following.add(driver(instances, statement)[0])
                except ValueError as error:
                    errors.append(f"Layer {depth}/{name}: {error}")
        frontier = following - selected
    selected.update(frontier)
    # Include complete incident nets so every retained cfg can be inspected
    # against its actual pins, including packed companion logic and clocks.
    for name, statement in nets.items():
        if any(comp in selected for kind, comp, pin in xdl.net_pins(statement)):
            selected_nets.add(name)
    records = [instances[name] for name in sorted(selected)]
    records += [nets[name] for name in sorted(selected_nets)]
    raw_bytes = sum(len(record.encode("utf-8")) + 1 for record in records)
    if not selected or len(selected) > 400 or len(selected_nets) > 700 or raw_bytes > 3_000_000:
        raise ValueError(f"Bound exceeded; no truncation accepted: {len(selected)} instances/{len(selected_nets)} nets/{raw_bytes} bytes")
    print(f"Retain {len(selected)} complete instances/{len(selected_nets)} complete nets/{raw_bytes} raw bytes")
    print("BEGIN COMPLETE BOUNDED RAW STATEMENTS")
    for record in records:
        print(record)
    print("END COMPLETE BOUNDED RAW STATEMENTS")
    print("Physical COMP names do not imply logical coupling. CE pin loads are not FF counts.")
    print("Three specified predecessor layers include packed companion logic; not a complete logical cone, baseline, routing benefit, sequential equivalence or timing pass.")
    if errors:
        raise ValueError("Inspection incomplete after raw retention:\n" + "\n".join(errors))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: inspect-basex-dma-map.py XDL|--self-check")
    controls()
    if sys.argv[1] != "--self-check":
        inspect(Path(sys.argv[1]))
