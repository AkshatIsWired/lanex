"""End-to-end RTL->GDS smoke test.

This drives LanEx's *real* local-run path — scaffold a design with
``scaffold.create_project`` (the same generator the New-project wizard uses),
then run it through ``runner.FlowRunner`` in ``local`` mode (the same code path
a GUI "Run flow" click takes) — and asserts a GDSII stream lands in ``final/``.

It needs the full EDA toolchain (Yosys, OpenROAD, Magic, KLayout, Netgen) *and*
an enabled sky130 PDK, so it is **gated behind ``LANEX_RTL2GDS=1``** and skips
everywhere else. The CI ``rtl2gds`` job sets that variable inside the official
``ghcr.io/librelane/librelane`` image (which ships the toolchain) after enabling
the PDK; the normal fast test matrix never touches it.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

_ENABLED = os.environ.get("LANEX_RTL2GDS") == "1"

# A Classic sky130 run of the tiny counter is a few minutes on a 2-core CI
# runner; give generous head-room so a slow runner never flakes on the wait.
_DEADLINE_SECONDS = int(os.environ.get("LANEX_RTL2GDS_TIMEOUT", "2700"))


@pytest.mark.skipif(
    not _ENABLED,
    reason="full toolchain + PDK required; set LANEX_RTL2GDS=1 inside the librelane image",
)
def test_counter_rtl_to_gds(tmp_path: Path) -> None:
    from librelane.flows import Flow

    from lanex.controller import runner as runner_mod
    from lanex.controller import scaffold

    pdk = os.environ.get("LANEX_RTL2GDS_PDK", "sky130A")
    scl = os.environ.get("LANEX_RTL2GDS_SCL", "sky130_fd_sc_hd")
    pdk_root = os.environ.get("PDK_ROOT") or None

    # 1. Scaffold the smallest design that still exercises the whole flow, using
    #    LanEx's own generator (proves the rendered config.json is run-valid).
    dest = tmp_path / "counter"
    res = scaffold.create_project(
        dest_dir=str(dest),
        template="counter",
        top="counter",
        pdk=pdk,
        scl=scl,
        clock_period=10.0,
    )
    assert res.get("ok"), f"scaffold failed: {res}"
    design_dir = Path(res["design_dir"])
    config = design_dir / "config.json"
    assert config.is_file(), "scaffold did not write config.json"

    # 2. Drive the real GUI run path: Classic flow, local (in-process) mode.
    flow_factory = Flow.factory.get("Classic")
    assert flow_factory is not None, "Classic flow is not registered"

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
    assert started.get("ok"), f"runner refused to start: {started}"

    # 3. Wait for the worker thread to finish.
    deadline = time.time() + _DEADLINE_SECONDS
    while runner.running and time.time() < deadline:
        time.sleep(3)
    assert not runner.running, f"flow did not finish within {_DEADLINE_SECONDS}s"
    assert runner.error is None, f"flow errored: {runner.error}"

    run_dir = Path(runner.run_dir or "")
    assert run_dir.is_dir(), f"no run dir produced (got {runner.run_dir!r})"

    # 4. A complete run must stream out a GDSII in final/.
    gds = sorted(run_dir.glob("final/**/*.gds")) or sorted(run_dir.glob("**/final/**/*.gds"))
    assert gds, f"no GDS produced under {run_dir} (steps: {runner.step_statuses})"
    assert gds[0].stat().st_size > 0, f"GDS is empty: {gds[0]}"

    # 5. Metrics must exist and parse (locks the round-27 non-finite-JSON fix:
    #    a bare Infinity/NaN here would break the browser's JSON.parse).
    metrics = run_dir / "final" / "metrics.json"
    assert metrics.is_file(), "final/metrics.json missing"
    data = json.loads(metrics.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and data, "metrics.json did not parse to a non-empty object"

    # 6. No step ended in failure.
    failed = {k: v for k, v in (runner.step_statuses or {}).items() if v == "failed"}
    assert not failed, f"steps failed: {failed}"
