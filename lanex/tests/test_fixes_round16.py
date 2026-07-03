# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Round-16 lock-in tests: auto-config, container step-by-step slicing,
container-tool launch argv, custom-cell swap overrides, manual-console
allow-list + CLI reveal. Pure / tool-free (no OpenROAD / no Docker needed)."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest


# --------------------------------------------------------------------------- #1
def test_autoconfig_detects_top_and_clock(tmp_path):
    from lanex.controller import autoconfig

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "sub.v").write_text(
        "module adder(input clk, input [3:0] a, output reg [3:0] s);\n"
        " always @(posedge clk) s<=a; endmodule\n"
    )
    (tmp_path / "src" / "top.v").write_text(
        "module top(input sys_clk, input [3:0] x, output [3:0] y);\n"
        " adder u(.clk(sys_clk), .a(x), .s(y)); endmodule\n"
    )
    scan = autoconfig.scan_sources(str(tmp_path))
    # `adder` is instantiated by `top`; the never-instantiated module is the top.
    assert scan["top"] == "top"
    assert "adder" in scan["instantiated"]
    assert scan["clock_port"] == "sys_clk"

    res = autoconfig.suggest_config(str(tmp_path), pdk="sky130A", scl="sky130_fd_sc_hd")
    assert res["ok"]
    cfg = res["config"]
    assert cfg["DESIGN_NAME"] == "top"
    assert cfg["CLOCK_PORT"] == "sys_clk"
    assert cfg["PDK"] == "sky130A"
    assert all(v.startswith("dir::") for v in cfg["VERILOG_FILES"])


def test_autoconfig_emits_only_real_vars(tmp_path):
    from lanex.controller import autoconfig, introspect

    real = {v["name"] if isinstance(v, dict) else getattr(v, "name", "")
            for v in introspect.list_variables()}
    # Everything in the canonical emit set must be a real LibreLane variable.
    for name in autoconfig._EMIT_VARS:
        assert name in real, f"{name} is not a real LibreLane variable"


def test_autoconfig_write_no_clobber_and_confined(tmp_path):
    from lanex.controller import autoconfig

    (tmp_path / "a.v").write_text("module a(input clk); endmodule\n")
    cfg = {"DESIGN_NAME": "a", "VERILOG_FILES": ["dir::a.v"], "BOGUS_VAR": 1}
    w = autoconfig.write_config(str(tmp_path), cfg, fmt="json")
    assert w["ok"]
    assert "BOGUS_VAR" not in w["config"]  # fake var dropped
    assert (tmp_path / "config.json").is_file()
    # Refuses to clobber.
    w2 = autoconfig.write_config(str(tmp_path), cfg, fmt="json")
    assert not w2["ok"] and "exists" in w2["error"]
    # Overwrite allowed when asked.
    assert autoconfig.write_config(str(tmp_path), cfg, fmt="json", overwrite=True)["ok"]


def test_autoconfig_requires_design_name(tmp_path):
    from lanex.controller import autoconfig
    w = autoconfig.write_config(str(tmp_path), {"VERILOG_FILES": ["dir::a.v"]}, fmt="json")
    assert not w["ok"]


# --------------------------------------------------------------------------- #2
def test_slice_steps_honours_from_to_skip():
    from lanex.controller.runner import FlowRunner

    steps = ["s.lint", "s.synth", "s.floorplan", "s.place", "s.route", "s.gds"]
    assert FlowRunner._slice_steps(steps, None, None, []) == steps
    assert FlowRunner._slice_steps(steps, "s.synth", "s.place", []) == \
        ["s.synth", "s.floorplan", "s.place"]
    assert FlowRunner._slice_steps(steps, None, None, ["s.place"]) == \
        ["s.lint", "s.synth", "s.floorplan", "s.route", "s.gds"]
    # Inverted window falls back to the full list.
    assert FlowRunner._slice_steps(steps, "s.route", "s.synth", []) == steps


def test_dockerized_argv_from_to_emit_flags():
    from lanex.controller.container_run import build_dockerized_argv

    argv = build_dockerized_argv(
        config_file="config.json", design_dir="/d", flow="Classic",
        pdk="sky130A", tag="t1", frm="floorplan", to="floorplan",
    )
    s = " ".join(argv)
    assert "--dockerized" in s
    assert "-F floorplan" in s and "-T floorplan" in s
    assert "--run-tag t1" in s


