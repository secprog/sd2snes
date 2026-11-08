#!/usr/bin/env python3
"""Check board coverage and packaged images on the GitHub runner."""
import json
import io
import hashlib
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[2]
# These exclusions follow the firmware's CONFIG_MK2 guards and the variant
# project files. Legacy NES/SMS .xise files do not make their MCU loaders work
# on MkII. New core directories require an explicit board-support audit here.
EXCLUDED = {
    "mk2": {"a26", "gbc", "nes", "nes_k", "nes_mmc3", "nes_mmc5", "sms"},
    "mk3": {"atari", "basex", "dspx", "sgb_msu"},
}
EXT = {"mk2": "bit", "mk3": "bi3"}
FIRMWARE = {"mk2": "firmware.img", "mk3": "firmware.im3", "mk3-stm32": "firmware.stm"}
# src/config-mk* and src/ovl.c: overlays use the MCU file suffix, not the FPGA board.
FIRMWARE_SPEC = {"mk2": (b"SNSD", 0x100, "img"),
                 "mk3": (b"SNS3", 0x100, "im3"),
                 "mk3-stm32": (b"STM3", 0x200, "stm")}
CARD_MODULES = ("nsfplay.bin", "memtest.bin", "pcmplay.bin", "rtc7110.bin",
                "fileops.bin", "rmdir.bin", "xc_soc.bin")
MENU_ASSETS = ("classic.thm", "menu.spc", "sfx_cursor.pcm", "sfx_confirm.pcm",
               "sfx_back.pcm", "sfx_error.pcm", "welcome.fmv", "welcome.pcm")
MK3_PLAYERS = ("nes_snes.bin", "sms_snes.bin", "gbc_snes.bin", "a26_snes.bin",
               "cgb_boot.bin", "cgb_boot.LICENSE")
GBC_BOOT_SIZE = 2304
GBC_BOOT_CRC = 0x8113B4D8
MAX_PACKAGE_BYTES = 256 * 1024 * 1024


def cores(board):
    names = subprocess.check_output(
        ["make", "--no-print-directory", "-s", f"list-fpga-{board}"],
        cwd=ROOT, text=True,
    ).split()
    inventory = {p.parent.name.removeprefix("sd2snes_")
                 for p in (ROOT / "verilog").glob("sd2snes_*/Makefile")}
    expected = inventory - EXCLUDED[board]
    if len(names) != len(set(names)) or set(names) != expected:
        raise RuntimeError(f"{board} core list: missing {sorted(expected - set(names))}; "
                           f"unexpected {sorted(set(names) - expected)}; check duplicates too")
    for name in names:
        project = ROOT / "verilog" / f"sd2snes_{name}"
        required = ([f"sd2snes_{name}.xise"] if board == "mk2"
                    else [f"sd2snes_{name}.qpf", "main.qsf"])
        for filename in required:
            if not (project / filename).is_file():
                raise RuntimeError(f"Missing {board} project: {project / filename}")
        if board == "mk2":
            makefile = (project / "Makefile").read_text()
            ip_dir = re.search(r"^XIL_IPCORE_DIR\s*=\s*(\S+)", makefile, re.MULTILINE)
            if ip_dir:
                ip_path = project / ip_dir[1]
                if any(ip_path.glob("*.xco")) and not (ip_path / "coregen.cgc").is_file():
                    raise RuntimeError(f"Missing CoreGen project: {ip_path / 'coregen.cgc'}")
    return names


def images(board):
    return {f"verilog/sd2snes_{name}/fpga_{name}.{EXT[board]}" for name in cores(board)}


def check_equal(actual, expected, label):
    if actual != expected:
        raise RuntimeError(f"{label}: missing {sorted(expected - actual)}; "
                           f"unexpected {sorted(actual - expected)}")


