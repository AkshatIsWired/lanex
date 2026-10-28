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

Each stream sleeps until an event arrives, its heartbeat is due, or its
browser goes away (one shared watcher thread blocks in ``select`` on every
stream's socket), instead of waking every 0.4 s per open window. Events that
arrive together go out in one write; a busy log is sent at most every 0.1 s.
"""
from __future__ import annotations

import json
import logging
import os
import select
import socket
import threading
import time
from collections import OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Set

from ..controller.runner import FlowRunner
from .jsonsafe import json_safe

_log = logging.getLogger("librelane.gui.sse")


# Active SSE handlers (used for diagnostics; useful for tests).
_HANDLERS: Set["ISSEHandler"] = set()


def attach_sse_handler(h: "ISSEHandler") -> None:
    _HANDLERS.add(h)


def detach_sse_handler(h: "ISSEHandler") -> None:
    _HANDLERS.discard(h)
    _WATCHER.remove(h)


def active_handlers() -> Set["ISSEHandler"]:
    return set(_HANDLERS)


def _json_default(obj: Any) -> Any:
    try:
        return obj.__dict__
    except Exception:
        return str(obj)


# A write of at least this many events makes the stream wait this long before
# the next one, so a flow printing thousands of log lines a second costs ten
# writes a second per window instead of one per line. Fewer events go at once.
_BATCH_EVENTS = 20
_BATCH_PAUSE_S = 0.1

# Encoded frames by event sequence: every open window sends the same events,
# so each is serialised once.
_FRAMES: "OrderedDict[tuple, str]" = OrderedDict()
_FRAMES_MAX = 4096
_FRAMES_LOCK = threading.Lock()


def _bus_wake(bus: Any) -> None:
    """Wake every stream waiting on *bus* (a peer went away, a stream was told
    to stop)."""
    cond = getattr(bus, "_cond", None)
    if cond is None:
        return
    try:
        with cond:
            cond.notify_all()
    except Exception:
        pass


class _PeerWatcher:
    """One thread that sleeps in ``select`` on every open stream's socket and
    marks a stream closed the moment its browser closes it (EOF), so the
    open-window count the Windows launcher polls drops at once while no
    stream has to wake up to check."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._socks: Dict[int, "ISSEHandler"] = {}
        self._thread: Optional[threading.Thread] = None
        self._r: Optional[int] = None
        self._w: Optional[int] = None

    def add(self, h: "ISSEHandler") -> bool:
        try:
            fd = h.request_handler.connection.fileno()
        except Exception:
            return False
        if not isinstance(fd, int) or fd < 0:
            return False
        with self._lock:
            if self._thread is None:
                self._r, self._w = os.pipe()
                os.set_blocking(self._w, False)
                self._thread = threading.Thread(target=self._run, name="lanex-sse-watch", daemon=True)
                self._thread.start()
            self._socks[fd] = h
        self._poke()
        return True

    def remove(self, h: "ISSEHandler") -> None:
        with self._lock:
            for fd, x in list(self._socks.items()):
                if x is h:
                    del self._socks[fd]
        self._poke()

    def _poke(self) -> None:
        if self._w is not None:
            try:
                os.write(self._w, b"x")
            except OSError:
                pass

    def _run(self) -> None:
        while True:
            with self._lock:
                fds = list(self._socks)
            try:
                readable, _, _ = select.select(fds + [self._r], [], [])
            except (OSError, ValueError):
                # A socket closed under us: drop the ones that are gone.
                with self._lock:
                    for fd in list(self._socks):
                        try:
                            os.fstat(fd)
                        except OSError:
                            h = self._socks.pop(fd)
                            h._mark_gone()
                time.sleep(0.05)
                continue
            for fd in readable:
                if fd == self._r:
                    try:
                        os.read(self._r, 4096)
                    except OSError:
                        pass
                    continue
                with self._lock:
                    h = self._socks.get(fd)
                if h is None:
                    continue
                if h._peer_gone(drain=True):
                    with self._lock:
                        self._socks.pop(fd, None)
                    h._mark_gone()


_WATCHER = _PeerWatcher()


class ISSEHandler:
    """Asynchronous-ish content writer over a hijacked request handler.

    The :class:`http.server.BaseHTTPRequestHandler` is not async-friendly, so
    we write directly to ``self.wfile`` and flush between events. We rely on
    the underlying ThreadingHTTPServer to keep the connection alive per
    thread.
    """

    def __init__(self, request_handler: Any) -> None:
        self.request_handler = request_handler
        self.__closed = False
        self._bus: Any = None

    # Setting ``_closed`` (a failed write, a disconnect, a test stopping the
    # stream) wakes the stream at once instead of at its next heartbeat.
    @property
    def _closed(self) -> bool:
        return self.__closed

    @_closed.setter
    def _closed(self, value: bool) -> None:
        self.__closed = bool(value)
        if value and self._bus is not None:
            _bus_wake(self._bus)

    def _mark_gone(self) -> None:
        self._closed = True

    # ----------------------------------------------------------- wire format

    @staticmethod
    def _frame(ev_type: str, payload: Any, *, event: Optional[str] = None, id: Optional[str] = None) -> str:
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
        return "\n".join(headers) + "\n\n"

    def _send(self, text: str) -> None:
        if self._closed:
            return
        try:
            self.request_handler.wfile.write(text.encode("utf-8"))
            self.request_handler.wfile.flush()
        except Exception as ex:
            _log.debug("SSE write failed (client likely disconnected): %s", ex)
            self._closed = True

    def _write(self, ev_type: str, payload: Any, *, event: Optional[str] = None, id: Optional[str] = None) -> None:
        if self._closed:
            return
        self._send(self._frame(ev_type, payload, event=event, id=id))

    def _bus_frames(self, ev: Dict[str, Any]) -> str:
        """The wire frames of one bus event (cached by sequence). A ``batch``
        event (several events emitted as one) goes out as its events, in
        order, the last carrying the batch's id."""
        seq = ev.get("seq", 0)
        key = (seq, id(ev))
        with _FRAMES_LOCK:
            hit = _FRAMES.get(key)
        if hit is not None:
            return hit
        if ev.get("type") == "batch" and isinstance(ev.get("events"), list):
            subs = [e for e in ev["events"] if isinstance(e, dict)]
            parts = [self._frame(e.get("type", "info"), e, id=(str(seq) if i == len(subs) - 1 else None))
                     for i, e in enumerate(subs)]
            text = "".join(parts)
        else:
            text = self._frame(ev.get("type", "info"), ev, id=str(seq))
        with _FRAMES_LOCK:
            _FRAMES[key] = text
            while len(_FRAMES) > _FRAMES_MAX:
                _FRAMES.popitem(last=False)
        return text

    def _peer_gone(self, drain: bool = False) -> bool:
        """True once the browser has closed this stream's socket.

        A closed window otherwise goes unnoticed until the next write fails,
        which can take a heartbeat plus a buffered write or two (15-45 s). The
        open-window count in ``/api/presence`` is what the Windows launcher
        uses to decide that LanEx was closed, so it must drop within a tick.
        An EventSource never sends anything after its request, so a readable
        socket that peeks zero bytes can only mean EOF. (``drain``: bytes a
        client did send are read and dropped, so the watcher's select does
        not spin on them.)
        """
        try:
            sock = self.request_handler.connection
            readable, _, _ = select.select([sock], [], [], 0)
            if not readable:
                return False
            data = sock.recv(4096 if drain else 1, socket.MSG_DONTWAIT if drain else socket.MSG_PEEK)
            return data == b""
        except (BlockingIOError, InterruptedError, socket.timeout):
            return False
        except (OSError, ValueError):
            return True
        except Exception:
            return False

    @staticmethod
    def _events_since(bus: Any, cursor: int, timeout: float) -> List[Dict[str, Any]]:
        """Events after *cursor*, waiting up to *timeout* for one. Reads the
        ring from its newest end (the old read compared all 20 000 entries
        on every wake), in ring order, like ``bus.events_since``."""
        cond = getattr(bus, "_cond", None)
        buf = getattr(bus, "_buf", None)
        if cond is None or buf is None:
            return bus.events_since(cursor, block=True, timeout=timeout)

        def collect() -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            # Walk back until well past the cursor: emitters stamp sequence
            # numbers before taking the ring's lock, so the ring is ordered
            # only nearly; 64 entries of slack cover any interleaving.
            slack = 64
            for e in reversed(buf):
                if e.get("seq", 0) > cursor:
                    out.append(e)
                else:
                    slack -= 1
                    if slack <= 0:
                        break
            out.reverse()
            return out

        with cond:
            new = collect()
            if new or timeout <= 0:
                return new
            cond.wait(timeout)
            return collect()

    def stream_until_closed(self, runner: FlowRunner, *, heartbeat: float = 15.0, idle: float = 0.4, start_seq: int = -1) -> None:
        """Stream events from the shared bus until the client disconnects.

        Reads :data:`lanex.controller.events.bus` non-destructively by sequence
        cursor, so every connected client sees every event (the cockpit and the
        ``/ide`` pop-out can both be open). The process-global, never-resetting
        sequence means a reconnecting ``EventSource`` (which sends the last
        ``id:`` it saw as ``Last-Event-ID``) resumes exactly where it left off —
        including the *next* run, which earlier was dropped as "already seen".

        Heartbeats (15s) keep proxies from aborting idle connections. The
        ``runner`` argument is kept for signature stability but unused, and
        ``idle`` is now only an upper bound on one wait for a stream whose
        socket cannot be watched (a test's fake connection).
        """
        from ..controller import events as _events
        bus = _events.bus
        self._bus = bus

        try:
            self.request_handler.send_response(200)
            self.request_handler.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.request_handler.send_header("Cache-Control", "no-store")
            self.request_handler.send_header("X-Accel-Buffering", "no")
            # The stream has no length: it ends when the connection does, so
            # the (HTTP/1.1, otherwise kept-alive) connection is not reused.
            self.request_handler.send_header("Connection", "close")
            self.request_handler.close_connection = True
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

        watched = _WATCHER.add(self)
        last_heartbeat = time.time()
        # A fresh connection (no Last-Event-ID) starts at the current end of the
        # ring so it doesn't replay the whole session's history; a reconnect
        # (start_seq >= 0) resumes from exactly where the client left off.
        last_seen_seq = start_seq if start_seq >= 0 else bus.max_seq
        try:
            while not self._closed:
                wait = max(0.0, heartbeat - (time.time() - last_heartbeat))
                if not watched:
                    wait = min(wait, idle)
                try:
                    evs = self._events_since(bus, last_seen_seq, wait)
                except Exception:
                    evs = []
                if self._closed:
                    break
                if not evs:
                    if not watched and self._peer_gone():
                        self._closed = True
                        break
                    if time.time() - last_heartbeat >= heartbeat:
                        self._write("ping", {"ts": time.time()}, event="ping")
                        last_heartbeat = time.time()
                    continue
                parts: List[str] = []
                for ev in evs:
                    seq = ev.get("seq", 0)
                    if seq <= last_seen_seq:
                        continue
                    last_seen_seq = seq
                    parts.append(self._bus_frames(ev))
                if parts:
                    self._send("".join(parts))
                last_heartbeat = time.time()
                if len(parts) >= _BATCH_EVENTS and not self._closed:
                    time.sleep(_BATCH_PAUSE_S)
        finally:
            _WATCHER.remove(self)
