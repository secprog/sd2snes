#!/usr/bin/env python3
"""Retain complete bounded physical records for the new status/patch hypotheses."""
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


def controls():
    xdl.fixture_checks()
    for kind in ("vcc", "gnd"):
        assert constant(f'net "GLOBAL" {kind}, inpin "slice" F1;')
    for value in ('net "vcc" , inpin "slice" F1;',
                  'net "GLOBAL" vccx, inpin "slice" F1;',
                  'net "GLOBAL", outpin "vcc" X;', ''):
        assert not constant(value)
    print("Hosted parser fixtures and explicit constant-source syntax controls passed; synthetic, not FPGA evidence.")


def inspect(family, path):
    controls()
    if family not in ("dsp", "basex", "dsp-stack-low", "dsp-stack-high", "dsp-stack-decode", "basex-srtc") or path.stat().st_size > 32_000_000:
        raise SystemExit("Invalid family or excessive XDL")
    instances, nets = xdl.parse(path.read_text(encoding="utf-8", errors="strict"))
    if len(instances) < 100 or len(nets) < 100:
        raise SystemExit("Unexpectedly small full mapped design")
    stack_ff = family in ("dsp-stack-low", "dsp-stack-high")
    if stack_ff:
        pattern = re.compile(r'(?!)')
        words = range(8) if family == "dsp-stack-low" else range(8, 16)
        targets = [f"snes_dspx/stack<{w}>_{b}" for w in words for b in range(11)]
        observed = []
    elif family == "dsp-stack-decode":
        pattern = re.compile(r'stack_late_|stack_early_|stack_restore_prefix|restore_prefix_[0-4]|run_permit|restore_permit|late_(?:low|high)_[0-9]+')
        targets = []
        observed = [f"snes_dspx/ss_wa<{b}>" for b in range(8)] + ["snes_dspx/ss_wr"]
        observed += [f"snes_dspx/stack_restore_prefix<{g}>" for g in range(5)]
        observed += [f"snes_dspx/stack_early_{lane}<{i}>" for lane in ("push", "low", "high") for i in range(16)]
        observed += [f"snes_dspx/stack_late_{lane}<{i}>" for lane in ("low", "high") for i in range(16)]
        observed += ["snes_dspx/stack_late_run", "snes_dspx/stack_late_restore"]
    elif family == "basex-srtc":
        pattern = re.compile(r'srtc_other_permit|srtc_late_bits_decode|srtc_enable')
        targets = ["snes_srtc/rtc_ptr_3"]
        observed = ["srtc_enable", "snes_addr/srtc_other_permit", "snes_addr/SNES_ADDR<4>", "snes_addr/SNES_ADDR<6>"]
    elif family == "dsp":
        pattern = re.compile(r'sr_(?:cpu_|restore_|late_|write_|data_|enable_)')
        targets = [f"snes_dspx/regs_sr_{i}" for i in (0, 1, 7, 8, 9, 10, 11, 13, 14)]
        targets += ["snes_dspx/ss_frozen"]
        observed = ["snes_dspx/ss_frozen", "dspx_reset_out"]
    else:
        pattern = re.compile(r'patch_(?:normal_addr|last_)')
        targets = ["snes_addr/SNES_ADDR_21", "CTX_ROM_ADDRr_22_BRB1"]
        observed = ["IS_PATCH", "snes_addr/SNES_ADDR<21>"]
    selected = {name for name, text in instances.items() if pattern.search(text)}
    errors, bindings, target_bindings = [], [], []
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

    for name in sorted(set(observed) | {n for n in nets if pattern.search(n)}):
        driver(name)
    for target in targets:
        try:
            comp = xdl.bind(instances, target)
            selected.add(comp)
            statement = " ".join(instances[comp].split())
            hits = re.findall(r"(?<!\S)FF([XY]):" + re.escape(target) + r":#FF(?=\s|$)", statement)
            if len(hits) != 1:
                raise ValueError("Missing or ambiguous exact FF slot")
            detail = ""
            if stack_ff:
                ce_name, ce = xdl.ce_for(nets, comp)
                driver(ce_name)
                detail = f", CE={ce_name}"
            target_bindings.append(f"Target {target}: COMP={comp}, FF={hits[0]}{detail}")
        except ValueError as error:
            errors.append(f"Target {target}: {error}; no missing-state inference")
    # One physical input-driver layer, then complete incident nets for every COMP.
    # Packed unrelated LUTs are retained but never assumed logically coupled.
    for comp in ([] if stack_ff else sorted(selected.copy())):
        for pin in sorted(xdl.INPUT_PINS):
            name = pin_nets.get((comp, pin))
            if name:
                driver(name)
    selected_nets = {name for name, text in nets.items() if name in observed or any(
        comp in selected for kind, comp, pin in xdl.net_pins(text))}
    records = [instances[n] for n in sorted(selected)] + [nets[n] for n in sorted(selected_nets)]
    raw = "\n".join(records)
    if not selected or len(selected) > 400 or len(selected_nets) > 700 or len(raw.encode()) > 3_000_000:
        raise SystemExit(f"Complete bounds failed: {len(selected)} COMPs/{len(selected_nets)} nets/{len(raw.encode())} bytes")
    print(f"Full XDL {len(instances)} instances/{len(nets)} nets; retained {len(selected)} complete instances/{len(selected_nets)} complete nets/{len(raw.encode())} bytes.")
    print("Complete bounded raw records precede binding outcomes; mapped only, not routed timing.")
    print(raw)
    print("\n".join(sorted(bindings)))
    print("\n".join(target_bindings))
    print(f"Exact FF targets bound: {len(target_bindings)}/{len(targets)}")
    if errors:
        raise SystemExit("\n".join(errors))
    print("Independent actual LUT equations, physical input pins, output muxes and FF init/clock/CE review required. No timing or hardware pass.")


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        controls()
    else:
        inspect(sys.argv[1], Path(sys.argv[2]))
