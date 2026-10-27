# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""A run resumed from another one: where it starts, what it keeps.

LibreLane 3.0.4 can start a new run from a step of an old one:
``--run-tag NEW -i runs/OLD/NN-<step>/state_out.json --from <next step>``
(``flows/cli.py`` loads the state and checks every path in it exists;
``flows/sequential.py`` skips the steps before ``--from`` without making
folders for them). The new run's later steps read files in the old run's
folders, so the old run must stay (``history.lineage_steps`` follows them).

A resumed run has to be the old run plus the change, nothing else: it keeps
the old run's PDK, library, flow, sources and its settings "for this run
only", and only the variables being changed differ. Where it starts is the
first step that reads any of them (``varstage.py``). Anything else that
differs since the old run moves that start earlier, so the reused steps never
stand on stale inputs:

* a setting in the config file whose value is not the one the old run used
  (read straight from the config file, for this run's PDK and library);
* a file the old run read (RTL, SDC, pin order…) that changed after the
  first reused step ran: its variable's first reader.

``plan()`` answers all of this without changing anything; the server's
``/api/fix/apply`` writes the config (``configedit``) and starts the run.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import configedit, flowstages, history, introspect, varstage

_SKIP_KEYS = {"meta", "PDK", "STD_CELL_LIBRARY", "DESIGN_DIR", "PDK_ROOT"}


class BranchError(Exception):
    """A resume that can't be planned (no such run, no saved state…)."""


# ------------------------------------------------------------------ values

def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def show(v: Any) -> str:
    """A value the way the fix sheet and the command show it."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return " ".join(show(x) for x in v)
    f = _num(v)
    if f is not None:
        return str(int(f)) if f == int(f) and abs(f) < 1e15 else ("%.6f" % f).rstrip("0").rstrip(".")
    return str(v)


def same(a: Any, b: Any) -> Optional[bool]:
    """Whether two settings are equal, or None when LanEx can't tell (paths,
    globs and nested values are resolved by LibreLane, not here)."""
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        la = a if isinstance(a, (list, tuple)) else str(a or "").split()
        lb = b if isinstance(b, (list, tuple)) else str(b or "").split()
        na, nb = [_num(x) for x in la], [_num(x) for x in lb]
        if None in na or None in nb:
            return None
        return len(na) == len(nb) and all(abs(x - y) < 1e-9 for x, y in zip(na, nb))
    if isinstance(a, dict) or isinstance(b, dict):
        return None
    if isinstance(a, bool) or isinstance(b, bool):
        ba = a if isinstance(a, bool) else str(a).strip().lower() in ("1", "true", "yes", "on")
        bb = b if isinstance(b, bool) else str(b).strip().lower() in ("1", "true", "yes", "on")
        return ba == bb
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) < 1e-9
    if a is None or b is None:
        return a is None and b is None
    sa, sb = str(a), str(b)
    if sa.startswith(("dir::", "pdk_dir::", "refg::", "/")) or "*" in sa or "$" in sa:
        return None
    return sa == sb


def coerce(value: Any, info: Optional[Dict[str, Any]]) -> Any:
    """*value* (often text from a field) as the variable's own type
    (``introspect`` ``kind``), for writing into a config file: numbers,
    booleans, lists of numbers. Raises :class:`BranchError` for a value of
    the wrong kind."""
    kind = (info or {}).get("kind") or "text"
    name = (info or {}).get("name") or "This setting"
    if not isinstance(value, str):
        return value
    s = value.strip()
    if kind == "bool":
        if s.lower() in ("true", "1", "yes", "on"):
            return True
        if s.lower() in ("false", "0", "no", "off"):
            return False
        raise BranchError(f"{name} is true or false, not '{s}'.")
    if kind in ("int", "number"):
        n = _num(s)
        if n is None:
            raise BranchError(f"{name} takes a number, not '{s}'.")
        if kind == "int" and n != int(n):
            raise BranchError(f"{name} takes a whole number, not '{s}'.")
        return int(n) if n == int(n) else n
    if kind == "numbers":
        parts = [x for x in re.split(r"[\s,]+", s.strip("[]() ")) if x]
        nums = [_num(x) for x in parts]
        if not nums or None in nums:
            raise BranchError(f"{name} takes numbers, not '{s}'.")
        return [int(n) if n == int(n) else n for n in nums]
    if kind == "choice":
        choices = [str(c) for c in (info or {}).get("choices") or []]
        if choices and s not in choices:
            raise BranchError(f"{name} is one of {', '.join(choices)}, not '{s}'.")
    return s


def _vars() -> Dict[str, Dict[str, Any]]:
    try:
        return {v["name"]: v for v in introspect.list_variables()}
    except Exception:
        return {}


# ------------------------------------------------------------------ the old run

def _read(p: Path) -> Dict[str, Any]:
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def run_info(run_dir: Path) -> Dict[str, Any]:
    gui = _read(run_dir / "gui-run.json")
    resolved = history._read_config(run_dir) or {}
    meta = resolved.get("meta") if isinstance(resolved.get("meta"), dict) else {}
    return {
        "gui": gui, "resolved": resolved,
        "flow": gui.get("flow") or meta.get("flow") or "Classic",
        "pdk": gui.get("pdk") or resolved.get("PDK"),
        "scl": gui.get("scl") or resolved.get("STD_CELL_LIBRARY"),
        "overrides": dict(gui.get("overrides") or {}),
    }


def config_entry(data: Dict[str, Any], var: str, pdk: Optional[str], scl: Optional[str]) -> Optional[Dict[str, Any]]:
    """Where the config file sets *var* for this PDK and library: the most
    specific section that applies wins over the top level, as in LibreLane.
    ``{value, scope: [section keys] or None, label}``."""
    best: Optional[Tuple[int, Dict[str, Any]]] = None
    if var in data:
        best = (0, {"value": data[var], "scope": None, "label": "top level"})
    for e in configedit.scoped_values(data, var):
        if configedit.applies(e, pdk, scl):
            depth = len(e["scope"].split(" / "))
            if best is None or depth >= best[0]:
                best = (depth, {"value": e["value"], "scope": e["scope"].split(" / "), "label": e["scope"] + " section"})
    return best[1] if best else None


def origin(var: str, info: Dict[str, Any], cfg: Dict[str, Any], vinfo: Optional[Dict[str, Any]],
           cfg_name: str = "the config") -> Dict[str, Any]:
    """Where the old run's value of *var* came from: ``run`` (set for that run
    only), ``config`` (the file, and which section), ``pdk`` or ``default``."""
    used = info["resolved"].get(var)
    if var in info["overrides"]:
        return {"layer": "run", "label": "set for " + info["gui"].get("tag", "that run") + " only", "value": used}
    e = config_entry(cfg, var, info["pdk"], info["scl"])
    if e is not None:
        where = cfg_name + (", " + e["label"] if e["scope"] else "")
        return {"layer": "config", "label": where, "scope": e["scope"], "value": used}
    dflt = (vinfo or {}).get("default")
    if (vinfo or {}).get("pdk") or (dflt not in (None, "") and same(dflt, used) is False):
        return {"layer": "pdk", "label": "the PDK (" + str(info["pdk"] or "") + ")", "value": used}
    return {"layer": "default", "label": "LibreLane's default", "value": used}


def _first_reused_start(steps: List[Dict[str, Any]]) -> Optional[float]:
    for s in steps:
        p = s["path"] / "state_in.json"
        try:
            return p.stat().st_mtime
        except OSError:
            continue
    return None


def _paths_in(v: Any) -> Iterable[str]:
    if isinstance(v, str):
        yield v
    elif isinstance(v, (list, tuple)):
        for x in v:
            if isinstance(x, str):
                yield x


def changed_files(run_dir: Path, resolved: Dict[str, Any], design_dir: Path, since: Optional[float]) -> List[Dict[str, Any]]:
    """Files in the project that the old run read and that changed after
    *since* (when the first reused step ran): ``[{path, vars}]``."""
    if since is None:
        return []
    dd = design_dir.resolve()
    runs = (dd / "runs").resolve()
    hits: Dict[str, Dict[str, Any]] = {}
    for k, v in resolved.items():
        if k in _SKIP_KEYS or not isinstance(k, str):
            continue
        for s in _paths_in(v):
            if not s.startswith("/") or len(s) > 4096:
                continue
            try:
                p = Path(s).resolve()
                if runs in p.parents or dd not in p.parents or not p.is_file():
                    continue
                if p.stat().st_mtime > since + 1:
                    rel = p.relative_to(dd).as_posix()
                    hits.setdefault(rel, {"path": rel, "vars": []})["vars"].append(k)
            except (OSError, ValueError):
                continue
    return sorted(hits.values(), key=lambda h: h["path"])


def changed_settings(cfg: Dict[str, Any], info: Dict[str, Any], exclude: Iterable[str],
                     known: Optional[set] = None) -> List[Dict[str, Any]]:
    """Settings the config file now gives a value other than the one the old
    run used (``[{var, was, now, where}]``). Settings the old run set for
    itself are carried over to the new run, so they can't differ."""
    out = []
    skip = set(exclude) | set(info["overrides"]) | _SKIP_KEYS
    keys = {k for k in cfg if isinstance(k, str) and not k.startswith(("pdk::", "scl::"))}

    def walk(section: Dict[str, Any]) -> None:
        for k, v in section.items():
            if isinstance(k, str) and k.startswith(("pdk::", "scl::")) and isinstance(v, dict):
                keys.update(x for x in v if isinstance(x, str) and not x.startswith(("pdk::", "scl::")))
                walk(v)
    walk(cfg)
    for k in sorted(keys - skip):
        if known and k not in known:
            continue
        e = config_entry(cfg, k, info["pdk"], info["scl"])
        if e is None or k not in info["resolved"]:     # resolved.json lists every variable it used
            continue
        was = info["resolved"].get(k)
        if same(e["value"], was) is False:
            out.append({"var": k, "was": show(was), "now": show(e["value"]), "where": e["label"]})
    return out


