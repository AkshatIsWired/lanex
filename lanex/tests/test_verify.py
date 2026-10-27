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
    # Setup, hold, DRC and LVS are the core results a ready verdict needs.
    run = _run(tmp_path, {
        "design__lint_error__count": 0,
        "timing__setup__ws": 0.5,
        "timing__hold__ws": 0.2,
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


# ---------------------------------------------------------------- LibreLane-exact rules
def _cfg_run(tmp_path: Path, metrics: dict, cfg: dict, *, steps=()) -> Path:
    run = _run(tmp_path, metrics, steps=steps)
    (run / "resolved.json").write_text(json.dumps(cfg), encoding="utf-8")
    return run


_CLEAN = {
    "timing__setup__ws": 1.0, "timing__hold__ws": 0.2,
    "magic__drc_error__count": 0, "klayout__drc_error__count": 0, "design__lvs_error__count": 0,
}


def _check(rep: dict, cid: str) -> dict:
    return next(c for c in rep["checks"] if c["id"] == cid)


def test_setup_violation_only_in_unchecked_corner_is_warning(tmp_path: Path):
    """LibreLane errors on setup violations only in TIMING_VIOLATION_CORNERS;
    other corners just warn (steps/checker.py TimingViolations)."""
    m = dict(_CLEAN, **{
        "timing__setup_vio__count": 3,
        "timing__setup_vio__count__corner:nom_tt_025C_1v80": 0,
        "timing__setup_vio__count__corner:nom_ss_100C_1v60": 3,
    })
    rep = verify.verify_report(_cfg_run(tmp_path, m, {"TIMING_VIOLATION_CORNERS": ["*tt*"]}))
    c = _check(rep, "setup")
    assert c["status"] == "warn" and c["gate"] == "warns"
    assert rep["verdict"]["state"] == "ready"
    gating = {r["corner"]: r["gating"] for r in c["corners"]}
    assert gating == {"nom_tt_025C_1v80": True, "nom_ss_100C_1v60": False}


def test_setup_violation_in_checked_corner_fails(tmp_path: Path):
    m = dict(_CLEAN, **{"timing__setup_vio__count__corner:nom_tt_025C_1v80": 2})
    rep = verify.verify_report(_cfg_run(tmp_path, m, {"TIMING_VIOLATION_CORNERS": ["*tt*"]}))
    assert _check(rep, "setup")["status"] == "fail"
    assert rep["verdict"]["state"] == "blocked"


def test_max_slew_only_warns_by_default(tmp_path: Path):
    """MAX_SLEW_VIOLATION_CORNERS defaults to [''] (no corner) -> warning."""
    m = dict(_CLEAN, **{"design__max_slew_violation__count__corner:max_ss_100C_1v60": 20})
    rep = verify.verify_report(_cfg_run(tmp_path, m, {}))
    assert _check(rep, "slew")["status"] == "warn"
    assert rep["verdict"]["ready"] is True


def test_error_on_switch_off_turns_failure_into_warning(tmp_path: Path):
    m = dict(_CLEAN, magic__drc_error__count=5)
    rep = verify.verify_report(_cfg_run(tmp_path, m, {"ERROR_ON_MAGIC_DRC": False}))
    c = _check(rep, "magic_drc")
    assert c["status"] == "warn" and "ERROR_ON_MAGIC_DRC = false" in c["gate_note"]
    # The page links "Decides" to that switch's line in resolved.json.
    assert c["error_var"] == "ERROR_ON_MAGIC_DRC"
    assert _check(rep, "setup")["corner_var"]


def test_only_critical_disconnected_pins_count(tmp_path: Path):
    """Checker.DisconnectedPins reads design__critical_disconnected_pin__count,
    not the total (which includes harmless unused outputs)."""
    m = dict(_CLEAN, design__disconnected_pin__count=4, design__critical_disconnected_pin__count=0)
    rep = verify.verify_report(_cfg_run(tmp_path, m, {}))
    assert _check(rep, "disc_pin")["status"] == "pass"


def test_raised_checker_wins_over_clean_metric(tmp_path: Path):
    """A checker dir with state_in.json but no state_out.json raised an error;
    that is a failure even if the metric now reads 0."""
    run = _cfg_run(tmp_path, dict(_CLEAN), {}, steps=[("Checker.LVS", False)])
    (run / "1-checker-lvs" / "state_in.json").write_text("{}", encoding="utf-8")
    rep = verify.verify_report(run)
    c = _check(rep, "lvs")
    assert c["status"] == "fail" and c["checker"]["outcome"] == "raised"
    assert rep["flow_state"]["state"] == "deferred_errors"


def test_turned_off_check_is_skipped_not_passed(tmp_path: Path):
    m = {k: v for k, v in _CLEAN.items() if k != "design__lvs_error__count"}
    rep = verify.verify_report(_cfg_run(tmp_path, m, {"RUN_LVS": False}))
    assert _check(rep, "lvs")["status"] == "skipped"
    v = rep["verdict"]
    assert v["state"] == "incomplete" and "lvs" in v["skipped_core"]


def test_stopped_flow_marks_later_checks_not_reached(tmp_path: Path):
    run = tmp_path / "runs" / "S"
    run.mkdir(parents=True)
    (run / "resolved.json").write_text("{}", encoding="utf-8")
    d = run / "01-verilator-lint"; d.mkdir(); (d / "state_in.json").write_text("{}"); (d / "state_out.json").write_text("{}")
    d = run / "02-checker-linterrors"; d.mkdir(); (d / "state_in.json").write_text("{}")
    rep = verify.verify_report(run)
    assert rep["flow_state"]["state"] == "stopped"
    assert _check(rep, "lint_errors")["status"] == "fail"
    lvs = _check(rep, "lvs")
    assert lvs["status"] == "not_run" and "stopped at step 2" in lvs["detail"]
    assert rep["verdict"]["ready"] is False


def test_antenna_violation_fails_like_manufacturability_report(tmp_path: Path):
    m = dict(_CLEAN, antenna__violating__nets=2, antenna__violating__pins=3)
    rep = verify.verify_report(_cfg_run(tmp_path, m, {}))
    assert _check(rep, "antenna")["status"] == "fail"


def test_rdb_summary_counts_categories_and_locations(tmp_path: Path):
    p = tmp_path / "drc.lyrdb"
    p.write_text(
        "<?xml version='1.0' encoding='utf8'?><report-database><categories>"
        "<category><name>met1.2</name><description>met1 spacing &lt; 0.14um</description></category>"
        "<category><name>poly.1a</name><description>poly width</description></category>"
        "</categories><cells><cell><name>top</name></cell></cells><items>"
        "<item><category>'met1.2'</category><cell>top</cell><values><value>polygon: (1,2;3,2;3,4;1,4)</value></values></item>"
        "<item><category>'met1.2'</category><cell>top</cell><values><value>box: (5,6;7,8)</value></values></item>"
        "</items></report-database>", encoding="utf-8")
    s = verify._rdb_summary(p)
    assert s["total"] == 2 and s["rules"] == 2
    cat = s["categories"][0]
    assert cat["name"] == "met1.2" and cat["count"] == 2 and cat["description"].startswith("met1 spacing")
    assert cat["samples"][0] == [1.0, 2.0, 3.0, 4.0]
    assert len(s["categories"]) == 1   # rules with no markers are not listed


def test_stopped_run_uses_last_finished_step_metrics(tmp_path: Path):
    """No final/metrics.json after a stop: the checks that ran are judged on
    the metrics LibreLane saved in the last finished step's state_out.json."""
    run = tmp_path / "runs" / "S"
    run.mkdir(parents=True)
    (run / "resolved.json").write_text("{}", encoding="utf-8")
    d = run / "01-verilator-lint"; d.mkdir()
    (d / "state_in.json").write_text("{}")
    (d / "state_out.json").write_text(json.dumps({"metrics": {"design__lint_error__count": 0}}))
    d = run / "02-checker-linterrors"; d.mkdir()
    (d / "state_in.json").write_text("{}")
    (d / "state_out.json").write_text(json.dumps({"metrics": {"design__lint_error__count": 0}}))
    d = run / "03-yosys-synthesis"; d.mkdir(); (d / "state_in.json").write_text("{}")
    rep = verify.verify_report(run)
    assert rep["metrics_from"]["n"] == 2
    assert _check(rep, "lint_errors")["status"] == "pass"
    assert rep["flow_state"]["state"] == "stopped" and rep["verdict"]["state"] == "stopped"