# --------------------------------------------------------------------------- #3/#6
def test_container_tool_argv_magic_uses_rcfile_and_mounts():
    from lanex.controller import container_tools

    argv = container_tools.build_argv(
        "docker", "ghcr.io/librelane/librelane:3.0.4", "magic",
        design_dir=Path("/proj"), work_dir=Path("/proj/runs/r1"),
        gds=Path("/proj/runs/r1/final/gds/top.gds"),
        pdk="sky130A", pdk_root="/pdks",
    )
    s = " ".join(argv)
    assert s.startswith("docker run --rm")
    assert "-v /proj:/proj" in s          # design dir mounted at same path
    assert "-v /pdks:/pdks" in s          # PDK root mounted
    assert "PDK_ROOT=/pdks" in s
    assert "magic -rcfile /pdks/sky130A/libs.tech/magic/sky130A.magicrc" in s
    assert s.endswith("/proj/runs/r1/final/gds/top.gds")


def test_container_tool_openroad_is_gui():
    from lanex.controller import container_tools
    argv = container_tools.build_argv(
        "podman", "img", "openroad",
        design_dir=Path("/d"), work_dir=Path("/d/runs/r1"),
        odb=Path("/d/runs/r1/final/odb/x.odb"),
    )
    assert argv[:3] == ["podman", "run", "--rm"]
    assert argv[-2:] == ["openroad", "-gui"]


def test_display_available_returns_shape():
    from lanex.controller import container_tools
    d = container_tools.display_available()
    assert "ok" in d and "reason" in d


# --------------------------------------------------------------------------- #5
def test_customcell_vars_are_real():
    from lanex.controller import customcells, introspect
    real = {v["name"] if isinstance(v, dict) else getattr(v, "name", "")
            for v in introspect.list_variables()}
    for spec in customcells._VIEW_VARS.values():
        assert spec["var"] in real, f"{spec['var']} not a real LibreLane variable"
    assert "EXTRA_EXCLUDED_CELLS" in real


def test_customcell_save_requires_lef_and_builds_overrides(tmp_path):
    from lanex.controller import customcells

    libb = base64.b64encode(b"library(x){}").decode()
    # No LEF -> rejected.
    bad = customcells.save_cell(str(tmp_path), "c1", views={"lib": {"filename": "c1.lib", "content_b64": libb}})
    assert not bad["ok"]

    lefb = base64.b64encode(b"MACRO c1\nEND c1\n").decode()
    ok = customcells.save_cell(
        str(tmp_path), "c1", swap_out=["sky130_fd_sc_hd__nand2_1"],
        views={"lef": {"filename": "c1.lef", "content_b64": lefb},
               "lib": {"filename": "c1.lib", "content_b64": libb}},
    )
    assert ok["ok"]
    assert (tmp_path / "custom_cells" / "c1" / "c1.lef").is_file()
    ov = customcells.build_overrides(str(tmp_path))
    assert ov["EXTRA_LEFS"].startswith("dir::custom_cells/c1/")
    assert ov["EXTRA_LIBS"]
    assert ov["EXTRA_EXCLUDED_CELLS"] == "sky130_fd_sc_hd__nand2_1"

    # Disabling removes it from the run overrides.
    customcells.set_enabled(str(tmp_path), "c1", False)
    assert customcells.build_overrides(str(tmp_path)) == {}


def test_customcell_name_rejects_traversal(tmp_path):
    from lanex.controller import customcells
    lefb = base64.b64encode(b"MACRO x\nEND x\n").decode()
    bad = customcells.save_cell(str(tmp_path), "../escape",
                                views={"lef": {"filename": "x.lef", "content_b64": lefb}})
    assert not bad["ok"]


def test_customcell_merge_appends():
    from lanex.controller import customcells
    out = customcells.merge_into({"EXTRA_LEFS": "user.lef"},
                                 {"EXTRA_LEFS": "cc.lef", "EXTRA_EXCLUDED_CELLS": "a"})
    assert out["EXTRA_LEFS"] == "user.lef cc.lef"
    assert out["EXTRA_EXCLUDED_CELLS"] == "a"


