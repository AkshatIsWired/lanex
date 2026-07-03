# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Round-22 lock-in tests:

* server-side known-designs persistence (so cross-design Compare/DSE find every
  design the user opened, even after localStorage is cleared);
* the /api/known-designs endpoint reflects opened designs + the active one;
* OpenROAD container GUI forces software GL (fixes qglx_findConfig + chart/
  hierarchy glitches when the container has no GPU passthrough);
* the request handler treats a dropped client connection as benign (no 500
  cascade / log spam — the BrokenPipeError the user saw on /api/preflight).

Pure/stdlib + an in-process server; no Docker/PDK/network."""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from lanex.controller import container_tools as ct
from lanex.server.app import LibreLaneGUIRequestHandler as H


def test_designs_remember_and_list(tmp_path, monkeypatch):
    from lanex.controller import designs
    home = tmp_path / "home"
    monkeypatch.setenv("LANEX_HOME", str(home))
    a = tmp_path / "A"; a.mkdir()
    b = tmp_path / "B"; b.mkdir()
    designs.remember(str(a))
    designs.remember(str(b))
    designs.remember(str(a))                 # re-open A → moves to front, no dup
    got = designs.list_designs()
    assert got[0] == str(a.resolve())
    assert set(got) == {str(a.resolve()), str(b.resolve())}
    # A removed-from-disk design is dropped from the listing.
    import shutil
    shutil.rmtree(b)
    assert str(b.resolve()) not in designs.list_designs()


def test_openroad_forces_software_gl():
    flags = ct._x11_flags()
    assert "LIBGL_ALWAYS_SOFTWARE=1" in flags     # software Mesa
    assert "GALLIUM_DRIVER=llvmpipe" in flags


def test_conn_error_classifier():
    assert H._is_conn_error(BrokenPipeError())
    assert H._is_conn_error(ConnectionResetError())
    assert H._is_conn_error(ConnectionAbortedError())
    assert not H._is_conn_error(ValueError("nope"))


@pytest.fixture()
def _server(tmp_path, monkeypatch):
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))
    from lanex.server.app import make_server
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        base = s.getsockname()[1]
    httpd, port = make_server(host="127.0.0.1", port=base)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.05)
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"})
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


def _get(port, path):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 headers={"X-Requested-With": "XMLHttpRequest"})
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


def test_known_designs_endpoint(tmp_path, _server):
    port = _server
    a = tmp_path / "A"; (a / "runs").mkdir(parents=True)
    b = tmp_path / "B"; (b / "runs").mkdir(parents=True)
    _post(port, "/api/set-design-dir", {"path": str(a)})
    _post(port, "/api/set-design-dir", {"path": str(b)})   # B active now
    known = _get(port, "/api/known-designs")["data"]["designs"]
    # Both designs are remembered even though only B is active.
    assert str(a.resolve()) in known and str(b.resolve()) in known
