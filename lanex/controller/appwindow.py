# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Open LanEx in its own app window using an installed Chromium-family browser.

LanEx ships no browser engine of its own (no Electron/CEF — those mean owning
Chromium security updates and a per-platform build matrix). Instead it reuses
the engine the user already has: every Chromium-family browser (Chrome, Edge,
Chromium, Brave, Vivaldi) supports ``--app=<url>`` — a chromeless standalone
window with its own taskbar entry, no tabs and no URL bar. The OS keeps the
engine patched; LanEx just launches it.

Launch strategy (every step degrades to the next — the caller falls back to a
plain browser tab when nothing here works):

* **WSL** — launch the *Windows* browser (Edge ships with Windows, so it is
  always there): first the well-known ``/mnt/c`` install paths directly via the
  interop bridge, then ``cmd.exe /c start`` which resolves ``msedge``/``chrome``
  through the App Paths registry. The window is a native Windows window — no
  WSLg, no GL. If interop is disabled, fall back to a Linux browser under WSLg.
* **Linux** — Chromium-family binary from ``$PATH`` (WSL-filtered), then
  Flatpak exported wrappers.
* **macOS** — the standard ``/Applications`` bundle binaries.
* **Native Windows** — the standard install paths under Program Files.

A dedicated ``--user-data-dir`` profile gives the window its own process and
taskbar identity and keeps LanEx out of the user's browsing session. It is
deliberately *omitted* for snap/Flatpak browsers (their confinement cannot
write the hidden ``~/.lanex`` dir) and when the profile dir cannot be created —
the app window still opens, it just shares the default profile.

Overrides: ``LANEX_BROWSER`` forces a specific browser (name or absolute
path); ``LANEX_NO_APP_WINDOW=1`` disables app-window launching entirely
(same effect as ``lanex --tab``).

Stdlib only; never imports ``webbrowser`` (the tab fallback lives in cli.py).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Dict, List, Optional, Tuple

from . import platform_env

_log = logging.getLogger("librelane.lanex.appwindow")

# How long to give a spawned browser before checking whether it died instantly.
# A healthy launch either keeps running (dedicated profile → own process) or
# exits 0 quickly (handed the URL to an already-running instance / `cmd start`).
# Only a fast NON-ZERO exit means "this candidate cannot launch — try the next".
_SPAWN_GRACE_S = 1.2

# PATH names, most-specific first. Chromium before Chrome so a distro Chromium
# is preferred over a Chrome that corporate policy may lock down; Edge before
# the more niche forks.
_POSIX_CANDIDATES = (
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
    "microsoft-edge",
    "microsoft-edge-stable",
    "brave-browser",
    "vivaldi",
)

# Flatpak exports a plain executable wrapper per app; launching the wrapper is
# equivalent to `flatpak run <id>` and passes our flags through.
_FLATPAK_IDS = (
    "org.chromium.Chromium",
    "com.google.Chrome",
    "com.microsoft.Edge",
    "com.brave.Browser",
)
_FLATPAK_EXPORT_DIRS = (
    "/var/lib/flatpak/exports/bin",
    os.path.expanduser("~/.local/share/flatpak/exports/bin"),
)

_MACOS_BUNDLE_BINARIES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
)

# Well-known Windows install paths, as seen from WSL (/mnt/c) and natively.
# Edge first: it ships with every Windows 10/11, so this list practically
# always resolves on WSL.
_WINDOWS_EXE_SUFFIXES = (
    "Microsoft/Edge/Application/msedge.exe",
    "Google/Chrome/Application/chrome.exe",
)
_WSL_PROGRAM_FILES = ("/mnt/c/Program Files (x86)", "/mnt/c/Program Files")


def app_window_disabled() -> bool:
    """True when the user opted out via ``LANEX_NO_APP_WINDOW``."""
    return os.environ.get("LANEX_NO_APP_WINDOW", "").strip() not in ("", "0")


def _sandboxed_browser(path: str) -> bool:
    """True for snap/Flatpak browsers whose confinement blocks ``~/.lanex``.

    Snap strict confinement only allows non-hidden files under ``$HOME``, and a
    Flatpak's home access is per-app policy — for both, pointing
    ``--user-data-dir`` at the hidden ``~/.lanex/app-profile`` fails (Chromium
    aborts with "cannot create profile directory"). Detect them and skip the
    flag; the app window works fine on the default profile.
    """
    try:
        real = os.path.realpath(path)
    except OSError:
        real = path
    parts = ("/snap/", "/flatpak/")
    return any(m in real or m in path for m in parts)


