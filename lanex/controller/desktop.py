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
"""Launch a desktop EDA tool on a run artifact ("Open in KLayout/Magic/GDS3D").

Real layout/3D viewing is done by the user's own desktop tools — KLayout (2D),
GDS3D (3D physical-layer render), Magic, OpenROAD GUI — not in the browser. This
opens the run's GDS in one of those, as a **detached host subprocess**. Like the
reveal-in-file-manager feature, it only makes sense when the browser and the
server run on the same machine (the normal localhost cockpit). Best-effort and
honest: if the tool isn't installed it says so. Pure stdlib; no new dependency.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Whitelisted tools: binary name + kind. The browser can only ask for these
# keys — never an arbitrary command. The actual argv is built per-tool by
# ``_build_argv`` so we can inject the PDK tech files (magicrc / layer props)
# that make the layer stack render correctly.
_TOOLS: Dict[str, Dict[str, Any]] = {
    "klayout": {"label": "KLayout", "kind": "2D", "bin": "klayout", "alts": []},
    # GDS3D's Makefile emits the binary as ``GDS3D`` (capital); some installs ship
    # it lowercase. Look for both — on case-sensitive Linux a single spelling
    # silently reports "not installed".
    "gds3d":   {"label": "GDS3D",   "kind": "3D", "bin": "gds3d", "alts": ["GDS3D"]},
    "magic":   {"label": "Magic",   "kind": "2D", "bin": "magic", "alts": []},
    # NOTE: OpenROAD's GUI loads an ODB via a script, not a GDS on argv, so we do
    # NOT offer an "open this GDS in OpenROAD" launch — it would just open an
    # empty GUI. Use KLayout/Magic for layout, GDS3D for the 3D stack.
}


def _resolve_bin(spec: Dict[str, Any]) -> Optional[str]:
    """Return the path to a tool's binary, trying its name + known alternates.

    Uses ``resolve_user_bin``: ``usable_which`` first (so a Windows ``*.exe`` on
    the WSL ``/mnt/c`` PATH never shadows the real Linux viewer), then the user
    install dirs (``~/.local/bin`` etc.) so a tool a one-click install placed off
    ``$PATH`` — e.g. the GDS3D source build → ``~/.local/bin/gds3d`` — is still
    found and reported installed."""
    from . import platform_env
    return platform_env.resolve_user_bin(spec["bin"], spec.get("alts", []))


def available_tools() -> List[Dict[str, Any]]:
    """Which desktop viewers are installed on this host (for the UI to show)."""
    out: List[Dict[str, Any]] = []
    for key, spec in _TOOLS.items():
        out.append({
            "key": key, "label": spec["label"], "kind": spec["kind"],
            "available": bool(_resolve_bin(spec)),
        })
    return out


def _gds3d_techfile_dirs() -> List[Path]:
    """Directories that may hold GDS3D process/tech files (the ``-p`` argument)."""
    dirs: List[Path] = []
    from . import platform_env
    home = platform_env.home()
    dirs.append(home / "tools" / "GDS3D" / "techfiles")
    found = platform_env.resolve_user_bin("gds3d", ["GDS3D"])
    if found:
        bp = Path(found).resolve().parent
        dirs += [bp / "techfiles", bp.parent / "techfiles",
                 bp.parent / "share" / "gds3d" / "techfiles"]
    seen: set = set()
    out: List[Path] = []
    for d in dirs:
        if str(d) not in seen and d.is_dir():
            seen.add(str(d))
            out.append(d)
    return out


def gds3d_process_file(pdk: Optional[str]) -> Optional[str]:
    """Locate a GDS3D process/tech file matching *pdk*.

    GDS3D **requires** a process file (``-p``) describing the layer stack — a bare
    ``gds3d -i x.gds`` opens nothing. GDS3D ships example tech files (sky130.txt,
    sg13g2.txt, …) in its ``techfiles/`` dir; map the PDK to one. Returns None when
    none is found so the caller can give honest guidance instead of a dud launch."""
    if not pdk:
        return None
    p = pdk.lower()
    if p.startswith("sky130"):
        tokens = ["sky130"]
    elif p.startswith("gf180"):
        tokens = ["gf180"]
    elif "sg13g2" in p:
        tokens = ["sg13g2"]
    else:
        tokens = [p]
    for d in _gds3d_techfile_dirs():
        files = sorted(d.glob("*.txt"))
        for tok in tokens:
            cands = [f for f in files if tok in f.stem.lower()]
            # shortest stem wins → sky130.txt over sky130_s10.txt
            cands.sort(key=lambda f: len(f.stem))
            if cands:
                return str(cands[0])
    return None


def _pdk_tech_files(pdk: Optional[str], pdk_root: Optional[str]) -> Dict[str, Optional[str]]:
    """Locate the PDK tech files desktop viewers need to render layers correctly:
    Magic's ``<pdk>.magicrc`` and KLayout's layer-properties ``<pdk>.lyp``.

    Searches the run's resolved ``PDK_ROOT`` first, then every PDK root the GUI
    knows (ciel homes etc.), cross-platform via ``pathlib``. Returns a dict of
    str-paths (or None when not found) — callers degrade gracefully."""
    out: Dict[str, Optional[str]] = {"magicrc": None, "klayout_lyp": None, "root": None}
    if not pdk:
        return out
    roots: List[Path] = []
    if pdk_root:
        roots.append(Path(pdk_root).expanduser())
    try:
        from . import pdk as _pdk
        roots.extend(_pdk._candidate_pdk_roots())
    except Exception:
        pass
    seen: set = set()
    for root in roots:
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        base = root / pdk / "libs.tech"
        magicrc = base / "magic" / f"{pdk}.magicrc"
        if out["magicrc"] is None and magicrc.is_file():
            out["magicrc"] = str(magicrc)
            out["root"] = str(root)        # remember the root for PDK_ROOT env
        lyp = base / "klayout" / "tech" / f"{pdk}.lyp"
        if out["klayout_lyp"] is None and lyp.is_file():
            out["klayout_lyp"] = str(lyp)
            if out["root"] is None:
                out["root"] = str(root)
    return out


def _build_argv(tool: str, binary: str, f: str, tech: Dict[str, Optional[str]], use_tech: bool) -> List[str]:
    """Per-tool argv. When *use_tech* and the PDK tech files are found, inject them
    so layers render (a bare ``magic <gds>`` falls back to the 'minimum' tech and
    shows nothing). *use_tech* False = the tool's default view (lets the user pick
    e.g. KLayout's plain colours vs the PDK layer-properties). *binary* is the
    resolved executable (e.g. ``gds3d`` may actually be ``GDS3D``)."""
    if tool == "magic":
        if use_tech and tech.get("magicrc"):
            return [binary, "-rcfile", tech["magicrc"], f]
        return [binary, f]
    if tool == "klayout":
        # -l loads the PDK layer-properties so metals/vias get the right colours.
        if use_tech and tech.get("klayout_lyp"):
            return [binary, "-l", tech["klayout_lyp"], f]
        return [binary, f]
    if tool == "gds3d":
        # GDS3D REQUIRES a process file (-p) describing the layer stack; without it
        # it opens nothing. The caller resolves it into tech["gds3d_process"].
        proc = tech.get("gds3d_process")
        if proc:
            return [binary, "-p", proc, "-i", f]
        return [binary, "-i", f]   # last resort (will likely fail; caller warns)
    return [binary, f]


def open_in_tool(tool: str, file_path: str | Path, *,
                 pdk: Optional[str] = None, pdk_root: Optional[str] = None,
                 use_tech: bool = True) -> Dict[str, Any]:
    """Launch *tool* on *file_path* (already traversal-validated by the caller).

    *pdk*/*pdk_root* (from the run's resolved config) let us pass the PDK tech
    files so layers render — and the matching ``PDK_ROOT``/``PDK``/``PDKPATH`` env
    the magicrc references (without them Magic prints a tech error and quits).
    *use_tech* False launches the tool's default view. Returns ``{ok, tool, file}``
    or ``{ok: False, need?/error}``. Never raises; the process is detached."""
    spec = _TOOLS.get(tool)
    if spec is None:
        return {"ok": False, "error": f"unknown tool '{tool}'"}
    f = Path(file_path)
    if not f.is_file():
        return {"ok": False, "error": "file not found"}
    binary = _resolve_bin(spec)
    if not binary:
        bin_name = spec["bin"]
        return {"ok": False, "need": bin_name,
                "error": f"{spec['label']} ({bin_name}) isn't installed on this machine. "
                         f"Install it (Tools / Add-ons), then retry. This only works when the "
                         f"GUI runs on your own computer."}
    # A desktop tool needs a graphical session; on a headless box (SSH / server,
    # no $DISPLAY) it would flash-and-exit with no window and no error. Tell the
    # user honestly instead of pretending we launched something.
    try:
        from . import platform_env
        if not platform_env.host_display_available():
            return {"ok": False, "need": "display",
                    "error": f"No graphical display on this host, so {spec['label']} can't open a "
                             "window. Run the GUI on your own desktop, or use the container "
                             "(version-matched) launch with X11/WSLg forwarding."}
    except Exception:
        pass
    # GL viewers need Mesa's DRI drivers on the host. A fresh minimal WSL/Ubuntu
    # ships without libgl1-mesa-dri — then there is NO renderer (llvmpipe itself
    # is one of those drivers) and the tool hangs or opens a blank window with
    # no error. Detect it, auto-install through the usual escalation, and only
    # fail (honestly, with the exact commands) when we genuinely can't.
    if sys.platform.startswith("linux") and tool in ("gds3d", "klayout"):
        try:
            from . import installer, platform_env
            if platform_env.mesa_dri_present() is False:
                gres = installer.ensure_gl_runtime()
                if not gres.get("ok"):
                    return {"ok": False, "need": "gl-runtime",
                            "error": f"{spec['label']} can't render: the Mesa OpenGL drivers are "
                                     "missing on this system (fresh WSL/minimal installs ship "
                                     "without them) and they couldn't be installed automatically. "
                                     + (gres.get("error") or gres.get("manual")
                                        or installer.gl_runtime_guidance())}
        except Exception:
            pass
    tech = _pdk_tech_files(pdk, pdk_root)
    if tool == "gds3d":
        # GDS3D can't render without a process/tech file. Find one for the PDK; if
        # none exists, fail with honest guidance rather than launching a dud that
        # opens an empty window or exits immediately.
        proc = gds3d_process_file(pdk)
        if not proc:
            return {"ok": False, "need": "gds3d-techfile",
                    "error": "GDS3D needs a process/tech file (the layer stack) to render"
                             + (f" {pdk}" if pdk else "") + ", and none was found. GDS3D ships "
                             "example tech files in its techfiles/ folder — install GDS3D from "
                             "Tools (it builds those in), or drop a matching <pdk>.txt into "
                             "~/.lanex/tools/GDS3D/techfiles/, then retry."}
        tech["gds3d_process"] = proc
        # GDS3D segfaults the instant its window opens if the legacy X11
        # ``-misc-fixed-`` fonts are missing (it dereferences a NULL font). A
        # fresh WSL/Ubuntu ships none, and they can also be removed later. Rather
        # than make the user discover + run the apt command, auto-install them
        # here (same escalation as every other install: passwordless sudo, else a
        # one-time terminal/pkexec password). Only fall back to guidance if we
        # genuinely can't install them.
        try:
            from . import platform_env
            if platform_env.x11_fixed_fonts_present() is False:
                from . import installer
                fres = installer.ensure_x11_fixed_fonts()
                if not fres.get("ok"):
                    return {"ok": False, "need": "x11-fonts",
                            "error": "GDS3D needs the legacy X11 fonts to draw its menus, and they're "
                                     "missing — without them it crashes (segfault) the moment it opens. "
                                     "Tried to install them automatically but couldn't (needs a password "
                                     "in the terminal, or a non-apt system). Install them, then retry:\n"
                                     "    " + getattr(installer, "_GDS3D_FONT_CMD",
                                                      "sudo apt-get install -y xfonts-base")}
        except Exception:
            pass
    argv = _build_argv(tool, binary, str(f), tech, use_tech)
    # Magic's magicrc resolves $PDK_ROOT/$PDK/$PDKPATH; export them so it doesn't
    # error out with the 'minimum' tech and close immediately.
    launch_env = os.environ.copy()
    tech_root = tech.get("root") or pdk_root
    if pdk and tech_root and use_tech:
        launch_env["PDK_ROOT"] = tech_root
        launch_env["PDK"] = pdk
        launch_env["PDKPATH"] = str(Path(tech_root) / pdk)
    # Under WSL, force Mesa software GL (llvmpipe) so a stale WSLg vGPU ("copy
    # mode" after the host sleeps) can't deadlock the tool on window mapping —
    # GDS3D/KLayout/OpenROAD-GUI then render reliably without the GPU passthrough.
    # No-op off WSL; opt out with LIBRELANE_GUI_WSL_HW_GL=1.
    try:
        from . import platform_env
        launch_env = platform_env.wsl_gl_env(launch_env)
    except Exception:
        pass
    try:
        kwargs: Dict[str, Any] = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "cwd": str(f.parent),
            "env": launch_env,
        }
        if sys.platform != "win32":
            kwargs["start_new_session"] = True  # detach from the server process
        subprocess.Popen(argv, **kwargs)  # noqa: S603 - whitelisted tool only
        return {"ok": True, "tool": tool, "label": spec["label"], "file": str(f),
                "used_tech": bool((use_tech and (tech.get("magicrc") or tech.get("klayout_lyp")))
                                  or tech.get("gds3d_process"))}
    except Exception as ex:  # pragma: no cover - platform dependent
        return {"ok": False, "error": str(ex)}
