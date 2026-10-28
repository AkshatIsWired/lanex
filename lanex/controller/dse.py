# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Design-Space Exploration (Phase 2.B): run one design under N configs.

DSE is **a queue of normal runs** — it reuses the existing
:class:`runner.FlowRunner` (container or local), one config at a time (single
engine, storage-sane), each with a distinct ``--run-tag``. This module owns the
pure planning (sweep expansion, deterministic tags, combo cap + validation) and
a small sequential queue manager that emits ``dse_*`` progress events on the
shared bus. No new dependency; no new run engine.
"""
from __future__ import annotations

import itertools
import json
import os
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import events, introspect

# Hard cap on enumerated combos to avoid runaway storage (each run writes a dir).
MAX_COMBOS = 64

# Sweep manifests live as a sidecar in the design dir (travels with the project,
# matching the existing `.gui-custom-cells.json` / `gui-run.json` convention) so
# a server restart can still list past sweeps without re-deriving them from a
# fragile run-tag regex, and so a re-run never silently overwrites a prior sweep.
_SWEEPS_FILE = ".gui-dse-sweeps.json"


def _sweeps_path(design_dir: str | Path) -> Path:
    return Path(design_dir) / _SWEEPS_FILE


def load_sweeps(design_dir: str | Path) -> List[Dict[str, Any]]:
    """All recorded sweep manifests for a design, newest first."""
    p = _sweeps_path(design_dir)
    if not p.is_file():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    sweeps = doc.get("sweeps") if isinstance(doc, dict) else doc
    if not isinstance(sweeps, list):
        return []
    sweeps.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return sweeps


def new_sweep_id(design_dir: str | Path | None = None) -> str:
    """A sortable, collision-resistant sweep id (``YYYYMMDD-HHMMSS``), in the
    person's own time zone (the distro's clock runs on UTC). With
    ``design_dir``, an id already recorded there gets ``-2``, ``-3``..."""
    from . import platform_env
    base = platform_env.local_now().strftime("%Y%m%d-%H%M%S")
    if design_dir is None:
        return base
    taken = {s.get("id") for s in load_sweeps(design_dir)}
    sid, k = base, 1
    while sid in taken:
        k += 1
        sid = f"{base}-{k}"
    return sid


# Serialises every load-modify-write of a sweeps file: the sweep worker
# records each point while a request thread may be recording the manifest.
_sweeps_lock = threading.RLock()


def _write_sweeps(p: Path, sweeps: List[Dict[str, Any]]) -> None:
    # A unique temp name per write, so two writers never share one file.
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps({"sweeps": sweeps}, indent=2), encoding="utf-8")
        tmp.replace(p)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def record_sweep(design_dir: str | Path, sweep: Dict[str, Any]) -> None:
    """Append (or replace by id) a sweep manifest. Best-effort; never raises.
    Point results already recorded under the same id are kept when ``sweep``
    brings none of its own."""
    try:
        with _sweeps_lock:
            p = _sweeps_path(design_dir)
            existing = load_sweeps(design_dir)
            sid = sweep.get("id")
            prior = next((s for s in existing if s.get("id") == sid), None)
            sweep = dict(sweep)
            if prior and prior.get("results") and "results" not in sweep:
                sweep["results"] = prior["results"]
            existing = [s for s in existing if s.get("id") != sid]
            existing.insert(0, sweep)
            # Keep the file bounded.
            existing = existing[:200]
            _write_sweeps(p, existing)
    except Exception:
        pass


def forget_sweep(design_dir: str | Path, sweep_id: str) -> None:
    """Drop the manifest of a sweep that never started. Best-effort."""
    try:
        with _sweeps_lock:
            existing = load_sweeps(design_dir)
            kept = [s for s in existing if s.get("id") != sweep_id]
            if len(kept) != len(existing):
                _write_sweeps(_sweeps_path(design_dir), kept)
    except Exception:
        pass


def record_point(design_dir: str | Path, sweep_id: str, tag: str, result: Dict[str, Any]) -> None:
    """Note how one point of a sweep ended in its manifest (``results``), so
    the outcome survives a reload and a restart. Best-effort; never raises."""
    try:
        with _sweeps_lock:
            for s in load_sweeps(design_dir):
                if s.get("id") == sweep_id:
                    res = dict(s.get("results") or {})
                    res[tag] = dict(result)
                    s["results"] = res
                    record_sweep(design_dir, s)
                    return
    except Exception:
        pass


def stamp_run(run_dir: str | Path, sweep_id: str, values: Dict[str, Any]) -> None:
    """Mark a run folder as a sweep point (``gui-run.json`` ``sweep``), so the
    Runs table can group it and name its origin. Best-effort."""
    try:
        p = Path(run_dir) / "gui-run.json"
        if not p.parent.is_dir():
            return
        doc = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        if not isinstance(doc, dict):
            doc = {}
        doc["sweep"] = {"id": sweep_id, "values": dict(values)}
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)
    except Exception:
        pass


def unique_base_tag(design_dir: str | Path, base_tag: str, n: int) -> str:
    """Return a base tag whose ``dse-<base>-NN`` run dirs don't already exist.

    DSE used a deterministic ``dse-<base>-NN`` scheme with ``overwrite=True`` — a
    second sweep with the same base silently destroyed the first sweep's run
    dirs. Here we bump the base (``<base>``, ``<base>-2``, …) until none of the N
    target run dirs collide, so prior sweeps are preserved by default.
    """
    runs_root = Path(design_dir) / "runs"
    base = base_tag or "sweep"
    candidate = base
    suffix = 1
    while True:
        tags = [f"dse-{candidate}-{i:02d}" for i in range(n)]
        if not runs_root.is_dir() or not any((runs_root / t).exists() for t in tags):
            return candidate
        suffix += 1
        candidate = f"{base}-{suffix}"


def system_resources() -> Dict[str, Any]:
    """Best-effort host memory/CPU snapshot used to warn before a DSE sweep.

    Each DSE config is a *full* RTL→GDS flow; OpenROAD detailed routing + STA
    peak at several GB of RAM. On a machine with little free RAM and **no swap**,
    a single heavy run can exhaust memory and freeze the desktop session — which
    is exactly what makes an unattended N-run sweep risky. We surface the numbers
    so the GUI can warn (it never blocks the user).

    Uses ``psutil`` — already a LibreLane dependency (see ``runner.py`` /
    ``manualcmd.py``), so no new dependency is added. Degrades gracefully (numbers
    become ``None``) when it can't be read. Cross-platform.
    """
    info: Dict[str, Any] = {
        "ok": False, "total_gb": None, "available_gb": None,
        "swap_gb": None, "cores": None, "risk": "unknown", "reasons": [],
    }
    try:
        import psutil  # LibreLane dependency, not a new one

        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        info["total_gb"] = round(vm.total / 2 ** 30, 1)
        info["available_gb"] = round(vm.available / 2 ** 30, 1)
        info["swap_gb"] = round(sw.total / 2 ** 30, 1)
        info["cores"] = psutil.cpu_count(logical=True)
        info["ok"] = True
    except Exception:
        info["cores"] = os.cpu_count()
        return info

    reasons: List[str] = []
    avail = info["available_gb"]
    swap = info["swap_gb"]
    # Heuristics tuned for a real RTL→GDS flow (routing/STA peak ~2–6 GB).
    if avail is not None and avail < 4:
        reasons.append(f"only {avail} GB RAM free right now")
    if swap == 0:
        reasons.append("no swap configured (a memory spike hangs the machine "
                       "instead of slowing down)")
    if info["total_gb"] is not None and info["total_gb"] < 16:
        reasons.append(f"{info['total_gb']} GB total RAM is tight for back-to-back flows")
    if (avail is not None and avail < 3) or (swap == 0 and (info["total_gb"] or 0) < 12):
        info["risk"] = "high"
    elif reasons:
        info["risk"] = "elevated"
    else:
        info["risk"] = "ok"
    info["reasons"] = reasons
    return info


@lru_cache(maxsize=1)
def _known_var_names() -> frozenset:
    return frozenset(v["name"] for v in introspect.list_variables())


def _format_value(v: Any) -> str:
    """Format a sweep value as a LibreLane override string (permissive)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def expand_sweep(spec: Dict[str, Any]) -> List[Dict[str, str]]:
    """Expand a sweep spec into the list of per-run override dicts.

    ``spec = {"axes":[{"var":"FP_CORE_UTIL","values":[40,50,60]}, ...],
    "mode":"grid|list"}``. ``grid`` = cartesian product; ``list`` = zipped
    (all axes must share length). Validates every ``var`` against
    ``introspect.list_variables()`` and enforces :data:`MAX_COMBOS`. Raises
    ``ValueError`` on a bad spec so the endpoint returns a clear 400.
    """
    axes = spec.get("axes") or []
    mode = spec.get("mode") or "grid"
    if not axes:
        raise ValueError("sweep has no axes")
    names = _known_var_names()
    for ax in axes:
        var = ax.get("var")
        if not var:
            raise ValueError("an axis is missing 'var'")
        if names and var not in names:
            raise ValueError(f"unknown config variable '{var}'")
        if not ax.get("values"):
            raise ValueError(f"axis '{var}' has no values")

    if mode == "list":
        n = len(axes[0]["values"])
        if any(len(ax["values"]) != n for ax in axes):
            raise ValueError("list mode requires every axis to have the same number of values")
        combos = [[ax["values"][i] for ax in axes] for i in range(n)]
    else:
        combos = list(itertools.product(*[ax["values"] for ax in axes]))

    if len(combos) > MAX_COMBOS:
        raise ValueError(f"sweep expands to {len(combos)} runs (max {MAX_COMBOS}); narrow it down")

    out: List[Dict[str, str]] = []
    for combo in combos:
        out.append({axes[i]["var"]: _format_value(combo[i]) for i in range(len(axes))})
    return out


