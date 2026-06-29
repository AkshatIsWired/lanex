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
"""Inspect and validate PDK installs (sky130, gf180mcu, ...).

This module is intentionally best-effort: when LibreLane's
``Config`` module is unavailable, or when ciel is not installed, we still
want the GUI to come up and surface a useful onboarding message in the wizard.
"""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import PDK, to_json

# Sibling directories that live next to PDK families inside a PDK root but are
# *not* themselves PDKs (ciel's store, volare's legacy store, build metadata).
_NON_PDK_DIRS = {
    "libs.ref",
    "libs.tech",
    "libs.doc",
    "libs.qa",
    "open_pdks",
    "cells",
    "ciel",
    "volare",
    "build",
    "node_modules",
}


def _candidate_pdk_roots() -> List[Path]:
    """Discover PDK roots in priority order.

    Cross-platform: detects Windows ``%APPDATA%``, WSL paths, and
    standard Linux/macOS locations.
    """
    roots: List[Path] = []

    env = os.environ.get("PDK_ROOT")
    if env:
        roots.append(Path(env).expanduser())

    # Ciel is the canonical PDK manager for LibreLane; ask it where it keeps
    # PDKs so we agree with what the engine will actually resolve.
    try:
        import ciel  # type: ignore

        home = ciel.get_ciel_home(env or None)
        if home:
            roots.append(Path(home).expanduser())
    except Exception:
        pass

    ciel = Path.home() / ".ciel"
    if ciel.is_dir():
        roots.append(ciel)

    volare = Path.home() / ".volare"
    if volare.is_dir():
        roots.append(volare)

    home_pdk = Path.home() / "pdk"
    if home_pdk.is_dir():
        roots.append(home_pdk)

    cwd_pdk = Path.cwd() / "pdks"
    if cwd_pdk.is_dir():
        roots.append(cwd_pdk)

    # Windows: %APPDATA%\ciel
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            win_ciel = Path(appdata) / "ciel"
            if win_ciel.is_dir():
                roots.append(win_ciel)
        # WSL2 path on Windows host
        wsl_pdk = Path.home() / "AppData" / "Local" / "ciel"
        if wsl_pdk.is_dir():
            roots.append(wsl_pdk)

    # Ciel uses PDK_ROOT or ~/.ciel by default, which we already checked.

    # De-dupe, preserving order.
    out: List[Path] = []
    seen: set = set()
    for r in roots:
        if r.exists() and r.resolve() not in seen:
            seen.add(r.resolve())
            out.append(r)
    return out


