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
"""Lock-in tests for the install/compatibility foolproofing round:

* cancel actually cancels — the flag stops strategy loops, and the kill takes
  down the whole process GROUP (the `sh -c` → ciel grandchild orphan bug);
* async tool installs (the 30 s "request timed out" popup fix) — started shape
  + the final ``installer_result`` SSE event;
* pipx compatibility — pip/ciel/librelane detected via the module even when the
  console scripts are off PATH, and ciel invoked as ``python -m ciel``;
* GL foolproofing — the LANEX_HW_GL / LANEX_SOFTWARE_GL overrides on both the
  native env and the container flags, and the Mesa DRI probe;
* IPv6 loopback bind (``--host ::1``).

GOTCHA (round-25): installer/desktop import platform_env lazily — monkeypatch
the REAL ``platform_env`` module, not an attribute on the importer.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time

import pytest

from lanex.controller import container_tools, installer, platform_env, tools


# --------------------------------------------------------------------------- #
# Cancel: flag + process-group kill
# --------------------------------------------------------------------------- #

def test_begin_job_clears_stale_cancel_flag() -> None:
    key = "unit-test-flag"
    installer._mark_cancelled(key)
    assert installer._is_cancelled(key)
    assert installer._begin_job(key)
    try:
        assert not installer._is_cancelled(key)
    finally:
        installer._end_job(key)


def test_cancel_between_strategies_stops_the_loop(monkeypatch) -> None:
    """A cancel that lands while NO subprocess is running (between strategies)
    must stop the job at the next checkpoint — the old code only killed the
    current process, and the loop then started the NEXT strategy's download."""
    key = "faketool-loop"
    calls = []

    def fake_run_argv(argv, *, label, key):
        calls.append(label)
        # Simulate the user cancelling while this strategy runs.
        installer._mark_cancelled(key)
        return {"ok": False, "rc": 1, "output": []}

    def fake_strategies(env):
        return [
            {"label": "one", "methods": ["pip"], "prepare": lambda e, k: ["echo", "1"]},
            {"label": "two", "methods": ["pip"], "prepare": lambda e, k: ["echo", "2"]},
        ]

    monkeypatch.setattr(installer, "_run_argv", fake_run_argv)
    monkeypatch.setattr(installer, "_strategies_for", fake_strategies)
    monkeypatch.setattr(installer, "_verify_install", lambda k: False)

    assert installer._begin_job(key)
    try:
        result = installer._install_tool_impl(key)
    finally:
        installer._end_job(key)
    assert result.get("cancelled") is True
    assert calls == ["one"], "the second strategy must never start after cancel"


def test_cancel_already_cancelled_before_first_strategy(monkeypatch) -> None:
    key = "faketool-precancel"
    monkeypatch.setattr(installer, "_strategies_for", lambda env: [
        {"label": "one", "methods": [], "prepare": lambda e, k: ["echo", "1"]},
    ])
    ran = []
    monkeypatch.setattr(installer, "_run_argv",
                        lambda argv, *, label, key: ran.append(label) or {"ok": True, "rc": 0})
    assert installer._begin_job(key)
    try:
        installer._mark_cancelled(key)
        result = installer._install_tool_impl(key)
    finally:
        installer._end_job(key)
    assert result.get("cancelled") is True
    assert ran == []


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX")
def test_kill_proc_tree_kills_grandchildren() -> None:
    """`sh -c` spawns a grandchild; a plain terminate() orphans it mid-download.
    _kill_proc_tree must take down the whole session/process group."""
    proc = subprocess.Popen(
        ["sh", "-c", "sleep 300 & echo started; wait"],
        stdout=subprocess.PIPE, text=True, start_new_session=True,
    )
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == "started"  # grandchild is alive
    pgid = os.getpgid(proc.pid)
    installer._kill_proc_tree(proc)
    assert proc.poll() is not None
    # The WHOLE group must be gone — signalling it now must fail.
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        os.killpg(pgid, signal.SIGKILL)
        pytest.fail("process group survived _kill_proc_tree")


def test_cancel_install_without_job_reports_not_running() -> None:
    out = installer.cancel_install("never-started-key")
    assert out.get("ok") is False
    assert "not running" in (out.get("reason") or "")


def test_cancel_install_marks_flag_when_job_in_progress_without_proc() -> None:
    key = "inprog-no-proc"
    assert installer._begin_job(key)
    try:
        out = installer.cancel_install(key)
        assert out.get("ok") is True
        assert out.get("status") == "cancelling"
        assert installer._is_cancelled(key)
    finally:
        installer._end_job(key)
        installer._clear_cancelled(key)


