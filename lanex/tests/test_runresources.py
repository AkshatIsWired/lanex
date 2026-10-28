# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Thread counts sized to the PC (runresources), the config-wins rule, the
gui-run.json record, the low-memory heads-up and log-line batching."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from lanex.controller import runresources as rr

ALL = set(rr.THREAD_VARS)


def _v(cores, avail, **kw):
    return rr.size_threads(cores, avail, **kw)["values"]


# ------------------------------------------------------------- sizing rules

def test_strong_pc_caps_router_and_klayout():
    # 32 threads, 44 GB free (this dev PC): DRT capped at 16, KLayout at 8,
    # STA = every corner when the corner count is known.
    v = _v(32, 44.1, corners=9)
    assert v == {"DRT_THREADS": 16, "KLAYOUT_DRC_THREADS": 8, "KLAYOUT_XOR_THREADS": 8,
                 "KLAYOUT_DENSITY_THREADS": 8, "STA_THREADS": 9}


def test_low_spec_laptop():
    # 8 GB / 4-core laptop: WSL gets ~4 GB, ~3 GB free at run start.
    v = _v(4, 3.0, corners=9)
    assert v["DRT_THREADS"] == 4          # floor((3-2)/0.25) = 4, = cores
    assert v["KLAYOUT_DRC_THREADS"] == 2  # < 4 GB free
    assert v["KLAYOUT_XOR_THREADS"] == 2
    assert v["STA_THREADS"] == 3          # floor(3 GB) corners at once


@pytest.mark.parametrize("cores,avail,drt,kl,sta", [
    (4, 3.0, 4, 2, 3),
    (4, 7.0, 4, 4, 4),
    (8, 3.0, 4, 2, 3),
    (8, 7.0, 8, 8, 7),
    (8, 15.0, 8, 8, 8),
    (16, 7.0, 16, 8, 7),
    (16, 15.0, 16, 8, 9),
    (32, 7.0, 16, 8, 7),
    (32, 15.0, 16, 8, 9),
    (32, 30.0, 16, 8, 9),
    (2, 1.5, 1, 2, 1),
    (1, 0.5, 1, 1, 1),
])
def test_sizing_table(cores, avail, drt, kl, sta):
    v = _v(cores, avail, corners=9)
    assert v["DRT_THREADS"] == drt
    assert v["KLAYOUT_DRC_THREADS"] == v["KLAYOUT_XOR_THREADS"] == kl
    assert v["STA_THREADS"] == sta


def test_router_memory_bound():
    # 5 GB free: floor((5-2)/0.25) = 12 threads even with 32 cores.
    assert _v(32, 5.0)["DRT_THREADS"] == 12


def test_sta_without_known_corners_is_cores_and_memory():
    assert _v(32, 44.0)["STA_THREADS"] == 32
    assert _v(32, 6.4)["STA_THREADS"] == 6


def test_never_below_one_thread():
    v = _v(1, 0.0)
    assert all(n == 1 for n in v.values())


def test_unreadable_pc_sets_nothing():
    assert _v(None, 8.0) == {}
    assert _v(8, None) == {}


def test_only_variables_the_flow_reads():
    # The Optimizing flow reads only STA_THREADS; Classic has no Density step.
    assert set(_v(8, 8.0, flow_vars={"STA_THREADS"})) == {"STA_THREADS"}
    classic = {"DRT_THREADS", "KLAYOUT_DRC_THREADS", "KLAYOUT_XOR_THREADS", "STA_THREADS"}
    assert set(_v(8, 8.0, flow_vars=classic)) == classic


def test_taken_variables_are_kept_not_sized():
    out = rr.size_threads(8, 8.0, taken={"STA_THREADS", "ROUTING_CORES"})
    assert "STA_THREADS" not in out["values"] and "DRT_THREADS" not in out["values"]
    assert out["kept"] == ["DRT_THREADS", "STA_THREADS"]


def test_why_is_plain_words():
    out = rr.size_threads(32, 44.0, corners=9)
    assert "16 at most" in out["why"]["DRT_THREADS"]
    assert out["why"]["STA_THREADS"].startswith("every corner")
    assert rr.reason_text(8, 5.06) == "8 cores, 5.1 GB free"


