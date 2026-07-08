#!/usr/bin/env python3
# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Layout-file validity probe for the differential CI.

Plain-language purpose: when a user clicks "open my chip in KLayout / Magic /
GDS3D / OpenROAD", the GUI picks a layout file from the finished run and hands
its path to that tool. This probe re-derives THE SAME file the GUI would pick
(mirrors ``routes._final_gds`` / ``_final_odb``) and checks it is real content
a viewer can actually draw — non-empty, and (for GDS) a genuine GDSII stream —
so CI proves the correct output reaches the viewers AND catches the day a run
hands over an empty / truncated / not-really-a-GDS file (a viewer would then
open a blank window that a user could mistake for a real empty chip).

Standalone stdlib; imported by ``differential_run.py`` (gate G8) and unit-tested
in ``lanex/tests/test_ci_helpers.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

# A GDSII stream begins with a HEADER record: length 0x0006, record-type 0x00,
# data-type 0x02 (int16) → bytes ``00 06 00 02``. gzip magic is ``1f 8b`` (some
# flows gzip the stream, even under a ``.gds`` name).
_GDS_HEADER = b"\x00\x06\x00\x02"
_GZIP_MAGIC = b"\x1f\x8b"

# The GUI's final-GDS search order (routes._final_gds): first match wins.
_GDS_SUBDIRS = ("gds", "klayout_gds", "mag_gds")


def gds_status(path: str | Path) -> Dict[str, object]:
    """Is *path* a layout file a viewer can render? ``{ok, reason}``.

    Existence + non-empty always; GDSII header (or gzip magic) for ``.gds`` /
    ``.gdsii`` / ``.gz``. Other tool-owned formats (``.odb`` etc.) get the
    existence + non-empty check only. Reads at most 4 bytes."""
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "reason": "file not found"}
    try:
        size = p.stat().st_size
    except OSError as ex:
        return {"ok": False, "reason": str(ex)}
    if size == 0:
        return {"ok": False, "reason": "empty (0 bytes) — run failed/cancelled before writing it"}
    name = p.name.lower()
    try:
        with p.open("rb") as fh:
            head = fh.read(4)
    except OSError as ex:
        return {"ok": False, "reason": str(ex)}
    if name.endswith(".gz"):
        if head[:2] != _GZIP_MAGIC:
            return {"ok": False, "reason": "not gzip data — truncated/corrupt .gz"}
        return {"ok": True, "reason": "gzip"}
    if name.endswith(".gds") or name.endswith(".gdsii"):
        if head[:2] == _GZIP_MAGIC:
            return {"ok": True, "reason": "gzip"}
        if head != _GDS_HEADER:
            return {"ok": False, "reason": "no GDSII header — truncated or not a real GDS"}
        return {"ok": True, "reason": "gdsii"}
    return {"ok": True, "reason": "non-empty"}


def pick_final_gds(run_dir: str | Path) -> Optional[Path]:
    """The GDS the GUI viewer would open for this run (mirror of
    ``routes._final_gds``): first ``*.gds`` then ``*.gds.gz`` under
    ``final/{gds,klayout_gds,mag_gds}``. ``None`` if the run has none."""
    final = Path(run_dir) / "final"
    for sub in _GDS_SUBDIRS:
        d = final / sub
        if d.is_dir():
            hits = sorted(d.glob("*.gds")) + sorted(d.glob("*.gds.gz"))
            if hits:
                return hits[0]
    return None


def viewer_gds_status(run_dir: str | Path) -> Dict[str, object]:
    """Validity of the exact GDS a viewer would open for *run_dir*.
    ``{ok, reason, path}``; ``ok=False`` when there is no GDS at all."""
    pick = pick_final_gds(run_dir)
    if pick is None:
        return {"ok": False, "reason": "no final GDS in this run", "path": None}
    st = gds_status(pick)
    st["path"] = str(pick)
    return st


def _main(argv: List[str]) -> int:
    if not argv:
        print("usage: layout_probe.py <run_dir> [run_dir …]")
        return 2
    rc = 0
    for rd in argv:
        st = viewer_gds_status(rd)
        mark = "OK " if st["ok"] else "BAD"
        print(f"{mark} {rd} :: {st['reason']} :: {st.get('path')}")
        if not st["ok"]:
            rc = 1
    return rc


if __name__ == "__main__":
    import sys
    sys.exit(_main(sys.argv[1:]))
