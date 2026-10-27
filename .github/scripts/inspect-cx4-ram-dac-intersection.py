#!/usr/bin/env python3
"""Inspect a stricter, diagnostic-only RAM-to-FF trace against the DAC group."""

import argparse
import re
from pathlib import Path


NAME = "TS_DIAG_RAM_TO_ALLFF"
ADDITION = (
    'TS_DIAG_RAM_TO_ALLFF = MAXDELAY FROM TIMEGRP "RAMS" '
    'TO TIMEGRP "FFS" TS_CLK21;\n'
)
ORIGINAL = 'TS_DAC2 = MAXDELAY FROM TIMEGRP "RAMS" TO TIMEGRP "DAC" TS_CLK21 / 4;'
TARGETS = tuple(f"snes_dac/ci_0_{n}" for n in range(4))
RAM_PREFIX = "snes_dac/snes_dac_buf/"


def group(text, name):
    parts = re.findall(r"(?ms)^TIMEGRP\s+" + re.escape(name) + r"\s*=\s*(.*?);", text)
    if len(parts) != 1:
        raise SystemExit(f"Expected exactly one {name} group; inspection inconclusive")
    return set(re.findall(r'\bBEL\s+"([^"]+)"', parts[0]))


def original_pcf(path):
    text = Path(path).read_text(encoding="utf-8", errors="strict")
    for line in (ORIGINAL, 'TIMEGRP "RAMS" = RAMS(*);', 'TIMEGRP "FFS" = FFS(*);'):
        if text.count(line) != 1:
            raise SystemExit(f"Missing or duplicate original PCF line: {line}")
    if text.count("SCHEMATIC END;") != 1 or NAME in text:
        raise SystemExit("Unexpected original PCF terminator or diagnostic name")
    dac = group(text, "DAC")
    clk = group(text, "CLK21")
    if len(dac) != 40 or not all(t in clk and t not in dac for t in TARGETS):
        raise SystemExit("Unexpected DAC or CLK21 membership; inspection inconclusive")
    return text, dac


def prepare(source, destination):
    original, dac = original_pcf(source)
    result = original.replace("SCHEMATIC END;", ADDITION + "SCHEMATIC END;", 1)
    if result.replace(ADDITION, "", 1) != original:
        raise SystemExit("Diagnostic PCF failed exact original recovery")
    Path(destination).write_text(result, encoding="utf-8")
    print(f"Preserved every original PCF line and all {len(dac)} DAC members.")
    print("Added a separate one-cycle RAMS-to-FFS diagnostic; this is not a production timing result.")


def section(text, name):
    matches = re.findall(r"(?ms)^Timing constraint:\s*" + re.escape(name)
                         + r"\b.*?(?=^={10,}|\Z)", text)
    if len(matches) != 1:
        raise SystemExit(f"Missing or duplicate {name} section; inspection inconclusive")
    return matches[0]


def counts(part, name):
    match = re.search(r"(\d+) paths analyzed,\s*(\d+) endpoints analyzed,\s*"
                      r"(\d+) failing endpoints", part)
    if not match:
        raise SystemExit(f"Missing {name} coverage summary; inspection inconclusive")
    return tuple(map(int, match.groups()))


