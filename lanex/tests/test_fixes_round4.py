# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Lock-in tests for the round-4 user-reported fixes.

Tool-free / pure: build fixtures on disk and assert the pure controller logic.
Covers cell-usage parsing (the Analytics breakdown) and GDS3D launch resolution.
"""
from __future__ import annotations

from pathlib import Path

# A trimmed Rich "Cells by Master" report exactly as Odb.CellFrequencyTables
# writes it (heavy bars on the header/borders, light │ on data rows).
_CELL_RPT = (
    "                         Cells by Master\n"
    "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┓\n"
    "┃ Cell                                  ┃ Count   ┃\n"
    "┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━┩\n"
    "│ sky130_fd_sc_hd__decap_3              │ 819     │\n"
    "│ sky130_fd_sc_hd__inv_2                │ 64      │\n"
    "│ sky130_fd_sc_hd__and2_2               │ 32      │\n"
    "└───────────────────────────────────────┴─────────┘\n"
)


def _make_run_with_cellfreq(tmp_path: Path) -> Path:
    run = tmp_path / "runs" / "test-run"
    step = run / "53-odb-cellfrequencytables"
    step.mkdir(parents=True)
    (step / "cell.rpt").write_text(_CELL_RPT, encoding="utf-8")
    # A decoy stats JSON that the OLD code mistook for a cell table.
    (step / "odb-cellfrequencytables.process_stats.json").write_text(
        '{"time": {"runtime": "00:00:00.8"}, "peak_resources": {"cpu_percent": 101}}',
        encoding="utf-8",
    )
    return run


def test_cell_usage_parses_cells_by_master(tmp_path):
    from lanex.controller import history

    run = _make_run_with_cellfreq(tmp_path)
    rows = history.cell_usage(run)
    cells = {r["cell"]: r["count"] for r in rows}
    # Real masters + counts, sorted by count desc.
    assert cells == {
        "sky130_fd_sc_hd__decap_3": 819,
        "sky130_fd_sc_hd__inv_2": 64,
        "sky130_fd_sc_hd__and2_2": 32,
    }
    assert rows[0]["cell"] == "sky130_fd_sc_hd__decap_3"
    # The stats JSON keys must NOT leak in as bogus "cells".
    assert "time" not in cells and "peak_resources" not in cells


def test_cell_usage_ignores_stats_json_without_rpt(tmp_path):
    # If only the stats JSON exists (no cell.rpt), we must NOT report its keys as
    # cells — better to return nothing than garbage.
    from lanex.controller import history

    run = tmp_path / "runs" / "r"
    step = run / "01-odb-cellfrequencytables"
    step.mkdir(parents=True)
    (step / "x.process_stats.json").write_text(
        '{"time": {"runtime": "1"}, "peak_resources": {"cpu": 1}}', encoding="utf-8")
    assert history.cell_usage(run) == []


def test_gds3d_argv_includes_process_file():
    from lanex.controller import desktop

    tech = {"gds3d_process": "/tf/sky130.txt"}
    argv = desktop._build_argv("gds3d", "gds3d", "/x.gds", tech, True)
    # GDS3D needs -p <process> or it opens nothing.
    assert argv == ["gds3d", "-p", "/tf/sky130.txt", "-i", "/x.gds"]


def test_gds3d_process_file_maps_pdk(tmp_path, monkeypatch):
    from lanex.controller import desktop

    tf = tmp_path / "tools" / "GDS3D" / "techfiles"
    tf.mkdir(parents=True)
    for name in ("sky130.txt", "sky130_s10.txt", "sg13g2.txt"):
        (tf / name).write_text("# techfile\n", encoding="utf-8")
    monkeypatch.setenv("LIBRELANE_GUI_HOME", str(tmp_path))

    # sky130A -> sky130.txt (shortest stem wins over sky130_s10.txt).
    assert Path(desktop.gds3d_process_file("sky130A")).name == "sky130.txt"
    # ihp-sg13g2 -> sg13g2.txt
    assert Path(desktop.gds3d_process_file("ihp-sg13g2")).name == "sg13g2.txt"
    # gf180mcuD -> none shipped here.
    assert desktop.gds3d_process_file("gf180mcuD") is None


def test_relativize_to_handles_space_and_absolute(tmp_path):
    # Round-14 fix (was code-done but untested): VERILOG_FILES is a
    # whitespace-separated override, so a design dir with a SPACE + host-absolute
    # paths corrupt the list and don't exist in the container. _relativize_to must
    # turn paths under the design dir into bare, space-free, dir-relative names.
    from lanex.controller.runner import _relativize_to
    from pathlib import Path

    base = tmp_path / "processor codes"   # NOTE the space
    (base / "src").mkdir(parents=True)
    a = base / "control.v"; a.write_text("//", encoding="utf-8")
    b = base / "src" / "alu.v"; b.write_text("//", encoding="utf-8")
    out = _relativize_to([str(a), str(b)], base)
    assert out == ["control.v", "src/alu.v"]            # no space, dir-relative
    assert all(" " not in p for p in out)
    # Already-relative paths pass through unchanged.
    assert _relativize_to(["control.v"], base) == ["control.v"]
    # Paths outside the design dir are left as-is (can't be relativised).
    assert _relativize_to(["/elsewhere/x.v"], base) == ["/elsewhere/x.v"]
    assert _relativize_to(None, base) == []


def test_desktop_resolve_bin_finds_capital_gds3d(tmp_path, monkeypatch):
    # GDS3D's Makefile emits a capital "GDS3D"; resolution must find it via alts.
    from lanex.controller import desktop

    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "GDS3D"
    exe.write_text("#!/bin/sh\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir), prepend=False)
    assert desktop._resolve_bin(desktop._TOOLS["gds3d"]) == str(exe)
