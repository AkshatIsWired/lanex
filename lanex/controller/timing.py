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


# ---------------------------------------------------------------- where it failed
# LibreLane times the design several times (Classic, 3.0.4): before placement
# (STAPrePNR: ideal clocks, no wires, every STA corner), during place and route
# (STAMidPNR, four times, the default corner only) and after routing
# (STAPostPNR: every corner, with extracted parasitics). A corner a step didn't
# time keeps the value an earlier step left in the metrics (LibreLane issue
# #1040), so each step is read only for the corners it actually timed: the
# banners in its max.rpt, or its per-corner folders.

_STA_STEPS = ("OpenROAD.STAPrePNR", "OpenROAD.STAMidPNR", "OpenROAD.STAPostPNR")
_AFTER = {  # the step before each STA, in plain words
    "OpenROAD.STAPrePNR": "before placement",
    "OpenROAD.GlobalPlacement": "after global placement",
    "OpenROAD.RepairDesignPostGPL": "after placement",
    "OpenROAD.DetailedPlacement": "after placement",
    "OpenROAD.CTS": "after clock tree synthesis",
    "OpenROAD.ResizerTimingPostCTS": "after timing repair",
    "OpenROAD.GlobalRouting": "after global routing",
    "OpenROAD.CheckAntennas": "after global routing",
    "OpenROAD.RepairAntennas": "after global routing",
    "OpenROAD.ResizerTimingPostGRT": "after global routing",
    "OpenROAD.STAPostPNR": "after routing",
}
_VIO_RE = re.compile(r"^\[(setup|hold) (in|reg)-(reg|out)\]")


def _base_id(sid: Optional[str]) -> str:
    return re.sub(r"-\d+$", "", sid or "")


