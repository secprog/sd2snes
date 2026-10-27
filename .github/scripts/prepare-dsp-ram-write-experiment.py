#!/usr/bin/env python3
"""Prepare a pinned, runner-only DSP RAM-write factoring experiment."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


EXPECTED_BLOB = "ba14f5b6dd198fbb5645f005fb3784890beec2c4"
ORIGINAL = "wire ram_web = reg_we_rising & DP_enable & ~ss_regwin & ~ss_ctrl;"
CTRL = "assign ss_ctrl = ss_window_en & DP_enable & (DP_ADDR == 11'h7ff);"
REGWIN = "assign ss_regwin = ss_window_en & DP_enable & ss_frozen & (DP_ADDR[10:8] == 3'b110);"
FACTORED = (
    "wire ram_web = reg_we_rising & DP_enable & ~(ss_window_en & DP_enable & "
    "((ss_frozen & (DP_ADDR[10:8] == 3'b110)) | (DP_ADDR == 11'h7ff)));"
)
WRAPPED = "`ifdef MK2\n" + FACTORED + "\n`else\n" + ORIGINAL + "\n`endif"


def unique(text, fragment):
    if text.count(fragment) != 1:
        raise SystemExit(f"Expected exactly one source fragment: {fragment!r}")


def model(name, expression):
    return (
        f"module {name}(input reg_we_rising, DP_enable, ss_window_en, ss_frozen,\n"
        "  input [10:0] DP_ADDR, output ss_ctrl, ss_regwin, ram_web);\n"
        + CTRL + "\n" + REGWIN + "\n"
        + expression.replace("wire ram_web =", "assign ram_web =", 1)
        + "\nendmodule\n"
    )


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-ram-write-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete DSP source blob: {blob}")
    original = raw.decode("utf-8")
    for fragment in (ORIGINAL, CTRL, REGWIN, ".web(ram_web)", ".wren_b(ram_web)"):
        unique(original, fragment)
    no_comments = re.sub(r"/\*.*?\*/|//[^\n]*", "", original, flags=re.S)
    if len(re.findall(r"\bram_web\b", no_comments)) != 3:
        raise SystemExit("Unexpected RAM write-enable declaration or consumer")

    candidate = original.replace(ORIGINAL, WRAPPED, 1)
    if candidate.replace(WRAPPED, ORIGINAL, 1) != original:
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

    mutations = {
        "bad-address": FACTORED.replace("11'h7ff", "11'h7fe", 1),
        "bad-freeze": FACTORED.replace("ss_frozen & (DP_ADDR", "1'b1 & (DP_ADDR", 1),
        "bad-write": FACTORED.replace("reg_we_rising & DP_enable", "~reg_we_rising & DP_enable", 1),
        # Binary-equivalent absorption that differs when DP_enable is unknown.
        "bad-absorb": FACTORED.replace("ss_window_en & DP_enable & ", "ss_window_en & ", 1),
    }
    if any(value == FACTORED for value in mutations.values()):
        raise SystemExit("A required negative control was not generated")
    files = {
        "original-upd77c25.v": original,
        "candidate-upd77c25.v": candidate,
        "gold.v": model("gold", ORIGINAL),
        "gate.v": model("gate", FACTORED),
        **{name + ".v": model("gate", value) for name, value in mutations.items()},
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
                                     "original-upd77c25.v", "candidate-upd77c25.v")),
        encoding="utf-8",
    )
    print(f"Pinned DSP blob {blob}; both RAM write-enable consumers audited.")
    print("Exact source recovery and four non-MkII configurations checked.")
    print("Prepared original control/regwin and RAM-enable projections with four mutants.")


if __name__ == "__main__":
    main()
