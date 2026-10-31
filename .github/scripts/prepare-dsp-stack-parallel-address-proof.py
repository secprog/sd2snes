#!/usr/bin/env python3
"""Hosted-only proof draft for a measured DSPx parallel stack address decoder.

Never execute locally. Failed native 41241427380 remains rejected.
This prepares text models; the workflow separately performs every strict proof.
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

spec = importlib.util.spec_from_file_location(
    "late_low_reference", Path(__file__).with_name("prepare-dsp-stack-late-low-proof.py"))
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
ref = old.ref
PROOF_RETURN = old.PROOF_RETURN

HELPERS = """// Preserve both original procedural ancestor guards, including X handling.
(* LUT_MAP="yes" *)
module dsp_stack_run_permit(input reset_n, frozen, output reg permit);
always @* begin
  permit = 1'b0;
  if (reset_n & ~frozen) permit = 1'b1;
end
endmodule

// The restore strobe joins the unchanged procedural reset/freeze ancestors.
(* LUT_MAP="yes" *)
module dsp_stack_restore_write_permit(input reset_n, frozen, ss_wr, output reg permit);
always @* begin
  permit = 1'b0;
  if (reset_n & ~frozen) begin
  end else if (reset_n & frozen) begin
    if (ss_wr) permit = 1'b1;
  end
end
endmodule

// Four address inputs are compared in parallel before the final word gate.
(* LUT_MAP="yes" *)
module dsp_stack_nibble_match #(parameter [3:0] VALUE = 4'd0)(
  input [3:0] addr, output reg selected
);
always @* begin
  selected = 1'b0;
  if (addr == VALUE) selected = 1'b1;
end
endmodule

// Four real inputs; retain the original run, CALL and word priorities.
(* LUT_MAP="yes" *)
module dsp_stack_cpu_word_select(
  input reset_n, frozen, push_now, sp_selected, output reg selected
);
always @* begin
  selected = 1'b0;
  if (reset_n & ~frozen) begin
    if (push_now) begin
      if (sp_selected) selected = 1'b1;
    end
  end
end
endmodule

