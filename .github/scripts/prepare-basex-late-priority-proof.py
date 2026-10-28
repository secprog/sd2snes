#!/usr/bin/env python3
"""Prepare a hosted-only feasibility proof of a different late priority boundary."""

import difflib
import hashlib
import importlib.util
import re
import subprocess
import sys
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "reference", Path(__file__).with_name("prepare-basex-write-gate-experiment.py")
)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)

UNLOCK = "assign snescmd_unlock = snescmd_unlock_r | exe_unlock_r;"
HELPERS = """// Four source inputs, including both original unlock states.
// Keep procedural guards in the permit and word-selection components.
(* LUT_MAP="yes" *)
module cheat_command_permit(
  input command_unlock, exe_unlock, enabled, strobe,
  output reg permit
);
always @* begin
  permit = 1'b1;
  if ((command_unlock | exe_unlock) & enabled & strobe) permit = 1'b0;
end
endmodule

module cheat_program_select #(parameter [2:0] WORD = 3'd0)(
  input reset, pgm_we, input [2:0] index,
  output reg selected
);
always @* begin
  selected = 1'b0;
  if (reset) begin
  end else if (pgm_we) begin
    if (index < 6) begin
      if (index == WORD) selected = 1'b1;
    end
  end
end
endmodule

// Preserve a separate two-input final gate after early word qualification.
(* LUT_MAP="yes" *)
module cheat_program_late_and(input selected, permit, output write);
assign write = selected & permit;
endmodule
"""
PORTS = """module cheat_programming_model(
  input CLK, SNES_reset_strobe, snescmd_unlock_r, exe_unlock_r,
  input snescmd_enable, SNES_wr_strobe, pgm_we,
  input [2:0] pgm_idx, input [31:0] pgm_in,
  output [191:0] state
);
wire clk = CLK;
wire snescmd_unlock;
""" + UNLOCK + "\n"


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def normalize(text):
    return re.sub(r"\s+", "", ref.without_comments(text))


def scoped_only(text):
    return "`ifdef MK2\n`ifdef BASE_EXT\n" + text + "\n`endif\n`endif"


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"Ambiguous source or mutation boundary: {old!r}")
    return text.replace(old, new, 1)


def late_writes():
    lines = [
        "wire cheat_late_permit;",
        "wire [5:0] cheat_early_selected, cheat_late_write;",
        "cheat_command_permit command_permit(",
        "  .command_unlock(snescmd_unlock_r), .exe_unlock(exe_unlock_r),",
        "  .enabled(snescmd_enable), .strobe(SNES_wr_strobe), .permit(cheat_late_permit)",
        ");",
    ]
    for word in range(6):
        lines += [
            f"cheat_program_select #(.WORD(3'd{word})) early_select_{word}(",
            "  .reset(SNES_reset_strobe), .pgm_we(pgm_we), .index(pgm_idx),",
            f"  .selected(cheat_early_selected[{word}])",
            ");",
            f"cheat_program_late_and late_and_{word}(",
            f"  .selected(cheat_early_selected[{word}]), .permit(cheat_late_permit),",
            f"  .write(cheat_late_write[{word}])",
            ");",
            "always @(posedge clk) begin",
            f"  if (cheat_late_write[{word}]) begin",
            f"    cheat_addr[{word}] <= pgm_in[31:8];",
            f"    cheat_data[{word}] <= pgm_in[7:0];",
            "  end",
            "end",
        ]
    return "\n".join(lines) + "\n"


def model(write, helpers=""):
    views = "".join(
        f"assign state[{word * 32} +: 32] = {{cheat_addr[{word}], cheat_data[{word}]}};\n"
        for word in range(6)
    )
    return PORTS + ref.DECL + "\n" + ref.STROBE + "\n" + write + "\n" + views + "endmodule\n" + helpers


