#!/usr/bin/env python3
"""Differential leg L: lanex LOCAL-mode RTL->GDS on an already-copied design.

Runs INSIDE the official LibreLane image (launched by differential_run.py via
``docker run`` with the repo + workspace mounted at their identical host
paths — never a `container:` job; the nix image can't exec GitHub's injected
Node, and it ships no pip/pytest so this stays stdlib + PYTHONPATH).

Same honesty floor as scripts/ci_rtl2gds_run.py (which stays untouched — this
script is parameterized for the differential workspace instead of a tempdir):
flow finishes, no failed step, non-empty GDS in final/, metrics.json parses.

env: LANEX_LEG_DESIGN (design dir containing config.yaml), LANEX_LEG_TAG,
     LANEX_LEG_PDK / LANEX_LEG_SCL (default sky130A / sky130_fd_sc_hd),
     PDK_ROOT, LANEX_LEG_TIMEOUT (default 3000 s).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _fail(msg: str) -> int:
    print(f"leg-local FAILED: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    from librelane.flows import Flow

    from lanex.controller import runner as runner_mod

    design_dir = os.environ.get("LANEX_LEG_DESIGN", "")
    tag = os.environ.get("LANEX_LEG_TAG", "local")
    pdk = os.environ.get("LANEX_LEG_PDK", "sky130A")
    scl = os.environ.get("LANEX_LEG_SCL", "sky130_fd_sc_hd")
    pdk_root = os.environ.get("PDK_ROOT") or None
    deadline_s = int(os.environ.get("LANEX_LEG_TIMEOUT", "3000"))

    design = Path(design_dir)
    config = design / "config.yaml"
    if not config.is_file():
        return _fail(f"no config.yaml under {design_dir!r}")

    flow_factory = Flow.factory.get("Classic")
    if flow_factory is None:
        return _fail("Classic flow is not registered")

    runner = runner_mod.FlowRunner()
    started = runner.start(
        flow_factory=flow_factory,
        config_files=[str(config)],
        design_dir=str(design),
        pdk_root=pdk_root,
        pdk=pdk,
        scl=scl,
        tag=tag,
        run_mode="local",
        flow_name="Classic",
    )
    if not started.get("ok"):
        return _fail(f"runner refused to start: {started}")

    print(f"leg-local running (tag={tag}, deadline {deadline_s}s)...")
    deadline = time.time() + deadline_s
    while runner.running and time.time() < deadline:
        time.sleep(3)
    if runner.running:
        return _fail(f"flow did not finish within {deadline_s}s")
    if runner.error:
        return _fail(f"flow errored: {runner.error}")

    run_dir = design / "runs" / tag
    if not run_dir.is_dir():
        return _fail(f"no run dir at {run_dir}")
    gds = sorted(run_dir.glob("final/**/*.gds"))
    if not gds or gds[0].stat().st_size <= 0:
        return _fail(f"no non-empty GDS under {run_dir}/final")
    metrics = run_dir / "final" / "metrics.json"
    try:
        data = json.loads(metrics.read_text(encoding="utf-8"))
    except Exception as ex:  # noqa: BLE001
        return _fail(f"metrics.json did not parse: {ex}")
    if not isinstance(data, dict) or not data:
        return _fail("metrics.json did not parse to a non-empty object")
    failed = {k: v for k, v in (runner.step_statuses or {}).items() if v == "failed"}
    if failed:
        return _fail(f"steps failed: {failed}")
    print(f"leg-local PASSED: {gds[0]} ({gds[0].stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