def verify_source_contract():
    """A source format/ABI change requires an explicit packaging audit too."""
    makefile = (ROOT / "src/Makefile").read_text()
    for board, (magic, header_size, suffix) in FIRMWARE_SPEC.items():
        config = (ROOT / "src" / f"config-{board}").read_text()
        for name, value in (("CONFIG_FW_FILE", FIRMWARE[board]),
                            ("CONFIG_FW_MAGIC", magic.decode("ascii"))):
            if re.findall(rf"^{name}\s*=\s*(\S+)\s*$", config, re.MULTILINE) != [value]:
                raise RuntimeError(f"Unaudited {board} {name} contract")
        sizes = re.findall(r"^CONFIG_FW_HEADERSIZE\s*=\s*(0x[0-9a-fA-F]+|[0-9]+)\s*$",
                           config, re.MULTILINE)
        if len(sizes) != 1 or int(sizes[0], 0) != header_size:
            raise RuntimeError(f"Unaudited {board} firmware header size")
        if re.findall(rf"^OVL_SFX_{re.escape(board)}\s*=\s*(\S+)\s*$",
                      makefile, re.MULTILINE) != [suffix]:
            raise RuntimeError(f"Unaudited {board} overlay suffix")
    ovl_header = (ROOT / "src/ovl.h").read_text()
    if re.findall(r"^#define OVL_COUNT\s+([0-9]+)\s*$", ovl_header, re.MULTILINE) != ["2"]:
        raise RuntimeError("Unaudited number of card overlays")
    for number, entries in ((1, 18), (2, 10)):
        source = (ROOT / "src/ovl" / f"ovl_hdr{number}.c").read_text()
        if re.findall(r"uint32_t e\[([0-9]+)\]", source) != [str(entries)]:
            raise RuntimeError(f"Unaudited overlay {number} entry count")
    gbc_header = (ROOT / "src/gbc.h").read_text()
    if (re.findall(r"^#define GBC_BOOT_SIZE\s+([0-9]+)\s*$", gbc_header, re.MULTILINE) != [str(GBC_BOOT_SIZE)]
            or re.findall(r"^#define GBC_BOOT_CRC_SAMEBOY\s+(0x[0-9A-Fa-f]+)\s*$",
                          gbc_header, re.MULTILINE) != ["0x8113B4D8"]):
        raise RuntimeError("Unaudited SameBoy boot size/CRC contract")


def package_files(board, *, root=None, image_paths=None):
    """Exact card paths and build inputs used by the board-specific release recipe."""
    root = ROOT if root is None else root
    obj = root / "src" / f"obj-{board}"
    fpga_board = "mk2" if board == "mk2" else "mk3"
    sources = {}

    def add(path, name=None):
        card_path = "sd2snes/" + (name or path.name)
        if card_path in sources:
            raise RuntimeError(f"Duplicate package destination: {card_path}")
        if not path.is_file() or path.is_symlink() or not path.stat().st_size:
            raise RuntimeError(f"Missing, empty or linked package input: {path}")
        sources[card_path] = path

    for name in sorted(images(fpga_board) if image_paths is None else image_paths):
        add(root / name)
    add(obj / FIRMWARE[board])
    menu = "menu.bin" if board == "mk2" else "m3nu.bin"
    for name in (menu, "igmenu.bin", "onboarding.bin"):
        add(root / "snes" / name)
    for name in CARD_MODULES:
        add(obj / name)
    suffix = FIRMWARE_SPEC[board][2]
    for number in (1, 2):
        add(obj / f"ovl{number}.{suffix}")
    if board == "mk2":
        add(obj / "bootscr.img")
        add(root / "misc" / "atari_snes.bin")
    else:
        for name in MK3_PLAYERS:
            add(root / "misc" / name)
    for name in MENU_ASSETS:
        add(root / "misc" / name)
    add(root / "misc/music/CREDITS.txt", "music/CREDITS.txt")
    for lang in ("ja", "zh"):
        for extension in ("bin", "fnt"):
            add(root / "snes" / f"lang_{lang}.{extension}", f"lang/{lang}.{extension}")
    for directory, pattern, prefix in (("bin", "*.bin", ""), ("", "README*", ""),
                                        ("snes/fonts", "*.txt", "lang/"),
                                        ("misc/music", "*.spc", "music/"),
                                        ("savestate", "savestate*.yml", "")):
        paths = sorted((root / directory).glob(pattern))
        if not paths:
            raise RuntimeError(f"Missing release input group: {directory}/{pattern}")
        for path in paths:
            add(path, prefix + path.name)
    total = sum(path.stat().st_size for path in sources.values())
    if total > MAX_PACKAGE_BYTES:
        raise RuntimeError("Package input total exceeds the 256 MiB inspection bound")
    return {name: path.read_bytes() for name, path in sources.items()}