def dse_run_tags(base_tag: str, n: int) -> List[str]:
    """Deterministic, unique per-config run tags: ``dse-<base>-<NN>``."""
    base = base_tag or "sweep"
    return [f"dse-{base}-{i:02d}" for i in range(n)]


# Short names for the variables people sweep most, so a point's run is named by
# what it tried: sweep-util-65, sweep-clk-12.5, sweep-synth-AREA_0.
_SHORT = {
    "FP_CORE_UTIL": "util",
    "CLOCK_PERIOD": "clk",
    "PL_TARGET_DENSITY_PCT": "density",
    "SYNTH_STRATEGY": "synth",
    "FP_ASPECT_RATIO": "aspect",
    "GRT_ADJUSTMENT": "grtadj",
}


def _slug(v: Any) -> str:
    out = "".join(c if (c.isalnum() or c in ".-") else "_" for c in str(v).strip())
    return out.strip("_") or "x"


def sweep_run_tags(design_dir: str | Path, overrides_list: Sequence[Dict[str, Any]]) -> List[str]:
    """One run name per sweep point, named by the values it tries
    (``sweep-util-65``; two variables: ``sweep-util-50-clk-10``). A name that
    already has a run folder, or repeats within the sweep, gets ``-2``, ``-3``…
    so an earlier sweep's runs are never overwritten."""
    runs_root = Path(design_dir) / "runs"
    used: set = set()
    tags: List[str] = []
    for ov in overrides_list:
        parts = []
        for var, val in ov.items():
            parts.append(_SHORT.get(var) or _slug(str(var).lower()))
            parts.append(_slug(val))
        base = ("sweep-" + "-".join(parts))[:80]
        tag, k = base, 1
        while tag in used or (runs_root / tag).exists():
            k += 1
            tag = f"{base}-{k}"
        used.add(tag)
        tags.append(tag)
    return tags