# --------------------------------------------------------- config wins

def test_config_sets_json_including_scoped(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"DESIGN_NAME": "x", "DRT_THREADS": 4,
                             "pdk::gf180mcu*": {"STA_THREADS": 2}}), encoding="utf-8")
    assert rr.config_sets([p]) == {"DRT_THREADS", "STA_THREADS"}


def test_config_sets_minified_json(tmp_path: Path):
    p = tmp_path / "config.json"
    p.write_text('{"DESIGN_NAME":"x","KLAYOUT_XOR_THREADS":3}', encoding="utf-8")
    assert rr.config_sets([p]) == {"KLAYOUT_XOR_THREADS"}


def test_config_sets_yaml_and_tcl(tmp_path: Path):
    y = tmp_path / "config.yaml"
    y.write_text("DESIGN_NAME: x\npdk::sky130*:\n  KLAYOUT_DRC_THREADS: 2\n# DRT_THREADS: 9\n",
                 encoding="utf-8")
    assert rr.config_sets([y]) == {"KLAYOUT_DRC_THREADS"}
    t = tmp_path / "config.tcl"
    t.write_text("set ::env(DESIGN_NAME) x\nset ::env(ROUTING_CORES) 6\n", encoding="utf-8")
    assert rr.config_sets([t]) == {"DRT_THREADS"}


def test_plan_config_and_run_overrides_win(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LANEX_THREAD_SIZING", raising=False)
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"DESIGN_NAME": "x", "DRT_THREADS": 4}), encoding="utf-8")
    out = rr.plan(design_dir=tmp_path, config_files=[cfg], overrides={"STA_THREADS": "3"},
                  facts={"cores": 32, "available_gb": 44.0, "total_gb": 47.0})
    assert "DRT_THREADS" not in out["overrides"] and "STA_THREADS" not in out["overrides"]
    assert out["overrides"] == {"KLAYOUT_DRC_THREADS": 8, "KLAYOUT_XOR_THREADS": 8,
                                "KLAYOUT_DENSITY_THREADS": 8}
    rec = out["record"]
    assert rec["source"] == "LanEx (sized to this PC)"
    assert rec["reason"] == "32 cores, 44.0 GB free"
    assert rec["kept"] == {"DRT_THREADS": "your config", "STA_THREADS": "this run's settings"}
    assert rec["values"] == out["overrides"]


def test_plan_reads_flow_variables_and_corners(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LANEX_THREAD_SIZING", raising=False)
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))

    class _V:
        def __init__(self, name):
            self.name = name

    class _S:
        config_vars = [_V("STA_THREADS"), _V("DRT_THREADS"), _V("OTHER")]

    class _Flow:
        Steps = [_S]

    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "resolved.json").write_text(json.dumps({"PDK": "sky130A", "STA_CORNERS": ["a", "b", "c"]}))
    out = rr.plan(design_dir=tmp_path, config_files=[], flow_factory=_Flow, pdk="sky130A",
                  facts={"cores": 16, "available_gb": 30.0})
    assert out["overrides"] == {"DRT_THREADS": 16, "STA_THREADS": 3}
    # Another PDK's run says nothing about this one's corners.
    out = rr.plan(design_dir=tmp_path, config_files=[], flow_factory=_Flow, pdk="gf180mcuD",
                  facts={"cores": 16, "available_gb": 30.0})
    assert out["overrides"]["STA_THREADS"] == 16


