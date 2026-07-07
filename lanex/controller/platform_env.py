"""Cross-platform host-environment helpers (WSL, DNS, Windows-PATH binaries).

Pure stdlib, no new dependencies — part of the upstream-mergeable controller
"moat". These detect the few host quirks that surface as confusing GUI bugs on
Windows/WSL2 (the platform LibreLane supports via the WSL2 + container path):

  * WSL2 ships a broken auto-generated ``/etc/resolv.conf`` often enough that
    ``ciel fetch`` / image pulls time out resolving GitHub (DNS failure, not a
    LibreLane bug). We DETECT it and surface the exact remediation — we never
    rewrite the user's system files for them.
  * Under WSL, the Linux ``PATH`` includes the Windows ``PATH`` (``/mnt/c/...``),
    so a tool installed natively on Windows (e.g. ``verilator.exe``) is "found"
    but cannot actually be used by the Linux flow.

Everything degrades gracefully (returns ``False``/``None``) when a probe can't
run, so importing this module is always safe on every platform.
"""

from __future__ import annotations

import functools
import logging
import os
import shutil
import socket
import sys
from pathlib import Path
from typing import Dict, Optional

_log = logging.getLogger("librelane.lanex.platform_env")


def home() -> Path:
    """The LanEx config/state home directory (F1).

    Resolution order:
      1. ``$LANEX_HOME`` if set.
      2. ``$LIBRELANE_GUI_HOME`` if set — deprecated, honoured for one release
         (warn-logged) so an existing install isn't stranded.
      3. ``~/.lanex`` — the new default. If it doesn't exist yet but the old
         ``~/.librelane-gui`` does, the old dir is used (keeps known-designs.json,
         plugins, and the GDS3D tool tree working without a manual migration).
    """
    env_new = os.environ.get("LANEX_HOME")
    if env_new:
        return Path(env_new)
    env_old = os.environ.get("LIBRELANE_GUI_HOME")
    if env_old:
        _log.warning("LIBRELANE_GUI_HOME is deprecated — set LANEX_HOME instead")
        return Path(env_old)
    new_default = Path.home() / ".lanex"
    old_default = Path.home() / ".librelane-gui"
    if not new_default.exists() and old_default.exists():
        return old_default
    return new_default

# GitHub is what ciel/volare and the container registry resolve against, so it
# is the right host to test reachability for the PDK/image download paths.
_DNS_PROBE_HOST = "github.com"


@functools.lru_cache(maxsize=1)
def is_wsl() -> bool:
    """True when running inside Windows Subsystem for Linux (WSL1/WSL2)."""
    if not sys.platform.startswith("linux"):
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    for probe in ("/proc/sys/kernel/osrelease", "/proc/version"):
        try:
            with open(probe, "r", encoding="utf-8", errors="ignore") as fh:
                blob = fh.read().lower()
            if "microsoft" in blob or "wsl" in blob:
                return True
        except OSError:
            continue
    return False


def hw_gl_requested() -> bool:
    """User explicitly wants hardware GL (skip every software-GL forcing).

    ``LIBRELANE_GUI_WSL_HW_GL=1`` is the historical name (round 27b, native
    path); ``LANEX_HW_GL=1`` is the product-named alias. Either disables the
    llvmpipe forcing on BOTH the native and the container launch paths, for
    machines whose GPU/GL stack is healthy and fast.
    """
    return bool(os.environ.get("LIBRELANE_GUI_WSL_HW_GL") or os.environ.get("LANEX_HW_GL"))


def software_gl_forced() -> bool:
    """User explicitly wants software GL everywhere (``LANEX_SOFTWARE_GL=1``).

    The symmetric override to :func:`hw_gl_requested` — useful off-WSL too when
    a native GPU stack is broken (stale driver after suspend, remote X, VNC).
    """
    return bool(os.environ.get("LANEX_SOFTWARE_GL"))


