#!/usr/bin/env python3
"""Bounded raw evidence from the retained, failed S-RTC basex mapped NCD.

This does not inspect the original baseline or a routed design. Physical slice
adjacency includes unrelated packed logic and is not a logical-cone proof.
Run the extractor and its synthetic controls only on the hosted runner.
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

TARGETS = ("snes_cheat/cheat_data_1_1", "snes_cheat/cheat_addr_1_3")
SITE = re.compile(r'\bplaced\s+\S+\s+(SLICE_X(\d+)Y(\d+))\b')


def bind(instances, target):
    pattern = re.compile(r'(?<!\S)FF([XY]):' + re.escape(target) + r':#FF(?=\s|$)')
    hits = [(comp, match.group(1)) for comp, statement in instances.items()
            for match in pattern.finditer(statement)]
    if len(hits) != 1:
        raise ValueError(f"Expected one exact FF binding for {target}: {hits}")
    return hits[0]


def site(statement):
    hits = SITE.findall(statement)
    if len(hits) != 1:
        raise ValueError("Expected one placed slice site")
    name, x, y = hits[0]
    return name, int(x), int(y)


def ce_driver(instances, nets, comp):
    net_name, statement = xdl.ce_for(nets, comp)
    drivers = [(name, pin) for kind, name, pin in xdl.net_pins(statement)
               if kind == "outpin"]
    if len(drivers) != 1 or drivers[0][0] not in instances:
        raise ValueError(f"Missing or ambiguous CE driver: {drivers}")
    site(instances[drivers[0][0]])
    return net_name, drivers[0]


def placed_slices(instances):
    result = {}
    for comp, statement in instances.items():
        if not re.match(r'inst\s+"[^"]+"\s+"SLICE[LM]"', statement):
            continue
        if not SITE.search(statement):
            continue
        name, x, y = site(statement)
        if name in result:
            raise ValueError(f"Two slice components occupy {name}")
        result[name] = (comp, x, y)
    return result


def controls():
    fixture = '''
inst "target" "SLICEL", placed R1C1 SLICE_X1Y1,
 cfg " FFX:snes_cheat/cheat_data_1_1:#FF FFY:snes_cheat/cheat_addr_1_3:#FF ";
inst "driver" "SLICEL", placed R1C2 SLICE_X2Y1, cfg " F:enable:#LUT:D=A1 ";
net "ce", outpin "driver" X, inpin "target" CE;
'''
    instances, nets = xdl.parse(fixture)
    if [bind(instances, target) for target in TARGETS] != [("target", "X"), ("target", "Y")]:
        raise ValueError("Shared-slice, distinct-FF positive control failed")
    if ce_driver(instances, nets, "target") != ("ce", ("driver", "X")):
        raise ValueError("CE driver positive control failed")
    if len(placed_slices(instances)) != 2:
        raise ValueError("Placed-slice positive control failed")
    negatives = {
        "missing FF": lambda: bind(instances, "missing"),
        "duplicate FF in another slice": lambda: bind({**instances, "other": instances["target"]}, TARGETS[0]),
        "duplicate FF in the same slice": lambda: bind({"target": instances["target"].replace(TARGETS[1], TARGETS[0])}, TARGETS[0]),
        "LUT name is not FF": lambda: bind({"driver": instances["driver"].replace("enable", TARGETS[0])}, TARGETS[0]),
        "missing CE": lambda: ce_driver(instances, {}, "target"),
        "duplicate CE": lambda: ce_driver(instances, {**nets, "other": nets["ce"]}, "target"),
        "missing driver": lambda: ce_driver({"target": instances["target"]}, nets, "target"),
        "multiple drivers": lambda: ce_driver(instances, {"ce": nets["ce"].replace(";", ', outpin "target" Y;')}, "target"),
        "unplaced target": lambda: site(instances["target"].replace("placed R1C1 SLICE_X1Y1", "unplaced")),
        "unplaced driver": lambda: ce_driver({**instances, "driver": instances["driver"].replace("placed R1C2 SLICE_X2Y1", "unplaced")}, nets, "target"),
        "conflicting slice placement": lambda: placed_slices({**instances, "other": instances["target"]}),
        "truncated XDL": lambda: xdl.parse(fixture.rstrip().removesuffix(";")),
    }
    for name, control in negatives.items():
        try:
            control()
        except ValueError:
            print(f"Rejected synthetic control: {name}")
        else:
            raise ValueError(f"Accepted invalid synthetic control: {name}")
    print("Accepted synthetic FF/CE/placement controls; fixtures are not design evidence")


def inspect(path):
    text = Path(path).read_text(encoding="utf-8", errors="strict")
    if not re.search(r'\bxc3s400pq208-4\b', text):
        raise ValueError("Expected xc3s400pq208-4 XDL identity missing")
    instances, nets = xdl.parse(text)
    if len(instances) < 100 or len(nets) < 100:
        raise ValueError("Unexpectedly small mapped design")
    print("FAILED S-RTC decoder candidate 40735386633 only; NOT original baseline, routed timing, or equivalence evidence.")
    print(f"Parsed {len(instances)} complete instance and {len(nets)} complete net statements")
    chosen_instances, chosen_nets, frontier, centers = set(), set(), set(), set()
    for target in TARGETS:
        comp, slot = bind(instances, target)
        target_site = site(instances[comp])
        net_name, driver = ce_driver(instances, nets, comp)
        driver_site = site(instances[driver[0]])
        loads = [(name, pin) for kind, name, pin in xdl.net_pins(nets[net_name]) if kind == "inpin"]
        print(f"FF {target}: COMP={comp} slot=FF{slot} site={target_site[0]}; CE={net_name}; driver={driver} at {driver_site[0]}; all {len(loads)} physical loads={loads!r}")
        chosen_instances.add(comp)
        chosen_instances.update(name for name, _ in loads if name in instances)
        chosen_nets.add(net_name)
        frontier.add(driver[0])
        centers.update((target_site[1:], driver_site[1:]))
    # Include complete statements, never clipped fanout lists. Packed companion
    # logic is deliberately visible; do not infer an exact logical cone from it.
    for depth in range(4):
        chosen_instances.update(frontier)
        following = set()
        for name, statement in nets.items():
            pins = xdl.net_pins(statement)
            if any(kind == "inpin" and comp in frontier and pin in xdl.INPUT_PINS
                   for kind, comp, pin in pins):
                chosen_nets.add(name)
                following.update(comp for kind, comp, _ in pins if kind == "outpin" and comp in instances)
        print(f"Physical predecessor layer {depth}: {len(frontier)} components")
        frontier = following - chosen_instances
    # Preserve every output net of the included components, so full fanout is
    # available even where a net is not a predecessor of a selected target.
    for name, statement in nets.items():
        if any(kind == "outpin" and comp in chosen_instances for kind, comp, _ in xdl.net_pins(statement)):
            chosen_nets.add(name)
    n46 = [name for name in nets if name == "snes_cheat/N46"]
    print(f"Exact snes_cheat/N46 names in this different mapped design: {n46!r}; names do not prove baseline correspondence")
    chosen_nets.update(n46)
    occupied = placed_slices(instances)
    for name, (comp, x, y) in sorted(occupied.items()):
        if any(abs(x - cx) <= 2 and abs(y - cy) <= 2 for cx, cy in centers):
            print(f"Nearby occupied mapped slice: {name} COMP={comp}")
            chosen_instances.add(comp)
    print("Neighborhood lists existing occupied sites within +/-2 slice coordinates only; omitted sites are NOT established legal/free capacity.")
    print("Four-layer traversal follows physical pins including packed companion logic; it is NOT an exhaustive logical cone or a routed-placement claim.")
    if len(chosen_instances) > 400 or len(chosen_nets) > 700:
        raise ValueError("Excerpt exceeds bounds; no truncation accepted")
    records = [instances[name] for name in sorted(chosen_instances)] + [nets[name] for name in sorted(chosen_nets)]
    if sum(map(len, records)) > 3_000_000:
        raise ValueError("Excerpt exceeds 3 MB; no truncation accepted")
    print(f"Retaining {len(chosen_instances)} entire instances and {len(chosen_nets)} entire nets")
    for record in records:
        print("\n" + record)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: inspect-basex-retained-map.py XDL|--self-check")
    controls()
    if sys.argv[1] != "--self-check":
        inspect(sys.argv[1])
