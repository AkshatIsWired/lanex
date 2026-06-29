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
"""Custom standard-cell injection / swap-out for a single run (advanced).

LibreLane lets a design pull in extra cell views and exclude library cells via
**verified-real** variables:

* ``EXTRA_LEFS`` / ``EXTRA_LIBS`` / ``EXTRA_GDS`` / ``EXTRA_SPICE_MODELS`` /
  ``EXTRA_VERILOG_MODELS`` / ``EXTRA_CDLS`` / ``EXTRA_SPEFS`` — add the custom
  cell's physical (LEF/GDS), timing (LIB), and verification (SPICE/CDL/Verilog)
  views so synthesis, PnR, STA and signoff all know about it; and
* ``EXTRA_EXCLUDED_CELLS`` — the standard cells to *remove* from synthesis and
  placement, so the tools pick the custom cell "in exchange" for them.

This module stores a per-design set of custom cells in a GUI sidecar
(``<design>/.gui-custom-cells.json``) with the uploaded files saved under
``<design>/custom_cells/<name>/``, and turns the enabled ones into a run-time
override dict. The overrides are applied **per run** (never written into the
user's ``config.json``), matching "use my cell for this run". Pure stdlib; all
writes confined to the design dir; cross-platform via ``pathlib``.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_SIDECAR = ".gui-custom-cells.json"
_CELLS_SUBDIR = "custom_cells"
_MAX_FILE_BYTES = 64 * 1024 * 1024  # a GDS can be sizeable; cap to a sane bound.

# Cell-view kind -> (LibreLane variable, allowed extensions).
_VIEW_VARS: Dict[str, Dict[str, Any]] = {
    "lef":     {"var": "EXTRA_LEFS",           "exts": (".lef",)},
    "lib":     {"var": "EXTRA_LIBS",           "exts": (".lib",)},
    "gds":     {"var": "EXTRA_GDS",            "exts": (".gds", ".gds.gz")},
    "spice":   {"var": "EXTRA_SPICE_MODELS",   "exts": (".spice", ".sp", ".cir")},
    "verilog": {"var": "EXTRA_VERILOG_MODELS", "exts": (".v", ".sv")},
    "cdl":     {"var": "EXTRA_CDLS",           "exts": (".cdl", ".spice")},
    "spef":    {"var": "EXTRA_SPEFS",          "exts": (".spef",)},
}

_NAME_RX = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _sidecar_path(design_dir: str | Path) -> Path:
    return Path(design_dir).resolve() / _SIDECAR


def _load(design_dir: str | Path) -> List[Dict[str, Any]]:
    f = _sidecar_path(design_dir)
    if not f.is_file():
        return []
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
        return doc.get("cells", []) if isinstance(doc, dict) else []
    except Exception:
        return []


def _save(design_dir: str | Path, cells: List[Dict[str, Any]]) -> None:
    f = _sidecar_path(design_dir)
    f.write_text(json.dumps({"cells": cells}, indent=2) + "\n", encoding="utf-8")


def list_cells(design_dir: str | Path) -> Dict[str, Any]:
    """Return the design's saved custom cells (read-only)."""
    return {"ok": True, "cells": _load(design_dir)}


