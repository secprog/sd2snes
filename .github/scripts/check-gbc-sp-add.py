"""Prove the two SP-offset operations' full next-state equations in Actions.

Use the production MkII and unchanged MkIII branches. Operands, old carry
registers, flags, opcode and stage counter are all unconstrained, so this also
covers intermediate pipeline clocks and changing inputs before completion.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="gbc-sp-add-proof-") as tmp:
    work = Path(tmp)
    blocks = []
    for board, prefix in (("MK2", "actual"), ("MK3", "reference")):
        preprocessed = work / f"cpu-{board}.v"
        subprocess.run(["iverilog", "-E", f"-D{board}", "-I", str(root / "verilog/sd2snes_gbc"),
                        "-o", str(preprocessed), str(root / "verilog/sd2snes_gbc/sgb_cpu.v")], check=True)
        cpu = preprocessed.read_text()
        marker = "else if (IFD_EXE_op[3:0] == 4'h8) begin"
        start = cpu.index(marker) + len(marker)
        end = cpu.index("\n        end\n      end\n      else begin\n        // ALU", start)
        body = cpu[start:end]
        names = {"exe_res_r": prefix + "_result", "exe_res_cc_r": prefix + "_flags",
                 "exe_res_c3_r": prefix + "_c3", "exe_res_c7_r": prefix + "_c7",
                 "exe_lat_add_r": prefix + "_lat"}

        def next_state(match):
            # Rename only assignment targets. RHS carries must remain the
            # previous pipeline stage, as in the original nonblocking code.
            lhs = match[1]
            for old, new in names.items():
                lhs = re.sub(r"\b" + old + r"\b", new, lhs)
            return lhs + " =" + match[2] + ";"

        body = re.sub(r"(?m)^([^\n;]+?)\s*<=([^;]+);", next_state, body)
        declarations = f"reg [15:0] {prefix}_result; reg [7:0] {prefix}_flags;\n"
        declarations += f"reg {prefix}_c3,{prefix}_c7; reg [2:0] {prefix}_lat;\n"
        if board == "MK2":
            declarations += "\n".join(re.findall(r"wire \[[^\]]+\] mk2_sp_\w+\s*=.*?;", cpu, re.S))
        blocks.append(declarations + "\nalways @* begin\n" + body + "\nend\n")
    body = '''module check(input [15:0] exe_dst_r,exe_src_r,SP_r,
 input [23:0] IFD_EXE_op, input [7:0] exe_cc_r, input [2:0] exe_ctr_r,
 input exe_res_c3_r,exe_res_c7_r, output equivalent);
''' + "\n".join(blocks)
    actual = "{actual_result,actual_flags,actual_c3,actual_c7,actual_lat}"
    reference = "{reference_result,reference_flags,reference_c3,reference_c7,reference_lat}"
    for negative in (False, True):
        source = work / ("negative.v" if negative else "actual.v")
        source.write_text(body + f"assign equivalent = {actual} == ({reference} ^ "
                          + ("29'd1" if negative else "29'd0") + ");\nendmodule\n")
        script = work / "proof.ys"
        script.write_text(f'read_verilog "{source}"\nprep -top check\n'
                          'sat -verify -prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the changed-latency control\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("SP-offset next-state equivalence failed\n" + log)
    print("PASS: both SP-offset operations preserve all result, flag, carry and latency bits; "
          "SAT rejects the changed-latency control")
