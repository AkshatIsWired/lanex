#!/usr/bin/env python3
"""sha256 manifest of a directory tree: ``<sha256>  <size>  <relpath>`` sorted.

``--exclude NAME`` skips a top-level entry (repeatable) — the differential and
e2e jobs use ``--exclude runs`` to prove a flow never touches the user's design
sources (only ``runs/`` may change).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from typing import List


def manifest(root: str, exclude: List[str]) -> List[str]:
    rows: List[str] = []
    root = os.path.abspath(root)
    for dp, dn, fn in os.walk(root):
        if dp == root:
            dn[:] = [d for d in dn if d not in exclude]
        dn.sort()
        for f in sorted(fn):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root)
            if os.path.sep in rel and rel.split(os.path.sep, 1)[0] in exclude:
                continue
            try:
                h = hashlib.sha256()
                with open(p, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                rows.append(f"{h.hexdigest()}  {os.path.getsize(p)}  {rel}")
            except OSError as ex:
                rows.append(f"ERROR:{ex}  -1  {rel}")
    return rows


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("dir")
    ap.add_argument("--exclude", action="append", default=[],
                    help="top-level entry name to skip (repeatable)")
    a = ap.parse_args(argv)
    for row in manifest(a.dir, a.exclude):
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
