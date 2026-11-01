#!/usr/bin/env python3
"""Hosted-only exact retained-input preparation. Never executes FPGA tools."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import zipfile


REPO = 'repos/secprog/sd2snes/'
FIXTURE = '.github/fixtures/successor-native-input-data.json'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def command(*args):
    return subprocess.check_output(list(args), timeout=120)


def git(*args):
    return command('git', *args)


def api(path):
    data = command('gh', 'api', REPO + path)
    require(len(data) <= 8_000_000, 'API metadata bound exceeded')
    return json.loads(data)


def safe_name(name):
    path = PurePosixPath(name)
    require(bool(name) and not path.is_absolute() and path.as_posix() == name
            and '..' not in path.parts and ':' not in name and '\\' not in name,
            'Unsafe relative path: ' + name)
    return path


def put(root, name, data):
    path = root / safe_name(name)
    require(root.resolve() in path.resolve().parents and not path.exists()
            and not path.is_symlink(), 'Refuse unsafe or existing output: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def write_json(root, name, value):
    data = (json.dumps(value, indent=2) + '\n').encode()
    require(len(data) <= 3_000_000, 'Ancillary JSON report bound exceeded')
    put(root, name, data)


def exact_fields(actual, expected, label):
    for key, value in expected.items():
        require(actual.get(key) == value, label + ': field differs: ' + key)


def bind_runs(contracts):
    observed, artifacts = {}, {}
    for expected in contracts:
        rid = expected['run']['id']
        require(rid not in observed, 'Duplicate run contract')
        run = api(f'actions/runs/{rid}')
        exact_fields(run, expected['run'], 'Historical/current run')
        record = {'run': {k: run[k] for k in expected['run']}}
        for key in ('jobs', 'artifacts'):
            result = api(f'actions/runs/{rid}/{key}?per_page=100')
            rows = {x['id']: x for x in result[key]}
            require(result['total_count'] == len(result[key]) == len(rows)
                    == len(expected[key]), 'Incomplete ' + key + ' inventory')
            require(set(rows) == {x['id'] for x in expected[key]}, 'Changed ' + key + ' set')
            record[key] = []
            for item in expected[key]:
                actual = rows[item['id']]
                exact_fields(actual, item, 'Complete ' + key + ' record')
                record[key].append({k: actual[k] for k in item})
                if key == 'artifacts':
                    require(not actual['expired'] and actual['workflow_run']['id'] == rid
                            and actual['workflow_run']['head_sha'] == run['head_sha'],
                            'Expired or mismatched artifact')
                    require(actual['id'] not in artifacts, 'Duplicate artifact contract')
                    artifacts[actual['id']] = actual
        observed[rid] = record
    return observed, artifacts


def require_regular_archive(artifact, names, native, limits):
    # Preserve the old retained-map downloader unchanged, but reject its
    # historical mode-0 allowance before it can extract these exact bytes.
    require(0 < artifact['size_in_bytes'] <= limits['zipBytes'], 'ZIP compressed bound')
    raw = command('gh', 'api', REPO + f"actions/artifacts/{artifact['id']}/zip")
    require(len(raw) == artifact['size_in_bytes'] and 'sha256:' + sha(raw) == artifact['digest'],
            'ZIP size/digest differs; do not inspect metadata')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        require(0 < len(entries) == len(names) <= limits['members']
                and {entry.filename for entry in entries} == set(names),
                'Exact retained ZIP member paths/count differ')
        require(sum(entry.file_size for entry in entries) <= (16_000_000 if native else 50_000_000)
                and all(entry.file_size <= (16_000_000 if native else 25_000_000)
                        for entry in entries), 'Original retained ZIP byte bounds')
        require(all(stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFREG
                    and not entry.is_dir() for entry in entries),
                'Retained original ZIP must declare regular files explicitly')


def verified_zip(artifact, pins, kind, family, limits):
    require(0 < artifact['size_in_bytes'] <= limits['zipBytes'], 'ZIP compressed bound')
    raw = command('gh', 'api', REPO + f"actions/artifacts/{artifact['id']}/zip")
    require(len(raw) == artifact['size_in_bytes'] and 'sha256:' + sha(raw) == artifact['digest'],
            'ZIP size/digest differs; do not parse')
    archive = zipfile.ZipFile(io.BytesIO(raw))
    entries = archive.infolist()
    expected = {x['name']: x for x in pins}
    require(len(expected) == len(pins) == len(entries) <= limits['members'], 'Complete ZIP count')
    require({x.filename for x in entries} == set(expected), 'Complete ZIP paths differ')
    bound = limits['ipAggregateBytes'] if kind == 'ip' else limits['textAggregateBytes']
    require(sum(x.file_size for x in entries) <= bound, 'ZIP aggregate bound')
    seen, files = set(), {}
    for entry in entries:
        safe_name(entry.filename)
        mode = stat.S_IFMT(entry.external_attr >> 16)
        require(not entry.is_dir() and not entry.flag_bits & 1 and mode == stat.S_IFREG
                and entry.filename.casefold() not in seen, 'Nonregular/encrypted/duplicate ZIP entry')
        seen.add(entry.filename.casefold())
        cap = (limits['ipFileBytes'] if kind == 'ip' else
               limits['proofFileBytes'] if kind == 'proof' else limits['textFileBytes'])
        if kind == 'collection' and entry.filename == f'successor-diagnosed-{family}-inspection-console.txt':
            cap = limits['consoleBytes']
        require(entry.file_size <= cap, 'ZIP member bound')
        data = archive.read(entry)
        pin = expected[entry.filename]
        require(len(data) == entry.file_size and sha(data) == pin['sha256'], 'Exact member SHA differs')
        if 'bytes' in pin:
            require(len(data) == pin['bytes'], 'Exact member size differs')
        if kind != 'ip':
            data.decode('utf-8', errors='strict')
            require(b'\0' not in data, 'NUL in text evidence')
        files[entry.filename] = data
    require(archive.testzip() is None, 'ZIP CRC failure')
    return raw, files


def verify_files(root, pins):
    actual = [p for p in root.rglob('*') if p.is_file()]
    require({p.relative_to(root).as_posix() for p in actual} == {x['name'] for x in pins},
            'Complete extracted path set differs')
    for pin in pins:
        path = root / safe_name(pin['name'])
        require(path.is_file() and not path.is_symlink(), 'Nonregular extracted file')
        data = path.read_bytes()
        require(len(data) == pin['bytes'] and sha(data) == pin['sha256'], 'Extracted byte pin differs')


def save_bundle(root, raw, files):
    require(not root.exists(), 'Evidence bundle already exists')
    for name, data in files.items():
        put(root, name, data)
    put(root.parent, root.name + '.zip', raw)


def parse_manifest(data):
    result = {}
    for line in data.decode().splitlines():
        digest, name = line.split('  ', 1)
        safe_name(name)
        require(re.fullmatch('[0-9a-f]{64}', digest) and name not in result, 'Bad/duplicate SHA row')
        result[name] = digest
    return result


def canonical(commit):
    rows = []
    for item in git('ls-tree', '-r', '-z', commit).split(b'\0'):
        if item:
            left, name = item.split(b'\t')
            mode, kind, oid = left.decode().split()
            require(kind == 'blob', 'Unexpected nonblob tracked entry')
            rows.append((mode, oid, name.decode()))
    proc = subprocess.Popen(['git', 'cat-file', '--batch'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    hashes = {}
    try:
        for mode, oid, name in rows:
            proc.stdin.write((oid + '\n').encode())
            proc.stdin.flush()
            header = proc.stdout.readline().decode().split()
            require(header[:2] == [oid, 'blob'], 'Canonical blob header differs')
            data = proc.stdout.read(int(header[2]))
            require(proc.stdout.read(1) == b'\n' and blob(data) == oid, 'Canonical blob bytes differ')
            hashes[name] = sha(data)
    finally:
        proc.stdin.close()
    require(proc.wait(timeout=60) == 0, 'Git canonical reader failed')
    index = ''.join(f'{mode} {oid} 0\t{name}\n' for mode, oid, name in rows).encode()
    return hashes, index


def inventory():
    names = [x.decode() for x in git('ls-files', '-z').split(b'\0') if x]
    hashes = {}
    for name in names:
        safe_name(name)
        path = Path(name)
        require(path.is_file() and not path.is_symlink(), 'Nonregular tracked input')
        hashes[name] = sha(path.read_bytes())
    return hashes, git('ls-files', '-s')


def manifest(hashes):
    return ''.join(f'{value}  {name}\n' for name, value in sorted(hashes.items())).encode()


def verify_old_source(root, family, expected, original_hashes, original_index):
    prefix = ('basex-normal-unshared-isolated-map' if family == 'basex'
              else 'dsp-parallel-stack-isolated-map')
    base = root / '_temp'
    before = (base / (prefix + '-before.sha256')).read_bytes()
    require(before == (base / (prefix + '-after.sha256')).read_bytes(), 'Original MAP source changed')
    candidate_hashes = dict(original_hashes)
    candidate_hashes[expected['candidate']['path']] = expected['candidate']['sha256']
    require(parse_manifest(before) == candidate_hashes, 'Original MAP complete canonical source mismatch')
    for suffix in ('before-index.txt', 'after-index.txt', 'final-index.txt'):
        require((base / (prefix + '-' + suffix)).read_bytes() == original_index, 'Original MAP index mismatch')
    final = ''.join(name + ': OK\n' for name in parse_manifest(before)).encode()
    require((base / (prefix + '-final-manifest-check.txt')).read_bytes() == final,
            'Original MAP final full check differs')
    require(not (base / (prefix + '-post-staged.diff')).read_bytes(), 'Original staged diff nonempty')
    require((base / (prefix + '-post-paths.txt')).read_text().splitlines()
            == [expected['candidate']['path']], 'Original source override path differs')


def proof_manifest(root):
    rows = parse_manifest((root / 'SHA256SUMS').read_bytes())
    for name, digest in rows.items():
        require(sha((root / name).read_bytes()) == digest, 'Full proof manifest hash differs')
    require((root / 'verified.txt').stat().st_size > 0, 'Missing proof completion marker')


def main():
    require(os.environ.get('GITHUB_ACTIONS') == 'true' and sys.flags.optimize == 0,
            'Hosted execution with assertions enabled only')
    require(len(sys.argv) == 3 and sys.argv[1] in ('basex', 'dsp'),
            'usage: prepare-successor-native-inputs.py FAMILY ABSENT_EVIDENCE_ROOT')
    for key in ('PYTHONOPTIMIZE', 'MAKEFILES', 'MAKEFLAGS', 'GNUMAKEFLAGS',
                'MFLAGS', 'MAKEOVERRIDES', 'MAKELEVEL', 'MAKE_RESTARTS'):
        require(not os.environ.get(key), 'Unexpected environment override: ' + key)
    family, root = sys.argv[1], Path(sys.argv[2]).resolve()
    repo = Path.cwd().resolve()
    require(not root.exists() and root != repo and repo not in root.parents,
            'Evidence root must be absent and outside checkout')
    data = json.loads(Path(FIXTURE).read_bytes())
    require(data['schema'] == 1 and set(data['families']) == {'basex', 'dsp'}, 'Unexpected input contract')
    selected = data['families'][family]
    for path, pin in data['sourcePins'].items():
        raw = Path(path).read_bytes()
        require(len(raw) == pin['bytes'] and sha(raw) == pin['sha256'] and blob(raw) == pin['blob'],
                'Canonical helper/source pin differs: ' + path)
    approval_pin = data['physicalAcceptance']
    require(approval_pin['pending'] is False, 'Physical acceptance is still pending')
    approval_raw = Path(approval_pin['path']).read_bytes()
    require(len(approval_raw) == approval_pin['bytes'] and sha(approval_raw) == approval_pin['sha256']
            and blob(approval_raw) == approval_pin['blob'], 'Exact physical acceptance document differs')
    approval = json.loads(approval_raw)
    eligibility = approval['families'][family]
    require(eligibility['physicalReviewComplete'] is True
            and eligibility['nativeInputPreparationEligible'] is True,
            'Selected family has not passed independent physical review')
    require(approval['schemaVersion'] == 1
            and approval['productionVerilogTree'] == data['productionVerilogTree']
            and approval['collection'] == {'run':41323541435,
                'head':'7715718873706c6a55ab77a5aaa76becb8c2894f',
                'outcome':'success', 'sourceEntries':2439}, 'Physical collection identity differs')
    require(eligibility['mappedNcdSha256'] == selected['ncd']['sha256']
            and eligibility['candidateSha256'] == selected['candidate']['sha256']
            and eligibility['proofRun'] == next(x['run'] for x in selected['proofs']
                                              if x['role'] == 'successor')
            and eligibility['collectionJob'] == (124898621295 if family == 'basex' else 124898621413),
            'Accepted physical evidence is not bound to these inputs')
    require(approval['limitations']['nativeTimingAccepted'] is False
            and approval['limitations']['productionPromotionAuthorizedByThisReceipt'] is False,
            'Preparation acceptance scope changed')
    for path in ['verilog/settings.local.mk'] + [f'verilog/sd2snes_{core}/{name}'
            for core in ('basex', 'dspx') for name in ('GNUmakefile', 'makefile', 'ucf.extra')]:
        require(not Path(path).exists() and not Path(path).is_symlink(), 'Unexpected optional input: ' + path)
    git('diff', '--exit-code')
    git('diff', '--cached', '--exit-code')
    checkout = git('rev-parse', 'HEAD').decode().strip()
    require(git('rev-parse', 'HEAD:verilog').decode().strip() == data['productionVerilogTree'],
            'Production source tree changed')
    for pin in data['historicalWorkflowPins']:
        require(git('rev-parse', data['historicalWorkflowCommit'] + ':' + pin['path']).decode().strip()
                == pin['blob'], 'Historical removed workflow identity differs')
    before, before_index = inventory()
    pristine, pristine_index = canonical(checkout)
    require(before == pristine and before_index == pristine_index, 'Checkout is not canonical')
    original_hashes, original_index = canonical(data['mapSourceHead'])
    require(len(original_hashes) == 2426, 'Original MAP canonical source count differs')
    root.mkdir(parents=True)
    put(root, 'checkout-before.sha256', manifest(before))
    put(root, 'checkout-before-index.txt', before_index)
    observed, artifacts = bind_runs(data['runs'])
    require(len(observed) == 25 and observed[40960956589]['run']['conclusion'] == 'success',
            'Complete prerequisite/isolation inventory differs')
    original_contract = json.loads(Path('.github/fixtures/successor-retained-map-data.json').read_bytes())[family]
    for key in ('reportArtifact', 'ncdArtifact'):
        matches = [a for a in observed[selected['mapRun']]['artifacts']
                   if a['name'] == original_contract[key]]
        require(len(matches) == 1, 'Exact original ZIP identity is ambiguous')
        native = key == 'ncdArtifact'
        names = ['main_map.ncd'] if native else [p['name'] for p in data['mapReports'][family]['members']]
        require_regular_archive(artifacts[matches[0]['id']], names, native, data['limits'])
    command(sys.executable, '.github/scripts/download-successor-retained-map.py', family, str(root / 'original'))
    map_roots, collections = {}, {}
    for which in ('basex', 'dsp'):
        contract = data['mapReports'][which]
        if which == family:
            folder = root / 'original/reports'
            verify_files(folder, contract['members'])
        else:
            raw, files = verified_zip(artifacts[contract['artifact']], contract['members'], 'text', which, data['limits'])
            folder = root / ('map-reports-' + which)
            save_bundle(folder, raw, files)
        map_roots[which] = folder
        verify_old_source(folder, which, data['families'][which], original_hashes, original_index)
        contract = data['collectionReports'][which]
        raw, files = verified_zip(artifacts[contract['artifact']], contract['members'], 'collection', which, data['limits'])
        collections[which] = root / ('collection-' + which)
        save_bundle(collections[which], raw, files)
    declarations = data['originalPrerequisiteDeclarations']
    require(len(declarations) == 26 and len({x['run'] for x in declarations}) == 19,
            'Original prerequisite declarations incomplete')
    for item in declarations:
        node = json.loads((map_roots[item['family']] / safe_name(item['report'])).read_bytes())
        for key in item['jsonPointer']:
            node = node[key]
        current = observed[item['run']]
        exact_fields(node['run'], current['run'], 'Original declared run')
        jobs = {x['id']: x for x in node['jobs']['jobs']}
        require(node['jobs']['total_count'] == len(jobs) == len(current['jobs']), 'Declared job count differs')
        for job in current['jobs']:
            exact_fields(jobs[job['id']], job, 'Original declared complete job')
    proof_roots = {}
    for proof in selected['proofs']:
        role = proof['role']
        folder = root / ('proof-' + role)
        if role in ('parent', 'successor'):
            # Validate the complete exact ZIP before the unchanged proof helper
            # performs its original semantic/source/manifest checks and extraction.
            raw, files = verified_zip(artifacts[proof['artifact']], proof['members'], 'proof', family, data['limits'])
            put(root, 'proof-' + role + '.zip', raw)
            script = ('download-measured-slow-path-proof.py' if role == 'parent'
                      else 'download-measured-successor-proof.py')
            command(sys.executable, '.github/scripts/' + script, family, str(folder),
                    str(root / ('proof-' + role + '-provenance.json')))
            verify_files(folder, proof['members'])
        else:
            raw, files = verified_zip(artifacts[proof['artifact']], proof['members'], 'proof', family, data['limits'])
            save_bundle(folder, raw, files)
        proof_manifest(folder)
        proof_roots[role] = folder
    prior_name = 'candidate-address.v' if family == 'basex' else 'candidate-upd77c25.v'
    prior = (proof_roots['prior'] / prior_name).read_bytes()
    parent = (proof_roots['parent'] / 'candidate.v').read_bytes()
    prior_original = 'original-address.v' if family == 'basex' else 'original-upd77c25.v'
    require((proof_roots['prior'] / prior_original).read_bytes()
            == Path(selected['candidate']['path']).read_bytes(), 'Prior proof production source differs')
    require(prior == (proof_roots['parent'] / 'original.v').read_bytes()
            == Path(f'.github/fixtures/slow-path-parent-{family}.v').read_bytes(), 'Full parent source chain differs')
    successor_parent = 'original.v' if family == 'basex' else 'parent-upd77c25.v'
    require(parent == (proof_roots['successor'] / successor_parent).read_bytes(), 'Successor parent differs')
    if family == 'dsp':
        require(parent == (proof_roots['successor'] / 'parent-proof/candidate.v').read_bytes(),
                'Nested DSP parent proof source differs')
    candidate = (proof_roots['successor'] / selected['candidate']['proofArchiveMember']).read_bytes()
    pin = selected['candidate']
    require(len(candidate) == pin['bytes'] and sha(candidate) == pin['sha256'] and blob(candidate) == pin['blob'],
            'Exact proved successor candidate differs')
    ip_pins = [{'name':x['expectedArchiveBasename'], 'sha256':x['sha256']} for x in selected['ipMembers']]
    raw, ip_files = verified_zip(artifacts[selected['ipArtifact']], ip_pins, 'ip', family, data['limits'])
    save_bundle(root / 'isolated-ip', raw, ip_files)
    ncd = (root / 'original/input/main_map.ncd').read_bytes()
    require(0 < len(ncd) <= 16_000_000 and sha(ncd) == selected['ncd']['sha256'], 'Retained NCD differs')
    pcf = (map_roots[family] / selected['pcf']['sourceReportRelativePath']).read_bytes()
    require(len(pcf) == selected['pcf']['bytes'] and sha(pcf) == selected['pcf']['sha256'], 'Whole PCF differs')
    timing = [line.strip() for line in pcf.decode().splitlines()
              if re.match(r'^\s*(SYSTEM_JITTER|TS_\S+\s*=)', line)]
    require(timing == selected['pcf']['allTimingStatements'], 'Original PCF timing statements differ')
    require(('SYSTEM_JITTER = 480 ps;' in timing) == (family == 'dsp'), 'Original jitter contract differs')
    restore = {pin['path']:candidate, selected['ncd']['restorePath']:ncd,
               selected['pcf']['restorePath']:pcf}
    for entry in selected['ipMembers']:
        restore[entry['path']] = ip_files[entry['expectedArchiveBasename']]
    require(len(restore) == (6 if family == 'basex' else 9), 'Restoration input set differs')
    require(inventory() == (before, before_index), 'Preparation changed tracked sources before restoration')
    for name in restore:
        target = repo / safe_name(name)
        require(repo in target.resolve().parents and not target.is_symlink(), 'Unsafe restore target')
        require(name == pin['path'] or not target.exists(), 'Restored artifact target already exists')
    for name in ('main.ncd', 'main.par', 'main.twr'):
        require(not Path(f"verilog/sd2snes_{selected['core']}/{name}").exists(), 'Native output already exists')
    # All identity, proof, physical acceptance and source checks precede this mutation.
    for name, contents in restore.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
        require(target.read_bytes() == contents, 'Restored bytes differ')
    after, after_index = inventory()
    expected = dict(before)
    expected[pin['path']] = pin['sha256']
    require(after == expected and after_index == before_index, 'Unexpected candidate/source/index mutation')
    require(git('diff', '--name-only').decode().splitlines() == [pin['path']], 'Unexpected tracked diff')
    git('diff', '--cached', '--exit-code')
    after_manifest = manifest(after)
    restored_manifest = manifest({name:sha(contents) for name, contents in restore.items()})
    put(root, 'checkout-after-candidate.sha256', after_manifest)
    put(root, 'checkout-after-candidate-index.txt', after_index)
    put(root, 'restored-inputs.sha256', restored_manifest)
    provenance = {'family':family, 'checkoutHead':checkout, 'productionVerilogTree':data['productionVerilogTree'],
                  'fixtureSha256':sha(Path(FIXTURE).read_bytes()), 'physicalAcceptance':approval,
                  'physicalAcceptanceSha256':sha(approval_raw), 'runs':list(observed.values()),
                  'originalPrerequisiteDeclarations':declarations, 'mapReports':data['mapReports'],
                  'collectionReports':data['collectionReports'], 'proofBundles':selected['proofs'],
                  'restoredInputs':[{'path':name,'bytes':len(contents),'sha256':sha(contents)}
                                    for name,contents in sorted(restore.items())],
                  'allOldFailuresPreserved':True, 'strictRegularArchiveModePrechecked':True,
                  'nativeExecution':False, 'timingAccepted':False}
    write_json(root, 'provenance.json', provenance)
    result = {'preparationComplete':True, 'family':family, 'checkoutHead':checkout,
              'productionVerilogTree':data['productionVerilogTree'], 'sourcePath':pin['path'],
              'candidateSha256':pin['sha256'], 'ncdSha256':sha(ncd), 'pcfSha256':sha(pcf),
              'restoredInputsManifestSha256':sha(restored_manifest),
              'checkoutAfterCandidateSha256':sha(after_manifest),
              'checkoutAfterCandidateIndexSha256':sha(after_index),
              'provenanceSha256':sha((root / 'provenance.json').read_bytes()),
              'nativeExecution':False, 'timingAccepted':False}
    write_json(root, 'preparation-result.json', result)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
