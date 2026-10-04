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
  placement per instance. LibreLane's Classic flow has no automatic macro
  placer (only ``Odb.ManualMacroPlacement``), so every instance needs one; a
  blank location is stored but flagged (see :func:`merge_warning`).

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
# Instance names are flattened paths: ``u_core.u_sram`` or ``mem[0]``.
_INST_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*(\[\d+\])?(\.[A-Za-z_][A-Za-z0-9_$]*(\[\d+\])?)*$")

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
    "spice": {"field": "spice", "shape": "list",   "exts": (".spice", ".sp", ".cir", ".cdl"), "required": False},
    "vh":    {"field": "vh",    "shape": "list",   "exts": (".v", ".vh", ".sv"),     "required": False},
    "pnl":   {"field": "pnl",   "shape": "list",   "exts": (".v", ".pnl.v"),         "required": False},
}

# A view reference that is not a GUI upload: a PDK file (``pdk_dir::``) or one
# already inside the design (``dir::``). Absolute paths are copied in instead.
_REF_RX = re.compile(r"^(pdk_dir|dir)::[^\s]+$")


# --------------------------------------------------------------------------- #
# Sidecar I/O (the GUI's own record; NOT a LibreLane config).
# --------------------------------------------------------------------------- #
def _sidecar_path(design_dir: str | Path) -> Path:
    return Path(design_dir).resolve() / _SIDECAR


