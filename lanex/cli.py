# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""LanEx entry point — the ``lanex`` console script.

LanEx is a standalone browser cockpit for the LibreLane RTL-to-GDSII flow. It
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
        description="Launch LanEx — a browser cockpit for the LibreLane RTL-to-GDSII flow.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="preferred port (default 8765)")
    parser.add_argument("--allow-remote", action="store_true",
                        help="permit binding a non-loopback host (exposes the GUI to your "
                             "network — there is no authentication; use with care)")
    parser.add_argument("--no-browser", action="store_true", help="don't open the default browser")
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

    url = f"http://{args.host}:{port}/"
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

    threading.Timer(0.5, _lazy_open, args=(home_url, args.no_browser)).start()
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
        sys.stdout.write(
            "\nImage pulled. Container run mode is ready — run `lanex` and keep the "
            "Container engine selected.\n"
        )
    else:
        sys.stderr.write(f"\n{engine} pull exited with code {rc}.\n")
    return rc


def _lazy_open(url: str, no_browser: bool) -> None:
    if no_browser:
        return
    import webbrowser

    try:
        webbrowser.open(url, new=2)
    except Exception as ex:  # pragma: no cover
        sys.stderr.write(f"could not launch browser: {ex}\n")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
