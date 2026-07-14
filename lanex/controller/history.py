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
"""Browse the runs/ directory and summarise past invocations.

LibreLane writes runs at ``design_dir/runs/<tag>/`` with this layout:
    config.json, state_out.json, metrics.json, metrics.csv,
    runtime.yaml, warnings.txt,
    <NNN-StepName>/<tcl>, <outputs>, <.log>,
    final/{nl,def,gds,sdf,spef,lib,render}/.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import RunSummary, RunView, MetricSet, to_json

# The metric keys we surface on the dashboard by default.
# Kept conservative: pull every key from metrics.json and let the
# SPA pick a curated subset for the hero cards.

def _walk_runs(design_dir: Path) -> List[Path]:
    """Return run dirs sorted newest-first by mtime."""
    runs_root = design_dir / "runs"
    if not runs_root.is_dir():
        return []
    out: List[Path] = []
    for p in runs_root.iterdir():
        if not p.is_dir() or p.name.startswith("."):
            continue
        out.append(p)
    out.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        # errors="replace": EDA tools occasionally emit non-UTF-8 bytes; a strict
        # decode would raise and lose the whole (otherwise valid) JSON file.
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _read_config(run_dir: Path) -> Dict[str, Any]:
    """Resolved config + meta."""
    cfg = _read_json(run_dir / "config.json") or {}
    if not cfg and (run_dir / "resolved.json").is_file():
        cfg = _read_json(run_dir / "resolved.json") or {}
    return cfg if isinstance(cfg, dict) else {}


def _completed(run_dir: Path) -> bool:
    """A flow that finished writes its output views to ``<run>/final/``.

    LibreLane only saves ``final/`` on a clean completion (a failing step
    raises and aborts first), so its presence is the authoritative
    "this run finished" signal. We also accept a run-root ``state_out.json``
    for layouts/older flows that write completion state there.
    """
    return (run_dir / "final").is_dir() or (run_dir / "state_out.json").is_file()


def _load_metrics(run_dir: Path) -> Dict[str, Any]:
    """The run's metric dict, from ``final/metrics.json`` (where LibreLane
    writes it) with a run-root fallback. ``metrics.json`` is a flat
    ``{metric: value}`` map."""
    for p in (run_dir / "final" / "metrics.json", run_dir / "metrics.json"):
        doc = _read_json(p)
        if isinstance(doc, dict) and doc:
            if "metrics" in doc and isinstance(doc["metrics"], dict):
                return doc["metrics"]
            return doc
    return {}


# Hard-error counters that, if > 0, mean the run did not cleanly sign off.
_FAIL_METRICS = (
    "flow__errors__count",
    "design__lint_error__count",
    "synthesis__check_error__count",
    "magic__drc_error__count",
    # The KLayout/routing DRC count is `route__drc_errors` — `klayout__drc_error__count`
    # is NOT a real metric (verified against introspect.list_metrics()), so the old
    # key never matched and a run with KLayout DRC violations could be marked success.
    "route__drc_errors",
    "design__lvs_error__count",
    "design__critical_disconnected_pin__count",
    "design__instance_unmapped__count",
)


def _success_from_metrics(metrics: Dict[str, Any], *, run_dir: Optional[Path] = None) -> bool:
    # A run is a success when it completed (wrote final/) and no hard-error
    # counter is non-zero. Completion alone is a strong signal (gating checkers
    # abort the flow), but we still honour explicit error counts when present.
    if run_dir is not None and not _completed(run_dir):
        return False
    for key in _FAIL_METRICS:
        v = metrics.get(key)
        if isinstance(v, dict):
            if any((x or 0) for x in v.values()):
                return False
        elif v is not None and v:
            return False
    # No metrics but completed -> still a success (e.g. a partial -F/-T run) —
    # but only when every step dir actually finished (has state_out.json). A
    # final/ dir sitting next to an aborted step means the run dir is mangled;
    # claiming green there would let the Runs list disagree with Verify.
    if run_dir is not None and not metrics:
        try:
            for entry in run_dir.iterdir():
                if not entry.is_dir():
                    continue
                prefix, sep, _ = entry.name.partition("-")
                if not prefix.isdigit() or not sep:
                    continue
                if (entry / "state_in.json").is_file() and not (entry / "state_out.json").is_file():
                    return False
        except Exception:
            pass
    return True if run_dir is not None else bool(metrics)


def list_runs(design_dir: str | Path) -> List[Dict[str, Any]]:
    design_dir = Path(design_dir).resolve()
    runs = _walk_runs(design_dir)
    out: List[Dict[str, Any]] = []
    for run in runs:
        try:
            summary = _summarise(run)
            out.append(to_json(summary))
        except Exception:
            # Don't let a malformed run hide the others.
            continue
    return out


def _summarise(run_dir: Path) -> RunSummary:
    cfg = _read_config(run_dir)
    metrics = _load_metrics(run_dir)

    flow_name = ""
    if isinstance(cfg.get("meta"), dict):
        flow_name = cfg["meta"].get("flow") or ""

    pdk = cfg.get("PDK") if isinstance(cfg.get("PDK"), str) else None
    scl = cfg.get("STD_CELL_LIBRARY") if isinstance(cfg.get("STD_CELL_LIBRARY"), str) else None

    # Step completion: presence of <NNN-StepName>/<writable marker>
    steps_done = 0
    steps_failed = 0
    step_count = 0
    for entry in run_dir.iterdir():
        if not entry.is_dir():
            continue
        prefix, sep, _ = entry.name.partition("-")
        if not prefix.isdigit() or not sep:
            continue
        step_count += 1
        state_out = entry / "state_out.json"
        state_in = entry / "state_in.json"
        if state_out.is_file():
            steps_done += 1
        elif state_in.is_file() and not state_out.is_file():
            steps_failed += 1

    wall_time = None
    rt = _read_yaml(run_dir / "runtime.yaml")
    if isinstance(rt, dict):
        # runtime.yaml is dict of step -> seconds
        try:
            wall_time = sum(float(v or 0) for v in rt.values())
        except Exception:
            wall_time = None
    if wall_time is None:
        # No run-level runtime.yaml: sum the per-step ``runtime.txt`` files,
        # each formatted ``HH:MM:SS.mmm``.
        total = 0.0
        found = False
        for entry in run_dir.iterdir():
            rtf = entry / "runtime.txt"
            if entry.is_dir() and rtf.is_file():
                secs = _parse_runtime_txt(rtf)
                if secs is not None:
                    total += secs
                    found = True
        if found:
            wall_time = total

    # Pull the highlighted metrics out for the run row.
    hero_keys = [
        "timing__setup__ws",
        "timing__setup__tns",
        "design__instance__area",
        "design__instance__count",
        "antenna__violating__nets",
        "design__lvs_error__count",
    ]
    key: Dict[str, Any] = {}
    for k in hero_keys:
        v = metrics.get(k)
        if v is not None:
            key[k] = v

    return RunSummary(
        tag=run_dir.name,
        run_dir=str(run_dir),
        success=_success_from_metrics(metrics, run_dir=run_dir),
        flow=flow_name or "Classic",
        pdk=pdk,
        scl=scl,
        started_at=datetime.fromtimestamp(run_dir.stat().st_mtime).isoformat(),
        step_count=step_count,
        steps_done=steps_done,
        steps_failed=steps_failed,
        wall_time_s=wall_time,
        key_metrics=key,
        imported=(run_dir / _IMPORT_MARKER).is_file(),
        pinned=(run_dir / _PIN_MARKER).is_file(),
    )


def _parse_runtime_txt(path: Path) -> Optional[float]:
    """Seconds from a per-step ``runtime.txt`` (``HH:MM:SS.mmm`` or a number)."""
    try:
        s = path.read_text(encoding="utf-8").strip()
    except Exception:
        return None
    if not s:
        return None
    try:
        if ":" in s:
            h, m, sec = s.split(":")
            return int(h) * 3600 + int(m) * 60 + float(sec)
        return float(s)
    except Exception:
        return None


def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        try:
            import yaml
            return yaml.safe_load(path.read_text(encoding="utf-8"))
        except ImportError:
            # Minimal fallback for runtime.yaml (key: float/string)
            data = {}
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.split("#")[0].strip()
                if not line or ":" not in line:
                    continue
                k, v = line.split(":", 1)
                try:
                    data[k.strip()] = float(v.strip())
                except ValueError:
                    data[k.strip()] = v.strip()
            return data
    except Exception:
        return None


def get_run(run_dir: str | Path) -> Dict[str, Any]:
    """Full state + metrics + step summaries for one run."""
    run_dir = Path(run_dir).resolve()
    metrics_dict = _load_metrics(run_dir)
    # Final design state: the newest step's state_out.json (LibreLane doesn't
    # write one at the run root); falls back to run-root if present.
    state_doc = _read_json(run_dir / "state_out.json") or {}
    if not state_doc:
        try:
            step_states = sorted(
                (e for e in run_dir.iterdir() if e.is_dir() and _is_step_dir(e.name)
                 and (e / "state_out.json").is_file()),
                key=lambda e: int(e.name.split("-", 1)[0]),
            )
            if step_states:
                state_doc = _read_json(step_states[-1] / "state_out.json") or {}
        except Exception:
            state_doc = {}
    # Point provenance at the file metrics were actually loaded from (LibreLane
    # writes ``final/metrics.json``; a run-root copy is the fallback) so the
    # advertised "source of truth" path resolves to a real file.
    _metrics_file = next(
        (p for p in (run_dir / "final" / "metrics.json", run_dir / "metrics.json") if p.is_file()),
        run_dir / "final" / "metrics.json",
    )
    metric_set = MetricSet(
        path=str(_metrics_file),
        values=metrics_dict,
    )
    summaries = list(_step_summaries(run_dir))
    # Derive design_dir from the run_dir layout: ``<design_dir>/runs/<tag>``.
    runs_root = run_dir.parent
    design_dir: Optional[str] = None
    if runs_root.name == "runs":
        design_dir = str(runs_root.parent)
    view = RunView(
        tag=run_dir.name,
        run_dir=str(run_dir),
        design_dir=design_dir,
        state=state_doc if isinstance(state_doc, dict) else {},
        metrics=metric_set,
        summaries=summaries,
    )
    doc = to_json(view)
    # Curated headline stats + I/O pin count (no metric exists for pins).
    doc["summary"] = design_summary(run_dir, metrics_dict)
    doc["io"] = _io_pins(run_dir)
    return doc


def _is_step_dir(name: str) -> bool:
    """True if name matches <NNN>-<StepName> pattern (e.g. ``001-Yosys.Synthesis``).

    Supports single (``1-``), double (``10-``), and triple-digit (``100-``)
    ordinals.
    """
    prefix, sep, _ = name.partition("-")
    return bool(prefix.isdigit() and sep == "-")


def _step_summaries(run_dir: Path) -> List[str]:
    """Per-step one-liners for the inspector panel."""
    rows: List[str] = []
    try:
        entries = sorted(
            [e for e in run_dir.iterdir() if e.is_dir() and _is_step_dir(e.name)],
            key=lambda e: int(e.name.split("-", 1)[0]),
        )
    except Exception:
        return rows
    for entry in entries:
        step = "-".join(entry.name.split("-")[1:])
        log = entry / f"{step}.log"
        if not log.is_file():
            tcls = list(entry.glob("*.tcl"))
            log = entry / (tcls[0].stem + ".log") if tcls else None
        line = f"{step}: "
        if log is None or not log.is_file():
            line += "no log"
        else:
            try:
                with log.open("r", encoding="utf-8", errors="replace") as f:
                    tail = f.read()[-1000:]
                last = [ln.strip() for ln in tail.splitlines() if ln.strip()][-1:] or [""]
                line += (last[0] or "ok")[:140]
            except Exception:
                line += "log unreadable"
        rows.append(line)
    return rows


_IMAGE_EXTS = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp"}


def list_run_files(run_dir: str | Path, *, max_entries: int = 5000) -> List[Dict[str, Any]]:
    """Flat listing of every file/dir under a run (rel path + size + is_dir),
    for the per-run file browser. Capped so a huge run can't blow up the JSON."""
    run = Path(run_dir)
    out: List[Dict[str, Any]] = []
    try:
        for p in sorted(run.rglob("*"), key=lambda x: str(x.relative_to(run))):
            rel = p.relative_to(run)
            is_dir = p.is_dir()
            try:
                size = p.stat().st_size if not is_dir else 0
            except Exception:
                size = 0
            out.append({"path": str(rel), "dir": is_dir, "size": size})
            if len(out) >= max_entries:
                break
    except Exception:
        pass
    return out


