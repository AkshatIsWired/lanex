# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""The PDK chosen in LanEx and the one the config names must agree.

Field report: only gf180 installed, gf180 picked for Blinky, the run stopped
with "sky130A not found": config.json still said sky130A, and LibreLane
3.0.4 takes the config's PDK over ``-p`` (config.py ``__load_dict``:
``pdk = mutable.get(SpecialKeys.pdk) or pdk``). These lock the server-side
guard, the config reader it uses, and the per-PDK template tuning that lets
the starters reach a clean GDS on gf180mcuD and ihp-sg13g2 too.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lanex.controller import configedit, scaffold


def _cfg(d: Path, data, name="config.json") -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps(data, indent=2) if name.endswith(".json") else data, encoding="utf-8")
    return p


# ---------------------------------------------------------------- config reader

def test_config_pdk_reads_json_yaml_and_tcl(tmp_path: Path) -> None:
    _cfg(tmp_path / "j", {"DESIGN_NAME": "x", "PDK": "sky130A", "STD_CELL_LIBRARY": "sky130_fd_sc_hd"})
    c = configedit.config_pdk(tmp_path / "j")
    assert (c["pdk"], c["scl"], c["name"], c["editable"]) == ("sky130A", "sky130_fd_sc_hd", "config.json", True)

    _cfg(tmp_path / "y", "DESIGN_NAME: x\nPDK: gf180mcuD\n", "config.yaml")
    c = configedit.config_pdk(tmp_path / "y")
    assert c["pdk"] == "gf180mcuD" and c["scl"] is None

    _cfg(tmp_path / "t", 'set ::env(DESIGN_NAME) x\nset ::env(PDK) "sky130B"\nset ::env(STD_CELL_LIBRARY) {sky130_fd_sc_hs}\n',
         "config.tcl")
    c = configedit.config_pdk(tmp_path / "t")
    assert (c["pdk"], c["scl"], c["editable"]) == ("sky130B", "sky130_fd_sc_hs", False)

    # pdk:: sections never count: they apply only when the PDK already matches.
    _cfg(tmp_path / "s", {"DESIGN_NAME": "x", "pdk::gf180*": {"STD_CELL_LIBRARY": "gf180mcu_fd_sc_mcu9t5v0"}})
    c = configedit.config_pdk(tmp_path / "s")
    assert c["pdk"] is None and c["scl"] is None


# ---------------------------------------------------------------- mismatch rule

def test_mismatch_names_both_values_and_the_fix(tmp_path: Path) -> None:
    _cfg(tmp_path, {"DESIGN_NAME": "blinky", "PDK": "sky130A", "STD_CELL_LIBRARY": "sky130_fd_sc_hd"})
    mm = configedit.pdk_mismatch(tmp_path, "gf180mcuD", "gf180mcu_fd_sc_mcu7t5v0")
    assert mm is not None
    assert mm["keys"] == ["PDK", "STD_CELL_LIBRARY"]
    assert mm["config"] == {"pdk": "sky130A", "scl": "sky130_fd_sc_hd"}
    assert mm["fix"] == {"PDK": "gf180mcuD", "STD_CELL_LIBRARY": "gf180mcu_fd_sc_mcu7t5v0"}
    assert mm["editable"] is True
    msg = mm["message"]
    for word in ("sky130A", "gf180mcuD", "config.json"):
        assert word in msg
    assert "\n" not in msg


def test_agreeing_or_silent_config_is_not_a_mismatch(tmp_path: Path) -> None:
    _cfg(tmp_path / "a", {"PDK": "gf180mcuD", "STD_CELL_LIBRARY": "gf180mcu_fd_sc_mcu7t5v0"})
    assert configedit.pdk_mismatch(tmp_path / "a", "gf180mcuD", "gf180mcu_fd_sc_mcu7t5v0") is None
    # A config that names no PDK (LibreLane's SPM: pdk:: sections only) builds
    # for whatever -p says.
    _cfg(tmp_path / "b", {"DESIGN_NAME": "spm", "pdk::sky130*": {"CLOCK_PERIOD": 10}})
    assert configedit.pdk_mismatch(tmp_path / "b", "ihp-sg13g2", "sg13g2_stdcell") is None
    # Nothing asked: nothing to disagree with.
    assert configedit.pdk_mismatch(tmp_path / "a", None, None) is None


