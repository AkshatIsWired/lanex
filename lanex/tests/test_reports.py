# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for :mod:`lanex.controller.reports`."""
from __future__ import annotations

from pathlib import Path

import pytest


def test_parse_drc_missing_file(tmp_path: Path):
    from lanex.controller import reports

    out = reports.parse_drc(tmp_path / "nope.drc")
    assert out["bbox_count"] == 0
    assert out["violations"] == []
    # Three-state: a missing report must NEVER be indistinguishable from a
    # clean one (the UI shows green only for status == "parsed").
    assert out["status"] == "missing"
    assert out["error"]


def test_parse_drc_empty_file(tmp_path: Path):
    from lanex.controller import reports

    f = tmp_path / "empty.drc"
    f.write_text("", encoding="utf-8")
    out = reports.parse_drc(f)
    assert out is not None
    assert "bbox_count" in out
    # Empty file = truncated/failed write, not a clean result.
    assert out["status"] == "error"


def test_parse_lvs_extracts_counts(tmp_path: Path):
    from lanex.controller import reports

    f = tmp_path / "lvs.log"
    f.write_text(
        "Netgen LVS report\n"
        "Unmatched devices = 2\n"
        "unmatched nets: 5\n"
        "unmatched pins = 0\n",
        encoding="utf-8",
    )
    out = reports.parse_lvs(f)
    assert out["path"].endswith("lvs.log")
    assert out["counts"]["unmatched_devices"] == 2
    assert out["counts"]["unmatched_nets"] == 5
    assert out["counts"]["unmatched_pins"] == 0


def test_parse_lvs_missing_file(tmp_path: Path):
    from lanex.controller import reports

    out = reports.parse_lvs(tmp_path / "missing.txt")
    assert out["counts"] == {}
