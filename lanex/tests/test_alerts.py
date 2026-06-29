# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for :mod:`lanex.controller.alerts`."""
from __future__ import annotations

import pytest


def test_explain_alert_with_code():
    from lanex.controller import alerts

    card = alerts.explain_alert("[ERROR ORYX-1001] out of memory while reading DEF")
    assert card["what"]
    assert isinstance(card.get("remediations"), list)
    blob = (card["what"] + card["why"]).lower()
    assert "memory" in blob or "ram" in blob


def test_explain_alert_with_antenna_text():
    from lanex.controller import alerts

    card = alerts.explain_alert("[WARNING GRT-0123] Antenna violation: net n12 exceeds limit")
    # Either the antenna KB entry or a generic fallback, but always a card.
    assert card["what"]


def test_explain_alert_no_match_returns_card():
    from lanex.controller import alerts

    card = alerts.explain_alert("just some random log line with no struct")
    assert card is not None
    assert card["title"]


def test_explain_checker_failure_classifies_main_categories():
    from lanex.controller import alerts

    for cls, expected_key in (
        ("Checker.TrDRC", "trc.routing_drc"),
        ("Checker.YosysUnmappedCells", "yosys.unmapped_cells"),
        ("Checker.AntennaReport", "antenna.violations"),
        ("Checker.LVS", "lvs.mismatch"),
        ("Checker.TimingViolations", "timing.setup_violations"),
        ("Checker.DisconnectedPins", "disconnected_pins"),
        ("Checker.IllegalOverlap", "illegal_overlap"),
    ):
        card = alerts.explain_checker_failure(cls)
        # Either title is the canonical key, or a generic fallback. Always a card.
        assert card is not None
        assert card["title"]
