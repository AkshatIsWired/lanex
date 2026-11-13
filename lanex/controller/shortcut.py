# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""A desktop shortcut that starts LanEx without a terminal.

* macOS: ``~/Applications/LanEx.app`` (no sudo; indexed by Spotlight and
  Launchpad) plus a link to it on the Desktop. The bundle is minimal: an
  ``Info.plist``, a launcher script in ``Contents/MacOS`` and, when ``sips``
  and ``iconutil`` work, an ``.icns`` built from the packaged PNG icon.
* Linux: ``~/.local/share/applications/lanex.desktop`` with the icon under
  ``~/.local/share/icons``, and a copy in the Desktop folder when one exists.
* WSL and Windows: nothing; Windows has its own launcher.

Both launch ``<this python> -m lanex --from-shortcut``, which opens the window
of an already running LanEx instead of starting a second one, and writes its
output to ``~/.lanex/logs/lanex-app.log``. Re-running replaces only what this
module created. ``LANEX_NO_SHORTCUT=1`` skips it.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

BUNDLE_ID = "io.github.akshatiswired.lanex"
APP_NAME = "LanEx"
DESKTOP_FILE = "lanex.desktop"
LOG_NAME = "lanex-app.log"
# Marks files this module wrote, so a re-run never replaces a user's own file.
_MARK = "X-LanEx-Shortcut=1"

_VENDOR = Path(__file__).resolve().parent.parent / "server" / "static" / "vendor"
_ICON_512 = _VENDOR / "icon-512.png"
_ICON_192 = _VENDOR / "icon-192.png"

_LSREGISTER = ("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
               "LaunchServices.framework/Support/lsregister")

# Finder and Launchpad start an app with launchd's bare PATH
# (/usr/bin:/bin:/usr/sbin:/sbin): no Homebrew, no Docker Desktop CLI.
_DARWIN_PATH = (
    "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/local/sbin:"
    "/Applications/Docker.app/Contents/Resources/bin:/opt/podman/bin:/opt/X11/bin:"
    "$HOME/.local/bin"
)


def _home(home: Optional[Path]) -> Path:
    return Path(home) if home else Path.home()


def _lanex_home(home: Path) -> Path:
    env = os.environ.get("LANEX_HOME")
    return Path(env).expanduser() if env else home / ".lanex"


def log_path(home: Optional[Path] = None) -> Path:
    return _lanex_home(_home(home)) / "logs" / LOG_NAME


def launch_argv(python: Optional[str] = None) -> List[str]:
    """The command a shortcut runs. The interpreter path is kept unresolved so
    a venv's ``bin/python`` still selects that venv."""
    return [python or sys.executable, "-m", "lanex", "--from-shortcut"]


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\"'\"'") + "'"


def _skip_reason() -> Optional[str]:
    if os.environ.get("LANEX_NO_SHORTCUT", "") not in ("", "0"):
        return "LANEX_NO_SHORTCUT is set"
    if sys.platform == "darwin":
        return None
    if sys.platform.startswith("linux"):
        from . import platform_env

        if platform_env.is_wsl():
            return "WSL: Windows has its own LanEx launcher"
        return None
    return "no desktop shortcut on this platform"


# ------------------------------------------------------------------ macOS ----

def mac_launcher_script(argv: List[str], log: Path) -> str:
    cmd = " ".join(_sh_quote(a) for a in argv)
    return f"""#!/bin/bash
# LanEx app launcher, written by `lanex --install-shortcut`.
# Started from Finder there is no terminal and only launchd's bare PATH.
export PATH="{_DARWIN_PATH}:$PATH"
LOG={_sh_quote(str(log))}
mkdir -p "$(dirname "$LOG")" 2>/dev/null
cd "$HOME" || exit 1
if [ ! -x {_sh_quote(argv[0])} ]; then
    /usr/bin/osascript -e 'display alert "LanEx could not start" message "The Python that LanEx was installed with is gone. Run the LanEx install command again in Terminal. Details are in ~/.lanex/logs/{LOG_NAME}."' >/dev/null 2>&1
    echo "$(date): {argv[0]} is missing; run the LanEx installer again" >> "$LOG"
    exit 1
fi
echo "$(date): starting from the app" >> "$LOG"
nohup {cmd} >> "$LOG" 2>&1 < /dev/null &
exit 0
"""


