# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for :mod:`lanex.controller.fsbrowser`."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

import pytest


def test_list_dir_returns_entries(tmp_path: Path):
    from lanex.controller import fsbrowser

    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "inner.txt").write_text("hello")
    (tmp_path / "top.v").write_text("// empty")
    out = fsbrowser.list_dir(str(tmp_path))
    assert out["ok"]
    names = sorted(e["name"] for e in out["entries"])
    assert names == ["sub", "top.v"]
    assert out["entries"][0]["is_dir"] is True
    assert out["entries"][1]["is_dir"] is False


def test_list_dir_rejects_missing(tmp_path: Path):
    from lanex.controller import fsbrowser

    out = fsbrowser.list_dir(str(tmp_path / "nosuch"))
    assert out["ok"] is False
    assert "not a directory" in out["error"]


def test_walk_sources_finds_every_verilog(tmp_path: Path):
    from lanex.controller import fsbrowser

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.v").write_text("// a")
    (tmp_path / "src" / "b.sv").write_text("// b")
    (tmp_path / "src" / "header.vh").write_text("// header")
    (tmp_path / "src" / "ignore.me").write_text("// nope")
    (tmp_path / "src" / "data.mem").write_text("@0")
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "x").write_text("drop")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("0")
    out = fsbrowser.walk_sources(str(tmp_path))
    assert out["ok"]
    sources = [s["name"] for s in out["sources"]]
    assert "a.v" in sources
    assert "b.sv" in sources
    assert "header.vh" in sources
    assert "ignore.me" not in sources
    assert "drop" not in sources  # runs/ skipped
    mems = [m["name"] for m in out["memories"]]
    assert mems == ["data.mem"]


def test_walk_sources_includes_nested(tmp_path: Path):
    from lanex.controller import fsbrowser

    (tmp_path / "modules" / "alu").mkdir(parents=True)
    (tmp_path / "modules" / "alu" / "alu.v").write_text("// alu")
    (tmp_path / "modules" / "cpu.v").write_text("// cpu")
    out = fsbrowser.walk_sources(str(tmp_path))
    names = [s["relpath"] for s in out["sources"]]
    assert "modules/cpu.v" in names
    assert "modules/alu/alu.v" in names


def test_read_text_bounded(tmp_path: Path):
    from lanex.controller import fsbrowser

    p = tmp_path / "tiny.v"
    p.write_text("// tiny")
    out = fsbrowser.read_text(str(p))
    assert out["ok"]
    assert out["text"] == "// tiny"


def test_read_text_rejects_oversize(tmp_path: Path):
    from lanex.controller import fsbrowser

    p = tmp_path / "big.v"
    # Exceed the read cap (4 MiB, matching the IDE write limit).
    p.write_text("a" * (4 * 1024 * 1024 + 10))
    out = fsbrowser.read_text(str(p))
    assert out["ok"] is False
    assert "too large" in out["error"]
    # An explicit tighter cap is honoured too.
    small = tmp_path / "small.v"
    small.write_text("a" * 2048)
    assert fsbrowser.read_text(str(small), max_bytes=1024)["ok"] is False


def test_list_run_reports_groups_correctly(tmp_path: Path):
    from lanex.controller import fsbrowser

    design = tmp_path
    runs = design / "runs"
    run = runs / "RUN_TEST"
    run.mkdir(parents=True)
    # Layout like LibreLane's run output.
    step_dir = run / "1-Magic.DRC"
    step_dir.mkdir()
    (step_dir / "drc.rpt").write_text("violations: 0\n")
    step_dir2 = run / "2-Netgen.LVS"
    step_dir2.mkdir()
    (step_dir2 / "lvs.rpt").write_text("lvs\n")
    step_dir3 = run / "3-OpenROAD.RCX"
    step_dir3.mkdir()
    (step_dir3 / "cli.spef").write_text("spef\n")
    step_dir4 = run / "4-OpenROAD.IRDropReport"
    step_dir4.mkdir()
    (step_dir4 / "ir_drop.rpt").write_text("ir\n")

    out = fsbrowser.list_run_reports(str(design), "RUN_TEST")
    assert out["ok"]
    by_kind = {}
    for r in out["reports"]:
        by_kind.setdefault(r["kind"], []).append(r["name"])
    assert "DRC" in by_kind and "drc.rpt" in by_kind["DRC"]
    assert "LVS" in by_kind and "lvs.rpt" in by_kind["LVS"]
    assert "Parasitics" in by_kind and "cli.spef" in by_kind["Parasitics"]
    assert "IR drop" in by_kind and "ir_drop.rpt" in by_kind["IR drop"]
