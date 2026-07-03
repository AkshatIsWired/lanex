# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""The HTTP handler.

A single ``BaseHTTPRequestHandler`` subclass dispatches based on ``self.path``.
Routing logic lives in :mod:`lanex.server.routes` so this file only deals with
transport concerns (encoding, headers, error mapping).
"""
from __future__ import annotations

import json
import logging
import math
import numbers
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .routes import ROUTES, static_root, serve_view, serve_run_file
from .sse import ISSEHandler, attach_sse_handler, detach_sse_handler
from ..controller.runner import FlowRunner

_log = logging.getLogger("librelane.lanex.server")

# Hosts considered loopback-safe for the default no-auth localhost cockpit.
# NB: the all-interfaces wildcards ("0.0.0.0", "::") are deliberately NOT here —
# they are the most-exposing bind there is and must go through the explicit
# --allow-remote gate in make_server(), same as any other non-loopback host.
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
# Set True by make_server(allow_remote=True). When the server is bound to a
# non-loopback address the operator has explicitly opted into LAN exposure;
# we still keep the same-origin check below as defence-in-depth.
_ALLOW_REMOTE = False


# The non-finite-float sanitiser lives in a neutral module (jsonsafe.py) so both
# the REST path here and the SSE path (sse.py) share ONE implementation without
# the app⇄sse import cycle. Re-exported under the historical private name for
# back-compat (tests and callers import ``lanex.server.app._json_safe``).
from .jsonsafe import json_safe as _json_safe

_RUNNER_LOCK = threading.Lock()
_RUNNER: Optional[FlowRunner] = None


def get_runner() -> FlowRunner:
    """Singleton runner per server process."""
    global _RUNNER
    with _RUNNER_LOCK:
        if _RUNNER is None:
            _RUNNER = FlowRunner()
        return _RUNNER


def set_runner(r: Optional[FlowRunner]) -> None:
    """Tests can swap the runner."""
    global _RUNNER
    with _RUNNER_LOCK:
        _RUNNER = r


class LibreLaneGUIRequestHandler(BaseHTTPRequestHandler):
    """One request handler. Stream-friendly, no globals except the runner."""

    server_version = "LibreLaneGUI/0.1"

    # Reduce the default BaseHTTPRequestHandler noise.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        _log.debug("%s - %s", self.address_string(), format % args)

    # ---------- low-level helpers

    def _send_json(self, obj: Any, status: int = 200) -> None:
        # allow_nan=False guarantees standards-compliant JSON; _json_safe has
        # already converted every non-finite float, so this never raises here.
        body = json.dumps(_json_safe(obj), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, blob: bytes, status: int = 200, content_type: str = "application/octet-stream") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)

    def _send_404(self) -> None:
        self._send_text("Not found", 404)

    def _read_json_body(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length") or "0")
        if n > 10 * 1024 * 1024:  # 10MB limit
            raise ValueError("Payload too large")
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        try:
            parsed = json.loads(raw)
        except Exception:
            # A genuinely malformed body must not be silently treated as ``{}``
            # (the handler would then run on defaults and "succeed" misleadingly).
            raise ValueError("Invalid JSON body")
        # Only object bodies are expected; coerce a bare value to {} so handlers
        # that do ``body.get(...)`` don't crash, but a syntactically valid scalar
        # isn't an error.
        return parsed if isinstance(parsed, dict) else {}

    def _same_origin_ok(self) -> bool:
        """Reject cross-origin POSTs (DNS-rebinding / malicious local page).

        The ``Origin``/``Referer`` host:port must equal the ``Host`` the request
        arrived on. Non-browser clients (curl/urllib/tests) send neither and are
        allowed — this only tightens the browser path, on top of the loopback
        bind and the ``X-Requested-With`` check.
        """
        origin = self.headers.get("Origin") or self.headers.get("Referer")
        if not origin:
            return True
        try:
            from urllib.parse import urlparse
            netloc = urlparse(origin).netloc
        except Exception:
            return False
        host_hdr = self.headers.get("Host", "")
        return bool(netloc) and netloc == host_hdr

    # ---------- dispatch

    @staticmethod
    def _is_conn_error(ex: BaseException) -> bool:
        """A dropped client connection (navigated away / cancelled fetch), not a
        server bug — writing a response back is impossible and just spams logs."""
        return isinstance(ex, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError))

    @staticmethod
    def _match(prefix: str, path: str) -> bool:
        """Match an HTTP path against an ROUTES prefix.

        A prefix ending with ``/`` (e.g. ``/api/tools/install/``) consumes the
        rest of the path. A prefix without the trailing slash matches only the
        exact path. ``GET /api/run/status`` does NOT accidentally hit
        ``/api/run/`` — the slash is significant.
        """
        if prefix.endswith("/"):
            return path == prefix or path.startswith(prefix)
        return prefix == path

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/api/events":
            last_event_id = self.headers.get("Last-Event-ID", "-1")
            try:
                start_seq = int(last_event_id)
            except Exception:
                start_seq = -1
            handler = ISSEHandler(self)
            attach_sse_handler(handler)
            try:
                handler.stream_until_closed(get_runner(), start_seq=start_seq)
            finally:
                detach_sse_handler(handler)
            return

        for prefix, fn in ROUTES:
            if self._match(prefix, path):
                # Found exact match — dispatch.
                try:
                    fn(self)
                except Exception as ex:
                    if self._is_conn_error(ex):
                        _log.debug("client closed connection on %s", self.path)
                        return            # socket is gone — don't try to write a 500
                    _log.exception("dispatch failure on %s", self.path)
                    try:
                        self._send_json({"error": str(ex)}, 500)
                    except Exception as ex2:
                        if not self._is_conn_error(ex2):
                            raise
                return

        # Static fallback.
        if path == "/" or path == "":
            self._serve_static("index.html")
            return
        if path == "/ide" or path == "/ide.html":
            self._serve_static("ide.html")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/"):]
            self._serve_static(rel)
            return
        if path.startswith("/api/views/"):
            self._serve_view(path[len("/api/views/"):])
            return
        if path == "/api/run-file":
            self._serve_run_file(self.path)
            return

        self._send_404()

    def _serve_run_file(self, full_path: str) -> None:
        """Serve any file inside a run dir (path-traversal safe) — powers the
        per-run file browser + image gallery."""
        try:
            response = serve_run_file(full_path)
        except Exception as ex:
            self._send_json({"error": str(ex)}, 400)
            return
        if response is None:
            self._send_404()
            return
        self._send_bytes(response["blob"], 200, response["content_type"])

    def do_HEAD(self) -> None:  # noqa: N802
        """Many browsers and module loaders issue HEAD.

        Mirror do_GET logic to compute headers, but write no body.
        """
        path = self.path.split("?", 1)[0]
        if path == "/api/events":
            # Long-lived stream; bail to the underlying HTTP server default
            # (which is a 200 since the connection will persist).
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            return

        for prefix, _fn in ROUTES:
            if self._match(prefix, path):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        if path.startswith("/static/"):
            base = static_root()
            target = (base / path[len("/static/"):]).resolve()
            try:
                target.relative_to(base)
                if target.is_file():
                    ext = target.suffix.lower()
                    ctype = {
                        ".html": "text/html; charset=utf-8",
                        ".js": "application/javascript; charset=utf-8",
                        ".mjs": "application/javascript; charset=utf-8",
                        ".css": "text/css; charset=utf-8",
                        ".json": "application/json; charset=utf-8",
                        ".svg": "image/svg+xml",
                        ".png": "image/png",
                        ".ico": "image/x-icon",
                    }.get(ext, "application/octet-stream")
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(target.stat().st_size))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                else:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                return
            except ValueError:
                pass
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    _install_rates: Dict[str, float] = {}

    def do_POST(self) -> None:  # noqa: N802
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            self._send_text("CSRF validation failed", 403)
            return
        if not self._same_origin_ok():
            self._send_text("cross-origin request rejected", 403)
            return

        path = self.path.split("?", 1)[0]

        # Rate limit install endpoints
        if "/install" in path:
            ip = self.client_address[0]
            now = time.time()
            if now - self._install_rates.get(ip, 0) < 1.0:
                self._send_text("Rate limit exceeded", 429)
                return
            self._install_rates[ip] = now

        try:
            body = self._read_json_body()
        except ValueError as ex:
            msg = str(ex)
            self._send_text(msg, 413 if "too large" in msg.lower() else 400)
            return
            
        self._body = body  # type: ignore[attr-defined]
        for prefix, fn in ROUTES:
            if self._match(prefix, path):
                try:
                    fn(self)
                except Exception as ex:
                    if self._is_conn_error(ex):
                        _log.debug("client closed connection on %s", self.path)
                        return
                    _log.exception("dispatch failure on %s", self.path)
                    try:
                        self._send_json({"error": str(ex)}, 500)
                    except Exception as ex2:
                        if not self._is_conn_error(ex2):
                            raise
                return
        self._send_404()

    # ---------- static

    def _serve_static(self, rel: str) -> None:
        base = static_root().resolve()
        target = (base / rel).resolve()
        if not target.is_relative_to(base):
            self._send_404()
            return
        if not target.is_file():
            self._send_404()
            return
        ext = target.suffix.lower()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".mjs": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
        }.get(ext, "application/octet-stream")
        try:
            st = target.stat()
            blob = target.read_bytes()
        except Exception:
            self._send_404()
            return
        # Vendored, version-bumped assets (echarts ~1 MB, three.js, fonts, logos)
        # live under static/vendor/ and are immutable between releases. Serve them
        # with a validating ETag + max-age instead of the blanket no-store, so a
        # WSL2/remote client stops re-downloading a megabyte on every page load.
        # First-party code (index.html, app.js, modules/*) stays no-store so edits
        # show up without a server restart (C4).
        rel_posix = target.relative_to(base).as_posix()
        if rel_posix.startswith("vendor/"):
            etag = '"%x-%x"' % (int(st.st_mtime), st.st_size)
            if (self.headers.get("If-None-Match") or "") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("ETag", etag)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(blob)
            return
        self._send_bytes(blob, 200, ctype)

    def _serve_view(self, spec: str) -> None:
        """Serve an artefact from the active run dir."""
        try:
            response = serve_view(spec)
        except FileNotFoundError:
            self._send_404()
            return
        except Exception as ex:
            self._send_json({"error": str(ex)}, 400)
            return
        if response is None:
            self._send_404()
            return
        self._send_bytes(response["blob"], 200, response["content_type"])


def find_free_port(preferred: int = 8765, *, host: str = "127.0.0.1", retries: int = 5) -> int:
    """Pick a free port, starting at `preferred`.

    Bind a socket on port 0 to let the kernel choose, then close it and
    return that number. We support up to ``retries`` tries if the requested
    range looks crowded; if every one collides, raise.
    """
    last_exc: Optional[Exception] = None
    for delta in range(0, retries + 2):
        port = preferred + delta
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError as ex:
                last_exc = ex
                continue
            return port
    raise RuntimeError(f"could not bind {host}:{preferred}+{retries} ({last_exc})")


def make_server(host: str = "127.0.0.1", port: int = 8765,
                allow_remote: bool = False) -> Tuple[ThreadingHTTPServer, int]:
    """Make a ThreadingHTTPServer bound to (host, port). Returns (server, actual_port).

    The GUI has no authentication and exposes filesystem + tool-launch endpoints,
    so binding to anything other than loopback is refused unless the operator
    passes ``allow_remote=True`` (CLI ``--allow-remote``). Even then the
    same-origin check on POSTs stays on.
    """
    global _ALLOW_REMOTE
    if host not in _LOOPBACK_HOSTS and not allow_remote:
        raise RuntimeError(
            f"refusing to bind {host!r}: the GUI has no authentication and serves "
            "filesystem + tool-launch endpoints. Bind 127.0.0.1 (default), or pass "
            "--allow-remote if you understand you're exposing it to your network."
        )
    _ALLOW_REMOTE = bool(allow_remote)
    actual_port = find_free_port(port, host=host)
    httpd = ThreadingHTTPServer((host, actual_port), LibreLaneGUIRequestHandler)
    return httpd, actual_port


def open_browser(url: str) -> None:
    """Cross-platform browser launch via stdlib."""
    try:
        webbrowser.open(url, new=2)
    except Exception:
        _log.exception("failed to open browser at %s", url)


def serve_forever(httpd: ThreadingHTTPServer, *, open_after: bool, url: Optional[str] = None) -> None:
    """Block on serve_forever(). Optionally open the browser once."""
    if open_after and url:
        threading.Timer(0.5, open_browser, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stdout.write("\nshutting down…\n")
        httpd.shutdown()
