#!/usr/bin/env python3
"""Compare a run-bundle zip's members against the run-dir originals, byte-wise.

Each member is located in the run dir (exact relpath first, then a
unique-basename search) and sha256-compared. Members the bundler GENERATES
(they have no on-disk original by design — the manifest and the derived CSVs,
regenerated sorted with identical values, plus SKIPPED.json) are listed but not
byte-compared.

``--strict`` turns the check into a gate: exit 2 if any NON-generated member
differs from its original or has no source file at all.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import zipfile
from typing import List

# Bundle members written by bundle.py's add_text() — generated at export time,
# not copied from disk (see controller/bundle.py). Everything else must be a
# byte-exact copy of a run-dir file.
GENERATED = {"MANIFEST.json", "metrics.csv", "settings.csv", "analytics.csv", "SKIPPED.json"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("bundle")
    ap.add_argument("run_dir")
    ap.add_argument("--root", action="append", default=[],
                    help="extra search root for member originals (repeatable) — "
                         "the 'sources' part copies from the DESIGN dir, not the run dir")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args(argv)

    disk = {}
    for root in [a.run_dir] + a.root:
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                disk.setdefault(f, []).append(os.path.join(dp, f))

    bad = 0
    z = zipfile.ZipFile(a.bundle)
    print("MEMBER | MATCH_MODE | RESULT")
    for info in z.infolist():
        if info.is_dir():
            continue
        name = info.filename
        base = os.path.basename(name)
        if base in GENERATED and "/" not in name:  # generated members sit at zip root
            print(f"{name} | generated | NOT_BYTE_COMPARED size={info.file_size}")
            continue
        data = z.read(name)
        cand = os.path.join(a.run_dir, name)
        if os.path.isfile(cand):
            mode, paths = "relpath", [cand]
        elif base in disk:
            mode, paths = f"basename({len(disk[base])})", disk[base]
        else:
            print(f"{name} | none | SOURCE_NOT_FOUND size={len(data)}")
            bad += 1
            continue
        zh = _sha(data)
        results = []
        for p in paths:
            with open(p, "rb") as fh:
                results.append("EQUAL" if _sha(fh.read()) == zh else "DIFF")
        verdict = "/".join(results)
        # basename fallback: EQUAL to ANY candidate counts (same content exists
        # on disk); relpath match must be EQUAL itself.
        ok = "EQUAL" in results
        if not ok:
            bad += 1
        print(f"{name} | {mode} | {verdict} size={len(data)}")
    if "SKIPPED.json" in z.namelist():
        print("== SKIPPED.json content ==")
        print(z.read("SKIPPED.json").decode("utf-8", "replace"))
    print(f"COUNT non_matching={bad}")
    return 2 if (a.strict and bad) else 0


if __name__ == "__main__":
    sys.exit(main())
