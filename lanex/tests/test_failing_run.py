# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Known-BAD golden — the Fear-A insurance regression.

The clean/non-finite goldens prove a *passing* run is shown faithfully. This
one proves the opposite half, which is the dangerous half: a run that **failed
signoff** — real Magic DRC violations, a Netgen LVS mismatch, and a negative
worst-slack in the final STA — must be reported as FAILED across every surface,
and can NEVER render as tape-out ready. It is the "planted DRC violation"
reference the faithfulness plan asked for.

The corpus (``tests/goldens/failing_run/``) is hand-built from the real report
formats the tools emit (Magic DRC blocks, a Netgen ``Final result`` line, an
OpenSTA ``slack (VIOLATED)`` path), so this exercises the actual parsers, not a
mock. Pure stdlib — no EDA tools, no network — so it runs on every PR.
"""
from __future__ import annotations

from pathlib import Path

from lanex.controller import history, reports, timing, verify

GOLDENS = Path(__file__).parent / "goldens"
FAILING = GOLDENS / "failing_run"


def test_failing_golden_present() -> None:
    assert (FAILING / "final" / "metrics.json").is_file()
    assert (FAILING / "64-magic-drc" / "spm.magic.rpt").is_file()
    assert (FAILING / "70-netgen-lvs" / "lvs.report").is_file()
    assert (FAILING / "55-openroad-stapostpnr" / "max.rpt").is_file()


# --------------------------------------------------------------- the verdict
def test_failing_run_is_never_tapeout_ready() -> None:
    """The single most important assertion in the whole suite: a run that failed
    signoff must not read as ready, and must not be excused as merely
    'incomplete' — it reached signoff and FAILED."""
    report = verify.verify_report(FAILING)
    verdict = report["verdict"]
    assert verdict["ready"] is False, "a DRC/LVS/timing-failing run rendered as tape-out ready"
    assert verdict["incomplete"] is False, "a genuine FAILURE was mislabelled as merely incomplete"
    assert verdict["blockers"], "no blockers surfaced for a run that fails DRC, LVS and setup timing"


def test_failing_run_blockers_name_the_real_failures() -> None:
    blockers = verify.verify_report(FAILING)["verdict"]["blockers"]
    # The specific tool failures the user must see, each sourced from a real
    # non-zero metric / negative slack.
    for expected in ("Magic DRC", "Routing DRC", "LVS", "Setup violations"):
        assert expected in blockers, f"{expected!r} missing from blockers: {blockers}"


def test_failing_run_physical_and_timing_stages_fail() -> None:
    stages = verify.verify_report(FAILING)["stages"]
    assert stages["physical"]["status"] == "fail"
    assert stages["timing"]["status"] == "fail"


# ------------------------------------------------------------- run success
def test_failing_run_is_not_a_success() -> None:
    metrics = history._load_metrics(FAILING)
    assert history._success_from_metrics(metrics, run_dir=FAILING) is False


def test_failing_run_summary_marks_it_failed() -> None:
    summary = history._summarise(FAILING)
    doc = history.to_json(summary)
    assert doc["success"] is False


# ------------------------------------------------------- DRC (real Magic parse)
def test_failing_run_drc_parses_real_violations() -> None:
    drc = reports.parse_drc(FAILING / "64-magic-drc" / "spm.magic.rpt")
    # It really parsed (3-state) and found real violations — NOT a false clean.
    assert drc["status"] == "parsed"
    assert len(drc["violations"]) == 2
    assert drc["bbox_count"] == 3
    cats = {v["category"] for v in drc["violations"]}
    assert cats == {"LU.3", "met1.2"}


# ------------------------------------------------------- LVS (real Netgen parse)
def test_failing_run_lvs_is_mismatch() -> None:
    lvs = reports.parse_lvs(FAILING / "70-netgen-lvs" / "lvs.report")
    assert lvs["status"] == "mismatch"
    assert lvs["counts"].get("unmatched_nets") == 5


# ------------------------------------------------------- timing (real STA parse)
def test_failing_run_timing_worst_slack_is_negative() -> None:
    t = timing.timing_paths(FAILING, kind="setup")
    assert t["ok"] is True
    assert t["worst_slack"] is not None and t["worst_slack"] < 0
    assert t["violating"] >= 1
    # Sourced from the FINAL post-PnR STA step, not a mid-PnR one.
    assert t["step"] == "55-openroad-stapostpnr"
    # The worst path equals the metrics' worst-setup-slack (honest by construction).
    assert abs(t["worst_slack"] - (-0.285741)) < 1e-6


# --------------------------------------------- exported summary is not green
def test_failing_run_export_is_not_ready() -> None:
    """The saved MD/HTML report must not print a green tape-out verdict either."""
    md = history.export_run(FAILING, fmt="md")
    assert md["ok"] is True
    text = md["text"]
    assert "✅ yes" not in text, "MD export shows a green tape-out verdict for a failing run"
    assert "❌ no" in text or "incomplete" in text.lower()
