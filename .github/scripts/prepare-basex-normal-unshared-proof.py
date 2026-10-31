#!/usr/bin/env python3
"""GitHub-only source-bound proof preparation; never invoke FPGA tools."""
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PARENT_SHA = "0bffc02d472fd317321ad90e2f3dd685951a77e7b814033408d078a15f032be4"
CANDIDATE_SHA = "3495a360ab7c4f881bda3819decfe495d2de601e389ba378c14b6c9d346c524d"
NORMAL_SHA = "4ac7fb4db5066f86155cb8e456423739b6ace2ebdc1fc21e769c186cefce8af7"
PORTS = [("IS_PATCH", 1), ("SNES_ADDR", 24), ("MAPPER_DEC", 8), ("IS_SAVERAM", 1),
         ("SAVERAM_ADDR", 24), ("SAVERAM_MASK", 24), ("BS_PACK_HIT_HI", 1), ("ROM_MASK", 24),
         ("BS_PACK_HIT", 1), ("LOROM_OFF", 20), ("BSLOROM_HI", 1), ("BSLOROM_ADDR", 24),
         ("MAP_GAMARS", 1), ("BSX_IS_CARTROM", 1), ("BSX_IS_PSRAM", 1), ("BSX_ADDR", 24),
         ("bs_page_enable", 1), ("bs_page", 10), ("bs_page_offset", 9), ("MAP_SUFAMI", 1),
         ("ST_SAVERAM_B", 24), ("SAVERAM_MASK_B", 24), ("ROM_MASK_B", 24)]


def once(text, before, after):
    if text.count(before) != 1:
        raise SystemExit(f"Expected exactly one source boundary: {before!r}")
    return text.replace(before, after, 1)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def normalized(text):
    return re.sub(r"\s+", "", re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S))