// Four real inputs; both restore address halves enter this final LUT directly.
(* LUT_MAP="yes" *)
module dsp_stack_parallel_join(
  input cpu_selected, restore_permit, addr_high, addr_low, output write
);
assign write = cpu_selected | (restore_permit & addr_high & addr_low);
endmodule
"""

def writes():
    lines = [
        '(* KEEP="TRUE" *) wire stack_late_run, stack_restore_write;',
        '(* KEEP="TRUE" *) wire [15:0] stack_sp_match, stack_cpu_word, stack_addr_low;',
        '(* KEEP="TRUE" *) wire [2:0] stack_addr_high;',
        "wire [15:0] stack_late_low, stack_late_high;",
        "wire [10:0] stack_late_push_data = pc + 1;",
        "wire [10:0] stack_late_data = stack_late_run ? stack_late_push_data : {ss_wd[2:0], ss_wd};",
        "dsp_stack_run_permit run_permit(.reset_n(RST), .frozen(ss_frozen), .permit(stack_late_run));",
        "dsp_stack_restore_write_permit restore_write_permit(",
        "  .reset_n(RST), .frozen(ss_frozen), .ss_wr(ss_wr), .permit(stack_restore_write)",
        ");",
    ]
    for high in range(3):
        lines += [
            f"dsp_stack_nibble_match #(.VALUE(4'd{high + 3})) restore_high_{high}(",
            "  .addr(ss_wa[7:4]),", f"  .selected(stack_addr_high[{high}])", ");",
        ]
    for low in range(16):
        lines += [
            f"dsp_stack_nibble_match #(.VALUE(4'd{low})) restore_low_{low}(",
            "  .addr(ss_wa[3:0]),", f"  .selected(stack_addr_low[{low}])", ");",
        ]
    for word in range(16):
        address = 0x34 + 2 * word
        high, low = (address >> 4) - 3, address & 15
        lines += [
            f"dsp_stack_nibble_match #(.VALUE(4'd{word})) stack_pointer_{word}(",
            "  .addr(regs_sp),", f"  .selected(stack_sp_match[{word}])", ");",
            f"dsp_stack_cpu_word_select cpu_word_{word}(",
            "  .reset_n(RST), .frozen(ss_frozen), .push_now(push_now),",
            f"  .sp_selected(stack_sp_match[{word}]), .selected(stack_cpu_word[{word}])", ");",
        ]
        for lane, index in (("low", low), ("high", low + 1)):
            lines += [
                f"dsp_stack_parallel_join late_{lane}_{word}(",
                f"  .cpu_selected(stack_cpu_word[{word}]), .restore_permit(stack_restore_write),",
                f"  .addr_high(stack_addr_high[{high}]), .addr_low(stack_addr_low[{index}]),",
                f"  .write(stack_late_{lane}[{word}])", ");",
            ]
        lines += [
            "always @(posedge CLK) begin",
            f"  if (stack_late_low[{word}]) stack[{word}][7:0] <= stack_late_data[7:0];",
            f"  if (stack_late_high[{word}]) stack[{word}][10:8] <= stack_late_data[10:8];",
            "end",
        ]
    return "\n".join(lines) + "\n"


def once(text, before, after):
    if text.count(before) != 1:
        raise SystemExit(f"Ambiguous source or control boundary: {before!r}")
    return text.replace(before, after, 1)


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def blob(text):
    raw = text.encode()
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def normalize(text):
    return re.sub(r"\s+", "", ref.without_comments(text))


def replace_join_input(gate, word, lane, before, after):
    fragment = re.search(rf"dsp_stack_parallel_join late_{lane}_{word}\(.*?\n\);", gate, flags=re.S)
    if fragment is None:
        raise SystemExit("Missing final word/lane instance for negative control")
    changed = once(fragment.group(), before, after)
    return once(gate, fragment.group(), changed)


def address_x_mutant(gate, instance):
    # Mutate only the specified address comparator; the SP comparator stays exact.
    helper = re.search(r"module dsp_stack_nibble_match .*?\nendmodule\n", HELPERS, flags=re.S)
    if helper is None:
        raise SystemExit("Missing complete four-bit comparison helper")
    changed = once(helper.group(), "module dsp_stack_nibble_match", "module dsp_stack_nibble_match_x_bad")
    changed = once(changed, "if (addr == VALUE) selected = 1'b1;",
                   "if ((addr == VALUE) !== 1'b0) selected = 1'b1;")
    pattern = rf"dsp_stack_nibble_match (#\(\.VALUE\(4'd[0-9]+\)\) {instance}\()"
    selected = re.findall(pattern, gate)
    if len(selected) != 1:
        raise SystemExit("Ambiguous X-address target instance")
    return once(gate, "dsp_stack_nibble_match " + selected[0],
                "dsp_stack_nibble_match_x_bad " + selected[0]) + changed


def main():
    source_name, parent_name, output_name = sys.argv[1:]
    source, parent_dir, output = Path(source_name), Path(parent_name), Path(output_name)
    original = source.read_bytes().decode("utf-8")
    if blob(original) != ref.EXPECTED_BLOB:
        raise SystemExit("Original production source blob changed")
    headers = {
        "dsp": (source.parent / "config.vh", "1a9a6a14b8b08eb6e931ce2320326e913aa8000e"),
        "dspx": (source.parent.parent / "sd2snes_dspx" / "config.vh", "4cf8aa3111a5bf103065cded5fb77fdfc39ee239"),
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
        raise SystemExit("Unmodelled original stack declaration, access, init or reset")
    push_context = ("always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n"
                    "`ifdef MK2\n    push_now <= 1'b0;\n" + ref.PUSH + "\n`endif\n")
    if original.count(push_context) != 1:
        raise SystemExit("Original CALL clock, guard or priority changed")
    restore_context = re.search(
        r"  end else if\(RST & ss_frozen\) begin\n"
        r"    // savestate RESTORE.*?\n    if\(ss_wr\) begin\n"
        r"      if\(ss_wa >= 8'h34 && ss_wa <= 8'h53\) begin\n"
        + re.escape(ref.RESTORE) + r"\n      end else case\(ss_wa\)", original, flags=re.S)
    if restore_context is None:
        raise SystemExit("Original restore clock, range, ancestors or priority changed")
    if original.count("`ifndef MK2\n" + ref.OTHER_PUSH + "\n`endif") != 1:
        raise SystemExit("Original non-MkII CALL boundary changed")

    # Source proof provenance/full ZIP is checked by the pinned downloader first.
    # Independently bind its complete source and invert both earlier changes.
    parent = (parent_dir / "candidate.v").read_bytes().decode("utf-8")
    late = (parent_dir / "original.v").read_bytes().decode("utf-8")
    data = json.loads((parent_dir / "proof-data.json").read_text())["dsp"]
    fixtures = Path(__file__).parent.parent / "fixtures"
    if (parent_dir / "proof-data.json").read_bytes() != (fixtures / "slow-path-proof-data.json").read_bytes():
        raise SystemExit("Original source proof data differs from pinned fixture")
    if late.encode() != (fixtures / "slow-path-parent-dsp.v").read_bytes():
        raise SystemExit("Original stack parent differs from pinned fixture")
    if sha(parent) != "95aa37433035439b6998e09e6fb2d85d934ea42f31f9666fd02085bf428e7007" or blob(parent) != "5fd95bbd641a0068fcca947bd9a2a26da67a4553":
        raise SystemExit("Rejected status/native parent source differs")
    if sha(late) != "b536c4ab74015b76751d0544e48cce23a458b70b2e0e34f101bdd18421907d4a":
        raise SystemExit("Previously proved late-low stack source differs")
    if sha(parent) != data["candidateSha256"] or sha(late) != data["parentSha256"]:
        raise SystemExit("Status proof data/source bindings changed")
    if not parent.startswith(data["define"]) or not parent.endswith(data["appendix"]):
        raise SystemExit("Status scope boundaries changed")
    status_inverse = parent.removeprefix(data["define"]).removesuffix(data["appendix"])
    status_inverse = once(status_inverse, data["inserted"], "")
    for assignment in data["assignments"]:
        status_inverse = once(status_inverse, "\n`ifndef DSP_STATUS_LATE_CONTROL\n" + assignment + "\n`endif\n", assignment)
    if status_inverse != late or len(data["assignments"]) != 34:
        raise SystemExit("Complete status source inverse failed")
    old_write = old.writes()
    old_suffix = "\n" + old.scoped(old.HELPERS) + "\n"
    if not late.endswith(old_suffix):
        raise SystemExit("Old stack helper scope changed")
    index = ref.WRITE_INDEX + "\n" + old.scoped(old_write)
    push = "`ifdef DSP_COMP\n    // Target stack writes are below.\n`else\n" + ref.PUSH + "\n`endif"
    restore = ("`ifdef MK2\n`ifdef DSP_COMP\n        // Target stack writes are below.\n"
               "`else\n" + ref.RESTORE + "\n`endif\n`else\n" + ref.RESTORE + "\n`endif")
    recovered = late.removesuffix(old_suffix)
    recovered = once(once(once(recovered, index, ref.WRITE_INDEX), restore, ref.RESTORE), push, ref.PUSH)
    if recovered != original:
        raise SystemExit("Complete original production source inverse failed")

    write = writes()
    candidate = once(once(parent, old_write, write), old.HELPERS, HELPERS)
    if sha(candidate) != "3a0af6c79f2e0d775414503780c0d6d12f89bdfd119fedcf9d382df723c9c357":
        raise SystemExit("Complete new source differs from independently prepared candidate")
    if once(once(candidate, write, old_write), HELPERS, old.HELPERS) != parent:
        raise SystemExit("Complete new source inverse failed")
    clocked = r"always @\(posedge CLK\) begin.*?\nend"
    old_blocks = re.findall(clocked, old_write, flags=re.S)
    new_blocks = re.findall(clocked, write, flags=re.S)
    if len(old_blocks) != 16 or old_blocks != new_blocks:
        raise SystemExit("Actual sixteen state-write blocks changed")
    if ref.RETURN not in candidate or candidate.count(ref.DECL) != 1:
        raise SystemExit("Native return or storage declaration changed")

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
    files = {"original-upd77c25.v": original, "parent-upd77c25.v": parent,
             "candidate-upd77c25.v": candidate, **{name + ".v": model for name, model in models.items()}}
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
        for version in ("original", "parent", "candidate"):
            dest = output / f"pp-{name}-{version}.v"
            subprocess.run(["iverilog", "-g2012", "-E", "-I", str(header.parent.resolve())]
                           + ["-D" + item for item in defines]
                           + ["-o", str(dest), str(output / f"{version}-upd77c25.v")], check=True)
            selected[version] = dest.read_text(encoding="utf-8")
        if not all(text.strip() for text in selected.values()):
            raise SystemExit("Empty actual preprocessing output")
        if not target:
            if len({normalize(text) for text in selected.values()}) != 1:
                raise SystemExit(f"Non-target production/parent/candidate mismatch: {name}")
        else:
            reverted = once(once(selected["candidate"], write, old_write), HELPERS, old.HELPERS)
            if normalize(reverted) != normalize(selected["parent"]):
                raise SystemExit("Target preprocessing changes more than the decoder")
        audit.append(dict(name=name, defines=defines, target=target, headerBlob=header_blob,
                          versions=["original", "parent", "candidate"]))
    (output / "preprocessing.json").write_text(json.dumps(audit, indent=2) + "\n")
    (output / "variants.json").write_text(json.dumps(dict(models=list(models), binary=binary_negatives,
                                                        xstate=x_negatives), indent=2) + "\n")
    for filename, before, after in (("candidate.diff", parent, candidate), ("production-candidate.diff", original, candidate)):
        (output / filename).write_text("".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                                                 "before.v", "candidate.v")), encoding="utf-8")
    (output / "parallel-address-generator.py.txt").write_bytes(Path(__file__).read_bytes())
    boundary = dict(originalBlob=blob(original), parentBlob=blob(parent), candidateBlob=blob(candidate),
        candidateSha256=sha(candidate), wholeOriginalInverse=True, wholeParentInverse=True,
        all16ClockedBlocksByteIdentical=True, clock="posedge CLK", originalStackHasNoRTLInit=True,
        stateBits=176, scanBits=11, returnBits=11, proofOnlyReturn=PROOF_RETURN,
        actualNativeReturn=ref.RETURN, inputs=ref.PORTS, goldWrite=gold_write, candidateWrite=write,
        helpers=HELPERS, unchangedStatusProofRun=41235863589, failedNativeBasis=41241427380,
        limits="No local proof, no mapped/startup equivalence, no Z/electrical/whole-FPGA/native timing/hardware result")
    (output / "source-boundary.json").write_text(json.dumps(boundary, indent=2) + "\n")
    (output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(output.iterdir()) if path.is_file() and path.name != "SHA256SUMS"), encoding="utf-8")
    print(f"Exact source inverse: original {blob(original)}, rejected parent {blob(parent)}, new candidate {blob(candidate)}")
    print("All176 state bits and both actual read expressions; 21 complete models; 13 binary and 6 binary-equivalent X negatives prepared")
    print("Ten non-target/two target configurations checked using all36 actual Icarus preprocessing outputs")
    print("This is preparation only. Every state-view, miter, witness, source/input and later native gate remains mandatory.")


if __name__ == "__main__":
    main()
