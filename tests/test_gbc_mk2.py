"""Execute the Mk.II framebuffer RTL against an independent planar oracle."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--ivl-base", help="Icarus module directory for an unpacked installation")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--clock-only", action="store_true", help="run only the clock equivalence check")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    player = (root / "snes/gbc/gbc_snes.asm").read_text()
    for threshold in ("IN", "OUT"):
        value = re.search(rf"^!GBC_FB_COLW_{threshold}\s*=\s*(\d+)\s*;", player, re.M)
        if value is None or not 0 < int(value[1]) <= 256:
            raise RuntimeError("MkII palette-count saturation no longer covers the player's thresholds")
    with tempfile.TemporaryDirectory(prefix="gbc-mk2-") as tmp:
        # The unchanged Mk.III arithmetic is a separate compiled reference.
        clock_ref = Path(tmp) / "clock_ref.v"
        preprocess_clock = [args.iverilog, "-E", "-DMK3", "-I",
                            str(root / "verilog/sd2snes_gbc"), "-o", str(clock_ref),
                            str(root / "verilog/sd2snes_gbc/gbc_clk.v")]
        if args.ivl_base:
            preprocess_clock += ["-B", args.ivl_base]
        subprocess.run(preprocess_clock, check=True)
        source, count = re.subn(r"\bmodule gbc_clk\(", "module gbc_clk_ref(", clock_ref.read_text())
        if count != 1:
            raise RuntimeError("GBC clock reference interface changed")
        clock_ref.write_text(source)
        clock = Path(tmp) / "clock.vvp"
        compile_clock = [args.iverilog, "-g2012", "-DMK2", "-s", "gbc_clock_tb", "-o", str(clock),
                         "-I", str(root / "verilog/sd2snes_gbc"),
                         str(root / "tests/rtl/gbc_clock_tb.v"), str(clock_ref),
                         str(root / "verilog/sd2snes_gbc/gbc_clk.v")]
        if args.ivl_base:
            compile_clock += ["-B", args.ivl_base]
        subprocess.run(compile_clock, check=True)
        subprocess.run([args.vvp, str(clock)], check=True, timeout=60)
        if args.clock_only:
            return
        # Include the production address delay assignments, early-stage tap,
        # and decoder module. Compare to decoding the original final address,
        # even when raw pins change every clock instead of holding a bus cycle.
        main_source = (root / "verilog/sd2snes_gbc/main.v").read_text()
        address_shift = re.findall(r"^\s*SNES_ADDRr\[\d\] <=[^;]+;", main_source, re.M)
        if len(address_shift) != 7:
            raise RuntimeError("SNES address delay pipeline changed")
        address_wire = re.search(r"wire \[23:0\] SNES_ADDR =[^;]+;", main_source)[0]
        command_start = main_source.index("gbc_command_decode command_decode(")
        command_instance = main_source[command_start:main_source.index(");", command_start)+2]
        command_module = main_source[main_source.index("module gbc_command_decode("):]
        command_source = Path(tmp) / "command_actual.v"
        command_source.write_text('''
module gbc_command_actual(input CLK2, input [23:0] SNES_ADDR_IN,
 output [23:0] ADDRESS, output [8:0] MATCH);
 reg [23:0] SNES_ADDRr [6:0];
 wire [8:0] gbc_cmd_match;
''' + address_wire + "\n" + command_instance
            + "\nassign ADDRESS=SNES_ADDR; assign MATCH=gbc_cmd_match;\n"
            + "always @(posedge CLK2) begin\n" + "\n".join(address_shift)
            + "\nend\nendmodule\n" + command_module)
        commands = Path(tmp) / "commands.vvp"
        compile_commands = [args.iverilog, "-g2012", "-s", "gbc_command_tb",
                            "-o", str(commands), str(command_source),
                            str(root / "tests/rtl/gbc_command_tb.v")]
        if args.ivl_base:
            compile_commands += ["-B", args.ivl_base]
        subprocess.run(compile_commands, check=True)
        subprocess.run([args.vvp, str(commands)], check=True, timeout=60)
        # Compile the production read function AND its actual sequential call
        # sites, including OPR_I holds. The test oracle is the old flat table.
        cpu = (root / "verilog/sd2snes_gbc/sgb_cpu.v").read_text()
        # Exercise the production wave-memory gate/instance and sample latch.
        # The independent oracle retains the old register-array reset/write
        # behavior, including simultaneous reset, write and APU sample reads.
        wave_start = cpu.index("wire apu_wave_write =")
        wave_end = cpu.index("`else", wave_start)
        wave_sample = re.search(r"  if \(apu_wave_sample_update_r\)[^;]+;", cpu)[0]
        wave_source = Path(tmp) / "wave_actual.v"
        wave_source.write_text('''
`define NR52_CONTROL_ENABLE 7:7
module gbc_wave_actual(input CLK,cpu_ireset_r,REG_req_val,REG_req_dbg,
 input [7:0] REG_NR52_r, input apu_wave_enable_r,
 input [7:0] REG_address,REG_req_data, input [4:0] apu_wave_pos_r,
 input apu_wave_sample_update_r, output [7:0] cpu_q,apu_q, output [3:0] sample);
 wire [7:0] reg_wave_cpu_data,reg_wave_apu_data;
 reg [3:0] apu_wave_sample_r;
 assign cpu_q=reg_wave_cpu_data; assign apu_q=reg_wave_apu_data;
 assign sample=apu_wave_sample_r;
''' + cpu[wave_start:wave_end] + "\nalways @(posedge CLK) begin\n"
            + wave_sample + "\nend\nendmodule\n")
        wave = Path(tmp) / "wave.vvp"
        compile_wave = [args.iverilog, "-g2012", "-s", "gbc_wave_ram_tb", "-o", str(wave),
                        str(wave_source), str(root / "tests/rtl/gbc_wave_ram_tb.v"),
                        str(root / "verilog/sd2snes_gbc/mk2_memory.v")]
        if args.ivl_base:
            compile_wave += ["-B", args.ivl_base]
        subprocess.run(compile_wave, check=True)
        subprocess.run([args.vvp, str(wave)], check=True, timeout=60)
        # Exhaust every input to the production APU period expressions against
        # the original shifts, including NR43's otherwise inactive high shifts.
        sweep_start = cpu.index("reg  [10:0] apu_square1_sweep_freq_r;")
        sweep_start = cpu.index(";", sweep_start) + 1
        noise_start = cpu.index("reg  [14:0] apu_noise_lfsr_r;")
        noise_start = cpu.index(";", noise_start) + 1
        period_defines = "\n".join(line for line in cpu.splitlines()
                                  if line.startswith(("`define NR10_", "`define NR43_")))
        period_source = Path(tmp) / "apu_period_actual.v"
        period_source.write_text(period_defines + '''
module gbc_apu_period_actual(input [7:0] REG_NR10_r, REG_NR43_r,
 input [10:0] apu_square1_sweep_freq_r,
 output [15:0] sweep, output [21:0] noise);
''' + cpu[sweep_start:cpu.index("wire [12:0] apu_square1_period", sweep_start)]
            + cpu[noise_start:cpu.index("wire [4:0] apu_noise_output", noise_start)]
            + "\nassign sweep=apu_square1_sweep_freq_next; assign noise=apu_noise_period;\nendmodule\n")
        periods = Path(tmp) / "apu-periods.vvp"
        compile_periods = [args.iverilog, "-g2012", "-DMK2", "-s", "gbc_apu_period_tb",
                           "-o", str(periods), str(period_source),
                           str(root / "tests/rtl/gbc_apu_period_tb.v")]
        if args.ivl_base:
            compile_periods += ["-B", args.ivl_base]
        subprocess.run(compile_periods, check=True)
        subprocess.run([args.vvp, str(periods)], check=True, timeout=60)
        defines = cpu[cpu.index("`define OPR_I"):cpu.index("// Forwarded signals")]
        aliases = cpu[cpu.index("`define AF_r"):cpu.index("`define HL_r")].strip()
        aliases += "\n`define HL_r {H_r,L_r}\n"
        fn_start = cpu.index("function [15:0] mk2_operand;")
        function = cpu[fn_start:cpu.index("endfunction", fn_start) + len("endfunction")]
        read_start = cpu.index("  // operand read\n")
        read_end = cpu.index("  // condition code read", read_start)
        operand_source = Path(tmp) / "operand_actual.v"
        operand_source.write_text(defines + aliases + '''
module gbc_operand_actual(input CLK,
 input [7:0] A_r,F_r,B_r,C_r,D_r,E_r,H_r,L_r,
 input [15:0] SP_r,IFD_EXE_pc_next,IFD_EXE_decode,
 input [23:0] IFD_EXE_op, output [15:0] src,dst);
 reg [15:0] exe_src_r,exe_dst_r;
 assign src=exe_src_r; assign dst=exe_dst_r;
''' + function + "\nalways @(posedge CLK) begin\n" + cpu[read_start:read_end]
                                  + "\nend\nendmodule\n")
        operands = Path(tmp) / "operands.vvp"
        compile_operands = [args.iverilog, "-g2012", "-DMK2", "-s", "gbc_operand_tb",
                            "-o", str(operands), str(operand_source),
                            str(root / "tests/rtl/gbc_operand_tb.v")]
        if args.ivl_base:
            compile_operands += ["-B", args.ivl_base]
        subprocess.run(compile_operands, check=True)
        subprocess.run([args.vvp, str(operands)], check=True, timeout=60)
        out = Path(tmp) / "sram.vvp"
        cmd = [args.iverilog, "-g2012", "-s", "gbc_mk2_sram_tb", "-o", str(out)]
        if args.ivl_base:
            cmd += ["-B", args.ivl_base]
        cmd += [str(root / "tests/rtl/gbc_mk2_sram_tb.v"),
                str(root / "verilog/sd2snes_gbc/c6_sram.v")]
        subprocess.run(cmd, check=True)
        subprocess.run([args.vvp, str(out)], check=True, timeout=60)
        # Exercise the production SRAM controller itself, rather than a second
        # implementation of its arbitration. Unrelated MCU/PSRAM inputs are idle.
        begin = main_source.index("parameter ST_RAM_IDLE")
        end = main_source.index("assign mcu_rdy_int", begin)
        end = main_source.index(";", end) + 1
        wrapper = Path(tmp) / "sram_arb.v"
        wrapper.write_text('''`include "config.vh"
module gbc_sram_arb_model(
 input CLK2, SNES_ROMSEL_IN, SNES_cycle_start, SNES_PULSE_end, ROM_HIT,
 input [23:0] SNES_ADDR_IN, input [18:0] MAPPED_SNES_ADDR,
 input FB_MEM_REQ, FB_MEM_WR, input [18:0] FB_MEM_ADDR,
 input [7:0] FB_MEM_DATA, output FB_MEM_ACK, output reg [7:0] FB_MEM_Q,
 output [18:0] RAM_ADDR, inout [7:0] RAM_DATA, output RAM_WE, RAM_OE
);
 wire SNES_DEADr=0; wire [7:0] SNES_CPU_CLKr=0;
 wire MCU_RRQ=0, MCU_WRQ=0, MCU_RAM=0, SD_DMA_TO_RAM=0;
 wire MCU_WRITE_1=1, MCU_WRITE=1, IS_SAVERAM=0, SNES_CPU_CLK=0, SNES_WRITE=1;
 wire [23:0] MCU_ADDR=0; wire [7:0] MCU_DOUT=0;
 wire [7:0] SNES_DATA=0; reg [7:0] MCU_RAM_DINr, MCU_DINr;
 wire [7:0] MCU_ROM_DINr=0, SGB_MCU_DIN=0;
 wire MCU_SGB_RD_PENDr=0, SGB_MCU_RSP=0;
 wire [8:0] STATE=0, ST_MCU_RD_END=0;
 wire RQ_MCU_RDYr=1, RQ_SGB_MCU_RDYr=1;
 wire mcu_rdy_int, ram_free_slot;
 reg ram_free_strobe=0;
''' + main_source[begin:end] + "\nendmodule\n")
        bus = Path(tmp) / "bus.vvp"
        compile_bus = [args.iverilog, "-g2012", "-DMK2", "-s", "gbc_sram_bus_tb",
                       "-I", str(root / "verilog/sd2snes_gbc"), "-o", str(bus),
                       str(wrapper), str(root / "tests/rtl/gbc_sram_bus_tb.v"),
                       str(root / "verilog/sd2snes_gbc/c6_sram.v")]
        if args.ivl_base:
            compile_bus += ["-B", args.ivl_base]
        subprocess.run(compile_bus, check=True)
        subprocess.run([args.vvp, str(bus)], check=True, timeout=60)
        log_ram = Path(tmp) / "log-ram.vvp"
        compile_log = [args.iverilog, "-g2012", "-s", "gbc_log_ram_tb", "-o", str(log_ram),
                       str(root / "tests/rtl/gbc_log_ram_tb.v"),
                       str(root / "tests/rtl/gbc_log_bram_model.v"),
                       str(root / "verilog/sd2snes_gbc/mk2_memory.v")]
        if args.ivl_base:
            compile_log += ["-B", args.ivl_base]
        subprocess.run(compile_log, check=True)
        subprocess.run([args.vvp, str(log_ram)], check=True, timeout=60)
        dirty_ram = Path(tmp) / "dirty-ram.vvp"
        compile_dirty = [args.iverilog, "-g2012", "-s", "gbc_dirty_ram_tb", "-o", str(dirty_ram),
                         str(root / "tests/rtl/gbc_dirty_ram_tb.v"),
                         str(root / "verilog/sd2snes_gbc/mk2_memory.v")]
        if args.ivl_base:
            compile_dirty += ["-B", args.ivl_base]
        subprocess.run(compile_dirty, check=True)
        subprocess.run([args.vvp, str(dirty_ram)], check=True, timeout=60)
        pixel_ram = Path(tmp) / "pixel-ram.vvp"
        compile_pixel = [args.iverilog, "-g2012", "-s", "gbc_pixel_ram_tb", "-o", str(pixel_ram),
                         str(root / "tests/rtl/gbc_pixel_ram_tb.v"),
                         str(root / "verilog/sd2snes_gbc/mk2_memory.v")]
        if args.ivl_base:
            compile_pixel += ["-B", args.ivl_base]
        subprocess.run(compile_pixel, check=True)
        subprocess.run([args.vvp, str(pixel_ram)], check=True, timeout=60)
        snapshots = Path(tmp) / "snapshots.vvp"
        compile_snapshots = [args.iverilog, "-g2012", "-DMK2", "-s", "gbc_snapshot_tb",
                             "-I", str(root / "verilog/sd2snes_gbc"), "-o", str(snapshots),
                             str(root / "tests/rtl/gbc_snapshot_tb.v")]
        compile_snapshots += [str(root / "verilog/sd2snes_gbc" / name) for name in
                              ("gbc_bridge.v", "c6_fb.v", "c6_sram.v", "mk2_memory.v")]
        compile_snapshots.append(str(root / "tests/rtl/gbc_log_bram_model.v"))
        if args.ivl_base:
            compile_snapshots += ["-B", args.ivl_base]
        subprocess.run(compile_snapshots, check=True)
        subprocess.run([args.vvp, str(snapshots)], check=True, timeout=60)
        coe = (root / "verilog/sd2snes_sgb/ip/mk2/dec_table.coe").read_text()
        radix = int(re.search(r"memory_initialization_radix\s*=\s*(\d+)", coe)[1])
        vector = re.search(r"memory_initialization_vector\s*=\s*([^;]+);", coe, re.S)[1]
        decoder = [int(value.strip(), radix) for value in vector.split(",") if value.strip()]
        if len(decoder) != 256 or any(value >= 65536 for value in decoder):
            raise RuntimeError("unexpected canonical CPU decoder shape")
        (Path(tmp) / "decode_reference.hex").write_text("\n".join(f"{v:04x}" for v in decoder))
        decode_hram = Path(tmp) / "decode-hram.vvp"
        compile_decode = [args.iverilog, "-g2012", "-s", "gbc_decode_hram_tb",
                          "-o", str(decode_hram), str(root / "tests/rtl/gbc_decode_hram_tb.v"),
                          str(root / "verilog/sd2snes_gbc/mk2_decode_hram.v")]
        if args.ivl_base:
            compile_decode += ["-B", args.ivl_base]
        subprocess.run(compile_decode, check=True)
        subprocess.run([args.vvp, str(decode_hram)], cwd=tmp, check=True, timeout=60)
        row_flags = Path(tmp) / "row-flags.vvp"
        compile_flags = [args.iverilog, "-g2012", "-s", "gbc_row_flags_tb", "-o", str(row_flags),
                         str(root / "tests/rtl/gbc_row_flags_tb.v"),
                         str(root / "verilog/sd2snes_gbc/mk2_memory.v")]
        if args.ivl_base:
            compile_flags += ["-B", args.ivl_base]
        subprocess.run(compile_flags, check=True)
        subprocess.run([args.vvp, str(row_flags)], check=True, timeout=60)
        oam_positions = Path(tmp) / "oam-positions.vvp"
        compile_oam = [args.iverilog, "-g2012", "-s", "gbc_oam_positions_tb", "-o", str(oam_positions),
                       str(root / "tests/rtl/gbc_oam_positions_tb.v"),
                       str(root / "verilog/sd2snes_gbc/mk2_memory.v")]
        if args.ivl_base:
            compile_oam += ["-B", args.ivl_base]
        subprocess.run(compile_oam, check=True)
        subprocess.run([args.vvp, str(oam_positions)], check=True, timeout=60)
        dirty_pages = Path(tmp) / "dirty-pages.vvp"
        compile_dirty = [args.iverilog, "-g2012", "-s", "gbc_dirty_pages_tb", "-o", str(dirty_pages),
                         str(root / "tests/rtl/gbc_dirty_pages_tb.v"),
                         str(root / "verilog/sd2snes_gbc/mk2_memory.v")]
        if args.ivl_base:
            compile_dirty += ["-B", args.ivl_base]
        subprocess.run(compile_dirty, check=True)
        subprocess.run([args.vvp, str(dirty_pages)], check=True, timeout=60)
        # Compile the existing, independent SGB audio implementation with zero
        # PCM data, then compare every cartridge output against the GBC DAC.
        reference = Path(tmp) / "dac_ref.v"
        preprocess = [args.iverilog, "-E", "-DMK3", "-I",
                      str(root / "verilog/sd2snes_sgb"), "-o", str(reference),
                      str(root / "verilog/sd2snes_sgb/dac.v")]
        if args.ivl_base:
            preprocess += ["-B", args.ivl_base]
        subprocess.run(preprocess, check=True)
        source, count = re.subn(r"\bmodule dac\(", "module dac_ref(", reference.read_text())
        if count != 1:
            raise RuntimeError("SGB DAC reference interface changed")
        reference.write_text(source)
        audio = Path(tmp) / "audio.vvp"
        compile_audio = [args.iverilog, "-g2012", "-DMK2", "-s", "gbc_audio_tb",
                         "-I", str(root / "verilog/sd2snes_gbc"), "-o", str(audio),
                         str(root / "tests/rtl/gbc_audio_tb.v"), str(reference),
                         str(root / "verilog/sd2snes_gbc/dac.v")]
        if args.ivl_base:
            compile_audio += ["-B", args.ivl_base]
        subprocess.run(compile_audio, check=True)
        subprocess.run([args.vvp, str(audio)], check=True, timeout=60)


if __name__ == "__main__":
    main()
