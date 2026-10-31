#!/usr/bin/env python3
"""Hosted-only source-bound component proofs for measured native slow paths.

DSP: frozen/reset late selection for nine status bits. Basex: final patch mux.
No FPGA tool is invoked here. Component results do not establish routed timing.
"""
import difflib
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def once(text, before, after):
    if text.count(before) != 1:
        raise SystemExit(f"Expected exactly one source boundary: {before!r}")
    return text.replace(before, after, 1)


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def normalized(text):
    return re.sub(r"\s+", "", re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S))


def dsp_models(source, data):
    assignments = data["assignments"]
    target = r"regs_sr\[(?:0|1|7|8|9|11|13|14|SR_DRC)\]\s*<=\s*[^;]+;"
    actual = re.findall(target, re.sub(r"//[^\n]*", "", source))
    if len(actual) != 34 or actual != assignments:
        raise SystemExit("Complete source does not have the reviewed 34 status writes")
    params = ["parameter STATE_STORE = 8'b00010000;", "parameter I_OP = 2'b00;",
              "parameter I_RT = 2'b01;", "parameter I_LD = 2'b11;", "parameter SR_DRC = 10;"]
    for fragment in params + ["  regs_sr = 16'b0;"]:
        if source.count(fragment) != 1:
            raise SystemExit(f"Status parameter/init source changed: {fragment}")
    # Every ancestor of each selected write was independently reviewed in the
    # complete pinned source. Preserve case (including invalid/X selections),
    # reset/freeze priority, the stack-window exclusion and both restore lanes.
    gold_body = """always @(posedge CLK) begin
 if(RST & ~ss_frozen) begin
  case(insn_state)
   STATE_STORE: begin
    case(op)
     I_OP, I_RT: begin
      case(op_dst)
       4'b0111: begin
IDB_WRITES
       end
      endcase
     end
     I_LD: begin
      case(ld_dst)
       4'b0111: begin
LD_WRITES
       end
      endcase
     end
    endcase
   end
  endcase
 end else if(RST & ss_frozen) begin
  if(ss_wr) begin
   if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin
   end else case(ss_wa)
    8'h0c: begin
LOW_WRITES
    end
    8'h0d: begin
HIGH_WRITES
    end
   endcase
  end
 end else begin
RESET_WRITES
 end
end
"""
    for name, lines in (("IDB_WRITES", assignments[:9]), ("LD_WRITES", assignments[9:18]),
                        ("LOW_WRITES", assignments[18:21]), ("HIGH_WRITES", assignments[21:27]),
                        ("RESET_WRITES", assignments[27:])):
        gold_body = once(gold_body, name, "\n".join(lines))
    header = """module status_model(
 input CLK, RST, ss_frozen, ss_wr,
 input [7:0] insn_state, ss_wa, ss_wd,
 input [1:0] op, input [3:0] op_dst, ld_dst,
 input [15:0] idb, ld_id, output [8:0] state);
reg [15:0] regs_sr;
initial {regs_sr[14],regs_sr[13],regs_sr[11],regs_sr[10],regs_sr[9],regs_sr[8],regs_sr[7],regs_sr[1],regs_sr[0]} = 9'b0;
assign state = {regs_sr[14],regs_sr[13],regs_sr[11],regs_sr[10],regs_sr[9],regs_sr[8],regs_sr[7],regs_sr[1],regs_sr[0]};
""" + "\n".join(params) + "\n"
    gold = header + gold_body + "endmodule\n"
    gate = header + data["body"] + "endmodule\n" + data["helpers"]
    changes = {
        "bad-opdst": ("4'b0111: sr_cpu_selected = 1'b1;", "4'b0110: sr_cpu_selected = 1'b1;", 0),
        "bad-lddst": ("4'b0111: sr_cpu_selected = 1'b1;", "4'b0110: sr_cpu_selected = 1'b1;", 1),
        "bad-state": ("STATE_STORE: case(op)", "8'b00100000: case(op)", None),
        "bad-low-address": ("8'h0c: sr_restore_low", "8'h0e: sr_restore_low", None),
        "bad-high-address": ("8'h0d: sr_restore_high", "8'h0e: sr_restore_high", None),
        "bad-low-data": (".restore_data(ss_wd[7]),", ".restore_data(ss_wd[6]),", None),
        "bad-high-data": (".restore_data(ss_wd[6]),", ".restore_data(ss_wd[7]),", None),
        "bad-cpu-data": (".cpu_data(sr_cpu_data[0]),", ".cpu_data(sr_cpu_data[1]),", None),
        "bad-freeze": ("if (reset_n & ~frozen) write = cpu_selected;", "if (reset_n) write = cpu_selected;", None),
        "bad-reset-hold": ("#(.RESET_WRITE(0)) sr_enable_hold", "#(.RESET_WRITE(1)) sr_enable_hold", None),
        "bad-reset-clear": ("#(.RESET_WRITE(1)) sr_enable_low", "#(.RESET_WRITE(0)) sr_enable_low", None),
        "bad-x-guard": ("if (reset_n & ~frozen) write = cpu_selected;", "if ((reset_n & ~frozen) !== 1'b0) write = cpu_selected;", None),
        "bad-x-data": ("value = cpu_data;", "value = cpu_data ^ (restore_data ^ restore_data);", None),
    }
    models = {"gold": gold, "gate": gate}
    for name, (before, after, index) in changes.items():
        if index is None:
            models[name] = once(gate, before, after)
        else:
            if gate.count(before) != 2:
                raise SystemExit("CPU destination mutation boundary changed")
            pieces = gate.split(before)
            models[name] = pieces[0] + (after if index == 0 else before) + pieces[1] + (after if index == 1 else before) + pieces[2]
    return models, gold_body


