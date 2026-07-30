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
"""Round-75 correctness locks — the two bugs the first real Windows-appliance
install hit, neither of which any prior test could see because both need a
server whose working directory it never chose:

  * #1 — the inherited working directory. ``wsl.exe`` translates the CALLING
    process's Windows cwd into the Linux one, and the Windows launcher lives in
    ``C:\\Program Files\\LanEx``, so the server came up in
    ``/mnt/c/Program Files/LanEx`` — unwritable for the appliance user. Anything
    defaulting to "the current directory" then failed there: "Could not copy the
    SPM example: [Errno 13] Permission denied:
    '/mnt/c/Program Files/LanEx/spm_example'", and a file picker offering that
    same dead end as "Current dir".
  * #2 — GDS3D's toolchain. A missing compiler returned a copy-paste apt command
    "then click Build again", i.e. a hand-off to a terminal the Windows
    installer promises the user will never see — while the very next apt call in
    the same function proved the machinery to install it was already there. Plus
    the reason that call would have failed anyway: the appliance image bake
    deletes ``/var/lib/apt/lists/*``, so an install with no index refresh dies
    with "Unable to locate package".

Pure stdlib — no EDA tools, no container engine, no apt, no live run.
"""
from __future__ import annotations

import os
import platform
from pathlib import Path

import pytest

from lanex import cli
from lanex.controller import installer
from lanex.server import routes

REPO = Path(__file__).resolve().parents[2]


def _deny_access(monkeypatch, denied: Path) -> None:
    """Make ``os.access`` report *denied* unwritable, everything else honestly."""
    real = os.access

    def fake(path, mode, **kw):
        try:
            same = Path(str(path)) == denied
        except Exception:
            same = False
        if same and mode & os.W_OK:
            return False
        return real(path, mode, **kw)

    monkeypatch.setattr(os, "access", fake)


# ------------------------------------------------------- #1 the inherited cwd
def test_server_leaves_an_unwritable_cwd(monkeypatch, tmp_path):
    # The Program Files case: cwd exists and is readable, but nothing can be
    # created in it. The server must not keep it — every "current directory"
    # default resolves against it and every child process inherits it.
    monkeypatch.chdir(tmp_path)
    _deny_access(monkeypatch, tmp_path)
    cli._leave_unwritable_cwd()
    assert Path.cwd() != tmp_path
    assert os.access(str(Path.cwd()), os.W_OK | os.X_OK)


def test_server_keeps_a_writable_cwd(monkeypatch, tmp_path):
    # The other half of the contract: a deliberate `cd my-design && lanex` keeps
    # its cwd, because relative paths typed into the GUI resolve against it.
    monkeypatch.chdir(tmp_path)
    cli._leave_unwritable_cwd()
    assert Path.cwd().resolve() == tmp_path.resolve()


def test_relative_design_dir_survives_the_cwd_move(monkeypatch, tmp_path):
    # Ordering lock: the cwd move happens AFTER the path arguments are resolved,
    # so `lanex --design-dir ./cpu` still means ./cpu and not <home>/cpu.
    design = tmp_path / "cpu"
    design.mkdir()
    monkeypatch.chdir(tmp_path)
    _deny_access(monkeypatch, tmp_path)

    from lanex.server import app as server_app

    class _FakeHTTPD:
        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(server_app, "make_server",
                        lambda **kw: (_FakeHTTPD(), 8765))
    monkeypatch.setattr(server_app, "serve_forever", lambda httpd, **kw: None)

    class _NoTimer:
        def __init__(self, *a, **kw):
            pass

        def start(self) -> None:
            pass

    monkeypatch.setattr(cli.threading, "Timer", _NoTimer)

    previous = routes._get_active_design_dir()
    try:
        rc = cli.main(["--no-browser", "--design-dir", "cpu"])
        assert rc == 0
        assert routes._get_active_design_dir() == str(design)
        # …and the move still happened.
        assert Path.cwd() != tmp_path
    finally:
        routes._ACTIVE_DESIGN_DIR.clear()
        if previous:
            routes._ACTIVE_DESIGN_DIR.append(previous)


def test_default_write_base_avoids_an_unwritable_cwd(monkeypatch, tmp_path):
    # What "Load the SPM example" copies into when the user named no folder.
    monkeypatch.chdir(tmp_path)
    _deny_access(monkeypatch, tmp_path)
    assert routes._default_write_base() == Path.home()


