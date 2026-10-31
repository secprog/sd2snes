#!/usr/bin/env python3
"""Inspect exact unretained IS_PATCH consumer pins; no FPGA generation."""
import importlib.util
import re
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("xdl", Path(__file__).with_name("inspect-dsp-retained-map.py"))
xdl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(xdl)


def constant(statement):
    # Authentic ISE output is: net "GLOBAL_LOGIC1" vcc, ... ;
    return bool(re.match(r'^net\s+"[^"]+"\s+(?:vcc|gnd)\s*,', statement))


def edge_present(instances, nets, comp, pin, net_name="IS_PATCH", kind="inpin"):
    return comp in instances and (kind, comp, pin) in xdl.net_pins(nets.get(net_name, ""))


def controls():
    xdl.fixture_checks()
    for kind in ("vcc", "gnd"):
        assert constant(f'net "GLOBAL" {kind}, inpin "slice" F1;')
    for value in ('net "vcc" , inpin "slice" F1;',
                  'net "GLOBAL" vccx, inpin "slice" F1;',
                  'net "GLOBAL", outpin "vcc" X;', ''):
        assert not constant(value)
    fixture_instances = {"wanted": 'inst "wanted" "SLICEL", cfg " ";'}
    fixture_nets = {"IS_PATCH": 'net "IS_PATCH", inpin "wanted" F2;'}
    assert edge_present(fixture_instances, fixture_nets, "wanted", "F2")
    assert not edge_present({}, fixture_nets, "wanted", "F2")
    assert not edge_present(fixture_instances, fixture_nets, "wanted", "G2")
    assert not edge_present(fixture_instances, {"OTHER": fixture_nets["IS_PATCH"]}, "wanted", "F2")
    assert not edge_present(fixture_instances, {"IS_PATCH": 'net "IS_PATCH", outpin "wanted" F2;'}, "wanted", "F2")
    source_fixture = {"DATA": 'net "DATA", outpin "wanted" X;'}
    assert edge_present(fixture_instances, source_fixture, "wanted", "X", "DATA", "outpin")
    assert not edge_present(fixture_instances, source_fixture, "wanted", "X", "DATA", "inpin")
    print("Exact edge synthetic two positive and five negative controls passed; not FPGA evidence.")
    print("Hosted parser fixtures and explicit constant-source syntax controls passed; synthetic, not FPGA evidence.")


def inspect(family, path):
    controls()
    edges_by_scope = {
        "basex-consumers-a": [("DMA_DINr_0_BRB0", "F2", "IS_PATCH", "inpin"), ("MCU_WR_PENDr", "F1", "IS_PATCH", "inpin"),
                              ("N695", "G1", "IS_PATCH", "inpin"), ("snes_addr/patch_last_2", "F1", "IS_PATCH", "inpin"),
                              ("snes_addr/patch_last_5", "F1", "IS_PATCH", "inpin")],
        "basex-consumers-b": [("snes_bsx/bs_erase_blk_r_3_BRB0", "G3", "IS_PATCH", "inpin"),
                              ("snes_mcu_cmd/ROM_MASK_B<14>", "F2", "IS_PATCH", "inpin"),
                              ("snes_mcu_cmd/ROM_MASK_B<4>", "F1", "IS_PATCH", "inpin"),
                              ("snes_sfxdma/byte_r_0_BRB2", "G1", "IS_PATCH", "inpin"),
                              ("snes_sfxdma/len_r<0>", "G1", "IS_PATCH", "inpin")],
        "basex-ctx22-peer": [("CTX_ROM_ADDRr_22_BRB2", "BX", "IS_PATCH", "inpin")],
        "basex-data-aliases": [("CTX_ROM_ADDRr_7_BRB2", "X", "snes_addr/patch_normal_addr<7>", "outpin"),
                               ("snes_addr/SNES_ADDR<1>", "YQ", "snes_addr/SNES_ADDR<7>", "outpin"),
                               ("CTX_ROM_ADDRr_0_BRB5", "X", "snes_addr/patch_normal_addr<0>", "outpin"),
                               ("snes_mcu_cmd/sfx_len_out<4>", "G2", "snes_addr/patch_last_7", "inpin"),
                               ("ROM_ADDRr<8>", "G2", "snes_addr/patch_last_8", "inpin")],
    }
    if family not in edges_by_scope or path.stat().st_size > 32_000_000:
        raise SystemExit("Invalid scope or excessive XDL")
    instances, nets = xdl.parse(path.read_text(encoding="utf-8", errors="strict"))
    if len(instances) < 100 or len(nets) < 100:
        raise SystemExit("Unexpectedly small full mapped design")
    # Exact edges were retained in authentic complete IS_PATCH and data nets.
    # Their logical low-bit associations are not inferred from COMP names.
    selected = set()
    errors, bindings = [], []
    pin_nets = {}
    for name, statement in nets.items():
        for kind, comp, pin in xdl.net_pins(statement):
            if (comp, pin) in pin_nets:
                raise SystemExit(f"Duplicate physical pin {(comp, pin)}")
            pin_nets[(comp, pin)] = name

    def driver(name):
        if name not in nets:
            errors.append(f"Observed net absent: {name}; not absent logic")
            return
        pins = [(c, p) for k, c, p in xdl.net_pins(nets[name]) if k == "outpin"]
        if constant(nets[name]):
            if pins:
                errors.append(f"Constant net also has outpin: {name}")
            bindings.append(f"Observed net {name}: explicit constant source")
        elif len(pins) != 1 or pins[0][0] not in instances:
            errors.append(f"Ambiguous driver {name}: {pins}")
        else:
            selected.add(pins[0][0])
            bindings.append(f"Observed net {name}: driver={pins[0]}")

    for comp, pin, net_name, kind in edges_by_scope[family]:
        if not edge_present(instances, nets, comp, pin, net_name, kind) or pin_nets.get((comp, pin)) != net_name:
            errors.append(f"Required actual edge absent: {net_name} {kind} {comp}.{pin}; inconclusive")
        else:
            selected.add(comp)
            bindings.append(f"Observed edge {net_name}: {kind} {comp}.{pin}")

    # One physical input-driver layer, then complete incident nets for every COMP.
    # Packed unrelated LUTs are retained but never assumed logically coupled.
    for comp in sorted(selected.copy()):
        for pin in sorted(xdl.INPUT_PINS):
            name = pin_nets.get((comp, pin))
            if name:
                driver(name)
    selected_nets = {name for name, text in nets.items() if any(
        comp in selected for kind, comp, pin in xdl.net_pins(text))}
    records = [instances[n] for n in sorted(selected)] + [nets[n] for n in sorted(selected_nets)]
    raw = "\n".join(records)
    if not selected or len(selected) > 400 or len(selected_nets) > 700 or len(raw.encode()) > 3_000_000:
        raise SystemExit(f"Complete bounds failed: {len(selected)} COMPs/{len(selected_nets)} nets/{len(raw.encode())} bytes")
    print(f"Full XDL {len(instances)} instances/{len(nets)} nets; retained {len(selected)} complete instances/{len(selected_nets)} complete nets/{len(raw.encode())} bytes.")
    print("Complete bounded raw records precede binding outcomes; mapped only, not routed timing.")
    print(raw)
    print("\n".join(sorted(bindings)))
    print(f"Exact observed consumer edges required: {len(edges_by_scope[family])}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("Independent actual LUT equations, physical input pins, output muxes and FF init/clock/CE review required. No timing or hardware pass.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        controls()
    else:
        inspect(sys.argv[1], Path(sys.argv[2]))