def point_outcome(run_dir: str | Path) -> Dict[str, Any]:
    """How one sweep point really ended, from the run folder (the same reading
    the Flow page uses, runexplain): ``{ok, kind, stage, step, reason}``.
    ``ok`` only for a run that reached the end with nothing raised; a run that
    merely launched is not a pass."""
    try:
        from . import runexplain
        rx = runexplain.explain_run(run_dir)
    except Exception as ex:  # pragma: no cover - unreadable folder
        return {"ok": False, "kind": "unknown", "stage": None, "step": None,
                "reason": f"could not read the run: {ex}"}
    kind = rx.get("kind")
    card = rx.get("card") or {}
    step = rx.get("step") or {}
    reason = None
    if kind == "halted":
        reason = card.get("title") or ((rx.get("errors") or [None])[0])
    elif kind == "checks-failed":
        rc = rx.get("raised_checkers") or []
        names = [str((r.get("id") if isinstance(r, dict) else r) or "").replace("Checker.", "") for r in rc[:3]]
        reason = "sign-off checks failed" + (": " + ", ".join(n for n in names if n) if names else "")
    elif kind == "stopped":
        reason = "stopped"
    elif kind == "incomplete":
        reason = "ended before the last step"
    return {"ok": kind == "clean", "kind": kind, "stage": rx.get("stage"),
            "step": step.get("id") or step.get("dir"), "reason": reason}


