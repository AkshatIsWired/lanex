# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for :mod:`lanex.controller.scaffold` (Phase 0 project wizard)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lanex.controller import scaffold


def test_list_templates_nonempty_and_shaped():
    tpls = scaffold.list_templates()
    names = {t["name"] for t in tpls}
    assert {"counter", "fifo", "blinky", "multiplier", "empty"} <= names
    for t in tpls:
        assert t["title"] and "top" in t and "clock_port" in t
    # The blank project leads; examples follow in their curated order.
    assert tpls[0]["name"] == "empty" and tpls[0]["kind"] == "blank"
    assert all(t["kind"] == "example" for t in tpls[1:])


def test_blank_project_renames_its_starter_module(tmp_path: Path):
    dest = tmp_path / "mychip"
    res = scaffold.create_project(str(dest), "empty", top="alu", pdk="sky130A")
    assert res["ok"] is True
    assert (dest / "src" / "alu.v").is_file() and not (dest / "src" / "top.v").exists()
    assert "module alu" in (dest / "src" / "alu.v").read_text()
    assert json.loads((dest / "config.json").read_text())["DESIGN_NAME"] == "alu"


def test_blank_systemverilog_project(tmp_path: Path):
    dest = tmp_path / "svchip"
    res = scaffold.create_project(str(dest), "empty", top="alu", pdk="sky130A", language="systemverilog")
    assert res["ok"] is True
    assert (dest / "src" / "alu.sv").is_file() and not (dest / "src" / "alu.v").exists()
    assert "module alu" in (dest / "src" / "alu.sv").read_text()
    assert json.loads((dest / "config.json").read_text())["VERILOG_FILES"] == ["dir::src/*.sv"]


def test_blank_project_sizes_its_die_from_the_design(tmp_path: Path):
    # A fixed 150 um die put a 32x32 multiplier at 370 % utilization. A
    # utilization-sized die grows with the design; measured with LibreLane
    # 3.0.4 on sky130A, the 8-bit starter (35x46 um die) and a 32x32
    # multiplier both reach a clean GDS at FP_CORE_UTIL 40 / density 55.
    dest = tmp_path / "b"
    scaffold.create_project(str(dest), "empty", top="top", pdk="sky130A")
    cfg = json.loads((dest / "config.json").read_text())
    assert cfg["FP_SIZING"] == "relative" and "DIE_AREA" not in cfg
    assert cfg["FP_CORE_UTIL"] == 40 and cfg["PL_TARGET_DENSITY_PCT"] > cfg["FP_CORE_UTIL"]
    assert "DIE_AREA" not in cfg.get("pdk::gf180mcu*", {})
    assert cfg["DESIGN_NAME"] == "top"


@pytest.mark.parametrize("tdir", sorted(p.name for p in scaffold._templates_root().iterdir() if p.is_dir()))
def test_no_template_pins_a_die_it_cannot_outgrow(tdir: str):
    # A DIE_AREA beside relative sizing is ignored by the floorplan but still
    # drawn as the outline by Magic's stream-out, which fails the XOR check.
    doc = scaffold._read_manifest(scaffold._templates_root() / tdir) or {}
    sections = [doc.get("config") or {}] + [(v.get("config") or {}) for v in (doc.get("pdk") or {}).values()]
    for sec in sections:
        if sec.get("FP_SIZING") != "absolute":
            assert "DIE_AREA" not in sec, tdir
        if "PL_TARGET_DENSITY_PCT" in sec and "FP_CORE_UTIL" in sec:
            assert sec["PL_TARGET_DENSITY_PCT"] >= sec["FP_CORE_UTIL"] + 10, tdir


def test_template_config_keys_are_real_variables():
    from lanex.controller import introspect
    known = {v["name"] for v in introspect.list_variables()}
    if not known:
        pytest.skip("librelane not importable in this environment")
    for tdir in scaffold._templates_root().iterdir():
        doc = scaffold._read_manifest(tdir) if tdir.is_dir() else None
        for key in ((doc or {}).get("config") or {}):
            assert key in known, f"{tdir.name}: {key} is not a real LibreLane variable"


def test_language_leaves_examples_alone(tmp_path: Path):
    dest = tmp_path / "ex"
    scaffold.create_project(str(dest), "blinky", top="", pdk="sky130A", language="systemverilog")
    assert (dest / "src" / "blinky.v").is_file()
    assert json.loads((dest / "config.json").read_text())["VERILOG_FILES"] == ["dir::src/*.v"]


def test_example_keeps_its_own_top_module(tmp_path: Path):
    # An example's top is fixed by its Verilog; a different name would point
    # DESIGN_NAME at a module that doesn't exist.
    dest = tmp_path / "ex"
    res = scaffold.create_project(str(dest), "blinky", top="something_else", pdk="sky130A")
    assert json.loads((dest / "config.json").read_text())["DESIGN_NAME"] == "blinky"
    assert res["top"] == "blinky"


def test_spm_example_copies_its_tuned_config(tmp_path: Path):
    if scaffold.spm_source() is None:
        import pytest
        pytest.skip("no SPM example available in this install")
    dest = tmp_path / "spm"
    res = scaffold.create_project(str(dest), "spm", top="", pdk="sky130A")
    assert res["ok"] is True
    assert (dest / "config.yaml").is_file() and not (dest / "config.json").exists()
    assert (dest / "src" / "spm.v").is_file() and not (dest / "runs").exists()


def test_create_project_writes_config_and_sources(tmp_path: Path):
    dest = tmp_path / "myctr"
    res = scaffold.create_project(str(dest), "counter", top="counter", pdk="sky130A",
                                  scl="sky130_fd_sc_hd", clock_period=10.0)
    assert res["ok"] is True
    assert (dest / "config.json").is_file()
    assert (dest / "src" / "counter.v").is_file()
    cfg = json.loads((dest / "config.json").read_text())
    assert cfg["DESIGN_NAME"] == "counter"
    assert cfg["VERILOG_FILES"] == ["dir::src/*.v"]
    assert cfg["CLOCK_PORT"] == "clk"
    assert cfg["CLOCK_PERIOD"] == 10.0
    assert cfg["PDK"] == "sky130A"
    assert "config.json" in res["files"]


def test_create_project_only_real_vars():
    """Every key a scaffolded config emits must be a real LibreLane variable."""
    from lanex.controller import introspect
    known = {v["name"] for v in introspect.list_variables()}
    if not known:
        pytest.skip("librelane not importable in this environment")
    cfg = scaffold._render_config(top="t", pdk="sky130A", scl="sky130_fd_sc_hd",
                                  clock_port="clk", clock_period=10.0)
    for key in cfg:
        assert key in known, f"{key} is not a real LibreLane variable"


def test_create_project_refuses_nonempty(tmp_path: Path):
    dest = tmp_path / "used"
    dest.mkdir()
    (dest / "something.txt").write_text("hi")
    res = scaffold.create_project(str(dest), "counter", top="counter", pdk="sky130A")
    assert res["ok"] is False
    assert "not empty" in res["error"]


def test_create_project_unknown_template(tmp_path: Path):
    res = scaffold.create_project(str(tmp_path / "x"), "../etc", top="t", pdk="sky130A")
    assert res["ok"] is False


def test_create_project_no_path_escape(tmp_path: Path):
    """A template can never write outside the destination dir."""
    dest = tmp_path / "blink"
    res = scaffold.create_project(str(dest), "blinky", top="blinky", pdk="sky130A")
    assert res["ok"] is True
    for rel in res["files"]:
        resolved = (dest / rel).resolve()
        assert str(resolved).startswith(str(dest.resolve()))
