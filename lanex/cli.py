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

    # macOS: make Homebrew-installed tools (podman, klayout, …) visible even
    # when this process was launched without `brew shellenv` on its PATH
    # (pipx entry point, app-window launcher). Appends only; no-op elsewhere.
    try:
        from .controller.platform_env import ensure_darwin_path
        ensure_darwin_path()
    except Exception:
        pass
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
    parser.add_argument("--install-tool", metavar="TOOL", default=None,
                        help="install one supporting tool headlessly and exit (e.g. gds3d, "
                             "gtkwave, iverilog, graphviz) — the same strategies as the "
                             "Tools tab's Install button; skips the GUI")
    parser.add_argument("--verbose", action="store_true")
    # Not argparse's `action="version"`: that evaluates its version string while
    # the parser is being built, and get_version() imports librelane — a cost
    # every single `lanex` invocation would pay for one rarely used flag.
    parser.add_argument("--version", action="store_true",
                        help="print the LanEx version and exit")
    args = parser.parse_args(argv)

    if args.version:
        from ._version import get_version

        sys.stdout.write(f"lanex {get_version()}\n")
        return 0

    _setup_logging(args.verbose)

    # Resolve the path arguments against the cwd the user typed them in BEFORE
    # _leave_unwritable_cwd() possibly moves us: `lanex --design-dir ./cpu` must
    # keep meaning ./cpu.
    if args.pdk_root:
        args.pdk_root = os.path.abspath(os.path.expanduser(args.pdk_root))
    if args.design_dir:
        args.design_dir = os.path.abspath(os.path.expanduser(args.design_dir))
    _leave_unwritable_cwd()

    if args.pdk_root:
        os.environ["PDK_ROOT"] = args.pdk_root

    if args.pull_image:
        return _pull_image_cli()

    if args.install_tool:
        return _install_tool_cli(args.install_tool)

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
            from .server import routes as _routes

            # Already absolute — resolved above, against the cwd the user typed
            # it in rather than whichever one we ended up with.
            p = args.design_dir
            if os.path.isdir(p):
                _routes._set_active_design_dir(p)
                sys.stdout.write(f"loaded design: {p}\n")
            else:
                sys.stderr.write(f"--design-dir not found: {p}\n")
        except Exception as ex:  # pragma: no cover - defensive
            sys.stderr.write(f"could not set --design-dir: {ex}\n")

    threading.Timer(0.5, _lazy_open, args=(home_url, args.no_browser, args.tab)).start()
    _write_server_record(url, port)
    try:
        serve_forever(httpd, open_after=False)
    except KeyboardInterrupt:
        sys.stdout.write("\nshutting down…\n")
        try:
            httpd.shutdown()
        except Exception:
            pass
        return 0
    finally:
        _clear_server_record()
    return 0


def _leave_unwritable_cwd() -> None:
    """Move off a working directory we cannot write into.

    A long-running server's cwd is invisible to the user but not harmless: it is
    what everything defaulting to "the current directory" resolves to, and what
    every child process inherits. On the Windows appliance the launcher
    (``windows/launcher``) lives in ``C:\\Program Files\\LanEx`` and ``wsl.exe``
    translates its Windows cwd into the Linux one, so the server started life in
    ``/mnt/c/Program Files/LanEx`` — read-only for the appliance user. The visible
    symptom was "Could not copy the SPM example: [Errno 13] Permission denied:
    '/mnt/c/Program Files/LanEx/spm_example'"; the file picker's "Current dir"
    root pointed at the same dead end.

    ``wsl.go``'s ``cd ~`` fixes it at the source, but that lives in ``LanEx.exe``
    and only reaches users who reinstall — whereas this file ships in the pip
    layer, so an existing install gets the fix on a server update alone. It also
    covers the native case: LanEx started from a read-only directory anywhere.

    Only ever moves when the cwd is genuinely unwritable — a deliberate
    ``cd my-design && lanex`` must keep its cwd, because relative paths the user
    types into the GUI resolve against it.
    """
    try:
        cwd = os.getcwd()
    except OSError:
        # cwd deleted under us. Nothing to preserve; anywhere writable is better.
        cwd = None
    if cwd is not None and os.access(cwd, os.W_OK | os.X_OK):
        return
    import tempfile

    for candidate in (os.path.expanduser("~"), tempfile.gettempdir()):
        if not candidate or not os.access(candidate, os.W_OK | os.X_OK):
            continue
        try:
            os.chdir(candidate)
        except OSError:
            continue
        _log.info("working directory %s is not writable — using %s instead",
                  cwd, candidate)
        return
    # Nowhere to go: leave it be. Every write path reports its own error, and a
    # server that refuses to start is strictly worse than one with a bad cwd.
    _log.warning("working directory %s is not writable and no alternative was "
                 "usable", cwd)


