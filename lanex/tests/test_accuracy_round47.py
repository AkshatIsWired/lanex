# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Lock-in tests for the accuracy-audit round (round 47).

Codifies the two HIGH accuracy bugs the external audit found, plus the
loud-failure guards and consistency fixes shipped with them:

* Timing panel must read the FINAL multi-corner STA step (per-corner subdirs),
  never silently fall back to a mid-PnR report presented as if final.
* ``parse_lvs`` must anchor its verdict on Netgen's own final-verdict line and
  never read inventory counts as unmatched counts (a clean run showed
  "362 unmatched devices").
* Whitespace-in-path refusal, recorded-CLI passthrough, step-log id forms,
  non-finite export tokens, tool-probe caching.

Pure stdlib, hermetic — every run dir is synthesised in ``tmp_path``.
"""
from __future__ import annotations

import json
from pathlib import Path

from lanex.controller import history, reports, timing, tools
from lanex.server import routes


# --------------------------------------------------------------------------
# HIGH #1 — final STA step with per-corner subdirs must win over mid-PnR
# --------------------------------------------------------------------------

_MET_REPORT = """
Startpoint: a (input)
Endpoint: _1_ (flip-flop)
Path Group: clk
Path Type: max
                       9.000000   data required time
                      -8.223000   data arrival time
                       0.777000   slack (MET)
"""

_VIOLATED_REPORT = """
Startpoint: b (input)
Endpoint: _2_ (flip-flop)
Path Group: clk
Path Type: max
                       1.000000   data required time
                      -1.285741   data arrival time
                      -0.285741   slack (VIOLATED)
"""


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_timing_prefers_postpnr_corner_subdirs(tmp_path: Path):
    """The exact audit failure: mid-PnR said MET, final slow corner VIOLATED.
    Only the top-level report existed for mid-PnR, so the old picker showed the
    optimistic mid-PnR numbers as if they were signoff."""
    run = tmp_path / "runs" / "r1"
    _write(run / "43-openroad-stamidpnr-3" / "max.rpt", _MET_REPORT)
    _write(run / "55-openroad-stapostpnr" / "max_ss_100C_1v60" / "max.rpt",
           _VIOLATED_REPORT)
    _write(run / "55-openroad-stapostpnr" / "nom_tt_025C_1v80" / "max.rpt",
           _MET_REPORT)
    r = timing.timing_paths(run, kind="setup")
    assert r["ok"] is True
    assert r["step"] == "55-openroad-stapostpnr"
    # Both corners aggregated; worst-first ordering surfaces the violation.
    assert set(r["corners"]) == {"max_ss_100C_1v60", "nom_tt_025C_1v80"}
    assert r["violating"] == 1
    assert r["paths"][0]["slack"] < 0
    assert r["paths"][0]["corner"] == "max_ss_100C_1v60"
    # Provenance says step 55 across corners, and lists every file read.
    assert "55-openroad-stapostpnr" in r["source"]
    assert len(r["sources"]) == 2


def test_timing_top_level_report_still_works(tmp_path: Path):
    run = tmp_path / "runs" / "r1"
    _write(run / "43-openroad-stamidpnr-3" / "max.rpt", _MET_REPORT)
    r = timing.timing_paths(run, kind="setup")
    assert r["ok"] is True
    assert r["step"] == "43-openroad-stamidpnr-3"
    assert r["violating"] == 0


def test_timing_no_reports_is_explicit(tmp_path: Path):
    r = timing.timing_paths(tmp_path, kind="setup")
    assert r["ok"] is False
    assert "no setup timing report" in r["error"]


# --------------------------------------------------------------------------
# HIGH #2 — parse_lvs three-state verdict, inventory counts never mislabelled
# --------------------------------------------------------------------------

_NETGEN_CLEAN = """Netgen 1.5.295
Circuit 1 contains 362 devices, circuit 2 contains 362 devices.
Number of devices: 362         |Number of devices: 362
Number of nets: 395            |Number of nets: 395
Netlists match uniquely.
Cell pin lists are equivalent.
Device classes spm and spm are equivalent.

Final result: Circuits match uniquely.
"""

_NETGEN_DIRTY = """Netgen 1.5.295
Number of devices: 362         |Number of devices: 360
NET mismatches: unmatched nets = 3
unmatched devices: 2

