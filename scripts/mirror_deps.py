#!/usr/bin/env python3
"""Pin and mirror the downloads Windows Setup depends on.

  py scripts/mirror_deps.py prepare --out <dir>
      Downloads the Ubuntu WSL rootfs and every PDK asset of the pinned ciel
      versions (windows/setup/pdk-pins.json), checks the rootfs against its
      pinned SHA-256, and writes windows/setup/pdk-assets.json: for each PDK
      family and version, every asset's name, upstream URL, size and SHA-256.
      Setup refuses any PDK file that does not match it.

  py scripts/mirror_deps.py upload --out <dir> --tag deps-v1 [--repo owner/name]
      Uploads the prepared files to a GitHub release of this repository (the
      "our copy" that Setup tries first). Needs the gh CLI and the
      maintainer's OK: it publishes files.

  py scripts/mirror_deps.py check
      Re-fetches every pinned file from every location and reports anything
      missing or changed (used by .github/workflows/dependency-watch.yml).

Only the standard library is used, so this runs on any Python 3.9+.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP = REPO_ROOT / "windows" / "setup"
PDK_PINS = SETUP / "pdk-pins.json"
PDK_ASSETS = SETUP / "pdk-assets.json"
MANIFEST = SETUP / "build-manifest.json"
CIEL_STATIC = "https://fossi-foundation.github.io/ciel-releases"
DEFAULT_REPO = "AkshatIsWired/lanex"
DEFAULT_TAG = "deps-v1"
ROOTFS = {
    "file": "ubuntu-24.04.4-wsl-amd64.wsl",
    "sha256": "9b2f7730dc68227dd04a9f3e5eab86ad85caf556b8606ad94f1f29ff5c4fd3f5",
    "urls": [
        "https://releases.ubuntu.com/24.04.4/ubuntu-24.04.4-wsl-amd64.wsl",
        "https://old-releases.ubuntu.com/releases/24.04.4/ubuntu-24.04.4-wsl-amd64.wsl",
    ],
}
UA = {"User-Agent": "lanex-mirror-deps/1"}


def mirror_name(family: str, version: str, filename: str) -> str:
    """Asset name in our release: unique across families and versions."""
    return f"{family}-{version[:12]}-{filename}"


def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, tries: int = 6) -> None:
    """Resumable download into dest (dest.part until complete)."""
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, tries + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = dict(UA)
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as r:
                mode = "ab" if (have and r.status == 206) else "wb"
                with part.open(mode) as f:
                    while True:
                        chunk = r.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
            part.replace(dest)
            return
        except urllib.error.HTTPError as e:
            if e.code == 416:
                part.unlink(missing_ok=True)
            elif e.code in (403, 404, 410):
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            print(f"   retry {attempt}: {e}", file=sys.stderr)
        time.sleep(min(5 * attempt, 30))
    raise RuntimeError(f"download failed after {tries} attempts: {url}")


def pinned_versions() -> dict:
    pins = json.loads(PDK_PINS.read_text(encoding="utf-8"))
    out = {}
    for variant in pins["variants"].values():
        out[variant["family"]] = variant["requiredVersion"]
    return out


def cmd_prepare(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rootfs = out / ROOTFS["file"]
    if not (rootfs.exists() and sha256_file(rootfs) == ROOTFS["sha256"]):
        print(f"rootfs: {ROOTFS['urls'][0]}")
        download(ROOTFS["urls"][0], rootfs)
    if sha256_file(rootfs) != ROOTFS["sha256"]:
        raise SystemExit("rootfs SHA-256 does not match the pin")
    print(f"rootfs ok: {rootfs.stat().st_size} bytes")

    families = {}
    for family, version in sorted(pinned_versions().items()):
        manifest = get_json(f"{CIEL_STATIC}/{family}/{version}/manifest.json")
        listing = get_json(f"{CIEL_STATIC}/{family}/manifest.json")
        dated = next((v for v in listing["versions"] if v["version"] == version), None)
        if dated is None:
            raise SystemExit(f"{family} {version} is not listed upstream")
        assets = []
        for asset in manifest["assets"]:
            name = mirror_name(family, version, asset["filename"])
            dest = out / name
            if not dest.exists():
                print(f"{family}: {asset['filename']}")
                download(asset["url"], dest)
            assets.append({
                "content": asset["content"],
                "filename": asset["filename"],
                "mirrorName": name,
                "url": asset["url"],
                "size": dest.stat().st_size,
                "sha256": sha256_file(dest),
            })
        families[family] = {
            "version": version,
            "date": dated["date"],
            "prerelease": bool(dated.get("prerelease", False)),
            "assets": assets,
        }
        total = sum(a["size"] for a in assets)
        print(f"{family} {version[:12]}: {len(assets)} assets, {total / 1e6:.1f} MB")
    doc = {
        "schema": 1,
        "comment": "SHA-256 of every PDK file Setup may download. Generated by scripts/mirror_deps.py prepare.",
        "mirrorBase": f"https://github.com/{DEFAULT_REPO}/releases/download/{DEFAULT_TAG}",
        "rootfs": dict(ROOTFS, size=rootfs.stat().st_size),
        "families": families,
    }
    PDK_ASSETS.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {PDK_ASSETS}")
    return 0


def cmd_upload(args) -> int:
    out = Path(args.out)
    doc = json.loads(PDK_ASSETS.read_text(encoding="utf-8"))
    files = [out / ROOTFS["file"]]
    for fam in doc["families"].values():
        files += [out / a["mirrorName"] for a in fam["assets"]]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise SystemExit("run prepare first; missing: " + ", ".join(missing[:5]))
    for f in files:
        if f.name == ROOTFS["file"]:
            ok = sha256_file(f) == ROOTFS["sha256"]
        else:
            want = next(a["sha256"] for fam in doc["families"].values()
                        for a in fam["assets"] if a["mirrorName"] == f.name)
            ok = sha256_file(f) == want
        if not ok:
            raise SystemExit(f"{f} no longer matches its pinned SHA-256")
    repo = args.repo
    if subprocess.run(["gh", "release", "view", args.tag, "--repo", repo],
                      capture_output=True).returncode != 0:
        subprocess.run(["gh", "release", "create", args.tag, "--repo", repo,
                        "--title", f"Pinned dependencies ({args.tag})",
                        "--notes", "Copies of the files LanEx Setup downloads, so installs keep "
                                   "working if an upstream host moves or deletes them. Setup checks "
                                   "every file against windows/setup/pdk-assets.json.",
                        "--prerelease"], check=True)
    for f in files:
        print(f"upload {f.name}")
        subprocess.run(["gh", "release", "upload", args.tag, str(f), "--repo", repo,
                        "--clobber"], check=True)
    return 0


def head_ok(url: str) -> tuple[bool, str]:
    try:
        req = urllib.request.Request(url, method="HEAD", headers=UA)
        with urllib.request.urlopen(req, timeout=60) as r:
            return True, str(r.status)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def cmd_check(args) -> int:
    """Fetch every pinned file and compare hashes. Prints a Markdown report."""
    doc = json.loads(PDK_ASSETS.read_text(encoding="utf-8"))
    problems: list[str] = []
    tmp = Path(args.work)
    tmp.mkdir(parents=True, exist_ok=True)

    def verify(url: str, want: str, label: str) -> None:
        dest = tmp / "f"
        dest.unlink(missing_ok=True)
        try:
            download(url, dest, tries=3)
        except Exception as e:  # noqa: BLE001
            problems.append(f"- **missing**: {label} at {url} ({e})")
            return
        got = sha256_file(dest)
        dest.unlink(missing_ok=True)
        if got != want:
            problems.append(f"- **changed**: {label} at {url}: SHA-256 {got}, pinned {want}")
        else:
            print(f"ok {label} {url}")

    base = doc["mirrorBase"]
    verify(f"{base}/{ROOTFS['file']}", ROOTFS["sha256"], "rootfs (our copy)")
    for url in ROOTFS["urls"]:
        ok, why = head_ok(url)
        if ok:
            verify(url, ROOTFS["sha256"], "rootfs")
        else:
            print(f"note: rootfs not at {url} ({why})")
    if not any(head_ok(u)[0] for u in ROOTFS["urls"]):
        problems.append("- **missing upstream**: the Ubuntu rootfs is at none of its upstream URLs")
    for family, fam in doc["families"].items():
        try:
            listing = get_json(f"{CIEL_STATIC}/{family}/manifest.json")
            if not any(v["version"] == fam["version"] for v in listing["versions"]):
                problems.append(f"- **missing**: {family} {fam['version']} is no longer listed upstream")
        except Exception as e:  # noqa: BLE001
            problems.append(f"- **missing**: {family} manifest at {CIEL_STATIC} ({e})")
        for a in fam["assets"]:
            verify(a["url"], a["sha256"], f"{family} {a['filename']} (upstream)")
            verify(f"{base}/{a['mirrorName']}", a["sha256"], f"{family} {a['filename']} (our copy)")
    report = "\n".join(problems)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")
    print(report or "all pinned files present and unchanged")
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--out", required=True)
    u = sub.add_parser("upload")
    u.add_argument("--out", required=True)
    u.add_argument("--tag", default=DEFAULT_TAG)
    u.add_argument("--repo", default=DEFAULT_REPO)
    c = sub.add_parser("check")
    c.add_argument("--work", default=os.environ.get("RUNNER_TEMP", "."))
    c.add_argument("--report", default="")
    args = ap.parse_args()
    return {"prepare": cmd_prepare, "upload": cmd_upload, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