def base_models(data):
    ports = [("IS_PATCH", 1), ("SNES_ADDR", 24), ("MAPPER_DEC", 8), ("IS_SAVERAM", 1),
             ("SAVERAM_ADDR", 24), ("SAVERAM_MASK", 24), ("BS_PACK_HIT_HI", 1), ("ROM_MASK", 24),
             ("BS_PACK_HIT", 1), ("LOROM_OFF", 20), ("BSLOROM_HI", 1), ("BSLOROM_ADDR", 24),
             ("MAP_GAMARS", 1), ("BSX_IS_CARTROM", 1), ("BSX_IS_PSRAM", 1), ("BSX_ADDR", 24),
             ("bs_page_enable", 1), ("bs_page", 10), ("bs_page_offset", 9), ("MAP_SUFAMI", 1),
             ("ST_SAVERAM_B", 24), ("SAVERAM_MASK_B", 24), ("ROM_MASK_B", 24)]
    header = "module address_model(\n" + "\n".join(
        f" input {'[' + str(width-1) + ':0] ' if width > 1 else ''}{name}," for name, width in ports
    ) + "\n output [23:0] SRAM_SNES_ADDR);\n"
    gold = header + data["originalExpression"] + "\nendmodule\n"
    gate = header + data["body"] + "endmodule\n" + data["helpers"]
    changes = {
        "bad-patch": ("result = patch ?", "result = ~patch ?"),
        "bad-direct-bit": (".direct_bit(SNES_ADDR[22])", ".direct_bit(SNES_ADDR[21])"),
        "bad-mapper-priority": ("((MAPPER_DEC[3'b000])", "((MAPPER_DEC[3'b001])"),
        "bad-saveram": ("{15'b0, SNES_ADDR[8:0]}", "{15'b0, SNES_ADDR[9:1]}"),
        "bad-sufami": (":(MAP_SUFAMI)", ":(1'b0)"),
        "bad-bsx-page": (": bs_page_enable", ": 1'b0"),
        "bad-menu-bank": ("+ 24'hC00000", "+ 24'h800000"),
    }
    models = {"gold": gold, "gate": gate}
    for name, (before, after) in changes.items():
        models[name] = once(gate, before, after)
    for name, bit in (("bad-x-mapper", "MAPPER_DEC[0]"), ("bad-x-mask", "SAVERAM_MASK[23]")):
        body = data["body"].replace(".result(SRAM_SNES_ADDR[", ".result(pre_output[")
        if body.count(".result(pre_output[") != 24:
            raise SystemExit("X-control did not include all address bits")
        body = "wire [23:0] pre_output;\n" + body + f"assign SRAM_SNES_ADDR = pre_output ^ {{24{{{bit} ^ {bit}}}}};\n"
        models[name] = header + body + "endmodule\n" + data["helpers"]
    return models, ports


