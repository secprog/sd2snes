#!/usr/bin/env python3
"""Verify linked menu translation pointers against the source text.

This checks ROM addresses after relocation, including shared string suffixes
and the auxiliary C3 tables. It runs on the hosted menu builder after linking.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
SNES = ROOT / "snes"
sys.path.insert(0, str(SNES / "utils"))
import build_const as codec

LOCALES = {0: "en", 1: "ptbr", 2: "es", 3: "de", 4: "fr",
           5: "it", 6: "ru", 7: "nl", 10: "ptpt"}


def main():
    image = (SNES / "m3nu.bin").read_bytes()
    symbols = {}
    for path in SNES.glob("*.map"):
        for line in path.read_text(errors="replace").splitlines():
            match = re.fullmatch(r"\s*([0-9a-fA-F]{6})\s+(\w+)\s*", line)
            if match:
                symbols[match[2]] = int(match[1], 16)

    def read(address, length):
        offset = address - 0xC00000
        if offset < 0 or offset + length > len(image):
            raise ValueError(f"translation points outside menu ROM: ${address:06X}")
        return image[offset:offset + length]

    def word(address):
        return int.from_bytes(read(address, 2), "little")

    main_lo, main_hi = symbols["strtab_lo"], symbols["strtab_hi"]
    aux_lo, aux_hi = symbols["fmtab_lo"], symbols["fmtab_hi"]
    assert read(symbols["strtab_nlang"], 1)[0] == 11, "saved locale IDs changed"
    assert read(symbols["fmtab_nlang"], 1)[0] == 11, "auxiliary locale IDs changed"
    for code, locale in (("ja", 8), ("zh", 9)):
        header = (SNES / f"lang_{code}.bin").read_bytes()[:5]
        assert header == b"SDL1" + bytes((locale,)), f"saved {code} locale ID changed"
    _, english = codec.parse_base(SNES / "const.a65")
    translations = {code: codec.load_dict(SNES / "utils" / f"lang_{code}.py")
                    for code in LOCALES.values() if code != "en"}
    labels = set().union(*(dictionary.keys() for dictionary in translations.values()))
    checked = 0
    auxiliary = 0
    for label in sorted(labels):
        if label.startswith("text_igm_"):
            continue  # separately linked in igmenu.bin, with its own width guards
        address = symbols[label]
        for locale, code in LOCALES.items():
            args = english[label]
            if code != "en" and translations[code].get(label):
                args = codec.encode_string(translations[code][label])
            expected = codec.args_to_bytes(args)
            if main_lo <= address < main_hi:
                bank = read(symbols["strpool_bank"] + locale, 1)[0]
                target = (bank << 16) | word(address + 2 * locale)
            elif aux_lo <= address < aux_hi:
                bank = read(symbols["fmpool_bank"] + locale, 1)[0]
                target = (bank << 16) | word(address + 2 * locale)
                auxiliary += 1
            else:
                target = address  # language-neutral string
            actual = read(target, len(expected))
            if actual != expected:
                raise ValueError(f"{label} [{code}, ID {locale}]: wrong linked text at ${target:06X}")
            checked += 1
    print(f"menu languages: {checked} linked strings verified across 9 Latin locales "
          f"({auxiliary} auxiliary strings); saved IDs 0..9 retained, pt-PT=10")


if __name__ == "__main__":
    main()
