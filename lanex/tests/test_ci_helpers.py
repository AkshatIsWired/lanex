# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Unit tests for the scripts/ci differential/e2e helpers.

The comparators ARE the CI gates — a bug in one would turn a real divergence
into a silent green, the worst possible outcome for a suite whose whole point
is equivalence proof. So they get first-class tests: known-identical inputs
must pass, known-different inputs must fail, the non-finite token bridge and
path canonicalization must behave, and the hand-rolled "native" argv must stay
byte-identical to what lanex's own builder produces (drift lock).

This file belongs to the removable CI suite (scripts/ci/README.md): deleting
scripts/ci/, .github/workflows/differential.yml, and this file removes the
feature entirely; nothing else references them.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

_SC = Path(__file__).resolve().parents[2] / "scripts" / "ci"
if str(_SC) not in sys.path:
    sys.path.insert(0, str(_SC))

import bundle_verify  # noqa: E402
import compare_flat  # noqa: E402
import csv_cross  # noqa: E402
import layout_probe  # noqa: E402
from differential_run import build_native_argv  # noqa: E402
from flatten_metrics import descend, flatten  # noqa: E402
from hash_tree import manifest  # noqa: E402


# ---------------------------------------------------------------------------
# flatten_metrics
# ---------------------------------------------------------------------------

def test_flatten_sorts_and_reprs_nested():
    out = flatten({"b": {"y": 2, "x": 1}, "a": [True, None, "s"]})
    assert out == [("a[0]", "True"), ("a[1]", "None"), ("a[2]", "'s'"),
                   ("b.x", "1"), ("b.y", "2")]


def test_flatten_accepts_bare_nonfinite_json(tmp_path: Path):
    # LibreLane's own metrics.json may hold bare Infinity/NaN literals.
    p = tmp_path / "m.json"
    p.write_text('{"ws": Infinity, "tns": -Infinity, "x": NaN}', encoding="utf-8")
    with open(p, encoding="utf-8") as fh:
        out = dict(flatten(json.load(fh)))
    assert out["ws"] == "inf" and out["tns"] == "-inf" and out["x"] == "nan"


def test_descend_walks_api_envelope():
    data = {"ok": True, "data": {"metrics": {"k": 1}}}
    assert descend(data, "data.metrics") == {"k": 1}
    with pytest.raises(KeyError):
        descend(data, "data.nope")


# ---------------------------------------------------------------------------
# compare_flat — exit code IS the gate
# ---------------------------------------------------------------------------

def _write_flat(p: Path, rows):
    p.write_text("".join(f"{k}\t{v}\n" for k, v in rows), encoding="utf-8")


def test_compare_identical_passes(tmp_path: Path, capsys):
    a, b = tmp_path / "a", tmp_path / "b"
    _write_flat(a, [("k1", "1"), ("k2", "'x'")])
    _write_flat(b, [("k1", "1"), ("k2", "'x'")])
    assert compare_flat.main([str(a), str(b)]) == 0
    assert "value_diff=0" in capsys.readouterr().out


