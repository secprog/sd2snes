#!/usr/bin/env python3
"""Audit every state bit, then expose the complete combinational transition relation.

Replacing every audited DFF Q by a shared symbolic input and exposing every D
proves a one-step congruence for ALL common states, rather than a bounded reset
trace or conditional induction. Read outputs are checked in the same miter.
"""

import json
import sys
from pathlib import Path


source, destination, name = sys.argv[1:]
design = json.loads(Path(source).read_text(encoding="utf-8"))
if set(design["modules"]) != {"gpr_model"} or name not in ("gold", "gate"):
    raise SystemExit("Expected one complete GPR component without blackboxes")
module = design["modules"]["gpr_model"]
state = module["ports"]["state"]["bits"]
clock = module["ports"]["CLK"]["bits"]
if len(state) != 392 or len(set(state)) != 392 or any(type(bit) is not int for bit in state):
    raise SystemExit("Canonical state must bijectively expose all 384 GPR and 8 bus-output bits")
if len(clock) != 1 or module["ports"]["CLK"]["direction"] != "input":
    raise SystemExit("Unexpected clock boundary")
if module["ports"]["state"]["direction"] != "output":
    raise SystemExit("Expected a state observation output")
for net in module["netnames"].values():
    if "init" in net.get("attributes", {}):
        raise SystemExit("Unexpected initialization; original GPR state has no reset or initializer")

next_bits = {}
registers = []
for cell_name, cell in module["cells"].items():
    kind = cell["type"]
    if kind != "$dff":
        if (not kind.startswith("$") or any(word in kind.lower() for word in
                ("dff", "latch", "mem")) or kind in ("$ff", "$anyseq", "$anyconst")
                or "CLK" in cell["connections"]):
            raise SystemExit(f"Unmodelled state or blackbox: {kind}")
        continue
    if (cell["connections"]["CLK"] != clock
            or int(cell["parameters"]["CLK_POLARITY"], 2) != 1):
        raise SystemExit("A state clock or clock edge changed")
    q, d = cell["connections"]["Q"], cell["connections"]["D"]
    if len(q) != len(d):
        raise SystemExit("Inconsistent state transition width")
    for qbit, dbit in zip(q, d):
        if qbit in next_bits:
            raise SystemExit("Multiply driven state bit")
        next_bits[qbit] = dbit
    registers.append(cell_name)
if set(next_bits) != set(state):
    raise SystemExit("The canonical relation omits or invents sequential state")
input_bits = {bit for port in module["ports"].values()
              if port["direction"] == "input" for bit in port["bits"]}
if input_bits & set(state):
    raise SystemExit("A state bit already aliases an external input")
for cell_name in registers:
    del module["cells"][cell_name]
for cell in module["cells"].values():
    for port, bits in cell["connections"].items():
        if cell["port_directions"][port] == "output" and set(bits) & set(state):
            raise SystemExit("Non-register driver found on symbolic state")

# The canonical byte/bit ordering is identical in both models. Nothing is tied
# to zero, and no address, opcode, freeze or write-priority assumption is added.
del module["ports"]["state"]
module["ports"]["state_in"] = {"direction": "input", "bits": state}
module["ports"]["next_state"] = {"direction": "output", "bits": [next_bits[bit] for bit in state]}
module["netnames"]["state_in"] = {"hide_name": 0, "bits": state, "attributes": {}}
module["netnames"]["next_state"] = {"hide_name": 0, "bits": [next_bits[bit] for bit in state], "attributes": {}}
module.get("attributes", {}).pop("top", None)
design["modules"] = {name: module}
Path(destination).write_text(json.dumps(design), encoding="utf-8")
print(f"{name}: all 392 state bits audited; one positive CLK; no reset/init/hidden state.")
print("Exposed every next-state bit and the CPU read result for universal combinational SAT.")
