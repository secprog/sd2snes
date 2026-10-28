#!/usr/bin/env python3
"""Audit the runner-only DSPx placement probe without editing its inputs.

The PCF locates a mapped COMP, whereas the named flip-flops are BELs inside
that component.  Bind each requested FF to its XDL component before checking
the corresponding PCF range and the position in the selected NCD.
"""

import re
import sys
from pathlib import Path


TARGETS = ("snes_dspx/stack<9>_3", "snes_dspx/stack<9>_6")
LOCATION = "SLICE_X30Y50:SLICE_X34Y55"


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: inspect-dsp-placement-probe.py MAIN.PCF DESIGN.XDL NCD_NAME")
    pcf_path, xdl_path = (Path(value) for value in sys.argv[1:3])
    ncd_name = sys.argv[3]
    if ncd_name not in ("main_map.ncd", "main.ncd"):
        raise SystemExit("Unexpected NCD name")
    pcf = pcf_path.read_text()
    xdl = xdl_path.read_text()

    # Keep all LOCATE statements for a component so ambiguity cannot pass.
    locations = {}
    for match in re.finditer(
        r'(?m)^\s*COMP\s+"([^"\n]+)"\s+LOCATE\s*=\s*([^;]*);', pcf
    ):
        locations.setdefault(match.group(1), []).append(match.group(2).strip())

    statements = re.findall(r"(?ms)^\s*inst\s+.*?;", xdl)
    if not statements:
        raise SystemExit("No XDL instance statements found")
    bindings = {target: [] for target in TARGETS}
    for statement in statements:
        cfg_match = re.search(r'\bcfg\s+"((?:[^"\\]|\\.)*)"', statement, re.S)
        if not cfg_match:
            continue
        cfg = cfg_match.group(1)
        for target in TARGETS:
            ff_matches = re.findall(
                r"(?<!\S)(FFX|FFY):" + re.escape(target) + r":#FF(?=\s|$)", cfg
            )
            if not ff_matches:
                continue
            header = re.match(
                r'\s*inst\s+"([^"\n]+)"\s+"(SLICEL|SLICEM)"\s*,\s*'
                r'placed\s+\S+\s+(SLICE_X(\d+)Y(\d+))\b',
                statement,
            )
            if not header:
                raise SystemExit(f"Target {target} has no placed SLICE instance")
            for ff in ff_matches:
                bindings[target].append(
                    (header.group(1), ff, header.group(3), int(header.group(4)), int(header.group(5)), statement)
                )

    print(f"Auditing placement from {ncd_name}; this is not a timing result")
    seen_slots = set()
    comp_sites = {}
    for target in TARGETS:
        if len(bindings[target]) != 1:
            raise SystemExit(f"Expected exactly one placed FF binding for {target}: {bindings[target]}")
        comp, ff, site, x, y, statement = bindings[target][0]
        slot = (comp, ff)
        if slot in seen_slots:
            raise SystemExit(f"Two targets claim the same FF slot: {slot}")
        seen_slots.add(slot)
        if comp in comp_sites and comp_sites[comp] != site:
            raise SystemExit(f"Conflicting sites for component {comp}")
        comp_sites[comp] = site
        entries = locations.get(comp, [])
        if len(entries) != 1:
            raise SystemExit(f"Expected exactly one PCF LOCATE for {comp}: {entries}")
        expected = re.fullmatch(r'SITE\s+"([^"\n]+)"\s+LEVEL\s+\d+', entries[0])
        if not expected or expected.group(1) != LOCATION:
            raise SystemExit(f"Wrong PCF placement range for {comp}: {entries[0]}")
        if not (30 <= x <= 34 and 50 <= y <= 55):
            raise SystemExit(f"{target} was placed outside the diagnostic range: {site}")
        print(f"{target}: {comp} {ff}, PCF {LOCATION}, {site}")
        print(f'COMP "{comp}" LOCATE = {entries[0]};')
        print(statement)
    if len(set(comp_sites.values())) != len(comp_sites):
        raise SystemExit("Distinct components claim the same SLICE site")
    print("Both requested FF bindings and their actual component placements were verified.")


if __name__ == "__main__":
    main()
