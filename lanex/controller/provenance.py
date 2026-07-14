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
            # yaml `VAR:` at any indent; tcl `set ::env(VAR)`. Among several
            # matches the LEAST indented (top-level) wins — the same rule as
            # the JSON path and config_var_lines, so the "your config" chip
            # and this open-at-line answer always name the SAME line.
            pats = (re.compile(r"^\s*" + re.escape(var) + r"\s*:"),
                    re.compile(r"::env\(" + re.escape(var) + r"\)"))
            hit = None
            best_indent = 1 << 30
            for i, line in enumerate(lines, start=1):
                if any(p.search(line) for p in pats):
                    indent = len(line) - len(line.lstrip())
                    if indent < best_indent:
                        hit, best_indent = (i, line.rstrip("\n")), indent
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


# ---------------------------------------------------------------------------
# Bulk input-side map: every variable the design's config file sets.
# ---------------------------------------------------------------------------

# A LibreLane variable name as it appears as a config key. Scope sections
# (pdk::sky130*, scl::sky130_fd_sc_hs) are tracked separately — a scoped value
# only applies when the run's PDK/SCL matches, and LanEx must NEVER claim it
# does (that would re-implement LibreLane's config resolution and risk showing
# a value the flow would not use). Scoped entries are therefore LABELLED, not
# resolved.
_VAR_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_JSON_KEY_RE = re.compile(r'^(\s*)"([^"]+)"\s*:(.*)$')
_YAML_KEY_RE = re.compile(r"^(\s*)([A-Za-z_][\w:*.\-]*)\s*:(.*)$")
_TCL_SET_RE = re.compile(r"^\s*set\s+::env\((\w+)\)\s+(.*)$")


def _frag_display(frag: str) -> str:
    """The value exactly as written in the file, trimmed for a chip."""
    s = frag.strip().rstrip(",").strip()
    if len(s) > 60:
        s = s[:57] + "…"
    return s


def config_var_lines(design_dir: Path) -> Dict[str, Any]:
    """Map every variable the design's own config file sets to its line.

    Returns ``{ok, rel, vars: {VAR: {line, text, value, scoped, scope}}}``.
    ``value`` is the raw fragment AS WRITTEN on that line (never normalized —
    the file is the truth); ``scoped`` marks entries inside a ``pdk::``/
    ``scl::`` section, whose applicability depends on the run's PDK — the UI
    must present those as conditional. When a variable appears both at top
    level and inside a scope, the top-level line wins (it is unconditionally
    read by every flow); extra occurrences are counted in ``others``.
    Line-scan only — same discipline as the rest of this module: report what
    the file says, never resolve what the flow would compute.
    """
    for name in ("config.json", "config.yaml", "config.tcl"):
        path = Path(design_dir) / name
        if not path.is_file():
            continue
        lines = _read_lines(path)
        if lines is None:
            return {"ok": False, "reason": f"could not read {name}"}
        out: Dict[str, Dict[str, Any]] = {}
        # innermost-first stack of (indent, scope_key) for pdk::/scl:: blocks
        scopes: list[Tuple[int, str]] = []

        def _record(var: str, i: int, line: str, frag: str) -> None:
            entry = {
                "line": i, "text": line.rstrip("\n"),
                "value": _frag_display(frag),
                "scoped": bool(scopes),
                "scope": scopes[-1][1] if scopes else None,
            }
            prev = out.get(var)
            if prev is None:
                entry["others"] = 0
                out[var] = entry
            elif prev["scoped"] and not entry["scoped"]:
                # top-level beats scoped: it applies to every run
                entry["others"] = prev["others"] + 1
                out[var] = entry
            else:
                prev["others"] += 1

        if name == "config.tcl":
            for i, line in enumerate(lines, start=1):
                m = _TCL_SET_RE.match(line)
                if m and _VAR_RE.match(m.group(1)):
                    _record(m.group(1), i, line, m.group(2))
        else:
            key_re = _JSON_KEY_RE if name.endswith(".json") else _YAML_KEY_RE
            for i, line in enumerate(lines, start=1):
                m = key_re.match(line)
                if not m:
                    continue
                indent, key, rest = len(m.group(1)), m.group(2), m.group(3)
                while scopes and scopes[-1][0] >= indent:
                    scopes.pop()
                if key.startswith(("pdk::", "scl::")):
                    scopes.append((indent, key))
                    continue
                if _VAR_RE.match(key):
                    _record(key, i, line, rest)
        return {"ok": True, "rel": name, "vars": out}
    return {"ok": False, "reason": "no config file found in the design dir"}


# ---------------------------------------------------------------------------
# Post-run: every resolved value + where it came from.
# ---------------------------------------------------------------------------

