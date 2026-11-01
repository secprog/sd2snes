#!/usr/bin/env python3
"""Hosted-only retrieval of exact failed MAP evidence; never rebuilds an FPGA."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import zipfile


REPO = 'repos/secprog/sd2snes/'
TEXT_SUFFIXES = {'.txt', '.log', '.json', '.sha256', '.diff', '.xst', '.prj',
                 '.pcf', '.xise', '.syr', '.mrp', '.psr', '.bld'}


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', REPO + path]))


def same_fields(actual, expected, label):
    for key, value in expected.items():
        if actual.get(key) != value:
            raise SystemExit(f'{label}: field {key} differs from reviewed evidence')


def verified_zip(artifact, native=False):
    if not 0 < artifact['size_in_bytes'] <= 10_000_000:
        raise SystemExit('Unexpected compressed artifact size')
    raw = subprocess.check_output(['gh', 'api', REPO + 'actions/artifacts/'
                                   + str(artifact['id']) + '/zip'])
    if len(raw) != artifact['size_in_bytes'] or 'sha256:' + hashlib.sha256(raw).hexdigest() != artifact['digest']:
        raise SystemExit('Artifact ZIP size or digest differs; do not parse or extract')
    archive = zipfile.ZipFile(io.BytesIO(raw))
    items = archive.infolist()
    if not 1 <= len(items) <= (1 if native else 1000):
        raise SystemExit('Unexpected complete artifact member count')
    if sum(item.file_size for item in items) > (16_000_000 if native else 50_000_000):
        raise SystemExit('Complete artifact exceeds uncompressed bound')
    seen, records = set(), []
    for item in items:
        path = PurePosixPath(item.filename)
        mode = (item.external_attr >> 16) & 0xffff
        if (item.is_dir() or path.is_absolute() or path.as_posix() != item.filename
                or '..' in path.parts or ':' in item.filename or '\\' in item.filename
                or item.flag_bits & 1 or item.filename.casefold() in seen
                or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
            raise SystemExit('Unsafe or nonregular artifact member')
        seen.add(item.filename.casefold())
        if item.file_size > (16_000_000 if native else 25_000_000):
            raise SystemExit('Individual artifact member exceeds bound')
        if native:
            if item.filename != 'main_map.ncd' or item.file_size == 0:
                raise SystemExit('Expected exactly one nonempty mapped NCD')
        elif path.suffix not in TEXT_SUFFIXES:
            raise SystemExit('Nontext report extension rejected')
        data = archive.read(item)  # CRC verified by zipfile before any extraction.
        if len(data) != item.file_size:
            raise SystemExit('Artifact member length differs')
        if not native:
            data.decode('utf-8', errors='strict')
            if b'\0' in data:
                raise SystemExit('NUL in text report')
        records.append((path, data))
    if archive.testzip() is not None:
        raise SystemExit('Artifact CRC failure')
    return raw, records


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Hosted GitHub runner only; no local repository-script execution')
    if len(sys.argv) != 3 or sys.argv[1] not in ('basex', 'dsp'):
        raise SystemExit('Usage: download-successor-retained-map.py FAMILY OUTPUT_ROOT')
    family, output = sys.argv[1], Path(sys.argv[2])
    if output.exists():
        raise SystemExit('Refuse to overwrite an evidence directory')
    fixture = Path('.github/fixtures/successor-retained-map-data.json')
    expected = json.loads(fixture.read_text(encoding='utf-8'))[family]
    run_id = expected['run']['id']
    run = api(f'actions/runs/{run_id}')
    same_fields(run, expected['run'], 'Exact original failed MAP run')
    if run['status'] != 'completed' or run['conclusion'] != 'failure' or run['run_attempt'] != 1:
        raise SystemExit('Original failed run outcome must remain a failure')
    jobs = api(f'actions/runs/{run_id}/jobs?per_page=100')
    if jobs['total_count'] != len(expected['jobs']) or len(jobs['jobs']) != jobs['total_count']:
        raise SystemExit('Incomplete or unexpected job inventory')
    by_job = {job['id']: job for job in jobs['jobs']}
    if set(by_job) != {job['id'] for job in expected['jobs']}:
        raise SystemExit('Exact failed MAP jobs differ')
    for job in expected['jobs']:
        same_fields(by_job[job['id']], job, 'Full original job and every step')
        failed = [step['number'] for step in job['steps'] if step['conclusion'] != 'success']
        if failed != expected['failureSteps']:
            raise SystemExit('Original failed steps differ')
    inventory = api(f'actions/runs/{run_id}/artifacts?per_page=100')
    by_artifact = {artifact['id']: artifact for artifact in inventory['artifacts']}
    if (inventory['total_count'] != len(expected['artifacts'])
            or len(inventory['artifacts']) != inventory['total_count']
            or len(by_artifact) != inventory['total_count']):
        raise SystemExit('Incomplete or unexpected artifact inventory')
    if set(by_artifact) != {artifact['id'] for artifact in expected['artifacts']}:
        raise SystemExit('Original artifact set differs')
    for artifact in expected['artifacts']:
        same_fields(by_artifact[artifact['id']], artifact, 'Original artifact identity')
        if artifact['expired'] or artifact['workflow_run']['id'] != run_id or artifact['workflow_run']['head_sha'] != run['head_sha']:
            raise SystemExit('Expired or mismatched retained artifact')
    reports = next(a for a in inventory['artifacts'] if a['name'] == expected['reportArtifact'])
    mapped = next(a for a in inventory['artifacts'] if a['name'] == expected['ncdArtifact'])
    report_zip, report_files = verified_zip(reports)
    ncd_zip, ncd_files = verified_zip(mapped, native=True)
    if hashlib.sha256(ncd_files[0][1]).hexdigest() != expected['ncdSha256']:
        raise SystemExit('Mapped NCD differs from exact reviewed MAP report hash')
    report_hashes = {}
    for path, data in report_files:
        report_hashes[path.as_posix()] = hashlib.sha256(data).hexdigest()
    xdl_records = [(path, data) for path, data in report_files if path.name.endswith('-xdl-sha256.txt')]
    ncd_records = [(path, data) for path, data in report_files if path.name.endswith('-map-sha256.txt')]
    if len(xdl_records) != 1 or len(ncd_records) != 1:
        raise SystemExit('Missing or ambiguous original XDL/NCD hash records')
    if xdl_records[0][1].decode().split()[0] != expected['xdlSha256'] or ncd_records[0][1].decode().split()[0] != expected['ncdSha256']:
        raise SystemExit('Original report hashes do not bind the retained design')
    output.mkdir(parents=True)
    for folder, records in [('reports', report_files), ('input', ncd_files)]:
        for path, data in records:
            destination = output / folder / path
            if output.resolve() not in destination.resolve().parents:
                raise SystemExit('Resolved artifact destination escapes evidence root')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    (output / 'reports.zip').write_bytes(report_zip)
    (output / 'mapped-ncd.zip').write_bytes(ncd_zip)
    record = {'family': family, 'run': run, 'jobs': jobs, 'artifacts': inventory,
              'originalFailuresPreserved': expected['failureSteps'],
              'reportFileHashes': report_hashes, 'ncdSha256': expected['ncdSha256'],
              'xdlSha256': expected['xdlSha256'], 'xdlName': expected['xdlName'],
              'fpgaRegeneration': False, 'nativeTimingPass': False}
    (output / 'download-provenance.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(f'{family}: exact failed run, all steps/artifacts and complete digest-before-safe-extraction reports verified; retained NCD bound. No regeneration or timing result.')


if __name__ == '__main__':
    main()
