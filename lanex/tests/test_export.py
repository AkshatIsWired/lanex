# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Tests for run export + multi-run compare (Phase 0.4 / Phase 1.B)."""
from __future__ import annotations

import json
from pathlib import Path

from lanex.controller import history


def _make_run(root: Path, *, tag: str, metrics: dict, config: dict | None = None) -> Path:
    run = root / "runs" / tag
    (run / "final").mkdir(parents=True)
    (run / "final" / "metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    cfg = {"meta": {"flow": "Classic"}, "PDK": "sky130A", "STD_CELL_LIBRARY": "sky130_fd_sc_hd"}
    cfg.update(config or {})
    (run / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    (run / "state_out.json").write_text("{}", encoding="utf-8")
    return run


def test_export_csv(tmp_path: Path):
    run = _make_run(tmp_path, tag="R1", metrics={"design__instance__count": 100, "timing__setup__ws": 0.5})
    r = history.export_run(run, "csv")
    assert r["ok"]
    assert r["filename"].endswith(".csv")
    assert "metric,value" in r["text"]
    assert "design__instance__count,100" in r["text"]


def test_export_html_standalone(tmp_path: Path):
    run = _make_run(tmp_path, tag="R1", metrics={
        "design__instance__count": 100,
        "design__die__area": 5000.0,
        "magic__drc_error__count": 0,
        "timing__setup__ws": 0.4,
    })
    r = history.export_run(run, "html")
    assert r["ok"]
    assert "<!doctype html>" in r["text"].lower()
    assert "Tape-out ready" in r["text"]  # clean -> ready
    assert "R1" in r["text"]


def test_export_html_flags_drc_failure(tmp_path: Path):
    run = _make_run(tmp_path, tag="BAD", metrics={"magic__drc_error__count": 7})
    r = history.export_run(run, "html")
    assert "Not ready" in r["text"]


def test_export_unsupported_fmt(tmp_path: Path):
    run = _make_run(tmp_path, tag="R1", metrics={})
    r = history.export_run(run, "pdf")
    assert r["ok"] is False


def test_compare_runs(tmp_path: Path):
    a = _make_run(tmp_path, tag="A", metrics={"design__instance__area": 100.0, "timing__setup__ws": -0.5},
                  config={"FP_CORE_UTIL": 40})
    b = _make_run(tmp_path, tag="B", metrics={"design__instance__area": 80.0, "timing__setup__ws": 0.2},
                  config={"FP_CORE_UTIL": 55})
    out = history.compare_runs([a, b])
    assert {r["tag"] for r in out["runs"]} == {"A", "B"}
    # Every per-run table is keyed by the unique ``col`` (run_dir), NOT the tag.
    col = {r["tag"]: r["col"] for r in out["runs"]}
    assert col["A"] == str(a.resolve()) and col["B"] == str(b.resolve())
    # FP_CORE_UTIL differs -> appears in config_diff (inner keys are cols).
    assert "FP_CORE_UTIL" in out["config_diff"]
    assert set(out["config_diff"]["FP_CORE_UTIL"]) == {col["A"], col["B"]}
    # PDK is identical -> not in diff.
    assert "PDK" not in out["config_diff"]
    # "best" points at the winning run's COL, following the metric's registry
    # direction — A=-0.5/B=0.2 for ws, A=100/B=80 for area.
    ws_hib = out["metric_meta"]["timing__setup__ws"]["higher_is_better"]
    assert out["best"]["timing__setup__ws"] == (col["B"] if ws_hib else col["A"])
    area_hib = out["metric_meta"]["design__instance__area"]["higher_is_better"]
    assert out["best"]["design__instance__area"] == (col["A"] if area_hib else col["B"])


def test_compare_runs_same_tag_two_designs_no_collision(tmp_path: Path):
    """N1: two designs each with a run named 'baseline' must NOT collapse onto
    one column. Before the fix the tag-keyed table showed only the second
    design's numbers under a single 'baseline' column (silent Fear-F/M)."""
    da = tmp_path / "spm"
    db = tmp_path / "processor"
    a = _make_run(da, tag="baseline", metrics={"design__instance__count": 100.0},
                  config={"FP_CORE_UTIL": 40})
    b = _make_run(db, tag="baseline", metrics={"design__instance__count": 999.0},
                  config={"FP_CORE_UTIL": 55})
    out = history.compare_runs([a, b])
    # Two distinct columns, both tagged 'baseline' but disambiguated by design.
    assert len(out["runs"]) == 2
    assert [r["tag"] for r in out["runs"]] == ["baseline", "baseline"]
    assert {r["design"] for r in out["runs"]} == {"spm", "processor"}
    cols = [r["col"] for r in out["runs"]]
    assert len(set(cols)) == 2  # never merged
    per = out["metric_table"]["design__instance__count"]
    # BOTH runs' own values survive, keyed by their own col — not overwritten.
    assert per[str(a.resolve())] == 100.0
    assert per[str(b.resolve())] == 999.0
    # config_diff also keeps both (FP_CORE_UTIL 40 vs 55).
    assert set(out["config_diff"]["FP_CORE_UTIL"]) == {str(a.resolve()), str(b.resolve())}


def test_compare_best_skips_unknown_direction_metric(tmp_path: Path):
    """N8: a metric NOT in the registry has no known optimisation direction, so
    ``best`` must not guess (and highlight the worse run). It is simply absent."""
    a = _make_run(tmp_path, tag="A", metrics={"custom__unregistered__metric": 5.0})
    b = _make_run(tmp_path, tag="B", metrics={"custom__unregistered__metric": 9.0})
    out = history.compare_runs([a, b])
    assert "custom__unregistered__metric" in out["metric_table"]
    assert out["metric_meta"]["custom__unregistered__metric"]["direction_known"] is False
    assert "custom__unregistered__metric" not in out["best"]
