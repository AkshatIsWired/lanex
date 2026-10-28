# Copyright 2026 LanEx Contributors
"""HTTP/1.1 keep-alive, gzip and validators (perf pass 2026-10-28).

Every kind of answer (JSON, static, a streamed run file, 404, a refused POST,
the event stream, 304) must leave a kept-alive connection usable, or close it
and say so, and a compressed or revalidated answer must decode to the very
bytes the plain one carries.
"""
from __future__ import annotations

import contextlib
import gzip
import json
import os
import socket
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from lanex.server import app as app_mod
from lanex.server import routes


def _port() -> int:
    with contextlib.closing(socket.socket()) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server():
    httpd, port = app_mod.make_server(host="127.0.0.1", port=_port())
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            c = HTTPConnection("127.0.0.1", port, timeout=2)
            c.request("GET", "/api/health")
            c.getresponse().read()
            c.close()
            break
        except Exception:
            time.sleep(0.05)
    yield port
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def design(tmp_path, monkeypatch):
    run = tmp_path / "runs" / "r1"
    (run / "final" / "gds").mkdir(parents=True)
    big = os.urandom(3 * 1024 * 1024 + 17)
    (run / "final" / "gds" / "top.gds").write_bytes(big)
    log = ("[INFO] step line with some text\n" * 4000).encode()
    (run / "flow.log").write_bytes(log)
    (run / "state_out.json").write_text(json.dumps({"gds": "final/gds/top.gds"}))
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(tmp_path))
    return {"dir": tmp_path, "gds": big, "log": log}


def _get(c: HTTPConnection, path: str, headers=None, method="GET", body=None):
    c.request(method, path, body=body, headers=headers or {})
    r = c.getresponse()
    data = r.read()
    return r, data


def test_one_connection_serves_every_kind_of_answer(server, design):
    c = HTTPConnection("127.0.0.1", server, timeout=10)
    socks = set()

    def note():
        socks.add(id(c.sock))

    r, d = _get(c, "/api/health")
    assert r.status == 200 and json.loads(d)["ok"] and r.getheader("Content-Length") == str(len(d))
    note()
    r, d = _get(c, "/static/app.js")
    assert r.status == 200 and b"import" in d
    note()
    r, d = _get(c, "/static/no-such-file.js")
    assert r.status == 404
    note()
    r, d = _get(c, "/api/run-file?tag=r1&path=final/gds/top.gds")
    assert r.status == 200 and d == design["gds"]
    note()
    r, d = _get(c, "/api/views/r1/gds")
    assert r.status == 200 and d == design["gds"]
    note()
    r, d = _get(c, "/static/app.js", method="HEAD")
    assert r.status == 200 and d == b""
    note()
    etag = None
    r, d = _get(c, "/api/steps")
    etag = r.getheader("ETag")
    assert r.status == 200 and etag and r.getheader("Cache-Control") == "no-cache"
    r, d = _get(c, "/api/steps", {"If-None-Match": etag})
    assert r.status == 304 and d == b"" and r.getheader("Content-Length") is None
    note()
    # A refused POST with a body: its body is drained, the connection goes on.
    r, d = _get(c, "/api/set-design-dir", {"Content-Type": "application/json"},
                method="POST", body=json.dumps({"path": "/tmp"}))
    assert r.status == 403
    note()
    r, d = _get(c, "/api/health")
    assert r.status == 200
    note()
    assert len(socks) == 1, "the connection was not kept alive"
    c.close()


def test_oversized_post_closes_and_says_so(server):
    s = socket.create_connection(("127.0.0.1", server), timeout=10)
    s.sendall(b"POST /api/set-design-dir HTTP/1.1\r\nHost: 127.0.0.1\r\n"
              b"X-Requested-With: XMLHttpRequest\r\nContent-Type: application/json\r\n"
              b"Content-Length: 20000000\r\n\r\n{")
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    head = data.split(b"\r\n\r\n", 1)[0].decode()
    assert " 413 " in head.splitlines()[0]
    assert "Connection: close" in head


