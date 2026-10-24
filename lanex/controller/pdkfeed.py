# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""A verified, resumable PDK download feed for ciel.

ciel 2.6.1 downloads each PDK tarball in one request, keeps nothing when the
connection drops, and checks no hash. When LanEx knows the SHA-256 of every
asset of the pinned version (``windows/setup/pdk-assets.json``, carried in the
Windows build manifest and copied to ``~/.lanex/pdk-assets.json``), it
downloads the assets itself instead:

* our own copy first (a GitHub release of this repository), the upstream
  ciel-releases asset second;
* into a persistent cache, resuming a partial file after a drop or a sleep;
* every file checked against its pinned SHA-256 before ciel sees it.

ciel then reads exactly those files from a static-web data source served on
127.0.0.1 for the length of the fetch, so its own unpacking and enabling are
unchanged.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional

_UA = {"User-Agent": "LanEx-pdkfeed/1"}
# Total time a single asset may keep failing (connection refused, DNS down, no
# route) before the PDK step gives up and Setup offers Retry. Long enough to
# ride out a Wi-Fi drop or a laptop lid closed for a few minutes.
FAILURE_BUDGET_S = 20 * 60


def pins_path() -> Path:
    from . import platform_env

    return platform_env.home() / "pdk-assets.json"


def load_pins(family: str, version: str,
              pins: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The pinned asset list for *family* at *version*, or ``None``."""
    doc = pins
    if doc is None:
        try:
            doc = json.loads(pins_path().read_text(encoding="utf-8"))
        except Exception:
            return None
    fam = (doc.get("families") or {}).get(family) if isinstance(doc, dict) else None
    if not isinstance(fam, dict) or fam.get("version") != version:
        return None
    if not isinstance(fam.get("assets"), list) or not fam["assets"]:
        return None
    out = dict(fam)
    out["mirrorBase"] = doc.get("mirrorBase") or ""
    return out


def needed_assets(family: str, pinned: Dict[str, Any],
                  libraries: Optional[Iterable[str]]) -> List[Dict[str, Any]]:
    """The assets ciel will ask for: ``common`` plus the resolved libraries."""
    wanted: Optional[set] = None
    try:
        from ciel.families import Family  # type: ignore

        fam = Family.by_name.get(family)
        if fam is not None:
            wanted = set(fam.resolve_libraries(list(libraries) if libraries else None))
    except Exception:
        wanted = set(libraries) if libraries else None
    out = []
    for asset in pinned["assets"]:
        content = asset.get("content")
        if content == "common" or wanted is None or content in wanted:
            out.append(asset)
    return out


def cache_dir(family: str, version: str) -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "lanex" / "pdk-assets" / f"{family}-{version}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Cancelled(Exception):
    pass


def _fetch_once(url: str, part: Path, on_bytes: Callable[[int], None],
                cancelled: Callable[[], bool]) -> None:
    have = part.stat().st_size if part.exists() else 0
    headers = dict(_UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        if have and r.status != 206:
            have = 0  # the server ignored the range: start over
        length = r.headers.get("Content-Length")
        expected = have + int(length) if length and length.isdigit() else None
        with part.open("ab" if have else "wb") as f:
            while True:
                if cancelled():
                    raise Cancelled()
                chunk = r.read(1 << 18)
                if not chunk:
                    break
                f.write(chunk)
                on_bytes(len(chunk))
    # A connection that closes early can end the read without an error; keep
    # the part for the next attempt to resume instead of hashing a stub.
    if expected is not None and part.stat().st_size < expected:
        raise ConnectionError(f"connection closed after {part.stat().st_size} of {expected} bytes")


def fetch_verified(asset: Dict[str, Any], dest_dir: Path, mirror_base: str, *,
                   on_bytes: Callable[[int], None],
                   cancelled: Callable[[], bool],
                   log: Callable[[str], None]) -> Path:
    """One asset on disk with the pinned SHA-256, or an exception."""
    dest = dest_dir / asset["filename"]
    want = str(asset["sha256"]).lower()
    if dest.exists():
        if _sha256(dest) == want:
            on_bytes(dest.stat().st_size)
            return dest
        dest.unlink()
    part = dest.with_name(dest.name + ".part")
    if part.exists():
        on_bytes(part.stat().st_size)
    urls = []
    if mirror_base and asset.get("mirrorName"):
        urls.append(f"{mirror_base.rstrip('/')}/{asset['mirrorName']}")
    urls.append(asset["url"])
    failing_since: Optional[float] = None
    delay = 2.0
    while True:
        for url in urls:
            if cancelled():
                raise Cancelled()
            try:
                _fetch_once(url, part, on_bytes, cancelled)
            except Cancelled:
                raise
            except urllib.error.HTTPError as e:
                if e.code == 416:
                    part.unlink(missing_ok=True)
                log(f"   {asset['filename']}: HTTP {e.code} from {url}")
                continue
            except Exception as e:  # noqa: BLE001 - network errors of every kind
                log(f"   {asset['filename']}: connection problem ({type(e).__name__}: {e}); "
                    "the part already downloaded is kept")
                continue
            got = _sha256(part)
            if got == want:
                part.replace(dest)
                return dest
            log(f"   {asset['filename']} from {url} did not match its pinned SHA-256; discarded")
            part.unlink(missing_ok=True)
        now = time.monotonic()
        failing_since = failing_since or now
        if now - failing_since > FAILURE_BUDGET_S:
            raise RuntimeError(f"could not download {asset['filename']} with the pinned SHA-256 "
                               f"from {', '.join(urls)}")
        for _ in range(int(delay * 10)):
            if cancelled():
                raise Cancelled()
            time.sleep(0.1)
        delay = min(delay * 2, 30.0)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # noqa: D401 - silence access log
        pass


@contextmanager
def serve(root: Path) -> Iterator[str]:
    """Serve *root* on 127.0.0.1 for the duration of the block; yields the URL."""
    handler = lambda *a, **k: _QuietHandler(*a, directory=str(root), **k)  # noqa: E731
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, name="lanex-pdkfeed", daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def write_static_source(root: Path, family: str, pinned: Dict[str, Any],
                        files: Dict[str, Path], base_url: str) -> None:
    """ciel's static-web layout, pointing every asset at the verified file."""
    (root / family / pinned["version"]).mkdir(parents=True, exist_ok=True)
    (root / family / "manifest.json").write_text(json.dumps({
        "pdk": family,
        "versions": [{"version": pinned["version"], "date": pinned.get("date"),
                      "prerelease": bool(pinned.get("prerelease", False))}],
    }), encoding="utf-8")
    assets = []
    for asset in pinned["assets"]:
        path = files.get(asset["filename"])
        if path is None:
            continue
        link = root / "files" / asset["filename"]
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            link.unlink()
        try:
            os.symlink(path, link)
        except OSError:
            import shutil

            shutil.copyfile(path, link)
        assets.append({"content": asset["content"], "filename": asset["filename"],
                       "url": f"{base_url}/files/{asset['filename']}"})
    (root / family / pinned["version"] / "manifest.json").write_text(
        json.dumps({"assets": assets}), encoding="utf-8")


def no_proxy_env() -> Dict[str, str]:
    """Keep a forwarded corporate proxy away from the 127.0.0.1 feed."""
    current = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    parts = [p for p in current.split(",") if p]
    for host in ("127.0.0.1", "localhost"):
        if host not in parts:
            parts.append(host)
    value = ",".join(parts)
    return {"NO_PROXY": value, "no_proxy": value}
