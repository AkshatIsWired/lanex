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
"""Lock-in tests for the heavy-deliverable bundle parts (GDS / layout views /
netlists / timing / images / diagrams) added to ``controller.bundle``.

Pure / stdlib — no EDA tools needed. The diagram-render-to-SVG path is
graphviz-optional: we assert the ``.dot`` source is always bundled and only
assert the ``.svg`` when ``dot`` is on PATH."""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

import pytest

from lanex.controller import bundle


# --------------------------------------------------------------------------- #
# A synthetic run dir mirroring LibreLane's <run>/final/ deliverable tree.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    run = tmp_path / "runs" / "rtest"
    final = run / "final"

    def write(rel: str, data: bytes | str = b"x") -> None:
        p = final / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            p.write_text(data)
        else:
            p.write_bytes(data)

    write("gds/spm.gds", b"GDSII" * 64)
    write("def/spm.def", "DEF placed routed")
    write("lef/spm.lef", "LEF abstract")
    write("odb/spm.odb", b"\x01\x02odb")
    write("nl/spm.nl.v", "module spm; endmodule")
    write("pnl/spm.pnl.v", "module spm_pwr; endmodule")
    write("spice/spm.spice", ".subckt spm")
    write("lib/nom.lib", "library(spm)")
    write("spef/nom.spef", "*SPEF")
    write("sdc/spm.sdc", "create_clock")
    write("render/spm.png", b"\x89PNG\r\n\x1a\n" + b"img")
    write("metrics.json", '{"design__instance__area":42}')

    # A Yosys diagram in a numbered step dir.
    step = run / "01-yosys-synthesis"
    step.mkdir(parents=True)
    (step / "hierarchy.dot").write_text("digraph { a -> b }")

    (run / "config.json").write_text('{"PDK":"sky130A"}')
    (run / "resolved.json").write_text('{"PDK":"sky130A"}')
    return run


def _names(run: Path, include) -> list[str]:
    return sorted(zipfile.ZipFile(io.BytesIO(bundle.build_bundle(run, include=include))).namelist())


# --------------------------------------------------------------------------- #
# Each heavy part pulls exactly its category of artefacts.
# --------------------------------------------------------------------------- #
def test_gds_part(run_dir: Path):
    n = _names(run_dir, ["gds"])
    assert "gds/spm.gds" in n
    # GDS-only must not drag in netlists/timing/etc.
    assert not any(x.startswith(("netlists/", "timing/", "layout/")) for x in n)


def test_layout_views_excludes_gds_and_render(run_dir: Path):
    n = _names(run_dir, ["layout_views"])
    assert "layout/def/spm.def" in n
    assert "layout/lef/spm.lef" in n
    assert "layout/odb/spm.odb" in n
    # The GDS stream and the PNG render have their own parts.
    assert not any(x.endswith(".gds") for x in n)
    assert not any(x.endswith(".png") for x in n)


def test_netlists_part(run_dir: Path):
    n = _names(run_dir, ["netlists"])
    assert "netlists/nl/spm.nl.v" in n
    assert "netlists/pnl/spm.pnl.v" in n
    assert "netlists/spice/spm.spice" in n


def test_timing_part(run_dir: Path):
    n = _names(run_dir, ["timing"])
    assert "timing/lib/nom.lib" in n
    assert "timing/spef/nom.spef" in n
    assert "timing/sdc/spm.sdc" in n


def test_images_part(run_dir: Path):
    n = _names(run_dir, ["images"])
    assert any(x.startswith("images/") and x.endswith(".png") for x in n)


def test_diagrams_part(run_dir: Path):
    n = _names(run_dir, ["diagrams"])
    assert any(x.endswith("hierarchy.dot") for x in n), "the .dot source is always bundled"
    if shutil.which("dot"):
        assert any(x.endswith(".dot.svg") for x in n), "graphviz present → rendered svg too"
        assert any(x.endswith(".dot.png") for x in n), "graphviz present → rendered png too"


