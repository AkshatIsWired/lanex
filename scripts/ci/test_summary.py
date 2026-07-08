#!/usr/bin/env python3
# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Render a rich GitHub-Actions step summary from a pytest JUnit XML report.

The Actions "Summary" tab otherwise shows nothing for the unit suite — just a
green check. This turns the ~500-test run into a grouped table that also states,
for every group, WHAT a failure there would mean (the implication), so a reader
who never opens the logs still understands what each test protects.

Usage:  python scripts/ci/test_summary.py <pytest-junit.xml> [--title "..."]
Reads GITHUB_STEP_SUMMARY from the env (falls back to stdout). Stdlib only.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

# What each test file protects — the "implication" column. A file not listed
# gets the generic regression note (still counted, never hidden).
IMPLICATIONS: Dict[str, str] = {
    "test_goldens": "Metric passthrough is byte/value-faithful; non-finite metrics never reach the wire raw (Fear A).",
    "test_failing_run": "A run that FAILED signoff (real DRC/LVS/timing) is never shown as tape-out ready (Fear A, known-bad).",
    "test_verify": "The signoff verdict stays 3-state — pass / fail / unknown never collapse to two.",
    "test_reports": "DRC/LVS parsers are 3-state: a missing or empty report can never read as clean.",
    "test_accuracy_round47": "Timing reads the FINAL post-PnR STA; Netgen LVS verdict-anchored; probe timeouts bounded.",
    "test_accuracy_round52": "Input hygiene (whitespace, atomic sidecars, list overrides) + viewer tech-file guards + 3-state DRC.",
    "test_custom_macros": "A custom hard macro (MACROS overlay) reaches the flow exactly as configured.",
    "test_container_run": "The dockerized argv LanEx builds equals the librelane command a user would type (CLI≡GUI).",
    "test_cancel_container": "Cancel actually kills the container — a cancelled run leaves no orphan flow still writing.",
    "test_bundle_artifacts": "Run bundles are byte-faithful and record honestly what was skipped (Fear C).",
    "test_export": "CSV/MD/HTML exports equal the metrics on disk; non-finite tokens agree across every surface.",
    "test_history": "Run success + metrics are derived correctly from the on-disk run tree.",
    "test_run_import": "Importing a run reproduces identical metrics (round-trip fidelity, Fear C).",
    "test_installer": "PDK/tool installation logic behaves and self-heals instead of looping on a bad state.",
    "test_install_foolproof": "The one-click install path stays foolproof across the platform edge cases it has hit.",
    "test_pdk": "PDK detection/enable is correct so the flow runs against the PDK the user picked (Fear B).",
    "test_pdk_resolve": "The resolved PDK_ROOT points at the files the selected run mode actually needs.",
    "test_compat": "Drift canary — parsers stay aligned with the installed librelane; upstream changes fail loud, not silent.",
    "test_ci_helpers": "The CI comparators themselves are correct, incl. G8 (a viewer only ever gets a valid, non-empty GDS).",
    "test_editor_lint_sim": "IDE lint/sim jobs behave; watchdogs free a stuck job instead of hanging 'running'.",
    "test_introspect": "Step/metric/variable introspection matches librelane, so the UI offers real options only.",
    "test_scaffold": "Generated example/config scaffolding is valid and launches.",
    "test_server": "HTTP routing, CSRF, and traversal confinement hold (no arbitrary file read).",
    "test_tools": "Tool/engine detection is accurate and its probes can't hang the UI.",
    "test_fsbrowser": "The file browser stays confined to allowed roots (no path traversal).",
    "test_alerts": "Failed-step advisories map to the right plain-language explanation.",
    "test_watch_pin": "Run watch/pin/notes persist and read back correctly.",
    "test_dse_reverify": "DSE sweeps + targeted re-verify launch through the SAME assembly path as a normal run (Fear B).",
    "test_viewers_plugins": "Cell parsing + the plugin store (checksum-verified installs) behave.",
    "test_packaging": "The built wheel ships the frontend assets — no 'installs but blank page'.",
}

_GENERIC = "Regression lock for a previously-fixed issue — keeps it from coming back."


def _file_key(testcase: ET.Element) -> str:
    """Best-effort test-file basename for a <testcase> (e.g. 'test_goldens')."""
    f = testcase.get("file")
    if f:
        return Path(f).stem
    cls = testcase.get("classname") or ""
    for part in cls.split("."):
        if part.startswith("test_"):
            return part
    return cls or "other"


def _parse(xml_path: Path) -> Tuple[Dict[str, List[int]], int, int, int, float]:
    """Return (per-file [pass,fail,skip], totals pass/fail/skip, wall seconds)."""
    root = ET.parse(xml_path).getroot()
    per: Dict[str, List[int]] = defaultdict(lambda: [0, 0, 0])
    tot_p = tot_f = tot_s = 0
    wall = 0.0
    for tc in root.iter("testcase"):
        key = _file_key(tc)
        wall += float(tc.get("time") or 0.0)
        if tc.find("failure") is not None or tc.find("error") is not None:
            per[key][1] += 1
            tot_f += 1
        elif tc.find("skipped") is not None:
            per[key][2] += 1
            tot_s += 1
        else:
            per[key][0] += 1
            tot_p += 1
    return per, tot_p, tot_f, tot_s, wall


def render(xml_path: Path, title: str) -> str:
    per, tp, tf, ts, wall = _parse(xml_path)
    verdict = "✓ all green" if tf == 0 else f"✗ {tf} FAILING"
    lines: List[str] = [
        f"## {title}",
        "",
        f"**{tp} passed · {tf} failed · {ts} skipped** in {wall:.1f}s — {verdict}",
        "",
        "| Test group | Result | Tests | What a failure here would mean |",
        "|---|---|--:|---|",
    ]
    for key in sorted(per):
        p, f, s = per[key]
        if f:
            res = f"✗ {f} FAIL"
        elif p:
            res = "✓ pass"
        else:
            res = "– skip"
        n = p + f + s
        why = IMPLICATIONS.get(key, _GENERIC)
        lines.append(f"| `{key}` | {res} | {n} | {why} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: List[str]) -> int:
    if not argv:
        print("usage: test_summary.py <pytest-junit.xml> [--title T]", file=sys.stderr)
        return 2
    xml_path = Path(argv[0])
    title = "Unit tests"
    if "--title" in argv:
        title = argv[argv.index("--title") + 1]
    if not xml_path.is_file():
        print(f"no JUnit report at {xml_path}", file=sys.stderr)
        return 0  # don't fail the job over a missing summary
    text = render(xml_path, title)
    dest = os.environ.get("GITHUB_STEP_SUMMARY")
    if dest:
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
