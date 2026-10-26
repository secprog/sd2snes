#!/usr/bin/env python3
"""Audit the initial state relation required by this restricted RTL experiment."""

import json
import sys
from collections import defaultdict
from pathlib import Path


def state_inventory(path):
    design = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(design["modules"]) != {"cheat"}:
        raise ValueError("Expected the complete cheat module without blackboxes")
    module = design["modules"]["cheat"]
    clock = module["ports"]["clk"]
    if clock["direction"] != "input" or len(clock["bits"]) != 1:
        raise ValueError("Expected the original scalar clock input")
    names = defaultdict(list)
    initial = defaultdict(set)
    for name, net in module["netnames"].items():
        for index, bit in enumerate(net["bits"]):
            if not name.startswith("$"):
                names[bit].append((name, index))
        init = net.get("attributes", {}).get("init")
        if init is not None:
            # Modern write_json preserves x/z as binary strings. Yosys 0.9 emits
            # short constants as integers and cannot support this lossless audit.
            if not isinstance(init, str) or len(init) != len(net["bits"]) or not set(init) <= set("01xz"):
                raise ValueError(f"Ambiguous initial state on {name}")
            for bit, value in zip(net["bits"], reversed(init)):
                initial[bit].add(value)

    inventory = {}
    seen_bits = set()
    for cell in module["cells"].values():
        kind = cell["type"]
        if kind != "$dff":
            if not kind.startswith("$") or any(
                word in kind.lower() for word in ("dff", "latch", "mem")
            ) or kind == "$ff" or "CLK" in cell["connections"]:
                raise ValueError(f"Unexpected sequential cell or blackbox: {kind}")
            continue
        if cell["connections"]["CLK"] != clock["bits"] or int(
            cell["parameters"]["CLK_POLARITY"], 2
        ) != 1:
            raise ValueError("A register clock or edge changed")
        for bit in cell["connections"]["Q"]:
            labels = tuple(sorted(names[bit]))
            if not isinstance(bit, int) or not labels or bit in seen_bits:
                raise ValueError("Unmapped, constant or multiply driven state bit")
            if labels in inventory or len(initial[bit]) > 1:
                raise ValueError("Ambiguous register identity or initial value")
            # An unspecified initial value stays arbitrary; never substitute zero.
            inventory[labels] = next(iter(initial[bit]), "x")
            seen_bits.add(bit)
    if not inventory:
        raise ValueError("No state bits were audited")
    return inventory


gold = state_inventory(sys.argv[1])
gate = state_inventory(sys.argv[2])
if gold != gate:
    missing = set(gold) - set(gate)
    added = set(gate) - set(gold)
    changed = sum(gold[key] != gate[key] for key in set(gold) & set(gate))
    raise SystemExit(
        f"State relation changed: {len(missing)} missing, {len(added)} added, "
        f"{changed} different initial values"
    )
print(f"Matched all {len(gold)} state bits, positive clock edges and initial values.")
print("Uninitialized bits remain arbitrary in both models; no reset assumption was added.")
