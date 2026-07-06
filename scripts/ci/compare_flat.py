#!/usr/bin/env python3
"""Diff two flattened key/value files (the output of flatten_metrics.py).

Exit code is the gate: 0 when the files are identical after exclusions and
canonicalization, 2 when any key is missing on either side or differs in value.

Options:
  --exclude KEY         drop this exact key from both sides (repeatable). Every
                        exclusion in CI must be a reviewed, commented entry —
                        never a pattern.
  --exclude-file F      file of exact keys, one per line, ``#`` comments allowed
  --sub OLD::NEW        literal substring replacement applied to VALUES on both
                        sides before comparing (repeatable; used to canonicalize
                        run-specific paths like the design dir or run tag)
  --canon-nonfinite     treat the API's non-finite STRING tokens ('Infinity',
                        '-Infinity', 'NaN' — the documented wire contract) as
                        equal to the float spellings json.load produces from the
                        tool's own files (inf, -inf, nan)
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List

# repr() of the API's string tokens → repr() of the floats json.load yields
# from LibreLane's own bare-literal metrics.json. Same value, two spellings.
_NONFINITE = {"'Infinity'": "inf", "'-Infinity'": "-inf", "'NaN'": "nan"}


def load(path: str) -> Dict[str, str]:
    d: Dict[str, str] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            k, _, v = line.partition("\t")
            d[k] = v
    return d


def canon(v: str, subs: List[List[str]], nonfinite: bool) -> str:
    for old, new in subs:
        v = v.replace(old, new)
    if nonfinite:
        v = _NONFINITE.get(v, v)
    return v


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--exclude-file")
    ap.add_argument("--sub", action="append", default=[],
                    help="OLD::NEW value substring replacement")
    ap.add_argument("--canon-nonfinite", action="store_true")
    args = ap.parse_args(argv)

    excludes = set(args.exclude)
    if args.exclude_file:
        with open(args.exclude_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    excludes.add(line)
    subs = []
    for s in args.sub:
        old, sep, new = s.partition("::")
        if not sep:
            print(f"bad --sub (want OLD::NEW): {s!r}", file=sys.stderr)
            return 1
        subs.append([old, new])

    a, b = load(args.a), load(args.b)
    excluded = sum(1 for k in excludes if k in a or k in b)
    for k in excludes:
        a.pop(k, None)
        b.pop(k, None)
    a = {k: canon(v, subs, args.canon_nonfinite) for k, v in a.items()}
    b = {k: canon(v, subs, args.canon_nonfinite) for k, v in b.items()}

    only_a = sorted(set(a) - set(b))
    only_b = sorted(set(b) - set(a))
    diff = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    same = len(set(a) & set(b)) - len(diff)
    print(f"COUNT identical={same} value_diff={len(diff)} "
          f"only_in_A={len(only_a)} only_in_B={len(only_b)} excluded={excluded}")
    print("== ONLY_IN_A ==")
    for k in only_a:
        print(f"{k}\t{a[k]}")
    print("== ONLY_IN_B ==")
    for k in only_b:
        print(f"{k}\t{b[k]}")
    print("== VALUE_DIFF (key / A / B) ==")
    for k in diff:
        print(f"{k}\t{a[k]}\t{b[k]}")
    return 2 if (diff or only_a or only_b) else 0


if __name__ == "__main__":
    sys.exit(main())