def wsl_gl_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return *base* augmented with env that forces Mesa software GL (llvmpipe).

    Under WSL the GPU is a paravirtualized passthrough (``/dev/dxg`` via the
    dxgkrnl/VAIL D3D12 bridge). After the Windows host sleeps or its graphics
    driver resets (TDR), WSLg silently degrades from VAIL to RAIL "copy mode" and
    a strictly hardware-GL app — GDS3D, KLayout, the OpenROAD GUI — **deadlocks on
    X11 window mapping** (the blank/frozen window). Forcing the Mesa software
    rasterizer (llvmpipe) makes the tool render through the CPU and never touch the
    flaky vGPU, so it works regardless of the WSLg transport state. A layout/3D
    viewer does not need the GPU, so this is the reliable default on WSL.

    No-op off WSL (native HW GL is kept) unless ``LANEX_SOFTWARE_GL=1`` forces it
    everywhere; skippable with ``LIBRELANE_GUI_WSL_HW_GL=1`` / ``LANEX_HW_GL=1``
    for boxes whose hardware GL is healthy. Pure env; adds no dependency and
    changes nothing on macOS/Windows-native.
    """
    env: Dict[str, str] = dict(base) if base else {}
    if hw_gl_requested():
        return env
    if not (is_wsl() or software_gl_forced()):
        return env
    env.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    env.setdefault("GALLIUM_DRIVER", "llvmpipe")
    # Qt (OpenROAD GUI) falls back cleanly when its GLX probe can't use the vGPU.
    env.setdefault("QT_XCB_GL_INTEGRATION", "none")
    return env


# Multi-arch DRI driver locations (Debian/Ubuntu multiarch, Fedora/RHEL lib64,
# plain /usr/lib layouts). Mesa's software rasterizer (swrast/llvmpipe) and the
# WSLg d3d12 driver both live here when libgl1-mesa-dri (or distro equivalent)
# is installed.
_DRI_DIRS = (
    "/usr/lib/x86_64-linux-gnu/dri",
    "/usr/lib/aarch64-linux-gnu/dri",
    "/usr/lib/i386-linux-gnu/dri",
    "/usr/lib64/dri",
    "/usr/lib/dri",
    "/usr/local/lib/dri",
)


def mesa_dri_present() -> Optional[bool]:
    """Best-effort: are Mesa's DRI drivers (incl. llvmpipe/swrast) installed?

    A fresh minimal WSL/Ubuntu ships **without** ``libgl1-mesa-dri``. Then no GL
    renderer exists at all: a native GL viewer (GDS3D, KLayout) hangs or crashes
    with a blank window, and forcing ``LIBGL_ALWAYS_SOFTWARE=1`` cannot help
    because llvmpipe itself IS one of these missing drivers. Returns ``True``
    when a driver is found, ``False`` when we can positively tell they're absent,
    ``None`` when we can't tell (non-Linux, or a non-FHS layout like Nix/conda
    where the drivers live elsewhere) — callers must never block on ``None``.
    """
    if not sys.platform.startswith("linux"):
        return None
    search: list = list(_DRI_DIRS)
    extra = os.environ.get("LIBGL_DRIVERS_PATH", "")
    search.extend(p for p in extra.split(os.pathsep) if p)
    saw_dir = False
    for d in search:
        try:
            if not os.path.isdir(d):
                continue
            saw_dir = True
            if any(name.endswith("_dri.so") for name in os.listdir(d)):
                return True
        except OSError:
            continue
    if saw_dir:
        # A DRI dir exists but holds no driver — positively missing.
        return False
    # No DRI dir anywhere. On a dpkg system that means the package is absent
    # (installing libgl1-mesa-dri always creates the multiarch dir); elsewhere
    # (Nix, conda, exotic prefixes) we genuinely can't tell.
    if shutil.which("dpkg-query"):
        try:
            import subprocess
            out = subprocess.run(
                ["dpkg-query", "-W", "-f", "${Status}", "libgl1-mesa-dri"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0 and "installed" in (out.stdout or ""):
                return True
            return False
        except Exception:
            return None
    return None


def wsl_gl_remediation() -> str:
    """Guidance for the (now rare) case where even software GL won't start on WSL —
    usually a stale WSLg/vGPU after the host slept. Detect-and-guide only; we never
    run these host-level commands ourselves (``wsl --shutdown`` would tear down the
    very VM we run in)."""
    return ("If a desktop tool still won't open under WSL, the WSLg GPU bridge is "
            "likely stale (it degrades after the Windows host sleeps). In a Windows "
            "(PowerShell/CMD) terminal run:\n"
            "    wsl --update\n"
            "    wsl --shutdown\n"
            "then reopen your Linux terminal and the GUI — WSLg cold-boots a fresh "
            "GPU context. (We default GL tools to software rendering on WSL, so this "
            "is rarely needed.)")


def is_windows_mount_path(path: Optional[str]) -> bool:
    """True if *path* is a Windows binary visible from WSL.

    Matches the WSL DrvFs mount (``/mnt/<drive>/...``) and Windows executable
    extensions, both of which indicate a binary that the Linux-side flow cannot
    use even though ``shutil.which`` resolves it.
    """
    if not path:
        return False
    p = str(path)
    low = p.lower()
    if low.endswith((".exe", ".bat", ".cmd", ".com")):
        return True
    norm = p.replace("\\", "/").lower()
    if norm.startswith("/mnt/") and len(norm) > 6 and norm[5].isalpha() and norm[6] == "/":
        return True
    return False


def linux_only_path(path: Optional[str] = None) -> str:
    """Return *path* (or ``$PATH``) with Windows-mount dirs removed under WSL.

    Under WSL the Linux ``PATH`` inherits the Windows ``PATH`` (``/mnt/c/...``),
    so ``subprocess`` / ``shutil.which`` can resolve a Windows tool (e.g. the
    Windows ``verilator`` at ``/mnt/c/FOSSEE/...``) that the Linux-side flow
    cannot actually run. Stripping the ``/mnt/<drive>/`` dirs makes every tool
    lookup prefer a real Linux build. ``/mnt/wsl/...`` (Docker-Desktop's WSL
    integration etc.) is NOT a drive mount, so it is kept. Off WSL the PATH is
    returned unchanged.
    """
    raw = path if path is not None else os.environ.get("PATH", "")
    if not is_wsl() or not raw:
        return raw
    kept = [d for d in raw.split(os.pathsep) if d and not is_windows_mount_path(d)]
    return os.pathsep.join(kept)


def usable_which(name: str, path: Optional[str] = None) -> Optional[str]:
    """``shutil.which`` that, under WSL, ignores Windows-mounted binaries.

    Use this anywhere the GUI must run a tool itself (lint, sim, viewers): it
    returns a Linux-usable path or ``None`` even when a Windows ``.exe`` of the
    same name sits earlier on the inherited PATH. Off WSL it is plain
    ``shutil.which``.
    """
    return shutil.which(name, path=linux_only_path(path))


def user_bin_dirs() -> list:
    """Well-known install dirs the GUI drops tools into that may be off ``$PATH``.

    A one-click install (e.g. the GDS3D source build) writes to ``~/.local/bin``,
    and the GDS3D build tree lives under ``$LANEX_HOME/tools/GDS3D``. The
    server's own ``$PATH`` often doesn't include ``~/.local/bin`` (it isn't on a
    fresh login shell's PATH until re-login), so a freshly installed tool would
    look "not installed". These dirs are searched as a fallback. POSIX-oriented
    (Linux/WSL/macOS — where these builds land); harmless elsewhere.
    """
    user = os.path.expanduser("~")
    gui_home = str(home())
    return [
        os.path.join(user, ".local", "bin"),
        os.path.join(gui_home, "tools", "GDS3D", "linux"),
        os.path.join(gui_home, "tools", "GDS3D", "mac"),
    ]


def resolve_user_bin(name: str, alts: Optional[list] = None,
                     path: Optional[str] = None) -> Optional[str]:
    """Resolve a tool to an executable path, checking ``$PATH`` then user dirs.

    First tries :func:`usable_which` (so a Windows ``.exe`` on the WSL ``/mnt/c``
    PATH is ignored), then the :func:`user_bin_dirs` fallbacks for a tool a
    one-click install placed off ``$PATH``. Tries *name* then each of *alts*
    (e.g. ``gds3d`` then ``GDS3D`` — the Makefile emits the capitalised name).
    Returns an absolute path or ``None``.
    """
    candidates = [name, *(alts or [])]
    for cand in candidates:
        hit = usable_which(cand, path)
        if hit:
            return hit
    for d in user_bin_dirs():
        for cand in candidates:
            p = os.path.join(d, cand)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return None


def sanitized_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """A copy of *env* (default ``os.environ``) whose ``PATH`` is Linux-only.

    Hand this to ``subprocess`` for any tool the Linux flow must run so a
    bare-name argv (``["verilator", ...]``) can never resolve to a Windows
    binary on WSL. A no-op off WSL.
    """
    out: Dict[str, str] = dict(os.environ if env is None else env)
    out["PATH"] = linux_only_path(out.get("PATH"))
    return out


def has_controlling_tty() -> bool:
    """True when this process has a controlling terminal (POSIX only).

    The GUI is normally launched from a terminal (``python3 -m lanex.cli``); that
    terminal is still reachable via ``/dev/tty`` even though the install
    subprocess captures its own stdout. We use it so a privileged install can
    let ``sudo`` prompt for a password on that terminal — the most reliable way
    to get root on WSL, where polkit/askpass agents are usually absent.
    """
    if os.name != "posix":
        return False
    try:
        fd = os.open("/dev/tty", os.O_RDWR | getattr(os, "O_NOCTTY", 0))
    except OSError:
        return False
    else:
        os.close(fd)
        return True


def x11_fixed_fonts_present() -> Optional[bool]:
    """Best-effort: are the legacy X11 ``-misc-fixed-`` bitmap fonts installed?

    GDS3D dereferences a NULL when it requests the classic ``fixed`` font and it
    is absent (a fresh WSL/Ubuntu ships none), segfaulting the instant its window
    opens. The fix is the ``xfonts-base`` package. Returns ``True`` when the fonts
    look present, ``False`` when they look missing, ``None`` when we can't tell
    (so callers never block on an uncertain probe). Linux only.
    """
    if not sys.platform.startswith("linux"):
        return None
    # `xset q` lists the X font path; if the misc dir with fonts.dir is on it and
    # populated, the fixed fonts are available. Fall back to the on-disk package
    # location when xset isn't around.
    misc_dirs = [
        "/usr/share/fonts/X11/misc",
        "/usr/share/X11/fonts/misc",
        "/usr/lib/X11/fonts/misc",
    ]
    for d in misc_dirs:
        try:
            fonts_dir = os.path.join(d, "fonts.dir")
            if os.path.isfile(fonts_dir):
                with open(fonts_dir, "r", encoding="utf-8", errors="ignore") as fh:
                    if "fixed" in fh.read():
                        return True
        except OSError:
            continue
    # The misc dirs exist on the system but none advertises `fixed` → missing.
    if any(os.path.isdir(d) for d in misc_dirs):
        return False
    return None


def dns_ok(host: str = _DNS_PROBE_HOST, timeout: float = 4.0) -> Optional[bool]:
    """Best-effort DNS check. ``True`` resolvable, ``False`` not, ``None`` unknown."""
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        socket.getaddrinfo(host, 443)
        return True
    except socket.gaierror:
        return False
    except OSError:
        # A non-name error (e.g. no route) — can't attribute to DNS; unknown.
        return None
    except Exception:
        return None
    finally:
        try:
            socket.setdefaulttimeout(old)
        except Exception:
            pass


def wsl_dns_remediation() -> str:
    """The exact, copy-pasteable fix for the broken WSL2 ``/etc/resolv.conf``."""
    return (
        "WSL2 DNS looks broken — downloads can't resolve github.com. WSL "
        "sometimes generates a non-working /etc/resolv.conf. Fix it in a WSL "
        "terminal, then retry:\n"
        "    sudo rm -f /etc/resolv.conf\n"
        "    sudo bash -c 'echo \"nameserver 8.8.8.8\" > /etc/resolv.conf'\n"
        "To make it stick across reboots, add to /etc/wsl.conf:\n"
        "    [network]\n"
        "    generateResolvConf = false"
    )


# Substrings that mark a name-resolution / connectivity failure in tool output.
_NET_FAILURE_MARKERS = (
    "temporary failure in name resolution",
    "could not resolve host",
    "name or service not known",
    "getaddrinfo failed",
    "failed to resolve",
    "nodename nor servname",
    "no address associated with hostname",
    "connectionerror",
    "readtimeout",
    "read timed out",
    "connecttimeout",
    "connection timed out",
    "max retries exceeded",
    "network is unreachable",
)


def looks_like_network_failure(text: str) -> bool:
    """True when *text* (tool stdout/stderr) shows a DNS/connectivity failure."""
    if not text:
        return False
    low = text.lower()
    return any(m in low for m in _NET_FAILURE_MARKERS)


def network_remediation(output: str = "") -> Optional[str]:
    """Return remediation guidance for a download that failed on the network.

    Prefers the WSL2 resolv.conf fix when applicable (the common, fixable case);
    otherwise returns generic connectivity guidance. Returns ``None`` when there
    is no evidence of a network problem and DNS resolves fine.
    """
    net_evident = looks_like_network_failure(output)
    resolves = dns_ok()
    if resolves is True and not net_evident:
        return None
    if is_wsl() and (resolves is False or net_evident):
        return wsl_dns_remediation()
    if resolves is False or net_evident:
        return (
            "The download couldn't reach the network (DNS/connectivity). Check "
            "your internet connection, any proxy/VPN/firewall, then retry. "
            "If you're behind a proxy, set HTTP_PROXY/HTTPS_PROXY before launching."
        )
    return None


def host_display_available() -> bool:
    """True when the host has a graphical session that a desktop tool can open on.

    macOS and native Windows always have native windowing. On Linux (incl. WSLg)
    a GUI needs ``$DISPLAY`` (X11) or ``$WAYLAND_DISPLAY`` (Wayland) — if neither
    is set we're effectively headless (SSH / server), so launching KLayout/Magic
    would silently flash-and-exit with no window. Best-effort; never raises.
    """
    if sys.platform == "darwin" or os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def wsl_windows_path(linux_path: str) -> Optional[str]:
    """Translate a WSL Linux path to a Windows path via ``wslpath -w``.

    Returns ``None`` off WSL or when ``wslpath`` isn't available. Used so
    "reveal in file manager" can hand a real ``C:\\``-style path to
    ``explorer.exe``. Stdlib subprocess; degrades gracefully.
    """
    if not is_wsl():
        return None
    try:
        import subprocess
        out = subprocess.run(
            ["wslpath", "-w", linux_path],
            capture_output=True, text=True, timeout=5,
        )
        win = (out.stdout or "").strip()
        return win or None
    except Exception:
        return None


def network_status() -> dict:
    """JSON-safe snapshot for the UI: WSL flag, DNS reachability, remediation."""
    resolves = dns_ok()
    rem = None
    if resolves is False:
        rem = wsl_dns_remediation() if is_wsl() else network_remediation()
    return {
        "wsl": is_wsl(),
        "dns_ok": resolves,
        "remediation": rem,
    }


def atomic_write_text(path, text: str, *, encoding: str = "utf-8") -> None:
    """Write *text* to *path* atomically (temp file + ``os.replace``).

    A plain ``write_text`` truncates in place, so a crash mid-write leaves
    invalid JSON — for the GUI's sidecars (custom cells/macros, notes,
    gui-run.json) that silently reads back as "no data", losing user state.
    ``os.replace`` is atomic on POSIX and Windows (same filesystem, which a
    sibling temp file guarantees). Raises on failure like ``write_text``.
    """
    import os as _os
    import tempfile as _tempfile
    from pathlib import Path as _Path

    p = _Path(path)
    fd, tmp = _tempfile.mkstemp(prefix=p.name + ".", suffix=".tmp", dir=str(p.parent))
    try:
        with _os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(text)
        _os.replace(tmp, str(p))
    except Exception:
        try:
            _os.unlink(tmp)
        except OSError:
            pass
        raise
