#!/usr/bin/env python3
"""Extract selected DAC RAM paths from an unmodified-constraint TRACE report."""

import argparse
import re
from pathlib import Path


TARGETS = tuple(f"snes_dac/ci_0_{index}" for index in range(4))
RAM_PREFIX = "snes_dac/snes_dac_buf/"


def check_pcf(path):
    text = Path(path).read_text(encoding="utf-8")
    expected = 'TS_DAC2 = MAXDELAY FROM TIMEGRP "RAMS" TO TIMEGRP "DAC" TS_CLK21 / 4;'
    if text.count(expected) != 1 or text.count('TIMEGRP "RAMS" = RAMS(*);') != 1:
        raise SystemExit("Expected unchanged original RAMS and TS_DAC2 constraints")
    members = {}
    for group in ("CLK21", "DAC"):
        matches = re.findall(r"(?ms)^TIMEGRP\s+" + group + r"\s*=\s*(.*?);", text)
        if len(matches) != 1:
            raise SystemExit(f"Expected one {group} group")
        members[group] = set(re.findall(r'\bBEL\s+"([^"]+)"', matches[0]))
    for target in TARGETS:
        if target not in members["CLK21"] or target in members["DAC"]:
            raise SystemExit(f"Unexpected original group membership: {target}")
    print("Original PCF: TS_DAC2 unchanged; four target registers in CLK21 and absent from DAC.")


def check_report(path):
    section = False
    saw_clk = False
    saw_completion = False
    endpoint = None
    block = []
    found = {}
    summary = None
    error_summary = None

    def consume():
        nonlocal block
        if not block or not endpoint:
            block = []
            return
        content = "".join(block)
        source = re.search(r"(?m)^\s*Source:\s+(\S+)\s+\(RAM\)", content)
        dest = re.search(r"(?m)^\s*Destination:\s+(\S+)\s+\(FF\)", content)
        requirement = re.search(r"(?m)^\s*Requirement:\s+([0-9.]+)ns", content)
        source_clock = re.search(r"(?m)^\s*Source Clock:\s+CLK2 rising", content)
        dest_clock = re.search(r"(?m)^\s*Destination Clock:\s+CLK2 rising", content)
        if (source and source.group(1).startswith(RAM_PREFIX) and dest
                and dest.group(1) == endpoint and requirement and source_clock and dest_clock
                and 12.493 <= float(requirement.group(1)) <= 12.496):
            found.setdefault(endpoint, content.rstrip())
        block = []

    with Path(path).open(encoding="utf-8", errors="strict") as handle:
        for line in handle:
            if "Analysis completed" in line:
                saw_completion = True
            if line.startswith("Timing constraint:"):
                consume()
                section = bool(re.match(r"^Timing constraint:\s+TS_CLK21\s*=\s*PERIOD\b", line))
                if section:
                    if saw_clk:
                        raise SystemExit("Duplicate TS_CLK21 section")
                    saw_clk = True
                endpoint = None
                continue
            if section and re.match(r"^={10,}", line):
                consume()
                section, endpoint = False, None
                continue
            if not section:
                continue
            counts = re.match(r"^\s*(\d+) paths analyzed,\s*(\d+) endpoints analyzed,\s*(\d+) failing endpoints", line)
            if counts:
                summary = tuple(map(int, counts.groups()))
            errors = re.match(r"^\s*(\d+) timing errors? detected\.\s*\((\d+) setup errors?,\s*(\d+) hold errors?", line)
            if errors:
                error_summary = tuple(map(int, errors.groups()))
            if line.startswith("Paths for end point "):
                consume()
                match = re.match(r"^Paths for end point\s+(\S+)\s", line)
                endpoint = match.group(1) if match and match.group(1) in TARGETS else None
            elif endpoint and re.match(r"^Slack(?: \(setup path\))?:", line):
                consume()
                block = [line]
            elif block and re.match(r"^-{10,}", line):
                consume()
            elif block:
                block.append(line)
    consume()
    if not saw_completion or not saw_clk:
        raise SystemExit("Missing completed original TS_CLK21 report; inspection inconclusive")
    if not summary or summary[0] == 0 or summary[1] == 0 or summary[2] != 0:
        raise SystemExit("Missing or failing original TS_CLK21 coverage; inspection inconclusive")
    if error_summary != (0, 0, 0):
        raise SystemExit("Missing or failing original TS_CLK21 setup/hold summary; inspection inconclusive")
    missing = [target for target in TARGETS if target not in found]
    if missing:
        raise SystemExit("Missing RAM-to-filter path(s) under original TS_CLK21; inspection inconclusive: " + ", ".join(missing))
    for target in TARGETS:
        print(f"Original TS_CLK21 RAM-to-filter path to {target}:")
        print(found[target])
    print(f"Original TS_CLK21: {summary[0]} paths, {summary[1]} endpoints, no setup/hold errors.")
    print("Four selected RAM paths were explicitly reported under the original clock constraint.")
    print("This is focused timing evidence, not complete I/O/CDC/jitter or hardware qualification.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pcf")
    parser.add_argument("report")
    args = parser.parse_args()
    check_pcf(args.pcf)
    check_report(args.report)


if __name__ == "__main__":
    main()
