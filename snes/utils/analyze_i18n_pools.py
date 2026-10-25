#!/usr/bin/env python3
"""Report resident string-pool partitions without generating assembly or binaries.

Run on a GitHub runner before the menu build. Optional --c1-bytes/--c2-bytes
are observed bank totals for the current POOL_B_LANGS, so deltas predict the
same source's link totals after repartitioning. The menu linker remains the
final check, including other objects and bank placement.
"""
import argparse
import ast
import itertools
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import build_const as bc


def generator_constant(name):
    tree = ast.parse(Path(bc.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == name
                for target in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError("build_const.py has no literal " + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--c1-bytes", type=int)
    parser.add_argument("--c2-bytes", type=int)
    parser.add_argument("--limit", type=int, default=16)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    codes = ("ptbr", "es", "de", "fr", "it", "ru", "nl", "ja", "zh", "ptpt")
    dictionaries = {code: bc.load_dict(here / ("lang_" + code + ".py"))
                    for code in codes}
    latin = ("en",) + tuple(code for code in codes if code not in bc.CJK_LANGS)
    _, english = bc.parse_base(here.parent / "const.a65")
    drop = generator_constant("DROP_PREFIXES")
    separate = generator_constant("FM_PREFIXES")
    current_b = frozenset(generator_constant("POOL_B_LANGS"))
    translated = {label for dictionary in dictionaries.values() for label in dictionary
                  if not label.startswith(drop) and not label.startswith(separate)}
    strings = {code: set() for code in latin}
    table_count = 0
    for label in sorted(translated):
        en = english[label]
        normalized_en = bc.encode_string(bc.decode_args(en))

        def differs(code):
            text = dictionaries[code].get(label)
            if not text:
                return False
            # CJK text necessarily differs from the Latin English source, and
            # its bytes live in an external WRAM pool, outside both candidates.
            if any(bc.is_cjk(char) for char in text):
                return True
            return bc.encode_string(text) != normalized_en

        if not any(differs(code) for code in codes):
            continue                      # generator emits one neutral C0 string
        table_count += 1
        strings["en"].add(en)
        for code in latin[1:]:
            text = dictionaries[code].get(label)
            strings[code].add(bc.encode_string(text) if text else en)

    sizes = {text: len(bc.args_to_bytes(text))
             for column in strings.values() for text in column}

    def pool_bytes(group):
        unique = set().union(*(strings[code] for code in group))
        return sum(sizes[text] for text in unique)

    baseline_a = pool_bytes(set(latin) - current_b)
    baseline_b = pool_bytes(current_b)
    candidates = []
    for mask in itertools.product((False, True), repeat=len(latin) - 1):
        pool_b = {code for code, selected in zip(latin[1:], mask) if selected}
        # Keep the two Portuguese variants together so their shared strings
        # are stored once. English stays in pool A to avoid complement duplicates.
        if ("ptbr" in pool_b) != ("ptpt" in pool_b):
            continue
        pool_a = set(latin) - pool_b
        a_bytes, b_bytes = pool_bytes(pool_a), pool_bytes(pool_b)
        row = {"pool_b": [code for code in latin if code in pool_b],
               "a_bytes": a_bytes, "b_bytes": b_bytes,
               "c1_delta": b_bytes - baseline_b,
               "c2_delta": a_bytes - baseline_a}
        if args.c1_bytes is not None:
            row["c1_total"] = args.c1_bytes + row["c1_delta"]
        if args.c2_bytes is not None:
            row["c2_total"] = args.c2_bytes + row["c2_delta"]
        candidates.append(row)

    def rank(row):
        c1 = row.get("c1_total", row["b_bytes"])
        c2 = row.get("c2_total", row["a_bytes"])
        return (max(0, c1 - 65536) + max(0, c2 - 65536),
                max(c1, c2), c1 + c2)

    candidates.sort(key=rank)
    report = {"baseline": {"pool_b": sorted(current_b),
                           "a_bytes": baseline_a, "b_bytes": baseline_b,
                           "resident_dispatch_tables": table_count},
              "candidates": candidates[:args.limit]}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
