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
"""Curated plugin store (Phase 4.4).

Locked decision: **curated registry only** — the store lists only entries from
one ``plugins.json`` index, and every download is **sha256-verified before it is
extracted** (mismatch → reject). No arbitrary third-party URLs. Plugins install
into a per-user dir (never inside the design or the librelane install) and are
opt-in. Pure stdlib: ``urllib`` / ``hashlib`` / ``json`` / ``zipfile`` /
``shutil``. No new dependency.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.request import urlopen

# Default curated registry (override for testing/forks via env). Shipped empty
# so the store never advertises an unverified plugin out of the box.
DEFAULT_REGISTRY_URL = os.environ.get(
    "LIBRELANE_GUI_PLUGIN_REGISTRY",
    "https://librelane.github.io/librelane-gui-plugins/plugins.json",
)


def plugins_home() -> Path:
    base = Path(os.environ.get("LIBRELANE_GUI_HOME", str(Path.home() / ".librelane-gui")))
    return base / "plugins"


def _state_file() -> Path:
    return plugins_home().parent / "plugins-state.json"


def _registry_cache() -> Path:
    return plugins_home().parent / "registry-cache.json"


def _load_state() -> Dict[str, Any]:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": {}}


def _save_state(state: Dict[str, Any]) -> None:
    f = _state_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(state, indent=2), encoding="utf-8")


_BUNDLED_REGISTRY = Path(__file__).with_name("plugins_registry.json")


def _bundled_registry() -> List[Dict[str, Any]]:
    """The curated catalog that ships with the GUI (used offline / pre-publish)."""
    try:
        data = json.loads(_BUNDLED_REGISTRY.read_text(encoding="utf-8"))
        plugins = data.get("plugins") if isinstance(data, dict) else data
        return plugins if isinstance(plugins, list) else []
    except Exception:
        return []


def fetch_registry(url: Optional[str] = None, *, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """Fetch the curated registry; fall back to cache then the bundled catalog.

    Returns the list of plugin manifests. Never raises — an unreachable registry
    yields the last cached copy, and failing that the catalog bundled with the
    GUI (so the Add-ons tab always shows the built-in viewers + external tools,
    even fully offline) instead of an empty store."""
    url = url or DEFAULT_REGISTRY_URL
    try:
        with urlopen(url, timeout=timeout) as resp:  # noqa: S310 - curated URL only
            data = json.loads(resp.read().decode("utf-8"))
        plugins = data.get("plugins") if isinstance(data, dict) else data
        if isinstance(plugins, list) and plugins:
            try:
                cache = _registry_cache()
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({"plugins": plugins}), encoding="utf-8")
            except Exception:
                pass
            return plugins
    except Exception:
        pass
    try:
        cached = json.loads(_registry_cache().read_text(encoding="utf-8"))
        plugins = cached.get("plugins", []) if isinstance(cached, dict) else []
        if plugins:
            return plugins
    except Exception:
        pass
    return _bundled_registry()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_hash(manifest: Dict[str, Any]) -> Optional[str]:
    val = manifest.get("sha256") or manifest.get("checksum") or ""
    if isinstance(val, str) and val.startswith("sha256:"):
        val = val.split(":", 1)[1]
    return val or None


def install(manifest: Dict[str, Any], *, archive_path: Optional[str] = None,
            timeout: float = 60.0) -> Dict[str, Any]:
    """Install a plugin from its manifest. Downloads the archive (or uses a
    local ``archive_path`` for tests), **verifies sha256 before extraction**,
    and unpacks into ``plugins_home()/<id>/``. Refuses on checksum mismatch.

    Reuses the storage-safe in-progress guard so two installs of the same id
    can't race. Returns ``{ok, id, dir}`` or ``{ok: False, error}``."""
    pid = manifest.get("id")
    if not pid:
        return {"ok": False, "error": "manifest has no id"}
    expected = _expected_hash(manifest)
    if not expected:
        return {"ok": False, "error": "manifest has no sha256 — refusing (curated registry requires it)"}

    guard_key = f"plugin:{pid}"
    try:
        from . import installer
        if installer.is_in_progress(guard_key):
            return {"ok": False, "in_progress": True}
        installer._begin_job(guard_key)
    except Exception:
        installer = None  # type: ignore

    tmp: Optional[Path] = None
    try:
        home = plugins_home()
        home.mkdir(parents=True, exist_ok=True)
        tmp = home / f".{pid}.download.zip"
        if archive_path:
            shutil.copyfile(archive_path, tmp)
        else:
            url = manifest.get("url")
            if not url:
                return {"ok": False, "error": "manifest has no download url"}
            with urlopen(url, timeout=timeout) as resp:  # noqa: S310 - curated registry
                tmp.write_bytes(resp.read())

        actual = _sha256_file(tmp)
        if actual.lower() != expected.lower():
            return {"ok": False, "error": f"checksum mismatch (expected {expected[:12]}…, got {actual[:12]}…)"}

        dest = home / pid
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        with zipfile.ZipFile(tmp) as zf:
            # Guard against zip-slip: refuse entries that escape dest.
            for member in zf.namelist():
                target = (dest / member).resolve()
                try:
                    target.relative_to(dest.resolve())
                except ValueError:
                    shutil.rmtree(dest, ignore_errors=True)
                    return {"ok": False, "error": f"unsafe path in archive: {member}"}
            zf.extractall(dest)
        (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"ok": True, "id": pid, "dir": str(dest)}
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    finally:
        if tmp is not None:
            try:
                tmp.unlink()
            except OSError:
                pass
        if installer is not None:
            try:
                installer._end_job(guard_key)
            except Exception:
                pass


def list_installed() -> List[Dict[str, Any]]:
    home = plugins_home()
    state = _load_state()
    out: List[Dict[str, Any]] = []
    if not home.is_dir():
        return out
    for d in sorted(home.iterdir()):
        if not d.is_dir():
            continue
        mf = d / "manifest.json"
        manifest: Dict[str, Any] = {}
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            manifest = {"id": d.name}
        out.append({
            "id": d.name,
            "manifest": manifest,
            "enabled": bool(state.get("enabled", {}).get(d.name, True)),
        })
    return out


def remove(pid: str) -> Dict[str, Any]:
    home = plugins_home()
    dest = (home / pid).resolve()
    try:
        dest.relative_to(home.resolve())
    except ValueError:
        return {"ok": False, "error": "invalid plugin id"}
    if not dest.is_dir():
        return {"ok": False, "error": "plugin not installed"}
    shutil.rmtree(dest)
    state = _load_state()
    state.get("enabled", {}).pop(pid, None)
    _save_state(state)
    return {"ok": True, "removed": pid}


def set_enabled(pid: str, enabled: bool) -> Dict[str, Any]:
    if not (plugins_home() / pid).is_dir():
        return {"ok": False, "error": "plugin not installed"}
    state = _load_state()
    state.setdefault("enabled", {})[pid] = bool(enabled)
    _save_state(state)
    return {"ok": True, "id": pid, "enabled": bool(enabled)}
