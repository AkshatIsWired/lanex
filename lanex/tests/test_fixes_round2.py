# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Regression tests for the round-1/round-2 audit fixes.

All pure (no EDA tools / PDK / Docker needed) so they run anywhere CI does.
"""
from __future__ import annotations

from pathlib import Path


# --- C1/M5: process-global monotonic seq + non-destructive cursor read -------

def test_event_seq_is_global_monotonic_and_nondestructive():
    from lanex.controller import events

    s1 = events.next_seq()
    s2 = events.next_seq()
    assert s2 == s1 + 1  # never resets, always increases

    b = events.EventBus()
    b.emit("step_started", {})
    b.emit("flow_done", {})
    cur = b.max_seq
    # A "second run" emits more events; a client whose cursor is at the first
    # run's end still receives them (the bug was these being dropped).
    b.emit("step_started", {})
    b.emit("flow_done", {})
    got = b.events_since(cur)
    assert len(got) == 2
    # Non-destructive: reading again returns the same events.
    assert len(b.events_since(cur)) == 2


# --- C2/C3: lint command is verilator --lint-only, no PDK/flow ---------------

def test_build_lint_command_local_and_container():
    from lanex.controller import lint

    argv = lint.build_lint_command("/d", sources=["src/a.v"], top="a", run_mode="local")
    assert argv[0] == "verilator" and "--lint-only" in argv
    assert "src/a.v" in argv and "--top-module" in argv

    cargv = lint.build_lint_command("/d", sources=["src/a.v"], run_mode="container",
                                    engine="podman", image="img:1")
    assert cargv[0] == "podman" and "run" in cargv and "img:1" in cargv
    # the inner shell still invokes verilator --lint-only
    assert any("verilator --lint-only" in a for a in cargv)


# --- C4: testbench top auto-derive + stale-VCD mtime gate --------------------

def test_top_module_of(tmp_path: Path):
    from lanex.controller import simulate

    tb = tmp_path / "verify" / "foo_tb.v"
    tb.parent.mkdir(parents=True)
    tb.write_text("module foo(input a); endmodule\nmodule foo_tb;\ninitial $finish;\nendmodule\n")
    # Picks the port-less bench module, not the DUT.
    assert simulate.top_module_of(tmp_path, "verify/foo_tb.v") == "foo_tb"


def test_find_waveform_ignores_stale(tmp_path: Path):
    import time
    from lanex.controller.simulate import SimJob

    old = tmp_path / "dump.vcd"
    old.write_text("$old")
    started = time.time() + 5  # the "run" started after the file was written
    # Stale file (mtime < started) must NOT be returned as this run's output.
    assert SimJob._find_waveform(tmp_path, "dump.vcd", started) is None


# --- C5 + M8: runner exposes a real error signal -----------------------------

def test_runner_error_property():
    from lanex.controller.runner import FlowRunner

    r = FlowRunner()
    assert r.error is None
    r._error = "boom"
    assert r.error == "boom"


# --- C6: hard tools are flagged container-only -------------------------------

def test_hard_tools_marked_container_only():
    from lanex.controller import tools

    by_key = {t["key"]: t for t in tools.EDA_TOOLS}
    for k in ("openroad", "magic", "netgen"):
        assert by_key[k].get("container_only") is True
    # And verilator/yosys are NOT (they have real host packages).
    assert not by_key["yosys"].get("container_only")


# --- C6: no phantom yowasp-openroad ------------------------------------------

def test_no_yowasp_openroad():
    import inspect
    from lanex.controller import installer

    src = inspect.getsource(installer)
    # The only mentions of yowasp-openroad should be in explanatory comments,
    # never in an executable command list.
    for line in src.splitlines():
        stripped = line.strip()
        if "yowasp-openroad" in stripped and not stripped.startswith("#"):
            raise AssertionError(f"executable reference to yowasp-openroad: {line}")


# --- C7: sudo gate helpers ---------------------------------------------------

def test_needs_sudo_detection():
    from lanex.controller import installer

    assert installer._needs_sudo(["sudo", "apt-get", "install", "-y", "yosys"]) is True
    assert installer._needs_sudo(["sh", "-c", "sudo apt-get install x"]) is True
    assert installer._needs_sudo(["verilator", "--version"]) is False


# --- M1: success detection uses the real KLayout DRC metric key --------------

def test_fail_metrics_use_real_drc_key():
    from lanex.controller import history

    assert "route__drc_errors" in history._FAIL_METRICS
    assert "klayout__drc_error__count" not in history._FAIL_METRICS


# --- M7: re-verify continues the prior run's state ---------------------------

def test_reverify_kwargs_continues_run():
    from lanex.controller import reverify

    kw = reverify.reverify_kwargs("/x/runs/TAG", "Magic.DRC")
    assert kw["last_run"] is True and kw["frm"] == "Magic.DRC"


# --- L8: VHDL is editable ----------------------------------------------------

def test_vhdl_editable():
    from lanex.controller import editor

    assert ".vhd" in editor.EDITABLE_EXTS and ".vhdl" in editor.EDITABLE_EXTS
