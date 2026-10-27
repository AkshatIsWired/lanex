# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""The verified PDK feed: resume, hash checks, mirror order, ciel's view."""

from __future__ import annotations

import hashlib
import http.server
import threading
from pathlib import Path

import pytest

from lanex.controller import pdkfeed


class _RangeHandler(http.server.SimpleHTTPRequestHandler):
    """Static files with single-range support and an optional mid-file drop."""

    drop_after: dict = {}

    def log_message(self, *args):
        pass

    def do_GET(self):  # noqa: N802
        path = Path(self.directory) / self.path.lstrip("/")
        if not path.is_file():
            self.send_error(404)
            return
        data = path.read_bytes()
        start = 0
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            start = int(rng[6:].split("-")[0])
            if start >= len(data):
                self.send_error(416)
                return
            self.send_response(206)
        else:
            self.send_response(200)
        body = data[start:]
        cut = self.drop_after.pop(self.path, None)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if cut is not None:
            self.wfile.write(body[:cut])
            self.wfile.flush()
            self.connection.close()
            return
        self.wfile.write(body)


@pytest.fixture
def server(tmp_path):
    root = tmp_path / "srv"
    root.mkdir()
    handler = lambda *a, **k: _RangeHandler(*a, directory=str(root), **k)  # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield root, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def _asset(root: Path, base: str, name: str, payload: bytes, mirror: bool = False):
    (root / ("m-" + name if mirror else name)).write_bytes(payload)
    return {"content": name.split(".")[0], "filename": name, "mirrorName": "m-" + name,
            "url": f"{base}/{name}", "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}


def test_resumes_after_a_dropped_connection(server, tmp_path):
    root, base = server
    payload = bytes(range(256)) * 4000
    asset = _asset(root, base, "lib.tar.zst", payload)
    _RangeHandler.drop_after["/lib.tar.zst"] = 100_000
    got = []
    out = pdkfeed.fetch_verified(asset, tmp_path, "", on_bytes=got.append,
                                 cancelled=lambda: False, log=lambda s: None)
    assert out.read_bytes() == payload
    assert not (tmp_path / "lib.tar.zst.part").exists()
    assert sum(got) == len(payload)  # the first 100 kB were not fetched twice


def test_mirror_first_and_wrong_hash_never_kept(server, tmp_path):
    root, base = server
    good = b"pdk" * 1000
    asset = _asset(root, base, "c.tar.zst", good)
    (root / "m-c.tar.zst").write_bytes(b"tampered" * 10)  # our copy is bad
    lines = []
    out = pdkfeed.fetch_verified(asset, tmp_path, base, on_bytes=lambda n: None,
                                 cancelled=lambda: False, log=lines.append)
    assert out.read_bytes() == good
    assert any("did not match its pinned SHA-256" in line for line in lines)


def test_cached_file_with_wrong_hash_is_replaced(server, tmp_path):
    root, base = server
    good = b"x" * 5000
    asset = _asset(root, base, "d.tar.zst", good)
    (tmp_path / "d.tar.zst").write_bytes(b"stale")
    out = pdkfeed.fetch_verified(asset, tmp_path, "", on_bytes=lambda n: None,
                                 cancelled=lambda: False, log=lambda s: None)
    assert out.read_bytes() == good


def test_gives_up_after_budget(server, tmp_path, monkeypatch):
    root, base = server
    asset = {"content": "e", "filename": "e.tar.zst", "url": f"{base}/missing",
             "sha256": "0" * 64, "size": 1}
    monkeypatch.setattr(pdkfeed, "FAILURE_BUDGET_S", 0)
    with pytest.raises(RuntimeError, match="pinned SHA-256"):
        pdkfeed.fetch_verified(asset, tmp_path, "", on_bytes=lambda n: None,
                               cancelled=lambda: False, log=lambda s: None)


def test_cancel_keeps_the_part_file(server, tmp_path):
    root, base = server
    asset = _asset(root, base, "f.tar.zst", b"y" * 300_000)
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(pdkfeed.Cancelled):
        pdkfeed.fetch_verified(asset, tmp_path, "", on_bytes=lambda n: None,
                               cancelled=cancelled, log=lambda s: None)
    assert (tmp_path / "f.tar.zst.part").exists()


def test_ciel_reads_the_local_feed(tmp_path):
    ciel_source = pytest.importorskip("ciel.source")
    common = pytest.importorskip("ciel.common")
    files = {"common.tar.zst": tmp_path / "common.tar.zst"}
    files["common.tar.zst"].write_bytes(b"c")
    pinned = {"version": "a" * 40, "date": "2025-04-17T00:00:00Z",
              "assets": [{"content": "common", "filename": "common.tar.zst"}]}
    root = tmp_path / "feed"
    with pdkfeed.serve(root) as url:
        root.mkdir(exist_ok=True)
        pdkfeed.write_static_source(root, "sky130", pinned, files, url)
        source = ciel_source.StaticWebDataSource(url)
        versions = source.get_available_versions("sky130")
        assert [v.name for v in versions] == ["a" * 40]
        _client, assets = source.get_downloads_for_version(common.Version("a" * 40, "sky130"))
        assert [a.url for a in assets] == [f"{url}/files/common.tar.zst"]


def test_load_pins_matches_family_and_version(tmp_path):
    doc = {"mirrorBase": "https://m", "families": {"sky130": {
        "version": "v1", "assets": [{"filename": "a", "content": "common"}]}}}
    assert pdkfeed.load_pins("sky130", "v1", doc)["mirrorBase"] == "https://m"
    assert pdkfeed.load_pins("sky130", "v2", doc) is None
    assert pdkfeed.load_pins("gf180mcu", "v1", doc) is None
