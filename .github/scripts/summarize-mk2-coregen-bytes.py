#!/usr/bin/env python3
"""Describe byte offsets in retained NGCs on a hosted runner, without decoding them."""

import hashlib
import sys
from pathlib import Path


IPS = {
    "basex": ("dac_buf", "msu_databuf", "snescmd_buf"),
    "dspx": ("dac_buf", "msu_databuf", "snescmd_buf", "upd77c25_datram",
             "upd77c25_datrom", "upd77c25_pgmrom"),
}


def ranges(left, right):
    """Byte offsets that differ; unlike a sequence alignment, never shift data."""
    changes = [i for i in range(max(len(left), len(right))) if left[i:i + 1] != right[i:i + 1]]
    result = []
    for i in changes:
        if result and i == result[-1][1]:
            result[-1] = (result[-1][0], i + 1)
        else:
            result.append((i, i + 1))
    return changes, result


def window(data, start, end):
    part = data[max(0, start - 16):min(len(data), end + 16)]
    if len(part) > 96:
        return part[:48].hex() + "..." + part[-48:].hex() + " (middle omitted)"
    return part.hex()


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in IPS:
        raise SystemExit("usage: summarize-mk2-coregen-bytes.py CORE ARTIFACT_DIR")
    core, root = sys.argv[1], Path(sys.argv[2])
    print("Offset comparison only: unequal bytes do not establish a functional difference, and equal regions do not prove equivalence.")
    print("Offsets are zero-based and ranges use an exclusive end. Hex context extends by at most 16 bytes.")
    for ip in IPS[core]:
        data = {sample: (root / f"{sample}-outputs" / f"{ip}.ngc").read_bytes()
                for sample in ("a1", "a2", "b")}
        for sample, blob in data.items():
            if not blob:
                raise SystemExit(f"empty sample {sample}/{ip}")
            print(f"{ip} {sample}: length={len(blob)} sha256={hashlib.sha256(blob).hexdigest()}")
        positive, _ = ranges(data["a1"], data["a1"])
        negative, negative_ranges = ranges(data["a1"], data["a1"] + b"\x01")
        if positive or negative != [len(data["a1"])] or negative_ranges != [(len(data["a1"]), len(data["a1"]) + 1)]:
            raise SystemExit(f"offset comparison control failed: {ip}")
        print(f"{ip}: same-file and appended-byte offset controls passed")
        for left_name, right_name in (("a1", "a2"), ("a1", "b"), ("a2", "b")):
            left, right = data[left_name], data[right_name]
            changes, spans = ranges(left, right)
            print(f"{ip} {left_name}/{right_name}: lengths={len(left)}/{len(right)}, differing_offsets={len(changes)}, contiguous_ranges={len(spans)}")
            # Always show the number of offsets/ranges; bound context output and
            # say explicitly when the full set of ranges is not printed.
            shown = spans if len(spans) <= 80 else spans[:40] + spans[-40:]
            if len(shown) != len(spans):
                print(f"  Context truncated: showing first/last 40 of {len(spans)} ranges")
            for start, end in shown:
                print(f"  [{start},{end}) left={window(left, start, end)} right={window(right, start, end)}")
    print("No byte range is classified as metadata, logic, or timing evidence by this report.")


if __name__ == "__main__":
    main()
