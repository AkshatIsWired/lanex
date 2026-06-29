# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Tests for editor write-guard, Verilator lint parsing, and sim command (Phase 3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lanex.controller import editor, lint, simulate


# ---- editor ----------------------------------------------------------------

def test_write_inside_ok(tmp_path: Path):
    res = editor.write_text(tmp_path, "src/foo.v", "module foo; endmodule\n")
    assert res["ok"]
    assert (tmp_path / "src" / "foo.v").read_text().startswith("module foo")


def test_write_rejects_traversal(tmp_path: Path):
    res = editor.write_text(tmp_path, "../escape.v", "x")
    assert res["ok"] is False


def test_write_rejects_absolute(tmp_path: Path):
    res = editor.write_text(tmp_path, "/etc/passwd", "x")
    assert res["ok"] is False


def test_write_rejects_bad_extension(tmp_path: Path):
    res = editor.write_text(tmp_path, "evil.sh", "rm -rf /")
    assert res["ok"] is False


def test_write_rejects_symlink_escape(tmp_path: Path):
    outside = tmp_path.parent / "outside_dir"
    outside.mkdir()
    design = tmp_path / "design"
    design.mkdir()
    (design / "link").symlink_to(outside)
    res = editor.write_text(design, "link/pwned.v", "x")
    assert res["ok"] is False


def test_write_is_atomic_no_partial(tmp_path: Path):
    editor.write_text(tmp_path, "a.v", "original")
    # A failing write (bad ext) must not touch the existing file.
    editor.write_text(tmp_path, "a.exe", "nope")
    assert (tmp_path / "a.v").read_text() == "original"


# ---- lint ------------------------------------------------------------------

def test_parse_verilator():
    log = (
        "%Error: top.v:12:7: syntax error, unexpected ';'\n"
        "%Warning-WIDTH: bar.sv:30:14: Operator ADD expects 8 bits\n"
        "some unrelated line\n"
        "%Error-UNUSED: baz.v:3: Signal is unused\n"
    )
    diags = lint.parse_verilator(log)
    assert len(diags) == 3
    assert diags[0] == {"file": "top.v", "line": 12, "col": 7, "severity": "error",
                        "code": "", "msg": "syntax error, unexpected ';'"}
    assert diags[1]["severity"] == "warning" and diags[1]["code"] == "WIDTH"
    assert diags[2]["col"] == 1  # no column -> default 1
    s = lint.summarize(diags)
    assert s["errors"] == 2 and s["warnings"] == 1


# ---- simulate --------------------------------------------------------------

def test_build_sim_command_container():
    argv = simulate.build_sim_command(
        "/work/design", top="counter", sources=["src/counter.v"],
        testbench="verify/counter_tb.v", trace="vcd", run_mode="container",
        engine="docker", image="ghcr.io/librelane/librelane:1.2.3",
    )
    assert argv[0] == "docker" and "run" in argv and "--rm" in argv
    assert "ghcr.io/librelane/librelane:1.2.3" in argv
    assert argv[-3] == "bash" and argv[-2] == "-lc" and argv[-1].startswith("set -e;")
    assert "verilator" in argv[-1] and "--binary" in argv[-1] and "--trace" in argv[-1]
    assert "src/counter.v" in argv[-1] and "verify/counter_tb.v" in argv[-1]


def test_build_sim_command_local_bare():
    argv = simulate.build_sim_command(
        "/work/design", top="t", sources=["a.v"], testbench="tb.v",
        run_mode="local",
    )
    assert argv[0] == "bash" and argv[1] == "-lc"
    assert "docker" not in argv[0]


def test_build_sim_command_fst():
    argv = simulate.build_sim_command("/d", top="t", sources=["a.v"], testbench="tb.v",
                                      trace="fst", run_mode="local")
    assert "--trace-fst" in argv[-1]


def test_build_sim_command_iverilog():
    argv = simulate.build_sim_command("/d", top="tb", sources=["a.v"], testbench="tb.v",
                                      run_mode="local", sim_engine="iverilog")
    shell = argv[-1]
    assert "iverilog" in shell and "vvp" in shell
    assert "-s tb" in shell
    assert "verilator" not in shell


def test_find_testbenches(tmp_path: Path):
    (tmp_path / "verify").mkdir()
    (tmp_path / "verify" / "counter_tb.v").write_text("")
    (tmp_path / "tb_top.sv").write_text("")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "ignored_tb.v").write_text("")
    tbs = simulate.find_testbenches(tmp_path)
    assert "verify/counter_tb.v" in tbs
    assert "tb_top.sv" in tbs
    assert not any("runs" in t for t in tbs)
