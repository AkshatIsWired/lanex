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
"""Learned per-step durations → a live ETA for a running flow.

A bare ``done/total`` progress bar is useless when step durations span 3 orders
of magnitude (lint << detailed routing). We keep a tiny rolling history of how
long each ``Step.id`` actually took, keyed by id, in a per-user JSON file
(``~/.librelane-gui/step-timings.json`` — never in the design dir). The runner
estimates remaining time as the sum of the best estimate for each not-yet-done
step (learned median, else the current run's average of finished steps). Pure
stdlib; degrades to "no estimate" with zero history. Cross-platform.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Dict, Iterable, List, Optional

_LOCK = threading.Lock()
_ALPHA = 0.4  # EWMA weight on the newest observation


def _home() -> Path:
    from . import platform_env
    return platform_env.home()


def _store_path() -> Path:
    return _home() / "step-timings.json"


def load() -> Dict[str, Dict[str, float]]:
    p = _store_path()
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def record(step_id: str, seconds: float) -> None:
    """Fold one observed duration into the EWMA for *step_id*. Best-effort."""
    if not step_id or seconds is None or seconds < 0:
        return
    with _LOCK:
        try:
            data = load()
            cur = data.get(step_id) or {}
            prev = cur.get("ewma")
            ewma = seconds if prev is None else (_ALPHA * seconds + (1 - _ALPHA) * prev)
            data[step_id] = {"ewma": round(ewma, 3), "count": int(cur.get("count", 0)) + 1}
            p = _store_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            tmp.replace(p)
        except Exception:
            pass


def estimate_remaining(remaining_ids: Iterable[str],
                       observed: Optional[List[float]] = None) -> Optional[float]:
    """Best-effort seconds remaining for the not-yet-done steps.

    For each remaining step, use its learned EWMA; if a step has no history, fall
    back to the mean of this run's already-observed durations. Returns ``None``
    when there is nothing to base any estimate on (first run, no history).
    """
    ids = list(remaining_ids)
    if not ids:
        return 0.0
    data = load()
    obs = [d for d in (observed or []) if d is not None and d >= 0]
    run_avg = (sum(obs) / len(obs)) if obs else None
    total = 0.0
    have_any = False
    for sid in ids:
        ewma = (data.get(sid) or {}).get("ewma")
        est = ewma if ewma is not None else run_avg
        if est is None:
            continue
        total += est
        have_any = True
    return round(total, 1) if have_any else None
