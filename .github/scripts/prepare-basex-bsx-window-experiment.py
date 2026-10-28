#!/usr/bin/env python3
"""Prepare a pinned, runner-only BS-X base-window decoder experiment."""

import difflib
import hashlib
import re
import sys
from pathlib import Path


EXPECTED_BLOB = "3ca70f4901a5fefef1576bae144060462b4c4254"
ORIGINAL = """wire base_enable = feat_bs_base_enable
                   & (use_bsx) && (!snes_addr[22] && (snes_addr[15:0] >= 16'h2188)
                                 && (snes_addr[15:0] <= 16'h219f));"""
CANDIDATE = """wire base_enable = feat_bs_base_enable
                   & (use_bsx) && (!snes_addr[22]
                                 && ((snes_addr[15:0] - 16'h2188) <= 16'h0017));"""
WRAPPED = ("`ifdef MK2\n`ifdef BASE_EXT\n" + CANDIDATE + "\n`else\n" + ORIGINAL
           + "\n`endif\n`else\n" + ORIGINAL + "\n`endif")


def configured(text, initial_defines):
    """Select the pinned source's conditional lines, including its local define."""
    defines = set(initial_defines)
    active, stack, output = True, [], []
    for line in text.splitlines(True):
        match = re.fullmatch(r"\s*`(ifdef|ifndef)\s+(\w+)\s*", line)
        if match:
            kind, macro = match.groups()
            if macro not in {"MK2", "BASE_EXT", "BSX_ENABLE"}:
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
        elif re.fullmatch(r"\s*`define\s+BSX_ENABLE\s*", line):
            if active:
                defines.add("BSX_ENABLE")
        elif re.match(r"\s*`(?:elsif|undef|define)\b", line):
            raise SystemExit(f"Unreviewed preprocessor directive: {line.strip()}")
        elif active:
            output.append(line)
    if stack:
        raise SystemExit("Unbalanced preprocessor conditionals")
    return "".join(output)


def model(name, declaration, x_control=False):
    prefix = (f"module {name}(input [23:0] snes_addr, input feat_bs_base_enable,\n"
              "  input use_bsx, output base_enable);\n")
    if x_control:
        return (prefix + declaration.replace("wire base_enable =", "wire actual_value =", 1)
                + "\nassign base_enable = actual_value & (snes_addr[23] | ~snes_addr[23]);\nendmodule\n")
    return prefix + declaration.replace("wire base_enable =", "assign base_enable =", 1) + "\nendmodule\n"


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-basex-bsx-window-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete BS-X source blob: {blob}")
    original = raw.decode("utf-8")
    for fragment in (ORIGINAL, "reg [23:0] snes_addr; always @(posedge clkin) snes_addr <= snes_addr_in;",
                     "  input use_bsx,", "  input feat_bs_base_enable,"):
        if original.count(fragment) != 1:
            raise SystemExit(f"Unexpected source boundary: {fragment!r}")
    no_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", original, flags=re.S)
    if len(re.findall(r"\bwire\s+base_enable\s*=", no_comments)) != 1:
        raise SystemExit("Unexpected base-window driver")
    candidate = original.replace(ORIGINAL, WRAPPED, 1)
    if candidate.replace(WRAPPED, ORIGINAL, 1) != original:
        raise SystemExit("Candidate failed exact source recovery")
    for defines in (set(), {"MK3"}, {"MK3", "BASE_EXT"}, {"MK2"},
                    {"MK2", "BOOTLEG"}, {"BASE_EXT"}):
        if configured(original, defines) != configured(candidate, defines):
            raise SystemExit(f"Non-target source changed under {sorted(defines)}")
    mutations = {
        "bad-low": CANDIDATE.replace("16'h2188", "16'h2189", 1),
        "bad-high": CANDIDATE.replace("16'h0017", "16'h0016", 1),
        "bad-address-width": CANDIDATE.replace("snes_addr[15:0] - 16'h2188", "snes_addr[7:0] - 8'h88", 1),
        "bad-feature": CANDIDATE.replace("= feat_bs_base_enable", "= ~feat_bs_base_enable", 1),
        "bad-cart": CANDIDATE.replace("(use_bsx)", "(~use_bsx)", 1),
        "bad-bank": CANDIDATE.replace("!snes_addr[22]", "snes_addr[22]", 1),
    }
    if any(value == CANDIDATE for value in mutations.values()):
        raise SystemExit("A required negative control was not generated")
    files = {
        "original-bsx.v": original,
        "candidate-bsx.v": candidate,
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
                                     "original-bsx.v", "candidate-bsx.v")), encoding="utf-8")
    print(f"Pinned complete BS-X blob {blob}; registered address and both feature inputs audited.")
    print("Exact source recovery and six non-target configurations checked.")
    print("Prepared original/candidate decoder projections and seven negative controls.")


if __name__ == "__main__":
    main()