def _scan_top_level_json_lines(lines: list) -> Dict[str, Tuple[int, str]]:
    """One pass over a json.dump file: {key: (line, text)} for the LEAST
    indented occurrence of each key (same top-level rule as _find_json_key)."""
    out: Dict[str, Tuple[int, str, int]] = {}
    for i, line in enumerate(lines, start=1):
        m = _JSON_KEY_RE.match(line)
        if not m:
            continue
        indent, key = len(m.group(1)), m.group(2)
        prev = out.get(key)
        if prev is None or indent < prev[2]:
            out[key] = (i, line.rstrip("\n"), indent)
    return {k: (v[0], v[1]) for k, v in out.items()}


def _display_value(v: Any) -> str:
    """A resolved value for a table cell — compact, trimmed, never mangled
    beyond truncation (the full line is one click away via its line number)."""
    import json as _json
    try:
        s = v if isinstance(v, str) else _json.dumps(v)
    except Exception:
        s = str(v)
    s = " ".join(s.split())
    if len(s) > 100:
        s = s[:97] + "…"
    return s


def resolved_settings(run_dir: Path, design_dir: Optional[Path]) -> Dict[str, Any]:
    """Every variable in the run's resolved.json + an honest source label.

    The VALUE column is LibreLane's own record (resolved.json), never an
    inference. The SOURCE column is attribution by key origin — which input
    carried the variable into the run:
      * ``override``  — the key is in gui-run.json's recorded overrides (the
        exact set this GUI sent for this run);
      * ``picker``    — PDK / STD_CELL_LIBRARY chosen in Setup (flow options);
      * ``config``    — the design's config file sets the key (line included;
        scoped sections labelled — a scoped line only applied if the run's
        PDK/SCL matched it);
      * ``default``   — none of the above: LibreLane's or the PDK's own value.
    Attribution is NEVER by value comparison: LibreLane expands what it reads
    (``dir::`` globs, expressions, units), so the resolved value routinely
    differs textually from the config line that set it. Runs without
    gui-run.json (started outside this GUI) degrade honestly: overrides
    unknown, stated in ``note``.
    """
    import json as _json
    rpath = Path(run_dir) / "resolved.json"
    if not rpath.is_file():
        return {"ok": False, "reason":
                "no resolved.json in this run — the flow never resolved a "
                "config (it failed before configuration)."}
    lines = _read_lines(rpath)
    if lines is None:
        return {"ok": False, "reason": "could not read resolved.json"}
    raw = "\n".join(lines)
    tokened = re.sub(r'([:\[,]\s*)(-?Infinity|NaN)(\s*[,}\]])', r'\1"\2"\3', raw)
    try:
        resolved = _json.loads(tokened)
    except Exception:
        return {"ok": False, "reason": "resolved.json is not parseable JSON"}
    if not isinstance(resolved, dict):
        return {"ok": False, "reason": "resolved.json is not an object"}
    linemap = _scan_top_level_json_lines(lines)

    gui_overrides: Optional[Dict[str, Any]] = None
    gui_pdk = gui_scl = None
    gpath = Path(run_dir) / "gui-run.json"
    if gpath.is_file():
        try:
            gui = _json.loads(gpath.read_text(encoding="utf-8"))
            gui_overrides = dict(gui.get("overrides") or {})
            gui_pdk, gui_scl = gui.get("pdk"), gui.get("scl")
        except Exception:
            gui_overrides = None

    cfg = config_var_lines(design_dir) if design_dir else {"ok": False}
    cfg_vars = cfg.get("vars") or {}
    cfg_rel = cfg.get("rel")

    rows = []
    for key in sorted(resolved):
        lm = linemap.get(key)
        row: Dict[str, Any] = {
            "name": key,
            "value": _display_value(resolved[key]),
            "line": lm[0] if lm else None,
        }
        c = cfg_vars.get(key)
        if gui_overrides is not None and key in gui_overrides:
            row["source"] = "override"
        elif key == "PDK" and gui_pdk:
            row["source"] = "picker"
        elif key == "STD_CELL_LIBRARY" and gui_scl:
            row["source"] = "picker"
        elif c:
            row["source"] = "config"
            row["config_line"] = c["line"]
            if c["scoped"]:
                row["scoped"] = True
                row["scope"] = c["scope"]
        else:
            row["source"] = "default"
        rows.append(row)
    out: Dict[str, Any] = {"ok": True, "rows": rows, "config_rel": cfg_rel,
                           "gui_meta": gui_overrides is not None}
    if gui_overrides is None:
        out["note"] = ("this run has no gui-run.json (started outside this GUI, "
                       "or an old run) — override attribution is unavailable; "
                       "config/default attribution still applies.")
    return out