def test_plan_turned_off(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LANEX_HOME", str(tmp_path))
    monkeypatch.delenv("LANEX_THREAD_SIZING", raising=False)
    (tmp_path / "settings.json").write_text('{"thread_sizing": false}', encoding="utf-8")
    out = rr.plan(design_dir=tmp_path, config_files=[], facts={"cores": 8, "available_gb": 8})
    assert out["overrides"] == {} and out["record"]["enabled"] is False
    (tmp_path / "settings.json").unlink()
    monkeypatch.setenv("LANEX_THREAD_SIZING", "0")
    assert rr.plan(design_dir=tmp_path, config_files=[], facts={"cores": 8, "available_gb": 8})["overrides"] == {}


def test_usable_cores_respects_openlane_max_cores(monkeypatch):
    monkeypatch.setenv("_OPENLANE_MAX_CORES", "3")
    n = rr.usable_cores()
    assert n is not None and n <= 3


# ------------------------------------------------ the run path + gui-run.json

def test_assemble_overrides_sizes_threads_but_keeps_user_overrides_apart(tmp_path, monkeypatch):
    from lanex.server import routes
    monkeypatch.delenv("LANEX_THREAD_SIZING", raising=False)
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(rr, "machine", lambda: {"cores": 8, "available_gb": 7.0, "total_gb": 8.0})
    (tmp_path / "config.json").write_text('{"DESIGN_NAME": "x", "KLAYOUT_DRC_THREADS": 1}',
                                          encoding="utf-8")
    asm = routes._assemble_overrides(str(tmp_path), {"overrides": {"STA_THREADS": "2", "A": "1"}})
    assert asm["overrides"] == {"STA_THREADS": "2", "A": "1"}       # the user's, untouched
    assert "KLAYOUT_DRC_THREADS" not in asm["threads"]               # config wins
    assert "STA_THREADS" not in asm["threads"]                       # run override wins
    assert asm["threads"]["DRT_THREADS"] == 8
    assert asm["resources"]["values"] == asm["threads"]
    assert asm["resources"]["kept"]["KLAYOUT_DRC_THREADS"] == "your config"


def test_gui_run_json_records_resources(tmp_path: Path):
    from lanex.controller.runner import FlowRunner
    r = FlowRunner()
    run = tmp_path / "runs" / "t1"
    run.mkdir(parents=True)
    rec = {"source": rr.SOURCE, "reason": "8 cores, 5.1 GB free",
           "values": {"DRT_THREADS": 8}, "kept": {}}
    r._gui_meta = {"flow": "Classic", "overrides": {}, "resources": rec}
    r._run_dir = str(run)
    r._persist_gui_meta()
    meta = json.loads((run / "gui-run.json").read_text(encoding="utf-8"))
    assert meta["resources"] == rec
    assert meta["overrides"] == {}
    # The Final-settings table attributes the value to LanEx, not to the user.
    from lanex.controller import provenance
    (run / "resolved.json").write_text(json.dumps({"DRT_THREADS": 8, "DESIGN_NAME": "x"}))
    rows = {x["name"]: x for x in provenance.resolved_settings(run, tmp_path)["rows"]}
    assert rows["DRT_THREADS"]["source"] == "lanex"
    assert rows["DRT_THREADS"]["reason"] == "8 cores, 5.1 GB free"
    # Reproduce carries them (and the recorded command already has them as -c).
    from lanex.controller import manualcmd
    info = manualcmd.reproduce_info(meta, {}, str(run))
    assert info["threads"]["values"] == {"DRT_THREADS": 8}


def test_resources_note_in_the_run_log():
    from lanex.controller.runner import FlowRunner
    r = FlowRunner()
    r._gui_meta = {"resources": {"reason": "4 cores, 3.0 GB free",
                                 "values": {"DRT_THREADS": 4, "STA_THREADS": 3},
                                 "kept": {"KLAYOUT_DRC_THREADS": "your config"}}}
    r._emit_resources_note()
    msgs = [e.get("message", "") for e in r.drain(block=False, timeout=0.05)]
    assert any("Threads sized to this PC (4 cores, 3.0 GB free): DRT_THREADS=4 STA_THREADS=3." in m
               and "KLAYOUT_DRC_THREADS (your config)" in m for m in msgs)


# ------------------------------------------------------- memory heads-up

def test_memory_check_rule_and_last_run(tmp_path: Path):
    assert rr.memory_check(8.0, 16.0, None)["warn"] is False
    low = rr.memory_check(1.4, 4.0, None)
    assert low["warn"] and low["need_gb"] == 2.0 and low["basis"] == "rule"
    assert "1.4 GB" in low["message"] and "wsl --shutdown" in low["next_step"]
    assert low["link"].startswith("https://learn.microsoft.com/")
    peak = {"gb": 3.4, "tag": "r1", "step": "41-openroad-detailedrouting"}
    w = rr.memory_check(3.0, 8.0, peak)
    assert w["warn"] and w["need_gb"] == 3.9 and w["basis"] == "last-run" and "r1" in w["message"]
    assert rr.memory_check(5.0, 8.0, peak)["warn"] is False


def test_last_run_peak_reads_process_stats(tmp_path: Path):
    step = tmp_path / "runs" / "r1" / "41-openroad-detailedrouting"
    step.mkdir(parents=True)
    (step / "openroad-detailedrouting.process_stats.json").write_text(
        json.dumps({"peak_resources": {"memory_rss": "2.5GiB"}}))
    other = tmp_path / "runs" / "r1" / "06-yosys-synthesis"
    other.mkdir()
    (other / "yosys-synthesis.process_stats.json").write_text(
        json.dumps({"peak_resources": {"memory_rss": "197MiB"}}))
    peak = rr.last_run_peak_gb(tmp_path)
    assert peak == {"gb": 2.5, "tag": "r1", "step": "41-openroad-detailedrouting"}
    assert rr.last_run_peak_gb(tmp_path / "nothing") is None


def test_last_run_peak_reads_a_finished_run_once(tmp_path: Path, monkeypatch):
    run = tmp_path / "runs" / "r1"
    for name, rss in [("06-yosys-synthesis", "197MiB"), ("41-openroad-detailedrouting", "2.5GiB")]:
        d = run / name
        d.mkdir(parents=True)
        (d / (name.split("-", 1)[1] + ".process_stats.json")).write_text(
            json.dumps({"peak_resources": {"memory_rss": rss}}))
    rr._PEAK_CACHE.clear()
    assert rr.last_run_peak_gb(tmp_path)["gb"] == 2.5
    reads = []
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: reads.append(self.name) or real(self, *a, **k))
    assert rr.last_run_peak_gb(tmp_path)["gb"] == 2.5
    assert reads == []          # nothing changed: no step folder read again
    # a new step (a run still going, or resumed) is read
    d = run / "52-openroad-fillinsertion"
    d.mkdir()
    (d / "openroad-fillinsertion.process_stats.json").write_text(
        json.dumps({"peak_resources": {"memory_rss": "3.0GiB"}}))
    peak = rr.last_run_peak_gb(tmp_path)
    assert peak == {"gb": 3.0, "tag": "r1", "step": "52-openroad-fillinsertion"}
    assert reads


