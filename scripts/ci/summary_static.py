#!/usr/bin/env python3
# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Append the non-pytest gates of the CI 'test' job to the step summary.

The unit-test table (test_summary.py) covers pytest; this documents the other
gates the same job enforces — the frontend behaviour test, JS syntax, the
emoji-hygiene rule, and the wheel-bundles-assets check — each with what it
protects, so the Summary tab describes the WHOLE job, not just pytest. Stdlib.
"""
from __future__ import annotations

import os
import sys

ROWS = [
    ("Frontend behaviour (`frontend_test.mjs`)",
     "Executes the display functions (metric formatting, HTML escaping, CSV quoting) — a wrong number or "
     "unescaped tool string on screen fails here (syntax-checking alone never runs this)."),
    ("JavaScript syntax (`node --check`)",
     "Every frontend module parses — a broken build can't ship a blank cockpit."),
    ("Static hygiene (no emoji pictographs)",
     "First-party UI uses the shared line-icon set, not emoji — locks the round-26 rule."),
    ("Wheel bundles the frontend",
     "The built package actually contains `server/static/**` — no 'installs but shows a blank page'."),
]


def main() -> int:
    lines = [
        "### Other gates in this job",
        "",
        "| Gate | What it protects |",
        "|---|---|",
    ]
    for gate, why in ROWS:
        lines.append(f"| {gate} | {why} |")
    lines += [
        "",
        "> Reaching this summary means the steps above ran; a red job shows which one stopped it.",
        "",
    ]
    text = "\n".join(lines) + "\n"
    dest = os.environ.get("GITHUB_STEP_SUMMARY")
    if dest:
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