def verify_build_pair(board, files, fw_header, boot_header):
    """Runner-only checks of the firmware/overlay format and the MkII boot contract."""
    magic, header_size, suffix = FIRMWARE_SPEC[board]
    firmware = files[f"sd2snes/{FIRMWARE[board]}"]
    if (len(firmware) <= header_size or firmware[:4] != magic
            or len(fw_header) != header_size or firmware[:header_size] != fw_header):
        raise RuntimeError("Packaged firmware does not match its board and generated fw.hdr")
    body_size, build_crc = struct.unpack_from("<II", firmware, 8)
    if body_size != len(firmware) - header_size or zlib.crc32(firmware[header_size:]) != build_crc:
        raise RuntimeError("Packaged firmware size or payload CRC mismatch")
    for number, entries in ((1, 18), (2, 10)):
        image = files[f"sd2snes/ovl{number}.{suffix}"]
        if len(image) < 16 + 4 * entries or image[:4] != f"SOV{number}".encode("ascii"):
            raise RuntimeError(f"Overlay {number} has the wrong header or missing entry table")
        build, size, crc = struct.unpack_from("<III", image, 4)
        checked = image[:12] + b"\0\0\0\0" + image[16:]
        if build != build_crc or size != len(image) or zlib.crc32(checked) != crc:
            raise RuntimeError(f"Overlay {number} is stale, truncated or corrupt")
    if board == "mk2":
        # src/Makefile emits these two declarations for the same MCU compilation;
        # src/memory.c requires both values before decoding the card boot program.
        match = re.fullmatch(rb"#define BOOTSCR_SIZE ([0-9]+)U\n"
                             rb"#define BOOTSCR_CRC 0x([0-9a-f]{8})UL\n", boot_header)
        boot = files["sd2snes/bootscr.img"]
        if (match is None or len(boot) != int(match[1])
                or zlib.crc32(boot) != int(match[2], 16)):
            raise RuntimeError("MkII boot screen differs from the MCU's generated size/CRC")
        player = files["sd2snes/atari_snes.bin"]
        if len(player) != 32768:
            raise RuntimeError("MkII Atari player must be a complete 32 KiB LoROM image")
        complement, checksum = struct.unpack_from("<HH", player, 0x7fdc)
        if complement ^ checksum != 0xffff or sum(player) & 0xffff != checksum:
            raise RuntimeError("MkII Atari player checksum mismatch")


