# Copyright 2026 LanEx Contributors
# Licensed under the Apache License, Version 2.0
"""The desktop shortcut: LanEx.app on macOS, a .desktop entry on Linux.

Hermetic: a temporary HOME, the platform monkeypatched, no sips/iconutil/gio
or LaunchServices calls executed.
"""
from __future__ import annotations

import json
import os
import plistlib
import sys
from pathlib import Path

import pytest

from lanex import cli
from lanex.controller import platform_env, shortcut


@pytest.fixture
def mac(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("LANEX_NO_SHORTCUT", raising=False)
    monkeypatch.delenv("LANEX_HOME", raising=False)
    monkeypatch.setattr(shortcut, "_build_icns", lambda dest, src=None: False)
    monkeypatch.setattr(shortcut.subprocess, "run", lambda *a, **k: pytest.fail("no subprocess"))
    monkeypatch.setattr(shortcut, "_LSREGISTER", str(tmp_path / "no-lsregister"))
    (tmp_path / "Desktop").mkdir()
    return tmp_path


@pytest.fixture
def linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("LANEX_NO_SHORTCUT", raising=False)
    monkeypatch.delenv("LANEX_HOME", raising=False)
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    monkeypatch.setattr(shortcut.shutil, "which", lambda name: None)
    return tmp_path


def _symlinks_work(tmp_path: Path) -> bool:
    try:
        (tmp_path / "_probe").symlink_to(tmp_path)
        (tmp_path / "_probe").unlink()
        return True
    except OSError:
        return False


def test_mac_bundle_contents(mac):
    res = shortcut.install(home=mac, python="/Users/me/.local/pipx/venvs/lanex/bin/python")
    assert res["ok"] is True
    app = mac / "Applications" / "LanEx.app"
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "LanEx"
    assert info["CFBundleIdentifier"] == shortcut.BUNDLE_ID
    assert info["CFBundlePackageType"] == "APPL"
    assert "CFBundleIconFile" not in info  # no icon built: the bundle still ships
    script = (app / "Contents" / "MacOS" / "LanEx").read_text(encoding="utf-8")
    assert script.startswith("#!/bin/bash\n")
    # Finder's bare PATH gets Homebrew (both prefixes) and the Docker CLI.
    assert "/opt/homebrew/bin" in script and "/usr/local/bin" in script
    assert "/Applications/Docker.app/Contents/Resources/bin" in script
    assert "'/Users/me/.local/pipx/venvs/lanex/bin/python' '-m' 'lanex' '--from-shortcut'" in script
    assert str(mac / ".lanex" / "logs" / "lanex-app.log") in script
    assert "nohup" in script and "&\nexit 0" in script
    if sys.platform != "win32" and os.name != "nt":
        assert os.access(app / "Contents" / "MacOS" / "LanEx", os.X_OK)
    if _symlinks_work(mac):
        link = mac / "Desktop" / "LanEx.app"
        assert link.is_symlink() and os.path.realpath(link) == os.path.realpath(app)
    assert "Applications" in res["message"]


def test_mac_bundle_with_icon(mac, monkeypatch):
    def fake_icns(dest, src=None):
        dest.write_bytes(b"icns")
        return True

    monkeypatch.setattr(shortcut, "_build_icns", fake_icns)
    shortcut.install(home=mac, python="/x/python")
    app = mac / "Applications" / "LanEx.app"
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleIconFile"] == "LanEx"
    assert (app / "Contents" / "Resources" / "LanEx.icns").is_file()


def test_mac_install_is_idempotent(mac):
    first = shortcut.install(home=mac, python="/x/python")
    second = shortcut.install(home=mac, python="/y/python")
    assert first["ok"] and second["ok"]
    script = (mac / "Applications" / "LanEx.app" / "Contents" / "MacOS" / "LanEx").read_text(encoding="utf-8")
    assert "'/y/python'" in script and "'/x/python'" not in script


def test_mac_leaves_a_foreign_app_alone(mac):
    foreign = mac / "Applications" / "LanEx.app" / "Contents"
    foreign.mkdir(parents=True)
    (foreign / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.someone.else"}))
    res = shortcut.install(home=mac, python="/x/python")
    assert res["ok"] is False and "left alone" in res["message"]
    assert not (foreign / "MacOS").exists()


def test_mac_remove(mac):
    shortcut.install(home=mac, python="/x/python")
    res = shortcut.remove(home=mac)
    assert res["ok"] is True
    assert not (mac / "Applications" / "LanEx.app").exists()
    assert not os.path.lexists(mac / "Desktop" / "LanEx.app")


def test_linux_desktop_entry(linux):
    (linux / "Desktop").mkdir()
    res = shortcut.install(home=linux, python="/home/me/.lanex/venv/bin/python")
    assert res["ok"] is True
    entry = linux / ".local" / "share" / "applications" / "lanex.desktop"
    text = entry.read_text(encoding="utf-8")
    assert text.startswith("[Desktop Entry]\n")
    assert "Type=Application\n" in text and "Name=LanEx\n" in text
    assert "Exec=/home/me/.lanex/venv/bin/python -m lanex --from-shortcut\n" in text
    assert "Terminal=false\n" in text
    icon = linux / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps" / "lanex.png"
    assert icon.is_file() and f"Icon={icon}\n" in text
    copy = linux / "Desktop" / "lanex.desktop"
    assert copy.read_text(encoding="utf-8") == text
    assert "Desktop" in res["message"]


def test_linux_exec_quotes_spaces_and_percent():
    entry = shortcut.desktop_entry(["/opt/my apps/py%thon", "-m", "lanex"], "lanex")
    assert 'Exec="/opt/my apps/py%%thon" -m lanex\n' in entry


def test_linux_no_desktop_folder_is_fine_and_rerun_is_idempotent(linux):
    first = shortcut.install(home=linux, python="/p")
    second = shortcut.install(home=linux, python="/p")
    assert first["ok"] and second["ok"]
    assert len(second["paths"]) == 1
    assert second["message"] == "LanEx is in your applications menu."


def test_linux_leaves_a_foreign_entry_alone(linux):
    apps = linux / ".local" / "share" / "applications"
    apps.mkdir(parents=True)
    (apps / "lanex.desktop").write_text("[Desktop Entry]\nName=Mine\n", encoding="utf-8")
    res = shortcut.install(home=linux, python="/p")
    assert res["ok"] is False
    assert "Name=Mine" in (apps / "lanex.desktop").read_text(encoding="utf-8")


def test_linux_remove(linux):
    (linux / "Desktop").mkdir()
    shortcut.install(home=linux, python="/p")
    shortcut.remove(home=linux)
    assert not (linux / ".local" / "share" / "applications" / "lanex.desktop").exists()
    assert not (linux / "Desktop" / "lanex.desktop").exists()


def test_skipped_on_wsl_and_by_env(linux, monkeypatch):
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    res = shortcut.install(home=linux, python="/p")
    assert res["skipped"] is True and not (linux / ".local").exists()
    monkeypatch.setattr(platform_env, "is_wsl", lambda: False)
    monkeypatch.setenv("LANEX_NO_SHORTCUT", "1")
    res = shortcut.install(home=linux, python="/p")
    assert res["skipped"] is True and not (linux / ".local").exists()


def test_cli_install_shortcut_flag(monkeypatch, capsys):
    monkeypatch.setattr(shortcut, "install", lambda: {"ok": True, "paths": ["/a"], "message": "done here"})
    assert cli.main(["--install-shortcut"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == "done here"
    assert json.loads(out.splitlines()[-1])["shortcut"]["paths"] == ["/a"]


def test_cli_from_shortcut_reuses_a_running_instance(monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "_redirect_to_shortcut_log", lambda: None)
    monkeypatch.setattr(cli, "_running_instance_url", lambda: "http://127.0.0.1:8766/")
    monkeypatch.setattr(cli, "_lazy_open", lambda url, no_browser, tab=False: opened.append(url))
    assert cli.main(["--from-shortcut"]) == 0
    assert opened == ["http://127.0.0.1:8766/"]


def test_running_instance_url_rejects_stale_or_foreign_records(monkeypatch, tmp_path):
    rec = tmp_path / "server.json"
    monkeypatch.setattr(cli, "_server_record_path", lambda: rec)
    assert cli._running_instance_url() is None  # no record
    rec.write_text(json.dumps({"url": "http://example.com:80/"}), encoding="utf-8")
    assert cli._running_instance_url() is None  # never a remote host
    rec.write_text(json.dumps({"url": "http://127.0.0.1:1/"}), encoding="utf-8")
    assert cli._running_instance_url(timeout=0.5) is None  # nothing answers


def test_install_script_calls_the_shortcut_and_honours_the_opt_out():
    script = (Path(__file__).resolve().parents[2] / "scripts" / "install.sh").read_text(encoding="utf-8")
    body = script[script.index("shortcut_stage() {"):]
    body = body[:body.index("\n}\n")]
    assert '"$LAUNCHER" --install-shortcut' in body
    assert "LANEX_NO_SHORTCUT" in body
    assert "die " not in body
    assert script.count("shortcut_stage") >= 3  # defined, plain path, wizard finish
