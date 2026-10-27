#!/usr/bin/env python3
"""Prepare a pinned DSPx freeze-register replication experiment for hosted CI."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "stack_reference", Path(__file__).with_name("prepare-dsp-stack-experiment.py")
)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)

FREEZE_DECL = "reg  ss_frozen; initial ss_frozen = 1'b0;"
WAIT_DECL = "reg [7:0] ss_wait; initial ss_wait = 8'h00;"
FREEZE_BLOCK = """always @(posedge CLK) begin
  if(~RST | ~ss_halt_eff) begin
    ss_frozen <= 1'b0;
    ss_wait   <= 8'h00;
  end else if(~ss_frozen) begin
    ss_wait <= ss_wait + 1'b1;
    if(ss_boundary | (&ss_wait)) ss_frozen <= 1'b1;
  end
end"""
REPLICA = """`ifdef MK2
// A same-edge copy separates the main core's freeze load from other consumers.
// Its initial value and next-state relation are proven equal to ss_frozen.
(* equivalent_register_removal = "no" *)
reg ss_core_frozen; initial ss_core_frozen = 1'b0;
always @(posedge CLK) begin
  if(~RST | ~ss_halt_eff)
    ss_core_frozen <= 1'b0;
  else if(~ss_frozen && (ss_boundary | (&ss_wait)))
    ss_core_frozen <= 1'b1;
end
`endif"""
MAIN_HEAD = """always @(posedge CLK) begin
  if(RST & ~ss_frozen) begin
`ifdef MK2
    push_now <= 1'b0;"""
MAIN_HEAD_CANDIDATE = """always @(posedge CLK) begin
`ifdef MK2
  if(RST & ~ss_core_frozen) begin
`else
  if(RST & ~ss_frozen) begin
`endif
`ifdef MK2
    push_now <= 1'b0;"""
RESTORE_HEAD = """  end else if(RST & ss_frozen) begin
    // savestate RESTORE (Phase 2): load FSM-owned state from the scan window."""
RESTORE_HEAD_CANDIDATE = """`ifdef MK2
  end else if(RST & ss_core_frozen) begin
`else
  end else if(RST & ss_frozen) begin
`endif
    // savestate RESTORE (Phase 2): load FSM-owned state from the scan window."""
PORTS = """(input RST, ss_halt_eff, ss_boundary, ss_frozen,
 input [7:0] ss_wait, output reg next_frozen,
 output core_run, core_restore);
"""
def comb_original():
    block = FREEZE_BLOCK.replace("always @(posedge CLK) begin",
                                 "always @* begin\n  next_frozen = ss_frozen;", 1)
    block = block.replace("ss_frozen <=", "next_frozen =")
    block = block.replace("    ss_wait   <= 8'h00;\n", "")
    block = block.replace("    ss_wait <= ss_wait + 1'b1;\n", "")
    if "ss_wait <=" in block or "posedge" in block:
        raise SystemExit("Could not project the pinned original freeze transition")
    return block


def comb_replica():
    block = REPLICA.split("always @(posedge CLK) begin\n", 1)[1].split("\nend\n`endif", 1)[0]
    block = block.replace("ss_core_frozen <=", "next_frozen =")
    return "always @* begin\n  next_frozen = ss_frozen;\n" + block + "\nend"


def model(name, block, guards):
    return f"module {name}" + PORTS + block + "\n" + guards + "endmodule\n"