def declarations(ports):
    return "\n".join(f"  input {'[' + str(width-1) + ':0] ' if width > 1 else ''}{name}," for name, width in ports)


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("GitHub-hosted execution only")
    prior_name, fixtures_name, output_name = sys.argv[1:]
    prior, fixtures, output = Path(prior_name), Path(fixtures_name), Path(output_name)
    source = (prior / "candidate.v").read_text()
    if sha(source) != PARENT_SHA:
        raise SystemExit("Exact rejected parent candidate mismatch")
    data_bytes = (fixtures / "slow-path-proof-data.json").read_bytes()
    data = json.loads(data_bytes)["basex"]
    if (prior / "proof-data.json").read_bytes() != data_bytes:
        raise SystemExit("Full prior proof fixture mismatch")
    if (prior / "original.v").read_bytes() != (fixtures / "slow-path-parent-basex.v").read_bytes():
        raise SystemExit("Full prior proof original source mismatch")
    if json.loads((prior / "projection-boundary.json").read_text()) != [list(p) for p in PORTS]:
        raise SystemExit("Prior proof common-input projection changed")
    old_body, old_helpers = data["body"], data["helpers"]
    if source.count(old_body) != 1 or source.count(old_helpers) != 1:
        raise SystemExit("Parent actual source does not contain exact proof boundaries")
    start = old_body.index("assign patch_normal_addr = ")
    end = old_body.index("\nbasex_patch_last_mux patch_last_0", start)
    normal = old_body[start:end]
    if len(normal.encode()) != 4935 or sha(normal) != NORMAL_SHA:
        raise SystemExit("Complete normal-mapper expression mismatch")
    helper_ports = PORTS[1:]
    instance = "basex_normal_addr_unshared normal_addr_unshared(\n" + "\n".join(
        f"  .{name}({name})," for name, _ in helper_ports
    ) + "\n  .patch_normal_addr(patch_normal_addr)\n);"
    helper = ('// Keep the existing normal-map arithmetic independent across priority branches.\n'
              '// This targets the measured input muxes before the shared 24-bit adder.\n'
              '(* resource_sharing = "no" *)\n'
              'module basex_normal_addr_unshared(\n' + declarations(helper_ports)
              + '\n  output wire [23:0] patch_normal_addr\n);\n' + normal + '\nendmodule\n')
    appendix = "\n`ifdef MK2\n`ifdef BASE_EXT\n`ifndef BOOTLEG\n" + helper + "`endif\n`endif\n`endif\n"
    new_body = once(old_body, normal, instance)
    candidate = once(source, old_body, new_body) + appendix
    inverse = once(candidate.removesuffix(appendix), new_body, old_body)
    if inverse != source or sha(candidate) != CANDIDATE_SHA:
        raise SystemExit("Whole-source inverse or exact new candidate SHA failed")
    if any(re.search(r"\b" + word + r"\b", re.sub(r"//[^\n]*", "", helper)) for word in ("always", "initial", "reg")):
        raise SystemExit("New helper acquired procedural state")
    bindings = re.findall(r"\.([A-Za-z_][A-Za-z_0-9]*)\(([A-Za-z_][A-Za-z_0-9]*)\)", instance)
    expected_bindings = [(name, name) for name, _ in helper_ports] + [("patch_normal_addr", "patch_normal_addr")]
    if bindings != expected_bindings:
        raise SystemExit("All 22 exact same-name helper input bindings and output were not preserved")

    header = "module address_model(\n" + declarations(PORTS) + "\n  output [23:0] SRAM_SNES_ADDR,\n  output [23:0] NORMAL_ADDR\n);\n"
    alias = "assign NORMAL_ADDR = patch_normal_addr;\n"
    gold = header + old_body + alias + "endmodule\n" + old_helpers
    gate = header + new_body + alias + "endmodule\n" + old_helpers + helper
    changes = {
        "bad-patch": ("result = patch ?", "result = ~patch ?"),
        "bad-direct-bit": (".direct_bit(SNES_ADDR[22])", ".direct_bit(SNES_ADDR[21])"),
        "bad-mapper-priority": ("((MAPPER_DEC[3'b000])", "((MAPPER_DEC[3'b001])"),
        "bad-saveram": ("{15'b0, SNES_ADDR[8:0]}", "{15'b0, SNES_ADDR[9:1]}"),
        "bad-sufami": (":(MAP_SUFAMI)", ":(1'b0)"),
        "bad-bsx-page": (": bs_page_enable", ": 1'b0"),
        "bad-menu-bank": ("+ 24'hC00000", "+ 24'h800000"),
        "bad-helper-mask-b": (".SAVERAM_MASK_B(SAVERAM_MASK_B)", ".SAVERAM_MASK_B(SAVERAM_MASK)"),
        "bad-helper-address": (".SNES_ADDR(SNES_ADDR)", ".SNES_ADDR({SNES_ADDR[23:1], ~SNES_ADDR[0]})"),
    }
    models = {"gold": gold, "gate": gate}
    for name, (before, after) in changes.items():
        models[name] = once(gate, before, after)
    for name, bit in (("bad-x-mapper", "MAPPER_DEC[0]"), ("bad-x-mask", "SAVERAM_MASK[23]")):
        body = new_body.replace(".result(SRAM_SNES_ADDR[", ".result(pre_output[")
        if body.count(".result(pre_output[") != 24:
            raise SystemExit("X-control did not include every final address bit")
        body = "wire [23:0] pre_output;\n" + body + f"assign SRAM_SNES_ADDR = pre_output ^ {{24{{{bit} ^ {bit}}}}};\n"
        models[name] = header + body + alias + "endmodule\n" + old_helpers + helper
    output.mkdir(parents=True, exist_ok=True)
    for name, text in {"original.v": source, "candidate.v": candidate, **{name + ".v": model for name, model in models.items()}}.items():
        (output / name).write_text(text)
    configs = [("none", []), ("mk3", ["MK3"]), ("mk3-ext", ["MK3", "BASE_EXT"]),
               ("mk2", ["MK2"]), ("mk2-bootleg", ["MK2", "BOOTLEG"]),
               ("mk2-ext-bootleg", ["MK2", "BASE_EXT", "BOOTLEG"]), ("ext", ["BASE_EXT"]),
               ("bootleg", ["BOOTLEG"]), ("mk2-ext", ["MK2", "BASE_EXT"]),
               ("mk2-ext-debug", ["MK2", "BASE_EXT", "DEBUG"])]
    preprocessing = []
    for name, defines in configs:
        target = "MK2" in defines and "BASE_EXT" in defines and "BOOTLEG" not in defines
        selected = []
        for version in ("original", "candidate"):
            dest = output / f"pp-{name}-{version}.v"
            subprocess.run(["iverilog", "-g2012", "-E"] + ["-D" + d for d in defines]
                           + ["-o", str(dest), str(output / f"{version}.v")], check=True)
            selected.append(dest.read_text())
        if not all(s.strip() for s in selected):
            raise SystemExit("Empty actual Icarus preprocessing output")
        before, after = selected
        if target:
            after = once(once(after, instance, normal), helper, "")
        if normalized(before) != normalized(after):
            raise SystemExit(f"Actual configuration changed beyond the exact helper extraction: {name}")
        preprocessing.append({"name": name, "defines": defines, "target": target})
    boundary = {"inputs": PORTS, "outputs": [("NORMAL_ADDR", 24), ("SRAM_SNES_ADDR", 24)],
                "helperInputs": helper_ports, "helperBindings": bindings, "normalBytes": len(normal.encode()),
                "normalSha256": NORMAL_SHA, "parentSha256": PARENT_SHA, "candidateSha256": CANDIDATE_SHA,
                "noInputAssumptions": True, "sourceInverseByteExact": True}
    for filename, value in (("preprocessing.json", preprocessing), ("projection-boundary.json", boundary),
                            ("variants.json", list(models))):
        (output / filename).write_text(json.dumps(value, indent=2) + "\n")
    (output / "candidate.diff").write_text("".join(difflib.unified_diff(source.splitlines(True), candidate.splitlines(True), "original.v", "candidate.v")))
    (output / "normal-original.v.txt").write_text(normal + "\n")
    (output / "normal-helper.v.txt").write_text(helper)
    (output / "generator.py.txt").write_bytes(Path(__file__).read_bytes())
    (output / "proof-runner.sh.txt").write_bytes(Path(".github/scripts/run-basex-normal-unshared-proof.sh").read_bytes())
    (output / "prior-proof-data.json").write_bytes(data_bytes)
    (output / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in sorted(output.iterdir()) if p.is_file() and p.name != "SHA256SUMS"))
    print(f"Exact parent/new source, whole inverse, 22 helper inputs and all {len(configs)} actual Icarus configurations verified")
    print(f"Prepared {len(models)} models comparing both complete 24-bit outputs; proof and independent miter/witness review remain required")


if __name__ == "__main__":
    main()
