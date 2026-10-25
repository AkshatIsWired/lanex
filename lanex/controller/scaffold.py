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


def spm_source() -> Optional[Path]:
    """The SPM example LanEx bundles (repo checkout), else LibreLane's own copy."""
    here = Path(__file__).resolve().parents[2] / "spm"
    if here.is_dir():
        return here
    try:
        import librelane  # noqa: F401  (optional at import time)
        cand = Path(librelane.__file__).parent / "examples" / "spm"
        return cand if cand.is_dir() else None
    except Exception:
        return None


def _copy_from(manifest: Dict[str, Any]) -> Optional[Path]:
    """A template that ships a complete, tuned design (its own config, SDC and
    pin order) is copied verbatim instead of rendered from the manifest."""
    if manifest.get("copy_from") == "spm":
        return spm_source()
    return None


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
                # The clock each PDK family starts on ({glob: ns}), where the
                # template's default is too fast for that process.
                "pdk_clock": {g: v["clock_period"] for g, v in _pdk_tuning(doc).items()
                              if v.get("clock_period") is not None},
                "has_testbench": bool(tb),
                "kind": doc.get("kind") or "example",
                "fixed_config": bool(doc.get("copy_from")),
                "order": doc.get("order", 99),
            }
        )
    # The blank project leads; examples follow in their curated order.
    out.sort(key=lambda d: (d["kind"] != "blank", d["order"], d["name"]))
    return out


def _pdk_tuning(manifest: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The manifest's per-PDK tuning: ``{"gf180mcu*": {"clock_period": ns,
    "config": {...}}}``. The examples are written for sky130; gf180's cells
    are several times slower and bigger, so some need a longer clock and a
    looser placement there (the values LibreLane's own SPM example uses)."""
    raw = manifest.get("pdk")
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, dict):
        for pat, v in raw.items():
            if isinstance(pat, str) and pat and isinstance(v, dict):
                out[pat] = v
    return out


def _apply_pdk_tuning(cfg: Dict[str, Any], manifest: Dict[str, Any], pdk: str,
                      clock_explicit: bool) -> None:
    """Fold the tuning for the chosen PDK into the top level, and write the
    others as ``pdk::<glob>`` sections, which LibreLane applies to a run for a
    matching PDK, so the project still reaches a GDS after the PDK picker
    changes. A section carries only what that PDK needs beyond the top level:
    a longer clock than the top-level one, and its settings."""
    import fnmatch
    for pat, tune in _pdk_tuning(manifest).items():
        extra = {k: v for k, v in (tune.get("config") or {}).items() if isinstance(k, str)}
        cp = tune.get("clock_period")
        if pdk and fnmatch.fnmatchcase(pdk, pat):
            if cp is not None and not clock_explicit:
                cfg["CLOCK_PERIOD"] = float(cp)
            cfg.update(extra)
            continue
        section = dict(extra)
        if cp is not None and float(cp) > float(cfg.get("CLOCK_PERIOD") or 0):
            section["CLOCK_PERIOD"] = float(cp)
        if section:
            cfg["pdk::" + pat] = section


def _rename_starter(dest: Path, old: str, new: str, written: List[str]) -> None:
    import re
    src = dest / "src" / (old + ".v")
    if not src.is_file() or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", new):
        return
    text = src.read_text(encoding="utf-8")
    text = re.sub(r"\bmodule\s+" + re.escape(old) + r"\b", "module " + new, text, count=1)
    target = dest / "src" / (new + ".v")
    target.write_text(text, encoding="utf-8")
    src.unlink()
    rel_old, rel_new = str(Path("src") / (old + ".v")), str(Path("src") / (new + ".v"))
    written[:] = [rel_new if w == rel_old else w for w in written]


def _to_sv(dest: Path, top: str, written: List[str]) -> None:
    """A blank SystemVerilog project: the starter module (plain Verilog is
    valid SystemVerilog) moves to src/<top>.sv, and its note says *.sv."""
    src = dest / "src" / (top + ".v")
    if not src.is_file():
        return
    text = src.read_text(encoding="utf-8").replace("src/*.v", "src/*.sv").replace("any *.v", "any *.sv")
    (dest / "src" / (top + ".sv")).write_text(text, encoding="utf-8")
    src.unlink()
    rel_old, rel_new = str(Path("src") / (top + ".v")), str(Path("src") / (top + ".sv"))
    written[:] = [rel_new if w == rel_old else w for w in written]


def _render_config(
    *, top: str, pdk: str, scl: Optional[str], clock_port: str, clock_period: Optional[float],
    sources: str = "dir::src/*.v",
) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "DESIGN_NAME": top,
        # `dir::` resolves relative to the config file's directory, so any *.v
        # (or *.sv) the user drops into src/ is picked up automatically.
        "VERILOG_FILES": [sources],
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
    language: str = "verilog",
) -> Dict[str, Any]:
    """Copy *template* into *dest_dir* and render its ``config.json``.

    *language* ("verilog" or "systemverilog") only changes a blank project:
    its starter module becomes ``src/<top>.sv`` and the config builds
    ``src/*.sv``. Examples keep the language they're written in.

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

    verbatim = _copy_from(manifest)
    if manifest.get("copy_from"):
        if verbatim is None:
            return {"ok": False, "error": "this example isn't available in this install"}
        shutil.copytree(str(verbatim), str(dest), dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("runs", "__pycache__"))
        files = sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file())
        return {"ok": True, "design_dir": str(dest), "template": template,
                "top": manifest.get("top") or template, "files": files}

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

    tpl_top = manifest.get("top") or template
    top = top or tpl_top
    if manifest.get("kind") == "blank" and top != tpl_top:
        # A blank project's starter module takes the name the person chose, so
        # DESIGN_NAME, the module and its file all agree.
        _rename_starter(dest, tpl_top, top, written)
    elif manifest.get("kind") != "blank":
        # An example's top module is fixed by its Verilog.
        top = tpl_top
    sv = manifest.get("kind") == "blank" and language == "systemverilog"
    if sv:
        _to_sv(dest, top, written)
    clock_port = manifest.get("clock_port") or "clk"
    explicit_clock = clock_period is not None
    if clock_period is None:
        clock_period = manifest.get("clock_period")
    cfg = _render_config(top=top, pdk=pdk, scl=scl, clock_port=clock_port, clock_period=clock_period,
                         sources="dir::src/*.sv" if sv else "dir::src/*.v")
    # A template may add settings its design needs, such as a fixed die for a
    # design too small for a utilization-sized one (placement can't legalize
    # the clock buffers on a die a few dozen microns across).
    extra = manifest.get("config")
    if isinstance(extra, dict):
        cfg.update({k: v for k, v in extra.items() if isinstance(k, str) and k not in cfg})
    _apply_pdk_tuning(cfg, manifest, pdk, clock_explicit=explicit_clock)
    (dest / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    written.append("config.json")

    return {"ok": True, "design_dir": str(dest), "template": template, "top": top, "files": sorted(written)}