def test_customcell_wrong_extension_rejected(tmp_path):
    from lanex.controller import customcells
    b = base64.b64encode(b"data").decode()
    bad = customcells.save_cell(str(tmp_path), "c",
                                views={"lef": {"filename": "c.txt", "content_b64": b}})
    assert not bad["ok"] and "lef" in bad["error"].lower()


# --------------------------------------------------------------------------- #4
@pytest.mark.parametrize("cmd,ok", [
    ("librelane --dockerized config.json -T floorplan", True),
    ("openroad -version", True),
    ("python -m librelane x", True),
    ("docker ps", True),
    ("sudo rm -rf /", False),
    ("rm -rf x", False),
    ("python -c import_os", False),
    ("yosys -V; echo hi", False),
    ("cat /etc/passwd | grep root", False),
    ("", False),
])
def test_manual_validate_allowlist(cmd, ok):
    from lanex.controller import manualcmd
    assert manualcmd.validate(cmd)["ok"] is ok


def test_manual_python_only_librelane():
    from lanex.controller import manualcmd
    assert not manualcmd.validate("python -m pip install evil")["ok"]
    assert manualcmd.validate("python3 -m librelane config.json")["ok"]


def test_cli_command_container_ordering():
    from lanex.controller import manualcmd
    r = manualcmd.cli_command_for(
        design_dir="/d/proj", config_file="/d/proj/config.json", flow="Classic",
        pdk="sky130A", scl="sky130_fd_sc_hd", pdk_root="/pdks", run_mode="container",
        to="floorplan", overrides={"FP_CORE_UTIL": 45},
    )
    c = r["container"]
    # Host flag (--pdk-root) MUST precede --dockerized; config relative to design.
    assert c.index("--pdk-root") < c.index("--dockerized")
    assert "config.json" in c and "-T floorplan" in c
    assert "-c FP_CORE_UTIL=45" in c
    assert r["recommended"] == "container"


def test_cli_command_mirrors_dockerized_argv_with_sources_and_overlay():
    # A3: cli_command_for must faithfully reproduce build_dockerized_argv — the
    # Setup picker sources become VERILOG_FILES/EXTRA_FILES overrides and the
    # macro overlay rides as an extra CONFIG_FILE positional. Omitting them made
    # the revealed / persisted command run different RTL (or drop macros).
    import shlex
    from lanex.controller import manualcmd, container_run

    kw = dict(
        design_dir="/d/proj", config_file="/d/proj/config.json", flow="Classic",
        pdk="sky130A", scl="sky130_fd_sc_hd", pdk_root="/pdks", run_mode="container",
        tag="spm-1", overrides={"FP_CORE_UTIL": 45},
        extra_sources=["src/spm.v", "verify/tb.v"], extra_extras=["ip/mem.v"],
        extra_config_files=["/d/proj/.gui-macros.json"],
    )
    revealed = shlex.split(manualcmd.cli_command_for(**kw)["container"])
    # The real argv the container path would execute for the same inputs:
    argv = container_run.build_dockerized_argv(
        config_file="/d/proj/config.json", design_dir=Path("/d/proj"),
        flow="Classic", pdk="sky130A", scl="sky130_fd_sc_hd", pdk_root="/pdks",
        tag="spm-1", overrides={"FP_CORE_UTIL": 45},
        extra_sources=["src/spm.v", "verify/tb.v"], extra_extras=["ip/mem.v"],
        extra_config_files=["/d/proj/.gui-macros.json"],
    )
    # Overlay positional present, sources folded into list overrides.
    assert ".gui-macros.json" in revealed
    joined = " ".join(revealed)
    assert "VERILOG_FILES=src/spm.v verify/tb.v" in joined
    assert "EXTRA_FILES=ip/mem.v" in joined
    # Everything from --dockerized onward (the inner librelane invocation) must be
    # identical. The two differ only in the host launcher prefix — cli_command_for
    # shows `librelane`, build_dockerized_argv uses `python3 -m librelane` — which
    # the audit test plan explicitly allows.
    assert revealed[revealed.index("--dockerized"):] == argv[argv.index("--dockerized"):]
