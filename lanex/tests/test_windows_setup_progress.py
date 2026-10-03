# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""Regressions for the Windows Setup field reports of October 2026.

* "stuck at 80%": the long finalize phase now reports steps and measured
  download progress, and a dead connection is detected and retried.
* "Cancel leaves Setup frozen": the wizard's wait loop has a bounded exit and
  Cancel is only intercepted while a step is really running.
* "[WARN: COPY MODE] is back": every process the appliance starts gets an
  X11-only display environment, and the GUI runtime is installed up front.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from lanex.controller import container_tools, installer, platform_env, provisioning

REPO = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ COPY MODE --

def test_wsl_gui_env_drops_wayland_display_on_wsl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.delenv("LANEX_WAYLAND", raising=False)
    monkeypatch.delenv("LANEX_HW_GL", raising=False)
    monkeypatch.delenv("LIBRELANE_GUI_WSL_HW_GL", raising=False)
    env = platform_env.wsl_gui_env({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"})
    assert "WAYLAND_DISPLAY" not in env
    assert env["GDK_BACKEND"].startswith("x11")
    assert env["QT_QPA_PLATFORM"].startswith("xcb")


def test_wsl_gui_env_keeps_wayland_when_user_opts_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.setenv("LANEX_WAYLAND", "1")
    env = platform_env.wsl_gui_env({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"})
    assert env["WAYLAND_DISPLAY"] == "wayland-0"


def test_wsl_gui_env_without_x11_does_not_strip_the_only_display(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.delenv("LANEX_WAYLAND", raising=False)
    env = platform_env.wsl_gui_env({"WAYLAND_DISPLAY": "wayland-0"})
    assert env["WAYLAND_DISPLAY"] == "wayland-0"


def test_container_viewers_are_told_to_use_x11() -> None:
    flags = container_tools._x11_flags()
    assert "QT_QPA_PLATFORM=xcb" in flags
    assert "GDK_BACKEND=x11" in flags


def test_appliance_installs_gui_runtime_and_x11_profile_before_first_launch() -> None:
    provision = (REPO / "windows/provision/provision.sh").read_text(encoding="utf-8")
    stage = provision[provision.index("gui_runtime() {"):provision.index("# ---------------------------------------------------------------- 5. docker --")]
    for package in ("libgl1-mesa-dri", "libegl1", "xfonts-base", "libxcb-cursor0"):
        assert package in stage
    assert "/etc/profile.d/lanex-wslg.sh" in stage and "unset WAYLAND_DISPLAY" in stage
    main = provision[provision.index("main() {"):]
    steps = [line.strip() for line in main.splitlines()]
    assert steps.index("base_packages") < steps.index("gui_runtime") < steps.index("app_user")


# -------------------------------------------------------- progress and stalls --

def test_run_argv_kills_a_stalled_download_and_reports_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer, "_net_rx_bytes", lambda: 1000)  # no traffic at all
    argv = [sys.executable, "-c", "import time; time.sleep(60)"]
    started = time.time()
    result = installer._run_argv(argv, label="silent download", key="test:stall",
                                 expect_bytes=10 << 20, stall_s=1.0)
    assert time.time() - started < 30
    assert result["ok"] is False and result.get("stalled") is True


def test_run_argv_reports_download_progress_events(monkeypatch: pytest.MonkeyPatch) -> None:
    rx = iter(range(0, 10 << 30, 50 << 20))
    monkeypatch.setattr(installer, "_net_rx_bytes", lambda: next(rx))
    seen = []
    monkeypatch.setattr(installer, "_emit", lambda kind, payload: seen.append((kind, payload)))
    argv = [sys.executable, "-c", "import time; time.sleep(7)"]
    result = installer._run_argv(argv, label="download", key="test:progress",
                                 expect_bytes=1 << 30, stall_s=600.0)
    assert result["ok"] is True
    progress = [p for kind, p in seen if kind == "installer_progress"]
    assert progress and 0 < progress[-1]["percent"] <= 99
    assert "downloaded" in progress[-1]["message"]


def test_finalize_announces_weighted_steps_for_setup(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    from lanex.tests.test_windows_provisioning import _manifest, _write  # type: ignore

    plan = provisioning.load_plan(
        _write(tmp_path, _manifest()),
        choices={"profile": "custom", "engine": "none", "image": False,
                 "pdks": [], "libraries": {}, "nativeTools": ["iverilog", "graphviz"]},
    )
    initial = {"schema": 1, "ready": False,
               "checks": {"native:iverilog": {"ready": True},
                          "native:graphviz": {"ready": False}}}
    monkeypatch.setattr(provisioning, "readiness_report", lambda *a, **k: initial)
    monkeypatch.setattr(installer, "install_tool", lambda key: {"ok": True})
    monkeypatch.delenv("LANEX_SETUP_CANCEL_FILE", raising=False)
    provisioning.finalize(plan)
    events = [json.loads(line[len("@@LANEX:"):]) for line in capsys.readouterr().out.splitlines()
              if line.startswith("@@LANEX:")]
    plan_events = [e for e in events if e["event"] == "plan"]
    steps = [e for e in events if e["event"] == "step"]
    assert plan_events and plan_events[0]["total"] == 2
    assert [s["component"] for s in steps[:2]] == ["native:iverilog", "native:graphviz"]
    starts = [s["start"] for s in steps]
    assert starts == sorted(starts) and steps[-1]["start"] == 100


# ------------------------------------------------------------- wizard contract --

def _iss() -> str:
    return (REPO / "windows/installer/lanex.iss").read_text(encoding="utf-8")


def test_wizard_streams_through_chunk_runner_not_a_growing_log() -> None:
    iss = _iss()
    run = iss[iss.index("function RunLogged("):iss.index("function ExecAndLogOutput(")]
    assert "run-streamed.ps1" in run and "chunk-" in run
    # The old loop re-read the whole output file on every 50 ms poll.
    assert "lanex_exec.log" not in iss
    # Bounded exit after Cancel, and a dead runner is noticed.
    assert "kill.request" in run and "CancelAge > 60000" in run and "alive.txt" in run
    assert "'--terminate ' + DistroNameValue" in run
    assert 'Source: "..\\setup\\run-streamed.ps1"; Flags: dontcopy' in iss


def test_cancel_is_only_intercepted_while_a_step_runs() -> None:
    iss = _iss()
    handler = iss[iss.index("procedure CancelButtonClick("):iss.index("// ------------------------------------------------------------------ uninstall --")]
    assert "if not WorkerRunning then Exit;" in handler
    assert "ForceStopRequested := True" in handler


def test_finalize_phase_owns_half_the_bar() -> None:
    iss = _iss()
    assert "FinalizeBase = 48" in iss and "FinalizeSpan = 51" in iss
    assert "HandleSetupEvent" in iss and "'progress'" in iss


def test_firmware_disabled_reopens_setup_after_sign_in() -> None:
    iss = _iss()
    block = iss[iss.index("if PreflightDecision = 'firmware-disabled' then\n  begin\n    Result := False;"):]
    block = block[:block.index("ClearFirmwareResume;")]
    assert "ScheduleFirmwareResume" in block and "RestartIntoFirmware" in block
    assert "/r /fw" in iss and "LanExSetupAfterFirmware" in iss


def test_runner_script_contract() -> None:
    runner = (REPO / "windows/setup/run-streamed.ps1").read_text(encoding="utf-8")
    for token in ("command.txt", "chunk-{0:D6}.txt", "alive.txt", "kill.request", "exit.code",
                  "taskkill.exe", "/T /F"):
        assert token in runner
