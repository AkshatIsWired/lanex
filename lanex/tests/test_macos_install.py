# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""macOS install-path fixes: GDS3D prebuilt app, engine installs, XQuartz.

Locks the round-59 macOS foolproofing:

* GDS3D's ``mac/`` tree has NO Makefile (an Xcode project + a prebuilt
  ``GDS3D.app``) — the darwin install must use the prebuilt app, never ``make``.
* ``brew install --cask docker-desktop`` conflicts with leftovers of a previous
  Docker install → retried with ``--force``; podman's "no bottle available"
  (Tier-3 brew) is routed to Docker Desktop guidance; a fresh podman gets its
  one-time ``podman machine`` VM set up.
* Container-tool display checks on macOS reason about XQuartz (installed /
  running / TCP listening), not about the server's own ``$DISPLAY``.

All hermetic: subprocess/argv runners are monkeypatched, nothing executes.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lanex.controller import container_tools, installer, platform_env


# ---------------------------------------------------------------- GDS3D ----

def test_gds3d_darwin_script_uses_prebuilt_app_not_make(tmp_path):
    script = installer._gds3d_darwin_script(tmp_path / "GDS3D", tmp_path / "bin")
    # The exact round-58 macOS failure was `make` in a Makefile-less dir.
    assert " make" not in script and ";make" not in script
    assert "GDS3D.app/Contents/MacOS/GDS3D" in script
    assert installer._GDS3D_REPO in script
    assert script.startswith("set -e; ")
    # Wrapper (not a copy): moving the binary out of the .app would break its
    # bundle resource lookup.
    assert "exec %s" in script or "exec " in script
    assert str(tmp_path / "bin" / "gds3d") in script


def test_gds3d_darwin_script_fails_loud_when_prebuilt_missing(tmp_path):
    script = installer._gds3d_darwin_script(tmp_path / "GDS3D", tmp_path / "bin")
    assert "no longer ships the prebuilt macOS app" in script
    assert "exit 1" in script


def test_gds3d_linux_build_keeps_linux_subdir_only():
    import inspect

    src = inspect.getsource(installer._install_gds3d)
    # The mac branch must exit before the make-based build; the build itself
    # only ever cds into linux/ (the sole tree with a Makefile).
    assert '"mac" if sys.platform' not in src
    assert 'subdir = "linux"' in src
    assert "_install_gds3d_darwin()" in src


# --------------------------------------------------------- brew failures ----

def test_brew_conflict_detects_leftover_binary():
    # Verbatim from the user's failing docker-desktop cask install.
    out = ("Error: It seems there is already a Binary at "
           "'/usr/local/bin/docker-credential-desktop'.")
    assert installer._brew_conflict_needs_force(out) is True
    assert installer._brew_conflict_needs_force(
        "Error: It seems there is already an App at '/Applications/Docker.app'.") is True
    assert installer._brew_conflict_needs_force("Error: something else") is False
    assert installer._brew_conflict_needs_force("") is False


def test_brew_no_bottle_detected():
    # Verbatim from the user's failing podman install (Tier-3 brew config).
    assert installer._brew_no_bottle("Error: podman: no bottle available!") is True
    assert installer._brew_no_bottle("==> Fetching podman") is False


# ------------------------------------------------- macOS engine installs ----

