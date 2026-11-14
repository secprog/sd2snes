"""Prove the production CPU controllers can share the HRAM/palette port.

Run in GitHub Actions. The MCT state machine and REG handshake are extracted
from the preprocessed MkII CPU. Addresses, requests, data, peripheral locks,
DMA arbitration and response delays are unconstrained; no bus exclusion is
assumed. The properties cover writes and the previous cycle of every consumed
read, which matters because both memories have registered outputs.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]


def case_end(text, start):
    depth = 0
    for token in re.finditer(r"\b(case|casex|casez|endcase)\b", text[start:]):
        depth += -1 if token[0] == "endcase" else 1
        if depth == 0:
            return start + token.end()
    raise RuntimeError("unterminated production case")


with tempfile.TemporaryDirectory(prefix="gbc-smallmem-proof-") as tmp:
    work = Path(tmp)
    cpu_file = work / "cpu.v"
    subprocess.run(["iverilog", "-E", "-DMK2", "-I", str(root / "verilog/sd2snes_gbc"),
                    "-o", str(cpu_file), str(root / "verilog/sd2snes_gbc/sgb_cpu.v")], check=True)
    raw = cpu_file.read_text()
    cpu = re.sub(r"/\*.*?\*/|//[^\n]*", "", raw, flags=re.S)
    if re.findall(r"assign DBG_REG_req_val\s*=\s*([^;]+);", cpu) != ["1'b0"]:
        raise RuntimeError("MkII debug access is enabled: re-prove port arbitration")

    def assignment(name):
        return re.search(r"assign\s+" + name + r"\s*=.*?;", cpu, re.S)[0]

    reg_start = cpu.index("case (reg_state_r)")
    reg_case = cpu[reg_start:case_end(cpu, reg_start)]
    inner_start = reg_case.index("case (reg_addr_r)")
    # Data/register side effects cannot affect the unconditional REQ -> END
    # transition. Keep the complete IDLE request latch and END transition.
    reg_case = reg_case[:inner_start] + reg_case[case_end(reg_case, inner_start):]
    mct_start = re.search(r"always @\(posedge CLK\) begin\s*if \(cpu_ireset_r\) begin\s*"
                          r"mct_state_r <= ST_MCT_IDLE;", cpu).start()
    mct_case = cpu.index("case (mct_state_r)", mct_start)
    mct_end = case_end(cpu, mct_case)
    mct_tail = re.match(r"\s*mct_req_r <=[^;]+;\s*end\s*end", cpu[mct_end:])
    if mct_tail is None:
        raise RuntimeError("MCT request pipeline changed")
    mct_logic = cpu[mct_start:mct_end + mct_tail.end()]
    constants = "\n".join(re.findall(r"parameter\s+ST_(?:REG|MCT)_IDLE.*?;", cpu, re.S))
    macros = "\n".join(re.findall(r"^`define MCT_TGT_(?:VRAM|HIGH)[^\n]+", raw, re.M))
    # Icarus has expanded these macros inside the extracted controller.
    select = re.search(r"wire mk2_hram_select\s*=.*?;", cpu, re.S)[0]
    body = '''module check(input CLK,cpu_ireset_r,
 input EXE_MCT_req_val,EXE_MCT_req_wr,IFD_MCT_req_val,
 input [15:0] mct_addr_d1,mct_addr_next,
 input [7:0] EXE_MCT_req_data_d1,VRAM_data,OAM_data,REG_data,HRAM_data,
 input [7:0] mct_clash_data,SYS_RDDATA,
 input PPU_MCT_vram_active,PPU_MCT_oam_active,mct_dma_take,DMA_SYS_active,SYS_RDY,
 output equivalent);
 reg [7:0] mct_state_r,mct_mdr_r;
 reg [15:0] mct_addr_r,mct_oam_error_r,mct_vram_error_r;
 reg mct_src_r,mct_wr_r,mct_conflict_r;
 reg [1:0] mct_req_r;
 reg [2:0] reg_state_r;
 reg reg_src_r,reg_wr_r;
 reg [7:0] reg_addr_r,reg_wr_data_r;
 wire MCT_REG_req_val,MCT_REG_wren,REG_MCT_rsp_val,MCT_HRAM_wren;
 wire [7:0] MCT_REG_address,MCT_REG_data;
 wire DBG_REG_req_val=0,DBG_REG_wren=0;
 wire [7:0] DBG_REG_address=0,DBG_REG_data=0;
 reg hram_selected_d1;
''' + constants + "\n" + macros + "\n" + select + "\n"
    body += "\n".join(assignment(name) for name in (
        "MCT_REG_req_val", "MCT_REG_wren", "MCT_REG_address", "MCT_REG_data",
        "REG_MCT_rsp_val", "MCT_HRAM_wren"))
    body += "\nalways @(posedge CLK) begin\nif(cpu_ireset_r) reg_state_r <= ST_REG_IDLE;\nelse "
    body += reg_case + "\nend\n" + mct_logic
    body += '''
 always @(posedge CLK) hram_selected_d1 <= mk2_hram_select;
 wire cram_use = |(reg_state_r & ST_REG_REQ) &&
                 ((reg_addr_r == 8'h69) || (reg_addr_r == 8'h6b));
 wire hram_consume = |(mct_state_r & ST_MCT_HRAM) && ~|mct_req_r;
 // Prove state membership too. Without this invariant, induction can start
 // in an impossible multi-hot MCT state that the case statement never exits.
 wire controllers_valid =
   (reg_state_r == ST_REG_IDLE || reg_state_r == ST_REG_REQ || reg_state_r == ST_REG_END) &&
   (mct_state_r == ST_MCT_IDLE || mct_state_r == ST_MCT_DEC ||
    mct_state_r == ST_MCT_VRAM || mct_state_r == ST_MCT_OAM ||
    mct_state_r == ST_MCT_REG || mct_state_r == ST_MCT_HRAM ||
    mct_state_r == ST_MCT_EXT || mct_state_r == ST_MCT_END);
 assign equivalent = cpu_ireset_r ||
   (controllers_valid && (!cram_use || (!mk2_hram_select && !hram_selected_d1)) &&
    (!MCT_HRAM_wren || mk2_hram_select) &&
    (!hram_consume || hram_selected_d1));
endmodule
'''
    for negative in (False, True):
        source = work / ("negative.v" if negative else "actual.v")
        source.write_text(body.replace(select, select.replace("= |", "= ~|")) if negative else body)
        script = work / "proof.ys"
        script.write_text(f'read_verilog "{source}"\nprep -top check\n'
                          'sat -verify -tempinduct -seq 6 -maxsteps 20 -set-init-zero '
                          '-set-at 1 cpu_ireset_r 1 -prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the inverted memory-bank control\n" + log)
        elif result.returncode or "Induction step proven" not in log:
            raise RuntimeError("CPU memory-port exclusion/read-window proof failed\n" + log)
    print("PASS: production MCT/REG controllers preserve every shared-memory read/write window; "
          "induction proven, inverted-bank control rejected")
