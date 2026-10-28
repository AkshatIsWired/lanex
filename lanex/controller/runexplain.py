# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Why a run ended the way it did, in plain words, for the Flow page.

Reads only what LibreLane wrote: ``error.log`` and ``warning.log`` at the run
root, the stopped step's own log (for the line of the first error), and
``resolved.json`` for the value a fix would change. What an error means and
what to change come from the one knowledge base, ``problems.py``. The run's
outcome comes from the same flow state Verify uses (``verify._flow_state``),
so the two pages never disagree about whether a run halted or finished with
failing checks.

``kind``:
  ``clean``         reached the end, nothing raised
  ``checks-failed`` reached the end (``final/`` written), then LibreLane failed
                    the run on its deferred sign-off checks
  ``halted``        a step raised; nothing after it ran
  ``stopped``       the user stopped it (``gui-run.json`` ``outcome``)
  ``incomplete``    the folder ends mid-flow with no error: still running, or
                    the process was killed
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import flowstages, problems, verify

_CODE_RX = re.compile(r"\[(?:ERROR |WARNING )?([A-Z]{2,5}-\d{4})\]")
_ERR_RX = re.compile(r"\[ERROR(?: [A-Z]{2,5}-\d{4})?\]|^ERROR\b|\bError:")


def _read(p: Path, limit: int = 2_000_000) -> str:
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except Exception:
        return ""


def _lines(p: Path) -> List[str]:
    return [ln.rstrip() for ln in _read(p).splitlines() if ln.strip()]


def _step_log(run_dir: Path, step_dir: str) -> Optional[Path]:
    d = run_dir / step_dir
    if not d.is_dir():
        return None
    suffix = step_dir.split("-", 1)[1] if "-" in step_dir else step_dir
    log = d / (suffix + ".log")
    if log.is_file():
        return log
    logs = sorted(d.glob("*.log"))
    return logs[0] if logs else None


def _first_error(log: Optional[Path]) -> Optional[Dict[str, Any]]:
    """Line number (1-based) and text of the first error in a step log."""
    if log is None:
        return None
    for i, ln in enumerate(_read(log).splitlines(), 1):
        if _ERR_RX.search(ln):
            return {"line": i, "text": ln.strip()[:400]}
    return None


def _warnings(run_dir: Path, base_dir: Optional[Path]) -> Dict[str, Any]:
    lines = _lines(run_dir / "warning.log")
    base_codes = None
    if base_dir is not None:
        base_codes = {m.group(1) for ln in _lines(base_dir / "warning.log") for m in [_CODE_RX.search(ln)] if m}
    groups: Dict[str, Dict[str, Any]] = {}
    other = 0
    for ln in lines:
        m = _CODE_RX.search(ln)
        if not m:
            other += 1
            continue
        g = groups.setdefault(m.group(1), {"code": m.group(1), "count": 0, "sample": ln[:300]})
        g["count"] += 1
    # The full GPL-0302 text spans two lines in the step log; read it there.
    for code, g in groups.items():
        if code in problems.WARNING_NOTES:
            g["note"] = problems.WARNING_NOTES[code](_grep_step_logs(run_dir, code) or g["sample"])
        if base_codes is not None:
            g["new"] = code not in base_codes
    ordered = sorted(groups.values(), key=lambda g: (not g.get("note"), not g.get("new", False), -g["count"]))
    return {"total": len(lines), "by_code": ordered, "other": other,
            "compared_with": base_dir.name if base_dir is not None else None}


def _grep_step_logs(run_dir: Path, code: str) -> Optional[str]:
    try:
        for log in sorted(run_dir.glob("*/*.log")):
            text = _read(log, 4_000_000)
            i = text.find(code)
            if i >= 0:
                return text[i:i + 400]
    except Exception:
        pass
    return None


# A checker step that raised only says "N Lint errors found." and writes no
# log; what failed is in the tool step it checks. Each checker -> the check
# id problems.py explains, a title, and the tool step whose log has the lines.
_CHECKERS = {
    "Checker.LintErrors": ("lint_errors", "The RTL has lint errors", "Verilator.Lint"),
    "Checker.LintTimingConstructs": ("lint_timing_constructs", "The RTL has delays synthesis can't build", "Verilator.Lint"),
    "Checker.LintWarnings": ("lint_warnings", "The RTL has lint warnings, and this run fails on them", "Verilator.Lint"),
    "Checker.YosysUnmappedCells": ("unmapped", "Synthesis left cells it couldn't map", "Yosys.Synthesis"),
    "Checker.YosysSynthChecks": ("synth_check", "Synthesis found structural problems", "Yosys.Synthesis"),
    "Checker.NetlistAssignStatements": ("assign", "The netlist has assign statements", "Yosys.Synthesis"),
}
_VL_RX = re.compile(r"^%(Error|Warning)(?:-([A-Z0-9_]+))?: (.*)")
_YS_RX = re.compile(r"^\s*(?:Warning|ERROR|Error): (.*)")


