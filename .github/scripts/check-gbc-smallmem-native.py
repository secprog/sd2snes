"""Check the inferred CPU RAM's actual Xilinx primitive in GitHub Actions.

Use the primitive kind and parameters from the native synthesis export, with
the production address/data/enable muxes and decoder. The independent byte
oracle also checks same-address writes on the palette engine's read port.
The installed vendor model is read in place and is never redistributed.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("netlist", type=Path)
parser.add_argument("vendor_model", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
netlist = args.netlist.read_text()
matches = [match for match in re.findall(
    r"\b(RAMB16_S9_S9) #\((.*?)\)\s+\\([^\s]+)\s+\((.*?)\n  \);", netlist, re.S)
    if match[2] == "snes_sgb/cpu/cpu_memory/Mram_bytes"]
if len(matches) != 1:
    raise RuntimeError("expected exactly one shared CPU RAMB16_S9_S9")
kind, parameters, name, connections = matches[0]
if '.WRITE_MODE_A ( "READ_FIRST" )' not in parameters:
    raise RuntimeError("native CPU RAM lost READ_FIRST")
initializers = re.findall(r"\.INIT(?:P)?_[0-9A-F]+\s*\(\s*256'h([0-9a-fA-F]+)", parameters)
if len(initializers) != 72 or any(int(value, 16) for value in initializers):
    raise RuntimeError("native CPU RAM initialization differs from the RTL")
for port in ("CLKA", "CLKB"):
    if f".{port}(CLK2)" not in connections:
        raise RuntimeError("shared RAM ports no longer use the same clock")

source = (root / "verilog/sd2snes_gbc/mk2_cpu_memory.v").read_text()
replacements = {
    '  (* ram_style = "block" *) reg [7:0] bytes [0:255];': "",
    '  reg [7:0] cpu_q;': '  wire [7:0] cpu_q;',
    'output reg [7:0] CRAM_Q_B': 'output [7:0] CRAM_Q_B',
    '    for(init_i=0;init_i<256;init_i=init_i+1) bytes[init_i]=0;': "",
    '    if(cpu_we) bytes[cpu_addr] <= cpu_data;': "",
    '    cpu_q <= bytes[cpu_addr];': "",
    "    CRAM_Q_B <= bytes[{1'b0,CRAM_ADDR_B}];": "",
}
for old, new in replacements.items():
    if source.count(old) != 1:
        raise RuntimeError("production memory shape changed: " + old)
    source = source.replace(old, new)
primitive = f'''  {kind} #({parameters}) native_ram(
 .CLKA(CLK),.CLKB(CLK),.ENA(1'b1),.ENB(1'b1),.WEA(cpu_we),.WEB(1'b0),
 .SSRA(1'b0),.SSRB(1'b0),.ADDRA({{3'b000,cpu_addr}}),
 .ADDRB({{4'b0000,CRAM_ADDR_B}}),.DIA(cpu_data),.DIB(8'b0),
 .DIPA(1'b0),.DIPB(1'b0),.DOA(cpu_q),.DOB(CRAM_Q_B),.DOPA(),.DOPB());
'''
source = source.replace("endmodule", primitive + "endmodule")
coe = (root / "verilog/sd2snes_sgb/ip/mk2/dec_table.coe").read_text()
radix = int(re.search(r"memory_initialization_radix\s*=\s*(\d+)", coe)[1])
vector = re.search(r"memory_initialization_vector\s*=\s*([^;]+);", coe, re.S)[1]
decoder = [int(value.strip(), radix) for value in vector.split(",") if value.strip()]
if len(decoder) != 256:
    raise RuntimeError("canonical decoder changed shape")
with tempfile.TemporaryDirectory(prefix="gbc-native-smallmem-") as tmp:
    work = Path(tmp)
    (work / "memory.v").write_text(source)
    (work / "decode_reference.hex").write_text("\n".join(f"{v:04x}" for v in decoder))
    subprocess.run(["iverilog", "-g2012", "-s", "gbc_decode_hram_tb", "-s", "glbl",
                    "-o", str(work / "test.vvp"), str(work / "memory.v"),
                    str(root / "tests/rtl/gbc_decode_hram_tb.v"),
                    str(args.vendor_model.resolve())], check=True)
    subprocess.run(["vvp", str(work / "test.vvp")], cwd=work, check=True, timeout=120)
print("PASS: shared CPU RAM native primitive parameters and installed Xilinx collision model")
