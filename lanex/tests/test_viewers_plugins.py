# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Tests for cell parsing and the desktop tool launcher guards."""
from __future__ import annotations

from pathlib import Path

from lanex.controller import cells


# ---- cells -----------------------------------------------------------------

def test_parse_lef_macros():
    lef = """
VERSION 5.7 ;
MACRO sky130_fd_sc_hd__inv_1
  SIZE 1.38 BY 2.72 ;
END sky130_fd_sc_hd__inv_1
MACRO sky130_fd_sc_hd__dfxtp_1
END sky130_fd_sc_hd__dfxtp_1
MACRO sky130_fd_sc_hd__inv_1
END sky130_fd_sc_hd__inv_1
"""
    macros = cells.parse_lef_macros(lef)
    assert macros == ["sky130_fd_sc_hd__inv_1", "sky130_fd_sc_hd__dfxtp_1"]  # de-duped


def test_classify_cell():
    assert cells.classify_cell("sky130_fd_sc_hd__dfxtp_1") == "sequential"
    assert cells.classify_cell("sky130_fd_sc_hd__inv_2") == "inverter"
    assert cells.classify_cell("sky130_fd_sc_hd__nand2_1") == "combinational"
    assert cells.classify_cell("sky130_fd_sc_hd__decap_3") == "physical"


def test_list_pdk_cells_missing_pdk(monkeypatch):
    # A PDK/SCL that exists nowhere on disk → honest not-found (the lookup now
    # searches all candidate roots incl. ciel homes, so use a bogus name rather
    # than a real PDK that might actually be installed here).
    monkeypatch.delenv("PDK_ROOT", raising=False)
    res = cells.list_pdk_cells("nonexistent_pdk_xyz", "nonexistent_scl_xyz")
    assert res["ok"] is False
    assert res["cells"] == []


# ---- desktop launcher guards -------------------------------------------------

def test_desktop_open_in_tool_guards(tmp_path: Path):
    from lanex.controller import desktop
    # Unknown tool is rejected.
    assert desktop.open_in_tool("rm-rf", tmp_path / "x.gds")["ok"] is False
    # Missing file is rejected even for a whitelisted tool.
    r = desktop.open_in_tool("klayout", tmp_path / "nope.gds")
    assert r["ok"] is False
    # available_tools reports the whitelist with availability flags.
    tools = {t["key"] for t in desktop.available_tools()}
    assert {"klayout", "gds3d", "magic"} <= tools


def test_plugin_surface_removed():
    """The Add-ons/plugins ghost feature is gone for good: no controller module,
    no /api/plugins routes. Locks the removal so it can't drift back."""
    import importlib

    import pytest as _pytest

    with _pytest.raises(ModuleNotFoundError):
        importlib.import_module("lanex.controller.plugins")
    from lanex.server.routes import ROUTES
    assert not [p for p, _h in ROUTES if p.startswith("/api/plugins")]
