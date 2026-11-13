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
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="gbc-mk2-") as tmp:
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
        main_source = (root / "verilog/sd2snes_gbc/main.v").read_text()
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
        if args.ivl_base:
            compile_snapshots += ["-B", args.ivl_base]
        subprocess.run(compile_snapshots, check=True)
        subprocess.run([args.vvp, str(snapshots)], check=True, timeout=60)
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
