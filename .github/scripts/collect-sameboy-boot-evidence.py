#!/usr/bin/env python3
"""GitHub-only, one pinned official archive; text evidence only, no ROM extraction.

This is collection, not build parity, package acceptance or execution. A boot CRC
mismatch is reported faithfully and does not change the firmware's allowed CRC.
"""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import sys
import urllib.parse
import urllib.request
import zipfile
import zlib

REPO = "LIJI32/SameBoy"
TAG_OBJECT = "5104c0429df2a73cfccea8c5034d5cb72c13c5f2"
COMMIT = "208ba4afabffab9edde416f2dbb8ae459e34adb8"
TAG = "v1.0.3"
RELEASE = 293176243
ASSET = 367047031
ARCHIVE_BYTES = 1629322
ARCHIVE_SHA = "66fb05acc075abba860f2c5fa31af2198fef9767573d28834c78d0dfc15746b2"
ARCHIVE_URL = "https://github.com/LIJI32/SameBoy/releases/download/v1.0.3/sameboy_winsdl_v1.0.3.zip"
LICENSE_URL = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/LICENSE"
LICENSE_SHA = "875b2c940181c315fa99ce5292326b985a43cdc4e878b38995066d6b495ff151"
FIXTURE_SHA = "cab3ca9108cd78d1ca07bbf6d8429ba6aa10da679d8291d5a0cd57877a0065bd"
MAX_FILE = 3000000


def require(ok, why):
    if not ok:
        raise ValueError(why)


def pin(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def failure_detail(exc):
    raw = f"{type(exc).__name__}: {exc}".encode("utf-8", "backslashreplace")
    result = {**pin(raw), "encoding": "utf-8 with backslash replacement for invalid code points"}
    candidate = {**result, "complete": True, "text": raw.decode("utf-8")}
    # Apply the identical JSON serialization used by save. Escaping can expand
    # control characters, backslashes and non-ASCII text beyond the raw size.
    # Reserve space for this small record's fixed collection-result envelope.
    encoded = (json.dumps(candidate, indent=2, sort_keys=True) + "\n").encode()
    if len(encoded) <= MAX_FILE - 4096:
        result = candidate
    else:
        result.update(complete=False, reason="Complete diagnostic exceeds report bound; content omitted, never silently clipped")
    return result


def utf8(data):
    require(b"\0" not in data, "NUL in report text")
    return data.decode("utf-8", "strict")


def save(root, name, value):
    require(Path(name).name == name and name not in (".", ".."), "report basename")
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode() if not isinstance(value, bytes) else value
    require(len(data) <= MAX_FILE, "report cap")
    utf8(data)
    with (root / name).open("xb") as stream:
        stream.write(data)


def fetch(url, cap):
    request = urllib.request.Request(url, headers={"User-Agent": "sd2snes-boot-evidence", "Accept": "application/vnd.github+json"} if url.startswith("https://api.github.com/") else {"User-Agent": "sd2snes-boot-evidence"})
    with urllib.request.urlopen(request, timeout=90) as response:
        final = urllib.parse.urlsplit(response.url)
        require(final.scheme == "https" and final.hostname in ("github.com", "api.github.com", "raw.githubusercontent.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"), "unexpected download endpoint")
        data = response.read(cap + 1)
        require(len(data) <= cap, "download exceeds cap")
        return data, {"requestedUrl": url, "finalHost": final.hostname, "status": response.status, **pin(data)}


def fetch_report(root, url, cap, report):
    body, observation = fetch(url, cap)
    save(root, report + "-download.json", observation)
    try:
        utf8(body)
    except (ValueError, UnicodeError):
        # Hash/size always survive; preserve invalid bounded text losslessly too
        # when its hexadecimal representation fits the unchanged text bound.
        hex_body = body.hex().encode("ascii") + b"\n"
        if len(hex_body) <= MAX_FILE:
            save(root, report + ".hex.txt", hex_body)
        else:
            save(root, report + "-unretained.json", {**pin(body), "complete": False, "reason": "Nontext response cannot be losslessly represented within report bound"})
        raise
    save(root, report, body)
    return body, observation


def read_fixture(root, path):
    require(path.is_file() and not path.is_symlink() and path.stat().st_size == 2214, "fixture file identity")
    body = path.read_bytes()
    save(root, "collection-data.json", body)
    require(pin(body)["sha256"] == FIXTURE_SHA, "fixture hash identity")
    fixture = json.loads(utf8(body))
    require(fixture["repository"] == REPO and fixture["releaseId"] == RELEASE and fixture["annotatedTagObject"] == TAG_OBJECT and fixture["sourceCommit"] == COMMIT and fixture["tag"] == TAG, "fixture source contract")
    require(fixture["asset"] == {"id": ASSET, "name": "sameboy_winsdl_v1.0.3.zip", "bytes": ARCHIVE_BYTES, "sha256": ARCHIVE_SHA, "url": ARCHIVE_URL}, "fixture asset contract")
    return fixture


def member_metadata(info):
    name = info.filename
    require(info.orig_filename == name and name and len(name) <= 240, "member filename")
    require(all(ord(c) >= 32 and ord(c) != 127 for c in name), "member control character")
    require("\\" not in name and ":" not in name and not name.startswith("/"), "member absolute or non-POSIX path")
    path = PurePosixPath(name)
    require(all(p not in ("", ".", "..") for p in name.rstrip("/").split("/")), "member path component")
    require(not path.is_absolute(), "absolute member")
    require(not info.flag_bits & 1, "encrypted member")
    require(info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), "unsupported compression")
    mode = info.external_attr >> 16
    require(stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR), "non-regular archive member")
    require(not (stat.S_ISDIR(mode) and not info.is_dir()), "directory mode mismatch")
    require(not (stat.S_ISREG(mode) and info.is_dir()), "regular mode mismatch")
    require(0 <= info.file_size <= 16000000 and 0 <= info.compress_size <= ARCHIVE_BYTES, "member size cap")
    require(not info.is_dir() or info.file_size == 0, "nonempty directory")
    return {"name": name, "bytes": info.file_size, "compressedBytes": info.compress_size, "crc32": f"{info.CRC:08x}", "flags": info.flag_bits, "compression": info.compress_type, "externalAttributes": info.external_attr, "headerOffset": info.header_offset, "directory": info.is_dir()}


