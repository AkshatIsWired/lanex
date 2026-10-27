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
"""Round-76 correctness locks — two "the status is a lie" bugs.

  * #1 — GDS3D removal searched fewer places than GDS3D detection. The probe
    (``platform_env.resolve_user_bin`` via ``user_bin_dirs``) accepts the BUILD
    TREE output ``$LANEX_HOME/tools/GDS3D/linux/GDS3D`` that ``make`` leaves
    behind, but ``_uninstall_gds3d`` only deleted ``~/.local/bin/gds3d`` and
    ``/usr/local/bin/gds3d``. So Remove deleted the installed copy, the probe
    still found the build output, and the card stayed "installed" with only a
    Remove button — no route back to Install — while a second click reported
    "GDS3D binary not found in ~/.local/bin or /usr/local/bin (already
    removed?)". Whatever the probe accepts, removal must delete.
  * #2 — the Desktop-layout-viewers block probed HOST binaries only, so
    KLayout/Magic read "not found" on the appliance, where they ship in the
    pulled LibreLane image and the Layout tab launches them from there.
"""

from pathlib import Path

from lanex.controller import installer, platform_env

_STATIC = Path(__file__).resolve().parents[1] / "server" / "static"


def _isolate_home(monkeypatch, root: Path) -> Path:
    """Point every home-derived path (``Path.home``, ``$HOME``, ``$LANEX_HOME``)
    at *root* so a removal test can never touch the developer's own install."""
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(installer.Path, "home", classmethod(lambda cls: root))
    monkeypatch.setenv("HOME", str(root))
    monkeypatch.setenv("USERPROFILE", str(root))
    monkeypatch.setenv("LANEX_HOME", str(root / ".lanex"))
    return root


def test_uninstall_gds3d_deletes_the_build_tree_binary(monkeypatch, tmp_path):
    # The stuck-card bug: make's output in the build tree is what the probe
    # found, so removal has to delete it or "installed" never clears.
    home = _isolate_home(monkeypatch, tmp_path / "home")
    installed = home / ".local" / "bin" / "gds3d"
    installed.parent.mkdir(parents=True)
    installed.write_text("#!/bin/sh\n")
    built = home / ".lanex" / "tools" / "GDS3D" / "linux" / "GDS3D"
    built.parent.mkdir(parents=True)
    built.write_text("ELF\n")
    built.chmod(0o755)

    res = installer.uninstall_tool("gds3d")

    assert res["ok"] is True
    assert not installed.exists()
    assert not built.exists(), "build-tree binary left behind — probe stays 'installed'"
    # Spelling of the recorded path follows whichever name matched on this
    # filesystem (case-insensitive on Windows/macOS, exact on Linux).
    assert any(str(built.parent) in p for p in res["removed"])
    # The source tree itself survives, so a re-install re-links instead of
    # re-cloning.
    assert built.parent.is_dir()
    # And the fact the UI reads is now false.
    assert platform_env.resolve_user_bin("gds3d", ["GDS3D"]) is None


def test_uninstall_gds3d_absent_is_success_not_a_dead_end(monkeypatch, tmp_path):
    # Nothing anywhere = already removed. Reporting ok:False here is what left
    # the card showing Remove with no way back to "Build & install".
    _isolate_home(monkeypatch, tmp_path / "home")

    res = installer.uninstall_tool("gds3d")

    assert res["ok"] is True
    assert res["already_absent"] is True
    assert res["removed"] == []


def test_uninstall_gds3d_reports_a_copy_it_cannot_own(monkeypatch, tmp_path):
    # A GDS3D LanEx didn't install (somewhere else on $PATH) keeps the badge
    # "installed" after removal — say so instead of claiming success.
    home = _isolate_home(monkeypatch, tmp_path / "home")
    foreign = tmp_path / "opt" / "gds3d"
    foreign.parent.mkdir(parents=True)
    foreign.write_text("#!/bin/sh\n")
    monkeypatch.setattr(platform_env, "resolve_user_bin",
                        lambda name, alts=None, path=None: str(foreign))

    res = installer.uninstall_tool("gds3d")

    assert res["ok"] is False
    assert str(foreign) in res["reason"]
    assert "Recheck" in res["reason"]
    assert home.is_dir()


def test_desktop_viewer_badges_count_the_container_image():
    # KLayout/Magic ship in the image; a host-only probe called them "not found"
    # while the Layout tab launched them fine.
    js = (_STATIC / "modules" / "tools.js").read_text(encoding="utf-8")
    body = js.split("async function renderDesktopViewers")[1].split("\n}")[0]
    assert "in_container" in body and "image_present" in body
    assert "in container image" in body
    # The block is painted from the same probe result as the tool grid.
    assert "renderDesktopViewers(info);" in js


def test_gds3d_remove_reprobes_instead_of_repainting_stale_state():
    js = (_STATIC / "modules" / "tools.js").read_text(encoding="utf-8")
    handler = js.split('btn-remove-gds3d")?.addEventListener')[1].split("\n  });")[0]
    assert "renderTools(true)" in handler, \
        "removal must re-probe; repainting the captured `info` shows the old status"
    assert "renderRecommendedTools(info)" not in handler
