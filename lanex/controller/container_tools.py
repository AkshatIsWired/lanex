# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Launch an EDA tool **inside the LibreLane container** with a GUI.

The host's native tools are often the wrong version for a given PDK — e.g. a
system ``magic 8.3.105`` cannot read the sky130A techfile, which now requires
``8.3.411`` (the techfile bumps its ``version`` section), so it opens a black,
empty layout. The container image LibreLane ships carries the *exact* matched
tool versions, so running the GUI from the image renders correctly.

This module builds a ``<engine> run`` command that:

* forwards the host X11 display (``DISPLAY`` + ``/tmp/.X11-unix``) so the tool's
  window appears on the user's desktop,
* bind-mounts the design dir **and** the PDK root at their *same host paths*
  inside the container (so every file path on the command line is valid
  unchanged), and exports ``PDK_ROOT``/``PDK``/``PDKPATH`` for the tech files,
* runs the requested tool (``magic``/``klayout``/``openroad``/``netgen``).

Only works where the host has a usable X11 display reachable by containers:
Linux/X11, WSLg (Windows), or XQuartz (macOS, with ``xhost`` configured). On a
headless box or without a display it returns honest guidance instead of a dud
launch. Pure stdlib; reuses the engine/image helpers already in the controller.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Tools we can launch in the container + how each takes its input file.
#  magic     : -rcfile <pdk magicrc> <gds>      (PDK-matched tech → renders layers)
#  klayout   : -e <gds>  (edit mode); PDK layer-props auto-found by name otherwise
#  openroad  : -gui      (interactive; user reads the run's .odb)
#  netgen    : -batch (no gui) — offered for LVS console, launched as interactive tcl
_CONTAINER_TOOLS = {
    "magic": {"label": "Magic", "kind": "layout", "needs_display": True},
    "klayout": {"label": "KLayout", "kind": "layout", "needs_display": True},
    "openroad": {"label": "OpenROAD GUI", "kind": "pnr", "needs_display": True},
    "netgen": {"label": "Netgen", "kind": "lvs", "needs_display": True},
}


def container_tools() -> List[Dict[str, Any]]:
    """Static catalog of tools that can be launched in the container (UI listing)."""
    return [
        {"key": k, "label": v["label"], "kind": v["kind"]}
        for k, v in _CONTAINER_TOOLS.items()
    ]


def _image_present(engine: str, image: str, *, sg_wrap: bool = False) -> bool:
    """Is *image* already in the engine's local store? Best-effort: on a probe
    error (timeout, odd engine) assume present rather than block the launch."""
    try:
        from . import tools as tools_mod

        argv = [engine, "image", "inspect", image, "--format", "{{.Id}}"]
        if sg_wrap:
            argv = tools_mod.sg_wrap_argv(argv)
        rc, _out, _err = tools_mod._shell_exec(argv, timeout=8.0)
        return rc == 0
    except Exception:
        return True


XQUARTZ_APP = "/Applications/Utilities/XQuartz.app"
XQUARTZ_INSTALL_CMD = "brew install --cask xquartz"
XQUARTZ_TCP_PREF_CMD = "defaults write org.xquartz.X11 nolisten_tcp -bool false"
# Display :0 over TCP: what containers reach as host.docker.internal:0.
_XQUARTZ_TCP = ("127.0.0.1", 6000)


def _xquartz_installed() -> bool:
    return Path("/opt/X11/bin/Xquartz").exists() or Path(XQUARTZ_APP).exists()


def _xquartz_running() -> bool:
    """Is the XQuartz server process alive?

    Asked of the process table first: a crashed XQuartz leaves its socket in
    /tmp/.X11-unix behind, and a stale socket must not read as "running" (the
    restart path would then wait forever for it to quit). The socket is the
    fallback only when pgrep itself cannot be run."""
    answered = False
    for argv in (["/usr/bin/pgrep", "-xq", "Xquartz"], ["/usr/bin/pgrep", "-fq", "X11.bin"]):
        try:
            rc = subprocess.run(argv, capture_output=True, timeout=5).returncode
        except Exception:
            continue
        if rc == 0:
            return True
        if rc == 1:   # pgrep ran and found nothing
            answered = True
    if answered:
        return False
    try:
        sock_dir = Path("/tmp/.X11-unix")
        return sock_dir.is_dir() and any(sock_dir.iterdir())
    except Exception:
        return False


def _xquartz_tcp_listening(timeout: float = 1.0) -> bool:
    """True when an X server accepts TCP connections on display :0."""
    import socket

    try:
        with socket.create_connection(_XQUARTZ_TCP, timeout=timeout):
            return True
    except OSError:
        return False