def _profile_dir_for(browser_path: str) -> Optional[str]:
    """The dedicated profile dir for *browser_path*, or None to skip the flag."""
    if _sandboxed_browser(browser_path):
        return None
    try:
        d = platform_env.home() / "app-profile"
        d.mkdir(parents=True, exist_ok=True)
        return str(d)
    except OSError:
        # Unwritable home (disk full, root-owned ~/.lanex, …) must not block
        # the window — degrade to the browser's default profile.
        return None


def build_app_argv(browser: str, url: str, *, profile_dir: Optional[str] = None) -> List[str]:
    """The ``--app`` argv for *browser*. List form only — never a shell string."""
    argv = [
        browser,
        f"--app={url}",
        # A fresh dedicated profile must not show Chrome's first-run wizard or
        # the default-browser nag inside what looks like the LanEx window.
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if profile_dir:
        argv.append(f"--user-data-dir={profile_dir}")
    if sys.platform.startswith("linux"):
        # X11/Wayland window class — lets the DE (and a user .desktop file with
        # StartupWMClass=lanex) group/pin the window as its own app.
        argv.append("--class=lanex")
    argv.append("--window-size=1440,900")
    return argv


def find_chromium_candidates() -> List[str]:
    """Every launchable Chromium-family browser on this host, preferred first.

    ``LANEX_BROWSER`` (absolute path or bare name) short-circuits to exactly
    that browser. PATH probes go through :func:`platform_env.usable_which` so a
    Windows ``.exe`` on the inherited WSL PATH is never picked for the *Linux*
    launch path (the Windows browser has its own dedicated branch).
    """
    forced = os.environ.get("LANEX_BROWSER", "").strip()
    if forced:
        if os.path.sep in forced:
            return [forced] if os.path.isfile(forced) and os.access(forced, os.X_OK) else []
        hit = platform_env.usable_which(forced)
        return [hit] if hit else []

    out: List[str] = []
    if sys.platform == "darwin":
        for name in _POSIX_CANDIDATES:
            hit = shutil.which(name)
            if hit and hit not in out:
                out.append(hit)
        for p in _MACOS_BUNDLE_BINARIES:
            if os.path.isfile(p) and os.access(p, os.X_OK) and p not in out:
                out.append(p)
        return out
    if os.name == "nt":  # native Windows (unusual for LanEx, but must not crash)
        for root in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.environ.get("ProgramFiles", r"C:\Program Files")):
            for suffix in _WINDOWS_EXE_SUFFIXES:
                p = os.path.join(root, *suffix.split("/"))
                if os.path.isfile(p) and p not in out:
                    out.append(p)
        return out
    # Linux / WSL (Linux-side)
    for name in _POSIX_CANDIDATES:
        hit = platform_env.usable_which(name)
        if hit and hit not in out:
            out.append(hit)
    for d in _FLATPAK_EXPORT_DIRS:
        for app_id in _FLATPAK_IDS:
            p = os.path.join(d, app_id)
            if os.path.isfile(p) and os.access(p, os.X_OK) and p not in out:
                out.append(p)
    return out


def find_chromium() -> Optional[str]:
    """The single best Chromium-family browser, or None."""
    cands = find_chromium_candidates()
    return cands[0] if cands else None


def _spawn_ok(argv: List[str], *, cwd: Optional[str] = None) -> bool:
    """Spawn *argv* detached; True unless it dies with a non-zero code instantly.

    Detached (``start_new_session``) with all stdio on DEVNULL — Chromium is
    noisy on stderr and must not inherit the server's terminal. ``rc == 0``
    within the grace window is SUCCESS (the process handed the URL to an
    already-running browser instance, or ``cmd start`` returned after
    launching); only a fast non-zero exit marks the candidate unusable.
    """
    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as ex:
        _log.debug("app-window spawn failed: %s (%s)", argv[0], ex)
        return False
    time.sleep(_SPAWN_GRACE_S)
    rc = proc.poll()
    if rc not in (None, 0):
        _log.debug("app-window candidate exited rc=%s: %s", rc, argv[0])
        return False
    return True


