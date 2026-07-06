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
"""System + tool orchestration.

This module is **read-only** by default; it inspects the host for the tools
LibreLane shells out to plus the ``ciel`` PDK store, then surfaces
whether they're installed. We deliberately do NOT run installs at import
time to keep the GUI usable even when the host is missing everything.

The accompanying ``installer.py`` (separate module so that, when installed
without internet, the rest still imports) shells out to ``pip``,
``ciel``, ``brew`` or ``apt-get`` and streams its stdout back.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import to_json


def _subprocess_settings() -> Dict[str, Any]:
    """Shared subprocess settings for all tool interactions.

    Ensures consistent Windows/Mac/Linux flags (CREATE_NO_WINDOW on
    Windows, universal pipe setup).
    """
    settings: Dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "bufsize": 1,
        "text": True,
    }
    if sys.platform == "win32":
        settings["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return settings


# ---------------------------------------------------------------------------
# Each tool has: a ``key`` (used as id), a ``label``, a list of binary names
# to probe (first hit wins), a ``version_flag`` (each must be a list-form
# argv), an ``install`` recipe, and a "what it does" sentence.
#
# Binary search paths include ``yowasp-*`` WASM builds (platform-agnostic,
# no native dependencies) for macOS/Windows users who can't easily install
# native tools. See https://yowasp.org.
# ---------------------------------------------------------------------------

# Rough installed-footprint estimates, in MB. These are deliberately
# APPROXIMATE order-of-magnitude figures (a native build's real size varies by
# platform, build flags, and shared libraries) and are always surfaced to the
# user with an explicit "~ approx" label — never presented as exact. For an
# installed tool we cannot cheaply measure the full dependency closure, so the
# estimate stands; for PDKs (below) we measure the real on-disk size instead.
_APPROX_TOOL_MB: Dict[str, int] = {
    "python": 120,
    "pip": 20,
    "librelane": 60,
    "yosys": 120,
    "openroad": 500,
    "klayout": 250,
    "magic": 40,
    "netgen": 25,
    "verilator": 120,
    "iverilog": 30,
    "graphviz": 40,
    "ciel": 15,
}

# Container-engine minimum versions LibreLane itself checks for (see
# librelane/container.py: container_version_error). Kept as constants so the UI
# can warn on an outdated engine without importing a private helper.
_ENGINE_MIN_VERSION = {"docker": "25.0.5", "podman": "4.1.0"}

EDA_TOOLS: List[Dict[str, Any]] = [
    {
        "key": "python",
        "label": "Python",
        "binary": [sys.executable],
        "version_flag": ["--version"],
        "install": None,
        "what": "Python interpreter that runs LibreLane itself.",
        "category": "core",
    },
    {
        "key": "pip",
        "label": "pip",
        "binary": ["pip", "pip3"],
        "version_flag": ["--version"],
        "install": ["python3", "-m", "pip", "install", "--upgrade", "pip"],
        "what": "Python package manager. Needed to install LibreLane and plugins.",
        "category": "core",
    },
    {
        "key": "librelane",
        "label": "LibreLane",
        "binary": ["librelane"],
        "version_flag": ["--bare-version"],
        "install": ["python3", "-m", "pip", "install", "--upgrade", "librelane"],
        "what": "The flow orchestrator itself.",
        "category": "core",
    },
    {
        "key": "yosys",
        "label": "Yosys",
        "binary": [
            "yosys",
            "/opt/yosys/bin/yosys",
            "yowasp-yosys",
        ],
        "version_flag": ["--version"],
        "install": {
            "linux": "apt:yosys",
            "darwin": "brew:yosys",
            "windows": "pip install yowasp-yosys",
        },
        "what": "Logic synthesis: turns your Verilog RTL into a gate-level netlist.",
        "category": "eda",
    },
    {
        "key": "openroad",
        "label": "OpenROAD",
        "binary": [
            "openroad",
            "OpenROAD",
        ],
        "version_flag": ["-version"],
        "install": {
            "linux": "conda install -c litex-hub openroad  (or Nix, or `librelane --dockerized`)",
            "darwin": "conda install -c litex-hub openroad  (or Nix, or `librelane --dockerized`)",
            "windows": "Use WSL2, then conda/Nix; or run `librelane --dockerized`.",
        },
        "what": "PnR (place-and-route) and STA. The biggest, slowest tool in the chain.",
        "category": "eda",
        # No pip/apt/brew package exists. The supported way to get it is the
        # version-matched LibreLane container (or conda/Nix for advanced users),
        # so the GUI points at "Pull image" instead of a host Install button.
        "container_only": True,
    },
    {
        "key": "klayout",
        "label": "KLayout",
        "binary": ["klayout", "KLayout"],
        "version_flag": ["-v"],
        "install": {
            "linux": "https://www.klayout.de/build.html",
            "darwin": "brew:klayout",
            "windows": "https://www.klayout.de/build.html",
        },
        "what": "Layout viewer/editor; renders the GDS preview you see at the end.",
        "category": "eda",
    },
    {
        "key": "magic",
        "label": "Magic",
        "binary": ["magic"],
        "version_flag": ["--version"],
        "install": {
            "linux": "conda install -c litex-hub magic  (or Nix `magic-vlsi`, or `librelane --dockerized`)",
            "darwin": "conda install -c litex-hub magic  (or Nix `magic-vlsi`, or `librelane --dockerized`)",
            "windows": "Use WSL2, then conda/Nix; or run `librelane --dockerized`.",
        },
        "what": "Layout editor; performs signoff DRC and writes the canonical GDSII.",
        "category": "eda",
        "container_only": True,
    },
    {
        "key": "netgen",
        "label": "Netgen",
        "binary": ["netgen"],
        "version_flag": ["-h"],
        "install": {
            "linux": "conda install -c litex-hub netgen  (or Nix `netgen-lvs`, or `librelane --dockerized`)",
            "darwin": "conda install -c litex-hub netgen  (or Nix `netgen-lvs`, or `librelane --dockerized`)",
            "windows": "Use WSL2, then conda/Nix; or run `librelane --dockerized`.",
        },
        "what": "LVS checker: verifies that the routed layout matches your RTL.",
        "category": "eda",
        "container_only": True,
    },
    {
        "key": "verilator",
        "label": "Verilator",
        "binary": ["verilator"],
        "version_flag": ["--version"],
        "install": {
            "linux": "apt:verilator",
            "darwin": "brew:verilator",
            "windows": "WSL2 recommended",
        },
        "what": "Verilog linter; catches RTL issues before they reach synthesis.",
        "category": "eda",
    },
    {
        "key": "iverilog",
        "label": "Icarus Verilog",
        "binary": ["iverilog"],
        "version_flag": ["-V"],
        "install": {
            "linux": "apt:iverilog",
            "darwin": "brew:icarus-verilog",
            "windows": "WSL2 recommended",
        },
        "what": "Event-driven Verilog simulator (iverilog + vvp) for the RTL IDE's "
                "simulation window — best for classic 4-state testbenches with delays. "
                "Optional; not used by the hardening flow.",
        "category": "eda",
        "optional": True,
    },
    {
        "key": "graphviz",
        "label": "Graphviz",
        "binary": ["dot"],
        "version_flag": ["-V"],
        "install": {
            "linux": "apt:graphviz",
            "darwin": "brew:graphviz",
            "windows": "choco install graphviz",
        },
        "what": "Renders the synthesis RTL/netlist schematics (the .dot files Yosys "
                "writes when SYNTH_SHOW is on) into viewable diagrams. Optional; "
                "only needed for the Reports & diagrams view.",
        "category": "eda",
        "optional": True,
    },
    {
        "key": "ciel",
        "label": "Ciel (PDK store)",
        "binary": ["ciel"],
        "version_flag": ["--version"],
        "install": ["python3", "-m", "pip", "install", "--upgrade", "ciel"],
        "what": "Manages PDK installs (sky130A/B/C, gf180mcu, IHP-SG13G2…).",
        "category": "pdk",
    },
]


# ---------------------------------------------------------------------------
# PDK catalog. The list of families, variants, and libraries is read from
# ``ciel`` itself (the PDK manager LibreLane uses) so it is always accurate and
# never goes stale. We add only short, factual, foundry/node descriptions —
# nothing about densities, metal stacks, or shuttle history that we cannot
# verify from the source.
# ---------------------------------------------------------------------------

# Human-readable, defensible facts keyed by ciel family name.
_FAMILY_FACTS: Dict[str, Dict[str, str]] = {
    "sky130": {
        "foundry": "SkyWater Technology",
        "node": "130 nm",
        "description": (
            "SkyWater 130 nm open PDK — the most widely used process for "
            "open-source tapeouts. Variant A is the default; variant B adds "
            "ReRAM/SONOS device models."
        ),
        # Approximate full-family download; the actual size depends on which
        # libraries you select (always labelled "~ approx" in the UI).
        "approx_gb": 2.5,
    },
    "gf180mcu": {
        "foundry": "GlobalFoundries",
        "node": "180 nm",
        "description": (
            "GlobalFoundries 180 nm MCU open PDK. Variants A–D differ in the "
            "available standard-cell / option set; D is ciel's default."
        ),
        "approx_gb": 1.8,
    },
    "ihp-sg13g2": {
        "foundry": "IHP",
        "node": "130 nm SiGe BiCMOS",
        "description": (
            "IHP SG13G2 — 130 nm SiGe BiCMOS open PDK with high-frequency "
            "bipolar devices, suited to RF and analog/mixed-signal designs."
        ),
        "approx_gb": 1.9,
    },
}


def _family_registry() -> Dict[str, Any]:
    try:
        from ciel.common import Family  # type: ignore

        return dict(getattr(Family, "by_name", {}) or {})
    except Exception:
        return {}


def build_pdk_catalog() -> Dict[str, Dict[str, Any]]:
    """Build the per-variant PDK catalog from ciel's authoritative metadata."""
    catalog: Dict[str, Dict[str, Any]] = {}
    for fam_name, fam in _family_registry().items():
        facts = _FAMILY_FACTS.get(fam_name, {})
        variants = list(getattr(fam, "variants", []) or [fam_name])
        default_variant = getattr(fam, "default_variant", None)
        libraries = list(getattr(fam, "all_libraries", []) or [])
        default_includes = list(getattr(fam, "default_includes", []) or [])
        for variant in variants:
            catalog[variant] = {
                "label": variant,
                "family": fam_name,
                "foundry": facts.get("foundry", ""),
                "node": facts.get("node", ""),
                "description": facts.get("description", ""),
                "recommended": variant == default_variant,
                "libraries": libraries,
                "default_libraries": default_includes,
                "approx_gb": facts.get("approx_gb"),
            }
    return catalog


