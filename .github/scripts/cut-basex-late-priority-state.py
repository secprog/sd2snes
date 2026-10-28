#!/usr/bin/env python3
"""Expose every named cheat word Q/D and independently check the state view."""

import copy
import json
import sys
from pathlib import Path


source, destination, name = sys.argv[1:]
design = json.loads(Path(source).read_text(encoding="utf-8"))
if set(design["modules"]) != {"cheat_programming_model"} or name not in ("gold", "gate"):
    raise SystemExit("Expected one complete cheat programming component")
module = design["modules"]["cheat_programming_model"]
observed = module["ports"]["state"]["bits"]
clock = module["ports"]["CLK"]["bits"]
if module["ports"]["state"]["direction"] != "output" or len(observed) != 192:
    raise SystemExit("Unexpected full state observation")
if len(clock) != 1 or module["ports"]["CLK"]["direction"] != "input":
    raise SystemExit("Unexpected clock boundary")
for net in module["netnames"].values():
    if "init" in net.get("attributes", {}):
        raise SystemExit("Unexpected initialization in the original uninitialized arrays")

state = []
for word in range(6):
    # The RTL observation is {address,data}, so data occupies the low eight bits.
    for array, width in (("cheat_data", 8), ("cheat_addr", 24)):
        net = module["netnames"].get(f"{array}[{word}]")
        if net is None or len(net["bits"]) != width:
            raise SystemExit(f"Missing or malformed {array} word {word}")
        state.extend(net["bits"])
if len(state) != 192 or len(set(state)) != 192 or any(type(bit) is not int for bit in state):
    raise SystemExit("The six word names must expose192 distinct driven bits")
next_bits, registers = {}, []
for cell_name, cell in module["cells"].items():
    kind = cell["type"]
    if kind != "$dff":
        if (not kind.startswith("$") or any(word in kind.lower() for word in
                ("dff", "latch", "mem")) or kind in ("$ff", "$anyseq", "$anyconst")
                or "CLK" in cell["connections"]):
            raise SystemExit(f"Unmodelled state or blackbox: {kind}")
        continue
    if cell["connections"]["CLK"] != clock or int(cell["parameters"]["CLK_POLARITY"], 2) != 1:
        raise SystemExit("State clock or edge changed")
    q, d = cell["connections"]["Q"], cell["connections"]["D"]
    if len(q) != len(d):
        raise SystemExit("Inconsistent state width")
    for qbit, dbit in zip(q, d):
        if qbit in next_bits:
            raise SystemExit("Multiply driven state bit")
        next_bits[qbit] = dbit
    registers.append(cell_name)
if set(next_bits) != set(state):
    raise SystemExit("Named cheat words do not bijectively match every DFF Q")
inputs = {bit for port in module["ports"].values()
          if port["direction"] == "input" for bit in port["bits"]}
if inputs & set(state):
    raise SystemExit("A state bit aliases an existing input")
for cell_name in registers:
    del module["cells"][cell_name]
for cell in module["cells"].values():
    for port, bits in cell["connections"].items():
        if cell["port_directions"][port] == "output" and set(bits) & set(state):
            raise SystemExit("Non-register driver found on symbolic state")

all_bits = [bit for port in module["ports"].values() for bit in port["bits"]]
all_bits += [bit for net in module["netnames"].values() for bit in net["bits"]]
all_bits += [bit for cell in module["cells"].values()
             for bits in cell["connections"].values() for bit in bits]
match_bit = max(bit for bit in all_bits if type(bit) is int) + 1
for key in ("state_in", "next_state", "state_view_ok"):
    if key in module["ports"] or key in module["netnames"]:
        raise SystemExit(f"Unexpected pre-existing proof boundary {key}")
cell_name = "$state_view_strict_eq"
if cell_name in module["cells"]:
    raise SystemExit("Unexpected pre-existing state-view comparator")
width = format(192, "032b")
module["cells"][cell_name] = {
    "hide_name": 1, "type": "$eqx", "attributes": {},
    "parameters": {"A_SIGNED": "0" * 32, "B_SIGNED": "0" * 32,
                   "A_WIDTH": width, "B_WIDTH": width, "Y_WIDTH": format(1, "032b")},
    "port_directions": {"A": "input", "B": "input", "Y": "output"},
    "connections": {"A": observed, "B": state, "Y": [match_bit]},
}
del module["ports"]["state"]
for key, direction, bits in (
    ("state_in", "input", state),
    ("next_state", "output", [next_bits[bit] for bit in state]),
    ("state_view_ok", "output", [match_bit]),
):
    module["ports"][key] = {"direction": direction, "bits": bits}
    module["netnames"][key] = {"hide_name": 0, "bits": bits, "attributes": {}}
module.get("attributes", {}).pop("top", None)
design["modules"] = {name: module}
Path(destination).write_text(json.dumps(design), encoding="utf-8")
if name == "gold":
    mutant = copy.deepcopy(design)
    bits = mutant["modules"]["gold"]["cells"][cell_name]["connections"]["B"]
    bits[0], bits[1] = bits[1], bits[0]
    Path(destination).with_name("state-view-mutant.json").write_text(json.dumps(mutant), encoding="utf-8")
print(f"{name}: all192 named Q/D bits audited; one positive CLK, no init or hidden state.")
print("The entire original state observation is retained for independent unrestricted-X state_view_ok proof.")