def main():
    source, output = map(Path, sys.argv[1:])
    raw = source.read_bytes()
    if blob(raw) != ref.EXPECTED_BLOB:
        raise SystemExit(f"Unexpected complete cheat source blob: {blob(raw)}")
    original = raw.decode("utf-8")
    for fragment in (ref.DECL, ref.WRITES, ref.STROBE, ref.PROGRAM, UNLOCK):
        if original.count(fragment) != 1:
            raise SystemExit(f"Original source boundary changed: {fragment!r}")
    if re.findall(r"^\s*`(\w+)", original, flags=re.M) != ["timescale"]:
        raise SystemExit("Unreviewed original preprocessor directives")
    if len(re.findall(r"^\s*module\b", original, flags=re.M)) != 1:
        raise SystemExit("Expected one complete original cheat module")
    if re.search(r"\bcheat_(?:late_|early_|command_permit|program_select|program_late_and)", original):
        raise SystemExit("New proof identifiers collide with the original source")

    remainder = ref.without_comments(original.replace(ref.DECL, "").replace(ref.WRITES, ""))
    for name in ("cheat_addr", "cheat_data"):
        accesses = re.findall(r"\b" + name + r"\[([^\]]+)\]", remainder)
        if sorted(accesses) != [str(i) for i in range(6)]:
            raise SystemExit(f"Unmodelled {name} access: {accesses}")
        if re.search(r"\b" + name + r"\b", re.sub(r"\b" + name + r"\[[^\]]+\]", "", remainder)):
            raise SystemExit(f"Unmodelled {name} declaration or access")

    write = late_writes()
    wrapped = ("`ifdef MK2\n`ifdef BASE_EXT\n"
               "        // The array writes are below, with the same guards.\n"
               "`else\n" + ref.WRITES + "\n`endif\n`else\n" + ref.WRITES + "\n`endif")
    program = replace_once(ref.PROGRAM, ref.WRITES, wrapped) + "\n\n" + scoped_only(write)
    candidate = replace_once(original, ref.PROGRAM, program) + "\n" + scoped_only(HELPERS) + "\n"
    recovered = candidate.removesuffix("\n" + scoped_only(HELPERS) + "\n")
    recovered = replace_once(recovered, program, ref.PROGRAM)
    if recovered != original:
        raise SystemExit("Complete source inverse failed")

    # This projection keeps each ancestor of the original two array writes.
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
end
"""
    gold, gate = model(gold_write), model(write, HELPERS)
    mutants = {
        "bad-data": ("cheat_data[0] <= pgm_in[7:0];", "cheat_data[0] <= pgm_in[7:0] ^ 8'h01;"),
        "bad-unlock": ("(command_unlock | exe_unlock)", "exe_unlock"),
        "bad-exe": ("(command_unlock | exe_unlock)", "command_unlock"),
        "bad-enable": (" & enabled & strobe", " & strobe"),
        "bad-strobe": (" & enabled & strobe", " & enabled"),
        "bad-reset": ("if (reset) begin", "if (1'b0) begin"),
        "bad-pgm": ("else if (pgm_we) begin", "else if (1'b1) begin"),
        "bad-index": ("#(.WORD(3'd0)) early_select_0", "#(.WORD(3'd1)) early_select_0"),
        "bad-x-command": (
            "always @* begin\n  permit = 1'b1;\n  if ((command_unlock | exe_unlock) & enabled & strobe) permit = 1'b0;\nend",
            "always @* permit = ~((command_unlock | exe_unlock) & enabled & strobe);"),
        "bad-x-select": (
            "always @* begin\n  selected = 1'b0;\n  if (reset) begin\n  end else if (pgm_we) begin\n    if (index < 6) begin\n      if (index == WORD) selected = 1'b1;\n    end\n  end\nend",
            "always @* selected = ~reset & pgm_we & (index == WORD);"),
        "bad-x-data": ("cheat_data[0] <= pgm_in[7:0];",
                       "cheat_data[0] <= pgm_in[7:0] ^ {8{(snescmd_unlock_r ^ snescmd_unlock_r)}};"),
    }
    files = {"original-cheat.v": original, "candidate-cheat.v": candidate,
             "gold.v": gold, "gate.v": gate}
    for name, (before, after) in mutants.items():
        files[name + ".v"] = replace_once(gate, before, after)
    output.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (output / name).write_text(text, encoding="utf-8")

    configurations = (
        ("none", []), ("debug", ["DEBUG"]), ("mk3", ["MK3"]),
        ("mk3-debug", ["MK3", "DEBUG"]), ("mk2", ["MK2"]),
        ("mk2-debug", ["MK2", "DEBUG"]), ("base", ["BASE_EXT"]),
        ("base-debug", ["BASE_EXT", "DEBUG"]), ("mk3-base", ["MK3", "BASE_EXT"]),
        ("mk3-base-debug", ["MK3", "BASE_EXT", "DEBUG"]),
        ("mk2-base", ["MK2", "BASE_EXT"]), ("mk2-base-debug", ["MK2", "BASE_EXT", "DEBUG"]),
    )
    audit = []
    for cfg, defines in configurations:
        selected = []
        for version in ("original", "candidate"):
            target = output / f"pp-{cfg}-{version}.v"
            command = ["iverilog", "-g2012", "-E"] + ["-D" + flag for flag in defines]
            subprocess.run(command + ["-o", str(target), str(output / f"{version}-cheat.v")], check=True)
            selected.append(target.read_text(encoding="utf-8"))
        if not all(text.strip() for text in selected):
            raise SystemExit(f"Empty actual preprocessing output: {cfg}")
        is_target = "MK2" in defines and "BASE_EXT" in defines
        if not is_target and normalize(selected[0]) != normalize(selected[1]):
            raise SystemExit(f"Non-target preprocessing changed: {cfg}")
        if is_target:
            if selected[1].count(write) != 1 or selected[1].count(HELPERS) != 1:
                raise SystemExit(f"Wrong target preprocessing selection: {cfg}")
            # Remove exactly the known replacements from the actual preprocessor result.
            restored = selected[1].replace(write, "", 1).replace(HELPERS, "", 1)
            old_without_writes = replace_once(selected[0], ref.WRITES, "")
            if normalize(restored) != normalize(old_without_writes):
                raise SystemExit(f"Target changed more than the two array writes: {cfg}")
        audit.append(f"{cfg}: {'target replacements verified' if is_target else 'non-target token identity'}\n")
    (output / "preprocessing.txt").write_text("".join(audit), encoding="utf-8")
    (output / "candidate.diff").write_text("".join(difflib.unified_diff(
        original.splitlines(True), candidate.splitlines(True), "original-cheat.v", "candidate-cheat.v")), encoding="utf-8")
    files_to_hash = sorted(path for path in output.iterdir() if path.is_file())
    (output / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in files_to_hash), encoding="utf-8")
    print(f"Pinned original blob {blob(raw)}; runner-only candidate blob {blob(candidate.encode('utf-8'))}.")
    print("Complete source inverse and actual Icarus preprocessing: ten non-target, two target configurations.")
    print("Six unchanged words, all192 state bits, both independent unlock inputs; no state/clock/cycle added.")
    print("Feasibility only: different four-input command boundary plus separate final two-input gates.")
    print("No native mapping, routing/timing, generated-input integrity or hardware result is implied.")


if __name__ == "__main__":
    main()
