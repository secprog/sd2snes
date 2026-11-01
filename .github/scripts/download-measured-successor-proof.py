#!/usr/bin/env python3
"""Retrieve pinned, independently reviewed successor proofs on GitHub only."""
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath


def api(route, binary=False):
    data = subprocess.check_output(
        ['gh', 'api', 'repos/secprog/sd2snes/' + route], timeout=60)
    assert len(data) <= 8_000_000, 'Excessive API response'
    return data if binary else json.loads(data)


def main():
    assert os.environ.get('GITHUB_ACTIONS') == 'true', 'GitHub-hosted execution only'
    family, destination, provenance = sys.argv[1:]
    fixture = Path('.github/fixtures/measured-successor-proof-data.json')
    expected = json.loads(fixture.read_text())[family]
    run = api(f"actions/runs/{expected['run']['id']}")
    assert all(run[key] == value for key, value in expected['run'].items())
    jobs = api(f"actions/runs/{run['id']}/jobs?per_page=100")
    assert jobs['total_count'] == len(jobs['jobs']) == 1
    job = jobs['jobs'][0]
    assert all(job[key] == value for key, value in expected['job'].items())
    assert all(step['status'] == 'completed' for step in job['steps'])
    assert [{key: step[key] for key in ('number', 'name', 'conclusion')}
            for step in job['steps']] == expected['steps']
    artifact = api(f"actions/artifacts/{expected['artifact']['id']}")
    assert all(artifact[key] == value for key, value in expected['artifact'].items())
    assert artifact['workflow_run']['id'] == run['id']
    assert artifact['workflow_run']['head_sha'] == run['head_sha']
    raw = api(f"actions/artifacts/{artifact['id']}/zip", True)
    assert len(raw) == artifact['size_in_bytes']
    assert 'sha256:' + hashlib.sha256(raw).hexdigest() == artifact['digest']
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        assert len(entries) == expected['entries']
        assert sum(item.file_size for item in entries) == expected['textBytes']
        for item in entries:
            name, path = item.filename, PurePosixPath(item.filename)
            assert not item.is_dir() and not path.is_absolute() and '..' not in path.parts
            assert str(path) == name and '\\' not in name and ':' not in name
            assert name not in files and not item.flag_bits & 1
            assert stat.S_ISREG(item.external_attr >> 16)
            assert item.file_size <= 16_000_000
            data = archive.read(item)  # zipfile validates CRC before returning.
            data.decode('utf-8', errors='strict')
            assert b'\0' not in data
            files[name] = data
    verified = set()
    for line in files['SHA256SUMS'].decode().splitlines():
        digest, name = line.split('  ', 1)
        assert name not in verified and hashlib.sha256(files[name]).hexdigest() == digest
        verified.add(name)
    assert len(verified) == expected['manifestEntries']
    for name, pin in expected['pins'].items():
        assert len(files[name]) == pin['bytes']
        assert hashlib.sha256(files[name]).hexdigest() == pin['sha256']
    for name, source in expected['repositoryBindings'].items():
        assert files[name] == Path(source).read_bytes(), source
    assert files['tracked-before.sha256'] == files['tracked-after.sha256']
    assert files['index-before.txt'] == files['index-after.txt']
    manifests = files['tracked-before.sha256'].decode().splitlines()
    names = [line.split('  ', 1)[1] for line in manifests]
    assert len(names) == len(set(names)) == expected['trackedEntries']
    assert files['tracked-final-check.txt'].decode() == ''.join(name + ': OK\n' for name in names)
    assert b'Yosys 0.33 (git sha1 2584903a060)' in files['tool-version.txt']
    assert b'Icarus Verilog version 12.0' in files['iverilog-version.txt']
    for record in expected['proofOutcomes']:
        message = (b'SAT proof finished - no model found: SUCCESS!' if record['success']
                   else b'SAT proof finished - model found: FAIL!')
        assert message in files[record['log']]
        if not record['success']:
            witness = json.loads(files[record['witness']])
            assert witness['signal']
    prerequisites = []
    for name in expected['prerequisiteProvenance']:
        prior = json.loads(files[name])
        prior_run = api(f"actions/runs/{prior['run']['id']}")
        for key in ('id', 'head_sha', 'path', 'status', 'conclusion', 'event', 'run_attempt'):
            assert prior_run[key] == prior['run'][key]
        prior_jobs = api(f"actions/runs/{prior_run['id']}/jobs?per_page=100")
        assert prior_jobs['total_count'] == len(prior_jobs['jobs']) == prior['jobs']['total_count']
        assert {j['id'] for j in prior_jobs['jobs']} == {j['id'] for j in prior['jobs']['jobs']}
        for original_job in prior['jobs']['jobs']:
            actual_job = next(j for j in prior_jobs['jobs'] if j['id'] == original_job['id'])
            for key in ('id', 'run_id', 'head_sha', 'status', 'conclusion', 'run_attempt'):
                assert actual_job[key] == original_job[key]
            assert all(s['status'] == 'completed' for s in actual_job['steps'])
            assert [{k: s[k] for k in ('number', 'name', 'conclusion')} for s in actual_job['steps']] == [
                {k: s[k] for k in ('number', 'name', 'conclusion')} for s in original_job['steps']]
        prior_artifact = api(f"actions/artifacts/{prior['artifact']['id']}")
        assert not prior_artifact['expired']
        for key in ('id', 'name', 'size_in_bytes', 'digest', 'workflow_run'):
            assert prior_artifact[key] == prior['artifact'][key]
        prerequisites.append(dict(run=prior_run, jobs=prior_jobs, artifact=prior_artifact))
    root = Path(destination)
    assert not root.exists()
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    result = dict(run=run, jobs=jobs, artifact=artifact,
                  zipSha256=hashlib.sha256(raw).hexdigest(), entries=len(files),
                  textBytes=sum(map(len, files.values())), manifestEntries=len(verified),
                  independentReview=expected['independentReview'],
                  prerequisites=prerequisites,
                  priorFailuresRemainFailures=True, mappingOrTimingPass=False)
    Path(provenance).write_text(json.dumps(result, indent=2) + '\n')
    print(f"{family}: complete reviewed successor proof, all steps, full ZIP, source/graph/witness pins verified; no timing result")


if __name__ == '__main__':
    main()
