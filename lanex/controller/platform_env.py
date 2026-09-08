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
import re
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
         ``~/.librelane-gui`` does, the old dir is used (keeps known-designs.json
         and the GDS3D tool tree working without a manual migration).
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


def wsl_gui_env(base: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Full launch env for a native desktop tool: GL forcing PLUS toolkit
    transport pinning. Superset of :func:`wsl_gl_env` — use this at launch sites.

    WSLg exports BOTH a Wayland socket and an X11 (XWayland) display. GTK3 apps
    (GTKWave is the only one LanEx launches) pick Wayland first, and WSLg's
    Wayland/RAIL presentation is exactly the path that degrades to "copy mode":
    the surface maps but never presents — a blank window that exists only in the
    taskbar, its title suffixed ``[WARN: COPY MODE]``, and clicking it does
    nothing. Every tool that works reliably on WSL (KLayout/Qt, Magic/Tk,
    GDS3D/GL, OpenROAD/Qt) talks X11/XWayland — so pin GTK (and any future
    Wayland-default Qt6 build) to that same known-good transport. The trailing
    fallback entries mean a system with no X11 at all still gets a window rather
    than an abort. GTK2 ignores ``GDK_BACKEND``; native Linux/macOS are
    untouched (``is_wsl`` gate); ``LANEX_WAYLAND=1`` opts back into Wayland.
    """
    env = wsl_gl_env(base)
    if is_wsl() and not os.environ.get("LANEX_WAYLAND"):
        env.setdefault("GDK_BACKEND", "x11,*")
        env.setdefault("QT_QPA_PLATFORM", "xcb;wayland")
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


def ensure_darwin_path() -> None:
    """On macOS, append Homebrew's fixed prefixes (+ ``~/.local/bin``) to PATH.

    LanEx is often launched from a context that never sourced ``brew shellenv``
    (pipx entry point, the app-window launcher, a bare login shell) — then
    every probe and subprocess misses ``/opt/homebrew/bin`` (Apple Silicon) and
    freshly brew-installed tools (podman, yosys, klayout…) look "not
    installed". Appending (never prepending) fills the gap without overriding
    the user's own PATH order. No-op off macOS; idempotent; only existing dirs
    are added. Call once at startup — subprocesses inherit the fix.
    """
    if sys.platform != "darwin":
        return
    extras = ["/opt/homebrew/bin", "/usr/local/bin",
              os.path.expanduser("~/.local/bin"),
              # The official podman .pkg installer (LanEx's brew-less fallback)
              # lands here and adds no PATH entry of its own.
              "/opt/podman/bin",
              # Docker Desktop keeps `docker` AND its credential helpers
              # (docker-credential-desktop/-osxkeychain) inside the .app bundle;
              # the privileged /usr/local/bin symlinks only appear after Docker's
              # first run. Without this dir on PATH, `docker pull` dies with
              # `docker-credential-desktop: executable file not found in $PATH`
              # even though Docker Desktop is installed and running.
              "/Applications/Docker.app/Contents/Resources/bin",
              os.path.expanduser("~/Applications/Docker.app/Contents/Resources/bin")]
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    add = [d for d in extras if d not in parts and os.path.isdir(d)]
    if add:
        os.environ["PATH"] = os.pathsep.join(parts + add)


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
    if sys.platform == "darwin":
        for cand in candidates:
            for p in _DARWIN_APP_BINARIES.get(cand.lower(), []):
                p = os.path.expanduser(p)
                if os.path.isfile(p) and os.access(p, os.X_OK):
                    return p
    return None


# macOS installs GUI tools as .app bundles with NO CLI link on PATH — the brew
# cask / official .dmg drop KLayout in /Applications and `which klayout` finds
# nothing, so the tool showed "missing" while plainly installed. The bundle's
# inner binary is directly runnable with the same argv as the Linux build.
_DARWIN_APP_BINARIES = {
    "klayout": [
        "/Applications/klayout.app/Contents/MacOS/klayout",
        "/Applications/KLayout.app/Contents/MacOS/klayout",
        "/Applications/KLayout/klayout.app/Contents/MacOS/klayout",
        "~/Applications/klayout.app/Contents/MacOS/klayout",
    ],
}


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
    """Safe WSL DNS guidance which preserves the host's resolver strategy."""
    return (
        "DNS resolution failed inside WSL. Keep WSL's generated resolver and DNS "
        "tunneling enabled so VPN and company DNS continue to work. Check the "
        "Windows network/VPN and WSL networking settings, restart only the LanEx "
        "environment, then retry. A static resolv.conf is a last-resort, diagnosed "
        "repair and must not replace an existing resolver configuration."
    )


_DNS_FAILURE_MARKERS = (
    "temporary failure in name resolution", "could not resolve host",
    "name or service not known", "getaddrinfo failed", "failed to resolve",
    "nodename nor servname", "no address associated with hostname",
)
_ROUTE_FAILURE_MARKERS = (
    "network is unreachable", "enetunreach", "no route to host",
    "destination host unreachable",
)
_TLS_FAILURE_MARKERS = (
    "certificate verify failed", "certificate verification failed",
    "unable to get local issuer certificate", "self signed certificate",
    "tls handshake", "ssl certificate problem", "x509:",
)
_TIMEOUT_MARKERS = (
    "readtimeout", "read timed out", "connecttimeout", "connection timed out",
    "operation timed out", "timed out", "timeout was reached",
)
_CONNECTION_MARKERS = (
    "connectionerror", "connection refused", "connection reset",
    "connection aborted", "max retries exceeded", "couldn't connect",
    "failed to connect",
)


def redact_network_diagnostics(text: str) -> str:
    """Remove proxy/HTTP credentials before diagnostics reach logs or state."""
    if not text:
        return ""
    clean = re.sub(
        r"(?i)(https?://)([^\s/@:]+):([^\s/@]+)@",
        r"\1[redacted]@",
        str(text),
    )
    clean = re.sub(
        r"(?im)\b(authorization|proxy-authorization)\s*:\s*\S+[^\r\n]*",
        r"\1: [redacted]",
        clean,
    )
    clean = re.sub(
        r"(?i)([?&](?:access_token|auth|key|password|sig|token)=)[^&\s]+",
        r"\1[redacted]",
        clean,
    )
    return clean


def _diagnostic_tail(text: str, *, max_lines: int = 20, max_chars: int = 4000) -> str:
    lines = redact_network_diagnostics(text).splitlines()[-max_lines:]
    return "\n".join(lines)[-max_chars:]


def diagnose_network_failure(output: str = "", *,
                             dns_result: Optional[bool] = None) -> Optional[dict]:
    """Classify a failed network/package operation without collapsing it to DNS.

    The result is JSON-safe and includes a bounded, credential-redacted log tail.
    ``None`` means the supplied evidence does not describe a known failure.
    """
    tail = _diagnostic_tail(output)
    low = tail.lower()
    if dns_result is None:
        dns_result = dns_ok()

    category = ""
    retryable = False
    summary = ""
    remediation = ""

    # Local resource/package-manager failures outrank incidental network text.
    if any(m in low for m in ("no space left on device", "enospc", "disk quota exceeded")):
        category, summary = "no-space", "The target filesystem ran out of space."
        remediation = "Free space on the reported filesystem, then retry; completed caches are retained."
    elif any(m in low for m in ("permission denied", "operation not permitted", "eacces")):
        category, summary = "permission", "The operation was denied by filesystem permissions."
        remediation = "Repair ownership of the LanEx-owned path shown in the log, then retry."
    elif any(m in low for m in ("could not get lock", "unable to acquire the dpkg frontend lock",
                                "waiting for cache lock", "is another process using it")):
        category, retryable = "apt-lock", True
        summary = "Another package manager currently owns the apt/dpkg lock."
        remediation = "Let the active package operation finish, then retry; do not delete apt lock files."
    elif any(m in low for m in ("dpkg was interrupted", "you must manually run 'dpkg --configure -a'",
                                "dpkg --configure -a")):
        category, retryable = "apt-interrupted", True
        summary = "A previous package operation left dpkg configuration incomplete."
        remediation = "LanEx can resume dpkg configuration after confirming no package manager is active."
    elif any(m in low for m in ("unable to locate package", "some index files failed to download",
                                "does not have a release file")):
        category, retryable = "apt-index", True
        summary = "The apt package index is missing, stale, or unavailable."
        remediation = "Refresh the package index with bounded retries, preserving downloaded package caches."
    elif "407" in low or "proxy authentication required" in low:
        category = "proxy-auth"
        summary = "The configured proxy requires authentication."
        remediation = "Provide an explicit HTTP(S) proxy URL or ask the administrator for shell proxy settings; PAC files are not shell proxy URLs."
    elif "429" in low or "too many requests" in low or "rate limit" in low:
        category, retryable = "rate-limit", True
        summary = "The remote service rate-limited the request."
        remediation = "Wait for the service's retry window, then retry without discarding completed downloads."
    elif any(m in low for m in _TLS_FAILURE_MARKERS):
        category = "tls"
        summary = "TLS certificate verification failed."
        remediation = "Check the system clock, CA certificates, and any inspecting proxy; TLS verification will not be disabled."
    elif any(m in low for m in _ROUTE_FAILURE_MARKERS) and dns_result is True:
        category, retryable = "route", True
        summary = "DNS works, but the destination has no reachable network route."
        remediation = "Check VPN, firewall, route, and IPv4/IPv6 connectivity, then retry."
    elif any(m in low for m in _DNS_FAILURE_MARKERS) or (not low and dns_result is False):
        category, retryable = "dns", True
        summary = "The destination name could not be resolved."
        remediation = wsl_dns_remediation() if is_wsl() else (
            "Check the current DNS/VPN/proxy configuration, then retry; LanEx will not replace it."
        )
    elif any(m in low for m in _ROUTE_FAILURE_MARKERS):
        category, retryable = "route", True
        summary = "The destination has no reachable network route."
        remediation = "Check VPN, firewall, route, and IPv4/IPv6 connectivity, then retry."
    elif any(m in low for m in _TIMEOUT_MARKERS):
        category, retryable = "timeout", True
        summary = "The network operation exceeded its bounded timeout."
        remediation = "Check slow or filtered connectivity and retry; completed caches are retained."
    elif re.search(r"\b(?:http[^\r\n]*\s)?(?:401|403)\b", low):
        category = "http-auth"
        summary = "The remote HTTP service rejected authorization."
        remediation = "Check repository or registry access; the endpoint itself was reachable."
    elif re.search(r"\b(?:http[^\r\n]*\s)?(?:4\d\d|5\d\d)\b", low):
        category, retryable = "http-status", bool(re.search(r"\b5\d\d\b", low))
        summary = "The remote HTTP service returned an error response."
        remediation = "Verify the requested URL and retry later for a server-side error."
    elif any(m in low for m in _CONNECTION_MARKERS):
        category, retryable = "connection", True
        summary = "The connection could not be established or was interrupted."
        remediation = "Check proxy, VPN, firewall, and destination availability, then retry."
    else:
        return None

    return {
        "category": category,
        "retryable": retryable,
        "summary": summary,
        "remediation": remediation,
        "dns_ok": dns_result,
        "log_tail": tail,
    }


def looks_like_network_failure(text: str) -> bool:
    """True when *text* shows a transport, TLS, proxy, or HTTP failure."""
    diagnosis = diagnose_network_failure(text, dns_result=True)
    return bool(diagnosis and diagnosis["category"] not in {
        "no-space", "permission", "apt-lock", "apt-interrupted", "apt-index",
    })


def network_remediation(output: str = "") -> Optional[str]:
    """Return remediation guidance for a download that failed on the network.

    Prefers the WSL2 resolv.conf fix when applicable (the common, fixable case);
    otherwise returns generic connectivity guidance. Returns ``None`` when there
    is no evidence of a network problem and DNS resolves fine.
    """
    resolves = dns_ok()
    diagnosis = diagnose_network_failure(output, dns_result=resolves)
    if diagnosis is None:
        return None
    return diagnosis["summary"] + " " + diagnosis["remediation"]


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
    diagnosis = diagnose_network_failure("", dns_result=resolves)
    return {
        "wsl": is_wsl(),
        "dns_ok": resolves,
        "category": diagnosis["category"] if diagnosis else None,
        "remediation": diagnosis["remediation"] if diagnosis else None,
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