def list_run_images(run_dir: str | Path) -> List[Dict[str, Any]]:
    """Every image artefact in a run, tagged with the step (or ``final``) it
    came from, so the Preview tab can show a per-stage gallery. LibreLane's
    Classic flow renders only the final layout by default, so typically this is
    the final GDS render plus its step copy."""
    run = Path(run_dir)
    out: List[Dict[str, Any]] = []
    try:
        for p in sorted(run.rglob("*")):
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
                rel = p.relative_to(run)
                parts = rel.parts
                top = parts[0] if parts else ""
                if top == "final":
                    step = "final"
                elif _is_step_dir(top):
                    step = "-".join(top.split("-")[1:])
                else:
                    step = top
                out.append({"path": str(rel), "name": p.name, "step": step})
    except Exception:
        pass
    return out


# --------------------------------------------------------------------------
# Design summary (hero stats) + I/O pin counting
# --------------------------------------------------------------------------

def _io_pins(run_dir: Path) -> Dict[str, int]:
    """Top-module I/O port + pin counts from the Yosys JSON header.

    LibreLane has no metric for design pin count, but it writes a JSON design
    header (``final/json_h/<top>.h.json``) whose top module lists every port
    with its bit-vector. ``ports`` = number of named ports; ``pins`` = total
    bits (a 32-bit bus counts as 32 pins). Best-effort: returns {} if absent.
    """
    try:
        jdir = run_dir / "final" / "json_h"
        files = list(jdir.glob("*.json")) if jdir.is_dir() else []
        if not files:
            return {}
        doc = _read_json(files[0]) or {}
        modules = doc.get("modules") or {}
        if not isinstance(modules, dict) or not modules:
            return {}
        # Prefer a module flagged top; else the first one.
        top = None
        for name, m in modules.items():
            attrs = (m or {}).get("attributes") or {}
            if str(attrs.get("top", "0")) not in ("0", ""):
                top = m
                break
        if top is None:
            top = next(iter(modules.values()))
        ports = (top or {}).get("ports") or {}
        if not isinstance(ports, dict):
            return {}
        pins = 0
        for pv in ports.values():
            bits = pv.get("bits") if isinstance(pv, dict) else None
            pins += len(bits) if isinstance(bits, list) else 1
        return {"ports": len(ports), "pins": pins}
    except Exception:
        return {}


def _bbox_dims(bbox: Any) -> Optional[List[float]]:
    """``"x0 y0 x1 y1"`` (string or list) -> [width, height] in microns."""
    try:
        nums = [float(x) for x in (bbox.split() if isinstance(bbox, str) else bbox)]
        if len(nums) == 4:
            return [round(nums[2] - nums[0], 3), round(nums[3] - nums[1], 3)]
    except Exception:
        pass
    return None


