# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Lock-in tests for the post-audit round (P0 fixes + new features).

Pure / tool-free where possible; real-run-dependent tests skip gracefully when
the bundled ``spm_example`` run output isn't present.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from lanex.controller import (
    bundle,
    dse,
    history,
    manualcmd,
    platform_env,
    runtimings,
    timing,
)

REPO = Path(__file__).resolve().parents[2]
SPM_RUN = REPO / "spm_example" / "runs" / "test-2-new"


# --------------------------------------------------------------------------
# P0 #1 — CLI reveal mirrors the runner (includes --docker-no-tty)
# --------------------------------------------------------------------------

def test_cli_command_container_includes_docker_no_tty():
    cmd = manualcmd.cli_command_for(
        design_dir="/d", config_file="/d/config.json", run_mode="container",
        pdk="sky130A", pdk_root="/root",
    )
    c = cmd["container"]
    assert "--docker-no-tty" in c
    # ...and it must come before --dockerized (host-side flag ordering).
    assert c.index("--docker-no-tty") < c.index("--dockerized")


# --------------------------------------------------------------------------
# P0 #5 — manual console narrows docker/podman to read-only subcommands
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cmd,ok", [
    ("docker ps", True),
    ("docker images", True),
    ("docker pull alpine", True),
    ("docker image inspect alpine", True),
    ("podman info", True),
    ("docker run -v /:/host alpine sh", False),
    ("docker exec x sh", False),
    ("docker image rm alpine", False),
    ("docker volume create x", False),
    ("podman cp a b", False),
])
def test_manual_docker_subcommand_allowlist(cmd, ok):
    assert manualcmd.validate(cmd)["ok"] is ok


def test_manual_still_blocks_sudo_and_shell_ops():
    assert manualcmd.validate("sudo rm -rf /")["ok"] is False
    assert manualcmd.validate("yosys -version | grep x")["ok"] is False


# --------------------------------------------------------------------------
# P0 #4 — DSE sweep manifest + overwrite-prevention
# --------------------------------------------------------------------------

def test_dse_unique_base_tag_avoids_existing(tmp_path):
    runs = tmp_path / "runs"
    (runs / "dse-mychip-00").mkdir(parents=True)
    (runs / "dse-mychip-01").mkdir()
    # First sweep's dirs exist → a new sweep must pick a different base.
    base = dse.unique_base_tag(tmp_path, "mychip", 2)
    assert base != "mychip"
    tags = dse.dse_run_tags(base, 2)
    assert not any((runs / t).exists() for t in tags)


def test_dse_unique_base_tag_clean_dir(tmp_path):
    assert dse.unique_base_tag(tmp_path, "fresh", 3) == "fresh"


def test_dse_record_and_load_sweeps(tmp_path):
    sid = dse.new_sweep_id()
    dse.record_sweep(tmp_path, {"id": sid, "base": "x", "created_at": "2026-06-28T00:00:00",
                                "axes": [], "tags": ["dse-x-00"], "count": 1})
    sweeps = dse.load_sweeps(tmp_path)
    assert len(sweeps) == 1 and sweeps[0]["id"] == sid
    # Re-record same id replaces, doesn't duplicate.
    dse.record_sweep(tmp_path, {"id": sid, "base": "x2", "created_at": "2026-06-28T00:01:00",
                                "tags": [], "count": 0})
    sweeps = dse.load_sweeps(tmp_path)
    assert len(sweeps) == 1 and sweeps[0]["base"] == "x2"


# --------------------------------------------------------------------------
# P0 #9 — host display guard for desktop tools
# --------------------------------------------------------------------------

def test_host_display_available(monkeypatch):
    import lanex.controller.platform_env as pe
    monkeypatch.setattr(pe.sys, "platform", "linux")
    monkeypatch.setattr(pe.os, "name", "posix")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    assert pe.host_display_available() is False
    monkeypatch.setenv("DISPLAY", ":0")
    assert pe.host_display_available() is True


