"""Hosted logic-remapping diagnostic, preserving XST's RAM/FF boundaries.

This deliberately emits no FPGA image. The native artifact and its provenance
remain the reference; a successful logic proof is not a place/route result.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from gbc_edif import Network

root = Path(__file__).resolve().parents[2]
netlist = Path(sys.argv[1]).resolve()
report = Path(sys.argv[2]).resolve()
report.mkdir(parents=True, exist_ok=True)


def run(name, commands, expect_counterexample=False):
    script = report / (name + ".ys")
    script.write_text("\n".join(commands) + "\n")
    log = report / (name + ".log")
    result = subprocess.run(["yosys", "-Q", "-q", "-l", str(log), "-s", str(script)],
                            timeout=300)
    if expect_counterexample:
        if result.returncode == 0 or "proof did fail" not in log.read_text():
            raise RuntimeError("The deliberately corrupted output was not rejected by SAT")
    else:
        result.check_returncode()


def quote(path):
    return '"' + str(path) + '"'


network = None
if netlist.suffix.lower() in (".edf", ".edif"):
    network = Network(netlist.read_text())
    (report / "native-reconstructed.edf").write_text(network.implementation_text())
    native, native_ids = network.logic_model()
    (report / "native.json").write_text(json.dumps({"modules": {"main": native}}))
else:
    wrappers = [root / "verilog/sd2snes_sgb/ip/mk2" / (n + ".v")
                for n in ("vram", "snescmd_buf", "oam")]
    # The NetGen path is diagnostic only. Its simulation primitives must never
    # become the fixed implementation structure of an exported EDIF candidate.
    extra = report / "legacy.v"
    extra.write_text("(* blackbox *) module BUFGP(input I, output O); endmodule\n")
    diagnostic = report / "native-diagnostic.v"
    source = netlist.read_text()
    source = source[:source.index("endmodule") + len("endmodule")] + "\n"
    source = re.sub(r"// synthesis translate_(?:off|on)", "", source)
    source = source.replace("/* synthesis syn_black_box syn_noprune=1 */", "")
    diagnostic.write_text(source)
    run("read", ["read_verilog -lib +/xilinx/cells_sim.v +/xilinx/cells_xtra.v",
                 "read_verilog -lib " + " ".join(map(quote, wrappers + [extra])),
                 "read_verilog " + quote(diagnostic), "hierarchy -top main",
                 "blackbox =A:whitebox",
                 "write_json " + quote(report / "native.json")])
    native = json.loads((report / "native.json").read_text())["modules"]["main"]


def output_port(cell):
    return "LO" if cell["type"] == "MULT_AND" else "O"


def render_logic(model, logic_types, inputs, outputs, module_name, logic_names=()):
    logic = [c for n, c in model["cells"].items() if c["type"] in logic_types or n in logic_names]
    bits = {b for c in logic for values in c["connections"].values()
            for b in values if isinstance(b, int)} | set(inputs) | set(outputs)
    constants = {bit: str(int(c["type"] == "VCC")) for c in model["cells"].values()
                 if c["type"] in ("VCC", "GND") for values in c["connections"].values()
                 for bit in values if isinstance(bit, int)}

    def signal(bit):
        if isinstance(bit, str) and bit not in ("0", "1"):
            raise ValueError("Unknown/X constant in logic network")
        return "n" + str(bit) if isinstance(bit, int) else "1'b" + bit

    lines = [f"module {module_name}(input [{len(inputs)-1}:0] i, output [{len(outputs)-1}:0] o);"]
    lines += ["wire " + ",".join(signal(b) for b in sorted(bits)) + ";"]
    lines += [f"assign {signal(bit)}=i[{idx}];" for idx, bit in enumerate(inputs)]
    lines += [f"assign o[{idx}]={signal(bit)};" for idx, bit in enumerate(outputs)]
    lines += [f"assign {signal(bit)}=1'b{value};" for bit, value in constants.items() if bit in bits]
    for c in logic:
        if not all(len(values) == 1 for values in c["connections"].values()):
            raise ValueError("Non-scalar logic connection")
        ports = {p: signal(values[0]) for p, values in c["connections"].items()}
        if c["type"].startswith("LUT"):
            width = int(c["type"][3:])
            init = c["parameters"]["INIT"]
            address = "{" + ",".join(ports["I" + str(n)] for n in reversed(range(width))) + "}"
            expression = f"({len(init)}'b{init} >> {address})"
        elif c["type"] == "INV":
            expression = "~" + ports["I"]
        elif c["type"] == "MUXCY":
            expression = f"{ports['S']} ? {ports['CI']} : {ports['DI']}"
        elif c["type"] == "XORCY":
            expression = f"{ports['LI']} ^ {ports['CI']}"
        elif c["type"] == "MULT_AND":
            expression = f"{ports['I0']} & {ports['I1']}"
        else:
            expression = f"{ports['S']} ? {ports['I1']} : {ports['I0']}"
        lines.append(f"assign {ports[output_port(c)]}={expression};")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"
native_counts = Counter(c["type"] for c in native["cells"].values())
if sum(native_counts[t] for t in ("LUT1", "LUT2", "LUT3", "LUT4")) < 5000:
    raise RuntimeError("native diagnostic did not retain the expected LUT primitives")
summaries = {}
# Discover whole carry chains with no sum XOR. Keep arithmetic chains fixed;
# comparator-only chains can instead be optimized with the surrounding LUTs.
# Exclude XST's wide-gate read muxes here: the earlier widegate trial regressed.
carry = {n: c for n, c in native["cells"].items() if c["type"] == "MUXCY"}
carry_driver = {c["connections"]["O"][0]: n for n, c in carry.items()}
carry_edges = defaultdict(set)
for name, cell in carry.items():
    previous = carry_driver.get(cell["connections"]["CI"][0])
    if previous is not None:
        carry_edges[name].add(previous)
        carry_edges[previous].add(name)
sum_carry = {carry_driver[c["connections"]["CI"][0]] for c in native["cells"].values()
             if c["type"] == "XORCY" and c["connections"]["CI"][0] in carry_driver}
# MULT_AND has only a dedicated connection into a MUXCY. Even a chain without
# sum outputs must retain that physical connection (ISE logical DRC LIT:102).
hard_and_outputs = {c["connections"]["LO"][0] for c in native["cells"].values()
                    if c["type"] == "MULT_AND"}
hard_and_carry = {n for n, c in carry.items()
                  if c["connections"]["DI"][0] in hard_and_outputs}
compare_carry, gate_carry, short_carry, visited = set(), set(), set(), set()
for name in carry:
    if name in visited:
        continue
    pending, chain = [name], set()
    while pending:
        member = pending.pop()
        if member not in chain:
            chain.add(member)
            pending.extend(carry_edges[member] - chain)
    visited |= chain
    if not chain & (sum_carry | hard_and_carry):
        gate_carry |= chain
        if not any("_wg_cy" in n for n in chain):
            compare_carry |= chain
    if len(chain) <= 8 and not chain & hard_and_carry:
        short_carry |= chain
short_carry |= compare_carry
short_outputs = {carry[n]["connections"]["O"][0] for n in short_carry}
short_inputs = {(carry[n]["connections"]["CI"][0], carry[n]["connections"]["S"][0])
                for n in short_carry}
short_sums = {n for n, c in native["cells"].items() if c["type"] == "XORCY"
              and (c["connections"]["CI"][0] in short_outputs
                   or (c["connections"]["CI"][0], c["connections"]["LI"][0]) in short_inputs)}
# Use ABC's area-oriented cut selection as well as its default delay-oriented
# selection. Every candidate has the same whole-cone proof obligation; a lower
# logic count still requires native MAP/PAR before it can become an FPGA image.
abc_prefix = "strash; &get -n; &fraig -x; &put; scorr; dc2; dretime; strash; dch -f; "
# Expanded standard ABC resynthesis/resubstitution sequences, avoiding aliases
# that depend on a user abc.rc. Reference: berkeley-abc/abc, abc.rc.
resyn2 = ("balance; rewrite; refactor; balance; rewrite; rewrite -z; "
          "balance; refactor -z; rewrite -z; balance; ")
resub = ("balance; resub -K 6; rewrite; resub -K 6 -N 2; refactor; "
         "resub -K 8; balance; resub -K 8 -N 2; rewrite; resub -K 10; "
         "rewrite -z; resub -K 10 -N 2; balance; resub -K 12; refactor -z; "
         "resub -K 12 -N 2; rewrite -z; balance; ")
area_tail = "dch -f; if -K 4 -a; mfs2; lutpack -S 1"
compress_resub = "; ".join(command.strip() + " -l" for command in resub.split(";")
                           if command.strip()) + "; "
profiles = (("fixed-mux", False, None),
            ("fixed-mux-area", False, abc_prefix + "if -K 4 -a; mfs2; lutpack -S 1"),
            ("fixed-mux-area2", False, abc_prefix + "if -K 4 -a; mfs2; mfs2; lutpack -S 1"),
            ("lut4", True, None),
            ("lut4-area", True, abc_prefix + "if -K 4 -a; mfs2; lutpack -S 1"),
            ("fixed-mux-resyn2", False, "strash; " + resyn2 + resyn2 + area_tail),
            ("fixed-mux-resub", False, "strash; " + resub + area_tail),
            ("lut4-resub", True, "strash; " + resub + area_tail),
            ("widegate-area", False, abc_prefix + "if -K 4 -a; mfs2; lutpack -S 1"),
            ("widegate-resub", False, "strash; " + resub + area_tail),
            ("fixed-mux-cuts", False, "strash; " + resub +
             "dch -f; if -K 4 -C 32 -F 3 -A 4 -a; mfs2 -e; lutpack -S 1"),
            ("fixed-mux-sat", False, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &put; lutpack -S 1"),
            ("fixed-mux-sat-area", False, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4 -a; &put; lutpack -S 1"),
            ("lut4-sat", True, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &put; lutpack -S 1"),
            ("lut4-resub2-sat", True, "strash; " + resub + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &put; lutpack -S 1"),
            ("lut4-compress-sat", True, "strash; " + compress_resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &put; lutpack -S 1"),
            ("compare-lut4-sat", True, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &put; lutpack -S 1"),
            ("gate-lut4-sat", True, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &put; lutpack -S 1"),
            ("gate-lut4-sat-area", True, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4 -a; &put; lutpack -S 1"),
            ("gate-lut4-sat2", True, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &mfs2 -K 4; &put; lutpack -S 1"),
            # Cost 1/2/4 for LUT4/5/6 reflects their decomposition into real
            # LUT4s plus MUXF5/F6. Let ABC select and group these cones anew.
            ("wide-lut5-resub", True, "strash; " + resub + "dch -f; if -a; mfs2"),
            ("wide-lut6-resub", True, "strash; " + resub + "dch -f; if -a; mfs2"),
            ("compare-resub", False, "strash; " + resub + area_tail),
            ("compare-sat", False, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &put; lutpack -S 1"),
            ("short-carry-sat", True, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &put; lutpack -S 1"),
            ("all-carry-sat", True, "strash; " + resub + area_tail +
             "; &get -m -n; &mfs2 -K 4; &put; lutpack -S 1"))
if len(sys.argv) > 3:
    selected = set(sys.argv[3:])
    if not selected <= {p[0] for p in profiles}:
        raise ValueError("Unknown mapping profile")
    profiles = tuple(p for p in profiles if p[0] in selected)
for profile, remap_mux, abc_script in profiles:
    logic_types = {"LUT1", "LUT2", "LUT3", "LUT4", "INV"}
    if remap_mux:
        logic_types |= {"MUXF5", "MUXF6", "MUXF7", "MUXF8"}
    if profile == "all-carry-sat":
        # Include the dedicated AND with its carry consumers. Keeping its
        # output as a fixed boundary would violate the physical connection.
        logic_types |= {"MUXCY", "XORCY", "MULT_AND"}
    # XST also uses carry multiplexers for wide gates (not arithmetic). Let
    # these named cones participate in Boolean optimization in two trials;
    # all arithmetic carry chains and every state/memory primitive stay fixed.
    logic_names = {n for n, c in native["cells"].items() if c["type"] in logic_types
                   or (profile.startswith("widegate-") and c["type"] == "MUXCY" and "_wg_cy" in n)}
    if profile.startswith("compare-"):
        logic_names |= compare_carry
    if profile.startswith("gate-lut4-"):
        logic_names |= gate_carry
    if profile == "short-carry-sat":
        logic_names |= short_carry | short_sums
    logic = [c for n, c in native["cells"].items() if n in logic_names]
    driven = {bit for c in logic for bit in c["connections"][output_port(c)] if isinstance(bit, int)}
    used = {bit for c in logic for port, bits in c["connections"].items() if port != output_port(c)
            for bit in bits if isinstance(bit, int)}
    boundary = {bit for n, c in native["cells"].items() if n not in logic_names
                for bits in c["connections"].values() for bit in bits if isinstance(bit, int)}
    boundary |= {bit for port in native["ports"].values() for bit in port["bits"]
                 if isinstance(bit, int)}
    constants = {bit: str(int(c["type"] == "VCC")) for c in native["cells"].values()
                 if c["type"] in ("VCC", "GND") for bits in c["connections"].values()
                 for bit in bits if isinstance(bit, int)}
    inputs, outputs = sorted(used - driven - constants.keys()), sorted(driven & boundary)
    if not inputs or not outputs:
        raise RuntimeError("empty native logic boundary")
    source = report / (profile + ".v")
    source.write_text(render_logic(native, logic_types, inputs, outputs, "gbc_logic", logic_names))
    if not summaries:
        corrupt = report / "corrupt-output.v"
        corrupt.write_text(
            f"module gbc_corrupt(input [{len(inputs)-1}:0] i, output [{len(outputs)-1}:0] o);\n"
            f"wire [{len(outputs)-1}:0] raw; gbc_logic original(i,raw);\n"
            f"assign o = raw ^ {len(outputs)}'d1; endmodule\n")
        run("negative-control", ["read_verilog " + quote(source) + " " + quote(corrupt),
                                 "proc", "opt", "techmap", "opt",
                                 "miter -equiv -flatten gbc_logic gbc_corrupt miter",
                                 "hierarchy -top miter", "sat -verify -prove trigger 0"],
            expect_counterexample=True)
    (report / (profile + "-boundary.json")).write_text(json.dumps({
        "inputs": inputs, "outputs": outputs, "logic_types": sorted(logic_types),
        "logic_names": sorted(logic_names),
    }, indent=2) + "\n")
    lut_width = "4:5" if profile == "wide-lut5-resub" else "4:6" if profile == "wide-lut6-resub" else "4"
    abc_command = "abc -lut " + lut_width
    if abc_script:
        script_path = report / (profile + ".abc")
        # &get needs -n as well as -m: otherwise &put invents boundary names
        # and Yosys cannot reconnect the BLIF. Retain ABC's output for audit.
        script_path.write_text(abc_script + "; write_blif "
                               + quote(report / (profile + "-abc.blif")) + "\n")
        abc_command += " -script " + quote(script_path)
    # Compare at every fixed-macro input and top-level output. Sequential
    # state, memories, clocking and I/O stay outside these cones. Selected
    # carry cells use the exact MUXCY/XORCY/MULT_AND truth tables from UG607.
    run(profile, ["read_verilog " + quote(source), "hierarchy -top gbc_logic",
                  "proc", "flatten", "opt", "techmap", "opt",
                  # Only fixed-macro boundary ports are the proof contract.
                  # ABC can legally repurpose/eliminate named internal nodes;
                  # matching those names creates false equivalence cutpoints.
                  "rename -hide",
                  "design -save reference", abc_command, "clean",
                  "design -save mapped", "rename gbc_logic gate",
                  "design -copy-from reference -as gold gbc_logic",
                  # Some boundary outputs also feed other output cones (for
                  # example CLK_CPU_EDGE/CLK_BUS_EDGE). A whole-cone miter
                  # keeps those relationships; per-output cutpoints do not.
                  "miter -equiv -flatten gold gate miter", "hierarchy -top miter",
                  "sat -verify -prove trigger 0 -show-inputs -show-outputs",
                  "design -load mapped",
                  "techmap -map +/xilinx/lut_map.v -D LUT_WIDTH=4", "clean",
                  "write_json " + quote(report / (profile + ".json"))])
    result = json.loads((report / (profile + ".json")).read_text())["modules"]["gbc_logic"]
    cells = Counter(c["type"] for c in result["cells"].values())
    fixed = Counter(c["type"] for n, c in native["cells"].items() if n not in logic_names)
    summaries[profile] = {
        "native_sha256": hashlib.sha256(netlist.read_bytes()).hexdigest(),
        "native_cells": dict(sorted(native_counts.items())),
        "remapped_cells": dict(sorted(cells.items())),
        "fixed_cells": dict(sorted(fixed.items())),
        "combinational_equivalence": "proved at every fixed-macro input and top-level output",
        "negative_control": "SAT rejected a deliberately inverted boundary output",
        "limitations": "Diagnostic only; fixed macro boundaries, no native placement/timing or console validation.",
    }
    if network is not None:
        rebuilt = network.splice(result, inputs, outputs, logic_types, native_ids, logic_names)
        # Prove the parsed output EDIF as well as ABC's in-memory mapping. This
        # catches connection, INIT, output-alias and constant reconstruction bugs.
        rebuilt_model, _ = rebuilt.logic_model(native_ids)
        merged = report / (profile + "-merged.v")
        merged.write_text(render_logic(rebuilt_model, logic_types, inputs, outputs, "gbc_merged", logic_names))
        run(profile + "-merged", ["read_verilog " + quote(source) + " " + quote(merged),
                                  # Lower constant LUT tables before SAT, as in
                                  # the first proof. Unlowered word shifts add
                                  # over a million irrelevant SAT variables.
                                  "proc", "opt", "techmap", "opt",
                                  "miter -equiv -flatten gbc_logic gbc_merged miter",
                                  "hierarchy -top miter",
                                  "sat -verify -prove trigger 0 -show-inputs -show-outputs"])
        (report / (profile + ".edf")).write_text(rebuilt.implementation_text())
        summaries[profile]["edif_equivalence"] = "proved after serializing and reparsing the merged native EDIF"
        summaries[profile]["fixed_structure"] = "all fixed instance definitions, pin nets, net properties and top-level interface unchanged"
        summaries[profile]["merged_cells"] = dict(sorted(Counter(c["type"] for c in rebuilt_model["cells"].values()).items()))
    (report / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
print(json.dumps(summaries, indent=2))
