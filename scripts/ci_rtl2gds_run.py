#!/usr/bin/env python3
"""Complete RTL->GDS smoke run, driven through LanEx's own code path.

Runs INSIDE the official LibreLane image (see the `rtl2gds` job in
.github/workflows/ci.yml). Scaffolds the `counter` template with LanEx's own
generator, runs it through ``runner.FlowRunner`` in local mode (the real
"Run flow" code path a GUI click takes), and checks a GDSII lands in ``final/``.

No pytest / pip needed: the nix-based LibreLane image ships neither, but it does
ship python3 + librelane + ciel + the toolchain. We rely on that python plus the
LanEx source on ``PYTHONPATH`` (LanEx is pure-Python/stdlib, so it needs no
install). Exits 0 on success; prints the reason and exits non-zero on failure.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path


def _fail(msg: str) -> int:
    print(f"RTL->GDS smoke FAILED: {msg}", file=sys.stderr)
    return 1


def main() -> int:
    from librelane.flows import Flow

    from lanex.controller import runner as runner_mod
    from lanex.controller import scaffold

    pdk = os.environ.get("LANEX_RTL2GDS_PDK", "sky130A")
    scl = os.environ.get("LANEX_RTL2GDS_SCL", "sky130_fd_sc_hd")
    pdk_root = os.environ.get("PDK_ROOT") or None
    deadline_s = int(os.environ.get("LANEX_RTL2GDS_TIMEOUT", "2700"))

    # 1. Scaffold the smallest design that still exercises the whole flow with
    #    LanEx's own generator (proves the rendered config.json is run-valid).
    work = Path(tempfile.mkdtemp(prefix="lanex-rtl2gds-"))
    dest = work / "counter"
    res = scaffold.create_project(
        dest_dir=str(dest),
        template="counter",
        top="counter",
        pdk=pdk,
        scl=scl,
        clock_period=10.0,
    )
    if not res.get("ok"):
        return _fail(f"scaffold failed: {res}")
    design_dir = Path(res["design_dir"])
    config = design_dir / "config.json"
    if not config.is_file():
        return _fail("scaffold did not write config.json")
    print(f"scaffolded counter at {design_dir}")

    # 2. Drive the real GUI run path: Classic flow, local (in-process) mode.
    flow_factory = Flow.factory.get("Classic")
    if flow_factory is None:
        return _fail("Classic flow is not registered")

    runner = runner_mod.FlowRunner()
    started = runner.start(
        flow_factory=flow_factory,
        config_files=[str(config)],
        design_dir=str(design_dir),
        pdk_root=pdk_root,
        pdk=pdk,
        scl=scl,
        run_mode="local",
        flow_name="Classic",
    )
    if not started.get("ok"):
        return _fail(f"runner refused to start: {started}")

    # 3. Wait for the worker thread to finish.
    print(f"flow running (deadline {deadline_s}s)...")
    deadline = time.time() + deadline_s
    while runner.running and time.time() < deadline:
        time.sleep(3)
    if runner.running:
        return _fail(f"flow did not finish within {deadline_s}s")
    if runner.error:
        return _fail(f"flow errored: {runner.error}")

    run_dir = Path(runner.run_dir or "")
    if not run_dir.is_dir():
        return _fail(f"no run dir produced (got {runner.run_dir!r})")

    # 4. A complete run must stream out a non-empty GDSII in final/.
    gds = sorted(run_dir.glob("final/**/*.gds")) or sorted(run_dir.glob("**/final/**/*.gds"))
    if not gds:
        return _fail(f"no GDS under {run_dir} (steps: {runner.step_statuses})")
    if gds[0].stat().st_size <= 0:
        return _fail(f"GDS is empty: {gds[0]}")
    print(f"GDS produced: {gds[0]} ({gds[0].stat().st_size} bytes)")

    # 5. Metrics must exist and parse (locks the non-finite-JSON fix: a bare
    #    Infinity/NaN here would break the browser's JSON.parse).
    metrics = run_dir / "final" / "metrics.json"
    if not metrics.is_file():
        return _fail("final/metrics.json missing")
    try:
        data = json.loads(metrics.read_text(encoding="utf-8"))
    except Exception as ex:  # noqa: BLE001
        return _fail(f"metrics.json did not parse: {ex}")
    if not isinstance(data, dict) or not data:
        return _fail("metrics.json did not parse to a non-empty object")

    # 6. No step ended in failure.
    failed = {k: v for k, v in (runner.step_statuses or {}).items() if v == "failed"}
    if failed:
        return _fail(f"steps failed: {failed}")

    print("RTL->GDS smoke PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
