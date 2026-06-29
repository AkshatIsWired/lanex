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
"""Round-25 lock-in tests — WSL native-tool foolproofing.

Three root causes, all pure / tool-free (no verilator, Docker, PDK, or network):

* A. **Wrong tool from the Windows PATH** (#4 syntax-check-fires-once, #5 spm sim
     uses the /mnt/c verilator). ``platform_env.linux_only_path`` strips the
     ``/mnt/<drive>/`` dirs under WSL (keeping ``/mnt/wsl`` + Linux dirs) and is a
     no-op off WSL; ``usable_which`` / ``sanitized_env`` / ``installer._check_cmd``
     honour it. PLUS the ``LintJob`` watchdog: a wedged linter is killed so
     ``job.running`` ALWAYS frees (the class-bug behind "works only once").
* B. **apt needs root, GUI couldn't prompt** (#1 graphviz, #6 iverilog —
     "exit None"). ``installer._escalate_argv`` gains root via the controlling
     terminal, else a graphical pkexec, else None (copy-paste fallback).
* C. **GDS3D** (#3 segfault-on-open). ``x11_fixed_fonts_present`` /
     ``_x11_fixed_fonts_missing`` drive the ``xfonts-base`` remediation, surfaced
     both in the installer deps and the ``desktop.open_in_tool`` launch guard.
"""
from __future__ import annotations

import os
import sys
import time

import pytest

from lanex.controller import desktop, events, installer, lint, platform_env, simulate


