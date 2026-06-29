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
"""Filesystem helpers for the GUI.

The frontend never touches the filesystem directly; every read is mediated
through this module so we can:
  * sanitize paths against traversal,
  * stay cross-platform via ``pathlib``,
  * gate which extensions count as "RTL sources" (configurable).

No shell-outs; everything uses stdlib.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# Default "Verilog-ish" extensions plus memory files.
DEFAULT_SOURCE_EXTS = {
    ".v", ".sv", ".vh", ".svh", ".verilog",
    ".vhd", ".vhdl",
    ".mem", ".hex", ".bin",
}


def _safe_resolve(path: str, *, must_exist: bool) -> Optional[Path]:
    """Normalise ``path`` (expanduser + resolve) to an absolute Path.

    NOTE: this only *normalises* — it does **not** confine the result to any base
    directory. Callers that accept a user-supplied path from the network (e.g.
    the read-text / reports endpoints) MUST gate it against an allowlist of roots
    first (see ``routes._path_within_roots``); otherwise any local file would be
    readable.
    """
    if not path:
        return None
    p = Path(os.path.expanduser(path)).resolve()
    if must_exist and not p.exists():
        return None
    return p


def list_dir(path: str) -> Dict[str, Any]:
    """Return a JSON-safe directory listing.

    Each entry has: ``name``, ``path`` (absolute), ``is_dir``, ``size``,
    ``mtime`` (epoch seconds), ``ext`` (lowercase, "" for dirs).
    """
    p = _safe_resolve(path, must_exist=True)
    if p is None or not p.is_dir():
        return {"ok": False, "error": "not a directory"}
    out: List[Dict[str, Any]] = []
    try:
        iters = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except PermissionError as ex:
        return {"ok": False, "error": "permission denied: " + str(ex)}
    except OSError as ex:
        return {"ok": False, "error": "io error: " + str(ex)}
    for entry in iters:
        if entry.name.startswith("."):
            continue
        try:
            st = entry.stat()
            out.append(
                {
                    "name": entry.name,
                    "path": str(entry),
                    "is_dir": entry.is_dir(),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "ext": entry.suffix.lower(),
                }
            )
        except OSError:
            continue
    return {
        "ok": True,
        "path": str(p),
        "parent": str(p.parent) if p != p.parent else None,
        "entries": out,
    }


def walk_sources(
    design_dir: str,
    *,
    extra_exts: Optional[set] = None,
    max_results: int = 4096,
) -> Dict[str, Any]:
    """Walk ``design_dir`` recursively and return every file whose extension
    is in ``DEFAULT_SOURCE_EXTS | extra_exts``.

    Skips ``.git``, ``runs``, ``tmp``, ``__pycache__``.
    """
    p = _safe_resolve(design_dir, must_exist=True)
    if p is None or not p.is_dir():
        return {"ok": False, "error": "not a directory"}
    exts = {e.lower() for e in (DEFAULT_SOURCE_EXTS | (extra_exts or set()))}
    skip_dirs = {".git", "runs", "tmp", "__pycache__", "build", "node_modules"}
    hits: List[Dict[str, Any]] = []
    for root, dirs, files in os.walk(str(p)):
        # Prune skip-dirs in-place to avoid descending into them.
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if len(hits) > max_results:
                break
            ext = Path(f).suffix.lower()
            if ext in exts:
                fp = Path(root) / f
                try:
                    size = fp.stat().st_size
                except OSError:
                    size = 0
                hits.append(
                    {
                        "name": f,
                        "relpath": str(fp.relative_to(p)),
                        "abspath": str(fp),
                        "ext": ext,
                        "size": size,
                    }
                )
    # Also include any *.mem/hex files separately so users can map them
    # to memory cells.
    memory_exts = {".mem", ".hex", ".bin"}
    memories = [h for h in hits if h["ext"] in memory_exts]
    sources = [h for h in hits if h["ext"] not in memory_exts]
    return {
        "ok": True,
        "design_dir": str(p),
        "sources": sources,
        "memories": memories,
        "total": len(sources) + len(memories),
    }


def read_text(path: str, *, max_bytes: int = 4 * 1024 * 1024) -> Dict[str, Any]:
    """Read a text file safely. Bounded (default 4 MiB, matching the IDE's write
    limit) so a large generated RTL file still opens in the editor."""
    p = _safe_resolve(path, must_exist=True)
    if p is None or not p.is_file():
        return {"ok": False, "error": "not a file"}
    try:
        size = p.stat().st_size
    except OSError as ex:
        return {"ok": False, "error": str(ex)}
    if size > max_bytes:
        return {"ok": False, "error": f"file too large (>{max_bytes // (1024 * 1024)} MiB); preview not supported"}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as ex:
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "path": str(p), "text": text, "size": size}


def list_run_reports(design_dir: str, run_tag: str) -> Dict[str, Any]:
    """Auto-discover DRC / LVS / STA / antenna reports in a run dir.

    Walks every ``<NN-StepName>/`` folder under ``runs/<run_tag>/`` and lists
    files matching the conventional report extensions / names.
    """
    p = _safe_resolve(design_dir + "/runs/" + run_tag, must_exist=False)
    if p is None or not p.is_dir():
        return {"ok": False, "error": "run not found"}
    reports: List[Dict[str, Any]] = []
    # Extension-based default keyword map.
    ext_map = {
        ".drc": "DRC",
        ".lvs": "LVS",
        ".xor": "XOR",
        ".sdf": "STA",
        ".spef": "Parasitics",
        ".ant": "Antenna",
    }
    # Step-name keyword lookup: e.g. "Magic.DRC" or "MagicDRC" -> DRC.
    step_name_map = [
        ("Magic.DRC", "DRC"),
        ("MagicDRC", "DRC"),
        ("KLayoutDRC", "DRC"),
        ("KLayout.DRC", "DRC"),
        ("TrDRC", "routing DRC"),
        ("Netgen.LVS", "LVS"),
        ("NetgenLVS", "LVS"),
        ("RCX", "Parasitics"),
        ("STAPrePNR", "STA"),
        ("STAMidPNR", "STA"),
        ("STAPostPNR", "STA"),
        ("STA", "STA"),
        ("AntennaReport", "Antenna"),
        ("AntennaReportChecker", "Antenna"),
        ("IRDropReport", "IR drop"),
        ("XOR", "XOR"),
        ("DisconnectedPins", "DRC"),
        ("WireLength", "Timing"),
    ]
    for entry in sorted(p.iterdir()):
        if not entry.is_dir():
            continue
        if "-" not in entry.name:
            continue
        if not entry.name.split("-", 1)[0].isdigit():
            continue
        step = entry.name.split("-", 1)[1]
        for f in entry.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            kind = ext_map.get(ext)
            if kind is None and ext in (".rpt", ".report", ".log", ".txt"):
                # Heuristic: name-based.
                name_lower = f.name.lower()
                if "drc" in name_lower:
                    kind = "DRC"
                elif "lvs" in name_lower:
                    kind = "LVS"
                elif "antenna" in name_lower or "ant.report" in name_lower:
                    kind = "Antenna"
                elif "ir" in name_lower and "drop" in name_lower:
                    kind = "IR drop"
                elif "sta" in name_lower and "report" in name_lower:
                    kind = "STA"
                elif "sta" in name_lower:
                    kind = "STA"
            if kind is None:
                # Try step-name map (last resort).
                for token, k in step_name_map:
                    if token in step:
                        kind = k
                        break
            if kind is None:
                continue
            try:
                rel = str(f.relative_to(p))
            except Exception:
                rel = f.name
            reports.append(
                {
                    "step": step,
                    "name": f.name,
                    "path": str(f),
                    "rel": rel,           # relative to the run dir (for download/reveal)
                    "kind": kind,
                    "ext": ext,
                    "size": f.stat().st_size,
                }
            )
    reports.sort(key=lambda r: (r["step"], r["kind"], r["name"]))
    return {"ok": True, "reports": reports}
