# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""What quitting LanEx right now would interrupt.

The Windows launcher quits LanEx (server + WSL appliance) when the last app
window closes, because a headless appliance quietly holding gigabytes of RAM
and CPU is worse than a cold start. Quitting kills everything inside the
appliance, so before it does, the launcher asks ``/api/presence`` what is still
going. Anything listed here gets a "LanEx is still busy with…" confirmation
instead of a silent kill; an empty list means the window close was the whole
story and LanEx can go.

Desktop viewers (KLayout, GTKWave, Magic, OpenROAD GUI…) are tracked by their
process handle because they outlive the browser window by design: a user who
opened KLayout and closed the cockpit is still working.
"""
from __future__ import annotations

import subprocess
import threading
import time
from typing import Dict, List, Optional, Tuple

_viewers: List[Tuple[str, subprocess.Popen]] = []
_viewers_lock = threading.Lock()
_last_page_request = time.monotonic()


def note_page_request() -> None:
    """Record that a LanEx page just talked to the server."""
    global _last_page_request
    _last_page_request = time.monotonic()


def seconds_since_page_request() -> float:
    """How long since any LanEx page last made a request.

    The open-stream count drops to zero for a moment whenever a window reloads;
    a page that is booting is still fetching, so this tells a reload apart
    from a close.
    """
    return max(0.0, time.monotonic() - _last_page_request)


# Pages that said hello recently, by the id each page picks for itself. An
# event stream is not enough to prove a window is open: a sleeping laptop, a
# Wi-Fi drop or Edge freezing a hidden window ends the stream while the window
# (and the user's unsaved work in it) is still there. The heartbeat survives
# those, and the page's own goodbye on close is what lets the launcher quit
# quickly when the user really did close it.
_pages: Dict[str, float] = {}
_pages_lock = threading.Lock()
_last_bye: Optional[float] = None
# A hidden page's timers can be throttled to one run a minute, so a heartbeat
# every 20 s may arrive only every ~60 s.
PAGE_ALIVE_FOR = 150.0


def note_hello(page_id: str) -> None:
    """A page is alive (sent on load and then on a timer)."""
    if not page_id:
        return
    with _pages_lock:
        _pages[page_id[:64]] = time.monotonic()
        if len(_pages) > 64:  # never grows without bound
            oldest = min(_pages, key=_pages.get)
            _pages.pop(oldest, None)


def note_bye(page_id: str) -> None:
    """A page is going away on purpose (closed, reloaded or navigated)."""
    global _last_bye
    with _pages_lock:
        _pages.pop(page_id[:64], None)
        _last_bye = time.monotonic()


def live_pages() -> int:
    """Pages whose last hello is recent enough to count as open."""
    now = time.monotonic()
    with _pages_lock:
        for pid in [k for k, t in _pages.items() if now - t > PAGE_ALIVE_FOR]:
            _pages.pop(pid, None)
        return len(_pages)


def seconds_since_bye() -> Optional[float]:
    """How long since a page last said goodbye (None if none ever did)."""
    with _pages_lock:
        if _last_bye is None:
            return None
        return max(0.0, time.monotonic() - _last_bye)


def track_viewer(proc: subprocess.Popen, label: str) -> None:
    """Remember a launched desktop tool until its process exits."""
    with _viewers_lock:
        _viewers.append((label, proc))


def open_viewers() -> List[str]:
    """Labels of tracked desktop tools whose process is still alive."""
    # One entry that can't be polled is dropped on its own; it must not make
    # every other open viewer vanish from the quit check.
    def alive(p) -> bool:
        try:
            return p.poll() is None
        except Exception:
            return False

    with _viewers_lock:
        _viewers[:] = [(label, p) for label, p in _viewers if alive(p)]
        return [label for label, _ in _viewers]


def busy() -> List[str]:
    """Plain-language list of work a quit would interrupt (empty when idle).

    Every probe is isolated: a broken subsystem must never make the launcher
    believe LanEx is idle when it is not, but it must not crash presence
    either, so a failing probe is simply skipped.
    """
    out: List[str] = []

    def probe(label: str, check) -> None:
        try:
            if check():
                out.append(label)
        except Exception:
            pass

    def _flow() -> bool:
        from ..server.app import get_runner
        return get_runner().running

    def _sweep() -> bool:
        from . import dse
        return dse.job.active

    def _sim() -> bool:
        from . import simulate
        return simulate.job.running

    def _manual() -> bool:
        from . import manualcmd
        return manualcmd.get_job().running

    def _install() -> bool:
        from . import installer
        with installer._in_progress_lock:
            return bool(installer._in_progress)

    probe("a flow run", _flow)
    probe("a design-space sweep", _sweep)
    probe("a simulation", _sim)
    probe("a command you started", _manual)
    probe("a download or install", _install)
    try:
        viewers = open_viewers()
    except Exception:
        viewers = []
    for label in sorted(set(viewers)):
        n = viewers.count(label)
        out.append(label if n == 1 else f"{label} ({n} windows)")
    return out
