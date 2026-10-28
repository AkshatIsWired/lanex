# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Sweeps inside Runs: points named by value, real outcomes, persisted results,
and the Runs table's origin / summary fields."""
from __future__ import annotations

import json
import time
from pathlib import Path

from lanex.controller import dse, history


def _drain(job, n=300):
    for _ in range(n):
        if not job.active:
            return
        time.sleep(0.02)
    raise AssertionError("sweep thread never finished")


# ---------------------------------------------------------------- naming
def test_points_are_named_by_value(tmp_path):
    tags = dse.sweep_run_tags(tmp_path, [{"FP_CORE_UTIL": "35"}, {"FP_CORE_UTIL": "65"}])
    assert tags == ["sweep-util-35", "sweep-util-65"]


def test_two_variables_and_unknown_vars_and_odd_values(tmp_path):
    tags = dse.sweep_run_tags(tmp_path, [{"FP_CORE_UTIL": "50", "CLOCK_PERIOD": "12.5"},
                                         {"SYNTH_STRATEGY": "AREA 0"},
                                         {"GRT_LAYER_ADJUSTMENTS": "0.1,0.2"}])
    assert tags[0] == "sweep-util-50-clk-12.5"
    assert tags[1] == "sweep-synth-AREA_0"
    assert tags[2].startswith("sweep-grt_layer_adjustments-0.1_0.2")
    assert all("/" not in t and " " not in t for t in tags)


def test_names_never_overwrite_an_earlier_run(tmp_path):
    (tmp_path / "runs" / "sweep-util-50").mkdir(parents=True)
    tags = dse.sweep_run_tags(tmp_path, [{"FP_CORE_UTIL": "50"}, {"FP_CORE_UTIL": "50"}])
    assert tags == ["sweep-util-50-2", "sweep-util-50-3"]


# ---------------------------------------------------------------- outcome
def test_a_launched_but_failed_point_is_failed_with_its_reason():
    job = dse.DseJob()
    seen = []

    def start_one(tag, ov):
        if tag == "b":
            return {"ok": False, "kind": "halted", "stage": "place", "step": "OpenROAD.DetailedPlacement",
                    "reason": "Detailed placement failed (DPL-0036)"}
        return {"ok": True, "kind": "clean", "stage": None, "step": None, "reason": None}

    res = job.start(start_one=start_one, overrides_list=[{"X": "1"}, {"X": "2"}, {"X": "3"}],
                    tags=["a", "b", "c"], sweep_id="s1", on_point=lambda t, r: seen.append((t, r["ok"])))
    assert res["ok"]
    _drain(job)
    st = job.status()
    assert st["done"] == ["a", "c"] and st["failed"] == ["b"]
    assert st["results"]["b"]["reason"].endswith("(DPL-0036)")
    assert st["results"]["b"]["stage"] == "place"
    assert st["results"]["b"]["values"] == {"X": "2"}
    assert st["sweep_id"] == "s1" and st["total"] == 3
    assert seen == [("a", True), ("b", False), ("c", True)]


def test_bare_bool_results_still_work():
    job = dse.DseJob()
    job.start(start_one=lambda t, o: t != "b", overrides_list=[{}, {}], tags=["a", "b"])
    _drain(job)
    assert job.done == ["a"] and job.failed == ["b"]
    assert job.results["b"]["reason"] == "did not start"


def test_stop_when_one_is_good_enough():
    job = dse.DseJob()
    ran = []

    def start_one(tag, ov):
        ran.append(tag)
        return {"ok": tag == "b", "kind": "clean" if tag == "b" else "checks-failed"}

    job.start(start_one=start_one, overrides_list=[{}, {}, {}, {}], tags=["a", "b", "c", "d"],
              stop_when_good=True)
    _drain(job)
    assert ran == ["a", "b"]
    assert job.status()["stopped_early"] is True
    assert job.status()["queued"] == []


def test_point_outcome_of_a_halted_folder(tmp_path):
    # A run folder whose only step started but never finished, with an error log.
    run = tmp_path / "runs" / "sweep-util-65"
    step = run / "01-openroad-detailedplacement"
    step.mkdir(parents=True)
    (step / "state_in.json").write_text("{}")
    (run / "error.log").write_text("[ERROR DPL-0036] Detailed placement failed.\n")
    out = dse.point_outcome(run)
    assert out["ok"] is False
    assert out["kind"] in ("halted", "incomplete")
    assert out["reason"]


def test_results_persist_in_the_manifest(tmp_path):
    dse.record_sweep(tmp_path, {"id": "s9", "created_at": "2026-10-28T10:00:00", "tags": ["a"]})
    dse.record_point(tmp_path, "s9", "a", {"ok": False, "kind": "halted", "reason": "boom"})
    sw = dse.load_sweeps(tmp_path)[0]
    assert sw["results"]["a"]["reason"] == "boom"


# ---------------------------------------------------------------- origin
def test_run_origin_kinds(tmp_path):
    a = tmp_path / "a"; a.mkdir()
    assert history.run_origin(a) == {"kind": "manual"}
    b = tmp_path / "b"; b.mkdir()
    (b / "gui-run.json").write_text(json.dumps({"branched_from": {
        "tag": "sweep-util-65", "step": "OpenROAD.Floorplan", "stage": "floorplan",
        "changes": [{"var": "FP_CORE_UTIL", "from": "65", "to": "55"}]}}))
    o = history.run_origin(b)
    assert o["kind"] == "fix" and o["parent"] == "sweep-util-65" and o["changes"][0]["to"] == "55"
    c = tmp_path / "c"; c.mkdir()
    dse.stamp_run(c, "s1", {"FP_CORE_UTIL": "45"})
    assert history.run_origin(c) == {"kind": "sweep", "sweep_id": "s1", "values": {"FP_CORE_UTIL": "45"}}


def test_summary_carries_the_table_fields(tmp_path):
    run = tmp_path / "runs" / "r1"
    (run / "final").mkdir(parents=True)
    (run / "final" / "metrics.json").write_text(json.dumps({
        "timing__setup__ws": 4.1, "timing__hold__ws": 0.28, "design__die__area": 10367.1,
        "design__instance__area__stdcell": 4546.86, "design__instance__utilization": 0.63,
        "power__total": 0.00147, "magic__drc_error__count": 0}))
    (run / ".gui-note.txt").write_text("try lower util")
    s = history.list_runs(tmp_path)[0]
    km = s["key_metrics"]
    assert km["timing__hold__ws"] == 0.28 and km["design__instance__area__stdcell"] == 4546.86
    assert km["power__total"] == 0.00147
    assert s["note"] == "try lower util"
    assert s["origin"] == {"kind": "manual"}
