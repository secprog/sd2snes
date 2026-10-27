#!/usr/bin/env python3
"""Extract evidence of DAC sampler paths from the original-constraint TRACE report."""

import re
import sys
from pathlib import Path


def main():
    if len(sys.argv) not in (2, 5) or (len(sys.argv) == 5 and sys.argv[2] != "--path"):
        raise SystemExit("usage: inspect-cx4-sampler-paths.py REPORT.twr [--path SOURCE DESTINATION]")
    report = Path(sys.argv[1]).read_text()
    if "Analysis completed" not in report:
        raise SystemExit("TRACE did not complete the original-constraint analysis")
    section = re.search(
        r'(?ms)^Timing constraint: TS_DAC = MAXDELAY.*?(?=^={10,}|\Z)',
        report,
    )
    if not section or 'TS_CLK21 / 4;' not in section.group(0):
        raise SystemExit("Original four-cycle TS_DAC section is missing")
    blocks = re.split(r"(?m)(?=^Paths for end point )", section.group(0))
    expected = (
        ((sys.argv[3], sys.argv[4]),)
        if len(sys.argv) == 5
        else (
            ("snes_dac/sysclk_sreg_0", "snes_dac/sysclk_sreg_1"),
            ("snes_dac/sysclk_sreg_1", "snes_dac/sysclk_sreg_2"),
        )
    )
    matched = 0
    for source, destination in expected:
        candidates = [
            block
            for block in blocks
            if block.startswith(f"Paths for end point {destination} ")
        ]
        for candidate in candidates:
            paths = re.split(r"(?m)(?=^Slack \(setup paths\):)", candidate)
            for path in paths:
                if (
                    re.search(rf"(?m)^\s*Source:\s+{re.escape(source)}\s", path)
                    and re.search(rf"(?m)^\s*Destination:\s+{re.escape(destination)}\s", path)
                    and re.search(r"(?m)^\s*Requirement:\s*49\.97[0-9]ns", path)
                ):
                    matched += 1
                    print(f"Original TS_DAC path {source} -> {destination}:")
                    print(path.rstrip())
        if not candidates:
            print(f"No reported endpoint for {destination}")
        elif not any(
            re.search(rf"(?m)^\s*Source:\s+{re.escape(source)}\s", block)
            for block in candidates
        ):
            print(f"No reported path from {source} to {destination}")
    if not matched:
        raise SystemExit("No expected sampler path was found; diagnostic is inconclusive")
    print(f"Found {matched} sampler path(s) under the original four-cycle TS_DAC.")
    print("TRACE describes physical paths; RTL cycle semantics and hardware remain separate questions.")


if __name__ == "__main__":
    main()
