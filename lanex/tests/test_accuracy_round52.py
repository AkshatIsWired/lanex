# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Round-52 accuracy/robustness lock-ins.

Covers: three-state DRC parsing (a missing/empty report must never render as
clean), custom cell/macro input hygiene (whitespace, atomic sidecars, YAML
MACROS merge, Tcl replace warning), the magicrc lookup fallbacks, list-override
joining, the numeric step-ordinal .odb sort, and the completed-but-mangled run
success heuristic.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest


# --------------------------------------------------------------- parse_drc 3-state
def test_parse_drc_real_report_is_parsed(tmp_path: Path):
    from lanex.controller import reports

    f = tmp_path / "drc.rpt"
    f.write_text(
        "spm\n"
        "----------------------------------------\n"
        "P-diff distance to N-tap must be < 15.0um (LU.3)\n"
        "----------------------------------------\n"
        "17.990um 21.995um 18.265um 22.995um\n"
        "----------------------------------------\n",
        encoding="utf-8",
    )
    out = reports.parse_drc(f)
    assert out["status"] == "parsed"
    assert len(out["violations"]) == 1


def test_parse_drc_whitespace_only_is_error(tmp_path: Path):
    from lanex.controller import reports

    f = tmp_path / "drc.rpt"
    f.write_text("   \n\n  ", encoding="utf-8")
    out = reports.parse_drc(f)
    assert out["status"] == "error"
    assert out["violations"] == []


# ------------------------------------------------------------- custom cells hygiene
def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def test_save_cell_rejects_whitespace_swap_out(tmp_path: Path):
    from lanex.controller import customcells

    res = customcells.save_cell(
        tmp_path, "mycell",
        swap_out=["sky130_fd_sc_hd__and2_1", "bad name"],
        views={"lef": {"filename": "mycell.lef", "content_b64": _b64(b"LEF")}},
    )
    assert res["ok"] is False
    assert "whitespace" in res["error"]


def test_save_cell_sanitises_spaced_filename(tmp_path: Path):
    from lanex.controller import customcells

    res = customcells.save_cell(
        tmp_path, "mycell",
        views={"lef": {"filename": "my cell v2.lef", "content_b64": _b64(b"LEF")}},
    )
    assert res["ok"] is True
    path = res["cell"]["views"]["lef"]
    assert " " not in path
    assert path.startswith("dir::custom_cells/mycell/")
    # The file really exists at the sanitised path.
    assert (tmp_path / path.replace("dir::", "")).is_file()


def test_save_macro_sanitises_spaced_filename(tmp_path: Path):
    from lanex.controller import custommacros

    res = custommacros.save_macro(
        tmp_path, "mymac",
        views={
            "gds": {"filename": "my mac.gds", "content_b64": _b64(b"GDS")},
            "lef": {"filename": "my mac.lef", "content_b64": _b64(b"LEF")},
        },
    )
    assert res["ok"] is True
    for kind in ("gds", "lef"):
        assert " " not in res["macro"]["views"][kind]


def test_sidecar_survives_partial_write(tmp_path: Path, monkeypatch):
    """Atomic sidecar: a crash mid-save must leave the previous content intact."""
    from lanex.controller import customcells, platform_env

    customcells.save_cell(
        tmp_path, "keepme",
        views={"lef": {"filename": "k.lef", "content_b64": _b64(b"LEF")}},
    )
    sidecar = tmp_path / ".gui-custom-cells.json"
    before = sidecar.read_text(encoding="utf-8")

    real_replace = platform_env.os.replace if hasattr(platform_env, "os") else None

    def _boom(path, text, **kw):
        raise OSError("disk full")

    monkeypatch.setattr(platform_env, "atomic_write_text", _boom)
    res = customcells.save_cell(
        tmp_path, "other",
        views={"lef": {"filename": "o.lef", "content_b64": _b64(b"LEF")}},
    )
    assert res["ok"] is False
    # The sidecar was NOT truncated by the failed save.
    assert sidecar.read_text(encoding="utf-8") == before
    assert real_replace is None or callable(real_replace)


def test_atomic_write_text_roundtrip(tmp_path: Path):
    from lanex.controller import platform_env

    f = tmp_path / "x.json"
    platform_env.atomic_write_text(f, '{"a": 1}\n')
    assert json.loads(f.read_text(encoding="utf-8")) == {"a": 1}
    # Overwrite works and leaves no stray temp files behind.
    platform_env.atomic_write_text(f, '{"a": 2}\n')
    assert json.loads(f.read_text(encoding="utf-8")) == {"a": 2}
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