def design_summary(run_dir: str | Path, metrics: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """A curated set of the most useful headline stats for a run.

    Returns an ordered list of ``{label, value, unit, key, status}`` rows so the
    UI can render a hero strip without re-deriving units/semantics. ``status`` is
    one of pass/fail/warn/"" (neutral) so violations stand out. Pure: reads only
    the already-parsed metrics plus the JSON header for pin count. Only includes
    a row when its source value exists, so it degrades gracefully across flows.
    """
    run_dir = Path(run_dir)
    m = metrics if metrics is not None else _load_metrics(run_dir)
    rows: List[Dict[str, Any]] = []

    def g(key: str) -> Any:
        return m.get(key)

    def add(label: str, value: Any, unit: str = "", key: str = "", status: str = "") -> None:
        if value is None or value == "":
            return
        rows.append({"label": label, "value": value, "unit": unit, "key": key, "status": status})

    # --- Chip size ---
    die = g("design__die__area")
    dims = _bbox_dims(g("design__die__bbox"))
    if die is not None:
        add("Die area", die, "µm²", "design__die__area")
    if dims:
        add("Die size", f"{dims[0]} × {dims[1]}", "µm", "design__die__bbox")
    add("Core area", g("design__core__area"), "µm²", "design__core__area")

    # --- Utilization ---
    util = g("design__instance__utilization")
    if isinstance(util, (int, float)):
        add("Utilization", round(float(util) * 100, 1), "%", "design__instance__utilization")

    # --- Cells / pins ---
    add("Cell count", g("design__instance__count"), "", "design__instance__count")
    add("Sequential cells", g("design__instance__count__class:sequential_cell"), "",
        "design__instance__count__class:sequential_cell")
    add("Cell area", g("design__instance__area"), "µm²", "design__instance__area")
    io = _io_pins(run_dir)
    if io.get("pins") is not None:
        add("I/O pins", io["pins"], "", "")
    if io.get("ports") is not None:
        add("I/O ports", io["ports"], "", "")

    # --- Power / routing ---
    pw = g("power__total")
    if isinstance(pw, (int, float)):
        add("Total power", round(float(pw) * 1000, 4), "mW", "power__total")
    add("Wirelength", g("route__wirelength"), "µm", "route__wirelength")

    # --- Timing (worst slack across corners) ---
    def slack_row(label: str, key: str) -> None:
        v = g(key)
        if isinstance(v, (int, float)):
            st = "pass" if v >= 0 else "fail"
            add(label, round(float(v), 4) if abs(float(v)) != float("inf") else v, "ns", key, st)
    slack_row("Worst setup slack", "timing__setup__ws")
    slack_row("Worst hold slack", "timing__hold__ws")

    # --- Signoff pass/fail ---
    def fail_row(label: str, key: str) -> None:
        v = g(key)
        if isinstance(v, (int, float)):
            add(label, int(v), "", key, "pass" if v == 0 else "fail")
    fail_row("DRC errors (Magic)", "magic__drc_error__count")
    fail_row("DRC errors (Routing)", "route__drc_errors")
    fail_row("DRC errors (KLayout)", "klayout__drc_error__count")
    fail_row("LVS errors", "design__lvs_error__count")
    fail_row("Antenna violations", "route__antenna_violation__count")
    fail_row("Setup violations", "timing__setup_vio__count")
    fail_row("Hold violations", "timing__hold_vio__count")

    return rows


# --------------------------------------------------------------------------
# Categorised output artefacts (for the Preview "outputs" browser)
# --------------------------------------------------------------------------

# Map a final/<id>/ subdir to (category, friendly label). Ids are stable
# LibreLane DesignFormat ids; unknown ids fall back to the raw subdir name
# under a generic "Other" category, so new formats still appear.
_OUTPUT_MAP: Dict[str, "tuple[str, str]"] = {
    "render": ("Layout", "Layout render (PNG)"),
    "gds": ("Layout", "GDSII stream"),
    "klayout_gds": ("Layout", "GDSII (KLayout)"),
    "mag_gds": ("Layout", "GDSII (Magic)"),
    "def": ("Layout", "DEF — placed & routed"),
    "mag": ("Layout", "Magic layout view"),
    "lef": ("Layout", "LEF abstract"),
    "openroad_lef": ("Layout", "LEF (OpenROAD)"),
    "odb": ("Layout", "OpenDB database"),
    "nl": ("Netlist", "Verilog netlist"),
    "pnl": ("Netlist", "Powered Verilog netlist"),
    "logical_nl": ("Netlist", "Logical netlist"),
    "logical_pnl": ("Netlist", "Logical powered netlist"),
    "spice": ("Netlist", "SPICE netlist"),
    "spice_rcx": ("Netlist", "SPICE netlist (RC-extracted)"),
    "cdl": ("Netlist", "CDL netlist"),
    "json_h": ("Netlist", "Design JSON header"),
    "vh": ("Netlist", "Verilog header"),
    "lib": ("Timing", "Liberty timing (.lib)"),
    "sdf": ("Timing", "SDF delays"),
    "sdf_pnl": ("Timing", "Powered netlist for SDF sim"),
    "spef": ("Timing", "Parasitics (SPEF)"),
    "sdc": ("Timing", "Constraints (SDC)"),
}

_CATEGORY_ORDER = ["Layout", "Netlist", "Timing", "Reports", "Other"]


def list_run_outputs(run_dir: str | Path) -> List[Dict[str, Any]]:
    """The canonical output artefacts of a run, grouped by category.

    LibreLane consolidates every deliverable under ``<run>/final/`` (the layout
    render, GDS/DEF, netlists, timing libs, parasitics, the metrics CSV/JSON).
    We enumerate that tree so the Preview tab can show, download, and reveal
    every output — without dumping the thousands of intermediate step files
    (those stay available in the per-run Files browser). Pure / stdlib only.
    """
    run = Path(run_dir)
    final = run / "final"
    out: List[Dict[str, Any]] = []
    if not final.is_dir():
        return out
    try:
        for p in sorted(final.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(run)            # e.g. final/lib/nom_tt.../spm.lib
            parts = p.relative_to(final).parts  # e.g. (lib, nom_tt..., spm.lib)
            fmt_id = parts[0] if len(parts) > 1 else ""
            try:
                size = p.stat().st_size
            except Exception:
                size = 0
            if fmt_id in _OUTPUT_MAP:
                category, label = _OUTPUT_MAP[fmt_id]
            elif p.name in ("metrics.json", "metrics.csv"):
                category, label = "Reports", "Metrics table"
            elif fmt_id == "":
                category, label = "Reports", p.name
            else:
                category, label = "Other", fmt_id
            # A per-corner sub-path (lib/<corner>/...) -> show the corner.
            variant = parts[1] if len(parts) > 2 else ""
            out.append({
                "path": str(rel),
                "name": p.name,
                "category": category,
                "label": label,
                "format": fmt_id,
                "variant": variant,
                "size": size,
            })
    except Exception:
        pass
    # Stable order: by category rank, then label, then name.
    rank = {c: i for i, c in enumerate(_CATEGORY_ORDER)}
    out.sort(key=lambda r: (rank.get(r["category"], 99), r["label"], r["name"]))
    return out


# --------------------------------------------------------------------------
# Synthesis diagrams (graphviz DOT from Yosys, gated behind SYNTH_SHOW)
# --------------------------------------------------------------------------

# Yosys' ``show -prefix <name>`` writes these when SYNTH_SHOW is enabled.
_DIAGRAM_LABELS = {
    "hierarchy": "Design hierarchy (block diagram)",
    "primitive_techmap": "Gate-level schematic (post-techmap)",
}


def list_run_diagrams(run_dir: str | Path) -> List[Dict[str, Any]]:
    """Graphviz DOT diagrams a run produced (Yosys synthesis schematics).

    LibreLane only writes these when ``SYNTH_SHOW`` is enabled — the Yosys
    synthesis step emits ``hierarchy.dot`` (block diagram) and
    ``primitive_techmap.dot`` (gate-level schematic). They are ``.dot`` source,
    not rendered images; :func:`render_dot` turns one into SVG on demand. Pure /
    stdlib. Empty list means none were generated (the common default)."""
    run = Path(run_dir)
    out: List[Dict[str, Any]] = []
    seen: set = set()
    try:
        for p in sorted(run.rglob("*.dot")):
            if not p.is_file():
                continue
            rel = p.relative_to(run)
            top = rel.parts[0] if rel.parts else ""
            if top == "final":
                step = "final"
            elif _is_step_dir(top):
                step = "-".join(top.split("-")[1:])
            else:
                step = top
            # Dedupe: the same diagram can be copied into several locations
            # (step dir + final). One card per (step, filename) is enough — the
            # UI was rendering 3-4 identical copies otherwise.
            key = (step, p.name)
            if key in seen:
                continue
            seen.add(key)
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            out.append({
                "path": str(rel),
                "name": p.name,
                "step": step,
                "label": _DIAGRAM_LABELS.get(p.stem, p.name),
                "size": size,
                # Gate-level schematics of a real netlist can be enormous; flag
                # them so the UI renders on demand instead of auto-OOMing dot.
                "large": size > _DOT_AUTO_RENDER_MAX,
            })
    except Exception:
        pass
    return out


# Above this, graphviz auto-render is refused (must pass force=True). A
# gate-level techmap schematic of thousands of cells can balloon dot's memory
# and produce a multi-MB SVG that freezes the browser — so big diagrams are
# render-on-demand only.
_DOT_AUTO_RENDER_MAX = 350_000        # bytes of .dot source
_DOT_HARD_MAX = 8_000_000             # never even attempt above this
_SVG_MAX_BYTES = 12_000_000           # refuse to serve an SVG larger than this


def _dot_rlimit():
    """Best-effort preexec that caps a child `dot`'s RAM + CPU (POSIX only).

    Without this a runaway graphviz layout can exhaust system memory and take
    the whole machine down (the reported "broken pipe" / laptop hang). On
    Windows there is no `resource` module, so we rely on the timeout alone.
    """
    try:
        import resource  # POSIX only
    except Exception:
        return None

    def _apply():  # pragma: no cover - runs in the forked child
        try:
            resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 ** 3, 2 * 1024 ** 3))
        except Exception:
            pass
        try:
            resource.setrlimit(resource.RLIMIT_CPU, (45, 50))
        except Exception:
            pass

    return _apply


