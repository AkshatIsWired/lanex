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
"""The system file/folder picker (controller/native_pick.py): modes and filters."""

from lanex.controller import native_pick as np


def test_extensions_are_cleaned_before_reaching_a_dialog():
    assert np._clean_exts([".ZIP", "zip", "gz", "", "*.exe", "a|b", "x;y", "../x", None]) == [".zip", ".gz"]
    assert np._clean_exts(None) == []


def test_windows_filter_lists_the_types_then_all_files():
    assert np._win_filter([".zip"]) == "ZIP files (*.zip)|*.zip|All files (*.*)|*.*"
    assert np._win_filter([]) == ""


def _capture(monkeypatch, wsl):
    seen = {}
    monkeypatch.setattr(np.platform_env, "is_wsl", lambda: wsl)
    monkeypatch.setattr(np, "_pick_windows", lambda m, t, s, e=None: seen.update(win=(m, e)) or ["/a.zip"])
    monkeypatch.setattr(np, "_pick_linux", lambda m, t, s, e=None: seen.update(lin=(m, e)) or [])
    return seen


def test_pick_passes_mode_and_clean_extensions(monkeypatch):
    seen = _capture(monkeypatch, True)
    assert np.pick("file", "Choose", "", exts=["ZIP"]) == {"native": True, "paths": ["/a.zip"]}
    assert seen["win"] == ("file", [".zip"])
    seen = _capture(monkeypatch, False)
    np.pick("bogus")
    assert seen["lin"] == ("folder", [])


def test_linux_single_file_uses_a_filter(monkeypatch):
    calls = []

    class R:
        returncode = 0
        stdout = "/home/x/b.zip\n"
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(np.shutil, "which", lambda n: "/usr/bin/zenity" if n == "zenity" else None)
    monkeypatch.setattr(np.subprocess, "run", lambda cmd, **k: calls.append(cmd) or R())
    assert np._pick_linux("file", "Pick", "/home/x", [".zip"]) == ["/home/x/b.zip"]
    cmd = calls[0]
    assert "--directory" not in cmd and "--multiple" not in cmd
    assert cmd[cmd.index("--file-filter") + 1] == "*.zip"
