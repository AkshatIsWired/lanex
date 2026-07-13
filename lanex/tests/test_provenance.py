# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Provenance: displayed values must trace to the exact tool-written line.

The killer property, proven against the committed golden of a REAL SPM run's
metrics.json: for EVERY metric key, the located line's own text parses back to
exactly the value the API serves. A locator that points at the wrong line —
the one class of bug that would make the transparency feature itself
misleading — fails here.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from lanex.controller import provenance

GOLDEN_METRICS = Path(__file__).parent / "goldens" / "display_run" / "metrics.json"


@pytest.fixture()
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "final").mkdir()
    shutil.copy(GOLDEN_METRICS, tmp_path / "final" / "metrics.json")
    return tmp_path


def _parse_line_value(line_text: str, key: str):
    """Parse the value out of one `"key": value,` line of a json.dump file.

    Splits AFTER the key (corner-qualified metric names contain ':' inside
    the key itself, so a naive colon split would cut the key in half).
    """
    frag = line_text.split(f'"{key}":', 1)[1].strip().rstrip(",")
    if frag in ("Infinity", "-Infinity", "NaN"):
        return frag  # the token convention the API serves
    return json.loads(frag)


def test_every_golden_metric_locates_to_its_own_line(run_dir: Path) -> None:
    raw = GOLDEN_METRICS.read_text()
    # Same non-finite tokening the server's json_safe applies before the wire.
    import re
    tokened = re.sub(r'([:\[,]\s*)(-?Infinity|NaN)(\s*[,}\]])', r'\1"\2"\3', raw)
    metrics = json.loads(tokened)
    lines = raw.splitlines()
    assert len(metrics) >= 300, "golden shrank"
    for key, want in metrics.items():
        res = provenance.metric_provenance(run_dir, key)
        assert res["ok"], f"{key}: {res}"
        assert res["rel"] == "final/metrics.json"
        line_text = lines[res["line"] - 1]
        assert res["text"] == line_text, f"{key}: returned text != file line"
        assert f'"{key}":' in line_text, f"{key}: line does not carry the key"
        got = _parse_line_value(line_text, key)
        assert got == want, f"{key}: line value {got!r} != metrics value {want!r}"


def test_absent_metric_is_honestly_absent(run_dir: Path) -> None:
    res = provenance.metric_provenance(run_dir, "no__such__metric")
    assert res["ok"] is False
    assert "not in" in res["reason"]


def test_no_metrics_file_is_honest(tmp_path: Path) -> None:
    res = provenance.metric_provenance(tmp_path, "design__instance__count")
    assert res["ok"] is False
    assert "no metrics.json" in res["reason"]


def test_run_root_metrics_fallback(tmp_path: Path) -> None:
    (tmp_path / "metrics.json").write_text('{\n    "design__instance__count": 3\n}\n')
    res = provenance.metric_provenance(tmp_path, "design__instance__count")
    assert res["ok"] and res["rel"] == "metrics.json" and res["line"] == 2


def test_metric_key_with_special_chars_never_regexes(tmp_path: Path) -> None:
    # Metric names carry ':' and '.' (corner-qualified keys) — the locator must
    # treat them literally.
    key = "timing__setup_r2r__ws__corner:nom_tt_025C_1v80"
    (tmp_path / "metrics.json").write_text('{\n    "%s": 1.5\n}\n' % key)
    res = provenance.metric_provenance(tmp_path, key)
    assert res["ok"] and res["line"] == 2


def test_traversalish_keys_rejected(run_dir: Path) -> None:
    for bad in ("../x", "a/b", "a\\b", ""):
        assert provenance.metric_provenance(run_dir, bad)["ok"] is False
        assert provenance.config_provenance(run_dir, bad)["ok"] is False
        assert provenance.base_config_provenance(run_dir, bad)["ok"] is False


def test_config_provenance_prefers_top_level_over_nested(tmp_path: Path) -> None:
    # A nested corner map could carry a same-named key deeper — the top-level
    # (least indented) line is the variable the flow resolved.
    (tmp_path / "resolved.json").write_text(
        '{\n'
        '    "SOME_MAP": {\n'
        '        "FP_CORE_UTIL": 99\n'
        '    },\n'
        '    "FP_CORE_UTIL": 45\n'
        '}\n')
    res = provenance.config_provenance(tmp_path, "FP_CORE_UTIL")
    assert res["ok"] and res["line"] == 5 and '"FP_CORE_UTIL": 45' in res["text"]


def test_config_provenance_no_resolved_is_honest(tmp_path: Path) -> None:
    res = provenance.config_provenance(tmp_path, "PDK")
    assert res["ok"] is False and "resolved.json" in res["reason"]


