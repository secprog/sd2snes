#!/usr/bin/env python3
"""Prepare a source-bound DSPx freeze-buffer experiment for hosted proof."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "read_index", Path(__file__).with_name("prepare-dsp-stack-read-index-proof.py")
)
read_index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(read_index)

SOURCE_BLOB = "ba14f5b6dd198fbb5645f005fb3784890beec2c4"
DECL = "reg  ss_frozen; initial ss_frozen = 1'b0;"
BUFFER = """`ifdef MK2
`ifdef DSP_COMP
wire ss_frozen_global;
BUFG dspx_freeze_bufg (.I(ss_frozen), .O(ss_frozen_global));
`endif
`endif"""
INSTANCE = "BUFG dspx_freeze_bufg (.I(ss_frozen), .O(ss_frozen_global));"
RUN = "  if(RST & ~ss_frozen) begin"
RESTORE = "  end else if(RST & ss_frozen) begin"


def git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def normalize(text):
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    return re.sub(r"\s+", "", text)


def scoped(original, selected):
    return ("`ifdef MK2\n`ifdef DSP_COMP\n" + selected + "\n`else\n"
            + original + "\n`endif\n`else\n" + original + "\n`endif")


def change_nth(text, old, new, index, expected):
    if text.count(old) != expected:
        raise SystemExit(f"Unexpected mutation count for {old!r}: {text.count(old)}")
    pieces = text.split(old)
    return old.join(pieces[:index + 1]) + new + old.join(pieces[index + 1:])


def guards(source):
    run = re.findall(r"(?m)^  if\((RST & [^)]*)\) begin$", source)
    restore = re.findall(r"(?m)^  end else if\((RST & [^)]*)\) begin$", source)
    if len(run) != 4 or len(restore) != 4:
        raise SystemExit(f"Unexpected run/restore guards: {run!r} {restore!r}")
    return run, restore


def model(name, configured_source, buffered, bad_x=False):
    run, restore = guards(configured_source)
    if buffered:
        if configured_source.count("wire ss_frozen_global;") != 1:
            raise SystemExit("Buffered signal declaration is missing or duplicated")
        inst = re.findall(
            r"(?m)^BUFG dspx_freeze_bufg \(\.I\(([^)]*)\), \.O\(ss_frozen_global\)\);$",
            configured_source,
        )
        if len(inst) != 1:
            raise SystemExit(f"Unexpected BUFG instance: {inst!r}")
        connection = "wire ss_frozen_global;\n" + (
            f"BUFG dspx_freeze_bufg (.I({inst[0]}), .O(ss_frozen_global));\n"
        )
        seen = "ss_frozen_global"
    else:
        connection = ""
        seen = "ss_frozen"
    lines = [
        f"module {name}(input RST, input ss_frozen,",
        "  output [3:0] run_guard, output [3:0] restore_guard,",
        "  output reg [7:0] action, output frozen_seen);",
        connection,
        f"assign frozen_seen = {seen};",
    ]
    for i in range(4):
        lines += [f"assign run_guard[{i}] = {run[i]};",
                  f"assign restore_guard[{i}] = {restore[i]};"]
    lines += ["always @* begin", "  action = 8'b0;"]
    for i in range(4):
        lines += [f"  if ({run[i]}) action[{i * 2} +: 2] = 2'b01;",
                  f"  else if ({restore[i]}) action[{i * 2} +: 2] = 2'b10;"]
    lines += ["end", "endmodule"]
    if buffered:
        primitive = "assign O = (I === 1'b1);" if bad_x else "assign O = I;"
        lines += ["module BUFG(input I, output O);", primitive, "endmodule"]
    return "\n".join(lines) + "\n"


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: prepare-dsp-freeze-bufg-proof.py SOURCE OUTPUT_DIR")
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    if git_blob(raw) != SOURCE_BLOB:
        raise SystemExit(f"Unexpected source blob: {git_blob(raw)}")
    original = raw.decode("utf-8")
    if original.count(DECL) != 1 or original.count(RUN) != 4 or original.count(RESTORE) != 4:
        raise SystemExit("The original declaration or eight control guards changed")
    if re.search(r"\b(?:ss_frozen_global|dspx_freeze_bufg)\b", original):
        raise SystemExit("The buffer identifiers already occur in the original source")
    wrapped_run = scoped(RUN, RUN.replace("ss_frozen", "ss_frozen_global"))
    wrapped_restore = scoped(RESTORE, RESTORE.replace("ss_frozen", "ss_frozen_global"))
    candidate = original.replace(DECL, DECL + "\n" + BUFFER, 1)
    candidate = candidate.replace(RUN, wrapped_run).replace(RESTORE, wrapped_restore)
    if candidate.count(wrapped_run) != 4 or candidate.count(wrapped_restore) != 4:
        raise SystemExit("Candidate guard insertion is incomplete")
    recovered = candidate.replace(DECL + "\n" + BUFFER, DECL, 1)
    recovered = recovered.replace(wrapped_run, RUN).replace(wrapped_restore, RESTORE)
    if recovered != original:
        raise SystemExit("The candidate does not recover the exact original source")

    non_target = (set(), {"DEBUG"}, {"MK3"}, {"MK3", "DEBUG"},
                  {"MK2"}, {"MK2", "DEBUG"}, {"DSP_COMP"},
                  {"DSP_COMP", "DEBUG"}, {"MK3", "DSP_COMP"},
                  {"MK3", "DSP_COMP", "DEBUG"})
    for defines in non_target:
        before = read_index.configured(original, defines)
        after = read_index.configured(candidate, defines)
        if normalize(before) != normalize(after):
            raise SystemExit(f"Non-target configuration changed: {sorted(defines)}")

    original_target = read_index.configured(original, {"MK2", "DSP_COMP"})
    target = read_index.configured(candidate, {"MK2", "DSP_COMP"})
    for defines in ({"MK2", "DSP_COMP"}, {"MK2", "DSP_COMP", "DEBUG"}):
        selected = read_index.configured(candidate, defines)
        if selected.count(INSTANCE) != 1 or selected.count("ss_frozen_global") != 10:
            raise SystemExit(f"Unexpected target buffer selection: {sorted(defines)}")
        run, restore = guards(selected)
        if run != ["RST & ~ss_frozen_global"] * 4 or restore != ["RST & ss_frozen_global"] * 4:
            raise SystemExit("A target guard is not connected to the buffer output")
    if guards(original_target) != (["RST & ~ss_frozen"] * 4, ["RST & ss_frozen"] * 4):
        raise SystemExit("Original target guards differ from the modeled boundary")

    variants = {"gate": target}
    variants["bad-invert"] = target.replace(INSTANCE, INSTANCE.replace(".I(ss_frozen)", ".I(~ss_frozen)"), 1)
    variants["bad-stuck"] = target.replace(INSTANCE, INSTANCE.replace(".I(ss_frozen)", ".I(1'b0)"), 1)
    for i in range(4):
        variants[f"bad-run{i}"] = change_nth(
            target, "  if(RST & ~ss_frozen_global) begin",
            "  if(RST & ss_frozen_global) begin", i, 4)
        variants[f"bad-restore{i}"] = change_nth(
            target, "  end else if(RST & ss_frozen_global) begin",
            "  end else if(RST & ~ss_frozen_global) begin", i, 4)
    if any(value == target for name, value in variants.items() if name != "gate"):
        raise SystemExit("A binary negative control was not applied")

    files = {"original-upd77c25.v": original, "candidate-upd77c25.v": candidate,
             "gold.v": model("gold", original_target, False)}
    for name, selected in variants.items():
        files[name + ".v"] = model("gate", selected, True)
        if name != "gate":
            files[name + "-source.v"] = selected
    files["bad-x-buffer.v"] = model("gate", target, True, bad_x=True)
    output.mkdir(parents=True, exist_ok=True)
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
    (output / "guard-bindings.txt").write_text(
        f"Original: {guards(original_target)!r}\nCandidate: {guards(target)!r}\n"
        f"BUFG source instance: {INSTANCE}\n", encoding="utf-8")
    print(f"Original blob {SOURCE_BLOB}; candidate blob {git_blob(candidate.encode('utf-8'))}.")
    print("The full original source was recovered; ten non-target and two target selections audited.")
    print("Prepared actual four run/restore guard pairs, procedural priorities, BUFG model and mutations.")


if __name__ == "__main__":
    main()
