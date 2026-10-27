#!/usr/bin/env python3
"""Audit the runner-only DSPx placement probe; never modify implementation files."""

import re
import sys
from pathlib import Path


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: inspect-dsp-placement-probe.py MAIN.PCF DESIGN.XDL NCD_NAME")
    pcf_path, xdl_path = (Path(value) for value in sys.argv[1:3])
    ncd_name = sys.argv[3]
    pcf = pcf_path.read_text()
    xdl = xdl_path.read_text()
    targets = ("snes_dspx/stack<9>_3", "snes_dspx/stack<9>_6")
    location = "SLICE_X30Y50:SLICE_X34Y55"
    statements = re.findall(r"(?ms)^\s*inst\s+.*?;", xdl)
    if not statements:
        raise SystemExit("No XDL instance statements found")
    print(f"Auditing placement from {ncd_name}")
    for target in targets:
        matching_pcf = [part.strip() for part in pcf.split(";") if target in part and location in part]
        if not matching_pcf:
            raise SystemExit(f"No PCF placement range found for {target}")
        print(f"PCF for {target}:\n" + ";\n".join(matching_pcf) + ";")
        locations = []
        for statement in statements:
            if target not in statement:
                continue
            site = re.search(r"\bplaced\s+\S+\s+SLICE_X(\d+)Y(\d+)\b", statement)
            if site:
                locations.append((int(site.group(1)), int(site.group(2))))
                print(f"XDL instance for {target}:\n{statement[:12000]}")
        if not locations:
            raise SystemExit(f"No placed XDL instance found for {target}")
        if any(not (30 <= x <= 34 and 50 <= y <= 55) for x, y in locations):
            raise SystemExit(f"{target} was placed outside the diagnostic range: {locations}")
        print(f"Verified {target} in the diagnostic range: {locations}")


if __name__ == "__main__":
    main()