def inspect_archive(data, source_license):
    # Do not extract members to disk or decode unrelated binary members.
    utf8(source_license)
    sdl_license = b"".join(line + b"\n" for line in source_license.splitlines() if not line.startswith(b"  "))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        require(0 < len(infos) <= 512, "member count")
        rows = [member_metadata(i) for i in infos]
        names = [r["name"].rstrip("/").casefold() for r in rows]
        require(len(names) == len(set(names)), "duplicate or case-aliased member")
        require(sum(i.file_size for i in infos) <= 32000000, "archive aggregate cap")
        boots = [i for i in infos if not i.is_dir() and PurePosixPath(i.filename).name == "cgb_boot.bin"]
        licenses = [i for i in infos if not i.is_dir() and PurePosixPath(i.filename).name.casefold() in ("license", "license.txt")]
        require(len(boots) == 1, "expected exactly one named cgb_boot.bin")
        require(0 < len(licenses) <= 8, "license candidate count")
        boot_info = boots[0]
        require(boot_info.file_size <= 65536, "boot cap")
        boot = archive.read(boot_info)  # ZIP member CRC is checked by zipfile.
        require(len(boot) == boot_info.file_size, "boot length")
        crc = f"{zlib.crc32(boot) & 0xffffffff:08x}"
        require(crc == f"{boot_info.CRC:08x}", "boot metadata CRC")
        boot_result = {"member": boot_info.filename, **pin(boot), "crc32": crc, "firmwareRequiredBytes": 2304, "firmwareRequiredCrc32": "8113b4d8", "matchesFirmwareContract": len(boot) == 2304 and crc == "8113b4d8", "bytesWrittenToDisk": False, "executed": False}
        license_results, texts = [], {}
        for index, info in enumerate(licenses):
            require(info.file_size <= 131072, "license cap")
            body = archive.read(info)
            require(len(body) == info.file_size, "license length")
            utf8(body)
            output = f"archive-license-{index + 1}.txt"
            texts[output] = body
            license_results.append({"member": info.filename, "report": output, **pin(body), "matchesRootSourceLicense": body == source_license, "matchesPinnedMakefileSdlLicense": body == sdl_license})
        return {"members": rows, "memberCount": len(rows), "aggregateUncompressedBytes": sum(i.file_size for i in infos), "boot": boot_result, "licenses": license_results, "sourceLicense": pin(source_license), "sourceDerivedSdlLicense": pin(sdl_license), "archiveLicenseMatchesSource": any(x["matchesRootSourceLicense"] or x["matchesPinnedMakefileSdlLicense"] for x in license_results)}, texts


