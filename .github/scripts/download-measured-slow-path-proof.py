#!/usr/bin/env python3
"""Hosted-only retrieval of complete, independently reviewed component evidence."""
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

RECORDS = {
    "dsp": dict(run=41235863589, job=124639398863,
                head="ad558a585a494b089f908d56ea7a47d328fc3f88", conclusion="failure",
                jobs={124639398863: "success", 124639399086: "failure"},
                artifact=13055880281, name="dsp-measured-slow-path-proof", length=1189138,
                digest="9ce23ad78c3bb910f3f42c665180b9a8d61c4379edb95855b7be7a35b75055a8",
                entries=229, text_bytes=12712476, manifest=52),
    "basex": dict(run=41236527893, job=124641370373,
                  head="87182f6b0d77b782093056b27bd12e6b33fb1f6f", conclusion="success",
                  jobs={124641370373: "success"},
                  artifact=13056320784, name="basex-patch-merged-proof", length=1286671,
                  digest="4e2c38d1910330deea191f0b4d768995b7f6624fc685eb8f8f490a75603667bd",
                  entries=143, text_bytes=8446428, manifest=44),
}


def get(route, binary=False):
    result = subprocess.check_output(["gh", "api", "repos/secprog/sd2snes/" + route], timeout=60)
    if len(result) > 8_000_000:
        raise SystemExit("Excessive API response")
    return result if binary else json.loads(result)


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("GitHub-hosted execution only")
    family, destination, provenance = sys.argv[1:]
    expected = RECORDS[family]
    run = get(f"actions/runs/{expected['run']}")
    jobs = get(f"actions/runs/{expected['run']}/jobs?per_page=100")
    assert run["head_sha"] == expected["head"] and run["status"] == "completed"
    assert run["conclusion"] == expected["conclusion"]
    assert run["event"] == "workflow_dispatch" and run["run_attempt"] == 1
    assert jobs["total_count"] == len(jobs["jobs"]) == len(expected["jobs"])
    assert {j["id"]: j["conclusion"] for j in jobs["jobs"]} == expected["jobs"]
    assert all(j["status"] == "completed" and j["head_sha"] == expected["head"] for j in jobs["jobs"])
    selected = [j for j in jobs["jobs"] if j["id"] == expected["job"]]
    assert len(selected) == 1 and selected[0]["conclusion"] == "success"
    assert all(s["status"] == "completed" and s["conclusion"] == "success" for s in selected[0]["steps"])
    metadata = get(f"actions/artifacts/{expected['artifact']}")
    assert metadata["id"] == expected["artifact"] and metadata["name"] == expected["name"]
    assert metadata["workflow_run"]["id"] == expected["run"]
    assert metadata["workflow_run"]["head_sha"] == expected["head"]
    assert not metadata["expired"] and metadata["size_in_bytes"] == expected["length"]
    assert metadata["digest"] == "sha256:" + expected["digest"]
    raw = get(f"actions/artifacts/{expected['artifact']}/zip", True)
    assert len(raw) == expected["length"] and hashlib.sha256(raw).hexdigest() == expected["digest"]
    files = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        assert len(entries) == expected["entries"]
        assert sum(item.file_size for item in entries) == expected["text_bytes"]
        for item in entries:
            name, path = item.filename, PurePosixPath(item.filename)
            assert not item.is_dir() and not path.is_absolute() and ".." not in path.parts
            assert "\\" not in name and ":" not in name and name not in files
            assert not (item.flag_bits & 1) and not stat.S_ISLNK(item.external_attr >> 16)
            assert item.file_size <= 16_000_000
            data = archive.read(item)
            data.decode("utf-8", errors="strict")
            files[name] = data
    verified = set()
    for line in files["SHA256SUMS"].decode().splitlines():
        digest, name = line.split("  ", 1)
        assert name not in verified and hashlib.sha256(files[name]).hexdigest() == digest
        verified.add(name)
    assert len(verified) == expected["manifest"]
    assert files["original.v"] == Path(f".github/fixtures/slow-path-parent-{family}.v").read_bytes()
    assert files["proof-data.json"] == Path(".github/fixtures/slow-path-proof-data.json").read_bytes()
    assert files["generator.py.txt"] == Path(".github/scripts/prepare-slow-path-proofs.py").read_bytes()
    data = json.loads(files["proof-data.json"])[family]
    assert hashlib.sha256(files["candidate.v"]).hexdigest() == data["candidateSha256"]
    assert b"strict binary and unrestricted Yosys-X component proof" in files["verified.txt"]
    for mode in ("binary", "xstate"):
        assert b"SAT proof finished - no model found: SUCCESS!" in files[f"gate/proof-{mode}.log"]
    root = Path(destination)
    assert not root.exists()
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    Path(provenance).write_text(json.dumps(dict(run=run, jobs=jobs, artifact=metadata,
        zipSha256=expected["digest"], entries=len(files), selectedJob=expected["job"]), indent=2) + "\n")
    print(f"{family}: complete proof ZIP/digest/inventory and exact successful job verified; run conclusion remains {run['conclusion']}")


if __name__ == "__main__":
    main()
