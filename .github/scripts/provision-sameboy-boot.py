#!/usr/bin/env python3
"""Provision the reviewed free SameBoy boot on GitHub, without executing it.

Only the two accepted members are written. The original collection remains
immutable; this separate operation checks its own downloads and installation.
"""
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "sameboy_collection", ROOT / ".github/scripts/collect-sameboy-boot-evidence.py")
COLLECTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECTION)
require = COLLECTION.require
BOOT = {"bytes": 2304, "crc32": "8113b4d8",
        "sha256": "f767b8e7e510a255f81328c89dba6e0c996b370e1bc86aebb8584a7da47a5bba"}
LICENSE = {"bytes": 1076,
           "sha256": "625e39d02285f37b6b89a60ec6fabd8afc780a052b179442ce0676eed299858a"}
EVIDENCE = {
    "repository": "LIJI32/SameBoy",
    "source_commit": "208ba4afabffab9edde416f2dbb8ae459e34adb8",
    "run_id": "42504433661", "artifact_id": "13625819878",
    "artifact_sha256": "62e176334043203a0baf5672c27836c5d412d89d05501b93bd502dd17efb7a2f",
    "root_receipt_sha256": "87e4248e66ba72660b1c8df83cffe358ab9a32b88c417405f5bc81cbcfba1ab0",
}
ACCEPTANCE = {"schema": 1, "status": "accepted-for-packaging",
              "boot": BOOT, "license": LICENSE, "evidence": EVIDENCE}


def verify_pair(boot, license_text, acceptance):
    require(acceptance == ACCEPTANCE, "Exact reviewed packaging acceptance required")
    require({**COLLECTION.pin(boot), "crc32": f"{zlib.crc32(boot):08x}"} == BOOT,
            "Boot differs from accepted size, CRC or complete SHA256")
    COLLECTION.utf8(license_text)
    require(COLLECTION.pin(license_text) == LICENSE, "Accepted license identity required")


def controls(boot, license_text, acceptance):
    cases = [("exact accepted pair", boot, license_text, acceptance, True)]
    for name, changed_boot, changed_license in (
            ("truncated boot", boot[:-1], license_text),
            ("corrupt boot", bytes([boot[0] ^ 1]) + boot[1:], license_text),
            ("empty boot", b"", license_text),
            ("missing license", boot, b""),
            ("substituted license", boot, license_text + b"\n"),
            ("NUL license", boot, b"\0" + license_text[1:])):
        cases.append((name, changed_boot, changed_license, acceptance, False))
    for field in ACCEPTANCE:
        changed = copy.deepcopy(acceptance)
        del changed[field]
        cases.append(("missing acceptance " + field, boot, license_text, changed, False))
    changed = copy.deepcopy(acceptance)
    changed["evidence"]["source_commit"] = "0" * 40
    cases.append(("foreign provenance", boot, license_text, changed, False))
    rows = []
    for name, data, notice, manifest, expected in cases:
        error = None
        try:
            verify_pair(data, notice, manifest)
        except Exception as exc:
            error = str(exc)
        rows.append({"case": name, "expectedAccepted": expected,
                     "accepted": error is None, "passed": (error is None) == expected,
                     "error": error})
    require(all(row["passed"] for row in rows), "Provisioning control failed")
    return rows


def install_pair(misc, manifest, reports, boot, license_text, result, inject=None):
    """Own exclusive output creation and restore the generated record on failure."""
    outputs = [(misc / "cgb_boot.bin", boot), (misc / "cgb_boot.LICENSE", license_text)]
    receipt = reports / "provision-result.json"
    require(misc.is_dir() and not misc.is_symlink() and misc.resolve() == misc,
            "Canonical misc directory required")
    require(manifest.is_file() and not manifest.is_symlink(), "Fresh player record required")
    original = manifest.read_bytes()
    require(b"cgb_boot." not in original, "Boot must not already appear in player record")
    require(not receipt.exists() and not receipt.is_symlink(), "Fresh result required")
    require(all(not path.exists() and not path.is_symlink() for path, _ in outputs),
            "Refuse to overwrite an existing boot or license")
    installed = []
    record_touched = False

    def event(name):
        if inject == name or (inject == "cleanup-unlink-1" and name == "after-result"):
            raise OSError("Injected installation failure: " + name)

    try:
        for number, (path, data) in enumerate(outputs, 1):
            event(f"before-create-{number}")
            with path.open("xb") as stream:
                installed.append(path)  # Own the file before any write can fail.
                event(f"after-create-{number}")
                stream.write(data)
                event(f"after-write-{number}")
                stream.flush()
                event(f"before-fsync-{number}")
                os.fsync(stream.fileno())
        verify_pair(outputs[0][0].read_bytes(), outputs[1][0].read_bytes(), ACCEPTANCE)
        record_touched = True
        with manifest.open("ab") as stream:
            for path, data in outputs:
                stream.write((COLLECTION.pin(data)["sha256"] + "  misc/" + path.name + "\n").encode())
            event("manifest-write")
            stream.flush()
            os.fsync(stream.fileno())
        event("before-result")
        COLLECTION.save(reports, "provision-result.json", result)
        event("after-result")
    except BaseException as primary:
        cleanup = []
        for number, path in enumerate(installed, 1):
            try:
                if inject == "cleanup-unlink-1" and number == 1:
                    raise OSError("Injected first-output cleanup failure")
                path.unlink()
            except OSError as exc:
                cleanup.append(str(exc))
        if record_touched:
            try:
                manifest.write_bytes(original)
            except OSError as exc:
                cleanup.append(str(exc))
        if receipt.exists():
            try:
                receipt.unlink()
            except OSError as exc:
                cleanup.append(str(exc))
        if cleanup:
            raise RuntimeError("Installation failed; incomplete cleanup: " + repr(cleanup)) from primary
        raise


