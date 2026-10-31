#!/usr/bin/env python3
"""Hosted-only check of deterministic report emission using authentic text fixtures.

No FPGA tools, synthesis, simulation, proof or native implementation is run.
Bounded physical excerpts are explicitly partial fixtures, not full XDL designs.
"""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

ARTIFACTS = [
    {
        "family": "basex",
        "label": "reviewed",
        "run": 41135768963,
        "head": "5a40b1915b25180f6615c0dd43d70595fabbf9f6",
        "run_outcome": "failure",
        "job": 124337706603,
        "job_outcome": "success",
        "jobs": 2,
        "id": 13015763462,
        "name": "late-decoder-predecessors-basex-reports",
        "bytes": 351636,
        "zip_sha": "fd7dabda879ce45e4ce440900a4aa040b1dab2f9c1c948e680317b3698e7cc5c",
        "suffix": "raw.txt",
        "raw_sha": "66a4525dee74e50f7e8fae87cf2e62641ed277460e430f19693d61365be7d92a"
    },
    {
        "family": "dsp-drivers",
        "label": "reviewed",
        "run": 41136938577,
        "head": "e4a810b648d9bf269d609ae085f8130d38359abd",
        "run_outcome": "success",
        "job": 124341594600,
        "job_outcome": "success",
        "jobs": 3,
        "id": 13017258331,
        "name": "late-decoder-predecessors-dsp-drivers-reports",
        "bytes": 351028,
        "zip_sha": "45250e6005d6d8b5dd2f1472b85d7ce833d3ba0a0cce3ebf1dd7a277885c385c",
        "suffix": "raw.txt",
        "raw_sha": "52a27735ed903cc3a7ac81320de7e5f334c53b8a76a554d214f07526437519d5"
    },
    {
        "family": "dsp-ff-low",
        "label": "reviewed",
        "run": 41136938577,
        "head": "e4a810b648d9bf269d609ae085f8130d38359abd",
        "run_outcome": "success",
        "job": 124341594999,
        "job_outcome": "success",
        "jobs": 3,
        "id": 13016558555,
        "name": "late-decoder-predecessors-dsp-ff-low-reports",
        "bytes": 364416,
        "zip_sha": "0a4d51f420de7c6aa5f41a47d0a0eae68c4e6764d8037fc70753a6df43af406c",
        "suffix": "raw.txt",
        "raw_sha": "824f01ee44d2799671af489d40535e106b81d5c0541ff8141d1a2501128ec64b"
    },
    {
        "family": "dsp-ff-high",
        "label": "reviewed",
        "run": 41136938577,
        "head": "e4a810b648d9bf269d609ae085f8130d38359abd",
        "run_outcome": "success",
        "job": 124341595190,
        "job_outcome": "success",
        "jobs": 3,
        "id": 13016998344,
        "name": "late-decoder-predecessors-dsp-ff-high-reports",
        "bytes": 359511,
        "zip_sha": "286c260ffbb5020ef8bb3312cd59c9385a48be3400b8b49c9a5bbe5131ae2190",
        "suffix": "raw.txt",
        "raw_sha": "df01d88a70ea30c9571f481bc3e350016cdffd0c00ee6226f77ee47ce0ab14eb"
    },
    {
        "family": "basex",
        "label": "failed-native-preflight",
        "run": 41230014063,
        "head": "a62e5686ba72300f0af4013a3dd64c9acc808f36",
        "run_outcome": "failure",
        "job": 124622086785,
        "job_outcome": "failure",
        "jobs": 1,
        "id": 13053801022,
        "name": "basex-srtc-late-bits-isolated-native-seed-46-reports",
        "bytes": 589189,
        "zip_sha": "2688ecaee1821fc87dda9121b1dac102c24f155502b11b4cda2efcadef1c2a5a",
        "suffix": "-expanded-basex.txt",
        "raw_sha": "821e3e68d961af6074216f371f244c1c97072be069a32672244c49679611653d"
    },
    {
        "family": "dsp-drivers",
        "label": "failed-native-preflight",
        "run": 41229993033,
        "head": "a62e5686ba72300f0af4013a3dd64c9acc808f36",
        "run_outcome": "failure",
        "job": 124622027000,
        "job_outcome": "failure",
        "jobs": 1,
        "id": 13053447542,
        "name": "dsp-late-low-isolated-native-seed-68-reports",
        "bytes": 581507,
        "zip_sha": "2bd934278b4db8cc792232c71c8e29e4f7195a906d9f673124dd6ea6a092ecc2",
        "suffix": "-expanded-dsp-drivers.txt",
        "raw_sha": "95aecd8825a5054006f7386746942ceb2a91c54ae26e1c2b6da485eea908c182"
    }
]
REFERENCES = {
    "basex": {
        "bytes": 253550,
        "sha": "174fbb7b93b55740756ab19448a570150c077e6187d5c6b126012f6790eb7cbe",
        "bindings": 40
    },
    "dsp-drivers": {
        "bytes": 251303,
        "sha": "07333d0cb76b6a4342ac9bcd4acbf0cc7ff90bb3857cf413d1bb66d709490a9b",
        "bindings": 34
    },
    "dsp-ff-low": {
        "bytes": 408974,
        "sha": "f5eed88fa1dbecb5b641bfe6a622c65b4187923f3383d57c04e6210ec8867d1e",
        "bindings": 88
    },
    "dsp-ff-high": {
        "bytes": 364313,
        "sha": "de638a4e6ba8edcbd49f2740dee99f887408b45f251e468648ecf7a5407a94ad",
        "bindings": 88
    }
}
REPORT = Path(os.environ["RUNNER_TEMP"]) / "stable-report-order"
REPORT.mkdir()
SOURCE = Path(".github/scripts/inspect-late-decoder-stable.py")
OLD = Path(".github/scripts/inspect-late-decoder-predecessors.py")
old = OLD.read_bytes()
new = SOURCE.read_bytes()
before = br'print("\n".join(bindings))'
after = br'print("\n".join(sorted(bindings)))'
assert old.count(before) == 1 and old.replace(before, after) == new
assert hashlib.sha256(new).hexdigest() == "b20e6cb7e8886cd9a4f3ea4dc13eb2fe5a6427e11f78aa6718cba4965dcd36e7"
API = "https://api.github.com/repos/secprog/sd2snes/"
cache = {}
reports = {}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def get(path):
    result = subprocess.run(["gh", "api", "repos/secprog/sd2snes/" + path],
                            capture_output=True, timeout=60, check=True)
    data = result.stdout
    assert len(data) <= 20_000_000
    return data

