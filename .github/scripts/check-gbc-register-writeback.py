"""Prove every register-file writeback bit against unchanged MkIII in Actions.

Extract the production reset/advance/complete guards and destination cases.
All operands, old registers, decode bits and controls are unconstrained. The
negative controls lose a POP destination's SP write and swap the shared byte
selector. Both must be rejected.
"""
from pathlib import Path
from collections import Counter
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
        end = cpu.index("// delay 1 inst because fetch", start)
        body = cpu[start:end] + "\nend\nend\nend\n"
        debug_start = cpu.index("// debug writes", end)
        debug_end = cpu.index("\nend\n", debug_start)
        body += cpu[debug_start:debug_end]
        # These three independent control-register writes precede writeback;
        # the register-file proof neither observes nor changes them.
        body = re.sub(r"\b(?:exe_ctr_r|exe_ime_r|dbg_advance_r)\s*<=\s*[^;]+;", ";", body)
        definitions = ""
        if board == "MK2":
            wb_start = cpu.index("// MkII register-file writeback.")
            wb_end = cpu.index("// End MkII register-file writeback.", wb_start)
            writeback = cpu[wb_start:wb_end]
            definitions = "\n".join(re.findall(
                r"wire\s+(?:\[[^\]]+\]\s+)?mk2_\w+\s*=.*?;", writeback, re.S))
        body = re.sub(r"//[^\n]*", "", body)

        assignments = r"(\{[^{}]+\}|\w+(?:\[[^\]]+\])?)\s*<=\s*([^;]+);"

        def register_writes(text):
            text = re.sub(r"//[^\n]*|/\*.*?\*/", "", text, flags=re.S)
            return Counter((lhs, rhs) for lhs, rhs in re.findall(assignments, text)
                           if set(re.findall(r"\b\w+_r\b", lhs)) & registers.keys())

        # Cover every writer in the full preprocessed CPU, including debug
        # overrides. This catches an omitted path or a second clocked driver.
        if register_writes(cpu) != register_writes(body):
            raise RuntimeError("The proof omitted a register-file writer")
        if register_writes(cpu) != register_writes(cpu[start:debug_end]):
            raise RuntimeError("Register-file writes occur outside their clocked block")

        def next_state(match):
            lhs = match[1]
            names = re.findall(r"\b\w+_r\b", lhs)
            if not names or any(name not in registers for name in names):
                raise RuntimeError("Unexpected writeback target: " + lhs)
            for name in registers:
                lhs = re.sub(r"\b" + name + r"\b", prefix + "_" + name, lhs)
            return lhs + " = " + match[2] + ";"

        body, count = re.subn(assignments, next_state, body)
        if count < 18 or "<=" in body:
            raise RuntimeError("Incomplete register writeback extraction")
        declarations = "\n".join(f"reg [{width - 1}:0] {prefix}_{name};" for name, width in registers.items())
        defaults = "\n".join(f"{prefix}_{name} = {name};" for name in registers)
        blocks.append(definitions + "\n" + declarations + "\nalways @* begin\n" + defaults + body + "\nend\n")

    inputs = ", ".join(f"input [{width - 1}:0] {name}" for name, width in registers.items())
    body = "module check(" + inputs + """,
 input cpu_ireset_r,CLK_BUS_EDGE,exe_advance_r,exe_complete_r,
 input exe_res_sp_mod_r,exe_res_hl_mod_r,
 input [15:0] IFD_EXE_decode,exe_res_r,exe_res_sp_r,exe_res_hl_r,
 input [7:0] exe_res_cc_r,REG_address,REG_req_data,
 input REG_req_dbg,reg_src_r, output equivalent);
""" + "\n".join(blocks)
    actual = "{" + ",".join("actual_" + name for name in registers) + "}"
    reference = "{" + ",".join("reference_" + name for name in registers) + "}"
    body += f"assign equivalent = {actual} == {reference};\nendmodule\n"
    for mutation in ("actual", "missing-pop-de", "swapped-byte"):
        candidate = body
        if mutation == "missing-pop-de":
            candidate, count = re.subn(r"IFD_EXE_decode\[11:8\] == 4'd5\s*\|\|", "", candidate, count=1)
            if count != 1:
                raise RuntimeError("Cannot construct the missing-POP-DE negative control")
        elif mutation == "swapped-byte":
            candidate, count = re.subn(r"IFD_EXE_decode\[11\] \?", "!IFD_EXE_decode[11] ?", candidate)
            if count != 1:
                raise RuntimeError("Cannot construct the swapped-byte negative control")
        source = work / (mutation + ".v")
        source.write_text(candidate)
        script = work / "proof.ys"
        script.write_text(f'read_verilog "{source}"\nprep -top check\n'
                          'sat -verify -prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if mutation != "actual":
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the " + mutation + " control\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("Register-file next-state equivalence failed\n" + log)
    print("PASS: all 80 register-file bits preserve every reset, hold, write and debug override; "
          "SAT rejects missing-POP-DE and swapped-byte controls")
