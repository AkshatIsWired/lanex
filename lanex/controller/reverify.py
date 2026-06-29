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
"""Targeted re-verification (Phase 2.A): re-run a single signoff step.

Re-running just ``Magic.DRC`` or ``OpenROAD.STAPostPNR`` against an existing run
takes seconds instead of a full RTL→GDS. This module is thin orchestration: it
validates the request and builds the exact single-step invocation. The actual
execution goes through the existing :class:`runner.FlowRunner` (container or
local) — no new run engine, no new dependency.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import container_run, introspect


@lru_cache(maxsize=1)
def _known_step_ids() -> frozenset:
    return frozenset(s["id"] for s in introspect.list_steps())


@lru_cache(maxsize=1)
def _known_var_names() -> frozenset:
    return frozenset(v["name"] for v in introspect.list_variables())


def validate(step_id: str, overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Reject unknown steps and unknown override variables (so a bad var can
    never be injected into a re-run). Returns ``{ok}`` or ``{ok: False, error}``.
    Skips a check only when introspection is unavailable (no librelane)."""
    steps = _known_step_ids()
    if steps and step_id not in steps:
        return {"ok": False, "error": f"unknown step id '{step_id}'"}
    names = _known_var_names()
    if names:
        for k in (overrides or {}):
            if k not in names:
                return {"ok": False, "error": f"unknown config variable '{k}'"}
    return {"ok": True}


def reverify_argv(
    run_dir: str | Path,
    step_id: str,
    *,
    overrides: Optional[Dict[str, Any]] = None,
    config_file: str | Path,
    design_dir: str | Path,
    pdk: Optional[str] = None,
    scl: Optional[str] = None,
    pdk_root: Optional[str] = None,
    flow: Optional[str] = None,
) -> List[str]:
    """Build the container ``--dockerized`` argv that re-runs only *step_id*
    against the existing run (``--run-tag <tag> -F step -T step``, continuing the
    prior state — no ``--overwrite`` so inputs like the netlist/ODB/SPEF persist).
    Delegates to :func:`container_run.build_dockerized_argv`."""
    tag = Path(run_dir).name
    return container_run.build_dockerized_argv(
        config_file=config_file,
        design_dir=design_dir,
        flow=flow,
        pdk=pdk,
        scl=scl,
        pdk_root=pdk_root,
        tag=tag,
        frm=step_id,
        to=step_id,
        overrides=overrides or {},
        overwrite=False,
    )


def reverify_kwargs(run_dir: str | Path, step_id: str,
                    *, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The runner-`start` kwargs for a single-step re-run continuing *run_dir*.
    The endpoint merges these into the existing run-start path."""
    return {
        "tag": Path(run_dir).name,
        "frm": step_id,
        "to": step_id,
        "overwrite": False,
        # Continue the existing run's saved state so the single step has its
        # inputs (netlist/ODB/SPEF). Without this, a local single-step re-run
        # starts from the design's initial state and the step has nothing to act
        # on. (Container mode resumes via --run-tag and ignores this.)
        "last_run": True,
        "config_overrides": dict(overrides or {}),
    }