def _doc(design_dir: str | Path) -> Dict[str, Any]:
    f = _sidecar_path(design_dir)
    if not f.is_file():
        return {}
    try:
        doc = json.loads(f.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def _load(design_dir: str | Path) -> List[Dict[str, Any]]:
    m = _doc(design_dir).get("macros", [])
    return m if isinstance(m, list) else []


def _settings(design_dir: str | Path) -> Dict[str, Any]:
    st = _doc(design_dir).get("settings", {})
    return st if isinstance(st, dict) else {}


def _save(design_dir: str | Path, macros: List[Dict[str, Any]],
          settings: Optional[Dict[str, Any]] = None) -> None:
    from . import platform_env
    f = _sidecar_path(design_dir)
    doc: Dict[str, Any] = {"macros": macros}
    st = _settings(design_dir) if settings is None else settings
    if st:
        doc["settings"] = st
    # Atomic: a crash mid-write must not corrupt the sidecar (a corrupt sidecar
    # reads back as "no macros" and the next save persists the loss).
    platform_env.atomic_write_text(f, json.dumps(doc, indent=2) + "\n")


def _confined(design_dir: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(design_dir.resolve())
        return True
    except Exception:
        return False


def list_macros(design_dir: str | Path) -> Dict[str, Any]:
    """Return the design's saved custom macros (read-only)."""
    return {"ok": True, "macros": _load(design_dir), "settings": _settings(design_dir),
            "orientations": list(ORIENTATIONS)}


def set_settings(design_dir: str | Path, settings: Dict[str, Any]) -> Dict[str, Any]:
    """Page-wide macro settings: the keep-out halo around every macro (µm)."""
    clean: Dict[str, Any] = {}
    for k in ("halo_h", "halo_v"):
        v = (settings or {}).get(k)
        if v in (None, ""):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            return {"ok": False, "error": f"{k} must be a number of microns"}
        if f < 0 or f > 1000:
            return {"ok": False, "error": f"{k} must be between 0 and 1000 µm"}
        clean[k] = f
    _save(design_dir, _load(design_dir), clean)
    return {"ok": True, "settings": clean}


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
        if not _INST_RX.match(name):
            return [], (f"instance name '{name}' must be the instance's path in your RTL, "
                        "e.g. u_sram or u_core.u_sram")
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
                return [], f"location for '{name}' must be two numbers 'x y' (microns)"
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
    refs: Optional[Dict[str, Any]] = None,
    copies: Optional[Dict[str, Any]] = None,
    power: Optional[Dict[str, Any]] = None,
    source: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Save (or replace) a custom macro for *design_dir*.

    *name* is the macro's Verilog **module name** (the ``MACROS`` dict key).
    *views* maps a kind (``gds``/``lef``/``lib``/``nl``/``spef``/``spice``/``vh``)
    to an upload ``{filename, content_b64}``; *refs* maps a kind to a path used
    in place (``pdk_dir::…`` for a PDK macro); *copies* maps a kind to an
    absolute file (or ``{corner: file}`` for lib/spef) to copy in, e.g. another
    project's finished run. GDS and LEF are required. *instances* is a list of
    ``{name, location, orientation}``. *power* is ``{vdd_pin, gnd_pin, vdd_net,
    gnd_net}`` for ``PDN_MACRO_CONNECTIONS``. Files are written under
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
        # Space-free on disk: several LibreLane steps hand view paths to Tcl
        # scripts that split lists on whitespace — don't seed that failure.
        fname = re.sub(r"\s+", "_", fname)
        if not any(fname.lower().endswith(e) for e in spec["exts"]):
            return {"ok": False, "error": f"{kind} file should end with {' or '.join(spec['exts'])}"}
        try:
            raw = base64.b64decode((payload or {}).get("content_b64") or "", validate=False)
        except Exception:
            return {"ok": False, "error": f"could not decode {kind} file"}
        if len(raw) > _MAX_FILE_BYTES:
            return {"ok": False, "error": f"{kind} file exceeds {_MAX_FILE_BYTES // (1024*1024)} MiB"}
        decoded[kind] = (fname, raw)

    clean_refs: Dict[str, Any] = {}
    for kind, ref in (refs or {}).items():
        if kind not in _VIEW_SPECS:
            return {"ok": False, "error": f"unknown macro view '{kind}'"}
        items = ref.values() if isinstance(ref, dict) else [ref]
        if not all(isinstance(r, str) and _REF_RX.match(r) for r in items):
            return {"ok": False, "error": f"{kind} must be a pdk_dir:: or dir:: path"}
        clean_refs[kind] = dict(ref) if isinstance(ref, dict) else ref
    copy_plan: Dict[str, Any] = {}
    for kind, src in (copies or {}).items():
        if kind not in _VIEW_SPECS:
            return {"ok": False, "error": f"unknown macro view '{kind}'"}
        items = src.items() if isinstance(src, dict) else [("", src)]
        planned = {}
        for corner, f in items:
            fp = Path(str(f))
            if not fp.is_absolute() or not fp.is_file():
                return {"ok": False, "error": f"{kind} file not found: {f}"}
            if fp.stat().st_size > _MAX_FILE_BYTES:
                return {"ok": False, "error": f"{kind} file exceeds {_MAX_FILE_BYTES // (1024*1024)} MiB"}
            planned[corner] = fp
        copy_plan[kind] = planned if isinstance(src, dict) else planned[""]

    # Carry forward views from a prior save when this save didn't re-upload them,
    # so editing instances/orientation doesn't force re-uploading every file.
    prior = next((m for m in _load(d) if m.get("name") == name), None)
    saved_views: Dict[str, Any] = dict((prior or {}).get("views") or {}) if prior else {}
    if copy_plan or clean_refs:
        # a new source replaces the whole set, so no stale view lingers
        saved_views = {}
    saved_views.update(clean_refs)

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

    import shutil

    def put(fp: Path, kind: str, corner: str = "") -> str:
        sub = macro_dir / kind / corner if corner else macro_dir
        sub.mkdir(parents=True, exist_ok=True)
        target = (sub / re.sub(r"\s+", "_", fp.name)).resolve()
        if not _confined(d, target):
            raise ValueError("invalid file name")
        shutil.copyfile(fp, target)
        return "dir::" + str(target.relative_to(d)).replace("\\", "/")
    for kind, plan in copy_plan.items():
        try:
            if isinstance(plan, dict):
                saved_views[kind] = {c: put(fp, kind, "" if c == "*" else c) for c, fp in plan.items()}
            else:
                saved_views[kind] = put(plan, kind)
        except Exception as ex:
            return {"ok": False, "error": f"could not copy the {kind} view: {ex}"}

    if not saved_views.get("gds") or not saved_views.get("lef"):
        return {"ok": False, "error": "a GDS and a LEF view are both required for a macro"}

    macros = [m for m in _load(d) if m.get("name") != name]
    entry = {
        "name": name,
        "enabled": bool(enabled),
        "instances": clean_inst,
        "views": saved_views,
    }
    pw = power if power is not None else (prior or {}).get("power")
    if pw:
        clean_pw = {k: str(pw.get(k) or "").strip() for k in ("vdd_pin", "gnd_pin", "vdd_net", "gnd_net")}
        if any(clean_pw.values()):
            bad = [k for k, v in clean_pw.items() if v and not re.match(r"^[\w$\[\]!|.*^]+$", v)]
            if bad or not all(clean_pw.values()):
                return {"ok": False, "error": "power hookup needs all four names: the macro's power and "
                                              "ground pins and the design nets they connect to"}
            entry["power"] = clean_pw
    src = source if source is not None else (prior or {}).get("source")
    if isinstance(src, dict):
        entry["source"] = {k: src[k] for k in ("kind", "label", "pdk", "library", "design_dir", "tag") if k in src}
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
        if isinstance(path, dict):            # {corner: path} (a run's lib/spef)
            if spec["shape"] == "list":
                first = next(iter(path.values()), None)
                if first:
                    cfg[spec["field"]] = [first]
            else:
                cfg[spec["field"]] = {_corner_key(c): [p] for c, p in path.items()}
        elif spec["shape"] == "list":
            cfg[spec["field"]] = [path]
        else:  # corner-keyed dict, "*" = all corners
            cfg[spec["field"]] = {"*": [path]}
    instances: Dict[str, Any] = {}
    for inst in entry.get("instances") or []:
        instances[inst["name"]] = {
            "location": inst.get("location"),     # None => unplaced (the run stops at PDN)
            "orientation": inst.get("orientation") or "N",
        }
    if instances:
        cfg["instances"] = instances
    return cfg


def _corner_key(corner: str) -> str:
    """A run's ``final/<view>/<dir>`` name as a LibreLane corner wildcard. Lib
    folders are full timing corners (``max_ss_100C_1v60``) and match as-is;
    SPEF folders are RC corners (``min``/``nom``/``max``), which must become
    ``max_*`` to match the timing corners they belong to."""
    if not corner or corner == "*":
        return "*"
    return corner if "_" in corner or "*" in corner else corner + "_*"


def _user_config_list(design_dir: Path, key: str) -> List[str]:
    for ext in ("json", "yaml", "yml"):
        f = design_dir / f"config.{ext}"
        if not f.is_file():
            continue
        try:
            if ext == "json":
                doc = json.loads(f.read_text(encoding="utf-8"))
            else:
                import yaml  # type: ignore
                doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            return []
        v = doc.get(key) if isinstance(doc, dict) else None
        if isinstance(v, list):
            return [str(x) for x in v]
        if isinstance(v, str) and v.strip():
            return [v]
        return []
    return []


def _inst_regex(name: str) -> str:
    """An instance path as the regex PDN_MACRO_CONNECTIONS expects (dots and
    brackets escaped)."""
    return re.sub(r"([.\[\]])", r"\\\1", name)


def pdn_connections(design_dir: str | Path) -> List[str]:
    """``PDN_MACRO_CONNECTIONS`` lines for the enabled macros that have a power
    hookup: one per instance, ``<inst_rx> <vdd_net> <gnd_net> <vdd_pin> <gnd_pin>``."""
    out = []
    for m in _load(design_dir):
        pw = m.get("power")
        if not m.get("enabled", True) or not pw:
            continue
        for inst in m.get("instances") or []:
            out.append(f"{_inst_regex(inst['name'])} {pw['vdd_net']} {pw['gnd_net']} {pw['vdd_pin']} {pw['gnd_pin']}")
    return out


def _user_config_macros(design_dir: Path) -> Dict[str, Any]:
    """Best-effort read of any ``MACROS`` already in the user's JSON/YAML config,
    so an overlay augments rather than silently replaces it. Tcl/unreadable
    configs or a non-dict ``MACROS`` are skipped (the overlay then carries only
    GUI macros — see :func:`merge_warning` for the honest heads-up)."""
    for ext in ("json", "yaml", "yml"):
        f = design_dir / f"config.{ext}"
        if not f.is_file():
            continue
        try:
            if ext == "json":
                doc = json.loads(f.read_text(encoding="utf-8"))
            else:
                # YAML configs are first-class in LibreLane; parse with the same
                # library it uses (already a dependency) so a config.yaml MACROS
                # is MERGED rather than silently replaced by the overlay.
                import yaml  # type: ignore
                doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if isinstance(doc, dict) and isinstance(doc.get("MACROS"), dict):
            return dict(doc["MACROS"])
        return {}
    return {}


def merge_warning(design_dir: str | Path) -> Optional[str]:
    """A plain-language warning when enabled GUI macros will REPLACE (not merge
    with) macros in the user's own config — i.e. a Tcl config that mentions
    ``MACROS`` (we can't parse Tcl to merge it). ``None`` when there's nothing
    to warn about."""
    d = Path(design_dir).resolve()
    enabled = [m for m in _load(d) if m.get("enabled", True)]
    if not enabled:
        return None
    # LibreLane's Classic flow has no automatic macro placer (only
    # Odb.ManualMacroPlacement): an instance without a location is never
    # placed and the run stops at GeneratePDN with "Design has unplaced macros".
    unplaced = [i["name"] for m in enabled for i in (m.get("instances") or []) if not i.get("location")]
    if unplaced:
        return ("macro instance" + ("s " if len(unplaced) > 1 else " ") + ", ".join(unplaced[:4]) +
                (" have" if len(unplaced) > 1 else " has") + " no position. LibreLane places macros only "
                "where you put them, so the run will stop at the power grid (PDN-0235 unplaced macros). "
                "Set X/Y on the Cells tab (Macros → Arrange for me).")
    tcl = d / "config.tcl"
    if tcl.is_file() and not any((d / f"config.{e}").is_file() for e in ("json", "yaml", "yml")):
        try:
            if "MACROS" in tcl.read_text(encoding="utf-8", errors="replace"):
                return ("your config.tcl defines MACROS, which the GUI cannot merge — "
                        "for this run the GUI-managed macros will replace it. Move the "
                        "config's MACROS into config.json/yaml to combine both.")
        except Exception:
            return None
    return None


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
    extra: Dict[str, Any] = {}
    if macros:
        hooks = pdn_connections(d)
        if hooks:
            mine = _user_config_list(d, "PDN_MACRO_CONNECTIONS")
            extra["PDN_MACRO_CONNECTIONS"] = mine + [h for h in hooks if h not in mine]
        st = _settings(d)
        if "halo_h" in st:
            extra["FP_MACRO_HORIZONTAL_HALO"] = st["halo_h"]
        if "halo_v" in st:
            extra["FP_MACRO_VERTICAL_HALO"] = st["halo_v"]
    if not macros:
        try:
            overlay.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass
        return None
    try:
        from . import platform_env
        platform_env.atomic_write_text(overlay, json.dumps(dict({"MACROS": macros}, **extra), indent=2) + "\n")
    except Exception:
        return None
    return str(overlay)