# ===================================================================== A. PATH
# linux_only_path: strip /mnt/<drive> under WSL, keep /mnt/wsl + Linux dirs.
def test_linux_only_path_strips_windows_mounts_under_wsl(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    raw = os.pathsep.join([
        "/usr/local/bin",
        "/mnt/c/FOSSEE/MSYS/usr/bin",   # Windows verilator lives here — must go
        "/usr/bin",
        "/mnt/d/Tools",                 # another drive mount — must go
        "/mnt/wsl/docker-desktop/cli-tools/usr/bin",  # NOT a drive — must stay
        "/home/u/.local/bin",
    ])
    out = platform_env.linux_only_path(raw).split(os.pathsep)
    assert "/mnt/c/FOSSEE/MSYS/usr/bin" not in out
    assert "/mnt/d/Tools" not in out
    assert "/usr/local/bin" in out
    assert "/usr/bin" in out
    assert "/home/u/.local/bin" in out
    # Docker-Desktop's WSL integration is under /mnt/wsl, NOT a drive — keep it so
    # the container engine still resolves.
    assert "/mnt/wsl/docker-desktop/cli-tools/usr/bin" in out


def test_linux_only_path_noop_off_wsl(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    raw = os.pathsep.join(["/usr/bin", "/mnt/c/Windows/System32"])
    # Off WSL a "/mnt/c" dir is a legitimate mount, not the Windows PATH — untouched.
    assert platform_env.linux_only_path(raw) == raw


def test_linux_only_path_empty_is_safe(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    assert platform_env.linux_only_path("") == ""


def test_usable_which_uses_linux_only_path(monkeypatch):
    # usable_which must hand shutil.which a PATH with the /mnt/c dirs already gone,
    # so a Windows verilator.exe earlier on the inherited PATH is never picked.
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    captured = {}

    def fake_which(name, path=None):
        captured["name"] = name
        captured["path"] = path
        return None

    monkeypatch.setattr(platform_env.shutil, "which", fake_which)
    platform_env.usable_which("verilator", path=os.pathsep.join(["/mnt/c/v", "/usr/bin"]))
    assert captured["name"] == "verilator"
    assert captured["path"] == "/usr/bin"  # /mnt/c stripped before the lookup


def test_sanitized_env_strips_path_keeps_other_keys(monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    env = {
        "PATH": os.pathsep.join(["/mnt/c/Tools", "/usr/bin"]),
        "HOME": "/home/u",
        "FOO": "bar",
    }
    out = platform_env.sanitized_env(env)
    assert out["PATH"] == "/usr/bin"
    assert out["HOME"] == "/home/u"      # non-PATH keys preserved verbatim
    assert out["FOO"] == "bar"
    assert env["PATH"].startswith("/mnt/c")  # input not mutated in place


def test_installer_check_cmd_uses_usable_which(monkeypatch):
    # A Windows tool on /mnt/c must NOT count as installed (usable_which → None),
    # so the GUI offers the native Linux install instead of a false "installed".
    monkeypatch.setattr(platform_env, "usable_which", lambda name: None)
    assert installer._check_cmd("verilator") is False
    monkeypatch.setattr(platform_env, "usable_which", lambda name: "/usr/bin/verilator")
    assert installer._check_cmd("verilator") is True


# --------------------------------------------------------- A. lint watchdog
def _drain_lint_done(cursor):
    for evt in events.bus.events_since(cursor):
        if evt.get("type") == "lint_done":
            return evt
    return None


@pytest.mark.skipif(os.name != "posix", reason="watchdog group-kill is POSIX-only")
def test_lint_watchdog_frees_the_job(tmp_path):
    """A wedged linter must be killed so job.running frees — the fix for
    "Check syntax works only once" (the Windows verilator hanging left the old
    job stuck running, refusing every later lint)."""
    j = lint.LintJob()
    # A linter that never returns (stand-in for the hanging Windows verilator).
    argv = [sys.executable, "-c", "import time; time.sleep(60)"]
    cursor = events.bus.max_seq
    res = j.start(argv, design_dir=str(tmp_path), timeout=1)
    assert res["ok"] is True
    assert j.running is True

    deadline = time.time() + 15
    while j.running and time.time() < deadline:
        time.sleep(0.05)
    assert j.running is False, "watchdog did not kill the wedged lint — job stuck"

    done = _drain_lint_done(cursor)
    assert done is not None, "no lint_done emitted after the watchdog fired"
    assert done["timed_out"] is True
    assert done["ok"] is False  # a timed-out lint is not a pass

    # The job is genuinely free: a second lint is accepted (not "already running").
    again = j.start([sys.executable, "-c", "pass"], design_dir=str(tmp_path), timeout=5)
    assert again["ok"] is True
    while j.running:
        time.sleep(0.02)


# ===================================================================== B. sudo
def test_escalate_argv_prefers_controlling_tty(monkeypatch):
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: True)
    out = installer._escalate_argv(["sudo", "apt-get", "install", "-y", "graphviz"])
    assert out is not None
    argv, inherit_tty = out
    assert inherit_tty is True
    assert argv == ["sudo", "apt-get", "install", "-y", "graphviz"]


def test_escalate_argv_falls_back_to_pkexec(monkeypatch):
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: False)
    monkeypatch.setattr(platform_env, "host_display_available", lambda: True)
    monkeypatch.setattr(installer, "_check_cmd", lambda name: name == "pkexec")
    out = installer._escalate_argv(["sudo", "apt-get", "install", "-y", "iverilog"])
    assert out is not None
    argv, inherit_tty = out
    assert inherit_tty is False
    assert argv == ["pkexec", "apt-get", "install", "-y", "iverilog"]  # sudo→pkexec


def test_escalate_argv_none_when_no_path(monkeypatch):
    # No terminal, no display/pkexec → None → caller shows a copy-paste command.
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: False)
    monkeypatch.setattr(platform_env, "host_display_available", lambda: False)
    monkeypatch.setattr(installer, "_check_cmd", lambda name: False)
    assert installer._escalate_argv(["sudo", "apt-get", "install", "-y", "yosys"]) is None


def test_escalate_argv_pkexec_only_rewrites_plain_sudo(monkeypatch):
    # A `sh -c "… sudo …"` form (e.g. ciel) can't be pkexec-rewritten; with no tty
    # it must fall through to None, not produce a broken pkexec argv.
    monkeypatch.setattr(platform_env, "has_controlling_tty", lambda: False)
    monkeypatch.setattr(platform_env, "host_display_available", lambda: True)
    monkeypatch.setattr(installer, "_check_cmd", lambda name: name == "pkexec")
    assert installer._escalate_argv(["sh", "-c", "apt-get update && sudo apt-get install x"]) is None


# ===================================================================== C. GDS3D
def test_x11_fixed_fonts_missing_tri_state(monkeypatch):
    monkeypatch.setattr(platform_env, "x11_fixed_fonts_present", lambda: False)
    assert installer._x11_fixed_fonts_missing() is True
    # None (can't tell) must NOT be treated as missing — never block on uncertainty.
    monkeypatch.setattr(platform_env, "x11_fixed_fonts_present", lambda: None)
    assert installer._x11_fixed_fonts_missing() is False
    monkeypatch.setattr(platform_env, "x11_fixed_fonts_present", lambda: True)
    assert installer._x11_fixed_fonts_missing() is False


def test_gds3d_font_package_is_xfonts_base():
    assert installer._GDS3D_FONT_PACKAGES == ["xfonts-base"]


def test_open_gds3d_guards_on_missing_x11_fonts(monkeypatch, tmp_path):
    """The launch guard returns the xfonts-base remediation instead of launching
    GDS3D into the segfault when the legacy X11 fonts are absent."""
    gds = tmp_path / "design.gds"
    gds.write_text("")  # f.is_file() gate
    monkeypatch.setattr(desktop, "_resolve_bin", lambda spec: "/usr/bin/gds3d")
    monkeypatch.setattr(platform_env, "host_display_available", lambda: True)
    monkeypatch.setattr(desktop, "_pdk_tech_files", lambda pdk, pdk_root: {})
    monkeypatch.setattr(desktop, "gds3d_process_file", lambda pdk: str(tmp_path / "sky130.txt"))
    monkeypatch.setattr(platform_env, "x11_fixed_fonts_present", lambda: False)
    out = desktop.open_in_tool("gds3d", str(gds), pdk="sky130A")
    assert out["ok"] is False
    assert out["need"] == "x11-fonts"
    assert "xfonts-base" in out["error"]


# ============================================================ caveat: sim PATH
def test_sim_local_argv_is_bash_lc():
    """REMAINS item 3 — local sim is ``bash -lc '…'``. The sanitized PATH is
    exported into the subprocess env (SimJob._run), and WSL injects the Windows
    /mnt/c PATH at interop session-init, NOT via /etc/profile — so re-sourcing
    profile in the login shell does not re-prepend it; the explicit PATH wins.
    Lock the shape so a future edit can't silently drop the leading ``bash``."""
    argv = simulate.build_sim_command(
        "/some/design",
        top="tb",
        sources=["tb.v", "dut.v"],
        testbench="tb.v",
        sim_engine="iverilog",
        run_mode="local",
    )
    assert argv[0] == "bash"
    assert argv[1] == "-lc"
