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


def new_sweep_id() -> str:
    """A sortable, collision-resistant sweep id (``YYYYMMDD-HHMMSS``)."""
    return time.strftime("%Y%m%d-%H%M%S", time.localtime())


def record_sweep(design_dir: str | Path, sweep: Dict[str, Any]) -> None:
    """Append (or replace by id) a sweep manifest. Best-effort; never raises."""
    try:
        p = _sweeps_path(design_dir)
        existing = load_sweeps(design_dir)
        sid = sweep.get("id")
        existing = [s for s in existing if s.get("id") != sid]
        existing.insert(0, sweep)
        # Keep the file bounded.
        existing = existing[:200]
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps({"sweeps": existing}, indent=2), encoding="utf-8")
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
            }

    def start(self, *, start_one, overrides_list: Sequence[Dict[str, str]],
              tags: Sequence[str]) -> Dict[str, Any]:
        """Begin the queue. ``start_one(tag, overrides) -> bool`` starts a single
        run through the runner (returns whether it started). ``wait_idle`` is
        polled by the worker via ``start_one`` semantics (the caller wires the
        runner). Returns ``{ok, count, run_tags}``."""
        with self._lock:
            if self.active:
                return {"ok": False, "error": "a DSE job is already running"}
            self._cancel.clear()
            self.queued = list(tags)
            self.done = []
            self.failed = []
            self.running_tag = None
            self._thread = threading.Thread(
                target=self._run, args=(start_one, list(overrides_list), list(tags)),
                daemon=True, name="librelane.gui.DseJob",
            )
            self._thread.start()
        return {"ok": True, "count": len(tags), "run_tags": list(tags)}

    def cancel(self) -> None:
        self._cancel.set()

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
            ok = False
            try:
                ok = bool(start_one(tag, overrides_list[i]))
            except Exception as ex:  # pragma: no cover - depends on live runner
                events.publish("log", {"message": f"DSE: failed to start {tag}: {ex}"})
                ok = False
            with self._lock:
                (self.done if ok else self.failed).append(tag)
                self.running_tag = None
            events.publish("dse_config_done", {"tag": tag, "ok": ok, "index": i, "total": len(tags)})
        events.publish("dse_done", {"done": list(self.done), "failed": list(self.failed),
                                    "cancelled": self._cancel.is_set()})
        with self._lock:
            self.running_tag = None


# Process-wide singleton (one engine -> one queue at a time).
job = DseJob()
