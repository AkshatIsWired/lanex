# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Standard-cell library browser (Phase 4.3).

Lists the cells in a PDK's standard-cell library by parsing the LEF the PDK
already ships (``$PDK_ROOT/<variant>/libs.ref/<scl>/lef/*.lef``). Pure stdlib —
no klayout needed to *list* cells (rendering a cell layout is the optional
image step). No new dependency.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_MACRO_RX = re.compile(r"^\s*MACRO\s+(\S+)", re.MULTILINE)

# Coarse kind classification from common open-PDK cell naming conventions.
_KIND_RULES = [
    # Buffers/delay cells first so dly* isn't misread as a latch.
    (re.compile(r"(?:^|_)(buf|clkbuf|clkdly|dlygate|dlymetal)", re.I), "buffer"),
    # DFF/latch families: (s)(e)df…, dl{x,r,clk}…, dlatch, latch.
    (re.compile(r"(?:^|_)(s?e?df[a-z0-9]*|dl[xrc][a-z0-9]*|dlatch|latch)", re.I), "sequential"),
    (re.compile(r"(?:^|_)(fill|decap|tap|diode|antenna|conb|endcap)", re.I), "physical"),
    (re.compile(r"(?:^|_)(inv|not)", re.I), "inverter"),
    (re.compile(r"(?:^|_)(mux)", re.I), "mux"),
    (re.compile(r"(?:^|_)(fa|ha|maj)", re.I), "arithmetic"),
    (re.compile(r"(?:^|_)(nand|nor|and|or|xor|xnor|aoi|oai)", re.I), "combinational"),
]


def classify_cell(name: str) -> str:
    for rx, kind in _KIND_RULES:
        if rx.search(name):
            return kind
    return "other"


def parse_lef_macros(text: str) -> List[str]:
    """Every ``MACRO <name>`` in a LEF, in file order, de-duplicated."""
    out: List[str] = []
    seen = set()
    for m in _MACRO_RX.finditer(text or ""):
        name = m.group(1)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _scl_lef_dir(pdk: str, scl: Optional[str]) -> Optional[Path]:
    if not scl:
        return None
    # Search every candidate PDK root the GUI knows about — env PDK_ROOT, ciel
    # homes, volare, etc. (same enumeration the Setup PDK picker uses) — not just
    # $PDK_ROOT, so cells resolve for ciel-installed PDKs too.
    roots: List[Path] = []
    try:
        from . import pdk as _pdk
        roots.extend(_pdk._candidate_pdk_roots())
    except Exception:
        pass
    env = os.environ.get("PDK_ROOT")
    if env:
        roots.append(Path(env))
    seen: set = set()
    for root in roots:
        if str(root) in seen:
            continue
        seen.add(str(root))
        for c in (root / pdk / "libs.ref" / scl / "lef",
                  root / "libs.ref" / scl / "lef"):
            if c.is_dir():
                return c
    # Last resort: shallow glob under each root for libs.ref/<scl>/lef.
    for root in roots:
        try:
            for p in root.glob(f"**/libs.ref/{scl}/lef"):
                if p.is_dir():
                    return p
        except Exception:
            continue
    return None


def list_pdk_cells(pdk: str, scl: Optional[str]) -> Dict[str, Any]:
    """List the standard cells of *scl* by parsing its LEF.

    Returns ``{ok, cells:[{cell, kind}], scl, source}`` or
    ``{ok: False, error}`` when the LEF can't be located (e.g. PDK not
    installed). Never raises."""
    lef_dir = _scl_lef_dir(pdk, scl)
    if lef_dir is None:
        return {"ok": False, "error": "could not locate the SCL's LEF — is the PDK installed?",
                "cells": []}
    names: List[str] = []
    seen = set()
    try:
        lefs = sorted(lef_dir.glob("*.lef"))
        for lf in lefs:
            try:
                for n in parse_lef_macros(lf.read_text(encoding="utf-8", errors="replace")):
                    if n not in seen:
                        seen.add(n)
                        names.append(n)
            except Exception:
                continue
    except Exception as ex:
        return {"ok": False, "error": str(ex), "cells": []}
    cells = [{"cell": n, "kind": classify_cell(n)} for n in sorted(names)]
    return {"ok": True, "scl": scl, "source": str(lef_dir), "cells": cells}
