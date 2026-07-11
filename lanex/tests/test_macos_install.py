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

import json
import os
import sys
from pathlib import Path

from lanex.controller import container_tools, installer, platform_env
from lanex.controller import tools as tools_mod


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


# ------------------------------ bug 1: sudo-in-cask needs a GUI askpass ----

def test_ensure_darwin_path_adds_docker_app_bin(monkeypatch):
    # docker-credential-desktop lives inside Docker.app; without its bin dir on
    # PATH `docker pull` dies "docker-credential-desktop: executable file not
    # found in $PATH" even with Docker Desktop installed.
    docker_bin = "/Applications/Docker.app/Contents/Resources/bin"
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(platform_env.os.path, "isdir", lambda d: d == docker_bin)
    platform_env.ensure_darwin_path()
    assert docker_bin in os.environ["PATH"].split(":")


def test_darwin_askpass_helper_is_runnable_osascript(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform_env, "home", lambda: tmp_path)
    p = installer._darwin_askpass_path()
    assert p is not None
    script = Path(p)
    assert script.is_file() and os.access(p, os.X_OK)
    body = script.read_text()
    assert body.startswith("#!/bin/sh")
    assert "osascript" in body and "with hidden answer" in body


def test_darwin_askpass_none_off_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert installer._darwin_askpass_path() is None


def test_install_env_sets_sudo_askpass_on_macos(monkeypatch, tmp_path):
    # Homebrew adds `sudo -A` (graphical prompt) only when SUDO_ASKPASS is set —
    # that's what makes the docker-desktop cask installable with no terminal.
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform_env, "home", lambda: tmp_path)
    env = installer._install_env()
    assert env.get("SUDO_ASKPASS", "").endswith("askpass.sh")
    assert os.path.isfile(env["SUDO_ASKPASS"])


def test_install_env_no_askpass_off_macos(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert "SUDO_ASKPASS" not in installer._install_env()


def test_docker_install_announces_password_dialog(monkeypatch):
    # The user must be told a macOS password dialog is coming (it's not obvious).
    events = []
    monkeypatch.setattr(installer, "_emit",
                        lambda kind, payload: events.append((kind, payload)))
    monkeypatch.setattr(installer, "_brew_path", lambda: "/usr/local/bin/brew")
    monkeypatch.setattr(installer, "_run_argv",
                        lambda *a, **k: {"ok": True, "rc": 0, "output": []})
    monkeypatch.setattr(installer, "_is_cancelled", lambda key: False)
    monkeypatch.setattr(installer.subprocess, "Popen", lambda *a, **k: None)
    installer._install_engine_macos("docker")
    msgs = [p.get("message", "") for _, p in events]
    assert any("password dialog" in m for m in msgs)
    assert any(p.get("needs_password") for _, p in events)


# ---------------- bug 2: pull past a broken Docker credential helper ----

def test_docker_cred_helper_error_detected():
    real = ('error getting credentials - err: exec: "docker-credential-desktop": '
            "executable file not found in $PATH, out: ``")
    assert installer._docker_cred_helper_error(real) is True
    assert installer._docker_cred_helper_error("no space left on device") is False
    assert installer._docker_cred_helper_error("") is False


def test_no_creds_docker_env_strips_credstore(monkeypatch, tmp_path):
    home = tmp_path / "lanexhome"
    docker_cfg = tmp_path / "dot-docker"
    docker_cfg.mkdir()
    (docker_cfg / "config.json").write_text(json.dumps({
        "credsStore": "desktop",
        "credHelpers": {"ghcr.io": "desktop"},
        "proxies": {"default": {"httpProxy": "http://x"}},
    }))
    monkeypatch.setattr(platform_env, "home", lambda: home)
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p: str(docker_cfg / "config.json")
                        if p == "~/.docker/config.json" else p)
    env = installer._no_creds_docker_env()
    cfg_path = Path(env["DOCKER_CONFIG"]) / "config.json"
    data = json.loads(cfg_path.read_text())
    assert "credsStore" not in data and "credHelpers" not in data
    # Unrelated settings survive so a proxied setup still works.
    assert data.get("proxies", {}).get("default", {}).get("httpProxy") == "http://x"


def test_pull_retries_without_credential_helper(monkeypatch):
    calls = []

    def fake_run_argv(argv, *, label="", key="", timeout_s=None, env_extra=None):
        calls.append({"argv": list(argv), "env_extra": env_extra})
        if len(calls) == 1:
            return {"ok": False, "rc": 1, "output": [
                'error getting credentials - err: exec: '
                '"docker-credential-desktop": executable file not found in $PATH']}
        return {"ok": True, "rc": 0, "output": ["Status: Downloaded"]}

    class _SyncThread:
        def __init__(self, target=None, **kw):
            self._t = target

        def start(self):
            if self._t:
                self._t()

    monkeypatch.setattr(installer.shutil, "which",
                        lambda n: "/x/docker" if n == "docker" else None)
    monkeypatch.setattr(tools_mod, "resolve_engine",
                        lambda: {"ready": True, "engine": "docker"})
    monkeypatch.setattr(installer, "_run_argv", fake_run_argv)
    monkeypatch.setattr(installer, "_begin_job", lambda key: True)
    monkeypatch.setattr(installer, "_end_job", lambda key: None)
    monkeypatch.setattr(installer, "_no_creds_docker_env",
                        lambda: {"DOCKER_CONFIG": "/tmp/nocreds"})
    monkeypatch.setattr(installer, "record_image_digest",
                        lambda *a, **k: "sha256:deadbeef")
    monkeypatch.setattr(installer.threading, "Thread", _SyncThread)

    res = installer.pull_image()
    assert res["ok"] is True
    assert len(calls) == 2               # first pull failed, retried
    assert calls[0]["env_extra"] is None
    assert calls[1]["env_extra"] == {"DOCKER_CONFIG": "/tmp/nocreds"}
