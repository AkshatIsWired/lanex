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
"""Multi-layer tool + PDK installer.

Foolproof architecture — tries install strategies in priority order
until one succeeds. Detects host capabilities (pip, apt, brew, conda,
docker, etc.) and picks the best available path for each tool.

Strategy layers (tried in order):
  1. pip (Python package)
  2. conda (conda-forge channel)
  3. apt-get (Linux Debian/Ubuntu)
  4. brew (macOS)
  5. choco (Windows Chocolatey)
  6. scoop (Windows Scoop)
  7. yowasp (WASM builds via pip — platform-agnostic)
  8. prebuilt binary download (GitHub releases)
  9. Docker/Podman container with all tools
 10. Nix (if available)
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .events import bus

_active_installs: Dict[str, subprocess.Popen] = {}

# Jobs the user cancelled. Consulted by every strategy/retry loop so a cancel
# stops the WHOLE job, not just the currently-running subprocess — the old bug
# was that killing one strategy's process made the loop move on and start the
# NEXT strategy's multi-GB download. Cleared when a fresh job claims the key.
_cancelled: set = set()
_cancelled_lock = threading.Lock()


def _mark_cancelled(key: str) -> None:
    with _cancelled_lock:
        _cancelled.add(key)


def _clear_cancelled(key: str) -> None:
    with _cancelled_lock:
        _cancelled.discard(key)


def _is_cancelled(key: str) -> bool:
    with _cancelled_lock:
        return key in _cancelled


def _kill_proc_tree(proc: subprocess.Popen, grace: float = 2.0) -> None:
    """Terminate *proc* AND its descendants (POSIX: the whole process group).

    ``proc.terminate()`` alone kills only the direct child; install strategies
    run ``sh -c`` scripts whose grandchildren (``ciel fetch``, ``pip``, ``curl``)
    would survive as orphans and keep downloading — the "I cancelled and it kept
    going" bug. Requires the process to have been spawned with
    ``start_new_session=True`` (POSIX) for the group kill to be precise; falls
    back to a plain terminate/kill everywhere else. Never raises.
    """
    def _signal_group(sig: int) -> bool:
        if os.name != "posix":
            return False
        try:
            os.killpg(os.getpgid(proc.pid), sig)
            return True
        except (ProcessLookupError, PermissionError, OSError):
            return False

    try:
        if not _signal_group(signal.SIGTERM):
            proc.terminate()
    except Exception:
        pass
    try:
        proc.wait(timeout=grace)
    except Exception:
        try:
            if not _signal_group(signal.SIGKILL):
                proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=grace)
        except Exception:
            pass

# In-progress download/install guard, keyed by job id (tool key, ``pdk:<v>``,
# or ``container:image``). Prevents a second concurrent download of the SAME
# thing — the real "double download". Interrupted downloads resume naturally on
# the next attempt because the underlying tools keep their caches (docker layer
# cache, apt/pip/conda caches, ciel's tarball store); we never wipe those.
_in_progress: set = set()
_in_progress_lock = threading.Lock()


def _begin_job(key: str) -> bool:
    """Claim a job. Returns False if one with this key is already running."""
    with _in_progress_lock:
        if key in _in_progress:
            return False
        _in_progress.add(key)
    # A fresh job must not inherit a stale cancel from a previous attempt.
    _clear_cancelled(key)
    return True


def _end_job(key: str) -> None:
    with _in_progress_lock:
        _in_progress.discard(key)
    # Every installer job (tool/PDK/image) mutates state that check_tools()
    # TTL-caches; drop the cache so the UI's post-job refetch is never stale.
    try:
        from . import tools as _tools
        _tools._check_tools_cache.clear()
    except Exception:
        pass


def is_in_progress(key: str) -> bool:
    with _in_progress_lock:
        return key in _in_progress

# ---------------------------------------------------------------------------
# Event helpers — push progress to SSE via shared bus
# ---------------------------------------------------------------------------

def _emit(kind: str, payload: Dict[str, Any]) -> None:
    bus.emit(kind, payload)


# ---------------------------------------------------------------------------
# Host capability detection
# ---------------------------------------------------------------------------

def _check_cmd(name: str) -> bool:
    # usable_which, not shutil.which: under WSL a Windows tool on the inherited
    # /mnt/c PATH must NOT count as "installed" — the Linux flow can't run it, so
    # the GUI should offer the native Linux install instead of falsely verifying.
    from . import platform_env
    return platform_env.usable_which(name) is not None


def _py_module_available(mod: str) -> bool:
    """True when *mod* is importable in THIS interpreter.

    A pipx/venv install of LanEx has ``pip``, ``ciel`` and ``librelane``
    importable in its own environment while their console scripts are NOT on the
    system ``$PATH`` (pipx only exposes the ``lanex`` entry point). A PATH-only
    probe would wrongly report them missing and route installs down doomed
    strategies — module probing keeps every one-click path working under pipx.
    """
    try:
        import importlib.util
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def _ciel_argv() -> Optional[List[str]]:
    """Argv prefix that invokes ciel: the CLI if on PATH, else ``python -m ciel``.

    Returns ``None`` when ciel is neither on PATH nor importable."""
    if _check_cmd("ciel"):
        return ["ciel"]
    if _py_module_available("ciel"):
        return [sys.executable or "python3", "-m", "ciel"]
    return None


def _ciel_shell_cmd() -> Optional[str]:
    """Shell-safe command string that invokes ciel (for generated sh scripts)."""
    import shlex

    if _check_cmd("ciel"):
        return "ciel"
    if _py_module_available("ciel"):
        return f"{shlex.quote(sys.executable or 'python3')} -m ciel"
    return None


def _can_sudo() -> bool:
    """True if ``sudo`` can run non-interactively (NOPASSWD or a fresh ticket).

    The GUI launches installs as a detached subprocess with **no controlling
    terminal**, so a ``sudo`` that needs a password can't prompt — it just fails
    (or, worse, blocks). We probe with ``sudo -n true`` first so we can give the
    user a copy-pasteable command instead of a doomed/hung install."""
    if sys.platform == "win32":
        return False
    try:
        out = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5)
        return out.returncode == 0
    except Exception:
        return False


def _needs_sudo(argv: List[str]) -> bool:
    return bool(argv) and (argv[0] == "sudo" or (argv[0] in ("sh", "bash") and any("sudo " in a for a in argv)))


def _escalate_argv(argv: List[str]) -> Optional[Tuple[List[str], bool]]:
    """Pick a way to gain root when passwordless ``sudo`` isn't available.

    Returns ``(argv, inherit_tty)`` or ``None`` when no non-interactive path
    exists (caller then shows a copy-paste command). Order is by reliability on
    the platform LibreLane supports:

    1. **Prompt on the controlling terminal.** The GUI is launched from a
       terminal (``python3 -m lanex.cli``); ``sudo`` can read a password from
       ``/dev/tty`` there. This works on WSL/Linux even when no polkit/askpass
       agent is installed (the usual case on a fresh WSL Ubuntu), so it is the
       primary path — it makes the one-click install genuinely install natively.
    2. **Graphical PolicyKit prompt** (``sudo`` → ``pkexec``) when there is a
       display and ``pkexec`` exists — for GUI-only launches with no terminal.
       Only the plain ``sudo <cmd>`` form; ``sh -c "… sudo …"`` can't be
       rewritten, so those fall through to the copy-paste command.
    """
    from . import platform_env

    if platform_env.has_controlling_tty():
        return list(argv), True
    if (argv and argv[0] == "sudo" and _check_cmd("pkexec")
            and platform_env.host_display_available()):
        return ["pkexec", *argv[1:]], False
    return None


# Hard ceiling so a wedged install can never hold the in-progress lock forever
# (the lock is what stops duplicate downloads). Generous — real downloads of the
# image/PDK take a while — but finite.
_INSTALL_TIMEOUT_S = 3600


def _shell_exec_quiet(argv: List[str], timeout: float = 10.0) -> Tuple[int, str, str]:
    """Run a probe command, capturing output; never raises. (rc, stdout, stderr)."""
    try:
        kwargs: Dict[str, Any] = {"capture_output": True, "text": True, "timeout": timeout, "check": False}
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(argv, **kwargs)
        return out.returncode, (out.stdout or ""), (out.stderr or "")
    except FileNotFoundError as ex:
        return 127, "", str(ex)
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as ex:
        return 1, "", f"{type(ex).__name__}: {ex}"


def ciel_home() -> str:
    """The PDK root ciel/librelane will use, falling back to ``~/.ciel``."""
    try:
        import ciel  # type: ignore

        return ciel.get_ciel_home(os.environ.get("PDK_ROOT") or None)
    except Exception:
        return os.path.expanduser("~/.ciel")


def repair_ciel_store(family: Optional[str] = None, *, pdk_root: Optional[str] = None) -> Dict[str, Any]:
    """Recover a ciel PDK store wedged by an interrupted download.

    An aborted ``ciel fetch`` (network timeout mid-extract) can leave a version
    directory a later fetch can't overwrite, surfacing as
    ``[Errno 13] Permission denied`` on ``~/.ciel/…``. This re-opens write
    permission across the store (owner-scoped ``chmod u+w`` — no root needed for a
    user-owned ``~/.ciel``) and, when *family* is given, removes just that
    family's cached versions so the next install re-downloads them cleanly; other
    installed PDKs are untouched. ``family=None`` only restores write bits and
    deletes nothing. Best-effort; never raises.
    """
    root = pdk_root or os.environ.get("PDK_ROOT") or ciel_home()
    store = os.path.join(root, "ciel")
    out: Dict[str, Any] = {"ok": True, "store": store, "removed": []}
    if not os.path.isdir(store):
        out["note"] = "no ciel store found — nothing to repair"
        return out
    try:
        # Re-open write perms on everything we own, so a subsequent removal (ours
        # or ciel's) can't be blocked by a directory written without a write bit.
        for base, dirs, files in os.walk(store):
            for name in dirs + files:
                p = os.path.join(base, name)
                if os.path.islink(p):
                    continue
                try:
                    os.chmod(p, os.lstat(p).st_mode | 0o200)
                except OSError:
                    pass
        if family:
            versions = os.path.join(store, _pdk_family(family), "versions")
            if os.path.isdir(versions):
                shutil.rmtree(versions, ignore_errors=True)
                out["removed"].append(versions)
        return out
    except Exception as ex:  # pragma: no cover - defensive
        return {"ok": False, "reason": f"{type(ex).__name__}: {ex}", "store": store}


def _ciel_root(pdk_root: Optional[str] = None) -> str:
    """The directory that CONTAINS the ``ciel/`` store (``~/.ciel`` by default)."""
    return pdk_root or os.environ.get("PDK_ROOT") or ciel_home()


def _foreign_owned_sample(path: str, limit: int = 3) -> List[str]:
    """Up to *limit* entries under *path* not owned by the current user.

    Empty on platforms without ``os.getuid`` (Windows) or when everything is
    ours. This is how we distinguish the round-42 *interrupted-download* wedge
    (owner-scoped ``chmod``/``rm`` self-heals it) from a store a prior ``sudo``
    run left owned by root — which owner-scoped healing can NEVER fix, so ciel
    keeps failing with ``[Errno 13] Permission denied`` on every retry.
    """
    if not hasattr(os, "getuid"):
        return []
    me = os.getuid()
    out: List[str] = []
    try:
        if os.lstat(path).st_uid != me:
            out.append(path)
    except OSError:
        return out
    for base, dirs, files in os.walk(path):
        for name in dirs + files:
            p = os.path.join(base, name)
            try:
                if os.lstat(p).st_uid != me:
                    out.append(p)
                    if len(out) >= limit:
                        return out
            except OSError:
                continue
    return out


def ciel_permission_status(pdk_root: Optional[str] = None) -> Dict[str, Any]:
    """Report whether the ciel PDK store has root-owned files blocking writes.

    Returns ``{"needs_root": bool, ...}``. When True, ``chown_cmd`` is the exact
    command that fixes it and ``message`` is a plain-language explanation — the
    caller surfaces both instead of looping into the same ``Permission denied``.
    """
    root = _ciel_root(pdk_root)
    store = os.path.join(root, "ciel")
    sample = _foreign_owned_sample(store) if os.path.isdir(store) else []
    if not sample:
        return {"needs_root": False, "root": root}
    try:
        import getpass
        user = getpass.getuser()
    except Exception:
        user = str(os.getuid()) if hasattr(os, "getuid") else "$USER"
    chown_cmd = f"sudo chown -R {user} {root}"
    return {
        "needs_root": True,
        "root": root,
        "sample": sample,
        "chown_cmd": chown_cmd,
        "message": (
            f"The PDK store at {root} contains files owned by root — most likely "
            "from an earlier command run with sudo. ciel can't write there, so the "
            "download keeps failing with 'Permission denied'. Restore ownership to "
            f"you with:\n    {chown_cmd}"
        ),
    }


def fix_ciel_permissions(pdk_root: Optional[str] = None) -> Dict[str, Any]:
    """Restore ownership of the ciel store to the current user (opt-in, escalated).

    Runs ``sudo chown -R <uid>:<gid> <root>`` scoped to the ciel home only, using
    the same escalation as tool installs (a terminal /dev/tty prompt, else pkexec).
    Never runs ``rm`` and never touches anything outside ``~/.ciel``. Async: the
    outcome streams as ``installer_*`` events (including the password banner).
    """
    if not hasattr(os, "getuid"):
        return {"ok": False, "reason": "not supported on this platform"}
    root = _ciel_root(pdk_root)
    if not os.path.isdir(root):
        return {"ok": True, "note": "no ciel store — nothing to repair"}
    key = "ciel:perms"
    if not _begin_job(key):
        return {"ok": True, "in_progress": True, "status": "already-running"}
    uid, gid = os.getuid(), os.getgid()

    def _worker() -> None:
        try:
            _emit("installer_info", {"key": key, "message": f"Repairing ownership of {root}…"})
            # Prefixed with sudo so _run_argv routes it through the escalation path
            # (tty prompt / pkexec); _run_argv emits installer_done/error itself.
            _run_argv(["sudo", "chown", "-R", f"{uid}:{gid}", root],
                      label="fix ciel permissions", key=key)
        finally:
            _end_job(key)

    threading.Thread(target=_worker, daemon=True, name="ciel_perms").start()
    return {"ok": True, "status": "started"}


def _check_python_capable(pkg: str) -> bool:
    """Check if pip can install *pkg* by testing importability."""
    try:
        __import__(pkg.replace("-", "_"))
        return True
    except ImportError:
        pass
    if _check_cmd("pip"):
        return True
    if _check_cmd("pip3"):
        return True
    return False


def platform_machine() -> str:
    try:
        import platform
        return platform.machine().lower()
    except Exception:
        return "unknown"


def detect_environment() -> Dict[str, Any]:
    """Detect all available install methods on the host machine."""
    is_linux = sys.platform.startswith("linux")
    is_macos = sys.platform == "darwin"
    is_win = sys.platform == "win32"

    machine = "unknown"
    if not is_win and hasattr(os, "uname"):
        machine = os.uname().machine
    else:
        machine = platform_machine()

    return {
        "os": "linux" if is_linux else ("macos" if is_macos else "windows"),
        "arch": machine,
        "python": sys.executable,
        "python_version": sys.version,
        # Module-aware: inside a pipx/venv install the console scripts are off
        # the system PATH, but `python -m pip` works — count that as pip.
        "pip": _check_cmd("pip") or _check_cmd("pip3") or _py_module_available("pip"),
        "pip3": _check_cmd("pip3"),
        "conda": _check_cmd("conda") or _check_cmd("mamba"),
        "apt": _check_cmd("apt-get") if is_linux else False,
        "apt_fast": _check_cmd("apt-fast") if is_linux else False,
        # PATH-independent: brew's two canonical prefixes are probed directly,
        # since a pipx/app-window launch may never have sourced `brew shellenv`.
        "brew": (_check_cmd("brew") or _brew_path() is not None) if is_macos else False,
        "choco": _check_cmd("choco") if is_win else False,
        "scoop": _check_cmd("scoop") if is_win else False,
        "docker": _check_cmd("docker"),
        "podman": _check_cmd("podman"),
        "nix": _check_cmd("nix"),
        "curl": _check_cmd("curl"),
        "wget": _check_cmd("wget"),
        "git": _check_cmd("git"),
        "wsl": is_win and _check_cmd("wsl"),
        # Module-aware for the same pipx reason as pip above.
        "ciel": _check_cmd("ciel") or _py_module_available("ciel"),
    }


# ---------------------------------------------------------------------------
# Tool install strategies (priority-ordered)
# ---------------------------------------------------------------------------
# Each strategy is a dict:
#   methods: list of method names (all must be in env for this strategy)
#   label: human-readable description
#   prepare: callable(env, tool_key) -> list of argv or None (skip)
#   verify: callable(key) -> bool (post-install check)
#
# Strategies are tried in order; first one whose prepare() returns argv and
# whose verify() passes after execution wins.

_STRATEGY_REGISTRY: List[Dict[str, Any]] = []


def _strategy(methods: List[str], label: str, priority: int = 100):
    """Decorator to register an install strategy."""
    def wrap(fn):
        _STRATEGY_REGISTRY.append({
            "methods": methods,
            "label": label,
            "priority": priority,
            "prepare": fn,
        })
        _STRATEGY_REGISTRY.sort(key=lambda s: s["priority"])
        return fn
    return wrap


def _get_env_value(env: Dict[str, Any], key: str) -> bool:
    return env.get(key, False)


def _strategies_for(env: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return strategies whose required methods are all available."""
    return [
        s for s in _STRATEGY_REGISTRY
        if all(_get_env_value(env, m) for m in s["methods"])
    ]


