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
"""Custom hard-macro insertion for a single run (advanced).

A *macro* is a pre-hardened block (an SRAM, a PLL, an analog IP, or a separately
hardened sub-design) that is dropped into the floorplan as a fixed black box and
routed around — it does **not** sit in the standard-cell rows the way a custom
*cell* does (see :mod:`librelane.lanex.controller.customcells`). LibreLane models a
macro with the verified-real ``MACROS`` configuration variable, a
``Dict[str, Macro]`` keyed by the macro's Verilog **module name**; each
:class:`librelane.config.Macro` carries the block's views:

* ``gds`` / ``lef`` — the layout and the abstract (pins/obstructions/size).
  **Both are required** (LibreLane raises if either is missing).
* ``lib`` — per-corner timing; lets synthesis black-box the macro and STA time
  through it. (``Dict[corner-wildcard, [lib…]]``; we key it ``"*"`` = all corners.)
* ``nl`` — a gate-level Verilog netlist of the macro, for power/STA.
* ``spef`` — per-corner parasitics (``Dict[wildcard, [spef…]]``).
* ``spice`` — device netlist for LVS.
* ``instances`` — ``{instance_name: {location, orientation}}``; a fixed
  placement per instance (leave the location blank for automatic placement).

Why an **overlay config file** and not a ``-c KEY=VALUE`` override: LibreLane
parses a *string* value for a ``Dict`` variable as a flat Tcl ``key value …``
list (``config/variable.py``), which cannot represent a nested ``Macro`` object.
But ``Config.load`` accepts a *sequence* of config sources and merges them, and a
mapping member is consumed natively. So we write the enabled macros to a small
``<design>/.gui-macros.json`` overlay and hand its path to the flow as a second
config file — works identically for the in-process (local) flow and the
``librelane`` CLI (``CONFIG_FILES`` is ``nargs=-1``), and the ``dir::`` paths
resolve against ``DESIGN_DIR`` in both. Per-run only; the user's ``config.json``
is never modified. Pure stdlib; writes confined to the design dir; cross-platform
via ``pathlib``.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SIDECAR = ".gui-custom-macros.json"
_OVERLAY = ".gui-macros.json"          # the generated LibreLane config overlay
_MACROS_SUBDIR = "macros"
_MAX_FILE_BYTES = 256 * 1024 * 1024    # a hardened-macro GDS can be large.

# A macro module name / instance name is a Verilog identifier. (We also accept a
# leading-digit-free dotted/hier form some flows use, but keep it conservative.)
_IDENT_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

# Orientations LibreLane's ``Orientation`` enum accepts (config/variable.py).
ORIENTATIONS = ("N", "S", "E", "W", "FN", "FS", "FE", "FW")

# Macro view kind -> how it lands in the Macro object.
#   shape "list"  -> a ``List[Path]`` field   (gds/lef/nl/spice)
#   shape "corner"-> a ``Dict[wildcard, [Path]]`` field, keyed "*" (lib/spef)
_VIEW_SPECS: Dict[str, Dict[str, Any]] = {
    "gds":   {"field": "gds",   "shape": "list",   "exts": (".gds", ".gds.gz"),      "required": True},
    "lef":   {"field": "lef",   "shape": "list",   "exts": (".lef",),                "required": True},
    "lib":   {"field": "lib",   "shape": "corner", "exts": (".lib",),                "required": False},
    "nl":    {"field": "nl",    "shape": "list",   "exts": (".v", ".sv", ".nl.v"),   "required": False},
    "spef":  {"field": "spef",  "shape": "corner", "exts": (".spef",),               "required": False},
    "spice": {"field": "spice", "shape": "list",   "exts": (".spice", ".sp", ".cir"), "required": False},
}


# --------------------------------------------------------------------------- #
# Sidecar I/O (the GUI's own record; NOT a LibreLane config).
# --------------------------------------------------------------------------- #
def _sidecar_path(design_dir: str | Path) -> Path:
    return Path(design_dir).resolve() / _SIDECAR


def _load(design_dir: str | Path) -> List[Dict[str, Any]]:
    f = _sidecar_path(design_dir)
    if not f.is_file():
        return []
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
        return doc.get("macros", []) if isinstance(doc, dict) else []
    except Exception:
        return []


def _save(design_dir: str | Path, macros: List[Dict[str, Any]]) -> None:
    f = _sidecar_path(design_dir)
    f.write_text(json.dumps({"macros": macros}, indent=2) + "\n", encoding="utf-8")


def _confined(design_dir: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(design_dir.resolve())
        return True
    except Exception:
        return False


def list_macros(design_dir: str | Path) -> Dict[str, Any]:
    """Return the design's saved custom macros (read-only)."""
    return {"ok": True, "macros": _load(design_dir), "orientations": list(ORIENTATIONS)}


