"""Compare the production MkII read mux with the unchanged legacy read cases."""
from pathlib import Path
import re
import subprocess


def check_mmio(root, tmp, args):
    source_path = root / "verilog/sd2snes_gbc/sgb_cpu.v"
    sources = {}
    for board in ("MK2", "MK3"):
        out = Path(tmp) / ("cpu_" + board + ".v")
        command = [args.iverilog, "-E", "-D" + board, "-I",
                   str(source_path.parent), "-o", str(out), str(source_path)]
        if args.ivl_base:
            command += ["-B", args.ivl_base]
        subprocess.run(command, check=True)
        sources[board] = out.read_text(encoding="utf-8")

    legacy = sources["MK3"]
    begin = legacy.index("ST_REG_REQ: begin\n        case (reg_addr_r)")
    end = legacy.index("reg_state_r <= ST_REG_END;", begin)
    legacy = legacy[begin:end]
    rows = re.findall(r"^\s*8'h([0-9A-Fa-f]{2}):\s*(?:begin\s+)?"
                      r"reg_mdr_r(?:\[7:0\])?\s*<=\s*([^;]+);", legacy, re.M)
    if len(rows) != 76 or len({address for address, _ in rows}) != 76:
        raise RuntimeError("Legacy MMIO read cases changed; update extraction coverage")
    if "default: reg_mdr_r <= 8'hFF;" not in legacy:
        raise RuntimeError("Legacy MMIO default changed")

    production = sources["MK2"]
    mux = production.split("// GBC_MK2_MMIO_BEGIN\n", 1)[1].split("// GBC_MK2_MMIO_END", 1)[0]
    if len(re.findall(r"reg\s+\[7:0\]\s+mmio_read\s*;", production)) != 1:
        raise RuntimeError("Production MMIO result declaration changed")
    mux = "reg [7:0] mmio_read;\n" + mux
    expressions = " ".join(expression for _, expression in rows)
    expressions = re.sub(r"\d*'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_]+", " ", expressions)
    signals = sorted(set(re.findall(r"\b[A-Za-z_]\w*\b", expressions)) | {"reg_addr_r"})
    declarations, randomize = [], []
    for name in signals:
        pattern = (r"^\s*(?:wire|reg)\s*(?:signed\s+)?(\[[^\]\n]+\])?\s*"
                   + re.escape(name) + r"\s*(\[[^\]\n]+\])?\s*(?:=|;)")
        matches = re.findall(pattern, production, re.M)
        if len(matches) != 1:
            raise RuntimeError("Cannot determine the production width of " + name)
        width, array = matches[0]
        declarations.append("reg " + width + " " + name + array + ";")
        if name == "reg_addr_r":
            continue
        value = "trial==0 ? 0 : trial==1 ? -1 : trial==2 ? 32'h55555555 : trial==3 ? 32'haaaaaaaa : $random(seed)"
        if array:
            if name != "REG_WAV_r" or array != "[15:0]":
                raise RuntimeError("Unexpected MMIO array layout: " + name + array)
            randomize.append("for(j=0;j<16;j=j+1) " + name + "[j]=" + value + ";")
        else:
            randomize.append(name + "=" + value + ";")

    oracle = "\n".join("8'h" + address + ": expected=" + expression + ";" for address, expression in rows)
    bench = Path(tmp) / "mmio_tb.v"
    bench.write_text("""`timescale 1ns/1ps
module mmio_tb;
""" + "\n".join(declarations) + "\n" + mux + """
reg [7:0] expected;
always @(*) begin
case(reg_addr_r)
""" + oracle + """
default: expected=8'hff;
endcase
end
integer trial,address,j,checks=0,seed=32'h5129ad34;
initial begin
  for(trial=0;trial<128;trial=trial+1) begin
    for(address=0;address<256;address=address+1) begin
      reg_addr_r=address;
""" + "\n".join(randomize) + """
      #1;
      if(mmio_read !== expected)
        $fatal(1,"MMIO mismatch address=%h trial=%0d got=%h expected=%h",reg_addr_r,trial,mmio_read,expected);
      checks=checks+1;
    end
  end
  $display("PASS: grouped MkII MMIO reads match legacy masks and access gates (%0d addresses/data patterns)",checks);
  $finish;
end
endmodule
""", encoding="utf-8")
    executable = Path(tmp) / "mmio.vvp"
    command = [args.iverilog, "-g2012", "-s", "mmio_tb", "-o", str(executable), str(bench)]
    if args.ivl_base:
        command += ["-B", args.ivl_base]
    subprocess.run(command, check=True)
    subprocess.run([args.vvp, str(executable)], check=True, timeout=60)
