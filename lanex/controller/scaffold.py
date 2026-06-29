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
"""New-project scaffolding from bundled templates (Phase 0).

Each template lives under ``gui/controller/templates/<name>/`` with a
``template.json`` manifest, a ``src/`` tree, and an optional ``verify/``
testbench. :func:`create_project` copies the tree into a fresh design dir and
renders a ``config.json`` using only **verified-real** LibreLane variables
(``DESIGN_NAME``, ``VERILOG_FILES``, ``CLOCK_PORT``, ``CLOCK_PERIOD``, ``PDK``,
``STD_CELL_LIBRARY``). Pure / stdlib only — no new deps, no librelane internals.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

# Variables we render into a scaffolded config. Kept to the canonical,
# verified-real set so a scaffolded design always passes config resolution.
# (Cross-checked against ``introspect.list_variables()`` in test_scaffold.py.)
_CONFIG_VARS = ("DESIGN_NAME", "VERILOG_FILES", "CLOCK_PORT", "CLOCK_PERIOD", "PDK", "STD_CELL_LIBRARY")


def _templates_root() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _read_manifest(tdir: Path) -> Optional[Dict[str, Any]]:
    mf = tdir / "template.json"
    if not mf.is_file():
        return None
    try:
        doc = json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(doc, dict) or not doc.get("name"):
        return None
    return doc


def list_templates() -> List[Dict[str, Any]]:
    """Enumerate the bundled project templates (read-only).

    Returns each manifest plus ``has_testbench`` so the wizard can offer
    "simulate after scaffold". Sorted with ``empty`` last so concrete examples
    surface first.
    """
    root = _templates_root()
    out: List[Dict[str, Any]] = []
    if not root.is_dir():
        return out
    for tdir in sorted(root.iterdir()):
        if not tdir.is_dir():
            continue
        doc = _read_manifest(tdir)
        if doc is None:
            continue
        tb = doc.get("testbench")
        out.append(
            {
                "name": doc["name"],
                "title": doc.get("title") or doc["name"],
                "description": doc.get("description") or "",
                "top": doc.get("top") or doc["name"],
                "clock_port": doc.get("clock_port") or "clk",
                "clock_period": doc.get("clock_period"),
                "has_testbench": bool(tb),
            }
        )
    out.sort(key=lambda d: (d["name"] == "empty", d["name"]))
    return out


def _render_config(
    *, top: str, pdk: str, scl: Optional[str], clock_port: str, clock_period: Optional[float]
) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "DESIGN_NAME": top,
        # `dir::` resolves relative to the config file's directory, so any *.v
        # the user drops into src/ is picked up automatically.
        "VERILOG_FILES": ["dir::src/*.v"],
        "CLOCK_PORT": clock_port,
    }
    if clock_period is not None:
        cfg["CLOCK_PERIOD"] = float(clock_period)
    if pdk:
        cfg["PDK"] = pdk
    if scl:
        cfg["STD_CELL_LIBRARY"] = scl
    return cfg


def create_project(
    dest_dir: str | Path,
    template: str,
    *,
    top: str,
    pdk: str,
    scl: Optional[str] = None,
    clock_period: Optional[float] = None,
) -> Dict[str, Any]:
    """Copy *template* into *dest_dir* and render its ``config.json``.

    Refuses to write into a non-empty existing directory (never clobbers user
    work). All writes are confined to *dest_dir*. Returns
    ``{ok, design_dir, files:[rel,...]}`` or ``{ok: False, error}``.
    """
    troot = _templates_root()
    tdir = (troot / template).resolve()
    # Confine the template lookup to the bundled templates dir.
    try:
        tdir.relative_to(troot.resolve())
    except ValueError:
        return {"ok": False, "error": "unknown template"}
    manifest = _read_manifest(tdir)
    if manifest is None:
        return {"ok": False, "error": f"unknown template '{template}'"}

    dest = Path(dest_dir).expanduser().resolve()
    if dest.exists():
        if not dest.is_dir():
            return {"ok": False, "error": "destination exists and is not a directory"}
        if any(dest.iterdir()):
            return {"ok": False, "error": "destination directory is not empty"}
    dest.mkdir(parents=True, exist_ok=True)

    written: List[str] = []
    # Copy src/ and verify/ trees (only those — never the manifest).
    for sub in ("src", "verify"):
        srcdir = tdir / sub
        if not srcdir.is_dir():
            continue
        for f in sorted(srcdir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(tdir)
            target = (dest / rel).resolve()
            # Defence in depth: never escape dest.
            try:
                target.relative_to(dest)
            except ValueError:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, target)
            written.append(str(rel))

    top = top or manifest.get("top") or template
    clock_port = manifest.get("clock_port") or "clk"
    if clock_period is None:
        clock_period = manifest.get("clock_period")
    cfg = _render_config(top=top, pdk=pdk, scl=scl, clock_port=clock_port, clock_period=clock_period)
    (dest / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    written.append("config.json")

    return {"ok": True, "design_dir": str(dest), "template": template, "top": top, "files": sorted(written)}
