# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Server-Sent Events streaming.

The HTTP request handler hands control over to :class:`ISSEHandler` which
drains the :class:`FlowRunner` event queue and writes ``text/event-stream``
blocks until the client disconnects or the runner reports a ``FLOW_DONE``.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterable, List, Optional, Set

from ..controller.runner import FlowRunner
from .jsonsafe import json_safe

_log = logging.getLogger("librelane.gui.sse")


# Active SSE handlers (used for diagnostics; useful for tests).
_HANDLERS: Set["ISSEHandler"] = set()


def attach_sse_handler(h: "ISSEHandler") -> None:
    _HANDLERS.add(h)


def detach_sse_handler(h: "ISSEHandler") -> None:
    _HANDLERS.discard(h)


def active_handlers() -> Set["ISSEHandler"]:
    return set(_HANDLERS)


def _json_default(obj: Any) -> Any:
    try:
        return obj.__dict__
    except Exception:
        return str(obj)


class ISSEHandler:
    """Asynchronous-ish content writer over a hijacked request handler.

    The :class:`http.server.BaseHTTPRequestHandler` is not async-friendly, so
    we write directly to ``self.wfile`` and flush between events. We rely on
    the underlying ThreadingHTTPServer to keep the connection alive per
    thread.
    """

    def __init__(self, request_handler: Any) -> None:
        self.request_handler = request_handler
        self._closed = False

    # ----------------------------------------------------------- wire format

    def _write(self, ev_type: str, payload: Any, *, event: Optional[str] = None, id: Optional[str] = None) -> None:
        if self._closed:
            return
        try:
            # json_safe() strips bare Infinity/NaN (the REST path already does
            # this via app._json_safe); allow_nan=False then guarantees the wire
            # is strict JSON the browser's JSON.parse accepts, so a live metric
            # of `inf` (normal for a design with no reg-to-reg paths) can no
            # longer silently kill the flow_done event client-side.
            body = json.dumps(json_safe(payload), default=_json_default, allow_nan=False)
        except Exception:
            body = json.dumps({"type": ev_type, "error": "unserialisable payload"})
        headers = []
        if id is not None:
            headers.append(f"id: {id}")
        if event:
            headers.append(f"event: {event}")
        headers.append(f"data: {body}")
        try:
            self.request_handler.wfile.write(("\n".join(headers) + "\n\n").encode("utf-8"))
            self.request_handler.wfile.flush()
        except Exception as ex:
            _log.debug("SSE write failed (client likely disconnected): %s", ex)
            self._closed = True

    def stream_until_closed(self, runner: FlowRunner, *, heartbeat: float = 15.0, idle: float = 0.4, start_seq: int = -1) -> None:
        """Stream events from the shared bus until the client disconnects.

        Reads :data:`lanex.controller.events.bus` non-destructively by sequence
        cursor, so every connected client sees every event (the cockpit and the
        ``/ide`` pop-out can both be open). The process-global, never-resetting
        sequence means a reconnecting ``EventSource`` (which sends the last
        ``id:`` it saw as ``Last-Event-ID``) resumes exactly where it left off —
        including the *next* run, which earlier was dropped as "already seen".

        Heartbeats (15s) keep proxies from aborting idle connections. The
        ``runner`` argument is kept for signature stability but unused.
        """
        from ..controller.events import bus

        try:
            self.request_handler.send_response(200)
            self.request_handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.request_handler.send_header("Cache-Control", "no-store")
            self.request_handler.send_header("X-Accel-Buffering", "no")
            self.request_handler.send_header("Connection", "keep-alive")
            self.request_handler.end_headers()
        except Exception:
            return

        # Thread-leak watchdog: bound every write so a wedged / half-open client
        # (one whose TCP receive buffer fills and never drains) can't pin this
        # ThreadingHTTPServer worker forever. A stuck write then raises
        # socket.timeout, which `_write` treats as a disconnect and closes the
        # stream. The 15s heartbeat below is the liveness probe that actually
        # triggers it on a silently-gone client. Stdlib only; cross-platform.
        try:
            self.request_handler.connection.settimeout(30.0)
        except Exception:
            pass

        self._write("hello", {"ts": time.time()}, event="hello")

        # A reconnecting client resumes from the last ``id:`` it saw. If events
        # were emitted and EVICTED from the bounded ring while it was gone (e.g.
        # a laptop slept through a verbose flow that pushed past the ring size),
        # resuming silently loses those step-transition events — the live
        # timeline would then show stale states behind a green "connected" chip.
        # Emit an explicit ``gap`` so the client re-hydrates from /api/run/status
        # rather than trusting its now-incomplete event history (Fear F, N3).
        min_buffered = bus.min_seq
        if start_seq >= 0 and min_buffered > 0 and start_seq + 1 < min_buffered:
            self._write(
                "gap",
                {"ts": time.time(), "resync": True,
                 "from_seq": start_seq, "oldest_seq": min_buffered},
                event="gap",
            )

        last_heartbeat = time.time()
        # A fresh connection (no Last-Event-ID) starts at the current end of the
        # ring so it doesn't replay the whole session's history; a reconnect
        # (start_seq >= 0) resumes from exactly where the client left off.
        last_seen_seq = start_seq if start_seq >= 0 else bus.max_seq
        while not self._closed:
            try:
                events = bus.events_since(last_seen_seq, block=True, timeout=idle)
            except Exception:
                events = []
            if not events:
                if time.time() - last_heartbeat > heartbeat:
                    self._write("ping", {"ts": time.time()}, event="ping")
                    last_heartbeat = time.time()
                continue
            for ev in events:
                seq = ev.get("seq", 0)
                if seq <= last_seen_seq:
                    continue
                last_seen_seq = seq
                self._write(ev.get("type", "info"), ev, id=str(seq))
            last_heartbeat = time.time()
