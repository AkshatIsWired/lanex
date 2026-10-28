# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""``/api/presence``: the open-window count and busy list the Windows launcher
uses to quit LanEx when its last window closes."""
from __future__ import annotations

import contextlib
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest


def _pick_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    from lanex.server.app import make_server

    httpd, port = make_server(host="127.0.0.1", port=_pick_port())
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.05)
    yield port
    httpd.shutdown()
    httpd.server_close()


def _presence(port: int) -> dict:
    body = json.loads(urllib.request.urlopen(
        f"http://127.0.0.1:{port}/api/presence", timeout=2).read())
    assert body["ok"] is True
    return body["data"]


def _open_stream(port: int) -> socket.socket:
    """A raw EventSource stand-in: send the request, read past the hello."""
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    s.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\n"
              b"Accept: text/event-stream\r\n\r\n")
    buf = b""
    while b"event: hello" not in buf:
        chunk = s.recv(4096)
        assert chunk, "stream closed before hello"
        buf += chunk
    return s


def _wait_windows(port: int, want: int, timeout: float = 3.0) -> int:
    deadline = time.time() + timeout
    n = -1
    while time.time() < deadline:
        n = _presence(port)["windows"]
        if n == want:
            return n
        time.sleep(0.05)
    return n


def test_window_count_follows_open_and_closed_streams(server):
    base = _presence(server)["windows"]
    a = _open_stream(server)
    b = _open_stream(server)
    assert _wait_windows(server, base + 2) == base + 2
    # A closed window must drop out within a poll tick, not after the 15 s
    # heartbeat: the launcher's quit decision waits on this number.
    t0 = time.time()
    a.close()
    assert _wait_windows(server, base + 1) == base + 1
    assert time.time() - t0 < 2.0
    b.close()
    assert _wait_windows(server, base) == base


def test_idle_server_reports_nothing_busy(server):
    assert _presence(server)["busy"] == []


def test_busy_lists_live_viewers_and_forgets_exited_ones():
    from lanex.controller import activity

    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait()
    try:
        activity.track_viewer(live, "KLayout")
        activity.track_viewer(done, "GTKWave")
        assert "KLayout" in activity.busy()
        assert "GTKWave" not in activity.busy()
        live.kill()
        live.wait()
        assert "KLayout" not in activity.busy()
    finally:
        if live.poll() is None:
            live.kill()


def test_busy_lists_an_install_in_progress():
    from lanex.controller import activity, installer

    assert installer._begin_job("presence-test")
    try:
        assert "a download or install" in activity.busy()
    finally:
        installer._end_job("presence-test")
    assert "a download or install" not in activity.busy()


def test_page_requests_reset_idle_but_launcher_probes_do_not(server):
    # A cheap page request: idle time counts from when it arrived, so a slow
    # endpoint (/api/about reads versions, ~2 s cold) would fail this on its own.
    urllib.request.urlopen(f"http://127.0.0.1:{server}/", timeout=2).read()
    assert _presence(server)["idleSeconds"] < 1.0
    time.sleep(1.2)
    # The launcher polls presence and health; those must not look like a page.
    urllib.request.urlopen(f"http://127.0.0.1:{server}/api/health", timeout=2).read()
    assert _presence(server)["idleSeconds"] >= 1.0


def _bye(port: int, page_id: str) -> None:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/bye", method="POST",
        data=json.dumps({"id": page_id}).encode(),
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"})
    urllib.request.urlopen(req, timeout=2).read()


def test_heartbeat_counts_a_window_without_a_stream(server):
    # A laptop that slept drops the event stream, but the window is still
    # open: its heartbeat keeps it counted, so the launcher does not quit.
    base = _presence(server)["windows"]
    urllib.request.urlopen(f"http://127.0.0.1:{server}/api/hello?id=sleepy", timeout=2).read()
    assert _presence(server)["windows"] >= max(base, 1)
    _bye(server, "sleepy")
    p = _presence(server)
    assert p["windows"] == base
    assert p["byeSeconds"] is not None and p["byeSeconds"] < 2


def test_stale_heartbeat_stops_counting(monkeypatch):
    from lanex.controller import activity
    activity.note_hello("old-page")
    assert activity.live_pages() >= 1
    monkeypatch.setattr(activity, "PAGE_ALIVE_FOR", -1.0)
    assert activity.live_pages() == 0


def test_one_bad_viewer_entry_does_not_hide_the_others():
    from lanex.controller import activity

    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        activity.track_viewer(None, "Broken")   # e.g. a test's fake Popen
        activity.track_viewer(live, "KLayout")
        assert activity.open_viewers() == ["KLayout"]
    finally:
        live.kill()
        live.wait()
