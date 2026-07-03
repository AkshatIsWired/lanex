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
"""Lock-in tests for run import (E1): adopt a run directory + import an export
bundle. Pure stdlib — no EDA tools. The headline guarantee is that an imported
bundle reproduces the EXACT same metric values (the three-fears fidelity rule)
and that a malicious zip member can never escape the run dir (zip-slip)."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from lanex.controller import bundle, history


def _make_run(root: Path, tag: str = "RUN_1") -> Path:
    run = root / "runs" / tag
    (run / "final").mkdir(parents=True)
    (run / "final" / "metrics.json").write_text(
        '{"design__instance__area": 42.5, "timing__setup__ws": 0.13, "n": 7}'
    )
    (run / "resolved.json").write_text(
        '{"PDK":"sky130A","STD_CELL_LIBRARY":"sky130_fd_sc_hd","meta":{"flow":"Classic"}}'
    )
    step = run / "01-yosys-synthesis"
    step.mkdir()
    (step / "runtime.txt").write_text("00:00:05.0")
    (step / "synth.rpt").write_text("area 42")
    return run


# --------------------------------------------------------------------------- #
# Mode 1 — adopt a run directory
# --------------------------------------------------------------------------- #
def test_adopt_run_copies_and_badges(tmp_path: Path) -> None:
    src = _make_run(tmp_path / "srcdesign")
    dest_design = tmp_path / "dstdesign"
    res = history.adopt_run(str(src), str(dest_design))
    assert res["tag"] == "RUN_1-imported"
    runs = history.list_runs(str(dest_design))
    assert len(runs) == 1
    assert runs[0]["tag"] == "RUN_1-imported"
    assert runs[0]["imported"] is True
    assert runs[0]["pdk"] == "sky130A"
    # A copy, not a link — deleting the source must not affect the import.
    assert (dest_design / "runs" / "RUN_1-imported" / "final" / "metrics.json").is_file()
    assert (dest_design / "runs" / "RUN_1-imported" / "gui-imported.json").is_file()


def test_adopt_run_collision_suffixes(tmp_path: Path) -> None:
    src = _make_run(tmp_path / "srcdesign")
    dest_design = tmp_path / "dstdesign"
    a = history.adopt_run(str(src), str(dest_design))
    b = history.adopt_run(str(src), str(dest_design))
    assert a["tag"] == "RUN_1-imported"
    assert b["tag"] == "RUN_1-imported-2"


def test_adopt_run_rejects_non_run(tmp_path: Path) -> None:
    junk = tmp_path / "notarun"
    junk.mkdir()
    (junk / "readme.txt").write_text("hi")
    with pytest.raises(ValueError):
        history.adopt_run(str(junk), str(tmp_path / "dst"))


def test_adopt_run_missing_source(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        history.adopt_run(str(tmp_path / "ghost"), str(tmp_path / "dst"))


def test_adopt_run_refuses_own_runs(tmp_path: Path) -> None:
    design = tmp_path / "design"
    src = _make_run(design)  # already under design/runs/
    with pytest.raises(ValueError):
        history.adopt_run(str(src), str(design))


# --------------------------------------------------------------------------- #
# Mode 2 — import an export bundle
# --------------------------------------------------------------------------- #
def test_import_bundle_roundtrip_metric_equality(tmp_path: Path) -> None:
    src = _make_run(tmp_path / "srcdesign")
    zb = bundle.build_bundle(str(src))  # default = text parts (incl. config)
    # The real metrics.json rides along byte-for-byte.
    assert "final/metrics.json" in zipfile.ZipFile(io.BytesIO(zb)).namelist()

    dest_design = tmp_path / "dstdesign"
    res = bundle.import_bundle(io.BytesIO(zb), str(dest_design))
    runs = history.list_runs(str(dest_design))
    assert len(runs) == 1 and runs[0]["imported"] is True

    imported_dir = Path(runs[0]["run_dir"])
    got = history._load_metrics(imported_dir)
    src_metrics = json.loads((src / "final" / "metrics.json").read_text())
    assert got == src_metrics  # byte-equal metric values survive the round trip


def test_import_bundle_zip_slip_rejected(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("MANIFEST.json", '{"run_tag": "evil"}')
        zf.writestr("../evil.txt", "pwned")          # escapes the run dir
        zf.writestr("final/metrics.json", '{"a": 1}')  # a legit member so it isn't empty
    buf.seek(0)
    dest_design = tmp_path / "dstdesign"
    res = bundle.import_bundle(buf, str(dest_design))
    run_dir = dest_design / "runs" / res["tag"]
    assert (run_dir / "final" / "metrics.json").is_file()
    # The escaping member must NOT have been written anywhere near the design.
    assert not (dest_design.parent / "evil.txt").exists()
    assert not (dest_design / "evil.txt").exists()


def test_import_bundle_warns_on_missing_parts(tmp_path: Path) -> None:
    src = _make_run(tmp_path / "srcdesign")
    zb = bundle.build_bundle(str(src))  # text only → no GDS
    res = bundle.import_bundle(io.BytesIO(zb), str(tmp_path / "dst"))
    assert any("GDS" in w for w in res["warnings"])