class DseJob:
    """A sequential queue of runs over an expanded override list.

    Drives the shared :class:`runner.FlowRunner` one config at a time, waiting
    for each to finish (``runner.running`` falls) before starting the next.
    Emits ``dse_config_started`` / ``dse_config_done`` / ``dse_done`` on the bus
    so the SPA can show queue progress. Cancellation stops the active run and
    drops the rest. Runs in a daemon thread.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()
        self.queued: List[str] = []
        self.running_tag: Optional[str] = None
        self.done: List[str] = []
        self.failed: List[str] = []
        # tag -> {ok, kind, stage, step, reason, values}: how each point ended.
        self.results: Dict[str, Dict[str, Any]] = {}
        self.sweep_id: Optional[str] = None
        self.total = 0
        self.started_at: Optional[float] = None
        self._on_point = None
        self.stop_when_good = False
        self.stopped_early = False

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "active": self.active,
                "queued": list(self.queued),
                "running": self.running_tag,
                "done": list(self.done),
                "failed": list(self.failed),
                "results": {k: dict(v) for k, v in self.results.items()},
                "sweep_id": self.sweep_id,
                "total": self.total,
                "started_at": self.started_at,
                "stopped_early": self.stopped_early,
            }

    def start(self, *, start_one, overrides_list: Sequence[Dict[str, str]],
              tags: Sequence[str], sweep_id: Optional[str] = None,
              on_point=None, stop_when_good: bool = False) -> Dict[str, Any]:
        """Begin the queue. ``start_one(tag, overrides)`` runs one point through
        the runner and blocks until it ends; it returns the point's outcome
        (``{ok, kind, stage, step, reason}``, see :func:`point_outcome`) or a
        bare bool. ``on_point(tag, result)`` is called after each point (the
        route persists results into the sweep manifest with it). Returns
        ``{ok, count, run_tags}``."""
        with self._lock:
            if self.active:
                return {"ok": False, "error": "a sweep is already running"}
            self._cancel.clear()
            self.queued = list(tags)
            self.done = []
            self.failed = []
            self.results = {}
            self.sweep_id = sweep_id
            self.total = len(tags)
            self.started_at = time.time()
            self._on_point = on_point
            self.stop_when_good = bool(stop_when_good)
            self.stopped_early = False
            self.running_tag = None
            self._thread = threading.Thread(
                target=self._run, args=(start_one, list(overrides_list), list(tags)),
                daemon=True, name="librelane.gui.DseJob",
            )
            self._thread.start()
        return {"ok": True, "count": len(tags), "run_tags": list(tags)}

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        """Stop was asked for the current queue."""
        return self._cancel.is_set()

    def _run(self, start_one, overrides_list, tags) -> None:
        for i, tag in enumerate(tags):
            if self._cancel.is_set():
                break
            with self._lock:
                self.running_tag = tag
                if tag in self.queued:
                    self.queued.remove(tag)
            events.publish("dse_config_started", {"tag": tag, "index": i, "total": len(tags),
                                                  "overrides": overrides_list[i]})
            res: Dict[str, Any]
            try:
                out = start_one(tag, overrides_list[i])
                # A launched run is not a passed run: the closure reports how
                # the point really ended. A bare bool is accepted for callers
                # that only know whether it ran.
                res = dict(out) if isinstance(out, dict) else {"ok": bool(out), "kind": None,
                                                               "reason": None if out else "did not start"}
            except Exception as ex:  # pragma: no cover - depends on live runner
                events.publish("log", {"message": f"Sweep: could not run {tag}: {ex}"})
                res = {"ok": False, "kind": "error", "reason": f"could not start: {ex}"}
            if self._cancel.is_set() and not res.get("ok"):
                res.setdefault("kind", "stopped")
                res["reason"] = res.get("reason") or "stopped"
            res["values"] = dict(overrides_list[i])
            ok = bool(res.get("ok"))
            with self._lock:
                (self.done if ok else self.failed).append(tag)
                self.results[tag] = res
                self.running_tag = None
            if self._on_point:
                try:
                    self._on_point(tag, res)
                except Exception:  # pragma: no cover - persistence is best effort
                    pass
            events.publish("dse_config_done", {"tag": tag, "ok": ok, "index": i, "total": len(tags),
                                               "kind": res.get("kind"), "stage": res.get("stage"),
                                               "reason": res.get("reason")})
            if ok and self.stop_when_good and i + 1 < len(tags):
                # "Stop when one is good enough": timing met and every check
                # clean (a "clean" run); the rest are dropped, not run.
                with self._lock:
                    self.stopped_early = True
                    self.queued = []
                break
        events.publish("dse_done", {"done": list(self.done), "failed": list(self.failed),
                                    "cancelled": self._cancel.is_set(), "sweep_id": self.sweep_id,
                                    "stopped_early": self.stopped_early})
        with self._lock:
            self.running_tag = None
            self.queued = []


# Process-wide singleton (one engine -> one queue at a time).
job = DseJob()