# Backwards-compatible module attribute (some callers/tests import this name).
PDK_CATALOG: Dict[str, Dict[str, Any]] = build_pdk_catalog()


# ---------------------------------------------------------------------------

def _shell_exec(argv: List[str], timeout: float = 4.0) -> Tuple[int, str, str]:
    """Run ``argv``; return (returncode, stdout, stderr); bound by timeout.

    Uses cross-platform flags (e.g. CREATE_NO_WINDOW on Windows).
    """
    try:
        kwargs: Dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "check": False,
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        out = subprocess.run(argv, **kwargs)
        return out.returncode, (out.stdout or "").strip(), (out.stderr or "").strip()
    except FileNotFoundError as ex:
        return 127, "", f"file not found: {ex}"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as ex:
        return 1, "", f"{type(ex).__name__}: {ex}"


def _version_string(blob: str) -> str:
    """Pick the most-likely version-looking line out of a stdout blob."""
    for line in (blob or "").splitlines():
        # match ``Foo 1.2.3`` or ``FooBar 1.2``
        m = re.search(r"(\d+\.\d+(?:\.\d+)?(?:[\.\-a-z0-9]*)?)", line)
        if m:
            return line.strip()[:120]
    return (blob or "").splitlines()[0].strip()[:120] if blob else ""


