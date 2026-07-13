# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Unit/scale fidelity of every DERIVED display value.

Most numbers pass through untouched (locked elsewhere); the design-summary
hero derives a handful — die W×H from the bbox string, utilization
fraction→percent, power W→mW. A wrong factor here shows a plausible-looking
but wrong number, the hardest display bug to spot — so each derivation is
recomputed here from the committed golden of a real run's metrics.json and
must match to the digit.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from lanex.controller import history

GOLDEN_METRICS = Path(__file__).parent / "goldens" / "display_run" / "metrics.json"


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "final").mkdir()
    shutil.copy(GOLDEN_METRICS, tmp_path / "final" / "metrics.json")
    return tmp_path


def _golden() -> dict:
    raw = GOLDEN_METRICS.read_text()
    tokened = re.sub(r'([:\[,]\s*)(-?Infinity|NaN)(\s*[,}\]])', r'\1"\2"\3', raw)
    return json.loads(tokened)


def _summary_rows(run_dir: Path) -> dict:
    rows = history.design_summary(str(run_dir))
    return {r["label"]: r for r in rows}


def test_utilization_is_the_raw_fraction_times_100(run_dir: Path) -> None:
    m = _golden()
    rows = _summary_rows(run_dir)
    raw = m["design__instance__utilization"]
    assert rows["Utilization"]["value"] == round(raw * 100, 1)
    assert rows["Utilization"]["unit"] == "%"
    # The provenance key on the row points at the RAW metric, so the source
    # dialog shows the fraction the percentage was derived from.
    assert rows["Utilization"]["key"] == "design__instance__utilization"


def test_die_size_recomputes_from_the_bbox_string(run_dir: Path) -> None:
    m = _golden()
    rows = _summary_rows(run_dir)
    x0, y0, x1, y1 = [float(v) for v in m["design__die__bbox"].split()]
    want = f"{round(x1 - x0, 3)} × {round(y1 - y0, 3)}"
    assert rows["Die size"]["value"] == want
    assert rows["Die size"]["key"] == "design__die__bbox"


def test_power_is_watts_times_1000_labelled_mw(run_dir: Path) -> None:
    m = _golden()
    rows = _summary_rows(run_dir)
    if "Total power" not in rows:
        pytest.skip("golden has no power__total")
    assert rows["Total power"]["value"] == round(m["power__total"] * 1000, 4)
    assert rows["Total power"]["unit"] == "mW"


def test_untouched_rows_pass_through_exactly(run_dir: Path) -> None:
    m = _golden()
    rows = _summary_rows(run_dir)
    for label, key in (("Die area", "design__die__area"),
                       ("Core area", "design__core__area"),
                       ("Cell count", "design__instance__count"),
                       ("Wirelength", "route__wirelength")):
        if label in rows:
            assert rows[label]["value"] == m[key], f"{label} altered in display"


def test_every_summary_row_names_its_source_metric(run_dir: Path) -> None:
    # The provenance buttons rely on row["key"] being a REAL metric key (or a
    # real key the derivation started from) — an invented key would make the
    # source dialog honestly fail, so lock that every key exists in the file.
    m = _golden()
    for r in history.design_summary(str(run_dir)):
        if r.get("key"):
            assert r["key"] in m, f"summary row '{r['label']}' names unknown key {r['key']}"
