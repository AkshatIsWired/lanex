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
        card["fixes"] = problems.finish(card.get("fixes", []), (cfg.get("meta") or {}).get("flow") or "Classic")
        out["card"] = card
    # A run resumed from another one: where it started, and what changed.
    out["branched_from"] = run.branch
    return out
