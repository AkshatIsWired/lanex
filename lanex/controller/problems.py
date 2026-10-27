# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""LanEx's one knowledge base: what went wrong in a run, in plain words, and
what to change.

Every problem has one shape, whatever found it (workflow spec 5.6)::

    {id, severity: fail|warn, kind: halted|check, title, plain,
     where: {stage, step, check}, evidence: [lines], diag: {...},
     fixes: [{kind: "setting", var, from, to, why, resume}
             | {kind: "open", label, go, why}],
     notes: [sentences], learn: [glossary keys]}

Sources: a step that raised (an OpenROAD error code), and every sign-off check
that failed or warned (``verify.py``), with timing read from each of the run's
timing analyses (``timing.py``) and DRC grouped by rule and by place.

Rules the fixes follow (each from the spec and checked against LibreLane
3.0.4): a setting is only offered when this LibreLane knows it; hold problems
never offer a slower clock; timing leads with where it first failed, and a
path that already fails before placement gets no placement setting; I/O
constraints are named before the logic; ``resume`` is the first step that
reads the variable (``varstage.py``). Proposed values are a starting point the
fix sheet lets you change. Nothing here computes a silicon number: every
value comes from the run's own files.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_CODE_RX = re.compile(r"\[(?:ERROR |WARNING )?([A-Z]{2,5}-\d{4})\]")


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def fmt(v: Any) -> str:
    if isinstance(v, (list, tuple)):
        return " ".join(fmt(x) for x in v)
    f = _num(v)
    if f is not None and not isinstance(v, bool):
        return str(int(f)) if f == int(f) else ("%.3f" % f).rstrip("0").rstrip(".")
    if isinstance(v, bool):
        return "true" if v else "false"
    return "" if v is None else str(v)


def _setting(var: str, frm: Any, to: Any, why: str, label: str = "") -> Dict[str, Any]:
    return {"kind": "setting", "var": var, "from": fmt(frm), "to": fmt(to), "why": why, "label": label}


def _open(label: str, go: Dict[str, Any], why: str = "") -> Dict[str, Any]:
    return {"kind": "open", "label": label, "go": go, "why": why}


def _ns(v: Optional[float]) -> str:
    return "—" if v is None else ("%+.2f ns" % v).replace("-", "−")


def _round_up(v: float, step: float) -> float:
    return round(math.ceil(v / step - 1e-9) * step, 6)


# ---------------------------------------------------------------- a step raised
# One function per error code, checked against the OpenROAD LibreLane 3.0.4
# ships (dcf36133). Each returns the card's title, what happened with the
# log's own numbers, and the fixes.