def _xquartz_tcp_pref() -> Optional[bool]:
    """The ``nolisten_tcp`` preference read as "allows TCP": True/False, or None
    when it was never written (XQuartz then refuses TCP)."""
    for domain in ("org.xquartz.X11", "org.macosforge.xquartz.X11"):
        try:
            r = subprocess.run(["defaults", "read", domain, "nolisten_tcp"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                return (r.stdout or "").strip() in ("0", "false", "NO")
        except Exception:
            continue
    return None


def write_xquartz_tcp_pref() -> bool:
    """Let XQuartz accept TCP clients from its next start. Idempotent."""
    if sys.platform != "darwin":
        return False
    if _xquartz_tcp_pref() is True:
        return True
    try:
        return subprocess.run(XQUARTZ_TCP_PREF_CMD.split(), capture_output=True,
                              timeout=10).returncode == 0
    except Exception:
        return False


def _brew_available() -> bool:
    try:
        from . import installer

        return bool(installer._brew_path())
    except Exception:
        return False


def _xquartz_status() -> Dict[str, Any]:
    """XQuartz on macOS: ``{installed, running, tcp_ok, tcp_pref, brew}``.

    ``tcp_ok`` is measured, not inferred from the preference: while XQuartz
    runs, whether it accepts a TCP connection on 127.0.0.1:6000 (what containers
    use through ``host.docker.internal:0``). ``None`` while it is not running.
    Never raises."""
    installed = _xquartz_installed()
    running = _xquartz_running() if installed else False
    tcp_ok: Optional[bool] = _xquartz_tcp_listening() if running else None
    return {"installed": installed, "running": running, "tcp_ok": tcp_ok,
            "tcp_pref": _xquartz_tcp_pref() if installed else None,
            "brew": _brew_available()}


def _xquartz_install_verdict(brew: bool) -> Dict[str, Any]:
    if brew:
        reason = ("Viewers from the container need XQuartz, which is not installed. "
                  "Install it here (macOS asks for your password in its own dialog), "
                  f"or in Terminal with:  {XQUARTZ_INSTALL_CMD}")
    else:
        reason = ("Viewers from the container need XQuartz, which is not installed. "
                  "Download it from https://www.xquartz.org, install it, then try again. "
                  "The Layout tab works without it.")
    return {"ok": False, "reason": reason, "action": "install-xquartz",
            "can_install": bool(brew), "command": XQUARTZ_INSTALL_CMD}


def _darwin_display_status(xq: Dict[str, Any]) -> Dict[str, Any]:
    """Compose the macOS ``{ok, reason, action?}`` verdict from an XQuartz status.

    Pure so tests can drive every branch. An installed XQuartz that is not
    running counts as launchable: :func:`ensure_xquartz` starts it. The server's
    own ``$DISPLAY`` is deliberately not a prerequisite; container launches use
    ``host.docker.internal:0`` over TCP."""
    if not xq.get("installed"):
        return _xquartz_install_verdict(bool(xq.get("brew")))
    if not xq.get("running"):
        return {"ok": True, "reason": "XQuartz is installed; LanEx starts it when a viewer opens."}
    if xq.get("tcp_ok") is False:
        return {"ok": False, "action": "restart-xquartz", "reason":
                "XQuartz is running but does not accept connections from the container. "
                "Restarting XQuartz fixes it, and closes the XQuartz windows open now. "
                "(The setting is XQuartz > Settings > Security > Allow connections "
                "from network clients.)"}
    return {"ok": True, "reason":
            "XQuartz is ready. LanEx runs xhost +localhost before each launch."}


def _wait(cond: Any, seconds: float, step: float = 0.25) -> bool:
    import time

    deadline = time.monotonic() + seconds
    while True:
        if cond():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(step)


def ensure_xquartz(*, restart: bool = False, wait_s: float = 25.0) -> Dict[str, Any]:
    """Make XQuartz ready for a container viewer on macOS.

    Writes the TCP preference, starts XQuartz when it is not running and waits
    for it to accept TCP. A running XQuartz that refuses TCP needs a restart,
    which closes the user's X11 windows, so that happens only with *restart*;
    otherwise the result carries ``action: "restart-xquartz"`` for the UI to
    offer. Returns ``{ok, started?, restarted?}`` or ``{ok: False, need, error,
    action?}``. No-op off macOS. Never raises."""
    if sys.platform != "darwin":
        return {"ok": True}
    try:
        if not _xquartz_installed():
            v = _xquartz_install_verdict(_brew_available())
            return {"ok": False, "need": "display", "error": v["reason"],
                    "action": v["action"], "can_install": v["can_install"],
                    "command": v["command"]}
        write_xquartz_tcp_pref()
        restarted = False
        if _xquartz_running():
            if _xquartz_tcp_listening():
                return {"ok": True}
            if not restart:
                v = _darwin_display_status({"installed": True, "running": True, "tcp_ok": False})
                return {"ok": False, "need": "display", "error": v["reason"],
                        "action": "restart-xquartz"}
            subprocess.run(["/usr/bin/osascript", "-e", 'quit app "XQuartz"'],
                           capture_output=True, timeout=15)
            if not _wait(lambda: not _xquartz_running(), 15.0):
                return {"ok": False, "need": "display", "error":
                        "XQuartz did not quit. Quit it yourself (XQuartz > Quit X11), "
                        "then open the viewer again."}
            restarted = True
        subprocess.run(["/usr/bin/open", "-a", "XQuartz"], capture_output=True, timeout=15)
        if not _wait(_xquartz_tcp_listening, wait_s):
            return {"ok": False, "need": "display", "error":
                    f"XQuartz did not start accepting connections within {int(wait_s)} seconds. "
                    "Open XQuartz yourself, turn on XQuartz > Settings > Security > Allow "
                    "connections from network clients, quit and reopen XQuartz, then "
                    "open the viewer again."}
        return {"ok": True, "started": True, "restarted": restarted}
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "need": "display",
                "error": f"Could not start XQuartz ({ex}). Open it yourself with:  open -a XQuartz"}


def _darwin_allow_x11_clients(env: Dict[str, str]) -> None:
    """Best-effort ``xhost +localhost``/``+127.0.0.1`` before a container launch.

    This is the one manual XQuartz step everyone forgets; running it here (with
    XQuartz's own xhost, against the local display) removes it. Silent no-op on
    any failure — the launch hint still tells the user the manual command."""
    xhost = "/opt/X11/bin/xhost"
    if not Path(xhost).exists():
        return
    xenv = dict(env)
    xenv.setdefault("DISPLAY", ":0")
    for host in ("+localhost", "+127.0.0.1"):
        try:
            subprocess.run([xhost, host], env=xenv, capture_output=True, timeout=5)
        except Exception:
            return


def display_available() -> Dict[str, Any]:
    """Best-effort check that a GUI launched in a container could reach a display.

    Returns ``{ok, reason}``. We don't try to *prove* the X server accepts the
    connection (that needs ``xhost``); we check the prerequisites are present so
    the UI can warn early and give the right per-platform fix."""
    plat = sys.platform
    disp = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
    if plat.startswith("linux"):
        if not disp:
            return {"ok": False, "reason": "no DISPLAY set — are you on a headless server? "
                    "Container GUIs need an X11 display (or WSLg). Use the built-in "
                    "layout preview instead, or run on a desktop session."}
        if not Path("/tmp/.X11-unix").exists():
            return {"ok": False, "reason": "X11 socket /tmp/.X11-unix not found. If you're on "
                    "Wayland, run the GUI under XWayland, or install an X server."}
        return {"ok": True, "reason": "X11 display detected."}
    if plat == "darwin":
        return _darwin_display_status(_xquartz_status())
    if plat.startswith("win"):
        return {"ok": bool(disp), "reason": "On Windows use WSL2 with WSLg (Win 11) — DISPLAY "
                "is provided automatically. Run the GUI from inside WSL." if not disp else
                "WSLg display detected."}
    return {"ok": bool(disp), "reason": "unknown platform; DISPLAY " + ("set" if disp else "missing")}


def _x11_flags(engine: str = "docker") -> List[str]:
    """Container flags to forward the host display, cross-platform best-effort.

    *engine* matters only on macOS: the in-container alias for the host is
    ``host.docker.internal`` under Docker Desktop but ``host.containers.internal``
    under a podman machine (older podman doesn't define the docker spelling)."""
    from . import platform_env

    flags: List[str] = []
    # The container has no GPU passthrough (we never pass --gpus), so a hardware
    # GLX context can't be created — that's the `qglx_findConfig: Failed to find
    # matching FBConfig` spam and the OpenROAD/KLayout viewport/chart glitches.
    # Force Mesa's software renderer so the GUI (layout view, timing charts, the
    # hierarchy browser) renders reliably over X forwarding / WSLg / VNC.
    # Escape hatch (same as the native launch path): LIBRELANE_GUI_WSL_HW_GL=1 /
    # LANEX_HW_GL=1 skips the forcing for setups that DO have in-container GL
    # (e.g. a user who runs the engine with GPU passthrough themselves).
    # QT_XCB_GL_INTEGRATION=none as on the native path (platform_env.wsl_gl_env):
    # Qt then skips its GLX probe instead of mapping a window it can't present.
    if not platform_env.hw_gl_requested():
        flags += ["-e", "LIBGL_ALWAYS_SOFTWARE=1", "-e", "GALLIUM_DRIVER=llvmpipe",
                  "-e", "QT_XCB_GL_INTEGRATION=none"]
    # Only an X11 display is ever forwarded into the container, so say so:
    # a Qt/GTK build that defaults to Wayland would otherwise probe for a
    # compositor that is not there (on WSL, the [WARN: COPY MODE] class).
    flags += ["-e", "QT_QPA_PLATFORM=xcb", "-e", "GDK_BACKEND=x11"]
    # HiDPI: a container starts with none of the host's environment, so hand it
    # the scale the viewer needs. That is the host desktop's own setting where
    # one is exported (GNOME/KDE), or on WSL the measured Windows display scale
    # (WSLg otherwise shows the GUI at half size on a 4K / 175 % laptop).
    host_scale = {k: os.environ[k] for k in platform_env.VIEWER_SCALE_VARS if os.environ.get(k)}
    for key, val in platform_env.viewer_scale_env(host_scale).items():
        flags += ["-e", f"{key}={val}"]
    disp = os.environ.get("DISPLAY")
    if sys.platform.startswith("linux"):
        if disp:
            flags += ["-e", f"DISPLAY={disp}"]
        # Host networking lets `localhost:N`/`:N` displays resolve; Linux-only.
        flags += ["--net=host"]
        if Path("/tmp/.X11-unix").exists():
            flags += ["-v", "/tmp/.X11-unix:/tmp/.X11-unix"]
        xauth = os.environ.get("XAUTHORITY")
        if xauth and Path(xauth).is_file():
            flags += ["-e", f"XAUTHORITY={xauth}", "-v", f"{xauth}:{xauth}"]
    elif sys.platform == "darwin":
        # XQuartz listens on TCP; containers reach it via the host gateway.
        host_alias = ("host.containers.internal" if (engine or "").startswith("podman")
                      else "host.docker.internal")
        flags += ["-e", f"DISPLAY={host_alias}:0"]
    elif sys.platform.startswith("win"):
        if disp:
            flags += ["-e", f"DISPLAY={disp}"]
        if Path("/tmp/.X11-unix").exists():  # WSLg
            flags += ["-v", "/tmp/.X11-unix:/tmp/.X11-unix"]
    return flags


def _mount(host_path: Path) -> List[str]:
    """Bind-mount *host_path* at the SAME path inside the container so absolute
    file paths on the command line stay valid unchanged."""
    p = str(host_path)
    return ["-v", f"{p}:{p}"]


def _tool_command(tool: str, *, gds: Optional[Path], pdk: Optional[str],
                  pdk_root: Optional[str], odb: Optional[Path],
                  script: Optional[Path] = None,
                  marker_dbs: Optional[List[Path]] = None) -> List[str]:
    """The argv to run *inside* the container for *tool*. *script* is a generated
    startup .tcl (written by the caller into a mounted dir) used to load the run
    into OpenROAD / set Netgen up."""
    if tool == "magic":
        cmd = ["magic"]
        if script is not None:
            # Display-scaling startup file; it sources the PDK magicrc itself.
            cmd += ["-rcfile", str(script)]
        elif pdk and pdk_root:
            # Same guard the klayout branch below gained in round 50: only pass
            # -rcfile when the rc actually exists (family-level naming variance
            # + a nonexistent path would error Magic out), resolved through the
            # shared exact→family→glob lookup.
            from .desktop import find_magicrc
            magicrc = find_magicrc(Path(pdk_root) / pdk / "libs.tech", pdk)
            if magicrc is not None:
                cmd += ["-rcfile", str(magicrc)]
        if gds:
            cmd += [str(gds)]
        return cmd
    if tool == "klayout":
        cmd = ["klayout"]
        if pdk and pdk_root:
            # Only pass ``-l`` when the layer-properties file actually exists:
            # KLayout errors ``Unable to open file … (errno=2)`` on a missing one
            # (it does NOT ignore it), and the file's name/location varies by PDK
            # (gf180mcu ships gf180mcu.lyp, not gf180mcuC.lyp). find_klayout_lyp
            # resolves it or returns None → omit the flag and open with defaults.
            from .desktop import find_klayout_lyp
            lyp = find_klayout_lyp(Path(pdk_root) / pdk / "libs.tech", pdk)
            if lyp is not None:
                cmd += ["-l", str(lyp)]
        if gds:
            cmd += [str(gds)]
            # Load the run's DRC/XOR report databases into the marker browser
            # (-m binds to the layout given just before it). The paths live in
            # the run dir, which is mounted, so they resolve in-container.
            for db in marker_dbs or []:
                cmd += ["-m", str(db)]
        return cmd
    if tool == "openroad":
        # Open the GUI with the run's database already loaded. `read_db` restores
        # the full OpenDB (tech + libs + placement + routing) from the run's .odb,
        # so the layout shows instead of an empty canvas (issue #9). The startup
        # script is generated by the caller; without an odb we still open the GUI.
        if script is not None:
            return ["openroad", "-gui", str(script)]
        return ["openroad", "-gui"]
    if tool == "netgen":
        # Interactive Netgen console (Tk). `-batch` ran no GUI and exited with no
        # script, so the window never appeared (issue #10). Pass a startup script
        # that sources the PDK's netgen setup (so LVS commands work) and stays
        # interactive; fall back to a bare interactive console. netgen.tcl runs
        # its arguments with `eval $argv`, so a bare path was evaluated as a
        # command name and silently failed; `source <path>` actually runs it.
        if script is not None:
            return ["netgen", "source", str(script)]
        return ["netgen"]
    return [tool]


def build_argv(
    engine: str,
    image: str,
    tool: str,
    *,
    design_dir: Path,
    work_dir: Path,
    gds: Optional[Path] = None,
    odb: Optional[Path] = None,
    pdk: Optional[str] = None,
    pdk_root: Optional[str] = None,
    script: Optional[Path] = None,
    marker_dbs: Optional[List[Path]] = None,
) -> List[str]:
    """Assemble the full ``<engine> run --rm … <image> <tool> …`` command."""
    argv: List[str] = [engine, "run", "--rm", "-i"]
    argv += _x11_flags(engine)
    # Mount the design dir (covers the run + its GDS/odb) at its own path.
    argv += _mount(design_dir)
    # Mount + export the PDK so tech files resolve inside the container. Mount
    # whenever a root is given (the caller resolves it from the run's
    # resolved.json, so it exists) — otherwise the -rcfile path we reference
    # below wouldn't be visible in the container.
    if pdk_root:
        argv += _mount(Path(pdk_root))
        argv += ["-e", f"PDK_ROOT={pdk_root}"]
        if pdk:
            argv += ["-e", f"PDK={pdk}", "-e", f"PDKPATH={Path(pdk_root) / pdk}"]
    argv += ["-w", str(work_dir)]
    argv += [image]
    argv += _tool_command(tool, gds=gds, pdk=pdk, pdk_root=pdk_root, odb=odb, script=script,
                          marker_dbs=marker_dbs)
    return argv


def _netgen_setup_file(pdk: Optional[str], pdk_root: Optional[str]) -> Optional[Path]:
    """The PDK's Netgen LVS setup tcl, if present (``<root>/<pdk>/libs.tech/
    netgen/<pdk>_setup.tcl``). Sourcing it makes ``lvs`` work out of the box."""
    if not (pdk and pdk_root):
        return None
    cand = Path(pdk_root) / pdk / "libs.tech" / "netgen" / f"{pdk}_setup.tcl"
    return cand if cand.is_file() else None


def _tcl_word(s: str) -> str:
    """A safe Tcl word: bare if it's a plain identifier, else brace-quoted."""
    import re as _re
    s = str(s or "")
    return s if _re.fullmatch(r"[A-Za-z0-9_.:-]+", s) else "{" + s.replace("}", "") + "}"


def _read_run_config(run_dir: Path) -> Dict[str, Any]:
    """The run's resolved config (``resolved.json``, else ``config.json``)."""
    import json
    for name in ("resolved.json", "config.json"):
        f = run_dir / name
        if f.is_file():
            try:
                return json.loads(f.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
    return {}


def _corner_libs(cfg: Dict[str, Any], corner: Optional[str]) -> List[str]:
    """Liberty files for *corner* from the resolved ``LIB`` mapping.

    ``LIB`` is ``{"*_tt_025C_1v80": [paths], …}`` (keys are corner globs); pick the
    set whose glob matches *corner*. Falls back to every lib in the mapping (or a
    flat list) so timing still has data even if the corner name doesn't match."""
    import fnmatch
    lib = cfg.get("LIB")
    out: List[str] = []
    if isinstance(lib, dict):
        if corner:
            for key, vals in lib.items():
                if fnmatch.fnmatch(corner, key):
                    out = list(vals) if isinstance(vals, (list, tuple)) else [vals]
                    break
        if not out:  # no corner match → union of everything (de-duped, order-stable)
            seen = set()
            for vals in lib.values():
                for v in (vals if isinstance(vals, (list, tuple)) else [vals]):
                    if v not in seen:
                        seen.add(v)
                        out.append(v)
    elif isinstance(lib, (list, tuple)):
        out = list(lib)
    elif isinstance(lib, str):
        out = [lib]
    return [p for p in out if p and Path(p).is_file()]


def _openroad_timing_files(run_dir: Path, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the files the OpenROAD GUI needs for a fully-timed session: the
    corner liberty (.lib), the signoff SDC, and the matching SPEF. All live in
    the run dir / PDK, both mounted into the container. Missing pieces are simply
    omitted (the layout still loads; timing degrades gracefully)."""
    corner = cfg.get("DEFAULT_CORNER")
    final = run_dir / "final"
    libs = _corner_libs(cfg, corner)

    sdc: Optional[Path] = None
    for cand_dir in (final / "sdc", run_dir):
        if cand_dir.is_dir():
            hits = sorted(cand_dir.glob("*.sdc"))
            if hits:
                sdc = hits[0]
                break

    # SPEF for the corner's process token (nom/min/max), else any.
    spef: Optional[Path] = None
    spef_root = final / "spef"
    if spef_root.is_dir():
        proc = (corner.split("_")[0] if corner else "") or "nom"
        for sub in (spef_root / proc, spef_root):
            if sub.is_dir():
                hits = sorted(sub.glob("*.spef"))
                if hits:
                    spef = hits[0]
                    break
        if spef is None:
            hits = sorted(spef_root.rglob("*.spef"))
            spef = hits[0] if hits else None
    return {"libs": libs, "sdc": sdc, "spef": spef, "corner": corner}


def _write_startup_script(tool: str, work_dir: Path, *, odb: Optional[Path],
                          pdk: Optional[str], pdk_root: Optional[str]) -> Optional[Path]:
    """Write a per-tool startup .tcl into *work_dir* (a mounted dir, so the path
    is valid inside the container). Returns the path, or None when no script is
    needed / it can't be written. Best-effort — never raises."""
    try:
        from . import platform_env
        if tool == "magic":
            # Magic's Tk UI has no scale environment variable; on a HiDPI
            # display it starts through a script that enlarges its fonts and
            # then sources the PDK magicrc. No scaling needed = no script.
            from .desktop import find_magicrc, magic_scaled_rcfile
            magicrc = (find_magicrc(Path(pdk_root) / pdk / "libs.tech", pdk)
                       if pdk and pdk_root else None)
            sp = magic_scaled_rcfile(str(magicrc) if magicrc else None,
                                     platform_env.viewer_scale(), work_dir)
            return Path(sp) if sp else None
        if tool == "openroad":
            if odb is None:
                return None
            sp = work_dir / ".gui_openroad.tcl"
            cfg = _read_run_config(work_dir)
            tf = _openroad_timing_files(work_dir, cfg)
            # Mirror LibreLane's own OpenROAD GUI launcher
            # (librelane/scripts/openroad/gui.tcl) so the GUI's Timing Report,
            # Clock Tree Viewer, and setup/hold slack all work — not just a static
            # render. The exact sequence matters:
            #   read_db → define_corners <corner> → read_liberty -corner <corner>
            #   <lib>… → read_sdc → read_spef -corner <corner> <spef>
            # The previous version had no `define_corners` and no `-corner` flag,
            # so the GUI's per-corner timing query found no libraries (STA-2141).
            # Every step is wrapped in catch so one missing file can't abort the
            # GUI; the console prints what loaded.
            corner = tf.get("corner") or "default"
            lines = ["# Auto-generated by the LanEx — mirrors librelane gui.tcl (view + timing).\n"]

            def _try(cmd: str, ok_msg: str, fail_msg: str) -> None:
                lines.append(
                    f"if {{[catch {{{cmd}}} err]}} {{\n"
                    f"  puts \"LanEx: {fail_msg}: $err\"\n"
                    f"}} else {{ puts \"LanEx: {ok_msg}\" }}\n"
                )

            _try(f"read_db {{{odb}}}", "layout + design loaded", "could not read_db")
            if tf["libs"]:
                # define_corners MUST precede read_liberty -corner.
                _try(f"define_corners {_tcl_word(corner)}", f"corner '{corner}' defined", "define_corners failed")
                for lib in tf["libs"]:
                    _try(f"read_liberty -corner {_tcl_word(corner)} {{{lib}}}",
                         f"liberty loaded ({Path(lib).name})", "read_liberty failed")
            if tf["sdc"] is not None:
                _try(f"read_sdc {{{tf['sdc']}}}", f"constraints loaded ({tf['sdc'].name})", "read_sdc failed")
            # The run's SPEF is extracted from the FINAL layout; on an earlier
            # stage's database (Layout tab: "open this stage") its nets and
            # instances don't match, so timing there stays on estimates.
            try:
                final_db = odb.resolve().relative_to(work_dir.resolve()).parts[:1] == ("final",)
            except ValueError:
                final_db = False
            if tf["spef"] is not None and tf["libs"] and final_db:
                _try(f"read_spef -corner {_tcl_word(corner)} {{{tf['spef']}}}",
                     f"parasitics loaded ({tf['spef'].name})", "read_spef failed")
            elif tf["spef"] is not None and tf["libs"]:
                lines.append("puts \"LanEx: this is a stage before extraction, so timing uses wire estimates "
                             "(the run's SPEF belongs to the final layout)\"\n")
            # ---- DRC / marker inventory ------------------------------------
            # Modern OpenROAD stores DRC results as marker categories INSIDE the
            # OpenDB (the old gui::load_drc tcl command no longer exists — the
            # DRC Viewer's file loading is menu-only). DetailedRouting writes a
            # "DRC" category into the .odb, so after read_db the viewer already
            # has the data. What was missing is the EXPLANATION: a clean run has
            # zero markers and the viewer looks "broken empty". Enumerate the
            # categories, say clean-vs-violations out loud, and when there ARE
            # violations pop the viewer open on the offending category.
            lines.append(
                "if {[catch {\n"
                "  set _lx_total 0\n"
                "  set _lx_cats {}\n"
                "  set _lx_sel {}\n"
                "  foreach _lx_c [[ord::get_db_block] getMarkerCategories] {\n"
                "    set _lx_n [$_lx_c getMarkerCount]\n"
                "    incr _lx_total $_lx_n\n"
                "    lappend _lx_cats \"[$_lx_c getName]=$_lx_n\"\n"
                "    if {$_lx_n > 0 && $_lx_sel eq {}} { set _lx_sel [$_lx_c getName] }\n"
                "  }\n"
                "  if {[llength $_lx_cats] == 0} {\n"
                "    puts \"LanEx: no DRC/marker data stored in this database — the DRC Viewer starts empty (Tools > DRC Viewer > Load can open a report file).\"\n"
                "  } elseif {$_lx_total == 0} {\n"
                "    puts \"LanEx: DRC markers: [join $_lx_cats {, }] — zero violations; an EMPTY DRC Viewer is the correct result for this run.\"\n"
                "  } else {\n"
                "    puts \"LanEx: DRC markers: [join $_lx_cats {, }] — opening the DRC Viewer.\"\n"
                "    catch {gui::show_widget drc_viewer}\n"
                "    catch {gui::select_marker_category $_lx_sel}\n"
                "  }\n"
                "} _lx_err]} { puts \"LanEx: marker inventory failed: $_lx_err\" }\n"
            )
            # Point at the on-disk DRT report too (the DRC Viewer's Load button
            # accepts it), with its violation count so empty-vs-broken is never
            # ambiguous.
            try:
                from .desktop import find_run_reports
                rep = find_run_reports(work_dir)
            except Exception:
                rep = {}
            if rep.get("drt_drc"):
                v = rep.get("drt_violations")
                vtxt = f"{v} violation(s)" if v is not None else "count unknown"
                lines.append(
                    "puts {LanEx: DetailedRouting DRC report on disk: "
                    f"{rep['drt_drc']} ({vtxt}) — DRC Viewer > Load opens it; "
                    "Magic/KLayout DRC results live in the Verify tab.}\n"
                )
            # A friendly hint in the OpenROAD console on what's now possible.
            ready = bool(tf["libs"] and tf["sdc"] is not None)
            lines.append(
                "puts \"LanEx: " + (
                    "timing ready — open Tools ▸ Timing Report / Clock Tree Viewer, "
                    "or run report_checks / report_clock_skew in this console.\""
                    if ready else
                    "layout loaded (timing data incomplete for this run — liberty/SDC not found).\""
                ) + "\n"
            )
            sp.write_text("".join(lines), encoding="utf-8")
            return sp
        if tool == "netgen":
            setup = _netgen_setup_file(pdk, pdk_root)
            sp = work_dir / ".gui_netgen.tcl"
            lines = ["# Auto-generated by the LanEx — interactive Netgen.\n",
                     platform_env.tk_scale_tcl(platform_env.viewer_scale())]
            # The PDK setup file is lvs's third argument, not a script to
            # source at startup (it reads the circuits lvs has just loaded and
            # errors "No circuit has been declared" on its own). Keep its path
            # in $setup so the printed command works as typed.
            if setup is not None:
                lines.append(f"set setup {{{setup}}}\n")
                lines.append("puts \"LanEx: PDK LVS setup is in \\$setup: $setup\"\n")
            lines.append(
                "puts \"LanEx: run LVS with  lvs "
                "{<layout.spice> <top>} {<schematic.v> <top>} "
                + ("\\$setup " if setup is not None else "<pdk>_setup.tcl ")
                + "comp.out\"\n"
            )
            sp.write_text("".join(lines), encoding="utf-8")
            return sp
    except Exception:
        return None
    return None


def open_in_container_tool(
    tool: str,
    *,
    design_dir: str | Path,
    work_dir: str | Path,
    gds: Optional[str | Path] = None,
    odb: Optional[str | Path] = None,
    pdk: Optional[str] = None,
    pdk_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Launch *tool* inside the LibreLane container as a detached process.

    Returns ``{ok, tool, argv}`` or ``{ok: False, error/need}``. Never raises."""
    spec = _CONTAINER_TOOLS.get(tool)
    if spec is None:
        return {"ok": False, "error": f"unknown container tool '{tool}'"}
    try:
        from . import tools as tools_mod
        from .container_run import image_ref

        resolved = tools_mod.resolve_engine()
        if not resolved.get("ready"):
            return {"ok": False, "need": "engine",
                    "error": "No usable Docker/Podman engine. Install one in Tools, "
                             "then retry — container tools need it."}
        engine = resolved.get("engine") or "docker"
        image = image_ref()
        if not _image_present(engine, image, sg_wrap=bool(resolved.get("sg_wrap"))):
            # Without this guard `docker run` would silently pull the multi-GB
            # image in the background (stdout is detached) — the launch looks
            # like a no-op for minutes. Route the user to the visible pull.
            return {"ok": False, "need": "image",
                    "error": f"The LibreLane image ({image}) isn't pulled yet. "
                             "Open Tools and click ‘Pull image’ first — the download "
                             "streams there with progress."}
    except Exception as ex:  # pragma: no cover - import/env dependent
        return {"ok": False, "error": f"could not resolve container engine: {ex}"}

    if spec.get("needs_display"):
        if sys.platform == "darwin":
            # Starts XQuartz when it is installed but not running.
            ready = ensure_xquartz()
            if not ready.get("ok"):
                return ready
        else:
            disp = display_available()
            if not disp.get("ok"):
                return {"ok": False, "need": "display", "error": disp.get("reason", "no display")}

    design_dir = Path(design_dir).resolve()
    work_dir = Path(work_dir).resolve()
    gds_p = Path(gds).resolve() if gds else None
    odb_p = Path(odb).resolve() if odb else None
    # KLayout: attach the run's DRC/XOR marker databases (same gating as the
    # host launch — only when the GDS belongs to this run, since the markers
    # name the run's top cell).
    marker_dbs: List[Path] = []
    if tool == "klayout" and gds_p is not None:
        try:
            if gds_p.is_relative_to(work_dir):
                from .desktop import find_run_reports
                marker_dbs = find_run_reports(work_dir).get("marker_dbs") or []
        except Exception:
            marker_dbs = []
    # Generate the tool's startup script (loads the .odb into OpenROAD; sets up
    # Netgen) into the mounted run dir so the GUI opens with the run loaded.
    script_p = _write_startup_script(tool, work_dir, odb=odb_p, pdk=pdk, pdk_root=pdk_root)
    argv = build_argv(
        engine, image, tool,
        design_dir=design_dir, work_dir=work_dir,
        gds=gds_p, odb=odb_p, pdk=pdk, pdk_root=pdk_root, script=script_p,
        marker_dbs=marker_dbs,
    )
    run_env = os.environ.copy()
    try:
        from . import tools as tools_mod

        resolved = tools_mod.resolve_engine()
        run_env.update(resolved.get("env") or {})
        if resolved.get("sg_wrap"):
            argv = tools_mod.sg_wrap_argv(argv)
    except Exception:
        pass
    if sys.platform == "darwin":
        _darwin_allow_x11_clients(run_env)
    try:
        kwargs: Dict[str, Any] = {
            "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
            "cwd": str(design_dir), "env": run_env,
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(argv, **kwargs)  # noqa: S603 - whitelisted tool/engine only
        from . import activity
        activity.track_viewer(proc, spec["label"])
        hint = None
        if tool == "openroad":
            hint = (f"OpenROAD GUI opening with the run loaded ({odb_p.name}). The console "
                    "explains the DRC Viewer's contents (an empty viewer on a clean run is "
                    "correct); qglx/GL warnings there are harmless."
                    if odb_p else
                    "OpenROAD GUI opened, but this run has no final .odb to load "
                    "(it may not have reached routing). Use File ▸ Open in the GUI.")
        elif tool == "netgen":
            hint = ("Netgen console opening. The PDK LVS setup file is in $setup; run "
                    "`lvs` with the run's layout + schematic netlists and $setup.")
        elif tool == "klayout" and marker_dbs:
            hint = (f"{len(marker_dbs)} DRC/XOR marker database(s) loaded — open KLayout's "
                    "marker browser to step through violations.")
        out = {"ok": True, "tool": tool, "label": spec["label"], "argv": argv,
               "used_odb": bool(tool == "openroad" and odb_p), "hint": hint}
        if marker_dbs:
            out["marker_dbs"] = [str(p) for p in marker_dbs]
        return out
    except Exception as ex:  # pragma: no cover - platform dependent
        return {"ok": False, "error": str(ex)}
