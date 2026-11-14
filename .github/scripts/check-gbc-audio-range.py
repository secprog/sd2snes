"""Prove the MkII audio saturation branch is unreachable in GitHub Actions.

Use the actual volume register, sample selection, signed product and pipeline.
All filter outputs and every volume selection are free on every clock. The
unchanged MkIII clamp is the reference. An excessive-boost mutation must fail.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="gbc-audio-range-proof-") as tmp:
    work = Path(tmp)
    sources = {}
    for board in ("MK2", "MK3"):
        preprocessed = work / f"dac-{board}.v"
        subprocess.run(["iverilog", "-E", f"-D{board}", "-I", str(root / "verilog/sd2snes_gbc"),
                        "-o", str(preprocessed), str(root / "verilog/sd2snes_gbc/dac.v")], check=True)
        sources[board] = preprocessed.read_text()
    actual = sources["MK2"]
    start = actual.index("// assign SGB volume boost")
    end = re.search(r"always @\(posedge clkin\) begin\s*if \(sclk_falling\)", actual[start:]).start() + start
    production = actual[start:end]
    production = production.replace("sgb_co[2][1]", "right_sample").replace("sgb_co[2][0]", "left_sample")
    gain = re.search(r"reg \[10:0\] sgb_vol_reg\s*=.*?;", actual)[0]
    reference = re.search(r"wire signed \[15:0\] vol_sample_sat\s*=.*?;", sources["MK3"], re.S)[0]
    reference = reference.replace("vol_sample_sat", "reference_sat")
    for negative in (False, True):
        candidate = production
        if negative:
            candidate, count = re.subn("11'h380", "11'h780", production)
            if count != 1:
                raise RuntimeError("Cannot construct the excessive-boost negative control")
        # This membership is part of the induction claim, not an assumption.
        # Derive it anew for the mutant too, so its failure must reach the
        # sample comparison instead of merely rejecting the changed setting.
        gains = sorted(set(re.findall(r"sgb_vol_reg\s*=\s*(11'h[0-9a-fA-F]+)\s*;", candidate)))
        if not gains:
            raise RuntimeError("No production gain settings found")
        gain_valid = " || ".join("sgb_vol_reg == " + value for value in gains)
        body = '''module check(input clkin,lrck, input [2:0] sgb_vol_select,
 input [27:0] left_sample,right_sample, output equivalent);
''' + gain + "\n" + candidate + "\n" + reference
        body += "\nassign equivalent = (" + gain_valid + ") && (vol_sample_sat == reference_sat);\nendmodule\n"
        source = work / ("negative.v" if negative else "actual.v")
        source.write_text(body)
        script = work / "proof.ys"
        script.write_text(f'read_verilog -sv "{source}"\nprep -top check\n'
                          'sat -verify -tempinduct -seq 3 -maxsteps 8 -set-init-zero '
                          '-prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=180)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the excessive-boost control\n" + log)
        elif result.returncode or "Induction step proven" not in log:
            raise RuntimeError("Audio saturation-range proof failed\n" + log)
    print("PASS: all production volume settings preserve every 16-bit output without saturation; "
          "induction proven, excessive-boost control rejected")
