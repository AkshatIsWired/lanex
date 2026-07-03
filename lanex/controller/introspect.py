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
"""Introspect LibreLane's metadata into JSON-serialisable shapes.

The `:mod:` controller.introspect` module is the public driver introspection
surface. Anything the SPA needs is either serialised here or fetched live.
"""
from __future__ import annotations

import enum
import inspect
import re
import typing
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

# Vendor LibreLane. Deferred to module level so that any import-time failure
# surfaces at the first read (not at server boot), keeping the core CLI intact.
_LIBRELANE_AVAILABLE = False
try:
    from librelane.config import Variable
    from librelane.steps import Step
    from librelane.flows import Flow
    from librelane.state import DesignFormat
    _LIBRELANE_AVAILABLE = True
except ImportError:
    Variable = None
    Step = None
    Flow = None
    DesignFormat = None

from .models import DesignFormatInfo, FlowInfo, StepInfo, VariableInfo, to_json

# A bare-bones unqualified type renderer. LibreLane exposes :func:`repr_type`
# in ``variable.py`` but it would pull in MyST/dropdown machinery we don't need.
# We get 95% of the value with four canonical cases.

_LITERAL_RX = re.compile(r"Literal\[(.*)\]")
_UNION_RX = re.compile(r"Union\[(.*)\]")
_LIST_RX = re.compile(r"List\[(.+)\]")
_OPTIONAL_RX = re.compile(r"Optional\[(.+)\]")


def _stringify_type(tp: Any) -> str:
    """Render a Python type annotation as a UI-friendly string.

    Handles Literal, Optional, List, Union, dict, tuples, Path, enums, and falls
    back to :func:`repr` for the rest. No MyST/dropdown side effects.
    """
    if tp in (None, type(None)):
        return "None"
    s = str(tp)
    # Strip 'typing.' prefixes.
    s = re.sub(r"typing\.", "", s)

    # Strip Optional wrappers last.
    while True:
        m = _OPTIONAL_RX.match(s)
        if not m:
            break
        s = m.group(1)
    m = _LITERAL_RX.match(s)
    if m:
        return "Literal"
    m = _LIST_RX.match(s)
    if m:
        return f"List[{_stringify_type(m.group(1))}]"
    m = _UNION_RX.match(s)
    if m:
        names = [n.strip() for n in m.group(1).split(",")]
        return " | ".join(_stringify_type(n) for n in names)
    # Clean up common alias syntax.
    s = s.replace("~", "")
    s = re.sub(r"<.*>$", "", s)
    return s.split(".")[-1].split("[")[0]


def _choices_of(tp: Any) -> List[str]:
    """Extract the allowed values of a ``Literal``/``Enum`` (or ``Optional`` of
    one), so the UI can render a dropdown. Empty list for free-form types.
    """
    try:
        origin = typing.get_origin(tp)
        args = typing.get_args(tp)
        if origin is typing.Union:  # includes Optional[...]
            out: List[str] = []
            for a in args:
                if a is type(None):
                    continue
                out.extend(_choices_of(a))
            return out
        if origin is typing.Literal:
            return [str(a) for a in args]
        if isinstance(tp, type) and issubclass(tp, enum.Enum):
            return [str(e.value) for e in tp]
    except Exception:
        pass
    return []


def _stringify_default(default: Any) -> Any:
    """Convert a Variable default to JSON-serialisable."""
    if default is None:
        return None
    if isinstance(default, (bool, int, float, str)):
        return default
    if isinstance(default, Decimal):
        # Use LibreLane's own canonical decimal string, NOT float(): a binary
        # float can shift what the user sees (e.g. 2.4 -> 2.3999999999999999 after
        # JS formatting). Display-only; the field is a text input either way (A9).
        return str(default)
    if isinstance(default, (list, tuple)):
        return [_stringify_default(x) for x in default]
    if isinstance(default, dict):
        return {str(k): _stringify_default(v) for k, v in default.items()}
    return str(default)