def _is_step(s: Dict[str, Any], step_id: str) -> bool:
    """A step folder is *step_id*: by the id flow.log gave it, else by its
    folder name ("03-checker-linterrors" is Checker.LintErrors)."""
    if s.get("id"):
        return s["id"] == step_id
    return str(s.get("dir") or "").split("-", 1)[-1] == step_id.lower().replace(".", "-")


def _checker_of(step: Dict[str, Any]) -> Optional[tuple]:
    return next((v for k, v in _CHECKERS.items() if _is_step(step, k)), None)


def _checker_evidence(run: "verify._Run", tool_id: str, design_dir: Optional[Path]) -> Optional[Dict[str, Any]]:
    """The tool's own error lines behind a checker that raised: up to three,
    errors first, with paths relative to the design; and where the first one
    is in the tool step's log (``{lines, at}``)."""
    step = next((s for s in run.steps if _is_step(s, tool_id)), None)
    if step is None:
        return None
    log = _step_log(run.dir, step["dir"])
    if log is None:
        return None
    rx = _VL_RX if tool_id.startswith("Verilator") else _YS_RX
    hits = []
    for i, ln in enumerate(_read(log).splitlines(), 1):
        m = rx.match(ln)
        if not m or "Exiting due to" in ln:
            continue
        text = ln.strip()
        if design_dir is not None:
            text = text.replace(str(design_dir).rstrip("/") + "/", "")
        err = tool_id.startswith("Verilator") and m.group(1) == "Error" or ln.lstrip().upper().startswith("ERROR")
        hits.append((0 if err else 1, i, text[:400]))
    if not hits:
        return None
    hits.sort(key=lambda h: (h[0], h[1]))
    first = hits[0]
    return {"lines": [h[2] for h in hits[:3]],
            "at": {"path": step["dir"] + "/" + log.name, "line": first[1], "text": first[2], "step": tool_id}}


def _outcome(run_dir: Path) -> Optional[str]:
    try:
        doc = json.loads((run_dir / "gui-run.json").read_text(encoding="utf-8"))
        out = doc.get("outcome") if isinstance(doc, dict) else None
        return (out or {}).get("result") if isinstance(out, dict) else None
    except Exception:
        return None


def explain_run(run_dir: str | Path, base_dir: Optional[str | Path] = None) -> Dict[str, Any]:
    """Outcome, reason, fixes and warnings for one run (see module doc)."""
    run_dir = Path(run_dir)
    base = Path(base_dir) if base_dir else None
    run = verify._Run(run_dir)
    fs = verify._flow_state(run)
    cfg = run.cfg or {}
    outcome = _outcome(run_dir)
    state = fs.get("state")
    if state == "complete":
        kind = "clean"
    elif state in ("deferred_errors", "complete_with_errors"):
        kind = "checks-failed"
    elif outcome == "cancelled":
        kind = "stopped"
    elif state == "stopped" or fs.get("error_log"):
        kind = "halted"
    else:
        kind = "incomplete"
    step = fs.get("stopped_step") if kind in ("halted", "stopped") else None
    if kind == "incomplete" and fs.get("last_step"):
        step = fs["last_step"]
    out: Dict[str, Any] = {
        "tag": run_dir.name, "kind": kind, "state": state, "step": step,
        "stage": None, "errors": fs.get("error_log") or [],
        "raised_checkers": fs.get("raised_checkers") or [],
        "steps_done": fs.get("steps_done"), "steps_total": fs.get("steps_total"),
        "card": None, "at": None,
        "warnings": _warnings(run_dir, base if base and base.is_dir() else None),
    }
    if step:
        # Unlisted steps inherit the stage before them, so walk the run in order.
        names = [s.get("id") or s["dir"] for s in run.steps]
        stages = flowstages.stages_of(names)
        hit = next((i for i, s in enumerate(run.steps) if s["dir"] == step.get("dir")), None)
        out["stage"] = stages[hit] if hit is not None else flowstages.stages_of([step.get("id") or step.get("dir")])[0]
    if kind == "halted" and step:
        log = _step_log(run_dir, step["dir"])
        first = _first_error(log)
        if first and log is not None:
            out["at"] = {"path": step["dir"] + "/" + log.name, **first}
        text = "\n".join(out["errors"]) or (first or {}).get("text", "")
        card = problems.explain_error(text, cfg)
        ck = _checker_of(step)
        if ck and not card.get("title"):
            key, title, tool = ck
            card["title"] = title
            card["plain"] = problems._CHECK_PLAIN.get(key) or card.get("plain")
            if key in problems._CHECK_OPEN:
                label, go, why = problems._CHECK_OPEN[key]
                card["fixes"] = list(card.get("fixes") or []) + [problems._open(label, go, why)]
            dd = None
            try:
                dd = run_dir.parent.parent if run_dir.parent.name == "runs" else None
            except Exception:
                dd = None
            ev = _checker_evidence(run, tool, dd)
            if ev:
                card["evidence"] = ev["lines"]
                out["at"] = ev["at"]
        card["fixes"] = problems.finish(card.get("fixes", []), (cfg.get("meta") or {}).get("flow") or "Classic")
        out["card"] = card
    # A run resumed from another one: where it started, and what changed.
    out["branched_from"] = run.branch
    return out
