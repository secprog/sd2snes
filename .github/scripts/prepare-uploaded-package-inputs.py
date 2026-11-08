#!/usr/bin/env python3
"""Reuse the successful 45-core/menu build on GitHub after checker-only fixes."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import threading
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE_RUN = 42507318034
SOURCE_SHA = "31cecdc00d200691afe8a85a5ec6f8cc2924e92e"
ALLOWED_CHANGES = {
    ".github/scripts/check-fpga-manifest.py", ".github/scripts/check-mcu.sh",
    ".github/scripts/prepare-uploaded-package-inputs.py",
    ".github/workflows/package-uploaded-build.yml",
}
REPORTS = None
API_NUMBER = 0


def require(ok, why):
    if not ok:
        raise ValueError(why)


def git(*args):
    return subprocess.check_output(["git", "-c", "safe.directory=" + str(ROOT), *args], cwd=ROOT)


def api(endpoint, cap=3000000):
    global API_NUMBER
    API_NUMBER += 1
    prefix = REPORTS / f"api-{API_NUMBER:03d}"
    buffers, exceeded = [bytearray(), bytearray()], [False, False]
    reader_errors = []
    env = dict(os.environ)
    env.pop("GH_DEBUG", None)
    env["GH_PROMPT_DISABLED"] = "1"
    process = subprocess.Popen(["gh", "api", endpoint], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env=env)

    def read(stream, index, limit):
        try:
            with stream:
                while True:
                    chunk = stream.read(65536)
                    if not chunk:
                        break
                    remaining = limit + 1 - len(buffers[index])
                    buffers[index].extend(chunk[:remaining])
                    if len(chunk) > remaining or len(buffers[index]) > limit:
                        exceeded[index] = True
                        process.kill()
                        break
        except Exception as exc:
            reader_errors.append(str(exc))
            process.kill()

    readers = [threading.Thread(target=read, args=(stream, i, limit), daemon=True)
               for i, (stream, limit) in enumerate(((process.stdout, cap), (process.stderr, 256000)))]
    for reader in readers:
        reader.start()
    timed_out = False
    try:
        process.wait(timeout=120)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        process.wait(timeout=15)
    for reader in readers:
        reader.join(timeout=15)
    complete = not timed_out and not any(exceeded) and not reader_errors and not any(r.is_alive() for r in readers)
    stdout, stderr = bytes(buffers[0]), bytes(buffers[1])
    record = {"endpoint": endpoint, "clientExit": process.returncode, "clientReaped": process.poll() is not None,
              "complete": complete, "timedOut": timed_out, "boundExceeded": exceeded,
              "readerErrors": reader_errors, "stderrHex": stderr.hex(),
              "stdoutBytesRetained": len(stdout), "stdoutSha256": hashlib.sha256(stdout).hexdigest(),
              "stdoutKind": "artifact-zip-github-only" if endpoint.endswith("/zip") else "metadata"}
    prefix.with_suffix(".json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    if not endpoint.endswith("/zip"):
        # Preserve every complete metadata response, including a nonzero client's body.
        try:
            text = stdout.decode("utf-8", "strict")
            require("\0" not in text, "NUL metadata")
            prefix.with_suffix(".body.txt").write_bytes(stdout)
        except (UnicodeError, ValueError):
            prefix.with_suffix(".body-error.txt").write_text("Nontext metadata response; see exact byte hash in receipt.\n")
            raise ValueError("GitHub metadata must be complete UTF-8/NUL-free text")
    require(complete and process.returncode == 0, "GitHub API request failed; see complete request receipt")
    return stdout


def pages(endpoint, key):
    result = []
    for page in range(1, 11):
        data = json.loads(api(endpoint + f"?per_page=100&page={page}"))
        result.extend(data[key])
        if len(result) >= data["total_count"]:
            require(len(result) == data["total_count"], "Pagination count changed")
            return result
    raise ValueError("Pagination bound exceeded")


def unpack(artifact, destination, tracked, allowed):
    require(not artifact["expired"] and 0 < artifact["size_in_bytes"] <= 16000000,
            "Live bounded artifact required")
    body = api(f"repos/secprog/sd2snes/actions/artifacts/{artifact['id']}/zip", 16000000)
    require(len(body) == artifact["size_in_bytes"]
            and "sha256:" + hashlib.sha256(body).hexdigest() == artifact["digest"],
            "Complete artifact transport identity")
    files, seen, total = [], set(), 0
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        require(len(archive.infolist()) <= 1024, "Artifact member count")
        for info in archive.infolist():
            name = info.filename
            path = PurePosixPath(name)
            require(name == info.orig_filename and name and not path.is_absolute()
                    and "\\" not in name and ":" not in name
                    and all(p.casefold() != ".git" for p in path.parts)
                    and not any(ord(c) < 32 or ord(c) == 127 for c in name)
                    and all(p not in ("", ".", "..") for p in name.rstrip("/").split("/")),
                    "Unsafe archive path")
            alias = name.rstrip("/").casefold()
            require(alias not in seen, "Duplicate or case-aliased archive path")
            seen.add(alias)
            require(not info.flag_bits & 1 and info.compress_type in (0, 8)
                    and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG, stat.S_IFDIR),
                    "Non-regular or encrypted archive member")
            target = destination.joinpath(*path.parts)
            relative = target.relative_to(ROOT).as_posix()
            if info.is_dir():
                require(info.file_size == 0, "Nonempty directory")
                require(any(p.startswith(relative + "/") for p in allowed), "Unexpected output directory")
                continue
            require(info.file_size <= 16000000, "Artifact member bound")
            total += info.file_size
            require(total <= 64000000, "Artifact aggregate bound")
            require(relative in allowed, "Artifact member outside its exact advertised outputs")
            require(relative not in tracked and not target.exists() and not target.is_symlink(),
                    "Artifact would overwrite checkout or prior output")
            require(not any(p.is_symlink() for p in (target, *target.parents)), "Linked output ancestry")
            data = archive.read(info)  # Decompression also checks each CRC.
            require(len(data) == info.file_size, "Artifact member length")
            files.append((target, data))
    require({p.relative_to(ROOT).as_posix() for p, _ in files} == allowed,
            "Missing or extra advertised artifact outputs")
    for target, data in files:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
    return {"id": artifact["id"], "name": artifact["name"], "zipBytes": len(body),
            "zipSha256": hashlib.sha256(body).hexdigest(), "files": [
                {"path": p.relative_to(ROOT).as_posix(), "bytes": len(b),
                 "sha256": hashlib.sha256(b).hexdigest()} for p, b in files]}


def main():
    global REPORTS
    require(os.environ.get("GITHUB_ACTIONS") == "true", "GitHub-only operation")
    require(os.environ.get("GITHUB_REPOSITORY") == "secprog/sd2snes", "Exact fork required")
    require(len(sys.argv) == 3 and sys.argv[1] in ("mk2", "mk3", "mk3-stm32"),
            "Expected board and fresh absolute report directory")
    board, reports = sys.argv[1], Path(sys.argv[2])
    require(reports.is_absolute() and not reports.exists() and reports.parent.is_dir(), "Fresh reports required")
    reports.mkdir()
    REPORTS = reports
    require(git("rev-parse", "HEAD").decode().strip() == os.environ["GITHUB_SHA"]
            and git("rev-list", "--parents", "-n", "1", "HEAD").decode().split()
            == [os.environ["GITHUB_SHA"], SOURCE_SHA],
            "Exact current checkout and reviewed single-parent continuation required")
    changed = set(git("diff", "--name-only", SOURCE_SHA, "HEAD").decode().splitlines())
    require(changed == ALLOWED_CHANGES, "Only the four reviewed checker/workflow changes may differ")
    require(not git("diff", "--name-only") and not git("diff", "--cached", "--name-only"),
            "Tracked checkout must be clean")
    tracked = set(git("ls-files", "-z").decode().split("\0"))
    index_before = git("ls-files", "--stage", "-z")
    run = json.loads(api(f"repos/secprog/sd2snes/actions/runs/{SOURCE_RUN}"))
    require(run["head_sha"] == SOURCE_SHA and run["run_attempt"] == 1
            and run["status"] == "completed" and run["conclusion"] == "failure"
            and run["event"] == "workflow_dispatch"
            and run["repository"]["full_name"] == "secprog/sd2snes", "Immutable source run identity")
    jobs = pages(f"repos/secprog/sd2snes/actions/runs/{SOURCE_RUN}/jobs", "jobs")
    expected_failures = {"Build and package mk3 firmware", "Build and package mk3-stm32 firmware"}
    require({j["name"] for j in jobs if j["conclusion"] == "failure"} == expected_failures
            and all(j["conclusion"] in ("success", "failure", "skipped") for j in jobs),
            "Only the two preserved known package failures are permitted")
    expected_skips = {"Build MkII firmware bootstrap", "Check ${{ matrix.board }} firmware (${{ matrix.runner }})"}
    require({j["name"] for j in jobs if j["conclusion"] == "skipped"} == expected_skips,
            "Unexpected skipped source job")
    spec = importlib.util.spec_from_file_location("package_contract", ROOT / ".github/scripts/check-fpga-manifest.py")
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    expected = {f"Build {b} core {name}" for b in ("mk2", "mk3") for name in contract.cores(b)}
    core_jobs = [j for j in jobs if j["name"].startswith("Build mk") and " core " in j["name"]]
    require(len(expected) == 45 and len(core_jobs) == 45
            and {j["name"] for j in core_jobs} == expected
            and all(j["conclusion"] == "success" for j in core_jobs), "All exact 45 core jobs must have succeeded")
    for name in ("Build SNES menus and onboarding", "Collect complete mk2 FPGA set", "Collect complete mk3 FPGA set"):
        matches = [j for j in jobs if j["name"] == name]
        require(len(matches) == 1 and matches[0]["conclusion"] == "success", "Successful source job required: " + name)
    artifacts = pages(f"repos/secprog/sd2snes/actions/runs/{SOURCE_RUN}/artifacts", "artifacts")
    fpga = "mk2" if board == "mk2" else "mk3"
    selections = [("fpga-" + fpga, ROOT), ("menus", ROOT / "snes"),
                  ("atari-player" if board == "mk2" else "mk3-players", ROOT)]
    cc65 = {"snes/players/toolchains/cc65/" + p for p in (
        "host-compiler-version.txt", "source-commit.txt", "source.sha256",
        "ca65-version.txt", "ld65-version.txt", "tools.sha256")}
    asar = {"snes/players/toolchains/asar/" + p for p in (
        "host-compiler-version.txt", "cmake-version.txt", "source-commit.txt",
        "source.sha256", "asar-version.txt", "tools.sha256")}
    namespaces = {
        "fpga-" + fpga: contract.images(fpga),
        "menus": {"snes/" + p for p in ("menu.bin", "m3nu.bin", "igmenu.bin", "onboarding.bin",
                    "lang_ja.bin", "lang_zh.bin", "lang_ja.fnt", "lang_zh.fnt")},
        "atari-player": cc65 | {"misc/atari_snes.bin", "snes/atari/build.log",
                              "snes/atari/toolchain.log", "snes/atari/source-output.sha256"},
        "mk3-players": cc65 | asar | {"misc/" + p for p in (
            "nes_snes.bin", "nes_snes.map", "sms_snes.bin", "gbc_snes.bin", "a26_snes.bin",
            "cgb_boot.bin", "cgb_boot.LICENSE")} | {"snes/players/" + p for p in (
            "build.log", "toolchain.log", "source-output.sha256", "source-before.sha256", "source-check.log")},
    }
    records = []
    for name, destination in selections:
        matches = [a for a in artifacts if a["name"] == name]
        require(len(matches) == 1, "Exactly one artifact required: " + name)
        require(matches[0]["workflow_run"]["id"] == SOURCE_RUN
                and matches[0]["workflow_run"]["head_sha"] == SOURCE_SHA, "Artifact source run binding")
        records.append(unpack(matches[0], destination, tracked, namespaces[name]))
    require(not git("diff", "--name-only") and not git("diff", "--cached", "--name-only")
            and git("ls-files", "--stage", "-z") == index_before,
            "Tracked source/index changed during extraction")
    result = {"sourceRun": SOURCE_RUN, "sourceCommit": SOURCE_SHA,
              "sourceRunConclusion": run["conclusion"],
              "sourceJobDispositions": [{"id": j["id"], "name": j["name"],
                                         "conclusion": j["conclusion"]} for j in jobs],
              "currentCommit": git("rev-parse", "HEAD").decode().strip(), "board": board,
              "all45SourceCoresSucceeded": True, "unchangedRuntimeSources": True,
              "allowedChangedPaths": sorted(changed), "artifacts": records,
              "timingStatus": "unverified-user-waiver", "hardwareQualified": False}
    (reports / "reused-inputs.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "artifacts"}, sort_keys=True))


if __name__ == "__main__":
    main()