def render_dot(run_dir: str | Path, rel_path: str, *, force: bool = False) -> Dict[str, Any]:
    """Render a run's ``.dot`` to a sibling ``.svg`` via graphviz, cached.

    Returns ``{ok: True, svg: <rel-path>}`` (the caller serves it through the
    traversal-safe run-file route) or ``{ok: False, error, need?/too_large?}``.
    Graceful when graphviz is absent: callers offer the raw ``.dot`` download
    instead. The SVG is cached next to the DOT and reused until the DOT changes.

    Large diagrams (gate-level schematics of real netlists) are **not**
    auto-rendered: dot can balloon to gigabytes of RAM and emit a multi-MB SVG
    that hangs the browser. Pass ``force=True`` to render one anyway, under a
    memory/CPU rlimit + timeout so it can never take the host down. The caller
    must have already validated *rel_path* is inside *run_dir*."""
    run = Path(run_dir)
    dot_file = (run / rel_path).resolve()
    if dot_file.suffix.lower() != ".dot" or not dot_file.is_file():
        return {"ok": False, "error": "not a .dot file"}
    svg_file = dot_file.with_name(dot_file.name + ".svg")
    try:
        if svg_file.is_file() and svg_file.stat().st_mtime >= dot_file.stat().st_mtime:
            return {"ok": True, "svg": str(svg_file.relative_to(run))}
    except Exception:
        pass

    try:
        size = dot_file.stat().st_size
    except OSError:
        size = 0
    if size > _DOT_HARD_MAX:
        return {
            "ok": False, "too_large": True, "size": size,
            "error": f"diagram source is {size // 1000} KB — too large to render. "
                     "Download the .dot and view it in a desktop graphviz viewer.",
        }
    if size > _DOT_AUTO_RENDER_MAX and not force:
        return {
            "ok": False, "too_large": True, "size": size,
            "error": f"diagram source is {size // 1000} KB. Rendering big schematics "
                     "is slow and memory-heavy — click “Render anyway”, or download the .dot.",
        }

    from . import platform_env
    dot_bin = platform_env.usable_which("dot")  # ignore a Windows dot.exe on WSL
    if not dot_bin:
        return {
            "ok": False,
            "need": "graphviz",
            "error": "graphviz 'dot' is not installed on the machine running the GUI — "
                     "install graphviz to view diagrams, or download the .dot file.",
        }
    try:
        # -Gnslimit*/-Gmclimit cap graphviz's layout iterations so a pathological
        # graph terminates instead of spinning; the rlimit + timeout are the hard
        # safety net.
        proc = subprocess.run(
            [dot_bin, "-Tsvg", "-Gnslimit=2", "-Gnslimit2=2", "-Gmclimit=2", str(dot_file)],
            capture_output=True, timeout=60, preexec_fn=_dot_rlimit(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "graphviz timed out rendering this diagram — "
                "it is too large to render inline; download the .dot instead."}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    if proc.returncode != 0:
        msg = (proc.stderr.decode("utf-8", "replace").strip() or "dot failed")[:300]
        return {"ok": False, "error": msg}
    if len(proc.stdout) > _SVG_MAX_BYTES:
        return {"ok": False, "too_large": True, "size": len(proc.stdout),
                "error": "rendered SVG is too large to display in the browser — "
                         "download the .dot and view it in a desktop viewer."}
    try:
        svg_file.write_bytes(proc.stdout)
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "svg": str(svg_file.relative_to(run))}


def render_dot_png(run_dir: str | Path, rel_path: str, *, force: bool = False) -> Dict[str, Any]:
    """Render a run's ``.dot`` to a sibling PNG via graphviz, cached.

    Same safety envelope as :func:`render_dot` (size caps, RAM/CPU rlimit,
    timeout, ``usable_which`` to dodge a Windows ``dot.exe`` on WSL) but emits a
    raster ``<name>.dot.png``. Used by the run bundle so a schematic ships as a
    drop-in image, not just a ``.dot``/``.svg``. Returns ``{ok, png: <rel>}`` or
    ``{ok: False, ...}``; the caller treats failure as "skip this PNG".
    """
    run = Path(run_dir)
    dot_file = (run / rel_path).resolve()
    if dot_file.suffix.lower() != ".dot" or not dot_file.is_file():
        return {"ok": False, "error": "not a .dot file"}
    png_file = dot_file.with_name(dot_file.name + ".png")
    try:
        if png_file.is_file() and png_file.stat().st_mtime >= dot_file.stat().st_mtime:
            return {"ok": True, "png": str(png_file.relative_to(run))}
    except Exception:
        pass

    try:
        size = dot_file.stat().st_size
    except OSError:
        size = 0
    if size > _DOT_HARD_MAX:
        return {"ok": False, "too_large": True, "size": size,
                "error": f"diagram source is {size // 1000} KB — too large to render."}
    if size > _DOT_AUTO_RENDER_MAX and not force:
        return {"ok": False, "too_large": True, "size": size,
                "error": f"diagram source is {size // 1000} KB — too large to auto-render."}

    from . import platform_env
    dot_bin = platform_env.usable_which("dot")  # ignore a Windows dot.exe on WSL
    if not dot_bin:
        return {"ok": False, "need": "graphviz",
                "error": "graphviz 'dot' is not installed on the machine running the GUI."}
    try:
        proc = subprocess.run(
            [dot_bin, "-Tpng", "-Gnslimit=2", "-Gnslimit2=2", "-Gmclimit=2", str(dot_file)],
            capture_output=True, timeout=60, preexec_fn=_dot_rlimit(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "graphviz timed out rendering this diagram."}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    if proc.returncode != 0:
        msg = (proc.stderr.decode("utf-8", "replace").strip() or "dot failed")[:300]
        return {"ok": False, "error": msg}
    if not proc.stdout:
        return {"ok": False, "error": "graphviz produced an empty PNG"}
    try:
        png_file.write_bytes(proc.stdout)
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "png": str(png_file.relative_to(run))}


