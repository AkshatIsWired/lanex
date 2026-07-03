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
"""Golden-corpus regression suite (H5) — the permanent codification of the three
fears. A trimmed, checked-in corpus (``tests/goldens/``) proves that metric
passthrough stays byte/value-faithful and that non-finite metrics can never again
reach the wire as bare ``Infinity``/``NaN`` (the A1 class). Any future change that
mangles or drops a metric value fails here.

Pure stdlib — no EDA tools, no network. The ``nonfinite`` golden deliberately
carries bare ``Infinity``/``-Infinity``/``NaN`` tokens, exactly as LibreLane's
``json.dump`` emits them for infinite/undefined metrics."""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest

from lanex.controller import history
from lanex.server.jsonsafe import json_safe

# The corpus is stored WITHOUT a literal ``runs/`` dir: the repo's .gitignore
# excludes ``**/runs/`` (real run output), which would otherwise strip the
# checked-in goldens from git and break CI. The list_runs test below stages them
# into a temporary ``runs/`` layout at runtime.
GOLDENS = Path(__file__).parent / "goldens"
CLEAN = GOLDENS / "clean_run"
NONFINITE = GOLDENS / "nonfinite_run"


def test_goldens_present() -> None:
    assert (CLEAN / "final" / "metrics.json").is_file()
    assert (NONFINITE / "final" / "metrics.json").is_file()


def test_clean_metrics_passthrough_is_exact() -> None:
    """Contract = passthrough: the metric dict equals the file, value-for-value,
    and every finite value serialises strictly unchanged."""
    m = history._load_metrics(CLEAN)
    assert m == {
        "design__instance__area": 1234.56,
        "design__instance__count": 789,
        "timing__setup__ws": 0.4231,
        "timing__setup__tns": 0.0,
        "clock__skew__worst_setup": 0.0125,
        "design__lvs_error__count": 0,
        "antenna__violating__nets": 0,
        "route__drc_errors": 0,
    }
    safe = json_safe(m)
    assert safe == m  # nothing to sanitise → identical
    json.dumps(safe, allow_nan=False)  # strict-JSON clean


def test_nonfinite_corpus_really_carries_the_hazard() -> None:
    """Guards the guard: prove the golden actually contains bare Infinity/NaN, so
    the wire-safety test below is testing something real."""
    m = history._load_metrics(NONFINITE)
    assert math.isinf(m["timing__setup_r2r__ws"]) and m["timing__setup_r2r__ws"] > 0
    assert math.isinf(m["timing__hold_r2r__ws"]) and m["timing__hold_r2r__ws"] < 0
    assert math.isnan(m["clock__skew__worst_hold"])
    # Serialising the RAW metrics strictly MUST fail — that IS the A1 bug.
    with pytest.raises(ValueError):
        json.dumps(m, allow_nan=False)


def test_nonfinite_metrics_made_wire_safe() -> None:
    """The permanent A1 lock: after json_safe the payload is strict-JSON, finite
    values are intact, and non-finite ones become the exact tokens the frontend's
    fmt.metric understands."""
    m = history._load_metrics(NONFINITE)
    safe = json_safe(m)
    assert safe["design__instance__area"] == 1000.0   # finite unchanged
    assert safe["design__instance__count"] == 512
    assert safe["timing__setup_r2r__ws"] == "Infinity"
    assert safe["timing__hold_r2r__ws"] == "-Infinity"
    assert safe["clock__skew__worst_hold"] == "NaN"
    json.dumps(safe, allow_nan=False)  # must NOT raise — this is the wire contract


def test_list_runs_reads_the_corpus(tmp_path: Path) -> None:
    # Stage the goldens under a real design/runs/ layout (see module note).
    runs_root = tmp_path / "design" / "runs"
    runs_root.mkdir(parents=True)
    shutil.copytree(CLEAN, runs_root / "clean")
    shutil.copytree(NONFINITE, runs_root / "nonfinite")
    runs = {r["tag"]: r for r in history.list_runs(tmp_path / "design")}
    assert "clean" in runs and "nonfinite" in runs
    assert runs["clean"]["pdk"] == "sky130A"
    assert runs["clean"]["scl"] == "sky130_fd_sc_hd"
    assert runs["clean"]["steps_done"] == 1  # the yosys step has state_out.json


def test_export_run_is_faithful_and_finite() -> None:
    out = history.export_run(CLEAN, "csv")
    assert out["ok"] and "text" in out
    # The area value appears verbatim in the exported table.
    assert "1234.56" in out["text"]