def test_compare_detects_value_diff_and_missing_keys(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write_flat(a, [("k1", "1"), ("only_a", "2")])
    _write_flat(b, [("k1", "9"), ("only_b", "3")])
    assert compare_flat.main([str(a), str(b)]) == 2


def test_compare_exclusions_are_key_exact(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write_flat(a, [("noisy", "1"), ("k", "5")])
    _write_flat(b, [("noisy", "2"), ("k", "5")])
    assert compare_flat.main([str(a), str(b)]) == 2
    assert compare_flat.main([str(a), str(b), "--exclude", "noisy"]) == 0
    # exclusion must NOT be a prefix/pattern match
    _write_flat(b, [("noisy2", "1"), ("k", "5")])
    assert compare_flat.main([str(a), str(b), "--exclude", "noisy"]) == 2


def test_compare_canon_nonfinite_bridges_token_and_float(tmp_path: Path):
    # disk side: json.load of bare Infinity → repr 'inf'; API side: the
    # documented string tokens → repr "'Infinity'". Same value, two spellings.
    a, b = tmp_path / "a", tmp_path / "b"
    _write_flat(a, [("ws", "inf"), ("tns", "-inf"), ("x", "nan")])
    _write_flat(b, [("ws", "'Infinity'"), ("tns", "'-Infinity'"), ("x", "'NaN'")])
    assert compare_flat.main([str(a), str(b)]) == 2
    assert compare_flat.main([str(a), str(b), "--canon-nonfinite"]) == 0


def test_compare_sub_canonicalizes_paths(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write_flat(a, [("f", "'/w/spm_native/runs/native/x.gds'")])
    _write_flat(b, [("f", "'/w/spm_container/runs/containerleg/x.gds'")])
    assert compare_flat.main([str(a), str(b)]) == 2
    assert compare_flat.main([
        str(a), str(b),
        "--sub", "/w/spm_native::<D>", "--sub", "/w/spm_container::<D>",
        "--sub", "runs/native::runs/<T>", "--sub", "runs/containerleg::runs/<T>",
    ]) == 0


# ---------------------------------------------------------------------------
# csv_cross — numeric, not substring
# ---------------------------------------------------------------------------

def test_csv_cross_numeric_equality_and_token_spellings(tmp_path: Path):
    mj = tmp_path / "m.json"
    mj.write_text('{"a": 1.5, "ws": Infinity, "n": "text"}', encoding="utf-8")
    csvf = tmp_path / "e.csv"
    # 1.50 == 1.5 numerically; "Infinity" == inf; exact string for non-numbers.
    csvf.write_text("metric,value\na,1.50\nws,Infinity\nn,text\n", encoding="utf-8")
    assert csv_cross.main([str(csvf), str(mj), "--strict", "--min-matched", "3"]) == 0


def test_csv_cross_flags_real_mismatch_and_empty_csv(tmp_path: Path):
    mj = tmp_path / "m.json"
    mj.write_text('{"a": 1.5}', encoding="utf-8")
    bad = tmp_path / "bad.csv"
    bad.write_text("metric,value\na,1.6\n", encoding="utf-8")
    assert csv_cross.main([str(bad), str(mj), "--strict"]) == 2
    empty = tmp_path / "empty.csv"
    empty.write_text("metric,value\n", encoding="utf-8")
    # zero matched rows must not pass silently
    assert csv_cross.main([str(empty), str(mj), "--strict"]) == 2


def test_csv_cross_values_equal_semantics():
    assert csv_cross.values_equal("Infinity", "inf")
    assert csv_cross.values_equal("NaN", "nan")
    assert csv_cross.values_equal("1e-9", "1E-09")
    assert not csv_cross.values_equal("1.0000001", "1.0")
    assert csv_cross.values_equal("abc", "abc")
    assert not csv_cross.values_equal("abc", "abd")


# ---------------------------------------------------------------------------
# hash_tree — the "sources untouched" proof
# ---------------------------------------------------------------------------

def test_hash_tree_excludes_runs_and_detects_change(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.v").write_text("module a; endmodule\n")
    (tmp_path / "runs" / "t").mkdir(parents=True)
    (tmp_path / "runs" / "t" / "big.log").write_text("x")
    before = manifest(str(tmp_path), exclude=["runs"])
    assert not any("runs" in row for row in before)
    (tmp_path / "runs" / "t" / "more.log").write_text("y")
    assert manifest(str(tmp_path), exclude=["runs"]) == before  # runs/ ignored
    (tmp_path / "src" / "a.v").write_text("module b; endmodule\n")
    assert manifest(str(tmp_path), exclude=["runs"]) != before  # sources aren't


# ---------------------------------------------------------------------------
# bundle_verify — byte-equality gate with the generated-member allowlist
# ---------------------------------------------------------------------------

def _make_run_and_bundle(tmp_path: Path, tamper: bool):
    run = tmp_path / "run"
    (run / "final").mkdir(parents=True)
    (run / "final" / "metrics.json").write_text('{"k": 1}', encoding="utf-8")
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("final/metrics.json", '{"k": 2}' if tamper else '{"k": 1}')
        zf.writestr("MANIFEST.json", "{}")          # generated: never on disk
        zf.writestr("metrics.csv", "metric,value\n")  # generated: regenerated CSV
    return z, run


def test_bundle_verify_generated_members_tolerated(tmp_path: Path):
    z, run = _make_run_and_bundle(tmp_path, tamper=False)
    assert bundle_verify.main([str(z), str(run), "--strict"]) == 0


def test_bundle_verify_strict_fails_on_tampered_member(tmp_path: Path):
    z, run = _make_run_and_bundle(tmp_path, tamper=True)
    assert bundle_verify.main([str(z), str(run), "--strict"]) == 2


def test_bundle_verify_strict_fails_on_orphan_member(tmp_path: Path):
    run = tmp_path / "run"
    run.mkdir()
    z = tmp_path / "b.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("reports/ghost.rpt", "boo")
    assert bundle_verify.main([str(z), str(run), "--strict"]) == 2


# ---------------------------------------------------------------------------
# native-leg argv drift lock
# ---------------------------------------------------------------------------

def test_native_argv_matches_lanex_builder(tmp_path: Path):
    """The differential job's hand-rolled lanex-less command must be exactly
    what lanex's own CLI builder produces for the same inputs — if the builder
    ever changes flag order/spelling, this fails instead of the two paths
    silently running different commands."""
    from lanex.controller.container_run import build_dockerized_argv

    design = tmp_path / "spm"
    design.mkdir()
    (design / "config.yaml").write_text("{}", encoding="utf-8")
    ours = build_native_argv("python3", "/pdkroot", "sky130A",
                             "sky130_fd_sc_hd", "native")
    theirs = build_dockerized_argv(
        config_file=design / "config.yaml",
        design_dir=design,
        pdk="sky130A",
        scl="sky130_fd_sc_hd",
        pdk_root="/pdkroot",
        tag="native",
        python_exe="python3",
    )
    assert ours == theirs


def test_drivers_importable():
    # api_e2e imports lazily-heavy modules at import time; a syntax/import
    # regression must fail HERE, not first in a 40-minute CI job.
    import api_e2e  # noqa: F401
    import differential_run  # noqa: F401
    import leg_local_run  # noqa: F401
    import sse_capture  # noqa: F401
    import test_summary  # noqa: F401
    import summary_static  # noqa: F401


# ---------------------------------------------------------------------------
# test_summary — the Summary-tab renderer. A pytest JUnit report must turn into
# a grouped markdown table with per-group pass/fail + an implication line.
# ---------------------------------------------------------------------------
def test_test_summary_renders_grouped_table(tmp_path: Path):
    import test_summary

    xml = tmp_path / "j.xml"
    xml.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="lanex.tests.test_goldens" name="a" time="0.1"/>'
        '<testcase classname="lanex.tests.test_goldens" name="b" time="0.1"/>'
        '<testcase classname="lanex.tests.test_verify" name="c" time="0.2">'
        '<failure>boom</failure></testcase>'
        '<testcase classname="lanex.tests.test_history" name="d" time="0.0">'
        '<skipped/></testcase>'
        '</testsuite></testsuites>',
        encoding="utf-8",
    )
    out = test_summary.render(xml, "Unit tests")
    assert "2 passed · 1 failed · 1 skipped" in out
    # Grouped by file, with the curated implication text.
    assert "`test_goldens`" in out and "byte/value-faithful" in out
    # A failing group is marked, not hidden.
    assert "✗ 1 FAIL" in out and "`test_verify`" in out
    # An unmapped file would still appear with the generic note (none here).
    assert "| `test_history` |" in out


# ---------------------------------------------------------------------------
# layout_probe — the G8 "correct, non-empty layout reaches the viewers" check.
# These prove the DETECTOR: a real GDS passes; empty/truncated/not-a-GDS fail;
# and the viewer would pick the same file routes._final_gds does.
# ---------------------------------------------------------------------------

_VALID_GDS = b"\x00\x06\x00\x02\x00\x07" + b"\x00" * 64  # HEADER record + filler


def test_layout_probe_accepts_real_gds(tmp_path: Path):
    f = tmp_path / "spm.gds"
    f.write_bytes(_VALID_GDS)
    st = layout_probe.gds_status(f)
    assert st["ok"] is True


def test_layout_probe_rejects_empty(tmp_path: Path):
    f = tmp_path / "spm.gds"
    f.write_bytes(b"")
    st = layout_probe.gds_status(f)
    assert st["ok"] is False and "empty" in st["reason"].lower()


def test_layout_probe_rejects_truncated_or_nongds(tmp_path: Path):
    f = tmp_path / "spm.gds"
    f.write_bytes(b"NOT a gdsii stream at all")
    st = layout_probe.gds_status(f)
    assert st["ok"] is False and "gds" in st["reason"].lower()


def test_layout_probe_accepts_gzipped(tmp_path: Path):
    import gzip
    # gzipped under a .gds name, and a real .gds.gz.
    (tmp_path / "a.gds").write_bytes(gzip.compress(_VALID_GDS))
    (tmp_path / "b.gds.gz").write_bytes(gzip.compress(_VALID_GDS))
    assert layout_probe.gds_status(tmp_path / "a.gds")["ok"] is True
    assert layout_probe.gds_status(tmp_path / "b.gds.gz")["ok"] is True
    # a .gz that is not gzip data is rejected.
    (tmp_path / "c.gds.gz").write_bytes(b"plain, not gzip")
    assert layout_probe.gds_status(tmp_path / "c.gds.gz")["ok"] is False


def test_layout_probe_missing_file(tmp_path: Path):
    assert layout_probe.gds_status(tmp_path / "nope.gds")["ok"] is False


def test_pick_final_gds_mirrors_gui_order(tmp_path: Path):
    # routes._final_gds searches final/{gds,klayout_gds,mag_gds}; gds wins.
    (tmp_path / "final" / "mag_gds").mkdir(parents=True)
    (tmp_path / "final" / "mag_gds" / "spm.gds").write_bytes(_VALID_GDS)
    (tmp_path / "final" / "gds").mkdir(parents=True)
    (tmp_path / "final" / "gds" / "spm.gds").write_bytes(_VALID_GDS)
    pick = layout_probe.pick_final_gds(tmp_path)
    assert pick is not None and pick.parent.name == "gds"


def test_viewer_gds_status_end_to_end(tmp_path: Path):
    # Healthy run: the viewer file is valid.
    good = tmp_path / "runs" / "good"
    (good / "final" / "gds").mkdir(parents=True)
    (good / "final" / "gds" / "spm.gds").write_bytes(_VALID_GDS)
    st = layout_probe.viewer_gds_status(good)
    assert st["ok"] is True and st["path"].endswith("spm.gds")

    # Failed run left a 0-byte GDS: the probe FLAGS it (this is the day the
    # differential G8 gate would go red and stop a bad hand-off).
    bad = tmp_path / "runs" / "bad"
    (bad / "final" / "gds").mkdir(parents=True)
    (bad / "final" / "gds" / "spm.gds").write_bytes(b"")
    st = layout_probe.viewer_gds_status(bad)
    assert st["ok"] is False

    # A run with no GDS at all is also not viewable.
    none = tmp_path / "runs" / "none"
    (none / "final").mkdir(parents=True)
    assert layout_probe.viewer_gds_status(none)["ok"] is False


# ------------------------------------------------ Summary-tab completeness --

def test_every_test_file_has_an_explicit_summary_implication():
    """The Actions Summary tab must explain what EVERY test file protects.

    test_summary.py falls back to a generic line for unknown files — fine as a
    safety net, but a new test file shipping without a real implication row
    means the Summary tab can't say what a failure puts at stake. Lock the
    inventory: every lanex/tests/test_*.py needs its own IMPLICATIONS entry.
    """
    sys.path.insert(0, str(_SC))
    try:
        import test_summary as ts
    finally:
        sys.path.remove(str(_SC))
    files = sorted(p.stem for p in Path(__file__).parent.glob("test_*.py"))
    missing = [f for f in files if f not in ts.IMPLICATIONS]
    assert not missing, (
        "these test files have no Summary-tab implication row in "
        f"scripts/ci/test_summary.py IMPLICATIONS: {missing}")
    # And no stale rows for deleted files (a stale row is a lie in waiting).
    stale = [k for k in ts.IMPLICATIONS if k.startswith("test_") and k not in files]
    assert not stale, f"IMPLICATIONS rows for nonexistent test files: {stale}"
