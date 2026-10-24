# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Why a run ended the way it did, in plain words, for the Flow page.

Reads only what LibreLane wrote: ``error.log`` and ``warning.log`` at the run
root, the stopped step's own log (for the line of the first error), and
``resolved.json`` for the value a fix would change. The run's outcome comes
from the same flow state Verify uses (``verify._flow_state``), so the two pages
never disagree about whether a run halted or finished with failing checks.

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
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import flowstages, history, verify

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


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _fmt(v: Any) -> str:
    if isinstance(v, (list, tuple)):
        return " ".join(_fmt(x) for x in v)
    f = _num(v)
    if f is not None and not isinstance(v, bool):
        return str(int(f)) if f == int(f) else ("%.2f" % f).rstrip("0").rstrip(".")
    return "" if v is None else str(v)


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


# ---------------------------------------------------------------- explanations
# Each takes the error text and the run's resolved config, and returns the
# card: a plain title, what happened with the log's own numbers, and fixes
# that name a variable, its value in this run and a value to try. Only codes
# checked against the OpenROAD that LibreLane 3.0.4 ships (dcf36133).

def _gpl_0301(msg: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    m = re.search(r"Utilization (\d+(?:\.\d+)?) ?%", msg)
    util = _num(m.group(1)) if m else None
    sizing = str(cfg.get("FP_SIZING") or "relative")
    need = ("The cells need %.0f %% of the core area, so they can't all be placed." % util) if util else \
        "The cells need more than the whole core area, so they can't all be placed."
    fixes: List[Dict[str, Any]] = []
    if sizing == "absolute":
        die = cfg.get("DIE_AREA")
        dims = [_num(x) for x in (die if isinstance(die, (list, tuple)) else str(die or "").split())]
        plain = need + " The die is fixed by DIE_AREA (%s µm), so LibreLane can't make room." % _fmt(die)
        fixes.append({"var": "FP_SIZING", "from": "absolute", "to": "relative",
                      "why": "LibreLane sizes the die from the cells' area and FP_CORE_UTIL (%s %%)." % _fmt(cfg.get("FP_CORE_UTIL") or 50)})
        if len(dims) == 4 and None not in dims and util:
            k = math.sqrt(util / 100.0 / 0.5)       # room for the cells at about 50 % of the core
            w, h = (dims[2] - dims[0]) * k, (dims[3] - dims[1]) * k
            to = "%s %s %s %s" % (_fmt(dims[0]), _fmt(dims[1]), _fmt(dims[0] + 5 * math.ceil(w / 5)),
                                  _fmt(dims[1] + 5 * math.ceil(h / 5)))
            fixes.append({"var": "DIE_AREA", "from": _fmt(die), "to": to,
                          "why": "A die big enough for these cells at about half the core."})
    else:
        core = _num(cfg.get("FP_CORE_UTIL"))
        plain = need + " FP_CORE_UTIL asks for a core %s %% full, which leaves no room for the tap cells and buffers placement adds." % _fmt(core)
        if core:
            to = max(20, min(50, int(5 * math.floor(core * 100.0 / max(util or 100.0, 100.0) * 0.85 / 5))))
            fixes.append({"var": "FP_CORE_UTIL", "from": _fmt(core), "to": str(to),
                          "why": "A bigger core: room for the cells and what placement adds."})
    return {"title": "Placement ran out of room", "plain": plain, "fixes": fixes, "learn": ["utilization", "core"]}


def _dpl_0036(msg: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    fixes: List[Dict[str, Any]] = []
    core = _num(cfg.get("FP_CORE_UTIL"))
    if core and core > 25:
        fixes.append({"var": "FP_CORE_UTIL", "from": _fmt(core), "to": str(int(max(20, core - 10))),
                      "why": "More room around the cells the placer could not fit."})
    dens = _num(cfg.get("PL_TARGET_DENSITY_PCT"))
    if dens and dens > 30:
        fixes.append({"var": "PL_TARGET_DENSITY_PCT", "from": _fmt(dens), "to": str(int(max(20, dens - 10))),
                      "why": "Spread the cells out before they are legalised."})
    return {"title": "Detailed placement couldn't fit every cell",
            "plain": "Some cells have no legal spot in a row: the log lists them just above the error. "
                     "Usually the core is too full in that area; look at where they sit in Layout.",
            "fixes": fixes, "learn": ["utilization"]}


def _grt_0116(msg: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    fixes: List[Dict[str, Any]] = []
    core = _num(cfg.get("FP_CORE_UTIL"))
    if core and core > 25:
        fixes.append({"var": "FP_CORE_UTIL", "from": _fmt(core), "to": str(int(max(20, core - 10))),
                      "why": "A bigger core leaves more room for wires."})
    return {"title": "Routing is too congested",
            "plain": "Global routing found more wires than the metal layers have room for in some places.",
            "fixes": fixes, "learn": ["congestion"]}


def _pdn_0185(msg: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {"title": "The die is too small for the power grid",
            "plain": "The power straps' pitch is wider than the core, so the grid can't be built. "
                     "Make the die bigger, or ask for a finer grid.",
            "fixes": [], "learn": ["pdn"]}


_EXPLAIN = {"GPL-0301": _gpl_0301, "DPL-0036": _dpl_0036, "GRT-0116": _grt_0116, "PDN-0185": _pdn_0185}

# Warnings worth a sentence: what happened, with the log's numbers.
def _note_gpl_0302(text: str) -> Optional[str]:
    m = re.search(r"Target density (\d+(?:\.\d+)?).*?uniform density (\d+(?:\.\d+)?)", text, re.S)
    if not m:
        m2 = re.search(r"Target density (\d+(?:\.\d+)?)", text)
        return ("PL_TARGET_DENSITY_PCT asked for %.0f %%, which is below what this design can reach, so "
                "OpenROAD raised it. Remove the setting, or raise it." % (float(m2.group(1)) * 100)) if m2 else None
    a, b = float(m.group(1)) * 100, float(m.group(2)) * 100
    return ("PL_TARGET_DENSITY_PCT asked for %.0f %%, below what this design can reach, so OpenROAD used "
            "%.0f %% instead. Remove the setting, or set it to %d or more." % (a, b, math.ceil(b)))


_NOTES = {"GPL-0302": _note_gpl_0302}


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
        if code in _NOTES:
            g["note"] = _NOTES[code](_grep_step_logs(run_dir, code) or g["sample"])
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
        m = _CODE_RX.search(text)
        code = m.group(1) if m else None
        fn = _EXPLAIN.get(code or "")
        card = fn(text, cfg) if fn else None
        if card is None:
            card = {"title": None, "plain": None, "fixes": [], "learn": []}
        card["code"] = code
        for f in card.get("fixes", []):
            f.setdefault("label", f["var"])
        card["fixes"] = _valid(card.get("fixes", []))
        out["card"] = card
    return out


def _valid(fixes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Only fixes whose variable this LibreLane knows (as alerts does)."""
    try:
        from .alerts import _known_var_names
        names = _known_var_names()
    except Exception:
        names = set()
    if not names:          # no registry (tests, local mode without LibreLane): keep them
        return fixes
    return [f for f in fixes if f.get("var") in names]
