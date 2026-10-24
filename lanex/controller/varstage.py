# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Which step of the flow first reads a variable: where a run can resume
after that variable changes.

LibreLane hands each step only its own ``config_vars`` plus the variables
every step gets (``librelane.config.flow``), so a step-specific variable's
readers are exactly the steps that declare it. The common ones can't be told
apart that way; the table below names the first step that uses each of the
ones a fix touches, checked in LibreLane 3.0.4's own scripts:

* ``CLOCK_PERIOD``, ``MAX_FANOUT_CONSTRAINT``, ``MAX_TRANSITION_CONSTRAINT``:
  ``scripts/pyosys/construct_abc_script.py`` (ABC's delay target, every
  strategy); ``OUTPUT_CAP_LOAD``, ``SYNTH_DRIVING_CELL``:
  ``scripts/pyosys/synthesize.py``. First reader ``Yosys.Synthesis``.
* ``IO_DELAY_CONSTRAINT``, ``CLOCK_UNCERTAINTY_CONSTRAINT``,
  ``CLOCK_TRANSITION_CONSTRAINT``, ``TIME_DERATING_CONSTRAINT``,
  ``MAX_CAPACITANCE_CONSTRAINT``, ``SYNTH_CLK_DRIVING_CELL``, ``CLOCK_PORT``:
  ``scripts/base.sdc`` and ``scripts/openroad/common/io.tcl``, read by the
  OpenROAD steps; ``RT_MIN_LAYER``/``RT_MAX_LAYER``:
  ``openroad/common/set_routing_layers.tcl``; ``CLOCK_NET``: ``cts.tcl`` and
  ``steps/openroad.py``. First reader: the first step handed the SDC
  (``PNR_SDC_FILE``), ``OpenROAD.CheckSDCFiles``.
* ``DIE_AREA``: ``scripts/openroad/floorplan.tcl``. ``OpenROAD.Floorplan``.

Any other common or PDK variable means the whole flow. A ``RUN_*`` switch
resumes at the step it gates (``gating_config_vars``). Steps are named by ID,
never by folder number: a resumed run numbers its folders from ``01``.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from . import flowstages, introspect

_SYNTH = "Yosys.Synthesis"
_SDC = "@sdc"          # the first step that is handed PNR_SDC_FILE
_CURATED = {
    "CLOCK_PERIOD": _SYNTH, "MAX_FANOUT_CONSTRAINT": _SYNTH, "MAX_TRANSITION_CONSTRAINT": _SYNTH,
    "OUTPUT_CAP_LOAD": _SYNTH, "SYNTH_DRIVING_CELL": _SYNTH,
    "IO_DELAY_CONSTRAINT": _SDC, "CLOCK_UNCERTAINTY_CONSTRAINT": _SDC, "CLOCK_TRANSITION_CONSTRAINT": _SDC,
    "TIME_DERATING_CONSTRAINT": _SDC, "MAX_CAPACITANCE_CONSTRAINT": _SDC, "SYNTH_CLK_DRIVING_CELL": _SDC,
    "CLOCK_PORT": _SDC, "CLOCK_NET": _SDC, "RT_MIN_LAYER": _SDC, "RT_MAX_LAYER": _SDC, "FALLBACK_SDC": _SDC,
    "DIE_AREA": "OpenROAD.Floorplan",
}


def _index(steps: List[Dict[str, Any]], step_id: str) -> Optional[int]:
    for i, s in enumerate(steps):
        if s["id"] == step_id:
            return i
    return None


def _gated_steps(steps: List[Dict[str, Any]], gating: Dict[str, List[str]], var: str) -> List[int]:
    import fnmatch
    hits = []
    for key, vars_ in gating.items():
        if var not in vars_:
            continue
        for i, s in enumerate(steps):
            if s["id"] == key or fnmatch.fnmatchcase(s["id"], key):
                hits.append(i)
    return hits


def earliest(var: str, flow: str = "Classic", steps: Optional[List[Dict[str, Any]]] = None,
             gating: Optional[Dict[str, List[str]]] = None,
             common: Optional[Iterable[str]] = None) -> Optional[Dict[str, Any]]:
    """``{index, step, how}`` of the first step that reads *var* in *flow*:
    ``how`` is ``declared`` (its config_vars), ``curated`` (the table above),
    ``gating`` (a RUN_* switch) or ``common`` (read everywhere: index 0).
    None when no step of this flow reads it, or without LibreLane."""
    steps = introspect.flow_steps(flow) if steps is None else steps
    if not steps:
        return None
    gating = introspect.flow_gating(flow) if gating is None else gating
    common = introspect.flow_common_names() if common is None else frozenset(common)
    cands = []
    for i, s in enumerate(steps):
        if var in s["vars"]:
            cands.append((i, "declared"))
            break
    anchor = _CURATED.get(var)
    if anchor == _SDC:
        i = next((k for k, s in enumerate(steps) if "PNR_SDC_FILE" in s["vars"]), None)
        if i is not None:
            cands.append((i, "curated"))
    elif anchor:
        i = _index(steps, anchor)
        if i is not None:
            cands.append((i, "curated"))
    for i in _gated_steps(steps, gating, var):
        cands.append((i, "gating"))
    if not cands and var in common:
        cands.append((0, "common"))
    if not cands:
        return None
    i, how = min(cands)
    return {"index": i, "step": steps[i]["id"], "how": how}


def resume_point(variables: Iterable[str], flow: str = "Classic",
                 steps: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Where a run that changes all of *variables* has to start again:
    ``{index, step, stage, n, how, by, stage_start}`` for the earliest reader
    of any of them (``by`` names that variable; ``stage_start``: it is the
    stage's first step). None when no step reads any."""
    steps = introspect.flow_steps(flow) if steps is None else steps
    best = None
    for v in variables:
        e = earliest(v, flow, steps=steps)
        if e is not None and (best is None or e["index"] < best["index"]):
            best = dict(e, by=v)
    if best is None:
        return None
    stages = flowstages.stages_of([s["id"] for s in steps])
    best["stage"] = stages[best["index"]]
    best["n"] = best["index"] + 1
    best["stage_start"] = stages.index(best["stage"]) == best["index"]
    return best


def stage_starts(flow: str = "Classic") -> List[Dict[str, Any]]:
    """The first step of each stage: what "resume from Placement" means."""
    steps = introspect.flow_steps(flow)
    stages = flowstages.stages_of([s["id"] for s in steps])
    out, seen = [], set()
    for i, (s, st) in enumerate(zip(steps, stages)):
        if st not in seen:
            seen.add(st)
            out.append({"stage": st, "index": i, "step": s["id"], "n": i + 1})
    return out
