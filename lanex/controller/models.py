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
"""Typed shapes for the GUI controller public API.

Every dataclass here is JSON-serialisable (after :func:`controller.introspect.convert_value`)
and is what flows over the stdlib HTTP boundary to the SPA.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    Optional,
    Tuple,
)


class EventType(str, Enum):
    """The event types the SSE stream emits."""

    LOG = "log"
    STEP_STARTED = "step_started"
    STEP_DONE = "step_done"
    STEP_SKIPPED = "step_skipped"
    STEP_FAILED = "step_failed"
    PROGRESS = "progress"
    FLOW_DONE = "flow_done"
    ERROR = "error"
    INFO = "info"
    # Container run mode — pre-step preparation milestones (image pull, container
    # start, PDK resolution) so the long silence before step 1 is explained.
    PHASE = "phase"
    # Phase 2 — design-space exploration queue progress.
    DSE_CONFIG_STARTED = "dse_config_started"
    DSE_CONFIG_DONE = "dse_config_done"
    DSE_DONE = "dse_done"
    # Phase 3 — functional simulation.
    SIM_STARTED = "sim_started"
    SIM_DONE = "sim_done"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class ViolationSeverity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class VariableInfo:
    """One :class:`librelane.config.Variable` rendered for the UI form."""

    name: str
    type: str
    description: str
    default: Any
    units: Optional[str]
    pdk: bool
    optional: bool
    deprecated_names: List[str] = field(default_factory=list)
    # Allowed values for Literal/Enum-typed variables; empty for free-form types.
    # Drives a real <select> in the config form instead of a text box.
    choices: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class DesignFormatInfo:
    id: str
    extension: str
    full_name: str
    multiple: bool
    alts: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class StepInfo:
    id: str
    qualified: str  # module path; reproducible export needs this
    inputs: List[str]
    outputs: List[str]
    config_vars: List[str]
    help_md: str
    long_name: str


@dataclass(frozen=True)
class FlowInfo:
    name: str
    qualified: str
    steps: List[str]
    gating_config_vars: Dict[str, List[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class RunSummary:
    tag: str
    run_dir: str
    success: bool
    flow: str
    pdk: Optional[str]
    scl: Optional[str]
    started_at: Optional[str]
    step_count: int
    steps_done: int
    steps_failed: int
    wall_time_s: Optional[float]
    key_metrics: Dict[str, Any] = field(default_factory=dict)
    imported: bool = False
    pinned: bool = False


@dataclass(frozen=True)
class MetricSet:
    path: str  # filesystem path to metrics.json
    values: Dict[str, Any]


@dataclass(frozen=True)
class RunView:
    tag: str
    run_dir: str
    design_dir: Optional[str] = None
    state: Dict[str, Any] = field(default_factory=dict)  # design-format-id -> path / dict / list
    metrics: MetricSet = field(default_factory=lambda: MetricSet(path="", values={}))
    summaries: List[str] = field(default_factory=list)  # human-readable per-step summaries


@dataclass(frozen=True)
class Event:
    type: EventType
    seq: int
    ts: float
    payload: Dict[str, Any]
    tag: Optional[str] = None


@dataclass(frozen=True)
class PDK:
    name: str
    root: str
    variants: List[Tuple[str, str]]  # [(variant_label, scl_id), ...]
    ready: bool
    missing: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class Violation:
    """One DRC violation as the UI sees it."""

    category: str
    layer: str
    rule: str
    description: str
    boxes: List[Dict[str, str]]  # [{"llx":..,"lly":..,"urx":..,"ury":..}]


@dataclass(frozen=True)
class DRCReport:
    module: str
    bbox_count: int
    violations: List[Violation]


@dataclass(frozen=True)
class AdvisoryCard:
    """A plain-English explanation for a failed step or alert."""

    title: str
    what: str
    why: str
    remediations: List[str]  # ranked list of remediations
    fix: List[Dict[str, str]] = field(default_factory=list)  # [{var: value}, ...]


def _jsonable(o: Any) -> Any:
    """Recursively convert dataclass/Decimal/Path/Enum/set to JSON primitives.

    Notes
    -----
    * ``str`` and ``bytes`` are NOT iterated; iterating them turns each
      character into a numeric type and is a footgun (verified live).
    * ``Sequence`` (the ABC) is intentionally not in the iterable check; it's
      too broad — strings (``Sequence[str]``) match it.
    * Depth-bounded recursion + ``_seen`` guard against cyclic graphs in
      librelane objects.
    """
    return _convert(o, 0, _seen=set(), depth=20)


def _convert(v: Any, d: int, *, _seen: set, depth: int) -> Any:
    if v is None or isinstance(v, (bool, int, float, str, bytes)):
        if isinstance(v, bytes):
            try:
                return v.decode("utf-8", errors="replace")
            except Exception:
                return repr(v)
        return v
    if d > depth:
        return "<max-depth>"
    if id(v) in _seen:
        return "<cycle>"
    _seen.add(id(v))
    try:
        if isinstance(v, Decimal):
            try:
                # Return the float unconditionally (incl. NaN/±inf). Both wire
                # transports now run every payload through json_safe(), which
                # renders non-finites as "NaN"/"Infinity" strings — the same
                # presentation as a plain non-finite float. Previously a
                # Decimal("NaN") became JSON null here, silently indistinguishable
                # from an absent metric and inconsistent with the REST path.
                return float(v)
            except Exception:
                return str(v)
        try:
            import numpy as np
            if isinstance(v, np.integer): return int(v)
            if isinstance(v, np.floating): return float(v)
            if isinstance(v, np.ndarray): return v.tolist()
        except ImportError:
            pass
        if isinstance(v, Path):
            return str(v)
        if isinstance(v, Enum):
            return str(v.value)
        if isinstance(v, Mapping):
            return {
                str(_convert(k, d + 1, _seen=_seen, depth=depth)): _convert(val, d + 1, _seen=_seen, depth=depth)
                for k, val in v.items()
            }
        if isinstance(v, (list, tuple, set, frozenset)):
            return [_convert(item, d + 1, _seen=_seen, depth=depth) for item in v if not isinstance(item, type)]
        try:
            from dataclasses import is_dataclass

            if is_dataclass(v):
                return {
                    k: _convert(val, d + 1, _seen=_seen, depth=depth)
                    for k, val in asdict(v).items()
                }
        except Exception:
            pass
        try:
            return {
                k: _convert(val, d + 1, _seen=_seen, depth=depth)
                for k, val in vars(v).items()
                if not k.startswith("_")
            }
        except Exception:
            pass
        return str(v)
    finally:
        _seen.discard(id(v))


def to_json(obj: Any) -> Any:
    """Public entry for JSON conversion."""
    return _jsonable(obj)


__all__ = [
    "Event",
    "EventType",
    "StepStatus",
    "ViolationSeverity",
    "VariableInfo",
    "DesignFormatInfo",
    "StepInfo",
    "FlowInfo",
    "RunSummary",
    "RunView",
    "MetricSet",
    "PDK",
    "Violation",
    "DRCReport",
    "AdvisoryCard",
    "to_json",
]