def metadata(path):
    if path not in cache:
        cache[path] = json.loads(get(path))
    return cache[path]


for a in ARTIFACTS:
    run = metadata(f"actions/runs/{a['run']}")
    jobs = metadata(f"actions/runs/{a['run']}/jobs?per_page=100")
    artifact = metadata(f"actions/artifacts/{a['id']}")
    assert (run["id"], run["head_sha"], run["status"], run["conclusion"], run["run_attempt"]) == (
        a["run"], a["head"], "completed", a["run_outcome"], 1)
    assert jobs["total_count"] == len(jobs["jobs"]) == a["jobs"]
    selected = [j for j in jobs["jobs"] if j["id"] == a["job"]]
    assert len(selected) == 1
    job = selected[0]
    assert (job["status"], job["conclusion"], job["head_sha"]) == ("completed", a["job_outcome"], a["head"])
    if a["job_outcome"] == "success":
        assert all(s["conclusion"] == "success" for s in job["steps"])
    else:
        assert [s["number"] for s in job["steps"] if s["conclusion"] == "failure"] == [16]
        assert next(s for s in job["steps"] if s["number"] == 17)["conclusion"] == "skipped"
    for key, value in {"id": a["id"], "name": a["name"], "expired": False,
                       "size_in_bytes": a["bytes"], "digest": "sha256:" + a["zip_sha"]}.items():
        assert artifact[key] == value, key
    assert artifact["workflow_run"]["id"] == a["run"]
    assert artifact["workflow_run"]["head_sha"] == a["head"]
    label = a["family"] + "-" + a["label"]
    (REPORT / (label + "-provenance.json")).write_text(json.dumps(
        {"run": run, "jobs": jobs, "artifact": artifact}, indent=2) + "\n")
    data = get(f"actions/artifacts/{a['id']}/zip")
    assert len(data) == a["bytes"] and sha(data) == a["zip_sha"]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        assert 0 < len(members) <= 100
        assert sum(m.file_size for m in members) <= 20_000_000
        names = set()
        picked = []
        for m in members:
            p = PurePosixPath(m.filename)
            assert not p.is_absolute() and ".." not in p.parts and "\\" not in m.filename
            assert m.filename not in names and not m.is_dir() and not (m.flag_bits & 1)
            assert 0 <= m.file_size <= 8_000_000
            assert p.suffix.lower() not in {".ncd", ".ngc", ".bit", ".xdl"}
            names.add(m.filename)
            content = archive.read(m)
            content.decode("utf-8", errors="strict")
            if m.filename.endswith(a["suffix"]):
                picked.append(content)
    assert len(picked) == 1 and sha(picked[0]) == a["raw_sha"]
    reports[(a["family"], a["label"])] = picked[0]
    (REPORT / (label + "-authentic.txt")).write_bytes(picked[0])
    print(f"Authenticated {label}: {len(picked[0])} bytes SHA256 {sha(picked[0])}")


