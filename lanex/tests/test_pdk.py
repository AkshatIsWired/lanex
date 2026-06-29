# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for :mod:`lanex.controller.pdk`.

These do not create fake PDK trees; they assert graceful behaviour with the
absence of one.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_list_pdks_no_pdk_root(monkeypatch, tmp_path: Path):
    """With no PDK_ROOT, home, or ciel, returns empty list."""
    monkeypatch.delenv("PDK_ROOT", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from lanex.controller import pdk

    out = pdk.list_pdks()
    assert isinstance(out, list)


def test_check_pdk_ready_no_env(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("PDK_ROOT", raising=False)
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    from lanex.controller import pdk

    info = pdk.check_pdk_ready("sky130A", "sky130_fd_sc_hd")
    assert info["ready"] is False
    assert info["remediation"]
    assert "missing" in info and info["missing"]


def test_check_pdk_ready_partial_install(monkeypatch, tmp_path: Path):
    """A libs.ref/<scl> dir exists but no .lib -> ready=False with reason."""
    pdk_root = tmp_path / "pdk"
    pdk_dir = pdk_root / "sky130A"
    (pdk_dir / "libs.ref" / "sky130_fd_sc_hd").mkdir(parents=True)
    monkeypatch.setenv("PDK_ROOT", str(pdk_root))
    from lanex.controller import pdk

    info = pdk.check_pdk_ready("sky130A", "sky130_fd_sc_hd")
    assert info["ready"] is False
    assert any("lib" in m for m in info["missing"])
