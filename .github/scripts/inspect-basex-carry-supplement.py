#!/usr/bin/env python3
"""Hosted-only extra carry records from exact retained export A, without conversion.

The original 67-part collection and every old failure remain unchanged. This
separate task closes seven explicitly observed CIN-source record boundaries.
It follows physical pin references only; it never evaluates LUT equations.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys

COLLECTOR_SHA = 'dc33fa85bd0c3a8f45d03bf298ca03575226b4d6a490ba23106ba85e94b63b2a'
FIXTURE_SHA = '0d914a29bfdccc00e50866a9da14346c801a3dcbbde512aaa2d7c0c6f28921f9'
MAX_SELECTED_COMPONENTS = 400
MAX_SELECTED_NETS = 4000
MAX_CARRY_DEPTH = 32
OPERAND_PINS = {f'{s}{i}' for s in 'FG' for i in range(1, 5)} | {'BX', 'BY', 'FXINA', 'FXINB'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    data = (json.dumps(value, indent=2) + '\n').encode('utf-8')
    require(len(data) <= 3_000_000, f'Derived JSON exceeds3MB: {path.name}')
    path.write_bytes(data)


def load_collector():
    path = Path(__file__).with_name('inspect-basex-diagnosed-partitions.py')
    require(path.is_file() and not path.is_symlink(), 'Missing regular pinned collector')
    require(sha(path.read_bytes()) == COLLECTOR_SHA, 'Pinned collector source differs')
    spec = importlib.util.spec_from_file_location('prior_base_collector', path)
    require(spec is not None and spec.loader is not None, 'Cannot load pinned collector')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source(name, nets, pins):
    require(name in nets, f'Missing complete net: {name}')
    outputs = [(c, p) for kind, c, p in pins[name] if kind == 'outpin']
    if re.match(r'^net\s+"[^"\n]+"\s+(?:vcc|gnd)\s*,', nets[name]):
        require(not outputs, f'Constant net has a source pin: {name}')
        return None
    require(len(outputs) == 1, f'Nonunique source: {name}')
    return outputs[0]


def carry_active(statement):
    return bool(re.search(r'(?<!\S)CYINIT::(?:CIN|BX)(?=\s)', statement))


def collect_selection(instances, nets, pins, pin_nets, seed_components, progress=None):
    selected, processed, paths, operands = set(), set(), [], []
    pending = list(sorted(seed_components))
    while pending:
        initial = pending.pop(0)
        chain, comp = [], initial
        for depth in range(MAX_CARRY_DEPTH):
            require(comp in instances, f'Missing complete requested COMP: {comp}')
            require(comp not in chain, f'CIN cycle at {comp}')
            chain.append(comp)
            selected.add(comp)
            if progress is not None:
                progress.update(componentsObserved=sorted(selected), currentChain=list(chain),
                                completedChainRequests=list(paths), complete=False)
            require(len(selected) <= MAX_SELECTED_COMPONENTS, 'Separate400-COMP supplement bound exceeded')
            name = pin_nets.get((comp, 'CIN'))
            if name is None:
                if carry_active(instances[comp]):
                    require(re.search(r'(?<!\S)CYINIT::BX(?=\s)', instances[comp]),
                            f'Carry start has no CIN or BX selection: {comp}')
                    require((comp, 'BX') in pin_nets, f'Carry start has no physical BX net: {comp}')
                break
            require(re.search(r'(?<!\S)CYINIT::CIN(?=\s)', instances[comp]),
                    f'Observed CIN pin without selected CIN configuration: {comp}')
            driver = source(name, nets, pins)
            require(driver is not None and driver[1] in ('COUT', 'XB', 'YB'),
                    f'CIN source is not an actual carry output: {comp}/{name}/{driver}')
            comp = driver[0]
        else:
            raise ValueError('A requested CIN chain exceeds32 complete stages; no truncation')
        paths.append({'requested': initial, 'componentsFromConsumerTowardStart': chain})
        # Include all physical F/G/bypass/wide-mux operand sources of every
        # selected carry slice. A newly included carry slice also receives its
        # own complete CIN chain and operand records, to a bounded fixed point.
        # CE/SR/CLK and all other pins remain in every complete incident net;
        # this does not unroll FF state or recursively expand ordinary LUT cones.
        for current in sorted(selected - processed):
            processed.add(current)
            if not carry_active(instances[current]):
                continue
            for pin in sorted(OPERAND_PINS):
                name = pin_nets.get((current, pin))
                if name is None:
                    continue
                driver = source(name, nets, pins)
                operands.append({'consumer': current, 'pin': pin, 'net': name,
                                 'source': None if driver is None else {'comp': driver[0], 'pin': driver[1]}})
                if driver is not None:
                    require(driver[0] in instances, f'Missing operand source COMP: {name}')
                    if driver[0] not in selected and driver[0] not in pending:
                        pending.append(driver[0])
        pending.sort()
    validate_selection(instances, nets, pins, pin_nets, seed_components, selected)
    if progress is not None:
        progress.update(componentsObserved=sorted(selected), currentChain=[],
                        completedChainRequests=paths, complete=True)
    return selected, paths, operands


def validate_selection(instances, nets, pins, pin_nets, seed_components, selected):
    require(set(seed_components) <= selected, 'Missing explicit seed source COMP')
    require(len(selected) <= MAX_SELECTED_COMPONENTS, 'Separate400-COMP supplement bound exceeded')
    for comp in sorted(selected):
        require(comp in instances, f'Missing selected raw COMP: {comp}')
        if not carry_active(instances[comp]):
            continue
        for pin in sorted(OPERAND_PINS | {'CIN'}):
            name = pin_nets.get((comp, pin))
            if name is None:
                continue
            driver = source(name, nets, pins)
            require(driver is None or driver[0] in selected,
                    f'Incomplete selected carry/operand source: {comp}.{pin}/{name}')


def controls(reader):
    # Small text-only pin-reference fixtures, executed on GitHub only.
    text = '''inst "a" "SLICEL", cfg " CYINIT::BX F:x:#LUT:D=A1 ";
inst "b" "SLICEL", cfg " CYINIT::CIN F:y:#LUT:D=A1 ";
inst "q" "SLICEL", cfg " CYINIT::#OFF F:z:#LUT:D=A1 ";
net "zero" gnd, inpin "a" BX;
net "ab", outpin "a" COUT, inpin "b" CIN;
net "qdata", outpin "q" X, inpin "a" F1, inpin "b" F1;
'''
    inst, nets = reader.parse(text)
    pins = {n: reader.net_pins(s) for n, s in nets.items()}
    pin_nets = {(c, p): n for n, values in pins.items() for kind, c, p in values}
    selected, paths, operands = collect_selection(inst, nets, pins, pin_nets, {'b'})
    require(selected == {'a', 'b', 'q'}, 'Complete two-stage/operand positive fixture differs')
    require(collect_selection(dict(reversed(list(inst.items()))), dict(reversed(list(nets.items()))),
                              pins, pin_nets, {'b'}) == (selected, paths, operands),
            'Carry selection order is not deterministic')
    negatives = [
        lambda: validate_selection(inst, nets, pins, pin_nets, {'b'}, {'a', 'b'}),
        lambda: validate_selection(inst, nets, pins, pin_nets, {'b'}, {'a', 'q'}),
        lambda: collect_selection({k: v for k, v in inst.items() if k != 'a'}, nets, pins, pin_nets, {'b'}),
        lambda: collect_selection(inst, {k: v for k, v in nets.items() if k != 'ab'}, pins, pin_nets, {'b'}),
        lambda: collect_selection(inst, nets, {**pins, 'ab': [('outpin', 'a', 'X'), ('inpin', 'b', 'CIN')]}, pin_nets, {'b'}),
    ]
    cyc = {**inst, 'a': inst['a'].replace('CYINIT::BX', 'CYINIT::CIN')}
    cyc_nets = {**nets, 'ba': 'net "ba", outpin "b" COUT, inpin "a" CIN;'}
    cyc_pins = {**pins, 'ba': [('outpin', 'b', 'COUT'), ('inpin', 'a', 'CIN')]}
    negatives.append(lambda: collect_selection(cyc, cyc_nets, cyc_pins, {**pin_nets, ('a', 'CIN'): 'ba'}, {'b'}))
    def depth_fixture(count):
        fixture_inst = {f'c{i}': f'inst "c{i}" "SLICEL", cfg " CYINIT::{"BX" if i == 0 else "CIN"} ";'
                        for i in range(count)}
        fixture_nets = {'zero': 'net "zero" gnd, inpin "c0" BX;'}
        fixture_nets.update({f'n{i}': f'net "n{i}", outpin "c{i-1}" COUT, inpin "c{i}" CIN;'
                             for i in range(1, count)})
        fixture_pins = {n: reader.net_pins(s) for n, s in fixture_nets.items()}
        fixture_pin_nets = {(c, p): n for n, values in fixture_pins.items() for kind, c, p in values}
        return collect_selection(fixture_inst, fixture_nets, fixture_pins, fixture_pin_nets, {f'c{count-1}'})
    require(len(depth_fixture(32)[0]) == 32, 'Exact32-stage text boundary rejected')
    negatives.append(lambda: depth_fixture(33))
    many = {f'q{i}': f'inst "q{i}" "SLICEL", cfg " CYINIT::#OFF ";' for i in range(401)}
    require(len(collect_selection(many, {}, {}, {}, set(list(many)[:400]))[0]) == 400,
            'Exact400-COMP text boundary rejected')
    negatives.append(lambda: collect_selection(many, {}, {}, {}, set(many)))
    for number, negative in enumerate(negatives, 1):
        try:
            negative()
        except ValueError:
            pass
        else:
            raise ValueError(f'Carry supplement negative fixture{number} was accepted')
    print('Hosted carry-source, operand completeness, determinism, missing seed/record/net, wrong-output, cycle,32/33-stage and400/401-COMP controls passed; text fixtures only.')


def inspect(export_path, prior_root, output, fixture, collector, reader):
    raw = collector.exact_bytes(export_path, fixture['exportA']['bytes'], fixture['exportA']['sha256'])
    text = raw.decode('utf-8', errors='strict')
    require('\0' not in text, 'NUL in exact retained export')
    expected_paths = {m['name'] for m in fixture['members']}
    require(len(expected_paths) == len(fixture['members']) == 88, 'Expected exactly88 unique prior files')
    actual_paths = {p.relative_to(prior_root).as_posix() for p in prior_root.rglob('*') if p.is_file()}
    require(actual_paths == expected_paths, 'Complete prior collection file inventory differs')
    for item in fixture['members']:
        name = item['name']
        parsed = PurePosixPath(name)
        require(not parsed.is_absolute() and '..' not in parsed.parts and '\\' not in name and ':' not in name,
                'Unsafe fixture member')
        collector.exact_bytes(prior_root / name, item['bytes'], item['sha256'])
    prior = prior_root / 'successor-diagnosed-parts-basex'
    original_result = json.loads((prior / 'inspection-result.json').read_text(encoding='utf-8'))
    require(original_result['errors'] == [] and original_result['parts'] == 67
            and original_result['retainedComponents'] == 2613 and original_result['retainedNets'] == 7344,
            'Prior successful collection outcome differs')
    instances, nets = reader.parse(text)
    require((len(instances), len(nets)) == (3611, 8928), 'Exact full export inventory differs')
    pins = {n: reader.net_pins(s) for n, s in nets.items()}
    pin_nets, incident = {}, {c: set() for c in instances}
    for name, values in pins.items():
        source(name, nets, pins)
        for kind, comp, pin in values:
            require(comp in instances, f'Net refers to missing COMP: {name}/{comp}')
            require((comp, pin) not in pin_nets, f'Duplicate physical pin: {comp}.{pin}')
            pin_nets[(comp, pin)] = name
            incident[comp].add(name)
    old_inst, old_nets = {}, {}
    manifest = json.loads((prior / 'raw-record-manifest.json').read_text(encoding='utf-8'))
    require(len(manifest) == 67, 'Prior raw partition count differs')
    for part in manifest:
        data = collector.exact_bytes(prior / part['name'], part['bytes'], part['sha256'])
        ci, nn = reader.parse(data.decode('utf-8', errors='strict'))
        require(sorted(ci) == part['components'] and sorted(nn) == part['nets'], 'Prior raw part inventory differs')
        require(set(ci).isdisjoint(old_inst), 'Prior COMP duplicated across parts')
        for name, statement in ci.items():
            require(instances[name] == statement, f'Prior whole COMP changed: {name}')
            old_inst[name] = statement
        for name, statement in nn.items():
            require(nets[name] == statement, f'Prior whole net changed: {name}')
            require(name not in old_nets or old_nets[name] == statement, f'Prior duplicate net differs: {name}')
            old_nets[name] = statement
        require(set(nn) == set().union(*(incident[c] for c in ci)), 'Prior part omitted full incident net')
    require((len(old_inst), len(old_nets)) == (2613, 7344), 'Complete9957 prior raw records differ')
    seeds = []
    for row in fixture['seeds']:
        comp, name = row['source'], row['net']
        require(row['consumer'] in old_inst and comp not in old_inst, 'Expected original missing-source boundary differs')
        require(pin_nets.get((row['consumer'], 'CIN')) == name, 'Original boundary CIN net differs')
        require(source(name, nets, pins) == (comp, row['sourcePin']), 'Original boundary source differs')
        require(len(instances[comp].encode('utf-8')) == row['sourceBytes']
                and sha(instances[comp].encode('utf-8')) == row['sourceSha256'], 'Pinned source COMP differs')
        require(len(nets[name].encode('utf-8')) == row['netBytes']
                and sha(nets[name].encode('utf-8')) == row['netSha256'], 'Pinned boundary net differs')
        seeds.append(comp)
    require(len(set(seeds)) == len(seeds) == 7, 'Expected exactly seven unique source seeds')
    output.mkdir(parents=True, exist_ok=False)
    selected, paths, operands, parts, errors, progress = set(), [], [], [], [], {}
    try:
        selected, paths, operands = collect_selection(instances, nets, pins, pin_nets, seeds, progress)
        selected_nets = set().union(*(incident[c] for c in selected))
        require(len(selected_nets) <= MAX_SELECTED_NETS, 'Separate4000-net supplement bound exceeded')
        write_json(output / 'selection.json', {
            'exactSeeds': fixture['seeds'], 'components': sorted(selected), 'nets': sorted(selected_nets),
            'recursiveCinPaths': paths, 'physicalCarryOperandSources': operands,
            'newComponentsOutsideReviewedUnion': sorted(selected - old_inst.keys()),
            'newNetsOutsideReviewedUnion': sorted(selected_nets - old_nets.keys()),
            'interpretation': 'Physical adjacency to a bounded fixed point only; no Boolean evaluation or sequential equivalence.'})
        total = 0
        for comps, net_names in collector.partition_plan(instances, nets, incident, selected):
            data = collector.record_bytes(instances, nets, comps, net_names)
            collector.check_part_bounds(comps, net_names, data, len(parts), total)
            name = f'carry-raw-part-{len(parts):03d}.txt'
            (output / name).write_bytes(data)
            total += len(data)
            parts.append({'name': name, 'bytes': len(data), 'sha256': sha(data),
                          'components': comps, 'nets': sorted(net_names)})
            print(f'BEGIN COMPLETE RAW {name}')
            print(data.decode('utf-8'), end='')
            print(f'END COMPLETE RAW {name}')
        require({c for p in parts for c in p['components']} == selected, 'Missing complete supplement COMP')
        require({n for p in parts for n in p['nets']} == selected_nets, 'Missing complete supplement incident net')
    except (ValueError, KeyError) as error:
        errors.append(str(error))
    finally:
        write_json(output / 'selection-progress.json', progress)
        write_json(output / 'raw-record-manifest.json', parts)
        result = {
            'newSeparateTask': 'Seven observed CIN source boundaries; recursive physical carry/operand source closure',
            'historicalFailuresUnchanged': [41316512383, 41319824540],
            'originalFinalZeroAliasStillMissing': True,
            'priorCollection': {k: fixture[k] for k in ('collectionRun', 'collectionJob', 'collectionHead', 'collectionArtifact')},
            'all88PriorFilesExact': True, 'all9957PriorRawRecordsExact': True,
            'exportA': fixture['exportA'], 'mappedNcdSha256': fixture['mappedNcdSha256'],
            'limits': fixture['limits'], 'parts': len(parts), 'rawBytes': sum(p['bytes'] for p in parts),
            'retainedComponents': len({c for p in parts for c in p['components']}),
            'retainedNets': len({n for p in parts for n in p['nets']}), 'errors': errors,
            'reviewRequired': 'Every fresh raw record, exact CIN chains/operand sources, LUT/pin/output mux and FF INIT/CLK/CE/SR. No native, timing, mapped equivalence or hardware pass.'}
        write_json(output / 'inspection-result.json', result)
        print(json.dumps(result, indent=2))
    if errors:
        raise SystemExit('Separate carry supplement incomplete; no gate waiver or unchanged rerun')


def main():
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'GitHub-hosted read-only collection only')
    collector = load_collector()
    reader, original = collector.load_modules()
    collector.controls(reader, original)
    controls(reader)
    if sys.argv[1:] == ['--self-test']:
        return
    require(len(sys.argv) == 4, 'usage: inspect-basex-carry-supplement.py EXPORT_A PRIOR_COLLECTION_ROOT OUTPUT')
    fixture_path = Path(__file__).resolve().parent.parent / 'fixtures' / 'basex-carry-supplement-data.json'
    require(fixture_path.is_file() and not fixture_path.is_symlink(), 'Missing regular supplement fixture')
    raw = fixture_path.read_bytes()
    require(sha(raw) == FIXTURE_SHA, 'Exact supplement fixture differs')
    fixture = json.loads(raw.decode('utf-8', errors='strict'))
    require(fixture['limits'] == {'partComponents': 40, 'partNets': 6000, 'partBytes': 3_000_000,
            'totalRawBytes': 96_000_000, 'parts': 128, 'supplementComponents': MAX_SELECTED_COMPONENTS,
            'supplementNets': MAX_SELECTED_NETS, 'maximumCarryDepth': MAX_CARRY_DEPTH}, 'Explicit supplement limits differ')
    inspect(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), fixture, collector, reader)


if __name__ == '__main__':
    main()
