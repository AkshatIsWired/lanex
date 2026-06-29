# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Tests for the Verification Center (Phase 1.A)."""
from __future__ import annotations

import json
from pathlib import Path

from lanex.controller import verify


def _run(tmp_path: Path, metrics: dict, *, steps=()) -> Path:
    run = tmp_path / "runs" / "R"
    (run / "final").mkdir(parents=True)
    (run / "final" / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    (run / "state_out.json").write_text("{}", encoding="utf-8")
    for i, (name, completed) in enumerate(steps, start=1):
        # LibreLane names step dirs <NNN>-<step-id-lowercased-dashed>.
        d = run / f"{i}-{name.lower().replace('.', '-')}"
        d.mkdir()
        if completed:
            (d / "state_out.json").write_text("{}", encoding="utf-8")
    return run


def test_clean_run_is_ready(tmp_path: Path):
    run = _run(tmp_path, {
        "design__lint_error__count": 0,
        "timing__setup__ws": 0.5,
        "magic__drc_error__count": 0,
        "klayout__drc_error__count": 0,
        "design__lvs_error__count": 0,
        "route__antenna_violation__count": 0,
    })
    rep = verify.verify_report(run)
    assert rep["verdict"]["ready"] is True
    assert rep["stages"]["physical"]["status"] == "pass"


def test_lint_error_flips_verdict(tmp_path: Path):
    run = _run(tmp_path, {"design__lint_error__count": 3})
    rep = verify.verify_report(run)
    assert rep["stages"]["rtl"]["status"] == "fail"
    assert rep["verdict"]["ready"] is False
    assert any("Lint errors" in b for b in rep["verdict"]["blockers"])


def test_negative_slack_fails_timing(tmp_path: Path):
    run = _run(tmp_path, {"timing__setup__ws": -0.8})
    rep = verify.verify_report(run)
    assert rep["stages"]["timing"]["status"] == "fail"


def test_missing_stage_is_absent_not_crash(tmp_path: Path):
    run = _run(tmp_path, {})  # no metrics at all
    rep = verify.verify_report(run)
    assert rep["stages"]["timing"]["status"] == "absent"


def test_incomplete_run_is_not_ready(tmp_path: Path):
    """A run with no signoff data must NOT read as tape-out ready (it's a third,
    'incomplete' state, never green)."""
    run = _run(tmp_path, {})  # no metrics -> gating stages absent
    v = verify.verify_report(run)["verdict"]
    assert v["ready"] is False
    assert v["incomplete"] is True
    assert "timing" in v["missing_stages"] and "physical" in v["missing_stages"]


def test_klayout_drc_is_gated(tmp_path: Path):
    """A KLayout-only DRC failure must flip the verdict (it used to be orphaned)."""
    run = _run(tmp_path, {
        "timing__setup__ws": 0.5,
        "magic__drc_error__count": 0,
        "route__drc_errors": 0,
        "design__lvs_error__count": 0,
        "klayout__drc_error__count": 4,  # KLayout DRC dirty, everything else clean
    })
    rep = verify.verify_report(run)
    checks = {c["id"]: c for c in rep["stages"]["physical"]["checks"]}
    assert checks["klayout_drc"]["status"] == "fail"
    assert rep["verdict"]["ready"] is False


def test_nan_slack_is_absent_not_fail(tmp_path: Path):
    """A NaN slack is a no-value → the check is omitted, never a false 'fail'."""
    run = _run(tmp_path, {"timing__setup__ws": float("nan"),
                          "magic__drc_error__count": 0})
    rep = verify.verify_report(run)
    ids = {c["id"] for c in rep["stages"]["timing"]["checks"]}
    assert "setup_ws" not in ids  # omitted, not reported as fail


def test_eqy_step_presence_is_pass(tmp_path: Path):
    run = _run(tmp_path, {}, steps=[("Yosys.EQY", True)])
    rep = verify.verify_report(run)
    checks = {c["id"]: c for c in rep["stages"]["synth"]["checks"]}
    assert checks["eqy"]["status"] == "pass"
