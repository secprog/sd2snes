#!/usr/bin/env python3
"""Create and inspect a stricter, post-route DAC RAM path diagnostic."""

import argparse
import re
from pathlib import Path


TARGETS = tuple(f"snes_dac/ci_0_{index}" for index in range(4))
ORIGINAL_CONSTRAINT = (
    'TS_DAC2 = MAXDELAY FROM TIMEGRP "RAMS" TO TIMEGRP "DAC" TS_CLK21 / 4;'
)
DIAGNOSTIC_NAME = "TS_DIAG_RAM_TO_FILTER"
DIAGNOSTIC_GROUP = "DAC_FILTER_DIAG"
DIAGNOSTIC_ADDITION = (
    'TIMEGRP "DAC_FILTER_DIAG" = '
    + " ".join(f'BEL "{name}"' for name in TARGETS)
    + ';\n'
    + 'TS_DIAG_RAM_TO_FILTER = MAXDELAY FROM TIMEGRP "RAMS" '
    + 'TO TIMEGRP "DAC_FILTER_DIAG" TS_CLK21;\n'
)


def group(text, name):
    match = re.search(r"(?ms)^TIMEGRP\s+" + re.escape(name) + r"\s*=\s*(.*?);", text)
    if not match:
        raise SystemExit(f"Expected exactly one existing {name} timegroup")
    if len(re.findall(r"(?m)^TIMEGRP\s+" + re.escape(name) + r"\s*=", text)) != 1:
        raise SystemExit(f"Duplicate {name} timegroup")
    return match.group(1)


def prepare(source, destination):
    original = Path(source).read_text(encoding="utf-8")
    if original.count(ORIGINAL_CONSTRAINT) != 1:
        raise SystemExit("Expected the unchanged TS_DAC2 constraint")
    if original.count('TIMEGRP "RAMS" = RAMS(*);') != 1:
        raise SystemExit("Expected the existing predefined RAM group")
    if DIAGNOSTIC_GROUP in original or DIAGNOSTIC_NAME in original:
        raise SystemExit("Diagnostic group or constraint already exists")
    if original.count("SCHEMATIC END;") != 1:
        raise SystemExit("Expected one PCF schematic terminator")
    clk21 = group(original, "CLK21")
    dac = group(original, "DAC")
    for target in TARGETS:
        if f'BEL "{target}"' not in clk21:
            raise SystemExit(f"Expected filter register absent from CLK21: {target}")
        if f'BEL "{target}"' in dac:
            raise SystemExit(f"Filter register unexpectedly appears in DAC group: {target}")
    result = original.replace("SCHEMATIC END;", DIAGNOSTIC_ADDITION + "SCHEMATIC END;", 1)
    if result.replace(DIAGNOSTIC_ADDITION, "", 1) != original:
        raise SystemExit("Diagnostic PCF changed original text")
    Path(destination).write_text(result, encoding="utf-8")
    print("Original TS_DAC2 and every PCF line retained; four existing CLK21 filter registers added to a separate diagnostic group.")
    print("Those four filter registers are absent from the existing DAC group.")


def section(text, name):
    match = re.search(r"(?ms)^Timing constraint:\s*" + re.escape(name)
                      + r"\b.*?(?=^={10,}|\Z)", text)
    if not match:
        raise SystemExit(f"Missing {name} timing section; diagnostic inconclusive")
    return match.group(0)


def counts(part, name):
    match = re.search(r"(\d+) paths analyzed,\s*(\d+) endpoints analyzed,\s*"
                      r"(\d+) failing endpoints", part)
    if not match:
        raise SystemExit(f"Missing path coverage for {name}; diagnostic inconclusive")
    return tuple(map(int, match.groups()))


def check(original_report, diagnostic_report):
    original = Path(original_report).read_text(encoding="utf-8", errors="strict")
    diagnostic = Path(diagnostic_report).read_text(encoding="utf-8", errors="strict")
    original_counts = counts(section(original, "TS_DAC2"), "TS_DAC2")
    print(f"Original TS_DAC2: {original_counts[0]} paths, {original_counts[1]} endpoints, {original_counts[2]} failing endpoints.")
    if original_counts != (0, 0, 0):
        raise SystemExit("Original TS_DAC2 no longer has the observed zero-path result")

    part = section(diagnostic, DIAGNOSTIC_NAME)
    paths, endpoints, failures = counts(part, DIAGNOSTIC_NAME)
    print(f"Diagnostic RAM-to-filter group: {paths} paths, {endpoints} endpoints, {failures} failing endpoints.")
    if paths == 0 or endpoints == 0:
        raise SystemExit("No RAM-to-filter path found; diagnostic inconclusive")
    errors = re.search(r"(\d+) timing errors? detected\.\s*\("
                       r"(\d+) setup errors?,\s*(\d+) hold errors?", part)
    if not errors:
        raise SystemExit("Missing diagnostic setup/hold summary")
    total, setup, hold = map(int, errors.groups())
    blocks = re.findall(r"(?ms)^Slack \(setup path\):.*?(?=^-{5,}|\Z)", part)
    selected = [block for block in blocks
                if re.search(r"(?m)^\s*Source:\s+.*snes_dac/snes_dac_buf", block)
                and any(re.search(r"(?m)^\s*Destination:\s+" + re.escape(target) + r"\b", block)
                        for target in TARGETS)]
    if not selected:
        raise SystemExit("No reported DAC-buffer-to-target path found; diagnostic inconclusive")
    requirement = re.search(r"(?m)^\s*Requirement:\s+([0-9.]+)ns", selected[0])
    if not requirement or not 12.493 <= float(requirement.group(1)) <= 12.496:
        raise SystemExit("Unexpected diagnostic path requirement")
    print(selected[0])
    print(f"Diagnostic timing errors: {total}, setup: {setup}, hold: {hold}.")
    if failures or total or setup or hold:
        raise SystemExit("Stricter diagnostic reported timing errors")
    print("This focused trace identifies a physical RAM-to-filter path; it does not prove all paths or hardware are safe.")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("source")
    p.add_argument("destination")
    c = sub.add_parser("check")
    c.add_argument("original_report")
    c.add_argument("diagnostic_report")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.source, args.destination)
    else:
        check(args.original_report, args.diagnostic_report)


if __name__ == "__main__":
    main()