class _ArgvRecorder:
    """Fake _run_argv: returns queued results, records every argv."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, label="", key="", **kw):
        self.calls.append(list(argv))
        return self.results.pop(0) if self.results else {"ok": True, "rc": 0, "output": []}


def test_docker_install_retries_with_force_on_leftover_conflict(monkeypatch):
    rec = _ArgvRecorder([
        {"ok": False, "rc": 1, "output":
            ["Error: It seems there is already a Binary at "
             "'/usr/local/bin/docker-credential-desktop'."]},
        {"ok": True, "rc": 0, "output": ["installed"]},
    ])
    popens = []
    monkeypatch.setattr(installer, "_brew_path", lambda: "/usr/local/bin/brew")
    monkeypatch.setattr(installer, "_run_argv", rec)
    monkeypatch.setattr(installer, "_is_cancelled", lambda key: False)
    monkeypatch.setattr(installer.subprocess, "Popen",
                        lambda argv, **kw: popens.append(list(argv)))
    res = installer._install_engine_macos("docker")
    assert res["ok"] is True
    assert rec.calls[0][-1] == "docker-desktop"
    assert rec.calls[1][-1] == "--force"
    # Docker Desktop must be opened once or "installed" still can't pull.
    assert ["open", "-a", "Docker"] in popens


def test_docker_install_does_not_force_on_unrelated_failure(monkeypatch):
    rec = _ArgvRecorder([{"ok": False, "rc": 1, "output": ["Error: download failed"]}])
    monkeypatch.setattr(installer, "_brew_path", lambda: "/usr/local/bin/brew")
    monkeypatch.setattr(installer, "_run_argv", rec)
    monkeypatch.setattr(installer, "_is_cancelled", lambda key: False)
    monkeypatch.setattr(installer, "_verify_install", lambda key: False)
    res = installer._install_engine_macos("docker")
    assert res["ok"] is False
    assert len(rec.calls) == 1  # no blind --force retry
    assert "docs.docker.com" in res["guidance"]


def test_podman_no_bottle_routes_to_docker_desktop(monkeypatch):
    rec = _ArgvRecorder([{"ok": False, "rc": 1,
                          "output": ["Error: podman: no bottle available!",
                                     "This is a Tier 3 configuration"]}])
    monkeypatch.setattr(installer, "_brew_path", lambda: "/usr/local/bin/brew")
    monkeypatch.setattr(installer, "_run_argv", rec)
    monkeypatch.setattr(installer, "_is_cancelled", lambda key: False)
    monkeypatch.setattr(installer, "_verify_install", lambda key: False)
    res = installer._install_engine_macos("podman")
    assert res["ok"] is False
    assert "Docker Desktop" in res["guidance"]
    assert "--build-from-source" in res["guidance"]


def test_podman_success_sets_up_machine(monkeypatch):
    rec = _ArgvRecorder([
        {"ok": True, "rc": 0, "output": []},        # brew install podman
        {"ok": True, "rc": 0, "output": []},        # podman machine init
        {"ok": True, "rc": 0, "output": []},        # podman machine start
    ])
    monkeypatch.setattr(installer, "_brew_path", lambda: "/usr/local/bin/brew")
    monkeypatch.setattr(installer, "_run_argv", rec)
    monkeypatch.setattr(installer, "_is_cancelled", lambda key: False)
    monkeypatch.setattr(installer, "_podman_path", lambda: "/opt/homebrew/bin/podman")

    class _Done:
        returncode = 0
        stdout = ""       # no machine exists yet
        stderr = ""

    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: _Done())
    res = installer._install_engine_macos("podman")
    assert res["ok"] is True
    assert rec.calls[1][-2:] == ["machine", "init"]
    assert rec.calls[2][-2:] == ["machine", "start"]


def test_podman_machine_skips_init_when_machine_exists(monkeypatch):
    rec = _ArgvRecorder([{"ok": True, "rc": 0, "output": []}])  # machine start only
    monkeypatch.setattr(installer, "_run_argv", rec)
    monkeypatch.setattr(installer, "_is_cancelled", lambda key: False)
    monkeypatch.setattr(installer, "_podman_path", lambda: "/opt/homebrew/bin/podman")

    class _Done:
        returncode = 0
        stdout = "podman-machine-default\n"
        stderr = ""

    monkeypatch.setattr(installer.subprocess, "run", lambda *a, **k: _Done())
    installer._setup_podman_machine("podman")
    assert len(rec.calls) == 1
    assert rec.calls[0][-2:] == ["machine", "start"]


def test_install_tool_routes_engines_to_macos_helper(monkeypatch):
    seen = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(installer, "_install_engine_macos",
                        lambda key: (seen.append(key) or {"ok": True, "method": "brew"}))
    res = installer.install_tool("docker")
    assert res["ok"] is True and seen == ["docker"]


def test_strategy_brew_uses_current_cask_name(monkeypatch):
    monkeypatch.setattr(installer, "_brew_path", lambda: None)
    argv = installer._strategy_brew({}, "docker")
    assert argv[-1] == "docker-desktop" and "--cask" in argv


def test_scoop_no_longer_offers_engine_clients():
    # scoop's docker/podman are bare CLIs with no engine — they verified as
    # "installed" while every container operation failed.
    assert installer._strategy_scoop({}, "docker") is None
    assert installer._strategy_scoop({}, "podman") is None
    assert installer._strategy_scoop({}, "klayout") is not None


# ------------------------------------------------------- XQuartz display ----

def test_darwin_display_not_installed_names_the_cask():
    v = container_tools._darwin_display_status(
        {"installed": False, "running": False, "tcp_ok": None})
    assert v["ok"] is False
    assert "brew install --cask xquartz" in v["reason"]


def test_darwin_display_installed_not_running():
    v = container_tools._darwin_display_status(
        {"installed": True, "running": False, "tcp_ok": None})
    assert v["ok"] is False
    assert "open -a XQuartz" in v["reason"]


def test_darwin_display_running_but_tcp_refused():
    # Modern XQuartz default: nolisten_tcp ON — running yet unreachable from
    # containers. This must be its own precise message, not a generic failure.
    v = container_tools._darwin_display_status(
        {"installed": True, "running": True, "tcp_ok": False})
    assert v["ok"] is False
    assert "nolisten_tcp" in v["reason"]


def test_darwin_display_ok_mentions_xhost():
    v = container_tools._darwin_display_status(
        {"installed": True, "running": True, "tcp_ok": True})
    assert v["ok"] is True
    assert "xhost" in v["reason"]


def test_x11_flags_podman_uses_containers_host_alias(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert "DISPLAY=host.containers.internal:0" in container_tools._x11_flags("podman")
    assert "DISPLAY=host.docker.internal:0" in container_tools._x11_flags("docker")
    # Default stays the docker spelling (Docker Desktop).
    assert "DISPLAY=host.docker.internal:0" in container_tools._x11_flags()


# ------------------------------------------------------------ PATH shim ----

def test_ensure_darwin_path_appends_only_missing_existing_dirs(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setattr(platform_env.os.path, "isdir",
                        lambda d: d in ("/opt/homebrew/bin", "/usr/local/bin"))
    platform_env.ensure_darwin_path()
    import os
    parts = os.environ["PATH"].split(":")
    # Appended (never prepended) so the user's own PATH order wins.
    assert parts[:2] == ["/usr/bin", "/bin"]
    assert "/opt/homebrew/bin" in parts and "/usr/local/bin" in parts
    before = os.environ["PATH"]
    platform_env.ensure_darwin_path()   # idempotent
    assert os.environ["PATH"] == before


def test_ensure_darwin_path_noop_off_macos(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    platform_env.ensure_darwin_path()   # test env is linux — must not touch PATH
    import os
    assert os.environ["PATH"] == "/usr/bin"


def test_brew_path_probes_fixed_prefixes(monkeypatch):
    monkeypatch.setattr(platform_env, "usable_which", lambda n, path=None: None)
    monkeypatch.setattr(installer.os, "access",
                        lambda p, m: p == "/opt/homebrew/bin/brew")
    assert installer._brew_path() == "/opt/homebrew/bin/brew"


def test_resolve_user_bin_finds_klayout_app_bundle(monkeypatch):
    # The brew cask / official .dmg install KLayout as an .app bundle with no
    # CLI on PATH — the Tools tab showed it "missing" while plainly installed.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform_env, "usable_which", lambda n, path=None: None)
    monkeypatch.setattr(platform_env, "user_bin_dirs", lambda: [])
    app_bin = "/Applications/klayout.app/Contents/MacOS/klayout"
    monkeypatch.setattr(platform_env.os.path, "isfile", lambda p: p == app_bin)
    monkeypatch.setattr(platform_env.os, "access", lambda p, m: p == app_bin)
    assert platform_env.resolve_user_bin("klayout") == app_bin
    # No fabricated hits for tools without a known bundle.
    assert platform_env.resolve_user_bin("magic") is None
