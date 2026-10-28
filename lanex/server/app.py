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

import gzip
import hashlib
import json
import logging
import math
import numbers
import os
import socket
import stat as _stat
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


def host_is_loopback(host: Optional[str]) -> bool:
    """True for a ``Host`` header that names this machine's loopback
    (``127.0.0.1:8765``, ``localhost``, ``[::1]:8765``, ``lanex.localhost``),
    or for no header at all. Anything else is another site's name."""
    if host is None or not str(host).strip():
        return True
    name = str(host).strip().lower()
    if name.startswith("["):
        end = name.find("]")
        if end < 0:
            return False
        name = name[1:end]
    elif name.count(":") == 1:
        name = name.split(":", 1)[0]
    name = name.rstrip(".")
    return name in _LOOPBACK_HOSTS or name.endswith(".localhost")


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


# Requests the Windows launcher makes itself. Everything else comes from a
# LanEx page, so it proves a window is alive even before that page has opened
# its event stream (a reload is several seconds of boot fetches first).
_LAUNCHER_PATHS = frozenset({"/api/presence", "/api/health"})


def _note_page_activity(path: str) -> None:
    if path not in _LAUNCHER_PATHS:
        from ..controller import activity
        activity.note_page_request()


# ---------- transport: compression, validators, static cache

# Text answers above this size go gzip-compressed to a client that accepts it.
_GZIP_MIN = 1024
# Dynamic answers are compressed on the fly (level 1: ~1 ms for 300 KB of
# JSON); above this they are sent as they are.
_GZIP_MAX_DYNAMIC = 8 * 1024 * 1024
_COMPRESSIBLE = ("application/json", "text/", "application/javascript", "image/svg+xml")

_STATIC_TYPES = {
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
}

# Static files by real path: (mtime_ns, size, bytes, gzip bytes or None, etag).
# Re-read when the file's mtime or size moves, so an edited first-party file is
# served at once (the dev install edits them in place).
_STATIC_CACHE: Dict[str, Tuple[int, int, bytes, Optional[bytes], str]] = {}
_STATIC_CACHE_MAX_FILE = 16 * 1024 * 1024
_GZ_PENDING: Any = object()   # compressible, gzip copy not made yet
_STATIC_TARGETS: Dict[str, Path] = {}
_STATIC_LOCK = threading.Lock()
_STATIC_BASE: List[Path] = []


def _static_base() -> Path:
    if not _STATIC_BASE:
        _STATIC_BASE.append(static_root().resolve())
    return _STATIC_BASE[0]


def _compressible(ctype: str) -> bool:
    return any(ctype.startswith(c) for c in _COMPRESSIBLE)


def _gzip_etag(etag: str) -> str:
    return etag[:-1] + '-gz"'