def mac_info_plist(has_icon: bool, version: str) -> bytes:
    info: Dict[str, Any] = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
    }
    if has_icon:
        info["CFBundleIconFile"] = APP_NAME
    return plistlib.dumps(info)


def _is_our_bundle(app: Path) -> bool:
    try:
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        return info.get("CFBundleIdentifier") == BUNDLE_ID
    except Exception:
        return False


def _build_icns(dest: Path, src: Path = _ICON_512) -> bool:
    """``.icns`` from the packaged PNG with sips + iconutil; False on any failure."""
    if not src.is_file() or not shutil.which("sips") or not shutil.which("iconutil"):
        return False
    iconset = dest.parent / f"{APP_NAME}.iconset"
    try:
        shutil.rmtree(iconset, ignore_errors=True)
        iconset.mkdir(parents=True)
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                if px > 512:
                    continue
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                r = subprocess.run(["sips", "-z", str(px), str(px), str(src),
                                    "--out", str(iconset / name)],
                                   capture_output=True, timeout=30)
                if r.returncode != 0:
                    return False
        r = subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)],
                           capture_output=True, timeout=60)
        return r.returncode == 0 and dest.is_file()
    except Exception:
        return False
    finally:
        shutil.rmtree(iconset, ignore_errors=True)


def _version() -> str:
    try:
        from importlib.metadata import version

        return version("lanex")
    except Exception:
        return "1.0"


def install_mac(home: Path, argv: List[str]) -> Dict[str, Any]:
    apps = home / "Applications"
    app = apps / f"{APP_NAME}.app"
    if app.exists() and not _is_our_bundle(app):
        return {"ok": False, "paths": [], "message":
                f"{app} already exists and was not made by LanEx, so it was left alone. "
                "Start LanEx with the lanex command, or move that app and run "
                "lanex --install-shortcut again."}
    contents = app / "Contents"
    macos = contents / "MacOS"
    res = contents / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    exe = macos / APP_NAME
    exe.write_text(mac_launcher_script(argv, log_path(home)), encoding="utf-8")
    exe.chmod(0o755)
    icns = res / f"{APP_NAME}.icns"
    has_icon = icns.is_file() or _build_icns(icns)
    (contents / "Info.plist").write_bytes(mac_info_plist(has_icon, _version()))
    (contents / "PkgInfo").write_text("APPL????", encoding="ascii")
    paths = [str(app)]
    # Tell LaunchServices about the new or changed bundle (icon, Spotlight).
    if os.path.exists(_LSREGISTER):
        try:
            subprocess.run([_LSREGISTER, "-f", str(app)], capture_output=True, timeout=30)
        except Exception:
            pass
    desk = home / "Desktop"
    link = desk / f"{APP_NAME}.app"
    if desk.is_dir():
        if link.is_symlink():
            link.unlink()
        if not link.exists():
            try:
                link.symlink_to(app)
                paths.append(str(link))
            except OSError:
                pass
    return {"ok": True, "paths": paths, "icon": has_icon,
            "message": f"LanEx is in {apps} (Spotlight and Launchpad find it)"
                       + (" and on your Desktop." if str(link) in paths else ".")}


def remove_mac(home: Path) -> List[str]:
    removed = []
    link = home / "Desktop" / f"{APP_NAME}.app"
    app = home / "Applications" / f"{APP_NAME}.app"
    if link.is_symlink() and os.path.realpath(link) == os.path.realpath(app):
        link.unlink()
        removed.append(str(link))
    if app.exists() and _is_our_bundle(app):
        shutil.rmtree(app)
        removed.append(str(app))
    return removed


# ------------------------------------------------------------------ Linux ----

def _desktop_exec_quote(arg: str) -> str:
    """Quote one Exec argument per the Desktop Entry spec."""
    out = arg.replace("%", "%%")
    if any(c in out for c in ' \t\n"\'\\><~|&;$*?#()`'):
        for ch in ("\\", '"', "`", "$"):
            out = out.replace(ch, "\\" + ch)
        out = f'"{out}"'
    return out


def desktop_entry(argv: List[str], icon: str) -> str:
    exec_line = " ".join(_desktop_exec_quote(a) for a in argv)
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        f"Name={APP_NAME}\n"
        "GenericName=Chip design cockpit\n"
        "Comment=Run the LibreLane RTL-to-GDSII flow\n"
        f"Exec={exec_line}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Development;Electronics;\n"
        "StartupNotify=false\n"
        f"{_MARK}\n"
    )


