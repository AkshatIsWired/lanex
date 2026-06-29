# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for :mod:`lanex.controller.introspect` and :mod:`models`."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_models_to_json_handles_decimal_paths_enums():
    from decimal import Decimal
    from pathlib import Path

    from lanex.controller.models import StepStatus, to_json

    obj = {
        "x": Decimal("3.14"),
        "p": Path("/tmp/a"),
        "s": StepStatus.RUNNING,
        "n": None,
        "i": 5,
        "nested": [{"a": Decimal("1")}, {1, 2}],
    }
    out = to_json(obj)
    assert out["x"] == 3.14
    assert out["p"] == "/tmp/a"
    assert out["s"] == "running"
    assert out["nested"][0]["a"] == 1.0
    assert sorted(out["nested"][1]) == [1, 2]
    # Round-trip via stdlib json.dumps without TypeErrors.
    json.dumps(out)


def test_introspect_list_steps_runs():
    from lanex.controller import introspect

    steps = introspect.list_steps()
    assert isinstance(steps, list)
    assert len(steps) > 50, "expected the canonical Classic flow's 80-ish steps"
    for step in steps[:3]:
        assert {"id", "qualified", "inputs", "outputs", "config_vars"} <= set(step)
        assert isinstance(step["id"], str)


def test_introspect_list_design_formats_runs():
    from lanex.controller import introspect

    formats = introspect.list_design_formats()
    assert isinstance(formats, list)
    ids = {f["id"] for f in formats}
    for required in ("nl", "def", "gds", "sdf", "spef", "lib"):
        assert required in ids, f"missing canonical design format: {required}"
    for f in formats:
        assert "extension" in f and "full_name" in f
    # Should be de-duped.
    counts = {}
    for f in formats:
        counts[f["id"]] = counts.get(f["id"], 0) + 1
    for v in counts.values():
        assert v == 1, f"list_design_formats contains duplicates: {counts}"


def test_introspect_get_step_known_id():
    from lanex.controller import introspect

    first = introspect.list_steps()[0]
    s = introspect.get_step(first["id"])
    assert s is not None
    assert s["id"] == first["id"]
    assert isinstance(s["help_md"], str)


def test_introspect_get_step_unknown_returns_none():
    from lanex.controller import introspect

    assert introspect.get_step("OpenROAD.NotARealStepXYZ") is None


def test_introspect_list_flows_includes_classic():
    from lanex.controller import introspect

    flows = introspect.list_flows()
    assert isinstance(flows, list)
    names = {f["name"] for f in flows}
    assert any(n for n in names if n.lower() in {"classic", "asic"}), names


def test_introspect_variables_have_required_fields():
    from lanex.controller import introspect

    vs = introspect.list_variables()
    assert vs, "expected at least some Variables discovered"
    for v in vs[:5]:
        assert v["name"]
        assert isinstance(v["type"], str)
        assert isinstance(v["description"], str)
        assert isinstance(v["pdk"], bool)
        assert isinstance(v["optional"], bool)


def test_introspect_literal_variables_expose_choices():
    from lanex.controller import introspect

    vs = {v["name"]: v for v in introspect.list_variables()}
    # SYNTH_STRATEGY is a Literal['AREA 0'…'DELAY 4'] — its allowed values must
    # surface as `choices` so the config form renders a dropdown (not a textbox).
    ss = vs.get("SYNTH_STRATEGY")
    assert ss is not None
    assert "AREA 0" in ss["choices"] and "DELAY 3" in ss["choices"]
    # A free-form numeric var has no choices.
    cp = vs.get("CLOCK_PERIOD")
    assert cp is not None and cp["choices"] == []


def test_introspect_list_metrics_real_names():
    from lanex.controller import introspect

    mets = {m["name"]: m for m in introspect.list_metrics()}
    assert mets, "expected metrics from librelane's registry"
    # Canonical names that actually exist in librelane.common.metrics.library.
    for name in ("timing__setup__ws", "design__instance__count", "antenna__violating__nets"):
        assert name in mets, name
    # Critical violation metric carries the flag.
    assert mets["design__lvs_error__count"]["critical"] is True


def test_introspect_models_jsonable_bytes_not_iterated():
    from lanex.controller.models import _jsonable
    out = _jsonable(b"hello")
    # Bytes should NOT become [104, 101, 108, 108, 111] (integer stride).
    assert isinstance(out, str) or out in (b"hello",)


def test_introspect_models_jsonable_str_not_iterated():
    from lanex.controller.models import _jsonable

    # String is a Sequence but should pass through unchanged.
    assert _jsonable("stage.misc") == "stage.misc"


def test_introspect_models_jsonable_depth_guarded_cycle():
    from lanex.controller.models import _jsonable

    a = {}
    b = {"a": a}
    a["b"] = a  # cycle
    out = _jsonable(a)
    assert out is not None  # didn't infinite-loop
    from lanex.controller import introspect

    flows = introspect.list_flows()
    assert flows
    info = introspect.get_flow(flows[0]["name"])
    assert info is not None
    assert info["name"] == flows[0]["name"]
    assert isinstance(info["steps"], list)
