# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Viewer data-handoff contracts (round 56).

Every layout viewer must receive ALL the run data it can render, with
existence-guarded flags — these tests lock the whole handoff surface:

* OpenROAD  — startup tcl: read_db → define_corners → read_liberty -corner →
              read_sdc → read_spef, PLUS the marker/DRC inventory (modern
              OpenROAD stores DRC results as odb marker categories; the old
              ``gui::load_drc`` command no longer exists) and the on-disk DRT
              report pointer with its violation count.
* KLayout   — layer properties (-l) and the run's DRC/XOR report databases
              (-m), host and container.
* Magic     — -rcfile only when the magicrc exists.
* GDS3D     — -p process file required.

The fixture is a synthetic LibreLane run dir shaped like the real one
(numbered step dirs, reports in the PRODUCING step's dir, not final/).
"""

from pathlib import Path

import pytest

from lanex.controller import container_tools, desktop


TR_REPORT_2 = (
    "violation type: Short\n"
    "  srcs: net1 net2\n"
    "  bbox = ( 1.0, 2.0 ) - ( 3.0, 4.0 ) on Layer met1\n"
    "violation type: MetSpc\n"
    "  srcs: net3\n"
    "  bbox = ( 5.0, 6.0 ) - ( 7.0, 8.0 ) on Layer met2\n"
)

RDB = "<?xml version='1.0'?><report-database></report-database>\n"


def _mk_run(tmp_path: Path, *, violations: bool = True, with_reports: bool = True) -> Path:
    run = tmp_path / "runs" / "RUN_A"
    (run / "final" / "gds").mkdir(parents=True)
    (run / "final" / "odb").mkdir(parents=True)
    (run / "final" / "sdc").mkdir(parents=True)
    (run / "final" / "spef" / "nom").mkdir(parents=True)
    (run / "final" / "gds" / "spm.gds").write_bytes(b"\x00\x06\x00\x02\x02\x58")
    (run / "final" / "odb" / "spm.odb").write_bytes(b"odb")
    (run / "final" / "sdc" / "spm.sdc").write_text("create_clock\n")
    (run / "final" / "spef" / "nom" / "spm.nom.spef").write_text("*SPEF\n")
    lib = tmp_path / "tt.lib"
    lib.write_text("library(tt) {}\n")
    (run / "resolved.json").write_text(
        '{"DEFAULT_CORNER": "nom_tt_025C_1v80",'
        ' "LIB": {"*_tt_025C_1v80": ["%s"]}}' % lib
    )
    if with_reports:
        drt = run / "44-openroad-detailedrouting"
        drt.mkdir()
        (drt / "spm.drc").write_text(TR_REPORT_2 if violations else "")
        (drt / "spm.drc.xml").write_text(RDB)
        (run / "64-magic-drc" / "reports").mkdir(parents=True)
        (run / "64-magic-drc" / "reports" / "drc.magic.lyrdb").write_text(RDB)
        (run / "65-klayout-drc" / "reports").mkdir(parents=True)
        (run / "65-klayout-drc" / "reports" / "drc.klayout.lyrdb").write_text(RDB)
        (run / "62-klayout-xor").mkdir()
        (run / "62-klayout-xor" / "xor.xml").write_text(RDB)
    return run


# ---------------------------------------------------------------- discovery --

def test_find_run_reports_full(tmp_path) -> None:
    run = _mk_run(tmp_path)
    rep = desktop.find_run_reports(run)
    assert rep["drt_drc"] == run / "44-openroad-detailedrouting" / "spm.drc"
    assert rep["drt_violations"] == 2
    names = [p.name for p in rep["marker_dbs"]]
    assert names == ["drc.klayout.lyrdb", "drc.magic.lyrdb", "spm.drc.xml", "xor.xml"]


def test_find_run_reports_clean_run_counts_zero(tmp_path) -> None:
    rep = desktop.find_run_reports(_mk_run(tmp_path, violations=False))
    assert rep["drt_drc"] is not None
    assert rep["drt_violations"] == 0


def test_find_run_reports_absent_are_absent(tmp_path) -> None:
    rep = desktop.find_run_reports(_mk_run(tmp_path, with_reports=False))
    assert rep["drt_drc"] is None
    assert rep["drt_violations"] is None
    assert rep["marker_dbs"] == []
    # And a nonexistent dir never raises.
    rep2 = desktop.find_run_reports(tmp_path / "nope")
    assert rep2["marker_dbs"] == []


def test_find_run_reports_numeric_step_ordering(tmp_path) -> None:
    # "104-" must beat "44-" (numeric, not lexicographic — routes._final_odb
    # lesson). The LATEST detailed-routing step's report wins.
    run = _mk_run(tmp_path)
    late = run / "104-openroad-detailedrouting-1"
    late.mkdir()
    (late / "spm.drc").write_text("")
    rep = desktop.find_run_reports(run)
    assert rep["drt_drc"] == late / "spm.drc"
    assert rep["drt_violations"] == 0


# ------------------------------------------------------------ OpenROAD tcl --

def _openroad_tcl(tmp_path, **mk_kwargs) -> str:
    run = _mk_run(tmp_path, **mk_kwargs)
    sp = container_tools._write_startup_script(
        "openroad", run, odb=run / "final" / "odb" / "spm.odb",
        pdk=None, pdk_root=None)
    assert sp is not None
    return sp.read_text()


def test_openroad_tcl_loads_everything(tmp_path) -> None:
    tcl = _openroad_tcl(tmp_path)
    assert "read_db" in tcl
    assert "define_corners nom_tt_025C_1v80" in tcl
    assert "read_liberty -corner nom_tt_025C_1v80" in tcl
    assert "read_sdc" in tcl
    assert "read_spef -corner nom_tt_025C_1v80" in tcl


def test_openroad_tcl_marker_inventory_present(tmp_path) -> None:
    tcl = _openroad_tcl(tmp_path)
    # The db marker walk (DRC results live INSIDE the odb in modern OpenROAD).
    assert "getMarkerCategories" in tcl
    assert "getMarkerCount" in tcl
    # Clean runs must be EXPLAINED, not silently empty.
    assert "zero violations" in tcl
    # Violating runs pop the viewer open.
    assert "gui::show_widget drc_viewer" in tcl
    assert "gui::select_marker_category" in tcl
    # Everything is catch-guarded — a headless/odd build can't abort the GUI.
    assert "marker inventory failed" in tcl


def test_openroad_tcl_points_at_drt_report_with_count(tmp_path) -> None:
    tcl = _openroad_tcl(tmp_path)
    assert "44-openroad-detailedrouting" in tcl
    assert "spm.drc (2 violation(s))" in tcl


def test_openroad_tcl_no_reports_still_generates(tmp_path) -> None:
    tcl = _openroad_tcl(tmp_path, with_reports=False)
    assert "read_db" in tcl
    assert "getMarkerCategories" in tcl      # inventory always runs
    assert "DRC report on disk" not in tcl   # no false pointer


def test_openroad_tcl_never_mentions_removed_load_drc(tmp_path) -> None:
    # gui::load_drc was removed upstream; generating it would error every launch.
    tcl = _openroad_tcl(tmp_path)
    assert "load_drc" not in tcl


# ----------------------------------------------------------- KLayout argv --

def test_container_klayout_argv_has_markers_in_order(tmp_path) -> None:
    run = _mk_run(tmp_path)
    rep = desktop.find_run_reports(run)
    argv = container_tools._tool_command(
        "klayout", gds=run / "final" / "gds" / "spm.gds",
        pdk=None, pdk_root=None, odb=None, marker_dbs=rep["marker_dbs"])
    # -m binds to the layout BEFORE it: gds first, then one -m per database.
    gds_i = argv.index(str(run / "final" / "gds" / "spm.gds"))
    m_paths = [argv[i + 1] for i, a in enumerate(argv) if a == "-m"]
    assert [Path(p).name for p in m_paths] == [
        "drc.klayout.lyrdb", "drc.magic.lyrdb", "spm.drc.xml", "xor.xml"]
    assert all(argv.index(p) > gds_i for p in m_paths)


def test_container_klayout_argv_no_markers_no_flags(tmp_path) -> None:
    run = _mk_run(tmp_path, with_reports=False)
    argv = container_tools._tool_command(
        "klayout", gds=run / "final" / "gds" / "spm.gds",
        pdk=None, pdk_root=None, odb=None, marker_dbs=[])
    assert "-m" not in argv


def test_host_klayout_argv_markers_after_layout(tmp_path) -> None:
    run = _mk_run(tmp_path)
    rep = desktop.find_run_reports(run)
    tech = {"klayout_lyp": None, "marker_dbs": rep["marker_dbs"]}
    argv = desktop._build_argv("klayout", "klayout",
                               str(run / "final" / "gds" / "spm.gds"), tech, True)
    assert argv.count("-m") == 4
    assert argv.index("-m") > argv.index(str(run / "final" / "gds" / "spm.gds"))


def test_host_open_in_tool_only_attaches_markers_for_run_files(tmp_path, monkeypatch) -> None:
    # A GDS OUTSIDE the run (a cell, another design) must NOT get this run's
    # markers — they name the run's top cell and would overlay wrong geometry.
    run = _mk_run(tmp_path)
    foreign = tmp_path / "cell.gds"
    foreign.write_bytes(b"\x00\x06\x00\x02\x02\x58")
    captured = {}

    monkeypatch.setattr(desktop, "_resolve_bin", lambda spec: "klayout")
    monkeypatch.setattr(desktop.subprocess, "Popen",
                        lambda argv, **k: captured.setdefault("argv", argv))
    try:
        from lanex.controller import platform_env
        monkeypatch.setattr(platform_env, "host_display_available", lambda: True)
        monkeypatch.setattr(platform_env, "mesa_dri_present", lambda: True)
    except Exception:
        pass

    res = desktop.open_in_tool("klayout", run / "final" / "gds" / "spm.gds", run_dir=run)
    assert res["ok"] is True
    assert captured["argv"].count("-m") == 4
    assert res.get("marker_dbs") and len(res["marker_dbs"]) == 4

    captured.clear()
    res2 = desktop.open_in_tool("klayout", foreign, run_dir=run)
    assert res2["ok"] is True
    assert "-m" not in captured["argv"]
    assert "marker_dbs" not in res2


# ------------------------------------------------------- Magic / GDS3D argv --

def test_magic_argv_rcfile_only_when_present(tmp_path) -> None:
    argv = desktop._build_argv("magic", "magic", "x.gds", {"magicrc": None}, True)
    assert "-rcfile" not in argv
    argv2 = desktop._build_argv("magic", "magic", "x.gds", {"magicrc": "/pdk/x.magicrc"}, True)
    assert argv2[:3] == ["magic", "-rcfile", "/pdk/x.magicrc"]


def test_gds3d_argv_requires_process_file() -> None:
    argv = desktop._build_argv("gds3d", "GDS3D", "x.gds", {"gds3d_process": "/t/sky130.txt"}, True)
    assert argv == ["GDS3D", "-p", "/t/sky130.txt", "-i", "x.gds"]