# ---- Strategy: pip ----

# Only tools that genuinely ship a working pip/WASM build. Notably there is NO
# `yowasp-openroad` (OpenROAD is too large for the WASM toolchain) and the PyPI
# `verilator` package is not the real simulator — so neither is offered here.
@_strategy(["pip"], "pip install", priority=10)
def _strategy_pip(env: Dict[str, Any], key: str) -> Optional[List[str]]:
    py = sys.executable or "python3"
    mapping = {
        "yosys": [py, "-m", "pip", "install", "yowasp-yosys"],
        "ciel": [py, "-m", "pip", "install", "--upgrade", "ciel"],
        "librelane": [py, "-m", "pip", "install", "--upgrade", "librelane"],
    }
    return mapping.get(key)


# ---- Strategy: conda ----
# litex-hub is the channel the open-silicon ecosystem publishes the full EDA
# suite to, built to work together — the most reliable source for OpenROAD,
# Magic, and Netgen (the LVS tool, not the unrelated mesh generator that
# conda-forge/apt ship under the same name). Tried before conda-forge.
@_strategy(["conda"], "conda install (litex-hub)", priority=18)
def _strategy_conda_litex(env: Dict[str, Any], key: str) -> Optional[List[str]]:
    conda = "mamba" if _check_cmd("mamba") else "conda"
    mapping = {
        "yosys": [conda, "install", "-c", "litex-hub", "-y", "yosys"],
        "openroad": [conda, "install", "-c", "litex-hub", "-y", "openroad"],
        "klayout": [conda, "install", "-c", "litex-hub", "-y", "klayout"],
        "magic": [conda, "install", "-c", "litex-hub", "-y", "magic"],
        "netgen": [conda, "install", "-c", "litex-hub", "-y", "netgen"],
    }
    return mapping.get(key)


@_strategy(["conda"], "conda install (conda-forge)", priority=20)
def _strategy_conda(env: Dict[str, Any], key: str) -> Optional[List[str]]:
    conda = "mamba" if _check_cmd("mamba") else "conda"
    # conda-forge reliably has these three; its `magic`/`netgen` are different
    # tools, so we don't offer them here (litex-hub covers those).
    mapping = {
        "yosys": [conda, "install", "-c", "conda-forge", "-y", "yosys"],
        "klayout": [conda, "install", "-c", "conda-forge", "-y", "klayout"],
        "verilator": [conda, "install", "-c", "conda-forge", "-y", "verilator"],
        "iverilog": [conda, "install", "-c", "conda-forge", "-y", "iverilog"],
        "graphviz": [conda, "install", "-c", "conda-forge", "-y", "graphviz"],
    }
    return mapping.get(key)


# ---- Strategy: apt (Linux Debian/Ubuntu) ----

@_strategy(["apt"], "apt install (Linux)", priority=30)
def _strategy_apt(env: Dict[str, Any], key: str) -> Optional[List[str]]:
    apt = "apt-fast" if _check_cmd("apt-fast") else "apt-get"
    # Debian/Ubuntu ship yosys, klayout, verilator. They do NOT package
    # OpenROAD, and their `magic`/`netgen` are unrelated tools — so those are
    # intentionally omitted (use conda/nix/Docker instead).
    mapping = {
        "yosys": ["sudo", apt, "install", "-y", "yosys"],
        "klayout": ["sudo", apt, "install", "-y", "klayout"],
        "verilator": ["sudo", apt, "install", "-y", "verilator"],
        "iverilog": ["sudo", apt, "install", "-y", "iverilog"],
        "graphviz": ["sudo", apt, "install", "-y", "graphviz"],
        "ciel": ["sh", "-c", f"sudo {apt} install -y python3-pip && pip3 install ciel 2>/dev/null || pipx install ciel 2>/dev/null || pip3 install --break-system-packages ciel"],
        # Container engines: Podman is the rootless, daemonless choice and is the
        # simplest to bring up on Debian/Ubuntu. Docker via apt installs the
        # daemon (you may then need to add your user to the `docker` group).
        "podman": ["sudo", apt, "install", "-y", "podman"],
        "docker": ["sudo", apt, "install", "-y", "docker.io"],
    }
    return mapping.get(key)


# ---- Strategy: official Docker convenience script (Linux) ----
# The cross-distro method Docker documents. Needs curl + sudo. Linux only.
@_strategy(["curl"], "get.docker.com script (Linux)", priority=34)
def _strategy_docker_script(env: Dict[str, Any], key: str) -> Optional[List[str]]:
    if key != "docker" or env.get("os") != "linux":
        return None
    return ["sh", "-c", "curl -fsSL https://get.docker.com | sudo sh"]


# ---- Strategy: brew (macOS) ----

def _brew_path() -> Optional[str]:
    """Absolute path to ``brew``, even when it's off this process's PATH.

    LanEx may be launched from a context that never sourced ``brew shellenv``
    (pipx run from a bare login shell, an app-window launcher). Homebrew's two
    canonical prefixes are fixed: /opt/homebrew (Apple Silicon) and /usr/local
    (Intel). Returning the absolute path keeps every brew strategy working
    regardless of the server's PATH."""
    from . import platform_env
    hit = platform_env.usable_which("brew")
    if hit:
        return hit
    for cand in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew"):
        if os.access(cand, os.X_OK):
            return cand
    return None


@_strategy(["brew"], "brew install (macOS)", priority=40)
def _strategy_brew(env: Dict[str, Any], key: str) -> Optional[List[str]]:
    # Homebrew core has these; OpenROAD/Magic/Netgen are not in core (use
    # conda/nix/Docker on macOS).
    brew = _brew_path() or "brew"
    mapping = {
        "yosys": [brew, "install", "yosys"],
        "klayout": [brew, "install", "--cask", "klayout"],
        "verilator": [brew, "install", "verilator"],
        "iverilog": [brew, "install", "icarus-verilog"],
        "graphviz": [brew, "install", "graphviz"],
        # docker/podman never reach this generic strategy on macOS —
        # install_tool routes them to _install_engine_macos (cask rename,
        # --force retry, podman machine setup). Kept for completeness.
        "docker": [brew, "install", "--cask", "docker-desktop"],
        "podman": [brew, "install", "podman"],
    }
    return mapping.get(key)


# ---- Strategy: choco (Windows) ----

