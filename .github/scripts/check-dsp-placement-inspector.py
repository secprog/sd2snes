#!/usr/bin/env python3
"""Exercise the DSPx placement inspector using captured reports and mutations.

The captured PCF and XDL excerpts come from different failed runs.  Combined
or modified fixtures below are synthetic parser checks, not placement or
timing evidence for either run.
"""

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path


PCF_SHA256 = "3ea6b432f8300a6dec75d5e7f0924d17fab164fb2ec993d369cbc81504cfa0a4"
XDL_SHA256 = "2c5f8427b983810901671043d47d3bdab72b1b52842c93c9ec61012c2456162d"
RANGE = "SLICE_X30Y50:SLICE_X34Y55"
COMP3 = "snes_dspx/stack<9><3>"
COMP6 = "snes_dspx/stack<9><6>"
TARGET3 = "snes_dspx/stack<9>_3"
TARGET6 = "snes_dspx/stack<9>_6"


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"Fixture does not contain exactly one {old!r}")
    return text.replace(old, new, 1)


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: check-dsp-placement-inspector.py INSPECTOR CAPTURED.PCF CAPTURED-XDL.TXT")
    inspector, pcf_path, xdl_path = (Path(arg).resolve() for arg in sys.argv[1:])
    if hashlib.sha256(pcf_path.read_bytes()).hexdigest() != PCF_SHA256:
        raise SystemExit("Captured placement PCF hash mismatch")
    if hashlib.sha256(xdl_path.read_bytes()).hexdigest() != XDL_SHA256:
        raise SystemExit("Captured XDL excerpt hash mismatch")
    pcf = pcf_path.read_text()
    xdl = xdl_path.read_text()
    loc3 = f'COMP "{COMP3}" LOCATE = SITE "{RANGE}" LEVEL\n        1;'
    if pcf.count(loc3) != 1 or f'COMP "{COMP6}" LOCATE' in pcf:
        raise SystemExit("Captured PCF is not the expected one-COMP probe")
    if xdl.count(f"FFX:{TARGET3}:#FF") != 1 or xdl.count(f"FFX:{TARGET6}:#FF") != 1:
        raise SystemExit("Captured XDL excerpt lacks the expected FF bindings")

    # Create deliberately synthetic placements inside the requested range.
    inside = replace_once(xdl, "SLICE_X40Y42", "SLICE_X31Y51")
    inside = replace_once(inside, "SLICE_X46Y34", "SLICE_X32Y52")
    loc6 = f'COMP "{COMP6}" LOCATE = SITE "{RANGE}" LEVEL 1;'
    separate_pcf = pcf + "\n" + loc6 + "\n"

    with tempfile.TemporaryDirectory(prefix="dsp-placement-guard-") as tmp:
        temp = Path(tmp)
        synthetic_pcf, synthetic_xdl = temp / "candidate.pcf", temp / "candidate.xdl"

        def check(name, pcf_text, xdl_text, should_pass, expected):
            synthetic_pcf.write_text(pcf_text)
            synthetic_xdl.write_text(xdl_text)
            result = subprocess.run(
                [sys.executable, str(inspector), str(synthetic_pcf), str(synthetic_xdl), "main_map.ncd"],
                text=True, capture_output=True, check=False,
            )
            output = result.stdout + result.stderr
            if (result.returncode == 0) != should_pass or expected not in output:
                raise SystemExit(f"{name} returned {result.returncode}; expected {expected!r}\n{output}")
            print(f"{name}: {'accepted' if should_pass else 'rejected'} as expected")

        check("captured reports from different runs", pcf, xdl, False, "outside the diagnostic range")
        check("two separately constrained synthetic components", separate_pcf, inside, True, "Both requested FF bindings")
        check("missing second component constraint", pcf, inside, False, f"Expected exactly one PCF LOCATE for {COMP6}")
        check("duplicate constraint", separate_pcf + loc6, inside, False, f"Expected exactly one PCF LOCATE for {COMP6}")
        check("wrong range", replace_once(separate_pcf, loc6, loc6.replace(RANGE, "SLICE_X0Y0:SLICE_X1Y1")), inside, False, "Wrong PCF placement range")
        check("outside range", separate_pcf, replace_once(inside, "SLICE_X32Y52", "SLICE_X35Y52"), False, "outside the diagnostic range")
        check("unplaced component", separate_pcf, replace_once(inside, "placed R15C24 SLICE_X32Y52", "unplaced"), False, "no placed SLICE instance")
        check("wrong component", separate_pcf, replace_once(inside, f'inst "{COMP6}"', 'inst "wrong_component"'), False, "Expected exactly one PCF LOCATE for wrong_component")
        check("missing FF despite matching LUT name", separate_pcf, replace_once(inside, f"FFX:{TARGET6}:#FF", f"F:{TARGET6}:#LUT:D=A1"), False, f"Expected exactly one placed FF binding for {TARGET6}")
        check("duplicate FF binding", separate_pcf, inside + "\n" + inside[inside.index(f'inst "{COMP6}"'):inside.rindex(";") + 1], False, f"Expected exactly one placed FF binding for {TARGET6}")
        check("two components at one site", separate_pcf, replace_once(inside, "SLICE_X32Y52", "SLICE_X31Y51"), False, "Distinct components claim the same SLICE site")

        start = inside.index(f'inst "{COMP3}"')
        end = inside.index(";", start) + 1
        shared = replace_once(inside[start:end], "FFY::#OFF", f"FFY:{TARGET6}:#FF")
        check("two FFs packed in one synthetic component", pcf, shared, True, "Both requested FF bindings")
        check("two FFs claiming one slot", pcf, replace_once(shared, f"FFY:{TARGET6}:#FF", f"FFX:{TARGET6}:#FF"), False, "Two targets claim the same FF slot")
        check("empty XDL", separate_pcf, "", False, "No XDL instance statements found")
    print("Synthetic parser checks completed; no placement or timing result is implied.")


if __name__ == "__main__":
    main()