def test_event_stream_is_close_delimited(server):
    s = socket.create_connection(("127.0.0.1", server), timeout=10)
    s.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    buf = b""
    while b"event: hello" not in buf:
        buf += s.recv(4096)
    head = buf.split(b"\r\n\r\n", 1)[0].decode()
    assert "text/event-stream" in head and "Connection: close" in head
    assert "Content-Length" not in head
    s.close()


def _sse_frames(buf: bytes):
    out = []
    for block in buf.decode("utf-8", "replace").split("\n\n"):
        lines = [l for l in block.split("\n") if l]
        d = {}
        for l in lines:
            k, _, v = l.partition(": ")
            d[k] = v
        if "data" in d:
            out.append(d)
    return out


def _read_until(s: socket.socket, pred, timeout: float = 5.0) -> bytes:
    buf = b""
    deadline = time.time() + timeout
    s.settimeout(0.2)
    while time.time() < deadline:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            chunk = None
        if chunk == b"":
            break
        if chunk:
            buf += chunk
        if pred(buf):
            break
    return buf


def test_event_stream_sleeps_until_an_event_and_batches(server, monkeypatch):
    from lanex.controller import events
    from lanex.server import sse
    waits = []
    real = sse.ISSEHandler._events_since
    monkeypatch.setattr(sse.ISSEHandler, "_events_since",
                        staticmethod(lambda bus, cur, t: waits.append(t) or real(bus, cur, t)))
    sends = []
    real_send = sse.ISSEHandler._send
    monkeypatch.setattr(sse.ISSEHandler, "_send", lambda self, text: sends.append(text) or real_send(self, text))
    s = socket.create_connection(("127.0.0.1", server), timeout=10)
    s.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    _read_until(s, lambda b: b"event: hello" in b)
    time.sleep(1.2)
    # Idle: one wait for the heartbeat, not a wake-up every 0.4 s.
    assert len(waits) <= 2 and all(w > 5 for w in waits), waits
    t0 = time.time()
    events.publish("perf_probe", {"n": -1})
    buf = _read_until(s, lambda b: b'"perf_probe"' in b)
    assert b'"n": -1' in buf and time.time() - t0 < 1.0
    # A burst: every event, in order, each with its id, in few writes.
    sends.clear()
    for i in range(300):
        events.publish("perf_burst", {"n": i})
    buf = _read_until(s, lambda b: b'"n": 299' in b)
    got = [json.loads(f["data"]) for f in _sse_frames(buf) if '"perf_burst"' in f["data"]]
    assert [g["n"] for g in got] == list(range(300))
    assert all(f.get("id") for f in _sse_frames(buf) if '"perf_burst"' in f["data"])
    assert len(sends) < 60, len(sends)
    s.close()


