"""Prove the production shared CIC arithmetic and work-register invariant.

The controller, resets, rotating stores and arithmetic come from the actual
MkII DAC. Input samples and clock enables are unconstrained. Compare every
active stage with the previous separate integrator/comb equations, and prove
that the shared work register supplies the same operand in later stages.
The independent original SGB DAC remains the complete audio regression oracle.
"""
from pathlib import Path
import re
import subprocess
import tempfile


root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="gbc-cic-share-proof-") as tmp:
    work = Path(tmp)
    preprocessed = work / "dac.v"
    subprocess.run(["iverilog", "-E", "-DMK2", "-I", str(root / "verilog/sd2snes_gbc"),
                    "-o", str(preprocessed), str(root / "verilog/sd2snes_gbc/dac.v")], check=True)
    dac = preprocessed.read_text()
    constants = "\n".join(re.findall(r"parameter ST\w+\s*=.*?;", dac))
    start = dac.index("reg [(")
    end = dac.index("// assign SGB volume boost", start)
    production = dac[start:end]
    body = '''module check(input clkin,reset,sgb_apu_clk_edge,
 input [19:0] sgb_apu_dat, output equivalent);
 integer i;
''' + constants + "\n" + production
    body += '''
 wire int_phase = sgb_cicstate == ST4_INT1 || sgb_cicstate == ST5_INT2 || sgb_cicstate == ST6_INT3;
 wire comb_phase = sgb_cicstate == ST1_COMB1 || sgb_cicstate == ST2_COMB2 || sgb_cicstate == ST3_COMB3;
 wire use_integrator_result = sgb_cicstate == ST5_INT2 || sgb_cicstate == ST6_INT3 || sgb_cicstate == ST1_COMB1;
 wire state_valid = int_phase || comb_phase || sgb_cicstate == ST0_IDLE;
 wire next_valid = sgb_cicstate_next == ST0_IDLE || sgb_cicstate_next == ST1_COMB1;
 wire [1:0] channel_ok;
 genvar ch;
 generate for(ch=0;ch<2;ch=ch+1) begin : g_reference
   wire [27:0] int_reference = sgb_io[0][ch]
                           + (sgb_cicstate == ST4_INT1 ? sgb_bufi[ch] : sgb_io[2][ch]);
   wire [27:0] comb_reference = (sgb_cicstate == ST1_COMB1 ? sgb_io[2][ch] : sgb_comb_work[ch])
                              - sgb_ci[0][ch];
   assign channel_ok[ch] = (!use_integrator_result || sgb_comb_work[ch] == sgb_io[2][ch])
                       && (!int_phase || sgb_filter_result[ch] == int_reference)
                       && (!comb_phase || sgb_filter_result[ch] == comb_reference);
 end endgenerate
 assign equivalent = state_valid && next_valid && (reset || &channel_ok);
endmodule
'''
    for negative in (False, True):
        candidate = body
        if negative:
            # Lose the just-computed integrator result while leaving the
            # actual integrator history intact. The next stage must fail.
            marker = "sgb_comb_work[channel] <= sgb_filter_result[channel];"
            if body.count(marker) != 1:
                raise RuntimeError("The shared work-register updates changed")
            candidate = body.replace(marker, "sgb_comb_work[channel] <= 0;", 1)
        source = work / ("negative.v" if negative else "actual.v")
        source.write_text(candidate)
        script = work / "proof.ys"
        script.write_text(f'read_verilog -sv "{source}"\nprep -top check\nmemory_map\nopt\n'
                          'sat -verify -tempinduct -seq 6 -maxsteps 16 -set-init-zero '
                          '-set-at 1 reset 1 -prove equivalent 1 -show-inputs\n')
        result = subprocess.run(["yosys", "-Q", "-s", str(script)],
                                capture_output=True, text=True, timeout=180)
        log = result.stdout + result.stderr
        if negative:
            if result.returncode == 0 or "proof did fail" not in log:
                raise RuntimeError("SAT accepted the lost-integrator-result control\n" + log)
        elif result.returncode or "Induction step proven" not in log:
            raise RuntimeError("Shared CIC arithmetic invariant failed\n" + log)
    print("PASS: every full-width CIC stage preserves both channel results with arbitrary CE/data; "
          "induction proven, lost-integrator-result control rejected")
