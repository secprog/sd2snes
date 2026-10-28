#!/usr/bin/env python3
"""Prepare a pinned, runner-only basex S-RTC decoder experiment."""

import difflib
import hashlib
import re
import sys
from pathlib import Path


EXPECTED_BLOB = "36ce9a5c17fc80b9ddda1d869f0d75a4fb52356c"
ORIGINAL = "assign srtc_enable = featurebits[FEAT_SRTC] & (!SNES_ADDR[22] && ((SNES_ADDR[15:0] & 16'hfffe) == 16'h2800));"
CANDIDATE = """wire srtc_low_match;
wire srtc_bottom_match = (SNES_ADDR[3:1] == 3'b000);
wire srtc_middle_match = (SNES_ADDR[11:8] == 4'b1000);
wire srtc_high_match = featurebits[FEAT_SRTC] & (!SNES_ADDR[22] && (SNES_ADDR[15:12] == 4'h2));
basex_srtc_low srtc_low_decode(.addr(SNES_ADDR[7:4]), .hit(srtc_low_match));
basex_srtc_join srtc_join_decode(
  .parts({srtc_low_match, srtc_bottom_match, srtc_middle_match, srtc_high_match}),
  .hit(srtc_enable)
);"""
HELPERS = """(* LUT_MAP="yes" *)
module basex_srtc_low(input [3:0] addr, output hit);
assign hit = (addr == 4'b0000);
endmodule
(* LUT_MAP="yes" *)
module basex_srtc_join(input [3:0] parts, output hit);
assign hit = &parts;
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
    if re.search(r"\bmodule\s+basex_srtc_(?:low|join)\b", without_comments):
        raise SystemExit("S-RTC helper name already exists")
    candidate = original.replace(ORIGINAL, WRAPPED, 1) + HELPER_BLOCK
    recovered = candidate.removesuffix(HELPER_BLOCK).replace(WRAPPED, ORIGINAL, 1)
    if recovered != original:
        raise SystemExit("Candidate failed exact source recovery")
    for defines in (set(), {"MK3"}, {"MK3", "BASE_EXT"}, {"MK2"},
                    {"MK2", "BOOTLEG"}, {"MK2", "BASE_EXT", "BOOTLEG"},
                    {"BASE_EXT"}, {"BOOTLEG"}):
        if configured(original, defines) != configured(candidate, defines):
            raise SystemExit(f"Non-target source changed under {sorted(defines)}")
    mutations = {
        "bad-low-index": (replace_once(CANDIDATE, "SNES_ADDR[7:4]", "SNES_ADDR[6:3]"), HELPERS),
        "bad-low-bit6": (CANDIDATE, replace_once(HELPERS, "addr == 4'b0000", "addr == 4'b0100")),
        "bad-bottom": (replace_once(CANDIDATE, "3'b000", "3'b001"), HELPERS),
        "bad-middle": (replace_once(CANDIDATE, "4'b1000", "4'b1001"), HELPERS),
        "bad-upper": (replace_once(CANDIDATE, "4'h2", "4'h3"), HELPERS),
        "bad-bank": (replace_once(CANDIDATE, "!SNES_ADDR[22]", "SNES_ADDR[22]"), HELPERS),
        "bad-feature": (replace_once(CANDIDATE, "featurebits[FEAT_SRTC]", "~featurebits[FEAT_SRTC]"), HELPERS),
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
    (output / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-address.v", "candidate-address.v")), encoding="utf-8")
    print(f"Pinned complete address blob {blob}; registered address, feature bit and output audited.")
    print("Exact source recovery and eight non-target configurations checked.")
    print("Prepared original/candidate decoder projections, seven binary and two X controls.")


if __name__ == "__main__":
    main()