@_strategy(["choco"], "choco install (Windows)", priority=50)
def _strategy_choco(env: Dict[str, Any], key: str) -> Optional[List[str]]:
    mapping = {
        # Windows package managers only reliably carry KLayout. OpenROAD/Magic/
        # Netgen on Windows need WSL2 (where the Linux strategies apply).
        "klayout": ["choco", "install", "-y", "klayout"],
        "graphviz": ["choco", "install", "-y", "graphviz"],
        # Docker Desktop (WSL2 backend) is the supported Windows path.
        "docker": ["choco", "install", "-y", "docker-desktop"],
        "podman": ["choco", "install", "-y", "podman-cli"],
    }
    return mapping.get(key)


# ---- Strategy: scoop (Windows) ----

@_strategy(["scoop"], "scoop install (Windows)", priority=60)
def _strategy_scoop(env: Dict[str, Any], key: str) -> Optional[List[str]]:
    mapping = {
        "klayout": ["scoop", "install", "klayout"],
        "graphviz": ["scoop", "install", "graphviz"],
        # docker/podman removed on purpose: scoop's packages are the bare CLI
        # clients with NO engine — they'd verify as "installed" while every
        # container operation fails. Docker Desktop (choco) is the real path.
    }
    return mapping.get(key)


# ---- Strategy: Nix (nixpkgs) ----
# Nix is LibreLane's officially-supported way to get the full toolchain, and
# nixpkgs packages every tool (Magic is `magic-vlsi`, the LVS Netgen is
# `netgen-lvs`). Requires experimental flakes to be enabled for `nix profile`.
@_strategy(["nix"], "nix profile install (nixpkgs)", priority=70)
def _strategy_nix(env: Dict[str, Any], key: str) -> Optional[List[str]]:
    attr = {
        "yosys": "yosys",
        "openroad": "openroad",
        "klayout": "klayout",
        "verilator": "verilator",
        "iverilog": "verilog",
        "magic": "magic-vlsi",
        "netgen": "netgen-lvs",
        "graphviz": "graphviz",
    }.get(key)
    if not attr:
        return None
    return [
        "nix",
        "--extra-experimental-features", "nix-command flakes",
        "profile", "install", f"nixpkgs#{attr}",
    ]


# ---------------------------------------------------------------------------
# PDK install strategies (priority-ordered)
# ---------------------------------------------------------------------------

_PDK_STRATEGY_REGISTRY: List[Dict[str, Any]] = []


def _pdk_strategy(methods: List[str], label: str, priority: int = 100):
    def wrap(fn):
        _PDK_STRATEGY_REGISTRY.append({
            "methods": methods,
            "label": label,
            "priority": priority,
            "prepare": fn,
        })
        _PDK_STRATEGY_REGISTRY.sort(key=lambda s: s["priority"])
        return fn
    return wrap


def _pdk_strategies_for(env: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        s for s in _PDK_STRATEGY_REGISTRY
        if all(_get_env_value(env, m) for m in s["methods"])
    ]


def _pdk_family(pdk: str) -> str:
    """Resolve a PDK variant (sky130A) to its family (sky130).

    ``ciel`` accepts either form for ``--pdk-family`` and resolves variants
    itself, but we normalise for our own caches and messages.
    """
    p = (pdk or "").lower()
    if p.startswith("sky130"):
        return "sky130"
    if p.startswith("gf180mcu"):
        return "gf180mcu"
    if "sg13g2" in p or p.startswith("ihp"):
        return "ihp-sg13g2"
    return pdk


def _pinned_pdk_version(family: str) -> Optional[str]:
    """The exact version LibreLane pins for *family* (``pdk_hashes.yaml``).

    Computed on the host with no network — this is the version the flow and
    container mode's ``ciel.fetch`` will demand, so it's the one we must
    install. Delegates to :func:`lanex.controller.pdk.required_pdk_version`.
    """
    try:
        from . import pdk as _pdk

        return _pdk.required_pdk_version(family)
    except Exception:
        return None


