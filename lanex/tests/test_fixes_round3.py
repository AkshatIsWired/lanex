# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Regression tests for the round-3 UX-fix batch (the six reported issues + scan).

All pure (no EDA tools / PDK / Docker needed) so they run anywhere CI does.
"""
from __future__ import annotations


# --- #4: desktop viewers launch with the PDK tech files (Magic blank-window fix)

def test_magic_argv_injects_magicrc():
    from lanex.controller import desktop
    # With a magicrc + use_tech, Magic must be launched with -rcfile so it reads
    # GDS layers (bare `magic <gds>` falls back to the 'minimum' tech → empty).
    argv = desktop._build_argv("magic", "magic", "/x.gds", {"magicrc": "/pdk/sky130A.magicrc"}, True)
    assert argv == ["magic", "-rcfile", "/pdk/sky130A.magicrc", "/x.gds"]
    # use_tech=False → the tool's default view (lets the user choose).
    assert desktop._build_argv("magic", "magic", "/x.gds", {"magicrc": "/p"}, False) == ["magic", "/x.gds"]
    # Without a magicrc at all, fall back to the bare invocation.
    assert desktop._build_argv("magic", "magic", "/x.gds", {}, True) == ["magic", "/x.gds"]


def test_klayout_argv_uses_layer_props_when_present():
    from lanex.controller import desktop
    argv = desktop._build_argv("klayout", "klayout", "/x.gds", {"klayout_lyp": "/pdk/sky130A.lyp"}, True)
    assert argv[:3] == ["klayout", "-l", "/pdk/sky130A.lyp"]
    assert desktop._build_argv("klayout", "klayout", "/x.gds", {"klayout_lyp": "/p"}, False) == ["klayout", "/x.gds"]
    assert desktop._build_argv("klayout", "klayout", "/x.gds", {}, True) == ["klayout", "/x.gds"]


def test_desktop_tools_include_gds3d_as_3d():
    from lanex.controller import desktop
    tools = {t["key"]: t for t in desktop.available_tools()}
    assert tools["gds3d"]["kind"] == "3D"
    assert tools["magic"]["kind"] == "2D"
    # 'available' is just a which() probe — boolean either way, never raises.
    assert isinstance(tools["gds3d"]["available"], bool)


def test_pdk_tech_files_never_raises_without_pdk():
    from lanex.controller import desktop
    out = desktop._pdk_tech_files(None, None)
    assert out == {"magicrc": None, "klayout_lyp": None, "root": None}


# --- #4: GDS3D guided-install is wired into the installer ---------------------

def test_gds3d_known_to_installer():
    from lanex.controller import installer
    # verify mapping must recognise gds3d (else install_tool would mis-report).
    assert isinstance(installer._verify_install("gds3d"), bool)


# --- #3: run-vs-run compare exposes a key-config block ------------------------

def test_compare_runs_has_key_config_block():
    from lanex.controller import history
    # Even with no runs, the shape must include key_config (empty dict), so the
    # frontend can always render the section.
    out = history.compare_runs([])
    assert "key_config" in out and isinstance(out["key_config"], dict)
    assert history._KEY_CONFIG_VARS  # curated, non-empty


# --- #3: non-finite metrics are genuine (presentation only) -------------------

def test_key_config_vars_are_strings():
    from lanex.controller import history
    assert all(isinstance(v, str) for v in history._KEY_CONFIG_VARS)
