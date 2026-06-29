# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for :mod:`lanex.controller.history`.

These build a synthetic run directory under ``tmp_path`` so they don't depend
on any real LibreLane install having ever run.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def _make_run(root: Path, *, tag: str = "RUN_2026-06-22_14-30-00", with_metrics: bool = True):
    runs = root / "runs"
    run = runs / tag
    run.mkdir(parents=True)
    cfg = {
        "meta": {"flow": "Classic"},
        "PDK": "sky130A",
        "STD_CELL_LIBRARY": "sky130_fd_sc_hd",
        "design_dir": str(root),
    }
    (run / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    if with_metrics:
        metrics = {
            "timing__setup__ws": -1.23,
            "timing__setup__tns": -12.0,
            "design__instance__area": 12345.6,
            "design__instance__count": 4321,
            "antenna__violating__nets": 0,
            "design__lvs_error__count": 0,
        }
        # LibreLane writes JSON either as `{"metrics": {...}}` or as flat.
        (run / "metrics.json").write_text(json.dumps({"metrics": metrics}), encoding="utf-8")
    # Root-level state_out.json signals run completion.
    (run / "state_out.json").write_text("{}", encoding="utf-8")
    # Two fake step folders.
    (run / "1-OpenROAD.Floorplan").mkdir()
    (run / "1-OpenROAD.Floorplan" / "state_out.json").write_text("{}", encoding="utf-8")
    (run / "2-OpenROAD.GeneratePDN").mkdir()
    (run / "2-OpenROAD.GeneratePDN" / "state_in.json").write_text("{}", encoding="utf-8")
    return run


def test_list_runs_on_missing_directory(tmp_path: Path):
    from lanex.controller import history

    assert history.list_runs(tmp_path) == []


def test_list_runs_summarises(tmp_path: Path):
    from lanex.controller import history

    _make_run(tmp_path)
    out = history.list_runs(tmp_path)
    assert len(out) == 1
    s = out[0]
    assert s["tag"].startswith("RUN_")
    assert s["pdk"] == "sky130A"
    assert s["scl"] == "sky130_fd_sc_hd"
    assert s["flow"] == "Classic"
    assert s["step_count"] >= 2
    assert s["steps_done"] >= 1
    assert s["key_metrics"]["timing__setup__ws"] == -1.23
    assert s["success"] is True


def test_get_run_returns_state_and_metrics(tmp_path: Path):
    from lanex.controller import history

    _make_run(tmp_path)
    runs = history.list_runs(tmp_path)
    view = history.get_run(runs[0]["run_dir"])
    assert view["tag"] == runs[0]["tag"]
    assert "metrics" in view and "values" in view["metrics"]
    assert view["metrics"]["values"]["timing__setup__ws"] == -1.23
    assert isinstance(view["summaries"], list)
    assert view["summaries"], "expected per-step summaries"


def test_diff_runs_detects_changed_metric(tmp_path: Path):
    from lanex.controller import history

    a = _make_run(tmp_path, tag="RUN_A")
    b = _make_run(tmp_path, tag="RUN_B")
    # Override B: bump timing, change area, keep LVS errors equal (should NOT
    # appear because both sides have the same value).
    metrics_b = {
        "metrics": {
            "timing__setup__ws": 0.5,
            "timing__setup__tns": -12.0,           # same as A
            "design__instance__area": 9999.0,      # changed vs A
            "design__instance__count": 4321,        # same
            "antenna__violating__nets": 0,          # same
            "design__lvs_error__count": 0,          # same
        }
    }
    (b / "metrics.json").write_text(json.dumps(metrics_b), encoding="utf-8")

    diff = history.diff_runs(a, b)
    delta = diff["metric_deltas"]
    assert "timing__setup__ws" in delta
    assert delta["timing__setup__ws"]["from"] == pytest.approx(-1.23)
    assert delta["timing__setup__ws"]["to"] == pytest.approx(0.5)
    # Equal-value metrics that exist on both => NOT a delta.
    assert "design__lvs_error__count" not in delta
    assert "design__instance__area" in delta


def _make_final(root: Path, tag: str = "RUN_FINAL"):
    """A run with a populated final/ dir (deliverables + json_h + metrics)."""
    run = root / "runs" / tag
    final = run / "final"
    (final / "render").mkdir(parents=True)
    (final / "render" / "spm.png").write_bytes(b"\x89PNG")
    (final / "gds").mkdir()
    (final / "gds" / "spm.gds").write_bytes(b"GDS")
    (final / "def").mkdir()
    (final / "def" / "spm.def").write_text("DEF")
    (final / "nl").mkdir()
    (final / "nl" / "spm.nl.v").write_text("module spm; endmodule")
    (final / "lib" / "nom_tt_025C_1v80").mkdir(parents=True)
    (final / "lib" / "nom_tt_025C_1v80" / "spm.lib").write_text("lib")
    (final / "metrics.csv").write_text("a,b\n1,2\n")
    (final / "metrics.json").write_text(json.dumps({
        "design__die__area": 11317.8,
        "design__die__bbox": "0.0 0.0 101.16 111.88",
        "design__core__area": 8051.47,
        "design__instance__utilization": 0.572805,
        "design__instance__count": 1489,
        "design__instance__area": 8051.47,
        "power__total": 0.00153,
        "route__wirelength": 6216,
        "timing__setup__ws": float("inf"),
        "timing__hold__ws": 0.1279,
        "design__lvs_error__count": 0,
        "magic__drc_error__count": 2,
    }))
    # JSON header for the I/O pin counter (32-bit bus + 4 scalars = 36 pins).
    (final / "json_h").mkdir()
    (final / "json_h" / "spm.h.json").write_text(json.dumps({
        "modules": {"spm": {"ports": {
            "clk": {"direction": "input", "bits": [2]},
            "rst": {"direction": "input", "bits": [3]},
            "x": {"direction": "input", "bits": list(range(4, 36))},
            "y": {"direction": "input", "bits": [36]},
            "p": {"direction": "output", "bits": [37]},
        }}}
    }))
    return run


def test_design_summary_has_key_stats(tmp_path: Path):
    from lanex.controller import history

    run = _make_final(tmp_path)
    rows = history.design_summary(run)
    by_label = {r["label"]: r for r in rows}
    assert by_label["Die area"]["value"] == 11317.8
    assert by_label["Die size"]["value"] == "101.16 × 111.88"
    assert by_label["Utilization"]["value"] == 57.3        # ratio -> percent
    assert by_label["Cell count"]["value"] == 1489
    assert by_label["I/O pins"]["value"] == 36             # buses expanded
    assert by_label["I/O ports"]["value"] == 5
    # Status flags: clean LVS passes, non-zero DRC fails.
    assert by_label["LVS errors"]["status"] == "pass"
    assert by_label["DRC errors (Magic)"]["status"] == "fail"
    # inf slack is carried through (status pass since >= 0).
    assert by_label["Worst setup slack"]["status"] == "pass"


def test_get_run_includes_summary_and_io(tmp_path: Path):
    from lanex.controller import history

    _make_final(tmp_path)
    view = history.get_run(tmp_path / "runs" / "RUN_FINAL")
    assert isinstance(view["summary"], list) and view["summary"]
    assert view["io"] == {"ports": 5, "pins": 36}


def test_list_run_outputs_groups_by_category(tmp_path: Path):
    from lanex.controller import history

    run = _make_final(tmp_path)
    outs = history.list_run_outputs(run)
    cats = {o["category"] for o in outs}
    assert {"Layout", "Netlist", "Timing", "Reports"} <= cats
    # Per-corner lib carries its corner as the variant.
    lib = [o for o in outs if o["format"] == "lib"][0]
    assert lib["variant"] == "nom_tt_025C_1v80"
    # Every entry is a real file path under final/.
    assert all(o["path"].startswith("final/") for o in outs)


def test_list_run_diagrams_finds_dot(tmp_path: Path):
    from lanex.controller import history

    step = tmp_path / "runs" / "T" / "06-yosys-synthesis"
    step.mkdir(parents=True)
    (step / "hierarchy.dot").write_text("digraph G { a->b; }")
    (step / "primitive_techmap.dot").write_text("digraph G { c->d; }")
    diags = history.list_run_diagrams(tmp_path / "runs" / "T")
    labels = {d["label"] for d in diags}
    assert "Design hierarchy (block diagram)" in labels
    assert "Gate-level schematic (post-techmap)" in labels
    assert all(d["step"] == "yosys-synthesis" for d in diags)


def test_render_dot_to_svg_or_graceful(tmp_path: Path):
    import shutil as _sh
    from lanex.controller import history

    step = tmp_path / "runs" / "T" / "06-yosys-synthesis"
    step.mkdir(parents=True)
    (step / "hierarchy.dot").write_text("digraph G { a->b->c; a->c; }")
    res = history.render_dot(tmp_path / "runs" / "T", "06-yosys-synthesis/hierarchy.dot")
    if _sh.which("dot"):
        assert res["ok"] is True
        svg = (tmp_path / "runs" / "T" / res["svg"]).read_text()
        assert svg.lstrip().startswith("<?xml") or "<svg" in svg
        # Second call hits the cache (svg newer than dot).
        assert history.render_dot(tmp_path / "runs" / "T", "06-yosys-synthesis/hierarchy.dot")["ok"]
    else:
        assert res["ok"] is False and res.get("need") == "graphviz"


def test_render_dot_rejects_non_dot(tmp_path: Path):
    from lanex.controller import history

    step = tmp_path / "runs" / "T"
    step.mkdir(parents=True)
    (step / "x.txt").write_text("nope")
    assert history.render_dot(step, "x.txt")["ok"] is False