def test_desktop_open_in_tool_no_display(monkeypatch, tmp_path):
    from lanex.controller import desktop
    f = tmp_path / "x.gds"
    f.write_text("x")
    monkeypatch.setattr(desktop, "_resolve_bin", lambda spec: "/usr/bin/klayout")
    monkeypatch.setattr(platform_env, "host_display_available", lambda: False)
    r = desktop.open_in_tool("klayout", f)
    assert r["ok"] is False and r.get("need") == "display"


# --------------------------------------------------------------------------
# P0 #8 — WSL path translation is a no-op off WSL
# --------------------------------------------------------------------------

def test_wsl_windows_path_off_wsl(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    assert platform_env.wsl_windows_path("/home/x") is None


# --------------------------------------------------------------------------
# P0 #10 — path confinement has no unsafe string-prefix fallback
# --------------------------------------------------------------------------

def test_path_within_roots_rejects_sibling_prefix(monkeypatch, tmp_path):
    from lanex.server import routes
    root = tmp_path / "root"
    root.mkdir()
    sibling = tmp_path / "root2"
    sibling.mkdir()
    monkeypatch.setattr(routes, "_read_roots", lambda: [root.resolve()])
    assert routes._path_within_roots(str(root / "a.txt")) is True
    # `/tmp/root2` must NOT be considered inside `/tmp/root` (the old startswith bug).
    assert routes._path_within_roots(str(sibling / "a.txt")) is False


# --------------------------------------------------------------------------
# Timing feature — parser is the heart of it
# --------------------------------------------------------------------------

_SAMPLE = """
======================= nom_tt_025C_1v80 Corner ====================

Startpoint: y (input port clocked by clk)
Endpoint: _419_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

Fanout  Cap  Slew  Delay  Time  Description
                       9.995111   data required time
                      -3.960954   data arrival time
-------------------------------------------------------------------
                       6.034157   slack (MET)

Startpoint: a (input)
Endpoint: _500_ (flip-flop)
Path Group: clk
Path Type: max
                       1.000000   data required time
                      -2.000000   data arrival time
                      -1.000000   slack (VIOLATED)
"""


def test_timing_parse_report_checks():
    paths = timing.parse_report_checks(_SAMPLE)
    assert len(paths) == 2
    p0 = paths[0]
    assert p0["startpoint"] == "y" and p0["endpoint"] == "_419_"
    assert p0["group"] == "clk" and p0["type"] == "max"
    assert p0["corner"] == "nom_tt_025C_1v80"
    assert abs(p0["slack"] - 6.034157) < 1e-6 and p0["met"] is True
    assert paths[1]["met"] is False and abs(paths[1]["slack"] + 1.0) < 1e-6


def test_timing_histogram_shape():
    h = timing._histogram([1.0, 2.0, 3.0, 4.0], bins=4)
    assert len(h["bins"]) == 4 and sum(h["counts"]) == 4


@pytest.mark.skipif(not SPM_RUN.is_dir(), reason="bundled spm_example run not present")
def test_timing_paths_on_real_run():
    r = timing.timing_paths(SPM_RUN, kind="setup", limit=10)
    assert r["ok"] is True
    assert r["total"] > 0
    assert r["paths"] and "slack" in r["paths"][0]
    # sorted worst-first
    slacks = [p["slack"] for p in r["paths"]]
    assert slacks == sorted(slacks)


# --------------------------------------------------------------------------
# Run notes
# --------------------------------------------------------------------------

def test_run_note_roundtrip(tmp_path):
    assert history.read_note(tmp_path) == ""
    res = history.write_note(tmp_path, "best QoR so far")
    assert res["ok"] is True
    assert history.read_note(tmp_path) == "best QoR so far"
    # Empty note removes the file.
    history.write_note(tmp_path, "")
    assert not (tmp_path / ".gui-note.txt").exists()


def test_run_note_missing_dir():
    assert history.write_note("/no/such/dir/xyz", "x")["ok"] is False


# --------------------------------------------------------------------------
# Metric trends
# --------------------------------------------------------------------------

def _make_run(design: Path, tag: str, metrics: dict):
    rd = design / "runs" / tag / "final"
    rd.mkdir(parents=True)
    (rd / "metrics.json").write_text(json.dumps(metrics))
    return design / "runs" / tag


def test_metric_trends(tmp_path):
    _make_run(tmp_path, "r1", {"design__instance__area": 100.0, "timing__setup__ws": 1.0})
    _make_run(tmp_path, "r2", {"design__instance__area": 120.0, "timing__setup__ws": 0.5})
    t = history.metric_trends(tmp_path)
    assert t["ok"] is True
    assert len(t["runs"]) == 2
    assert "design__instance__area" in t["series"]
    assert len(t["series"]["design__instance__area"]) == 2


# --------------------------------------------------------------------------
# Support bundle
# --------------------------------------------------------------------------

def test_bundle_build(tmp_path):
    run = tmp_path / "runs" / "r1"
    (run / "final").mkdir(parents=True)
    (run / "config.json").write_text('{"PDK":"sky130A"}')
    (run / "resolved.json").write_text('{"PDK":"sky130A","CLOCK_PERIOD":10}')
    (run / "final" / "metrics.json").write_text('{"design__instance__area":42,"x":1}')
    step = run / "12-openroad-sta"
    step.mkdir()
    (step / "max.rpt").write_text("slack (MET)")
    # Full bundle (include=None → everything).
    blob = bundle.build_bundle(run)
    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = zf.namelist()
    assert "MANIFEST.json" in names
    assert "config/config.json" in names      # config now under config/
    assert "metrics.csv" in names             # metrics emitted as a CSV
    assert "settings.csv" in names
    assert "analytics.csv" in names
    assert any(n.endswith("max.rpt") for n in names)
    assert json.loads(zf.read("MANIFEST.json"))["run_tag"] == "r1"
    # The metrics CSV carries the real metric.
    assert "design__instance__area" in zf.read("metrics.csv").decode()


def test_bundle_selective_include(tmp_path):
    run = tmp_path / "runs" / "r2"
    (run / "final").mkdir(parents=True)
    (run / "config.json").write_text('{"PDK":"sky130A"}')
    (run / "final" / "metrics.json").write_text('{"x":1}')
    # Only metrics_csv requested → no config/, no settings/analytics.
    blob = bundle.build_bundle(run, include=["metrics_csv"])
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert "metrics.csv" in names
    assert "config/config.json" not in names
    assert "settings.csv" not in names
    # Legacy mode= still works (minimal → config + the CSVs + reports, no logs).
    blob2 = bundle.build_bundle(run, mode="minimal")
    names2 = zipfile.ZipFile(io.BytesIO(blob2)).namelist()
    assert "config/config.json" in names2


def test_bundle_missing_run():
    with pytest.raises(FileNotFoundError):
        bundle.build_bundle("/no/such/run")


# --------------------------------------------------------------------------
# Run ETA store
# --------------------------------------------------------------------------

def test_runtimings_record_and_estimate(tmp_path, monkeypatch):
    monkeypatch.setenv("LIBRELANE_GUI_HOME", str(tmp_path))
    runtimings.record("Yosys.Synthesis", 30.0)
    runtimings.record("OpenROAD.GlobalRoute", 120.0)
    data = runtimings.load()
    assert "Yosys.Synthesis" in data and data["Yosys.Synthesis"]["ewma"] > 0
    # Known steps → sum of their learned estimates.
    est = runtimings.estimate_remaining(["Yosys.Synthesis", "OpenROAD.GlobalRoute"])
    assert est is not None and est > 100
    # Unknown step with no history + no observed → None.
    assert runtimings.estimate_remaining(["Totally.Unknown.Step"]) is None
    # Unknown step but with an observed average → uses the average.
    assert runtimings.estimate_remaining(["Totally.Unknown.Step"], observed=[10.0]) == pytest.approx(10.0)
