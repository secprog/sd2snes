#!/usr/bin/env python3
"""Reconstruct every linked onboarding picture and compare original hashes."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SNES = ROOT / "snes"


def main():
    layout = json.loads((SNES / "onboarding/onb_demo_layout.json").read_text())
    assert layout["format_version"] == 1
    assert layout["chunk_size"] == 1024 and layout["chunks_per_picture"] == 7
    source = (SNES / "Makefile").read_text().replace("\\\n", " ")
    objects = re.search(r"^ONB_O65\s*=\s*(.*)$", source, re.MULTILINE).group(1).split()
    bases = {}
    for line in (SNES / "onb_link.log").read_text().splitlines():
        match = re.fullmatch(r"\s*([0-9a-fA-F]{6})\s+object_(\d+)_code\s*", line)
        if match:
            bases[int(match[2])] = int(match[1], 16)
    symbols = {}
    for index, name in enumerate(objects, 1):
        if not Path(name).name.startswith("packed_demo_"):
            continue
        for line in (SNES / (name + ".log")).read_text().splitlines():
            if line.startswith("Externs"):
                break
            match = re.fullmatch(r"\s*([0-9a-fA-F]+)\s+(\w+)\s*", line)
            if match:
                offset = int(match[1], 16)
                symbols[match[2]] = offset if offset > 0xFFFF else bases[index] + offset
    image = (SNES / "onboarding.bin").read_bytes()

    def read(address, size):
        offset = address - 0xC00000
        assert 0 <= offset and offset + size <= len(image), f"bad demo address ${address:06X}"
        return image[offset:offset + size]

    def pointer(address):
        return int.from_bytes(read(address, 3), "little")

    table = symbols["onb_demo_tbl"]
    pictures = layout["pictures"]
    assert len(pictures) == layout["picture_count"]
    for index, picture in enumerate(pictures):
        descriptor = pointer(table + index * 6)
        palette = pointer(table + index * 6 + 3)
        assert descriptor == symbols[picture["label"]], f"wrong demo descriptor: {picture['id']}"
        assert palette == symbols[picture["palette_label"]], f"wrong demo palette: {picture['id']}"
        tiles = b"".join(read(pointer(descriptor + chunk * 3), 1024) for chunk in range(7))
        palette_oam = read(palette, 256)
        assert len(tiles) == layout["picture_bytes"] == 7168
        assert hashlib.sha256(tiles).hexdigest() == picture["tile_sha256"], picture["id"]
        assert hashlib.sha256(palette_oam).hexdigest() == picture["palette_sha256"], picture["id"]
    print(f"onboarding demos: {len(pictures)} linked pictures and palette/OAM records "
          "reconstructed byte-for-byte; 7 unchanged 1024-byte DMA chunks per picture")


if __name__ == "__main__":
    main()
