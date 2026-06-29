# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Round-21 lock-in tests for the layout/OpenROAD follow-up batch:

* #3  OpenROAD GUI is foolproof: the generated startup .tcl loads liberty + the
      design DB + SDC + SPEF (so the GUI's Timing Report / Clock Tree Viewer work,
      not just a static render); corner liberty is matched by the DEFAULT_CORNER
      glob; a run missing the timing files still loads the layout (read_db only).

The unified Layout tool row (#2) and the compare run_dir plumbing (#1) are
frontend; their backends are covered by test_fixes_round20 (cross-design compare)
and the live endpoints. Pure/stdlib — no Docker/PDK/network."""
from __future__ import annotations

import json
from pathlib import Path

from lanex.controller import container_tools as ct


def _fake_run(tmp: Path) -> Path:
    """A run dir resembling a completed LibreLane run (final/ with odb/sdc/spef)."""
    run = tmp / "design" / "runs" / "t"
    (run / "final" / "odb").mkdir(parents=True)
    (run / "final" / "sdc").mkdir(parents=True)
    (run / "final" / "spef" / "nom").mkdir(parents=True)
    (run / "final" / "odb" / "top.odb").write_text("db")
    (run / "final" / "sdc" / "top.sdc").write_text("create_clock")
    (run / "final" / "spef" / "nom" / "top.nom.spef").write_text("*SPEF")
    libdir = tmp / "pdk" / "lib"
    libdir.mkdir(parents=True)
    tt = libdir / "sc__tt_025C_1v80.lib"
    ss = libdir / "sc__ss_100C_1v60.lib"
    tt.write_text("library(tt){}")
    ss.write_text("library(ss){}")
    (run / "resolved.json").write_text(json.dumps({
        "DEFAULT_CORNER": "nom_tt_025C_1v80",
        "LIB": {"*_tt_025C_1v80": [str(tt)], "*_ss_100C_1v60": [str(ss)]},
    }))
    return run


def test_corner_libs_matches_default_corner(tmp_path: Path):
    run = _fake_run(tmp_path)
    cfg = json.loads((run / "resolved.json").read_text())
    libs = ct._corner_libs(cfg, "nom_tt_025C_1v80")
    assert len(libs) == 1 and libs[0].endswith("sc__tt_025C_1v80.lib")
    # No corner match → union of all libs (so timing still has data).
    alllibs = ct._corner_libs(cfg, "does_not_exist")
    assert len(alllibs) == 2


def test_openroad_timing_files_resolved(tmp_path: Path):
    run = _fake_run(tmp_path)
    cfg = json.loads((run / "resolved.json").read_text())
    tf = ct._openroad_timing_files(run, cfg)
    assert tf["libs"] and tf["libs"][0].endswith("sc__tt_025C_1v80.lib")
    assert tf["sdc"] is not None and tf["sdc"].name == "top.sdc"
    assert tf["spef"] is not None and tf["spef"].name == "top.nom.spef"


def test_openroad_startup_script_loads_timing(tmp_path: Path):
    run = _fake_run(tmp_path)
    odb = run / "final" / "odb" / "top.odb"
    sp = ct._write_startup_script("openroad", run, odb=odb, pdk="sky130A", pdk_root=str(tmp_path / "pdk"))
    assert sp is not None
    text = sp.read_text()
    assert "read_db" in text
    assert "read_liberty" in text and "sc__tt_025C_1v80.lib" in text
    assert "read_sdc" in text and "top.sdc" in text
    assert "read_spef" in text and "top.nom.spef" in text
    assert "timing ready" in text          # the console hint when timing is loadable


def test_openroad_startup_degrades_without_final(tmp_path: Path):
    # An incomplete run (no final/, no resolved LIB): the layout still loads via
    # read_db; no liberty/sdc/spef lines, no crash, no false "timing ready".
    run = tmp_path / "d" / "runs" / "t"
    run.mkdir(parents=True)
    odb = run / "any.odb"
    odb.write_text("db")
    sp = ct._write_startup_script("openroad", run, odb=odb, pdk=None, pdk_root=None)
    assert sp is not None
    text = sp.read_text()
    assert "read_db" in text
    assert "read_liberty" not in text
    assert "timing data incomplete" in text


def test_openroad_no_odb_no_script(tmp_path: Path):
    run = tmp_path / "d" / "runs" / "t"
    run.mkdir(parents=True)
    assert ct._write_startup_script("openroad", run, odb=None, pdk=None, pdk_root=None) is None