def test_run_argv_spawns_its_own_process_group(monkeypatch) -> None:
    """POSIX installs must run in their own session so cancel/timeout can killpg."""
    if os.name != "posix":
        pytest.skip("POSIX only")
    seen = {}
    real_popen = subprocess.Popen

    def spy(argv, **kwargs):
        seen.update(kwargs)
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(installer.subprocess, "Popen", spy)
    res = installer._run_argv(["sh", "-c", "true"], label="unit", key="unit-sns")
    assert res.get("rc") == 0
    assert seen.get("start_new_session") is True


# --------------------------------------------------------------------------- #
# Async tool install (the 30 s timeout popup fix)
# --------------------------------------------------------------------------- #

def test_install_tool_async_started_then_result_event(monkeypatch) -> None:
    from lanex.controller.events import bus

    sentinel = {"ok": False, "reason": "no install method (unit)", "tried": []}
    monkeypatch.setattr(installer, "install_tool", lambda key: dict(sentinel))

    got = []
    handler = lambda kind, payload: kind == "installer_result" and got.append(payload)
    unsub = None
    sub = getattr(bus, "subscribe", None)
    if callable(sub):
        unsub = bus.subscribe(handler)
    else:  # fall back to draining the bus queue via emit monkeypatch
        real_emit = installer._emit
        monkeypatch.setattr(installer, "_emit",
                            lambda kind, payload: (got.append(payload) if kind == "installer_result" else None,
                                                   real_emit(kind, payload))[1])
    resp = installer.install_tool_async("unit-fake-tool")
    assert resp.get("status") == "started" and resp.get("ok") is True
    deadline = time.time() + 5
    while time.time() < deadline and not got:
        time.sleep(0.02)
    assert got, "installer_result event never fired"
    assert got[0].get("key") == "unit-fake-tool"
    assert got[0].get("reason") == sentinel["reason"]
    if unsub:
        unsub()


def test_install_tool_async_refuses_duplicate() -> None:
    key = "unit-dup-tool"
    assert installer._begin_job(key)
    try:
        resp = installer.install_tool_async(key)
        assert resp.get("in_progress") is True
    finally:
        installer._end_job(key)


# --------------------------------------------------------------------------- #
# pipx compatibility: module-aware detection + `python -m ciel`
# --------------------------------------------------------------------------- #

def test_detect_environment_counts_importable_pip_and_ciel(monkeypatch) -> None:
    # Simulate the pipx world: nothing on PATH, modules importable (both are
    # genuinely importable in this test environment).
    monkeypatch.setattr(platform_env, "usable_which", lambda name, path=None: None)
    env = installer.detect_environment()
    assert env["pip"] is True
    assert env["ciel"] is True


def test_ciel_argv_falls_back_to_python_module(monkeypatch) -> None:
    monkeypatch.setattr(installer, "_check_cmd", lambda name: False)
    argv = installer._ciel_argv()
    assert argv is not None
    assert argv[0] == (sys.executable or "python3")
    assert argv[1:] == ["-m", "ciel"]
    cmd = installer._ciel_shell_cmd()
    assert cmd is not None and cmd.endswith("-m ciel")


def test_provision_script_uses_resolved_ciel_cmd() -> None:
    script = installer._ciel_provision_script(
        "/tmp/pdkroot", "sky130A", None, ciel_cmd="'/py' -m ciel")
    assert "'/py' -m ciel fetch" in script
    assert "'/py' -m ciel enable" in script
    # No bare `ciel` invocation may survive when a module cmd was resolved.
    assert " ciel fetch" not in script.replace("-m ciel fetch", "")


def test_pdk_pip_strategy_installs_and_invokes_via_sys_executable(monkeypatch) -> None:
    monkeypatch.setattr(installer, "_ciel_shell_cmd", lambda: None)
    argv = installer._pdk_strategy_ciel({"pip": True}, "sky130A", None)
    assert argv is not None and argv[:2] == ["sh", "-c"]
    import shlex
    py = shlex.quote(sys.executable or "python3")
    assert f"{py} -m pip install ciel" in argv[2]
    assert f"{py} -m ciel fetch" in argv[2]


def test_tools_probe_falls_back_to_module_for_librelane() -> None:
    info = tools._module_probe_fallback("librelane", {"installed": False, "path": "", "version": "", "error": "x"})
    assert info["installed"] is True
    assert info["version"]  # real metadata version
    assert "-m librelane" in info["path"]


def test_tools_probe_fallback_leaves_real_hits_alone() -> None:
    hit = {"installed": True, "path": "/usr/bin/x", "version": "1", "error": ""}
    assert tools._module_probe_fallback("librelane", dict(hit)) == hit


# --------------------------------------------------------------------------- #
# GL foolproofing: overrides + Mesa DRI probe + container flag hatch
# --------------------------------------------------------------------------- #

