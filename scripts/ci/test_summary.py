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
    "test_fixes_round73": "Accuracy fixes N2-N7: partial-sim marked partial, SSE gap re-hydrates the live pipeline, timing unit single-sourced, multi-config warned + preflight/run-start agree, config drift hash (Fears A/F/G/K).",
    "test_fixes_round74": "The money-loss fear locks: every run stamps its toolchain identity (LanEx/LibreLane versions + container image) so results are reproducible (Fears Q/S); the reproduce command round-trips the run's inputs (Fear P); the DSE queue is strictly serial — no two runs cross-attribute (Fear N); and raw derivation inputs stay in physical range so an upstream units flip is caught before scaling (Fear R).",
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
    "test_viewers_plugins": "Cell parsing + desktop-tool launch guards behave; plugin surface stays removed.",
    "test_viewer_handoff": "Every layout viewer receives ALL the run data it can render: OpenROAD gets db+liberty+sdc+spef and the marker/DRC inventory (clean-vs-violations said out loud); KLayout gets the DRC/XOR marker databases; Magic/GDS3D flags stay existence-guarded.",
    "test_packaging": "The built wheel ships the frontend assets — no 'installs but blank page'.",
    "test_gtkwave": "The 'Open in GTKWave' pipeline is wired end-to-end: catalog/installer/whitelist entries, launch argv, VCD-header parsing, .gtkw generation, and the traversal-guarded route.",
    "test_wave_fidelity": "Every waveform parser (product, in-browser viewer, CI reference) reads the SAME golden Icarus dump and recovers the exact values the simulator wrote — a viewer can never show wrong sim data.",
    "test_provenance": "Every displayed value traces to the tool's own file+line: all 305 golden metrics locate to a line that parses back to the served value; absent keys honestly absent; traversal refused.",
    "test_dialog_scroll": "Long dialog content stays reachable: the body scrolls (real-browser layout check) and customDialog can never regress onto the folder-browser's clipped .dlg-wide variant.",
    "test_display_derivations": "The few DERIVED display values (utilization %, die W×H, power mW) recompute exactly from the raw golden metrics — no silent unit/scale mangling.",
    "test_install_script": "The one-line installer keeps its contracts: main-on-last-line, degradable stages, git+gtkwave in every package stage, and a skippable best-effort GDS3D stage.",
    "test_macos_install": "The macOS install paths (GDS3D app, engines, XQuartz display detection, arch/version guards) stay correct without a Mac in CI.",
    "test_appwindow": "The standalone app-window launcher picks a real browser per platform and can never leave the user with no UI.",
    "test_runner": "The flow runner streams librelane's own per-step events and full-detail logs (the __librelane__/SUBPROCESS bridge) — local runs stay first-class.",
    "test_tools_container_grid": "The Tools grid only advertises container launches the engine+image can actually deliver.",
    "test_fixes_gf180": "gf180/non-sky130 PDKs keep working: root-owned ciel store recovery and the generalized KLayout .lyp lookup.",
    "test_fixes_audit": "The audited round-19 fixes stay fixed: security confinement, DSE sweep manifests, SSE robustness.",
    "test_fixes_round2": "The round-1/2 audit fixes stay fixed (pure controller logic, no tools needed).",
    "test_fixes_round3": "The round-3 six-issue UX batch stays fixed (run scan, status truthfulness).",
    "test_fixes_round4": "The round-4 user-reported fixes stay fixed (fixture-driven controller checks).",
    "test_fixes_round16": "Auto-config, container step-slicing, container-tool argv, custom-cell swap, and the manual-console allow-list keep working.",
    "test_fixes_round17": "Auto-config never picks a testbench as top; override cleaning keeps 0/False; reproduce metadata stays complete.",
    "test_fixes_round18": "Platform/WSL batch: DNS remediation surfaces, Windows PATH filtering, GDS3D dev-header auto-install.",
    "test_fixes_round20": "Runaway sims get killed by the watchdog; file delete confined; bundle resolves real sources.",
    "test_fixes_round21": "OpenROAD GUI startup tcl loads db+liberty+sdc+spef; compare picks run dirs correctly.",
    "test_fixes_round22": "Known-designs persistence + OpenROAD STA corners stay correct (cross-design Compare/DSE).",
    "test_fixes_round25": "WSL native-tool probes ignore Windows /mnt/c binaries; root escalation works without a TTY.",
    "test_fixes_round26": "Tools installed into ~/.local/bin are detected; password-prompt banner reaches the user.",
    "test_fixes_round27": "GDS3D opens on WSL: software-GL fallback + legacy X11 fonts auto-install.",
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


def _detail_line(el: ET.Element) -> str:
    """One readable line from a <failure>/<error>/<skipped> element."""
    msg = (el.get("message") or (el.text or "").strip().splitlines()[0:1] or [""])
    if isinstance(msg, list):
        msg = msg[0]
    msg = " ".join(str(msg).split())
    if len(msg) > 220:
        msg = msg[:217] + "…"
    return msg.replace("|", "\\|")


def _parse(xml_path: Path) -> Tuple[Dict[str, List[int]], int, int, int, float,
                                    List[Tuple[str, str, str]],
                                    List[Tuple[str, str, str]]]:
    """Return (per-file [pass,fail,skip], totals pass/fail/skip, wall seconds,
    failures [(file, test, message)], skips [(file, test, reason)])."""
    root = ET.parse(xml_path).getroot()
    per: Dict[str, List[int]] = defaultdict(lambda: [0, 0, 0])
    tot_p = tot_f = tot_s = 0
    wall = 0.0
    failures: List[Tuple[str, str, str]] = []
    skips: List[Tuple[str, str, str]] = []
    for tc in root.iter("testcase"):
        key = _file_key(tc)
        name = tc.get("name") or "?"
        wall += float(tc.get("time") or 0.0)
        bad = tc.find("failure")
        if bad is None:
            bad = tc.find("error")
        if bad is not None:
            per[key][1] += 1
            tot_f += 1
            failures.append((key, name, _detail_line(bad)))
        elif (sk := tc.find("skipped")) is not None:
            per[key][2] += 1
            tot_s += 1
            skips.append((key, name, _detail_line(sk)))
        else:
            per[key][0] += 1
            tot_p += 1
    return per, tot_p, tot_f, tot_s, wall, failures, skips


def render(xml_path: Path, title: str) -> str:
    per, tp, tf, ts, wall, failures, skips = _parse(xml_path)
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
    # A red group in the table says WHERE; this says exactly WHICH test and
    # WHY it failed, so nobody has to dig the raw log for the first triage.
    if failures:
        lines += ["### ✗ Failing tests", "",
                  "| Test | Failure |", "|---|---|"]
        for key, name, msg in failures:
            impl = IMPLICATIONS.get(key)
            impl_note = f"<br><sub>At stake: {impl}</sub>" if impl else ""
            lines.append(f"| `{key}::{name}` | {msg or 'see the job log'}{impl_note} |")
        lines.append("")
    if skips:
        lines += ["<details><summary>Skipped tests"
                  f" ({len(skips)}) — each states its reason</summary>", ""]
        for key, name, msg in skips:
            lines.append(f"- `{key}::{name}` — {msg or 'no reason recorded'}")
        lines += ["", "</details>", ""]
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
