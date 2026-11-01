#!/usr/bin/env python3
"""Hosted-only bounded physical discovery; no synthesis, routing or Boolean evaluation.

Every retained record is complete. Source-label matches locate evidence; they do
not prove that packed LUTs or FFs are logically connected. An unresolved alias is
reported as inconclusive after all available raw evidence has been retained.
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path


MAX_XDL = 32_000_000
MAX_INSTANCES = 2000
MAX_NETS = 6000
MAX_PART_BYTES = 3_000_000
MAX_TOTAL_BYTES = 96_000_000
LABEL = re.compile(r'(?<!\S)(F|G|FFX|FFY):([^:\s]+):')
RELEVANT = re.compile(r'normal_addr_unshared|patch_normal_addr|patch_last_|srtc_other_permit|srtc_late_bits|srtc_enable|(?:^|/)IS_PATCH$')
CTX_FF = re.compile(r'^CTX_ROM_ADDRr_(\d+)(?:_BRB\d+)?$')


def source_bit(name, prefix, bit):
    return bool(re.search(r'(?:^|/)' + re.escape(prefix) + r'[<\[]' + str(bit) + r'[>\]]$', name))


def patch_bit(name, bit):
    return (name == f'MAPPED_SNES_ADDR<{bit}>'
            or (name.startswith('snes_addr/')
                and (source_bit(name, 'SRAM_SNES_ADDR', bit)
                     or bool(re.search(r'(?:^|/)patch_last_' + str(bit) + r'(?:/[^\s:]*)?$', name)))))


def controls(xdl):
    xdl.fixture_checks()
    assert source_bit('snes_addr/normal_addr_unshared/patch_normal_addr<7>', 'patch_normal_addr', 7)
    assert not source_bit('snes_addr/patch_normal_addr<17>', 'patch_normal_addr', 7)
    assert not source_bit('snes_addr/patch_normal_addr<7>_other', 'patch_normal_addr', 7)
    assert patch_bit('snes_addr/patch_last_7', 7)
    assert patch_bit('snes_addr/patch_last_7/result', 7)
    assert not patch_bit('snes_addr/patch_last_17', 7)
    assert not patch_bit('snes_addr/patch_last_7_other', 7)
    assert not patch_bit('snes_ctx/SRAM_SNES_ADDR<7>', 7)
    assert not patch_bit('other/MAPPED_SNES_ADDR<7>', 7)
    assert CTX_FF.fullmatch('CTX_ROM_ADDRr_21_BRB0')
    assert not CTX_FF.fullmatch('other_CTX_ROM_ADDRr_21_BRB0')
    print('Hosted parser and source-label positive/negative controls passed; not FPGA evidence.')


def inspect(path, output, xdl):
    if path.stat().st_size > MAX_XDL:
        raise SystemExit('Excessive XDL; no truncated inspection accepted')
    raw_input = path.read_bytes()
    instances, nets = xdl.parse(raw_input.decode('utf-8', errors='strict'))
    if len(instances) < 100 or len(nets) < 100:
        raise SystemExit('Unexpectedly small full mapped design')
    output.mkdir(parents=True, exist_ok=False)
    errors = []
    pin_nets, incident, net_pins, labels = {}, {name: set() for name in instances}, {}, {}
    for name, statement in nets.items():
        pins = xdl.net_pins(statement)
        net_pins[name] = pins
        for kind, comp, pin in pins:
            if comp not in instances:
                errors.append(f'Net {name} references missing COMP {comp}')
                continue
            if (comp, pin) in pin_nets:
                errors.append(f'Duplicate physical pin {comp}.{pin}')
            pin_nets[(comp, pin)] = name
            incident[comp].add(name)
    for comp, statement in instances.items():
        for slot, label in LABEL.findall(' '.join(statement.split())):
            labels.setdefault(label, []).append({'comp': comp, 'slot': slot})

    def driver(name):
        statement = nets[name]
        pins = [(comp, pin) for kind, comp, pin in net_pins[name] if kind == 'outpin']
        constant = bool(re.match(r'^net\s+"[^\"]+"\s+(?:vcc|gnd)\s*,', statement))
        if constant:
            if pins:
                errors.append(f'Constant net also has an output pin: {name}')
            return set()
        if len(pins) != 1 or pins[0][0] not in instances:
            errors.append(f'No unique actual driver for {name}: {pins}')
            return set()
        return {pins[0][0]}

    def matched(pattern):
        matched_nets = sorted(name for name in nets if pattern(name))
        matched_labels = {name: labels[name] for name in sorted(labels) if pattern(name)}
        components = {entry['comp'] for values in matched_labels.values() for entry in values}
        for name in matched_nets:
            components.update(driver(name))
        return {'nets': matched_nets, 'labels': matched_labels, 'components': sorted(components)}

    normal = [matched(lambda name, bit=bit: name.startswith('snes_addr/') and source_bit(name, 'patch_normal_addr', bit)) for bit in range(24)]
    final = [matched(lambda name, bit=bit: patch_bit(name, bit)) for bit in range(24)]
    for label, groups in (('normal', normal), ('final patch', final)):
        for bit, group in enumerate(groups):
            if not group['nets'] and not group['labels']:
                errors.append(f'Unresolved {label} bit {bit}: no exact source label; no missing-logic inference')
    relevant = matched(lambda name: bool(RELEVANT.search(name)))
    ctx = {label: entries for label, entries in labels.items()
           if CTX_FF.fullmatch(label) and any(e['slot'] in ('FFX', 'FFY') for e in entries)}
    for label, entries in ctx.items():
        if len([e for e in entries if e['slot'] in ('FFX', 'FFY')]) != 1:
            errors.append(f'Ambiguous exact CTX FF label {label}: {entries}')
    ctx_bits = sorted({int(CTX_FF.fullmatch(label).group(1)) for label in ctx})
    for bit in (21, 22):
        if bit not in ctx_bits:
            errors.append(f'No observed CTX FF source label for measured bit {bit}')
    srtc = []
    try:
        srtc.append(xdl.bind(instances, 'snes_srtc/rtc_ptr_3'))
    except ValueError as error:
        errors.append(f'S-RTC target unresolved: {error}')
    patch_control_nets = sorted(name for name in nets if re.search(r'(?:^|/)IS_PATCH$', name))
    if not patch_control_nets:
        errors.append('No actual IS_PATCH control net located')
    patch_consumers = []
    for name in patch_control_nets:
        patch_consumers.extend({'net': name, 'kind': kind, 'comp': comp, 'pin': pin}
                               for kind, comp, pin in net_pins[name])

    selected = set(relevant['components']) | set(srtc)
    selected.update(e['comp'] for entries in ctx.values() for e in entries)
    selected.update(e['comp'] for e in patch_consumers if e['comp'] in instances)
    for group in normal + final:
        selected.update(group['components'])
    discovery = {'inputSha256': hashlib.sha256(raw_input).hexdigest(),
                 'fullInstances': len(instances), 'fullNets': len(nets),
                 'normalBits': normal, 'finalBits': final, 'relevantSourceLabels': relevant,
                 'allObservedCtxFfLabels': ctx, 'ctxBits': ctx_bits,
                 'srtcTargetComponents': srtc, 'allPatchControlPins': patch_consumers,
                 'initialComponents': sorted(selected),
                 'interpretation': 'Labels locate evidence only. Packed peers are not assumed logically coupled. Unresolved labels are inconclusive, never absent logic.'}
    (output / 'source-discovery.json').write_text(json.dumps(discovery, indent=2) + '\n', encoding='utf-8')

    # Four physical predecessor layers expose output muxes and operand muxes.
    # This is conservative adjacency, not a claim of logical dependencies.
    traversal = []
    frontier = set(selected)
    for depth in range(4):
        following = set()
        for comp in sorted(frontier):
            for pin in sorted(xdl.INPUT_PINS):
                name = pin_nets.get((comp, pin))
                if name:
                    following.update(driver(name))
        following -= selected
        traversal.append({'kind': 'physical-input', 'depth': depth + 1, 'components': sorted(following)})
        selected.update(following)
        frontier = following

    # Continue actual CIN chains to their physical boundary without inventing
    # carry names. Include operand-driver records at each discovered carry slice.
    carry_seen = set()
    carry_frontier = set(selected)
    for depth in range(32):
        following = set()
        for comp in sorted(carry_frontier - carry_seen):
            carry_seen.add(comp)
            name = pin_nets.get((comp, 'CIN'))
            if name:
                following.update(driver(name))
        following -= carry_seen
        if not following:
            break
        selected.update(following)
        traversal.append({'kind': 'carry-input', 'depth': depth + 1, 'components': sorted(following)})
        carry_frontier = following
    else:
        errors.append('Carry adjacency exceeded 32 layers; incomplete, not a pass')
    operand_components = set()
    for comp in sorted(carry_seen):
        if (comp, 'CIN') not in pin_nets:
            continue
        for pin in sorted(xdl.INPUT_PINS - {'CIN'}):
            name = pin_nets.get((comp, pin))
            if name:
                operand_components.update(driver(name))
    selected.update(operand_components)
    selected_nets = set().union(*(incident[c] for c in selected)) if selected else set()
    inventory = {'components': sorted(selected), 'nets': sorted(selected_nets), 'traversal': traversal,
                 'carryOperandComponents': sorted(operand_components),
                 'scopeLimit': 'Four physical predecessor layers plus actual CIN chains and one operand-driver layer. Not a whole-design logical cone or timing proof.'}
    (output / 'physical-scope-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
    if not selected or len(selected) > MAX_INSTANCES or len(selected_nets) > MAX_NETS:
        errors.append(f'Complete scope bound failed: {len(selected)} COMPs/{len(selected_nets)} nets; raw scope not silently truncated')
    else:
        # Partition deterministically by complete COMPs with all incident nets.
        # Repeat nets across parts when necessary; never split an XDL statement.
        parts, current, current_nets, total = [], [], set(), 0

        def body(comps, net_names):
            return ('\n'.join([instances[c] for c in comps] + [nets[n] for n in sorted(net_names)]) + '\n').encode('utf-8')

        def retain(comps, net_names):
            nonlocal total
            data = body(comps, net_names)
            total += len(data)
            if len(data) > MAX_PART_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError('Complete raw record size bound exceeded; no truncation accepted')
            name = f'raw-part-{len(parts):03d}.txt'
            (output / name).write_bytes(data)
            parts.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                          'components': list(comps), 'nets': sorted(net_names)})
            print(f'BEGIN COMPLETE RAW {name}')
            print(data.decode('utf-8'), end='')
            print(f'END COMPLETE RAW {name}')

        try:
            for comp in sorted(selected):
                proposed_nets = current_nets | incident[comp]
                if current and (len(current) >= 40 or len(body(current + [comp], proposed_nets)) > MAX_PART_BYTES):
                    retain(current, current_nets)
                    current, current_nets = [], set()
                current.append(comp)
                current_nets.update(incident[comp])
            if current:
                retain(current, current_nets)
        except ValueError as error:
            errors.append(str(error))
        retained_comps = {c for part in parts for c in part['components']}
        retained_nets = {n for part in parts for n in part['nets']}
        if retained_comps != selected or retained_nets != selected_nets:
            errors.append('Retained raw parts do not cover the complete declared scope')
        (output / 'raw-record-manifest.json').write_text(json.dumps(parts, indent=2) + '\n', encoding='utf-8')
    result = {'errors': sorted(set(errors)), 'sourceLabelsLocated': {'normal': sum(bool(g['nets'] or g['labels']) for g in normal),
              'final': sum(bool(g['nets'] or g['labels']) for g in final)},
              'physicalComponents': len(selected), 'physicalNets': len(selected_nets),
              'reviewRequired': 'Independent equations/pins/output mux/FF CLK INIT CE SR/carry review. No mapped equivalence, timing or hardware pass.'}
    (output / 'inspection-result.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    if errors:
        raise SystemExit('Physical scope incomplete or ambiguous; retain NCD for read-only continuation, never rebuild unchanged')


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('GitHub-hosted inspection only')
    spec = importlib.util.spec_from_file_location('xdl', Path(__file__).with_name('inspect-dsp-retained-map.py'))
    xdl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(xdl)
    controls(xdl)
    if sys.argv[1:] == ['--self-test']:
        return
    if len(sys.argv) != 3:
        raise SystemExit('usage: inspect-basex-normal-unshared-map.py XDL OUTPUT_DIRECTORY')
    inspect(Path(sys.argv[1]), Path(sys.argv[2]), xdl)


if __name__ == '__main__':
    main()