def test_batch_event_goes_out_as_its_events(server):
    from lanex.controller import events
    s = socket.create_connection(("127.0.0.1", server), timeout=10)
    s.sendall(b"GET /api/events HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
    _read_until(s, lambda b: b"event: hello" in b)
    time.sleep(0.3)     # a fresh stream starts at the ring's end, just after hello
    events.publish("batch",{"events": [{"type": "log", "message": "a"}, {"type": "log", "message": "b"}]})
    buf = _read_until(s, lambda b: b'"message": "b"' in b)
    frames = [f for f in _sse_frames(buf) if '"log"' in f["data"]]
    assert [json.loads(f["data"])["message"] for f in frames] == ["a", "b"]
    assert "id" not in frames[0] and frames[1].get("id")
    s.close()


def test_gzip_decodes_to_the_same_bytes(server, design):
    c = HTTPConnection("127.0.0.1", server, timeout=10)
    for path in ("/static/app.js", "/api/steps", "/api/run-file?tag=r1&path=flow.log"):
        r, plain = _get(c, path)
        r2, packed = _get(c, path, {"Accept-Encoding": "gzip, deflate, br"})
        assert r2.getheader("Content-Encoding") == "gzip", path
        assert r2.getheader("Vary") == "Accept-Encoding"
        assert gzip.decompress(packed) == plain, path
        assert len(packed) < len(plain)
    # Small answers and binary files are sent as they are.
    r, d = _get(c, "/api/health", {"Accept-Encoding": "gzip"})
    assert r.getheader("Content-Encoding") is None
    r, d = _get(c, "/api/run-file?tag=r1&path=final/gds/top.gds", {"Accept-Encoding": "gzip"})
    assert r.getheader("Content-Encoding") is None and d == design["gds"]
    # gzip;q=0 means no.
    r, d = _get(c, "/static/app.js", {"Accept-Encoding": "gzip;q=0"})
    assert r.getheader("Content-Encoding") is None
    c.close()


def test_first_party_static_revalidates_and_follows_edits(server, tmp_path, monkeypatch):
    c = HTTPConnection("127.0.0.1", server, timeout=10)
    r, d = _get(c, "/static/app.js", {"Accept-Encoding": "gzip"})
    tag = r.getheader("ETag")
    assert r.getheader("Cache-Control") == "no-cache" and tag
    r, d = _get(c, "/static/app.js", {"Accept-Encoding": "gzip", "If-None-Match": tag})
    assert r.status == 304 and d == b""
    # An edited file (mtime moved) has a new validator and new bytes.
    root = tmp_path / "static"
    root.mkdir()
    (root / "m.js").write_text("export const a = 1;\n" * 200)
    monkeypatch.setattr(app_mod, "_STATIC_BASE", [root.resolve()])
    monkeypatch.setattr(app_mod, "_STATIC_TARGETS", {})
    r, d = _get(c, "/static/m.js")
    tag = r.getheader("ETag")
    r, d = _get(c, "/static/m.js", {"If-None-Match": tag})
    assert r.status == 304
    (root / "m.js").write_text("export const a = 2;\n" * 300)
    r, d = _get(c, "/static/m.js", {"If-None-Match": tag})
    assert r.status == 200 and r.getheader("ETag") != tag and d.startswith(b"export const a = 2;")
    monkeypatch.undo()
    # Vendor files keep their day-long cache.
    r, d = _get(c, "/static/vendor/echarts.min.js")
    assert "max-age=86400" in r.getheader("Cache-Control")
    c.close()


def test_json_etag_changes_with_the_answer(server, design):
    c = HTTPConnection("127.0.0.1", server, timeout=10)
    r, d = _get(c, "/api/runs")
    tag = r.getheader("ETag")
    r, d2 = _get(c, "/api/runs", {"If-None-Match": tag})
    assert r.status == 304
    (design["dir"] / "runs" / "r2" / "final").mkdir(parents=True)
    r, d3 = _get(c, "/api/runs", {"If-None-Match": tag})
    assert r.status == 200 and r.getheader("ETag") != tag and d3 != d
    # Errors and POST answers carry no validator.
    r, d = _get(c, "/api/runs/does-not-exist")
    assert r.getheader("ETag") is None and r.getheader("Cache-Control") == "no-store"
    c.close()


def test_launcher_probes_work(server):
    for path in ("/api/health", "/api/presence"):
        c = HTTPConnection("127.0.0.1", server, timeout=5)
        r, d = _get(c, path)
        assert r.status == 200 and json.loads(d)["ok"] is True
        c.close()


def test_http10_client_gets_a_closed_connection(server):
    s = socket.create_connection(("127.0.0.1", server), timeout=10)
    s.sendall(b"GET /api/health HTTP/1.0\r\n\r\n")
    data = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    head, body = data.split(b"\r\n\r\n", 1)
    assert b"200" in head.split(b"\r\n")[0] and json.loads(body)["ok"] is True


def test_a_handler_failing_mid_answer_closes(server, monkeypatch):
    def half(handler):
        handler.send_response(200)
        handler.send_header("Content-Length", "100")
        handler.end_headers()
        handler.wfile.write(b"partial")
        raise RuntimeError("boom")

    def silent(handler):
        return None

    monkeypatch.setattr(app_mod, "ROUTES", [("/api/test-half", half), ("/api/test-silent", silent)]
                        + list(app_mod.ROUTES))
    for path in ("/api/test-half", "/api/test-silent"):
        s = socket.create_connection(("127.0.0.1", server), timeout=10)
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
        data = b""
        while True:          # the server must end the connection, not hang
            chunk = s.recv(65536)
            if not chunk:
                break
            data += chunk
        s.close()
        assert b"boom" not in data