def test_default_write_base_is_the_cwd_when_usable(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert routes._default_write_base().resolve() == tmp_path.resolve()


class _CapturingHandler:
    """Minimal stand-in for the request handler: records what a route responds."""

    def __init__(self, path: str = "/api/fs-roots") -> None:
        self.path = path
        self.payload = None
        self.status = None

    def _send_json(self, obj, status: int = 200) -> None:
        self.payload = obj
        self.status = status


def test_file_picker_hides_an_unwritable_current_dir(monkeypatch, tmp_path):
    # The picker must not offer a root whose every write is denied — that was
    # "Current dir = /mnt/c/Program Files/LanEx" on the appliance.
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.chdir(tmp_path)
    _deny_access(monkeypatch, tmp_path)
    h = _CapturingHandler()
    routes.h_fs_roots(h)
    roots = h.payload["data"]["roots"]
    labels = [r["label"] for r in roots]
    assert "Home" in labels                     # the usable root stays
    assert "Current dir" not in labels
    assert str(tmp_path) not in [r["path"] for r in roots]


def test_file_picker_offers_a_writable_current_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.chdir(tmp_path)
    h = _CapturingHandler()
    routes.h_fs_roots(h)
    roots = h.payload["data"]["roots"]
    assert any(r["label"] == "Current dir" and
               Path(r["path"]).resolve() == tmp_path.resolve() for r in roots)


def test_copy_spm_permission_error_says_what_to_do(monkeypatch, tmp_path):
    # The message the user actually saw was the raw OSError, naming a path they
    # never picked. Replace it with an instruction, keep the 500.
    target = tmp_path / "locked"

    def boom(*a, **kw):
        raise PermissionError(13, "Permission denied", str(target / "spm_example"))

    monkeypatch.setattr(routes.shutil, "copytree", boom)
    monkeypatch.setattr(routes, "_dir_empty_or_absent", lambda p: True)
    h = _CapturingHandler("/api/copy-spm")
    h._body = {"design_dir": str(target)}
    routes.h_copy_spm(h)
    assert h.status == 500
    msg = h.payload["error"]
    assert "No permission" in msg
    assert "Browse" in msg
    assert "Errno 13" not in msg


@pytest.mark.skipif(not (REPO / "windows").is_dir(),
                    reason="source checkout only (the launcher isn't packaged)")
def test_windows_launcher_starts_the_server_in_the_home_dir():
    # The fix at the source. Guarded by a test because it is one word in a Go
    # string literal that reads like noise, and deleting it silently restores
    # a permission-denied SPM copy for every Windows user.
    src = (REPO / "windows" / "launcher" / "wsl.go").read_text(encoding="utf-8")
    assert 'cd ~ 2>/dev/null; exec lanex' in src
    # The three WSLg rules still hold: one wsl.exe, interactive bash.
    assert src.count('"bash", "-ic"') == 1


# --------------------------------------------------------- #2 GDS3D toolchain
def test_missing_build_tools_map_to_apt_packages():
    assert installer._gds3d_toolchain_packages(["git"]) == ["git"]
    assert installer._gds3d_toolchain_packages(["make"]) == ["build-essential"]
    # One package covers make AND the compiler — asking for it twice is apt's job.
    assert installer._gds3d_toolchain_packages(
        ["git", "make", "a C++ compiler"]) == ["git", "build-essential"]
    assert installer._gds3d_toolchain_packages([]) == []


def test_apt_install_refreshes_an_empty_index(monkeypatch, tmp_path):
    # The appliance ships with /var/lib/apt/lists/* deleted (the image bake), so
    # a plain `apt-get install` dies with "Unable to locate package".
    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "lock").write_bytes(b"")            # apt's own lock is not an index
    monkeypatch.setattr(installer, "_APT_LISTS_DIR", lists)
    calls: list = []
    monkeypatch.setattr(installer, "_run_argv",
                        lambda argv, **kw: calls.append(argv) or {"ok": True, "rc": 0})
    installer._apt_install(["build-essential"], label="x", key="gds3d")
    assert [c for c in calls if "update" in c], "no apt update before the install"
    assert calls[0][-1] == "update"
    assert calls[1][-1] == "build-essential"
    # Nothing here is attached to a terminal, so a debconf prompt from a
    # dependency would wedge the install with no one able to answer it.
    for c in calls:
        assert "DEBIAN_FRONTEND=noninteractive" in c
        assert "DPkg::Lock::Timeout=300" in c