class LibreLaneGUIRequestHandler(BaseHTTPRequestHandler):
    """One request handler. Stream-friendly, no globals except the runner."""

    server_version = "LibreLaneGUI/0.1"
    # Keep-alive: a page load is ~90 requests; HTTP/1.0 opened a new connection
    # (and a new server thread) for each. Every answer carries Content-Length
    # (or closes the connection: the event stream, a handler that wrote
    # nothing, a failure part-way through an answer).
    protocol_version = "HTTP/1.1"
    # An idle kept-alive connection is closed after this long.
    timeout = 120
    # Headers and body go out as two writes; on a kept-alive connection Nagle
    # would hold the second until the client's delayed ACK of the first
    # (~40 ms per small answer). TCP_NODELAY sends both at once.
    disable_nagle_algorithm = True

    # Reduce the default BaseHTTPRequestHandler noise.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        _log.debug("%s - %s", self.address_string(), format % args)

    def handle_one_request(self) -> None:
        self._responded = False
        self._body_read = False
        self._conn_hdr = False
        super().handle_one_request()

    def send_response(self, code: int, message: Optional[str] = None) -> None:
        self._responded = True
        super().send_response(code, message)
        if self.close_connection and self.request_version != "HTTP/0.9":
            # Decided before answering (an HTTP/1.0 or "Connection: close"
            # client, an unread oversized body): say so.
            self.send_header("Connection", "close")

    def send_header(self, keyword: str, value: str) -> None:
        if keyword.lower() == "connection":
            if getattr(self, "_conn_hdr", False):
                return
            self._conn_hdr = True
        super().send_header(keyword, value)

    def _discard_body(self) -> None:
        """Read and drop a request body we answer without using (a refused
        POST), so the kept-alive connection stays in step; a body too large
        to drain ends the connection instead."""
        try:
            n = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            n = -1
        if n == 0:
            self._body_read = True
        elif 0 < n <= 10 * 1024 * 1024:
            self._body_read = len(self.rfile.read(n)) == n
        if not self._body_read:
            self.close_connection = True

    # ---------- low-level helpers

    def _accepts_gzip(self) -> bool:
        for part in (self.headers.get("Accept-Encoding") or "").lower().split(","):
            name, _, params = part.strip().partition(";")
            if name.strip() in ("gzip", "*"):
                q = params.strip()
                if q.startswith("q="):
                    try:
                        return float(q[2:]) > 0
                    except ValueError:
                        return False
                return True
        return False

    def _etag_matches(self, *etags: str) -> bool:
        inm = self.headers.get("If-None-Match")
        if not inm:
            return False
        sent = {t.strip().removeprefix("W/") for t in inm.split(",")}
        return "*" in sent or any(e in sent for e in etags)

    def _send_not_modified(self, etag: str, cache_control: str, vary: bool = False) -> None:
        # 304: no body, so no Content-Length (the client knows there is none).
        self.send_response(304)
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", cache_control)
        if vary:
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()

    def _encode_body(self, body: bytes, content_type: str) -> Tuple[bytes, Optional[str]]:
        """gzip a text answer for a client that accepts it (level 1: cheap)."""
        if _GZIP_MIN <= len(body) <= _GZIP_MAX_DYNAMIC and _compressible(content_type) \
                and self._accepts_gzip():
            return gzip.compress(body, compresslevel=1, mtime=0), "gzip"
        return body, None

    def _send_json(self, obj: Any, status: int = 200) -> None:
        # allow_nan=False guarantees standards-compliant JSON; _json_safe has
        # already converted every non-finite float, so this never raises here.
        body = json.dumps(_json_safe(obj), allow_nan=False).encode("utf-8")
        ctype = "application/json; charset=utf-8"
        # A successful GET carries a validator: the browser revalidates every
        # time (no-cache), and an unchanged answer (steps, variables, the run
        # list...) comes back as a bodiless 304 instead of the same bytes.
        etag = None
        if status == 200 and getattr(self, "command", "") == "GET":
            etag = '"' + hashlib.blake2b(body, digest_size=12).hexdigest() + '"'
            if self._etag_matches(etag, _gzip_etag(etag)):
                self._send_not_modified(_gzip_etag(etag) if self._accepts_gzip() and len(body) >= _GZIP_MIN
                                        else etag, "no-cache", vary=True)
                return
        body, enc = self._encode_body(body, ctype)
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache" if etag else "no-store")
        if etag:
            self.send_header("ETag", _gzip_etag(etag) if enc else etag)
            self.send_header("Vary", "Accept-Encoding")
        if enc:
            self.send_header("Content-Encoding", enc)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        body, enc = self._encode_body(text.encode("utf-8"), content_type)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if enc:
            self.send_header("Content-Encoding", enc)
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, blob: bytes, status: int = 200, content_type: str = "application/octet-stream") -> None:
        blob, enc = self._encode_body(blob, content_type)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        if enc:
            self.send_header("Content-Encoding", enc)
            self.send_header("Vary", "Accept-Encoding")
        self.end_headers()
        self.wfile.write(blob)

    def _send_file(self, path: str, content_type: str, status: int = 200) -> None:
        """Stream a file (a run's GDS or log can be tens of MB) with
        ``sendfile`` instead of reading it into memory. Opening it may raise
        (nothing is sent then); a file that shrinks while it is sent ends the
        connection, since the promised length can no longer be met."""
        f = open(path, "rb")
        try:
            size = os.fstat(f.fileno()).st_size
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command == "HEAD" or size == 0:
                return
            try:
                sent = self.connection.sendfile(f, 0, size)
            except (AttributeError, ValueError, OSError) as ex:
                if self._is_conn_error(ex):
                    raise
                f.seek(0)
                sent = 0
                while sent < size:
                    chunk = f.read(min(1024 * 1024, size - sent))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    sent += len(chunk)
            if sent < size:
                self.close_connection = True
        finally:
            f.close()

    def _send_404(self) -> None:
        self._send_text("Not found", 404)

    def _read_json_body(self) -> Dict[str, Any]:
        n = int(self.headers.get("Content-Length") or "0")
        if n > 10 * 1024 * 1024:  # 10MB limit
            raise ValueError("Payload too large")
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        self._body_read = len(raw) == n
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

    def _host_ok(self) -> bool:
        """Answer only requests addressed to a loopback name (DNS rebinding).

        A web page can point its own domain at 127.0.0.1; the browser then
        treats LanEx as that page's origin, so Origin == Host and the
        same-origin check above passes, letting the page read files and start
        Console commands. The ``Host`` it sends still names its domain: only
        127.0.0.1, localhost, ::1 and ``*.localhost`` are answered, unless the
        operator opted into LAN exposure (``--allow-remote``). Clients that send
        no Host (HTTP/1.0, raw sockets in tests) are not browsers and pass."""
        if _ALLOW_REMOTE:
            return True
        return host_is_loopback(self.headers.get("Host"))

    def _refuse_host(self) -> None:
        port = self.server.server_address[1] if getattr(self, "server", None) else 8765
        self._send_text(f"This LanEx server only answers at 127.0.0.1 or localhost. "
                        f"Open http://127.0.0.1:{port}/ instead.", 403)

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
        if not self._host_ok():
            self._refuse_host()
            return
        path = self.path.split("?", 1)[0]
        _note_page_activity(path)
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
                self._dispatch(fn)
                return

        # Static fallback.
        if path == "/" or path == "":
            self._serve_static("index.html")
            return
        if path == "/ide" or path == "/ide.html":
            self._serve_static("ide.html")
            return
        if path == "/landing" or path == "/landing.html":
            self._serve_static("landing.html")
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
        self._send_path(response["path"], response["content_type"])

    def do_HEAD(self) -> None:  # noqa: N802
        """Many browsers and module loaders issue HEAD.

        Mirror do_GET logic to compute headers, but write no body.
        """
        if not self._host_ok():
            self.send_response(403)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
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
        try:
            self._do_post()
        finally:
            # A POST answered without reading its body (refused, too large)
            # leaves those bytes on the connection: the next "request" would
            # be read from them. End the connection instead.
            if not getattr(self, "_body_read", False):
                try:
                    pending = int(self.headers.get("Content-Length") or "0") > 0
                except ValueError:
                    pending = True
                if pending:
                    self.close_connection = True

    def _do_post(self) -> None:
        if not self._host_ok():
            self._discard_body()
            self._refuse_host()
            return
        if self.headers.get("X-Requested-With") != "XMLHttpRequest":
            self._discard_body()
            self._send_text("CSRF validation failed", 403)
            return
        if not self._same_origin_ok():
            self._discard_body()
            self._send_text("cross-origin request rejected", 403)
            return

        path = self.path.split("?", 1)[0]
        _note_page_activity(path)
        if self.headers.get("X-LanEx-UTC-Offset") is not None:
            # The browser's time zone, for run names in local time.
            from ..controller.platform_env import note_client_utc_offset
            note_client_utc_offset(self.headers.get("X-LanEx-UTC-Offset"))

        # Rate limit install endpoints
        if "/install" in path:
            ip = self.client_address[0]
            now = time.time()
            if now - self._install_rates.get(ip, 0) < 1.0:
                self._discard_body()
                self._send_text("Rate limit exceeded", 429)
                return
            self._install_rates[ip] = now

        try:
            body = self._read_json_body()
        except ValueError as ex:
            msg = str(ex)
            if not self._body_read:
                self._discard_body()
            self._send_text(msg, 413 if "too large" in msg.lower() else 400)
            return
            
        self._body = body  # type: ignore[attr-defined]
        for prefix, fn in ROUTES:
            if self._match(prefix, path):
                self._dispatch(fn)
                return
        self._send_404()

    def _dispatch(self, fn: Callable[[Any], None]) -> None:
        try:
            fn(self)
        except Exception as ex:
            if self._is_conn_error(ex):
                _log.debug("client closed connection on %s", self.path)
                self.close_connection = True
                return            # socket is gone — don't try to write a 500
            _log.exception("dispatch failure on %s", self.path)
            if getattr(self, "_responded", False):
                # Part of an answer is already out: a second one would corrupt
                # the kept-alive stream. Closing tells the client it ended.
                self.close_connection = True
                return
            try:
                self._send_json({"error": str(ex)}, 500)
            except Exception as ex2:
                if not self._is_conn_error(ex2):
                    raise
                self.close_connection = True
        if not getattr(self, "_responded", False):
            # A handler that wrote nothing: close, as HTTP/1.0 did, rather than
            # leave the client waiting on a kept-alive connection.
            self.close_connection = True

    # ---------- static

    def _static_entry(self, rel: str) -> Optional[Tuple[Path, Tuple[int, int, bytes, Optional[bytes], str]]]:
        """(real path, cache entry) of a static file, or None (404).

        Resolution (symlink-safe containment in static/) is remembered per
        name; the file itself is stat'ed every time and re-read only when its
        mtime or size moved. Text files keep a gzip copy, made once."""
        base = _static_base()
        target = _STATIC_TARGETS.get(rel)
        if target is None:
            target = (base / rel).resolve()
            if not target.is_relative_to(base):
                return None
            with _STATIC_LOCK:
                if len(_STATIC_TARGETS) > 4096:
                    _STATIC_TARGETS.clear()
                _STATIC_TARGETS[rel] = target
        try:
            st = os.stat(target)
        except OSError:
            return None
        if not _stat.S_ISREG(st.st_mode):
            return None
        key = str(target)
        ent = _STATIC_CACHE.get(key)
        if ent is None or ent[0] != st.st_mtime_ns or ent[1] != st.st_size:
            try:
                with open(target, "rb") as f:
                    blob = f.read()
            except OSError:
                return None
            ctype = _STATIC_TYPES.get(target.suffix.lower(), "application/octet-stream")
            # The gzip copy is made on the first request that accepts it.
            gz: Any = _GZ_PENDING if len(blob) >= _GZIP_MIN and _compressible(ctype) else None
            ent = (st.st_mtime_ns, st.st_size, blob, gz, '"%x-%x"' % (st.st_mtime_ns, st.st_size))
            if st.st_size <= _STATIC_CACHE_MAX_FILE:
                with _STATIC_LOCK:
                    _STATIC_CACHE[key] = ent
        return target, ent

    def _serve_static(self, rel: str) -> None:
        found = self._static_entry(rel)
        if found is None:
            self._send_404()
            return
        target, ent = found
        _mt, _sz, blob, gz, etag = ent
        ctype = _STATIC_TYPES.get(target.suffix.lower(), "application/octet-stream")
        compressible = gz is not None
        if gz is _GZ_PENDING and self._accepts_gzip():
            packed = gzip.compress(blob, compresslevel=6, mtime=0)
            gz = packed if len(packed) < len(blob) else None
            if _sz <= _STATIC_CACHE_MAX_FILE:
                with _STATIC_LOCK:
                    if _STATIC_CACHE.get(str(target)) is ent:
                        _STATIC_CACHE[str(target)] = (_mt, _sz, blob, gz, etag)
        if gz is _GZ_PENDING:
            gz = None
        # Vendored, version-bumped assets (echarts ~1 MB, three.js, fonts, logos)
        # live under static/vendor/ and are immutable between releases: cached
        # for a day. First-party code (index.html, app.js, modules/*) is
        # revalidated on every load (no-cache + ETag), so an edit shows at once
        # (C4) while an unchanged file is a bodiless 304, which also keeps the
        # browser's compiled-code cache.
        vendor = target.relative_to(_static_base()).as_posix().startswith("vendor/")
        cache_control = "public, max-age=86400" if vendor else "no-cache"
        use_gz = gz is not None and self._accepts_gzip()
        sent_etag = _gzip_etag(etag) if use_gz else etag
        if self._etag_matches(etag, _gzip_etag(etag)):
            self._send_not_modified(sent_etag, cache_control, vary=compressible)
            return
        body = gz if use_gz else blob
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("ETag", sent_etag)
        if compressible:
            self.send_header("Vary", "Accept-Encoding")
        if use_gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_path(self, path: str, content_type: str) -> None:
        """A run file or view: a text file small enough is sent compressed
        to a client that takes gzip; anything else is streamed."""
        try:
            size = os.stat(path).st_size
        except OSError:
            self._send_404()
            return
        if _GZIP_MIN <= size <= _GZIP_MAX_DYNAMIC and _compressible(content_type) and self._accepts_gzip():
            try:
                with open(path, "rb") as f:
                    blob = f.read()
            except OSError:
                self._send_404()
                return
            self._send_bytes(blob, 200, content_type)
            return
        try:
            self._send_file(path, content_type)
        except OSError as ex:
            if self._is_conn_error(ex) or getattr(self, "_responded", False):
                raise
            self._send_404()

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
        self._send_path(response["path"], response["content_type"])