def _get_pdk_version(family: str) -> Optional[str]:
    """Resolve the PDK version to install.

    Prefer the version **LibreLane pins** (:func:`_pinned_pdk_version`) so the
    install matches what a run resolves — installing the *newest* instead was
    the bug behind "reinstalled but still ✗ not installed" in container mode.
    Fall back to the newest remote (``ciel ls-remote``, newest-first on a
    non-TTY stdout) only when the pinned hash can't be determined.
    """
    pinned = _pinned_pdk_version(family)
    if pinned:
        return pinned
    ciel_argv = _ciel_argv()
    if ciel_argv is None:
        return None
    try:
        proc = subprocess.run(
            ciel_argv + ["ls-remote", "--pdk-family", family],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith(("failed", "you don't", "error")) or line.startswith("["):
            continue
        return line
    return None


def _ciel_cmd(verb: str, pdk_root: str, pdk: str, libraries: Optional[List[str]] = None) -> Optional[List[str]]:
    """Build a ``ciel fetch``/``ciel enable`` argv, or ``None`` if no version.

    The version is a *required* positional argument for both verbs, so we must
    resolve it up front. When ``libraries`` is omitted we let ciel pick its
    default set for the family (which matches what LibreLane needs); when an
    explicit list is given we pass it through.
    """
    family = _pdk_family(pdk)
    version = _get_pdk_version(family)
    if not version:
        return None
    cmd = ["ciel", verb, "--pdk-root", pdk_root, "--pdk-family", family, version]
    for lib in libraries or []:
        cmd.extend(["-l", lib])
    return cmd


def _ciel_fetch_cmd(pdk_root: str, pdk: str, libraries: Optional[List[str]] = None) -> Optional[List[str]]:
    return _ciel_cmd("fetch", pdk_root, pdk, libraries)


def _ciel_enable_cmd(pdk_root: str, pdk: str, libraries: Optional[List[str]] = None) -> Optional[List[str]]:
    return _ciel_cmd("enable", pdk_root, pdk, libraries)


def _ciel_provision_script(pdk_root: str, pdk: str, libraries: Optional[List[str]], *,
                           prefix: str = "", ciel_cmd: str = "ciel") -> str:
    """POSIX-sh that fetches+enables the version LibreLane pins, then enables it.

    The pinned hash is resolved on the host (no network) and baked into the
    script as a literal, so the install matches what a run resolves. Only when
    the pinned hash is unavailable do we fall back to resolving the newest
    version inside the script (``ciel ls-remote`` is newest-first on a non-TTY
    stdout) — that branch also covers strategies that must install ciel first.

    *ciel_cmd* is how the script invokes ciel — ``"ciel"`` when the CLI is on
    PATH, or ``"<python> -m ciel"`` for venv/pipx installs where the module is
    importable but the console script isn't exposed.
    """
    family = _pdk_family(pdk)
    lib_args = "".join(f" -l {lib}" for lib in (libraries or []))
    pre = (prefix + " && ") if prefix else ""
    pinned = _pinned_pdk_version(family)
    if pinned:
        ver_assign = f'PDK_VERSION="{pinned}"; '
    else:
        ver_assign = (
            f'PDK_VERSION="$({ciel_cmd} ls-remote --pdk-family {family} | head -n1)"; '
            f'if [ -z "$PDK_VERSION" ]; then echo "ERROR: could not resolve a {family} version '
            f'(no network or ciel not reachable)"; exit 3; fi; '
        )
    # A fetch cut off mid-download (a slow/flaky link on a multi-GB PDK) leaves a
    # half-extracted version directory. ciel's own retry then fails with
    # ``[Errno 13] Permission denied`` on it and EVERY retry repeats the same
    # error — the root cause of the "PDK install permanently stuck" reports. So
    # before each retry we clear ONLY the interrupted version dir: surgical (never
    # touches other installed PDKs) and owner-scoped (no sudo — the user owns
    # their ciel store; ``chmod -R u+w`` re-opens any directory ciel wrote without
    # a write bit, which is exactly what a bare ``rm`` would otherwise choke on).
    # This also self-heals a store already wedged by a previous interrupted run.
    ver_dir = f'"{pdk_root}/ciel/{family}/versions/$PDK_VERSION"'
    return (
        f"{pre}"
        f"{ver_assign}"
        f'echo "Installing {family} version $PDK_VERSION"; '
        f"for i in 1 2 3 4 5; do "
        f'{ciel_cmd} fetch --pdk-root "{pdk_root}" --pdk-family {family} "$PDK_VERSION"{lib_args} && break; '
        f"echo 'ciel fetch failed; clearing the interrupted partial download and retrying in 2s...'; "
        f"chmod -R u+w {ver_dir} 2>/dev/null || true; rm -rf {ver_dir} 2>/dev/null || true; "
        f"sleep 2; done && "
        f'{ciel_cmd} enable --pdk-root "{pdk_root}" --pdk-family {family} "$PDK_VERSION"{lib_args}'
    )


@_pdk_strategy(["ciel"], "ciel fetch+enable", priority=5)
def _pdk_strategy_ciel_direct(env: Dict[str, Any], pdk: str, libraries: Optional[List[str]] = None) -> Optional[List[str]]:
    pdk_root = os.environ.get("PDK_ROOT") or ciel_home()
    ciel_cmd = _ciel_shell_cmd()
    if ciel_cmd is None:
        return None
    return ["sh", "-c", _ciel_provision_script(pdk_root, pdk, libraries, ciel_cmd=ciel_cmd)]


@_pdk_strategy(["pip"], "pip → ciel fetch+enable", priority=10)
def _pdk_strategy_ciel(env: Dict[str, Any], pdk: str, libraries: Optional[List[str]] = None) -> Optional[List[str]]:
    if _ciel_shell_cmd() is not None:
        return None  # Direct strategy already tried and failed; do not retry.
    import shlex

    pdk_root = os.environ.get("PDK_ROOT") or ciel_home()
    # pip installs ciel into THIS interpreter's environment, so invoke both pip
    # and (afterwards) ciel through sys.executable — `python3` could be a
    # different (PEP 668-guarded system) interpreter, and the fresh ciel console
    # script may land in a bin dir that's not on PATH.
    py = shlex.quote(sys.executable or "python3")
    return ["sh", "-c", _ciel_provision_script(
        pdk_root, pdk, libraries,
        prefix=f"{py} -m pip install ciel",
        ciel_cmd=f"{py} -m ciel",
    )]


@_pdk_strategy(["conda"], "conda → ciel fetch+enable", priority=20)
def _pdk_strategy_conda_ciel(env: Dict[str, Any], pdk: str, libraries: Optional[List[str]] = None) -> Optional[List[str]]:
    if _ciel_shell_cmd() is not None:
        return None
    pdk_root = os.environ.get("PDK_ROOT") or ciel_home()
    conda = "mamba" if _check_cmd("mamba") else "conda"
    return ["sh", "-c", _ciel_provision_script(pdk_root, pdk, libraries, prefix=f"{conda} install -c conda-forge -y ciel")]


# ---------------------------------------------------------------------------
# Install execution
# ---------------------------------------------------------------------------

def _install_env() -> Dict[str, str]:
    """Environment for an install subprocess (PEP-668 bypass + Linux-only PATH)."""
    from . import platform_env

    env = os.environ.copy()
    env.pop("PIP_REQUIRE_VIRTUALENV", None)
    if env.get("GITHUB_TOKEN", "").startswith("github_pat_antigravity"):
        env.pop("GITHUB_TOKEN", None)
    env["PIP_BREAK_SYSTEM_PACKAGES"] = "1"
    # On WSL, keep package managers / build tools from resolving Windows binaries
    # on the inherited /mnt/c PATH.
    env["PATH"] = platform_env.linux_only_path(env.get("PATH"))
    return env


def _run_argv_on_tty(argv: List[str], *, label: str, key: str) -> Dict[str, Any]:
    """Run a privileged install attached to the controlling terminal.

    ``sudo`` prompts for the password on the terminal where the GUI was
    launched; its output goes there too (not the browser), so we only report the
    final result. POSIX only — the caller gates this on ``has_controlling_tty``.
    """
    try:
        tty_fd = os.open("/dev/tty", os.O_RDWR)
    except OSError as ex:
        guidance = ("Couldn't open the terminal for the password prompt (" + str(ex) +
                    "). Run it yourself, then click Recheck:\n    " + " ".join(argv))
        _emit("installer_error", {"key": key, "label": label, "message": guidance})
        return {"ok": False, "rc": None, "needs_sudo": True, "guidance": guidance, "label": label}
    try:
        proc = subprocess.Popen(argv, stdin=tty_fd, stdout=tty_fd, stderr=tty_fd,
                                env=_install_env())
        _active_installs[key] = proc

        def _watchdog() -> None:
            if proc.poll() is None:
                _emit("installer_line", {"key": key, "line":
                      f"Timed out after {_INSTALL_TIMEOUT_S}s — terminating.", "label": label})
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

        wd = threading.Timer(_INSTALL_TIMEOUT_S, _watchdog)
        wd.daemon = True
        wd.start()
        try:
            proc.wait()
        finally:
            wd.cancel()
            _active_installs.pop(key, None)
        rc = proc.returncode
        _emit("installer_done", {"key": key, "rc": rc, "label": label})
        return {"ok": rc == 0, "rc": rc, "output": [], "label": label}
    except Exception as ex:
        _emit("installer_error", {"key": key, "error": str(ex), "label": label})
        return {"ok": False, "rc": None, "error": str(ex), "label": label}
    finally:
        try:
            os.close(tty_fd)
        except OSError:
            pass


def _run_argv(argv: List[str], *, label: str, key: str,
              timeout_s: Optional[float] = None) -> Dict[str, Any]:
    """Run an install command, streaming output to the event bus.

    *timeout_s* overrides the default watchdog ceiling — the image pull passes a
    higher one because a multi-GB download on a slow line legitimately exceeds
    the 1-hour default (the engine resumes cached layers on retry, but killing a
    healthy download is still wrong)."""
    deadline_s = float(timeout_s or _INSTALL_TIMEOUT_S)
    # A sudo command can't prompt for a password through the browser. Rather than
    # give up, escalate: prompt on the terminal the GUI was launched from (the
    # reliable path on WSL), else a graphical pkexec dialog. Only fall back to a
    # copy-paste command when neither is possible.
    from . import platform_env
    inherit_tty = False
    if _needs_sudo(argv):
        have_tty = platform_env.has_controlling_tty()
        passwordless = _can_sudo()
        if have_tty:
            # ALWAYS attach a sudo command to the launching terminal when one
            # exists — even if `sudo -n true` just succeeded. The non-tty branch
            # below sets start_new_session=True (so cancel/timeout can kill the
            # whole tree), which drops the controlling terminal; sudo's default
            # `tty_tickets` keys the cached credential to that tty, so a detached
            # sudo re-authenticates with no terminal and dies
            # "sudo: A terminal is required to authenticate" — exactly the failure
            # the user hit installing GDS3D deps. Attaching to /dev/tty lets sudo
            # find its ticket (silent when cached) or prompt (when not).
            inherit_tty = True
            if not passwordless:
                _emit("installer_info", {"key": key, "label": label, "needs_password": True, "message":
                    "Administrator rights needed. A password prompt is waiting in the TERMINAL "
                    "where you launched LanEx — switch to that window and enter your password to "
                    "continue. (For security, sudo cannot prompt inside the browser.)"})
        elif not passwordless:
            # No terminal: fall back to a graphical pkexec dialog, else a
            # copy-paste command.
            esc = _escalate_argv(argv)
            if esc is None:
                cmd = " ".join(argv)
                guidance = (
                    "This step needs root, but there's no terminal or graphical prompt available to "
                    "enter a password. Run it yourself, then click Recheck:\n    " + cmd
                )
                _emit("installer_error", {"key": key, "label": label, "message": guidance})
                return {"ok": False, "rc": None, "needs_sudo": True, "guidance": guidance, "label": label}
            argv, inherit_tty = esc
            if argv and argv[0] == "pkexec":
                _emit("installer_info", {"key": key, "label": label, "needs_password": True, "message":
                    "Administrator rights needed. A system password dialog should appear — enter "
                    "your password to continue the install."})
    _emit("installer_started", {"key": key, "argv": argv, "label": label})
    if inherit_tty:
        return _run_argv_on_tty(argv, label=label, key=key)
    try:
        # PEP 668 bypass so pip works system-wide (typical on Debian/Ubuntu);
        # Linux-only PATH so WSL doesn't resolve Windows build tools.
        settings: Dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "bufsize": 1,
            "text": True,
            "env": _install_env(),
        }
        if sys.platform == "win32":
            settings["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        elif os.name == "posix":
            # Own process group, so cancel/timeout can kill the WHOLE tree —
            # `sh -c` strategies spawn grandchildren (ciel/pip/curl) that a plain
            # terminate() would orphan mid-download. (The tty path deliberately
            # does NOT do this: a new session has no controlling terminal, which
            # would break sudo's /dev/tty password prompt.)
            settings["start_new_session"] = True
        proc = subprocess.Popen(argv, **settings)
        _active_installs[key] = proc
        # Watchdog: kill a wedged install after the ceiling so it can't hold the
        # in-progress lock (and the UI) forever.
        timed_out = {"hit": False}

        def _watchdog() -> None:
            if proc.poll() is None:
                timed_out["hit"] = True
                _emit("installer_line", {"key": key, "line": f"Timed out after {int(deadline_s)}s — terminating.", "label": label})
                _kill_proc_tree(proc, grace=5.0)

        wd = threading.Timer(deadline_s, _watchdog)
        wd.daemon = True
        wd.start()
        out_lines: List[str] = []
        try:
            for line in proc.stdout:
                line = line.rstrip()
                out_lines.append(line)
                _emit("installer_line", {"key": key, "line": line, "label": label})
            proc.wait()
        finally:
            wd.cancel()
            _active_installs.pop(key, None)

        rc = proc.returncode
        _emit("installer_done", {"key": key, "rc": rc, "label": label})
        return {
            "ok": rc == 0,
            "rc": rc,
            "output": out_lines,
            "label": label,
        }
    except Exception as ex:
        _emit("installer_error", {"key": key, "error": str(ex), "label": label})
        return {
            "ok": False,
            "error": str(ex),
            "label": label,
        }


def _verify_install(key: str) -> bool:
    """Check if a tool/PDK is now installed after a strategy attempt."""
    mapping = {
        "yosys": lambda: _check_cmd("yosys") or _check_cmd("yowasp-yosys"),
        # NOTE: there is no `yowasp-openroad` package — OpenROAD has no WASM/pip
        # build. Only a native binary counts as installed.
        "openroad": lambda: _check_cmd("openroad"),
        "klayout": lambda: _check_cmd("klayout"),
        "magic": lambda: _check_cmd("magic"),
        "netgen": lambda: _check_cmd("netgen"),
        "verilator": lambda: _check_cmd("verilator"),
        "iverilog": lambda: _check_cmd("iverilog") and _check_cmd("vvp"),
        # Module-aware: in a pipx/venv install the console script is off PATH
        # but `python -m ciel` / `python -m pip` work fine.
        "ciel": lambda: _check_cmd("ciel") or _py_module_available("ciel"),
        "pip": lambda: _check_cmd("pip") or _check_cmd("pip3") or _py_module_available("pip"),
        "python": lambda: True,
        "librelane": lambda: _check_cmd("librelane"),
        "docker": lambda: _check_cmd("docker"),
        "podman": lambda: _check_cmd("podman"),
        "gds3d": lambda: _check_cmd("gds3d") or (Path.home() / ".local" / "bin" / "gds3d").exists(),
        "graphviz": lambda: _check_cmd("dot"),
    }
    checker = mapping.get(key)
    if checker is None:
        return False
    return checker()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_GDS3D_REPO = "https://github.com/trilomix/GDS3D"

# The Debian/Ubuntu dev packages GDS3D's Linux build needs. build-essential gives
# git/make/g++; the rest provide the X11 + OpenGL/GLUT headers it #includes
# (X11/keysym.h, GL/gl.h, GL/glu.h, GL/glut.h) — missing on stock WSL/Ubuntu.
_GDS3D_APT_PACKAGES = [
    "git", "build-essential", "libx11-dev", "libxmu-dev", "libxi-dev",
    "libgl1-mesa-dev", "libglu1-mesa-dev", "freeglut3-dev",
]
_GDS3D_APT_DEPS_CMD = "sudo apt-get install -y " + " ".join(_GDS3D_APT_PACKAGES)

# RUNTIME (not build) dependency: the legacy X11 ``-misc-fixed-`` bitmap fonts.
# GDS3D requests the classic ``fixed`` font for its menus and dereferences a NULL
# when it's absent — an instant segfault the moment the window opens, which a
# fresh WSL/Ubuntu hits because it ships none of these fonts. Installing
# ``xfonts-base`` fixes it (user-confirmed).
_GDS3D_FONT_PACKAGES = ["xfonts-base"]
_GDS3D_FONT_CMD = "sudo apt-get install -y " + " ".join(_GDS3D_FONT_PACKAGES)


def ensure_x11_fixed_fonts() -> Dict[str, Any]:
    """Make GDS3D's legacy X11 ``fixed`` fonts present, installing them if needed.

    Called at GDS3D launch time so the user never has to discover + run the apt
    command by hand (the fonts can go missing after install, e.g. a system
    cleanup). Uses the same escalation as every other install: passwordless sudo
    if available, else a one-time terminal/pkexec password (``_run_argv``), and
    streams progress over the existing SSE bus. Returns ``{ok, ...}``; ``ok`` True
    means present (or just installed). On a non-apt distro or when escalation
    isn't possible it returns ``ok: False`` + the exact manual command instead of
    blocking. Safe to call repeatedly; no-op when the fonts already look present.
    """
    from . import platform_env
    present = platform_env.x11_fixed_fonts_present()
    if present is not False:
        # True (present) or None (can't tell) — never block on an uncertain probe.
        return {"ok": True, "already": True}
    if not shutil.which("apt-get"):
        return {"ok": False, "need": "x11-fonts", "manual": _GDS3D_FONT_CMD,
                "error": "Legacy X11 fonts (xfonts-base) are missing and this isn't a "
                         "Debian/apt system. Install the equivalent fonts package, then retry."}
    res = _run_argv(["sudo", "apt-get", "install", "-y"] + _GDS3D_FONT_PACKAGES,
                    label="xfonts-base (GDS3D fonts)", key="xfonts-base")
    installed = bool(res.get("ok")) and platform_env.x11_fixed_fonts_present() is not False
    out: Dict[str, Any] = dict(res)
    out["ok"] = installed
    if not installed:
        out.setdefault("need", "x11-fonts")
        out.setdefault("manual", _GDS3D_FONT_CMD)
    return out

# RUNTIME dependency for every native GL viewer (GDS3D, KLayout, OpenROAD GUI):
# Mesa's DRI drivers. Fresh minimal WSL/Ubuntu images ship WITHOUT
# libgl1-mesa-dri, leaving the tool with no renderer at all — the blank
# `[WARN: COPY MODE]` window class of bugs. Installing this set provides BOTH
# the software rasterizer (llvmpipe/swrast — what our WSL default uses) and the
# WSLg d3d12 hardware driver.
_GL_RUNTIME_PACKAGES = ["libgl1", "libgl1-mesa-dri", "libegl1"]
_GL_RUNTIME_CMD = "sudo apt-get install -y " + " ".join(_GL_RUNTIME_PACKAGES)


def gl_runtime_guidance() -> str:
    """Per-distro guidance for installing the Mesa GL runtime drivers."""
    return (
        "The Mesa OpenGL drivers are missing, so a desktop GL viewer has no way "
        "to render (blank window / hang). Install them, then retry:\n"
        "    Debian/Ubuntu/WSL: " + _GL_RUNTIME_CMD + "\n"
        "    Fedora/RHEL: sudo dnf install -y mesa-dri-drivers mesa-libGL mesa-libEGL\n"
        "    Arch: sudo pacman -S --needed mesa"
    )


def ensure_gl_runtime() -> Dict[str, Any]:
    """Make Mesa's DRI GL drivers present, installing them if needed (Linux).

    Called before a native GL tool launch so the user never has to discover the
    missing-`libgl1-mesa-dri` failure mode by staring at a blank window. Same
    escalation as every other install (passwordless sudo, else a one-time
    terminal/pkexec password, streamed over SSE). Returns ``{ok, ...}``; on a
    non-apt distro or when escalation isn't possible it returns ``ok: False``
    plus the exact manual commands instead of blocking. No-op when the drivers
    already look present or when we can't tell (never block on an uncertain
    probe).
    """
    from . import platform_env

    present = platform_env.mesa_dri_present()
    if present is not False:
        return {"ok": True, "already": True}
    if not shutil.which("apt-get"):
        return {"ok": False, "need": "gl-runtime", "manual": _GL_RUNTIME_CMD,
                "error": gl_runtime_guidance()}
    res = _run_argv(["sudo", "apt-get", "install", "-y"] + _GL_RUNTIME_PACKAGES,
                    label="Mesa GL drivers (libgl1-mesa-dri)", key="gl-runtime")
    installed = bool(res.get("ok")) and platform_env.mesa_dri_present() is not False
    out: Dict[str, Any] = dict(res)
    out["ok"] = installed
    if not installed:
        out.setdefault("need", "gl-runtime")
        out.setdefault("manual", _GL_RUNTIME_CMD)
        out.setdefault("error", gl_runtime_guidance())
    return out


# Header → the Debian package that provides it, for the dev-dependency check.
_GDS3D_HEADER_PACKAGES = {
    "X11/keysym.h": "libx11-dev",
    "GL/gl.h": "libgl1-mesa-dev",
    "GL/glu.h": "libglu1-mesa-dev",
    "GL/glut.h": "freeglut3-dev",
}


def _header_present(header: str) -> bool:
    """True if a C/C++ system header is findable in the usual include roots."""
    roots = [
        "/usr/include", "/usr/local/include",
        "/usr/include/x86_64-linux-gnu", "/usr/include/aarch64-linux-gnu",
        os.environ.get("CPATH", ""), os.environ.get("C_INCLUDE_PATH", ""),
    ]
    extra = os.environ.get("CPLUS_INCLUDE_PATH", "")
    for chunk in (os.environ.get("CPATH", ""), extra):
        roots.extend(p for p in chunk.split(os.pathsep) if p)
    for root in roots:
        if root and Path(root, header).is_file():
            return True
    return False


def _missing_gds3d_dev_packages() -> List[str]:
    """Debian dev packages whose headers GDS3D needs but that are absent.

    Only meaningful on Linux (header-file check). Returns ``[]`` on macOS/Windows
    (handled separately) or when all headers are already present.
    """
    if not sys.platform.startswith("linux"):
        return []
    missing: List[str] = []
    for header, pkg in _GDS3D_HEADER_PACKAGES.items():
        if not _header_present(header) and pkg not in missing:
            missing.append(pkg)
    return missing


def _x11_fixed_fonts_missing() -> bool:
    """True when GDS3D's required legacy X11 fonts look absent (Linux only).

    Conservative: only ``True`` when we can positively tell the fonts are
    missing, so we never add a needless apt package on an uncertain probe.
    """
    from . import platform_env

    return platform_env.x11_fixed_fonts_present() is False


def _gds3d_dep_guidance(packages: List[str]) -> str:
    """Per-distro guidance for installing GDS3D's missing dev headers."""
    apt = "sudo apt-get install -y " + " ".join(packages)
    return (
        "GDS3D's build needs development headers that aren't installed "
        "(it #includes X11/keysym.h and OpenGL/GLUT headers). Install them, then "
        "click Build again:\n"
        "    Debian/Ubuntu/WSL: " + apt + "\n"
        "    Fedora/RHEL: sudo dnf install -y libX11-devel mesa-libGL-devel "
        "mesa-libGLU-devel freeglut-devel gcc-c++ make git\n"
        "    Arch: sudo pacman -S --needed libx11 mesa glu freeglut base-devel git"
    )


def _rosetta_present() -> Optional[bool]:
    """Is Rosetta 2 installed on this Apple Silicon Mac? None when unknowable.

    The GDS3D repo ships an Intel (x86_64) prebuilt app; on arm64 it runs only
    under Rosetta 2. ``oahd`` is Rosetta's launch daemon; the runtime file is
    the fallback probe. Never raises."""
    try:
        if Path("/Library/Apple/usr/share/rosetta/rosetta").exists():
            return True
        rc = subprocess.run(["/usr/bin/pgrep", "-q", "oahd"],
                            capture_output=True, timeout=5).returncode
        return rc == 0
    except Exception:
        return None


def _gds3d_darwin_script(src: Path, bindir: Path) -> str:
    """The shell script that installs GDS3D on macOS.

    The repo's ``mac/`` directory has NO Makefile — it holds an Xcode project
    plus a prebuilt, self-contained ``GDS3D.app`` (x86_64, links only system
    frameworks). Running ``make`` there fails with "No targets specified and no
    makefile found", which is exactly the bug this replaces. So on macOS the
    install is: clone/update the repo, verify the prebuilt binary, and drop a
    tiny exec wrapper at ``~/.local/bin/gds3d`` that runs the binary IN PLACE
    (moving it out of the .app would break its bundle resource lookup)."""
    import shlex
    q = shlex.quote
    app_bin = src / "mac" / "GDS3D.app" / "Contents" / "MacOS" / "GDS3D"
    wrapper = bindir / "gds3d"
    return (
        "set -e; "
        f"mkdir -p {q(str(src.parent))} {q(str(bindir))}; "
        f"if [ -d {q(str(src))}/.git ]; then cd {q(str(src))}; git pull --ff-only || true; "
        f"else git clone --depth 1 {q(_GDS3D_REPO)} {q(str(src))}; fi; "
        f'if [ ! -x {q(str(app_bin))} ]; then '
        'echo "ERROR: the repo no longer ships the prebuilt macOS app"; exit 1; fi; '
        # git clones carry no quarantine attr, but clear it anyway (harmless).
        f"xattr -dr com.apple.quarantine {q(str(app_bin.parent.parent.parent))} 2>/dev/null || true; "
        f"printf '#!/bin/sh\\nexec %s \"$@\"\\n' {q(str(app_bin))} > {q(str(wrapper))}; "
        f"chmod +x {q(str(wrapper))}; "
        f"test -x {q(str(wrapper))}; "
        f"echo installed to {q(str(wrapper))}"
    )


def _install_gds3d_darwin() -> Dict[str, Any]:
    """GDS3D on macOS: use the prebuilt app the repo ships (no build).

    Prerequisite is git only — but macOS's ``/usr/bin/git`` is a shim that pops
    a GUI "install the developer tools?" dialog when the Command Line Tools are
    absent, so check ``xcode-select -p`` first and give the exact command
    instead of a mystery non-zero exit."""
    try:
        rc = subprocess.run(["xcode-select", "-p"], capture_output=True,
                            timeout=10).returncode
    except Exception:
        rc = 1
    if rc != 0:
        g = ("git needs Apple's Command Line Tools. Run `xcode-select --install`, "
             "finish the dialog, then click Install again.")
        _emit("installer_error", {"key": "gds3d", "message": g})
        return {"ok": False, "guidance": g, "reason": g}

    from . import platform_env
    home = platform_env.home()
    src = home / "tools" / "GDS3D"
    bindir = Path.home() / ".local" / "bin"
    script = _gds3d_darwin_script(src, bindir)
    res = _run_argv(["bash", "-lc", script], label="gds3d (prebuilt macOS app)", key="gds3d")
    if _is_cancelled("gds3d"):
        return _cancelled_result("gds3d")
    if res.get("rc") == 0 and (bindir / "gds3d").exists():
        msg = f"GDS3D installed → {bindir / 'gds3d'} (prebuilt app from the GDS3D repo)."
        if platform_machine() == "arm64" and _rosetta_present() is False:
            msg += (" NOTE: the binary is Intel-only and this Mac has no Rosetta 2 — run "
                    "`softwareupdate --install-rosetta --agree-to-license` once, or GDS3D "
                    "will fail with 'Bad CPU type in executable'.")
        _emit("installer_info", {"key": "gds3d", "message": msg})
        return {"ok": True, "method": "prebuilt", "label": "gds3d (prebuilt macOS app)",
                "path": str(bindir / "gds3d")}
    g = ("Couldn't install the prebuilt GDS3D app — see the Install logs. Fallbacks: "
         f"open {_GDS3D_REPO} → mac/GDS3D.xcodeproj in Xcode and build it yourself, "
         "or use the 2D viewers (KLayout/Magic), which don't need GDS3D.")
    _emit("installer_error", {"key": "gds3d", "message": g})
    return {"ok": False, "reason": g, "guidance": g, "rc": res.get("rc")}


def _install_gds3d() -> Dict[str, Any]:
    """Guided install of GDS3D (the open-source 3D GDS viewer).

    GDS3D has no package-manager release. Linux: build the small OpenGL binary
    from source into ``~/.local/bin`` (the repo's ``linux/`` tree has the
    Makefile). macOS: the repo ships a prebuilt ``GDS3D.app`` — install that
    (the ``mac/`` tree has an Xcode project, NO Makefile, so a source build is
    not a one-click path there). Windows: point at the prebuilt binary. Streams
    progress via the same installer events; honest guidance on failure."""
    import shlex

    if sys.platform == "win32":
        g = ("GDS3D ships a prebuilt Windows binary — download it from "
             f"{_GDS3D_REPO}/releases, put gds3d.exe on your PATH, then click Recheck.")
        _emit("installer_error", {"key": "gds3d", "message": g})
        return {"ok": False, "guidance": g, "reason": g}

    if sys.platform == "darwin":
        return _install_gds3d_darwin()

    missing = [t for t in ("git", "make") if not shutil.which(t)]
    if not (shutil.which("g++") or shutil.which("clang++") or shutil.which("cc")):
        missing.append("a C++ compiler")
    if missing:
        # Only the apt path can auto-install the toolchain. Inside the bundled
        # LibreLane image (Nix base, no apt) GDS3D simply can't be built, so don't
        # show Debian instructions that will never apply — be honest about it.
        if detect_environment().get("apt"):
            g = ("GDS3D builds from source and needs: " + ", ".join(missing) +
                 ". On Debian/Ubuntu: " + _GDS3D_APT_DEPS_CMD + ". "
                 "Then click Build again, or use the manual steps in Tools.")
        else:
            g = ("GDS3D is a desktop OpenGL viewer and is not bundled in this image — "
                 "it needs a build toolchain (git, make, a C++ compiler) plus an X11 "
                 "display, which the headless container doesn't have. The web cockpit "
                 "doesn't need it; run LanEx on a host with those tools to use GDS3D. "
                 "Missing here: " + ", ".join(missing) + ".")
        _emit("installer_error", {"key": "gds3d", "message": g})
        return {"ok": False, "guidance": g, "reason": g}

    # GDS3D's Linux build includes <X11/keysym.h> + OpenGL/GLUT headers. Their dev
    # packages are missing on a stock WSL/Ubuntu, so make aborts with
    # "fatal error: X11/keysym.h: No such file or directory". Detect the missing
    # dev headers up front; auto-install them when apt + non-interactive sudo are
    # available, otherwise return the exact package list instead of a doomed build.
    # Install the build headers AND the runtime fonts in one apt call so GDS3D
    # both compiles and doesn't segfault on first launch. `_run_argv` now
    # escalates on its own (terminal prompt / pkexec), so we no longer require
    # passwordless sudo here — only that apt exists.
    env = detect_environment()
    header_pkgs = _missing_gds3d_dev_packages()
    font_pkgs = _GDS3D_FONT_PACKAGES if _x11_fixed_fonts_missing() else []
    # GDS3D is a GL app: without Mesa's DRI drivers (fresh minimal WSL/Ubuntu
    # ships none) it opens a blank window or hangs — even software rendering
    # needs them (llvmpipe IS one of those drivers). Install them alongside.
    from . import platform_env as _penv
    gl_pkgs = _GL_RUNTIME_PACKAGES if _penv.mesa_dri_present() is False else []
    apt_pkgs = header_pkgs + font_pkgs + gl_pkgs
    if apt_pkgs:
        if env.get("apt"):
            apt = "apt-fast" if _check_cmd("apt-fast") else "apt-get"
            _emit("installer_info", {"key": "gds3d",
                  "message": "installing GDS3D dependencies: " + " ".join(apt_pkgs)})
            dep_res = _run_argv(["sudo", apt, "install", "-y"] + apt_pkgs,
                                label="gds3d dependencies (apt)", key="gds3d")
            if _is_cancelled("gds3d"):
                return _cancelled_result("gds3d")
            still = _missing_gds3d_dev_packages()
            if still:
                g = _gds3d_dep_guidance(still)
                _emit("installer_error", {"key": "gds3d", "message": g})
                return {"ok": False, "guidance": g, "reason": g, "rc": dep_res.get("rc")}
        elif header_pkgs:
            g = _gds3d_dep_guidance(header_pkgs)
            _emit("installer_error", {"key": "gds3d", "message": g})
            return {"ok": False, "guidance": g, "reason": g}

    from . import platform_env
    home = platform_env.home()
    src = home / "tools" / "GDS3D"
    bindir = Path.home() / ".local" / "bin"
    # Only the repo's linux/ tree has a Makefile (mac/ = Xcode project + prebuilt
    # app, handled above; win32 = prebuilt release, handled above).
    subdir = "linux"
    q = shlex.quote
    dest = bindir / "gds3d"
    # The Makefile emits the binary as 'GDS3D' (capital). Earlier we cp'd 'gds3d'
    # (lowercase) inside an `&&` list, where `set -e` is suppressed for non-final
    # commands — so the cp failed silently and the build "succeeded" with no
    # binary. Find whichever name make produced, copy it as a standalone command
    # (so set -e catches a real failure), then verify the destination exists.
    script = (
        "set -e; "
        f"mkdir -p {q(str(src.parent))} {q(str(bindir))}; "
        f"if [ -d {q(str(src))}/.git ]; then cd {q(str(src))}; git pull --ff-only || true; "
        f"else git clone --depth 1 {q(_GDS3D_REPO)} {q(str(src))}; fi; "
        f"cd {q(str(src))}/{subdir}; make; "
        'bin=""; for c in GDS3D gds3d; do [ -f "$c" ] && bin="$c" && break; done; '
        'if [ -z "$bin" ]; then echo "ERROR: build produced no GDS3D binary"; exit 1; fi; '
        f"cp \"$bin\" {q(str(dest))}; "
        f"chmod +x {q(str(dest))}; "
        f"test -x {q(str(dest))}; "
        f"echo installed to {q(str(dest))}"
    )
    res = _run_argv(["bash", "-lc", script], label="gds3d (source build)", key="gds3d")
    if _is_cancelled("gds3d"):
        return _cancelled_result("gds3d")
    if (res.get("rc") == 0) and (_verify_install("gds3d") or (bindir / "gds3d").exists()):
        _emit("installer_info", {"key": "gds3d",
              "message": f"GDS3D built → {bindir / 'gds3d'}. If 'gds3d' isn't found, add {bindir} to your PATH."})
        return {"ok": True, "method": "source", "label": "gds3d (source build)",
                "path": str(bindir / "gds3d")}
    g = ("GDS3D build didn't produce a binary — see Install logs. You can build it "
         "manually (steps in Tools → Desktop layout viewers).")
    return {"ok": False, "reason": g, "guidance": g, "rc": res.get("rc")}


def _brew_conflict_needs_force(output: str) -> bool:
    """Does this brew failure mean 'leftover files from a previous install'?

    A wiped/reinstalled Docker Desktop leaves its CLI symlinks behind
    (``/usr/local/bin/docker-credential-desktop`` etc.); the cask then aborts
    with "It seems there is already a Binary at …" (or "…an App at …").
    ``--force`` overwrites those leftovers — they're Docker's own files, so the
    retry is safe."""
    low = (output or "").lower()
    return "already a binary at" in low or "already an app at" in low


def _brew_no_bottle(output: str) -> bool:
    """Did brew refuse because no prebuilt bottle exists for this machine?

    Happens on Homebrew "Tier 3" configurations (an old macOS version, or an
    OS/CPU combo brew no longer builds for): ``Error: <formula>: no bottle
    available!``. A source build needs the full Go toolchain and is nothing
    like one-click, so route the user to Docker Desktop instead."""
    return "no bottle available" in (output or "").lower()


def _podman_path() -> Optional[str]:
    """Absolute path to ``podman`` right after a brew install (PATH-independent)."""
    from . import platform_env
    hit = platform_env.usable_which("podman")
    if hit:
        return hit
    for cand in ("/opt/homebrew/bin/podman", "/usr/local/bin/podman"):
        if os.access(cand, os.X_OK):
            return cand
    return None


def _setup_podman_machine(key: str = "podman") -> None:
    """One-time podman VM setup on macOS (best-effort, streamed, never raises).

    On macOS podman is only a client — every container runs in a Linux VM that
    ``podman machine init`` creates and ``podman machine start`` boots. A brew
    install without this step looks successful but the engine probe fails with
    a connection error, which reads like a broken install. Do it for the user."""
    podman = _podman_path()
    if not podman:
        return
    try:
        ls = subprocess.run([podman, "machine", "list", "--format", "{{.Name}}"],
                            capture_output=True, text=True, timeout=20)
        have_machine = bool((ls.stdout or "").strip())
    except Exception:
        have_machine = False
    if not have_machine:
        _emit("installer_info", {"key": key, "message":
              "setting up the podman virtual machine (one-time VM image download)…"})
        res = _run_argv([podman, "machine", "init"], label="podman machine init", key=key)
        if _is_cancelled(key) or res.get("rc") != 0:
            _emit("installer_info", {"key": key, "message":
                  "podman machine init didn't finish — run `podman machine init && "
                  "podman machine start` in a terminal, then click ‘Pull image’."})
            return
    res = _run_argv([podman, "machine", "start"], label="podman machine start", key=key)
    out = "\n".join(res.get("output") or [])
    if res.get("rc") == 0 or "already running" in out.lower():
        _emit("installer_info", {"key": key, "message":
              "podman machine is running — click ‘Pull image’ next."})
    else:
        _emit("installer_info", {"key": key, "message":
              "podman is installed but its VM didn't start — run `podman machine start` "
              "in a terminal, then click ‘Pull image’."})


def _install_engine_macos(key: str) -> Dict[str, Any]:
    """Docker Desktop / podman install on macOS, with the real-world failure
    modes handled instead of surfaced raw:

    * cask renamed ``docker`` → ``docker-desktop`` (use the current name);
    * leftover CLI symlinks from a previous Docker install → retry ``--force``;
    * Docker Desktop needs its app opened once (privileged helper + daemon) —
      open it and say so, or 'installed' still can't pull;
    * podman "no bottle available" (Tier-3 brew config) → honest routing to
      Docker Desktop rather than a doomed source build;
    * podman on macOS needs ``machine init``/``start`` before it works at all.
    """
    brew = _brew_path()
    if not brew:
        g = ("Homebrew isn't installed, and it's how LanEx installs engines on "
             "macOS. Install it from https://brew.sh, or install Docker Desktop "
             "directly: https://docs.docker.com/desktop/setup/install/mac-install/. "
             "Then click ‘Pull image’.")
        _emit("installer_error", {"key": key, "message": g})
        return {"ok": False, "reason": g, "guidance": g}

    if key == "docker":
        argv = [brew, "install", "--cask", "docker-desktop"]
        res = _run_argv(argv, label="brew install --cask docker-desktop", key=key)
        if _is_cancelled(key):
            return _cancelled_result(key)
        out = "\n".join(res.get("output") or [])
        if res.get("rc") != 0 and _brew_conflict_needs_force(out):
            _emit("installer_info", {"key": key, "message":
                  "a previous Docker install left files behind — retrying with "
                  "--force (only overwrites Docker's own leftover links)…"})
            res = _run_argv(argv + ["--force"],
                            label="brew install --cask docker-desktop --force", key=key)
            if _is_cancelled(key):
                return _cancelled_result(key)
        if res.get("rc") == 0 or _verify_install("docker"):
            # The daemon only exists once Docker.app has run (first launch
            # installs its privileged helper). Open it so 'installed' means
            # 'usable', not 'a binary exists'.
            try:
                subprocess.Popen(["open", "-a", "Docker"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            _emit("installer_info", {"key": key, "message":
                  "Docker Desktop installed. Opening it now — approve its first-run "
                  "prompts, wait for ‘Docker Desktop is running’, then click ‘Pull image’."})
            return {"ok": True, "method": "brew", "label": "brew install --cask docker-desktop"}
        g = ("Docker Desktop didn't install (see the Install logs). Manual path: "
             "download it from https://docs.docker.com/desktop/setup/install/mac-install/, "
             "open Docker.app once, then click ‘Pull image’.")
        _emit("installer_error", {"key": key, "message": g})
        return {"ok": False, "reason": g, "guidance": g, "rc": res.get("rc")}

    # podman
    res = _run_argv([brew, "install", "podman"], label="brew install podman", key=key)
    if _is_cancelled(key):
        return _cancelled_result(key)
    out = "\n".join(res.get("output") or [])
    if res.get("rc") != 0 and not _verify_install("podman"):
        if _brew_no_bottle(out):
            g = ("Homebrew has no prebuilt podman for this Mac (a 'Tier 3' setup — "
                 "usually an older macOS, or an OS/CPU combo brew stopped building "
                 "for). Building it from source needs the whole Go toolchain and "
                 "often fails. Recommended: install Docker Desktop instead (click "
                 "Install on the Docker card, or "
                 "https://docs.docker.com/desktop/setup/install/mac-install/). "
                 "If you really want podman: `brew install --build-from-source podman`.")
        else:
            g = ("podman didn't install (see the Install logs). Recommended on "
                 "macOS: Docker Desktop — click Install on the Docker card.")
        _emit("installer_error", {"key": key, "message": g})
        return {"ok": False, "reason": g, "guidance": g, "rc": res.get("rc")}
    _setup_podman_machine(key)
    return {"ok": True, "method": "brew", "label": "brew install podman"}


def install_tool(key: str) -> Dict[str, Any]:
    """Try every available strategy to install *key*.

    Re-detects environment after any strategy succeeds (rc=0) but verify
    fails — this handles cases like ``apt install python3-pip`` making pip
    available for a retry.

    Returns:
        {"ok": True, "method": "...", "label": "..."} on success, or
        {"ok": False, "tried": [...], "reason": "..."} if all fail.
    """
    if not _begin_job(key):
        return {
            "ok": False,
            "in_progress": True,
            "reason": f"{key} is already being installed — watch the logs (no second download started).",
        }
    try:
        if key == "gds3d":
            return _install_gds3d()
        if key in ("docker", "podman") and sys.platform == "darwin":
            return _install_engine_macos(key)
        return _install_tool_impl(key)
    finally:
        _end_job(key)


def install_tool_async(key: str) -> Dict[str, Any]:
    """Non-blocking :func:`install_tool` — the HTTP route's entry point.

    A tool install can legitimately take minutes (a GDS3D source build, apt on a
    slow mirror), far past any sane HTTP timeout — the synchronous route was why
    the UI showed "request timed out" while the build was actually fine. This
    returns ``{status: "started"}`` immediately and runs the install in a
    daemon thread; progress streams over the existing SSE ``installer_*`` events
    and the final outcome is emitted as an ``installer_result`` event carrying
    the same dict :func:`install_tool` returns.
    """
    if is_in_progress(key):
        return {"ok": True, "in_progress": True, "status": "already-running",
                "reason": f"{key} is already being installed — watch the logs (no second download started)."}

    def _worker() -> None:
        try:
            result = install_tool(key)
        except Exception as ex:  # never die silently in a daemon thread
            result = {"ok": False, "reason": f"{type(ex).__name__}: {ex}"}
        # The install just changed the very state check_tools() caches; drop
        # the cache so the UI's post-install refetch sees the new tool.
        try:
            from . import tools as _tools
            _tools._check_tools_cache.clear()
        except Exception:
            pass
        payload = {"key": key}
        payload.update(result if isinstance(result, dict) else {"ok": bool(result)})
        _emit("installer_result", payload)

    t = threading.Thread(target=_worker, daemon=True, name=f"installer_tool[{key}]")
    t.start()
    return {"ok": True, "status": "started", "key": key}


def _cancelled_result(key: str) -> Dict[str, Any]:
    """The uniform outcome for a user-cancelled install job."""
    _emit("installer_error", {"key": key, "message": "Installation cancelled by user."})
    return {"ok": False, "cancelled": True, "reason": "Installation cancelled by user."}


def _install_tool_impl(key: str) -> Dict[str, Any]:
    _emit("installer_info", {"key": key, "message": f"starting {key} install…"})
    env = detect_environment()
    tried: List[str] = []
    seen_labels: set = set()
    max_passes = 3
    for _ in range(max_passes):
        for strategy in _strategies_for(env):
            # A cancel must stop the whole job here — never start the next
            # strategy's download after the user said stop.
            if _is_cancelled(key):
                return _cancelled_result(key)
            label = strategy["label"]
            if label in seen_labels:
                continue
            seen_labels.add(label)
            prepare = strategy["prepare"]
            try:
                argv = prepare(env, key)
            except Exception as ex:
                tried.append(f"{label}: prepare failed ({ex})")
                continue
            if argv is None:
                tried.append(f"{label}: no recipe")
                continue
            if not argv:
                tried.append(f"{label}: skipped")
                continue
            result = _run_argv(argv, label=label, key=key)
            if _is_cancelled(key):
                return _cancelled_result(key)
            # Treat "the thing is now present" as success even when the command
            # returned non-zero. Common case: `apt install docker.io` installs
            # the binary fine but its postinst can't start the daemon in a
            # sandbox/container/WSL and returns non-zero — the tool IS installed.
            if _verify_install(key):
                _emit("installer_info", {
                    "key": key,
                    "message": f"{key} installed via {label}"
                    + ("" if result.get("ok") else f" (command exit {result.get('rc')}, but {key} is present)"),
                })
                return {
                    "ok": True,
                    "method": strategy["methods"][0],
                    "label": label,
                    "argv": argv,
                    "rc": result.get("rc"),
                }
            if result.get("ok"):
                # Command ran OK but verify failed — re-detect environment
                # so newly available tools (e.g. pip after apt installing
                # python3-pip) are visible next pass.
                env = detect_environment()
            tried.append(f"{label}: exit {result.get('rc', '?')}")
    guidance = _install_guidance(key)
    _emit("installer_error", {"key": key, "message": f"could not auto-install {key}. {guidance}"})
    return {
        "ok": False,
        "tried": tried,
        "reason": f"Couldn't auto-install {key} on this system. {guidance}",
        "guidance": guidance,
        "docs": "https://librelane.readthedocs.io/en/latest/getting_started/",
    }


# Tools with no universal package; point users at LibreLane's supported paths.
_HARD_TOOLS = {"openroad", "magic", "netgen"}


def _install_guidance(key: str) -> str:
    """Actionable next step when automatic install isn't possible here."""
    if key in ("docker", "podman"):
        return (
            "Install a container engine for the recommended run mode. Linux: "
            "`sudo apt install podman` (or Docker via https://get.docker.com). "
            "macOS: Docker Desktop (`brew install --cask docker-desktop`, then open "
            "Docker.app once) or `brew install podman` followed by "
            "`podman machine init && podman machine start`. Windows: Docker Desktop "
            "with the WSL2 backend. After installing, click ‘Pull image’."
        )
    if key in _HARD_TOOLS:
        return (
            f"{key} has no pip/apt/brew package. The supported ways to get the full "
            "toolchain are: (1) Nix — `curl -L https://nixos.org/nix/install | sh` then "
            "install via nixpkgs; (2) conda — `conda install -c litex-hub "
            f"{'openroad' if key=='openroad' else key}`; or (3) run LibreLane in its "
            "prebuilt container with `librelane --dockerized` (every tool included)."
        )
    return (
        f"Install {key} with your system package manager, or use the LibreLane "
        "container (`librelane --dockerized`) which bundles every tool."
    )


def install_pdk(pdk: str, libraries: Optional[List[str]] = None) -> Dict[str, Any]:
    """Try every available strategy to install a PDK in the background.

    Same multi-layer fallback as :func:`install_tool`, but non-blocking. A second
    request for a PDK that is already downloading is refused (no double download);
    ciel resumes from its tarball cache on a fresh attempt after an interruption.
    """
    key = f"pdk:{pdk}"
    if not _begin_job(key):
        return {"ok": True, "in_progress": True, "status": "already-running",
                "reason": f"{pdk} is already downloading — no second download started."}

    def _worker():
      try:
        from . import platform_env

        _emit("installer_info", {"key": f"pdk:{pdk}", "message": f"starting {pdk} PDK install…"})
        # Proactive DNS check — a PDK download (ciel fetch / volare) needs to
        # resolve github.com. On WSL2 a broken auto-generated /etc/resolv.conf is
        # a common, fixable cause of repeated timeouts; warn up front (don't block
        # — the user may have a cache/mirror) with the exact remediation.
        if platform_env.dns_ok() is False:
            rem = platform_env.network_remediation()
            if rem:
                _emit("installer_error", {"key": f"pdk:{pdk}", "message": rem})
        # A ciel store left root-owned by an earlier sudo run can't be written or
        # self-healed (our chmod/rm are owner-scoped) — every strategy would just
        # loop on the same 'Permission denied'. Detect it up front and surface the
        # one-click fix + exact chown command instead of burning retries.
        perm = ciel_permission_status()
        if perm.get("needs_root"):
            _emit("installer_info", {
                "key": f"pdk:{pdk}", "needs_root": True, "message": perm["message"],
                "fix": {"endpoint": "/api/pdk/fix-permissions", "label": "Fix permissions"},
            })
            _emit("installer_error", {
                "key": f"pdk:{pdk}",
                "message": ("PDK store has root-owned files — install can't write to it. "
                            "Use 'Fix permissions', or run:  " + perm["chown_cmd"]),
            })
            return
        env = detect_environment()
        tried: List[str] = []
        all_output: List[str] = []
        for strategy in _pdk_strategies_for(env):
            # Cancel stops the whole job — never fall through to the next
            # strategy's fresh multi-GB download after the user said stop.
            if _is_cancelled(key):
                _cancelled_result(key)
                return
            prepare = strategy["prepare"]
            try:
                argv = prepare(env, pdk, libraries)
            except Exception as ex:
                tried.append(f"{strategy['label']}: prepare failed ({ex})")
                continue
            if argv is None:
                tried.append(f"{strategy['label']}: no recipe")
                continue
            result = _run_argv(argv, label=strategy["label"], key=f"pdk:{pdk}")
            all_output.extend(result.get("output") or [])
            if _is_cancelled(key) or result.get("rc") in (-15, -9):
                _cancelled_result(key)
                return
            if result.get("ok"):
                _emit("installer_info", {
                    "key": f"pdk:{pdk}",
                    "message": f"{pdk} installed via {strategy['label']}",
                })
                # Re-emit done to signal success specifically to frontend installer component
                _emit("installer_done", {
                    "key": f"pdk:{pdk}",
                    "rc": 0,
                    "label": strategy["label"],
                    "method": strategy["methods"][0]
                })
                return
            tried.append(f"{strategy['label']}: exit {result.get('rc', '?')}")
        _emit("installer_error", {
            "key": f"pdk:{pdk}",
            "message": f"all install strategies failed for {pdk}",
        })
        # If the failures look network-related, surface the (often WSL2 DNS) fix.
        rem = platform_env.network_remediation("\n".join(all_output))
        if rem:
            _emit("installer_error", {"key": f"pdk:{pdk}", "message": rem})
      finally:
        _end_job(key)

    t = threading.Thread(target=_worker, daemon=True, name=f"installer_pdk[{pdk}]")
    t.start()
    return {
        "ok": True,
        "pid": "thread",
        "status": "started"
    }


def pull_image() -> Dict[str, Any]:
    """Pull the version-matched LibreLane container image, streaming output.

    This is the one host requirement for **container run mode** — a single
    ``docker``/``podman pull`` instead of installing six native EDA tools. The
    output streams over the same SSE installer channel (key ``container:image``)
    that the Tools tab already renders.
    """
    from .container_run import image_ref

    from . import tools

    if not (shutil.which("docker") or shutil.which("podman")):
        return {
            "ok": False,
            "reason": "No container engine found. Install Docker or Podman first.",
        }
    image = image_ref()

    # Pick a usable engine (Docker, Podman, or Docker-via-group-activation). Fail
    # fast with actionable guidance if none is usable yet — otherwise the pull
    # errors cryptically (or looks like a hang).
    resolved = tools.resolve_engine()
    if not resolved.get("ready"):
        return {
            "ok": False,
            "reason": "No usable container engine yet (installed but not reachable).",
            "guidance": (
                "Use the runtime card's one-click fixes: install Podman (rootless, "
                "works immediately) or enable Docker for your user. Then click ‘Pull image’."
            ),
        }
    engine = resolved["engine"]
    pull_cmd = [engine, "pull", image]
    if resolved.get("sg_wrap"):
        pull_cmd = tools.sg_wrap_argv([engine, "pull", image])

    key = "container:image"
    if not _begin_job(key):
        # Already pulling — don't start a second; the engine would re-fetch the
        # same layers. The frontend re-attaches to the running pull's stream.
        return {"ok": True, "in_progress": True, "status": "already-running", "image": image, "engine": engine}

    # Disk headroom warning (never blocks): the compressed download plus the
    # extracted layers need several GB. The engine's store usually lives on the
    # root filesystem; a best-effort probe there catches the common failure of
    # a pull dying at 90% with a cryptic "no space left on device".
    try:
        free_gb = shutil.disk_usage("/").free / (1024 ** 3)
        if free_gb < 12:
            _emit("installer_info", {"key": key, "message": (
                f"Low disk space: ~{free_gb:.1f} GB free on /. The LibreLane image needs "
                "roughly 10 GB (download + extracted layers) — the pull may fail with "
                "'no space left on device'. Free some space if it does.")})
    except Exception:
        pass

    def _worker():
        try:
            # 4h ceiling instead of the default 1h: a multi-GB pull on a slow
            # connection is healthy long past the generic install watchdog.
            res = _run_argv(pull_cmd, label=f"{engine} pull", key=key, timeout_s=4 * 3600)
            if res.get("ok"):
                record_image_digest(engine, image, sg_wrap=bool(resolved.get("sg_wrap")))
            else:
                from . import platform_env
                rem = platform_env.network_remediation("\n".join(res.get("output") or []))
                if rem:
                    _emit("installer_error", {"key": key, "message": rem})
        finally:
            _end_job(key)

    t = threading.Thread(target=_worker, daemon=True, name="installer_pull_image")
    t.start()
    return {"ok": True, "status": "started", "image": image, "engine": engine}


def record_image_digest(engine: str, image: str, *, sg_wrap: bool = False) -> Optional[str]:
    """Record the pulled image's immutable digest in ``$LANEX_HOME/image.lock``.

    Cheap upstream-independence insurance: if the registry ever re-tags or
    rebuilds ``:X.Y.Z``, the lock file proves which exact bytes this install
    validated against (``docker pull ghcr.io/...@sha256:...`` restores them).
    Purely a record — image resolution is unchanged (it stays LibreLane's own
    version-tag scheme). Best-effort; never raises; returns the digest or None.
    """
    try:
        argv = [engine, "image", "inspect", image, "--format", "{{index .RepoDigests 0}}"]
        if sg_wrap:
            from . import tools as _tools
            argv = _tools.sg_wrap_argv(argv)
        rc, out, _err = _shell_exec_quiet(argv, timeout=15.0)
        digest = (out or "").strip().splitlines()[0].strip() if rc == 0 and (out or "").strip() else ""
        from . import platform_env
        home = platform_env.home()
        home.mkdir(parents=True, exist_ok=True)
        (home / "image.lock").write_text(
            json.dumps({
                "image": image,
                "digest": digest,
                "engine": engine,
                "recorded": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }, indent=2) + "\n",
            encoding="utf-8",
        )
        return digest or None
    except Exception:
        return None


def enable_docker_group() -> Dict[str, Any]:
    """Add the current user to the ``docker`` group — no re-login required.

    Adding a user to ``docker`` normally only applies to new login sessions, but
    once the membership exists the GUI runs Docker via ``sg docker -c`` to
    activate it immediately for this session (see tools.resolve_engine). This is
    the convenient alternative to "log out and back in". Linux only.
    """
    import getpass

    if not sys.platform.startswith("linux"):
        return {
            "ok": False,
            "reason": "Group activation only applies on Linux. On macOS/Windows use Docker Desktop or Podman.",
        }
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USER") or "$USER"
    res = _run_argv(
        ["sudo", "usermod", "-aG", "docker", user],
        label="enable docker group", key="docker-group",
    )
    if res.get("ok"):
        return {
            "ok": True,
            "message": f"Added '{user}' to the docker group — no logout needed; "
            "the GUI activates it via 'sg'. Click Recheck.",
        }
    return {
        "ok": False,
        "rc": res.get("rc"),
        "reason": "Could not add you to the docker group (needs sudo).",
        "guidance": f"Run manually: sudo usermod -aG docker {user}  — then click Recheck.",
    }


def cancel_install(key: str) -> Dict[str, Any]:
    """Cancel a running install/download — the whole JOB, not just one process.

    Two defects this closes (the "I cancelled the PDK install and it kept
    downloading" bug): (1) killing only the current strategy's subprocess let
    the strategy loop move on and start the NEXT strategy's fresh download —
    the ``_cancelled`` flag now stops the loop at its next checkpoint; and
    (2) ``terminate()`` killed only the direct ``sh`` child while its ciel/pip
    grandchildren kept downloading as orphans — ``_kill_proc_tree`` now kills
    the whole process group.

    We deliberately **keep** the download cache (ciel's tarball store, docker's
    layer cache, apt/pip caches) so the next attempt RESUMES instead of starting
    a fresh multi-GB download — that's the whole point of "no double downloads".
    To actually reclaim the space, use Delete/Remove (uninstall), which removes
    the installed artefact itself.
    """
    running = is_in_progress(key)
    if running:
        _mark_cancelled(key)
    proc = _active_installs.get(key)
    if proc is not None:
        _kill_proc_tree(proc)
        return {"ok": True, "status": "cancelled"}
    if running:
        # Between strategies (or before the first subprocess spawned): the flag
        # alone stops the loop at its next checkpoint. The owning worker thread
        # releases the job key itself.
        return {"ok": True, "status": "cancelling"}
    _end_job(key)  # stale key hygiene (no worker owns it)
    return {"ok": False, "reason": "not running"}


def _uninstall_gds3d() -> Dict[str, Any]:
    """Remove the source-built GDS3D binary.

    GDS3D has no package-manager release (``_install_gds3d`` builds it from
    source), so removal = delete the binary from the two locations we install
    it to: ``~/.local/bin/gds3d`` (user-writable, no privileges) and
    ``/usr/local/bin/gds3d`` (needs root, via the same escalation installs use).
    Idempotent: removing one that isn't there still succeeds if the other went.
    """
    removed: List[str] = []
    failed: List[str] = []

    user_bin = Path.home() / ".local" / "bin" / "gds3d"
    if user_bin.exists():
        try:
            user_bin.unlink()
            removed.append(str(user_bin))
        except OSError as ex:
            failed.append(f"{user_bin}: {ex}")

    sys_bin = Path("/usr/local/bin/gds3d")
    if sys_bin.exists():
        res = _run_argv(["sudo", "rm", "-f", str(sys_bin)], label="rm gds3d", key="gds3d")
        if not sys_bin.exists():
            removed.append(str(sys_bin))
        else:
            failed.append(f"{sys_bin}: exit {res.get('rc', '?')}")

    if removed and not failed:
        return {"ok": True, "method": "rm", "key": "gds3d", "removed": removed}
    if removed:
        return {"ok": True, "method": "rm", "key": "gds3d", "removed": removed,
                "warning": "some copies could not be removed: " + "; ".join(failed)}
    if failed:
        return {"ok": False, "tried": failed, "reason": "Could not remove the GDS3D binary"}
    return {"ok": False, "tried": [],
            "reason": "GDS3D binary not found in ~/.local/bin or /usr/local/bin (already removed?)"}


def uninstall_tool(key: str) -> Dict[str, Any]:
    """Try to uninstall a tool via pip or system package manager."""
    if key == "gds3d":
        return _uninstall_gds3d()

    env = detect_environment()
    tried: List[str] = []
    cmds = []

    if env.get("pip") or env.get("pip3"):
        pip_map = {
            "yosys": ["python3", "-m", "pip", "uninstall", "-y", "yowasp-yosys"],
            # (no openroad pip package exists — see _verify_install)
            "verilator": ["python3", "-m", "pip", "uninstall", "-y", "verilator"],
            "ciel": ["python3", "-m", "pip", "uninstall", "-y", "ciel"],
            "librelane": ["python3", "-m", "pip", "uninstall", "-y", "librelane"],
        }
        if key in pip_map:
            cmds.append(("pip uninstall", pip_map[key]))

    if env.get("apt"):
        apt = "apt-fast" if _check_cmd("apt-fast") else "apt-get"
        apt_map = {
            "yosys": ["sudo", apt, "remove", "-y", "yosys"],
            "openroad": ["sudo", apt, "remove", "-y", "openroad"],
            "klayout": ["sudo", apt, "remove", "-y", "klayout"],
            "magic": ["sudo", apt, "remove", "-y", "magic"],
            "netgen": ["sudo", apt, "remove", "-y", "netgen"],
            "verilator": ["sudo", apt, "remove", "-y", "verilator"],
            "iverilog": ["sudo", apt, "remove", "-y", "iverilog"],
            "graphviz": ["sudo", apt, "remove", "-y", "graphviz"],
            # Let users remove an engine and switch (e.g. drop Docker for Podman).
            "docker": ["sudo", apt, "remove", "-y", "docker.io"],
            "podman": ["sudo", apt, "remove", "-y", "podman"],
        }
        if key in apt_map:
            cmds.append(("apt remove", apt_map[key]))

    if env.get("brew"):
        brew_map = {
            "iverilog": ["brew", "uninstall", "icarus-verilog"],
            "graphviz": ["brew", "uninstall", "graphviz"],
            "yosys": ["brew", "uninstall", "yosys"],
            "verilator": ["brew", "uninstall", "verilator"],
            "magic": ["brew", "uninstall", "magic"],
        }
        if key in brew_map:
            cmds.append(("brew uninstall", brew_map[key]))

    if env.get("conda"):
        conda = "mamba" if _check_cmd("mamba") else "conda"
        conda_map = {
            "iverilog": [conda, "remove", "-y", "iverilog"],
            "graphviz": [conda, "remove", "-y", "graphviz"],
            "yosys": [conda, "remove", "-y", "yosys"],
            "verilator": [conda, "remove", "-y", "verilator"],
        }
        if key in conda_map:
            cmds.append(("conda remove", conda_map[key]))

    for label, argv in cmds:
        result = _run_argv(argv, label=label, key=key)
        if result.get("ok"):
            return {"ok": True, "method": label, "key": key}
        tried.append(f"{label}: exit {result.get('rc', '?')}")

    return {"ok": False, "tried": tried, "reason": "No uninstall method succeeded"}


def uninstall_pdk(pdk: str) -> Dict[str, Any]:
    """Remove every installed version of *pdk*'s family via ciel.

    ``ciel rm`` requires the exact ``<VERSION (HASH)>`` **and** the right
    ``--pdk-root`` (a family may have several versions, possibly spread across
    ``$PDK_ROOT`` and ``~/.ciel``). So we enumerate what's actually installed —
    read-only, across all ciel homes — and remove each. ciel's own ``rm`` clears
    the enabled-variant symlink (``unset_current``) before deleting the version
    dir, so no manual filesystem surgery (which would mishandle the symlinks) is
    needed. Idempotent: removing a family that isn't installed succeeds.
    """
    from . import pdk as pdk_mod

    family = _pdk_family(pdk)
    versions = pdk_mod.installed_pdk_versions(pdk)
    if not versions:
        manual = pdk_mod.manual_pdk_dirs(pdk)
        if manual:
            return {
                "ok": False,
                "key": pdk,
                "reason": (
                    "PDK is not ciel-managed (manual/volare install); ciel can't remove it. "
                    "Delete it by hand: " + ", ".join(manual)
                ),
            }
        return {"ok": True, "method": "noop", "key": pdk, "note": "no installed versions found"}

    ciel_argv = _ciel_argv()
    if ciel_argv is None:
        return {
            "ok": False,
            "tried": ["ciel not found"],
            "reason": "ciel is required to remove a PDK (it clears the enabled symlink and version store).",
        }

    import ciel  # type: ignore

    removed: List[str] = []
    tried: List[str] = []
    for version, home in versions:
        result = _run_argv(
            ciel_argv + ["rm", "--pdk-root", home, "--pdk-family", family, version, "--yes"],
            label="ciel rm",
            key=f"pdk:{pdk}",
        )
        try:
            still_there = ciel.Version(name=version, pdk=family).is_installed(home)
        except Exception:
            still_there = not result.get("ok")
        if result.get("ok") or not still_there:
            removed.append(f"{version[:12]}…@{home}")
        else:
            tried.append(f"ciel rm {version[:12]}… @ {home}: exit {result.get('rc', '?')}")

    if removed:
        return {"ok": True, "method": "ciel rm", "key": pdk, "removed": removed, "tried": tried}
    return {"ok": False, "tried": tried, "reason": "Could not remove PDK"}


# ---- Legacy API (backward compat) ----

def install_popen(argv: List[str]) -> Dict[str, Any]:
    """Kick off an install via raw argv. Returns ``{"ok", "pid", "argv"}``."""
    if not argv:
        return {"ok": False, "reason": "no command to run"}
    try:
        settings: Dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "bufsize": 1,
            "text": True,
        }
        if sys.platform == "win32":
            settings["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.Popen(argv, **settings)
        _emit("installer_started", {"argv": argv, "pid": p.pid})

        def _reader():
            try:
                for line in p.stdout:
                    _emit("installer_line", {"line": line.rstrip(), "pid": p.pid, "argv": argv})
            except Exception:
                pass
            rc = p.wait()
            _emit("installer_done", {"rc": rc, "pid": p.pid, "argv": argv})

        t = threading.Thread(target=_reader, daemon=True, name=f"installer[{p.pid}]")
        t.start()
        return {"ok": True, "pid": p.pid, "argv": argv}
    except Exception as ex:
        return {"ok": False, "reason": f"{type(ex).__name__}: {ex}"}


def install_ciel(pdk: str, *, until_version: Optional[str] = None) -> Dict[str, Any]:
    """Install a PDK via ciel (legacy, synchronous path). Falls back to multi-layer."""
    pdk_root = os.environ.get("PDK_ROOT") or ciel_home()
    if _ciel_shell_cmd() is None:
        ciel_result = install_tool("ciel")
        if not ciel_result.get("ok"):
            return install_pdk(pdk)
    script = _ciel_provision_script(pdk_root, pdk, None, ciel_cmd=_ciel_shell_cmd() or "ciel")
    return _run_argv(["sh", "-c", script], label="ciel fetch+enable", key=f"pdk:{pdk}")