def verify_archive(archive, board, expected, fw_header, boot_header):
    """Reject ambiguous ZIP paths and compare every delivered byte with this build."""
    infos = archive.infolist()
    if len(infos) > 4096 or len({entry.filename for entry in infos}) != len(infos):
        raise RuntimeError("Release ZIP has too many entries or duplicate paths")
    directories = {name[:index + 1] for name in expected
                   for index, char in enumerate(name) if char == "/"}
    entries = {}
    total = 0
    for entry in infos:
        name = entry.filename
        file_type = stat.S_IFMT(entry.external_attr >> 16)
        if entry.flag_bits & 1 or file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise RuntimeError(f"Encrypted or non-regular ZIP entry: {name}")
        if entry.is_dir():
            if name not in directories or entry.file_size or file_type not in (0, stat.S_IFDIR):
                raise RuntimeError(f"Unexpected ZIP directory: {name}")
            continue
        if file_type == stat.S_IFDIR or name not in expected:
            raise RuntimeError(f"Unexpected package path: {name}")
        if entry.file_size != len(expected[name]) or not entry.file_size:
            raise RuntimeError(f"Wrong package size: {name}")
        total += entry.file_size
        if total > MAX_PACKAGE_BYTES:
            raise RuntimeError("Release ZIP exceeds the 256 MiB inspection bound")
        entries[name] = archive.read(entry)  # zipfile checks each member's CRC too.
        if entries[name] != expected[name]:
            raise RuntimeError(f"Package bytes differ from their matching build input: {name}")
    check_equal(set(entries), set(expected), f"{board} complete package")
    verify_build_pair(board, entries, fw_header, boot_header)


def verify_cgb_boot(files, acceptance):
    """Only the accepted freely licensed SameBoy asset can enter a release package."""
    boot = files["sd2snes/cgb_boot.bin"]
    license_text = files["sd2snes/cgb_boot.LICENSE"]
    if len(boot) != GBC_BOOT_SIZE or zlib.crc32(boot) != GBC_BOOT_CRC:
        raise RuntimeError("Packaged SameBoy boot violates the unchanged 2304-byte/8113B4D8 contract")
    if (not isinstance(acceptance, dict) or set(acceptance) != {"schema", "status", "boot", "license", "evidence"}
            or acceptance["schema"] != 1 or acceptance["status"] != "accepted-for-packaging"):
        raise RuntimeError("SameBoy packaging requires an explicitly accepted provenance manifest")
    if acceptance["boot"] != {"bytes": GBC_BOOT_SIZE, "crc32": "8113b4d8",
                               "sha256": hashlib.sha256(boot).hexdigest()}:
        raise RuntimeError("Packaged SameBoy boot differs from the accepted exact bytes")
    if (not license_text or acceptance["license"] != {"bytes": len(license_text),
                                                       "sha256": hashlib.sha256(license_text).hexdigest()}):
        raise RuntimeError("Packaged SameBoy license differs from the accepted exact text")
    evidence = acceptance["evidence"]
    if (not isinstance(evidence, dict) or set(evidence) != {"repository", "source_commit", "run_id", "artifact_id",
                                                         "artifact_sha256", "root_receipt_sha256"}
            or evidence["repository"] != "LIJI32/SameBoy"
            or any(not isinstance(evidence[key], str) or not re.fullmatch(pattern, evidence[key])
                   for key, pattern in (("source_commit", r"[0-9a-f]{40}"), ("run_id", r"[1-9][0-9]*"),
                                        ("artifact_id", r"[1-9][0-9]*"), ("artifact_sha256", r"[0-9a-f]{64}"),
                                        ("root_receipt_sha256", r"[0-9a-f]{64}")))):
        raise RuntimeError("Incomplete accepted SameBoy provenance binding")


def accepted_cgb_boot():
    # This fixture is intentionally absent until hosted collection has independent
    # root acceptance. A collection-only result never creates or substitutes it.
    relative = ".github/fixtures/accepted-cgb-boot.json"
    path = ROOT / relative
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("SameBoy boot provenance has not been accepted for packaging")
    raw = path.read_bytes()
    # This checkout is runner-owned while the software container runs as root.
    # Trust only this canonical repository for this read, without global config.
    committed = subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT}", "show", "HEAD:" + relative], cwd=ROOT)
    if raw != committed:
        raise RuntimeError("SameBoy acceptance manifest must match the reviewed commit")
    return json.loads(raw)