def parts(data):
    assert data.endswith(b"\n") and b"\r" not in data
    marker = b"Complete bounded raw statements follow before binding outcomes.\n"
    assert data.count(marker) == 1
    begin = data.index(marker) + len(marker)
    observed = data.index(b"Observed net ", begin)
    assert data[begin:begin + 6] == b'inst "'
    lines = data[observed:].splitlines(keepends=True)
    count = 0
    for line in lines:
        if not line.startswith(b"Observed net "):
            break
        assert re.fullmatch(rb"Observed net [^\n]+: driver=\('[^'\n]+', '[A-Za-z0-9_]+'\)\n", line)
        count += 1
    assert count and not any(l.startswith(b"Observed net ") for l in lines[count:])
    return data[:observed], lines[:count], b"".join(lines[count:]), data[begin:observed]


def canonical(data):
    prefix, bindings, footer, _ = parts(data)
    return prefix + b"".join(sorted(bindings)) + footer


summary = {"native_execution": False, "old_failures_preserved": True, "families": []}
for family, ref in REFERENCES.items():
    original = reports[(family, "reviewed")]
    expected = canonical(original)
    assert len(expected) == ref["bytes"] and sha(expected) == ref["sha"]
    prefix, bindings, footer, physical = parts(original)
    assert len(bindings) == ref["bindings"]
    failed = reports.get((family, "failed-native-preflight"))
    if failed is not None:
        p2, b2, f2, _ = parts(failed)
        assert original != failed and prefix == p2 and footer == f2
        assert Counter(bindings) == Counter(b2)
        assert canonical(failed) == expected
    (REPORT / (family + "-canonical-reference.txt")).write_bytes(expected)
    # Fixture contains every retained physical record, but omits the rest of the design.
    fixture = REPORT / (family + "-partial-physical-fixture.txt")
    fixture.write_bytes(physical)
    header = re.search(rb"(?m)^Full XDL (\d+) instances/(\d+) nets; retained (\d+) complete instances/(\d+) complete nets/(\d+) bytes\.\n", expected)
    assert header
    full_header = header.group(0)
    partial_header = (b"Full XDL " + header[3] + b" instances/" + header[4] + b" nets; retained "
                      + header[3] + b" complete instances/" + header[4] + b" complete nets/" + header[5] + b" bytes.\n")
    expected_fixture = expected.replace(full_header, partial_header, 1)
    assert len(physical) == int(header[5]) + 1
    checks = []
    # These are Python hash-order controls, not FPGA placement/routing seeds.
    for hash_seed in ("0", "1"):
        result = subprocess.run([sys.executable, str(SOURCE), family, str(fixture)],
                                capture_output=True, timeout=30,
                                env={**os.environ, "PYTHONHASHSEED": hash_seed})
        (REPORT / f"{family}-hash-order-{hash_seed}-stdout.txt").write_bytes(result.stdout)
        (REPORT / f"{family}-hash-order-{hash_seed}-stderr.txt").write_bytes(result.stderr)
        assert result.returncode == 0 and not result.stderr and result.stdout == expected_fixture
        checks.append({"python_hash_seed": hash_seed, "bytes": len(result.stdout), "sha256": sha(result.stdout)})
    # Explicitly synthetic corruption controls exercise the actual inspector plus
    # exact full-output comparison; they are not native or physical-design evidence.
    mutations = {
        "lut": physical.replace(b"#LUT:D=", b"#LUT:D=~", 1),
        "init": physical.replace(b"_INIT_ATTR::INIT0", b"_INIT_ATTR::INIT1", 1),
        "truncated": physical.rstrip()[:-1] + b"\n",
    }
    negatives = []
    for label, altered in mutations.items():
        assert altered != physical
        bad = REPORT / (family + "-synthetic-" + label + ".txt")
        bad.write_bytes(altered)
        result = subprocess.run([sys.executable, str(SOURCE), family, str(bad)],
                                capture_output=True, timeout=30,
                                env={**os.environ, "PYTHONHASHSEED": "0"})
        (REPORT / f"{family}-synthetic-{label}-stdout.txt").write_bytes(result.stdout)
        (REPORT / f"{family}-synthetic-{label}-stderr.txt").write_bytes(result.stderr)
        assert result.returncode != 0 or result.stdout != expected_fixture
        negatives.append({"synthetic": label, "exit": result.returncode,
                          "output_sha256": sha(result.stdout), "exact_output_rejected": True})
    summary["families"].append({"family": family, "reference_bytes": len(expected),
                               "reference_sha256": sha(expected), "binding_lines_including_duplicates": len(bindings),
                               "partial_fixture_controls": checks, "synthetic_negatives": negatives})
    print(f"{family}: exact canonical reference and both Python-order controls pass; all three synthetic corruptions rejected")
(REPORT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
