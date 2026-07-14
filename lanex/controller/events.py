# Copyright 2026 LanEx Contributors
"""Process-wide event bus.

The runner, the installer, the simulator, and the tool manager all push events
here. Every SSE client drains from this single bus.

Design notes (why a ring buffer + a global sequence):

* **One monotonic sequence across the whole process** (:func:`next_seq`). The
  sequence never resets between runs, so a browser ``EventSource`` that
  reconnects (carrying ``Last-Event-ID``) correctly receives the *next* run's
  events instead of silently dropping them as "already seen".
* **Non-destructive reads** (:meth:`EventBus.events_since`). Multiple SSE clients
  (e.g. the main cockpit and the ``/ide`` pop-out, or two browser tabs) each keep
  their own cursor and all see every event — reading no longer consumes the
  queue, so clients can't starve each other.
* **Bounded** (a ``deque`` with ``maxlen``) so a long run can't grow memory
  without bound; very old events fall off the back once every client has long
  since read past them.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

# --- process-global monotonic sequence -------------------------------------

_seq_lock = threading.Lock()
_seq = 0


def next_seq() -> int:
    """Return the next process-global event sequence number (never resets)."""
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


class EventBus:
    """A bounded, broadcast, non-destructive event ring."""

    def __init__(self, maxlen: int = 20000) -> None:
        self._buf: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._cond = threading.Condition(threading.RLock())

    def emit(self, type_: str, payload: Optional[Dict[str, Any]] = None) -> None:
        """Append an event. If *payload* already carries an int ``seq`` (the
        runner mirrors its own events here with the seq it already stamped) we
        keep it so the two copies collapse; otherwise we assign a fresh one."""
        payload = payload or {}
        seq = payload.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool):
            seq = next_seq()
        evt = dict(payload)
        evt["type"] = type_
        evt["seq"] = seq
        evt.setdefault("ts", time.time())
        with self._cond:
            self._buf.append(evt)
            self._cond.notify_all()

    def events_since(self, cursor: int, *, block: bool = False, timeout: float = 0.4) -> List[Dict[str, Any]]:
        """Return every buffered event with ``seq > cursor`` (non-destructive).

        With ``block=True`` and nothing new, wait up to ``timeout`` for an emit
        before returning (so SSE can long-poll without a busy loop)."""
        with self._cond:
            new = [e for e in self._buf if e.get("seq", 0) > cursor]
            if new or not block:
                return new
            self._cond.wait(timeout)
            return [e for e in self._buf if e.get("seq", 0) > cursor]

    @property
    def max_seq(self) -> int:
        with self._cond:
            return self._buf[-1].get("seq", 0) if self._buf else 0

    @property
    def min_seq(self) -> int:
        """Sequence of the OLDEST event still buffered (0 when empty).

        A reconnecting client that resumes from a cursor older than this has had
        the events in between evicted from the ring — its live view is now stale
        with no way to notice. The SSE layer uses this to emit an explicit
        ``gap`` so the client can re-hydrate from the authoritative status."""
        with self._cond:
            return self._buf[0].get("seq", 0) if self._buf else 0


# Singleton
bus = EventBus()


def publish(type_: str, payload: Optional[Dict[str, Any]] = None) -> None:
    bus.emit(type_, payload or {})