def main():
    family, fixtures_name, output_name = sys.argv[1:]
    if family not in ("dsp", "basex"):
        raise SystemExit("Unknown proof family")
    fixtures, output = Path(fixtures_name), Path(output_name)
    data = json.loads((fixtures / "slow-path-proof-data.json").read_text())[family]
    source = (fixtures / f"slow-path-parent-{family}.v").read_text()
    if digest(source) != data["parentSha256"]:
        raise SystemExit("Exact independently reviewed parent source mismatch")
    if family == "dsp":
        candidate = source
        for assignment in data["assignments"]:
            candidate = once(candidate, assignment, "\n`ifndef DSP_STATUS_LATE_CONTROL\n" + assignment + "\n`endif\n")
        candidate = data["define"] + once(candidate, data["anchor"], data["inserted"] + data["anchor"]) + data["appendix"]
        inverse = candidate.removeprefix(data["define"]).removesuffix(data["appendix"])
        inverse = once(inverse, data["inserted"], "")
        for assignment in data["assignments"]:
            inverse = once(inverse, "\n`ifndef DSP_STATUS_LATE_CONTROL\n" + assignment + "\n`endif\n", assignment)
        models, projection = dsp_models(source, data)
        configs = [("none", []), ("debug", ["DEBUG"]), ("mk3", ["MK3"]), ("mk3-debug", ["MK3", "DEBUG"]),
                   ("mk2", ["MK2"]), ("mk2-debug", ["MK2", "DEBUG"]), ("dsp", ["DSP_COMP"]),
                   ("dsp-debug", ["DSP_COMP", "DEBUG"]), ("mk3-dsp", ["MK3", "DSP_COMP"]),
                   ("mk3-dsp-debug", ["MK3", "DSP_COMP", "DEBUG"]),
                   ("mk2-dsp", ["MK2", "DSP_COMP"]), ("mk2-dsp-debug", ["MK2", "DSP_COMP", "DEBUG"])]
    else:
        candidate = once(source, data["originalExpression"], data["wrapped"]) + data["appendix"]
        inverse = once(candidate.removesuffix(data["appendix"]), data["wrapped"], data["originalExpression"])
        models, projection = base_models(data)
        configs = [("none", []), ("mk3", ["MK3"]), ("mk3-ext", ["MK3", "BASE_EXT"]),
                   ("mk2", ["MK2"]), ("mk2-bootleg", ["MK2", "BOOTLEG"]),
                   ("mk2-ext-bootleg", ["MK2", "BASE_EXT", "BOOTLEG"]), ("ext", ["BASE_EXT"]),
                   ("bootleg", ["BOOTLEG"]), ("mk2-ext", ["MK2", "BASE_EXT"]), ("mk2-ext-debug", ["MK2", "BASE_EXT", "DEBUG"])]
    if inverse != source or digest(candidate) != data["candidateSha256"]:
        raise SystemExit("Whole candidate SHA or byte-exact source inverse failed")
    output.mkdir(parents=True, exist_ok=True)
    for name, text in {"original.v": source, "candidate.v": candidate, **{name + ".v": model for name, model in models.items()}}.items():
        (output / name).write_text(text)
    preprocessing = []
    for name, defines in configs:
        target = "MK2" in defines and (("DSP_COMP" in defines) if family == "dsp" else ("BASE_EXT" in defines and "BOOTLEG" not in defines))
        include = []
        if family == "dsp":
            header_dir = Path("verilog") / ("sd2snes_dspx" if target else "sd2snes_dsp")
            include = ["-I", str(header_dir.resolve())]
        selected = []
        for version in ("original", "candidate"):
            dest = output / f"pp-{name}-{version}.v"
            subprocess.run(["iverilog", "-g2012", "-E"] + include + ["-D" + d for d in defines]
                           + ["-o", str(dest), str(output / f"{version}.v")], check=True)
            selected.append(dest.read_text())
        if not all(s.strip() for s in selected):
            raise SystemExit("Empty actual Icarus output")
        before, after = selected
        if target:
            after = once(once(after, data["body"], ""), data["helpers"], "")
            if family == "dsp":
                for assignment in data["assignments"]:
                    before = once(before, assignment, "")
            else:
                before = once(before, data["originalExpression"], "")
        if normalized(before) != normalized(after):
            raise SystemExit(f"Actual source configuration changed outside intended boundary: {name}")
        preprocessing.append({"name": name, "defines": defines, "target": target})
    for filename, value in (("preprocessing.json", preprocessing), ("projection-boundary.json", projection),
                            ("variants.json", list(models))):
        (output / filename).write_text(json.dumps(value, indent=2) + "\n")
    (output / "candidate.diff").write_text("".join(difflib.unified_diff(source.splitlines(True), candidate.splitlines(True), "original.v", "candidate.v")))
    (output / "generator.py.txt").write_bytes(Path(__file__).read_bytes())
    (output / "proof-data.json").write_bytes((fixtures / "slow-path-proof-data.json").read_bytes())
    (output / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in sorted(output.iterdir()) if p.is_file() and p.name != "SHA256SUMS"))
    print(f"{family}: exact parent and candidate SHA, whole source inverse and all {len(configs)} actual Icarus selections passed")
    print(f"Prepared {len(models)} complete component models; actual proof, negative witnesses and independent review remain required")


if __name__ == "__main__":
    main()