def test_hw_gl_alias_skips_forcing_under_wsl(monkeypatch) -> None:
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.delenv("LIBRELANE_GUI_WSL_HW_GL", raising=False)
    monkeypatch.setenv("LANEX_HW_GL", "1")
    assert platform_env.wsl_gl_env({}) == {}


def test_software_gl_forced_applies_off_wsl(monkeypatch) -> None:
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    monkeypatch.delenv("LANEX_HW_GL", raising=False)
    monkeypatch.delenv("LIBRELANE_GUI_WSL_HW_GL", raising=False)
    monkeypatch.setenv("LANEX_SOFTWARE_GL", "1")
    env = platform_env.wsl_gl_env({})
    assert env.get("LIBGL_ALWAYS_SOFTWARE") == "1"
    assert env.get("GALLIUM_DRIVER") == "llvmpipe"


def test_container_x11_flags_default_forces_software_gl(monkeypatch) -> None:
    monkeypatch.delenv("LANEX_HW_GL", raising=False)
    monkeypatch.delenv("LIBRELANE_GUI_WSL_HW_GL", raising=False)
    flags = container_tools._x11_flags()
    assert "LIBGL_ALWAYS_SOFTWARE=1" in flags


def test_container_x11_flags_honour_hw_gl_hatch(monkeypatch) -> None:
    monkeypatch.setenv("LANEX_HW_GL", "1")
    flags = container_tools._x11_flags()
    assert "LIBGL_ALWAYS_SOFTWARE=1" not in flags
    assert "GALLIUM_DRIVER=llvmpipe" not in flags


def test_mesa_dri_probe_true_and_false(monkeypatch, tmp_path) -> None:
    if not sys.platform.startswith("linux"):
        pytest.skip("Linux-only probe")
    d = tmp_path / "dri"
    d.mkdir()
    monkeypatch.setattr(platform_env, "_DRI_DIRS", (str(d),))
    monkeypatch.setenv("LIBGL_DRIVERS_PATH", "")
    assert platform_env.mesa_dri_present() is False  # dir exists, no drivers
    (d / "swrast_dri.so").write_bytes(b"")
    assert platform_env.mesa_dri_present() is True


def test_ensure_gl_runtime_noop_when_present(monkeypatch) -> None:
    monkeypatch.setattr(platform_env, "mesa_dri_present", lambda: True)
    out = installer.ensure_gl_runtime()
    assert out == {"ok": True, "already": True}


def test_ensure_gl_runtime_guidance_without_apt(monkeypatch) -> None:
    monkeypatch.setattr(platform_env, "mesa_dri_present", lambda: False)
    monkeypatch.setattr(installer.shutil, "which", lambda name: None)
    out = installer.ensure_gl_runtime()
    assert out.get("ok") is False
    assert "libgl1-mesa-dri" in (out.get("manual") or "")
    assert "dnf" in (out.get("error") or "")  # per-distro guidance present


# --------------------------------------------------------------------------- #
# IPv6 loopback bind
# --------------------------------------------------------------------------- #

def _ipv6_loopback_available() -> bool:
    if not socket.has_ipv6:
        return False
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.bind(("::1", 0))
        s.close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _ipv6_loopback_available(), reason="no IPv6 loopback here")
def test_make_server_binds_ipv6_loopback() -> None:
    import threading
    import urllib.request

    from lanex.server.app import make_server

    httpd, port = make_server(host="::1", port=8971)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        r = urllib.request.urlopen(f"http://[::1]:{port}/api/health", timeout=10)
        assert r.status == 200
    finally:
        httpd.shutdown()


# --------------------------------------------------------------------------- #
# compat: validated-range check must not depend on `packaging`
# --------------------------------------------------------------------------- #

def test_version_range_fallback_matches_packaging_path() -> None:
    from lanex.controller import compat

    assert compat._version_in_range("3.0.4") is True
    assert compat._version_in_range("3.0.99") is True
    assert compat._version_in_range("3.1") is False
    assert compat._version_in_range("3.0.3") is False
    # The tuple fallback agrees.
    assert compat._vtuple("3.0.4") == (3, 0, 4)
    assert compat._vtuple("3.1") == (3, 1, 0)
    assert compat._vtuple("garbage") is None


# --------------------------------------------------------------------------- #
# pyproject ceiling stays in lock-step with compat.KNOWN_GOOD_MAX_EXCL
# --------------------------------------------------------------------------- #

def test_dependency_ceiling_matches_compat_range() -> None:
    from pathlib import Path

    from lanex.controller import compat

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if not pyproject.is_file():
        pytest.skip("repo pyproject not present (installed copy)")
    text = pyproject.read_text(encoding="utf-8")
    expected = f'"librelane>={compat.KNOWN_GOOD_MIN},<{compat.KNOWN_GOOD_MAX_EXCL}"'
    assert expected in text, (
        "pyproject dependency pin must mirror compat.KNOWN_GOOD_* — bump both together"
    )


