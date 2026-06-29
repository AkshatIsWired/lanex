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
    # FP_CORE_UTIL differs -> appears in config_diff.
    assert "FP_CORE_UTIL" in out["config_diff"]
    # PDK is identical -> not in diff.
    assert "PDK" not in out["config_diff"]
    # "best" must agree with the metric's own higher_is_better flag, whatever the
    # registry reports — A=-0.5/B=0.2 for ws, A=100/B=80 for area.
    ws_hib = out["metric_meta"]["timing__setup__ws"]["higher_is_better"]
    assert out["best"]["timing__setup__ws"] == ("B" if ws_hib else "A")
    area_hib = out["metric_meta"]["design__instance__area"]["higher_is_better"]
    assert out["best"]["design__instance__area"] == ("A" if area_hib else "B")
