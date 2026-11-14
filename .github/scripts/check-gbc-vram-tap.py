"""Prove that MkII dirty tracking records every actual VRAM write unchanged.

The physical RAM mux remains the reference. All master requests, addresses,
write enables, VBK and the PPU lock are unconstrained. The PPU-to-MCT lock
relation comes directly from the production source, not an assumed exclusion.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
cpu = (root / "verilog/sd2snes_gbc/sgb_cpu.v").read_text()
definitions = []
for name in ("vram_wren", "vram_address", "vram_bank"):
    definitions.append(re.search(r"wire\s+(?:\[[^\]]+\]\s+)?" + name +
                                 r"\s*=.*?;", cpu, re.S)[0])
for name in ("PPU_VRAM_active", "PPU_MCT_vram_active", "TAP_VRAM_WE",
             "TAP_VRAM_BANK", "TAP_VRAM_ADDR"):
    # The MkII tap assignments precede the unchanged MkIII alternatives.
    definitions.append(re.search(r"assign\s+" + name + r"\s*=.*?;", cpu, re.S)[0])
body = '''module check(
 input HDMA_VRAM_active,DMA_VRAM_active,hdma_vram_wren,
 input ppu_vram_active,ppu_cpu_lock,MCT_VRAM_wren,REG_VBK_r,
 input [12:0] hdma_vram_address,PPU_VRAM_address,MCT_VRAM_address,
 input [15:0] DMA_address, output equivalent);
 wire PPU_VRAM_active,PPU_MCT_vram_active,TAP_VRAM_WE,TAP_VRAM_BANK;
 wire [12:0] TAP_VRAM_ADDR;
''' + "\n".join(definitions)
with tempfile.TemporaryDirectory(prefix="gbc-vram-proof-") as tmp:
    work = Path(tmp)
    for negative in (False, True):
        source = work / ("negative.v" if negative else "actual.v")
        source.write_text(body + "\nassign equivalent = !vram_wren || "
                          "(TAP_VRAM_WE && {TAP_VRAM_BANK,TAP_VRAM_ADDR} == "
                          "({vram_bank,vram_address} ^ 14'd" +
                          ("1" if negative else "0") + "));\nendmodule\n")
        script = work / "proof.ys"
        script.write_text(f'read_verilog "{source}"\nprep -top check\n'
                          'sat -verify -prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the corrupted tap address\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("VRAM write-tap equivalence failed\n" + log)
    print("PASS: every VRAM write preserves its bank and dirty-tracking address; "
          "SAT rejects the corrupted-address control")
