#!/usr/bin/env python3
"""Hosted-only text export from one immutable mapped XDL; no FPGA regeneration.

The original over-bound discovery remains a failure. This different inspection
retains its exact inventory in bounded parts and separately records bit-0
consumers. It does not prove equivalence, logical dependence, or timing.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys


PREFIX = 'basex-normal-unshared-isolated-map-'
NCD_SHA = 'd7491c9fa35596d64c3ab6d6820b3c36f04769ae469467524cc17258f453dc5f'
XDL_SHA = 'fd08df56d4253b729eb00f9cc0fcfb5b3e98a69a9812952f4c0feb0f46da839b'
FILES = {
    'discovery': ('_temp/' + PREFIX + 'physical/source-discovery.json', 122602, 'e23fc08fbb3aca09f58c43d14833e4b5e7e4ff4be81fa3b819a827eccc8f10d8'),
    'inventory': ('_temp/' + PREFIX + 'physical/physical-scope-inventory.json', 444443, 'c0c51c441ee6e506155f1e34218cf22f83f1c4cf36e2059dd09fd5574c6ea59f'),
    'failure': ('_temp/' + PREFIX + 'physical/inspection-result.json', 460, 'bfb62a77704459442618000592f6bba99d904edba22ddc8069af3b82a5f4d432'),
    'srtc': ('_temp/' + PREFIX + 'xdl.txt', 311934, 'b11a7ff51788757e0b163850f287c0bd7aea3eb9ce3809f0b173192c4112c322'),
}
ORIGINAL_ERRORS = [
    'Complete scope bound failed: 2602 COMPs/7335 nets; raw scope not silently truncated',
    'Unresolved final patch bit 0: no exact source label; no missing-logic inference',
]
MODULES = {
    'xdl': ('inspect-dsp-retained-map.py', '0b608c249a64d831b9ec6d9dcef81a030def98928b9025ca421f0b728979a4d7'),
    'original': ('inspect-basex-normal-unshared-map.py', '017036a31802e881fac13fd30097e031bd6af79bee0883976b5d6a83522a2b63'),
}
MAX_XDL_BYTES = 32_000_000
MAX_PART_COMPONENTS = 40
MAX_PART_NETS = 6000
MAX_PART_BYTES = 3_000_000
MAX_TOTAL_RAW_BYTES = 96_000_000
MAX_PARTS = 128
MAX_EXTRA_COMPONENTS = 200
MAX_EXTRA_NETS = 1200
BIT_ZERO_LABELS = {
    'snes_addr/patch_last_0_SW0': [{'comp': 'N1080', 'slot': 'G'}],
    'snes_addr/patch_last_0_SW1': [{'comp': 'DMA_DINr_8_BRB2', 'slot': 'G'}],
    'snes_addr/patch_last_0_SW2': [{'comp': 'snes_mcu_cmd/ROM_MASK<10>', 'slot': 'F'}],
    'snes_addr/patch_last_0_SW3': [{'comp': 'N2276', 'slot': 'F'}],
}
BIT_ZERO_NETS = (
    'IS_PATCH', 'snes_addr/patch_normal_addr<0>', 'snes_addr/SNES_ADDR<0>',
    'snes_addr/patch_last_0_SW1/O', 'ROM_BHE_OBUF', 'ROM_BLE_OBUF',
    'ROM_BLE8', 'ROM_BLE23', 'ROM_ADDR013', 'ROM_ADDR026', 'ROM_ADDR04',
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def exact_bytes(path, expected_size, expected_sha):
    require(path.is_file() and not path.is_symlink(), f'Not a regular evidence file: {path}')
    require(path.stat().st_size == expected_size, f'Evidence size mismatch: {path}')
    data = path.read_bytes()
    require(digest(data) == expected_sha, f'Evidence digest mismatch: {path}')
    return data


def json_write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def record_bytes(instances, nets, comps, net_names):
    return ('\n'.join([instances[c] for c in sorted(comps)] + [nets[n] for n in sorted(net_names)]) + '\n').encode('utf-8')


def check_part_bounds(comps, net_names, content, part_count, total_bytes):
    require(0 < len(comps) <= MAX_PART_COMPONENTS, 'Per-part40-COMP bound exceeded')
    require(len(net_names) <= MAX_PART_NETS, 'Per-part6000-net bound exceeded')
    require(len(content) <= MAX_PART_BYTES, 'Per-part3MB bound exceeded; no truncation')
    require(part_count < MAX_PARTS, 'Maximum128-part bound exceeded; no truncation')
    require(total_bytes + len(content) <= MAX_TOTAL_RAW_BYTES, 'Unchanged96MB aggregate raw bound exceeded')


def validate_plan(instances, nets, incident, requested, parts):
    covered_comps, covered_nets, comp_count, total_bytes = set(), set(), 0, 0
    for number, (comps, net_names) in enumerate(parts):
        content = record_bytes(instances, nets, comps, net_names)
        check_part_bounds(comps, net_names, content, number, total_bytes)
        require(all(incident[c] <= net_names for c in comps), 'Partition omits a complete incident net')
        covered_comps.update(comps)
        covered_nets.update(net_names)
        comp_count += len(comps)
        total_bytes += len(content)
    expected_nets = set().union(*(incident[c] for c in requested)) if requested else set()
    require(covered_comps == set(requested), 'Partition COMP coverage differs')
    require(comp_count == len(requested), 'COMP duplicated across partitions')
    require(covered_nets == expected_nets, 'Partition complete-net union differs')


def partition_plan(instances, nets, incident, requested):
    parts, current, current_nets = [], [], set()
    for comp in sorted(requested):
        require(comp in instances and comp in incident, f'Missing requested COMP: {comp}')
        require(incident[comp] <= nets.keys(), f'Missing complete incident net for COMP: {comp}')
        proposed = current_nets | incident[comp]
        if current and (len(current) >= MAX_PART_COMPONENTS or len(proposed) > MAX_PART_NETS
                        or len(record_bytes(instances, nets, current + [comp], proposed)) > MAX_PART_BYTES):
            parts.append((current, current_nets))
            current, current_nets = [], set()
        current.append(comp)
        current_nets.update(incident[comp])
    if current:
        parts.append((current, current_nets))
    validate_plan(instances, nets, incident, requested, parts)
    return parts


def load_modules():
    result = {}
    for name, (filename, expected_sha) in MODULES.items():
        path = Path(__file__).with_name(filename)
        require(path.is_file() and not path.is_symlink(), f'Missing regular parser source: {path}')
        require(digest(path.read_bytes()) == expected_sha, f'Parser source digest mismatch: {path}')
        spec = importlib.util.spec_from_file_location(name, path)
        require(spec is not None and spec.loader is not None, f'Cannot load parser: {name}')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result[name] = module
    return result['xdl'], result['original']


def controls(reader, original):
    original.controls(reader)
    synthetic = 'inst "one" "SLICEL",placed R1C1 SLICE_X0Y0, cfg " F:a:#LUT:D=A1 ";\nnet "a", outpin "one" X;'
    inst, nets = reader.parse(synthetic)
    require(set(inst) == {'one'} and set(nets) == {'a'}, 'Complete synthetic inventory rejected')
    for records, expected in ((set(inst), {'one', 'missing'}), (set(nets), {'other'})):
        try:
            require(records == expected, 'Synthetic incomplete inventory rejected')
        except ValueError:
            pass
        else:
            raise ValueError('Synthetic incomplete inventory accepted')
    require(not original.patch_bit('snes_addr/patch_last_0_SW1/O', 0), 'Partial alias accepted as final bit0')
    # Exercise the actual partition planner and coverage guards with text records.
    # No equations are interpreted; these are only record/byte/count fixtures.
    names = [f'c{i:03d}' for i in range(41)]
    components = {c: f'inst "{c}" "SLICEL", cfg " F:fixture:#LUT:D=A1 ";' for c in names}
    records = {c: f'net "{c}" gnd, inpin "{c}" F1;' for c in names}
    records['shared'] = 'net "shared" gnd, ' + ', '.join(f'inpin "{c}" SR' for c in names) + ';'
    incidence = {c: {c, 'shared'} for c in names}
    plan = partition_plan(components, records, incidence, set(names))
    require([len(cs) for cs, ns in plan] == [40, 1], '40/41-COMP partition boundary differs')
    require(len(partition_plan(components, records, incidence, set(names[:40]))) == 1, 'Exact40-COMP boundary rejected')
    require(plan == partition_plan(dict(reversed(list(components.items()))), dict(reversed(list(records.items()))),
                                   incidence, set(reversed(names))), 'Partition order is not deterministic')
    oversized = {names[0]: 'inst "c000" "SLICEL", cfg " META::' + 'x' * MAX_PART_BYTES + ' ";'}
    many_nets = {f'n{i}': f'net "n{i}" gnd, inpin "c000" P{i};' for i in range(MAX_PART_NETS + 1)}
    first_comps, first_nets = plan[0]
    altered_missing_net = [(first_comps, first_nets - {'shared'}), plan[1]]
    negatives = (
        lambda: validate_plan(components, records, incidence, set(names), plan[:-1]),
        lambda: validate_plan(components, records, incidence, set(names), altered_missing_net),
        lambda: validate_plan(components, records, incidence, set(names), plan + [plan[1]]),
        lambda: partition_plan(components, {n: s for n, s in records.items() if n != names[0]}, incidence, set(names)),
        lambda: partition_plan(oversized, records, incidence, {names[0]}),
        lambda: partition_plan({names[0]: components[names[0]]}, many_nets, {names[0]: set(many_nets)}, {names[0]}),
        lambda: check_part_bounds([names[0]], {names[0]}, b'x', MAX_PARTS, 0),
        lambda: check_part_bounds([names[0]], {names[0]}, b'x', 0, MAX_TOTAL_RAW_BYTES),
    )
    for number, negative in enumerate(negatives, 1):
        try:
            negative()
        except ValueError:
            pass
        else:
            raise ValueError(f'Partition negative fixture{number} accepted')
    print('Hosted partition boundary, determinism, complete-union, missing-record, duplicate-COMP, byte/net/part/aggregate bound and partial-bit0 controls passed; synthetic only.')


def inspect(path, evidence_root, output, reader, original):
    require(path.is_file() and not path.is_symlink(), 'Input XDL must be a regular file')
    require(path.stat().st_size <= MAX_XDL_BYTES, 'Input XDL exceeds unchanged32MB limit')
    data = path.read_bytes()
    require(digest(data) == XDL_SHA, 'Immutable full XDL digest differs; do not regenerate or weaken this check')
    blobs = {name: exact_bytes(evidence_root / relative, size, sha)
             for name, (relative, size, sha) in FILES.items()}
    discovery = json.loads(blobs['discovery'].decode('utf-8', errors='strict'))
    inventory = json.loads(blobs['inventory'].decode('utf-8', errors='strict'))
    failed = json.loads(blobs['failure'].decode('utf-8', errors='strict'))
    require(failed['errors'] == ORIGINAL_ERRORS, 'Original failed result changed')
    require(failed['sourceLabelsLocated'] == {'normal': 24, 'final': 23}, 'Original alias outcome changed')
    require(failed['physicalComponents'] == 2602 and failed['physicalNets'] == 7335, 'Original failed scope counts changed')
    require(discovery['inputSha256'] == XDL_SHA, 'Discovery bound to another XDL')
    text = data.decode('utf-8', errors='strict')
    require('\0' not in text, 'NUL in XDL')
    instances, nets = reader.parse(text)
    require((len(instances), len(nets)) == (3611, 8928), 'Full design inventory differs')
    pins = {name: reader.net_pins(statement) for name, statement in nets.items()}
    incident = {comp: set() for comp in instances}
    component_pins = {comp: [] for comp in instances}
    pin_nets = {}
    labels = {}
    for name, values in pins.items():
        for kind, comp, pin in values:
            require(comp in instances, f'Net references missing COMP: {name}/{comp}')
            require((comp, pin) not in pin_nets, f'Duplicate physical pin: {comp}.{pin}')
            pin_nets[(comp, pin)] = name
            incident[comp].add(name)
            component_pins[comp].append({'kind': kind, 'pin': pin, 'net': name})
    for comp, statement in instances.items():
        for slot, label in original.LABEL.findall(' '.join(statement.split())):
            labels.setdefault(label, []).append({'comp': comp, 'slot': slot})

    def driver(name):
        require(name in nets, f'Exact observed net missing: {name}')
        outputs = [(comp, pin) for kind, comp, pin in pins[name] if kind == 'outpin']
        constant = re.match(r'^net\s+"[^\"]+"\s+(?:vcc|gnd)\s*,', nets[name])
        if constant:
            require(not outputs, f'Constant net also has output: {name}')
            return set()
        require(len(outputs) == 1, f'Nonunique physical source: {name}/{outputs}')
        return {outputs[0][0]}

    def matched(predicate):
        names = sorted(name for name in nets if predicate(name))
        found_labels = {name: labels[name] for name in sorted(labels) if predicate(name)}
        comps = {entry['comp'] for entries in found_labels.values() for entry in entries}
        for name in names:
            comps.update(driver(name))
        return {'nets': names, 'labels': found_labels, 'components': sorted(comps)}

    normal = [matched(lambda name, bit=bit: name.startswith('snes_addr/') and original.source_bit(name, 'patch_normal_addr', bit)) for bit in range(24)]
    final = [matched(lambda name, bit=bit: original.patch_bit(name, bit)) for bit in range(24)]
    relevant = matched(lambda name: bool(original.RELEVANT.search(name)))
    ctx = {label: entries for label, entries in labels.items()
           if original.CTX_FF.fullmatch(label) and any(e['slot'] in ('FFX', 'FFY') for e in entries)}
    patch_names = sorted(name for name in nets if re.search(r'(?:^|/)IS_PATCH$', name))
    patch_pins = [{'net': name, 'kind': kind, 'comp': comp, 'pin': pin}
                  for name in patch_names for kind, comp, pin in pins[name]]
    srtc = [reader.bind(instances, 'snes_srtc/rtc_ptr_3')]
    for key, actual in (('normalBits', normal), ('finalBits', final), ('relevantSourceLabels', relevant),
                        ('allObservedCtxFfLabels', ctx), ('allPatchControlPins', patch_pins),
                        ('srtcTargetComponents', srtc)):
        require(discovery[key] == actual, f'Fresh actual discovery differs: {key}')
    require(not final[0]['nets'] and not final[0]['labels'], 'Original missing final0 alias changed')
    require(len(ctx) == 56, 'Expected exact56 observed CTX FF labels')
    for label, entries in ctx.items():
        ff_entries = [entry for entry in entries if entry['slot'] in ('FFX', 'FFY')]
        require(len(ff_entries) == 1, f'Ambiguous exact CTX FF: {label}')
        require(reader.bind(instances, label) == ff_entries[0]['comp'], f'Actual CTX FF binding differs: {label}')

    selected = set(relevant['components']) | set(srtc)
    selected.update(e['comp'] for entries in ctx.values() for e in entries)
    selected.update(e['comp'] for e in patch_pins)
    for group in normal + final:
        selected.update(group['components'])
    require(sorted(selected) == discovery['initialComponents'], 'Initial observed COMP set differs')
    traversal = []
    frontier = set(selected)
    for depth in range(4):
        following = set()
        for comp in sorted(frontier):
            for pin in sorted(reader.INPUT_PINS):
                name = pin_nets.get((comp, pin))
                if name:
                    following.update(driver(name))
        following -= selected
        traversal.append({'kind': 'physical-input', 'depth': depth + 1, 'components': sorted(following)})
        selected.update(following)
        frontier = following
    carry_seen, carry_frontier = set(), set(selected)
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
        raise ValueError('Carry traversal exceeds original32-layer bound')
    operand_comps = set()
    for comp in sorted(carry_seen):
        if (comp, 'CIN') in pin_nets:
            for pin in sorted(reader.INPUT_PINS - {'CIN'}):
                name = pin_nets.get((comp, pin))
                if name:
                    operand_comps.update(driver(name))
    selected.update(operand_comps)
    selected_nets = set().union(*(incident[c] for c in selected))
    require(inventory['components'] == sorted(selected) and len(selected) == 2602, 'Exact original COMP inventory differs')
    require(inventory['nets'] == sorted(selected_nets) and len(selected_nets) == 7335, 'Exact original complete incident net inventory differs')
    require(inventory['traversal'] == traversal, 'Original physical predecessor traversal differs')
    require(inventory['carryOperandComponents'] == sorted(operand_comps), 'Original operand-driver set differs')
    for name in selected_nets:
        driver(name)
    srtc_inst, srtc_nets = reader.parse(blobs['srtc'].decode('utf-8', errors='strict'))
    require((len(srtc_inst), len(srtc_nets)) == (41, 279), 'Original SRTC raw inventory differs')
    require(set(srtc_inst) <= selected and set(srtc_nets) <= selected_nets, 'Original SRTC coverage missing')
    for name, statement in srtc_inst.items():
        require(instances[name] == statement, f'Original full SRTC COMP changed: {name}')
    for name, statement in srtc_nets.items():
        require(nets[name] == statement, f'Original full SRTC net changed: {name}')

    output.mkdir(parents=True, exist_ok=False)
    (output / 'original-inspection-result.json').write_bytes(blobs['failure'])
    (output / 'original-source-discovery.json').write_bytes(blobs['discovery'])
    (output / 'original-physical-scope-inventory.json').write_bytes(blobs['inventory'])
    (output / 'original-srtc-raw-report.txt').write_bytes(blobs['srtc'])
    json_write(output / 'immutable-input-binding.json', {
        'originalRun': 41316512383, 'originalJob': 124877607506,
        'originalHead': '5ffc853511cb8f6808dd0609a94bded32665aff5',
        'mappedNcdSha256': NCD_SHA, 'fullXdlSha256': XDL_SHA,
        'evidenceFiles': {k: {'path': v[0], 'bytes': v[1], 'sha256': v[2]} for k, v in FILES.items()},
        'originalFailurePreserved': ORIGINAL_ERRORS,
        'exactOriginalInventoryAndTraversalReproduced': {'components': 2602, 'nets': 7335},
        'originalFullSrtcRawRecordsEqual': {'components': 41, 'nets': 279},
        'interpretation': 'This new partitioned record-retention task does not pass or waive the original failed scope.'})
    parts, total_bytes, errors = [], 0, []
    completed_groups = []
    supplement = set()

    def retain(group, comps, net_names):
        nonlocal total_bytes
        content = record_bytes(instances, nets, comps, net_names)
        check_part_bounds(comps, net_names, content, len(parts), total_bytes)
        name = f'raw-part-{len(parts):03d}.txt'
        (output / name).write_bytes(content)
        total_bytes += len(content)
        parts.append({'name': name, 'group': group, 'bytes': len(content), 'sha256': digest(content),
                      'components': list(comps), 'nets': sorted(net_names)})
        print(f'BEGIN COMPLETE RAW {name}')
        print(content.decode('utf-8'), end='')
        print(f'END COMPLETE RAW {name}')

    def retain_group(group, comps):
        for current, current_nets in partition_plan(instances, nets, incident, comps):
            retain(group, current, current_nets)
        retained = {c for p in parts if p['group'] == group for c in p['components']}
        retained_nets = {n for p in parts if p['group'] == group for n in p['nets']}
        expected_nets = set().union(*(incident[c] for c in comps)) if comps else set()
        require(retained == set(comps) and retained_nets == expected_nets, f'Incomplete group: {group}')
        completed_groups.append(group)

    def net_binding(name):
        driver(name)
        return {'net': name, 'sha256': digest(nets[name].encode('utf-8')),
                'pins': [{'kind': k, 'comp': c, 'pin': p} for k, c, p in pins[name]]}

    def comp_binding(comp):
        return {'comp': comp, 'sha256': digest(instances[comp].encode('utf-8')),
                'physicalPins': sorted(component_pins[comp], key=lambda entry: entry['pin']),
                'rawConfiguration': instances[comp]}

    try:
        retain_group('original-observed-inventory', selected)
        for label, expected in BIT_ZERO_LABELS.items():
            require(labels.get(label) == expected, f'Exact observed partial bit0 label differs: {label}')
            supplement.update(entry['comp'] for entry in expected)
        required_nets = set(BIT_ZERO_NETS)
        for comp in list(supplement):
            required_nets.update(name for name in incident[comp]
                                 if any(kind == 'outpin' and c == comp for kind, c, pin in pins[name]))
        for name in sorted(required_nets):
            driver(name)
            supplement.update(comp for kind, comp, pin in pins[name])
        seed_components = sorted(supplement)
        # One complete physical input-driver layer for the explicit bit0 consumers.
        # Packed peer pins remain physical adjacency, never assumed logic dependence.
        for comp in seed_components:
            for pin in sorted(reader.INPUT_PINS):
                name = pin_nets.get((comp, pin))
                if name:
                    supplement.update(driver(name))
        extra = supplement - selected
        supplement_nets = set().union(*(incident[c] for c in supplement))
        extra_nets = supplement_nets - selected_nets
        json_write(output / 'bit-zero-consumer-discovery.json', {
            'originalExactFinalZeroAliasStillMissing': True,
            'partialLabels': BIT_ZERO_LABELS,
            'observedSeedNets': [net_binding(n) for n in BIT_ZERO_NETS],
            'partialCompOutputNetsWithAllConsumers': [net_binding(n) for n in sorted(required_nets)],
            'seedComponents': seed_components, 'completeOneLayerComponents': sorted(supplement),
            'additionalComponentsOutsideOriginalInventory': sorted(extra),
            'additionalNetsOutsideOriginalInventory': sorted(extra_nets),
            'interpretation': 'Distinct partial-expression/consumer evidence; does not synthesize a missing final0 alias or establish Boolean equivalence.'})
        require(len(extra) <= MAX_EXTRA_COMPONENTS, 'Bit0 supplement exceeds200 additional COMPs; retain original scope and fail')
        require(len(extra_nets) <= MAX_EXTRA_NETS, 'Bit0 supplement exceeds1200 additional nets; retain original scope and fail')
        for name in supplement_nets:
            driver(name)
        retain_group('bit-zero-additional-consumers', extra)
        all_retained_comps = {c for p in parts for c in p['components']}
        all_retained_nets = {n for p in parts for n in p['nets']}
        require(selected | supplement <= all_retained_comps, 'Missing requested consumer COMP')
        require(selected_nets | supplement_nets <= all_retained_nets, 'Missing complete requested consumer incident net')
        json_write(output / 'explicit-boundaries.json', {
            'normalBits': [{'bit': bit, 'observed': group, 'actualNets': [net_binding(n) for n in group['nets']]}
                           for bit, group in enumerate(normal)],
            'finalBits': [{'bit': bit, 'observed': group, 'actualNets': [net_binding(n) for n in group['nets']],
                           'exactSourceAliasLocated': bool(group['nets'] or group['labels'])}
                          for bit, group in enumerate(final)],
            'allObservedCtxFfs': [{'label': label, 'binding': entries,
                                  'component': comp_binding([e for e in entries if e['slot'] in ('FFX', 'FFY')][0]['comp'])}
                                 for label, entries in sorted(ctx.items())],
            'isPatch': [net_binding(n) for n in patch_names],
            'srtcTarget': comp_binding(srtc[0]),
            'srtcNets': [net_binding(n) for n in ('srtc_enable', 'snes_addr/srtc_other_permit',
                                                'snes_addr/SNES_ADDR<4>', 'snes_addr/SNES_ADDR<6>',
                                                'snes_srtc/rtc_ptr_not0001', 'snes_srtc/rtc_ptr_or0000')],
            'carryComponents': [comp_binding(c) for c in sorted(all_retained_comps)
                                if (c, 'CIN') in pin_nets or (c, 'COUT') in pin_nets],
            'interpretation': 'Literal physical records and source bindings for independent review; no equations evaluated.'})
    except (ValueError, KeyError) as error:
        errors.append(str(error))
    finally:
        json_write(output / 'raw-record-manifest.json', parts)
        result = {
            'originalInspectionOutcome': 'failure', 'originalErrorsPreserved': ORIGINAL_ERRORS,
            'newTask': 'Partition complete observed inventory and separately inspect bit0 consumers',
            'completedGroups': completed_groups, 'parts': len(parts), 'rawBytes': total_bytes,
            'retainedComponents': len({c for p in parts for c in p['components']}),
            'retainedNets': len({n for p in parts for n in p['nets']}), 'errors': errors,
            'bounds': {'partComponents': MAX_PART_COMPONENTS, 'partNets': MAX_PART_NETS,
                       'partBytes': MAX_PART_BYTES, 'totalRawBytes': MAX_TOTAL_RAW_BYTES,
                       'parts': MAX_PARTS, 'extraComponents': MAX_EXTRA_COMPONENTS,
                       'extraNets': MAX_EXTRA_NETS},
            'reviewRequired': 'All actual LUT inputs/equations/output muxes, carry operands, and FF INIT/CLK/CE/SR remain for independent review. No source/mapped equivalence, timing or hardware pass.'}
        json_write(output / 'inspection-result.json', result)
        print(json.dumps(result, indent=2))
    if errors:
        raise SystemExit('New partitioned inspection incomplete; original failure preserved; never rebuild unchanged')


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('GitHub-hosted read-only inspection only')
    reader, original = load_modules()
    controls(reader, original)
    if sys.argv[1:] == ['--self-test']:
        return
    if len(sys.argv) != 4:
        raise SystemExit('usage: inspect-basex-unshared-retained-partitions.py INPUT_XDL CURRENT_MAP_REPORT_ROOT OUTPUT_DIRECTORY')
    inspect(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), reader, original)


if __name__ == '__main__':
    main()
