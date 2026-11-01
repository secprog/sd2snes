#!/usr/bin/env python3
"""Hosted text investigation of two fresh exports of one workflow-pinned NCD.

No FPGA generation, Boolean evaluation, identity normalization or old-gate waiver.
The caller retains both full input exports separately on GitHub. This program
retains complete changed records, both design statements and all outside text.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys


READER_SHA = '0b608c249a64d831b9ec6d9dcef81a030def98928b9025ca421f0b728979a4d7'
MAX_INPUT = 32_000_000
MAX_FILE = 3_000_000
MAX_TOTAL_OUTPUT = 96_000_000
MAX_OUTPUT_FILES = 1024
RECORDS_PER_PART = 40
INDEX_ROWS_PER_PART = 256
FAMILIES = {
    'basex': {
        'run': 41316512383, 'job': 124877607506,
        'ncd': 'd7491c9fa35596d64c3ab6d6820b3c36f04769ae469467524cc17258f453dc5f',
        'oldXdl': 'fd08df56d4253b729eb00f9cc0fcfb5b3e98a69a9812952f4c0feb0f46da839b',
        'counts': {'inst': 3611, 'net': 8928, 'design': 1},
        'oldRawCounts': {'inst': 41, 'net': 279},
        'prefix': 'basex-normal-unshared-isolated-map-',
        'pins': {
            'xdl.txt': (311934, 'b11a7ff51788757e0b163850f287c0bd7aea3eb9ce3809f0b173192c4112c322', 'raw-success'),
            'physical/source-discovery.json': (122602, 'e23fc08fbb3aca09f58c43d14833e4b5e7e4ff4be81fa3b819a827eccc8f10d8', 'discovery'),
            'physical/physical-scope-inventory.json': (444443, 'c0c51c441ee6e506155f1e34218cf22f83f1c4cf36e2059dd09fd5574c6ea59f', 'inventory'),
            'physical/inspection-result.json': (460, 'bfb62a77704459442618000592f6bba99d904edba22ddc8069af3b82a5f4d432', 'failed-result'),
        },
    },
    'dsp': {
        'run': 41316546477, 'job': 124877702834,
        'ncd': '4f7b507e401b716cc16da5c89f2c7bfe18bdb6b33bc1dd76db36e43f7b961113',
        'oldXdl': '61b8d5bc20c9ce7901795981902af4b82a6047a029b9c367ce5ae3f26b947844',
        'counts': {'inst': 3608, 'net': 8637, 'design': 1},
        'oldRawCounts': {'inst': 340, 'net': 1457},
        'prefix': 'dsp-parallel-stack-isolated-map-',
        'pins': {
            'raw-address-high.txt': (269790, 'aabe514b95a6773b1e4233ed739155d7a3c4ea1e83136845fb0acc8550b77d16', 'raw-success'),
            'raw-address-low.txt': (382215, '65db81f2392fcf06afb6dd9753ecd136973b45ca16f69a3e83c38d3ab5db4ee7', 'raw-success'),
            'raw-cpu-permits.txt': (308971, '75237186836370bf5521ac23ce403d8a5c4b760a9050dc5a0c4f546492ef1f80', 'raw-success'),
            'raw-dsp-status.txt': (451, '6848d392111a45aaa9967cc7b323bee8a3d7cd0d338dea227e4400678c7e94b5', 'raw-failure'),
            'raw-joins-high-0.txt': (571848, '122c2fc0fe246a64a249a703b42e8cefea34130ffc4e14e4bff1e9e029f017db', 'raw-success'),
            'raw-joins-high-8.txt': (555833, '75feac09e0e882de1d648e1d4678c3c8aa55843b50af2b136ff16f1d23cd2acd', 'raw-success'),
            'raw-joins-low-0.txt': (1074, '28df40c33cbe20bb9c0a5c790eb27a02f418082cdd04045961ebbc34ebf4f67c', 'raw-failure'),
            'raw-joins-low-8.txt': (1074, '3dcd9f034293fe00c193619c45de1d773a65e7bfa73c3731ed7877a98c0655c7', 'raw-failure'),
            'raw-sources.txt': (508728, '0ee703ed5dbe98b4624dbe5c5ce8e32040e393cb882c1d560de563647f9cd152', 'raw-success'),
            'raw-stack-pointer.txt': (346727, '8fa8c8c45ac1a0d14604635f96fc201fa07d370e974a8c6e3f1d94f6724adf77', 'raw-success'),
            'scope-dsp-stack-high.txt': (410419, 'c89f7025bd5f2d88ea4d5e02973fec2c00c21565852e54b724804ba1ad520312', 'raw-success'),
            'scope-dsp-stack-low.txt': (402974, '13ba7ac0427bfd956f82fce822dc0e7ebe6e5a70bf16eace89304f67b1f979b2', 'raw-success'),
        },
    },
}
HEAD = re.compile(r'^(design|inst|net)\s+"((?:[^"\\]|\\.)*)"(?=\s|,|;)')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regular_bytes(path, maximum=MAX_INPUT):
    require(path.is_file() and not path.is_symlink(), f'Nonregular input: {path}')
    require(path.stat().st_size <= maximum, f'Input exceeds strict byte bound: {path}')
    data = path.read_bytes()
    require(len(data) <= maximum, f'Input grew beyond strict byte bound: {path}')
    return data


def load_reader():
    path = Path(__file__).with_name('inspect-dsp-retained-map.py')
    raw = regular_bytes(path, MAX_FILE)
    require(sha(raw) == READER_SHA, 'Original raw-report parser source changed')
    spec = importlib.util.spec_from_file_location('original_xdl_reader', path)
    require(spec is not None and spec.loader is not None, 'Cannot load pinned report reader')
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    return reader


def scan_complete(text):
    """Quote-aware statement boundaries; retain every byte outside statements too.

    Unfamiliar or incomplete statements are preserved as explicit residual
    records before validation fails. No text or whitespace is normalized.
    """
    require('\0' not in text, 'NUL in XDL')
    records, gaps, occurrences, issues = [], [], {}, []
    position, previous_end, line = 0, 0, 1
    while position < len(text):
        complete = False
        while position < len(text):
            if text[position].isspace():
                position += 1
            elif text[position] == '#':
                end = text.find('\n', position)
                position = len(text) if end == -1 else end + 1
            else:
                break
        gap = text[previous_end:position]
        gaps.append({'beforeRecord': len(records), 'characterStart': previous_end,
                     'characterEnd': position, 'line': line, 'text': gap})
        line += gap.count('\n')
        if position == len(text):
            previous_end = position
            break
        start, start_line = position, line
        quoted, escaped, comment = False, False, False
        while position < len(text):
            char = text[position]
            if comment:
                if char == '\n':
                    comment = False
            elif quoted:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == '#':
                comment = True
            elif char == ';':
                position += 1
                complete = True
                break
            position += 1
        raw = text[start:position]
        match = HEAD.match(raw)
        if not complete or match is None:
            kind, name = 'residual', f'character-{start}'
            issues.append(f'Unrecognized or incomplete top-level text at character {start}, line {start_line}; exact residual retained')
        else:
            kind, name = match.groups()
        occurrence = occurrences.get((kind, name), 0)
        occurrences[(kind, name)] = occurrence + 1
        if occurrence:
            issues.append(f'Duplicate complete {kind} record: {name}; occurrence {occurrence} retained')
        records.append({'kind': kind, 'name': name, 'occurrence': occurrence, 'complete': complete, 'line': start_line,
                        'characterStart': start, 'characterEnd': position, 'raw': raw})
        line += raw.count('\n')
        previous_end = position
    if len(gaps) == len(records):
        gaps.append({'beforeRecord': len(records), 'characterStart': previous_end,
                     'characterEnd': previous_end, 'line': line, 'text': ''})
    rebuilt = ''.join(gaps[i]['text'] + r['raw'] for i, r in enumerate(records)) + gaps[-1]['text']
    require(rebuilt == text, 'Full XDL character coverage differs')
    return records, gaps, issues


def keyed(records):
    return {(r['kind'], r['name'], r['occurrence']): r['raw'] for r in records}


def difference_keys(a, b):
    return sorted(key for key in a.keys() | b.keys() if a.get(key) != b.get(key))


def design_identity(raw):
    match = re.match(r'^design\s+"((?:[^"\\]|\\.)*)"\s+([^,;\"]+)[,;]', raw)
    if not match:
        return {'matchesKnownTuple': False, 'reason': 'Unrecognized design declaration; literal statement retained'}
    name, fields = match.groups()
    tokens = fields.split()
    # Both forms are documented XDL syntax; only this observed device tuple is accepted.
    accepted = (['xc3s400pq208-4', 'v3.2'], ['xc3s400', 'pq208', '-4', 'v3.2'])
    return {'name': name, 'declarationTokens': tokens,
            'matchesKnownTuple': name == 'main' and tokens in accepted,
            'knownTupleFromOriginalConversionAndMappingReports': {
                'design': 'main', 'ncdVersion': '3.2', 'device': 'xc3s400', 'package': 'pq208', 'speed': '-4'},
            'originalLiteralDesignStatementAvailable': False}


class Output:
    def __init__(self, root):
        root.mkdir(parents=True, exist_ok=False)
        self.root, self.total, self.files = root, 0, []

    def write(self, name, raw, final=False):
        require(len(raw) <= MAX_FILE, f'Complete output file exceeds 3 MB; no truncation: {name}')
        require(len(self.files) < MAX_OUTPUT_FILES - (0 if final else 1), 'Output file-count bound exceeded; no truncation')
        require(self.total + len(raw) <= MAX_TOTAL_OUTPUT - (0 if final else MAX_FILE), 'Aggregate 96 MB output bound exceeded with final-result reserve; no truncation')
        path = self.root / name
        require(path.parent == self.root and not path.exists(), 'Output name is not a fresh simple file')
        path.write_bytes(raw)
        row = {'name': name, 'bytes': len(raw), 'sha256': sha(raw)}
        self.files.append(row)
        self.total += len(raw)
        return row

    def json(self, name, value, final=False):
        return self.write(name, (json.dumps(value, indent=2) + '\n').encode('utf-8'), final=final)

    def rows(self, stem, rows):
        files = []
        for start in range(0, len(rows), INDEX_ROWS_PER_PART):
            files.append(self.json(f'{stem}-{len(files):03d}.json', rows[start:start + INDEX_ROWS_PER_PART]))
        return files

    def lines(self, stem, text):
        """Retain every complete line in order, with no line or byte truncation."""
        files, buffer, first_line, next_line = [], bytearray(), 1, 1
        for line in text.splitlines(keepends=True):
            raw = line.encode('utf-8')
            require(len(raw) <= MAX_FILE, f'One complete residual/header line exceeds 3 MB: {stem}')
            if buffer and len(buffer) + len(raw) > MAX_FILE:
                row = self.write(f'{stem}-{len(files):03d}.txt', bytes(buffer))
                files.append(row | {'firstLine': first_line, 'afterLastLine': next_line})
                buffer, first_line = bytearray(), next_line
            buffer.extend(raw)
            next_line += 1
        if buffer or not files:
            row = self.write(f'{stem}-{len(files):03d}.txt', bytes(buffer))
            files.append(row | {'firstLine': first_line, 'afterLastLine': next_line})
        require(sum(row['bytes'] for row in files) == len(text.encode('utf-8')), 'Residual/header byte coverage differs')
        return files


def retain_records(output, evidence, stem='complete-record-differences'):
    """Save every requested complete record; manifest offsets recover exact bytes."""
    entries, buffer, rows, manifests = [], bytearray(), [], []

    def flush():
        nonlocal buffer, rows
        if not rows:
            return
        file_row = output.write(f'{stem}-{len(manifests):03d}.txt', bytes(buffer))
        for row in rows:
            row['file'] = file_row['name']
            entries.append(row)
        manifests.append(file_row)
        buffer, rows = bytearray(), []

    for (side, kind, name, occurrence), raw in sorted(evidence.items()):
        data = raw.encode('utf-8')
        require(len(data) + 1 <= MAX_FILE, f'One complete changed record exceeds3MB: {side}/{kind}/{name}')
        if rows and (len(rows) >= RECORDS_PER_PART or len(buffer) + len(data) + 1 > MAX_FILE):
            flush()
        rows.append({'side': side, 'kind': kind, 'name': name, 'occurrence': occurrence, 'byteOffset': len(buffer),
                     'bytes': len(data), 'sha256': sha(data)})
        buffer.extend(data)
        buffer.extend(b'\n')
    flush()
    require(len(entries) == len(evidence), 'Changed-record retention incomplete')
    return {'rawParts': manifests, 'recordIndexParts': output.rows(f'{stem}-index', entries),
            'completeRecords': len(entries)}


def controls(reader):
    reader.fixture_checks()
    text = '# header ; outside\n' + 'design "main" xc3s400pq208-4 v3.2, cfg " _DESIGN_PROP::PK_NGMTIMESTAMP:123 ";\n'
    text += 'inst "x" "SLICEL", cfg " F:foo:#LUT:D=A1 META::a;#b\\\"c ";\n'
    text += '# between records\nnet "n" gnd, inpin "x" F1;\n# trailing\n'
    records, gaps, issues = scan_complete(text)
    require(not issues, 'Valid complete scanner fixture flagged')
    require([r['kind'] for r in records] == ['design', 'inst', 'net'], 'Complete scanner positive failed')
    require('#LUT:D=A1 META::a;#b' in records[1]['raw'], 'Quoted hash/semicolon content changed')
    require(design_identity(records[0]['raw'])['matchesKnownTuple'], 'Known design tuple rejected')
    changed = text.replace('PK_NGMTIMESTAMP:123', 'PK_NGMTIMESTAMP:124')
    altered, _, _ = scan_complete(changed)
    require(difference_keys(keyed(records), keyed(altered)) == [('design', 'main', 0)], 'Design cfg timestamp change hidden')
    header_changed, new_gaps, _ = scan_complete(text.replace('# header ; outside', '# different header'))
    require(keyed(records) == keyed(header_changed) and gaps != new_gaps, 'Outside-text difference hidden')
    reordered = records[:1] + list(reversed(records[1:]))
    require(keyed(records) == keyed(reordered) and records != reordered, 'Record order distinction lost')
    negatives = (
        text + 'inst "x" "SLICEL", cfg " F:a:#LUT:D=A1 ";',
        text + 'inst "unfinished" "SLICEL", cfg " F:x:#LUT:D=A1 ',
        text + 'unrecognized "statement";',
        text + 'residual text without a complete statement',
    )
    for number, bad in enumerate(negatives, 1):
        bad_records, bad_gaps, bad_issues = scan_complete(bad)
        require(bad_issues, f'Malformed/duplicate/residual fixture {number} accepted')
        recovered = ''.join(bad_gaps[i]['text'] + row['raw'] for i, row in enumerate(bad_records)) + bad_gaps[-1]['text']
        require(recovered == bad, f'Failed grammar fixture {number} lost bytes')
    duplicate_records, _, _ = scan_complete(negatives[0])
    require(('inst', 'x', 1) in keyed(duplicate_records), 'Duplicate record was overwritten')
    try:
        scan_complete(text + '\0')
    except ValueError:
        pass
    else:
        raise ValueError('NUL fixture accepted')
    require(not design_identity(records[0]['raw'].replace('xc3s400', 'xc3s200'))['matchesKnownTuple'], 'Wrong device accepted')
    print('Hosted complete-statement, quoted-CFG, design-change, residual, duplicate, order and device controls passed; text-only synthetic controls.')


def investigate(family, paths, report_root, output_root, reader):
    config = FAMILIES[family]
    inputs = {side: regular_bytes(path) for side, path in zip(('A', 'B'), paths)}
    output = Output(output_root)
    result = {
        'family': family, 'diagnosticComplete': False, 'oldIdentityGateChanged': False,
        'nativeTrialAuthorizedByThisDiagnostic': False,
        'originalMapRun': config['run'], 'originalMapJob': config['job'],
        'failedRetainedInspectionRunPreserved': 41319824540,
        'expectedNcdSha256VerifiedSeparatelyByWorkflow': config['ncd'],
        'originalFullXdlSha256': config['oldXdl'],
        'inputs': {side: {'path': str(path), 'bytes': len(inputs[side]), 'sha256': sha(inputs[side]),
                          'matchesOriginalFullXdlSha256': sha(inputs[side]) == config['oldXdl']}
                   for side, path in zip(('A', 'B'), paths)},
        'fullByteEqualityAtoB': inputs['A'] == inputs['B'],
        'historicalLimit': 'Neither original full XDL nor the failed retained-run full exports was retained. A/B diagnose only fresh export repeatability; exact historical mismatch cause is unknown. Only original available raw records and recorded hashes can be compared.',
        'fullInputRetention': 'Both complete input exports must remain in the separate GitHub-only workflow artifact.',
        'errors': [],
    }
    output.json('input-identity.json', result)
    try:
        parsed, maps, outside, layouts, evidence, indexes = {}, {}, {}, {}, {}, {}
        # Complete fresh text evidence precedes old-report, grammar, count and
        # design validation. Unknown grammar is retained and fails at the end.
        for side in ('A', 'B'):
            text = inputs[side].decode('utf-8', errors='strict')
            records, gaps, issues = scan_complete(text)
            parsed[side], maps[side] = records, keyed(records)
            result[f'{side}GrammarIssues'] = {'count': len(issues), 'parts': output.rows(f'grammar-issues-{side}', issues)}
            if issues:
                result['errors'].append(f'{side}: {len(issues)} grammar issues; exact text retained')
            counts = {kind: sum(r['kind'] == kind for r in records) for kind in ('design', 'inst', 'net')}
            if counts != config['counts']:
                result['errors'].append(f'{side}: full record counts differ: {counts}')
            outside[side] = ''.join(g['text'] for g in gaps)
            layouts[side] = [(g['beforeRecord'], g['text']) for g in gaps]
            result[f'{side}OutsideTextParts'] = output.lines(f'all-outside-record-text-{side}', outside[side])
            gap_rows, byte_offset = [], 0
            for gap in gaps:
                raw = gap['text'].encode('utf-8')
                gap_rows.append({k: v for k, v in gap.items() if k != 'text'} | {
                    'concatenatedOutsideFilesByteOffset': byte_offset, 'bytes': len(raw), 'sha256': sha(raw)})
                byte_offset += len(raw)
            result[f'{side}OutsideLayoutParts'] = output.rows(f'outside-record-layout-{side}', gap_rows)
            rows, designs, residuals = [], [], []
            duplicate_names = {(r['kind'], r['name']) for r in records if r['occurrence']}
            for ordinal, record in enumerate(records):
                raw = record['raw'].encode('utf-8')
                row = {k: v for k, v in record.items() if k != 'raw'}
                row.update(bytes=len(raw), sha256=sha(raw))
                rows.append(row)
                if record['kind'] == 'residual':
                    residuals.append(row | {'rawParts': output.lines(f'unrecognized-top-level-{side}-{ordinal:05d}', record['raw'])})
                elif record['kind'] == 'design' or (record['kind'], record['name']) in duplicate_names:
                    evidence[(side, record['kind'], record['name'], record['occurrence'])] = record['raw']
                if record['kind'] == 'design':
                    identity = design_identity(record['raw'])
                    designs.append(identity)
            indexes[side] = output.rows(f'ordered-record-index-{side}', rows)
            result[f'{side}Counts'] = counts
            identities_match = all(identity['matchesKnownTuple'] for identity in designs)
            if not identities_match:
                result['errors'].append(f'{side}: design identity differs or declaration is unsupported')
            result[f'{side}DesignIdentity'] = {'count': len(designs), 'allMatchKnownTuple': identities_match,
                                               'parts': output.rows(f'design-identities-{side}', designs)}
            result[f'{side}ResidualIndexParts'] = output.rows(f'unrecognized-top-level-index-{side}', residuals)
        changes = difference_keys(maps['A'], maps['B'])
        for key in changes:
            for side in ('A', 'B'):
                if key in maps[side] and key[0] != 'residual':
                    evidence[(side, *key)] = maps[side][key]
        result['orderedRecordIndexParts'] = indexes
        result['keyedRawRecordEqualityAtoB'] = not changes
        result['orderedRecordEqualityAtoB'] = [((r['kind'], r['name'], r['occurrence']), r['raw']) for r in parsed['A']] == [((r['kind'], r['name'], r['occurrence']), r['raw']) for r in parsed['B']]
        result['recordOrderEqualityAtoB'] = [(r['kind'], r['name'], r['occurrence']) for r in parsed['A']] == [(r['kind'], r['name'], r['occurrence']) for r in parsed['B']]
        result['outsideRecordTextEqualityAtoB'] = outside['A'] == outside['B']
        result['outsideRecordLayoutEqualityAtoB'] = layouts['A'] == layouts['B']
        result['designStatementsEqualAtoB'] = [r['raw'] for r in parsed['A'] if r['kind'] == 'design'] == [r['raw'] for r in parsed['B'] if r['kind'] == 'design']
        result['changedRecordIndexParts'] = output.rows('changed-key-index', [{'kind': k, 'name': n, 'occurrence': occurrence} for k, n, occurrence in changes])
        result['changedRecordCountAtoB'] = len(changes)
        result['completeDifferenceRecords'] = retain_records(output, evidence)
        result['freshExportEvidenceRetained'] = True

        prior, reports, original_evidence = {}, [], {}
        for number, (suffix, (size, digest, role)) in enumerate(config['pins'].items()):
            expected = config['prefix'] + suffix
            matches = list(report_root.rglob(expected))
            require(len(matches) == 1, f'Missing or ambiguous explicitly current-map report: {expected}')
            raw = regular_bytes(matches[0], MAX_FILE)
            require(len(raw) == size and sha(raw) == digest, f'Original report bytes differ: {expected}')
            content = raw.decode('utf-8', errors='strict')
            require('\0' not in content, f'NUL in original report: {expected}')
            original_copy = output.write(f'original-current-map-report-{number:02d}.txt', raw)
            report = {'source': expected, 'role': role, 'copy': original_copy}
            if role == 'raw-success':
                old_instances, old_nets = reader.parse(content)
                for kind, mapping in (('inst', old_instances), ('net', old_nets)):
                    for name, statement in mapping.items():
                        key = (kind, name, 0)
                        old_records, _, old_issues = scan_complete(statement)
                        require(not old_issues and keyed(old_records) == {key: statement}, f'Original reader statement is not exactly one complete quote-aware record: {key}')
                        require(key not in prior or prior[key] == statement, f'Conflicting original raw overlap: {key}')
                        prior[key] = statement
                report['rawCounts'] = {'inst': len(old_instances), 'net': len(old_nets)}
            elif role == 'raw-failure':
                require(not re.search(r'(?m)^\s*(inst|net)\s+"', content), 'Failed original scope unexpectedly has raw records')
                report['rawCounts'] = {'inst': 0, 'net': 0}
            reports.append(report)
        prior_counts = {kind: sum(key[0] == kind for key in prior) for kind in ('inst', 'net')}
        require(prior_counts == config['oldRawCounts'], 'Complete original available raw union count differs')
        result['originalReports'] = reports
        result['originalAvailableRawUnion'] = prior_counts
        result['olderReferenceFilesExcluded'] = 'Only explicit same-map pins above are compared. In particular base reference-failed-bits-8.txt is historical and is not current-export evidence.'
        original_comparisons = []
        mismatches = {'A': 0, 'B': 0}
        for key, expected in sorted(prior.items()):
            row = {'kind': key[0], 'name': key[1], 'originalSha256': sha(expected.encode('utf-8'))}
            for side in ('A', 'B'):
                actual = maps[side].get(key)
                unique = (key[0], key[1], 1) not in maps[side]
                row[side] = {'present': actual is not None, 'unique': unique, 'exactRawMatch': actual == expected and unique,
                             'sha256': sha(actual.encode('utf-8')) if actual is not None else None}
                if actual != expected or not unique:
                    original_evidence[('ORIGINAL', *key)] = expected
                    if actual is not None:
                        original_evidence[(side, *key)] = actual
                    mismatches[side] += 1
            original_comparisons.append(row)
        result['originalRawComparisonParts'] = output.rows('original-raw-comparison', original_comparisons)
        result['originalRawMismatchCounts'] = mismatches
        for side, count in mismatches.items():
            if count:
                result['errors'].append(f'{side}: {count} original complete raw records differ, are absent, or have duplicate names')
        result['originalRawDifferenceRecords'] = retain_records(output, original_evidence, stem='original-raw-differences')
        result['allOriginalAvailableRawRecordsMatchBoth'] = not any(not row[side]['exactRawMatch'] for row in original_comparisons for side in ('A', 'B'))
        result['diagnosticComplete'] = True
        result['interpretation'] = 'Text-level findings only. Any comment/design difference is retained, not normalized. A/B record differences do not establish functional differences, and record equality does not establish timing or whole mapped equivalence. Existing old-hash gates remain unchanged.'
    except (ValueError, UnicodeError, KeyError) as error:
        result['errors'].append(str(error))
        result['diagnosticComplete'] = False
    finally:
        result['outputBounds'] = {'fileBytes': MAX_FILE, 'totalBytes': MAX_TOTAL_OUTPUT,
                                  'files': MAX_OUTPUT_FILES, 'completeRecordsPerPart': RECORDS_PER_PART,
                                  'inputBytesEach': MAX_INPUT, 'reservedFinalResultBytes': MAX_FILE}
        result['outputFilesBeforeResult'] = list(output.files)
        result['outputBytesBeforeResult'] = output.total
        output.json('investigation-result.json', result, final=True)
        print(json.dumps({k: result[k] for k in ('family', 'diagnosticComplete', 'fullByteEqualityAtoB',
                                               'oldIdentityGateChanged', 'nativeTrialAuthorizedByThisDiagnostic')}, sort_keys=True))
    if result['errors'] or not result['diagnosticComplete']:
        raise SystemExit('Diagnostic incomplete or original record/design validation failed; preserve evidence and all previous failures')
    print('Complete export-difference evidence retained for independent review. No previous failure waived and no collection or native acceptance granted.')


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('GitHub-hosted text investigation only; never execute locally')
    reader = load_reader()
    controls(reader)
    if sys.argv[1:] == ['--self-test']:
        return
    if len(sys.argv) != 6 or sys.argv[1] not in FAMILIES:
        raise SystemExit('usage: inspect-successor-xdl-exports.py FAMILY XDL_A XDL_B ORIGINAL_MAP_REPORT_ROOT OUTPUT_DIR')
    family = sys.argv[1]
    path_a, path_b, report_root, output = map(Path, sys.argv[2:])
    require(report_root.is_dir() and not report_root.is_symlink(), 'Original report root must be a regular directory')
    require(path_a.resolve() != path_b.resolve(), 'Two distinct retained export files required')
    investigate(family, (path_a, path_b), report_root, output, reader)


if __name__ == '__main__':
    main()
