# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Tests for cell parsing and the plugin store (Phase 4)."""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from lanex.controller import cells, plugins


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


# ---- plugins ---------------------------------------------------------------

def _make_plugin_zip(tmp_path: Path) -> tuple[Path, str]:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("index.js", "export function init(sdk){}\n")
    data = buf.getvalue()
    archive = tmp_path / "plug.zip"
    archive.write_bytes(data)
    return archive, hashlib.sha256(data).hexdigest()


def test_plugin_install_verify_lifecycle(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LIBRELANE_GUI_HOME", str(tmp_path / "home"))
    archive, sha = _make_plugin_zip(tmp_path)
    manifest = {"id": "demo", "name": "Demo", "version": "1.0.0", "kind": "tab",
                "entry": "index.js", "sha256": sha}
    res = plugins.install(manifest, archive_path=str(archive))
    assert res["ok"], res
    installed = plugins.list_installed()
    assert any(p["id"] == "demo" for p in installed)
    # enable/disable
    assert plugins.set_enabled("demo", False)["ok"]
    assert any(p["id"] == "demo" and p["enabled"] is False for p in plugins.list_installed())
    # remove
    assert plugins.remove("demo")["ok"]
    assert plugins.list_installed() == []


def test_plugin_install_rejects_checksum_mismatch(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LIBRELANE_GUI_HOME", str(tmp_path / "home"))
    archive, _sha = _make_plugin_zip(tmp_path)
    manifest = {"id": "bad", "sha256": "deadbeef" * 8}
    res = plugins.install(manifest, archive_path=str(archive))
    assert res["ok"] is False
    assert "checksum mismatch" in res["error"]
    assert not (plugins.plugins_home() / "bad").exists()


def test_plugin_install_requires_sha(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LIBRELANE_GUI_HOME", str(tmp_path / "home"))
    archive, _ = _make_plugin_zip(tmp_path)
    res = plugins.install({"id": "nohash"}, archive_path=str(archive))
    assert res["ok"] is False


def test_bundled_registry_used_when_remote_unreachable(tmp_path: Path, monkeypatch):
    # No cache + unreachable remote -> the GUI's bundled curated catalog is shown
    # (so the Add-ons tab is never empty offline), with built-in + external entries.
    monkeypatch.setenv("LIBRELANE_GUI_HOME", str(tmp_path / "home"))
    reg = plugins.fetch_registry(url="http://127.0.0.1:9/nope.json", timeout=0.2)
    assert isinstance(reg, list) and len(reg) >= 1
    ids = {p.get("id") for p in reg}
    assert "viewer-3d" in ids
    statuses = {p.get("status") for p in reg}
    assert "built-in" in statuses and "external" in statuses


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
