#!/usr/bin/env python3
"""Prepare a hosted-only S-RTC late-address-bit feasibility proof.

Original Area46 paths from SNES_ADDR6/4 traverse three decoder LUT stages.
This new partition puts those bits after a kept permit for every other input.
No source state, clock, bus sample or cycle changes; native timing remains unproved.
"""

import difflib
import hashlib
import re
import subprocess
import sys
from pathlib import Path


EXPECTED_BLOB = "36ce9a5c17fc80b9ddda1d869f0d75a4fb52356c"
ORIGINAL = "assign srtc_enable = featurebits[FEAT_SRTC] & (!SNES_ADDR[22] && ((SNES_ADDR[15:0] & 16'hfffe) == 16'h2800));"
CANDIDATE = """(* KEEP="TRUE" *) wire srtc_other_permit;
assign srtc_other_permit = featurebits[FEAT_SRTC]
  & (!SNES_ADDR[22] && ({SNES_ADDR[15:7], SNES_ADDR[5], SNES_ADDR[3:1]} == 13'h0500));
basex_srtc_late_bits srtc_late_bits_decode(
  .prefix(srtc_other_permit), .bit4(SNES_ADDR[4]), .bit6(SNES_ADDR[6]),
  .hit(srtc_enable)
);"""
HELPERS = """// Measured failing address bits enter only this three-input final decoder.
(* LUT_MAP="yes" *)
module basex_srtc_late_bits(input prefix, bit4, bit6, output hit);
assign hit = prefix & ~bit4 & ~bit6;
endmodule
"""
WRAPPED = ("`ifdef MK2\n`ifdef BASE_EXT\n`ifndef BOOTLEG\n" + CANDIDATE
           + "\n`else\n" + ORIGINAL + "\n`endif\n`else\n" + ORIGINAL
           + "\n`endif\n`else\n" + ORIGINAL + "\n`endif")
HELPER_BLOCK = "`ifdef MK2\n`ifdef BASE_EXT\n`ifndef BOOTLEG\n" + HELPERS + "`endif\n`endif\n`endif\n"


def configured(text, initial_defines):
    """Select all conditionals in the pinned file, including BASE_LEAN."""
    defines = set(initial_defines)
    active, stack, output = True, [], []
    for line in text.splitlines(True):
        match = re.fullmatch(r"\s*`(ifdef|ifndef)\s+(\w+)\s*", line)
        if match:
            kind, macro = match.groups()
            if macro not in {"MK2", "BASE_EXT", "BASE_LEAN", "BOOTLEG"}:
                raise SystemExit(f"Unreviewed conditional macro: {macro}")
            condition = (macro in defines) == (kind == "ifdef")
            stack.append((active, condition))
            active = active and condition
        elif line.strip() == "`else":
            if not stack:
                raise SystemExit("Unmatched else")
            parent, condition = stack[-1]
            active = parent and not condition
        elif line.strip() == "`endif":
            if not stack:
                raise SystemExit("Unmatched endif")
            active, _ = stack.pop()
        elif re.fullmatch(r"\s*`define\s+BASE_LEAN\s*", line):
            if active:
                defines.add("BASE_LEAN")
        elif re.match(r"\s*`(?:elsif|undef|define)\b", line):
            raise SystemExit(f"Unreviewed preprocessor directive: {line.strip()}")
        elif active:
            output.append(line)
    if stack:
        raise SystemExit("Unbalanced preprocessor conditionals")
    return "".join(output)