def _server_record_path():
    """``~/.lanex/server.json`` — where this process advertises its port."""
    from .controller.platform_env import home

    return home() / "server.json"


def _write_server_record(url: str, port: int) -> None:
    """Record the bound URL/port/pid for out-of-process launchers.

    ``find_free_port`` may settle on 8766+ when something else owns 8765
    (app.py:436-453), so anything outside this process — the Windows launcher in
    ``windows/launcher``, a shortcut, a script — otherwise has to probe the whole
    range to find the cockpit. This file turns that into one read.

    Entirely best-effort, in both directions: a failure to write must never stop
    the server from serving, and readers must treat the file as a hint (a hard
    kill leaves it stale), health-check what they read, and keep the port scan as
    the fallback.
    """
    import json

    try:
        path = _server_record_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"url": url, "port": port, "pid": os.getpid()}
        # Write-then-rename: a reader polling every 500 ms must never catch a
        # half-written file and conclude LanEx isn't running.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(record) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:  # pragma: no cover - best-effort only
        pass


def _clear_server_record() -> None:
    """Remove the record on a clean shutdown (a stale one only costs a probe)."""
    try:
        _server_record_path().unlink()
    except Exception:  # pragma: no cover - best-effort only
        pass


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


def _install_tool_cli(key: str) -> int:
    """Install one supporting tool headlessly, streaming the installer's output.

    The EXACT code path the Tools tab's Install button runs (strategy chain,
    sudo escalation via terminal/pkexec/askpass, honest guidance on failure) —
    so ``lanex --install-tool gds3d`` from the install script behaves like the
    in-app click. Progress events normally ride the SSE bus; here we poll the
    same bus with a cursor and print them, so a terminal user sees the build.
    Returns 0 on success, 1 on failure, 2 when the environment can't load.
    """
    import threading

    try:
        from .controller import installer, tools
        from .controller.events import bus
    except Exception as ex:  # pragma: no cover - import/env dependent
        sys.stderr.write(f"cannot load the installer: {ex}\n")
        return 2

    known = {t["key"] for t in tools.EDA_TOOLS} | {"gds3d", "docker", "podman"}
    if key not in known:
        sys.stderr.write(f"unknown tool '{key}'. Installable tools: "
                         + ", ".join(sorted(known)) + "\n")
        return 2

    cursor = bus.max_seq
    result: dict = {}

    def _worker() -> None:
        try:
            result.update(installer.install_tool(key) or {})
        except Exception as ex:  # pragma: no cover - strategy/env dependent
            result.update({"ok": False, "reason": str(ex)})

    t = threading.Thread(target=_worker, daemon=True)
    sys.stdout.write(f"Installing {key}…\n")
    sys.stdout.flush()
    t.start()

    def _drain() -> None:
        nonlocal cursor
        for evt in bus.events_since(cursor):
            cursor = max(cursor, int(evt.get("seq") or cursor))
            if not str(evt.get("type") or "").startswith("installer"):
                continue
            line = evt.get("line") or evt.get("message") or ""
            if line:
                sys.stdout.write(str(line).rstrip() + "\n")
                sys.stdout.flush()

    try:
        while t.is_alive():
            _drain()
            t.join(0.25)
        _drain()
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        try:
            installer.cancel_install(key)
        except Exception:
            pass
        sys.stderr.write("\ninstall cancelled\n")
        return 130

    if result.get("ok"):
        method = result.get("method") or result.get("label") or "installed"
        sys.stdout.write(f"\n{key} installed ({method}).\n")
        return 0
    reason = result.get("guidance") or result.get("reason") or "no install method succeeded"
    sys.stderr.write(f"\n{key} install failed: {reason}\n"
                     f"You can retry any time from the cockpit: Tools tab → "
                     f"{key} → Install.\n")
    return 1


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
