"""Prove the direct C6 dirty-write clear decode for every command and row.

No row-freezing or command-spacing assumptions: use every input combination.
The existing packed-bitmap oracle checks the RAM's SET/CLEAR/ALL priorities.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="gbc-dirty-clear-proof-") as tmp:
    work = Path(tmp)
    preprocessed = work / "c6.v"
    subprocess.run(["iverilog", "-E", "-DMK2", "-I", str(root / "verilog/sd2snes_gbc"),
                    "-o", str(preprocessed), str(root / "verilog/sd2snes_gbc/c6_fb.v")], check=True)
    c6 = preprocessed.read_text()
    definitions = []
    for name in ("rd_all", "rd_one", "rd_row", "dirty_write_clear"):
        definitions.append(re.search(r"wire\s+(?:\[[^\]]+\]\s+)?" + name + r"\s*=.*?;", c6, re.S)[0])
    definitions.append("wire [17:0] rd_mask;")
    definitions.append(re.search(r"assign rd_mask\s*=.*?;", c6, re.S)[0])
    instance = re.search(r"c6_dirty_ram dirty_bitmap\(.*?\);", c6, re.S)[0]
    for connection in (".CLEAR(rd_mask)", ".ROW(wr_row2_r)", ".CLEAR_WRITE_ROW(dirty_write_clear)"):
        if connection not in instance:
            raise RuntimeError("The production RAM no longer uses the proved clear interface")
    ram = (root / "verilog/sd2snes_gbc/mk2_memory.v").read_text()
    for name in ("use_saved", "use_default", "base_word"):
        definitions.append(re.search(r"wire\s+(?:\[[^\]]+\]\s+)?" + name + r"\s*=.*?;", ram, re.S)[0])
    body = '''module check(input rowdone_wr_r, RST, input [7:0] wr_data_r,
 input [4:0] wr_row2_r, input [17:0] row_frozen_r, valid, default_one,
 input [19:0] write_word, output equivalent);
wire [4:0] ROW = wr_row2_r;
wire CLEAR_WRITE_ROW = dirty_write_clear;
''' + "\n".join(definitions)
    body += '''
wire [19:0] reference_word = (RST || rd_mask[ROW]) ? 20'd0
                           : valid[ROW] ? write_word : {20{default_one[ROW]}};
assign equivalent = ROW >= 18 || ((dirty_write_clear == rd_mask[ROW])
                                  && (base_word == reference_word));
endmodule
'''
    for negative in (False, True):
        candidate = body
        if negative:
            candidate, count = re.subn(r"rd_row == wr_row2_r", "rd_row != wr_row2_r", body)
            if count != 1:
                raise RuntimeError("Cannot construct the wrong-row negative control")
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
                raise RuntimeError("SAT accepted the wrong-row control\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("Direct dirty-write clear equivalence failed\n" + log)
    print("PASS: direct dirty-write clear and shared data masks match every valid row, command and stored bit; "
          "SAT rejects the wrong-row control")