# --------------------------------------------------------------------------- #
# Instance parsing/validation.
# --------------------------------------------------------------------------- #
def _clean_instances(instances: Optional[List[Dict[str, Any]]]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Validate the instance list; return (clean, error)."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for inst in instances or []:
        name = (str((inst or {}).get("name") or "")).strip()
        if not name:
            return [], "every instance needs a name (the instance name used in your RTL)"
        if not _IDENT_RX.match(name):
            return [], f"instance name '{name}' must be a valid identifier (letters/digits/_/$)"
        if name in seen:
            return [], f"duplicate instance name '{name}'"
        seen.add(name)
        orient = (str((inst or {}).get("orientation") or "N")).strip().upper() or "N"
        if orient not in ORIENTATIONS:
            return [], f"orientation '{orient}' is not one of {', '.join(ORIENTATIONS)}"
        loc_in = (inst or {}).get("location")
        location: Optional[List[float]] = None
        if loc_in not in (None, "", []):
            try:
                if isinstance(loc_in, str):
                    parts = [p for p in re.split(r"[,\s]+", loc_in.strip()) if p]
                else:
                    parts = list(loc_in)
                if len(parts) != 2:
                    raise ValueError
                location = [float(parts[0]), float(parts[1])]
            except Exception:
                return [], f"location for '{name}' must be two numbers 'x y' (microns) or blank for auto-place"
        out.append({"name": name, "location": location, "orientation": orient})
    return out, None


# --------------------------------------------------------------------------- #
# Save / enable / remove.
# --------------------------------------------------------------------------- #
def save_macro(
    design_dir: str | Path,
    name: str,
    *,
    instances: Optional[List[Dict[str, Any]]] = None,
    views: Optional[Dict[str, Dict[str, str]]] = None,
    enabled: bool = True,
) -> Dict[str, Any]:
    """Save (or replace) a custom macro for *design_dir*.

    *name* is the macro's Verilog **module name** (the ``MACROS`` dict key).
    *views* maps a kind (``gds``/``lef``/``lib``/``nl``/``spef``/``spice``) to
    ``{filename, content_b64}``. GDS and LEF are required. *instances* is a list
    of ``{name, location, orientation}``. Files are written under
    ``macros/<name>/`` and recorded as design-relative ``dir::`` paths. Never
    raises; returns ``{ok, macro}`` or ``{ok: False, error}``."""
    d = Path(design_dir).resolve()
    if not d.is_dir():
        return {"ok": False, "error": "design directory not found"}
    name = (name or "").strip()
    if not name or not _IDENT_RX.match(name):
        return {"ok": False, "error": "macro module name must be a valid Verilog identifier (letters/digits/_/$, no leading digit)"}

    clean_inst, err = _clean_instances(instances)
    if err:
        return {"ok": False, "error": err}

    macro_dir = (d / _MACROS_SUBDIR / name).resolve()
    if not _confined(d, macro_dir):
        return {"ok": False, "error": "refusing to write outside the design dir"}

    # Validate/decode every uploaded view BEFORE writing anything, so a bad file
    # can't leave a half-saved macro on disk.
    decoded: Dict[str, Tuple[str, bytes]] = {}
    for kind, payload in (views or {}).items():
        spec = _VIEW_SPECS.get(kind)
        if spec is None:
            return {"ok": False, "error": f"unknown macro view '{kind}'"}
        fname = Path((payload or {}).get("filename") or f"{name}.{kind}").name
        if not any(fname.lower().endswith(e) for e in spec["exts"]):
            return {"ok": False, "error": f"{kind} file should end with {' or '.join(spec['exts'])}"}
        try:
            raw = base64.b64decode((payload or {}).get("content_b64") or "", validate=False)
        except Exception:
            return {"ok": False, "error": f"could not decode {kind} file"}
        if len(raw) > _MAX_FILE_BYTES:
            return {"ok": False, "error": f"{kind} file exceeds {_MAX_FILE_BYTES // (1024*1024)} MiB"}
        decoded[kind] = (fname, raw)

    # Carry forward views from a prior save when this save didn't re-upload them,
    # so editing instances/orientation doesn't force re-uploading every file.
    prior = next((m for m in _load(d) if m.get("name") == name), None)
    saved_views: Dict[str, str] = dict((prior or {}).get("views") or {}) if prior else {}

    macro_dir.mkdir(parents=True, exist_ok=True)
    for kind, (fname, raw) in decoded.items():
        target = (macro_dir / fname).resolve()
        if not _confined(d, target):
            return {"ok": False, "error": "invalid file name"}
        try:
            target.write_bytes(raw)
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        saved_views[kind] = "dir::" + str(target.relative_to(d)).replace("\\", "/")

    if not saved_views.get("gds") or not saved_views.get("lef"):
        return {"ok": False, "error": "a GDS and a LEF view are both required for a macro"}

    macros = [m for m in _load(d) if m.get("name") != name]
    entry = {
        "name": name,
        "enabled": bool(enabled),
        "instances": clean_inst,
        "views": saved_views,
    }
    macros.append(entry)
    try:
        _save(d, macros)
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "macro": entry}


