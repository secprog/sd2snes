"""Prove the production sprite line predicate for all inputs in Actions.

Compare with the unchanged MkIII predicate, including every off-screen Y and
scanline value. The negative control deliberately drops the ninth delta bit.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="gbc-oam-range-proof-") as tmp:
    work = Path(tmp)
    sources = {}
    for board in ("MK2", "MK3"):
        preprocessed = work / f"cpu-{board}.v"
        subprocess.run(["iverilog", "-E", f"-D{board}", "-I", str(root / "verilog/sd2snes_gbc"),
                        "-o", str(preprocessed), str(root / "verilog/sd2snes_gbc/sgb_cpu.v")], check=True)
        sources[board] = preprocessed.read_text()

    actual = sources["MK2"]
    reference = sources["MK3"]
    definitions = []
    for name in ("ppu_oam_y_delta", "ppu_oam_line_hit"):
        definitions.append(re.search(r"wire\s+(?:\[[^\]]+\]\s+)?" + name +
                                     r"\s*=.*?;", actual, re.S)[0])
    declarations = []
    for name in ("ppu_scanline_r", "ppu_oam_data_r", "REG_LCDC_r"):
        pattern = r"reg\s+\[([^\]]+)\]\s+" + name + r"\s*;"
        width = re.search(pattern, actual)[1]
        if width != re.search(pattern, reference)[1]:
            raise RuntimeError(f"Reference width differs for {name}")
        declarations.append(f"input [{width}] {name}")

    def predicate(cpu):
        state = cpu[cpu.index("ST_PPU_OAM_POS : begin"):]
        return re.search(r"if \(~ppu_oam_lut_full & ppu_pix_phase_r & ~DMA_active\) begin\s*"
                         r"if \((.*?)\) begin", state, re.S)[1]

    if predicate(actual).strip() != "ppu_oam_line_hit":
        raise RuntimeError("The PPU no longer uses the predicate being proved")
    write = re.search(r"wire oam_position_write\s*=.*?;", actual, re.S)[0]
    if not re.search(r"&& ppu_oam_line_hit\s*;", write):
        raise RuntimeError("The sprite position memory no longer uses the proved predicate")

    body = ("module check(" + ",".join(declarations) + ",output equivalent);\n" +
            "\n".join(definitions) + "\nassign equivalent = ppu_oam_line_hit == (" +
            predicate(reference) + ");\nendmodule\n")
    for negative in (False, True):
        candidate = body
        if negative:
            candidate, count = re.subn(r"ppu_oam_y_delta\[8:4\]", "ppu_oam_y_delta[7:4]", body)
            if count != 1:
                raise RuntimeError("Cannot construct the missing-sign-bit negative control")
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
                raise RuntimeError("SAT accepted the missing-sign-bit control\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("Sprite scanline predicate equivalence failed\n" + log)
    print("PASS: sprite selection matches for all scanlines, Y positions and sizes; "
          "SAT rejects the eight-bit wrapping control")