def _probe(binaries: List[str], version_flag: List[str]) -> Dict[str, Any]:
    """Return ``{installed, path, version, error}``.

    Under WSL the Linux ``PATH`` includes the Windows ``PATH`` (``/mnt/c/...``),
    so a tool installed natively on Windows (e.g. ``verilator.exe``) resolves but
    is NOT usable by the Linux-side LibreLane flow. We skip such hits and, if no
    native Linux build is found, report it as missing with an explanatory note so
    the GUI offers the Linux install instead of falsely showing "installed".
    """
    from . import platform_env

    wsl = platform_env.is_wsl()
    win_only_path: Optional[str] = None
    for candidate in binaries:
        if not candidate:
            continue
        cp = Path(candidate)
        if cp.is_absolute():
            if not cp.is_file():
                continue
            argv = [str(cp)] + (version_flag or [])
        else:
            found = shutil.which(candidate)
            if not found:
                continue
            argv = [found] + (version_flag or [])
        if wsl and platform_env.is_windows_mount_path(argv[0]):
            # A Windows binary on the WSL PATH — record it but keep looking for a
            # real Linux build before giving up.
            if win_only_path is None:
                win_only_path = argv[0]
            continue
        rc, out, err = _shell_exec(argv, timeout=4.0)
        if rc == 0:
            return {
                "installed": True,
                "path": argv[0],
                "version": _version_string(out) or _version_string(err),
                "error": "",
            }
        # Some tools (e.g. magic) print version to stderr and exit non-zero.
        if rc != 127 and (out.strip() or err.strip()):
            return {
                "installed": True,
                "path": argv[0],
                "version": _version_string(out) or _version_string(err),
                "error": f"exit code {rc}",
            }
    if win_only_path:
        return {
            "installed": False,
            "path": "",
            "version": "",
            "error": (
                "found a Windows build on the WSL PATH (" + win_only_path + "), "
                "but it can't be used by the Linux flow — install the Linux build "
                "inside WSL (or use the container image)."
            ),
            "windows_only": True,
        }
    return {
        "installed": False,
        "path": "",
        "version": "",
        "error": "no candidate binary found on PATH",
    }