def set_enabled(design_dir: str | Path, name: str, enabled: bool) -> Dict[str, Any]:
    macros = _load(design_dir)
    found = False
    for m in macros:
        if m.get("name") == name:
            m["enabled"] = bool(enabled)
            found = True
    if not found:
        return {"ok": False, "error": "macro not found"}
    _save(design_dir, macros)
    return {"ok": True}


def remove_macro(design_dir: str | Path, name: str) -> Dict[str, Any]:
    """Remove a custom macro and its files."""
    import shutil
    d = Path(design_dir).resolve()
    macros = [m for m in _load(d) if m.get("name") != name]
    _save(d, macros)
    macro_dir = (d / _MACROS_SUBDIR / name).resolve()
    if _confined(d, macro_dir) and macro_dir.is_dir():
        try:
            shutil.rmtree(macro_dir)
        except Exception:
            pass
    return {"ok": True}


# --------------------------------------------------------------------------- #
# Override / overlay generation.
# --------------------------------------------------------------------------- #
def _macro_to_config(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Turn one stored macro into the ``Macro``-shaped dict LibreLane expects."""
    views = entry.get("views") or {}
    cfg: Dict[str, Any] = {}
    for kind, spec in _VIEW_SPECS.items():
        path = views.get(kind)
        if not path:
            continue
        if spec["shape"] == "list":
            cfg[spec["field"]] = [path]
        else:  # corner-keyed dict, "*" = all corners
            cfg[spec["field"]] = {"*": [path]}
    instances: Dict[str, Any] = {}
    for inst in entry.get("instances") or []:
        instances[inst["name"]] = {
            "location": inst.get("location"),     # None => automatic placement
            "orientation": inst.get("orientation") or "N",
        }
    if instances:
        cfg["instances"] = instances
    return cfg


def _user_config_macros(design_dir: Path) -> Dict[str, Any]:
    """Best-effort read of any ``MACROS`` already in the user's JSON config, so an
    overlay augments rather than silently replaces it. Tcl/unreadable configs or a
    non-dict ``MACROS`` are skipped (the overlay then carries only GUI macros)."""
    for ext in ("json", "yaml", "yml"):
        f = design_dir / f"config.{ext}"
        if not f.is_file():
            continue
        try:
            doc = json.loads(f.read_text(encoding="utf-8")) if ext == "json" else None
        except Exception:
            return {}
        if isinstance(doc, dict) and isinstance(doc.get("MACROS"), dict):
            return dict(doc["MACROS"])
        return {}
    return {}


def build_macros_dict(design_dir: str | Path) -> Dict[str, Any]:
    """The merged ``{module_name: macro_cfg}`` for all enabled macros (GUI macros
    win on a name clash with the user's config). ``{}`` if none enabled."""
    d = Path(design_dir).resolve()
    enabled = [m for m in _load(d) if m.get("enabled", True)]
    if not enabled:
        return {}
    merged = _user_config_macros(d)
    for entry in enabled:
        merged[entry["name"]] = _macro_to_config(entry)
    return merged


def write_overlay(design_dir: str | Path) -> Optional[str]:
    """Write the ``MACROS`` overlay config and return its path, or ``None`` when
    there are no enabled macros (also removing any stale overlay then). The path
    is handed to the flow as an extra config file. Per-run; never touches
    ``config.json``."""
    d = Path(design_dir).resolve()
    overlay = d / _OVERLAY
    macros = build_macros_dict(d)
    if not macros:
        try:
            overlay.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return None
    try:
        overlay.write_text(json.dumps({"MACROS": macros}, indent=2) + "\n", encoding="utf-8")
    except Exception:
        return None
    return str(overlay)
