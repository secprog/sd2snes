#!/usr/bin/env python3
"""Prepare a pinned, runner-only DSP data-RAM decoder experiment."""

import difflib
import hashlib
import re
import sys
from pathlib import Path


EXPECTED_BLOB = "45b2d274419eb5b1db0315ffb91b3862bb61a506"
ORIGINAL = """assign dspx_dp_enable = (SNES_ADDR[15:11] == 5'b00000)
                      & ( (featurebits[FEAT_ST0010] & (SNES_ADDR[22:19] == 4'b1101))
                        | (featurebits[FEAT_DSPX] & (map_unlock | snescmd_unlock) & (SNES_ADDR[23:16] == 8'hE8)) );"""
CANDIDATE = """assign dspx_dp_enable = (SNES_ADDR[15:11] == 5'b00000)
                      & (SNES_ADDR[22:19] == 4'b1101)
                      & (featurebits[FEAT_ST0010]
                        | (featurebits[FEAT_DSPX] & (map_unlock | snescmd_unlock)
                          & SNES_ADDR[23] & (SNES_ADDR[18:16] == 3'b000)));"""
WRAPPED = "`ifdef MK2\n" + CANDIDATE + "\n`else\n" + ORIGINAL + "\n`endif"


def configured(text, initial_defines):
    """Select the pinned source's conditional lines, including local defines."""
    defines = set(initial_defines)
    active, stack, output = True, [], []
    for line in text.splitlines(True):
        match = re.fullmatch(r"\s*`(ifdef|ifndef)\s+(\w+)\s*", line)
        if match:
            kind, macro = match.groups()
            if macro not in {"MK2", "DSP_COMP", "DSP_LEAN"}:
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
        elif re.fullmatch(r"\s*`define\s+DSP_LEAN\s*", line):
            if active:
                defines.add("DSP_LEAN")
        elif re.match(r"\s*`(?:elsif|undef|define)\b", line):
            raise SystemExit(f"Unreviewed preprocessor directive: {line.strip()}")
        elif active:
            output.append(line)
    if stack:
        raise SystemExit("Unbalanced preprocessor conditionals")
    return "".join(output)


def model(name, assignment, x_control=False):
    prefix = (
        f"module {name}(input [23:0] SNES_ADDR, input [15:0] featurebits,\n"
        "  input map_unlock, snescmd_unlock, output dspx_dp_enable);\n"
        "parameter [3:0] FEAT_DSPX = 0, FEAT_ST0010 = 1;\n"
    )
    if x_control:
        return (prefix + assignment.replace("assign dspx_dp_enable =", "wire actual_value =", 1)
                + "\nassign dspx_dp_enable = actual_value & (SNES_ADDR[0] | ~SNES_ADDR[0]);\nendmodule\n")
    return prefix + assignment + "\nendmodule\n"


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-dp-decode-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete DSP address source blob: {blob}")
    original = raw.decode("utf-8")
    for fragment in (ORIGINAL, "  FEAT_DSPX = 0,", "  FEAT_ST0010 = 1,",
                     "reg [23:0] SNES_ADDR; always @(posedge CLK) SNES_ADDR <= SNES_ADDR_early;",
                     "  output dspx_dp_enable,"):
        if original.count(fragment) != 1:
            raise SystemExit(f"Unexpected source boundary: {fragment!r}")
    no_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", original, flags=re.S)
    if len(re.findall(r"\bdspx_dp_enable\b", no_comments)) != 2:
        raise SystemExit("Unexpected decoder declaration or driver")
    candidate = original.replace(ORIGINAL, WRAPPED, 1)
    if candidate.replace(WRAPPED, ORIGINAL, 1) != original:
        raise SystemExit("Candidate failed exact source recovery")
    for defines in (set(), {"MK3"}, {"MK3", "DSP_COMP"}, {"DSP_LEAN"}, {"MK3", "DSP_LEAN"}):
        if configured(original, defines) != configured(candidate, defines):
            raise SystemExit(f"Non-MkII source changed under {sorted(defines)}")

    mutations = {
        "bad-window": CANDIDATE.replace("5'b00000", "5'b00001", 1),
        "bad-prefix": CANDIDATE.replace("4'b1101", "4'b1100", 1),
        "bad-high-bank": CANDIDATE.replace("& SNES_ADDR[23]", "& ~SNES_ADDR[23]", 1),
        "bad-low-bank": CANDIDATE.replace("3'b000", "3'b001", 1),
        "bad-unlock": CANDIDATE.replace("map_unlock | snescmd_unlock", "map_unlock & snescmd_unlock", 1),
        "bad-st": CANDIDATE.replace("featurebits[FEAT_ST0010]", "1'b0", 1),
    }
    if any(value == CANDIDATE for value in mutations.values()):
        raise SystemExit("A required negative control was not generated")
    files = {
        "original-address.v": original,
        "candidate-address.v": candidate,
        "gold.v": model("gold", ORIGINAL),
        "gate.v": model("gate", CANDIDATE),
        **{name + ".v": model("gate", value) for name, value in mutations.items()},
        "bad-x.v": model("gate", CANDIDATE, x_control=True),
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
                                     "original-address.v", "candidate-address.v")),
        encoding="utf-8",
    )
    print(f"Pinned complete DSP address blob {blob}; registered input and output boundary audited.")
    print("Exact source recovery and five non-MkII configurations checked.")
    print("Prepared original/candidate decoder projections and seven negative controls.")


if __name__ == "__main__":
    main()