# ------------------------------------------------------- log batching

def test_log_lines_are_batched_in_order():
    from lanex.controller.runner import FlowRunner
    from lanex.controller.models import EventType
    r = FlowRunner()
    for i in range(450):
        r._emit(EventType.LOG, {"message": f"line {i}"})
    r._emit(EventType.STEP_STARTED, {"step_id": "s2"})
    r._emit(EventType.LOG, {"message": "after"})
    time.sleep(r.LOG_BATCH_S * 3)          # the flusher sends the tail on its own
    evs = r.drain(block=False, timeout=0.05)
    logs = [e for e in evs if e["type"] == "log"]
    assert len(logs) <= 5                   # 450 lines -> 200 + 200 + 50, then "after"
    text = [ln for e in logs for ln in e["message"].split("\n")]
    assert text == [f"line {i}" for i in range(450)] + ["after"]
    # The step event lands after every line printed before it, before "after".
    kinds = [e["type"] for e in evs]
    assert kinds.index("step_started") > max(i for i, e in enumerate(evs)
                                             if e["type"] == "log" and "line 449" in e["message"])
    assert kinds.index("step_started") < [i for i, e in enumerate(evs)
                                          if e["type"] == "log" and e["message"] == "after"][0]
    seqs = [e["seq"] for e in evs]
    assert seqs == sorted(seqs)


def test_log_batch_keeps_the_worst_level():
    from lanex.controller.runner import FlowRunner
    from lanex.controller.models import EventType
    r = FlowRunner()
    r._emit(EventType.LOG, {"message": "a", "level": "INFO"})
    r._emit(EventType.LOG, {"message": "b", "level": "ERROR"})
    r._emit(EventType.INFO, {"message": "x"})
    evs = r.drain(block=False, timeout=0.05)
    assert evs[0]["type"] == "log" and evs[0]["message"] == "a\nb" and evs[0]["level"] == "ERROR"
    assert evs[1]["type"] == "info"
