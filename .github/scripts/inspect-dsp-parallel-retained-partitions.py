#!/usr/bin/env python3
"""Hosted read-only partitioning of three failed DSP MAP evidence collections.

Inputs are an export of the exact retained NCD and the authenticated original
text report artifact. This does not invoke FPGA tools or evaluate equations.
Every original success and failure report is copied byte-for-byte. Only the
three previously unprinted record unions receive new bounded partitions.
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted inspection only; never execute locally')

PREFIX = 'dsp-parallel-stack-isolated-map-'
LIMITS = (400, 700, 3_000_000)
ORIGINAL_RUN = 41316546477
ORIGINAL_JOB = 124877702834
ORIGINAL_HEAD = '5ffc853511cb8f6808dd0609a94bded32665aff5'
RETAINED_NCD_SHA256 = '4f7b507e401b716cc16da5c89f2c7bfe18bdb6b33bc1dd76db36e43f7b961113'
ORIGINAL_XDL_SHA256 = '61b8d5bc20c9ce7901795981902af4b82a6047a029b9c367ce5ae3f26b947844'
REPORT_ZIP_SHA256 = '3fb508b75d66b1673cabbe706705ebd61da434374fd9a9b874e9a3927404f90f'
MAX_TOTAL_RAW_BYTES = 96_000_000
MAX_TOTAL_PARTS = 128
REPORT_PINS = {
    'raw-address-high.txt': (269790, 'aabe514b95a6773b1e4233ed739155d7a3c4ea1e83136845fb0acc8550b77d16'),
    'raw-address-low.txt': (382215, '65db81f2392fcf06afb6dd9753ecd136973b45ca16f69a3e83c38d3ab5db4ee7'),
    'raw-cpu-permits.txt': (308971, '75237186836370bf5521ac23ce403d8a5c4b760a9050dc5a0c4f546492ef1f80'),
    'raw-dsp-status.txt': (451, '6848d392111a45aaa9967cc7b323bee8a3d7cd0d338dea227e4400678c7e94b5'),
    'raw-joins-high-0.txt': (571848, '122c2fc0fe246a64a249a703b42e8cefea34130ffc4e14e4bff1e9e029f017db'),
    'raw-joins-high-8.txt': (555833, '75feac09e0e882de1d648e1d4678c3c8aa55843b50af2b136ff16f1d23cd2acd'),
    'raw-joins-low-0.txt': (1074, '28df40c33cbe20bb9c0a5c790eb27a02f418082cdd04045961ebbc34ebf4f67c'),
    'raw-joins-low-8.txt': (1074, '3dcd9f034293fe00c193619c45de1d773a65e7bfa73c3731ed7877a98c0655c7'),
    'raw-sources.txt': (508728, '0ee703ed5dbe98b4624dbe5c5ce8e32040e393cb882c1d560de563647f9cd152'),
    'raw-stack-pointer.txt': (346727, '8fa8c8c45ac1a0d14604635f96fc201fa07d370e974a8c6e3f1d94f6724adf77'),
    'scope-dsp-stack-high.txt': (410419, 'c89f7025bd5f2d88ea4d5e02973fec2c00c21565852e54b724804ba1ad520312'),
    'scope-dsp-stack-low.txt': (402974, '13ba7ac0427bfd956f82fce822dc0e7ebe6e5a70bf16eace89304f67b1f979b2'),
}
FAILED = {
    'dsp-status': (147, 754, 590271),
    'joins-low-0': (237, 1036, 679455),
    'joins-low-8': (250, 1064, 695225),
}
FAILED_FILES = {f'raw-{scope}.txt' for scope in FAILED}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned_module(filename, blob, label):
    path = Path(__file__).with_name(filename)
    raw = path.read_bytes()
    actual = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    require(actual == blob, f'Reviewed dependency changed: {filename}')
    spec = importlib.util.spec_from_file_location(label, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


xdl = pinned_module('inspect-dsp-retained-map.py', '2b3b867372717b5729e26cb4880cb1af0b01a965', 'retained_partition_xdl')
parallel = pinned_module('inspect-dsp-parallel-stack-map.py', '4d766f0cf16948051b62bd93ee6a5f2238e61a98', 'original_parallel_collector')
legacy = pinned_module('inspect-measured-map-partitions.py', 'c3b5e255a911e76040be585abca5e7d2a5224f31', 'original_status_collector')


def raw_records(instances, nets):
    return '\n'.join([instances[n] for n in sorted(instances)] + [nets[n] for n in sorted(nets)])


def collect_status(instances, nets):
    # This is the original dsp-status selection, before its rejecting bounds.
    # No observed name, target, input-pin set, seed or predecessor depth changes.
    pattern = re.compile(r'sr_(?:cpu_|restore_|late_|write_|data_|enable_)')
    targets = [f"snes_dspx/regs_sr_{i}" for i in (0, 1, 7, 8, 9, 10, 11, 13, 14)]
    targets += ["snes_dspx/ss_frozen"]
    observed = ["snes_dspx/ss_frozen", "snes_mcu_cmd/dspx_reset_out"]
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
        if legacy.constant(nets[name]):
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
            target_bindings.append(f"Target {target}: COMP={comp}, FF={hits[0]}{detail}")
        except ValueError as error:
            errors.append(f"Target {target}: {error}; no missing-state inference")
    for comp in sorted(selected.copy()):
        for pin in sorted(xdl.INPUT_PINS):
            name = pin_nets.get((comp, pin))
            if name:
                driver(name)
    selected_nets = {name for name, text in nets.items() if name in observed or any(
        comp in selected for kind, comp, pin in xdl.net_pins(text))}
    raw = raw_records({n: instances[n] for n in selected}, {n: nets[n] for n in selected_nets})
    summary = dict(scope='dsp-status', fullInstances=len(instances), fullNets=len(nets),
                   selectedInstances=len(selected), selectedNets=len(selected_nets),
                   rawBytes=len(raw.encode()), rawSha256=sha(raw.encode()),
                   bindings=bindings, targetBindings=target_bindings, errors=errors,
                   mappedOnly=True, timingPass=False)
    return raw, summary


def incident_index(nets):
    result = {}
    for name, statement in nets.items():
        for _, comp, _ in xdl.net_pins(statement):
            result.setdefault(comp, set()).add(name)
    return result


def partition_records(instances, nets, all_incident):
    """Exact union; each COMP appears once with every complete incident net."""
    require(bool(instances), 'Empty original COMP collection')
    for comp in instances:
        require(all_incident.get(comp, set()) <= nets.keys(), f'Original collection omitted incident nets: {comp}')
    parts, comps, selected_nets = [], set(), set()

    def fits(cs, ns):
        raw = raw_records({n: instances[n] for n in cs}, {n: nets[n] for n in ns})
        return len(cs) <= LIMITS[0] and len(ns) <= LIMITS[1] and len(raw.encode()) <= LIMITS[2]

    for comp in sorted(instances):
        incoming = all_incident.get(comp, set())
        if not fits(comps | {comp}, selected_nets | incoming):
            require(bool(comps), f'Single complete COMP exceeds unchanged bounds: {comp}')
            parts.append((comps, selected_nets))
            comps, selected_nets = set(), set()
        require(fits({comp}, incoming), f'Single complete COMP exceeds unchanged bounds: {comp}')
        comps.add(comp)
        selected_nets.update(incoming)
    if comps:
        parts.append((comps, selected_nets))
    covered_nets = set().union(*(ns for _, ns in parts))
    # Retain any explicitly observed net having no incident selected COMP too.
    orphan_batch = set()
    for name in sorted(nets.keys() - covered_nets):
        if not fits(set(), orphan_batch | {name}):
            require(bool(orphan_batch), f'Single complete net exceeds unchanged bounds: {name}')
            parts.append((set(), orphan_batch))
            orphan_batch = set()
        require(fits(set(), {name}), f'Single complete net exceeds unchanged bounds: {name}')
        orphan_batch.add(name)
    if orphan_batch:
        parts.append((set(), orphan_batch))
    require(len(parts) <= 64, 'Unexpected partition count')
    require(set().union(*(cs for cs, _ in parts)) == instances.keys(), 'COMP coverage differs')
    require(sum(len(cs) for cs, _ in parts) == len(instances), 'COMP duplicated between parts')
    require(set().union(*(ns for _, ns in parts)) == nets.keys(), 'Net coverage differs')
    for cs, ns in parts:
        require(fits(cs, ns), 'Unbounded output partition')
        require(all(all_incident.get(c, set()) <= ns for c in cs), 'Partition omits incident net')
    return parts


def match_records(selected, complete):
    for kind, source, target in zip(('inst', 'net'), selected, complete):
        for name, record in source.items():
            require(target.get(name) == record, f'Original successful {kind} record changed: {name}')


def merge_records(target, additions):
    for dest, src in zip(target, additions):
        for name, statement in src.items():
            require(name not in dest or dest[name] == statement, f'Conflicting retained raw record: {name}')
            dest[name] = statement


def coverage(instances, nets, all_incident):
    targets = [f'snes_dspx/stack<{w}>_{b}' for w in range(16) for b in range(11)]
    targets += [f'snes_dspx/regs_sr_{b}' for b in (0, 1, 7, 8, 9, 10, 11, 13, 14)]
    rows, errors = [], []
    for name in targets:
        try:
            comp = xdl.bind(instances, name)
            slots = re.findall(r'(?<!\S)FF([XY]):' + re.escape(name) + r':#FF(?=\s|$)',
                               ' '.join(instances[comp].split()))
            require(len(slots) == 1, f'Ambiguous FF slot: {name}')
            ce_name, ce_record = xdl.ce_for(nets, comp)
            drivers = [(c, p) for k, c, p in xdl.net_pins(ce_record) if k == 'outpin']
            require(len(drivers) == 1 and drivers[0][0] in instances, f'Missing or ambiguous retained CE driver: {name}')
            require(all_incident.get(comp, set()) <= nets.keys(), f'Missing target incident nets: {name}')
            rows.append(dict(target=name, comp=comp, slot=slots[0], ce=ce_name,
                             ceDriver=drivers[0], compSha256=sha(instances[comp].encode()),
                             ceSha256=sha(ce_record.encode())))
        except ValueError as error:
            errors.append(str(error))
    # The current text union lacked these two actual common-data source COMPs.
    for name in ('snes_dma/kick_data_r<3>', 'snes_dma/kick_data_r<6>'):
        if name not in nets:
            errors.append(f'Missing observed data-source net: {name}')
            continue
        outputs = [(c, p) for k, c, p in xdl.net_pins(nets[name]) if k == 'outpin']
        if len(outputs) != 1 or outputs[0][0] not in instances:
            errors.append(f'Missing observed data-source COMP: {name}')
    return rows, errors


def controls():
    parallel.controls()
    legacy.controls()
    # Synthetic record-count controls only. No LUT or FPGA evaluation.
    inst = {c: f'inst "{c}" "SLICEL", cfg " F:logic:#LUT:D=A1 ";' for c in ('a', 'b')}
    nets = {f'n{c}{i:03}': f'net "n{c}{i:03}" gnd, inpin "{c}" P{i};'
            for c in ('a', 'b') for i in range(350)}
    nets['shared'] = 'net "shared" gnd, inpin "a" SR, inpin "b" SR;'
    nets['observed-alone'] = 'net "observed-alone" gnd, inpin "other" F1;'
    incidence = incident_index(nets)
    parts = partition_records(inst, nets, incidence)
    require(len(parts) == 3 and [len(ns) for _, ns in parts] == [351, 351, 1], 'Partition synthetic positive failed')
    require(parts == partition_records(dict(reversed(list(inst.items()))), dict(reversed(list(nets.items()))), incidence), 'Partition order not deterministic')
    try:
        match_records((inst, nets), ({**inst, 'a': 'changed'}, nets))
    except ValueError:
        pass
    else:
        raise ValueError('Changed successful record accepted')
    too_many = {f'n{i}': f'net "n{i}" gnd, inpin "a" P{i};' for i in range(701)}
    try:
        partition_records({'a': inst['a']}, too_many, incident_index(too_many))
    except ValueError:
        pass
    else:
        raise ValueError('Oversized single COMP accepted')
    try:
        partition_records(inst, {n: r for n, r in nets.items() if n != 'na000'}, incidence)
    except ValueError:
        pass
    else:
        raise ValueError('Omitted incident record accepted')
    rows, errors = coverage(inst, nets, incidence)
    require(not rows and len(errors) == 187, 'Missing target/source fixture accepted')
    print('Hosted partition controls passed: exact union, unchanged bounds, deterministic order, complete incident nets, identity and missing-binding rejection. Synthetic only.')


def main():
    if sys.argv[1:] == ['--self-test']:
        controls()
        return
    if len(sys.argv) != 4:
        raise SystemExit('usage: inspect-dsp-parallel-retained-partitions.py INPUT.xdl ORIGINAL_REPORT_ROOT OUTPUT_DIRECTORY | --self-test')
    controls()
    filename, report_root, output = map(Path, sys.argv[1:])
    require(filename.is_file() and not filename.is_symlink() and filename.stat().st_size <= 32_000_000, 'Invalid or excessive XDL')
    require(report_root.is_dir() and not report_root.is_symlink(), 'Invalid original report root')
    require(not output.exists(), 'Output directory must be new; original reports cannot be overwritten')
    input_bytes = filename.read_bytes()
    require(sha(input_bytes) == ORIGINAL_XDL_SHA256, 'Full original XDL digest differs; do not weaken this check or rebuild')
    text = input_bytes.decode('utf-8', errors='strict')
    require('\0' not in text, 'NUL in text XDL')
    instances, nets = xdl.parse(text)
    require((len(instances), len(nets)) == (3608, 8637), 'Full design record counts differ from authentic original scopes')
    incidence = incident_index(nets)
    output.mkdir(parents=True, exist_ok=False)
    preserved = output / 'original-reports'
    preserved.mkdir()
    retained = ({}, {})
    report_rows, copies, errors = [], [], []
    for suffix, (size, digest) in sorted(REPORT_PINS.items()):
        paths = list(report_root.rglob(PREFIX + suffix))
        require(len(paths) == 1, f'Missing or ambiguous original report: {suffix}')
        path = paths[0]
        require(path.is_file() and not path.is_symlink(), f'Nonregular original report: {suffix}')
        raw = path.read_bytes()
        require((len(raw), sha(raw)) == (size, digest), f'Original report bytes changed: {suffix}')
        content = raw.decode('utf-8', errors='strict')
        require('\0' not in content, f'NUL in original report: {suffix}')
        target = preserved / path.name
        target.write_bytes(raw)
        copies.append((target, raw))
        row = dict(name=path.name, bytes=size, sha256=digest, originalOutcome='failure' if suffix in FAILED_FILES else 'success')
        if suffix not in FAILED_FILES:
            selected = xdl.parse(content)
            match_records(selected, (instances, nets))
            merge_records(retained, selected)
            row.update(instances=len(selected[0]), nets=len(selected[1]), exactOriginalRecordIdentity=True)
        else:
            require(not re.search(r'(?m)^\s*(inst|net)\s+"', content), 'Original failed report unexpectedly contained raw records')
        report_rows.append(row)
    manifest = dict(schemaVersion=1, originalRun=ORIGINAL_RUN, originalJob=ORIGINAL_JOB,
                    originalHead=ORIGINAL_HEAD, originalRunOutcome='failure',
                    originalReportZipSha256=REPORT_ZIP_SHA256,
                    retainedNcdSha256RequiredByWorkflow=RETAINED_NCD_SHA256,
                    inputXdlSha256=sha(input_bytes),
                    fullInstances=len(instances), fullNets=len(nets),
                    limits=dict(instances=LIMITS[0], nets=LIMITS[1], rawBytes=LIMITS[2],
                                totalRawBytes=MAX_TOTAL_RAW_BYTES, totalParts=MAX_TOTAL_PARTS),
                    originalReports=report_rows, recoveredScopes=[], errors=errors,
                    mappedOnly=True, timingPass=False, independentPhysicalReviewRequired=True)
    total_raw_bytes, total_parts = 0, 0
    for scope, expected in FAILED.items():
        raw, summary = collect_status(instances, nets) if scope == 'dsp-status' else parallel.collect(scope, instances, nets)
        actual = tuple(summary[k] for k in ('selectedInstances', 'selectedNets', 'rawBytes'))
        require(actual == expected, f'Original failed scope collection differs: {scope}: {actual} != {expected}')
        selected = xdl.parse(raw)
        match_records(selected, (instances, nets))
        require(raw_records(*selected) == raw, f'Unexpected original record ordering: {scope}')
        parts = partition_records(*selected, incidence)
        rows, seen = [], ({}, {})
        for number, (cs, ns) in enumerate(parts, 1):
            part = ({n: selected[0][n] for n in cs}, {n: selected[1][n] for n in ns})
            part_raw = raw_records(*part)
            require(total_parts < MAX_TOTAL_PARTS, 'Aggregate partition count exceeded; no truncation')
            require(total_raw_bytes + len(part_raw.encode()) <= MAX_TOTAL_RAW_BYTES, 'Aggregate raw byte bound exceeded; no truncation')
            total_raw_bytes += len(part_raw.encode())
            total_parts += 1
            meta = dict(scope=scope, partition=number, partitionCount=len(parts),
                        instances=len(cs), nets=len(ns), rawBytes=len(part_raw.encode()),
                        rawSha256=sha(part_raw.encode()), completeIncidentNets=True,
                        mappedOnly=True, timingPass=False)
            name = f'{scope}-part-{number:03}.txt'
            report = 'Complete bounded original-scope records; no record or pin-list truncation.\n' + part_raw + '\n' + json.dumps(meta, indent=2, sort_keys=True) + '\n'
            (output / name).write_text(report, encoding='utf-8', newline='\n')
            rows.append(dict(meta, file=name, fileBytes=len(report.encode()), fileSha256=sha(report.encode()),
                             compNames=sorted(cs), netNames=sorted(ns)))
            merge_records(seen, part)
        require(seen == selected, f'Partition union differs from complete original collection: {scope}')
        merge_records(retained, seen)
        record_index = {kind: {n: sha(r.encode()) for n, r in sorted(mapping.items())}
                        for kind, mapping in zip(('instances', 'nets'), selected)}
        # All complete bounded raw partitions exist before binding errors appear.
        summary_path = output / f'{scope}-collection.json'
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
        manifest['recoveredScopes'].append(dict(scope=scope, originalFailureCounts=list(expected),
                                                completeUnionSha256=sha(raw.encode()),
                                                partitions=rows, recordIndex=record_index,
                                                exactOriginalSelectionPreserved=True,
                                                collectionFile=summary_path.name))
        errors.extend(f'{scope}: {message}' for message in summary['errors'])
    target_rows, target_errors = coverage(*retained, incidence)
    errors.extend(target_errors)
    manifest.update(retainedInstances=len(retained[0]), retainedNets=len(retained[1]),
                    totalRawPartitionBytes=total_raw_bytes, totalPartitions=total_parts,
                    requiredTargetCount=185, boundTargetCount=len(target_rows), targetBindings=target_rows)
    for path, raw in copies:
        require(path.read_bytes() == raw, f'Original report copy changed: {path.name}')
    manifest['allOriginalReportCopiesByteIdentical'] = True
    manifest['collectionComplete'] = not errors and len(target_rows) == 185
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({k: manifest[k] for k in ('originalRun', 'originalRunOutcome', 'boundTargetCount', 'collectionComplete', 'allOriginalReportCopiesByteIdentical', 'mappedOnly', 'timingPass')}, sort_keys=True))
    if errors:
        raise ValueError('\n'.join(errors))
    require(len(target_rows) == 185, 'Incomplete 176 stack plus nine SR target coverage')
    print('Complete bounded retained-NCD evidence is available for independent physical review. Original workflow remains failed; no timing or hardware pass.')


if __name__ == '__main__':
    main()