def _gpl_0301(msg: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    m = re.search(r"Utilization (\d+(?:\.\d+)?) ?%", msg)
    util = _num(m.group(1)) if m else None
    sizing = str(cfg.get("FP_SIZING") or "relative")
    pad = _num(cfg.get("GPL_CELL_PADDING")) or 0
    need = ("The cells need %.0f %% of the core area, so they can't all be placed." % util) if util else \
        "The cells need more than the whole core area, so they can't all be placed."
    fixes: List[Dict[str, Any]] = []
    plain = need
    if pad > 0:
        # Global placement pads each cell by GPL_CELL_PADDING sites and counts
        # the padding as area (an OpenROAD maintainer, OpenROAD issue #4318).
        plain += (" Global placement counts each cell %s sites wider (GPL_CELL_PADDING), and the padding "
                  "counts as area." % fmt(pad))
        fixes.append(_setting("GPL_CELL_PADDING", pad, 0,
                              "No padding at all. Padding gives the router room, so add some back if routing "
                              "struggles.", "Stop padding the cells"))
    if sizing == "absolute":
        die = cfg.get("DIE_AREA")
        dims = [_num(x) for x in (die if isinstance(die, (list, tuple)) else str(die or "").split())]
        plain += " The die is fixed by DIE_AREA (%s µm), so LibreLane can't make room." % fmt(die)
        fixes.append(_setting("FP_SIZING", "absolute", "relative",
                              "LibreLane sizes the die from the cells' area and FP_CORE_UTIL (%s %%)."
                              % fmt(cfg.get("FP_CORE_UTIL") or 50), "Let LibreLane size the die"))
        if len(dims) == 4 and None not in dims and util:
            k = math.sqrt(util / 100.0 / 0.5)       # room for the cells at about half the core
            w, h = (dims[2] - dims[0]) * k, (dims[3] - dims[1]) * k
            to = "%s %s %s %s" % (fmt(dims[0]), fmt(dims[1]), fmt(dims[0] + 5 * math.ceil(w / 5)),
                                  fmt(dims[1] + 5 * math.ceil(h / 5)))
            fixes.append(_setting("DIE_AREA", die, to, "A die big enough for these cells at about half the core.",
                                  "Make the die bigger"))
    else:
        core = _num(cfg.get("FP_CORE_UTIL"))
        if pad <= 0:
            plain += (" FP_CORE_UTIL asks for a core %s %% full, which leaves no room for the tap cells and "
                      "buffers placement adds." % fmt(core))
        if core:
            to = max(20, min(50, int(5 * math.floor(core * 100.0 / max(util or 100.0, 100.0) * 0.85 / 5))))
            fixes.append(_setting("FP_CORE_UTIL", core, to, "A bigger core: room for the cells and what placement adds.",
                                  "Make the core bigger"))
    return {"title": "Placement ran out of room", "plain": plain, "fixes": fixes, "learn": ["utilization", "core"]}


def _dpl_0036(msg: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    fixes: List[Dict[str, Any]] = []
    core = _num(cfg.get("FP_CORE_UTIL"))
    if core and core > 25:
        fixes.append(_setting("FP_CORE_UTIL", core, int(max(20, core - 10)),
                              "More room around the cells the placer could not fit.", "Make the core bigger"))
    dens = _num(cfg.get("PL_TARGET_DENSITY_PCT"))
    if dens and dens > 30:
        fixes.append(_setting("PL_TARGET_DENSITY_PCT", dens, int(max(20, dens - 10)),
                              "Spread the cells out before they are legalised.", "Spread the cells"))
    return {"title": "Detailed placement couldn't fit every cell",
            "plain": "Some cells have no legal spot in a row: the log lists them just above the error. "
                     "Usually the core is too full in that area; look at where they sit in Layout.",
            "fixes": fixes, "learn": ["utilization"]}


def _grt_0116(msg: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    fixes: List[Dict[str, Any]] = []
    core = _num(cfg.get("FP_CORE_UTIL"))
    if core and core > 25:
        fixes.append(_setting("FP_CORE_UTIL", core, int(max(20, core - 10)),
                              "A bigger core leaves more room for wires.", "Make the core bigger"))
    return {"title": "Routing is too congested",
            "plain": "Global routing found more wires than the metal layers have room for in some places.",
            "fixes": fixes, "learn": ["congestion"]}


def _pdn_0185(msg: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    fixes: List[Dict[str, Any]] = []
    core = _num(cfg.get("FP_CORE_UTIL"))
    if str(cfg.get("FP_SIZING") or "relative") == "relative" and core and core > 25:
        fixes.append(_setting("FP_CORE_UTIL", core, int(max(20, core - 15)),
                              "A bigger core has room for the power straps.", "Make the core bigger"))
    return {"title": "The die is too small for the power grid",
            "plain": "The power straps' pitch is wider than the core, so the grid can't be built. "
                     "Make the die bigger, or ask for a finer grid (PDN_VPITCH, PDN_HPITCH).",
            "fixes": fixes, "learn": ["pdn"]}


_EXPLAIN = {"GPL-0301": _gpl_0301, "DPL-0036": _dpl_0036, "GRT-0116": _grt_0116, "PDN-0185": _pdn_0185}

# A run that never got going: precise phrases only, so the advice never fires
# on the wrong error.
_ENV = [
    (("cannot connect to the docker daemon", "is the docker daemon running", "cannot connect to podman",
      "error during connect"),
     {"title": "The container engine isn't running",
      "plain": "Container mode needs Docker or Podman running. Start it (or switch the engine to Local tools in the "
               "Run menu), then run again."}),
    (("--dockerized is not supported on windows",),
     {"title": "Containers need WSL on Windows",
      "plain": "LibreLane's container mode needs a Linux container engine; run LanEx inside its WSL appliance."}),
]
_LOCAL_TOOLS = ("yosys", "openroad", "magic", "klayout", "netgen", "verilator")
_MISSING_RX = re.compile(r"\b(" + "|".join(_LOCAL_TOOLS) + r")\b[^\n]{0,40}(command not found|no such file or directory|not found)",
                         re.I)


def explain_error(text: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """The failure card for a step that raised: ``{code, title, plain, fixes,
    learn}`` (title None when LanEx has nothing to add to the tool's words)."""
    m = _CODE_RX.search(text or "")
    code = m.group(1) if m else None
    fn = _EXPLAIN.get(code or "")
    card = fn(text, cfg) if fn else None
    if card is None:
        low = (text or "").lower()
        hit = next((c for phrases, c in _ENV if any(p in low for p in phrases)), None)
        tool = _MISSING_RX.search(text or "") if hit is None else None
        if tool:
            # Local tools mode runs the tools on this machine's PATH.
            hit = {"title": tool.group(1).capitalize() + " isn't installed here",
                   "plain": "Local tools mode runs the tools installed on this machine, and " + tool.group(1) +
                            " isn't on the PATH. Switch the engine to Container in the Run menu (the LibreLane image has "
                            "every tool at the matching version), or install it from Tools."}
        card = dict(hit, fixes=[], learn=[]) if hit else {"title": None, "plain": None, "fixes": [], "learn": []}
    card["code"] = code
    return card


# Warnings worth a sentence: what happened, with the log's numbers.
def _note_gpl_0302(text: str) -> Optional[str]:
    m = re.search(r"Target density (\d+(?:\.\d+)?).*?uniform density (\d+(?:\.\d+)?)", text, re.S)
    if not m:
        m2 = re.search(r"Target density (\d+(?:\.\d+)?)", text)
        return ("The placement density (PL_TARGET_DENSITY_PCT, %.0f %%) is below what this design can "
                "reach, so OpenROAD raised it. Harmless; set PL_TARGET_DENSITY_PCT higher to silence it."
                % (float(m2.group(1)) * 100)) if m2 else None
    # Often LibreLane's own default (a small design's first run), so it never
    # says "your setting" and only says how to make it go away.
    a, b = float(m.group(1)) * 100, float(m.group(2)) * 100
    return ("The placement density (PL_TARGET_DENSITY_PCT, %.0f %%) is below what this design can reach, "
            "so OpenROAD used %.0f %% instead. Harmless; set it to %d or more to silence this."
            % (a, b, math.ceil(b)))


WARNING_NOTES = {"GPL-0302": _note_gpl_0302}


# ---------------------------------------------------------------- timing
def _pvt(corner: str) -> str:
    """``max_ss_100C_1v60`` -> ``ss_100C_1v60``: the process, temperature and
    voltage, without the wire corner (before placement there are no wires)."""
    return re.sub(r"^(nom|min|max)_", "", corner or "")


def _io_paths(kinds: Dict[str, int]) -> int:
    return sum(n for k, n in kinds.items() if k != "reg-reg")


def _kinds_text(kinds: Dict[str, int]) -> str:
    words = {"reg-reg": "register to register", "in-reg": "from an input", "reg-out": "to an output",
             "in-out": "input straight to an output"}
    order = ["reg-reg", "in-reg", "reg-out", "in-out"]
    return ", ".join("%d %s" % (kinds[k], words[k]) for k in order if kinds.get(k))


def _sdc_reads(cfg: Dict[str, Any], var: str) -> bool:
    """Whether the run's SDC reads *var*. LibreLane's own (scripts/base.sdc)
    spends IO_DELAY_CONSTRAINT on each input and output and puts
    OUTPUT_CAP_LOAD on every output; a design's own SDC may or may not."""
    sdc = cfg.get("PNR_SDC_FILE")
    if not sdc:
        return True
    try:
        return var in Path(str(sdc)).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def _relax_clock(period: float, wns: float, io_pct: float, through_io: bool) -> float:
    """A clock period the worst path would meet: on an input or output path
    the I/O delay grows with the period too (IO_DELAY_CONSTRAINT %)."""
    slope = (1 - io_pct / 100.0) if through_io else 1.0
    need = period + abs(wns) / max(0.2, slope)
    return _round_up(need, 0.1 if need < 20 else 1.0)


def timing_problems(run_dir: Path, rep: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Setup and hold, diagnosed from every timing analysis of the run."""
    from . import timing
    by = {c["id"]: c for c in rep.get("checks") or []}
    cfg = _cfg(run_dir)
    hist = timing.sta_history(run_dir)
    if not hist:
        return []
    final = next((h for h in reversed(hist) if h["signoff"]), None) or hist[-1]
    out = []
    s = _setup(run_dir, cfg, hist, final, by.get("setup"))
    if s:
        out.append(s)
    h = _hold(run_dir, cfg, hist, final, by.get("hold"))
    if h:
        out.append(h)
    return out


def _worst(corners: Dict[str, Any], key: str) -> Optional[str]:
    bad = [(v[key], c) for c, v in corners.items() if _num(v.get(key)) is not None and v[key] < 0]
    return min(bad)[1] if bad else None


def _setup(run_dir: Path, cfg: Dict[str, Any], hist: List[Dict[str, Any]], final: Dict[str, Any],
           check: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    from . import timing
    wc = _worst(final["corners"], "setup_ws")
    if wc is None or not check or check.get("status") not in ("fail", "warn"):
        return None
    w = final["corners"][wc]
    failing = sorted(c for c, v in final["corners"].items() if _num(v.get("setup_ws")) is not None and v["setup_ws"] < 0)
    passing = [c for c in final["corners"] if c not in failing]
    period = _num(cfg.get("CLOCK_PERIOD"))
    io_pct = _num(cfg.get("IO_DELAY_CONSTRAINT")) or 20.0
    kinds = w["kinds"].get("setup") or {}
    # Where this corner first failed: the first analysis that timed it.
    first = None
    for h in hist:
        v = next((x for c, x in h["corners"].items() if _pvt(c) == _pvt(wc)), None)
        if v and _num(v.get("setup_ws")) is not None and v["setup_ws"] < 0:
            first = (h, v, next(c for c in h["corners"] if _pvt(c) == _pvt(wc)))
            break
    before_pnr = bool(first and first[0]["ideal_clocks"])
    first_kinds = (first[1]["kinds"].get("setup") or {}) if first else {}
    # Each kind of path failing at sign-off, and whether it already failed
    # before placement (ideal clocks, no wires): a path that fails there is
    # the logic or the constraints, never placement.
    pre_k = first_kinds if before_pnr else {}
    io_n, rr_n = _io_paths(kinds), kinds.get("reg-reg", 0)
    if not kinds and before_pnr:                  # no violator list: one group
        io_n, rr_n = _io_paths(pre_k), pre_k.get("reg-reg", 0) or (0 if _io_paths(pre_k) else 1)
    early_io = bool(io_n and _io_paths(pre_k))
    early_rr = bool(rr_n and pre_k.get("reg-reg"))
    late = (io_n and not early_io) or (rr_n and not early_rr)
    # The first analysis after placement that timed this corner and failed.
    later = next((h for h in hist if not h["ideal_clocks"] and any(
        _pvt(c) == _pvt(wc) and _num(x.get("setup_ws")) is not None and x["setup_ws"] < 0 for c, x in h["corners"].items())), None)
    late_when = later["when"] if later else "after routing"
    untimed = later is not None and later["signoff"] and _pvt(wc) != _pvt(str(cfg.get("DEFAULT_CORNER") or ""))
    path = timing.worst_setup_path(run_dir, final["path"], wc)
    first_path = timing.worst_setup_path(run_dir, first[0]["path"], first[2]) if before_pnr else None
    budget = (path or {}).get("budget") or {}
    gating = bool(check and check.get("status") == "fail")
    sign = "after routing" if final["signoff"] else "in the last timing analysis (" + final["when"] + ", an estimate)"
    pre_txt = ("(%s, %d endpoints, ideal clocks and no wires)" % (_ns(first[1]["setup_ws"]), first[1].get("setup_vio") or 0)
               if before_pnr else "")

    leads = []
    if early_io:
        leads.append("Paths from inputs and to outputs already failed before placement %s: check the I/O "
                     "constraint first; placement can't help them." % pre_txt)
    if early_rr:
        leads.append("Register-to-register paths already failed before placement %s: too much logic between "
                     "registers for this clock (logic depth). Placement and routing settings can't fix that." % pre_txt)
    if late:
        if rr_n and not early_rr and (early_io or early_rr):
            what = ("A register-to-register path is the worst for %d endpoint%s %s and for none before placement"
                    % (rr_n, "" if rr_n == 1 else "s", late_when))
        else:
            what = "It passed before placement and fails %s" % late_when
        leads.append("%s: wires, clock skew or fanout, a physical problem.%s"
                     % (what, " (LibreLane times this corner only before placement and after routing.)" if untimed else ""))
    if early_io and late and not early_rr:
        title = "Setup: the I/O paths fail from the start, register paths " + late_when
    elif (early_io or early_rr) and not late:
        title = ("Setup fails before placement, on the input and output paths" if early_io and not early_rr
                 else "Setup fails before placement: too much logic for this clock")
    elif late:
        title = "Setup fails only " + late_when + ": a physical problem"
    else:
        title = "Setup fails in the slow corners" if passing else "Setup fails"
    plain = ("Worst slack %s in %s (%s): %d endpoints miss the clock there, %s short in all (TNS). "
             % (_ns(w["setup_ws"]), wc, sign, w.get("setup_vio") or 0,
                _ns(w.get("setup_tns")).replace("−", "") if _num(w.get("setup_tns")) is not None else "—")) + " ".join(leads)
    if passing and not gating:
        plain += " The corners LibreLane fails a run on pass, so this is a warning."
    evidence = []
    if kinds:
        evidence.append("Failing at sign-off in %s: %s." % (wc, _kinds_text(kinds)))
    if first_kinds and before_pnr:
        evidence.append("Failing before placement in %s: %s." % (first[2], _kinds_text(first_kinds)))

    fixes: List[Dict[str, Any]] = []
    through_io = budget.get("start") == "in" or budget.get("end") == "out"
    if period:
        to = _relax_clock(period, w["setup_ws"], io_pct, through_io)
        fixes.append(_setting("CLOCK_PERIOD", period, to,
                              "The direct fix: %s ns is about %.0f MHz. The worst path needs about %.2f ns more%s."
                              % (fmt(to), 1000.0 / to, abs(w["setup_ws"]),
                                 ", and the I/O delays grow with the clock" if through_io else ""),
                              "Slow the clock"))
    if (early_io or (through_io and io_n >= max(1, (io_n + rr_n) // 2))) and _sdc_reads(cfg, "IO_DELAY_CONSTRAINT"):
        to = max(5, int(io_pct // 2))
        fixes.append(_setting("IO_DELAY_CONSTRAINT", io_pct, to,
                              "LibreLane's SDC gives %s %% of the clock to the world outside the chip on every input and "
                              "output. Lower it only if your inputs really arrive that early." % fmt(io_pct),
                              "Check the I/O constraint"))
    load = _num(cfg.get("OUTPUT_CAP_LOAD")) if _sdc_reads(cfg, "OUTPUT_CAP_LOAD") else None
    if load and budget.get("end") == "out" and kinds.get("reg-out", 0) + kinds.get("in-out", 0) > 0:
        fixes.append(_setting("OUTPUT_CAP_LOAD", load, round(load / 2, 3),
                              "The SDC puts %s fF on every output pin, and the worst path ends at one: the cell driving "
                              "the pin is slower the bigger that load. Lower it only to what the pin really drives." % fmt(load),
                              "Check the output load"))
    if early_rr and str(cfg.get("SYNTH_STRATEGY") or "").startswith("AREA"):
        fixes.append(_setting("SYNTH_STRATEGY", cfg.get("SYNTH_STRATEGY"), "DELAY 0",
                              "Synthesis that favours speed over area. LibreLane: there is no way to know which "
                              "strategy is best before trying them.", "Synthesise for speed"))
    if late:
        if cfg.get("PL_TIMING_DRIVEN") is False:
            fixes.append(_setting("PL_TIMING_DRIVEN", False, True,
                                  "Placement that keeps the slow paths' cells close (off by default).",
                                  "Timing-driven placement"))
        if cfg.get("RUN_POST_GRT_RESIZER_TIMING") is False:
            fixes.append(_setting("RUN_POST_GRT_RESIZER_TIMING", False, True,
                                  "A second timing repair with the real routing estimates (off by default).",
                                  "Repair timing after routing too"))
        if abs(w["setup_ws"]) <= 0.1 and _num(cfg.get("PL_RESIZER_SETUP_SLACK_MARGIN")) is not None:
            m = _num(cfg.get("PL_RESIZER_SETUP_SLACK_MARGIN"))
            fixes.append(_setting("PL_RESIZER_SETUP_SLACK_MARGIN", m, round(m + 0.1, 3),
                                  "A small miss: repair aims a little past zero slack.", "Repair with more margin"))
    start = (path or {}).get("startpoint") if budget.get("start") == "reg" else None
    fixes.append(_open("Show the worst paths", {"tab": "analytics", "section": "an-timing"},
                       "Every failing path, worst first, with its cells."))
    notes = []
    if (early_io or early_rr) and late:
        notes.append("Placement settings are offered only for the paths that fail after routing. The ones that "
                     "fail before placement have no wires yet to shorten, so no placement or density setting can help them.")
    elif early_io or early_rr:
        notes.append("No placement or density setting is offered: these paths fail before placement, with no wires "
                     "yet to shorten.")
    if kinds or first_kinds:
        notes.append("Each failing endpoint is counted once, by its worst path (LibreLane's violator list).")
    if passing:
        notes.append("Passing: " + ", ".join(sorted(passing)) + ".")
    return {
        "id": "timing-setup", "severity": "fail" if gating else "warn", "kind": "check", "title": title,
        "plain": plain, "where": {"check": "setup", "stage": "signoff"}, "evidence": evidence,
        "diag": {"kind": "setup", "corner": wc, "ws": w["setup_ws"], "tns": w.get("setup_tns"),
                 "endpoints": w.get("setup_vio"), "kinds": kinds, "failing": failing,
                 "first": ({"when": first[0]["when"], "step": first[0]["id"], "corner": first[2],
                            "ws": first[1]["setup_ws"], "endpoints": first[1].get("setup_vio"),
                            "kinds": first_kinds, "run": first[0]["run"]} if first else None),
                 "before_placement": before_pnr, "io_first": early_io, "logic_depth": early_rr, "physical": bool(late),
                 "timeline": _timeline(hist, "setup_ws", wc), "path": path, "first_path": first_path,
                 "start_register": start, "period": period, "io_pct": io_pct, "out_load": load},
        "fixes": fixes, "notes": notes, "learn": ["slack", "wns", "tns"],
    }


def _timeline(hist: List[Dict[str, Any]], key: str, corner: str) -> List[Dict[str, Any]]:
    """Worst slack after each analysis: in the failing corner where it was
    timed, else in the corner the step did time (mid-PnR: the default one)."""
    out = []
    for h in hist:
        v = next(((c, x) for c, x in h["corners"].items() if _pvt(c) == _pvt(corner)), None)
        if v is None and h["corners"]:
            v = min(((c, x) for c, x in h["corners"].items() if _num(x.get(key)) is not None),
                    key=lambda t: t[1][key], default=None)
        if v is None:
            continue
        out.append({"when": h["when"], "step": h["id"], "corner": v[0], "ws": v[1].get(key),
                    "same_corner": _pvt(v[0]) == _pvt(corner), "ideal": h["ideal_clocks"], "signoff": h["signoff"]})
    return out


def _hold(run_dir: Path, cfg: Dict[str, Any], hist: List[Dict[str, Any]], final: Dict[str, Any],
          check: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    wc = _worst(final["corners"], "hold_ws")
    if wc is None or not check or check.get("status") not in ("fail", "warn"):
        return None
    w = final["corners"][wc]
    kinds = w["kinds"].get("hold") or {}
    gating = bool(check and check.get("status") == "fail")
    fixes = []
    m = _num(cfg.get("PL_RESIZER_HOLD_SLACK_MARGIN"))
    if m is not None:
        fixes.append(_setting("PL_RESIZER_HOLD_SLACK_MARGIN", m, round(m + abs(w["hold_ws"]) + 0.05, 3),
                              "Hold repair after the clock tree aims this far past zero, so it adds the buffers the "
                              "failing paths need.", "Repair hold with more margin"))
    if cfg.get("RUN_POST_GRT_RESIZER_TIMING") is False:
        fixes.append(_setting("RUN_POST_GRT_RESIZER_TIMING", False, True,
                              "A second repair with the routing estimates (off by default).", "Repair again after routing"))
    else:
        g = _num(cfg.get("GRT_RESIZER_HOLD_SLACK_MARGIN"))
        if g is not None:
            fixes.append(_setting("GRT_RESIZER_HOLD_SLACK_MARGIN", g, round(g + abs(w["hold_ws"]) + 0.05, 3),
                                  "The repair after routing aims this far past zero.", "More margin after routing"))
    plain = ("Worst hold slack %s in %s: %d endpoints. New data reaches a register too soon after the clock edge. "
             "A slower clock doesn't change hold, so none is offered; the repair steps add delay instead."
             % (_ns(w["hold_ws"]), wc, w.get("hold_vio") or 0))
    return {
        "id": "timing-hold", "severity": "fail" if gating else "warn", "kind": "check",
        "title": "Hold fails" + (" in the fast corners" if "ff" in wc else ""), "plain": plain,
        "where": {"check": "hold", "stage": "signoff"},
        "evidence": ["Failing at sign-off in %s: %s." % (wc, _kinds_text(kinds))] if kinds else [],
        "diag": {"kind": "hold", "corner": wc, "ws": w["hold_ws"], "tns": w.get("hold_tns"),
                 "endpoints": w.get("hold_vio"), "kinds": kinds},
        "fixes": fixes, "notes": ["Hold before the clock tree is built is an estimate (ideal clocks), so it isn't "
                                  "used to say where hold first failed."], "learn": ["hold"],
    }


# ---------------------------------------------------------------- DRC
_LAYERS = {"li": "local interconnect", "li1": "local interconnect", "met1": "metal 1", "met2": "metal 2",
           "met3": "metal 3", "met4": "metal 4", "met5": "metal 5", "m1": "metal 1", "m2": "metal 2", "m3": "metal 3",
           "m4": "metal 4", "m5": "metal 5", "via": "via 1", "via1": "via 1", "via2": "via 2", "via3": "via 3",
           "via4": "via 4", "mcon": "metal 1 contacts", "licon": "local interconnect contacts", "poly": "poly",
           "diff": "diffusion", "nwell": "n-well", "metal1": "metal 1", "metal2": "metal 2", "metal3": "metal 3",
           "metal4": "metal 4", "metal5": "metal 5", "local interconnect": "local interconnect"}
_KIND_WORDS = {"spacing": "shapes closer than", "width": "narrower than", "enclosure": "enclosed by less than",
               "extension": "extending less than", "area": "smaller than", "overlap": "overlapping by less than"}


def rule_in_words(name: str, description: str = "") -> str:
    """A DRC rule in plain words when its text follows the usual patterns
    (``Metal1 width < 0.14um (met1.1)``, ``m1.2 : min. met1 spacing : 0.14um``),
    else the deck's own description."""
    for text in (description, name):
        t = (text or "").strip()
        m = re.match(r"^(?:[\w.]+\s*:\s*)?min\.?\s+(\w+)\s+(spacing|width|enclosure|extension|area)\s*:?\s*([\d.]+)\s*(um2?|µm2?)?",
                     t, re.I)
        if not m:
            m2 = re.match(r"^(.+?)\s+(spacing|width|enclosure|extension|area|overlap)\b.*?<\s*([\d.]+)\s*(um2?|µm2?)?", t, re.I)
            if m2:
                m = m2
        if m:
            layer = _LAYERS.get(m.group(1).strip().lower(), m.group(1).strip())
            kind = m.group(2).lower()
            unit = "µm²" if kind == "area" or (m.group(4) or "").endswith("2") else "µm"
            return "%s %s %s %s" % (layer[0].upper() + layer[1:], _KIND_WORDS[kind], m.group(3), unit)
    return (description or name or "").strip()


def _region(cx: float, cy: float, die: Optional[List[float]]) -> str:
    if not die:
        return ""
    w, h = die[2] - die[0], die[3] - die[1]
    if w <= 0 or h <= 0:
        return ""
    fx, fy = (cx - die[0]) / w, (cy - die[1]) / h
    col = "left" if fx < 1 / 3 else "right" if fx > 2 / 3 else ""
    row = "bottom" if fy < 1 / 3 else "top" if fy > 2 / 3 else ""
    if row and col:
        return row + "-" + col + " corner"
    if row or col:
        return (row or col) + " edge"
    return "middle"


def _die(run_dir: Path) -> Optional[List[float]]:
    from . import history
    bb = str(history._load_metrics(run_dir).get("design__die__bbox") or "").split()
    try:
        d = [float(x) for x in bb]
        return d if len(d) == 4 else None
    except ValueError:
        return None


def cluster(items: List[Dict[str, Any]], radius: float) -> List[Dict[str, Any]]:
    """Group markers whose centres lie within *radius* µm of each other
    (single linkage), the way an engineer reads "two places", not "150 errors"."""
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    cs = [((it["bbox"][0] + it["bbox"][2]) / 2, (it["bbox"][1] + it["bbox"][3]) / 2) for it in items]
    order = sorted(range(n), key=lambda i: cs[i][0])
    for a_i, a in enumerate(order):          # sweep by x: only neighbours within radius in x
        for b in order[a_i + 1:]:
            if cs[b][0] - cs[a][0] > radius:
                break
            if abs(cs[b][1] - cs[a][1]) <= radius:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[ra] = rb
    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for idx in groups.values():
        bx = [items[i]["bbox"] for i in idx]
        rules: Dict[str, int] = {}
        for i in idx:
            rules[items[i]["cat"]] = rules.get(items[i]["cat"], 0) + 1
        out.append({"count": len(idx), "bbox": [min(b[0] for b in bx), min(b[1] for b in bx),
                                                max(b[2] for b in bx), max(b[3] for b in bx)],
                    "rules": sorted(({"name": k, "count": v} for k, v in rules.items()), key=lambda r: -r["count"])})
    out.sort(key=lambda g: -g["count"])
    return out


def drc_groups(run_dir: Path) -> Dict[str, Any]:
    """Each DRC checker's violations as rules and places, plus a note when
    the checkers disagree. Markers are the run's own report databases."""
    from . import layoutview
    die = _die(run_dir)
    diag = math.hypot(die[2] - die[0], die[3] - die[1]) if die else 100.0
    radius = max(5.0, 0.04 * diag)
    out = []
    for src in layoutview.markers(run_dir).get("sources") or []:
        if src.get("id") == "xor":
            continue
        cats = src.get("categories") or []
        places = cluster(src.get("items") or [], radius)
        for p in places:
            cx, cy = (p["bbox"][0] + p["bbox"][2]) / 2, (p["bbox"][1] + p["bbox"][3]) / 2
            p["center"] = [round(cx, 2), round(cy, 2)]
            p["where"] = _region(cx, cy, die)
        out.append({"id": src["id"], "label": src["label"], "total": src.get("total") or 0, "path": src.get("path"),
                    "rules": [{"name": c["name"], "count": c["count"], "description": c.get("description") or "",
                               "plain": rule_in_words(c["name"], c.get("description") or "")} for c in cats],
                    "places": places[:12], "more_places": max(0, len(places) - 12),
                    "listed": len(src.get("items") or [])})
    return {"sources": out, "radius": round(radius, 1), "die": die}


def checker_note(rep: Dict[str, Any], groups: Dict[str, Any]) -> Optional[str]:
    """When DRC checkers disagree, say why instead of showing two numbers."""
    by = {c["id"]: c for c in rep.get("checks") or []}
    val = lambda cid: _num((by.get(cid) or {}).get("value")) if (by.get(cid) or {}).get("status") in ("pass", "fail", "warn") else None  # noqa: E731
    mg, kl, rt = val("magic_drc"), val("klayout_drc"), val("route_drc")
    cfg = rep.get("_cfg") or {}
    parts = []
    if mg is not None and kl is not None and mg != kl:
        parts.append("Magic found %d and KLayout %d. LibreLane fails the run on either (ERROR_ON_MAGIC_DRC, "
                     "ERROR_ON_KLAYOUT_DRC), so both have to be clean; neither is the tiebreaker. Each runs its own rule "
                     "deck from the PDK, so the same problem can be one marker in one and several in the other, or "
                     "only in one." % (mg, kl))
    if mg is not None and kl is None and not str(rep.get("pdk") or "").startswith("sky130"):
        parts.append("KLayout DRC didn't run: in LibreLane 3.0.4 it supports only sky130A and sky130B, so Magic is the "
                     "only DRC for this PDK.")
    if rt == 0 and mg and mg > 0:
        parts.append("The router finished clean, yet Magic found %d. The router checks only its own wires, against the "
                     "routing rules it knows; Magic checks every shape in the final GDS, cells and power grid included." % mg)
    if cfg.get("MAGIC_DRC_USE_GDS") is False and mg:
        parts.append("Magic checked the DEF view (MAGIC_DRC_USE_GDS is off), which LibreLane says may be less accurate.")
    return " ".join(parts) or None


def drc_problems(run_dir: Path, rep: Dict[str, Any]) -> List[Dict[str, Any]]:
    by = {c["id"]: c for c in rep.get("checks") or []}
    bad = [cid for cid in ("magic_drc", "klayout_drc", "route_drc") if (by.get(cid) or {}).get("status") in ("fail", "warn")]
    if not bad:
        return []
    groups = drc_groups(run_dir)
    srcs = sorted((s for s in groups["sources"] if s["total"]), key=lambda s: -s["total"])
    total = sum(s["total"] for s in srcs)
    rules = {r["name"] for s in srcs for r in s["rules"] if r["count"]}
    places = sum(len(s["places"]) + s["more_places"] for s in srcs)
    head = srcs[0] if srcs else None
    if head:
        title = "%d DRC violation%s: %d rule%s in %d place%s" % (
            head["total"], "" if head["total"] == 1 else "s", len([r for r in head["rules"] if r["count"]]),
            "" if len([r for r in head["rules"] if r["count"]]) == 1 else "s",
            len(head["places"]) + head["more_places"], "" if len(head["places"]) + head["more_places"] == 1 else "s")
        title += " (" + head["label"] + ")"
    else:
        title = "DRC violations"
    fixes: List[Dict[str, Any]] = []
    if head and head["places"]:
        p = head["places"][0]
        fixes.append(_open("Show the biggest place in Layout", {"tab": "layout", "box": ",".join("%.2f" % v for v in p["bbox"])},
                           "%d violation%s %s." % (p["count"], "" if p["count"] == 1 else "s",
                                                   ("near the " + p["where"]) if p["where"] else "together")))
    if (by.get("route_drc") or {}).get("status") == "fail":
        cfg = _cfg(run_dir)
        core = _num(cfg.get("FP_CORE_UTIL"))
        if core and core > 25:
            fixes.append(_setting("FP_CORE_UTIL", core, int(max(20, core - 10)),
                                  "The router ran out of room: a bigger core leaves space for wires.", "Make the core bigger"))
        it = _num(cfg.get("DRT_OPT_ITERS"))
        if it:
            fixes.append(_setting("DRT_OPT_ITERS", it, int(it * 2), "Let the router keep trying longer.", "More routing passes"))
    rep2 = dict(rep, _cfg=_cfg(run_dir))
    note = checker_note(rep2, groups)
    return [{
        "id": "drc", "severity": "fail" if any((by.get(c) or {}).get("status") == "fail" for c in bad) else "warn",
        "kind": "check", "title": title,
        "plain": "%d in all, across %d rule%s and %d place%s. Engineers read DRC this way: a few rules in a few "
                 "places, where fixing one often clears several." % (total, len(rules), "" if len(rules) == 1 else "s",
                                                                        places, "" if places == 1 else "s"),
        "where": {"check": bad[0], "stage": "signoff"}, "evidence": [],
        "diag": {"kind": "drc", **groups}, "fixes": fixes, "notes": [note] if note else [], "learn": ["drc"],
    }]


# ---------------------------------------------------------------- other checks
# Settings a failing check can point at. Each entry: (variable, proposal, why);
# a proposal is a function of the run's current value.
def _minus(step: float, floor: float):
    return lambda v: None if v is None or v - step < floor else int(v - step) if float(v).is_integer() else round(v - step, 3)


def _plus(step: float):
    return lambda v: None if v is None else (int(v + step) if float(v).is_integer() and float(step).is_integer() else round(v + step, 3))


_CHECK_FIXES: Dict[str, List[Any]] = {
    "antenna": [("GRT_ANTENNA_REPAIR_ITERS", _plus(3), "More antenna-repair passes during global routing."),
                ("GRT_ANTENNA_REPAIR_MARGIN", _plus(10), "Repair with more margin than the limit (%)."),
                ("DIODE_ON_PORTS", lambda v: "in" if v in (None, "none") else None,
                 "Protection diodes on the top-level inputs, for violations on pins.")],
    "disc_pin": [("FP_CORE_UTIL", _minus(10, 20), "Usually congestion: a bigger core leaves room for every wire.")],
    "slew": [("DESIGN_REPAIR_MAX_SLEW_PCT", _plus(10), "Design repair aims this much under the slew limit (%).")],
    "cap": [("DESIGN_REPAIR_MAX_CAP_PCT", _plus(10), "Design repair aims this much under the capacitance limit (%).")],
}
_CHECK_OPEN = {
    "lint_errors": ("Open the RTL IDE", {"tab": "ide"}, "Its Problems list shows each lint error with file and line."),
    "lint_timing_constructs": ("Open the RTL IDE", {"tab": "ide"}, "Remove the delays or wrap them in `ifdef SIMULATION."),
    "unmapped": ("Open the RTL IDE", {"tab": "ide"}, "Usually a module that is used but never defined."),
    "synth_check": ("Open the RTL IDE", {"tab": "ide"}, "Drive every wire; break loops with a register."),
    "latch": ("Open the RTL IDE", {"tab": "ide"}, "Give every signal a value on every path of the always block."),
}


def check_problems(run_dir: Path, rep: Dict[str, Any], skip: set) -> List[Dict[str, Any]]:
    cfg = _cfg(run_dir)
    out = []
    for c in rep.get("checks") or []:
        if c["status"] not in ("fail", "warn") or c["id"] in skip:
            continue
        fixes = []
        for var, prop, why in _CHECK_FIXES.get(c["id"], []):
            cur = cfg.get(var)
            num = _num(cur)
            to = prop(num if num is not None else cur)
            if to is not None and fmt(to) != fmt(cur):
                fixes.append(_setting(var, cur, to, why))
        if c["id"] in _CHECK_OPEN:
            label, go, why = _CHECK_OPEN[c["id"]]
            fixes.append(_open(label, go, why))
        out.append({"id": "check-" + c["id"], "severity": c["status"], "kind": "check", "title": c["name"],
                    "plain": c.get("detail") or c.get("note") or "", "where": {"check": c["id"]},
                    "evidence": [], "diag": {"kind": "check", "value": c.get("value"), "limit": c.get("limit")},
                    "fixes": fixes, "notes": [], "learn": []})
    return out


# ---------------------------------------------------------------- the run
def _cfg(run_dir: Path) -> Dict[str, Any]:
    from . import history
    return history._read_config(Path(run_dir)) or {}


def resume_for(var: str, flow: str = "Classic") -> Optional[Dict[str, Any]]:
    from . import varstage
    try:
        return varstage.resume_point([var], flow)
    except Exception:
        return None


def finish(fixes: List[Dict[str, Any]], flow: str = "Classic") -> List[Dict[str, Any]]:
    """Keep only settings this LibreLane knows (applying an unknown one would
    fail the run) and say where each one resumes."""
    from . import introspect
    names = introspect.known_var_names()
    out = []
    for f in fixes:
        if f["kind"] == "setting":
            if names and f["var"] not in names:
                continue
            f["resume"] = resume_for(f["var"], flow)
        out.append(f)
    return out


_CACHE: Dict[str, Any] = {}


def _signature(run_dir: Path) -> tuple:
    sig = []
    for p in (run_dir, run_dir / "final" / "metrics.json", run_dir / "gui-run.json", run_dir / "error.log"):
        try:
            sig.append(p.stat().st_mtime_ns)
        except OSError:
            sig.append(0)
    return tuple(sig)


def run_problems(run_dir: str | Path) -> Dict[str, Any]:
    """Every problem of one run, worst first: the step that stopped it (if
    any), then each failing or warning check, timing and DRC diagnosed.
    Remembered until the run's folder changes."""
    run_dir = Path(run_dir).resolve()
    key, sig = str(run_dir), _signature(run_dir)
    hit = _CACHE.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    out = _run_problems(run_dir)
    if len(_CACHE) > 32:
        _CACHE.clear()
    _CACHE[key] = (sig, out)
    return out


def _run_problems(run_dir: Path) -> Dict[str, Any]:
    from . import runexplain, verify
    rep = verify.verify_report(run_dir)
    flow = rep.get("flow") or "Classic"
    problems: List[Dict[str, Any]] = []
    rx = runexplain.explain_run(run_dir)
    if rx.get("kind") == "halted" and rx.get("card"):
        c = rx["card"]
        step = rx.get("step") or {}
        problems.append({"id": "halted", "severity": "fail", "kind": "halted",
                         "title": c.get("title") or ("Stopped at " + (step.get("id") or step.get("dir") or "a step")),
                         "plain": c.get("plain") or "", "where": {"stage": rx.get("stage"), "step": step, "at": rx.get("at")},
                         "evidence": (rx.get("errors") or [])[:3], "diag": {"kind": "halted", "code": c.get("code")},
                         "fixes": c.get("fixes") or [], "notes": [], "learn": c.get("learn") or []})
    skip = set()
    for p in timing_problems(run_dir, rep):
        problems.append(p)
        skip.add(p["where"]["check"])
    for p in drc_problems(run_dir, rep):
        problems.append(p)
        skip.update({"magic_drc", "klayout_drc", "route_drc"})
    problems += check_problems(run_dir, rep, skip)
    for p in problems:
        p["fixes"] = finish(p["fixes"], flow) if p["kind"] != "halted" else p["fixes"]
    problems.sort(key=lambda p: (p["severity"] != "fail", p["kind"] != "halted"))
    return {"tag": run_dir.name, "flow": flow, "verdict": (rep.get("verdict") or {}).get("state"),
            "counts": {"fail": sum(1 for p in problems if p["severity"] == "fail"),
                       "warn": sum(1 for p in problems if p["severity"] == "warn")},
            "problems": problems}