def inventory_self_test():
    """Exercise the real inventory reader on complete synthetic board trees only."""
    # Independent expected paths make omissions from production constants visible.
    fpga_names = {
        "mk2": "atari base basex bootleg col20 cx4 dsp dspx gsu gsu3 obc1 sa1 sdd1 sgb sgb_msu spc7110 st0011 st0018 test xc mini".split(),
        "mk3": "a26 base bootleg col20 cx4 dsp gbc gsu gsu3 nes nes_k nes_mmc3 nes_mmc5 obc1 sa1 sdd1 sgb sms spc7110 st0011 st0018 test xc mini".split(),
    }
    if {board: len(names) for board, names in fpga_names.items()} != {"mk2": 21, "mk3": 24}:
        raise RuntimeError("Incomplete synthetic FPGA inventory")
    counts = {"positive": 0, "negative": 0}
    for board, firmware, suffix, menu in (("mk2", "firmware.img", "img", "menu.bin"),
                                         ("mk3", "firmware.im3", "im3", "m3nu.bin"),
                                         ("mk3-stm32", "firmware.stm", "stm", "m3nu.bin")):
        family = "mk2" if board == "mk2" else "mk3"
        extension = "bit" if family == "mk2" else "bi3"
        image_paths = [f"verilog/sd2snes_{core}/fpga_{core}.{extension}"
                       for core in fpga_names[family]]
        mapping = {path: "sd2snes/" + Path(path).name for path in image_paths}
        obj = f"src/obj-{board}/"
        for name in (firmware, "nsfplay.bin", "memtest.bin", "pcmplay.bin", "rtc7110.bin",
                     "fileops.bin", "rmdir.bin", "xc_soc.bin", f"ovl1.{suffix}", f"ovl2.{suffix}"):
            mapping[obj + name] = "sd2snes/" + name
        for name in (menu, "igmenu.bin", "onboarding.bin"):
            mapping["snes/" + name] = "sd2snes/" + name
        for name in ("classic.thm", "menu.spc", "sfx_cursor.pcm", "sfx_confirm.pcm",
                     "sfx_back.pcm", "sfx_error.pcm", "welcome.fmv", "welcome.pcm"):
            mapping["misc/" + name] = "sd2snes/" + name
        if family == "mk2":
            mapping[obj + "bootscr.img"] = "sd2snes/bootscr.img"
            mapping["misc/atari_snes.bin"] = "sd2snes/atari_snes.bin"
        else:
            for name in ("nes_snes.bin", "sms_snes.bin", "gbc_snes.bin", "a26_snes.bin", "cgb_boot.bin", "cgb_boot.LICENSE"):
                mapping["misc/" + name] = "sd2snes/" + name
        for language in ("ja", "zh"):
            for extension in ("bin", "fnt"):
                mapping[f"snes/lang_{language}.{extension}"] = f"sd2snes/lang/{language}.{extension}"
        mapping.update({"bin/bsxpage.bin": "sd2snes/bsxpage.bin", "README.md": "sd2snes/README.md",
                        "snes/fonts/LICENSE.txt": "sd2snes/lang/LICENSE.txt",
                        "misc/music/28.spc": "sd2snes/music/28.spc",
                        "misc/music/CREDITS.txt": "sd2snes/music/CREDITS.txt",
                        "savestate/savestate.yml": "sd2snes/savestate.yml"})
        with tempfile.TemporaryDirectory(prefix="package-inventory-") as directory:
            scratch = Path(directory)
            expected = {}
            for source, card in mapping.items():
                path = scratch / source
                path.parent.mkdir(parents=True, exist_ok=True)
                body = (board + ":" + source + "\n").encode("ascii")
                path.write_bytes(body)
                expected[card] = body
            actual = package_files(board, root=scratch, image_paths=image_paths)
            if actual != expected:
                raise RuntimeError(f"Synthetic {board} full inventory differs: {set(actual) ^ set(expected)}")
            counts["positive"] += 1
            print(f"package-inventory-control: {board} exact {len(expected)}-file inventory: accepted")

            def rejected(label):
                try:
                    package_files(board, root=scratch, image_paths=image_paths)
                except RuntimeError:
                    counts["negative"] += 1
                else:
                    raise RuntimeError(f"Inventory negative accepted: {board} {label}")
                print(f"package-inventory-control: {board} {label}: rejected")

            for source, card in mapping.items():
                path = scratch / source
                path.unlink()
                try:
                    rejected("missing " + source)
                finally:
                    path.write_bytes(expected[card])
            for source in (obj + firmware, "misc/music/CREDITS.txt", "snes/lang_ja.bin"):
                path = scratch / source
                path.write_bytes(b"")
                try:
                    rejected("empty " + source)
                finally:
                    path.write_bytes(expected[mapping[source]])
            link_path = scratch / "misc/music/CREDITS.txt"
            link_path.unlink()
            try:
                link_path.symlink_to(scratch / "README.md")
                rejected("linked music credits")
            finally:
                link_path.unlink(missing_ok=True)
                link_path.write_bytes(expected["sd2snes/music/CREDITS.txt"])
            (scratch / "bin" / menu).write_bytes(b"duplicate destination")
            rejected("duplicate menu destination from bin group")
            (scratch / "bin" / menu).unlink()
            overlay = scratch / obj / f"ovl1.{suffix}"
            foreign_suffix = "im3" if suffix != "im3" else "img"
            foreign_overlay = scratch / obj / f"ovl1.{foreign_suffix}"
            overlay.rename(foreign_overlay)
            rejected("foreign board overlay suffix cannot replace required suffix")
    if counts != {"positive": 3, "negative": 194}:
        raise RuntimeError(f"Incomplete inventory controls: {counts}")
    print("Package inventory controls: " + json.dumps(counts, sort_keys=True))


