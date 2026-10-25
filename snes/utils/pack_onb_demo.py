#!/usr/bin/env python3
"""Losslessly pack the committed onboarding demo bytes; no PNG/Pillow step.

The six-byte picture index keeps its palette/OAM pointer. Its first pointer
now addresses seven long pointers to shared 1,024-byte character chunks.
Generated source and occupancy metadata are written only after reconstructing
every original character payload and palette/OAM record byte for byte.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

CHUNK_SIZE = 1024
CHUNKS_PER_PICTURE = 7
PICTURE_BYTES = CHUNK_SIZE * CHUNKS_PER_PICTURE
PALETTE_OAM_BYTES = 256
BANK_CAPACITY = 8 * (PICTURE_BYTES + PALETTE_OAM_BYTES)
BANKS = tuple("$%02x" % bank for bank in range(0xC2, 0xCC))
SUFFIXES = "abcdefghij"
LABEL = re.compile(r"^(onb_demo_\w+):$")
TABLE_ROW = re.compile(
    r"^\.word !([\w]+)\s*:\s*\.byt \^([\w]+)\s*:\s*"
    r"\.word !([\w]+)\s*:\s*\.byt \^([\w]+)$")


def read_demos(source_dir):
    """Read original table order and strict literal byte payloads, without writes."""
    payloads, index = {}, []
    for suffix, bank in zip(SUFFIXES, BANKS):
        path = source_dir / ("onb_demo_%s.a65" % suffix)
        current = None
        for line_number, original in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = original.split(";", 1)[0].strip()
            if not line:
                continue
            if line.startswith(".link page "):
                if line != ".link page " + bank:
                    raise ValueError("%s:%d: unexpected source bank" % (path, line_number))
                continue
            label = LABEL.fullmatch(line)
            if label:
                current = label.group(1)
                if current in payloads:
                    raise ValueError("duplicate demo label: " + current)
                payloads[current] = bytearray()
                continue
            row = TABLE_ROW.fullmatch(line)
            if row and current == "onb_demo_tbl":
                tiles, tiles_bank, palette, palette_bank = row.groups()
                if tiles != tiles_bank or palette != palette_bank or palette != tiles + "_pal":
                    raise ValueError("%s:%d: inconsistent picture pointers" % (path, line_number))
                index.append((tiles, palette))
                continue
            if line.startswith(".byt ") and current and current != "onb_demo_tbl":
                for token in line[5:].split(","):
                    token = token.strip()
                    value = int(token[1:], 16) if token.startswith("$") else int(token, 0)
                    if not 0 <= value <= 255:
                        raise ValueError("%s:%d: byte out of range" % (path, line_number))
                    payloads[current].append(value)
                continue
            raise ValueError("%s:%d: unsupported demo source statement %r"
                             % (path, line_number, line))
    if not index or len({label for label, _ in index}) != len(index):
        raise ValueError("empty or duplicate picture index")
    expected = {"onb_demo_tbl"} | {label for pair in index for label in pair}
    if set(payloads) != expected:
        raise ValueError("picture index and source payload labels differ")
    pictures = []
    for label, palette_label in index:
        tiles, palette = bytes(payloads[label]), bytes(payloads[palette_label])
        if len(tiles) != PICTURE_BYTES or len(palette) != PALETTE_OAM_BYTES:
            raise ValueError("%s: expected %d character / %d palette+OAM bytes, got %d / %d"
                             % (label, PICTURE_BYTES, PALETTE_OAM_BYTES, len(tiles), len(palette)))
        pictures.append({"label": label, "palette_label": palette_label,
                         "tiles": tiles, "palette": palette})
    return pictures


def byte_lines(data):
    return ["  .byt " + ", ".join("$%02x" % value for value in data[start:start + 16])
            for start in range(0, len(data), 16)]


def pack_demos(pictures):
    chunks, chunk_labels, lists, palettes = {}, {}, {}, {}
    for picture in pictures:
        references = []
        for start in range(0, PICTURE_BYTES, CHUNK_SIZE):
            data = picture["tiles"][start:start + CHUNK_SIZE]
            if data not in chunk_labels:
                label = "onb_packed_chunk_%03d" % len(chunks)
                chunk_labels[data] = label
                chunks[label] = data
            references.append(chunk_labels[data])
        lists[picture["label"]] = references
        palettes[picture["palette_label"]] = picture["palette"]

    # The index stays in C2. All other complete objects go into the least-used
    # eligible bank, keeping spare text space across the existing picture banks.
    used = dict.fromkeys(BANKS, 0)
    used["$c2"] = 6 * len(pictures)
    objects = [(label, "chunk", len(data)) for label, data in chunks.items()]
    objects += [(label, "palette", len(data)) for label, data in palettes.items()]
    objects += [(label, "list", CHUNKS_PER_PICTURE * 3) for label in lists]
    placement = {}
    for label, kind, size in sorted(objects, key=lambda item: (-item[2], item[0])):
        available = [bank for bank in BANKS if used[bank] + size <= BANK_CAPACITY]
        if not available:
            raise ValueError("no picture bank has room for %s (%d bytes)" % (label, size))
        bank = min(available, key=lambda candidate: (used[candidate], BANKS.index(candidate)))
        placement[label] = (bank, kind, size)
        used[bank] += size

    # Verify reconstruction before any generated file is written. Chunk/list
    # placement changes neither character bytes nor palettes/OAM in either slot.
    for picture in pictures:
        references = lists[picture["label"]]
        if len(references) != CHUNKS_PER_PICTURE:
            raise ValueError("wrong chunk-list length: " + picture["label"])
        if b"".join(chunks[label] for label in references) != picture["tiles"]:
            raise ValueError("character reconstruction differs: " + picture["label"])
        if palettes[picture["palette_label"]] != picture["palette"]:
            raise ValueError("palette/OAM reconstruction differs: " + picture["label"])
    if any(total > BANK_CAPACITY for total in used.values()):
        raise ValueError("packed picture bank exceeds the reserved capacity")

    output = {bank: ["; GENERATED by utils/pack_onb_demo.py from committed onb_demo_*.a65.",
                     "; Shared 1024-byte character chunks; original palette/OAM bytes.",
                     ".link page " + bank, ""] for bank in BANKS}
    output["$c2"] += ["; Per picture: seven-chunk list long pointer, palette/OAM long pointer.",
                       "onb_demo_tbl:"]
    for picture in pictures:
        label, palette_label = picture["label"], picture["palette_label"]
        output["$c2"].append("  .word !%s : .byt ^%s : .word !%s : .byt ^%s"
                             % (label, label, palette_label, palette_label))
    output["$c2"].append("")
    for label, (bank, kind, _) in placement.items():
        output[bank].append(label + ":")
        if kind == "list":
            output[bank] += ["  .word !%s : .byt ^%s" % (chunk, chunk) for chunk in lists[label]]
        else:
            output[bank] += byte_lines(chunks[label] if kind == "chunk" else palettes[label])
        output[bank].append("")

    digest = lambda data: hashlib.sha256(data).hexdigest()
    metadata = {"format_version": 1, "chunk_size": CHUNK_SIZE,
                "chunks_per_picture": CHUNKS_PER_PICTURE, "picture_bytes": PICTURE_BYTES,
                "palette_oam_bytes": PALETTE_OAM_BYTES, "picture_count": len(pictures),
                "unique_chunk_count": len(chunks), "bank_capacity": BANK_CAPACITY,
                "bank_bytes": used,
                "pictures": [{"id": index, "label": picture["label"],
                              "palette_label": picture["palette_label"],
                              "chunk_labels": lists[picture["label"]],
                              "tile_sha256": digest(picture["tiles"]),
                              "palette_sha256": digest(picture["palette"])}
                             for index, picture in enumerate(pictures)],
                "chunks": [{"label": label, "bank": placement[label][0], "sha256": digest(data)}
                           for label, data in chunks.items()]}
    return output, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "onboarding")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    pictures = read_demos(args.source_dir)
    output, metadata = pack_demos(pictures)
    destination = args.output_dir if args.output_dir is not None else args.source_dir
    destination.mkdir(parents=True, exist_ok=True)
    for suffix, bank in zip(SUFFIXES, BANKS):
        (destination / ("packed_demo_%s.a65" % suffix)).write_text(
            "\n".join(output[bank]) + "\n", encoding="utf-8")
    (destination / "onb_demo_layout.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    raw_bytes = len(pictures) * (PICTURE_BYTES + PALETTE_OAM_BYTES + 6)
    packed_bytes = sum(metadata["bank_bytes"].values())
    print("pack_onb_demo: verified %d pictures byte-for-byte; %d chunks -> %d unique; "
          "%d B -> %d B (%d B saved)"
          % (len(pictures), len(pictures) * CHUNKS_PER_PICTURE, metadata["unique_chunk_count"],
             raw_bytes, packed_bytes, raw_bytes - packed_bytes))
    print("pack_onb_demo: bytes per bank: " + ", ".join(
        "%s=%d" % item for item in metadata["bank_bytes"].items()))


if __name__ == "__main__":
    main()
