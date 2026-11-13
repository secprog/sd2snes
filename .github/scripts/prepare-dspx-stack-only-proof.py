#!/usr/bin/env python3
"""GitHub-only proof preparation for the current stack-only DSPX repair.

The historical parallel decoder is reused as text; this independently binds the
new production integration to its current unmodified baseline and proves again.
"""
import difflib
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("GitHub-hosted execution only")

BASELINE = "689f3a2a4006d4aff66e343bd12be772eedad190"
SOURCE = "verilog/sd2snes_dsp/upd77c25.v"
CANDIDATE_SHA = "3f5bb39bc202fe77a9dd7a6e8497e902907e12161707e6028af921fd8c450612"
spec = importlib.util.spec_from_file_location(
    "parallel", Path(__file__).with_name("prepare-dsp-stack-parallel-address-proof.py"))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
ref, HELPERS, PROOF_RETURN = p.ref, p.HELPERS, p.PROOF_RETURN
once, sha, blob, normalize = p.once, p.sha, p.blob, p.normalize
replace_join_input, address_x_mutant = p.replace_join_input, p.address_x_mutant


def main():
    output = Path(sys.argv[1])
    original = subprocess.check_output(["git", "show", BASELINE + ":" + SOURCE]).decode("utf-8")
    candidate = Path(SOURCE).read_bytes().decode("utf-8")
    if blob(original) != ref.EXPECTED_BLOB or sha(original) != "af6ad41f629e2646763394ee0f2b5a1ef55e745fbb89b65701a3c8de54bcbf81":
        raise SystemExit("Current production baseline changed")
    if sha(candidate) != CANDIDATE_SHA or blob(candidate) != "6660fc95958e6eb0117d2018c1897257fb0b6cc2":
        raise SystemExit("Reviewed stack-only candidate changed")
    headers = {
        "dsp": (Path("verilog/sd2snes_dsp/config.vh"), "1a9a6a14b8b08eb6e931ce2320326e913aa8000e"),
        "dspx": (Path("verilog/sd2snes_dspx/config.vh"), "4cf8aa3111a5bf103065cded5fb77fdfc39ee239"),
    }
    for path, expected in headers.values():
        if blob(path.read_bytes().decode("utf-8")) != expected:
            raise SystemExit("Actual configuration header pin changed")
    fragments = (ref.DECL, ref.PUSH, ref.OTHER_PUSH, ref.SCAN_READ,
                 ref.RETURN, ref.RESTORE, ref.SCAN_INDEX, ref.WRITE_INDEX)
    remainder = original
    for fragment in fragments:
        remainder = once(remainder, fragment, "")
    if re.search(r"\bstack\b", ref.without_comments(remainder)):
        raise SystemExit("Unmodelled original stack access, initialization or reset")
    push_context = ("always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n"
                    "`ifdef MK2\n    push_now <= 1'b0;\n" + ref.PUSH + "\n`endif\n")
    if original.count(push_context) != 1:
        raise SystemExit("Original CALL ancestors or clock changed")
    restore_context = re.search(
        r"  end else if\(RST & ss_frozen\) begin\n"
        r"    // savestate RESTORE.*?\n    if\(ss_wr\) begin\n"
        r"      if\(ss_wa >= 8'h34 && ss_wa <= 8'h53\) begin\n"
        + re.escape(ref.RESTORE) + r"\n      end else case\(ss_wa\)", original, flags=re.S)
    if restore_context is None or original.count("`ifndef MK2\n" + ref.OTHER_PUSH + "\n`endif") != 1:
        raise SystemExit("Original restore or non-MkII CALL boundary changed")
    write = p.writes()
    if sha(write) != "3da63a53d183cd7a267e697d46216665cce4e2b71eced6b0623ae9046e34f2bd" or sha(HELPERS) != "4ec45537c9a2b00aa6ce512b4761e21023cea96eedb4ca4965e7e29532b0ad2f":
        raise SystemExit("Reviewed exact helper/write text changed")
    push = ("`ifdef DSP_COMP\n    // DSPX stack writes use the parallel word/lane decoder above.\n`else\n"
            + ref.PUSH + "\n`endif")
    restore = ("`ifdef MK2\n`ifdef DSP_COMP\n        // DSPX stack writes use the parallel word/lane decoder above.\n"
               "`else\n" + ref.RESTORE + "\n`endif\n`else\n" + ref.RESTORE + "\n`endif")
    index = ref.WRITE_INDEX + "\n" + p.old.scoped(write)
    appendix = "\n" + p.old.scoped(HELPERS) + "\n"
    if not candidate.endswith(appendix):
        raise SystemExit("Target helper scope changed")
    recovered = candidate.removesuffix(appendix)
    recovered = once(once(once(recovered, index, ref.WRITE_INDEX), restore, ref.RESTORE), push, ref.PUSH)
    if recovered != original:
        raise SystemExit("Whole candidate inverse differs from current production baseline")
    if ref.RETURN not in candidate or candidate.count(ref.DECL) != 1:
        raise SystemExit("Native unsized return or original storage changed")
    if len(re.findall(r"always @\(posedge CLK\) begin.*?\nend", write, flags=re.S)) != 16:
        raise SystemExit("Expected sixteen original-state word write blocks")

    # Full source-bound original transition. SP=0 undefined return is made
    # explicit in BOTH proof models only; native unsized subtraction is intact.
    gold_write = ("always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n" + ref.PUSH
                  + "\n  end else if(RST & ss_frozen) begin\n    if(ss_wr) begin\n"
                  + "      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n" + ref.RESTORE
                  + "\n      end\n    end\n  end\nend")
    gold = ref.model(ref.DECL, gold_write, "stack[ss_stk_idx]", PROOF_RETURN, False)
    gate = ref.model(ref.DECL, write, "stack[ss_stk_idx]", PROOF_RETURN, False) + HELPERS
    cpu_guard = "if (reset_n & ~frozen) begin\n    if (push_now) begin"
    changes = {
        "bad-data": ("stack[0][7:0] <= stack_late_data[7:0];", "stack[0][7:0] <= stack_late_data[7:0] ^ 8'h01;"),
        "bad-run": (cpu_guard, "if (reset_n) begin\n    if (push_now) begin"),
        "bad-restore": ("else if (reset_n & frozen) begin", "else if (reset_n & ~frozen) begin"),
        "bad-reset": (cpu_guard, "if (~frozen) begin\n    if (push_now) begin"),
        "bad-push": ("if (push_now) begin", "if (1'b1) begin"),
        "bad-strobe": ("if (ss_wr) permit = 1'b1;", "if (1'b1) permit = 1'b1;"),
        "bad-prefix": ("#(.VALUE(4'd3)) restore_high_0", "#(.VALUE(4'd4)) restore_high_0"),
        "bad-word": ("#(.VALUE(4'd0)) stack_pointer_0", "#(.VALUE(4'd1)) stack_pointer_0"),
        "bad-return": (PROOF_RETURN, "stack[regs_sp-4'd1]"),
        "bad-cpu-permit": ("if (sp_selected) selected = 1'b1;", "if (1'b1) selected = 1'b1;"),
        "bad-x-call-data": ("stack_late_push_data = pc + 1;", "stack_late_push_data = (pc + 1) ^ {11{ss_wa[0] ^ ss_wa[0]}};"),
        "bad-x-restore-data": (" : {ss_wd[2:0], ss_wd};", " : ({ss_wd[2:0], ss_wd} ^ {11{pc[0] ^ pc[0]}});"),
        "bad-x-cpu-guard": (cpu_guard, "if ((reset_n & ~frozen) !== 1'b0) begin\n    if (push_now) begin"),
    }
    models = {"gold": gold, "gate": gate}
    for name, (before, after) in changes.items():
        models[name] = once(gate, before, after)
    models["bad-lane"] = replace_join_input(gate, 0, "low", ".addr_low(stack_addr_low[4])", ".addr_low(stack_addr_low[5])")
    models["bad-high-half"] = replace_join_input(gate, 10, "low", ".addr_high(stack_addr_high[1])", ".addr_high(stack_addr_high[0])")
    models["bad-low-half"] = replace_join_input(gate, 10, "low", ".addr_low(stack_addr_low[8])", ".addr_low(stack_addr_low[10])")
    models["bad-x-address"] = address_x_mutant(gate, "restore_low_0")
    models["bad-x-high-address"] = address_x_mutant(gate, "restore_high_1")
    mask = once(gate, "input cpu_selected, restore_permit, addr_high, addr_low, output write",
                "input cpu_selected, restore_permit, addr_high, addr_low, ss_unused, output write")
    mask = mask.replace("  .cpu_selected(stack_cpu_word[", "  .ss_unused(ss_wd[0]), .cpu_selected(stack_cpu_word[")
    if mask.count(".ss_unused(ss_wd[0])") != 32:
        raise SystemExit("X-mask did not bind all thirty-two actual joins")
    models["bad-x-write-mask"] = once(mask,
        "assign write = cpu_selected | (restore_permit & addr_high & addr_low);",
        "assign write = (cpu_selected | (restore_permit & addr_high & addr_low)) ^ (ss_unused ^ ss_unused);")
    binary_negatives = ["bad-data", "bad-run", "bad-restore", "bad-reset", "bad-push", "bad-strobe",
                        "bad-lane", "bad-word", "bad-prefix", "bad-return", "bad-high-half", "bad-low-half", "bad-cpu-permit"]
    x_negatives = ["bad-x-call-data", "bad-x-restore-data", "bad-x-write-mask", "bad-x-address",
                   "bad-x-high-address", "bad-x-cpu-guard"]
    if set(models) != {"gold", "gate", *binary_negatives, *x_negatives} or len(models) != 21:
        raise SystemExit("Actual model inventory changed")
    output.mkdir(parents=True, exist_ok=True)
    files = {"original-upd77c25.v": original, "candidate-upd77c25.v": candidate,
             **{name + ".v": model for name, model in models.items()}}
    for name, text in files.items():
        (output / name).write_text(text, encoding="utf-8")
    for name, (path, _) in headers.items():
        (output / f"original-{name}-config.vh").write_bytes(path.read_bytes())
    configurations = (
        ("none", []), ("debug", ["DEBUG"]), ("mk3", ["MK3"]),
        ("mk3-debug", ["MK3", "DEBUG"]), ("mk2", ["MK2"]),
        ("mk2-debug", ["MK2", "DEBUG"]), ("dsp", ["DSP_COMP"]),
        ("dsp-debug", ["DSP_COMP", "DEBUG"]), ("mk3-dsp", ["MK3", "DSP_COMP"]),
        ("mk3-dsp-debug", ["MK3", "DSP_COMP", "DEBUG"]),
        ("mk2-dsp", ["MK2", "DSP_COMP"]), ("mk2-dsp-debug", ["MK2", "DSP_COMP", "DEBUG"]),
    )
    audit = []
    for name, defines in configurations:
        target = "MK2" in defines and "DSP_COMP" in defines
        header, header_blob = headers["dspx" if target else "dsp"]
        selected = {}
        for version in ("original", "candidate"):
            dest = output / f"pp-{name}-{version}.v"
            subprocess.run(["iverilog", "-g2012", "-E", "-I", str(header.parent.resolve())]
                           + ["-D" + item for item in defines]
                           + ["-o", str(dest), str(output / f"{version}-upd77c25.v")], check=True)
            selected[version] = dest.read_text(encoding="utf-8")
        if not all(text.strip() for text in selected.values()):
            raise SystemExit("Empty actual preprocessing output")
        if not target:
            if normalize(selected["candidate"]) != normalize(selected["original"]):
                raise SystemExit("Non-target source changed: " + name)
        else:
            # Invert the actual preprocessed target, including both disabled
            # procedural writes, not merely a separate hand-written model.
            reverted = once(once(selected["candidate"], write, ""), HELPERS, "")
            reverted = once(reverted, "\n    // DSPX stack writes use the parallel word/lane decoder above.\n", "\n" + ref.PUSH + "\n")
            reverted = once(reverted, "\n        // DSPX stack writes use the parallel word/lane decoder above.\n", "\n" + ref.RESTORE + "\n")
            if normalize(reverted) != normalize(selected["original"]):
                raise SystemExit("Target preprocessing changes more than the exact stack integration")
        audit.append(dict(name=name, defines=defines, target=target, headerBlob=header_blob,
                          versions=["original", "candidate"]))
    (output / "preprocessing.json").write_text(json.dumps(audit, indent=2) + "\n")
    (output / "variants.json").write_text(json.dumps(dict(models=list(models), binary=binary_negatives,
                                                        xstate=x_negatives), indent=2) + "\n")
    (output / "production-candidate.diff").write_text("".join(difflib.unified_diff(
        original.splitlines(True), candidate.splitlines(True), "baseline.v", "candidate.v")), encoding="utf-8")
    boundary = dict(baseline=BASELINE, originalBlob=blob(original), candidateBlob=blob(candidate),
        candidateSha256=sha(candidate), wholeOriginalInverse=True, originalStatusLogicUnchanged=True,
        clock="posedge CLK", originalStackHasNoRTLInit=True, stateBits=176, scanBits=11, returnBits=11,
        proofOnlyReturn=PROOF_RETURN, actualNativeReturn=ref.RETURN, inputs=ref.PORTS,
        goldWrite=gold_write, candidateWrite=write, helpers=HELPERS,
        componentTextReferenceRun=41246577034, freshProofRequired=True,
        limits="Full changed stack state and reads only; no mapped/startup/Z/electrical/whole-FPGA/hardware equivalence claim")
    (output / "source-boundary.json").write_text(json.dumps(boundary, indent=2) + "\n")
    (output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(output.iterdir()) if path.is_file() and path.name != "SHA256SUMS"), encoding="utf-8")
    print(f"Whole current-baseline inverse: {blob(original)}; stack-only candidate {blob(candidate)}")
    print("Prepared 21 complete models, all176 next-state bits/both11 reads, 13 binary and6 X negative controls.")
    print("Checked24 actual preprocessing outputs:10 unchanged non-target configurations and2 exact target inverses.")


if __name__ == "__main__":
    main()
