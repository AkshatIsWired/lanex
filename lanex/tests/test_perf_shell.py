# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Boot reads the config's PDK and library without scanning the project.

Setup's PDK picker follows the config when a project opens. It asked
/api/project/design-info for two keys, and that walked the whole project
tree (runs/ included) to find modules: 3.5-11 s on a project with 300 runs,
on the boot path. ``keys_only`` answers from the config alone.
"""
from __future__ import annotations

import json
from pathlib import Path

from lanex.server import routes


def _call(monkeypatch, design: Path, body: dict) -> dict:
    got: dict = {}
    monkeypatch.setattr(routes, "_design_dir_or_400", lambda h: str(design))
    monkeypatch.setattr(routes, "_respond", lambda h, payload, code=200: got.update(payload=payload, code=code))

    class _H:
        _body = body

    routes.h_design_info(_H())
    return got


def test_keys_only_reads_the_config_without_a_source_scan(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"DESIGN_NAME": "spm", "PDK": "sky130B", "STD_CELL_LIBRARY": "sky130_fd_sc_hd"}))
    from lanex.controller import autoconfig

    def boom(*a, **k):
        raise AssertionError("keys_only must not scan the sources")

    monkeypatch.setattr(autoconfig, "scan_sources", boom)
    got = _call(monkeypatch, tmp_path, {"keys": ["PDK", "STD_CELL_LIBRARY", "bad key"], "keys_only": True})
    assert got["code"] == 200
    p = got["payload"]
    assert p["settings"] == {"PDK": "sky130B", "STD_CELL_LIBRARY": "sky130_fd_sc_hd"}
    assert p["config"]["name"] == "config.json"
    assert p["config"]["editable"] is True
    assert "modules" not in p


def test_full_design_info_still_scans(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "config.json").write_text(json.dumps({"DESIGN_NAME": "top", "PDK": "sky130A"}))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "top.v").write_text("module top(input clk, output q); assign q = clk; endmodule\n")
    got = _call(monkeypatch, tmp_path, {"keys": ["PDK"]})
    assert got["code"] == 200
    p = got["payload"]
    assert p["settings"] == {"PDK": "sky130A"}
    assert "top" in p["modules"]
    assert [x["name"] for x in p["ports"]] == ["clk", "q"]