def _confined(design_dir: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(design_dir.resolve())
        return True
    except Exception:
        return False


def save_cell(
    design_dir: str | Path,
    name: str,
    *,
    swap_out: Optional[List[str]] = None,
    views: Optional[Dict[str, Dict[str, str]]] = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    """Save (or replace) a custom cell for *design_dir*.

    *views* maps a kind (``lef``/``lib``/``gds``/…) to ``{filename, content_b64}``
    — the uploaded file's name and base64 bytes. Files are written under
    ``custom_cells/<name>/`` and recorded as design-dir-relative ``dir::`` paths
    so they resolve in both local and container runs. *swap_out* is the list of
    standard-cell names to exclude (``EXTRA_EXCLUDED_CELLS``). Returns
    ``{ok, cell}`` or ``{ok: False, error}``. Never raises."""
    d = Path(design_dir).resolve()
    if not d.is_dir():
        return {"ok": False, "error": "design directory not found"}
    name = (name or "").strip()
    if not name or not _NAME_RX.match(name):
        return {"ok": False, "error": "cell name must be non-empty and use only letters/digits/_.-"}

    cell_dir = (d / _CELLS_SUBDIR / name).resolve()
    if not _confined(d, cell_dir):
        return {"ok": False, "error": "refusing to write outside the design dir"}
    cell_dir.mkdir(parents=True, exist_ok=True)

    saved_views: Dict[str, str] = {}
    for kind, payload in (views or {}).items():
        spec = _VIEW_VARS.get(kind)
        if spec is None:
            return {"ok": False, "error": f"unknown cell view '{kind}'"}
        fname = (payload or {}).get("filename") or f"{name}.{kind}"
        fname = Path(fname).name  # strip any directory component
        ext_ok = any(fname.lower().endswith(e) for e in spec["exts"])
        if not ext_ok:
            return {"ok": False,
                    "error": f"{kind} file should end with {' or '.join(spec['exts'])}"}
        b64 = (payload or {}).get("content_b64") or ""
        try:
            raw = base64.b64decode(b64, validate=False)
        except Exception:
            return {"ok": False, "error": f"could not decode {kind} file"}
        if len(raw) > _MAX_FILE_BYTES:
            return {"ok": False, "error": f"{kind} file exceeds {_MAX_FILE_BYTES // (1024*1024)} MiB"}
        target = (cell_dir / fname).resolve()
        if not _confined(d, target):
            return {"ok": False, "error": "invalid file name"}
        try:
            target.write_bytes(raw)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        saved_views[kind] = "dir::" + str(target.relative_to(d))

    if not saved_views.get("lef"):
        return {"ok": False, "error": "a LEF view is required (the cell's abstract/footprint)"}

    cells = [c for c in _load(d) if c.get("name") != name]
    entry = {
        "name": name,
        "enabled": bool(enabled),
        "swap_out": [s for s in (swap_out or []) if s],
        "views": saved_views,
    }
    cells.append(entry)
    try:
        _save(d, cells)
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "cell": entry}


def set_enabled(design_dir: str | Path, name: str, enabled: bool) -> Dict[str, Any]:
    cells = _load(design_dir)
    found = False
    for c in cells:
        if c.get("name") == name:
            c["enabled"] = bool(enabled)
            found = True
    if not found:
        return {"ok": False, "error": "cell not found"}
    _save(design_dir, cells)
    return {"ok": True}


def remove_cell(design_dir: str | Path, name: str) -> Dict[str, Any]:
    """Remove a custom cell and its files."""
    import shutil
    d = Path(design_dir).resolve()
    cells = [c for c in _load(d) if c.get("name") != name]
    _save(d, cells)
    cell_dir = (d / _CELLS_SUBDIR / name).resolve()
    if _confined(d, cell_dir) and cell_dir.is_dir():
        try:
            shutil.rmtree(cell_dir)
        except Exception:
            pass
    return {"ok": True}


def build_overrides(design_dir: str | Path) -> Dict[str, Any]:
    """Aggregate the enabled custom cells into a run-time override dict.

    List-valued overrides are whitespace-joined (how LibreLane parses list
    overrides on the CLI / via ``config_override_strings``). Returns ``{}`` when
    no enabled cells, so a normal run is unaffected."""
    cells = [c for c in _load(design_dir) if c.get("enabled", True)]
    if not cells:
        return {}
    accum: Dict[str, List[str]] = {}
    excluded: List[str] = []
    for c in cells:
        for kind, path in (c.get("views") or {}).items():
            var = _VIEW_VARS.get(kind, {}).get("var")
            if var and path:
                accum.setdefault(var, []).append(path)
        for cell_name in (c.get("swap_out") or []):
            if cell_name and cell_name not in excluded:
                excluded.append(cell_name)
    overrides: Dict[str, Any] = {k: " ".join(v) for k, v in accum.items()}
    if excluded:
        overrides["EXTRA_EXCLUDED_CELLS"] = " ".join(excluded)
    return overrides


def merge_into(overrides: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
    """Merge *extra* (custom-cell) overrides into user *overrides*, appending to
    whitespace-separated list values rather than clobbering them."""
    out = dict(overrides or {})
    list_vars = {spec["var"] for spec in _VIEW_VARS.values()} | {"EXTRA_EXCLUDED_CELLS"}
    for k, v in (extra or {}).items():
        if k in list_vars and out.get(k):
            out[k] = f"{out[k]} {v}".strip()
        else:
            out[k] = v
    return out
