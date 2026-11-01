#!/usr/bin/env python3
"""Hosted-only retrieval of exact retained diagnostic exports; no conversion.

Historical failing workflows and their hash gates remain unchanged. This new
input contract pins the complete reviewed A/B artifacts and every report byte.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import zipfile


HELPER_BLOB = 'b26865903a6a533a7e1e971f50e93e1cb943d10e'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def helper_module():
    path = Path(__file__).with_name('download-successor-retained-map.py')
    raw = path.read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    require(blob == HELPER_BLOB, 'Original evidence helper source changed')
    spec = importlib.util.spec_from_file_location('pinned_original_downloader', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bind_run(helper, expected):
    run_id = expected['run']['id']
    run = helper.api(f'actions/runs/{run_id}')
    helper.same_fields(run, expected['run'], 'Exact reviewed run')
    jobs = helper.api(f'actions/runs/{run_id}/jobs?per_page=100')
    actual_jobs = {j['id']: j for j in jobs['jobs']}
    require(jobs['total_count'] == len(jobs['jobs']) == len(actual_jobs) == len(expected['jobs']), 'Incomplete job inventory')
    require(set(actual_jobs) == {j['id'] for j in expected['jobs']}, 'Exact job set differs')
    for job in expected['jobs']:
        helper.same_fields(actual_jobs[job['id']], job, 'Full reviewed job and every step')
    artifacts = helper.api(f'actions/runs/{run_id}/artifacts?per_page=100')
    actual = {a['id']: a for a in artifacts['artifacts']}
    require(artifacts['total_count'] == len(artifacts['artifacts']) == len(actual) == len(expected['artifacts']), 'Incomplete artifact inventory')
    require(set(actual) == {a['id'] for a in expected['artifacts']}, 'Exact artifact set differs')
    for artifact in expected['artifacts']:
        helper.same_fields(actual[artifact['id']], artifact, 'Exact reviewed artifact')
        require(not actual[artifact['id']]['expired'] and artifact['workflow_run']['id'] == run_id
                and artifact['workflow_run']['head_sha'] == run['head_sha'], 'Expired or mismatched artifact')
    return {'run': run, 'jobs': jobs, 'artifacts': artifacts}


def export_zip(helper, artifact, expected):
    require(0 < artifact['size_in_bytes'] <= 10_000_000, 'Export ZIP compressed bound exceeded')
    raw = subprocess.check_output(['gh', 'api', helper.REPO + 'actions/artifacts/' + str(artifact['id']) + '/zip'])
    require(len(raw) == artifact['size_in_bytes'] and 'sha256:' + sha(raw) == artifact['digest'], 'Export ZIP digest/size differs; do not parse')
    archive = zipfile.ZipFile(io.BytesIO(raw))
    entries = archive.infolist()
    require(len(entries) == 2 and {i.filename for i in entries} == set(expected) == {'export-a.xdl', 'export-b.xdl'}, 'Exact two retained exports required')
    require(sum(i.file_size for i in entries) <= 64_000_000, 'Full export aggregate bound exceeded')
    records = []
    for entry in entries:
        mode = (entry.external_attr >> 16) & 0xffff
        require(not entry.is_dir() and not entry.flag_bits & 1 and stat.S_IFMT(mode) in (0, stat.S_IFREG), 'Nonregular/encrypted export')
        require(0 < entry.file_size <= 32_000_000, 'Export member bound exceeded')
        data = archive.read(entry)
        require(len(data) == entry.file_size == expected[entry.filename]['bytes'] and sha(data) == expected[entry.filename]['sha256'], 'Exact reviewed full export bytes differ')
        data.decode('utf-8', errors='strict')
        require(b'\0' not in data, 'NUL in export')
        records.append((PurePosixPath(entry.filename), data))
    require(archive.testzip() is None, 'Export CRC failure')
    return raw, records


def save(root, records):
    require(not root.exists(), 'Refuse to overwrite evidence')
    root.mkdir(parents=True)
    for relative, data in records:
        path = root / relative
        require(root.resolve() in path.resolve().parents, 'Output escapes evidence directory')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def main():
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'GitHub-hosted only; never execute locally')
    require(len(sys.argv) == 4 and sys.argv[1] in ('basex', 'dsp'), 'usage: download-diagnosed-successor-xdl.py FAMILY ORIGINAL_EVIDENCE NEW_OUTPUT')
    family, original, output = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    require(not output.exists() and original.is_dir() and not original.is_symlink(), 'Invalid evidence directories')
    helper = helper_module()
    fixture = json.loads(Path('.github/fixtures/successor-xdl-diagnosis-data.json').read_text())
    old_failed = json.loads(Path('.github/fixtures/successor-xdl-export-failure-data.json').read_text())
    expected = fixture['families'][family]
    diagnostic = bind_run(helper, fixture)
    require(diagnostic['run']['status'] == 'completed' and diagnostic['run']['conclusion'] == 'success', 'Diagnosis must be a complete success')
    historical_failure = bind_run(helper, old_failed)
    require(historical_failure['run']['conclusion'] == 'failure', 'Historical whole-XDL failure must remain failure')
    artifacts = {a['name']: a for a in diagnostic['artifacts']['artifacts']}
    report_zip, reports = helper.verified_zip(artifacts[expected['reportsName']])
    report_pins = {x['name']: x for x in expected['members']}
    require(len(report_pins) == len(expected['members']) == len(reports), 'Complete diagnostic report count differs')
    require({p.as_posix() for p, _ in reports} == set(report_pins), 'Complete report paths differ')
    for path, data in reports:
        pin = report_pins[path.as_posix()]
        require(len(data) <= 3_000_000 and len(data) == pin['bytes'] and sha(data) == pin['sha256'], 'Exact reviewed report bytes differ')
    require(sum(len(data) for _, data in reports) <= 112_000_000, 'Report aggregate exceeds declared bound')
    result = json.loads(dict((p.as_posix(), b) for p, b in reports)[expected['resultPath']])
    for key in ('diagnosticComplete', 'keyedRawRecordEqualityAtoB', 'orderedRecordEqualityAtoB', 'recordOrderEqualityAtoB', 'designStatementsEqualAtoB', 'allOriginalAvailableRawRecordsMatchBoth'):
        require(result[key] is True, 'Reviewed diagnostic evidence differs: ' + key)
    require(result['errors'] == [] and result['changedRecordCountAtoB'] == 0 and result['originalRawMismatchCounts'] == {'A': 0, 'B': 0}, 'Diagnostic mismatch/errors')
    require(result['oldIdentityGateChanged'] is False and result['nativeTrialAuthorizedByThisDiagnostic'] is False, 'Historical gate or native acceptance claim changed')
    require(result['originalAvailableRawUnion'] == expected['oldRawCounts'] and result['ACounts'] == result['BCounts'] == expected['fullCounts'], 'Diagnostic coverage differs')
    require(result['expectedNcdSha256VerifiedSeparatelyByWorkflow'] == expected['ncdSha256'] and result['originalFullXdlSha256'] == expected['historicalXdlSha256'], 'Historical identities differ')
    ncd = original / 'input/main_map.ncd'
    require(ncd.is_file() and not ncd.is_symlink() and ncd.stat().st_size <= 16_000_000 and sha(ncd.read_bytes()) == expected['ncdSha256'], 'Original NCD no longer matches')
    old_provenance = json.loads((original / 'download-provenance.json').read_text())
    require(old_provenance['family'] == family and old_provenance['ncdSha256'] == expected['ncdSha256'] and old_provenance['xdlSha256'] == expected['historicalXdlSha256'], 'Original MAP provenance differs')
    raw_exports, exports = export_zip(helper, artifacts[expected['exportsName']], expected['exports'])
    output.mkdir(parents=True)
    save(output / 'reports', reports)
    save(output / 'exports', exports)
    (output / 'reports.zip').write_bytes(report_zip)
    (output / 'exports.zip').write_bytes(raw_exports)
    for artifact in historical_failure['artifacts']['artifacts']:
        raw, records = helper.verified_zip(artifact)
        save(output / 'historical-failure' / artifact['name'], records)
        (output / 'historical-failure' / (artifact['name'] + '.zip')).write_bytes(raw)
    provenance = {'family': family, 'diagnostic': diagnostic, 'historicalFailure': historical_failure,
                  'ncdSha256': expected['ncdSha256'], 'historicalXdlSha256': expected['historicalXdlSha256'],
                  'retainedExports': expected['exports'], 'selectedInput': 'export-a.xdl',
                  'allReportPins': expected['members'], 'oldHashFailureUnwaived': True,
                  'historicalMismatchCause': 'undetermined', 'noConversionOrRegeneration': True,
                  'wholeMappedEquivalenceClaim': False, 'nativeTimingAccepted': False}
    (output / 'download-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    print('Exact retained diagnostic exports and every report byte verified; original MAP/NCD and historical failed jobs remain bound. No conversion, regeneration, normalization or timing acceptance.')


if __name__ == '__main__':
    main()