Final result: Netlists do not match.
"""


def test_parse_lvs_clean_run_shows_clean(tmp_path: Path):
    """The audit case: a clean report's inventory counts (362 devices / 395
    nets) were reported as unmatched_* counts. Verdict must be clean, counts
    empty."""
    f = tmp_path / "lvs.rpt"
    f.write_text(_NETGEN_CLEAN, encoding="utf-8")
    out = reports.parse_lvs(f)
    assert out["status"] == "clean"
    assert out["counts"] == {}
    assert "match uniquely" in out["verdict"].lower()


def test_parse_lvs_mismatch_run(tmp_path: Path):
    f = tmp_path / "lvs.rpt"
    f.write_text(_NETGEN_DIRTY, encoding="utf-8")
    out = reports.parse_lvs(f)
    assert out["status"] == "mismatch"
    assert out["counts"]["unmatched_nets"] == 3
    assert out["counts"]["unmatched_devices"] == 2


def test_parse_lvs_no_verdict_is_unknown(tmp_path: Path):
    f = tmp_path / "lvs.rpt"
    f.write_text("free-form text, netgen crashed before comparing\n", encoding="utf-8")
    out = reports.parse_lvs(f)
    assert out["status"] == "unknown"
    assert out["verdict"] is None


def test_parse_lvs_verdict_vs_counts_disagreement_surfaces(tmp_path: Path):
    """A 'clean' verdict alongside explicit non-zero unmatched counts must not
    be silently trusted — surface it as a mismatch."""
    f = tmp_path / "lvs.rpt"
    f.write_text("unmatched devices = 4\nFinal result: Circuits match uniquely.\n",
                 encoding="utf-8")
    out = reports.parse_lvs(f)
    assert out["status"] == "mismatch"


def test_parse_lvs_port_errors_is_not_clean(tmp_path: Path):
    f = tmp_path / "lvs.rpt"
    f.write_text("Final result: Circuits match uniquely with port errors.\n",
                 encoding="utf-8")
    out = reports.parse_lvs(f)
    assert out["status"] == "mismatch"


# --------------------------------------------------------------------------
# P1 — whitespace-in-path refusal (LibreLane/Yosys split paths on whitespace)
# --------------------------------------------------------------------------

def test_whitespace_path_error():
    assert routes._whitespace_path_error("/home/u/my_chip") is None
    err = routes._whitespace_path_error("/home/u/my chip")
    assert err is not None and "spaces" in err
    err = routes._whitespace_path_error("/home/u/ok", "/pdk root/with space")
    assert err is not None and "PDK root" in err


# --------------------------------------------------------------------------
# P2 — /api/cli-command returns an existing run's RECORDED command verbatim
# --------------------------------------------------------------------------

def test_recorded_cli_command_roundtrip(tmp_path: Path):
    run = tmp_path / "runs" / "t1"
    run.mkdir(parents=True)
    recorded = {
        "container": "librelane --pdk-root /home/u/.ciel --docker-no-tty --dockerized config.json",
        "local": "librelane --pdk-root /home/u/.ciel config.json",
        "recommended": "container",
        "cwd": str(tmp_path),
    }
    (run / "gui-run.json").write_text(
        json.dumps({"tag": "t1", "cli_command": recorded}), encoding="utf-8")
    out = routes._recorded_cli_command(str(tmp_path), "t1")
    assert out is not None
    assert out["recorded"] is True
    # Verbatim — the recorded strings, not a re-derivation from the current env.
    assert out["container"] == recorded["container"]
    assert out["local"] == recorded["local"]


def test_recorded_cli_command_partial_or_missing_falls_through(tmp_path: Path):
    assert routes._recorded_cli_command(str(tmp_path), "nope") is None
    run = tmp_path / "runs" / "t2"
    run.mkdir(parents=True)
    (run / "gui-run.json").write_text(
        json.dumps({"cli_command": {"container": "only-half"}}), encoding="utf-8")
    assert routes._recorded_cli_command(str(tmp_path), "t2") is None


# --------------------------------------------------------------------------
# P2 — step-log lookup accepts the on-disk dir name; a miss lists valid ids
# --------------------------------------------------------------------------

def test_get_step_output_accepts_both_id_forms(tmp_path: Path):
    step = tmp_path / "64-magic-drc"
    step.mkdir()
    (step / "magic-drc.log").write_text("drc output\n", encoding="utf-8")
    for form in ("Magic.DRC", "magic-drc", "64-magic-drc"):
        out = history.get_step_output(tmp_path, form)
        assert out["ok"] is True, form
        assert "drc output" in out["log"] or "drc output" in str(out)


def test_get_step_output_miss_lists_valid_steps(tmp_path: Path):
    (tmp_path / "64-magic-drc").mkdir()
    out = history.get_step_output(tmp_path, "Netgen.LVS")
    assert out["ok"] is False
    assert out["valid_steps"] == ["64-magic-drc"]


# --------------------------------------------------------------------------
# P2 — exports use one non-finite spelling: the API/CSV tokens
# --------------------------------------------------------------------------

def test_metric_text_tokens():
    assert history._metric_text(float("inf")) == "Infinity"
    assert history._metric_text(float("-inf")) == "-Infinity"
    assert history._metric_text(float("nan")) == "NaN"
    assert history._metric_text(1.5) == "1.5"
    assert history._metric_text("keep") == "keep"


def test_md_export_uses_infinity_token(tmp_path: Path):
    run = tmp_path / "runs" / "r1"
    (run / "final").mkdir(parents=True)
    # Bare Infinity exactly as LibreLane's json.dump emits it.
    (run / "final" / "metrics.json").write_text(
        '{"timing__setup_r2r__ws": Infinity, "design__instance__count": 7}',
        encoding="utf-8")
    out = history.export_run(run, "md")
    assert out["ok"] is True
    assert "Infinity" in out["text"]
    assert "| inf |" not in out["text"]


# --------------------------------------------------------------------------
# P1 — engine probe / check_tools caching (the preflight-hang fix)
# --------------------------------------------------------------------------

def test_engine_probe_cached(monkeypatch):
    calls = {"n": 0}

    def fake_exec(cmd, timeout=0.0):
        calls["n"] += 1
        return 1, "", "daemon down"

    monkeypatch.setattr(tools, "_shell_exec", fake_exec)
    tools._engine_probe_cache.clear()
    r1 = tools._engine_usable("docker")
    r2 = tools._engine_usable("docker")
    assert r1 == r2 == (False, "daemon down")
    assert calls["n"] == 1  # second call served from the TTL cache
    tools._engine_probe_cache.clear()


def test_check_tools_ttl_cache_and_force():
    r1 = tools.check_tools()
    r2 = tools.check_tools()
    assert r2 is r1  # within TTL: the same cached object, no re-probe
    r3 = tools.check_tools(force=True)
    assert isinstance(r3, dict) and "tools" in r3