def test_base_config_json_yaml_and_absent(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text('{\n    "CLOCK_PERIOD": 25\n}\n')
    res = provenance.base_config_provenance(tmp_path, "CLOCK_PERIOD")
    assert res["ok"] and res["rel"] == "config.json" and res["line"] == 2

    res = provenance.base_config_provenance(tmp_path, "FP_CORE_UTIL")
    assert res["ok"] is False and "not set" in res["reason"]

    y = tmp_path / "ydes"
    y.mkdir()
    (y / "config.yaml").write_text("DESIGN_NAME: spm\nCLOCK_PERIOD: 10\n")
    res = provenance.base_config_provenance(y, "CLOCK_PERIOD")
    assert res["ok"] and res["rel"] == "config.yaml" and res["line"] == 2

    t = tmp_path / "tdes"
    t.mkdir()
    (t / "config.tcl").write_text('set ::env(CLOCK_PERIOD) 10\n')
    res = provenance.base_config_provenance(t, "CLOCK_PERIOD")
    assert res["ok"] and res["rel"] == "config.tcl" and res["line"] == 1

    empty = tmp_path / "empty"
    empty.mkdir()
    assert provenance.base_config_provenance(empty, "PDK")["ok"] is False


def test_report_provenance_first_hit_and_raw_view(tmp_path: Path) -> None:
    rpt = tmp_path / "55-openroad-stapostpnr" / "max.rpt"
    rpt.parent.mkdir()
    rpt.write_text("header\nStartpoint: a\nslack (MET) 1.0\nStartpoint: b\n")
    res = provenance.report_provenance(tmp_path, "55-openroad-stapostpnr/max.rpt",
                                       "Startpoint:")
    assert res["ok"] and res["line"] == 2 and res["text"] == "Startpoint: a"
    # Empty needle = plain raw view, ok with no highlighted line.
    res = provenance.report_provenance(tmp_path, "55-openroad-stapostpnr/max.rpt", "")
    assert res["ok"] and res["line"] is None
    # Absent file / absent needle stay honest.
    assert provenance.report_provenance(tmp_path, "nope.rpt", "x")["ok"] is False
    miss = provenance.report_provenance(tmp_path, "55-openroad-stapostpnr/max.rpt", "zebra")
    assert miss["ok"] is False and "not found" in miss["reason"]


def test_lvs_verdict_line_locates_on_real_golden() -> None:
    # The committed known-bad golden carries a REAL Netgen report — the
    # violations tab highlights its "Final result" verdict line.
    root = Path(__file__).parent / "goldens" / "failing_run"
    hits = [p for p in root.rglob("*") if p.is_file() and
            ("lvs" in p.name.lower() or p.suffix == ".rpt")]
    lvs = [p for p in hits if "Final result" in p.read_text(errors="replace")]
    if not lvs:
        pytest.skip("no LVS report with a verdict line in the failing_run golden")
    rel = lvs[0].relative_to(root)
    res = provenance.report_provenance(root, str(rel), "Final result")
    assert res["ok"] and "Final result" in res["text"]


# ---------------------------------------------------------------- route level
class _FakeHandler:
    def __init__(self, path: str) -> None:
        self.path = path
        self.sent = None

    # routes._respond duck-typing surface
    def send_response(self, *a, **k): ...
    def send_header(self, *a, **k): ...
    def end_headers(self): ...
    class wfile:  # noqa: N801 - mimic attribute
        @staticmethod
        def write(_b): ...


def _call_route(monkeypatch, design_dir: Path, query: str):
    from lanex.server import routes
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(design_dir))
    captured = {}

    def fake_respond(handler, payload, code=200):
        captured["payload"] = payload
        captured["code"] = code

    monkeypatch.setattr(routes, "_respond", fake_respond)
    h = _FakeHandler("/api/provenance?" + query)
    routes.h_provenance(h)
    return captured


def test_route_metric_and_traversal(monkeypatch, tmp_path: Path) -> None:
    design = tmp_path
    run = design / "runs" / "r1"
    (run / "final").mkdir(parents=True)
    shutil.copy(GOLDEN_METRICS, run / "final" / "metrics.json")

    out = _call_route(monkeypatch, design,
                      "kind=metric&key=design__instance__count&tag=r1")
    p = out["payload"]
    assert p["ok"] and p["rel"] == "final/metrics.json" and p["line"] > 1
    assert p["abs"].endswith("final/metrics.json")

    # Unknown tag = honest refusal, never a path outside runs/.
    out = _call_route(monkeypatch, design,
                      "kind=metric&key=x&tag=../../etc")
    assert out["payload"]["ok"] is False

    # Report path traversal is a 400.
    out = _call_route(monkeypatch, design,
                      "kind=report&tag=r1&path=../../secret&needle=x")
    assert out["code"] == 400

    # Unknown kind is a 400.
    out = _call_route(monkeypatch, design, "kind=nope&key=x&tag=r1")
    assert out["code"] == 400


def test_route_input_kind(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text('{\n    "PDK": "sky130A"\n}\n')
    out = _call_route(monkeypatch, tmp_path, "kind=input&key=PDK")
    p = out["payload"]
    assert p["ok"] and p["rel"] == "config.json" and p["line"] == 2
