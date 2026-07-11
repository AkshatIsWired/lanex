# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Container-availability surface of the Tools tab (round: Add-ons removal).

Locks: the ``in_image`` catalog flags, the bare container-tool launch route,
the image-present launch guard (no silent multi-GB background pull), and the
pull hardening knobs (long watchdog, re-attach flag).
"""
from __future__ import annotations

import inspect
from pathlib import Path

from lanex.controller import container_tools, tools


# ---- catalog flags -----------------------------------------------------------

def test_in_image_flags_cover_the_image_toolchain():
    by_key = {t["key"]: t for t in tools.EDA_TOOLS}
    # Everything the LibreLane image bakes in.
    for key in ("librelane", "yosys", "openroad", "klayout", "magic", "netgen",
                "verilator", "iverilog"):
        assert by_key[key].get("in_image") is True, key
    # Not in the official image — flagging these would promise a tool the
    # container can't deliver.
    for key in ("graphviz", "python", "pip"):
        assert not by_key[key].get("in_image"), key


def test_check_tools_reports_in_container(monkeypatch):
    # Hermetic: fake the probe + engine so no subprocesses run.
    monkeypatch.setattr(tools, "_probe", lambda b, v: {
        "installed": False, "path": "", "version": "", "error": ""})
    monkeypatch.setattr(tools, "_module_probe_fallback", lambda k, info: info)
    monkeypatch.setattr(tools, "container_engine", lambda: {"ready": False})
    monkeypatch.setattr(tools, "build_pdk_catalog", lambda: {})
    monkeypatch.setattr(tools, "_pdk_roots", lambda: [])
    res = tools.check_tools(force=True)
    by_key = {t["key"]: t for t in res["tools"]}
    assert by_key["openroad"]["in_container"] is True
    assert by_key["graphviz"]["in_container"] is False
    tools._check_tools_cache.clear()   # don't poison other tests with fakes


# ---- bare launch route -------------------------------------------------------

def test_container_tool_open_route_registered():
    from lanex.server.routes import ROUTES
    paths = {p for p, _h in ROUTES}
    assert "/api/container-tools/open" in paths


def test_open_in_container_tool_guards_missing_image(monkeypatch, tmp_path: Path):
    # Engine ready but image absent → the launch must refuse with need="image"
    # instead of letting `docker run` pull multi-GB silently in the background.
    monkeypatch.setattr(tools, "resolve_engine",
                        lambda: {"engine": "docker", "ready": True, "sg_wrap": False, "env": {}})
    monkeypatch.setattr(container_tools, "_image_present", lambda *a, **k: False)
    res = container_tools.open_in_container_tool(
        "klayout", design_dir=tmp_path, work_dir=tmp_path)
    assert res["ok"] is False
    assert res.get("need") == "image"


def test_open_in_container_tool_rejects_unknown_tool(tmp_path: Path):
    res = container_tools.open_in_container_tool(
        "rm-rf", design_dir=tmp_path, work_dir=tmp_path)
    assert res["ok"] is False


# ---- pull hardening ----------------------------------------------------------

def test_run_argv_accepts_timeout_override():
    from lanex.controller import installer
    sig = inspect.signature(installer._run_argv)
    assert "timeout_s" in sig.parameters


def test_container_engine_reports_pulling(monkeypatch):
    from lanex.controller import installer
    monkeypatch.setattr(installer, "is_in_progress", lambda key: key == "container:image")
    res = tools.container_engine()
    assert res.get("pulling") is True