# --------------------------------------------------------------------------- #
# ciel interrupted-download self-heal (PDK "[Errno 13] Permission denied")
# --------------------------------------------------------------------------- #

def test_provision_script_clears_partial_before_retry() -> None:
    """A failed fetch must clear ONLY the interrupted version dir, then retry."""
    script = installer._ciel_provision_script(
        "/home/u/.ciel", "gf180mcuA", None, ciel_cmd="ciel"
    )
    ver_dir = '"/home/u/.ciel/ciel/gf180mcu/versions/$PDK_VERSION"'
    # Self-heal is scoped to the one interrupted version dir (never all of ~/.ciel).
    assert f"chmod -R u+w {ver_dir}" in script
    assert f"rm -rf {ver_dir}" in script
    # Owner-scoped, no sudo, and non-fatal so a clean first run is unaffected.
    assert "sudo" not in script
    assert "|| true" in script
    # Cleanup happens on the retry path, before `ciel enable`.
    assert script.index("chmod -R u+w") < script.index("enable")


def test_provision_script_clean_first_run_still_fetches_then_enables() -> None:
    script = installer._ciel_provision_script(
        "/root", "sky130A", ["sky130_fd_sc_hd"], ciel_cmd="ciel"
    )
    assert script.index("fetch") < script.index("chmod -R u+w") < script.index("enable")
    assert "-l sky130_fd_sc_hd" in script


def test_repair_ciel_store_restores_write_and_removes_family(tmp_path) -> None:
    import os
    store = tmp_path / "ciel"
    ver = store / "gf180mcu" / "versions" / "abc123"
    ver.mkdir(parents=True)
    (ver / "cell.lef").write_text("x", encoding="utf-8")
    # Simulate ciel's half-extracted, write-stripped directory.
    os.chmod(ver, 0o555)
    other = store / "sky130" / "versions" / "def456"
    other.mkdir(parents=True)

    res = installer.repair_ciel_store("gf180mcuA", pdk_root=str(tmp_path))

    assert res["ok"] is True
    assert not ver.parent.exists()          # gf180mcu versions removed
    assert other.exists()                   # other PDK untouched
    assert any("gf180mcu" in p for p in res["removed"])


def test_repair_ciel_store_family_none_keeps_files(tmp_path) -> None:
    import os
    store = tmp_path / "ciel"
    ver = store / "sky130" / "versions" / "v"
    ver.mkdir(parents=True)
    f = ver / "ro.lib"
    f.write_text("y", encoding="utf-8")
    os.chmod(ver, 0o555)

    res = installer.repair_ciel_store(None, pdk_root=str(tmp_path))

    assert res["ok"] is True
    assert res["removed"] == []             # deletes nothing
    assert f.exists()                       # file preserved
    assert os.access(ver, os.W_OK)          # write restored


def test_repair_ciel_store_missing_is_ok(tmp_path) -> None:
    res = installer.repair_ciel_store("sky130", pdk_root=str(tmp_path / "nope"))
    assert res["ok"] is True
    assert res["removed"] == []


# --------------------------------------------------------------------------- #
# WSL browser auto-open — webbrowser.open() returns True while the gio shim
# no-ops ("Operation not supported"), so on WSL we hand the URL to Windows first.
# --------------------------------------------------------------------------- #
def test_open_via_windows_launches_first_available(monkeypatch) -> None:
    from lanex import cli
    import shutil as _sh
    import subprocess as _sp

    launched = {}
    monkeypatch.setattr(_sh, "which", lambda n: "/usr/bin/wslview" if n == "wslview" else None)
    monkeypatch.setattr(_sp, "Popen", lambda argv, **k: launched.setdefault("argv", argv))

    assert cli._open_via_windows("http://127.0.0.1:8765/landing") is True
    assert launched["argv"][0] == "wslview"


def test_open_via_windows_false_when_nothing_present(monkeypatch) -> None:
    from lanex import cli
    import shutil as _sh
    monkeypatch.setattr(_sh, "which", lambda n: None)
    assert cli._open_via_windows("http://x") is False


def test_lazy_open_on_wsl_skips_webbrowser(monkeypatch) -> None:
    from lanex import cli

    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.setattr(cli, "_open_via_windows", lambda url: True)
    import webbrowser
    called = {"web": False}
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: called.__setitem__("web", True) or True)

    cli._lazy_open("http://127.0.0.1:8765/", no_browser=False)
    assert called["web"] is False   # Windows opener handled it; no Linux browser attempt
