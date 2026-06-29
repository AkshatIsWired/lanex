# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for :mod:`lanex.controller.tools` and :mod:`installer`."""
from __future__ import annotations

import os
import shutil
import sys

import pytest


def test_check_tools_runs():
    from lanex.controller import tools

    info = tools.check_tools()
    assert info["platform"] in {"linux", "darwin", "windows"}
    assert isinstance(info["tools"], list)
    assert len(info["tools"]) >= 8
    sample = next((t for t in info["tools"] if t["key"] == "python"), None)
    assert sample is not None
    # Python should always be installed (we're being run by it).
    assert sample["installed"] is True
    assert sample["path"]


def test_check_tools_eda_categorised():
    from lanex.controller import tools

    info = tools.check_tools()
    by_cat = {}
    for t in info["tools"]:
        by_cat.setdefault(t["category"], []).append(t["key"])
    assert "core" in by_cat
    assert "eda" in by_cat
    assert "yosys" in by_cat["eda"]


def test_install_tool_known_pip():
    from lanex.controller import tools

    info = tools.install_tool("yosys")
    # yosys is manual-install (not pip), so argv None expected.
    assert info["key"] == "yosys"
    # The recipe should be a non-empty string on Linux.
    if sys.platform.startswith("linux"):
        assert info.get("reason") or info.get("recipe")


def test_install_tool_pip_argv():
    from lanex.controller import tools

    info = tools.install_tool("ciel")
    # ciel IS pip-installable.
    argv = info.get("argv")
    assert argv is not None
    assert "pip" in argv


def test_install_tool_unknown_key():
    from lanex.controller import tools

    info = tools.install_tool("this-tool-does-not-exist")
    assert info["argv"] is None


def test_check_tools_reports_container_engine():
    from lanex.controller import tools

    info = tools.check_tools()
    assert "container" in info
    c = info["container"]
    # Always reports availability + the version-matched image ref, even with no
    # engine installed.
    assert set(c) >= {"available", "engine", "image", "image_present"}
    assert isinstance(c["available"], bool)
    assert "librelane" in c["image"]


def test_check_tools_has_no_fabricated_sizes():
    # The old build shipped hand-invented per-tool ``size_mb`` numbers; those are
    # gone. We now surface a clearly-approximate ``approx_mb`` instead, and a
    # measured on-disk size for installed PDKs.
    from lanex.controller import tools

    info = tools.check_tools()
    for t in info["tools"]:
        assert "size_mb" not in t
    # Container block now reports version/min-version, daemon usability + an
    # approx image size.
    c = info["container"]
    assert set(c) >= {"version", "min_version", "version_ok", "image_approx_mb", "daemon_ok", "ready"}
    # "ready" requires the daemon to be usable, not just the binary present.
    assert c["ready"] == (bool(c["available"]) and bool(c["daemon_ok"]))
    # PDK block carries measured sizes for whatever is installed (a dict).
    assert isinstance(info["pdk"].get("installed_sizes_mb", {}), dict)


def test_engine_install_strategies_resolve_without_executing():
    # Docker/Podman must be real, installable keys — verify the strategy
    # registry produces concrete argv for the current platform. We only call
    # prepare(); we never execute (that would touch the host package manager).
    from lanex.controller import installer

    env = installer.detect_environment()
    found = {"docker": [], "podman": []}
    for s in installer._strategies_for(env):
        for key in ("docker", "podman"):
            argv = s["prepare"](env, key)
            if argv:
                found[key].append(argv)
    # On any supported platform at least one engine should have a recipe; if the
    # host genuinely has no package manager, guidance still covers it.
    assert installer._verify_install("docker") in (True, False)
    assert "container engine" in installer._install_guidance("docker")
    if env["os"] == "linux" and env["apt"]:
        assert any("podman" in a for a in found["podman"])
        assert any("docker" in " ".join(a) for a in found["docker"])


def test_install_accepts_present_binary_despite_nonzero_exit(monkeypatch):
    # apt installs docker.io fine but its postinst can't start the daemon in a
    # sandbox and returns non-zero. The tool IS installed — we must not report
    # that as a failure (and must not fall through to a doomed fallback).
    from lanex.controller import installer

    monkeypatch.setattr(installer, "_run_argv", lambda argv, **k: {"ok": False, "rc": 100})
    monkeypatch.setattr(installer, "_verify_install", lambda key: key == "docker")
    res = installer.install_tool("docker")
    assert res["ok"] is True
    assert res["rc"] == 100  # surfaced honestly, but treated as installed


def test_uninstall_gds3d_removes_user_binary(monkeypatch, tmp_path):
    # GDS3D has no package manager; uninstall = delete the source-built binary.
    # The user-local copy (~/.local/bin/gds3d) needs no privileges.
    from lanex.controller import installer

    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    binary = home / ".local" / "bin" / "gds3d"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setattr(installer.Path, "home", classmethod(lambda cls: home))

    res = installer.uninstall_tool("gds3d")
    assert res["ok"] is True
    assert not binary.exists()
    assert str(binary) in res["removed"]


def test_uninstall_gds3d_absent_is_honest(monkeypatch, tmp_path):
    # Nothing to remove -> not a crash, an honest "not found".
    from lanex.controller import installer

    monkeypatch.setattr(installer.Path, "home", classmethod(lambda cls: tmp_path))
    # Pretend no /usr/local/bin/gds3d either.
    res = installer.uninstall_tool("gds3d")
    if not res["ok"]:
        assert "not found" in res["reason"]


def test_pull_image_fails_fast_without_engine_or_daemon():
    # With no usable engine, pull must return actionable guidance immediately
    # rather than launching a doomed background pull that looks like a hang.
    from lanex.controller import installer

    res = installer.pull_image()
    if not res.get("ok"):
        assert res.get("reason")
        # When a binary exists but the daemon is unreachable we also guide.
        assert "guidance" in res or "Install Docker or Podman" in res["reason"]


def test_no_double_download_guard():
    # A second install/pull/PDK request for something already in progress must be
    # refused (no concurrent duplicate download), keyed by job id.
    from lanex.controller import installer

    assert installer._begin_job("yosys") is True
    try:
        r = installer.install_tool("yosys")
        assert r["ok"] is False and r.get("in_progress") is True
    finally:
        installer._end_job("yosys")

    assert installer._begin_job("pdk:sky130A") is True
    try:
        r = installer.install_pdk("sky130A")
        assert r.get("in_progress") is True
    finally:
        installer._end_job("pdk:sky130A")


def test_cancel_keeps_resume_cache():
    # Cancelling must NOT wipe the download cache — that's what lets the next
    # attempt resume instead of re-downloading gigabytes.
    import inspect
    from lanex.controller import installer

    assert "rmtree" not in inspect.getsource(installer.cancel_install)


def test_openroad_install_returns_guidance_not_fake_command():
    # OpenROAD has no pip/apt package; the installer must fail gracefully with
    # actionable guidance rather than inventing a `yowasp-openroad` package.
    from lanex.controller import installer

    res = installer.install_tool("openroad")
    if res.get("ok"):
        # Already installed in this environment — nothing to assert.
        return
    assert "guidance" in res and res["guidance"]
    assert "yowasp-openroad" not in (res.get("reason", "") + res.get("guidance", ""))