def self_test():
    """Synthetic package-format controls; run on GitHub, never build FPGA inputs."""
    counts = {"positive": 0, "negative": 0}

    def check(label, board, files, fw_header, boot_header, expected=None,
              reject=False, duplicate=None, special=None):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
            if duplicate is not None:
                # zipfile warns about duplicates; retain that warning in the hosted log.
                archive.writestr(duplicate, files[duplicate])
            if special is not None:
                info = zipfile.ZipInfo(special)
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, b"target")
        stream.seek(0)
        try:
            with zipfile.ZipFile(stream) as archive:
                verify_archive(archive, board, files if expected is None else expected,
                               fw_header, boot_header)
        except RuntimeError as error:
            if not reject:
                raise RuntimeError(f"Positive control failed: {label}") from error
            counts["negative"] += 1
        else:
            if reject:
                raise RuntimeError(f"Negative control was accepted: {label}")
            counts["positive"] += 1
        print(f"package-control: {label}: {'rejected' if reject else 'accepted'}")

    for board, (magic, header_size, suffix) in FIRMWARE_SPEC.items():
        body = b"synthetic MCU payload for " + board.encode("ascii")
        header = bytearray(header_size)
        header[:4] = magic
        struct.pack_into("<II", header, 8, len(body), zlib.crc32(body))
        header = bytes(header)
        firmware_name = f"sd2snes/{FIRMWARE[board]}"
        files = {firmware_name: header + body,
                 f"sd2snes/{'menu.bin' if board == 'mk2' else 'm3nu.bin'}": b"menu",
                 "sd2snes/igmenu.bin": b"in-game menu",
                 "sd2snes/onboarding.bin": b"tour"}
        for name in CARD_MODULES:
            files["sd2snes/" + name] = (board + name).encode("ascii")
        for number, count in ((1, 18), (2, 10)):
            overlay = bytearray(16 + count * 4)
            overlay[:4] = f"SOV{number}".encode("ascii")
            struct.pack_into("<II", overlay, 4, zlib.crc32(body), len(overlay))
            struct.pack_into("<I", overlay, 12, zlib.crc32(overlay))
            files[f"sd2snes/ovl{number}.{suffix}"] = bytes(overlay)
        boot_header = b""
        if board == "mk2":
            boot = b"synthetic compressed boot bytes"
            files["sd2snes/bootscr.img"] = boot
            boot_header = (f"#define BOOTSCR_SIZE {len(boot)}U\n"
                           f"#define BOOTSCR_CRC 0x{zlib.crc32(boot):08x}UL\n").encode("ascii")
            player = bytearray(32768)
            player[0x7fdc:0x7fe0] = b"\xff\xff\0\0"
            checksum = sum(player) & 0xffff
            struct.pack_into("<HH", player, 0x7fdc, checksum ^ 0xffff, checksum)
            files["sd2snes/atari_snes.bin"] = bytes(player)
        check(board + " complete matching set", board, files, header, boot_header)
        for missing in files:
            changed = dict(files)
            del changed[missing]
            check(board + " missing " + missing, board, changed, header, boot_header,
                  expected=files, reject=True)
        changed = dict(files)
        changed[firmware_name] = files[firmware_name][:-1] + b"!"
        check(board + " substituted package byte", board, changed, header, boot_header,
              expected=files, reject=True)
        check(board + " bad firmware payload CRC", board, changed, header, boot_header,
              reject=True)
        check(board + " stale generated firmware header", board, files,
              header[:12] + b"\0\0\0\0" + header[16:], boot_header, reject=True)
        for number in (1, 2):
            name = f"sd2snes/ovl{number}.{suffix}"
            for offset, label in ((0, "wrong magic"), (4, "wrong firmware build"),
                                  (8, "wrong length"), (12, "wrong CRC"), (16, "corrupt entry")):
                changed = dict(files)
                data = bytearray(files[name])
                data[offset] ^= 1
                if offset == 4:
                    # A valid overlay CRC must not hide a different firmware build.
                    struct.pack_into("<I", data, 12, 0)
                    struct.pack_into("<I", data, 12, zlib.crc32(data))
                changed[name] = bytes(data)
                check(board + f" overlay {number} " + label, board, changed,
                      header, boot_header, reject=True)
        for extra in ("elsewhere/" + FIRMWARE[board], "sd2snes/../bad", "/sd2snes/extra",
                      "sd2snes/ovl1.wrong", "sd2snes\\extra"):
            changed = dict(files, **{extra: b"foreign bytes"})
            check(board + " unexpected path " + extra, board, changed, header, boot_header,
                  expected=files, reject=True)
        check(board + " duplicate path", board, files, header, boot_header,
              duplicate=firmware_name, reject=True)
        check(board + " linked entry", board, files, header, boot_header,
              special="sd2snes/link", reject=True)
        if board == "mk2":
            check("mk2 stale boot header", board, files, header,
                  boot_header.replace(b"BOOTSCR_SIZE ", b"BOOTSCR_SIZE 9"), reject=True)
            for name in ("sd2snes/bootscr.img", "sd2snes/atari_snes.bin"):
                changed = dict(files)
                changed[name] = bytes([files[name][0] ^ 1]) + files[name][1:]
                check("mk2 corrupt " + name, board, changed, header, boot_header, reject=True)
    for label, boot in (("wrong boot size", b"wrong"), ("wrong boot CRC", bytes(GBC_BOOT_SIZE))):
        try:
            verify_cgb_boot({"sd2snes/cgb_boot.bin": boot, "sd2snes/cgb_boot.LICENSE": b"synthetic license"}, {})
        except RuntimeError:
            counts["negative"] += 1
        else:
            raise RuntimeError(f"Negative SameBoy control was accepted: {label}")
        print(f"package-control: {label}: rejected")
    if counts != {"positive": 3, "negative": 106}:
        raise RuntimeError(f"Incomplete package control coverage: {counts}")
    print("Package format controls: " + json.dumps(counts, sort_keys=True))


