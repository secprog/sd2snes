#!/usr/bin/env python3
"""Prepare a pinned, runner-only basex clock-enable mapping experiment."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "basex_reference", Path(__file__).with_name("prepare-basex-write-gate-experiment.py")
)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)

ADDR = "reg [23:0] cheat_addr[5:0];"
DATA = "reg [7:0] cheat_data[5:0];"
ATTRIBUTE = '(* use_clock_enable = "no" *)\n'
MK2_ATTRIBUTE = "`ifdef MK2\n" + ATTRIBUTE + "`endif\n"


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-basex-ce-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != ref.EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete cheat source blob: {blob}")
    original = raw.decode("utf-8")
    for fragment in (ref.DECL, ref.WRITES, ref.STROBE, ref.PROGRAM, ADDR, DATA):
        if original.count(fragment) != 1:
            raise SystemExit(f"Unreviewed cheat source boundary: {fragment}")
    if re.findall(r"^\s*`(\w+)", original, flags=re.M) != ["timescale"]:
        raise SystemExit("Unexpected existing preprocessor directives")
    if len(re.findall(r"^\s*module\b", original, flags=re.M)) != 1:
        raise SystemExit("Expected the pinned standalone cheat module")

    remainder = ref.without_comments(original.replace(ref.DECL, "").replace(ref.WRITES, ""))
    for name in ("cheat_addr", "cheat_data"):
        accesses = re.findall(r"\b" + name + r"\[([^\]]+)\]", remainder)
        if sorted(accesses) != [str(i) for i in range(6)]:
            raise SystemExit(f"Unmodelled {name} access: {accesses}")
        if re.search(r"\b" + name + r"\b",
                     re.sub(r"\b" + name + r"\[[^\]]+\]", "", remainder)):
            raise SystemExit(f"Unmodelled {name} declaration or access")

    candidate = original.replace(ADDR, MK2_ATTRIBUTE + ADDR, 1)
    candidate = candidate.replace(DATA, MK2_ATTRIBUTE + DATA, 1)
    if candidate.count(MK2_ATTRIBUTE) != 2 or candidate.replace(MK2_ATTRIBUTE, "") != original:
        raise SystemExit("Candidate changed source beyond the two MkII synthesis attributes")

    # Exact projection of the pinned programming block onto its 192 array bits.
    # All source outside the two attributes is byte-identical, including reads.
    gold_write = """always @(posedge clk) begin
  if(SNES_reset_strobe) begin
  end else begin
    if(snescmd_unlock & snescmd_wr_strobe) begin
    end else if(pgm_we) begin
      if(pgm_idx < 6) begin
""" + ref.WRITES + """
      end
    end
  end
end"""
    gold = ref.model(gold_write)
    annotated_decl = ATTRIBUTE + ADDR + "\n" + ATTRIBUTE + DATA
    if gold.count(ref.DECL) != 1:
        raise SystemExit("Expected exactly one component declaration")
    gate = gold.replace(ref.DECL, annotated_decl, 1)
    if gate.replace(ATTRIBUTE, "") != gold:
        raise SystemExit("Proof model differs by more than the two synthesis attributes")
    bad_data = gate.replace(
        "cheat_data[pgm_idx] <= pgm_in[7:0];",
        "cheat_data[pgm_idx] <= pgm_in[7:0] ^ 8'h01;", 1)
    bad_priority = gate.replace(
        "if(snescmd_unlock & snescmd_wr_strobe) begin", "if(1'b0) begin", 1)
    bad_reset = gate.replace("if(SNES_reset_strobe) begin", "if(1'b0) begin", 1)
    if any(mutant == gate for mutant in (bad_data, bad_priority, bad_reset)):
        raise SystemExit("A required negative-control mutation was not applied")

    files = {
        "original-cheat.v": original, "candidate-cheat.v": candidate,
        "gold.v": gold, "gate.v": gate, "bad-data.v": bad_data,
        "bad-priority.v": bad_priority, "bad-reset.v": bad_reset,
    }
    output.mkdir(parents=True, exist_ok=True)
    hashes = []
    for name, text in files.items():
        data = text.encode("utf-8")
        (output / name).write_bytes(data)
        hashes.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(hashes), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-cheat.v", "candidate-cheat.v")),
        encoding="utf-8")
    print(f"Verified complete cheat source blob {blob}; all array accesses accounted for.")
    print("Only two MkII-only USE_CLOCK_ENABLE attributes differ; all other source is byte-identical.")
    print("Generated complete 192-bit transition projections and three negative controls.")
    print("Native mapping, capacity and timing remain unproven; production RTL is untouched.")


if __name__ == "__main__":
    main()
