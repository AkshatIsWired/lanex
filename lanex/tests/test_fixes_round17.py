# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Round-17 lock-in tests for the user-reported batch:

* #1  auto-config never picks a testbench as the top, excludes bench files from
      VERILOG_FILES, and restricts to tick-marked files when given.
* #4  the runner writes gui-run.json (reproducible run settings) into the run dir.
* #9/#10  container OpenROAD launches with the run loaded (read_db); Netgen opens
      interactively (no -batch).
* #11 empty / null overrides are stripped before they reach the engine.

All pure / tool-free — no OpenROAD, no Docker, no PDK needed."""
from __future__ import annotations

import json
from pathlib import Path


# ----------------------------------------------------------------- #1 autoconfig
def _design_with_testbench(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "verify").mkdir(parents=True, exist_ok=True)
    (root / "src" / "alu.v").write_text(
        "module alu(input clk, input [3:0] a, output reg [3:0] y);\n"
        " always @(posedge clk) y<=a; endmodule\n"
    )
    (root / "src" / "cpu.v").write_text(
        "module cpu(input clk, input [3:0] x, output [3:0] z);\n"
        " alu u(.clk(clk), .a(x), .y(z)); endmodule\n"
    )
    # Classic port-less testbench that instantiates the DUT and uses $finish.
    (root / "verify" / "tb_cpu.v").write_text(
        "module tb_cpu;\n reg clk; reg [3:0] x; wire [3:0] z;\n"
        " cpu dut(.clk(clk), .x(x), .z(z));\n"
        " initial begin $dumpfile(\"x.vcd\"); $dumpvars; #100 $finish; end\n"
        "endmodule\n"
    )


def test_autoconfig_does_not_pick_testbench_as_top(tmp_path):
    from lanex.controller import autoconfig

    _design_with_testbench(tmp_path)
    scan = autoconfig.scan_sources(str(tmp_path))
    assert scan["top"] == "cpu"
    assert "tb_cpu" in scan["testbench_modules"]
    assert "tb_cpu" not in (scan["top_candidates"] or [])
    # The bench file must not be in the synthesis source list.
    assert any(f.endswith("tb_cpu.v") for f in scan["testbench_files"])
    assert all("tb_cpu" not in p for p in scan["verilog"])


def test_autoconfig_config_excludes_testbench(tmp_path):
    from lanex.controller import autoconfig

    _design_with_testbench(tmp_path)
    res = autoconfig.suggest_config(str(tmp_path), pdk="ihp-sg13g2", scl="sg13g2_stdcell")
    assert res["ok"] is True
    cfg = res["config"]
    assert cfg["DESIGN_NAME"] == "cpu"
    assert all("tb_cpu" not in v for v in cfg["VERILOG_FILES"])
    # A note tells the user the bench was excluded.
    assert any("testbench" in n.lower() for n in res["meta"]["notes"])


def test_autoconfig_only_files_restricts_scan(tmp_path):
    from lanex.controller import autoconfig

    _design_with_testbench(tmp_path)
    # Tick only the two real RTL files; the bench is left unticked → ignored.
    ticked = [str(tmp_path / "src" / "alu.v"), str(tmp_path / "src" / "cpu.v")]
    scan = autoconfig.scan_sources(str(tmp_path), only_files=ticked)
    assert scan["restricted"] is True
    assert scan["top"] == "cpu"
    assert scan["testbench_modules"] == []  # bench file wasn't scanned at all
    assert all("tb_cpu" not in p for p in scan["verilog"])


def test_autoconfig_only_files_accepts_relative(tmp_path):
    from lanex.controller import autoconfig

    _design_with_testbench(tmp_path)
    scan = autoconfig.scan_sources(str(tmp_path), only_files=["src/cpu.v", "src/alu.v"])
    assert scan["restricted"] is True
    assert scan["top"] == "cpu"


# ------------------------------------------------------------ #11 clean overrides
def test_clean_overrides_strips_empty_keeps_falsy():
    from lanex.server.routes import _clean_overrides

    out = _clean_overrides({
        "PDN_CORE_RING_VOFFSET": "",      # the reported crash trigger → dropped
        "FP_CORE_UTIL": "55",             # kept
        "RT_MAX_LAYER": None,             # dropped
        "SYNTH_NO_FLAT": False,           # kept (real boolean value)
        "GRT_ANTENNA_REPAIR_ITERS": 0,    # kept (real zero value)
        "BLANKS": "   ",                  # whitespace-only → dropped
        "VERILOG_FILES": ["a.v", "", None],  # list cleaned of empties
        "EMPTY_LIST": [],                 # dropped
    })
    assert "PDN_CORE_RING_VOFFSET" not in out
    assert "RT_MAX_LAYER" not in out
    assert "BLANKS" not in out
    assert "EMPTY_LIST" not in out
    assert out["FP_CORE_UTIL"] == "55"
    assert out["SYNTH_NO_FLAT"] is False
    assert out["GRT_ANTENNA_REPAIR_ITERS"] == 0
    # Lists are whitespace-joined — that's how LibreLane parses a list override
    # (KEY=a b); a raw list would corrupt into its Python repr downstream.
    assert out["VERILOG_FILES"] == "a.v"
    assert _clean_overrides({"EXTRA_LEFS": ["a.lef", "b.lef"]})["EXTRA_LEFS"] == "a.lef b.lef"


# ----------------------------------------------------- #9/#10 container tool argv
def test_container_openroad_loads_run(tmp_path):
    from lanex.controller import container_tools

    odb = tmp_path / "final" / "odb" / "x.odb"
    odb.parent.mkdir(parents=True)
    odb.write_text("")  # placeholder; we only check argv + script
    script = container_tools._write_startup_script(
        "openroad", tmp_path, odb=odb, pdk=None, pdk_root=None
    )
    assert script is not None and script.is_file()
    assert "read_db" in script.read_text()
    cmd = container_tools._tool_command(
        "openroad", gds=None, pdk=None, pdk_root=None, odb=odb, script=script
    )
    # GUI flag + the startup script (so the layout loads, not an empty canvas).
    assert cmd[:2] == ["openroad", "-gui"]
    assert str(script) in cmd


def test_container_netgen_is_interactive():
    from lanex.controller import container_tools

    cmd = container_tools._tool_command(
        "netgen", gds=None, pdk=None, pdk_root=None, odb=None, script=None
    )
    # Must NOT be the old `netgen -batch` (which opened nothing and exited).
    assert cmd == ["netgen"]
    assert "-batch" not in cmd


def test_container_netgen_sources_setup(tmp_path):
    from lanex.controller import container_tools

    setup = tmp_path / "sky130A" / "libs.tech" / "netgen" / "sky130A_setup.tcl"
    setup.parent.mkdir(parents=True)
    setup.write_text("# setup\n")
    script = container_tools._write_startup_script(
        "netgen", tmp_path, odb=None, pdk="sky130A", pdk_root=str(tmp_path)
    )
    assert script is not None
    assert "source" in script.read_text()
    cmd = container_tools._tool_command(
        "netgen", gds=None, pdk="sky130A", pdk_root=str(tmp_path), odb=None, script=script
    )
    assert cmd == ["netgen", str(script)]


# --------------------------------------------------- DSE resource preflight (Q1)
def test_dse_system_resources_shape():
    from lanex.controller import dse

    info = dse.system_resources()
    # Always returns the documented keys, even if psutil were unavailable.
    for k in ("ok", "total_gb", "available_gb", "swap_gb", "cores", "risk", "reasons"):
        assert k in info
    assert info["risk"] in ("ok", "elevated", "high", "unknown")
    assert isinstance(info["reasons"], list)
    if info["ok"]:
        # No swap must surface as a reason + bump the risk above "ok".
        if info["swap_gb"] == 0:
            assert info["risk"] in ("elevated", "high")
            assert any("swap" in r.lower() for r in info["reasons"])


# ------------------------------------------------------------- #4 reproducibility
def test_runner_persists_gui_run_meta(tmp_path):
    from lanex.controller.runner import FlowRunner

    r = FlowRunner()
    r._gui_meta = {
        "flow": "Classic", "pdk": "ihp-sg13g2", "scl": "sg13g2_stdcell",
        "run_mode": "container", "overrides": {"FP_CORE_UTIL": "55"},
        "frm": None, "to": None, "skip": [],
    }
    r._gui_meta_written = False
    r._run_dir = str(tmp_path)
    r._persist_gui_meta()
    out = tmp_path / "gui-run.json"
    assert out.is_file()
    doc = json.loads(out.read_text())
    assert doc["pdk"] == "ihp-sg13g2"
    assert doc["overrides"]["FP_CORE_UTIL"] == "55"
    assert doc["tag"] == tmp_path.name
    # Idempotent: a second call must not raise and keeps the file.
    r._persist_gui_meta()
    assert out.is_file()
