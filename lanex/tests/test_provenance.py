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


def test_base_config_empty_var_locates_the_file_itself(tmp_path: Path) -> None:
    """Empty var = 'show me the config file' (the Setup-tab view button):
    the file is located honestly, with NO line — never a guessed highlight."""
    (tmp_path / "config.json").write_text('{"DESIGN_NAME": "spm"}\n')
    res = provenance.base_config_provenance(tmp_path, "")
    assert res["ok"] is True
    assert res["rel"] == "config.json"
    assert res["line"] is None
    assert res["writer"] == "your design config"


def test_base_config_empty_var_prefers_json_over_yaml(tmp_path: Path) -> None:
    # Same precedence as the var lookup — the file LibreLane reads first.
    (tmp_path / "config.json").write_text("{}\n")
    (tmp_path / "config.yaml").write_text("DESIGN_NAME: spm\n")
    res = provenance.base_config_provenance(tmp_path, "")
    assert res["ok"] is True and res["rel"] == "config.json"


def test_base_config_empty_var_no_config_is_honest(tmp_path: Path) -> None:
    res = provenance.base_config_provenance(tmp_path, "")
    assert res["ok"] is False and "no config file" in res["reason"]


def test_route_input_kind_empty_key_serves_whole_file(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text('{\n    "PDK": "sky130A"\n}\n')
    out = _call_route(monkeypatch, tmp_path, "kind=input&key=")
    p = out["payload"]
    assert p["ok"] is True and p["rel"] == "config.json" and p["line"] is None
    # abs points inside the design dir — what the viewer's Copy-path shows.
    assert p["abs"] == str(tmp_path / "config.json")


def test_frontend_trail_and_view_config_wiring() -> None:
    """The Setup-tab pieces exist in the served static files: the view-config
    button, its empty-key provenance call, and the prefetched trail dialog
    that names files + line numbers instead of hiding them behind buttons."""
    static = Path(__file__).resolve().parents[1] / "server" / "static"
    cfg = (static / "modules" / "config.js").read_text()
    assert "ov-view-config" in cfg
    assert 'kind: "input", key: ""' in cfg
    assert "Open resolved.json at line" in cfg  # trail states the exact line
    assert "nothing is inserted into your file" in cfg  # honest not-set case
    fv = (static / "modules" / "fileview.js").read_text()
    # The regression this locks: scrollIntoView scrolls the DIALOG too, making
    # the toolbar unreachable on long files — the pane must scroll itself.
    assert ".scrollIntoView(" not in fv  # (comments may explain WHY it is banned)
    assert "centerInPre" in fv


# ---------------------------------------------------- input-map (bulk tier) --

SPM_YAML = """\
DESIGN_NAME: spm
VERILOG_FILES: dir::src/*.v
CLOCK_PERIOD: 10
IO_PIN_ORDER_CFG: dir::pin_order.cfg
pdk::sky130*:
  FP_CORE_UTIL: 45
  CLOCK_PERIOD: 10.0
  scl::sky130_fd_sc_hs:
    CLOCK_PERIOD: 8
pdk::gf180mcu*:
  FP_CORE_UTIL: 38
"""


def test_config_var_lines_yaml_scoping(tmp_path: Path) -> None:
    """The spm example's real shape: top-level vars, pdk:: sections, an scl::
    section nested inside one. The map must report values AS WRITTEN, prefer
    top-level entries, and label scoped ones with their exact scope — never
    claiming a scoped value applies (that would re-implement LibreLane's
    config resolution)."""
    (tmp_path / "config.yaml").write_text(SPM_YAML)
    res = provenance.config_var_lines(tmp_path)
    assert res["ok"] is True and res["rel"] == "config.yaml"
    v = res["vars"]

    assert v["DESIGN_NAME"] == {"line": 1, "text": "DESIGN_NAME: spm",
                                "value": "spm", "scoped": False,
                                "scope": None, "others": 0}
    # CLOCK_PERIOD: top-level line 3 wins; the pdk- and scl-scoped entries
    # are counted, not promoted.
    cp = v["CLOCK_PERIOD"]
    assert cp["line"] == 3 and cp["value"] == "10" and cp["scoped"] is False
    assert cp["others"] == 2
    # FP_CORE_UTIL exists ONLY inside pdk:: sections — the user's actual
    # question: the chip must say it is scoped to pdk::sky130*, value 45.
    fcu = v["FP_CORE_UTIL"]
    assert fcu == {"line": 6, "text": "  FP_CORE_UTIL: 45", "value": "45",
                   "scoped": True, "scope": "pdk::sky130*", "others": 1}
    assert "NOT_SET_VAR" not in v


def test_config_var_lines_json_scoping(tmp_path: Path) -> None:
    (tmp_path / "config.json").write_text(
        '{\n'
        '    "DESIGN_NAME": "spm",\n'
        '    "FP_CORE_UTIL": 40,\n'
        '    "pdk::sky130*": {\n'
        '        "FP_CORE_UTIL": 45,\n'
        '        "SYNTH_STRATEGY": "AREA 0"\n'
        '    }\n'
        '}\n')
    res = provenance.config_var_lines(tmp_path)
    assert res["ok"] is True and res["rel"] == "config.json"
    v = res["vars"]
    fcu = v["FP_CORE_UTIL"]
    assert fcu["line"] == 3 and fcu["value"] == "40" and fcu["scoped"] is False
    assert fcu["others"] == 1
    ss = v["SYNTH_STRATEGY"]
    assert ss["scoped"] is True and ss["scope"] == "pdk::sky130*"
    assert ss["line"] == 6 and ss["value"] == '"AREA 0"'


def test_config_var_lines_tcl_and_long_values(tmp_path: Path) -> None:
    long_val = "x" * 70
    (tmp_path / "config.tcl").write_text(
        "set ::env(PL_TARGET_DENSITY) 0.5\n"
        f"set ::env(EXTRA_LEFS) {long_val}\n")
    res = provenance.config_var_lines(tmp_path)
    v = res["vars"]
    assert v["PL_TARGET_DENSITY"] == {"line": 1,
                                      "text": "set ::env(PL_TARGET_DENSITY) 0.5",
                                      "value": "0.5", "scoped": False,
                                      "scope": None, "others": 0}
    assert v["EXTRA_LEFS"]["value"].endswith("…")  # trimmed for the chip


def test_config_var_lines_no_config_is_honest(tmp_path: Path) -> None:
    res = provenance.config_var_lines(tmp_path)
    assert res["ok"] is False and "no config file" in res["reason"]


def test_map_and_per_var_lookup_name_the_same_line(tmp_path: Path) -> None:
    """The chip (bulk map) and its click-through (per-var lookup) must point
    at the SAME line, or the dialog would highlight a different line than the
    chip named. Scoped-first file order is the trap: both must prefer the
    top-level (least-indented) entry."""
    (tmp_path / "config.yaml").write_text(
        "pdk::sky130*:\n"
        "  CLOCK_PERIOD: 8\n"
        "CLOCK_PERIOD: 10\n")
    bulk = provenance.config_var_lines(tmp_path)["vars"]["CLOCK_PERIOD"]
    single = provenance.base_config_provenance(tmp_path, "CLOCK_PERIOD")
    assert bulk["line"] == 3 and bulk["scoped"] is False
    assert single["ok"] is True and single["line"] == 3
    assert single["text"] == bulk["text"]


def test_route_input_map(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "config.yaml").write_text(SPM_YAML)
    out = _call_route(monkeypatch, tmp_path, "kind=input-map")
    p = out["payload"]
    assert p["ok"] is True and p["rel"] == "config.yaml"
    assert p["abs"] == str(tmp_path / "config.yaml")
    assert p["vars"]["FP_CORE_UTIL"]["scope"] == "pdk::sky130*"


def test_frontend_config_tier_wiring() -> None:
    """The form's 'your config' tier exists in the served static files and
    keeps its honesty properties: bulk fetch, scoped labelling, no chip
    without a map entry."""
    static = Path(__file__).resolve().parents[1] / "server" / "static"
    cfg = (static / "modules" / "config.js").read_text()
    assert "annotateConfigLines" in cfg
    assert '"input-map"' in cfg
    assert "vconfig-scoped" in cfg
    prov_js = (static / "modules" / "provenance.js").read_text()
    assert "applies only when the run's PDK/SCL matches" in prov_js
    assert "configChipSpec" in prov_js
    css = (static / "styles.css").read_text()
    assert ".vconfig" in css and ".vconfig-scoped" in css


def test_final_settings_wiring_and_server_mirror() -> None:
    """The final-settings preview must mirror the server's run assembly.

    buildFinalSettingsModel pulls PDK/STD_CELL_LIBRARY out of the overrides
    exactly like routes._assemble_overrides does — if either side changes the
    split, the preview would lie about what rides -c. Lock both sides to the
    same two keys, and lock the dialog's entry points."""
    static = Path(__file__).resolve().parents[1] / "server" / "static"
    fsjs = (static / "modules" / "finalsettings.js").read_text()
    assert "buildFinalSettingsModel" in fsjs
    assert "delete ov.PDK;" in fsjs and "delete ov.STD_CELL_LIBRARY;" in fsjs
    # The preview's overrides come from the REAL run payload, not a re-derivation.
    assert "collectRunPayload" in fsjs
    routes_py = (Path(__file__).resolve().parents[1] / "server" / "routes.py").read_text()
    assert 'overrides.pop("PDK", None)' in routes_py
    assert 'overrides.pop("STD_CELL_LIBRARY", None)' in routes_py
    cfg = (static / "modules" / "config.js").read_text()
    assert "ov-final-settings" in cfg and "finalsettings.js" in cfg
    # setup.js still exports the payload builder the dialog depends on.
    setup_js = (static / "modules" / "setup.js").read_text()
    assert "export function collectRunPayload" in setup_js


# ------------------------------------------------ resolved-map (post-run) --

def _mk_resolved_run(tmp_path: Path, with_gui_meta: bool = True) -> Path:
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    (run / "resolved.json").write_text(
        '{\n'
        '    "PDK": "sky130A",\n'
        '    "STD_CELL_LIBRARY": "sky130_fd_sc_hd",\n'
        '    "FP_CORE_UTIL": 50,\n'
        '    "CLOCK_PERIOD": 10.0,\n'
        '    "DIODE_PADDING": 2,\n'
        '    "FALLBACK_SDC_FILE": null,\n'
        '    "WIRE_LENGTH_THRESHOLD": Infinity,\n'
        '    "TECH_LEFS": {\n'
        '        "nom_*": "/pdk/x.tlef"\n'
        '    }\n'
        '}\n')
    if with_gui_meta:
        (run / "gui-run.json").write_text(json.dumps({
            "overrides": {"FP_CORE_UTIL": 50},
            "pdk": "sky130A", "scl": "sky130_fd_sc_hd"}))
    (tmp_path / "config.yaml").write_text(
        "CLOCK_PERIOD: 10\n"
        "pdk::sky130*:\n"
        "  DIODE_PADDING: 2\n")
    return run


def test_resolved_settings_attributes_every_source(tmp_path: Path) -> None:
    """The post-run table: values verbatim from resolved.json (nulls and
    non-finite included), sources attributed by key ORIGIN — override from
    gui-run.json, picker for PDK/SCL, config with its line (scoped labelled),
    default for the rest. Never by value comparison."""
    run = _mk_resolved_run(tmp_path)
    res = provenance.resolved_settings(run, tmp_path)
    assert res["ok"] is True and res["gui_meta"] is True
    assert res["config_rel"] == "config.yaml"
    by = {r["name"]: r for r in res["rows"]}
    assert len(by) == 8

    assert by["FP_CORE_UTIL"]["source"] == "override"
    assert by["FP_CORE_UTIL"]["value"] == "50"
    assert by["PDK"]["source"] == "picker"
    assert by["STD_CELL_LIBRARY"]["source"] == "picker"
    cp = by["CLOCK_PERIOD"]
    assert cp["source"] == "config" and cp["config_line"] == 1 and "scoped" not in cp
    dp = by["DIODE_PADDING"]
    assert dp["source"] == "config" and dp["scoped"] is True and dp["scope"] == "pdk::sky130*"
    assert by["TECH_LEFS"]["source"] == "default"
    # Honest values: null stays null, Infinity keeps its token, dicts compact.
    assert by["FALLBACK_SDC_FILE"]["value"] == "null"
    # The file literally says `Infinity` — the display keeps that token.
    assert by["WIRE_LENGTH_THRESHOLD"]["value"] == "Infinity"
    assert "nom_*" in by["TECH_LEFS"]["value"]
    # Every row carries its resolved.json line for the one-click raw view.
    assert all(r["line"] for r in res["rows"])
    lines = (run / "resolved.json").read_text().splitlines()
    assert lines[by["FP_CORE_UTIL"]["line"] - 1].lstrip().startswith('"FP_CORE_UTIL"')


def test_resolved_settings_without_gui_meta_degrades_honestly(tmp_path: Path) -> None:
    run = _mk_resolved_run(tmp_path, with_gui_meta=False)
    res = provenance.resolved_settings(run, tmp_path)
    assert res["ok"] is True and res["gui_meta"] is False
    assert "note" in res and "gui-run.json" in res["note"]
    by = {r["name"]: r for r in res["rows"]}
    # No override claims possible — but config/default attribution still holds.
    assert not any(r["source"] in ("override", "picker") for r in res["rows"])
    assert by["CLOCK_PERIOD"]["source"] == "config"
    assert by["FP_CORE_UTIL"]["source"] == "default"


def test_resolved_settings_missing_file_is_honest(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "r1"
    run.mkdir(parents=True)
    res = provenance.resolved_settings(run, tmp_path)
    assert res["ok"] is False and "resolved.json" in res["reason"]


def test_route_resolved_map(monkeypatch, tmp_path: Path) -> None:
    _mk_resolved_run(tmp_path)
    out = _call_route(monkeypatch, tmp_path, "kind=resolved-map&tag=r1")
    p = out["payload"]
    assert p["ok"] is True and len(p["rows"]) == 8
    assert {r["name"]: r for r in p["rows"]}["FP_CORE_UTIL"]["source"] == "override"


def test_frontend_final_settings_extras_wiring() -> None:
    static = Path(__file__).resolve().parents[1] / "server" / "static"
    fsjs = (static / "modules" / "finalsettings.js").read_text()
    assert "buildCumulativeModel" in fsjs and "openResolvedSettings" in fsjs
    assert '"resolved-map"' in fsjs
    assert "Export CSV" in fsjs  # both big tables are exportable
    an = (static / "modules" / "analytics.js").read_text()
    assert "openResolvedSettings" in an
    html = (static / "index.html").read_text()
    assert "btn-analytics-settings" in html
