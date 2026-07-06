#!/usr/bin/env python3
"""Cross-check an exported two-column metrics CSV against metrics.json, NUMERICALLY.

The export CSV is ``metric,value`` rows (run-export and the bundle's
metrics.csv both use that shape). For every row whose key exists in the
metrics file, the two values are compared as numbers when both parse
(``float()`` accepts ``Infinity``/``-Infinity``/``NaN`` spellings, and
NaN==NaN counts as equal here), exact strings otherwise. This is deliberately
NOT a substring check — a substring version once produced false alarms on
``Infinity`` vs ``inf`` and exponent-case differences.

``--strict`` exits 2 on any value mismatch or if fewer than ``--min-matched``
keys were compared (an empty/renamed CSV must not pass silently).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from typing import Any, Dict, List

from flatten_metrics import descend, flatten


def _num(s: Any):
    try:
        return float(str(s))
    except (TypeError, ValueError):
        return None


def values_equal(a: Any, b: Any) -> bool:
    fa, fb = _num(a), _num(b)
    if fa is not None and fb is not None:
        if math.isnan(fa) and math.isnan(fb):
            return True
        return fa == fb
    return str(a) == str(b)


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_file")
    ap.add_argument("metrics_json")
    ap.add_argument("--path", default="", help="dotted descent into the JSON")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--min-matched", type=int, default=1)
    a = ap.parse_args(argv)

    with open(a.metrics_json, encoding="utf-8") as fh:
        metrics: Dict[str, str] = dict(flatten(descend(json.load(fh), a.path)))

    matched = mismatched = 0
    with open(a.csv_file, newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if len(row) < 2 or row[0] not in metrics:
                continue
            # metrics holds repr() strings; strip quotes off repr'd strings so
            # the CSV's raw text compares against the actual value.
            want = metrics[row[0]]
            if len(want) >= 2 and want[0] == want[-1] == "'":
                want = want[1:-1]
            if values_equal(row[1], want):
                matched += 1
            else:
                mismatched += 1
                print(f"MISMATCH {row[0]} | csv={row[1]!r} | metrics={want!r}")
    print(f"COUNT keys_in_metrics={len(metrics)} matched={matched} mismatched={mismatched}")
    if a.strict and (mismatched or matched < a.min_matched):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
