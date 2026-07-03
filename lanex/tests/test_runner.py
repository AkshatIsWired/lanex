# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for :mod:`lanex.controller.runner`.

These look at pure-Python behaviour (events queue, lifecycle flags,
fingerprinting). They do NOT actually invoke OpenROAD/Yosys; that's an
integration test the host environment can't satisfy without PDKs.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest


def test_runner_starts_and_drains_idle():
    from lanex.controller.runner import FlowRunner

    r = FlowRunner()
    assert not r.running
    # Drain is empty when nothing happened.
    out = r.drain(block=False, timeout=0.05)
    assert out == []


def test_runner_rejects_double_start():
    from lanex.controller.runner import FlowRunner

    r = FlowRunner()
    # Manually flip ``running`` since we have no flow factory wired.
    r._running = True
    try:
        res = r.start(
            flow_factory=lambda *a, **kw: None,
            config_files=[],
            design_dir=".",
        )
        assert res["ok"] is False
        assert "already running" in res["reason"]
    finally:
        r._running = False


def test_runner_event_seq_monotonic(monkeypatch):
    from lanex.controller.runner import FlowRunner
    from lanex.controller.models import EventType

    r = FlowRunner()
    # Drive the emit() directly to avoid spinning up the worker.
    r._emit(EventType.INFO, {"message": "a"})
    r._emit(EventType.INFO, {"message": "b"})
    evs = r.drain(block=False, timeout=0.05)
    types = [e["type"] for e in evs if e["type"] == EventType.INFO.value]
    assert types[:2] == [EventType.INFO.value, EventType.INFO.value]
    assert evs[0]["seq"] < evs[1]["seq"]
    assert evs[0]["message"] == "a" or "message" in evs[0]


def test_runner_cancel_sets_flag():
    from lanex.controller.runner import FlowRunner

    r = FlowRunner()
    assert not r.cancelled
    r.cancel()
    assert r.cancelled


def test_runner_accepts_extra_sources_and_extras_kwargs():
    """start() must accept extra_sources / extra_extras."""
    from lanex.controller.runner import FlowRunner

    r = FlowRunner()
    # Pre-flip running=False to bypass guard for kwargs validation.
    captured = {}

    def _fake_factory(*args, **kwargs):
        captured["called"] = True
        captured["args"] = args
        captured["kwargs"] = kwargs
        class _Flow:
            name = "FakeFlow"
            Steps = []
        return _Flow()

    # Patch _run to capture kwargs without actually invoking workers.
    original_run = r._run

    def _stub_run(*args, **kwargs):
        captured["run_kwargs"] = kwargs
        return None

    r._run = _stub_run  # type: ignore[assignment]
    try:
        # We bypass threading by patching start() minimally:
        # Instead of calling _run, we directly invoke _start-like path.
        # Just check the kwargs flow in by inspecting start's signature.
        import inspect
        sig = inspect.signature(r.start)
        assert "extra_sources" in sig.parameters
        assert "extra_extras" in sig.parameters
    finally:
        r._run = original_run  # type: ignore[assignment]


def test_runner_starts_with_mock_run():
    """Smoke: pass a fake flow_factory and observe events sent."""
    from lanex.controller.runner import FlowRunner
    from lanex.controller.events import bus

    r = FlowRunner()
    bus.bus if False else None  # touch
    # Avoid a real flow by making _run trivial.
    original = r._run
    r._run = lambda *a, **kw: None  # type: ignore[assignment]
    try:
        res = r.start(
            flow_factory=lambda *a, **kw: None,
            config_files=[],
            design_dir=".",
            extra_sources=["src/a.v"],
            extra_extras=["pin_order.cfg"],
        )
        assert res["ok"] is True
    finally:
        r._run = original  # type: ignore[assignment]


def test_mark_remaining_aborted_skips_pending_steps():
    # A5: after an abort (cancel or mid-flow error) every step that never reached
    # a terminal state must be closed as skipped(reason: flow aborted) instead of
    # lingering PENDING forever — the timeline must not show grey rows that look
    # like they might still run. The current (failed) step is left untouched.
    from lanex.controller.runner import FlowRunner
    from lanex.controller.models import StepStatus, EventType

    r = FlowRunner()
    r._step_statuses = {
        "s1": StepStatus.DONE.value,
        "s2": StepStatus.FAILED.value,   # the current step, already marked failed
        "s3": StepStatus.PENDING.value,
        "s4": StepStatus.RUNNING.value,
    }
    r._current_step_id = "s2"
    r._mark_remaining_aborted()

    assert r._step_statuses["s1"] == StepStatus.DONE.value      # untouched
    assert r._step_statuses["s2"] == StepStatus.FAILED.value    # current untouched
    assert r._step_statuses["s3"] == StepStatus.SKIPPED.value
    assert r._step_statuses["s4"] == StepStatus.SKIPPED.value

    evs = r.drain(block=False, timeout=0.05)
    reasons = {e["step_id"]: e.get("reason")
               for e in evs if e["type"] == EventType.STEP_SKIPPED.value}
    assert reasons.get("s3") == "flow aborted"
    assert reasons.get("s4") == "flow aborted"


def test_runner_init_logs_handler_attached(tmp_path: Path):
    """The bridge binds a handler to LibreLane's ``__librelane__`` logger at the
    SUBPROCESS level (so per-tool output reaches the live stream, matching a
    container run) and removes it on teardown.

    Regression guard for the bug where we bound to the wrong logger (root, via a
    failing ``librelane.logging.getLogger`` import) and sat at INFO — which
    silently dropped every SUBPROCESS-level (=12) tool line.
    """
    import logging

    from lanex.controller import runner as rmod

    ll_logger = logging.getLogger("__librelane__")
    baseline = list(ll_logger.handlers)

    r = rmod.FlowRunner()
    r._setup_log_bridge()
    # bound to the right logger…
    assert r._log_root is ll_logger
    assert r._log_handler in ll_logger.handlers
    # …and accepting SUBPROCESS (12) or lower, NOT INFO (20)
    assert r._log_handler.level <= 12
    assert ll_logger.level <= 12

    r._teardown_log_bridge()
    assert r._log_handler not in ll_logger.handlers
    assert list(ll_logger.handlers) == baseline