def _variable_to_info(v: Variable) -> VariableInfo:
    # `optional` may be a property or a plain attribute depending on the
    # LibreLane version. Read defensively.
    opt = v.optional
    if callable(opt):
        opt = opt()
    return VariableInfo(
        name=v.name,
        type=_stringify_type(v.type),
        description=v.description or "",
        default=_stringify_default(v.default),
        units=v.units,
        pdk=bool(v.pdk),
        optional=bool(opt),
        deprecated_names=list(v.deprecated_names or []),
        choices=_choices_of(v.type),
    )


@lru_cache(maxsize=None)
def list_variables() -> List[Dict[str, Any]]:
    """Return every known LibreLane Variable as a JSON-safe dict.

    Pulls from ``Variable.known_variable_names`` which is populated at
    class-definition time (i.e. on first librelane.steps import). This
    is the authoritative set a user can write into ``config.yaml``.
    """
    if not _LIBRELANE_AVAILABLE:
        return []
    out: List[Dict[str, Any]] = []
    for name in sorted(Variable.known_variable_names):
        # LibreLane doesn't expose a single reverse-lookup table; reconstruct
        # a tiny stub just by name. We rely on Step factories to give us
        # the real Variable objects via ``get_all_config_variables``.
        pass
    # The real source of truth is the global configurations + each Step's config_vars.
    seen: Dict[str, Variable] = {}
    
    try:
        from librelane.config.config import flow_common_variables, pad_variables, pdk_variables, scl_variables
        for var in flow_common_variables + pad_variables + pdk_variables + scl_variables:
            seen.setdefault(var.name, var)
    except Exception as ex:
        pass  # Fallback gracefully if librelane version lacks these

    for step_cls in _step_registry().values():
        try:
            for var in step_cls.get_all_config_variables():
                seen.setdefault(var.name, var)
        except Exception:
            continue
    for var in seen.values():
        out.append(to_json(_variable_to_info(var)))
    return out


@lru_cache(maxsize=None)
def list_metrics() -> List[Dict[str, Any]]:
    """Authoritative metric definitions from LibreLane's metric registry.

    Returns each metric's ``name`` plus ``higher_is_better`` / ``critical``
    flags (sourced from ``librelane.common.metrics.library``). LibreLane does
    not ship per-metric descriptions, so we expose only what is verifiable —
    the names and their pass/fail semantics. The UI groups them by the
    ``a__b__c`` prefix convention.
    """
    try:
        from librelane.common.metrics.metric import Metric  # type: ignore
        from librelane.common.metrics import library as _library  # noqa: F401  (registers metrics)
    except Exception:
        return []
    registry = getattr(Metric, "by_name", {}) or {}
    out: List[Dict[str, Any]] = []
    for name, m in registry.items():
        out.append(
            {
                "name": name,
                "higher_is_better": bool(getattr(m, "higher_is_better", True)),
                "critical": bool(getattr(m, "critical", False)),
            }
        )
    out.sort(key=lambda d: d["name"])
    return out


@lru_cache(maxsize=None)
def list_design_formats() -> List[Dict[str, Any]]:
    """All registered DesignFormats as JSON-safe dicts.

    De-dupes by id because alts point at the same DesignFormat object.
    Uses public ``.list()`` API when available; falls back to private
    ``__registry`` for older LibreLane versions.
    """
    if not _LIBRELANE_AVAILABLE:
        return []
    factory = DesignFormat.factory  # type: ignore[attr-defined]
    try:
        ids = factory.list()
        registry = {df_id: factory.get(df_id) for df_id in ids}
    except Exception:
        registry: Dict[str, Any] = (
            getattr(factory, "_DesignFormatFactory__registry", None)
            or getattr(factory, "_registry", None)
            or {}
        )
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for df in registry.values():
        if df.id in seen:
            continue
        seen.add(df.id)
        out.append(
            to_json(
                DesignFormatInfo(
                    id=df.id,
                    extension=df.extension,
                    full_name=df.full_name,
                    multiple=bool(df.multiple),
                    alts=list(df.alts or []),
                )
            )
        )
    out.sort(key=lambda d: d["id"])
    return out


def _step_registry() -> Dict[str, Type[Step]]:
    """Return the LibreLane Step type registry safely.

    ``Step.factory.__registry`` is named-mangled to ``_StepFactory__registry``
    because the class definition uses double-underscore prefix. Access it via
    :func:`getattr`, falling back to a name scan.
    """
    if not _LIBRELANE_AVAILABLE:
        return {}
    return (
        getattr(Step.factory, "_StepFactory__registry", None)
        or getattr(Step.factory, "_registry", None)
        or {}
    )