def installation_controls(boot, license_text):
    rows = []
    events = [f"{phase}-{number}" for number in (1, 2)
              for phase in ("before-create", "after-create", "after-write", "before-fsync")]
    for event in [None, *events, "manifest-write", "before-result", "after-result",
                  "preexisting", "cleanup-unlink-1"]:
        with tempfile.TemporaryDirectory(prefix="sameboy-install-control-") as directory:
            root = Path(directory).resolve()
            misc, reports = root / "misc", root / "reports"
            misc.mkdir()
            reports.mkdir()
            manifest = root / "source-output.sha256"
            original = b"synthetic original player record\n"
            manifest.write_bytes(original)
            if event == "preexisting":
                (misc / "cgb_boot.bin").write_bytes(b"existing unrelated input")
            error = None
            try:
                install_pair(misc, manifest, reports, boot, license_text,
                             {"control": True}, inject=event)
            except Exception as exc:
                error = str(exc)
            expected = event is None
            if expected:
                verify_pair((misc / "cgb_boot.bin").read_bytes(),
                            (misc / "cgb_boot.LICENSE").read_bytes(), ACCEPTANCE)
                expected_record = original + b"".join(
                    (COLLECTION.pin(data)["sha256"] + "  misc/" + name + "\n").encode()
                    for name, data in (("cgb_boot.bin", boot), ("cgb_boot.LICENSE", license_text)))
                intact = (manifest.read_bytes() == expected_record
                          and json.loads((reports / "provision-result.json").read_bytes()) == {"control": True})
            else:
                expected_files = ["cgb_boot.bin"] if event in ("preexisting", "cleanup-unlink-1") else []
                intact = sorted(p.name for p in misc.iterdir()) == expected_files
                intact = intact and manifest.read_bytes() == original and not list(reports.iterdir())
                if event == "preexisting":
                    intact = intact and (misc / "cgb_boot.bin").read_bytes() == b"existing unrelated input"
                if event == "cleanup-unlink-1":
                    intact = (intact and (misc / "cgb_boot.bin").read_bytes() == boot
                              and error is not None and "incomplete cleanup" in error)
            rows.append({"case": event or "successful exclusive installation",
                         "expectedAccepted": expected, "accepted": error is None,
                         "outputsAndRecordCorrect": intact,
                         "passed": ((error is None) == expected and intact), "error": error})
    require(all(row["passed"] for row in rows), "Installation lifecycle control failed")
    return rows


