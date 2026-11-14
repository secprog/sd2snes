"""Prove every register-file writeback bit against unchanged MkIII in Actions.

Extract the production reset/advance/complete guards and destination cases.
All operands, old registers, decode bits and controls are unconstrained. The
negative control loses one POP destination's SP write and must be rejected.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
registers = {"SP_r": 16, **{name + "_r": 8 for name in "AFBCDEHL"}}
with tempfile.TemporaryDirectory(prefix="gbc-writeback-proof-") as tmp:
    work = Path(tmp)
    blocks = []
    for board, prefix in (("MK2", "actual"), ("MK3", "reference")):
        preprocessed = work / f"cpu-{board}.v"
        subprocess.run(["iverilog", "-E", f"-D{board}", "-I", str(root / "verilog/sd2snes_gbc"),
                        "-o", str(preprocessed), str(root / "verilog/sd2snes_gbc/sgb_cpu.v")], check=True)
        cpu = preprocessed.read_text()
        marker = "always @(posedge CLK) begin\n  if (cpu_ireset_r) begin\n    exe_ctr_r <= 0;"
        start = cpu.index(marker) + len("always @(posedge CLK) begin")
        end = cpu.index("endcase", start) + len("endcase")
        body = cpu[start:end] + "\nend\nend\nend\n"
        # These three independent control-register writes precede writeback;
        # the register-file proof neither observes nor changes them.
        body = re.sub(r"\b(?:exe_ctr_r|exe_ime_r|dbg_advance_r)\s*<=\s*[^;]+;", "", body)
        definitions = ""
        if board == "MK2":
            definitions = "\n".join(re.findall(
                r"wire\s+(?:\[[^\]]+\]\s+)?mk2_sp_write(?:_data)?\s*=.*?;", cpu, re.S))
            sp_start = cpu.index("always @(posedge CLK) begin", cpu.index("wire mk2_sp_write"))
            sp_end = cpu.index("\nend", sp_start)
            body += cpu[sp_start + len("always @(posedge CLK) begin"):sp_end]
        body = re.sub(r"//[^\n]*", "", body)

        def next_state(match):
            lhs = match[1]
            names = re.findall(r"\b\w+_r\b", lhs)
            if not names or any(name not in registers for name in names):
                raise RuntimeError("Unexpected writeback target: " + lhs)
            for name in registers:
                lhs = re.sub(r"\b" + name + r"\b", prefix + "_" + name, lhs)
            return lhs + " = " + match[2] + ";"

        body, count = re.subn(r"(\{[^{}]+\}|\w+(?:\[[^\]]+\])?)\s*<=\s*([^;]+);", next_state, body)
        if count < 20 or "<=" in body:
            raise RuntimeError("Incomplete register writeback extraction")
        declarations = "\n".join(f"reg [{width - 1}:0] {prefix}_{name};" for name, width in registers.items())
        defaults = "\n".join(f"{prefix}_{name} = {name};" for name in registers)
        blocks.append(definitions + "\n" + declarations + "\nalways @* begin\n" + defaults + body + "\nend\n")

    inputs = ", ".join(f"input [{width - 1}:0] {name}" for name, width in registers.items())
    body = "module check(" + inputs + """,
 input cpu_ireset_r,CLK_BUS_EDGE,exe_advance_r,exe_complete_r,
 input exe_res_sp_mod_r,exe_res_hl_mod_r,
 input [15:0] IFD_EXE_decode,exe_res_r,exe_res_sp_r,exe_res_hl_r,
 input [7:0] exe_res_cc_r, output equivalent);
""" + "\n".join(blocks)
    actual = "{" + ",".join("actual_" + name for name in registers) + "}"
    reference = "{" + ",".join("reference_" + name for name in registers) + "}"
    body += f"assign equivalent = {actual} == {reference};\nendmodule\n"
    for negative in (False, True):
        candidate = body
        if negative:
            candidate, count = re.subn(r"IFD_EXE_decode\[11:8\] == 4'd5\s*\|\|", "", candidate, count=1)
            if count != 1:
                raise RuntimeError("Cannot construct the missing-POP-DE negative control")
        source = work / ("negative.v" if negative else "actual.v")
        source.write_text(candidate)
        script = work / "proof.ys"
        script.write_text(f'read_verilog "{source}"\nprep -top check\n'
                          'sat -verify -prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the missing-POP-DE control\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("Register-file next-state equivalence failed\n" + log)
    print("PASS: all 80 register-file bits preserve every reset, hold and write condition; "
          "SAT rejects the missing-POP-DE control")