def get_step_output(run_dir: str | Path, step_id: str, *, tail_bytes: int = 60000) -> Dict[str, Any]:
    """Return one step's log + reports for the click-to-inspect panel.

    Step directories are ``<NNN>-<step-id-lowercased-dashed>`` (e.g.
    ``66-checker-magicdrc`` for ``Checker.MagicDRC``) and the log inside is
    ``<suffix>.log``. Both the qualified step id (``Checker.MagicDRC``) and the
    on-disk directory name (``66-checker-magicdrc``, with or without the ``NN-``
    prefix) are accepted — API users reading ids off the run dir kept passing
    the dir form and getting an unexplained miss. A miss now lists the valid
    directory names instead of a bare "not found". ANSI is stripped and the
    log is tail-capped so a huge log can't blow up the response.
    """
    run = Path(run_dir)
    want = step_id.lower().replace(".", "-")
    step_dirs: List[Path] = []
    try:
        for e in sorted(run.iterdir(), key=lambda d: d.name):
            if e.is_dir() and _is_step_dir(e.name):
                step_dirs.append(e)
    except Exception:
        pass
    match: Optional[Path] = None
    for e in step_dirs:
        suffix = "-".join(e.name.split("-")[1:])
        if want in (suffix.lower(), e.name.lower()):
            match = e
            break
    if match is None:
        return {"ok": False, "step": step_id, "reason": "step not found in this run",
                "valid_steps": [e.name for e in step_dirs]}

    suffix = "-".join(match.name.split("-")[1:])
    log = match / f"{suffix}.log"
    if not log.is_file():
        candidates = sorted(match.glob("*.log"))
        log = candidates[0] if candidates else None

    text = "(no log file for this step)"
    truncated = False
    if log is not None and log.is_file():
        try:
            data = log.read_text(encoding="utf-8", errors="replace")
            if len(data) > tail_bytes:
                data = data[-tail_bytes:]
                truncated = True
            try:
                from .container_run import strip_ansi

                data = strip_ansi(data)
            except Exception:
                pass
            text = data
        except Exception:
            text = "(log unreadable)"

    reports: List[str] = []
    rdir = match / "reports"
    if rdir.is_dir():
        try:
            for r in sorted(rdir.rglob("*")):
                if r.is_file():
                    reports.append(str(r.relative_to(match)))
        except Exception:
            pass

    return {
        "ok": True,
        "step": step_id,
        "dir": match.name,
        "log_file": log.name if log else None,
        "log": text,
        "truncated": truncated,
        "reports": reports[:50],
        "completed": (match / "state_out.json").is_file(),
    }


# --------------------------------------------------------------------------
# Cell-usage table (Phase 1.D — mattvenn-style)
# --------------------------------------------------------------------------

# JSON/CSV files inside the CellFrequencyTables step dir that are NOT cell tables
# (process-stat dumps, OpenROAD metrics, step state/config) — must be skipped or
# their top-level keys (time/peak_resources/…) get mistaken for "cells".
_NON_CELL_FILES = (
    "process_stats", "or_metrics_out", "state_in", "state_out",
    "config", "runtime", "metrics",
)


def cell_usage(run_dir: str | Path) -> List[Dict[str, Any]]:
    """Per-cell-type usage counts for a run (the `--show-sky130`-style table).

    The ``Odb.CellFrequencyTables`` step writes the canonical "Cells by Master"
    table to ``cell.rpt`` (a Rich-rendered box table). We parse that first; then
    fall back to a genuine cell JSON/CSV, then to the per-class instance-count
    metrics. Returns ``[{cell, count, area?}]`` sorted by count desc. Pure /
    stdlib only — empty list when nothing is available."""
    run = Path(run_dir)
    step = None
    try:
        for e in sorted(run.iterdir(), key=lambda d: d.name):
            if e.is_dir() and _is_step_dir(e.name) and e.name.lower().endswith("cellfrequencytables"):
                step = e
                break
    except Exception:
        step = None

    rows: List[Dict[str, Any]] = []
    if step is not None:
        # 1) The "Cells by Master" report — the real per-cell-master breakdown.
        for name in ("cell.rpt", "cell_function.rpt"):
            rpt = step / name
            if rpt.is_file():
                rows = _cells_from_rpt(rpt)
                if rows:
                    break
        # 2) A genuine cell JSON/CSV table (skip stat/metrics/state dumps that
        #    would otherwise be mis-read as a {cell: count} map).
        if not rows:
            for jf in sorted(step.rglob("*.json")):
                if any(tok in jf.name.lower() for tok in _NON_CELL_FILES):
                    continue
                rows = _cells_from_json(_read_json(jf))
                if rows:
                    break
        if not rows:
            for cf in sorted(step.rglob("*.csv")):
                if any(tok in cf.name.lower() for tok in _NON_CELL_FILES):
                    continue
                rows = _cells_from_csv(cf)
                if rows:
                    break
    # 3) Coarse per-class fallback from metrics.json (always present).
    if not rows:
        rows = _cells_from_metrics(_load_metrics(run))
    rows.sort(key=lambda r: r.get("count") or 0, reverse=True)
    return rows


def _cells_from_rpt(path: Path) -> List[Dict[str, Any]]:
    """Parse a Rich box-table report (cell.rpt 'Cells by Master').

    Data rows use the light vertical bar ``│`` between columns; the header uses
    the heavy bar ``┃`` and borders use ``┏┳┓┡╇┩└┴┘━``, so filtering on ``│``
    cleanly selects ``│ <cell> │ <count> │`` rows. Returns ``[{cell, count}]``."""
    out: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if "│" not in line:
                    continue
                cols = [c.strip() for c in line.split("│") if c.strip() != ""]
                if len(cols) < 2:
                    continue
                cell, cnt = cols[0], cols[1]
                try:
                    count = int(cnt.replace(",", ""))
                except ValueError:
                    continue            # header ("Count") / non-numeric row
                out.append({"cell": cell, "count": count})
    except Exception:
        return []
    return out


