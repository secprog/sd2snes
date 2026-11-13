"""Read a flat native EDIF network without rewriting its fixed primitives.

The mapping experiment only needs scalar LUT/INV connections. Other cells,
properties, ports and library definitions remain opaque EDIF expressions.
Unsupported structures fail explicitly instead of being approximated.
"""
import copy
from datetime import datetime, timezone
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse(text):
    tokens = re.finditer(r'\(|\)|"(?:[^"]|"")*"|[^\s()"]+', text)
    root, stack, previous = [], [], 0
    current = root
    for match in tokens:
        require(not text[previous:match.start()].strip(), "Invalid EDIF token")
        previous = match.end()
        token = match.group()
        if token == "(":
            node = []
            current.append(node)
            stack.append(current)
            current = node
        elif token == ")":
            require(stack and current, "Unbalanced or empty EDIF expression")
            current = stack.pop()
        else:
            current.append(token)
    require(not stack and not text[previous:].strip(), "Incomplete EDIF")
    require(len(root) == 1 and key(root[0]) == "edif", "Expected one EDIF design")
    return root[0]


def emit(node):
    if isinstance(node, str):
        return node
    return "(" + " ".join(emit(x) for x in node) + ")"


def key(node):
    return node[0].lower() if isinstance(node, list) and node else ""


def children(node, tag):
    return [x for x in node if key(x) == tag.lower()]


def one(node, tag):
    matches = children(node, tag)
    require(len(matches) == 1, f"Expected one {tag}, got {len(matches)}")
    return matches[0]


def name(node):
    if isinstance(node, str):
        return node
    require(key(node) == "rename" and len(node) == 3, "Unsupported EDIF name")
    return node[1]


def reference(instance):
    return one(one(instance, "viewRef"), "cellRef")


