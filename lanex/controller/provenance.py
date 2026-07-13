# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Provenance: map a displayed value back to the tool-written file + line.

LanEx computes no silicon results — every number it shows was parsed from a
file LibreLane (or the underlying tool) wrote into the run dir. These helpers
locate the exact file and line a value came from, so the UI can open the RAW
tool output with the source line highlighted and the user can verify the
display against the tool's own words, never against LanEx's.

Hard rules:
* Only files LibreLane/the tools wrote are referenced (``final/metrics.json``,
  ``resolved.json``, step reports) — never a LanEx-generated artifact.
* A value we cannot locate returns an honest ``{"ok": False, "reason": ...}``
  — never a guessed line.
* Pure + read-only: no side effects, no writes, safe on any run dir shape.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Metrics live in final/metrics.json on a completed run; some older/partial
# runs only have the run-root copy. Both are written by LibreLane itself.
_METRIC_FILES = ("final/metrics.json", "metrics.json")

# Reports can be large (a routing DRC report on a big design); reading a
# bounded prefix keeps the endpoint snappy and is honest — a needle past the
# cap reports "not found in the first N MiB", never a wrong line.
_MAX_BYTES = 16 * 1024 * 1024


def _read_lines(path: Path) -> Optional[list[str]]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(_MAX_BYTES).splitlines()
    except OSError:
        return None


def _find_json_key(lines: list[str], key: str) -> Optional[Tuple[int, str]]:
    """1-based line of the top-most occurrence of ``"key":`` in a JSON dump.

    LibreLane writes these files with ``json.dump(..., indent=...)`` — one key
    per line. A nested dict value could contain a same-named key at deeper
    indentation (e.g. a corner-wildcard map), so among all matches the LEAST
    indented one wins: that is the top-level variable/metric.
    """
    needle = f'"{key}":'
    best: Optional[Tuple[int, str]] = None
    best_indent = 1 << 30
    for i, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if not stripped.startswith(needle):
            continue
        indent = len(line) - len(stripped)
        if indent < best_indent:
            best, best_indent = (i, line.rstrip("\n")), indent
    return best


def metric_provenance(run_dir: Path, key: str) -> Dict[str, Any]:
    """Locate metric *key* in the run's LibreLane-written metrics.json."""
    if not key or "/" in key or "\\" in key:
        return {"ok": False, "reason": "invalid metric key"}
    for rel in _METRIC_FILES:
        path = Path(run_dir) / rel
        if not path.is_file():
            continue
        lines = _read_lines(path)
        if lines is None:
            return {"ok": False, "reason": f"could not read {rel}"}
        hit = _find_json_key(lines, key)
        if hit is None:
            return {"ok": False, "reason":
                    f"'{key}' is not in {rel} — the flow did not emit this "
                    "metric for this run.", "rel": rel}
        return {"ok": True, "rel": rel, "line": hit[0], "text": hit[1],
                "writer": "LibreLane (flow metrics)"}
    return {"ok": False, "reason":
            "no metrics.json in this run — the flow never reached the "
            "metrics-writing stage."}


def config_provenance(run_dir: Path, var: str) -> Dict[str, Any]:
    """Locate config *var* in the run's LibreLane-written resolved.json.

    resolved.json is the flow's OWN record of every variable value it actually
    used — the authoritative answer to "did my setting reach the flow?".
    """
    if not var or "/" in var or "\\" in var:
        return {"ok": False, "reason": "invalid variable name"}
    path = Path(run_dir) / "resolved.json"
    if not path.is_file():
        return {"ok": False, "reason":
                "no resolved.json in this run — the flow never resolved a "
                "config (it failed before configuration)."}
    lines = _read_lines(path)
    if lines is None:
        return {"ok": False, "reason": "could not read resolved.json"}
    hit = _find_json_key(lines, var)
    if hit is None:
        return {"ok": False, "reason":
                f"'{var}' is not in resolved.json — not a variable this "
                "flow/PDK resolves.", "rel": "resolved.json"}
    return {"ok": True, "rel": "resolved.json", "line": hit[0],
            "text": hit[1], "writer": "LibreLane (resolved configuration)"}


def base_config_provenance(design_dir: Path, var: str) -> Dict[str, Any]:
    """Locate *var* in the design's own config file (config.json/.yaml).

    This is the USER'S file (or the auto-generated one they accepted), not a
    LanEx artifact — the input-side counterpart: "this is the line your
    override supersedes". Absent var = honest absent (the value would come
    from a preset/override or the PDK default). An empty *var* locates the
    config file itself with no line — the Setup tab's "view your config file"
    (that is not an error, mirroring report_provenance's empty needle).
    """
    if "/" in var or "\\" in var:
        return {"ok": False, "reason": "invalid variable name"}
    for name in ("config.json", "config.yaml", "config.tcl"):
        path = Path(design_dir) / name
        if not path.is_file():
            continue
        if not var:
            return {"ok": True, "rel": name, "line": None, "text": "",
                    "writer": "your design config"}
        lines = _read_lines(path)
        if lines is None:
            return {"ok": False, "reason": f"could not read {name}"}
        if name.endswith(".json"):
            hit = _find_json_key(lines, var)
        else:
            # yaml `VAR:` at any indent; tcl `set ::env(VAR)` — first match.
            pats = (re.compile(r"^\s*" + re.escape(var) + r"\s*:"),
                    re.compile(r"::env\(" + re.escape(var) + r"\)"))
            hit = None
            for i, line in enumerate(lines, start=1):
                if any(p.search(line) for p in pats):
                    hit = (i, line.rstrip("\n"))
                    break
        if hit is None:
            return {"ok": False, "rel": name, "reason":
                    f"'{var}' is not set in {name} — without your override "
                    "the flow would use the PDK/flow default."}
        return {"ok": True, "rel": name, "line": hit[0], "text": hit[1],
                "writer": "your design config"}
    return {"ok": False, "reason": "no config file found in the design dir"}


def report_provenance(run_dir: Path, rel: str, needle: str) -> Dict[str, Any]:
    """Locate literal *needle*'s first occurrence in a run-relative report.

    The caller (route) has already traversal-validated *rel* against the run
    dir; this only reads and searches. An empty *needle* opens the file with
    no highlighted line (a plain raw view) — that is not an error.
    """
    path = (Path(run_dir) / rel)
    if not path.is_file():
        return {"ok": False, "reason": f"{rel} does not exist in this run"}
    if not needle:
        return {"ok": True, "rel": rel, "line": None, "text": "",
                "writer": "tool report"}
    lines = _read_lines(path)
    if lines is None:
        return {"ok": False, "reason": f"could not read {rel}"}
    for i, line in enumerate(lines, start=1):
        if needle in line:
            return {"ok": True, "rel": rel, "line": i,
                    "text": line.rstrip("\n"), "writer": "tool report"}
    return {"ok": False, "rel": rel, "reason":
            f"'{needle}' not found in {rel}"}