def check(pcf, native_report, diagnostic_report, tsi):
    _, dac = original_pcf(pcf)
    native = Path(native_report).read_text(encoding="utf-8", errors="strict")
    if "Analysis completed" not in native:
        raise SystemExit("Incomplete native report; inspection inconclusive")
    if not re.search(r"Timing errors:\s*0\s+Score:\s*0\s+\(Setup/Max:\s*0,\s*Hold:\s*0\)", native):
        raise SystemExit("Native timing was not explicitly clean; inspection inconclusive")
    if counts(section(native, "TS_DAC2"), "TS_DAC2") != (0, 0, 0):
        raise SystemExit("Original TS_DAC2 is no longer the observed zero-path constraint")

    interactions = Path(tsi).read_text(encoding="utf-8", errors="strict")
    if "Constraint Interaction Report" not in interactions or "analysis completed" not in interactions.lower():
        raise SystemExit("Incomplete interaction report; inspection inconclusive")
    removed = re.findall(r"(?ms)^Constraint interactions for\s+" + NAME
                         + r"\b.*?(?=^Constraint interactions for|^Clock Domain Overlap Report|\Z)",
                         interactions)
    if any(re.search(r"\b[1-9]\d*\s+paths? removed", block) for block in removed):
        raise SystemExit("A higher-priority constraint removes diagnostic paths; inspection inconclusive")

    report = Path(diagnostic_report).read_text(encoding="utf-8", errors="strict")
    if "Analysis completed" not in report:
        raise SystemExit("Incomplete diagnostic report; inspection inconclusive")
    part = section(report, NAME)
    if not re.search(r'(?s)FROM TIMEGRP\s+"RAMS"\s+TO\s+TIMEGRP\s+"FFS"\s+TS_CLK21\s*;', part):
        raise SystemExit("Wrong diagnostic constraint; inspection inconclusive")
    paths, endpoints, failures = counts(part, NAME)
    errors = re.search(r"(\d+) timing errors? detected\.\s*\("
                       r"(\d+) setup errors?,\s*(\d+) hold errors?", part)
    if not errors or tuple(map(int, errors.groups())) != (0, 0, 0) or failures:
        raise SystemExit("Diagnostic has missing or failing timing summary; inspection inconclusive")
    if not paths or not endpoints:
        raise SystemExit("Diagnostic has no path coverage; inspection inconclusive")

    blocks = re.split(r"(?m)(?=^Paths for end point )", part)[1:]
    if len(blocks) != endpoints:
        raise SystemExit(f"Expected {endpoints} reported endpoints, found {len(blocks)}; inspection inconclusive")
    found = set()
    examples = {}
    for block in blocks:
        head = re.match(r"Paths for end point\s+(\S+)\s+\(", block)
        src = re.search(r"(?m)^\s*Source:\s+(\S+)\s+\(RAM\)", block)
        dest = re.search(r"(?m)^\s*Destination:\s+(\S+)\s+\(FF\)", block)
        req = re.search(r"(?m)^\s*Requirement:\s+([0-9.]+)ns", block)
        if not head or not src or not dest or head.group(1) != dest.group(1) or not req:
            raise SystemExit("Missing or inconsistent RAM/FF path details; inspection inconclusive")
        if not 12.493 <= float(req.group(1)) <= 12.496:
            raise SystemExit("Unexpected diagnostic requirement; inspection inconclusive")
        found.add(dest.group(1))
        if dest.group(1) in TARGETS and src.group(1).startswith(RAM_PREFIX):
            examples[dest.group(1)] = src.group(1)
    if set(examples) != set(TARGETS):
        raise SystemExit("Missing known DAC-buffer positive control; inspection inconclusive")
    intersection = sorted(found & dac)
    print(f"Original DAC group: {len(dac)} members.")
    print(f"Diagnostic: {paths} paths, {endpoints} reported endpoints, zero setup/hold errors.")
    print(f"Known DAC-buffer controls: {len(examples)} of {len(TARGETS)}.")
    print(f"Reported RAM-to-FF destination names also in original DAC group: {len(intersection)}")
    for name in intersection:
        print(f"  {name}")
    print("Diagnostic evidence is limited to reported paths and names; it is not hardware qualification.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("source")
    p.add_argument("destination")
    c = sub.add_parser("check")
    c.add_argument("pcf")
    c.add_argument("native_report")
    c.add_argument("diagnostic_report")
    c.add_argument("tsi")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.source, args.destination)
    else:
        check(args.pcf, args.native_report, args.diagnostic_report, args.tsi)


if __name__ == "__main__":
    main()
