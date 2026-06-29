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
"""Verification Center (Phase 1) — surface the signoff the flow already ran.

The ``Classic`` flow runs the full signoff suite on every RTL→GDS run (lint →
EQY → STA → DRC/LVS/antenna/XOR). This module **reads the artifacts that run
already wrote** and organizes them by stage with a single tape-out verdict. It
re-runs nothing and adds no dependency — pure stdlib + the existing
``history``/``reports`` controllers.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import history

# Stages that must have produced data before a run can be called tape-out ready.
# If either is ``absent`` the run did not reach signoff → the verdict is
# ``incomplete`` (never a green "ready"), not silently ready.
_GATING_STAGES = ("timing", "physical")


# Status values a check can carry.
_PASS, _FAIL, _WARN, _ABSENT = "pass", "fail", "warn", "absent"


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _check(cid: str, name: str, status: str, *, metric_keys: Optional[List[str]] = None,
           values: Optional[Dict[str, Any]] = None, detail: str = "",
           step_id: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": cid,
        "name": name,
        "status": status,
        "metric_keys": metric_keys or [],
        "values": values or {},
        "detail": detail,
        "step_id": step_id,
    }


def _count_status(metrics: Dict[str, Any], key: str) -> str:
    """pass if count==0, fail if >0, absent if the metric isn't present.

    A non-finite count (NaN/inf) is not a real count → ``absent`` (never coerced
    into a pass/fail), so a garbage value can't read as "0 violations".
    """
    v = _num(metrics.get(key))
    if v is None or not math.isfinite(v):
        return _ABSENT
    return _PASS if v == 0 else _FAIL


def _stage_status(checks: List[Dict[str, Any]]) -> str:
    statuses = [c["status"] for c in checks]
    if _FAIL in statuses:
        return _FAIL
    present = [s for s in statuses if s != _ABSENT]
    if not present:
        return _ABSENT
    if _WARN in statuses:
        return _WARN
    return _PASS


def _rtl_stage(metrics: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    err = _num(metrics.get("design__lint_error__count"))
    warn = _num(metrics.get("design__lint_warning__count"))
    tc = _num(metrics.get("design__lint_timing_construct__count"))
    if err is not None:
        checks.append(_check("lint_errors", "Lint errors", _PASS if err == 0 else _FAIL,
                             metric_keys=["design__lint_error__count"],
                             values={"design__lint_error__count": err}, step_id="Verilator.Lint"))
    if warn is not None:
        checks.append(_check("lint_warnings", "Lint warnings", _PASS if warn == 0 else _WARN,
                             metric_keys=["design__lint_warning__count"],
                             values={"design__lint_warning__count": warn}, step_id="Verilator.Lint"))
    if tc is not None:
        checks.append(_check("lint_timing_constructs", "Timing constructs in RTL",
                             _PASS if tc == 0 else _WARN,
                             metric_keys=["design__lint_timing_construct__count"],
                             values={"design__lint_timing_construct__count": tc},
                             step_id="Verilator.Lint"))
    return {"status": _stage_status(checks), "checks": checks}


def _synth_stage(metrics: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    # EQY equivalence: a completed step dir is the verdict (no failure metric).
    eqy_dir = _find_step_dir(run_dir, "Yosys.EQY")
    if eqy_dir is not None:
        ok = (eqy_dir / "state_out.json").is_file()
        checks.append(_check("eqy", "RTL ↔ netlist equivalence (formal)",
                             _PASS if ok else _FAIL, step_id="Yosys.EQY",
                             detail="Yosys EQY proves the gate netlist matches the RTL."))
    for key, name, cid in (
        ("design__instance_unmapped__count", "Unmapped cells", "unmapped"),
        ("synthesis__check_error__count", "Synthesis check errors", "synth_check"),
        ("design__inferred_latch__count", "Inferred latches", "latch"),
    ):
        st = _count_status(metrics, key)
        if st != _ABSENT:
            # latches/unmapped are warnings unless they're errors that gate.
            status = st
            if cid in ("latch",) and st == _FAIL:
                status = _WARN
            checks.append(_check(cid, name, status, metric_keys=[key],
                                 values={key: metrics.get(key)}))
    cell_count = _num(metrics.get("design__instance__count"))
    if cell_count is not None:
        checks.append(_check("cell_count", "Cell count", _PASS,
                             metric_keys=["design__instance__count"],
                             values={"design__instance__count": cell_count}))
    return {"status": _stage_status(checks), "checks": checks}


def _timing_stage(metrics: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def slack(cid: str, name: str, key: str) -> None:
        v = _num(metrics.get(key))
        # NaN slack = no value → omit (the stage reports it as absent), never a
        # false "fail". +inf slack = no constraining path → met (pass).
        if v is None or math.isnan(v):
            return
        status = _PASS if v >= 0 else _FAIL
        checks.append(_check(cid, name, status, metric_keys=[key], values={key: metrics.get(key)}))

    slack("setup_ws", "Worst setup slack", "timing__setup__ws")
    slack("setup_tns", "Total setup slack", "timing__setup__tns")
    slack("hold_ws", "Worst hold slack", "timing__hold__ws")
    slack("hold_tns", "Total hold slack", "timing__hold__tns")

    for key, name, cid in (
        ("timing__setup_vio__count", "Setup violations", "setup_vio"),
        ("timing__hold_vio__count", "Hold violations", "hold_vio"),
        ("design__max_slew_violation__count", "Max-slew violations", "slew_vio"),
        ("design__max_cap_violation__count", "Max-cap violations", "cap_vio"),
    ):
        st = _count_status(metrics, key)
        if st != _ABSENT:
            checks.append(_check(cid, name, st, metric_keys=[key], values={key: metrics.get(key)}))
    return {"status": _stage_status(checks), "checks": checks}


def _physical_stage(metrics: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    for key, name, cid, step in (
        ("magic__drc_error__count", "Magic DRC", "magic_drc", "Magic.DRC"),
        ("route__drc_errors", "Routing DRC", "route_drc", "OpenROAD.DetailedRouting"),
        ("klayout__drc_error__count", "KLayout DRC", "klayout_drc", "KLayout.DRC"),
        ("design__lvs_error__count", "LVS", "lvs", "Netgen.LVS"),
        ("design__disconnected_pin__count", "Disconnected pins", "disc_pin", None),
        ("design__xor_difference__count", "Mask XOR", "xor", "KLayout.XOR"),
    ):
        st = _count_status(metrics, key)
        if st != _ABSENT:
            checks.append(_check(cid, name, st, metric_keys=[key],
                                 values={key: metrics.get(key)}, step_id=step))
    # Antenna: violations may be repaired; non-zero remaining is a warn/fail.
    ant = _num(metrics.get("route__antenna_violation__count"))
    if ant is not None:
        checks.append(_check("antenna", "Antenna violations", _PASS if ant == 0 else _FAIL,
                             metric_keys=["route__antenna_violation__count"],
                             values={"route__antenna_violation__count": ant},
                             step_id="OpenROAD.CheckAntennas"))
    return {"status": _stage_status(checks), "checks": checks}


def _manufacturability_stage(metrics: Dict[str, Any], run_dir: Path) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    step = _find_step_dir(run_dir, "Misc.ReportManufacturability")
    if step is not None:
        checks.append(_check("manufacturability", "Manufacturability report",
                             _PASS if (step / "state_out.json").is_file() else _WARN,
                             step_id="Misc.ReportManufacturability",
                             detail="See the step report for density/manufacturability notes."))
    return {"status": _stage_status(checks), "checks": checks}


def _find_step_dir(run_dir: Path, step_id: str) -> Optional[Path]:
    want = step_id.lower().replace(".", "-")
    try:
        for e in sorted(run_dir.iterdir(), key=lambda d: d.name):
            if e.is_dir() and history._is_step_dir(e.name):
                suffix = "-".join(e.name.split("-")[1:])
                if suffix.lower() == want:
                    return e
    except Exception:
        pass
    return None


def _verdict(stages: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Roll the per-check statuses up into a single tape-out verdict.

    Three outcomes, never two: ``ready`` (green) requires no failing check AND the
    gating signoff stages (timing, physical) to be PRESENT; if a gating stage has
    no data the run hasn't reached signoff → ``incomplete`` (neutral), which is NOT
    ready. A failing check → not ready (and not incomplete). This is what stops an
    empty/partial/corrupt run from reading as "Tape-out ready".
    """
    blockers: List[str] = []
    warnings: List[str] = []
    for stage in stages.values():
        for c in stage["checks"]:
            if c["status"] == _FAIL:
                blockers.append(c["name"])
            elif c["status"] == _WARN:
                warnings.append(c["name"])
    missing = [s for s in _GATING_STAGES if stages.get(s, {}).get("status") == _ABSENT]
    incomplete = bool(missing)
    return {
        "ready": (not blockers) and not incomplete,
        "incomplete": incomplete,
        "missing_stages": missing,
        "blockers": blockers,
        "warnings": warnings,
    }


def verify_report(run_dir: str | Path) -> Dict[str, Any]:
    """Aggregate signoff status for a completed run, organized by stage.

    Reads ``final/metrics.json`` + the run's step dirs; never re-runs anything.
    A stage with no present data reports ``absent`` (not a crash). The verdict
    is ``ready`` when no check failed.
    """
    run = Path(run_dir).resolve()
    metrics = history._load_metrics(run)
    stages = {
        "rtl": _rtl_stage(metrics, run),
        "synth": _synth_stage(metrics, run),
        "timing": _timing_stage(metrics, run),
        "physical": _physical_stage(metrics, run),
        "manufacturability": _manufacturability_stage(metrics, run),
    }
    return {
        "run_dir": str(run),
        "tag": run.name,
        "stages": stages,
        "verdict": _verdict(stages),
    }
