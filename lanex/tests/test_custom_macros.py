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
"""Custom hard-macro insertion (controller + overlay + CLI argv + LibreLane round-trip)."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest


def _b64(s: str | bytes) -> str:
    if isinstance(s, str):
        s = s.encode()
    return base64.b64encode(s).decode()


def _views(gds=True, lef=True, lib=False, nl=False, spef=False, spice=False):
    v = {}
    if gds:
        v["gds"] = {"filename": "m.gds", "content_b64": _b64("gds-bytes")}
    if lef:
        v["lef"] = {"filename": "m.lef", "content_b64": _b64("MACRO m\nEND m\n")}
    if lib:
        v["lib"] = {"filename": "m.lib", "content_b64": _b64("library(m){}")}
    if nl:
        v["nl"] = {"filename": "m.v", "content_b64": _b64("module m(); endmodule")}
    if spef:
        v["spef"] = {"filename": "m.spef", "content_b64": _b64("*SPEF")}
    if spice:
        v["spice"] = {"filename": "m.spice", "content_b64": _b64(".subckt m")}
    return v


# --------------------------------------------------------------------------- #
# Variable reality (integrates with real LibreLane, no invented vars).
# --------------------------------------------------------------------------- #
def test_macros_is_a_real_librelane_variable():
    from lanex.controller import introspect
    real = {v["name"] if isinstance(v, dict) else getattr(v, "name", "")
            for v in introspect.list_variables()}
    assert "MACROS" in real, "MACROS is not a real LibreLane config variable"


# --------------------------------------------------------------------------- #
# Save: required views, name + instance validation, confinement.
# --------------------------------------------------------------------------- #
def test_save_requires_both_gds_and_lef(tmp_path):
    from lanex.controller import custommacros as cm
    # LEF only -> rejected (GDS missing).
    assert not cm.save_macro(str(tmp_path), "m", views=_views(gds=False, lef=True))["ok"]
    # GDS only -> rejected (LEF missing).
    assert not cm.save_macro(str(tmp_path), "m", views=_views(gds=True, lef=False))["ok"]
    # Both -> accepted.
    assert cm.save_macro(str(tmp_path), "m", views=_views())["ok"]


def test_save_rejects_bad_module_name(tmp_path):
    from lanex.controller import custommacros as cm
    for bad in ("", "9starts_with_digit", "has space", "has-dash", "a/b"):
        r = cm.save_macro(str(tmp_path), bad, views=_views())
        assert not r["ok"], bad


def test_save_files_confined_to_macros_subdir(tmp_path):
    from lanex.controller import custommacros as cm
    r = cm.save_macro(str(tmp_path), "m", views=_views())
    assert r["ok"]
    assert (tmp_path / "macros" / "m" / "m.gds").is_file()
    assert (tmp_path / "macros" / "m" / "m.lef").is_file()
    # A filename with path components is stripped to its basename (no escape).
    r2 = cm.save_macro(str(tmp_path), "m2", views={
        "gds": {"filename": "../../evil.gds", "content_b64": _b64("x")},
        "lef": {"filename": "m2.lef", "content_b64": _b64("MACRO m2\nEND m2\n")}})
    assert r2["ok"]
    assert not (tmp_path.parent / "evil.gds").exists()
    assert (tmp_path / "macros" / "m2" / "evil.gds").is_file()


def test_instance_validation(tmp_path):
    from lanex.controller import custommacros as cm
    # Bad orientation.
    r = cm.save_macro(str(tmp_path), "m", views=_views(),
                      instances=[{"name": "u", "orientation": "Z"}])
    assert not r["ok"] and "orientation" in r["error"]
    # Bad location (not two numbers).
    r = cm.save_macro(str(tmp_path), "m", views=_views(),
                      instances=[{"name": "u", "location": "100"}])
    assert not r["ok"] and "location" in r["error"]
    # Duplicate instance names.
    r = cm.save_macro(str(tmp_path), "m", views=_views(),
                      instances=[{"name": "u"}, {"name": "u"}])
    assert not r["ok"] and "duplicate" in r["error"]
    # Bad instance name.
    r = cm.save_macro(str(tmp_path), "m", views=_views(),
                      instances=[{"name": "has space"}])
    assert not r["ok"]


def test_location_string_and_list_both_parse(tmp_path):
    from lanex.controller import custommacros as cm
    r = cm.save_macro(str(tmp_path), "m", views=_views(),
                      instances=[{"name": "a", "location": "100 200", "orientation": "N"},
                                 {"name": "b", "location": [10, 20], "orientation": "FS"},
                                 {"name": "c", "location": None}])
    assert r["ok"], r
    macros = cm.build_macros_dict(str(tmp_path))
    inst = macros["m"]["instances"]
    assert inst["a"]["location"] == [100.0, 200.0]
    assert inst["b"]["location"] == [10.0, 20.0]
    assert inst["c"]["location"] is None        # blank => automatic placement
    assert inst["b"]["orientation"] == "FS"


# --------------------------------------------------------------------------- #
# build_macros_dict shape: corner-keyed dicts, lists, dir:: paths.
# --------------------------------------------------------------------------- #
def test_build_macros_dict_shape(tmp_path):
    from lanex.controller import custommacros as cm
    assert cm.save_macro(str(tmp_path), "sram", views=_views(lib=True, nl=True, spef=True, spice=True),
                         instances=[{"name": "u_sram", "location": [5, 6], "orientation": "N"}])["ok"]
    m = cm.build_macros_dict(str(tmp_path))["sram"]
    assert isinstance(m["gds"], list) and m["gds"][0].startswith("dir::macros/sram/")
    assert isinstance(m["lef"], list)
    assert isinstance(m["nl"], list)            # list-shaped view
    assert isinstance(m["spice"], list)
    assert m["lib"] == {"*": [m["lib"]["*"][0]]}  # corner-keyed dict
    assert list(m["spef"].keys()) == ["*"]
    assert m["instances"]["u_sram"]["orientation"] == "N"


def test_disabled_macro_excluded(tmp_path):
    from lanex.controller import custommacros as cm
    cm.save_macro(str(tmp_path), "a", views=_views())
    cm.save_macro(str(tmp_path), "b", views=_views())
    cm.set_enabled(str(tmp_path), "b", False)
    d = cm.build_macros_dict(str(tmp_path))
    assert "a" in d and "b" not in d


def test_build_merges_user_config_macros(tmp_path):
    from lanex.controller import custommacros as cm
    (tmp_path / "config.json").write_text(json.dumps({
        "DESIGN_NAME": "top",
        "MACROS": {"existing": {"gds": ["dir::x.gds"], "lef": ["dir::x.lef"]}},
    }), encoding="utf-8")
    cm.save_macro(str(tmp_path), "added", views=_views())
    d = cm.build_macros_dict(str(tmp_path))
    assert "existing" in d and "added" in d   # GUI macro augments, doesn't clobber


# --------------------------------------------------------------------------- #
# Overlay file lifecycle.
# --------------------------------------------------------------------------- #
def test_write_overlay_creates_and_removes(tmp_path):
    from lanex.controller import custommacros as cm
    # No macros -> no overlay, returns None.
    assert cm.write_overlay(str(tmp_path)) is None
    assert not (tmp_path / ".gui-macros.json").exists()
    # Add one -> overlay written with MACROS.
    cm.save_macro(str(tmp_path), "m", views=_views())
    p = cm.write_overlay(str(tmp_path))
    assert p and Path(p).is_file()
    doc = json.loads(Path(p).read_text())
    assert "MACROS" in doc and "m" in doc["MACROS"]
    # Disable all -> overlay removed, returns None (a stale overlay can't linger).
    cm.set_enabled(str(tmp_path), "m", False)
    assert cm.write_overlay(str(tmp_path)) is None
    assert not (tmp_path / ".gui-macros.json").exists()


def test_set_enabled_and_remove(tmp_path):
    from lanex.controller import custommacros as cm
    cm.save_macro(str(tmp_path), "m", views=_views())
    assert cm.set_enabled(str(tmp_path), "m", False)["ok"]
    assert not cm.set_enabled(str(tmp_path), "nope", False)["ok"]
    assert cm.remove_macro(str(tmp_path), "m")["ok"]
    assert not (tmp_path / "macros" / "m").exists()
    assert cm.list_macros(str(tmp_path))["macros"] == []


def test_resave_carries_forward_unuploaded_views(tmp_path):
    from lanex.controller import custommacros as cm
    cm.save_macro(str(tmp_path), "m", views=_views(lib=True))
    # Re-save with only instances changed (no files re-uploaded) -> GDS/LEF/LIB kept.
    r = cm.save_macro(str(tmp_path), "m", views={},
                      instances=[{"name": "u", "location": [1, 2]}])
    assert r["ok"], r
    m = cm.build_macros_dict(str(tmp_path))["m"]
    assert m["gds"] and m["lef"] and m["lib"]
    assert m["instances"]["u"]["location"] == [1.0, 2.0]


# --------------------------------------------------------------------------- #
# CLI argv: overlay rides as a relative positional config (container mode).
# --------------------------------------------------------------------------- #
def test_dockerized_argv_includes_overlay_positional(tmp_path):
    from lanex.controller.container_run import build_dockerized_argv
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / ".gui-macros.json").write_text("{}")
    argv = build_dockerized_argv(
        config_file=str(tmp_path / "config.json"),
        extra_config_files=[str(tmp_path / ".gui-macros.json")],
        design_dir=str(tmp_path), flow="Classic", pdk="sky130A", tag="t")
    assert "config.json" in argv and ".gui-macros.json" in argv
    i_cfg, i_ov = argv.index("config.json"), argv.index(".gui-macros.json")
    assert i_ov == i_cfg + 1                       # adjacent positional, after main config
    assert argv.index("--dockerized") < i_cfg      # config files are inner (post --dockerized)


# --------------------------------------------------------------------------- #
# The decisive proof: the overlay parses into real LibreLane Macro objects.
# --------------------------------------------------------------------------- #
def test_overlay_compiles_via_librelane(tmp_path):
    pytest.importorskip("librelane")
    from typing import Optional, Dict
    from librelane.config.variable import Variable, Macro, Instance
    from librelane.common import GenericDict
    from lanex.controller import custommacros as cm

    assert cm.save_macro(
        str(tmp_path), "sky130_sram_1kbyte", views=_views(lib=True),
        instances=[{"name": "u_sram", "location": [100, 200], "orientation": "N"},
                   {"name": "u_sram2", "location": None, "orientation": "FS"}])["ok"]
    overlay = json.loads(Path(cm.write_overlay(str(tmp_path))).read_text())

    # Resolve dir:: -> DESIGN_DIR exactly like LibreLane's preprocessor, so the
    # built-in path-existence check runs against the files we actually wrote.
    def resolve(o):
        if isinstance(o, str):
            return o.replace("dir::", str(tmp_path) + "/")
        if isinstance(o, list):
            return [resolve(x) for x in o]
        if isinstance(o, dict):
            return {k: resolve(v) for k, v in o.items()}
        return o

    _, final = Variable("MACROS", Optional[Dict[str, Macro]], "t").compile(
        GenericDict({"MACROS": resolve(overlay["MACROS"])}),
        warning_list_ref=[], permissive_typing=True)
    macro = final["sky130_sram_1kbyte"]
    assert isinstance(macro, Macro)
    assert len(macro.gds) == 1 and len(macro.lef) == 1
    assert "*" in macro.lib
    assert isinstance(macro.instances["u_sram"], Instance)
    # location is Decimal-typed; auto-place instance keeps None.
    assert macro.instances["u_sram"].location is not None
    assert macro.instances["u_sram2"].location is None
    assert str(macro.instances["u_sram2"].orientation) == "FS"