# --------------------------------------------------------------------------- #
# WSL → Windows-side launch
# --------------------------------------------------------------------------- #
def _windows_localappdata() -> Optional[str]:
    """The Windows ``%LOCALAPPDATA%`` path, resolved over the interop bridge.

    Used to give the Windows browser a Windows-side dedicated profile
    (``%LOCALAPPDATA%\\lanex\\app-profile``); a WSL path would be a fragile
    ``\\\\wsl$`` UNC for the Windows process. Returns None when it cannot be
    resolved — the caller then simply omits the profile flag.
    """
    cmdexe = shutil.which("cmd.exe")
    if not cmdexe:
        return None
    try:
        out = subprocess.run(
            [cmdexe, "/c", "echo %LOCALAPPDATA%"],
            capture_output=True, text=True, timeout=5,
            # A WSL cwd is a UNC path cmd.exe warns about; /mnt/c silences it.
            cwd="/mnt/c" if os.path.isdir("/mnt/c") else None,
        )
        val = (out.stdout or "").strip()
        if len(val) > 3 and val[1] == ":" and "%" not in val:
            return val
    except Exception:
        pass
    return None


def _windows_app_commands(url: str) -> List[Tuple[List[str], Optional[str]]]:
    """Candidate ``(argv, cwd)`` launches for a Windows-side app window."""
    cmds: List[Tuple[List[str], Optional[str]]] = []
    flags = [f"--app={url}", "--no-first-run", "--no-default-browser-check",
             "--window-size=1440,900"]
    lad = _windows_localappdata()
    if lad:
        flags.append(f"--user-data-dir={lad}\\lanex\\app-profile")

    # 1) Direct exe via the interop bridge — args pass verbatim, no cmd quoting.
    for root in _WSL_PROGRAM_FILES:
        for suffix in _WINDOWS_EXE_SUFFIXES:
            exe = os.path.join(root, *suffix.split("/"))
            if os.path.isfile(exe):
                cmds.append(([exe, *flags], None))
    # 2) Non-standard installs: `cmd start` resolves msedge/chrome through the
    #    App Paths registry. The empty "" arg is start's window-title slot.
    cmdexe = shutil.which("cmd.exe")
    if cmdexe:
        cwd = "/mnt/c" if os.path.isdir("/mnt/c") else None
        for name in ("msedge", "chrome"):
            cmds.append(([cmdexe, "/c", "start", "", name, *flags], cwd))
    return cmds


def _launch_windows_app(url: str) -> Dict[str, object]:
    for argv, cwd in _windows_app_commands(url):
        if _spawn_ok(argv, cwd=cwd):
            return {"ok": True, "method": "windows-app", "detail": argv[0]}
    return {"ok": False, "method": None,
            "detail": "no Windows browser reachable over the WSL interop bridge"}


def _launch_posix_app(url: str) -> Dict[str, object]:
    for browser in find_chromium_candidates():
        argv = build_app_argv(browser, url, profile_dir=_profile_dir_for(browser))
        if _spawn_ok(argv):
            return {"ok": True, "method": "app", "detail": browser}
    return {"ok": False, "method": None, "detail": "no Chromium-family browser found"}


def launch_app_window(url: str) -> Dict[str, object]:
    """Open *url* in a standalone app window. ``{"ok", "method", "detail"}``.

    Never raises; ``ok: False`` means the caller should fall back to a plain
    browser tab (and tell the user why, once).
    """
    try:
        if app_window_disabled():
            return {"ok": False, "method": None, "detail": "disabled by LANEX_NO_APP_WINDOW"}
        if platform_env.is_wsl():
            res = _launch_windows_app(url)
            if res["ok"]:
                return res
            # Interop disabled / no Windows browser: a Linux browser under
            # WSLg still gives an app window if there is a display.
            if platform_env.host_display_available():
                res = _launch_posix_app(url)
                if res["ok"]:
                    return res
            return {"ok": False, "method": None,
                    "detail": "no app-window-capable browser on Windows or WSL side"}
        if not platform_env.host_display_available():
            return {"ok": False, "method": None, "detail": "no graphical display"}
        return _launch_posix_app(url)
    except Exception as ex:  # pragma: no cover - absolute last-resort guard
        _log.debug("launch_app_window failed: %s", ex)
        return {"ok": False, "method": None, "detail": str(ex)}