def list_pdks() -> List[Dict[str, Any]]:
    """Discover installed PDKs across all known PDK roots.

    A PDK is identified by an immediate child directory of pdk_root which
    matches the canonical naming convention (sky130*, gf180mcu*, ihp*, ...).
    SCLs are discovered by inspecting each pdk/<pdk>/libs.ref/ subdir.
    """
    out: List[Dict[str, Any]] = []
    for root in _candidate_pdk_roots():
        try:
            for child in sorted(root.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                # Skip ciel/volare stores and PDK-internal subdirectories.
                if child.name in _NON_PDK_DIRS:
                    continue
                scl_tuples = _list_scls_at(child)
                # A real (enabled) PDK has a libs.ref directory. Without one this
                # is almost certainly noise, so don't surface it as a PDK.
                if not (child / "libs.ref").is_dir():
                    continue
                out.append(
                    to_json(
                        PDK(
                            name=child.name,
                            root=str(root),
                            variants=scl_tuples,
                            ready=bool(scl_tuples),
                            missing=[] if scl_tuples else ["libs.ref/<scl>"],
                        )
                    )
                )
        except Exception:
            continue
    return out


def _list_scls_at(pdk_dir: Path) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    libs = pdk_dir / "libs.ref"
    if not libs.is_dir():
        return out
    for scl in sorted(libs.iterdir()):
        if not scl.is_dir():
            continue
        label = scl.name
        out.append((label, label))
    return out


def list_scls(pdk: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for root in _candidate_pdk_roots():
        scl_dir = root / pdk / "libs.ref"
        if not scl_dir.is_dir():
            continue
        for scl in sorted(scl_dir.iterdir()):
            if not scl.is_dir():
                continue
            # Probe for the .lib that LibreLane expects.
            lib_hits = list(scl.rglob("*.lib"))
            out.append(
                to_json(
                    PDK(
                        name=pdk,
                        root=str(root),
                        variants=[(scl.name, scl.name)],
                        ready=bool(lib_hits),
                        missing=[] if lib_hits else ["*.lib not found under scl"],
                    )
                )
            )
    return out


# Host that serves ciel PDK releases (StaticWebDataSource in librelane's CLI).
# A reachability probe here tells us whether a missing PDK could be downloaded
# on the next run, so the GUI can distinguish "offline + missing" (hard blocker)
# from "online + missing" (will auto-download).
_PDK_SOURCE_HOST = "fossi-foundation.github.io"


def network_can_reach_pdk_source(timeout: float = 2.5) -> bool:
    """Best-effort TCP probe to the ciel release host (stdlib only)."""
    try:
        with socket.create_connection((_PDK_SOURCE_HOST, 443), timeout=timeout):
            return True
    except Exception:
        return False


def _resolve_family(pdk: str) -> Tuple[Optional[str], str]:
    """Map a PDK family **or** variant string to ``(family, variant)``.

    ``"sky130"`` -> ``("sky130", "sky130A")`` (family default variant);
    ``"sky130A"`` -> ``("sky130", "sky130A")``. Returns ``(None, pdk)`` when the
    family can't be resolved (ciel missing / unknown PDK).
    """
    try:
        from ciel.common import Family  # type: ignore
    except Exception:
        return None, pdk
    fam = Family.by_name.get(pdk)
    if fam is not None:
        return fam.name, getattr(fam, "default_variant", pdk)
    for f in Family.by_name.values():
        if pdk in (getattr(f, "variants", []) or []):
            return f.name, pdk
    return None, pdk


def _ciel_homes(roots: Optional[List[Path]] = None) -> List[str]:
    """Unique ciel homes derived from the candidate PDK roots (order-preserving)."""
    roots = roots if roots is not None else _candidate_pdk_roots()
    try:
        import ciel  # type: ignore
    except Exception:
        return [str(r) for r in roots]
    homes: List[str] = []
    for r in roots:
        try:
            h = ciel.get_ciel_home(str(r))
        except Exception:
            h = str(r)
        if h not in homes:
            homes.append(h)
    return homes


def installed_pdk_versions(pdk: str) -> List[Tuple[str, str]]:
    """``[(version_hash, ciel_home), …]`` for every installed version of the
    family *pdk* belongs to, across **all** known ciel homes.

    Read-only: no directory is created (we derive the versions dir from
    ``Version.get_dir`` without calling ciel's ``get_all_installed``, which
    ``mkdirp``s). Used by the uninstaller — so a delete targets the store(s) the
    PDK actually lives in, not just ``$PDK_ROOT`` — and by diagnostics.
    """
    family, _variant = _resolve_family(pdk)
    family = family or pdk
    out: List[Tuple[str, str]] = []
    try:
        import ciel  # type: ignore
    except Exception:
        return out
    seen: set = set()
    for home in _ciel_homes():
        try:
            versions_dir = Path(ciel.Version(name="_", pdk=family).get_dir(home)).parent
        except Exception:
            continue
        if not versions_dir.is_dir():
            continue
        for child in sorted(versions_dir.iterdir()):
            key = (child.name, home)
            if child.is_dir() and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def manual_pdk_dirs(pdk: str) -> List[str]:
    """Top-level ``<root>/<variant>/libs.ref`` dirs that are **not** ciel version
    stores — i.e. manual / git-cloned / volare-style installs ciel can't remove.

    Lets the uninstaller be honest ("present but not ciel-managed") instead of
    silently reporting success when nothing was actually removed.
    """
    _family, variant = _resolve_family(pdk)
    variant = variant or pdk
    out: List[str] = []
    for root in _candidate_pdk_roots():
        d = root / variant
        if (d / "libs.ref").is_dir() and str(d) not in out:
            out.append(str(d))
    return out


def required_pdk_version(family: str) -> Optional[str]:
    """The PDK commit hash LibreLane pins for *family* (``pdk_hashes.yaml``).

    This is the version the CLI's ``ciel.fetch`` will demand in **container**
    mode — so a different installed version forces a (re)download.
    """
    try:
        from librelane.common import get_pdk_hash  # type: ignore

        return get_pdk_hash(family)
    except Exception:
        return None


def _scl_has_libs(scl_dir: Path) -> bool:
    """A usable SCL has at least one Liberty (``.lib``) timing file."""
    if not scl_dir.is_dir():
        return False
    try:
        for _ in scl_dir.rglob("*.lib"):
            return True
    except Exception:
        return False
    return False


def _check_local_ready(variant: str, scl: str, roots: List[Path]) -> Dict[str, Any]:
    """Local mode: the Flow uses ``pdk_root`` directly (no ``ciel.fetch``), so a
    matching ``<root>/<variant>/libs.ref/<scl>`` with timing files is enough —
    the version doesn't matter."""
    for root in roots:
        scl_dir = root / variant / "libs.ref" / scl
        if scl_dir.is_dir():
            missing: List[str] = []
            if not _scl_has_libs(scl_dir):
                missing.append(".lib timing files")
            tech_hits = list(scl_dir.rglob("*.lef")) + list(scl_dir.rglob("*.gds"))
            if not tech_hits:
                missing.append(".lef/.gds technology files")
            return {
                "ready": not missing,
                "where": [str(scl_dir)],
                "pdk_root": str(root),
                "version_match": None,  # not meaningful in local mode
                "needs_download": False,
                "missing": missing,
                "remediation": (
                    f"Run `ciel enable --pdk-family <family> <version>` to (re)install '{variant}/{scl}'."
                    if missing
                    else ""
                ),
            }
    return {
        "ready": False,
        "where": [str(r / variant / "libs.ref" / scl) for r in roots],
        "pdk_root": str(roots[0]) if roots else None,
        "version_match": None,
        "needs_download": False,
        "missing": [
            f"PDK variant '{variant}/{scl}' not found under any of: {[str(r) for r in roots]}"
        ],
        "remediation": "Run `ciel enable --pdk-family <family> <version>` or switch to an installed variant.",
    }


def _check_container_ready(
    variant: str, scl: str, family: Optional[str], roots: List[Path]
) -> Dict[str, Any]:
    """Container mode: ``librelane --dockerized`` routes through the CLI's
    ``pdk_resolve_wrapper`` -> ``ciel.fetch``, which demands the **exact** pinned
    version (:func:`required_pdk_version`) in a ciel store under the chosen
    ``--pdk-root`` (or downloads it). So readiness here means *that* version,
    with this SCL's libs, is already on disk — and we return the ciel home that
    holds it so the run mounts the right store instead of a stale enabled one."""
    required = required_pdk_version(family) if family else None
    if not family or not required:
        # Can't determine the pinned version (ciel/librelane unavailable or
        # unknown family). Degrade to a version-agnostic check so the GUI still
        # works; the container will resolve/download as needed.
        res = _check_local_ready(variant, scl, roots)
        res["required_version"] = required
        res["version_match"] = None
        res["needs_download"] = not res.get("ready")
        return res

    import ciel  # type: ignore

    installed: List[str] = []
    homes: List[str] = []
    for root in roots:
        try:
            home = ciel.get_ciel_home(str(root))
        except Exception:
            home = str(root)
        if home not in homes:
            homes.append(home)
        ver = ciel.Version(name=required, pdk=family)
        # Read-only enumeration of installed versions (for the diagnostic).
        try:
            versions_dir = Path(ver.get_dir(home)).parent
            if versions_dir.is_dir():
                for child in versions_dir.iterdir():
                    if child.is_dir():
                        installed.append(child.name)
        except Exception:
            pass
        try:
            present = ver.is_installed(home)
        except Exception:
            present = False
        if present:
            scl_dir = Path(ver.get_dir(home)) / variant / "libs.ref" / scl
            if _scl_has_libs(scl_dir):
                return {
                    "ready": True,
                    "where": [str(scl_dir)],
                    "pdk_root": home,
                    "required_version": required,
                    "installed_versions": sorted(set(installed)),
                    "version_match": True,
                    "needs_download": False,
                    "missing": [],
                    "remediation": "",
                }

    installed = sorted(set(installed))
    online = network_can_reach_pdk_source()
    short = required[:12] + "…"
    if installed:
        miss = (
            f"container mode needs PDK store version {short} for '{variant}/{scl}'; "
            f"installed here: {', '.join(v[:12] + '…' for v in installed)}"
        )
    else:
        miss = f"'{variant}/{scl}' (version {short}) is not installed for container mode"
    rem = (
        f"Run `ciel enable --pdk-family {family} {required}` to fetch the version LibreLane "
        f"pins (needs network), or connect to the internet — the run downloads it automatically."
    )
    return {
        "ready": False,
        "where": homes,
        "pdk_root": homes[0] if homes else None,
        "required_version": required,
        "installed_versions": installed,
        "version_match": False,
        "needs_download": True,
        "network_available": online,
        "missing": [miss],
        "remediation": rem,
    }


def check_pdk_ready(
    pdk: str, scl: Optional[str] = None, run_mode: str = "local"
) -> Dict[str, Any]:
    """Diagnose whether *pdk*/*scl* can actually run, **for the active run mode**.

    Local and container mode resolve PDKs differently (see the two helpers), so
    the answer — and the ``pdk_root`` the run should use — depends on the mode.
    The returned ``pdk_root`` is the value to hand LibreLane so it mounts/uses
    the store that genuinely holds the required files.
    """
    roots = _candidate_pdk_roots()
    if not roots:
        return {
            "ready": False,
            "where": [],
            "pdk_root": None,
            "needs_download": True,
            "missing": ["no pdk_root configured or installed (set PDK_ROOT or run `ciel enable`)"],
            "remediation": "Use the PDK install wizard or `ciel enable --pdk-family sky130 <version>` (see docs).",
        }
    if not scl:
        return {
            "ready": False,
            "where": [str(r) for r in roots],
            "pdk_root": str(roots[0]),
            "needs_download": False,
            "missing": ["scl not chosen"],
            "remediation": "Choose a standard cell library (e.g. sky130_fd_sc_hd).",
        }

    family, variant = _resolve_family(pdk)
    variant = variant or pdk

    if run_mode == "container":
        return _check_container_ready(variant, scl, family, roots)
    return _check_local_ready(variant, scl, roots)