def main():
    mode = sys.argv[1]
    if mode == "self-test":
        if len(sys.argv) != 2:
            raise RuntimeError("self-test takes no arguments")
        verify_source_contract()
        self_test()
        inventory_self_test()
        return
    if mode == "matrix":
        matrix = [{"board": board, "core": name, "extension": EXT[board]}
                  for board in EXT for name in cores(board)]
        target = os.environ.get("RELEASE_TARGET", "all")
        package_boards = {
            "all": list(FIRMWARE), "mk2": ["mk2"], "mk3": ["mk3"],
            "mk3-stm32": ["mk3-stm32"], "mk3-both": ["mk3", "mk3-stm32"],
        }
        if target not in package_boards:
            raise RuntimeError(f"Unknown release target: {target}")
        selected_fpga = {"mk2" if board == "mk2" else "mk3"
                         for board in package_boards[target]}
        matrix = [item for item in matrix if item["board"] in selected_fpga]
        selection = os.environ.get("FPGA_CORES", "").strip()
        if selection:
            requested = set(selection.split(","))
            known = {f"{item['board']}:{item['core']}" for item in matrix}
            if requested - known:
                raise RuntimeError(f"Unknown FPGA targets: {sorted(requested - known)}")
            matrix = [item for item in matrix if f"{item['board']}:{item['core']}" in requested]
        seeds = os.environ.get("PLACEMENT_SEEDS", "").strip()
        if seeds:
            values = seeds.split(",")
            if (any(not re.fullmatch(r"[1-9][0-9]?|100", seed) for seed in values)
                    or len(values) != len(set(values)) or any(item["board"] != "mk2" for item in matrix)):
                raise RuntimeError("Placement seeds must be distinct values 1..100 for MkII targets only")
            matrix = [dict(item, seed=seed) for item in matrix for seed in values]
        if len(matrix) > 256:
            raise RuntimeError("FPGA matrix exceeds GitHub's 256-job limit; select fewer cores or seeds")
        print("matrix=" + json.dumps({"include": matrix}, separators=(",", ":")))
        print("boards=" + json.dumps(sorted({item["board"] for item in matrix})))
        packages = [{"board": board, "fpga": "mk2" if board == "mk2" else "mk3"}
                    for board in package_boards[target]]
        print("packages=" + json.dumps({"include": packages}, separators=(",", ":")))
        return
    board = sys.argv[2]
    fpga_board = "mk2" if board == "mk2" else "mk3"
    expected = images(fpga_board)
    if mode == "artifact":
        actual = {str(p.relative_to(ROOT)).replace("\\", "/")
                  for p in (ROOT / "verilog").glob("*/fpga_*") if p.is_file()
                  and p.suffix in {".bit", ".bi3"}}
        check_equal(actual, expected, f"{board} FPGA artifact")
        for filename in expected:
            if (ROOT / filename).stat().st_size == 0:
                raise RuntimeError(f"Empty FPGA image: {filename}")
    elif mode == "package":
        if board not in FIRMWARE or len(sys.argv) != 4:
            raise RuntimeError("Expected one board and exactly one release ZIP")
        verify_source_contract()
        files = package_files(board)
        obj = ROOT / "src" / f"obj-{board}"
        fw_header = (obj / "fw.hdr").read_bytes()
        boot_header = (obj / "bootzx0.h").read_bytes() if board == "mk2" else b""
        with zipfile.ZipFile(sys.argv[3]) as archive:
            verify_archive(archive, board, files, fw_header, boot_header)
        if board != "mk2":
            verify_cgb_boot(files, accepted_cgb_boot())
    else:
        raise RuntimeError(f"Unknown check: {mode}")
    print(f"{board}: verified {len(expected)} FPGA images ({mode})")


if __name__ == "__main__":
    main()