def _corners_timed(d: Path) -> List[str]:
    subs = sorted(p.name for p in d.iterdir() if p.is_dir() and (p / "max.rpt").is_file()) if d.is_dir() else []
    if subs:
        return subs
    rpt = d / "max.rpt"
    if not rpt.is_file():
        return []
    seen: List[str] = []
    with rpt.open("r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            m = _CORNER_RE.match(line)
            if m and m.group(1) not in seen:
                seen.append(m.group(1))
            if i > 4000:
                break
    return seen


def _violators(path: Path) -> Dict[str, Dict[str, int]]:
    """``violator_list.rpt``: LibreLane's own split of every failing endpoint
    into in-reg / reg-reg / reg-out / in-out, for setup and hold."""
    out: Dict[str, Dict[str, int]] = {"setup": {}, "hold": {}}
    if not path.is_file():
        return out
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _VIO_RE.match(line)
            if m:
                k = m.group(2) + "-" + m.group(3)
                out[m.group(1)][k] = out[m.group(1)].get(k, 0) + 1
    return out


def sta_history(run_dir: str | Path) -> List[Dict[str, Any]]:
    """Each timing analysis of the run in flow order (a resumed run's earlier
    ones come from its parent): ``[{id, dir, run, when, signoff, corners:
    {corner: {setup_ws, setup_tns, setup_vio, hold_ws, hold_tns, hold_vio,
    kinds}}}]``, values from the step's own ``state_out.json`` for the corners
    it timed, ``kinds`` from its violator lists."""
    import json as _json

    from . import history
    out: List[Dict[str, Any]] = []
    prev_id = None
    for s in history.lineage_steps(run_dir):
        sid = s["id"] or ""
        base = _base_id(sid)
        if base in _STA_STEPS and (s["path"] / "state_out.json").is_file():
            try:
                metrics = _json.loads((s["path"] / "state_out.json").read_text(encoding="utf-8")).get("metrics") or {}
            except Exception:
                metrics = {}
            corners: Dict[str, Any] = {}
            for c in _corners_timed(s["path"]):
                def g(k: str) -> Any:
                    return metrics.get(k + "__corner:" + c)
                vdir = s["path"] / c if (s["path"] / c).is_dir() else s["path"]
                corners[c] = {
                    "setup_ws": g("timing__setup__ws"), "setup_tns": g("timing__setup__tns"),
                    "setup_vio": g("timing__setup_vio__count"),
                    "hold_ws": g("timing__hold__ws"), "hold_tns": g("timing__hold__tns"),
                    "hold_vio": g("timing__hold_vio__count"),
                    "kinds": _violators(vdir / "violator_list.rpt"),
                }
            if base in ("OpenROAD.STAPrePNR", "OpenROAD.STAPostPNR"):
                when = _AFTER[base]
            else:
                pb = _base_id(prev_id)
                when = _AFTER.get(pb, "after " + (pb.split(".")[-1] or "the step before"))
            out.append({"id": sid, "dir": s["dir"], "run": s["run"], "path": str(s["path"]), "when": when,
                        "signoff": base == "OpenROAD.STAPostPNR", "ideal_clocks": base == "OpenROAD.STAPrePNR",
                        "corners": corners})
        # Name an STA by the step that changed the design before it, not by
        # the checks and bookkeeping in between.
        if base not in _STA_STEPS and not sid.startswith(("Checker.", "Odb.")):
            prev_id = sid
    return out


# ---------------------------------------------------------------- one path's budget
_ROW_RE = re.compile(r"^\s*((?:-?\d+(?:\.\d+)?(?:e-?\d+)?\s+)*)([\^v]\s+)?(.*?)\s*$")


def path_budget(path_text: str) -> Optional[Dict[str, Any]]:
    """Where the time of one setup path goes, from its ``report_checks`` rows
    (``-fields {slew cap input net fanout} -format full_clock_expanded``, as
    LibreLane writes them). Driver pins carry five numbers (fanout, cap, slew,
    delay, time) and their delay is the cell's; load pins carry three and
    their delay is the wire's. Returns ``{period, launch, capture, io_in,
    io_out, drive, clk_q, cells, wires, setup, uncertainty, crpr, levels,
    fanout: {pin, n, delay}, start, end, arrival, required, slack}`` in ns, or
    None when the text isn't a whole path."""
    lines = path_text.splitlines()
    start = next((ln for ln in lines[:6] if ln.startswith("Startpoint:")), None)
    end = next((ln for ln in lines[:6] if ln.startswith("Endpoint:")), "")
    if start is None:
        return None
    start_in = "input port" in start
    start_name = _after("Startpoint:", start)
    b: Dict[str, Any] = {
        "period": None, "launch": 0.0, "capture": 0.0, "io_in": 0.0, "io_out": 0.0, "drive": 0.0,
        "clk_q": 0.0, "cells": 0.0, "wires": 0.0, "setup": 0.0, "uncertainty": 0.0, "crpr": 0.0,
        "levels": 0, "fanout": None, "start": "in" if start_in else "reg",
        "end": "out" if "output port" in end else "reg", "arrival": None, "required": None, "slack": None}
    edges: List[float] = []
    required = False          # past "data arrival time"
    started = start_in        # past the start register's clock pin
    seen_driver = False

    def rel(nums: List[float]) -> float:
        return nums[-2] if len(nums) >= 2 else 0.0

    for ln in lines:
        s = ln.strip()
        if not s or s.startswith(("Startpoint", "Endpoint", "Path ", "Fanout", "---")):
            continue
        m = _ROW_RE.match(ln)
        nums = [float(x) for x in m.group(1).split()] if m and m.group(1) else []
        desc = m.group(3) if m else s
        if desc.startswith("data arrival time"):
            if b["arrival"] is None and nums:   # the summary repeats it, negated
                b["arrival"] = nums[-1]
            required = True
        elif desc.startswith("data required time"):
            if b["required"] is None and nums:
                b["required"] = nums[-1]
        elif desc.startswith("slack"):
            b["slack"] = nums[-1] if nums else None
            break
        elif desc.startswith("clock ") and "edge)" in desc:
            if nums:
                edges.append(nums[-1])
        elif desc.startswith(("clock network delay", "clock source latency")):
            b["capture" if required else "launch"] += rel(nums)
        elif desc.startswith("input external delay"):
            b["io_in"] += rel(nums)
        elif desc.startswith("output external delay"):
            b["io_out"] -= rel(nums)
        elif desc.startswith("clock uncertainty"):
            b["uncertainty"] -= rel(nums)
        elif desc.startswith("clock reconvergence pessimism"):
            b["crpr"] += rel(nums)
        elif desc.startswith("library setup time"):
            b["setup"] -= rel(nums)
        elif m and m.group(2) and not desc.endswith("(net)"):
            driver = len(nums) >= 5
            delay = rel(nums)
            pin = desc.split(" (")[0]
            if required:
                b["capture"] += delay          # the capture clock's tree
            elif not started:
                b["launch"] += delay           # the launch clock's tree, up to the register
                if pin.startswith(start_name + "/"):
                    started = True
            elif driver:
                if desc.endswith("(in)"):
                    b["drive"] += delay        # the input port's driver
                elif not seen_driver and not start_in:
                    b["clk_q"] += delay        # the start register, clock to Q
                else:
                    b["cells"] += delay
                    b["levels"] += 1
                seen_driver = True
                n_out = int(nums[0])
                if b["fanout"] is None or n_out > b["fanout"]["n"]:
                    b["fanout"] = {"pin": pin, "n": n_out, "delay": round(delay, 4)}
            else:
                b["wires"] += delay
    if len(edges) >= 2:
        b["period"] = round(edges[1] - edges[0], 6)
    for k in ("launch", "capture", "io_in", "io_out", "drive", "clk_q", "cells", "wires", "setup", "uncertainty", "crpr"):
        b[k] = round(b[k], 6)
    return b if b["slack"] is not None else None


def worst_setup_path(run_dir: str | Path, step_dir: str | Path, corner: Optional[str]) -> Optional[Dict[str, Any]]:
    """The worst setup path one STA step reported in *corner*, with its budget."""
    d = Path(step_dir)
    f = d / corner / "max.rpt" if corner and (d / corner / "max.rpt").is_file() else d / "max.rpt"
    if not f.is_file():
        return None
    try:
        with f.open("r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(3_000_000)
    except Exception:
        return None
    paths = [p for p in parse_report_checks(text) if p.get("slack") is not None and abs(p["slack"]) < _SENTINEL
             and (not corner or p.get("corner") in (None, corner))]
    if not paths:
        return None
    p = min(paths, key=lambda x: x["slack"])
    out = {k: p.get(k) for k in ("startpoint", "endpoint", "slack")}
    out["corner"] = p.get("corner") or corner
    out["budget"] = path_budget(p.get("path_text") or "")
    try:
        out["report"] = f.relative_to(Path(run_dir)).as_posix()
    except Exception:
        out["report"] = None
    return out
