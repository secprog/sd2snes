#!/usr/bin/env python3
"""Extract evidence of DAC sampler paths from the original-constraint TRACE report."""

import argparse
import re
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report")
    parser.add_argument("--cycles", type=int, choices=(1, 4), default=4)
    parser.add_argument("--path", nargs=2, metavar=("SOURCE", "DESTINATION"))
    args = parser.parse_args()
    report = Path(args.report).read_text()
    if "Analysis completed" not in report:
        raise SystemExit("TRACE did not complete the original-constraint analysis")
    section = re.search(
        r'(?ms)^Timing constraint: TS_DAC = MAXDELAY.*?(?=^={10,}|\Z)',
        report,
    )
    constraint = "TS_CLK21;" if args.cycles == 1 else "TS_CLK21 / 4;"
    requirement = r"12\.49[3-6]ns" if args.cycles == 1 else r"49\.97[0-9]ns"
    if not section or constraint not in section.group(0):
        raise SystemExit(f"Expected {args.cycles}-cycle TS_DAC section is missing")
    blocks = re.split(r"(?m)(?=^Paths for end point )", section.group(0))
    expected = (
        (tuple(args.path),)
        if args.path
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
            paths = re.split(r"(?m)(?=^Slack(?: \(setup paths?\))?:)", candidate)
            for path in paths:
                if (
                    re.search(rf"(?m)^\s*Source:\s+{re.escape(source)}\s", path)
                    and re.search(rf"(?m)^\s*Destination:\s+{re.escape(destination)}\s", path)
                    and re.search(rf"(?m)^\s*Requirement:\s*{requirement}", path)
                ):
                    matched += 1
                    print(f"TS_DAC path {source} -> {destination}:")
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
    print(f"Found {matched} sampler path(s) under the {args.cycles}-cycle TS_DAC.")
    print("TRACE describes physical paths; RTL cycle semantics and hardware remain separate questions.")


if __name__ == "__main__":
    main()
