#!/usr/bin/env python3
"""Prepare and check a stricter, report-only CX4 timing counterfactual."""

import re
import sys
from pathlib import Path

ORIGINAL = b'TS_DAC = MAXDELAY FROM TIMEGRP "FFS" TO TIMEGRP "DAC" TS_CLK21 / 4;'
SINGLE_CYCLE = b'TS_DAC = MAXDELAY FROM TIMEGRP "FFS" TO TIMEGRP "DAC" TS_CLK21;'


def prepare(original_path, diagnostic_path):
    original = Path(original_path).read_bytes()
    if original.count(ORIGINAL) != 1 or SINGLE_CYCLE in original:
        raise SystemExit("Expected exactly one original four-cycle TS_DAC in the routed PCF")
    diagnostic = original.replace(ORIGINAL, SINGLE_CYCLE, 1)
    if diagnostic.replace(SINGLE_CYCLE, ORIGINAL, 1) != original:
        raise SystemExit("Diagnostic PCF contains an unexpected change")
    Path(diagnostic_path).write_bytes(diagnostic)
    print("Prepared diagnostic PCF: only TS_DAC is tightened to one clock cycle.")


def check(report_path):
    report = Path(report_path).read_text()
    if "Analysis completed" not in report:
        raise SystemExit("TRACE did not finish the counterfactual analysis")
    section = re.search(
        r'(?ms)^Timing constraint: TS_DAC = MAXDELAY.*?(?=^={10,}|\Z)',
        report,
    )
    if not section:
        raise SystemExit("TRACE did not report the diagnostic TS_DAC constraint")
    block = section.group(0)
    counts = re.search(
        r"(?m)^\s*(\d+) paths analyzed,\s*(\d+) endpoints analyzed,\s*(\d+) failing endpoints",
        block,
    )
    errors = re.search(
        r"(?m)^\s*(\d+) timing errors detected\.\s*\((\d+) setup errors,\s*(\d+) hold errors",
        block,
    )
    requirement = re.search(r"(?m)^\s*Requirement:\s*([\d.]+)ns", block)
    total = re.search(r"(?m)^Timing errors:\s*(\d+)\s+Score:\s*(\d+)", report)
    if not all((counts, errors, requirement, total)):
        raise SystemExit("Missing diagnostic path, timing or completion data")
    paths, endpoints, failing = map(int, counts.groups())
    errors_total, setup_errors, hold_errors = map(int, errors.groups())
    required_ns = float(requirement.group(1))
    all_errors, score = map(int, total.groups())
    if paths == 0 or endpoints == 0 or not 12.493 <= required_ns <= 12.496:
        raise SystemExit("The diagnostic did not analyze DAC paths at the expected one-cycle period")
    print(
        f"Counterfactual TS_DAC: {paths} paths, {endpoints} endpoints, "
        f"{failing} failing endpoints, {setup_errors} setup errors, "
        f"{hold_errors} hold errors, requirement {required_ns:.3f} ns."
    )
    print(f"Counterfactual total: {all_errors} timing errors, score {score}.")
    if failing or errors_total or setup_errors or hold_errors or all_errors or score:
        raise SystemExit("The stricter counterfactual has timing errors; production constraints were unchanged")


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "prepare":
        prepare(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3 and sys.argv[1] == "check":
        check(sys.argv[2])
    else:
        raise SystemExit("usage: cx4-single-cycle-audit.py prepare ORIGINAL.PCF DIAGNOSTIC.PCF | check REPORT.TWR")


if __name__ == "__main__":
    main()