def _step_to_info(cls: Type[Step]) -> StepInfo:
    """Compress a Step class into a UI-friendly dict."""
    inputs = sorted({df.id for df in (cls.inputs or [])})
    outputs = sorted({df.id for df in (cls.outputs or [])})
    config_vars = sorted({v.name for v in cls.config_vars or []})
    try:
        help_md = cls.get_help_md() or ""
    except Exception as ex:  # pragma: no cover - helps in CI
        help_md = f"_(help unavailable: {ex})_"
    return StepInfo(
        id=cls.id,
        qualified=f"{cls.__module__}.{cls.__qualname__}",
        inputs=inputs,
        outputs=outputs,
        config_vars=config_vars,
        help_md=help_md,
        long_name=getattr(cls, "long_name", "") or cls.id,
    )


@lru_cache(maxsize=None)
def list_steps() -> List[Dict[str, Any]]:
    """All registered Step types, sorted by id."""
    raw_registry = _step_registry()
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for cls in raw_registry.values():
        if cls.id in seen:
            continue
        seen.add(cls.id)
        out.append(to_json(_step_to_info(cls)))
    out.sort(key=lambda d: d["id"])
    return out


def get_step(step_id: str) -> Optional[Dict[str, Any]]:
    if not _LIBRELANE_AVAILABLE:
        return None
    cls = Step.factory.get(step_id)
    if cls is None:
        return None
    return to_json(_step_to_info(cls))


def _display_name(cls: Any, fallback: str) -> str:
    name = getattr(cls, "name", None)
    if name is None:
        return fallback
    try:
        is_not_implemented = name is NotImplemented
    except Exception:  # pragma: no cover - defensive
        is_not_implemented = False
    if is_not_implemented:
        return fallback
    return name


@lru_cache(maxsize=None)
def list_flows() -> List[Dict[str, Any]]:
    """All registered Flow types, with their Steps (ids only).

    Falls back to the registry key for ``name`` when the class still carries
    ``name = NotImplemented`` (which is the case for built-in flows).
    """
    if not _LIBRELANE_AVAILABLE:
        return []
    factory = Flow.factory  # type: ignore[attr-defined]
    registry: Dict[str, Any] = (
        getattr(factory, "_FlowFactory__registry", None)
        or getattr(factory, "_registry", None)
        or {}
    )
    out: List[Dict[str, Any]] = []
    for label, cls in registry.items():
        steps = list(getattr(cls, "Steps", []) or [])
        display_name = _display_name(cls, label)
        out.append(
            to_json(
                FlowInfo(
                    name=display_name,
                    qualified=f"{cls.__module__}.{cls.__qualname__}",
                    steps=[s.id for s in steps],
                    gating_config_vars={
                        k: list(v) for k, v in (getattr(cls, "gating_config_vars", {}) or {}).items()
                    },
                )
            )
        )
    out.sort(key=lambda d: d["name"])
    return out


def get_flow(name: str) -> Optional[Dict[str, Any]]:
    if not _LIBRELANE_AVAILABLE:
        return None
    factory = Flow.factory  # type: ignore[attr-defined]
    registry: Dict[str, Any] = (
        getattr(factory, "_FlowFactory__registry", None)
        or getattr(factory, "_registry", None)
        or {}
    )
    for label, cls in registry.items():
        candidate_names = [
            getattr(cls, "name", None),
            label,
            cls.__qualname__,
        ]
        # ``NotImplemented`` is a sentinel value, not a missing name. Compare carefully.
        if any(n is not None and not (n is NotImplemented) and n == name for n in candidate_names):
            steps = list(getattr(cls, "Steps", []) or [])
            display_name = _display_name(cls, label)
            return to_json(
                FlowInfo(
                    name=display_name,
                    qualified=f"{cls.__module__}.{cls.__qualname__}",
                    steps=[s.id for s in steps],
                    gating_config_vars={
                        k: list(v) for k, v in (getattr(cls, "gating_config_vars", {}) or {}).items()
                    },
                )
            )
    return None
