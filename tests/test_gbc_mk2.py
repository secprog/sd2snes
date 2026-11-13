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