def test_library_alone_can_disagree(tmp_path: Path) -> None:
    _cfg(tmp_path / "a", {"PDK": "sky130A", "STD_CELL_LIBRARY": "sky130_fd_sc_hd"})
    mm = configedit.pdk_mismatch(tmp_path / "a", "sky130A", "sky130_fd_sc_hs")
    assert mm and mm["keys"] == ["STD_CELL_LIBRARY"] and "sky130_fd_sc_hs" in mm["message"]
    # A config with only a library, from another PDK family than the one asked for.
    _cfg(tmp_path / "b", {"STD_CELL_LIBRARY": "sky130_fd_sc_hd"})
    mm = configedit.pdk_mismatch(tmp_path / "b", "gf180mcuD", None)
    assert mm and mm["keys"] == ["STD_CELL_LIBRARY"]


def test_tcl_config_mismatch_has_no_save_fix(tmp_path: Path) -> None:
    _cfg(tmp_path, 'set ::env(PDK) "sky130A"\n', "config.tcl")
    mm = configedit.pdk_mismatch(tmp_path, "gf180mcuD", None)
    assert mm and mm["editable"] is False and "by hand" in mm["message"]


# ---------------------------------------------------------------- run start / preflight

class _Runner:
    running = False

    def __init__(self) -> None:
        self.started = None

    def start(self, **kw):
        self.started = kw
        return {"ok": True, "tag": "t"}


def test_run_start_refuses_a_disagreeing_picker(monkeypatch, tmp_path: Path) -> None:
    pytest.importorskip("librelane")
    from lanex.server import app, routes
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "blinky.v").write_text("module blinky(input clk); endmodule\n")
    _cfg(tmp_path, {"DESIGN_NAME": "blinky", "VERILOG_FILES": ["dir::src/*.v"], "CLOCK_PORT": "clk",
                    "CLOCK_PERIOD": 10, "PDK": "sky130A", "STD_CELL_LIBRARY": "sky130_fd_sc_hd"})
    runner = _Runner()
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(tmp_path))
    monkeypatch.setattr(app, "get_runner", lambda: runner)
    data, status = routes._start_run({"overrides": {"PDK": "gf180mcuD", "STD_CELL_LIBRARY": "gf180mcu_fd_sc_mcu7t5v0"},
                                      "run_mode": "container"})
    assert status == 200 and data["ok"] is False and data["started"] is False
    assert data["pdk_mismatch"]["config"]["pdk"] == "sky130A"
    assert "sky130A" in data["reason"] and "gf180mcuD" in data["reason"]
    assert runner.started is None   # nothing launched


def test_preflight_blocks_on_a_disagreeing_picker(monkeypatch, tmp_path: Path) -> None:
    from lanex.server import routes
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "blinky.v").write_text("module blinky(input clk); reg r; always @(posedge clk) r <= ~r; endmodule\n")
    _cfg(tmp_path, {"DESIGN_NAME": "blinky", "VERILOG_FILES": ["dir::src/*.v"], "PDK": "sky130A"})
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(tmp_path))
    monkeypatch.setattr(routes, "_preflight_tools_cached", lambda ttl=8.0: {})
    monkeypatch.setattr(routes.pdk_mod, "check_pdk_ready", lambda p, s, m: {"ready": True})
    got = {}
    monkeypatch.setattr(routes, "_respond", lambda h, payload, code=200: got.update(payload=payload))

    class H:
        path = "/api/preflight?pdk=gf180mcuD&scl=gf180mcu_fd_sc_mcu7t5v0&run_mode=container"
    routes.h_preflight(H())
    p = got["payload"]
    assert p["ready"] is False
    assert p["pdk"]["mismatch"]["requested"]["pdk"] == "gf180mcuD"
    assert any("sky130A" in b for b in p["blockers"])


# ---------------------------------------------------------------- template tuning

def test_templates_list_their_per_pdk_clock() -> None:
    by = {t["name"]: t for t in scaffold.list_templates()}
    assert by["blinky"]["pdk_clock"] == {"gf180mcu*": 20.0}
    assert by["fifo"]["pdk_clock"]["gf180mcu*"] > by["fifo"]["clock_period"]
    assert by["counter"]["pdk_clock"] == {}