def test_apt_install_skips_the_refresh_when_the_index_is_there(monkeypatch, tmp_path):
    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "archive.ubuntu.com_ubuntu_dists_noble_InRelease").write_bytes(b"x")
    monkeypatch.setattr(installer, "_APT_LISTS_DIR", lists)
    calls: list = []
    monkeypatch.setattr(installer, "_run_argv",
                        lambda argv, **kw: calls.append(argv) or {"ok": True, "rc": 0})
    installer._apt_install(["git"], label="x", key="gds3d")
    assert len(calls) == 1 and "install" in calls[0]


def test_apt_install_retries_once_on_a_stale_index(monkeypatch, tmp_path):
    # An appliance that sat unused while the archive moved on: the index exists
    # but is useless, and apt says the same "Unable to locate package" it says
    # for a typo. Refresh and try again before blaming the user.
    lists = tmp_path / "lists"
    lists.mkdir()
    (lists / "InRelease").write_bytes(b"x")
    monkeypatch.setattr(installer, "_APT_LISTS_DIR", lists)
    calls: list = []

    def fake(argv, **kw):
        calls.append(argv)
        if "install" in argv and len([c for c in calls if "install" in c]) == 1:
            return {"ok": False, "rc": 100,
                    "output": ["E: Unable to locate package build-essential"]}
        return {"ok": True, "rc": 0}

    monkeypatch.setattr(installer, "_run_argv", fake)
    res = installer._apt_install(["build-essential"], label="x", key="gds3d")
    assert res["ok"] is True
    assert [("update" in c) for c in calls] == [False, True, False]


def _stub_gds3d_env(monkeypatch, present: set):
    """Pretend to be a Debian host where only *present* commands exist."""
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer.shutil, "which",
                        lambda name, *a, **kw: ("/usr/bin/" + name) if name in present else None)
    monkeypatch.setattr(installer, "detect_environment", lambda: {"apt": True})
    monkeypatch.setattr(installer, "_missing_gds3d_dev_packages", lambda: [])
    monkeypatch.setattr(installer, "_x11_fixed_fonts_missing", lambda: False)
    from lanex.controller import platform_env
    monkeypatch.setattr(platform_env, "mesa_dri_present", lambda: True)
    monkeypatch.setattr(installer, "_verify_install", lambda key: True)


def test_gds3d_installs_its_own_toolchain_instead_of_asking_for_a_terminal(
        monkeypatch, tmp_path):
    present: set = set()          # no git, no make, no compiler
    _stub_gds3d_env(monkeypatch, present)
    installed: list = []

    def fake_apt(packages, *, label, key):
        installed.append(list(packages))
        present.update({"git", "make", "g++"})     # apt did its job
        return {"ok": True, "rc": 0}

    monkeypatch.setattr(installer, "_apt_install", fake_apt)
    monkeypatch.setattr(installer, "_run_argv",
                        lambda argv, **kw: {"ok": True, "rc": 0})
    monkeypatch.setattr(installer.Path, "home", staticmethod(lambda: tmp_path))
    (tmp_path / ".local" / "bin").mkdir(parents=True)
    (tmp_path / ".local" / "bin" / "gds3d").write_bytes(b"")

    res = installer._install_gds3d()
    assert installed, "the toolchain was never installed — still a hand-off"
    assert "build-essential" in installed[0] and "git" in installed[0]
    assert res["ok"] is True


def test_gds3d_reports_honestly_when_the_toolchain_install_fails(monkeypatch):
    present: set = set()
    _stub_gds3d_env(monkeypatch, present)
    # apt runs and fails: nothing appears, so say so — and do NOT start a build
    # that cannot compile.
    monkeypatch.setattr(installer, "_apt_install",
                        lambda pkgs, **kw: {"ok": False, "rc": 100})
    ran: list = []
    monkeypatch.setattr(installer, "_run_argv",
                        lambda argv, **kw: ran.append(argv) or {"ok": True, "rc": 0})
    res = installer._install_gds3d()
    assert res["ok"] is False
    assert "a C++ compiler" in res["guidance"]
    assert not ran, "a build was attempted with no compiler"


def test_gds3d_without_apt_is_still_honest(monkeypatch):
    # The bundled LibreLane image (Nix base, no apt): nothing to auto-install
    # with, so don't print Debian instructions that will never apply.
    monkeypatch.setattr(installer.sys, "platform", "linux")
    monkeypatch.setattr(installer.shutil, "which", lambda name, *a, **kw: None)
    monkeypatch.setattr(installer, "detect_environment", lambda: {"apt": False})
    res = installer._install_gds3d()
    assert res["ok"] is False
    assert "not bundled in this image" in res["guidance"]
    assert "apt-get" not in res["guidance"]
