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
"""Lock-in tests for the metric watch (E4.2) and run pinning (E4.5).

The watch's cardinal rule (three-fears fidelity): it must NEVER report a
violation for a metric that is missing or non-finite in the run — only a
genuinely-present, genuinely-finite value that genuinely breaks the bound. These
tests pin exactly that."""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from lanex.controller import history


# --------------------------------------------------------------------------- #
# evaluate_watch — the accuracy-critical evaluator
# --------------------------------------------------------------------------- #
def test_watch_flags_a_real_breach() -> None:
    metrics = {"timing__setup__ws": -0.05}
    rules = [{"metric": "timing__setup__ws", "cmp": ">=", "threshold": 0.0}]
    viols = history.evaluate_watch(metrics, rules)
    assert len(viols) == 1
    assert viols[0]["metric"] == "timing__setup__ws"
    assert viols[0]["value"] == -0.05


def test_watch_passes_when_bound_is_met() -> None:
    metrics = {"timing__setup__ws": 0.10}
    rules = [{"metric": "timing__setup__ws", "cmp": ">=", "threshold": 0.0}]
    assert history.evaluate_watch(metrics, rules) == []


def test_watch_ignores_missing_metric() -> None:
    # A rule on a metric the run didn't produce is neither pass nor fail.
    rules = [{"metric": "not__present", "cmp": ">=", "threshold": 0.0}]
    assert history.evaluate_watch({"other": 1}, rules) == []


def test_watch_ignores_non_finite_metric() -> None:
    # inf/NaN must never be reported as a violation (the A1 class).
    rules = [{"metric": "m", "cmp": "<=", "threshold": 5.0}]
    assert history.evaluate_watch({"m": float("inf")}, rules) == []
    assert history.evaluate_watch({"m": float("nan")}, rules) == []


def test_watch_handles_decimal_values() -> None:
    metrics = {"area": Decimal("100.5")}
    rules = [{"metric": "area", "cmp": "<", "threshold": 100.0}]
    viols = history.evaluate_watch(metrics, rules)
    assert len(viols) == 1 and viols[0]["value"] == 100.5


def test_watch_ignores_bool_and_string_values() -> None:
    rules = [{"metric": "m", "cmp": ">=", "threshold": 0.0}]
    assert history.evaluate_watch({"m": True}, rules) == []
    assert history.evaluate_watch({"m": "0"}, rules) == []


def test_watch_all_comparators() -> None:
    assert history.evaluate_watch({"m": 5}, [{"metric": "m", "cmp": ">", "threshold": 5}]) != []
    assert history.evaluate_watch({"m": 6}, [{"metric": "m", "cmp": ">", "threshold": 5}]) == []
    assert history.evaluate_watch({"m": 5}, [{"metric": "m", "cmp": "==", "threshold": 5}]) == []
    assert history.evaluate_watch({"m": 5}, [{"metric": "m", "cmp": "!=", "threshold": 5}]) != []


def test_write_watch_sanitises_bad_rules(tmp_path: Path) -> None:
    res = history.write_watch(str(tmp_path), [
        {"metric": "good", "cmp": ">=", "threshold": 0},
        {"metric": "", "cmp": ">=", "threshold": 0},          # no metric
        {"metric": "bad_cmp", "cmp": "~=", "threshold": 0},   # bad comparator
        {"metric": "bad_thr", "cmp": ">=", "threshold": "x"}, # non-numeric
    ])
    assert res["ok"]
    assert [r["metric"] for r in res["rules"]] == ["good"]
    # Round-trips through disk.
    assert history.read_watch(str(tmp_path)) == [{"metric": "good", "cmp": ">=", "threshold": 0.0}]


def test_write_empty_watch_removes_file(tmp_path: Path) -> None:
    history.write_watch(str(tmp_path), [{"metric": "m", "cmp": ">=", "threshold": 0}])
    assert (tmp_path / history._WATCH_FILE).is_file()
    history.write_watch(str(tmp_path), [])
    assert not (tmp_path / history._WATCH_FILE).is_file()
    assert history.read_watch(str(tmp_path)) == []


# --------------------------------------------------------------------------- #
# pinning (E4.5)
# --------------------------------------------------------------------------- #
def test_pin_and_unpin(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    (run / "final").mkdir(parents=True)
    (run / "final" / "metrics.json").write_text('{"a": 1}')
    (run / "resolved.json").write_text('{"PDK": "sky130A"}')

    history.set_pin(run, True)
    assert (run / history._PIN_MARKER).is_file()
    rows = {r["tag"]: r for r in history.list_runs(tmp_path)}
    assert rows["r1"]["pinned"] is True

    history.set_pin(run, False)
    assert not (run / history._PIN_MARKER).is_file()
    rows = {r["tag"]: r for r in history.list_runs(tmp_path)}
    assert rows["r1"]["pinned"] is False