def _is_ours(path: Path) -> bool:
    try:
        return _MARK in path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def _desktop_dir(home: Path) -> Optional[Path]:
    """The user's Desktop folder (xdg-user-dir aware), or None."""
    cand: Optional[Path] = None
    xdg = shutil.which("xdg-user-dir")
    if xdg:
        try:
            r = subprocess.run([xdg, "DESKTOP"], capture_output=True, text=True, timeout=5,
                               env={**os.environ, "HOME": str(home)})
            out = (r.stdout or "").strip()
            if r.returncode == 0 and out:
                cand = Path(out)
        except Exception:
            cand = None
    if cand is None:
        cand = home / "Desktop"
    try:
        if cand.resolve() == home.resolve() or not cand.is_dir():
            return None
    except Exception:
        return None
    return cand


def install_linux(home: Path, argv: List[str]) -> Dict[str, Any]:
    share = home / ".local" / "share"
    icon_path = share / "icons" / "hicolor" / "512x512" / "apps" / "lanex.png"
    icon = "lanex"
    try:
        icon_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_ICON_512, icon_path)
        small = share / "icons" / "hicolor" / "192x192" / "apps" / "lanex.png"
        small.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_ICON_192, small)
        # An absolute path works even where the icon theme cache is stale.
        icon = str(icon_path)
    except Exception:
        pass
    text = desktop_entry(argv, icon)
    apps = share / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    entry = apps / DESKTOP_FILE
    paths: List[str] = []
    if entry.exists() and not _is_ours(entry):
        return {"ok": False, "paths": [], "message":
                f"{entry} already exists and was not made by LanEx, so it was left alone."}
    entry.write_text(text, encoding="utf-8")
    entry.chmod(0o755)
    paths.append(str(entry))
    if shutil.which("update-desktop-database"):
        try:
            subprocess.run(["update-desktop-database", str(apps)], capture_output=True, timeout=30)
        except Exception:
            pass
    desk = _desktop_dir(home)
    on_desktop = None
    if desk is not None:
        copy = desk / DESKTOP_FILE
        if not copy.exists() or _is_ours(copy):
            copy.write_text(text, encoding="utf-8")
            copy.chmod(0o755)
            on_desktop = copy
            paths.append(str(copy))
            # GNOME runs a Desktop launcher only once it is marked trusted.
            if shutil.which("gio"):
                try:
                    subprocess.run(["gio", "set", str(copy), "metadata::trusted", "true"],
                                   capture_output=True, timeout=10)
                except Exception:
                    pass
    msg = "LanEx is in your applications menu"
    msg += f" and on your Desktop ({on_desktop})." if on_desktop else "."
    return {"ok": True, "paths": paths, "message": msg}


def remove_linux(home: Path) -> List[str]:
    removed = []
    share = home / ".local" / "share"
    cands = [share / "applications" / DESKTOP_FILE]
    desk = _desktop_dir(home)
    if desk is not None:
        cands.append(desk / DESKTOP_FILE)
    for p in cands:
        if p.is_file() and _is_ours(p):
            p.unlink()
            removed.append(str(p))
    for size in ("512x512", "192x192"):
        icon = share / "icons" / "hicolor" / size / "apps" / "lanex.png"
        if icon.is_file():
            icon.unlink()
            removed.append(str(icon))
    return removed


# ------------------------------------------------------------------- API ----

def install(home: Optional[Path] = None, python: Optional[str] = None) -> Dict[str, Any]:
    """Create or refresh the shortcut. Never raises."""
    why = _skip_reason()
    if why:
        return {"ok": True, "skipped": True, "paths": [], "message": f"No shortcut ({why})."}
    h = _home(home)
    argv = launch_argv(python)
    try:
        if sys.platform == "darwin":
            return install_mac(h, argv)
        return install_linux(h, argv)
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "paths": [], "message":
                f"Could not create the LanEx shortcut ({ex}). LanEx still starts with "
                "the lanex command; run lanex --install-shortcut to try again."}


def remove(home: Optional[Path] = None) -> Dict[str, Any]:
    """Remove what :func:`install` created. Never raises."""
    h = _home(home)
    try:
        if sys.platform == "darwin":
            removed = remove_mac(h)
        elif sys.platform.startswith("linux"):
            removed = remove_linux(h)
        else:
            removed = []
        return {"ok": True, "paths": removed}
    except Exception as ex:  # noqa: BLE001
        return {"ok": False, "paths": [], "message": f"Could not remove the shortcut ({ex})."}
