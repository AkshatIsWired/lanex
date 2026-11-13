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


# ------------------------------------------------- TLS context and failures ----

def test_https_context_verifies_and_adds_certifi(monkeypatch, tmp_path):
    import ssl
    import sys as _sys

    from lanex.controller import tlsctx

    loaded = []
    real = ssl.SSLContext.load_verify_locations

    def spy(self, cafile=None, *a, **k):
        loaded.append(cafile)
        return real(self, cafile, *a, **k)

    monkeypatch.setattr(ssl.SSLContext, "load_verify_locations", spy)
    certifi = pytest.importorskip("certifi")
    ctx = tlsctx.build_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True
    assert certifi.where() in loaded
    # macOS's own bundle is added only on macOS and only when present.
    bundle = tmp_path / "cert.pem"
    bundle.write_text(Path(certifi.where()).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(tlsctx, "_DARWIN_SYSTEM_BUNDLE", str(bundle))
    monkeypatch.setattr(_sys, "platform", "darwin")
    assert str(bundle) in tlsctx._extra_bundles()
    monkeypatch.setattr(_sys, "platform", "linux")
    assert str(bundle) not in tlsctx._extra_bundles()


def test_https_context_survives_missing_certifi(monkeypatch):
    import builtins
    import ssl

    from lanex.controller import tlsctx

    real_import = builtins.__import__

    def no_certifi(name, *a, **k):
        if name == "certifi":
            raise ImportError("no certifi")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_certifi)
    ctx = tlsctx.build_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_fetch_uses_the_lanex_context(monkeypatch, tmp_path):
    from lanex.controller import tlsctx

    seen = {}
    sentinel = object()
    monkeypatch.setattr(tlsctx, "https_context", lambda: sentinel)

    def fake_urlopen(req, timeout=None, context=None):
        seen["context"] = context
        raise OSError("stop")

    monkeypatch.setattr(pdkfeed.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(OSError):
        pdkfeed._fetch_once("https://example.invalid/x", tmp_path / "x.part",
                            lambda n: None, lambda: False)
    assert seen["context"] is sentinel


def _cert_error():
    import ssl
    import urllib.error

    err = ssl.SSLCertVerificationError(
        1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
           "unable to get local issuer certificate (_ssl.c:1000)")
    return urllib.error.URLError(err)


def test_certificate_failure_stops_after_one_try_per_url(monkeypatch, tmp_path):
    calls = []

    def fake_fetch(url, part, on_bytes, cancelled):
        calls.append(url)
        raise _cert_error()

    monkeypatch.setattr(pdkfeed, "_fetch_once", fake_fetch)
    monkeypatch.setattr(pdkfeed.time, "sleep", lambda s: pytest.fail("must not wait to retry"))
    asset = {"content": "common", "filename": "common.tar.zst", "mirrorName": "m-common",
             "url": "https://upstream.example/common.tar.zst", "sha256": "0" * 64}
    lines = []
    with pytest.raises(pdkfeed.CertificateError) as ei:
        pdkfeed.fetch_verified(asset, tmp_path, "https://mirror.example", on_bytes=lambda n: None,
                               cancelled=lambda: False, log=lines.append)
    assert calls == ["https://mirror.example/m-common", "https://upstream.example/common.tar.zst"]
    msg = str(ei.value)
    assert "\n" not in msg  # the terminal installer shows the first line only
    assert "certificate" in msg and "date and time" in msg and "proxy" in msg
    assert "retry" in msg.lower()


def test_certificate_advice_names_install_certificates_on_macos(monkeypatch):
    import sys as _sys

    from lanex.controller import tlsctx

    monkeypatch.setattr(_sys, "platform", "darwin")
    text = tlsctx.cert_failure_advice()
    assert "Install Certificates.command" in text
    monkeypatch.setattr(_sys, "platform", "linux")
    assert "Install Certificates" not in tlsctx.cert_failure_advice()


def test_is_cert_failure_classifies_through_platform_env():
    from lanex.controller import tlsctx

    assert tlsctx.is_cert_failure(_cert_error())
    assert tlsctx.is_cert_failure(OSError("SSL certificate problem: self signed certificate"))
    assert not tlsctx.is_cert_failure(ConnectionResetError("Connection reset by peer"))


def test_transient_failure_logs_once_then_short_retry_lines(monkeypatch, tmp_path):
    clock = {"t": 0.0}
    monkeypatch.setattr(pdkfeed.time, "monotonic", lambda: clock["t"])

    def fake_sleep(s):
        clock["t"] += s

    monkeypatch.setattr(pdkfeed.time, "sleep", fake_sleep)

    def fake_fetch(url, part, on_bytes, cancelled):
        raise ConnectionRefusedError("Connection refused")

    monkeypatch.setattr(pdkfeed, "_fetch_once", fake_fetch)
    asset = {"content": "c", "filename": "c.tar.zst", "url": "https://x.example/c",
             "sha256": "0" * 64}
    lines = []
    with pytest.raises(RuntimeError, match="after .* attempts"):
        pdkfeed.fetch_verified(asset, tmp_path, "", on_bytes=lambda n: None,
                               cancelled=lambda: False, log=lines.append)
    problem = [line for line in lines if "connection problem" in line]
    retry = [line for line in lines if "still retrying" in line]
    assert len(problem) == 1
    assert retry and "attempt 2" in retry[0] and "min left" in retry[0]
    # The budget is still the full 20 minutes of retrying.
    assert clock["t"] >= pdkfeed.FAILURE_BUDGET_S