def provision(reports):
    fixture = COLLECTION.read_fixture(
        reports, ROOT / ".github/fixtures/sameboy-103-boot-collection-data.json")
    acceptance_path = ROOT / ".github/fixtures/accepted-cgb-boot.json"
    require(acceptance_path.is_file() and not acceptance_path.is_symlink(), "Acceptance file required")
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    require(acceptance == ACCEPTANCE, "Reviewed acceptance file identity")
    observations = []
    for endpoint, name in (
            (f"releases/{COLLECTION.RELEASE}", "release.json"),
            (f"releases/assets/{COLLECTION.ASSET}", "asset.json"),
            (f"git/ref/tags/{COLLECTION.TAG}", "source-tag.json"),
            (f"git/tags/{COLLECTION.TAG_OBJECT}", "source-tag-object.json")):
        body, observation = COLLECTION.fetch_report(
            reports, f"https://api.github.com/repos/{COLLECTION.REPO}/{endpoint}",
            COLLECTION.MAX_FILE, name)
        observations.append(observation)
        data = json.loads(body)
        if name == "release.json":
            require(data["id"] == COLLECTION.RELEASE and data["tag_name"] == COLLECTION.TAG
                    and not data["draft"] and not data["prerelease"], "Release identity")
            require(sum(a["id"] == COLLECTION.ASSET for a in data["assets"]) == 1,
                    "Asset belongs to pinned release")
        elif name == "asset.json":
            require(data["id"] == COLLECTION.ASSET and data["state"] == "uploaded"
                    and data["name"] == fixture["asset"]["name"]
                    and data["size"] == COLLECTION.ARCHIVE_BYTES
                    and data["digest"] == "sha256:" + COLLECTION.ARCHIVE_SHA
                    and data["browser_download_url"] == COLLECTION.ARCHIVE_URL, "Asset identity")
        elif name == "source-tag.json":
            require(data["ref"] == "refs/tags/" + COLLECTION.TAG
                    and data["object"] == {"type": "tag", "sha": COLLECTION.TAG_OBJECT,
                                           "url": data["object"]["url"]}, "Source tag identity")
        else:
            require(data["sha"] == COLLECTION.TAG_OBJECT and data["tag"] == COLLECTION.TAG
                    and data["object"]["type"] == "commit"
                    and data["object"]["sha"] == COLLECTION.COMMIT, "Peeled source identity")
    source_license, observation = COLLECTION.fetch_report(
        reports, COLLECTION.LICENSE_URL, 1495, "source-LICENSE.txt")
    observations.append(observation)
    require(COLLECTION.pin(source_license) == {"bytes": 1495, "sha256": COLLECTION.LICENSE_SHA},
            "Source license identity")
    for key, name in (("sourceMakefile", "source-Makefile.txt"),
                      ("sourceBoot", "source-cgb-boot.asm.txt")):
        contract = fixture[key]
        body, observation = COLLECTION.fetch_report(
            reports, contract["url"], contract["bytes"], name)
        observations.append(observation)
        blob = hashlib.sha1(b"blob " + str(len(body)).encode() + b"\0" + body).hexdigest()
        require(len(body) == contract["bytes"] and blob == contract["gitBlob"],
                "Complete pinned source identity: " + key)
    archive_bytes, observation = COLLECTION.fetch(COLLECTION.ARCHIVE_URL, COLLECTION.ARCHIVE_BYTES)
    observations.append(observation)
    COLLECTION.save(reports, "downloads.json", observations)
    require(COLLECTION.pin(archive_bytes) == {"bytes": COLLECTION.ARCHIVE_BYTES,
                                            "sha256": COLLECTION.ARCHIVE_SHA}, "Archive identity")
    inspection, texts = COLLECTION.inspect_archive(archive_bytes, source_license)
    require(inspection["boot"]["matchesFirmwareContract"]
            and inspection["archiveLicenseMatchesSource"], "Firmware and license contracts")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        boot = archive.read(inspection["boot"]["member"])
    matches = [item for item in inspection["licenses"]
               if item["matchesPinnedMakefileSdlLicense"]]
    require(len(matches) == 1, "Exactly one accepted SDL license")
    license_text = texts[matches[0]["report"]]
    verify_pair(boot, license_text, acceptance)
    COLLECTION.save(reports, "controls.json", controls(boot, license_text, acceptance))
    COLLECTION.save(reports, "installation-controls.json", installation_controls(boot, license_text))
    COLLECTION.save(reports, "inspection.json", inspection)
    misc = ROOT / "misc"
    manifest = ROOT / "snes/players/source-output.sha256"
    result = {"provisioned": True, "boot": BOOT, "license": LICENSE, "evidence": EVIDENCE,
              "outputs": ["misc/cgb_boot.bin", "misc/cgb_boot.LICENSE"],
              "romExecuted": False, "sourceBuildParityProved": False,
              "scope": "Exact accepted freely licensed input provisioning only; no timing or hardware qualification"}
    install_pair(misc, manifest, reports, boot, license_text, result)
    return result


def main():
    require(len(sys.argv) == 2, "usage: provision-sameboy-boot.py NEW_REPORT_DIRECTORY")
    reports = Path(sys.argv[1])
    require(os.environ.get("GITHUB_ACTIONS") == "true", "Run only on GitHub Actions")
    require(reports.is_absolute() and reports.parent.resolve() == reports.parent
            and reports.parent.is_dir() and not reports.exists(), "Fresh absolute report directory required")
    reports.mkdir()
    try:
        result = provision(reports)
    except BaseException as exc:
        states = {}
        for name in ("misc/cgb_boot.bin", "misc/cgb_boot.LICENSE",
                     "snes/players/source-output.sha256"):
            path = ROOT / name
            try:
                states[name] = {"exists": path.exists(), "symlink": path.is_symlink()}
                if path.is_file() and not path.is_symlink():
                    states[name].update(COLLECTION.pin(path.read_bytes()))
            except Exception as state_error:
                states[name] = {"observationError": COLLECTION.failure_detail(state_error)}
        try:
            success_receipt_exists = (reports / "provision-result.json").exists()
        except Exception as state_error:
            success_receipt_exists = {"observationError": COLLECTION.failure_detail(state_error)}
        COLLECTION.save(reports, "provision-failure.json",
                        {"provisioned": False, "error": COLLECTION.failure_detail(exc),
                         "finalOutputStates": states,
                         "successReceiptExists": success_receipt_exists})
        raise


if __name__ == "__main__":
    main()
