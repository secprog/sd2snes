"""Prove the staged slew predicates for all 16-bit rates and targets in Actions.

Extract the actual sampled arithmetic and commit predicates, including the
otherwise unreachable unsigned wrap of the lower bound. The complete clock
test separately compares every output clock with the unchanged MkIII loop.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="gbc-clock-slew-proof-") as tmp:
    work = Path(tmp)
    preprocessed = work / "clock.v"
    subprocess.run(["iverilog", "-E", "-DMK2", "-I", str(root / "verilog/sd2snes_gbc"),
                    "-o", str(preprocessed), str(root / "verilog/sd2snes_gbc/gbc_clk.v")], check=True)
    clock = preprocessed.read_text()
    sample = clock.split("ST_SLEW1: begin", 1)[1].split("ST_SLEW2: begin", 1)[0]
    commit = clock.split("ST_SLEW2: begin", 1)[1].split("default:", 1)[0]
    expected_commit = ("rate_low_r <= !locked_q ? tgt_low_r : slew_up ? k2_hi_low_r[15:0] "
                       ": slew_down ? k2_lo_low_r : tgt_low_r;")
    if expected_commit not in re.sub(r"\s+", " ", commit):
        raise RuntimeError("The commit no longer uses the proved slew predicates")
    if not re.search(r"st_r\s*<=\s*ST_SLEW2\s*;", sample):
        raise RuntimeError("The slew sample/commit stages are no longer consecutive")
    # The target is written only at reset and ST_CLAMP. It cannot change
    # between ST_SLEW1 and ST_SLEW2, including Exact-mode transitions.
    target_writes = re.findall(r"\btgt_low_r\s*<=.*?;", clock, re.S)
    clamp = clock.split("ST_CLAMP: begin", 1)[1].split("ST_SLEW1: begin", 1)[0]
    clamp_writes = re.findall(r"\btgt_low_r\s*<=.*?;", clamp, re.S)
    if len(target_writes) != 2 or len(clamp_writes) != 1 or "tgt_low_r <= 0;" not in target_writes:
        raise RuntimeError("The sampled target's write coverage changed")
    definitions = []
    for name in ("k2_hi_low_r", "k2_lo_low_r", "slew_delta_r", "slew_lo_wrap_r"):
        declaration = re.search(r"reg\s+(?:signed\s+)?(?:\[[^\]]+\]\s+)?[^;]*\b" + name + r"\s*;", clock)[0]
        # k2_lo_low_r shares its declaration with the target input.
        declaration = declaration.replace("tgt_low_r, ", "").replace("reg", "wire", 1)
        assignment = re.findall(r"\b" + name + r"\s*<=\s*(.*?);", sample, re.S)
        if len(assignment) != 1:
            raise RuntimeError("The sampled slew arithmetic changed")
        definitions.append(declaration[:-1] + " = " + assignment[0] + ";")
    for name in ("slew_up", "slew_down"):
        definitions.append(re.search(r"wire\s+" + name + r"\s*=.*?;", clock, re.S)[0])
    body = '''module check(input [15:0] rate_low_r,tgt_low_r, input locked_q,
 output equivalent);
''' + "\n".join(definitions)
    body += '''
wire old_up = {1'b0,tgt_low_r} > k2_hi_low_r;
wire old_down = tgt_low_r < k2_lo_low_r;
assign equivalent = (slew_up == old_up) && (slew_down == old_down);
endmodule
'''
    for negative in (False, True):
        candidate = body
        if negative:
            candidate, count = re.subn(r"slew_delta_r > 17'sd8429", "slew_delta_r > 17'sd8430", body)
            if count != 1:
                raise RuntimeError("Cannot construct the threshold-edge negative control")
        source = work / ("negative.v" if negative else "actual.v")
        source.write_text(candidate)
        script = work / "proof.ys"
        script.write_text(f'read_verilog -sv "{source}"\nprep -top check\n'
                          'sat -verify -prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=120)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the wrong-threshold control\n" + log)
        elif result.returncode or "SUCCESS" not in log:
            raise RuntimeError("Staged slew predicate equivalence failed\n" + log)
    print("PASS: staged slew predicates match both original comparisons for every 16-bit "
          "rate and target, including wrap; SAT rejects the threshold-edge control")
