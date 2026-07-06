#!/usr/bin/env python3
"""Flatten a JSON file to sorted ``dotted.key<TAB>repr(value)`` lines.

``--path a.b.c`` descends through wrapper objects before flattening (e.g. the
API's ``{"ok":…, "data":{"metrics":…}}`` envelope → ``--path data.metrics``).
``json.load`` accepts the bare ``Infinity``/``NaN`` literals LibreLane's own
metrics.json may contain; API responses carry them as string tokens instead —
``compare_flat.py --canon-nonfinite`` bridges the two spellings.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Tuple


def flatten(obj: Any, prefix: str = "", out: List[Tuple[str, str]] | None = None) -> List[Tuple[str, str]]:
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k in sorted(obj):
            flatten(obj[k], f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            flatten(v, f"{prefix}[{i}]", out)
    else:
        out.append((prefix, repr(obj)))
    return out


def descend(data: Any, path: str) -> Any:
    for part in [p for p in (path or "").split(".") if p]:
        if not isinstance(data, dict) or part not in data:
            raise KeyError(f"--path component {part!r} not found (have: "
                           f"{sorted(data)[:20] if isinstance(data, dict) else type(data).__name__})")
        data = data[part]
    return data


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file")
    ap.add_argument("--path", default="", help="dotted descent before flattening")
    a = ap.parse_args(argv)
    with open(a.file, encoding="utf-8") as fh:
        data = json.load(fh)
    for k, v in flatten(descend(data, a.path)):
        print(f"{k}\t{v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
