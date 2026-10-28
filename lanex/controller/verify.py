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
"""Verification Center: the signoff checks a LibreLane run already made.

Every check here is one of LibreLane's own ``Checker.*`` steps (or, where
LibreLane has no checker, a metric its manufacturability report or STA
writes), judged the way LibreLane judges it:

* the same metric and threshold as the checker class (``steps/checker.py``),
* the same ``ERROR_ON_*`` switch deciding error vs. warning, read from the
  run's ``resolved.json`` (LibreLane's defaults when a key is absent),
* the same corner wildcards for setup/hold/slew/cap (``TIMING_VIOLATION_CORNERS``
  and friends, matched with ``fnmatch`` like ``librelane.common.Filter``),
* the same ``RUN_*`` gates that skip a step in the Classic flow.

The checker step's own outcome is read too: a checker dir with
``state_out.json`` finished; one with only ``state_in.json`` raised (a deferred
error, or the flow stopped there). If that disagrees with the metric, the
step's outcome wins and the disagreement is reported, never hidden.

Nothing is re-run. The report files each tool wrote (KLayout/Magic report
databases, the Netgen JSON, the XOR database, the antenna and IR-drop
reports) are summarised so the page can show *which* rule failed and where.
Pure stdlib.
"""
from __future__ import annotations

import fnmatch
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import history

_PASS, _FAIL, _WARN, _INFO = "pass", "fail", "warn", "info"
_SKIPPED, _NOT_RUN = "skipped", "not_run"
# Kept for callers of the old API: "absent" meant "no data".
_ABSENT = "absent"

# LibreLane 3 defaults for the switches a run's resolved.json may omit
# (steps/checker.py and flows/classic.py).
_DEFAULTS: Dict[str, Any] = {
    "ERROR_ON_LINTER_ERRORS": True,
    "ERROR_ON_LINTER_WARNINGS": False,
    "ERROR_ON_LINTER_TIMING_CONSTRUCTS": True,
    "ERROR_ON_UNMAPPED_CELLS": True,
    "ERROR_ON_SYNTH_CHECKS": True,
    "ERROR_ON_NL_ASSIGN_STATEMENTS": True,
    "ERROR_ON_PDN_VIOLATIONS": True,
    "ERROR_ON_TR_DRC": True,
    "ERROR_ON_DISCONNECTED_PINS": True,
    "ERROR_ON_LONG_WIRE": True,
    "ERROR_ON_XOR_ERROR": True,
    "ERROR_ON_MAGIC_DRC": True,
    "ERROR_ON_KLAYOUT_DRC": True,
    "ERROR_ON_ILLEGAL_OVERLAPS": True,
    "ERROR_ON_LVS_ERROR": True,
    "ERROR_ON_KLAYOUT_DENSITY": True,
    "ERROR_ON_KLAYOUT_ANTENNA": True,
    "RUN_LINTER": True,
    "RUN_EQY": False,
    "RUN_DRT": True,
    "RUN_MCSTA": True,
    "RUN_IRDROP_REPORT": True,
    "RUN_LVS": True,
    "RUN_MAGIC_STREAMOUT": True,
    "RUN_KLAYOUT_STREAMOUT": True,
    "RUN_KLAYOUT_XOR": True,
    "RUN_MAGIC_DRC": True,
    "RUN_KLAYOUT_DRC": True,
    "RUN_ANTENNA_REPAIR": True,
    "HOLD_VIOLATION_CORNERS": ["*"],
    "MAX_SLEW_VIOLATION_CORNERS": [""],
    "MAX_CAP_VIOLATION_CORNERS": [""],
}

# Report-database summaries are capped so a run with a million markers
# cannot stall the request; counts stay exact, samples are truncated.
_MAX_CATEGORIES = 60
_MAX_SAMPLES = 6


# ---------------------------------------------------------------- small helpers
def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _finite(v: Any) -> Optional[float]:
    n = _num(v)
    return n if n is not None and math.isfinite(n) else None


def _read_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _rel(run: Path, p: Optional[Path]) -> Optional[str]:
    if p is None:
        return None
    try:
        return p.relative_to(run).as_posix()
    except Exception:
        return None


def _corner_of(key: str) -> Optional[str]:
    """``…__corner:nom_tt_025C_1v80`` -> ``nom_tt_025C_1v80`` (METRICS2.1)."""
    parts = key.split("__")
    while parts and ":" in parts[-1]:
        k, v = parts.pop().split(":", 1)
        if k == "corner":
            return v
    return None


def _by_corner(metrics: Dict[str, Any], base: str) -> Dict[str, Any]:
    pre = base + "__corner:"
    return {k[len(pre):]: v for k, v in metrics.items() if k.startswith(pre)}


def _by_mod(metrics: Dict[str, Any], base: str, mod: str) -> Dict[str, Any]:
    pre = base + "__" + mod + ":"
    return {k[len(pre):]: v for k, v in metrics.items() if k.startswith(pre)}


class _Run:
    """One run directory: config, metrics and its step dirs, read once."""

    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.cfg = history._read_config(run_dir)
        self.has_cfg = bool(self.cfg)
        self.metrics = history._load_metrics(run_dir)
        self.completed = history._completed(run_dir)
        # A resumed run stands on the steps it took from its parent: their
        # checks (lint, synthesis…) are this run's too. ``run`` names the run
        # whose folder holds each step.
        steps: List[Dict[str, Any]] = []
        for s in history.lineage_steps(run_dir):
            e = s["path"]
            if (e / "state_out.json").is_file():
                status = "done"
            elif (e / "state_in.json").is_file():
                status = "stopped"
            else:
                status = "unknown"
            steps.append({"n": int(e.name.split("-", 1)[0]), "dir": e.name,
                          "id": s["id"], "status": status, "path": e,
                          "run": s["run"] if s["run"] != run_dir.name else None})
        self.steps = steps
        self.branch = history.branch_of(run_dir)
        # A run that stopped has no final/metrics.json, but every finished
        # step saved the metrics as of that point: use the last one, and say so.
        self.metrics_from: Optional[Dict[str, Any]] = None
        if not self.metrics:
            for st in reversed(steps):
                if st["status"] != "done":
                    continue
                doc = _read_json(st["path"] / "state_out.json")
                if isinstance(doc, dict) and isinstance(doc.get("metrics"), dict) and doc["metrics"]:
                    self.metrics = doc["metrics"]
                    self.metrics_from = {"n": st["n"], "dir": st["dir"], "id": st["id"]}
                    break
        gui = _read_json(run_dir / "gui-run.json")
        self.gui = gui if isinstance(gui, dict) else {}

    def conf(self, name: str) -> Any:
        if name in self.cfg:
            return self.cfg[name]
        return _DEFAULTS.get(name)

    def step(self, step_id: str) -> Optional[Dict[str, Any]]:
        """The LAST dir of a step (a re-run appends a new one)."""
        want = step_id.lower().replace(".", "-")
        hit = None
        for s in self.steps:
            if s["id"]:
                # flow.log names a repeated step "<Id>-1", "<Id>-2"…
                if s["id"] == step_id or re.sub(r"-\d+$", "", s["id"]) == step_id:
                    hit = s
                continue
            suffix = s["dir"].split("-", 1)[1] if "-" in s["dir"] else ""
            # A repeated step gets "-1", "-2"… appended to its dir name.
            base = re.sub(r"-\d+$", "", suffix)
            if suffix.lower() == want or base.lower() == want:
                hit = s
        return hit

    def file(self, step_id: str, *globs: str) -> Optional[Path]:
        s = self.step(step_id)
        if s is None:
            return None
        for g in globs:
            hits = sorted(p for p in s["path"].glob(g) if p.is_file())
            if hits:
                return hits[0]
        return None


# ---------------------------------------------------------------- check records
def _rec(cid: str, group: str, name: str, **kw: Any) -> Dict[str, Any]:
    r = {
        "id": cid, "group": group, "name": name,
        "status": _NOT_RUN,
        # blocks: an error stops LibreLane (or fails its manufacturability
        # report); warns: LibreLane only warns; info: LibreLane does not check it.
        "gate": "blocks",
        "gate_note": "",
        "value": None, "unit": "", "limit": "",
        "metric": None, "metric_keys": [], "values": {},
        "checker": None, "tool": None, "rerun": None,
        "reports": [], "corners": [], "breakdown": [],
        "note": "", "detail": "",
        "step_id": None,
    }
    r.update(kw)
    return r


