#!/usr/bin/env python3
"""Read actual slow-path mapped drivers from two rejected native trials; hosted only."""

import importlib.util
import re
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "xdl", Path(__file__).with_name("inspect-dsp-retained-map.py"))
xdl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xdl)


def inspect(family, path):
    xdl.fixture_checks()
    if family not in {"dsp-status", "basex-patch"} or path.stat().st_size > 32_000_000:
        raise SystemExit("Invalid family or excessive full XDL")
    instances, nets = xdl.parse(path.read_text(encoding="utf-8", errors="strict"))
    if len(instances) < 100 or len(nets) < 100:
        raise SystemExit("Unexpectedly small full mapped design")
    if family == "dsp-status":
        targets = ["snes_dspx/regs_sr_7", "snes_dspx/regs_sr_8",
                   "snes_dspx/regs_sr_13", "snes_dspx/ss_frozen"]
        seeds = ["snes_dspx/N99", "snes_dspx/N428"]
        observed = seeds + ["snes_dspx/ss_frozen"]
    else:
        targets = ["snes_addr/SNES_ADDR_21", "CTX_ROM_ADDRr_22_BRB1"]
        seeds = ["IS_PATCH", "snes_addr/SRAM_SNES_ADDR<22>80/O",
                 "snes_addr/SRAM_SNES_ADDR<22>88"]
        observed = seeds + ["snes_addr/SNES_ADDR<21>"]
    selected = set()
    errors = []
    bindings = []
    pin_nets = {}
    for name, statement in nets.items():
        for kind, comp, pin in xdl.net_pins(statement):
            key = (comp, pin)
            if key in pin_nets:
                raise SystemExit(f"Duplicate physical pin binding {key}")
            pin_nets[key] = name

    def retain_driver(name):
        if name not in nets:
            errors.append(f"Observed net {name} absent; no absent-logic inference")
            return None
        drivers = [(comp, pin) for kind, comp, pin in xdl.net_pins(nets[name]) if kind == "outpin"]
        if not drivers and re.search(r'^net\s+"[^"]+"\s*,\s*(?:vcc|gnd)\s*,', nets[name]):
            bindings.append(f"Observed net {name}: explicit constant source")
            return None
        if len(drivers) != 1 or drivers[0][0] not in instances:
            errors.append(f"Observed net {name} lacks one retained driver: {drivers}")
            return None
        selected.add(drivers[0][0])
        bindings.append(f"Observed net {name}: driver={drivers[0]}")
        return drivers[0][0]

    for name in observed:
        retain_driver(name)
    # Exactly one physical predecessor layer for the specified omitted drivers.
    # Other packed LUTs can be unrelated; never infer logical coupling from COMP.
    seed_comps = [retain_driver(name) for name in seeds]
    for comp in set(seed_comps) - {None}:
        for pin in ("F1", "F2", "F3", "F4", "G1", "G2", "G3", "G4", "BX"):
            name = pin_nets.get((comp, pin))
            if name:
                retain_driver(name)
    target_bindings = []
    for target in targets:
        try:
            comp = xdl.bind(instances, target)
            selected.add(comp)
            inputs = []
            for pin in sorted(xdl.INPUT_PINS):
                name = pin_nets.get((comp, pin))
                if name:
                    retain_driver(name)
                    inputs.append((pin, name))
            hits = re.findall(r"(?<!\S)FF([XY]):" + re.escape(target) + r":#FF(?=\s|$)", instances[comp])
            if len(hits) != 1:
                raise ValueError("Missing or ambiguous exact FF slot")
            target_bindings.append(f"Target {target}: COMP={comp}, FF={hits[0]}, physical_inputs={inputs}")
        except ValueError as error:
            errors.append(f"Target {target}: {error}; no missing-state inference")
    selected_nets = {name for name, statement in nets.items() if name in observed or any(
        comp in selected for kind, comp, pin in xdl.net_pins(statement))}
    records = [instances[name] for name in sorted(selected)]
    records += [nets[name] for name in sorted(selected_nets)]
    raw = "\n".join(records)
    if not selected or len(selected) > 400 or len(selected_nets) > 700 or len(raw.encode()) > 3_000_000:
        raise SystemExit(f"Complete raw bounds failed: {len(selected)} COMPs/{len(selected_nets)} nets/{len(raw.encode())} bytes; inconclusive")
    print("Retained failed native candidate MAP only; not routed connectivity or a timing pass.")
    print(f"Full XDL {len(instances)} instances/{len(nets)} nets; retained {len(selected)} complete instances/{len(selected_nets)} complete nets/{len(raw.encode())} bytes.")
    print("Complete bounded raw statements follow before binding outcomes.")
    print(raw)
    print("\n".join(sorted(bindings)))
    print("\n".join(target_bindings))
    print(f"Exact FF targets bound: {len(target_bindings)}/{len(targets)}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("Read-only retention complete. Independent FF/cfg/pin/mux/driver review remains required; no sequential, timing or hardware pass.")


if __name__ == "__main__":
    family, filename = sys.argv[1:]
    inspect(family, Path(filename))