def collect(root, fixture):
    observations = []
    for endpoint, report in ((f"https://api.github.com/repos/{REPO}/releases/{RELEASE}", "release.json"), (f"https://api.github.com/repos/{REPO}/releases/assets/{ASSET}", "asset.json"), (f"https://api.github.com/repos/{REPO}/git/ref/tags/{TAG}", "source-tag.json"), (f"https://api.github.com/repos/{REPO}/git/tags/{TAG_OBJECT}", "source-tag-object.json")):
        body, observation = fetch_report(root, endpoint, MAX_FILE, report)
        parsed = json.loads(utf8(body))
        observations.append(observation)
        if report == "release.json":
            require(parsed["id"] == RELEASE and parsed["tag_name"] == TAG and not parsed["draft"] and not parsed["prerelease"], "release identity")
            require(sum(a["id"] == ASSET for a in parsed["assets"]) == 1, "asset release membership")
        elif report == "asset.json":
            require(parsed["id"] == ASSET and parsed["name"] == "sameboy_winsdl_v1.0.3.zip" and parsed["size"] == ARCHIVE_BYTES and parsed["digest"] == "sha256:" + ARCHIVE_SHA and parsed["state"] == "uploaded" and parsed["browser_download_url"] == ARCHIVE_URL, "asset identity")
        elif report == "source-tag.json":
            require(parsed["ref"] == "refs/tags/" + TAG and parsed["object"]["type"] == "tag" and parsed["object"]["sha"] == TAG_OBJECT, "source tag reference identity")
        else:
            require(parsed["sha"] == TAG_OBJECT and parsed["tag"] == TAG and parsed["object"]["type"] == "commit" and parsed["object"]["sha"] == COMMIT, "peeled source commit identity")
    source_license, observation = fetch_report(root, LICENSE_URL, 1495, "source-LICENSE.txt")
    observations.append(observation)
    require(pin(source_license) == {"bytes": 1495, "sha256": LICENSE_SHA}, "source license identity")
    for key, report in (("sourceMakefile", "source-Makefile.txt"), ("sourceBoot", "source-cgb-boot.asm.txt")):
        contract = fixture[key]
        body, observation = fetch_report(root, contract["url"], contract["bytes"], report)
        observations.append(observation)
        blob = hashlib.sha1(b"blob " + str(len(body)).encode("ascii") + b"\0" + body).hexdigest()
        require(len(body) == contract["bytes"] and blob == contract["gitBlob"], key + " complete source identity")
    archive, observation = fetch(ARCHIVE_URL, ARCHIVE_BYTES)
    observations.append(observation)
    save(root, "archive-download.json", observation)
    save(root, "downloads.json", observations)
    require(pin(archive) == {"bytes": ARCHIVE_BYTES, "sha256": ARCHIVE_SHA}, "archive identity")
    result, texts = inspect_archive(archive, source_license)
    save(root, "archive-members.json", result.pop("members"))
    for name, body in texts.items():
        save(root, name, body)
    save(root, "inspection.json", result)
    return {"collectionComplete": True, "bootMatchesFirmwareContract": result["boot"]["matchesFirmwareContract"], "archiveLicenseMatchesSource": result["archiveLicenseMatchesSource"]}


