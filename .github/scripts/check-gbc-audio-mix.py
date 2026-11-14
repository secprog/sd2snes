"""Prove both production audio mixers and their sample pipelines in Actions.

Every five-bit channel value, NR50/51/52 byte and clock-to-clock transition is
free. Compare with unchanged MkIII, including both register stages and signed
output conversion. Reject dropped-carry and wrong-channel negative controls.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="gbc-audio-mix-proof-") as tmp:
    work = Path(tmp)
    modules = {}
    for board, name in (("MK2", "actual"), ("MK3", "reference")):
        preprocessed = work / f"cpu-{board}.v"
        subprocess.run(["iverilog", "-E", f"-D{board}", "-I", str(root / "verilog/sd2snes_gbc"),
                        "-o", str(preprocessed), str(root / "verilog/sd2snes_gbc/sgb_cpu.v")], check=True)
        cpu = preprocessed.read_text()
        start = re.search(r"wire\s+\[6:0\]\s+apu_data\[1:0\];", cpu).start()
        end = cpu.index("assign APU_REG_enable", start)
        mix = cpu[start:end]
        sample_start = cpu.index("always @(posedge CLK) begin\n  // Flop audio state", end)
        sample_end = cpu.index("  apu_wave_data_shifted_r", sample_start)
        pipeline = cpu[sample_start:sample_end] + "end\n"
        output = re.search(r"assign APU_DAT\s*=.*?;", cpu, re.S)[0]
        # Ensure that all writers of these sample stages are in
        # the extracted production path, rather than proving a partial model.
        assignments = r"\b(apu_data(?:_volume)?_r(?:\[[^\]]+\])+)\s*<=\s*([^;]+);"
        if re.findall(assignments, cpu) != re.findall(assignments, pipeline):
            raise RuntimeError("Audio mixer proof omitted a sample-register writer")
        if len(re.findall(assignments, pipeline)) != 3:
            raise RuntimeError("Unexpected audio mixer pipeline")
        modules[name] = f"""module {name}(input CLK,
 input [4:0] apu_square1_output,apu_square2_output,apu_wave_output,apu_noise_output,
 input [7:0] REG_NR50_r,REG_NR51_r,REG_NR52_r,
 output [13:0] mixed, output [19:0] APU_DAT);
integer apu_mix_i;
""" + mix + pipeline + output + "\nassign mixed={apu_data[1],apu_data[0]};\nendmodule\n"

    for mutation in ("actual", "dropped-pair-carry", "wrong-noise-select"):
        actual = modules["actual"]
        if mutation == "dropped-pair-carry":
            actual, count = re.subn(r"wire \[5:0\] squares", "wire [4:0] squares", actual)
            if count != 1:
                raise RuntimeError("Cannot construct the dropped-carry control")
        elif mutation == "wrong-noise-select":
            actual, count = re.subn(r"4\*apu_mix_ch\+3", "4*apu_mix_ch+2", actual)
            if count != 1:
                raise RuntimeError("Cannot construct the wrong-channel control")
        source = work / (mutation + ".v")
        source.write_text(actual + modules["reference"])
        script = work / "proof.ys"
        script.write_text(f'read_verilog "{source}"\n'
                          # Lower the array assignments and processes before
                          # flattening the two modules into a miter. Flattening
                          # their unlowered memories can lose the sample wires.
                          'proc\nmemory_map\nopt\ncheck -assert\n'
                          'miter -equiv -flatten actual reference check\n'
                          'prep -top check\n'
                          'check -assert\n'
                          # Two sample stages: after two arbitrary input
                          # clocks, no initial register value can affect the
                          # comparison. No zero initialization is assumed.
                          'sat -verify -seq 3 -prove-skip 2 -prove trigger 0 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=180)
        log = result.stdout + result.stderr
        if mutation != "actual":
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted " + mutation + "\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("Audio mixer equivalence failed\n" + log)
    print("PASS: both 7-bit channel sums and 10-bit sample pipelines preserve all values, "
          "routing, power and volume settings; carry and channel mutants rejected")