def model(name, fragment, helpers="", witness=None):
    prefix = (f"module {name}(input [23:0] SNES_ADDR, input [15:0] featurebits,\n"
              "  output srtc_enable);\nparameter [3:0] FEAT_SRTC = 2;\n")
    if witness:
        original_output = ".hit(srtc_enable)"
        if fragment.count(original_output) != 1:
            raise SystemExit("Unexpected projected output for X control")
        fragment = ("wire srtc_check;\n" + fragment.replace(original_output, ".hit(srtc_check)", 1)
                    + f"\nassign srtc_enable = srtc_check & ({witness} | ~{witness});")
    return prefix + fragment + "\nendmodule\n" + helpers


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise SystemExit(f"Unexpected mutation boundary: {before}")
    return text.replace(before, after, 1)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-basex-srtc-decode-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete address source blob: {blob}")
    original = raw.decode("utf-8")
    for fragment in (ORIGINAL, "FEAT_SRTC = 2,",
                     "reg [23:0] SNES_ADDR; always @(posedge CLK) SNES_ADDR <= SNES_ADDR_early;",
                     "  input [15:0] featurebits,", "  output srtc_enable,"):
        if original.count(fragment) != 1:
            raise SystemExit(f"Unexpected source boundary: {fragment!r}")
    without_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", original, flags=re.S)
    if len(re.findall(r"\bassign\s+srtc_enable\s*=", without_comments)) != 1:
        raise SystemExit("Unexpected S-RTC enable driver")
    if re.search(r"\b(?:basex_srtc_|srtc_other_permit)\w*", without_comments):
        raise SystemExit("S-RTC helper name already exists")
    candidate = original.replace(ORIGINAL, WRAPPED, 1) + HELPER_BLOCK
    if hashlib.sha1(b"blob " + str(len(candidate.encode())).encode() + b"\0" + candidate.encode()).hexdigest() != "544beeb3ee6c6805197d332b08d10b8ee179f38a" or hashlib.sha256(candidate.encode()).hexdigest() != "4f373b8ae27e58bc97d79ad2a6c67b1072f3f247058196f5b16ff6fd9fa46f22":
        raise SystemExit("Complete candidate differs from independent source pin")
    recovered = candidate.removesuffix(HELPER_BLOCK).replace(WRAPPED, ORIGINAL, 1)
    if recovered != original:
        raise SystemExit("Candidate failed exact source recovery")
    for defines in (set(), {"MK3"}, {"MK3", "BASE_EXT"}, {"MK2"},
                    {"MK2", "BOOTLEG"}, {"MK2", "BASE_EXT", "BOOTLEG"},
                    {"BASE_EXT"}, {"BOOTLEG"}):
        if configured(original, defines) != configured(candidate, defines):
            raise SystemExit(f"Non-target source changed under {sorted(defines)}")
    mutations = {
        "bad-bit4": (CANDIDATE, replace_once(HELPERS, "~bit4", "bit4")),
        "bad-bit6": (CANDIDATE, replace_once(HELPERS, "~bit6", "bit6")),
        "bad-prefix-field": (replace_once(CANDIDATE, "SNES_ADDR[5]", "SNES_ADDR[7]"), HELPERS),
        "bad-prefix-value": (replace_once(CANDIDATE, "13'h0500", "13'h0501"), HELPERS),
        "bad-bank": (replace_once(CANDIDATE, "!SNES_ADDR[22]", "SNES_ADDR[22]"), HELPERS),
        "bad-feature": (replace_once(CANDIDATE, "featurebits[FEAT_SRTC]", "~featurebits[FEAT_SRTC]"), HELPERS),
        "bad-join": (CANDIDATE, replace_once(HELPERS, "prefix & ~bit4 & ~bit6", "prefix | ~bit4 | ~bit6")),
    }
    files = {
        "original-address.v": original,
        "candidate-address.v": candidate,
        "gold.v": model("gold", ORIGINAL),
        "gate.v": model("gate", CANDIDATE, HELPERS),
        **{name + ".v": model("gate", fragment, helpers)
           for name, (fragment, helpers) in mutations.items()},
        "bad-x-address.v": model("gate", CANDIDATE, HELPERS, "SNES_ADDR[23]"),
        "bad-x-feature.v": model("gate", CANDIDATE, HELPERS, "featurebits[15]"),
    }
    output.mkdir(parents=True, exist_ok=True)
    checksums = []
    for name, content in files.items():
        data = content.encode("utf-8")
        (output / name).write_bytes(data)
        checksums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    configurations = (
        ("none", []), ("mk3", ["MK3"]), ("mk3-ext", ["MK3", "BASE_EXT"]),
        ("mk2", ["MK2"]), ("mk2-bootleg", ["MK2", "BOOTLEG"]),
        ("mk2-ext-bootleg", ["MK2", "BASE_EXT", "BOOTLEG"]),
        ("ext", ["BASE_EXT"]), ("bootleg", ["BOOTLEG"]),
        ("mk2-ext", ["MK2", "BASE_EXT"]),
        ("mk2-ext-debug", ["MK2", "BASE_EXT", "DEBUG"]),
    )
    preprocessing = []
    for name, defines in configurations:
        target = "MK2" in defines and "BASE_EXT" in defines and "BOOTLEG" not in defines
        versions = []
        for version in ("original", "candidate"):
            dest = output / f"pp-{name}-{version}.v"
            subprocess.run(["iverilog", "-g2012", "-E"] + ["-D" + d for d in defines]
                           + ["-o", str(dest), str(output / f"{version}-address.v")], check=True)
            versions.append(dest.read_text(encoding="utf-8"))
        if not all(text.strip() for text in versions):
            raise SystemExit("Empty actual preprocessing output")
        if target:
            if versions[1].count(CANDIDATE) != 1 or versions[1].count(HELPERS) != 1:
                raise SystemExit("Incorrect actual target selection")
            restored = versions[1].replace(CANDIDATE, ORIGINAL, 1).replace(HELPERS, "", 1)
            if re.sub(r"\s+", "", restored) != re.sub(r"\s+", "", versions[0]):
                raise SystemExit("Actual target preprocessing changed outside decoder")
        elif re.sub(r"\s+", "", versions[0]) != re.sub(r"\s+", "", versions[1]):
            raise SystemExit("Actual non-target preprocessing changed")
        preprocessing.append(f"{name}: {'target inverse' if target else 'non-target identity'}; actual Icarus global defines {defines}\n")
    (output / "preprocessing.txt").write_text("".join(preprocessing), encoding="utf-8")
    (output / "late-bits-generator.py.txt").write_bytes(Path(__file__).read_bytes())
    for file in sorted(output.iterdir()):
        if file.is_file() and file.name not in files and file.name != "SHA256SUMS":
            checksums.append(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n")
    (output / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-address.v", "candidate-address.v")), encoding="utf-8")
    print(f"Pinned complete address blob {blob}; registered address, feature bit and output audited.")
    print("Exact source recovery, eight non-target selections and actual ten Icarus configurations checked.")
    print("Prepared original/candidate decoder projections, seven binary and two X controls.")


if __name__ == "__main__":
    main()
