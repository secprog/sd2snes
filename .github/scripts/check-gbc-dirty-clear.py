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
    subprocess.run(["iverilog", "-E", "-I", str(root / "verilog/sd2snes_gbc"),
                    "-o", str(preprocessed), str(root / "verilog/sd2snes_gbc/c6_fb.v")], check=True)
    reference = preprocessed.read_text()
    captures = []
    for source, suffix in ((c6, ""), (reference, "_ref")):
        capture = re.search(r"always @\(posedge CLK\) begin\n.*?\nend", source, re.S)[0]
        names = ["ctl_wr_r", "rowdone_wr_r", "wr_data_r"]
        if not suffix:
            names += ["rowdone_all_r", "rowdone_one_r"]
        declarations = []
        for name in names:
            writes = re.findall(r"\b" + name + r"\s*<=.*?;", source, re.S)
            if len(writes) != 1 or writes[0] not in capture:
                raise RuntimeError("The row-command register writer coverage changed")
            declarations.append(re.search(r"reg\s+[^;\n]*\b" + name + r"\b[^;\n]*;", source)[0])
        capture = "\n".join(dict.fromkeys(declarations)) + "\n" + capture
        for name in ("rd_all", "rd_one"):
            capture += "\n" + re.search(r"wire\s+" + name + r"\s*=.*?;", source, re.S)[0]
        if suffix:
            capture = re.sub(r"\b(?:ctl_wr_r|rowdone_wr_r|wr_data_r|rd_all|rd_one)\b",
                             lambda match: match[0] + suffix, capture)
        captures.append(capture)
    # One unconstrained transition proves the retimed decode without any
    # initialization, command-spacing or input-data stability assumption.
    for negative in (False, True):
        actual = captures[0]
        if negative:
            actual, count = re.subn(r"WR_DATA < 8'd18", "WR_DATA < 8'd19", actual)
            if count != 1:
                raise RuntimeError("Cannot construct the row-range negative control")
        source = work / "command-stage.v"
        source.write_text('''module check(input CLK,RST,CTL_WR,ROWDONE_WR,
 input [7:0] WR_DATA, output equivalent);
''' + actual + "\n" + captures[1] + '''
assign equivalent = (rd_all == rd_all_ref) && (rd_one == rd_one_ref);
endmodule
''')
        script = work / "command-stage.ys"
        script.write_text(f'read_verilog "{source}"\nprep -top check\n'
                          'sat -verify -seq 2 -prove-skip 1 -prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the out-of-range row command\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("Registered row-command decode differs from the reference\n" + log)
    definitions = []
    for name in ("rd_all", "rd_one", "rd_row", "dirty_write_clear", "cache_clear"):
        definitions.append(re.search(r"wire\s+(?:\[[^\]]+\]\s+)?" + name + r"\s*=.*?;", c6, re.S)[0])
    definitions.append("wire [17:0] rd_mask;")
    definitions.append(re.search(r"assign rd_mask\s*=.*?;", c6, re.S)[0])
    instance = re.search(r"c6_dirty_ram dirty_bitmap\(.*?\);", c6, re.S)[0]
    for connection in (".CLEAR(rd_mask)", ".ROW(wr_row2_r)", ".CLEAR_WRITE_ROW(dirty_write_clear)"):
        if connection not in instance:
            raise RuntimeError("The production RAM no longer uses the proved clear interface")
    storage = re.search(r"c6_sram storage\(.*?\);", c6, re.S)[0]
    for connection in (".INVALIDATE_CACHE(cache_clear)", ".CACHE_ROW(cache_row)"):
        if connection not in storage:
            raise RuntimeError("The production cache no longer uses the proved clear interface")
    ram = (root / "verilog/sd2snes_gbc/mk2_memory.v").read_text()
    for name in ("use_saved", "use_default", "base_word"):
        definitions.append(re.search(r"wire\s+(?:\[[^\]]+\]\s+)?" + name + r"\s*=.*?;", ram, re.S)[0])
    body = '''module check(input rowdone_wr_r, rowdone_all_r, rowdone_one_r, RST,
 input [7:0] wr_data_r,
 input [4:0] wr_row2_r, cache_row, input [17:0] row_frozen_r, valid, default_one,
 input [19:0] write_word, output equivalent);
wire [4:0] ROW = wr_row2_r;
wire CLEAR_WRITE_ROW = dirty_write_clear;
''' + "\n".join(definitions)
    body += '''
wire [19:0] reference_word = (RST || rd_mask[ROW]) ? 20'd0
                           : valid[ROW] ? write_word : {20{default_one[ROW]}};
assign equivalent = (ROW >= 18 || ((dirty_write_clear == rd_mask[ROW])
                                   && (base_word == reference_word)))
                 && (cache_row >= 18 || cache_clear == rd_mask[cache_row]);
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
    # Prove the cache tag stays in the valid range. Abstract its installation
    # handshake to a free input; allowing more installations is a stronger
    # condition. The actual request acceptance guard and every tag writer are
    # checked against this model, including both reset assignments.
    sram = (root / "verilog/sd2snes_gbc/c6_sram.v").read_text()
    if not re.search(r"wire invalidating\s*=\s*INVALIDATE_CACHE\s*;", sram):
        raise RuntimeError("The cache invalidation consumer changed")
    if not re.search(r"assign CACHE_ROW\s*=\s*cache_row\s*;", sram):
        raise RuntimeError("The exported cache tag changed")
    guard = re.search(r"if \((PREPARE && PREPARE_ROW < 18 && FROZEN\[PREPARE_ROW\])\) begin", sram)[1]
    for name, values in (("cache_row", ["0", "request_row"]),
                         ("request_row", ["0", "PREPARE_ROW"])):
        writes = re.findall(r"\b" + name + r"\s*<=\s*([^;]+);", sram)
        if writes != values:
            raise RuntimeError("The cache tag writer coverage changed")
    acceptance = sram[sram.index("if (" + guard):sram.index("case (state)")]
    if "request_row <= PREPARE_ROW;" not in acceptance:
        raise RuntimeError("The validated request no longer dominates tag capture")
    for negative in (False, True):
        source = work / "cache-range.v"
        source.write_text('''module check(input CLK,RST,PREPARE,install,
 input [4:0] PREPARE_ROW, input [17:0] FROZEN, output equivalent);
reg [4:0] cache_row, request_row;
always @(posedge CLK) begin
  if (RST) begin cache_row <= 0; request_row <= 0; end
  else begin
''' + "    if (" + ("PREPARE" if negative else guard) + ") request_row <= PREPARE_ROW;\n" + '''
    if (install) cache_row <= request_row;
  end
end
assign equivalent = cache_row < 18 && request_row < 18;
endmodule
''')
        script = work / "cache-range.ys"
        script.write_text(f'read_verilog "{source}"\nprep -top check\n'
                          'sat -verify -tempinduct -seq 2 -maxsteps 4 -set-init-zero '
                          '-prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the unvalidated-cache-row control\n" + log)
        elif result.returncode or "Induction step proven" not in log:
            raise RuntimeError("Cache tag range induction failed\n" + log)
    print("PASS: row-command decode preserves its exact cycle and rejects invalid rows; "
          "direct dirty/cache clears and shared data masks match every valid row, command and stored bit; "
          "cache tags stay in range; "
          "SAT rejects the wrong-row control")
