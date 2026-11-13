# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""Which GTKWave is usable, shared by the installer, readiness and launch.

On macOS two GTKWaves exist. The Homebrew FORMULA (homebrew-core, 2024 on) is a
native binary that works. The legacy CASK installed ``gtkwave.app`` and linked a
``gtkwave`` launcher into ``/usr/local/bin``; that launcher is a Perl script
which needs ``Switch.pm``, a module modern macOS no longer ships, so it dies
with a Perl ``@INC`` error. A PATH lookup finds that launcher and calls GTKWave
installed. Here only a working binary counts:

* the formula's own binary (``<brew prefix>/opt/gtkwave/bin/gtkwave``) first,
  which works whether or not ``brew link`` could put it on PATH;
* otherwise the PATH hit, unless it is the legacy Perl launcher.

Off macOS this is the ordinary user-bin lookup.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Callable, Dict, List, Optional

FIX_COMMAND = "brew install gtkwave && brew link --overwrite gtkwave"

BROKEN_MESSAGE = (
    "The GTKWave on this Mac is the old GTKWave app, which no longer runs on "
    "this version of macOS (it needs a Perl module macOS removed). Install the "
    f"current one in Terminal with:  {FIX_COMMAND}  (your old app is not deleted)."
)

_BREW_PREFIXES = ("/opt/homebrew", "/usr/local")


def _formula_candidates() -> List[str]:
    return [f"{p}/opt/gtkwave/bin/gtkwave" for p in _BREW_PREFIXES]


def _executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def is_legacy_launcher(path: Optional[str]) -> bool:
    """True for the legacy cask's Perl launcher (or anything inside gtkwave.app
    that resolves to it)."""
    if not path:
        return False
    try:
        real = os.path.realpath(path)
    except Exception:
        real = path
    in_app = "gtkwave.app/" in real.replace("\\", "/").lower()
    try:
        with open(real, "rb") as f:
            head = f.read(256)
    except Exception:
        # Unreadable: only the cask's bundle is presumed to be the old launcher.
        return in_app
    return head.startswith(b"#!") and b"perl" in head.split(b"\n", 1)[0]


def _path_hit() -> Optional[str]:
    from . import platform_env

    return platform_env.resolve_user_bin("gtkwave")


def resolve() -> Optional[str]:
    """Path of a usable gtkwave binary, or None."""
    if sys.platform != "darwin":
        return _path_hit()
    for cand in _formula_candidates():
        if _executable(cand) and not is_legacy_launcher(cand):
            return cand
    hit = _path_hit()
    if hit and not is_legacy_launcher(hit):
        return hit
    return None


def status() -> Dict[str, Any]:
    """``{ready, path, legacy, message}``; *legacy* is the broken launcher's
    path when one is shadowing PATH."""
    path = resolve()
    legacy = None
    if sys.platform == "darwin":
        hit = _path_hit()
        if hit and is_legacy_launcher(hit):
            legacy = hit
    msg = ""
    if not path:
        msg = BROKEN_MESSAGE if legacy else (
            "GTKWave is not installed. Install it from the Tools tab"
            + (", or in Terminal with:  brew install gtkwave" if sys.platform == "darwin" else "")
            + ".")
    return {"ready": bool(path), "path": path, "legacy": legacy, "message": msg}


def link_conflict(output: str) -> bool:
    """brew's message when another file already sits where it wants a link."""
    low = (output or "").lower()
    return "could not symlink" in low or "brew link --overwrite" in low


def install_formula(run: Callable[[List[str]], Dict[str, Any]], brew: str) -> Dict[str, Any]:
    """Install the formula and put it ahead of a legacy launcher.

    *run* takes an argv and returns ``{rc, output}``. ``brew link --overwrite``
    replaces only the conflicting symlink in brew's bin directory; the old
    ``gtkwave.app`` itself is left alone."""
    res = run([brew, "install", "gtkwave"])
    out = "\n".join(res.get("output") or []) if isinstance(res.get("output"), list) \
        else str(res.get("output") or "")
    hit = _path_hit()
    if link_conflict(out) or (hit and is_legacy_launcher(hit)):
        run([brew, "link", "--overwrite", "gtkwave"])
    st = status()
    st["rc"] = res.get("rc")
    return st
