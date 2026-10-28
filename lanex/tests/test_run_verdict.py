# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""One run verdict for every page (Runs, run bar, Analytics, Verify), and a
run order that annotating a run never changes."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from lanex.controller import history, verify

CLEAN = {
    "design__lint_error__count": 0,
    "timing__setup__ws": 0.5,
    "timing__hold__ws": 0.2,
    "magic__drc_error__count": 0,
    "klayout__drc_error__count": 0,
    "design__lvs_error__count": 0,
    "route__antenna_violation__count": 0,
}


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))
    history._SUMMARY_CACHE.clear()
    history._START_CACHE.clear()


def _run(design: Path, tag: str, metrics=None, *, steps=(("Yosys.Synthesis", True),),
         final=True, gui=None, error_log="") -> Path:
    run = design / "runs" / tag
    run.mkdir(parents=True)
    (run / "resolved.json").write_text("{}", encoding="utf-8")
    if final:
        (run / "final").mkdir()
        (run / "final" / "metrics.json").write_text(json.dumps(metrics or {}), encoding="utf-8")
    for i, (name, done) in enumerate(steps, start=1):
        d = run / f"{i}-{name.lower().replace('.', '-')}"
        d.mkdir()
        (d / "state_in.json").write_text("{}", encoding="utf-8")
        if done:
            (d / "state_out.json").write_text("{}", encoding="utf-8")
    if gui is not None:
        (run / "gui-run.json").write_text(json.dumps(gui), encoding="utf-8")
    if error_log:
        (run / "error.log").write_text(error_log, encoding="utf-8")
    return run


def test_clean_run_passes_and_matches_verify(tmp_path):
    run = _run(tmp_path, "R", CLEAN)
    v = verify.run_verdict(run)
    assert v["state"] == "passed" and v["label"] == "Clean"
    assert verify.verify_report(run)["run_verdict"]["state"] == "passed"
    s = history.list_runs(tmp_path)[0]
    assert s["verdict"]["state"] == "passed" and s["success"] is True


def test_no_lvs_is_incomplete_not_clean(tmp_path):
    # The case Analytics used to call "Clean run: all N checks passed".
    m = dict(CLEAN)
    m.pop("design__lvs_error__count")
    run = _run(tmp_path, "R", m)
    assert verify.run_verdict(run)["state"] == "incomplete"
    s = history.list_runs(tmp_path)[0]
    assert s["verdict"]["state"] == "incomplete" and s["success"] is False


def test_error_on_switch_off_is_honoured(tmp_path):
    # ERROR_ON_KLAYOUT_DRC = false: LibreLane only warns, so the run passes
    # (the old fixed fail list called it failed).
    m = dict(CLEAN, klayout__drc_error__count=3)
    run = _run(tmp_path, "R", m)
    (run / "resolved.json").write_text(json.dumps({"ERROR_ON_KLAYOUT_DRC": False}), encoding="utf-8")
    v = verify.run_verdict(run)
    assert v["state"] == "passed" and "warning" in v["label"]


def test_blocking_check_fails_with_stage(tmp_path):
    run = _run(tmp_path, "R", dict(CLEAN, magic__drc_error__count=4))
    v = verify.run_verdict(run)
    assert v["state"] == "failed" and v["label"] == "1 check failed"
    assert v["stage"] == "signoff"


def test_raised_step_is_failed_and_cancel_is_stopped(tmp_path):
    steps = (("Yosys.Synthesis", True), ("OpenROAD.CTS", False))
    failed = _run(tmp_path, "F", final=False, steps=steps, error_log="[ERROR] boom\n")
    v = verify.run_verdict(failed)
    assert v["state"] == "failed" and v["label"] == "Failed at step 2" and v["stage"] == "cts"
    stopped = _run(tmp_path, "S", final=False, steps=steps, gui={"outcome": {"result": "cancelled"}})
    v = verify.run_verdict(stopped)
    assert v["state"] == "stopped" and v["label"] == "Stopped at step 2"


def test_live_run_reads_running(tmp_path):
    run = _run(tmp_path, "L", final=False, steps=(("Yosys.Synthesis", True), ("OpenROAD.Floorplan", False)))
    runs = history.mark_live(history.list_runs(tmp_path), str(run))
    assert runs[0]["verdict"]["state"] == "running" and runs[0]["success"] is False
    # the cached summary is not changed by the overlay
    assert history.list_runs(tmp_path)[0]["verdict"]["state"] != "running"


def test_annotating_an_old_run_keeps_the_order(tmp_path):
    old = _run(tmp_path, "old", CLEAN)
    new = _run(tmp_path, "new", CLEAN)
    t0 = time.time() - 3600
    for p in [old / "resolved.json", old]:
        os.utime(p, (t0, t0))
    for p in [new / "resolved.json", new]:
        os.utime(p, (t0 + 600, t0 + 600))
    assert [r["tag"] for r in history.list_runs(tmp_path)] == ["new", "old"]
    started = history.list_runs(tmp_path)[1]["started_at"]
    history.set_pin(old, True)                 # writes .gui-pin into the folder
    (old / ".gui-note.txt").write_text("best so far", encoding="utf-8")
    runs = history.list_runs(tmp_path)
    assert [r["tag"] for r in runs] == ["new", "old"]
    assert runs[1]["started_at"] == started and runs[1]["pinned"] is True


def test_resumed_run_counts_reused_steps(tmp_path):
    steps = (("Yosys.Synthesis", True), ("OpenROAD.Floorplan", True), ("OpenROAD.CTS", True))
    _run(tmp_path, "parent", CLEAN, steps=steps)
    child = _run(tmp_path, "child", CLEAN, steps=(("OpenROAD.Floorplan", True), ("OpenROAD.CTS", True)),
                 gui={"branched_from": {"tag": "parent", "step": "OpenROAD.Floorplan"}})
    s = next(r for r in history.list_runs(tmp_path) if r["tag"] == "child")
    assert s["branched_from"] == "parent"
    assert s["steps_reused"] == 1 and s["step_count"] == 3 and s["steps_done"] == 3
    assert child.is_dir()


def test_negative_slack_in_a_warning_corner_is_never_clean(tmp_path):
    # Setup misses only in a corner outside TIMING_VIOLATION_CORNERS: LibreLane
    # warns and passes the run, but LanEx must not call it clean.
    m = dict(CLEAN)
    m.update({"timing__setup__ws": -0.43, "timing__setup__ws__corner:max_ss_100C_1v60": -0.43,
              "timing__setup__ws__corner:nom_tt_025C_1v80": 0.8,
              "timing__setup_vio__count": 3, "timing__setup_vio__count__corner:max_ss_100C_1v60": 3,
              "timing__setup_vio__count__corner:nom_tt_025C_1v80": 0})
    run = _run(tmp_path, "R", m)
    (run / "resolved.json").write_text(json.dumps({"TIMING_VIOLATION_CORNERS": ["*tt*"]}), encoding="utf-8")
    v = verify.run_verdict(run)
    # Not "failed" (LibreLane passed it), never "passed"/"Clean": warning.
    assert v["state"] == "warning"
    assert v["label"] == "Finished: timing misses in the slow corner (setup -0.43 ns)"
    assert v["timing_miss"]["corner"] == "max_ss_100C_1v60"
    assert history.list_runs(tmp_path)[0]["success"] is False
