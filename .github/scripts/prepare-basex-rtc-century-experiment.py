#!/usr/bin/env python3
"""Prepare a pinned, runner-only RTC arithmetic experiment and proof models."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


EXPECTED_BLOB = "86041da7217d452fab390738d2137cd65fa00898"
DECL = "reg [15:0] dow_year_tmp;"
ORIGINAL_EXPR = """dow_year
                        + (dow_year >> 2)
                        - (dow_year100)
                        + (dow_year100 >> 2)"""
ORIGINAL_ASSIGN = "        dow_year_tmp <= " + ORIGINAL_EXPR + ";"
CORRECTION = "wire [6:0] dow_century_correction = dow_year100 - (dow_year100 >> 2);"
CANDIDATE_EXPR = """dow_year
                        + (dow_year >> 2)
                        - {9'b0, dow_century_correction}"""
CANDIDATE_ASSIGN = "        dow_year_tmp <= " + CANDIDATE_EXPR + ";"
WRAPPED_DECL = DECL + "\n`ifdef MK2\n" + CORRECTION + "\n`endif"
WRAPPED_ASSIGN = "`ifdef MK2\n" + CANDIDATE_ASSIGN + "\n`else\n" + ORIGINAL_ASSIGN + "\n`endif"


def unique(text, fragment):
    if text.count(fragment) != 1:
        raise SystemExit(f"Expected exactly one source fragment: {fragment!r}")


def model(name, declaration, expression, x_control=False):
    prefix = (
        f"module {name}(input [13:0] dow_year, input [6:0] dow_year100,\n"
        "  input witness, output [15:0] result);\n"
    )
    if declaration:
        prefix += declaration + "\n"
    if x_control:
        return (prefix + "wire [15:0] actual_value = " + expression + ";\n"
                + "assign result = actual_value & {16{witness | ~witness}};\nendmodule\n")
    return prefix + "assign result = " + expression + ";\nendmodule\n"


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-basex-rtc-century-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete RTC source blob: {blob}")
    original = raw.decode("utf-8")
    for fragment in (DECL, ORIGINAL_ASSIGN, "reg [13:0] dow_year;", "reg [6:0] dow_year100;",
                     "  dow_year_tmp = 0;", "      STATE_DOW2: begin\n        dow_tmp <= (83 * dow_month);\n" + ORIGINAL_ASSIGN,
                     "always @(posedge clkin) begin\n  if(pgm_we_rising) begin"):
        unique(original, fragment)
    no_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", original, flags=re.S)
    if len(re.findall(r"\bdow_year_tmp\s*(?:<=|=)", no_comments)) != 2:
        raise SystemExit("Unexpected RTC intermediate initialization or write")

    candidate = original.replace(DECL, WRAPPED_DECL, 1).replace(ORIGINAL_ASSIGN, WRAPPED_ASSIGN, 1)
    recovered = candidate.replace(WRAPPED_DECL, DECL, 1).replace(WRAPPED_ASSIGN, ORIGINAL_ASSIGN, 1)
    if recovered != original:
        raise SystemExit("Candidate failed exact original source recovery")
    spec = importlib.util.spec_from_file_location(
        "stack_reference", Path(__file__).with_name("prepare-dsp-stack-experiment.py")
    )
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    for defines in ({"MK3"}, {"MK3", "DEBUG"}, set(), {"DEBUG"}):
        before = re.sub(r"\s+", "", reference.without_comments(reference.configured(original, defines)))
        after = re.sub(r"\s+", "", reference.without_comments(reference.configured(candidate, defines)))
        if before != after:
            raise SystemExit(f"Non-MkII source changed under {sorted(defines)}")

    files = {
        "original-rtc.v": original,
        "candidate-rtc.v": candidate,
        "gold.v": model("gold", "", ORIGINAL_EXPR),
        "gate.v": model("gate", CORRECTION, CANDIDATE_EXPR),
        "bad-year-shift.v": model("gate", CORRECTION, CANDIDATE_EXPR.replace("dow_year >> 2", "dow_year >> 3")),
        "bad-century-shift.v": model("gate", CORRECTION.replace("dow_year100 >> 2", "dow_year100 >> 1"), CANDIDATE_EXPR),
        "bad-width.v": model("gate", CORRECTION.replace("[6:0]", "[5:0]"), CANDIDATE_EXPR.replace("9'b0", "10'b0")),
        "bad-sign.v": model("gate", CORRECTION, CANDIDATE_EXPR.replace("- {9'b0", "+ {9'b0")),
        # Equivalent for binary witness, different for an X witness and a one result bit.
        "bad-x.v": model("gate", CORRECTION, CANDIDATE_EXPR, x_control=True),
    }
    if any(files[key] == files["gate.v"] for key in files if key.startswith("bad-")):
        raise SystemExit("A required negative control was not generated")
    output.mkdir(parents=True, exist_ok=True)
    checksums = []
    for name, content in files.items():
        data = content.encode("utf-8")
        (output / name).write_bytes(data)
        checksums.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(checksums), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-rtc.v", "candidate-rtc.v")),
        encoding="utf-8",
    )
    print(f"Pinned complete RTC blob {blob}; intermediate initialization and write context audited.")
    print("Exact source recovery and four non-MkII configurations checked.")
    print("Prepared actual original/candidate RHS projections and five negative controls.")


if __name__ == "__main__":
    main()
