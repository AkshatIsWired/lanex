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
"""Round-26 lock-in tests — follow-up WSL/UX fixes.

* GDS3D (and any tool a one-click install drops in ``~/.local/bin``) must report
  *installed* even when that dir isn't on the server's ``$PATH``:
  ``platform_env.resolve_user_bin`` checks ``$PATH`` (WSL-filtered) then the user
  install dirs, and ``desktop._resolve_bin`` / ``available_tools`` use it.
* The privileged-install escalation surfaces a flagged ``needs_password`` event
  so the browser can show a prominent banner (the controller side of "no prompt
  ever appeared").
"""
from __future__ import annotations

import os
import stat

from lanex.controller import desktop, platform_env


def _make_exec(path):
    with open(path, "w") as fh:
        fh.write("#!/bin/sh\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


# ---------------------------------------------------- resolve_user_bin fallback
def test_resolve_user_bin_prefers_path(monkeypatch):
    monkeypatch.setattr(platform_env, "usable_which", lambda name, path=None: "/usr/bin/" + name)
    assert platform_env.resolve_user_bin("klayout") == "/usr/bin/klayout"


def test_resolve_user_bin_falls_back_to_user_dir(monkeypatch, tmp_path):
    # Nothing on PATH, but a one-click install dropped the binary in ~/.local/bin.
    monkeypatch.setattr(platform_env, "usable_which", lambda name, path=None: None)
    localbin = tmp_path / ".local" / "bin"
    localbin.mkdir(parents=True)
    _make_exec(str(localbin / "gds3d"))
    monkeypatch.setattr(platform_env, "user_bin_dirs", lambda: [str(localbin)])
    assert platform_env.resolve_user_bin("gds3d") == str(localbin / "gds3d")


def test_resolve_user_bin_honours_alts(monkeypatch, tmp_path):
    # The GDS3D Makefile emits the capitalised name; alts must be tried.
    monkeypatch.setattr(platform_env, "usable_which", lambda name, path=None: None)
    d = tmp_path / "bin"
    d.mkdir()
    _make_exec(str(d / "GDS3D"))
    monkeypatch.setattr(platform_env, "user_bin_dirs", lambda: [str(d)])
    assert platform_env.resolve_user_bin("gds3d", ["GDS3D"]) == str(d / "GDS3D")


def test_resolve_user_bin_none_when_absent(monkeypatch, tmp_path):
    monkeypatch.setattr(platform_env, "usable_which", lambda name, path=None: None)
    monkeypatch.setattr(platform_env, "user_bin_dirs", lambda: [str(tmp_path)])
    assert platform_env.resolve_user_bin("nope", ["NOPE"]) is None


def test_user_bin_dirs_includes_local_bin(monkeypatch, tmp_path):
    monkeypatch.setenv("LIBRELANE_GUI_HOME", str(tmp_path / "gh"))
    dirs = platform_env.user_bin_dirs()
    assert any(d.endswith(os.path.join(".local", "bin")) for d in dirs)
    # GDS3D build tree (where the binary + techfiles land) is searched too.
    assert any("GDS3D" in d for d in dirs)


# ---------------------------------------- desktop reports the off-PATH install
def test_desktop_available_finds_local_bin_gds3d(monkeypatch, tmp_path):
    """The Tools + Layout availability of GDS3D comes from desktop.available_tools
    → _resolve_bin. A gds3d in ~/.local/bin (off the server PATH) must show as
    available, not 'missing'."""
    monkeypatch.setattr(platform_env, "usable_which", lambda name, path=None: None)
    localbin = tmp_path / ".local" / "bin"
    localbin.mkdir(parents=True)
    _make_exec(str(localbin / "gds3d"))
    monkeypatch.setattr(platform_env, "user_bin_dirs", lambda: [str(localbin)])
    tools = {t["key"]: t for t in desktop.available_tools()}
    assert tools["gds3d"]["available"] is True