class Network:
    def __init__(self, text):
        self.tree = parse(text)
        require(one(self.tree, "edifVersion")[1:] == ["2", "0", "0"], "EDIF version")
        top_ref = one(one(self.tree, "design"), "cellRef")
        lib_id = one(top_ref, "libraryRef")[1].lower()
        libs = [x for x in self.tree if key(x) in ("library", "external")
                and name(x[1]).lower() == lib_id]
        require(len(libs) == 1, "Ambiguous top library")
        cells = [c for c in children(libs[0], "cell")
                 if name(c[1]).lower() == top_ref[1].lower()]
        require(len(cells) == 1, "Ambiguous top cell")
        self.top = cells[0]
        self.view = one(self.top, "view")
        self.contents = one(self.view, "contents")
        self.instances = {name(c[1]): c for c in children(self.contents, "instance")}
        self.nets = {name(n[1]): n for n in children(self.contents, "net")}
        require(len(self.instances) == len(children(self.contents, "instance")), "Duplicate instances")
        require(len(self.nets) == len(children(self.contents, "net")), "Duplicate nets")
        self.types = {n: reference(c)[1] for n, c in self.instances.items()}
        self.pin_net = {}
        for net_id, node in self.nets.items():
            for pin in one(node, "joined")[1:]:
                require(key(pin) == "portref", "Unsupported joined member")
                inst = children(pin, "instanceRef")
                require(len(inst) <= 1, "Ambiguous pin instance")
                inst_id = inst[0][1] if inst else None
                require(inst_id is None or inst_id in self.instances, "Unknown instance pin")
                pin_id = (inst_id, emit(pin[1]))
                require(pin_id not in self.pin_net, "Pin joined to multiple nets")
                self.pin_net[pin_id] = net_id

    def implementation_text(self):
        """Serialize our reconstructed netlist with its own, truthful producer.

        ISE rejects NGC2EDIF's timing-estimate producer tag (NgdBuild:766).
        This is a custom third-party reconstruction, not a supported NGC2EDIF
        implementation export. Keep the original file and SHA256 separately;
        only a successful native reference round trip can qualify this path.
        No structural expression may change when replacing the file metadata.
        """
        structure = [copy.deepcopy(x) for x in self.tree if key(x) != "status"]
        now = datetime.now(timezone.utc)
        status = ["status", ["written",
                  ["timeStamp", *(str(x) for x in (now.year, now.month, now.day,
                                                 now.hour, now.minute, now.second))],
                  ["program", '"sd2snes gbc_edif reconstruction"', ["version", '"1"']],
                  ["comment", '"Experimental reconstruction; requires native round-trip qualification."']]]
        position = structure.index(one(structure, "keywordMap")) + 1
        tree = structure[:position] + [status] + structure[position:]
        text = emit(tree) + "\n"
        parsed = Network(text)
        require([x for x in parsed.tree if key(x) != "status"] == structure,
                "Implementation serialization changed structural EDIF")
        return text

    def logic_model(self, known_ids=None):
        """Use Yosys-shaped JSON as a data interchange, without interpreting FFs."""
        ids = dict(known_ids or {})
        next_id = max(ids.values(), default=1) + 1
        for net in self.nets:
            if net not in ids:
                ids[net] = next_id
                next_id += 1
        cells, ports = {}, {}
        for inst, node in self.instances.items():
            kind = self.types[inst]
            params = {}
            if re.fullmatch(r"LUT[1-4]", kind):
                init = [p for p in children(node, "property") if name(p[1]).upper() == "INIT"]
                require(len(init) == 1, f"Missing or duplicate INIT on {inst}")
                value = one(init[0], "string")[1]
                require(re.fullmatch(r'"[0-9a-fA-F]+"', value), "Non-hex LUT INIT")
                width = 1 << int(kind[3:])
                number = int(value[1:-1], 16)
                require(number < (1 << width), "Oversize LUT INIT")
                params["INIT"] = format(number, f"0{width}b")
            cells[inst] = {"type": kind, "parameters": params, "connections": {}}
        for (inst, pin), net in self.pin_net.items():
            if inst is None:
                ports[pin] = {"bits": [ids[net]]}
            else:
                cells[inst]["connections"][pin] = [ids[net]]
        return {"cells": cells, "ports": ports,
                "netnames": {n: {"bits": [i]} for n, i in ids.items() if n in self.nets}}, ids

    def fixed_signature(self, logic_types, logic_names=()):
        """Properties, types and the net on every fixed pin must stay identical."""
        fixed = {n for n in self.instances if self.types[n] not in logic_types and n not in logic_names}
        fixed_nets = {n for p, n in self.pin_net.items() if p[0] is None or p[0] in fixed}
        return {
            "interface": copy.deepcopy(one(self.view, "interface")),
            "instances": {n: copy.deepcopy(self.instances[n]) for n in fixed},
            "pins": {p: n for p, n in self.pin_net.items() if p[0] is None or p[0] in fixed},
            "net_properties": {n: copy.deepcopy([p for p in v[2:] if key(p) != "joined"])
                               for n, v in self.nets.items()
                               if n in fixed_nets},
        }

    def splice(self, mapped, inputs, outputs, logic_types, ids, logic_names=()):
        """Replace only proved combinational cells in the original native EDIF.

        Boundary nets keep their original identifiers. Explicit identity LUTs
        handle aliases/constant outputs, so no fixed pin, net property, clock,
        reset, memory, carry chain or I/O definition needs to be rewritten.
        """
        original_signature = self.fixed_signature(logic_types, logic_names)
        result = copy.deepcopy(self)
        removed = {n for n in self.instances if self.types[n] in logic_types or n in logic_names}
        by_id = {v: n for n, v in ids.items()}
        require(len(by_id) == len(ids), "Duplicate native net identifiers")
        pins = {n: [copy.deepcopy(p) for p in one(node, "joined")[1:]
                    if not children(p, "instanceRef")
                    or one(p, "instanceRef")[1] not in removed]
                for n, node in self.nets.items()}
        prototypes = {}
        constants = {}
        for inst, kind in self.types.items():
            if kind in logic_types:
                prototypes.setdefault(kind, copy.deepcopy(one(self.instances[inst], "viewRef")))
            if kind in ("VCC", "GND"):
                connected = [n for (i, _), n in self.pin_net.items() if i == inst]
                require(len(connected) == 1, "Unexpected native constant primitive")
                constants[str(int(kind == "VCC"))] = connected[0]
        require(set(constants) == {"0", "1"}, "Missing native constant drivers")
        require(len(mapped["ports"]["i"]["bits"]) == len(inputs), "Input boundary width")
        require(len(mapped["ports"]["o"]["bits"]) == len(outputs), "Output boundary width")
        bit_net, new_instances = {}, []
        counter = 0

        def fresh(prefix):
            nonlocal counter
            while True:
                counter += 1
                candidate = f"gbc_remap_{prefix}_{counter}"
                if candidate not in self.instances and candidate not in pins:
                    return candidate

        def mapped_net(bit):
            if isinstance(bit, str):
                require(bit in constants, "Unknown/X bit in mapped network")
                return constants[bit]
            if bit not in bit_net:
                bit_net[bit] = fresh("net")
                pins[bit_net[bit]] = []
            return bit_net[bit]

        def add_cell(kind, connections, init=None):
            require(kind in prototypes, f"Missing native library prototype {kind}")
            inst = fresh("cell")
            cell = ["instance", inst, copy.deepcopy(prototypes[kind])]
            if kind.startswith("LUT"):
                width = 1 << int(kind[3:])
                require(init is not None and re.fullmatch(r"[01]+", init), "Invalid mapped INIT")
                require(len(init) == width, "Mapped LUT INIT width")
                value = format(int(init, 2), f"0{max(1, width // 4)}X")
                cell.append(["property", "INIT", ["string", '"' + value + '"']])
            else:
                require(kind == "INV" and init is None, "Unexpected mapped cell type")
            new_instances.append(cell)
            for port, net in connections.items():
                pins.setdefault(net, []).append(["portRef", port, ["instanceRef", inst]])

        for bit, native_id in zip(mapped["ports"]["i"]["bits"], inputs):
            require(isinstance(bit, int) and bit not in bit_net, "Aliased mapped inputs")
            bit_net[bit] = by_id[native_id]
        for bit, native_id in zip(mapped["ports"]["o"]["bits"], outputs):
            target = by_id[native_id]
            if isinstance(bit, int) and bit not in bit_net:
                bit_net[bit] = target
            else:
                source = mapped_net(bit)
                require(source != target, "Unexpected self-connected boundary")
                add_cell("LUT1", {"I0": source, "O": target}, "10")
        for cell in mapped["cells"].values():
            kind = cell["type"]
            require(kind in {"LUT1", "LUT2", "LUT3", "LUT4", "INV"}, "Unsupported remapped primitive")
            require(all(len(bits) == 1 for bits in cell["connections"].values()), "Non-scalar logic pin")
            add_cell(kind, {p: mapped_net(b[0]) for p, b in cell["connections"].items()},
                     cell["parameters"].get("INIT"))
        new_nets = []
        for net, joined in pins.items():
            if not joined:
                continue
            if net in result.nets:
                node = result.nets[net]
                node[node.index(one(node, "joined"))] = ["joined", *joined]
            else:
                node = ["net", net, ["joined", *joined]]
            new_nets.append(node)
        extras = [x for x in result.contents[1:] if key(x) not in ("instance", "net")]
        result.contents[:] = ["contents", *extras,
                              *(c for n, c in result.instances.items() if n not in removed),
                              *new_instances, *new_nets]
        # Parse our actual output again, independently of the mutation objects.
        rebuilt = Network(emit(result.tree))
        require(rebuilt.fixed_signature(logic_types, logic_names) == original_signature,
                "Fixed implementation structure changed during EDIF splicing")
        return rebuilt