def _step_ref(run: _Run, step_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not step_id:
        return None
    s = run.step(step_id)
    if s is None:
        return {"id": step_id, "dir": None, "n": None, "status": "absent"}
    ref = {"id": step_id, "dir": s["dir"], "n": s["n"], "status": s["status"]}
    if s.get("run"):
        ref["run"] = s["run"]      # taken from the run this one was resumed from
    return ref


def _gated(run: _Run, gates: Iterable[str]) -> Optional[str]:
    for g in gates:
        if run.has_cfg and run.conf(g) is False:
            return g
    return None


def _no_data_reason(run: _Run, checker_ref: Optional[Dict[str, Any]],
                    tool_ref: Optional[Dict[str, Any]]) -> str:
    stopped = next((s for s in run.steps if s["status"] == "stopped"), None)
    if not run.completed and stopped is not None:
        return (f"Not reached: the flow stopped at step {stopped['n']} "
                f"({stopped['id'] or stopped['dir']}) before this check.")
    if tool_ref and tool_ref.get("status") == "absent" and checker_ref and checker_ref.get("status") == "absent":
        return "This flow did not run the step that produces this check."
    return "No value recorded in this run's metrics."


def _apply_checker_outcome(rec: Dict[str, Any], exceeded: bool, error_on: bool) -> None:
    """Fold the checker step's real outcome into the record."""
    ck = rec.get("checker")
    if not ck or ck.get("status") == "absent":
        return
    if ck["status"] == "done":
        ck["outcome"] = "warned" if (exceeded and not error_on) else "passed"
        if exceeded and error_on:
            # The checker saw a clean value; the metric changed after (re-run).
            rec["note"] = ("LibreLane's checker passed when it ran, but the value has changed since "
                           "(a step was probably re-run afterwards). Re-run the flow to confirm.")
    elif ck["status"] == "stopped":
        ck["outcome"] = "raised"
        if rec["status"] in (_PASS, _WARN, _INFO):
            rec["status"] = _FAIL
            rec["gate"] = "blocks"
            rec["note"] = ("LibreLane's checker stopped with an error in this run even though the value "
                           "now reads clean (a step was probably re-run afterwards). Re-run the flow to confirm.")


def _metric_checker(run: _Run, rec: Dict[str, Any], *, metric: str, error_var: Optional[str],
                    checker: str, tool: Optional[str], gates: Iterable[str] = (),
                    threshold: float = 0.0, always_error: bool = False,
                    rerun: bool = True) -> Dict[str, Any]:
    """LibreLane's MetricChecker: value > threshold -> error (or a warning when
    the ``ERROR_ON_*`` switch is off). Missing metric -> the checker warns and
    passes; here it is "no data"."""
    rec["metric"] = metric
    rec["metric_keys"] = [metric]
    rec["checker"] = _step_ref(run, checker)
    rec["tool"] = _step_ref(run, tool)
    rec["step_id"] = tool or checker
    # Only steps whose re-run stands alone are offered (a lone synthesis
    # re-run would leave every later step stale).
    rec["rerun"] = tool if rerun else None
    error_on = True if always_error else bool(run.conf(error_var)) if error_var else True
    rec["limit"] = "0" if threshold == 0 else f"≤ {threshold:g}"
    # The resolved.json variable that decides error vs. warning, so the page
    # can open that line (provenance kind "var").
    rec["error_var"] = error_var
    if error_var:
        rec["gate_note"] = f"{error_var} = {'true' if error_on else 'false'}"
    elif always_error:
        rec["gate_note"] = "always an error in LibreLane"
    g = _gated(run, gates)
    v = run.metrics.get(metric)
    n = _num(v)
    if v is not None:
        rec["values"] = {metric: v}
        rec["value"] = v
    if g:
        rec["status"] = _SKIPPED
        rec["detail"] = f"Turned off for this run ({g} = false)."
        return rec
    if n is None or not math.isfinite(n):
        rec["status"] = _NOT_RUN
        rec["detail"] = _no_data_reason(run, rec["checker"], rec["tool"])
        ck = rec["checker"]
        if ck and ck.get("status") == "stopped":
            ck["outcome"] = "raised"
            rec["status"] = _FAIL
            rec["detail"] = "LibreLane's checker stopped with an error."
        return rec
    exceeded = n > threshold
    if not exceeded:
        rec["status"] = _PASS
    elif error_on:
        rec["status"] = _FAIL
    else:
        rec["status"] = _WARN
        rec["gate"] = "warns"
    _apply_checker_outcome(rec, exceeded, error_on)
    return rec


def _corner_rule(run: _Run, specific: str) -> Tuple[Optional[List[str]], str]:
    """The wildcards a TimingViolations checker errors on, and the variable
    they came from (``SETUP_VIOLATION_CORNERS`` falls back to
    ``TIMING_VIOLATION_CORNERS``)."""
    w = run.cfg.get(specific) if specific in run.cfg else _DEFAULTS.get(specific)
    src = specific
    if not w:
        w = run.cfg.get("TIMING_VIOLATION_CORNERS")
        src = "TIMING_VIOLATION_CORNERS"
    if w is None:
        return None, src
    return [x for x in w if x != ""], src


def _timing_checker(run: _Run, rec: Dict[str, Any], *, base: str, specific_var: str,
                    checker: str, what: str) -> Dict[str, Any]:
    """LibreLane's TimingViolations: a violation count per corner; corners
    matching the wildcards are errors, the rest only warnings."""
    rec["metric"] = base
    rec["checker"] = _step_ref(run, checker)
    rec["tool"] = _step_ref(run, "OpenROAD.STAPostPNR")
    rec["step_id"] = "OpenROAD.STAPostPNR"
    rec["rerun"] = "OpenROAD.STAPostPNR"
    rec["limit"] = "0"
    per = {c: _finite(v) for c, v in _by_corner(run.metrics, base).items()}
    wild, src = _corner_rule(run, specific_var)
    rec["corner_var"] = src
    rec["corner_wildcards"] = wild
    total = run.metrics.get(base)
    if total is not None:
        rec["values"] = {base: total}
        rec["value"] = total
    rec["metric_keys"] = [base] + [base + "__corner:" + c for c in sorted(per)]
    if wild is None:
        rec["gate_note"] = "corner rule unknown: every corner treated as blocking"
    elif not wild:
        rec["gate_note"] = f"{src} matches no corner, so LibreLane only warns"
    else:
        rec["gate_note"] = f"{src} = {', '.join(wild)}"

    if not per:
        n = _finite(total)
        if n is None:
            rec["status"] = _NOT_RUN
            rec["detail"] = _no_data_reason(run, rec["checker"], rec["tool"])
            ck = rec["checker"]
            if ck and ck.get("status") == "stopped":
                ck["outcome"] = "raised"
                rec["status"] = _FAIL
            return rec
        # Only the all-corner total exists (older or imported runs): the
        # corner split is unknown, so judge conservatively.
        blocking = wild is None or bool(wild)
        rec["status"] = _PASS if n == 0 else (_FAIL if blocking else _WARN)
        if n and not blocking:
            rec["gate"] = "warns"
        rec["note"] = "This run recorded only the all-corner total, not each corner."
        _apply_checker_outcome(rec, n > 0, blocking)
        return rec

    unmatched: List[str] = []
    if wild:
        for w in wild:
            if not any(fnmatch.fnmatchcase(c, w) for c in per):
                unmatched.append(w)
    err_corners, warn_corners = [], []
    for c, v in sorted(per.items()):
        gating = True if wild is None else any(fnmatch.fnmatchcase(c, w) for w in wild)
        rec["corners"].append({"corner": c, "value": v, "gating": gating})
        if v is not None and v > 0:
            (err_corners if gating else warn_corners).append(c)
    if err_corners or unmatched:
        rec["status"] = _FAIL
    elif warn_corners:
        rec["status"] = _WARN
        rec["gate"] = "warns"
    else:
        rec["status"] = _PASS
    if unmatched:
        rec["detail"] = (f"{src} has wildcards that match no analysed corner ({', '.join(unmatched)}); "
                         "LibreLane raises an error for that.")
    elif err_corners:
        rec["detail"] = f"{what} in blocking corners: {', '.join(err_corners)}."
    elif warn_corners:
        rec["detail"] = (f"{what} only in corners LibreLane warns about: {', '.join(warn_corners)}.")
    _apply_checker_outcome(rec, bool(err_corners or warn_corners), bool(err_corners or unmatched))
    return rec


def _worst(run: _Run, base: str) -> Optional[float]:
    return _num(run.metrics.get(base))


# ---------------------------------------------------------------- the checks
def _antenna_final(run: _Run) -> bool:
    """True once the antenna check after detailed routing has run (Classic
    runs OpenROAD.CheckAntennas after global routing too, as an estimate)."""
    drt = run.step("OpenROAD.DetailedRouting")
    if drt is None or drt["status"] != "done":
        return False
    for s in run.steps:
        if s["n"] <= drt["n"] or s["status"] != "done":
            continue
        sid = re.sub(r"-\d+$", "", s["id"] or "")
        sdir = re.sub(r"-\d+$", "", s["dir"].split("-", 1)[-1]).lower()
        if sid == "OpenROAD.CheckAntennas" or sdir == "openroad-checkantennas":
            return True
    return False


def _checks(run: _Run) -> List[Dict[str, Any]]:
    m = run.metrics
    out: List[Dict[str, Any]] = []

    # --- RTL lint (Verilator) ------------------------------------------------
    out.append(_metric_checker(run, _rec("lint_errors", "rtl", "Lint errors"),
               metric="design__lint_error__count", error_var="ERROR_ON_LINTER_ERRORS",
               checker="Checker.LintErrors", tool="Verilator.Lint", gates=["RUN_LINTER"]))
    out.append(_metric_checker(run, _rec("lint_timing_constructs", "rtl", "Timing constructs in RTL"),
               metric="design__lint_timing_construct__count", error_var=None, always_error=True,
               checker="Checker.LintTimingConstructs", tool="Verilator.Lint", gates=["RUN_LINTER"]))
    out.append(_metric_checker(run, _rec("lint_warnings", "rtl", "Lint warnings"),
               metric="design__lint_warning__count", error_var="ERROR_ON_LINTER_WARNINGS",
               checker="Checker.LintWarnings", tool="Verilator.Lint", gates=["RUN_LINTER"]))

    # --- Synthesis -----------------------------------------------------------
    out.append(_metric_checker(run, _rec("unmapped", "synth", "Unmapped cells"),
               metric="design__instance_unmapped__count", error_var="ERROR_ON_UNMAPPED_CELLS",
               checker="Checker.YosysUnmappedCells", tool="Yosys.Synthesis", rerun=False))
    out.append(_metric_checker(run, _rec("synth_check", "synth", "Synthesis check errors"),
               metric="synthesis__check_error__count", error_var="ERROR_ON_SYNTH_CHECKS",
               checker="Checker.YosysSynthChecks", tool="Yosys.Synthesis", rerun=False))
    # Assign statements: the checker scans the netlist text; no metric.
    rec = _rec("assign", "synth", "Assign statements in netlist", limit="",
               checker=_step_ref(run, "Checker.NetlistAssignStatements"),
               tool=_step_ref(run, "Yosys.Synthesis"), step_id="Checker.NetlistAssignStatements")
    err = bool(run.conf("ERROR_ON_NL_ASSIGN_STATEMENTS"))
    rec["gate_note"] = f"ERROR_ON_NL_ASSIGN_STATEMENTS = {'true' if err else 'false'}"
    ck = rec["checker"]
    if ck["status"] == "done":
        rec["status"] = _PASS
        ck["outcome"] = "passed"
        rec["value"] = "none" if err else None
        if not err:
            rec["detail"] = "The checker only warns in this run; any assign lines are listed in warning.log."
    elif ck["status"] == "stopped":
        rec["status"] = _FAIL
        ck["outcome"] = "raised"
        rec["value"] = "found"
    else:
        rec["detail"] = _no_data_reason(run, ck, rec["tool"])
    out.append(rec)
    # Latches: LibreLane has no checker; Yosys reports the count.
    rec = _rec("latch", "synth", "Inferred latches", gate="info", metric="design__inferred_latch__count",
               metric_keys=["design__inferred_latch__count"], limit="0 expected",
               gate_note="LibreLane does not stop on latches", tool=_step_ref(run, "Yosys.Synthesis"),
               rerun=None, step_id="Yosys.Synthesis")
    v = _finite(m.get("design__inferred_latch__count"))
    if v is None:
        rec["detail"] = _no_data_reason(run, None, rec["tool"])
    else:
        rec["value"] = m.get("design__inferred_latch__count")
        rec["values"] = {"design__inferred_latch__count": rec["value"]}
        rec["status"] = _PASS if v == 0 else _WARN
    out.append(rec)
    # Formal equivalence (off by default in Classic).
    rec = _rec("eqy", "synth", "RTL ↔ netlist equivalence (formal)", limit="proven",
               tool=_step_ref(run, "Yosys.EQY"), rerun="Yosys.EQY", step_id="Yosys.EQY")
    t = rec["tool"]
    if _gated(run, ["RUN_EQY"]) and t["status"] == "absent":
        rec["status"] = _SKIPPED
        rec["gate"] = "info"
        rec["gate_note"] = "RUN_EQY = false (LibreLane's default)"
        rec["detail"] = "Formal equivalence is off by default. Set RUN_EQY to true to prove the netlist matches the RTL."
    elif t["status"] == "done":
        rec["status"] = _PASS
        rec["value"] = "equivalent"
    elif t["status"] == "stopped":
        rec["status"] = _FAIL
        rec["value"] = "not proven"
    else:
        rec["gate"] = "info"
        rec["detail"] = _no_data_reason(run, None, t)
    out.append(rec)

    # --- Floorplan & power grid -----------------------------------------------
    rec = _metric_checker(run, _rec("pdn", "pnr", "Power-grid connections"),
                          metric="design__power_grid_violation__count", error_var="ERROR_ON_PDN_VIOLATIONS",
                          checker="Checker.PowerGridViolations", tool="OpenROAD.GeneratePDN")
    rec["rerun"] = None
    rec["breakdown"] = [{"label": "net " + k, "metric": "design__power_grid_violation__count__net:" + k, "value": v}
                        for k, v in sorted(_by_mod(m, "design__power_grid_violation__count", "net").items())]
    out.append(rec)

    # --- Routing ---------------------------------------------------------------
    rec = _metric_checker(run, _rec("route_drc", "pnr", "Routing DRC"),
                          metric="route__drc_errors", error_var="ERROR_ON_TR_DRC",
                          checker="Checker.TrDRC", tool="OpenROAD.DetailedRouting", gates=["RUN_DRT"])
    rec["rerun"] = None  # re-routing in place is a full re-run of routing onward
    iters = sorted(((int(k), v) for k, v in _by_mod(m, "route__drc_errors", "iter").items() if k.isdigit()))
    rec["breakdown"] = [{"label": f"iteration {i}", "metric": f"route__drc_errors__iter:{i}", "value": v} for i, v in iters]
    out.append(rec)
    rec = _metric_checker(run, _rec("disc_pin", "pnr", "Disconnected pins"),
                          metric="design__critical_disconnected_pin__count", error_var="ERROR_ON_DISCONNECTED_PINS",
                          checker="Checker.DisconnectedPins", tool="Odb.ReportDisconnectedPins")
    rec["rerun"] = None
    allp = m.get("design__disconnected_pin__count")
    if allp is not None:
        rec["breakdown"] = [
            {"label": "critical (checked)", "metric": "design__critical_disconnected_pin__count",
             "value": m.get("design__critical_disconnected_pin__count")},
            {"label": "all, including harmless ones", "metric": "design__disconnected_pin__count", "value": allp},
        ]
    out.append(rec)
    # Wire length: the threshold comes from the PDK; None -> checker skips.
    thr = _num(run.conf("WIRE_LENGTH_THRESHOLD"))
    rec = _rec("wire_length", "pnr", "Longest wire")
    if thr is None:
        rec.update(status=_INFO if m.get("route__wirelength__max") is not None else _NOT_RUN, gate="info",
                   metric="route__wirelength__max", metric_keys=["route__wirelength__max"],
                   value=m.get("route__wirelength__max"), unit="µm", limit="no limit set",
                   values={"route__wirelength__max": m.get("route__wirelength__max")}
                   if m.get("route__wirelength__max") is not None else {},
                   checker=_step_ref(run, "Checker.WireLength"), tool=_step_ref(run, "Odb.ReportWireLength"),
                   gate_note="WIRE_LENGTH_THRESHOLD is not set, so LibreLane skips this check",
                   step_id="Odb.ReportWireLength")
        if rec["checker"].get("status") == "done":
            rec["checker"]["outcome"] = "skipped"
    else:
        rec = _metric_checker(run, rec, metric="route__wirelength__max", error_var="ERROR_ON_LONG_WIRE",
                              checker="Checker.WireLength", tool="Odb.ReportWireLength", threshold=thr)
        rec["unit"] = "µm"
        rec["limit"] = f"≤ {thr:g} µm"
        rec["limit_var"] = "WIRE_LENGTH_THRESHOLD"
        rec["rerun"] = None
    out.append(rec)
    # Antenna: no checker step; LibreLane's manufacturability report marks
    # any violating net or pin as "Failed".
    rec = _rec("antenna", "pnr", "Antenna violations", limit="0",
               gate_note="LibreLane's manufacturability report marks this Failed; the flow itself continues",
               tool=_step_ref(run, "OpenROAD.CheckAntennas"), rerun="OpenROAD.CheckAntennas",
               step_id="OpenROAD.CheckAntennas")
    nets, pins = _finite(m.get("antenna__violating__nets")), _finite(m.get("antenna__violating__pins"))
    if nets is None and pins is None:
        legacy = _finite(m.get("route__antenna_violation__count"))
        if legacy is None:
            rec["detail"] = _no_data_reason(run, None, rec["tool"])
        else:
            rec.update(value=m.get("route__antenna_violation__count"), metric="route__antenna_violation__count",
                       metric_keys=["route__antenna_violation__count"],
                       values={"route__antenna_violation__count": m.get("route__antenna_violation__count")},
                       status=_PASS if legacy == 0 else _FAIL)
    else:
        rec.update(value=(nets or 0), metric="antenna__violating__nets",
                   metric_keys=["antenna__violating__nets", "antenna__violating__pins"],
                   values={"antenna__violating__nets": m.get("antenna__violating__nets"),
                           "antenna__violating__pins": m.get("antenna__violating__pins")},
                   status=_PASS if (nets or 0) + (pins or 0) == 0 else _FAIL)
        rec["breakdown"] = [
            {"label": "violating nets", "metric": "antenna__violating__nets", "value": m.get("antenna__violating__nets")},
            {"label": "violating pins", "metric": "antenna__violating__pins", "value": m.get("antenna__violating__pins")},
        ]
        if m.get("antenna_diodes_count") is not None:
            rec["breakdown"].append({"label": "diodes inserted", "metric": "antenna_diodes_count",
                                     "value": m.get("antenna_diodes_count")})
    # Classic checks antennas twice: after global routing (an estimate, before
    # the repair and detailed routing) and after detailed routing (the real
    # one). A run cut off before the second must not be judged on the first.
    if not run.completed and rec["status"] in (_PASS, _FAIL) and not _antenna_final(run):
        rec["estimate_only"] = ("the antenna check after detailed routing (the one checked at "
                                "global routing is an estimate, before antenna repair)")
    out.append(rec)

    # --- Timing sign-off (multi-corner STA) -------------------------------------
    rec = _timing_checker(run, _rec("setup", "timing", "Setup violations"),
                          base="timing__setup_vio__count", specific_var="SETUP_VIOLATION_CORNERS",
                          checker="Checker.SetupViolations", what="Setup violations")
    rec["worst"] = _worst(run, "timing__setup__ws")
    rec["tns"] = _worst(run, "timing__setup__tns")
    if rec["status"] == _NOT_RUN and rec["worst"] is not None and math.isfinite(rec["worst"]):
        # No violation counts at all, but a worst slack: judge on its sign.
        rec["status"] = _PASS if rec["worst"] >= 0 else _FAIL
        rec["metric"] = "timing__setup__ws"
        rec["metric_keys"] = ["timing__setup__ws"]
        rec["values"] = {"timing__setup__ws": run.metrics.get("timing__setup__ws")}
        rec["note"] = "This run recorded no violation counts; judged on the worst setup slack instead."
        rec["detail"] = ""
    out.append(rec)
    rec = _timing_checker(run, _rec("hold", "timing", "Hold violations"),
                          base="timing__hold_vio__count", specific_var="HOLD_VIOLATION_CORNERS",
                          checker="Checker.HoldViolations", what="Hold violations")
    rec["worst"] = _worst(run, "timing__hold__ws")
    rec["tns"] = _worst(run, "timing__hold__tns")
    if rec["status"] == _NOT_RUN and rec["worst"] is not None and math.isfinite(rec["worst"]):
        rec["status"] = _PASS if rec["worst"] >= 0 else _FAIL
        rec["metric"] = "timing__hold__ws"
        rec["metric_keys"] = ["timing__hold__ws"]
        rec["values"] = {"timing__hold__ws": run.metrics.get("timing__hold__ws")}
        rec["note"] = "This run recorded no violation counts; judged on the worst hold slack instead."
        rec["detail"] = ""
    out.append(rec)
    out.append(_timing_checker(run, _rec("slew", "timing", "Max slew violations"),
               base="design__max_slew_violation__count", specific_var="MAX_SLEW_VIOLATION_CORNERS",
               checker="Checker.MaxSlewViolations", what="Slew violations"))
    out.append(_timing_checker(run, _rec("cap", "timing", "Max capacitance violations"),
               base="design__max_cap_violation__count", specific_var="MAX_CAP_VIOLATION_CORNERS",
               checker="Checker.MaxCapViolations", what="Capacitance violations"))
    # Fanout: STA reports it; LibreLane has no checker for it.
    rec = _rec("fanout", "timing", "Max fanout violations", gate="info", limit="0 expected",
               gate_note="LibreLane does not check fanout", tool=_step_ref(run, "OpenROAD.STAPostPNR"),
               step_id="OpenROAD.STAPostPNR", metric="design__max_fanout_violation__count",
               metric_keys=["design__max_fanout_violation__count"])
    fv = _finite(m.get("design__max_fanout_violation__count"))
    if fv is None:
        rec["detail"] = _no_data_reason(run, None, rec["tool"])
    else:
        rec["value"] = m.get("design__max_fanout_violation__count")
        rec["values"] = {"design__max_fanout_violation__count": rec["value"]}
        rec["status"] = _PASS if fv == 0 else _WARN
        rec["corners"] = [{"corner": c, "value": _finite(v), "gating": False}
                          for c, v in sorted(_by_corner(m, "design__max_fanout_violation__count").items())]
    out.append(rec)

    # --- Physical verification -----------------------------------------------
    xor_gates = ["RUN_KLAYOUT_XOR", "RUN_MAGIC_STREAMOUT", "RUN_KLAYOUT_STREAMOUT"]
    out.append(_metric_checker(run, _rec("xor", "physical", "Mask XOR"),
               metric="design__xor_difference__count", error_var="ERROR_ON_XOR_ERROR",
               checker="Checker.XOR", tool="KLayout.XOR", gates=xor_gates))
    out.append(_metric_checker(run, _rec("magic_drc", "physical", "Magic DRC"),
               metric="magic__drc_error__count", error_var="ERROR_ON_MAGIC_DRC",
               checker="Checker.MagicDRC", tool="Magic.DRC", gates=["RUN_MAGIC_DRC"]))
    rec = _metric_checker(run, _rec("klayout_drc", "physical", "KLayout DRC"),
                          metric="klayout__drc_error__count", error_var="ERROR_ON_KLAYOUT_DRC",
                          checker="Checker.KLayoutDRC", tool="KLayout.DRC", gates=["RUN_KLAYOUT_DRC"])
    # gf180mcu's LibreLane config sets no KLayout deck: KLayout.DRC logs "This
    # step will be skipped" and Magic is the run's DRC. Say that, rather than
    # "No value recorded", and don't hold the DRC verdict open for it.
    if (rec["status"] == _NOT_RUN and run.completed and run.has_cfg
            and "KLAYOUT_DRC_RUNSET" in run.cfg and not run.cfg.get("KLAYOUT_DRC_RUNSET")):
        rec["status"] = _SKIPPED
        rec["gate"] = "info"
        rec["gate_note"] = "KLAYOUT_DRC_RUNSET is not set for this PDK, so LibreLane skips it"
        rec["detail"] = (f"LibreLane skipped KLayout DRC: {run.cfg.get('PDK') or 'this PDK'} has no "
                         "KLayout rule deck in its LibreLane config (KLAYOUT_DRC_RUNSET). Magic DRC "
                         "is this run's design-rule check.")
    out.append(rec)
    rec = _metric_checker(run, _rec("overlap", "physical", "Illegal overlaps"),
                          metric="magic__illegal_overlap__count", error_var="ERROR_ON_ILLEGAL_OVERLAPS",
                          checker="Checker.IllegalOverlap", tool="Magic.SpiceExtraction", gates=["RUN_LVS"])
    rec["rerun"] = None
    out.append(rec)
    rec = _metric_checker(run, _rec("lvs", "physical", "LVS"),
                          metric="design__lvs_error__count", error_var="ERROR_ON_LVS_ERROR",
                          checker="Checker.LVS", tool="Netgen.LVS", gates=["RUN_LVS"])
    rec["breakdown"] = [
        {"label": lbl, "metric": k, "value": m.get(k)} for lbl, k in (
            ("unmatched pins", "design__lvs_unmatched_pin__count"),
            ("unmatched nets", "design__lvs_unmatched_net__count"),
            ("unmatched devices", "design__lvs_unmatched_device__count"),
            ("net count difference", "design__lvs_net_difference__count"),
            ("device count difference", "design__lvs_device_difference__count"),
            ("property mismatches", "design__lvs_property_fail__count"),
        ) if m.get(k) is not None]
    out.append(rec)
    # Optional KLayout checks other flows add (not in Classic by default).
    for cid, name, metric, var, ck, tool in (
        ("klayout_density", "KLayout density", "klayout__density_error__count", "ERROR_ON_KLAYOUT_DENSITY",
         "Checker.KLayoutDensity", "KLayout.Density"),
        ("klayout_antenna", "KLayout antenna", "klayout__antenna_error__count", "ERROR_ON_KLAYOUT_ANTENNA",
         "Checker.KLayoutAntenna", "KLayout.Antenna"),
    ):
        if m.get(metric) is not None or run.step(ck) is not None:
            out.append(_metric_checker(run, _rec(cid, "physical", name), metric=metric, error_var=var,
                                       checker=ck, tool=tool))

    # A run that stopped: a check whose step never ran must not be judged on
    # whatever an earlier step estimated (e.g. mid-flow STA before routing).
    if not run.completed:
        for r in out:
            ck, tl = r.get("checker"), r.get("tool")
            ref = ck if ck else tl
            est = r.pop("estimate_only", None)
            if not est and (not ref or ref.get("status") != "absent"):
                continue
            if r["status"] in (_PASS, _WARN, _FAIL, _INFO):
                r["interim"] = r["value"]
                r["status"] = _NOT_RUN
                r["value"] = None
                r["corners"] = []
                r["detail"] = _no_data_reason(run, ck, tl)
                if est and not any(s["status"] == "stopped" for s in run.steps):
                    last = run.steps[-1] if run.steps else None
                    r["detail"] = (f"Not reached: the run ended after step {last['n']} "
                                   f"({last['id'] or last['dir']}), before {est}."
                                   if last else f"Not reached: the run ended before {est}.")
                if r["interim"] is not None and run.metrics_from:
                    iv = r["interim"]
                    iv = f"{iv:g}" if isinstance(iv, float) else iv
                    r["detail"] += (f" The last value LibreLane recorded (after step {run.metrics_from['n']}, "
                                    f"an earlier estimate) was {iv}.")

    # Report files that back each check (relative to the run).
    rep = {
        "lint_errors": [("Verilator.Lint", "*.log")],
        "lint_warnings": [("Verilator.Lint", "*.log")],
        "lint_timing_constructs": [("Verilator.Lint", "*.log")],
        "unmapped": [("Yosys.Synthesis", "reports/stat.rpt", "reports/*.rpt")],
        "synth_check": [("Yosys.Synthesis", "reports/pre_synth_chk.rpt", "reports/*chk*.rpt")],
        "pdn": [("OpenROAD.GeneratePDN", "*.log")],
        "route_drc": [("OpenROAD.DetailedRouting", "*.drc", "*.log")],
        "disc_pin": [("Odb.ReportDisconnectedPins", "*.log", "reports/*")],
        "antenna": [("OpenROAD.CheckAntennas", "reports/antenna_summary.rpt", "reports/antenna.rpt")],
        "setup": [("OpenROAD.STAPostPNR", "summary.rpt")],
        "hold": [("OpenROAD.STAPostPNR", "summary.rpt")],
        "slew": [("OpenROAD.STAPostPNR", "summary.rpt")],
        "cap": [("OpenROAD.STAPostPNR", "summary.rpt")],
        "fanout": [("OpenROAD.STAPostPNR", "summary.rpt")],
        "xor": [("KLayout.XOR", "*.log", "xor.xml")],
        "magic_drc": [("Magic.DRC", "reports/drc.magic.rpt")],
        "klayout_drc": [("KLayout.DRC", "reports/drc.klayout.json", "*.log")],
        "overlap": [("Magic.SpiceExtraction", "*.log")],
        "lvs": [("Netgen.LVS", "reports/lvs.netgen.rpt")],
    }
    for r in out:
        for spec in rep.get(r["id"], []):
            p = run.file(spec[0], *spec[1:])
            rel = _rel(run.dir, p)
            if rel:
                r["reports"].append({"label": p.name, "rel": rel})
    return out


# ---------------------------------------------------------------- report details
def _rdb_summary(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    """Summarise a KLayout report database (``.lyrdb``/``.xml``): every
    category with its marker count and description, plus a few sample marker
    locations each. Streams the file so big databases stay cheap."""
    if path is None or not path.is_file():
        return None
    descs: Dict[str, str] = {}
    order: List[str] = []
    counts: Dict[str, int] = {}
    samples: Dict[str, List[List[float]]] = {}
    total = 0
    path_stack: List[str] = []
    cat_name: List[Optional[str]] = []
    try:
        for ev, el in ET.iterparse(str(path), events=("start", "end")):
            tag = el.tag
            if ev == "start":
                # An item's <category> is a reference, not a definition.
                if tag == "category" and (path_stack[-1] if path_stack else "") != "item":
                    cat_name.append(None)
                path_stack.append(tag)
                continue
            path_stack.pop()
            parent = path_stack[-1] if path_stack else ""
            if tag == "name" and parent == "category" and cat_name:
                nm = (el.text or "").strip()
                # Nested categories get dotted names, as KLayout shows them.
                outer = [c for c in cat_name[:-1] if c]
                cat_name[-1] = ".".join(outer + [nm]) if outer else nm
                if cat_name[-1] not in descs:
                    descs[cat_name[-1]] = ""
                    order.append(cat_name[-1])
            elif tag == "description" and parent == "category" and cat_name and cat_name[-1]:
                descs[cat_name[-1]] = (el.text or "").strip()
            elif tag == "category" and parent != "item":
                if cat_name:
                    cat_name.pop()
            elif tag == "item":
                total += 1
                cat = (el.findtext("category") or "").strip().strip("'").replace("'.'", ".")
                counts[cat] = counts.get(cat, 0) + 1
                s = samples.setdefault(cat, [])
                if len(s) < _MAX_SAMPLES:
                    for val in el.iter("value"):
                        box = _bbox_of(val.text or "")
                        if box:
                            s.append(box)
                            break
                el.clear()
    except Exception:
        return {"ok": False, "total": None, "categories": []}
    cats = [{"name": c, "description": descs.get(c, ""), "count": counts.get(c, 0),
             "samples": samples.get(c, [])} for c in order]
    for c, n in counts.items():
        if c not in descs:
            cats.append({"name": c, "description": "", "count": n, "samples": samples.get(c, [])})
    cats.sort(key=lambda c: -c["count"])
    failing = [c for c in cats if c["count"]]
    return {"ok": True, "total": total, "rules": len(cats),
            "categories": failing[:_MAX_CATEGORIES], "more": max(0, len(failing) - _MAX_CATEGORIES)}


_NUM = r"-?\d+(?:\.\d+)?(?:e-?\d+)?"


def _bbox_of(text: str) -> Optional[List[float]]:
    """``polygon: (x,y;x,y;…)`` / ``box: (x,y;x,y)`` / ``edge-pair: …`` -> bbox µm."""
    pts = re.findall(r"(" + _NUM + r"),(" + _NUM + r")", text)
    if not pts:
        return None
    xs = [float(a) for a, _ in pts]
    ys = [float(b) for _, b in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _klayout_drc(run: _Run) -> Optional[Dict[str, Any]]:
    js = run.file("KLayout.DRC", "reports/drc.klayout.json")
    rdb = run.file("KLayout.DRC", "reports/*.lyrdb")
    if js is None and rdb is None:
        return None
    summary = _rdb_summary(rdb) or {"ok": False, "categories": []}
    rdb_summary = summary
    counts = _read_json(js) if js else None
    if isinstance(counts, dict):
        # The JSON is the per-rule count LibreLane totals into the metric.
        descs = {c["name"]: c for c in summary.get("categories", [])}
        rules = [{"name": k, "count": v, "description": (descs.get(k) or {}).get("description", ""),
                  "samples": (descs.get(k) or {}).get("samples", [])}
                 for k, v in counts.items() if isinstance(v, (int, float)) and v]
        rules.sort(key=lambda r: -r["count"])
        summary = {"ok": True, "rules": len(counts), "total": sum(v for v in counts.values()
                                                                 if isinstance(v, (int, float))),
                   "categories": rules[:_MAX_CATEGORIES], "more": max(0, len(rules) - _MAX_CATEGORIES)}
        # The marker database is read too: its count can disagree with the
        # per-rule JSON (an edited or stale report), and that must show.
        if rdb_summary.get("ok") and rdb_summary.get("total") is not None:
            summary["marker_total"] = rdb_summary["total"]
            summary["marker_categories"] = rdb_summary.get("categories", [])
    summary["report"] = _rel(run.dir, js or rdb)
    summary["markers"] = _rel(run.dir, rdb)
    return summary


def _magic_drc(run: _Run) -> Optional[Dict[str, Any]]:
    rdb = run.file("Magic.DRC", "reports/*.lyrdb")
    rpt = run.file("Magic.DRC", "reports/drc.magic.rpt", "reports/*.rpt")
    if rdb is None and rpt is None:
        return None
    s = _rdb_summary(rdb) or {"ok": False, "categories": []}
    s["report"] = _rel(run.dir, rpt or rdb)
    s["markers"] = _rel(run.dir, rdb)
    return s


def _route_drc(run: _Run) -> Optional[Dict[str, Any]]:
    s = run.step("OpenROAD.DetailedRouting")
    if s is None:
        return None
    drc = next((p for p in sorted(s["path"].glob("*.drc")) if p.is_file()), None)
    by_type: Dict[str, Dict[str, Any]] = {}
    total = 0
    if drc is not None:
        cur = None
        try:
            with drc.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("violation type:"):
                        cur = line.split(":", 1)[1].strip()
                    elif line.startswith("bbox") and cur:
                        total += 1
                        mm = re.search(r"\((" + _NUM + r"), (" + _NUM + r")\) - \((" + _NUM + r"), (" + _NUM +
                                       r")\) on Layer (\S+)", line)
                        layer = mm.group(5) if mm else ""
                        e = by_type.setdefault(cur + "|" + layer, {"name": cur, "layer": layer, "count": 0, "samples": []})
                        e["count"] += 1
                        if mm and len(e["samples"]) < _MAX_SAMPLES:
                            e["samples"].append([float(mm.group(i)) for i in range(1, 5)])
        except Exception:
            pass
    cats = sorted(by_type.values(), key=lambda c: -c["count"])
    iters = sorted(((int(k), v) for k, v in _by_mod(run.metrics, "route__drc_errors", "iter").items()
                    if k.isdigit()))
    xml = next((p for p in sorted(s["path"].glob("*.drc.xml")) if p.is_file()), None)
    return {"ok": drc is not None, "total": total, "categories": cats[:_MAX_CATEGORIES],
            "iterations": [{"iter": i, "count": v} for i, v in iters],
            "report": _rel(run.dir, drc), "markers": _rel(run.dir, xml)}


def _lvs(run: _Run) -> Optional[Dict[str, Any]]:
    js = run.file("Netgen.LVS", "reports/lvs.netgen.json")
    rpt = run.file("Netgen.LVS", "reports/lvs.netgen.rpt")
    if js is None and rpt is None:
        return None
    out: Dict[str, Any] = {"report": _rel(run.dir, rpt), "json": _rel(run.dir, js)}
    if rpt is not None:
        try:
            text = rpt.read_text(encoding="utf-8", errors="replace")
            mm = re.findall(r"^Final result:\s*(.+?)\s*$", text, flags=re.M)
            if mm:
                out["result"] = mm[-1].rstrip(".")
        except Exception:
            pass
    doc = _read_json(js) if js else None
    if isinstance(doc, list) and doc and isinstance(doc[-1], dict):
        top = doc[-1]
        names = top.get("name") or ["", ""]

        def side(i: int) -> Dict[str, Any]:
            d: Dict[str, Any] = {"name": names[i] if i < len(names) else ""}
            devs = top.get("devices")
            if isinstance(devs, list) and len(devs) > i:
                d["devices"] = sum(int(x[1]) for x in devs[i] if isinstance(x, list) and len(x) > 1)
            nets = top.get("nets")
            if isinstance(nets, list) and len(nets) > i:
                d["nets"] = nets[i]
            pins = top.get("pins")
            if isinstance(pins, list) and len(pins) > i and isinstance(pins[i], list):
                d["pins"] = len(pins[i])
            return d

        # Netgen's circuit 1 is the extracted layout, circuit 2 the netlist.
        out["layout"] = side(0)
        out["netlist"] = side(1)
        dev_diff = []
        devs = top.get("devices")
        if isinstance(devs, list) and len(devs) == 2:
            for a, b in zip(devs[0], devs[1]):
                try:
                    if a[1] != b[1] or a[0] != b[0]:
                        dev_diff.append({"layout": a[0], "layout_n": a[1], "netlist": b[0], "netlist_n": b[1]})
                except Exception:
                    continue
        out["device_diffs"] = dev_diff[:40]
        out["bad_nets"] = len(top.get("badnets") or [])
        out["bad_devices"] = len(top.get("badelements") or [])
        pin_diff = []
        pins = top.get("pins")
        if isinstance(pins, list) and len(pins) == 2:
            for a, b in zip(pins[0], pins[1]):
                if re.sub("!$", "", str(a).lower()) != re.sub("!$", "", str(b).lower()) \
                        and "(no pin)" not in (str(a).lower(), str(b).lower()):
                    pin_diff.append({"layout": a, "netlist": b})
        out["pin_diffs"] = pin_diff[:40]
    return out


def _xor(run: _Run) -> Optional[Dict[str, Any]]:
    x = run.file("KLayout.XOR", "xor.xml", "*.xml")
    if x is None:
        return None
    s = _rdb_summary(x) or {"ok": False, "categories": []}
    # Count layers compared (all categories, not only differing ones).
    try:
        layers = 0
        for ev, el in ET.iterparse(str(x), events=("start", "end")):
            if ev == "start" and el.tag == "items":
                break
            if ev == "end" and el.tag == "category":
                layers += 1
        s["layers"] = layers
    except Exception:
        pass
    s["report"] = _rel(run.dir, x)
    s["markers"] = _rel(run.dir, x)
    return s


def _antenna(run: _Run) -> Optional[Dict[str, Any]]:
    rpt = run.file("OpenROAD.CheckAntennas", "reports/antenna_summary.rpt")
    if rpt is None:
        return None
    rows: List[Dict[str, str]] = []
    try:
        for line in rpt.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.startswith("│"):
                continue
            cells = [c.strip() for c in line.strip("│").split("│")]
            if len(cells) >= 6 and cells[0] and cells[0] != "P / R":
                rows.append({"ratio": cells[0], "partial": cells[1], "required": cells[2],
                             "net": cells[3], "pin": cells[4], "layer": cells[5]})
    except Exception:
        pass
    return {"rows": rows[:100], "more": max(0, len(rows) - 100), "report": _rel(run.dir, rpt)}


def _ir(run: _Run) -> Optional[Dict[str, Any]]:
    rpt = run.file("OpenROAD.IRDropReport", "irdrop.rpt", "*.rpt")
    if rpt is None:
        return None
    nets: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    fields = {
        "Net": "net", "Corner": "corner", "Supply voltage": "supply", "Worstcase voltage": "worst_voltage",
        "Average voltage": "avg_voltage", "Average IR drop": "avg_drop", "Worstcase IR drop": "worst_drop",
        "Percentage drop": "pct",
    }
    try:
        for line in rpt.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            key = fields.get(k.strip())
            if not key:
                continue
            v = v.strip()
            if key == "net":
                cur = {"net": v}
                nets.append(cur)
                continue
            if cur is None:
                continue
            if key == "corner":
                cur[key] = v
            else:
                mm = re.match(r"(" + _NUM + r")", v.replace("E", "e"))
                if mm:
                    cur[key] = float(mm.group(1))
    except Exception:
        pass
    return {"nets": nets, "report": _rel(run.dir, rpt)}


def _timing_table(run: _Run, checks: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    m = run.metrics
    bases = {
        "setup_ws": "timing__setup__ws", "setup_tns": "timing__setup__tns", "setup_vio": "timing__setup_vio__count",
        "setup_r2r": "timing__setup_r2r__ws",
        "hold_ws": "timing__hold__ws", "hold_tns": "timing__hold__tns", "hold_vio": "timing__hold_vio__count",
        "hold_r2r": "timing__hold_r2r__ws",
        "slew": "design__max_slew_violation__count", "cap": "design__max_cap_violation__count",
        "fanout": "design__max_fanout_violation__count",
    }
    per: Dict[str, Dict[str, Any]] = {}
    for col, base in bases.items():
        for c, v in _by_corner(m, base).items():
            per.setdefault(c, {"corner": c})[col] = v
    gate = {}
    for cid in ("setup", "hold", "slew", "cap"):
        for row in checks.get(cid, {}).get("corners", []):
            gate.setdefault(row["corner"], {})[cid] = row["gating"]
    rows = []
    for c in sorted(per):
        r = per[c]
        r["gates"] = gate.get(c, {})
        rows.append(r)
    clk = run.cfg.get("CLOCK_PERIOD")
    sta = run.step("OpenROAD.STAPostPNR")
    return {
        # "signoff" when the post-route STA step finished; otherwise these are
        # the last estimates an earlier STA step left in the metrics.
        "source": "signoff" if sta and sta["status"] == "done" else ("estimate" if per else "none"),
        "corners": rows,
        "default_corner": run.cfg.get("DEFAULT_CORNER"),
        "clock_period": clk,
        "clock_port": run.cfg.get("CLOCK_PORT"),
        "setup_rule": {"var": checks.get("setup", {}).get("corner_var"),
                       "wildcards": checks.get("setup", {}).get("corner_wildcards")},
        "hold_rule": {"var": checks.get("hold", {}).get("corner_var"),
                      "wildcards": checks.get("hold", {}).get("corner_wildcards")},
        "totals": {k: m.get(v) for k, v in bases.items() if m.get(v) is not None},
    }


# ---------------------------------------------------------------- flow + verdict
def _planned_steps(run: _Run) -> Tuple[int, List[str]]:
    """``(total, ids turned off)``: how many steps this run's flow has once
    the steps its config switches off (``gating_config_vars``) are taken out."""
    if run.completed or not run.has_cfg:
        return len(run.steps), []
    try:
        from . import introspect
        meta = run.cfg.get("meta") if isinstance(run.cfg.get("meta"), dict) else {}
        name = (meta or {}).get("flow") or run.gui.get("flow") or "Classic"
        if not isinstance(name, str):
            name = "Classic"
        ids = [s["id"] for s in introspect.flow_steps(name)]
        gating = introspect.flow_gating(name)
    except Exception:
        return len(run.steps), []
    if not ids:
        return len(run.steps), []
    import fnmatch
    off: List[str] = []
    for sid in ids:
        base = re.sub(r"-\d+$", "", sid)
        for pat, gvars in gating.items():
            if (pat == base or fnmatch.fnmatchcase(base, pat)) and any(run.conf(g) is False for g in gvars):
                off.append(sid)
                break
    return max(len(ids) - len(off), len(run.steps)), off


def _flow_state(run: _Run) -> Dict[str, Any]:
    stopped = [s for s in run.steps if s["status"] == "stopped"]
    raised_checkers = [s for s in stopped if (s["id"] or "").startswith("Checker.")
                       or s["dir"].split("-", 1)[-1].startswith("checker-")]
    err_lines: List[str] = []
    try:
        el = run.dir / "error.log"
        if el.is_file():
            err_lines = [ln.rstrip() for ln in el.read_text(encoding="utf-8", errors="replace").splitlines()
                         if ln.strip()][:30]
    except Exception:
        pass
    # A run resumed from another one starts at --from too, but it is whole:
    # the steps before come from that run (``branched_from``).
    partial = bool((run.gui.get("frm") and not run.branch) or run.gui.get("to"))
    if run.completed and not stopped:
        state = "complete"
    elif run.completed and stopped and len(raised_checkers) == len(stopped):
        state = "deferred_errors"
    elif run.completed:
        state = "complete_with_errors"
    elif stopped:
        state = "stopped"
    else:
        state = "unknown"
    first_stop = stopped[0] if stopped else None
    last = run.steps[-1] if run.steps else None
    planned, off = _planned_steps(run)
    return {
        # FS.stepCounts' meaning: the flow's steps minus those this run's
        # config turns off. A finished run: its own step folders. A run that
        # ended early: the whole flow, not just the folders it got to.
        "steps_planned": planned,
        "steps_off": off,
        "state": state,
        "partial": partial,
        "frm": run.gui.get("frm"), "to": run.gui.get("to"),
        "branched_from": run.branch,
        "steps_total": len(run.steps),
        "steps_done": sum(1 for s in run.steps if s["status"] == "done"),
        "stopped_step": ({"n": first_stop["n"], "dir": first_stop["dir"], "id": first_stop["id"]}
                         if first_stop else None),
        "raised_checkers": [{"n": s["n"], "dir": s["dir"], "id": s["id"]} for s in raised_checkers],
        "last_step": ({"n": last["n"], "dir": last["dir"], "id": last["id"]} if last else None),
        "error_log": err_lines,
    }


# Checks that must have data before a run can be called ready.
_CORE = ("setup", "hold", "lvs")
_CORE_DRC = ("magic_drc", "klayout_drc")
_GROUPS = [
    {"id": "rtl", "title": "RTL lint", "tool": "Verilator"},
    {"id": "synth", "title": "Synthesis", "tool": "Yosys"},
    {"id": "pnr", "title": "Place & route", "tool": "OpenROAD"},
    {"id": "timing", "title": "Timing sign-off", "tool": "OpenSTA, every corner"},
    {"id": "physical", "title": "Physical verification", "tool": "Magic, KLayout, Netgen"},
]
_LEGACY_STAGE = {"rtl": "rtl", "synth": "synth", "pnr": "physical", "timing": "timing", "physical": "physical"}


def _legacy_status(checks: List[Dict[str, Any]]) -> str:
    st = [c["status"] for c in checks]
    if _FAIL in st:
        return _FAIL
    present = [s for s in st if s in (_PASS, _WARN, _INFO)]
    if not present:
        return _ABSENT
    return _WARN if _WARN in st else _PASS


def _verdict(checks: List[Dict[str, Any]], flow: Dict[str, Any]) -> Dict[str, Any]:
    by = {c["id"]: c for c in checks}
    blockers = [c for c in checks if c["status"] == _FAIL]
    warnings = [c for c in checks if c["status"] == _WARN]
    has = lambda c: c and c["status"] in (_PASS, _FAIL, _WARN)  # noqa: E731
    missing_core = [cid for cid in _CORE if not has(by.get(cid))]
    if not any(has(by.get(cid)) for cid in _CORE_DRC):
        missing_core.append("drc")
    skipped_core = [cid for cid in _CORE + _CORE_DRC if by.get(cid, {}).get("status") == _SKIPPED]
    stopped = flow["state"] == "stopped"
    if blockers:
        state = "blocked"
    elif stopped:
        state = "stopped"
    elif missing_core:
        state = "incomplete"
    else:
        state = "ready"
    counts: Dict[str, int] = {}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    # Old-API fields (stages by tool family) kept for existing callers.
    missing_stages = []
    if not any(has(by.get(c)) for c in ("setup", "hold", "slew", "cap")):
        missing_stages.append("timing")
    if not any(has(c) for c in checks if c["group"] in ("physical", "pnr")):
        missing_stages.append("physical")
    return {
        "state": state,
        "ready": state == "ready",
        "incomplete": state in ("incomplete", "stopped"),
        "missing_core": missing_core,
        "skipped_core": skipped_core,
        "missing_stages": missing_stages,
        "blockers": [c["name"] for c in blockers],
        "warnings": [c["name"] for c in warnings],
        "blocker_ids": [c["id"] for c in blockers],
        "warning_ids": [c["id"] for c in warnings],
        "counts": counts,
        "total": len(checks),
    }


def _stage_of(step_id: Optional[str]) -> Optional[str]:
    if not step_id:
        return None
    try:
        from . import flowstages
        return flowstages.listed_stage(step_id) or ("signoff" if step_id.startswith("Checker.") else None)
    except Exception:
        return None


def _corner_words(corner: Optional[str]) -> str:
    """``max_ss_100C_1v60`` -> ``the slow corner (max_ss_100C_1v60)``."""
    if not corner:
        return "one corner"
    c = corner.lower()
    kind = ("slow" if "_ss_" in c or c.startswith("ss") else "fast" if "_ff_" in c or c.startswith("ff")
            else "typical" if "_tt_" in c or c.startswith("tt") else "")
    return (f"the {kind} corner ({corner})" if kind else f"corner {corner}")


def _timing_miss(run: "_Run") -> Optional[Dict[str, Any]]:
    """The worst negative setup or hold slack STA reported in any corner, or
    None. A run with negative slack is never called clean, even when
    LibreLane only warns because the corner is outside
    ``TIMING_VIOLATION_CORNERS``: the chip would miss its clock there."""
    worst: Optional[Dict[str, Any]] = None
    for kind in ("setup", "hold"):
        base = f"timing__{kind}__ws"
        vals = {c: _finite(v) for c, v in _by_corner(run.metrics, base).items()}
        if not vals and _finite(run.metrics.get(base)) is not None:
            vals = {None: _finite(run.metrics.get(base))}
        for c, v in vals.items():
            if v is not None and v < 0 and (worst is None or v < worst["ws"]):
                worst = {"kind": kind, "ws": v, "corner": c}
    return worst


_STATE_BY_GROUP = {"rtl": "synthesis", "synth": "synthesis", "pnr": "routing",
                   "timing": "signoff", "physical": "signoff"}


def run_verdict_from(run: "_Run", checks: List[Dict[str, Any]], flow: Dict[str, Any],
                     v: Dict[str, Any], *, live: bool = False) -> Dict[str, Any]:
    """The one run verdict every page shows (Runs, run bar, Analytics, Verify,
    Compare, the default baseline): ``{state, label, stage?}`` plus counts.

    It is Verify's verdict, mapped onto five states:
    ``passed`` (Verify "ready"), ``failed`` (a check blocks the run, or a step
    raised), ``stopped`` (the user stopped it, or LanEx closed mid-run),
    ``running`` (the live run) and ``incomplete`` (nothing failed, but a core
    check has no result: LVS or DRC turned off, a partial -T run)."""
    outcome = (run.gui.get("outcome") or {}) if isinstance(run.gui.get("outcome"), dict) else {}
    stop = flow.get("stopped_step") or None
    out: Dict[str, Any] = {"checks_total": v["total"], "counts": v["counts"],
                           "warnings": len(v["warning_ids"]), "blockers": len(v["blocker_ids"])}
    if live:
        last = flow.get("last_step") or {}
        out.update(state="running", label="Running" + (f", step {last['n']}" if last.get("n") else ""))
        st = _stage_of(last.get("id") or last.get("dir")) if last else None
        if st:
            out["stage"] = st
        return out
    if outcome.get("result") == "cancelled":
        out.update(state="stopped", label=f"Stopped at step {stop['n']}" if stop else "Stopped")
        st = _stage_of(stop.get("id") or stop.get("dir")) if stop else None
        if st:
            out["stage"] = st
        return out
    if v["state"] == "blocked":
        k = len(v["blocker_ids"])
        first = next(c for c in checks if c["status"] == _FAIL)
        out.update(state="failed", label=f"{k} check{'s' if k != 1 else ''} failed")
        out["stage"] = (_stage_of(first.get("step_id") or (first.get("checker") or {}).get("id"))
                        or _STATE_BY_GROUP.get(first["group"]))
        return out
    if v["state"] == "stopped":
        # A step began and never finished. LibreLane raised (error.log, or the
        # GUI noted an error) -> failed; otherwise the run was cut off (LanEx or
        # the PC closed mid-run): stopped, not a failure of the design.
        raised = bool(flow.get("error_log")) or outcome.get("result") == "error"
        n = stop["n"] if stop else None
        out.update(state="failed" if raised else "stopped",
                   label=(("Failed" if raised else "Stopped") + (f" at step {n}" if n else "")))
        st = _stage_of(stop.get("id") or stop.get("dir")) if stop else None
        if st:
            out["stage"] = st
        return out
    if v["state"] == "incomplete" and not run.completed and not flow.get("partial"):
        # No final/ and nothing raised: the flow ended early (cut off between
        # two steps). Not a design failure, but not a finished run either.
        last = flow.get("last_step") or {}
        out.update(state="stopped", label="Stopped" + (f" after step {last['n']}" if last.get("n") else ""))
        st = _stage_of(last.get("id") or last.get("dir")) if last else None
        if st:
            out["stage"] = st
        return out
    miss = _timing_miss(run)
    if miss:
        # LibreLane passed the run (it only enforces the corners in
        # TIMING_VIOLATION_CORNERS), so LanEx does not call it failed; but the
        # design misses its clock there, so never "clean" either: warning.
        out.update(state="warning", stage="signoff", timing_miss={**miss, "where": _corner_words(miss["corner"])},
                   label=f"Finished: timing misses in {_corner_words(miss['corner']).split(' (')[0]}"
                         f" ({miss['kind']} {miss['ws']:.2f} ns)")
        return out
    if v["state"] == "incomplete":
        out.update(state="incomplete", label="Not enough to call it")
        return out
    w = len(v["warning_ids"])
    out.update(state="passed", label="Clean" + (f", {w} warning{'s' if w != 1 else ''}" if w else ""))
    return out


_DRC_METRICS = (("magic_drc", "magic__drc_error__count", _magic_drc),
                ("klayout_drc", "klayout__drc_error__count", _klayout_drc))


def _drc_disagreements(run: "_Run", details: Optional[Dict[str, Any]] = None,
                       *, clean_only: bool = False) -> Dict[str, Dict[str, Any]]:
    """DRC report files that contradict the metric LibreLane judged the run on
    ("0 errors" next to markers, or the reverse: an edited report, or one left
    from an earlier run). ``clean_only`` looks only where the metric says 0
    (the case that would otherwise read "clean"), so a run list stays cheap."""
    out: Dict[str, Dict[str, Any]] = {}
    for key, mkey, fn in _DRC_METRICS:
        mval = _finite(run.metrics.get(mkey))
        if mval is None or (clean_only and mval != 0):
            continue
        if details is not None:
            d = details.get(key)
        else:
            try:
                d = fn(run)
            except Exception:
                d = None
        if not isinstance(d, dict):
            continue
        rep_n = d.get("marker_total") if d.get("marker_total") is not None else d.get("total")
        if isinstance(rep_n, (int, float)) and (mval == 0) != (rep_n == 0):
            out[key] = {"metric_key": mkey, "metric": mval,
                        "metric_file": ("final/metrics.json" if (run.dir / "final" / "metrics.json").is_file()
                                        else "metrics.json"),
                        "report": rep_n, "report_file": d.get("markers") or d.get("report")}
    return out


def _with_drc_flag(run: "_Run", out: Dict[str, Any], dis: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Carry a DRC report/metric disagreement on the verdict. The state stays
    LibreLane's (the metric); consumers add a "report disagrees" flag."""
    if dis and out.get("state") not in ("running",):
        out["drc_disagree"] = {
            "markers": int(sum(d["report"] for d in dis.values() if d["metric"] == 0)),
            "checks": sorted(dis),
            "detail": {k: {"metric": d["metric"], "report": d["report"], "report_file": d["report_file"]}
                       for k, d in dis.items()},
        }
    return out


def run_verdict(run_dir: str | Path, *, live: bool = False) -> Dict[str, Any]:
    """:func:`run_verdict_from` for one run folder. Only the DRC marker
    databases of a run whose DRC metric reads 0 are parsed (for the
    report-disagrees flag)."""
    run = _Run(Path(run_dir).resolve())
    checks = _checks(run)
    flow = _flow_state(run)
    out = run_verdict_from(run, checks, flow, _verdict(checks, flow), live=live)
    if live:
        return out
    try:
        dis = _drc_disagreements(run, clean_only=True)
    except Exception:
        dis = {}
    return _with_drc_flag(run, out, dis)


def verify_report(run_dir: str | Path) -> Dict[str, Any]:
    """The signoff picture of one run, organised by flow stage.

    Reads ``final/metrics.json``, ``resolved.json``, ``flow.log``,
    ``error.log`` and the step dirs; never re-runs anything.
    """
    run = _Run(Path(run_dir).resolve())
    checks = _checks(run)
    flow = _flow_state(run)
    verdict = _verdict(checks, flow)
    by = {c["id"]: c for c in checks}
    groups = []
    for g in _GROUPS:
        gc = [c for c in checks if c["group"] == g["id"]]
        groups.append({**g, "status": _legacy_status(gc), "checks": [c["id"] for c in gc]})
    stages: Dict[str, Dict[str, Any]] = {}
    for gid, sid in _LEGACY_STAGE.items():
        stages.setdefault(sid, {"checks": []})["checks"].extend(c for c in checks if c["group"] == gid)
    for s in stages.values():
        s["status"] = _legacy_status(s["checks"])
    cfg = run.cfg
    meta = cfg.get("meta") if isinstance(cfg.get("meta"), dict) else {}
    details: Dict[str, Any] = {"timing": _timing_table(run, by)}
    for key, fn in (("klayout_drc", _klayout_drc), ("magic_drc", _magic_drc), ("route_drc", _route_drc),
                    ("lvs", _lvs), ("xor", _xor), ("antenna", _antenna), ("ir", _ir)):
        try:
            details[key] = fn(run)
        except Exception:
            details[key] = None
    # A DRC report file that contradicts the metric LibreLane judged the run
    # on ("0 errors" next to markers, or the reverse: an edited report, or one
    # left from an earlier run) is said, with both sources. The check keeps
    # the metric's verdict: it is what LibreLane decided on.
    dis_all = _drc_disagreements(run, details)
    for key, dis in dis_all.items():
        d = details[key]
        rep_n, mval = dis["report"], dis["metric"]
        d["disagree"] = dis
        if by.get(key):
            by[key]["note"] = ((by[key].get("note") or "") + " The report file lists " + str(int(rep_n)) +
                               (" marker" if rep_n == 1 else " markers") + " but the metric says " +
                               str(int(mval)) + ": they disagree.").strip()
    ir_m = {k: run.metrics.get(k) for k in ("ir__drop__worst", "ir__drop__avg", "ir__voltage__worst")
            if run.metrics.get(k) is not None}
    if ir_m:
        details["ir_metrics"] = ir_m
    return {
        "run_dir": str(run.dir),
        "tag": run.dir.name,
        "design": cfg.get("DESIGN_NAME"),
        "pdk": cfg.get("PDK"),
        "scl": cfg.get("STD_CELL_LIBRARY"),
        "flow": (meta or {}).get("flow") or run.gui.get("flow") or "",
        "librelane_version": (meta or {}).get("librelane_version"),
        "has_config": run.has_cfg,
        "metrics_from": run.metrics_from,
        "flow_state": flow,
        "checks": checks,
        "groups": groups,
        "stages": stages,
        "details": details,
        "verdict": verdict,
        # The five-state verdict the run lists use (same source, so Verify and
        # Runs can never disagree). "running" is decided by the caller.
        "run_verdict": _with_drc_flag(run, run_verdict_from(run, checks, flow, verdict),
                                      {k: d for k, d in dis_all.items() if d["metric"] == 0}),
    }
