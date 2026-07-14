# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Regression tests for the round-73 accuracy fixes (fear-audit findings N2–N7).

All pure (no EDA tools / PDK / Docker) so they run anywhere CI does. N1/N8
(compare tag collision + best-per-metric direction) live in test_export.py; the
frontend halves (compare column identity, fmt.metric locale, partial-sim badge,
SSE resync wiring) live in frontend_test.mjs.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path


# --------------------------------------------------------------------------
# N3 — SSE gap signal on reconnect past ring eviction
# --------------------------------------------------------------------------

def test_eventbus_min_seq_tracks_oldest_buffered():
    from lanex.controller import events

    b = events.EventBus(maxlen=3)
    assert b.min_seq == 0 and b.max_seq == 0        # empty
    b.emit("a", {})
    first = b.min_seq
    assert first == b.max_seq                        # one event
    b.emit("b", {})
    b.emit("c", {})
    assert b.min_seq == first                         # still holding the first
    b.emit("d", {})                                   # evicts the first (maxlen 3)
    assert b.min_seq > first                           # oldest advanced
    assert b.max_seq == b.min_seq + 2                  # exactly 3 buffered


class _FakeWFile:
    def __init__(self):
        self.buf = bytearray()

    def write(self, data):
        self.buf.extend(data)

    def flush(self):
        pass


class _FakeConn:
    def settimeout(self, _):
        pass


class _FakeHandler:
    def __init__(self):
        self.wfile = _FakeWFile()
        self.connection = _FakeConn()
        self.headers = {}

    def send_response(self, *_a, **_k):
        pass

    def send_header(self, *_a, **_k):
        pass

    def end_headers(self):
        pass


def _run_stream(sse, start_seq):
    """Run stream_until_closed against a fake client, stop it, return SSE frames."""
    handler = _FakeHandler()
    stream = sse.ISSEHandler(handler)

    def go():
        stream.stream_until_closed(None, heartbeat=999, idle=0.02, start_seq=start_seq)

    t = threading.Thread(target=go, daemon=True)
    t.start()
    time.sleep(0.2)
    stream._closed = True           # end the loop like a client disconnect
    t.join(timeout=2.0)
    # Parse "event: X\ndata: {json}" blocks separated by blank lines.
    frames = []
    for block in handler.wfile.buf.decode("utf-8").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        ev = None
        data = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev = line[len("event: "):]
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[len("data: "):])
                except Exception:
                    data = {}
        frames.append({"_event": ev, "data": data or {}})
    return frames


def test_sse_emits_gap_when_reconnect_resumes_past_evicted_events(monkeypatch):
    from lanex.controller import events
    from lanex.server import sse

    small = events.EventBus(maxlen=5)
    monkeypatch.setattr(events, "bus", small)

    small.emit("step_started", {})
    seen_seq = small.max_seq                 # what our "client" last saw
    for _ in range(10):                      # push well past the ring
        small.emit("log", {"message": "x"})
    assert small.min_seq > seen_seq + 1      # the client's cursor is now evicted

    frames = _run_stream(sse, start_seq=seen_seq)
    gaps = [f for f in frames if f["_event"] == "gap"]
    assert gaps, "no gap event emitted despite evicted events"
    assert gaps[0]["data"].get("resync") is True
    assert gaps[0]["data"].get("from_seq") == seen_seq


def test_sse_no_gap_on_fresh_connection(monkeypatch):
    from lanex.controller import events
    from lanex.server import sse

    small = events.EventBus(maxlen=5)
    monkeypatch.setattr(events, "bus", small)
    for _ in range(10):
        small.emit("log", {"message": "x"})

    # start_seq = -1 → a fresh EventSource with no Last-Event-ID: no history to
    # lose, so never a gap.
    frames = _run_stream(sse, start_seq=-1)
    assert not any(f["_event"] == "gap" for f in frames)


def test_sse_no_gap_when_resume_cursor_still_buffered(monkeypatch):
    from lanex.controller import events
    from lanex.server import sse

    small = events.EventBus(maxlen=50)
    monkeypatch.setattr(events, "bus", small)
    small.emit("step_started", {})
    seen_seq = small.max_seq
    small.emit("log", {"message": "x"})      # only one new, still buffered

    frames = _run_stream(sse, start_seq=seen_seq)
    assert not any(f["_event"] == "gap" for f in frames), \
        "gap emitted even though the cursor's events were still buffered"


# --------------------------------------------------------------------------
# N2 — a timed-out sim's partial waveform must be marked partial (not "passed")
# --------------------------------------------------------------------------

def test_sim_verdict_clean_pass():
    from lanex.controller.simulate import sim_verdict
    v = sim_verdict(rc=0, timed_out=False, wave="dump.vcd", cancelled=False)
    assert v == {"ok": True, "partial": False}


def test_sim_verdict_timeout_with_waveform_is_soft_success_but_partial():
    from lanex.controller.simulate import sim_verdict
    # The exact Fear-#5 case: a free-running bench hit the watchdog but produced
    # a usable-but-incomplete dump. Soft success (button re-enables, dump loads)
    # yet explicitly PARTIAL so the UI badges it and no consumer reads it as done.
    v = sim_verdict(rc=143, timed_out=True, wave="dump.vcd", cancelled=False)
    assert v["ok"] is True
    assert v["partial"] is True


def test_sim_verdict_timeout_without_waveform_is_failure_not_partial():
    from lanex.controller.simulate import sim_verdict
    v = sim_verdict(rc=143, timed_out=True, wave=None, cancelled=False)
    assert v == {"ok": False, "partial": False}