def self_test(root):
    rows = []
    source_license = b"  source scope\nExpat License\nPermission notice\n"
    def archive_bytes(entries):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, body in entries:
                archive.writestr(name, body)
        return buf.getvalue()
    base = [("cgb_boot.bin", b"sample"), ("LICENSE", b"Expat License\nPermission notice\n")]
    for name, entries, expected_ok in (
        ("valid collection explicitly reports CRC mismatch", base, True),
        ("full source license accepted", [("cgb_boot.bin", b"sample"), ("LICENSE", source_license)], True),
        ("traversal", base + [("../escape", b"x")], False),
        ("absolute", base + [("/escape", b"x")], False),
        ("backslash", base + [("dir\\escape", b"x")], False),
        ("case alias", base + [("CGB_BOOT.BIN", b"x")], False),
        ("two named boot members", base + [("extra/cgb_boot.bin", b"x")], False),
        ("missing boot", [base[1]], False),
        ("missing license", [base[0]], False),
        ("nontext license", [base[0], ("LICENSE", b"\xff")], False),
        ("NUL license", [base[0], ("LICENSE", b"x\0y")], False),
        ("oversized boot", [("cgb_boot.bin", b"x" * 65537), base[1]], False),
        ("oversized license", [base[0], ("LICENSE", b"x" * 131073)], False),
    ):
        error = None
        try:
            result, texts = inspect_archive(archive_bytes(entries), source_license)
            require(result["boot"]["matchesFirmwareContract"] is False, "synthetic mismatch must remain false")
            require(result["archiveLicenseMatchesSource"] is True and texts, "synthetic source license comparison")
        except Exception as exc:
            error = str(exc)
        passed = (error is None) == expected_ok
        rows.append({"case": name, "expectedAccepted": expected_ok, "accepted": error is None, "passed": passed, "error": error})
    for name, mutation in (("symlink", lambda i: setattr(i, "external_attr", (stat.S_IFLNK | 0o777) << 16)), ("encrypted", lambda i: setattr(i, "flag_bits", 1)), ("unknown compression", lambda i: setattr(i, "compress_type", 99))):
        info = zipfile.ZipInfo("candidate")
        mutation(info)
        error = None
        try:
            member_metadata(info)
        except Exception as exc:
            error = str(exc)
        rows.append({"case": name, "expectedAccepted": False, "accepted": error is None, "passed": error is not None, "error": error})
    save(root, "controls.json", rows)
    require(all(r["passed"] for r in rows), "collection control failure")
    return {"controlsPassed": True, "positiveControls": 2, "negativeControls": 14}


def main():
    require(len(sys.argv) == 4 and sys.argv[1] in ("--collect", "--self-test"), "usage: collect-sameboy-boot-evidence.py --collect|--self-test NEW_REPORT_DIRECTORY FIXTURE_PATH")
    root = Path(sys.argv[2])
    require(root.is_absolute() and root.parent.is_dir() and not root.exists() and not root.is_symlink(), "fresh absolute output directory required")
    require(root.parent.resolve() == root.parent, "canonical output parent required")
    root.mkdir()
    result = {"operation": sys.argv[1], "collectionOnly": True, "packageEligible": False, "sourceBuildParityProved": False, "nativeExecuted": False, "hardwareQualified": False, "error": None}
    code = 0
    try:
        fixture = read_fixture(root, Path(sys.argv[3]))
        result.update(collect(root, fixture) if sys.argv[1] == "--collect" else self_test(root))
    except BaseException as exc:
        code = 1
        result["error"] = failure_detail(exc)
    try:
        save(root, "collection-result.json", result)
        members = []
        for path in sorted(root.iterdir()):
            require(path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_FILE, "final report file")
            body = path.read_bytes()
            utf8(body)
            members.append({"path": path.name, **pin(body)})
        manifest = (json.dumps(members, indent=2, sort_keys=True) + "\n").encode()
        require(len(members) + 1 <= 1024 and sum(m["bytes"] for m in members) + len(manifest) <= 96000000, "manifest-inclusive final report aggregate")
        save(root, "reports.json", manifest)
    except BaseException as exc:
        code = 1
        save(root, "finalization-failure.json", failure_detail(exc))
    return code


if __name__ == "__main__":
    sys.exit(main())