def _cells_from_json(doc: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if isinstance(doc, dict):
        # {cell: count} or {cell: {count, area}}
        for cell, v in doc.items():
            if isinstance(v, dict):
                out.append({"cell": cell, "count": v.get("count"), "area": v.get("area")})
            elif isinstance(v, (int, float)):
                out.append({"cell": cell, "count": v})
    elif isinstance(doc, list):
        for item in doc:
            if isinstance(item, dict) and ("cell" in item or "name" in item):
                out.append({"cell": item.get("cell") or item.get("name"),
                            "count": item.get("count"), "area": item.get("area")})
    return [r for r in out if r.get("cell")]


def _cells_from_csv(path: Path) -> List[Dict[str, Any]]:
    import csv
    out: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                lk = {(k or "").strip().lower(): v for k, v in row.items()}
                cell = lk.get("cell") or lk.get("name") or lk.get("master")
                cnt = lk.get("count") or lk.get("frequency") or lk.get("instances")
                if not cell:
                    continue
                try:
                    cnt = int(float(cnt)) if cnt not in (None, "") else None
                except Exception:
                    cnt = None
                area = lk.get("area")
                try:
                    area = float(area) if area not in (None, "") else None
                except Exception:
                    area = None
                out.append({"cell": cell, "count": cnt, "area": area})
    except Exception:
        return []
    return out


def _cells_from_metrics(metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Derive a coarse usage table from ``design__instance__count__class:*`` keys."""
    out: List[Dict[str, Any]] = []
    prefix = "design__instance__count__class:"
    for k, v in metrics.items():
        if k.startswith(prefix) and isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append({"cell": k[len(prefix):], "count": int(v)})
    return out


# --------------------------------------------------------------------------
# Multi-run compare (Phase 1) + run export (Phase 0)
# --------------------------------------------------------------------------

def compare_runs(run_dirs: List[str | Path]) -> Dict[str, Any]:
    """Compare N runs: config diff, metric table, best-per-metric.

    Builds on :func:`get_run` (config + metrics + summary per run) and
    :func:`introspect.list_metrics` for higher-is-better semantics. Pure;
    non-finite metric values stay as-is (the server's ``_json_safe`` stringifies
    them at the boundary). Shape matches phase-1 spec section B.
    """
    runs: List[Dict[str, Any]] = []
    metric_union: Dict[str, Dict[str, Any]] = {}
    config_by_col: Dict[str, Dict[str, Any]] = {}
    for rd in run_dirs:
        try:
            view = get_run(rd)
        except Exception:
            continue
        run_dir = str(view.get("run_dir") or rd)
        tag = view.get("tag") or Path(run_dir).name
        # Column key MUST be unique per run, not the tag: two different designs
        # can each hold a run named "baseline" (``<design>/runs/baseline``) — a
        # tag-keyed table silently collapses them onto one column (Fear F/M). The
        # resolved run_dir is unique, so key every per-run table by it. ``tag`` +
        # ``design`` stay on the run row for display/disambiguation only.
        col = run_dir
        design = _design_name(run_dir)
        cfg = _read_config(Path(run_dir))
        config_by_col[col] = cfg if isinstance(cfg, dict) else {}
        metrics = (view.get("metrics") or {}).get("values") or {}
        for k, v in metrics.items():
            metric_union.setdefault(k, {})[col] = v
        runs.append({
            "col": col,
            "tag": tag,
            "design": design,
            "run_dir": run_dir,
            "success": _success_from_metrics(metrics, run_dir=Path(run_dir)),
            "summary": view.get("summary") or [],
        })

    cols = [r["col"] for r in runs]

    # Config diff: only keys whose value differs across the runs (or is absent
    # in some). Compared by JSON repr to avoid type/ordering false-negatives.
    all_keys = set()
    for cfg in config_by_col.values():
        all_keys.update(cfg.keys())
    config_diff: Dict[str, Dict[str, Any]] = {}
    for key in sorted(all_keys):
        vals = {c: config_by_col.get(c, {}).get(key) for c in cols}
        reprs = {json.dumps(_jsonify(v), sort_keys=True) for v in vals.values()}
        if len(reprs) > 1:
            config_diff[key] = vals

    # Key-config block: the most decision-relevant vars (clock, utilisation,
    # synth strategy, …) shown for EVERY run — not just the ones that differ —
    # so the user can see "what recipe made this" at a glance. Only vars present
    # in at least one run's resolved config are emitted.
    key_config: Dict[str, Dict[str, Any]] = {}
    for key in _KEY_CONFIG_VARS:
        present = {c: config_by_col.get(c, {}).get(key) for c in cols}
        if any(v is not None for v in present.values()):
            key_config[key] = present

    # Metric meta + best-per-metric. ``best`` is only computed when the metric's
    # optimisation direction is KNOWN from the registry — guessing a direction
    # for an unregistered/renamed metric could highlight the worse run as "best"
    # (a silent Fear-A/J trap), so an unknown metric gets no highlight.
    meta = _metric_meta()
    best: Dict[str, str] = {}
    metric_meta: Dict[str, Dict[str, Any]] = {}
    for metric, per_col in metric_union.items():
        m = meta.get(metric)
        known = m is not None
        hib = bool(m.get("higher_is_better", True)) if known else True
        metric_meta[metric] = {
            "higher_is_better": hib,
            "critical": bool(m.get("critical", False)) if known else False,
            "direction_known": known,
        }
        if not known:
            continue
        numeric = {c: float(v) for c, v in per_col.items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)
                   and float(v) == float(v) and abs(float(v)) != float("inf")}
        if numeric:
            best[metric] = (max if hib else min)(numeric, key=numeric.get)

    return {
        "runs": runs,
        "config_diff": config_diff,
        "key_config": key_config,
        "metric_table": metric_union,
        "metric_meta": metric_meta,
        "best": best,
    }


def _design_name(run_dir: str | Path) -> str:
    """Design folder name for a run laid out as ``<design_dir>/runs/<tag>``.

    Best-effort label only (used to disambiguate same-named runs from different
    designs in Compare); returns "" when the layout doesn't match.
    """
    try:
        p = Path(run_dir)
        if p.parent.name == "runs":
            return p.parent.parent.name
    except Exception:
        pass
    return ""


# Curated, decision-relevant config vars surfaced in run-vs-run compare. All are
# real LibreLane variables; absent ones are skipped, so this never fabricates.
_KEY_CONFIG_VARS = [
    "CLOCK_PERIOD", "CLOCK_PORT", "CLOCK_NET",
    "FP_CORE_UTIL", "FP_ASPECT_RATIO", "PL_TARGET_DENSITY_PCT",
    "SYNTH_STRATEGY", "SYNTH_SDC_FILE", "MAX_FANOUT_CONSTRAINT",
    "GRT_ANTENNA_REPAIR_ITERS", "DIODE_ON_PORTS", "RUN_LINTER",
    "GRT_ALLOW_CONGESTION", "PL_RESIZER_HOLD_SLACK_MARGIN",
]


def _jsonify(v: Any) -> Any:
    """Best-effort JSON-stable representation for diffing (handles non-finite)."""
    if isinstance(v, float) and (v != v or abs(v) == float("inf")):
        return str(v)
    try:
        json.dumps(v)
        return v
    except Exception:
        return str(v)


def _metric_meta() -> Dict[str, Dict[str, Any]]:
    try:
        from . import introspect
        return {m["name"]: m for m in introspect.list_metrics()}
    except Exception:
        return {}


def _export_verdict(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A light pass/fail rollup from design-summary rows (Phase 1's verify.py
    gives the rich version; export only needs a headline)."""
    blockers = [r["label"] for r in rows if r.get("status") == "fail"]
    return {"ready": not blockers, "blockers": blockers}


def export_run(run_dir: str | Path, fmt: str = "csv") -> Dict[str, Any]:
    """Export a run as a portable artifact (Phase 0.4).

    ``csv`` mirrors LibreLane's ``final/metrics.csv`` when present, else builds a
    two-column table from ``metrics.json``. ``md``/``html`` assemble a
    self-contained summary (design summary, verdict, key metrics, embedded
    preview PNG as a data-URI). Returns
    ``{ok, content_type, filename, text|b64}``. Pure / stdlib only.
    """
    run = Path(run_dir).resolve()
    tag = run.name
    metrics = _load_metrics(run)
    fmt = (fmt or "csv").lower()

    if fmt == "csv":
        existing = run / "final" / "metrics.csv"
        if existing.is_file():
            try:
                return {"ok": True, "content_type": "text/csv; charset=utf-8",
                        "filename": f"{tag}-metrics.csv", "text": existing.read_text(encoding="utf-8")}
            except Exception:
                pass
        import csv
        import io
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["metric", "value"])
        for k in sorted(metrics):
            v = metrics[k]
            w.writerow([k, "" if v is None else _metric_text(v)])
        return {"ok": True, "content_type": "text/csv; charset=utf-8",
                "filename": f"{tag}-metrics.csv", "text": buf.getvalue()}

    if fmt in ("md", "html"):
        rows = design_summary(run, metrics)
        # Reuse the Verification Center's three-state verdict (ready / incomplete /
        # not-ready) so a saved report can't show green "Tape-out ready" for a run
        # that never reached signoff. Lazy import avoids a verify<->history cycle.
        try:
            from . import verify as _verify
            verdict = _verify.verify_report(run)["verdict"]
        except Exception:
            verdict = _export_verdict(rows)
        if fmt == "md":
            text = _export_md(tag, rows, verdict, metrics)
            return {"ok": True, "content_type": "text/markdown; charset=utf-8",
                    "filename": f"{tag}-summary.md", "text": text}
        text = _export_html(run, tag, rows, verdict, metrics)
        return {"ok": True, "content_type": "text/html; charset=utf-8",
                "filename": f"{tag}-summary.html", "text": text}

    return {"ok": False, "error": f"unsupported format '{fmt}'"}


def _metric_text(v: Any) -> str:
    """Non-finite values print as the API/CSV tokens (``Infinity``, ``-Infinity``,
    ``NaN``). Python's default ``str()`` gives ``inf``/``nan``, which made the MD
    export disagree with the CSV export of the very same run."""
    if isinstance(v, float):
        if v == float("inf"):
            return "Infinity"
        if v == float("-inf"):
            return "-Infinity"
        if v != v:  # NaN
            return "NaN"
    return str(v)


def _fmt_val(r: Dict[str, Any]) -> str:
    v = r.get("value")
    unit = r.get("unit") or ""
    return f"{_metric_text(v)} {unit}".strip()


def _export_md(tag: str, rows: List[Dict[str, Any]], verdict: Dict[str, Any],
               metrics: Dict[str, Any]) -> str:
    lines = [f"# LibreLane run summary — `{tag}`", ""]
    if verdict.get("incomplete") and not verdict.get("blockers"):
        lines.append("**Signoff status:** ⚠ incomplete — no tape-out verdict (the run "
                     "did not produce all signoff data)")
        miss = verdict.get("missing_stages") or []
        if miss:
            lines.append("")
            lines.append("Missing signoff stages: " + ", ".join(miss))
    else:
        lines.append(f"**Tape-out ready:** {'✅ yes' if verdict['ready'] else '❌ no'}")
        if verdict.get("blockers"):
            lines.append("")
            lines.append("Blockers: " + ", ".join(verdict["blockers"]))
    lines += ["", "## Headline", "", "| Stat | Value |", "| --- | --- |"]
    for r in rows:
        lines.append(f"| {r['label']} | {_fmt_val(r)} |")
    lines += ["", "## All metrics", "", "| Metric | Value |", "| --- | --- |"]
    for k in sorted(metrics):
        lines.append(f"| `{k}` | {_metric_text(metrics[k])} |")
    lines.append("")
    return "\n".join(lines)


def _esc(s: Any) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _preview_data_uri(run: Path, *, max_bytes: int = 4 * 1024 * 1024) -> Optional[str]:
    """A base64 data-URI of the run's final layout render, for inline embedding.
    None when absent or too large (keeps the HTML reasonable)."""
    import base64
    try:
        imgs = list_run_images(run)
        final = [i for i in imgs if i.get("step") == "final" and i["name"].lower().endswith(".png")]
        pick = final or [i for i in imgs if i["name"].lower().endswith(".png")]
        if not pick:
            return None
        p = run / pick[0]["path"]
        if not p.is_file() or p.stat().st_size > max_bytes:
            return None
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return None


def _export_html(run: Path, tag: str, rows: List[Dict[str, Any]], verdict: Dict[str, Any],
                 metrics: Dict[str, Any]) -> str:
    incomplete = verdict.get("incomplete") and not verdict.get("blockers")
    ready = verdict["ready"]
    if incomplete:
        badge_color, badge_text = "#9a6700", "Signoff incomplete"
    elif ready:
        badge_color, badge_text = "#1a7f37", "Tape-out ready"
    else:
        badge_color, badge_text = "#cf222e", "Not ready"
    cards = "".join(
        f"<div class='card'><div class='k'>{_esc(r['label'])}</div>"
        f"<div class='v {('fail' if r.get('status')=='fail' else 'pass' if r.get('status')=='pass' else '')}'>"
        f"{_esc(_fmt_val(r))}</div></div>"
        for r in rows
    )
    metric_rows = "".join(
        f"<tr><td><code>{_esc(k)}</code></td><td>{_esc(_metric_text(metrics[k]))}</td></tr>"
        for k in sorted(metrics)
    )
    img = _preview_data_uri(run)
    img_html = f"<h2>Layout</h2><img src='{img}' alt='layout render'>" if img else ""
    blockers = ("<p class='blockers'>Blockers: " + ", ".join(_esc(b) for b in verdict["blockers"]) + "</p>") if verdict["blockers"] else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>LibreLane summary — {_esc(tag)}</title>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem auto; max-width: 960px; color: #1f2328; padding: 0 1rem; }}
  h1 {{ font-size: 1.5rem; }}
  .badge {{ display:inline-block; padding:.25rem .6rem; border-radius:6px; color:#fff; font-weight:600; background:{badge_color}; }}
  .blockers {{ color:#cf222e; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:.6rem; margin:1rem 0; }}
  .card {{ border:1px solid #d0d7de; border-radius:8px; padding:.6rem .8rem; }}
  .card .k {{ font-size:.78rem; color:#656d76; }}
  .card .v {{ font-size:1.1rem; font-weight:600; font-variant-numeric:tabular-nums; }}
  .v.pass {{ color:#1a7f37; }} .v.fail {{ color:#cf222e; }}
  table {{ border-collapse:collapse; width:100%; font-size:.85rem; }}
  td {{ border-bottom:1px solid #eaeef2; padding:.3rem .5rem; }}
  img {{ max-width:100%; border:1px solid #d0d7de; border-radius:8px; }}
  code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
</style></head>
<body>
  <h1>LibreLane run summary — {_esc(tag)}</h1>
  <p><span class="badge">{badge_text}</span></p>
  {blockers}
  <div class="cards">{cards}</div>
  {img_html}
  <h2>All metrics</h2>
  <table><thead><tr><th>Metric</th><th>Value</th></tr></thead><tbody>{metric_rows}</tbody></table>
</body></html>
"""


# --------------------------------------------------------------------------
# Run notes — a small per-run free-text annotation ("best QoR so far", "used the
# dodgy LEF"). Stored as a plain text sidecar IN the run dir so it travels with
# the run and never touches LibreLane's own artefacts. Bounded to keep it sane.
# --------------------------------------------------------------------------

_NOTE_FILE = ".gui-note.txt"
_NOTE_MAX = 4000

# Marker dropped into a run dir that was pulled in from elsewhere (E1). Used by
# _summarise() to badge the Runs row "imported".
_IMPORT_MARKER = "gui-imported.json"

# Empty marker file present iff the user pinned/starred the run (E4.5).
_PIN_MARKER = ".gui-pin"


# Per-design metric watch-list (E4.2): rules of the form "this metric must stay
# <cmp> <threshold>". Stored beside the design; evaluated against a finished run.
_WATCH_FILE = ".gui-watch.json"
_WATCH_CMPS = {">", "<", ">=", "<=", "==", "!="}


def read_watch(design_dir: str | Path) -> List[Dict[str, Any]]:
    p = Path(design_dir) / _WATCH_FILE
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []
    except Exception:
        return []


def write_watch(design_dir: str | Path, rules: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist the watch-list for a design. Rules are sanitised: each needs a
    non-empty ``metric``, a known comparator, and a numeric ``threshold``; bad
    rules are dropped rather than stored."""
    clean: List[Dict[str, Any]] = []
    for r in rules or []:
        if not isinstance(r, dict):
            continue
        metric = str(r.get("metric", "")).strip()
        cmp = str(r.get("cmp", "")).strip()
        try:
            threshold = float(r.get("threshold"))
        except (TypeError, ValueError):
            continue
        if metric and cmp in _WATCH_CMPS:
            clean.append({"metric": metric, "cmp": cmp, "threshold": threshold})
    p = Path(design_dir) / _WATCH_FILE
    try:
        if clean:
            p.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
        elif p.is_file():
            p.unlink()
        return {"ok": True, "rules": clean}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def _watch_satisfied(value: float, cmp: str, threshold: float) -> bool:
    if cmp == ">":
        return value > threshold
    if cmp == "<":
        return value < threshold
    if cmp == ">=":
        return value >= threshold
    if cmp == "<=":
        return value <= threshold
    if cmp == "==":
        return value == threshold
    if cmp == "!=":
        return value != threshold
    return True


def evaluate_watch(metrics: Dict[str, Any], rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the rules a run VIOLATES. Only rules whose metric is actually
    present and finite in the run are evaluated — a missing or non-finite metric
    is never reported as a pass OR a fail (no invented verdicts). Each violation
    carries the real observed value so the UI shows the truth, not a guess."""
    from decimal import Decimal
    violations: List[Dict[str, Any]] = []
    metrics = metrics or {}
    for r in rules or []:
        metric = r.get("metric")
        cmp = r.get("cmp")
        threshold = r.get("threshold")
        if metric not in metrics or cmp not in _WATCH_CMPS:
            continue
        v = metrics[metric]
        if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv != fv or fv in (float("inf"), float("-inf")):  # NaN / inf
            continue
        try:
            tf = float(threshold)
        except (TypeError, ValueError):
            continue
        if not _watch_satisfied(fv, cmp, tf):
            violations.append({"metric": metric, "value": fv, "cmp": cmp, "threshold": tf})
    return violations


def set_pin(run_dir: str | Path, pinned: bool) -> Dict[str, Any]:
    """Pin/unpin a run (E4.5) — drops or removes an empty ``.gui-pin`` marker.
    Purely a user bookmark; never touches run data."""
    rd = Path(run_dir)
    if not rd.is_dir():
        return {"ok": False, "error": "run not found"}
    marker = rd / _PIN_MARKER
    try:
        if pinned:
            marker.touch()
        elif marker.is_file():
            marker.unlink()
        return {"ok": True, "pinned": bool(pinned)}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


def _looks_like_run(d: Path) -> bool:
    """A directory looks like a LibreLane run if it holds resolved config, a
    ``final/`` dir, or at least one ``NN-StepName`` step dir."""
    if (d / "resolved.json").is_file() or (d / "config.json").is_file():
        return True
    if (d / "final").is_dir():
        return True
    for entry in d.iterdir():
        if entry.is_dir():
            prefix, sep, _ = entry.name.partition("-")
            if prefix.isdigit() and sep:
                return True
    return False


def adopt_run(src_run_dir: str | Path, design_dir: str | Path) -> Dict[str, Any]:
    """Copy an existing LibreLane run dir into ``<design>/runs/`` so LanEx can
    view it (E1, mode 1). Copies (never symlinks) so the import survives deletion
    of the source. Returns ``{"tag": <adopted tag>}``.

    Raises FileNotFoundError if the source is missing and ValueError if it does
    not look like a run or would escape the design's ``runs/`` dir.
    """
    src = Path(src_run_dir).expanduser().resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"not a directory: {src}")
    if not _looks_like_run(src):
        raise ValueError(
            "that folder is not a LibreLane run (no resolved.json / final/ / NN-Step dir)"
        )
    runs_root = (Path(design_dir).resolve() / "runs")
    runs_root.mkdir(parents=True, exist_ok=True)
    # Refuse to adopt a dir that already lives under this design's runs/.
    try:
        src.relative_to(runs_root)
        raise ValueError("that run already lives under this design — it's in the list")
    except ValueError as ex:
        if "already lives under" in str(ex):
            raise

    base = src.name or "imported-run"
    tag = f"{base}-imported"
    dest = runs_root / tag
    n = 2
    while dest.exists():
        tag = f"{base}-imported-{n}"
        dest = runs_root / tag
        n += 1
    # Confinement: the resolved destination must stay directly under runs/.
    if dest.resolve().parent != runs_root.resolve():
        raise ValueError("refusing to write outside the design's runs/ directory")
    shutil.copytree(src, dest)
    try:
        (dest / _IMPORT_MARKER).write_text(
            json.dumps(
                {"source": str(src), "imported_at": datetime.now().isoformat()},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    return {"tag": tag, "run_dir": str(dest)}


def read_note(run_dir: str | Path) -> str:
    p = Path(run_dir) / _NOTE_FILE
    if not p.is_file():
        return ""
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:_NOTE_MAX]
    except Exception:
        return ""


def write_note(run_dir: str | Path, text: str) -> Dict[str, Any]:
    rd = Path(run_dir)
    if not rd.is_dir():
        return {"ok": False, "error": "run not found"}
    text = (text or "")[:_NOTE_MAX]
    try:
        p = rd / _NOTE_FILE
        if text.strip():
            p.write_text(text, encoding="utf-8")
        elif p.is_file():
            p.unlink()  # empty note → remove the file
        return {"ok": True, "note": text}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}


# --------------------------------------------------------------------------
# Metric trends — how key metrics moved across a design's runs over time, so a
# regression is visible at a glance (no manual run-pair picking). Reuses the
# existing run walk + metric load; pure, no new dependency.
# --------------------------------------------------------------------------

# Curated default trend metrics (all verified-real LibreLane metric names).
TREND_METRICS = [
    "timing__setup__ws",
    "timing__hold__ws",
    "design__instance__area",
    "design__instance__count",
    "power__total",
    "route__wirelength",
    "route__drc_errors",
]


def metric_trends(design_dir: str | Path, keys: Optional[List[str]] = None,
                  *, limit: int = 30) -> Dict[str, Any]:
    """Per-metric series across a design's runs, oldest→newest (for line charts).

    Returns ``{ok, runs:[{tag, started_at, success}], series:{metric:[v,…]}}``
    where each series is aligned to ``runs``. Non-finite values pass through as-is
    (stringified at the JSON boundary). Capped to the most recent ``limit`` runs.
    """
    design_dir = Path(design_dir).resolve()
    run_dirs = _walk_runs(design_dir)[:max(1, limit)]
    run_dirs = list(reversed(run_dirs))  # oldest first for a left-to-right trend
    use_keys = keys or TREND_METRICS
    runs_meta: List[Dict[str, Any]] = []
    series: Dict[str, List[Any]] = {k: [] for k in use_keys}
    for rd in run_dirs:
        try:
            metrics = _load_metrics(rd)
        except Exception:
            metrics = {}
        runs_meta.append({
            "tag": rd.name,
            "started_at": datetime.fromtimestamp(rd.stat().st_mtime).isoformat(),
            "success": _success_from_metrics(metrics, run_dir=rd),
        })
        for k in use_keys:
            v = metrics.get(k)
            series[k].append(v if isinstance(v, (int, float)) else None)
    # Drop series that are entirely empty so the chart only offers real metrics.
    series = {k: v for k, v in series.items() if any(x is not None for x in v)}
    return {"ok": True, "runs": runs_meta, "series": series, "keys": list(series.keys())}


def diff_runs(run_dir_a: str | Path, run_dir_b: str | Path) -> Dict[str, Any]:
    """Diff two runs by metrics."""
    a = get_run(Path(run_dir_a).resolve())
    b = get_run(Path(run_dir_b).resolve())
    am = (a.get("metrics") or {}).get("values") or {}
    bm = (b.get("metrics") or {}).get("values") or {}
    keys = sorted(set(am) | set(bm))
    deltas: Dict[str, Dict[str, Any]] = {}
    for k in keys:
        av = am.get(k)
        bv = bm.get(k)
        if av == bv:
            continue
        deltas[k] = {"from": av, "to": bv}
    return {
        "from": {"tag": a.get("tag"), "run_dir": a.get("run_dir")},
        "to": {"tag": b.get("tag"), "run_dir": b.get("run_dir")},
        "metric_deltas": deltas,
    }