def _positions(step_ids: List[str]):
    """A step folder's place in the flow: by its id (flow.log), else by its
    folder name, which is the id in lower case with dashes
    (``OpenROAD.STAMidPNR-1`` -> ``NN-openroad-stamidpnr-1``)."""
    pos = {sid: i for i, sid in enumerate(step_ids)}
    by_slug = {sid.lower().replace(".", "-"): i for i, sid in enumerate(step_ids)}

    def at(s: Dict[str, Any]) -> Optional[int]:
        if s.get("id") in pos:
            return pos[s["id"]]
        return by_slug.get(str(s.get("dir") or "").split("-", 1)[-1])
    return at


def state_before(lineage: List[Dict[str, Any]], step_ids: List[str], index: int) -> Optional[Dict[str, Any]]:
    """The state a run that starts at flow step *index* continues from: the
    newest saved state of a step before it, ``{path, step, run}``."""
    at = _positions(step_ids)
    best = None
    for s in lineage:
        i = at(s)
        if i is None or i >= index:
            continue
        p = s["path"] / "state_out.json"
        if p.is_file() and (best is None or i > best[0]):
            best = (i, {"path": p, "step": step_ids[i], "run": s["run"]})
    return best[1] if best else None


def missing_paths(state_file: Path, limit: int = 5) -> List[str]:
    """Paths a saved state points at that no longer exist (LibreLane's ``-i``
    refuses such a state)."""
    out: List[str] = []

    def walk(v: Any) -> None:
        if len(out) >= limit:
            return
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str) and v.startswith("/") and not Path(v).exists():
            out.append(v)
    doc = _read(state_file)
    walk({k: v for k, v in doc.items() if k != "metrics"})
    return out