def _addr_family(host: str) -> int:
    """AF for *host* — an IPv6 literal (``::1``) needs AF_INET6 end to end.

    ``ThreadingHTTPServer`` defaults to AF_INET, so without this a perfectly
    loopback-safe ``--host ::1`` failed every bind attempt."""
    return socket.AF_INET6 if ":" in (host or "") else socket.AF_INET


class _ThreadingHTTPServer6(ThreadingHTTPServer):
    address_family = socket.AF_INET6


def find_free_port(preferred: int = 8765, *, host: str = "127.0.0.1", retries: int = 5) -> int:
    """Pick a free port, starting at `preferred`.

    Bind a socket on port 0 to let the kernel choose, then close it and
    return that number. We support up to ``retries`` tries if the requested
    range looks crowded; if every one collides, raise.
    """
    last_exc: Optional[Exception] = None
    for delta in range(0, retries + 2):
        port = preferred + delta
        with socket.socket(_addr_family(host), socket.SOCK_STREAM) as s:
            # The same option the server itself binds with (HTTPServer's
            # allow_reuse_address). Without it, connections of a server that
            # just died (TIME_WAIT) made its port look taken, so a restarted
            # LanEx came back one port up, where its open window could not
            # reconnect. On POSIX this never allows a port someone listens on;
            # on Windows SO_REUSEADDR would, so it is left off there.
            if os.name != "nt":
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
    server_cls = _ThreadingHTTPServer6 if _addr_family(host) == socket.AF_INET6 else ThreadingHTTPServer
    httpd = server_cls((host, actual_port), LibreLaneGUIRequestHandler)
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
