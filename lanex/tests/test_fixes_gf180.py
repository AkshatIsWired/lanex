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
"""Lock-in tests for the gf180mcu-observed WSL fixes.

1. KLayout layer-properties (.lyp) discovery generalizes past the sky130-shaped
   ``<variant>.lyp`` name (gf180mcu ships ``gf180mcu.lyp``); container mode only
   passes ``-l`` when the file exists (a missing one made KLayout error errno=2).
2. A root-owned ciel store is detected (owner-scoped self-heal can't fix it) and
   the one-click ``chown`` repair builds an escalated, ~/.ciel-scoped command.
"""
from __future__ import annotations

import os
from pathlib import Path

from lanex.controller import container_tools, installer
from lanex.controller.desktop import find_klayout_lyp


def _make_libs_tech(root: Path, *lyp_names: str, xsect: bool = True) -> Path:
    """Create ``<root>/libs.tech/klayout/tech/`` holding the given .lyp files."""
    tech = root / "libs.tech" / "klayout" / "tech"
    tech.mkdir(parents=True)
    for n in lyp_names:
        (tech / n).write_text("<layer-properties/>", encoding="utf-8")
    if xsect:
        xs = tech / "xsect"
        xs.mkdir()
        (xs / "cross_section.lyp").write_text("<xs/>", encoding="utf-8")
    return root / "libs.tech"


# ---------------------------------------------------------------- .lyp discovery

def test_find_lyp_exact_variant(tmp_path: Path) -> None:
    lt = _make_libs_tech(tmp_path, "sky130A.lyp")
    assert find_klayout_lyp(lt, "sky130A") == lt / "klayout" / "tech" / "sky130A.lyp"


def test_find_lyp_family_fallback_gf180(tmp_path: Path) -> None:
    # gf180 ships the family file, not gf180mcuC.lyp — the exact lookup misses.
    lt = _make_libs_tech(tmp_path, "gf180mcu.lyp")
    got = find_klayout_lyp(lt, "gf180mcuC")
    assert got == lt / "klayout" / "tech" / "gf180mcu.lyp"


def test_find_lyp_glob_excludes_xsect(tmp_path: Path) -> None:
    # Only the cross-section props exist under tech/xsect/ — never picked, since
    # a bare `-l xsect.lyp` would colour the layout with the wrong table.
    lt = _make_libs_tech(tmp_path, xsect=True)  # no top-level .lyp, only xsect/
    assert find_klayout_lyp(lt, "gf180mcuC") is None


def test_find_lyp_glob_last_resort(tmp_path: Path) -> None:
    lt = _make_libs_tech(tmp_path, "weirdname.lyp", xsect=False)
    assert find_klayout_lyp(lt, "gf180mcuC") == lt / "klayout" / "tech" / "weirdname.lyp"


def test_find_lyp_absent(tmp_path: Path) -> None:
    (tmp_path / "libs.tech" / "klayout").mkdir(parents=True)
    assert find_klayout_lyp(tmp_path / "libs.tech", "sky130A") is None


# ---------------------------------------------- container klayout argv guard

def test_container_klayout_omits_l_when_no_lyp(tmp_path: Path) -> None:
    # No PDK tree at all → no -l (the old `if lyp:` always-true bug passed a
    # nonexistent path and KLayout errored "Unable to open file … errno=2").
    (tmp_path / "gf180mcuC").mkdir()
    cmd = container_tools._tool_command(
        "klayout", gds=Path("/x/spm.gds"), pdk="gf180mcuC",
        pdk_root=str(tmp_path), odb=None)
    assert "-l" not in cmd
    assert cmd[0] == "klayout" and str(Path("/x/spm.gds")) in cmd


def test_container_klayout_includes_existing_lyp(tmp_path: Path) -> None:
    _make_libs_tech(tmp_path / "gf180mcuC", "gf180mcu.lyp", xsect=False)
    cmd = container_tools._tool_command(
        "klayout", gds=Path("/x/spm.gds"), pdk="gf180mcuC",
        pdk_root=str(tmp_path), odb=None)
    assert "-l" in cmd
    lyp = cmd[cmd.index("-l") + 1]
    assert lyp.endswith("gf180mcu.lyp") and Path(lyp).is_file()


# ------------------------------------------------ ciel permission detection

def test_permission_status_clean_when_all_ours(tmp_path: Path) -> None:
    store = tmp_path / "ciel" / "sky130" / "versions" / "v1"
    store.mkdir(parents=True)
    (store / "f").write_text("x", encoding="utf-8")
    res = installer.ciel_permission_status(pdk_root=str(tmp_path))
    assert res["needs_root"] is False


def test_permission_status_detects_foreign_owner(tmp_path: Path, monkeypatch) -> None:
    store = tmp_path / "ciel" / "gf180mcu" / "versions" / "v1"
    store.mkdir(parents=True)
    (store / "gf180mcuB").mkdir()
    # Simulate root ownership: make our uid differ from the files' real uid.
    real_uid = os.getuid()
    monkeypatch.setattr(installer.os, "getuid", lambda: real_uid + 4242)
    res = installer.ciel_permission_status(pdk_root=str(tmp_path))
    assert res["needs_root"] is True
    assert res["chown_cmd"].startswith("sudo chown -R ")
    assert str(tmp_path) in res["chown_cmd"]
    assert res["sample"]  # named at least one offending path


def test_fix_permissions_builds_escalated_chown(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "ciel").mkdir()
    seen = {}

    def fake_run_argv(argv, *, label, key):
        seen["argv"] = argv
        seen["key"] = key
        return {"ok": True, "rc": 0}

    monkeypatch.setattr(installer, "_run_argv", fake_run_argv)
    monkeypatch.setattr(installer, "_begin_job", lambda k: True)
    monkeypatch.setattr(installer, "_end_job", lambda k: None)
    res = installer.fix_ciel_permissions(pdk_root=str(tmp_path))
    assert res.get("status") == "started"
    # worker runs in a thread; give it a beat
    import time
    for _ in range(50):
        if "argv" in seen:
            break
        time.sleep(0.02)
    assert seen["argv"][0] == "sudo" and seen["argv"][1] == "chown"
    assert seen["argv"][2] == "-R"
    assert seen["argv"][-1] == str(tmp_path)


def test_fix_permissions_no_store_is_ok(tmp_path: Path) -> None:
    res = installer.fix_ciel_permissions(pdk_root=str(tmp_path / "nope"))
    assert res["ok"] is True and "note" in res