def progress(lineage: List[Dict[str, Any]], step_ids: List[str]) -> Dict[str, Any]:
    """How far the old run got: ``{done, stopped}`` flow indices (the last
    step with saved results; the first step after it that started and has
    none, where the run stopped). A checker that failed the run at the end
    (LibreLane's deferred errors) saves no state either, but steps after it
    ran, so it is not where the run stopped."""
    at = _positions(step_ids)
    done, open_ = -1, []
    for s in lineage:
        i = at(s)
        if i is None:
            continue
        if (s["path"] / "state_out.json").is_file():
            done = max(done, i)
        else:
            open_.append(i)
    after = [i for i in open_ if i > done]
    return {"done": done, "stopped": min(after) if after else None}


# ------------------------------------------------------------------ the plan

def _new_tag(runs_dir: Path, parent: str) -> str:
    import time
    base = time.strftime("glui-%Y%m%d-%H%M%S")
    tag, n = base, 2
    while (runs_dir / tag).exists():
        tag, n = f"{base}-{n}", n + 1
    return tag


def plan(design_dir: str | Path, tag: str, sets: Optional[Dict[str, Any]] = None, *,
         save: str = "auto", start: str = "auto", new_tag: Optional[str] = None) -> Dict[str, Any]:
    """What resuming *tag* with *sets* would do. Changes nothing.

    *save*: ``config`` (the project's config file), ``run`` (this run only) or
    ``auto`` (where the old value came from: a value set for that run only
    stays that way, anything else goes to the config). *start*: ``auto`` (the
    earliest step anything changed reaches), ``full`` (the whole flow), or a
    step id to resume from (moved earlier when something it doesn't cover
    changed)."""
    design_dir = Path(design_dir)
    run_dir = design_dir / "runs" / tag
    if not tag or "/" in tag or "\\" in tag or not run_dir.is_dir():
        raise BranchError(f"There is no run '{tag}' in this project.")
    if new_tag and (not re.fullmatch(r"[A-Za-z0-9._-]+", new_tag) or (design_dir / "runs" / new_tag).exists()):
        raise BranchError(f"A run named '{new_tag}' exists already: pick another run name in Setup.")
    info = run_info(run_dir)
    info["gui"].setdefault("tag", tag)
    sets = dict(sets or {})
    known = _vars()
    for k in sets:
        if known and k not in known:
            raise BranchError(f"{k} isn't a setting this LibreLane knows.")
    cfg_info = configedit.read_config(design_dir)
    cfg = cfg_info.get("data") or {}
    cfg_name = cfg_info.get("name") or "the config"
    steps = [s["id"] for s in introspect.flow_steps(info["flow"])]
    if not steps:
        raise BranchError("LanEx can't read the steps of the " + str(info["flow"]) + " flow.")
    stages = flowstages.stages_of(steps)
    lineage = history.lineage_steps(run_dir)
    prog = progress(lineage, steps)

    # The changes, each with where its old value came from and where it goes.
    changes = []
    for var, raw in sets.items():
        vi = known.get(var)
        to = coerce(raw, dict(vi or {}, name=var))
        o = origin(var, info, cfg, vi, cfg_name)
        where = save if save in ("config", "run") else ("run" if o["layer"] == "run" else "config")
        if where == "config" and not cfg_info.get("editable"):
            where = "run"
        entry = config_entry(cfg, var, info["pdk"], info["scl"]) if where == "config" else None
        changes.append({
            "var": var, "from": show(info["resolved"].get(var)), "to": show(to), "value": to,
            "origin": o, "save": where, "scope": (entry or {}).get("scope"),
            "info": {k: (vi or {}).get(k) for k in ("description", "units", "type", "kind", "default", "choices")},
            "reader": varstage.resume_point([var], info["flow"]),
        })
    same_as_now = [c["var"] for c in changes if same(c["value"], info["resolved"].get(c["var"])) is True]

    # The config file: one dry-run edit for everything saved there.
    to_config = [c for c in changes if c["save"] == "config"]
    cfg_diff: List[Dict[str, Any]] = []
    cfg_error = None
    if to_config:
        try:
            by_scope: Dict[Tuple[str, ...], Dict[str, Any]] = {}
            for c in to_config:
                by_scope.setdefault(tuple(c["scope"] or ()), {})[c["var"]] = c["value"]
            for scope, kv in by_scope.items():
                res = configedit.set_keys(design_dir, kv, dry_run=True, scope=list(scope) or None)
                cfg_diff += res.get("diff") or []
        except configedit.ConfigEditError as ex:
            cfg_error = str(ex)

    # Everything else that differs since the old run.
    drift = changed_settings(cfg, info, sets, set(known) if known else None)
    files = changed_files(run_dir, info["resolved"], design_dir, _first_reused_start(lineage))
    hash_now = None
    try:
        import hashlib
        p = Path(cfg_info.get("path") or "")
        hash_now = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
    except Exception:
        hash_now = None
    cfg_edited = bool(info["gui"].get("config_hash") and hash_now and info["gui"]["config_hash"] != hash_now)

    # Where to start.
    why = [c["var"] for c in changes] + [d["var"] for d in drift] + [v for f in files for v in f["vars"]]
    need = varstage.resume_point(why, info["flow"]) if why else None
    need_i = need["index"] if need else None
    # A variable no step of this flow reads by name (a PDK or common one
    # LanEx can't place): the whole flow.
    unplaced = [v for v in why if varstage.resume_point([v], info["flow"]) is None]
    if unplaced:
        need_i = 0
    limit = prog["stopped"] if prog["stopped"] is not None else prog["done"] + 1
    asked = None
    if start not in ("auto", "full"):
        if start not in steps:
            raise BranchError(f"{start} isn't a step of the {info['flow']} flow.")
        asked = steps.index(start)
    if start == "full":
        idx = 0
    elif asked is not None:
        idx = min(asked, need_i) if need_i is not None else asked
    else:
        idx = need_i if need_i is not None else 0
    reasons = []
    if asked is not None and need_i is not None and need_i < asked:
        reasons.append("earlier")
    if idx > limit:
        idx = max(0, limit)
        reasons.append("stopped")
    state = state_before(lineage, steps, idx) if idx > 0 else None
    blocked = None
    if idx > 0 and state is None:
        idx, state = 0, None
    if state is not None:
        gone = missing_paths(state["path"])
        if gone:
            blocked = ("Files " + tag + " needs to resume from are gone (" + gone[0] + "). Run the whole flow instead.")
    resume = None
    if idx > 0:
        resume = {"index": idx, "n": idx + 1, "step": steps[idx], "stage": stages[idx],
                  "stage_start": stages.index(stages[idx]) == idx,
                  "by": next((v for v in why if (varstage.resume_point([v], info["flow"]) or {}).get("index") == need_i), None),
                  "reasons": reasons,
                  "state": state["path"].relative_to(design_dir).as_posix() if state else None,
                  "state_step": state["step"] if state else None, "state_run": state["run"] if state else None}

    # What the new run inherits: the old run's settings for itself, minus the
    # ones changed now; a change saved "this run only" joins them.
    overrides = {k: v for k, v in info["overrides"].items() if k not in sets}
    for c in changes:
        if c["save"] == "run":
            overrides[c["var"]] = show(c["value"])
    stage_starts = []
    seen = set()
    for i, st in enumerate(stages):
        if st not in seen:
            seen.add(st)
            stage_starts.append({"stage": st, "index": i, "step": steps[i], "n": i + 1,
                                 "ok": 0 < i <= limit and (need_i is None or i <= need_i)})
    return {
        "ok": blocked is None and cfg_error is None,
        "blocked": blocked, "config_error": cfg_error,
        "parent": {"tag": tag, "flow": info["flow"], "pdk": info["pdk"], "scl": info["scl"],
                   "done": prog["done"], "stopped": prog["stopped"],
                   "stopped_step": steps[prog["stopped"]] if prog["stopped"] is not None else None},
        "changes": [{k: v for k, v in c.items() if k != "value"} for c in changes],
        "unchanged": same_as_now,
        "config": {"name": cfg_info.get("name"), "editable": bool(cfg_info.get("editable")),
                   "reason": cfg_info.get("reason"), "diff": cfg_diff, "edited_since": cfg_edited},
        "drift": {"settings": drift, "files": files, "unplaced": unplaced},
        "resume": resume, "stages": stage_starts, "steps_total": len(steps),
        "overrides": overrides,
        "sources": list(info["gui"].get("sources") or []), "extras": list(info["gui"].get("extras") or []),
        "tag": new_tag or _new_tag(design_dir / "runs", tag),
        "_values": {c["var"]: c["value"] for c in changes},
    }


def branch_meta(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What ``gui-run.json`` records as ``branched_from`` for a planned run
    (None when it starts from the beginning)."""
    r = p.get("resume")
    if not r:
        return None
    return {"tag": p["parent"]["tag"], "step": r["step"], "stage": r["stage"], "state": r["state"],
            "changes": [{"var": c["var"], "from": c["from"], "to": c["to"], "saved": c["save"]} for c in p["changes"]]}


def children(design_dir: str | Path, tag: str) -> List[str]:
    """Runs resumed from *tag*: deleting it would break them."""
    out = []
    runs = Path(design_dir) / "runs"
    try:
        for d in sorted(runs.iterdir()):
            if d.is_dir() and d.name != tag:
                b = (_read(d / "gui-run.json").get("branched_from") or {})
                if isinstance(b, dict) and b.get("tag") == tag:
                    out.append(d.name)
    except OSError:
        pass
    return out