def test_project_on_gf180_gets_the_tuning_at_the_top_level(tmp_path: Path) -> None:
    res = scaffold.create_project(tmp_path / "b", "blinky", top="", pdk="gf180mcuD", scl="gf180mcu_fd_sc_mcu7t5v0")
    cfg = json.loads((tmp_path / "b" / "config.json").read_text())
    assert res["ok"] and cfg["PDK"] == "gf180mcuD" and cfg["CLOCK_PERIOD"] == 20.0
    assert cfg["FP_CORE_UTIL"] == 38 and cfg["PL_TARGET_DENSITY_PCT"] == 50
    assert not any(k.startswith("pdk::") for k in cfg)


def test_project_on_sky130_carries_a_gf180_section(tmp_path: Path) -> None:
    scaffold.create_project(tmp_path / "b", "blinky", top="", pdk="sky130A", scl="sky130_fd_sc_hd")
    cfg = json.loads((tmp_path / "b" / "config.json").read_text())
    assert cfg["CLOCK_PERIOD"] == 10.0 and "FP_CORE_UTIL" not in cfg
    assert cfg["pdk::gf180mcu*"] == {"FP_CORE_UTIL": 38, "PL_TARGET_DENSITY_PCT": 50, "CLOCK_PERIOD": 20.0}
    # ...and the Design row says the section wins for a gf180 run.
    s = configedit.scoped_values(cfg, "CLOCK_PERIOD")
    assert s and configedit.applies(s[0], "gf180mcuD", None) is True and configedit.applies(s[0], "sky130A", None) is False


def test_a_typed_clock_wins_and_a_slower_one_needs_no_section(tmp_path: Path) -> None:
    scaffold.create_project(tmp_path / "a", "blinky", top="", pdk="gf180mcuD", clock_period=12.5)
    assert json.loads((tmp_path / "a" / "config.json").read_text())["CLOCK_PERIOD"] == 12.5
    scaffold.create_project(tmp_path / "b", "blinky", top="", pdk="sky130A", clock_period=30)
    sec = json.loads((tmp_path / "b" / "config.json").read_text())["pdk::gf180mcu*"]
    assert "CLOCK_PERIOD" not in sec


def test_blank_project_gets_a_bigger_gf180_die(tmp_path: Path) -> None:
    scaffold.create_project(tmp_path / "g", "empty", top="top", pdk="gf180mcuD")
    assert json.loads((tmp_path / "g" / "config.json").read_text())["DIE_AREA"] == [0, 0, 300, 300]
    scaffold.create_project(tmp_path / "s", "empty", top="top", pdk="sky130A")
    cfg = json.loads((tmp_path / "s" / "config.json").read_text())
    assert cfg["DIE_AREA"] == [0, 0, 150, 150] and cfg["pdk::gf180mcu*"]["DIE_AREA"] == [0, 0, 300, 300]


def test_template_pdk_tuning_keys_are_real_variables() -> None:
    from lanex.controller import introspect
    known = {v["name"] for v in introspect.list_variables()}
    if not known:
        pytest.skip("librelane not importable in this environment")
    for tdir in scaffold._templates_root().iterdir():
        doc = scaffold._read_manifest(tdir) if tdir.is_dir() else None
        for pat, tune in scaffold._pdk_tuning(doc or {}).items():
            for key in (tune.get("config") or {}):
                assert key in known, f"{tdir.name} {pat}: {key} is not a real LibreLane variable"


def test_resolved_settings_credits_the_config_for_its_pdk(tmp_path: Path) -> None:
    from lanex.controller import provenance
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "resolved.json").write_text(json.dumps({"PDK": "gf180mcuD", "STD_CELL_LIBRARY": "gf180mcu_fd_sc_mcu7t5v0"}, indent=2))
    (run / "gui-run.json").write_text(json.dumps({"overrides": {}, "pdk": "gf180mcuD", "scl": "gf180mcu_fd_sc_mcu7t5v0"}))
    _cfg(tmp_path, {"DESIGN_NAME": "x", "PDK": "gf180mcuD"})
    by = {r["name"]: r for r in provenance.resolved_settings(run, tmp_path)["rows"]}
    assert by["PDK"]["source"] == "config" and by["PDK"]["config_line"] == 3
    assert by["STD_CELL_LIBRARY"]["source"] == "picker"