def _platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


def _module_available(mod: str) -> bool:
    """Importable in THIS interpreter (pipx/venv installs keep the console
    scripts off the system PATH while the module works fine)."""
    try:
        import importlib.util
        return importlib.util.find_spec(mod) is not None
    except Exception:
        return False


def _module_version(pkg: str) -> str:
    try:
        import importlib.metadata
        return importlib.metadata.version(pkg)
    except Exception:
        return ""


def _module_probe_fallback(key: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """When a PATH probe found nothing, check the GUI's own Python environment.

    Under pipx (`pipx install lanex`) only the ``lanex`` entry point is exposed;
    ``librelane``, ``ciel`` and ``pip`` live inside the venv, importable and
    fully usable via ``python -m …`` — reporting them "not installed" was a lie
    that sent users off to install a second copy. Only used when the PATH probe
    failed, so a real system install always wins the display.
    """
    if info.get("installed"):
        return info
    mod = {"librelane": "librelane", "ciel": "ciel", "pip": "pip"}.get(key)
    if not mod or not _module_available(mod):
        return info
    py = sys.executable or "python3"
    return {
        "installed": True,
        "path": f"{py} -m {mod}",
        "version": _module_version(mod),
        "error": "",
    }


def _recipe_for(tool: Dict[str, Any]) -> str:
    """Format the install recipe as a UI-friendly line."""
    install = tool.get("install")
    if not install:
        return ""
    if isinstance(install, list):
        # A pip-style list — render as a single copyable command.
        return " ".join(install)
    pk = _platform_key()
    return str(install.get(pk, ""))


# A PDK tree is hundreds of thousands of files; sizing six of them cold took
# tens of seconds and made /api/tools appear hung. Sizes barely change, so
# cache per path and give the walk a deadline — an unfinished walk returns
# None (the UI simply omits the size) rather than a made-up partial number.
_DIR_SIZE_TTL_S = 600.0
_dir_size_cache: Dict[str, Tuple[float, Optional[int]]] = {}


def _dir_size_mb(path: Path, *, deadline_s: float = 3.0) -> Optional[int]:
    """Real on-disk size of a directory tree, in MB (best-effort, bounded).

    Used for *installed* PDKs so we show a measured number instead of guessing.
    Walks with ``os.scandir`` and silently skips unreadable entries.
    """
    key = str(path)
    hit = _dir_size_cache.get(key)
    now = time.time()
    if hit and (now - hit[0]) < _DIR_SIZE_TTL_S and hit[1] is not None:
        return hit[1]
    stop_at = now + deadline_s
    try:
        total = 0
        stack = [str(path)]
        while stack:
            if time.time() > stop_at:
                _dir_size_cache[key] = (now, None)
                return None
            d = stack.pop()
            try:
                with os.scandir(d) as it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                            else:
                                total += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            continue
            except OSError:
                continue
        result = int(total / (1024 * 1024))
        _dir_size_cache[key] = (now, result)
        return result
    except Exception:
        return None


def _version_tuple(s: str) -> Tuple[int, ...]:
    """Best-effort numeric version tuple from a version string."""
    m = re.search(r"(\d+(?:\.\d+){1,3})", s or "")
    if not m:
        return ()
    return tuple(int(x) for x in m.group(1).split("."))


# ``<engine> info`` against a hung daemon blocks until its timeout, and one
# status call fans out into several probes (docker, podman, docker-via-sg —
# from both resolve_engine and container_engine). Uncached at 12s each that
# stacked past 30s and froze /api/tools + /api/preflight on hosts with a
# wedged Docker (observed live). A short TTL keeps the answer fresh (a daemon
# started mid-window is seen on the next probe) while collapsing the fan-out
# to at most one real probe per engine per window.
_ENGINE_PROBE_TTL_S = 8.0
_engine_probe_cache: Dict[str, Tuple[float, Tuple[bool, str]]] = {}


def _engine_usable(engine: str, *, via_sg: bool = False) -> Tuple[bool, str]:
    """Is the engine actually usable (daemon reachable / store ready)?

    ``<engine> info`` exits 0 only when usable. ``via_sg`` runs it through
    ``sg docker -c`` so we can tell whether Docker-group activation (without a
    re-login) would work.
    """
    key = f"{engine}:sg={via_sg}"
    hit = _engine_probe_cache.get(key)
    now = time.time()
    if hit and (now - hit[0]) < _ENGINE_PROBE_TTL_S:
        return hit[1]
    cmd = ["sg", "docker", "-c", "docker info"] if via_sg else [engine, "info"]
    rc, out, err = _shell_exec(cmd, timeout=6.0)
    if rc == 0:
        result: Tuple[bool, str] = (True, "")
    else:
        lines = (err or out or "").strip().splitlines()
        result = (False, (lines[-1][:200] if lines else f"{engine} not reachable"))
    _engine_probe_cache[key] = (now, result)
    return result


def _docker_group_status() -> Tuple[bool, bool, bool]:
    """Return (in_group_db, active_in_session, sg_available) for the docker group.

    On Linux, adding a user to the ``docker`` group only takes effect in new
    login sessions — but ``sg docker -c <cmd>`` activates it immediately for a
    single command. So if the user is a member in the group database but it
    isn't active in this session, and ``sg`` exists, we can use Docker now
    without asking them to log out and back in.
    """
    if not sys.platform.startswith("linux"):
        return (False, False, False)
    sg_ok = shutil.which("sg") is not None
    try:
        import grp
        import getpass

        g = grp.getgrnam("docker")
        user = getpass.getuser()
        in_db = (user in g.gr_mem) or (g.gr_gid == os.getgid())
        active = g.gr_gid in os.getgroups()
        return (bool(in_db), bool(active), sg_ok)
    except Exception:
        return (False, False, sg_ok)


def sg_wrap_argv(argv: List[str]) -> List[str]:
    """Wrap a command so it runs with the ``docker`` group active (no re-login)."""
    import shlex

    return ["sg", "docker", "-c", shlex.join(argv)]


def resolve_engine() -> Dict[str, Any]:
    """Single source of truth for which engine to use and how to invoke it.

    Preference: a usable Docker → a usable Podman → Docker via ``sg`` group
    activation. Returns ``{engine, ready, sg_wrap, env}`` where ``env`` forces
    LibreLane to the chosen engine via the documented ``LIBRELANE_CONTAINER_ENGINE``
    variable (so a present-but-unusable Docker never shadows a working Podman).
    """
    res: Dict[str, Any] = {"engine": None, "ready": False, "sg_wrap": False, "env": {}}
    docker_path = shutil.which("docker")
    podman_path = shutil.which("podman")
    if docker_path and _engine_usable("docker")[0]:
        res.update(engine="docker", ready=True, env={"LIBRELANE_CONTAINER_ENGINE": "docker"})
    elif podman_path and _engine_usable("podman")[0]:
        res.update(engine="podman", ready=True, env={"LIBRELANE_CONTAINER_ENGINE": "podman"})
    elif docker_path:
        in_db, active, sg_ok = _docker_group_status()
        if in_db and not active and sg_ok and _engine_usable("docker", via_sg=True)[0]:
            res.update(
                engine="docker", ready=True, sg_wrap=True,
                env={"LIBRELANE_CONTAINER_ENGINE": "docker"},
            )
    return res


def container_engine() -> Dict[str, Any]:
    """Rich runtime-engine status for the Tools tab.

    Reports both engines, the chosen usable one (possibly Podman even when an
    unusable Docker is installed, or Docker activated via ``sg``), the image
    state, and everything the UI needs to offer convenient one-click fixes
    (install Podman, enable Docker for your user without a re-login, remove an
    engine).
    """
    from .container_run import image_ref

    image = image_ref()
    docker_path = shutil.which("docker")
    podman_path = shutil.which("podman")
    docker_usable, docker_msg = _engine_usable("docker") if docker_path else (False, "")
    podman_usable, podman_msg = _engine_usable("podman") if podman_path else (False, "")
    in_db, active, sg_ok = _docker_group_status()

    resolved = resolve_engine()
    engine = resolved["engine"]
    ready = resolved["ready"]
    sg_wrap = resolved["sg_wrap"]

    version = ""
    version_ok = True
    min_version = _ENGINE_MIN_VERSION.get(engine or "", "")
    if engine:
        _rc, vout, verr = _shell_exec([engine, "--version"], timeout=6.0)
        version = _version_string(vout) or _version_string(verr)
        if min_version:
            ev, mv = _version_tuple(version), _version_tuple(min_version)
            version_ok = (not ev) or ev >= mv

    image_present = False
    image_size_mb: Optional[int] = None
    if ready and engine:
        inspect = ["image", "inspect", image, "--format", "{{.Size}}"]
        cmd = sg_wrap_argv(["docker"] + inspect) if sg_wrap else [engine] + inspect
        rc, out, _err = _shell_exec(cmd, timeout=10.0)
        image_present = rc == 0
        if image_present:
            try:
                image_size_mb = int(int(out.strip().splitlines()[0]) / (1024 * 1024))
            except Exception:
                image_size_mb = None

    daemon_msg = ""
    if not ready:
        if docker_path and not docker_usable:
            daemon_msg = docker_msg
        elif podman_path and not podman_usable:
            daemon_msg = podman_msg

    return {
        "available": bool(docker_path or podman_path),
        "engine": engine,
        "ready": ready,
        "sg_wrap": sg_wrap,
        "version": version,
        "min_version": min_version,
        "version_ok": version_ok,
        "daemon_ok": ready,
        "daemon_msg": daemon_msg,
        "image": image,
        "image_present": image_present,
        "image_size_mb": image_size_mb,
        "image_approx_mb": 3000,
        "docker": {
            "present": bool(docker_path),
            "usable": docker_usable,
            "msg": docker_msg,
            "group_in_db": in_db,
            "group_active": active,
            "sg_available": sg_ok,
            # Can we get Docker working for this user without a re-login?
            "group_fixable": bool(docker_path and not docker_usable and sg_ok),
        },
        "podman": {"present": bool(podman_path), "usable": podman_usable, "msg": podman_msg},
    }


# Full probe = a dozen version subprocesses + engine probes + PDK sizing; the
# SPA calls /api/tools on tab open and preflight polls too. 8s of freshness is
# plenty (installs take minutes and re-query long after expiry) and turns
# repeat calls into dict lookups instead of multi-second re-probes.
_CHECK_TOOLS_TTL_S = 8.0
_check_tools_cache: List[Tuple[float, Dict[str, Any]]] = []


def check_tools(*, force: bool = False) -> Dict[str, Any]:
    """Probe every tool and return a JSON-safe dict (TTL-cached).

    Each tool gets: ``key, label, installed, path, version, what,
    category, install_recipe``. ``force=True`` bypasses the cache (used right
    after an install/uninstall mutates the very state this reports).
    """
    if not force and _check_tools_cache:
        ts, cached = _check_tools_cache[0]
        if (time.time() - ts) < _CHECK_TOOLS_TTL_S:
            return cached
    out = []
    for t in EDA_TOOLS:
        info = _probe(t["binary"], t["version_flag"])
        info = _module_probe_fallback(t["key"], info)
        out.append(
            {
                "key": t["key"],
                "label": t["label"],
                "what": t.get("what", ""),
                "category": t.get("category", "eda"),
                "installed": info["installed"],
                "path": info["path"],
                "version": info["version"],
                "error": info["error"],
                "install_recipe": _recipe_for(t),
                "platform": _platform_key(),
                "approx_mb": _APPROX_TOOL_MB.get(t["key"]),
                # No host package — get it via the container image (Pull image).
                "container_only": bool(t.get("container_only", False)),
                # A Windows build was found on the WSL PATH but isn't usable by the
                # Linux flow (so it's reported missing, with this flag for the UI).
                "windows_only": bool(info.get("windows_only", False)),
            }
        )

    # Installed PDKs: a variant is "installed" when it has been enabled into the
    # PDK root (i.e. ``$PDK_ROOT/<variant>/libs.ref`` exists). This is exactly
    # what LibreLane resolves at run time, and what the catalog keys against.
    ciel_probe = _module_probe_fallback("ciel", _probe(["ciel"], ["--version"]))
    catalog = build_pdk_catalog()
    installed_pdks: List[str] = []
    installed_sizes_mb: Dict[str, int] = {}
    for root in _pdk_roots():
        for variant in catalog:
            vdir = root / variant
            if (vdir / "libs.ref").is_dir() and variant not in installed_pdks:
                installed_pdks.append(variant)
                size = _dir_size_mb(vdir)
                if size is not None:
                    installed_sizes_mb[variant] = size
    pdk_out = {
        "ready": bool(installed_pdks),
        "installed_pdks": installed_pdks,
        "installed_sizes_mb": installed_sizes_mb,
        "ciel_installed": ciel_probe["installed"],
        "remediation": (
            "Install ciel (the PDK manager), then install a PDK below."
            if not ciel_probe["installed"]
            else ("Pick a PDK below and click Install." if not installed_pdks else "")
        ),
    }
    result = {
        "platform": _platform_key(),
        "tools": out,
        "pdk": pdk_out,
        "pdk_catalog": catalog,
        "container": container_engine(),
    }
    _check_tools_cache.clear()
    _check_tools_cache.append((time.time(), result))
    return result


def _pdk_roots() -> List[Path]:
    """PDK roots to probe for installed variants (env + ciel home)."""
    roots: List[Path] = []
    env = os.environ.get("PDK_ROOT")
    if env:
        roots.append(Path(env).expanduser())
    try:
        import ciel  # type: ignore

        home = ciel.get_ciel_home(env or None)
        if home:
            roots.append(Path(home))
    except Exception:
        pass
    seen: set = set()
    out: List[Path] = []
    for r in roots:
        try:
            rp = r.resolve()
        except Exception:
            continue
        if rp.is_dir() and rp not in seen:
            seen.add(rp)
            out.append(r)
    return out


def install_tool(key: str) -> Dict[str, Any]:
    """Return the recipe argv for a tool; do not execute (the installer does).

    The frontend POSTs to ``/api/tools/install/<key>`` which then runs the
    command in the actual subprocess runner so the SSE log stream stays
    consistent.
    """
    for t in EDA_TOOLS:
        if t["key"] != key:
            continue
        install = t.get("install")
        if not install:
            return {"ok": False, "key": key, "argv": None, "reason": "no install recipe in this build"}
        if isinstance(install, list):
            return {"ok": True, "key": key, "argv": install, "kind": "pip"}
        pk = _platform_key()
        recipe = install.get(pk, "")
        return {"ok": False, "key": key, "argv": None, "recipe": recipe, "kind": "manual", "reason": f"Manual install required: {recipe}"}
    return {"ok": False, "key": key, "argv": None, "reason": "unknown tool"}
