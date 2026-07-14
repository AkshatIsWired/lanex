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
"""Parse OpenSTA ``report_checks`` output into structured timing paths.

The single most-requested "switch from CLI to GUI" feature is being able to *see*
timing closure: the worst paths, their slack, and the slack distribution — not
just the scalar ``timing__setup__ws``. LibreLane already writes these reports as
part of every STA step (``openroad -path_delay max/min`` →
``<run>/<NN-OpenROAD-STA…>/max.rpt`` for setup, ``min.rpt`` for hold), so this is
pure parsing of existing run output: **no new dependency, no new LibreLane API,
no extra tool run.** Cross-platform (text + ``pathlib`` only).

Report shape (real sky130 output)::

    ======================= nom_tt_025C_1v80 Corner ====================
    Startpoint: y (input port clocked by clk)
    Endpoint: _419_ (rising edge-triggered flip-flop clocked by clk)
    Path Group: clk
    Path Type: max
    Fanout  Cap  Slew  Delay  Time  Description
    ... (the path rows) ...
                       9.995111   data required time
                      -3.960954   data arrival time
    -------------------------------------------------------------------
                       6.034157   slack (MET)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Time unit for slack/arrival numbers. OpenSTA reports are unitless — the value
# is in the liberty's ``time_unit``, which is **1 ns** for every PDK LanEx
# supports (sky130, gf180, ihp). We surface this ONE constant (never hardcode
# "ns" in the frontend) so the label always tracks a single source of truth; if
# a ps-unit PDK is ever added, change it here (or source it per-run) and every
# display follows. A ps liberty shown as ns would misstate slack ×1000 (Fear G),
# so ``test_supported_pdks_use_ns_time_unit`` canaries the assumption.
TIME_UNIT = "ns"

# A very large magnitude OpenSTA prints for "no path" slacks (e.g. 1e30); treat
# as "no real path" rather than a meaningful number.
_SENTINEL = 1e29

_CORNER_RE = re.compile(r"^=+\s*(\S+)\s+Corner\s*=+\s*$")
_NUM = r"(-?\d+(?:\.\d+)?)"
_SLACK_RE = re.compile(r"^\s*" + _NUM + r"\s+slack\s+\((MET|VIOLATED)\)")
_ARRIVAL_RE = re.compile(r"^\s*" + _NUM + r"\s+data arrival time\s*$")
_REQUIRED_RE = re.compile(r"^\s*" + _NUM + r"\s+data required time\s*$")
_PATH_MAX_LINES = 400  # cap stored path text so a pathological report can't bloat


def _after(label: str, line: str) -> str:
    """``'Startpoint: y (input ...)'`` → ``'y'`` (drop the parenthetical)."""
    rest = line.split(label, 1)[1].strip()
    return rest.split("(", 1)[0].strip()


def parse_report_checks(text: str) -> List[Dict[str, Any]]:
    """Parse every ``report_checks`` path block in *text*.

    Returns a list of ``{startpoint, endpoint, group, type, corner, slack, met,
    arrival, required, path_text}``. Robust to missing fields (any may be None).
    """
    lines = text.splitlines()
    paths: List[Dict[str, Any]] = []
    corner: Optional[str] = None
    cur: Optional[Dict[str, Any]] = None
    buf: List[str] = []

    def _flush() -> None:
        nonlocal cur, buf
        if cur is not None:
            cur["path_text"] = "\n".join(buf[:_PATH_MAX_LINES])
            paths.append(cur)
        cur = None
        buf = []

    for line in lines:
        m = _CORNER_RE.match(line)
        if m:
            corner = m.group(1)
            continue
        if line.startswith("Startpoint:"):
            _flush()
            cur = {
                "startpoint": _after("Startpoint:", line),
                "endpoint": None, "group": None, "type": None,
                "corner": corner, "slack": None, "met": None,
                "arrival": None, "required": None, "path_text": "",
            }
            buf = [line]
            continue
        if cur is None:
            continue
        buf.append(line)
        if line.startswith("Endpoint:"):
            cur["endpoint"] = _after("Endpoint:", line)
        elif line.startswith("Path Group:"):
            cur["group"] = line.split(":", 1)[1].strip()
        elif line.startswith("Path Type:"):
            cur["type"] = line.split(":", 1)[1].strip()
        else:
            ma = _ARRIVAL_RE.match(line)
            if ma:
                cur["arrival"] = float(ma.group(1))
                continue
            mr = _REQUIRED_RE.match(line)
            if mr:
                cur["required"] = float(mr.group(1))
                continue
            ms = _SLACK_RE.match(line)
            if ms:
                cur["slack"] = float(ms.group(1))
                cur["met"] = (ms.group(2) == "MET")
                _flush()  # slack line ends the block
    _flush()
    return paths


def _sta_dirs(run_dir: Path) -> List[Path]:
    """STA step dirs under a run, sorted by their numeric ordinal prefix."""
    out: List[Tuple[int, Path]] = []
    for entry in run_dir.iterdir():
        if not entry.is_dir():
            continue
        prefix, _, rest = entry.name.partition("-")
        if not prefix.isdigit():
            continue
        if "sta" in rest.lower():
            out.append((int(prefix), entry))
    out.sort(key=lambda t: t[0])
    return [p for _, p in out]


# Setup paths come from the ``-path_delay max`` report, hold from ``min``.
_REPORT_FOR = {"setup": "max.rpt", "hold": "min.rpt"}


def _pick_reports(run_dir: Path, kind: str) -> Tuple[List[Tuple[Path, Optional[str]]], Optional[Path]]:
    """All report files for *kind* from the most-final STA step.

    Multi-corner STA steps (``OpenROAD.STAPostPNR``) write one report per
    corner in per-corner SUBDIRS (``55-openroad-stapostpnr/max_ss_100C_1v60/
    max.rpt``); single-corner mid-PnR steps write a top-level ``max.rpt``.
    Only checking the top level silently skipped the final signoff STA and fell
    back to a mid-PnR report — pre-route numbers presented as if final (a run
    failing setup in its slow corner showed MET). So: for each STA dir in
    finality order, take the top-level report OR every per-corner one; the
    subdir name rides along as the corner label (per-corner files have no
    corner banner for the parser to find).

    Returns ``([(report_file, corner_hint), …], step_dir)``.
    """
    fname = _REPORT_FOR.get(kind, "max.rpt")
    dirs = _sta_dirs(run_dir)
    post = [d for d in dirs if "post" in d.name.lower()]
    ordered = (post[::-1] + dirs[::-1]) if post else dirs[::-1]
    for d in ordered:
        f = d / fname
        if f.is_file():
            return [(f, None)], d
        corner_files: List[Tuple[Path, Optional[str]]] = []
        try:
            for sub in sorted(d.iterdir(), key=lambda p: p.name):
                cf = sub / fname
                if sub.is_dir() and cf.is_file():
                    corner_files.append((cf, sub.name))
        except OSError:
            continue
        if corner_files:
            return corner_files, d
    return [], None


def _histogram(slacks: List[float], bins: int = 12) -> Dict[str, Any]:
    """Bucket slack values into a small histogram for a bar chart."""
    vals = [s for s in slacks if s is not None and abs(s) < _SENTINEL]
    if not vals:
        return {"bins": [], "counts": [], "edges": []}
    lo, hi = min(vals), max(vals)
    if lo == hi:
        return {"bins": [f"{lo:.3f}"], "counts": [len(vals)], "edges": [lo, hi]}
    width = (hi - lo) / bins
    counts = [0] * bins
    edges = [lo + i * width for i in range(bins + 1)]
    for v in vals:
        idx = int((v - lo) / width)
        if idx >= bins:
            idx = bins - 1
        counts[idx] += 1
    labels = [f"{edges[i]:.3f}" for i in range(bins)]
    return {"bins": labels, "counts": counts, "edges": edges}


def timing_paths(run_dir: str | Path, *, kind: str = "setup", limit: int = 100) -> Dict[str, Any]:
    """Structured timing paths for the worst-paths table + slack histogram.

    ``kind`` ∈ {setup, hold}. Returns ``{ok, kind, source, corner(s), total,
    violating, worst_slack, paths[], histogram}``. ``paths`` are sorted
    worst-slack-first and capped to ``limit``. Degrades to ``{ok: False, …}`` when
    no STA report is present (e.g. a partial run), so the UI shows an honest
    empty state instead of an error.
    """
    run_dir = Path(run_dir)
    if kind not in _REPORT_FOR:
        kind = "setup"
    reports, step_dir = _pick_reports(run_dir, kind)
    if not reports:
        return {"ok": False, "kind": kind,
                "error": f"no {kind} timing report (run an STA step / complete the flow first)"}
    paths: List[Dict[str, Any]] = []
    sources: List[str] = []
    for report, corner_hint in reports:
        try:
            text = report.read_text(encoding="utf-8", errors="replace")
        except Exception as ex:
            if len(reports) == 1:
                return {"ok": False, "kind": kind, "error": str(ex)}
            continue
        parsed = parse_report_checks(text)
        if corner_hint:
            for p in parsed:
                if not p.get("corner"):
                    p["corner"] = corner_hint
        paths.extend(parsed)
        try:
            sources.append(str(report.relative_to(run_dir)))
        except Exception:
            sources.append(report.name)
    if not paths and not sources:
        return {"ok": False, "kind": kind,
                "error": f"no readable {kind} timing report in {step_dir.name if step_dir else 'run'}"}
    # Drop sentinel-slack "no real path" blocks from the table/stats.
    real = [p for p in paths if p.get("slack") is not None and abs(p["slack"]) < _SENTINEL]
    real.sort(key=lambda p: p["slack"])  # worst (most negative) first
    violating = sum(1 for p in real if p.get("met") is False)
    worst = real[0]["slack"] if real else None
    corners = sorted({p["corner"] for p in real if p.get("corner")})
    step_name = step_dir.name if step_dir is not None else ""
    fname = _REPORT_FOR[kind]
    source = sources[0] if len(sources) == 1 else f"{step_name}/*/{fname} ({len(sources)} corners)"
    return {
        "ok": True,
        "kind": kind,
        "source": source,
        "sources": sources,
        "step": step_name,
        "corners": corners,
        "total": len(real),
        "violating": violating,
        "worst_slack": worst,
        "unit": TIME_UNIT,
        "paths": real[:max(1, limit)],
        "histogram": _histogram([p["slack"] for p in real]),
    }