# ------------------------------------------------------- MACROS merge + warning
def test_user_config_macros_merges_yaml(tmp_path: Path):
    from lanex.controller import custommacros

    pytest.importorskip("yaml")
    (tmp_path / "config.yaml").write_text(
        "MACROS:\n  their_mac:\n    gds: [a.gds]\n    lef: [a.lef]\n",
        encoding="utf-8",
    )
    custommacros.save_macro(
        tmp_path, "gui_mac",
        views={
            "gds": {"filename": "g.gds", "content_b64": _b64(b"G")},
            "lef": {"filename": "g.lef", "content_b64": _b64(b"L")},
        },
    )
    merged = custommacros.build_macros_dict(tmp_path)
    # The user's yaml MACROS entry rides along; the GUI macro is added.
    assert "their_mac" in merged
    assert "gui_mac" in merged


def test_merge_warning_for_tcl_macros(tmp_path: Path):
    from lanex.controller import custommacros

    (tmp_path / "config.tcl").write_text('set ::env(MACROS) "..."\n', encoding="utf-8")
    # No enabled macros -> no warning.
    assert custommacros.merge_warning(tmp_path) is None
    custommacros.save_macro(
        tmp_path, "m1",
        views={
            "gds": {"filename": "m.gds", "content_b64": _b64(b"G")},
            "lef": {"filename": "m.lef", "content_b64": _b64(b"L")},
        },
    )
    warn = custommacros.merge_warning(tmp_path)
    assert warn and "MACROS" in warn
    # A JSON config alongside means we merge instead -> no warning.
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    assert custommacros.merge_warning(tmp_path) is None


# --------------------------------------------------------------- magicrc lookup
def test_find_magicrc_exact_family_glob(tmp_path: Path, monkeypatch):
    from lanex.controller import desktop, installer

    libs = tmp_path / "libs.tech"
    magic = libs / "magic"
    magic.mkdir(parents=True)

    monkeypatch.setattr(installer, "_pdk_family", lambda p: "gf180mcu", raising=False)

    # Nothing there -> None (and the caller must then omit -rcfile).
    assert desktop.find_magicrc(libs, "gf180mcuC") is None
    # Family-level file (the gf180 .lyp naming variance, applied to magic).
    fam = magic / "gf180mcu.magicrc"
    fam.write_text("# rc", encoding="utf-8")
    assert desktop.find_magicrc(libs, "gf180mcuC") == fam
    # Exact per-variant file wins over family.
    exact = magic / "gf180mcuC.magicrc"
    exact.write_text("# rc", encoding="utf-8")
    assert desktop.find_magicrc(libs, "gf180mcuC") == exact


# --------------------------------------------------------- whitespace file guard
def test_whitespace_guard_covers_selected_files():
    from lanex.server.routes import _whitespace_path_error

    assert _whitespace_path_error("/ok/dir", None, files=["/ok/dir/a.v"]) is None
    err = _whitespace_path_error("/ok/dir", None, files=["/ok/dir/my file.v"])
    assert err and "my file.v" in err


# ------------------------------------------------------------ numeric .odb sort
def test_final_odb_numeric_step_ordering(tmp_path: Path):
    from lanex.server.routes import _final_odb

    # No final/odb -> fall back to the LATEST step numerically: 100 > 55 even
    # though "100-" sorts before "55-" lexicographically.
    for step in ("55-openroad-a", "100-openroad-b"):
        d = tmp_path / step
        d.mkdir()
        (d / "design.odb").write_text("", encoding="utf-8")
    pick = _final_odb(tmp_path)
    assert pick is not None and pick.parent.name == "100-openroad-b"


# ------------------------------------------- completed-but-mangled run heuristic
def test_success_requires_finished_steps_when_no_metrics(tmp_path: Path):
    from lanex.controller.history import _success_from_metrics

    run = tmp_path / "runs" / "t"
    (run / "final").mkdir(parents=True)          # "completed"
    step = run / "07-openroad-floorplan"
    step.mkdir()
    (step / "state_in.json").write_text("{}", encoding="utf-8")
    (step / "state_out.json").write_text("{}", encoding="utf-8")
    # Clean partial run (no metrics, every step finished) -> success.
    assert _success_from_metrics({}, run_dir=run) is True
    # An aborted step next to final/ -> the run dir is mangled; NOT success.
    bad = run / "08-openroad-place"
    bad.mkdir()
    (bad / "state_in.json").write_text("{}", encoding="utf-8")
    assert _success_from_metrics({}, run_dir=run) is False
