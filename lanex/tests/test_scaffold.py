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
    # `empty` sorts last.
    assert tpls[-1]["name"] == "empty"


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
