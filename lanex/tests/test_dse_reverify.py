# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Tests for DSE sweep expansion + targeted re-verify argv (Phase 2)."""
from __future__ import annotations

import pytest

from lanex.controller import dse, reverify


def test_expand_sweep_grid():
    spec = {"axes": [{"var": "FP_CORE_UTIL", "values": [40, 50, 60]},
                     {"var": "PL_TARGET_DENSITY_PCT", "values": [55, 65]}], "mode": "grid"}
    combos = dse.expand_sweep(spec)
    assert len(combos) == 6
    assert {"FP_CORE_UTIL": "40", "PL_TARGET_DENSITY_PCT": "55"} in combos
    assert {"FP_CORE_UTIL": "60", "PL_TARGET_DENSITY_PCT": "65"} in combos


def test_expand_sweep_list_zip():
    spec = {"axes": [{"var": "FP_CORE_UTIL", "values": [40, 60]},
                     {"var": "CLOCK_PERIOD", "values": [10, 12]}], "mode": "list"}
    combos = dse.expand_sweep(spec)
    assert combos == [{"FP_CORE_UTIL": "40", "CLOCK_PERIOD": "10"},
                      {"FP_CORE_UTIL": "60", "CLOCK_PERIOD": "12"}]


def test_expand_sweep_list_mismatched_lengths():
    spec = {"axes": [{"var": "FP_CORE_UTIL", "values": [40, 60]},
                     {"var": "CLOCK_PERIOD", "values": [10]}], "mode": "list"}
    with pytest.raises(ValueError):
        dse.expand_sweep(spec)


def test_expand_sweep_unknown_var_rejected():
    spec = {"axes": [{"var": "TOTALLY_FAKE_VAR_XYZ", "values": [1, 2]}]}
    # Only enforced when librelane is importable; if names empty it's a skip.
    if dse._known_var_names():
        with pytest.raises(ValueError):
            dse.expand_sweep(spec)


def test_expand_sweep_combo_cap():
    # 5 axes * many values -> exceeds MAX_COMBOS.
    axes = [{"var": "FP_CORE_UTIL", "values": list(range(10))}]
    axes += [{"var": "PL_TARGET_DENSITY_PCT", "values": list(range(10))}]
    spec = {"axes": axes, "mode": "grid"}
    # If var validation kicks in these are real vars; 10x10=100 > 64.
    with pytest.raises(ValueError):
        dse.expand_sweep(spec)


def test_dse_run_tags_deterministic_unique():
    tags = dse.dse_run_tags("spm", 3)
    assert tags == ["dse-spm-00", "dse-spm-01", "dse-spm-02"]
    assert len(set(tags)) == 3


def test_dse_bool_formatting():
    spec = {"axes": [{"var": "RUN_LVS", "values": [True, False]}]}
    if dse._known_var_names() and "RUN_LVS" not in dse._known_var_names():
        pytest.skip("RUN_LVS not in this librelane")
    combos = dse.expand_sweep(spec)
    assert combos == [{"RUN_LVS": "true"}, {"RUN_LVS": "false"}]


def test_assemble_overrides_cleans_and_carries_context(tmp_path):
    # A2: the shared assembler must clean blanks (keeping real 0/False), pull PDK/
    # SCL out as kwargs, and carry the picker sources/extras through — for BOTH
    # the Setup path and the DSE sweep path (they call the same helper).
    from lanex.server import routes

    body = {
        "overrides": {"A": "1", "BLANK": "", "SPACE": "   ",
                      "ZERO": 0, "FALSE": False, "PDK": "sky130A",
                      "STD_CELL_LIBRARY": "sky130_fd_sc_hd"},
        "sources": ["src/spm.v"],
        "extras": [],
    }
    asm = routes._assemble_overrides(str(tmp_path), body)
    assert asm["pdk"] == "sky130A"
    assert asm["scl"] == "sky130_fd_sc_hd"
    # blank/whitespace dropped; real falsy values preserved; PDK/SCL pulled out.
    assert asm["overrides"] == {"A": "1", "ZERO": 0, "FALSE": False}
    assert asm["extra_sources"] == ["src/spm.v"]
    assert asm["extra_extras"] is None            # [] normalises to None
    assert asm["extra_config_files"] is None      # no macro overlay in a bare dir


def test_dse_and_setup_assemble_identically(tmp_path):
    # A2 regression guard (the audit's "golden-equality between the two entry
    # points"): given the same merged overrides + sources, a DSE sweep point and
    # a Setup run must produce byte-identical assembled kwargs.
    from lanex.server import routes

    setup_body = {"overrides": {"FP_CORE_UTIL": "50", "PDK": "sky130A"},
                  "sources": ["src/spm.v"], "extras": ["macro.v"]}
    # DSE builds: synthetic["overrides"] = {**base_overrides, **swept_point}
    base_overrides = {"PDK": "sky130A"}
    swept_point = {"FP_CORE_UTIL": "50"}
    dse_body = {"overrides": {**base_overrides, **swept_point},
                "sources": ["src/spm.v"], "extras": ["macro.v"]}
    a = routes._assemble_overrides(str(tmp_path), setup_body)
    b = routes._assemble_overrides(str(tmp_path), dse_body)
    assert a == b


def test_reverify_validate_rejects_unknown_step():
    res = reverify.validate("Totally.Fake.Step", {})
    if reverify._known_step_ids():
        assert res["ok"] is False


def test_reverify_argv_single_step(tmp_path):
    run = tmp_path / "runs" / "RUN_X"
    run.mkdir(parents=True)
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")
    argv = reverify.reverify_argv(
        run, "OpenROAD.STAPostPNR",
        overrides={"CLOCK_PERIOD": "8"},
        config_file=tmp_path / "config.json", design_dir=tmp_path,
        pdk="sky130A", scl="sky130_fd_sc_hd",
    )
    assert "--dockerized" in argv
    assert "-F" in argv and "OpenROAD.STAPostPNR" in argv
    assert "-T" in argv
    assert "--run-tag" in argv and "RUN_X" in argv
    assert "--overwrite" not in argv  # continue, don't wipe
    # override threaded through.
    assert any(a == "CLOCK_PERIOD=8" for a in argv)


def test_reverify_kwargs():
    kw = reverify.reverify_kwargs("/x/runs/TAG", "Magic.DRC", overrides={"RUN_MAGIC_DRC": "true"})
    assert kw["tag"] == "TAG"
    assert kw["frm"] == "Magic.DRC" and kw["to"] == "Magic.DRC"
    assert kw["overwrite"] is False