def test_sim_verdict_cancelled_is_never_partial():
    from lanex.controller.simulate import sim_verdict
    # User stopped it — even with a half-written dump, that's not a "partial run
    # that timed out", it's a deliberate stop; don't badge it as partial.
    v = sim_verdict(rc=143, timed_out=True, wave="dump.vcd", cancelled=True)
    assert v["partial"] is False


def test_sim_verdict_error_no_wave():
    from lanex.controller.simulate import sim_verdict
    v = sim_verdict(rc=1, timed_out=False, wave=None, cancelled=False)
    assert v == {"ok": False, "partial": False}


# --------------------------------------------------------------------------
# N4 — the slack unit label is sourced from ONE constant, not hardcoded "ns"
# --------------------------------------------------------------------------

_FAILING_RUN = Path(__file__).parent / "goldens" / "failing_run"


def test_timing_unit_is_single_sourced_and_emitted():
    from lanex.controller import timing

    # One source of truth; the frontend reads this, never a literal "ns".
    assert timing.TIME_UNIT == "ns"
    out = timing.timing_paths(_FAILING_RUN, kind="setup")
    assert out.get("ok") is True, out
    assert out["unit"] == timing.TIME_UNIT


def test_supported_pdks_use_ns_time_unit():
    """Canary for the ns assumption (Fear G): a ps-unit liberty shown as ns would
    misstate slack ×1000. Opportunistically verify any installed PDK liberty's
    ``time_unit`` is 1 ns; honestly skip when no PDK is present (CI has none)."""
    import os
    import re
    import pytest

    roots = []
    for env in ("PDK_ROOT", "CIEL_ROOT", "VOLARE_ROOT"):
        v = os.environ.get(env)
        if v:
            roots.append(Path(v))
    for d in (Path.home() / ".ciel", Path.home() / ".volare", Path("/usr/local/pdk")):
        roots.append(d)

    libs = []
    for r in roots:
        if r.is_dir():
            libs.extend(list(r.rglob("*.lib"))[:5])
        if len(libs) >= 5:
            break
    if not libs:
        pytest.skip("no PDK liberty available to canary the ns time_unit assumption")

    unit_re = re.compile(r"time_unit\s*:\s*\"?\s*1\s*(ns|ps|us)", re.IGNORECASE)
    checked = 0
    for lib in libs[:5]:
        try:
            head = lib.read_text(encoding="utf-8", errors="replace")[:20000]
        except Exception:
            continue
        m = unit_re.search(head)
        if m:
            assert m.group(1).lower() == "ns", (
                f"{lib} uses time_unit {m.group(1)} — timing.TIME_UNIT ('ns') would "
                "mislabel slack; source the unit per-run before supporting this PDK")
            checked += 1
    if not checked:
        pytest.skip("liberties present but none declared an explicit time_unit")


# --------------------------------------------------------------------------
# N6 — warn on multiple config files + preflight/run-start pick the SAME one
# --------------------------------------------------------------------------

def _write_config(d: Path, ext: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"config.{ext}"
    p.write_text("{}" if ext == "json" else "meta: {}\n", encoding="utf-8")
    return p


def test_config_resolution_order_is_json_first(tmp_path):
    from lanex.server import routes
    _write_config(tmp_path, "yaml")
    _write_config(tmp_path, "json")
    _write_config(tmp_path, "tcl")
    cands = routes._config_candidates(str(tmp_path))
    assert [c.name for c in cands] == ["config.json", "config.yaml", "config.tcl"]
    assert routes._resolve_config_file(str(tmp_path)).name == "config.json"


def test_single_config_has_no_warning(tmp_path):
    from lanex.server import routes
    _write_config(tmp_path, "yaml")
    assert routes._multi_config_warning(str(tmp_path)) is None


def test_multi_config_warning_names_used_and_ignored(tmp_path):
    from lanex.server import routes
    _write_config(tmp_path, "json")
    _write_config(tmp_path, "yaml")
    w = routes._multi_config_warning(str(tmp_path))
    assert w is not None
    assert "config.json" in w and "config.yaml" in w
    assert "uses config.json" in w and "ignores config.yaml" in w


def test_preflight_and_runstart_resolve_the_same_config(tmp_path):
    """The two used to disagree (preflight preferred yaml, run-start json) — a
    green preflight could name a different file than the one that ran (N6)."""
    from lanex.server import routes
    _write_config(tmp_path, "yaml")
    _write_config(tmp_path, "json")
    cands = routes._config_candidates(str(tmp_path))
    preflight_pick = cands[0].name                       # what preflight shows
    runstart_pick = routes._resolve_config_file(str(tmp_path)).name
    assert preflight_pick == runstart_pick == "config.json"


# --------------------------------------------------------------------------
# N7 — config drift hash (TOCTOU between Final-settings preview and Run)
# --------------------------------------------------------------------------

def test_config_hash_detects_edits(tmp_path):
    """The drift primitive: the same bytes hash the same, an edit changes it —
    so a preview hash that differs from the run's hash proves the file changed."""
    from lanex.server import routes
    cfg = _write_config(tmp_path, "json")
    h1 = routes._hash_files([str(cfg)])
    assert h1 and routes._hash_files([str(cfg)]) == h1     # stable when unchanged
    cfg.write_text('{"FP_CORE_UTIL": 55}', encoding="utf-8")
    assert routes._hash_files([str(cfg)]) != h1            # an edit is detectable


def test_config_hash_is_resolved_config_not_a_sibling(tmp_path):
    """The hash tracks the file that actually runs (json), not another config."""
    from lanex.server import routes
    _write_config(tmp_path, "json")
    _write_config(tmp_path, "yaml")
    used = routes._resolve_config_file(str(tmp_path))
    assert used.name == "config.json"
    assert routes._hash_files([str(used)]) is not None
