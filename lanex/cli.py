# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""LanEx entry point — the ``lanex`` console script.

LanEx is a standalone cockpit for the LibreLane RTL-to-GDSII flow. It
ships as its own console script (``lanex``) and drives an installed ``librelane``
plus the EDA tools it orchestrates; it does not modify or depend on internals of
``librelane.__main__``.
"""
from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
from typing import List, Optional

_log = logging.getLogger("librelane.lanex.cli")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _print_url(url: str) -> None:
    sys.stdout.write(f"\nLanEx is running at: {url}\n")


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point. argv mirrors :mod:`click` style.

    Returns the :mod:`httpserver`-threading exit code.
    """
    import argparse  # stdlib
    parser = argparse.ArgumentParser(
        prog="lanex",
        description="Launch LanEx — a cockpit for the LibreLane RTL-to-GDSII flow.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="preferred port (default 8765)")
    parser.add_argument("--allow-remote", action="store_true",
                        help="permit binding a non-loopback host (exposes the GUI to your "
                             "network — there is no authentication; use with care)")
    parser.add_argument("--no-browser", action="store_true",
                        help="don't auto-open anything (headless; visit the printed URL)")
    parser.add_argument("--tab", action="store_true",
                        help="open in a normal browser tab instead of the standalone "
                             "app window (also: LANEX_NO_APP_WINDOW=1)")
    parser.add_argument("--design-dir", default=None, help="initial design directory")
    parser.add_argument("--pdk-root", default=None, help="PDK_ROOT (override)")
    parser.add_argument("--pull-image", action="store_true",
                        help="pull the version-matched LibreLane container image and exit "
                             "(headless toolchain setup for Container run mode); skips the GUI")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    _setup_logging(args.verbose)

    if args.pdk_root:
        os.environ["PDK_ROOT"] = args.pdk_root

    if args.pull_image:
        return _pull_image_cli()

    # Defer imports: read controller and server only when launched.
    try:
        from .server.app import make_server, serve_forever
    except Exception as ex:  # pragma: no cover
        sys.stderr.write(f"librelane gui cannot start: {ex}\n")
        return 2

    try:
        httpd, port = make_server(host=args.host, port=args.port, allow_remote=args.allow_remote)
    except Exception as ex:
        sys.stderr.write(f"could not bind {args.host}:{args.port} ({ex})\n")
        return 2

    # IPv6 literals need brackets in a URL (http://[::1]:8765/).
    host_disp = f"[{args.host}]" if ":" in args.host else args.host
    url = f"http://{host_disp}:{port}/"
    # The browser opens on the landing home screen; the printed URL stays the
    # cockpit root. The landing page honours the user's "skip this screen"
    # choice client-side and forwards to "/" instantly when set.
    home_url = url + "landing"
    _print_url(url)
    if args.design_dir:
        # Register the initial design directory directly with the server so the
        # GUI opens already pointed at it.
        try:
            import os.path

            from .server import routes as _routes

            p = os.path.abspath(os.path.expanduser(args.design_dir))
            if os.path.isdir(p):
                _routes._set_active_design_dir(p)
                sys.stdout.write(f"loaded design: {p}\n")
            else:
                sys.stderr.write(f"--design-dir not found: {p}\n")
        except Exception as ex:  # pragma: no cover - defensive
            sys.stderr.write(f"could not set --design-dir: {ex}\n")

    threading.Timer(0.5, _lazy_open, args=(home_url, args.no_browser, args.tab)).start()
    try:
        serve_forever(httpd, open_after=False)
    except KeyboardInterrupt:
        sys.stdout.write("\nshutting down…\n")
        try:
            httpd.shutdown()
        except Exception:
            pass
        return 0
    return 0


def _pull_image_cli() -> int:
    """Pull the version-matched LibreLane container image to completion, headless.

    The same toolchain setup the Tools tab's recommended one-click does, but from
    the command line — so ``pip install lanex && lanex --pull-image`` sets up the
    whole Container engine in one shot. Streams the engine's output and returns 0
    on success. The pulled image is auto-recognised by the GUI's Tools tab.
    """
    import subprocess

    try:
        from .controller import tools
        from .controller.container_run import image_ref, pull_argv
    except Exception as ex:  # pragma: no cover - import/env dependent
        sys.stderr.write(f"cannot resolve container helpers: {ex}\n")
        return 2

    resolved = tools.resolve_engine()
    if not resolved.get("ready"):
        sys.stderr.write(
            "No usable Docker or Podman engine found.\n"
            "Install one first (Linux: `curl -fsSL https://get.docker.com | sudo sh`, "
            "or `sudo apt install -y podman`; macOS: `brew install podman`; "
            "Windows: Docker Desktop with the WSL2 backend), then re-run "
            "`lanex --pull-image`. Or just run `lanex` and use the Tools tab — "
            "it can install the engine for you.\n"
        )
        return 1

    engine = resolved.get("engine") or "docker"
    image = image_ref()
    argv = pull_argv(engine)
    if resolved.get("sg_wrap"):
        argv = tools.sg_wrap_argv(pull_argv(engine))
    sys.stdout.write(f"Pulling {image} with {engine} (this is a one-time ~3 GB download)…\n")
    sys.stdout.flush()
    try:
        rc = subprocess.call(argv)
    except KeyboardInterrupt:  # pragma: no cover
        sys.stderr.write("\npull cancelled\n")
        return 130
    except Exception as ex:  # pragma: no cover - platform dependent
        sys.stderr.write(f"pull failed: {ex}\n")
        return 1
    if rc == 0:
        # Record the immutable digest of what we just validated against (cheap
        # upstream-independence insurance; see installer.record_image_digest).
        try:
            from .controller import installer

            digest = installer.record_image_digest(
                engine, image, sg_wrap=bool(resolved.get("sg_wrap")))
            if digest:
                sys.stdout.write(f"Image digest recorded: {digest}\n")
        except Exception:  # pragma: no cover - best-effort record only
            pass
        sys.stdout.write(
            "\nImage pulled. Container run mode is ready — run `lanex` and keep the "
            "Container engine selected.\n"
        )
    else:
        sys.stderr.write(f"\n{engine} pull exited with code {rc}.\n")
    return rc


def _lazy_open(url: str, no_browser: bool, tab: bool = False) -> None:
    if no_browser:
        return
    # Preferred: a standalone app window (Chromium-family `--app=` — own
    # window, no tabs/URL bar, own taskbar entry). `--tab` or
    # LANEX_NO_APP_WINDOW=1 opts out; every failure falls through to the
    # plain-tab logic below, so nothing here can leave the user with no UI.
    if not tab:
        try:
            from .controller import appwindow, platform_env

            res = appwindow.launch_app_window(url)
            if res.get("ok"):
                sys.stdout.write("LanEx opened in its own app window.\n")
                if res.get("method") == "windows-app" and platform_env.is_wsl():
                    # The one failure we cannot detect from inside WSL: broken
                    # Windows→WSL localhost forwarding (the window opens but
                    # cannot connect). Give the remedy up front.
                    sys.stdout.write(
                        "   If the window cannot reach LanEx, run `wsl --shutdown` "
                        "from Windows once, or use `lanex --tab`.\n")
                sys.stdout.flush()
                return
            if not appwindow.app_window_disabled():
                sys.stdout.write(
                    f"No app window ({res.get('detail')}) — opening a browser tab "
                    "instead. For an app window install Chrome/Edge/Chromium, or "
                    "use your browser's menu → 'Install LanEx'.\n")
                sys.stdout.flush()
        except Exception:  # pragma: no cover - defensive
            pass
    # On WSL, try the Windows browser FIRST. A fresh WSL distro has no Linux
    # browser, but webbrowser.open() still finds the gio/xdg-open shim and
    # returns True while that shim quietly no-ops ("gio: <url>: Operation not
    # supported") — so the page never opens and the fallback below never runs.
    # Handing the URL straight to Windows (wslview / powershell / explorer via
    # the interop bridge) opens the user's default Windows browser reliably.
    try:
        from .controller import platform_env

        if platform_env.is_wsl() and _open_via_windows(url):
            return
    except Exception:  # pragma: no cover - defensive
        pass

    import webbrowser

    try:
        if webbrowser.open(url, new=2):
            return
    except Exception:  # pragma: no cover
        pass
    sys.stderr.write(f"could not open a browser automatically — visit {url}\n")


def _open_via_windows(url: str) -> bool:
    """Open *url* in the user's Windows browser from WSL. True once one launches."""
    import shutil
    import subprocess

    # powershell Start-Process is the most reliable; explorer.exe last (it exits
    # non-zero on http URLs on some builds but still opens the browser).
    for argv in (
        ["wslview", url],
        ["powershell.exe", "-NoProfile", "-Command", f"Start-Process '{url}'"],
        ["explorer.exe", url],
    ):
        if not shutil.which(argv[0]):
            continue
        try:
            subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