def main_guards(source):
    run = re.findall(
        r"always @\(posedge CLK\) begin\n\s*if\(([^)]*)\) begin\n\s*push_now <= 1'b0;",
        source,
    )
    restore = re.findall(
        r"end else if\(([^)]*)\) begin\n\s*// savestate RESTORE \(Phase 2\)", source
    )
    if len(run) != 1 or len(restore) != 1:
        raise SystemExit("Expected exactly one main run/restore guard in MkII source")
    return f"assign core_run = {run[0]};\nassign core_restore = {restore[0]};\n"


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-freeze-replica-experiment.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if blob != ref.EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete DSP source blob: {blob}")
    original = raw.decode("utf-8")
    for fragment in (FREEZE_DECL, WAIT_DECL, FREEZE_BLOCK, MAIN_HEAD, RESTORE_HEAD):
        if original.count(fragment) != 1:
            raise SystemExit(f"Freeze source boundary changed: {fragment}")
    if re.search(r"\bss_core_frozen\b", ref.without_comments(original)):
        raise SystemExit("Replica identifier is already in use")
    candidate = original.replace(FREEZE_BLOCK, FREEZE_BLOCK + "\n" + REPLICA, 1)
    candidate = candidate.replace(MAIN_HEAD, MAIN_HEAD_CANDIDATE, 1)
    candidate = candidate.replace(RESTORE_HEAD, RESTORE_HEAD_CANDIDATE, 1)
    recovered = candidate.replace(FREEZE_BLOCK + "\n" + REPLICA, FREEZE_BLOCK, 1)
    recovered = recovered.replace(MAIN_HEAD_CANDIDATE, MAIN_HEAD, 1)
    recovered = recovered.replace(RESTORE_HEAD_CANDIDATE, RESTORE_HEAD, 1)
    if recovered != original:
        raise SystemExit("Source outside the audited replica and two guards changed")
    for defines in ({"MK3"}, {"MK3", "DEBUG"}, set(), {"DEBUG"}):
        before = re.sub(r"\s+", "", ref.without_comments(ref.configured(original, defines)))
        after = re.sub(r"\s+", "", ref.without_comments(ref.configured(candidate, defines)))
        if before != after:
            raise SystemExit(f"Non-MkII source changed under {sorted(defines)}")

    # The original and replica are both initialized to zero. Given equal current
    # values, prove their exact projected next-state and main-block guards for
    # every binary RST, halt, boundary and wait value. This relation then holds
    # inductively at each clock edge; source recovery checks all other logic.
    gold_guards = main_guards(ref.configured(original, {"MK2"}))
    gate_guards = main_guards(ref.configured(candidate, {"MK2"}))
    gate_guards = gate_guards.replace("ss_core_frozen", "ss_frozen")
    gold = model("gold", comb_original(), gold_guards)
    gate = model("gate", comb_replica(), gate_guards)
    bad_reset = gate.replace("if(~RST | ~ss_halt_eff)", "if(~RST & ~ss_halt_eff)", 1)
    bad_boundary = gate.replace("(ss_boundary | (&ss_wait))", "(ss_boundary & (&ss_wait))", 1)
    bad_guard = gate.replace("assign core_restore = RST & ss_frozen;", "assign core_restore = RST;", 1)
    if any(mutant == gate for mutant in (bad_reset, bad_boundary, bad_guard)):
        raise SystemExit("A required negative-control mutation was not applied")

    output.mkdir(parents=True, exist_ok=True)
    files = {
        "original-upd77c25.v": original,
        "candidate-upd77c25.v": candidate,
        "gold.v": gold,
        "gate.v": gate,
        "bad-reset.v": bad_reset,
        "bad-boundary.v": bad_boundary,
        "bad-guard.v": bad_guard,
    }
    hashes = []
    for name, text in files.items():
        data = text.encode("utf-8")
        (output / name).write_bytes(data)
        hashes.append(f"{hashlib.sha256(data).hexdigest()}  {name}\n")
    (output / "SHA256SUMS").write_text("".join(hashes), encoding="utf-8")
    (output / "candidate.diff").write_text(
        "".join(difflib.unified_diff(original.splitlines(True), candidate.splitlines(True),
                                     "original-upd77c25.v", "candidate-upd77c25.v")),
        encoding="utf-8",
    )
    print(f"Verified full DSP blob {blob}; original source recovered byte for byte.")
    print("Both freeze registers start at zero; replica adds no clock latency.")
    print("Non-MkII source is unchanged in four audited configurations.")
    print("Generated transition/guard models and reset, boundary and guard mutations.")


if __name__ == "__main__":
    main()
