# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Round 27 — WSL GDS3D foolproofing (software GL + auto-install legacy fonts).

These make GDS3D (and other host GL tools) open on WSL without the user having to
run ``wsl --shutdown`` or ``apt-get install xfonts-base`` by hand.
"""
from __future__ import annotations

from lanex.controller import installer, platform_env


# --- Fix A: force software GL under WSL so a stale WSLg vGPU can't deadlock GL --

def test_wsl_gl_env_forces_software_gl_under_wsl(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.delenv("LIBRELANE_GUI_WSL_HW_GL", raising=False)
    env = platform_env.wsl_gl_env({"PATH": "/usr/bin"})
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "1"
    assert env["GALLIUM_DRIVER"] == "llvmpipe"
    assert env["PATH"] == "/usr/bin"          # base preserved


def test_wsl_gl_env_noop_off_wsl(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    env = platform_env.wsl_gl_env({"PATH": "/usr/bin"})
    assert "LIBGL_ALWAYS_SOFTWARE" not in env
    assert env == {"PATH": "/usr/bin"}


def test_wsl_gl_env_opt_out(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.setenv("LIBRELANE_GUI_WSL_HW_GL", "1")
    assert "LIBGL_ALWAYS_SOFTWARE" not in platform_env.wsl_gl_env({})


def test_wsl_gl_env_respects_caller_override(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.delenv("LIBRELANE_GUI_WSL_HW_GL", raising=False)
    env = platform_env.wsl_gl_env({"LIBGL_ALWAYS_SOFTWARE": "0"})
    assert env["LIBGL_ALWAYS_SOFTWARE"] == "0"   # setdefault doesn't clobber


def test_wsl_remediation_mentions_shutdown():
    txt = platform_env.wsl_gl_remediation()
    assert "wsl --shutdown" in txt and "wsl --update" in txt


# --- Fix B: auto-install the legacy X11 fonts GDS3D needs --------------------

def test_ensure_fonts_noop_when_present(monkeypatch):
    monkeypatch.setattr(platform_env, "x11_fixed_fonts_present", lambda: True)
    res = installer.ensure_x11_fixed_fonts()
    assert res["ok"] is True and res.get("already") is True


def test_ensure_fonts_noop_when_unknown(monkeypatch):
    # None = can't tell → never block on an uncertain probe.
    monkeypatch.setattr(platform_env, "x11_fixed_fonts_present", lambda: None)
    assert installer.ensure_x11_fixed_fonts()["ok"] is True


def test_ensure_fonts_guidance_when_no_apt(monkeypatch):
    monkeypatch.setattr(platform_env, "x11_fixed_fonts_present", lambda: False)
    monkeypatch.setattr(installer.shutil, "which", lambda _n: None)
    res = installer.ensure_x11_fixed_fonts()
    assert res["ok"] is False
    assert "xfonts-base" in res.get("manual", "")
