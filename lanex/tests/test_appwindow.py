# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""App-window launcher (controller/appwindow.py) — hermetic lock-in tests.

Every test fakes subprocess/filesystem probes; nothing here launches a real
browser. The contract locked in:
  * discovery order + LANEX_BROWSER override,
  * argv shape (--app first, first-run suppression, dedicated profile),
  * snap/Flatpak sandbox detection → profile flag omitted,
  * spawn verdicts (stays-running/exit-0 = ok, fast non-zero = try next),
  * platform routing (WSL → Windows side first, headless → no attempt),
  * the LANEX_NO_APP_WINDOW / --tab opt-outs,
  * cli._lazy_open prefers the app window and never double-opens.
"""
from __future__ import annotations

import sys

from lanex.controller import appwindow, platform_env


class _FakeProc:
    def __init__(self, rc):
        self._rc = rc

    def poll(self):
        return self._rc


def _no_sleep(monkeypatch):
    monkeypatch.setattr(appwindow.time, "sleep", lambda s: None)


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def test_lanex_browser_env_absolute_path(monkeypatch, tmp_path):
    exe = tmp_path / "mybrowser"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    monkeypatch.setenv("LANEX_BROWSER", str(exe))
    assert appwindow.find_chromium_candidates() == [str(exe)]


def test_lanex_browser_env_missing_yields_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("LANEX_BROWSER", str(tmp_path / "nope"))
    assert appwindow.find_chromium_candidates() == []


def test_lanex_browser_env_bare_name_resolved(monkeypatch):
    monkeypatch.setenv("LANEX_BROWSER", "brave-browser")
    monkeypatch.setattr(platform_env, "usable_which",
                        lambda n, path=None: "/opt/brave/brave-browser" if n == "brave-browser" else None)
    assert appwindow.find_chromium_candidates() == ["/opt/brave/brave-browser"]


def test_candidate_order_prefers_chromium(monkeypatch):
    monkeypatch.delenv("LANEX_BROWSER", raising=False)
    hits = {"chromium": "/usr/bin/chromium", "google-chrome": "/usr/bin/google-chrome"}
    monkeypatch.setattr(platform_env, "usable_which", lambda n, path=None: hits.get(n))
    cands = appwindow.find_chromium_candidates()
    assert cands[0] == "/usr/bin/chromium"
    assert "/usr/bin/google-chrome" in cands


def test_no_browser_found_is_none(monkeypatch):
    monkeypatch.delenv("LANEX_BROWSER", raising=False)
    monkeypatch.setattr(platform_env, "usable_which", lambda n, path=None: None)
    monkeypatch.setattr(appwindow.os.path, "isfile", lambda p: False)
    assert appwindow.find_chromium() is None


# --------------------------------------------------------------------------- #
# Argv + profile
# --------------------------------------------------------------------------- #
def test_build_app_argv_shape():
    argv = appwindow.build_app_argv("/usr/bin/chromium", "http://127.0.0.1:8765/landing",
                                    profile_dir="/home/u/.lanex/app-profile")
    assert argv[0] == "/usr/bin/chromium"
    assert argv[1] == "--app=http://127.0.0.1:8765/landing"
    assert "--no-first-run" in argv
    assert "--no-default-browser-check" in argv
    assert "--user-data-dir=/home/u/.lanex/app-profile" in argv
    if sys.platform.startswith("linux"):
        assert "--class=lanex" in argv


def test_build_app_argv_without_profile():
    argv = appwindow.build_app_argv("/snap/bin/chromium", "http://x")
    assert not any(a.startswith("--user-data-dir") for a in argv)


def test_sandboxed_browser_detection():
    assert appwindow._sandboxed_browser("/snap/bin/chromium") is True
    assert appwindow._sandboxed_browser(
        "/var/lib/flatpak/exports/bin/org.chromium.Chromium") is True
    assert appwindow._sandboxed_browser("/usr/bin/chromium") is False


def test_profile_dir_omitted_for_snap():
    assert appwindow._profile_dir_for("/snap/bin/chromium") is None


def test_profile_dir_created_under_lanex_home():
    d = appwindow._profile_dir_for("/usr/bin/chromium")
    assert d is not None
    assert d == str(platform_env.home() / "app-profile")
    import os
    assert os.path.isdir(d)


def test_profile_dir_unwritable_home_degrades(monkeypatch, tmp_path):
    # A profile dir that cannot be created must NOT block the window.
    blocked = tmp_path / "blocked"
    blocked.write_text("i am a file, not a dir")
    monkeypatch.setattr(platform_env, "home", lambda: blocked)
    assert appwindow._profile_dir_for("/usr/bin/chromium") is None


# --------------------------------------------------------------------------- #
# Spawn verdicts
# --------------------------------------------------------------------------- #
def test_spawn_ok_when_process_stays_running(monkeypatch):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(appwindow.subprocess, "Popen", lambda *a, **k: _FakeProc(None))
    assert appwindow._spawn_ok(["b", "--app=x"]) is True


def test_spawn_ok_on_clean_fast_exit(monkeypatch):
    # Handed off to an already-running instance (or `cmd start` returned) → ok.
    _no_sleep(monkeypatch)
    monkeypatch.setattr(appwindow.subprocess, "Popen", lambda *a, **k: _FakeProc(0))
    assert appwindow._spawn_ok(["b"]) is True


def test_spawn_fails_on_fast_nonzero_exit(monkeypatch):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(appwindow.subprocess, "Popen", lambda *a, **k: _FakeProc(1))
    assert appwindow._spawn_ok(["b"]) is False


def test_spawn_fails_when_popen_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("no such binary")
    monkeypatch.setattr(appwindow.subprocess, "Popen", boom)
    assert appwindow._spawn_ok(["missing"]) is False


def test_posix_launch_falls_through_to_next_candidate(monkeypatch):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(appwindow, "find_chromium_candidates",
                        lambda: ["/usr/bin/broken", "/usr/bin/good"])
    monkeypatch.setattr(appwindow, "_profile_dir_for", lambda b: None)
    monkeypatch.setattr(
        appwindow.subprocess, "Popen",
        lambda argv, **k: _FakeProc(1 if argv[0] == "/usr/bin/broken" else None))
    res = appwindow._launch_posix_app("http://x")
    assert res["ok"] is True
    assert res["method"] == "app"
    assert res["detail"] == "/usr/bin/good"


# --------------------------------------------------------------------------- #
# Platform routing
# --------------------------------------------------------------------------- #
def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("LANEX_NO_APP_WINDOW", "1")
    called = {"spawn": False}
    monkeypatch.setattr(appwindow.subprocess, "Popen",
                        lambda *a, **k: called.__setitem__("spawn", True) or _FakeProc(None))
    res = appwindow.launch_app_window("http://x")
    assert res["ok"] is False
    assert "LANEX_NO_APP_WINDOW" in str(res["detail"])
    assert called["spawn"] is False


def test_headless_makes_no_attempt(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    monkeypatch.setattr(platform_env, "host_display_available", lambda: False)
    called = {"spawn": False}
    monkeypatch.setattr(appwindow.subprocess, "Popen",
                        lambda *a, **k: called.__setitem__("spawn", True) or _FakeProc(None))
    res = appwindow.launch_app_window("http://x")
    assert res["ok"] is False
    assert called["spawn"] is False


def test_wsl_prefers_windows_side(monkeypatch):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.setattr(appwindow, "_windows_app_commands",
                        lambda url: [(["/mnt/c/edge/msedge.exe", f"--app={url}"], None)])
    seen = {}

    def fake_popen(argv, **k):
        seen["argv"] = argv
        return _FakeProc(None)

    monkeypatch.setattr(appwindow.subprocess, "Popen", fake_popen)
    res = appwindow.launch_app_window("http://127.0.0.1:8765/landing")
    assert res["ok"] is True
    assert res["method"] == "windows-app"
    assert seen["argv"][0].endswith("msedge.exe")


def test_wsl_falls_back_to_linux_side(monkeypatch):
    _no_sleep(monkeypatch)
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.setattr(platform_env, "host_display_available", lambda: True)
    monkeypatch.setattr(appwindow, "_windows_app_commands", lambda url: [])
    monkeypatch.setattr(appwindow, "find_chromium_candidates", lambda: ["/usr/bin/chromium"])
    monkeypatch.setattr(appwindow, "_profile_dir_for", lambda b: None)
    monkeypatch.setattr(appwindow.subprocess, "Popen", lambda *a, **k: _FakeProc(None))
    res = appwindow.launch_app_window("http://x")
    assert res["ok"] is True
    assert res["method"] == "app"


def test_windows_app_commands_direct_exe_then_cmd_start(monkeypatch):
    edge = "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
    monkeypatch.setattr(appwindow.os.path, "isfile", lambda p: p == edge)
    monkeypatch.setattr(appwindow.os.path, "isdir", lambda p: p == "/mnt/c")
    monkeypatch.setattr(appwindow.shutil, "which",
                        lambda n: "/mnt/c/Windows/system32/cmd.exe" if n == "cmd.exe" else None)
    monkeypatch.setattr(appwindow, "_windows_localappdata",
                        lambda: "C:\\Users\\t\\AppData\\Local")
    cmds = appwindow._windows_app_commands("http://127.0.0.1:8765/landing")
    # Direct exe first, with a Windows-side dedicated profile.
    argv0, cwd0 = cmds[0]
    assert argv0[0] == edge
    assert argv0[1] == "--app=http://127.0.0.1:8765/landing"
    assert any(a == "--user-data-dir=C:\\Users\\t\\AppData\\Local\\lanex\\app-profile"
               for a in argv0)
    # App-Paths fallback via `cmd start` present for both browsers.
    starts = [argv for argv, _ in cmds if argv[0].endswith("cmd.exe")]
    assert len(starts) == 2
    assert starts[0][:4] == ["/mnt/c/Windows/system32/cmd.exe", "/c", "start", ""]
    assert starts[0][4] == "msedge"
    assert starts[1][4] == "chrome"


def test_windows_app_commands_omit_profile_when_lad_unresolved(monkeypatch):
    edge = "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
    monkeypatch.setattr(appwindow.os.path, "isfile", lambda p: p == edge)
    monkeypatch.setattr(appwindow.shutil, "which", lambda n: None)
    monkeypatch.setattr(appwindow, "_windows_localappdata", lambda: None)
    cmds = appwindow._windows_app_commands("http://x")
    argv0, _ = cmds[0]
    assert not any(a.startswith("--user-data-dir") for a in argv0)


# --------------------------------------------------------------------------- #
# cli integration
# --------------------------------------------------------------------------- #
def test_lazy_open_prefers_app_window(monkeypatch):
    from lanex import cli

    monkeypatch.setattr(appwindow, "launch_app_window",
                        lambda url: {"ok": True, "method": "app", "detail": "/usr/bin/chromium"})
    import webbrowser
    called = {"web": False}
    monkeypatch.setattr(webbrowser, "open",
                        lambda *a, **k: called.__setitem__("web", True) or True)
    cli._lazy_open("http://127.0.0.1:8765/landing", no_browser=False)
    assert called["web"] is False


def test_lazy_open_tab_flag_skips_app_window(monkeypatch):
    from lanex import cli

    called = {"app": False, "web": False}
    monkeypatch.setattr(appwindow, "launch_app_window",
                        lambda url: called.__setitem__("app", True) or {"ok": True})
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open",
                        lambda *a, **k: called.__setitem__("web", True) or True)
    cli._lazy_open("http://x", no_browser=False, tab=True)
    assert called["app"] is False
    assert called["web"] is True


def test_lazy_open_falls_back_to_tab_when_no_app(monkeypatch):
    from lanex import cli

    monkeypatch.setattr(appwindow, "launch_app_window",
                        lambda url: {"ok": False, "method": None, "detail": "none found"})
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    import webbrowser
    called = {"web": False}
    monkeypatch.setattr(webbrowser, "open",
                        lambda *a, **k: called.__setitem__("web", True) or True)
    cli._lazy_open("http://x", no_browser=False)
    assert called["web"] is True


def test_lazy_open_no_browser_does_nothing(monkeypatch):
    from lanex import cli

    called = {"app": False, "web": False}
    monkeypatch.setattr(appwindow, "launch_app_window",
                        lambda url: called.__setitem__("app", True) or {"ok": True})
    import webbrowser
    monkeypatch.setattr(webbrowser, "open",
                        lambda *a, **k: called.__setitem__("web", True) or True)
    cli._lazy_open("http://x", no_browser=True)
    assert called == {"app": False, "web": False}