def test_images_excludes_rendered_diagram_svg(run_dir: Path):
    # Render the diagram first so a <name>.dot.svg exists on disk, then confirm
    # the images part does NOT pick it up (it belongs to the diagrams part).
    if not shutil.which("dot"):
        pytest.skip("graphviz not installed")
    bundle.build_bundle(run_dir, include=["diagrams"])  # creates the cached .svg
    n = _names(run_dir, ["images"])
    assert not any(x.endswith(".dot.svg") for x in n)


# --------------------------------------------------------------------------- #
# Opt-in semantics: heavy parts never appear unless asked.
# --------------------------------------------------------------------------- #
def test_default_is_text_only(run_dir: Path):
    n = _names(run_dir, None)
    assert "metrics.csv" in n
    assert not any(x.startswith(("gds/", "layout/", "netlists/", "timing/", "images/", "diagrams/")) for x in n)


def test_minimal_mode_has_no_heavy(run_dir: Path):
    n = sorted(zipfile.ZipFile(io.BytesIO(bundle.build_bundle(run_dir, mode="minimal"))).namelist())
    assert "config/config.json" in n
    assert not any(x.startswith(("gds/", "images/")) for x in n)


def test_all_token_includes_heavy(run_dir: Path):
    n = _names(run_dir, ["all"])
    assert "gds/spm.gds" in n
    assert "netlists/nl/spm.nl.v" in n
    assert any(x.startswith("images/") for x in n)


def test_all_parts_is_text_plus_heavy():
    assert bundle.ALL_PARTS == bundle.TEXT_PARTS + bundle.HEAVY_PARTS
    for p in ("gds", "layout_views", "netlists", "timing", "images", "diagrams"):
        assert p in bundle.HEAVY_PARTS


# --------------------------------------------------------------------------- #
# Caps are honest: an oversized file is recorded in SKIPPED.json, never dropped.
# --------------------------------------------------------------------------- #
def test_oversize_file_is_skipped_not_dropped(tmp_path: Path):
    run = tmp_path / "runs" / "rcap"
    gdsdir = run / "final" / "gds"
    gdsdir.mkdir(parents=True)
    with open(gdsdir / "huge.gds", "wb") as f:
        f.truncate(bundle._BINARY_FILE_CAP + 1)
    (gdsdir / "ok.gds").write_bytes(b"G" * 32)
    (run / "final" / "metrics.json").write_text('{"a":1}')
    (run / "config.json").write_text('{"PDK":"x"}')

    blob = bundle.build_bundle(run, include=["gds"])
    zf = zipfile.ZipFile(io.BytesIO(blob))
    names = zf.namelist()
    assert "gds/ok.gds" in names
    assert "gds/huge.gds" not in names
    skipped = json.loads(zf.read("SKIPPED.json"))["files"]
    assert any(s["path"] == "gds/huge.gds" for s in skipped)


def test_write_bundle_streams_into_spooled_file(tmp_path: Path):
    run = tmp_path / "runs" / "rs"
    (run / "final" / "gds").mkdir(parents=True)
    (run / "final" / "gds" / "spm.gds").write_bytes(b"G" * 1000)
    (run / "final" / "metrics.json").write_text('{"a":1}')
    (run / "config.json").write_text('{"PDK":"x"}')

    spool = tempfile.SpooledTemporaryFile(max_size=256)
    summary = bundle.write_bundle(spool, run, include=["gds", "metrics_csv"])
    total = spool.tell()
    assert total > 0
    spool.seek(0)
    names = zipfile.ZipFile(spool).namelist()
    assert "gds/spm.gds" in names
    assert "metrics.csv" in names
    assert summary["parts"] == sorted(["gds", "metrics_csv"])


def test_missing_run_raises():
    with pytest.raises(FileNotFoundError):
        bundle.build_bundle("/no/such/run")
