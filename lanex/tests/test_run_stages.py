"""history.run_stages: per-step metrics, runtime and memory for Analytics."""
import json
from pathlib import Path

from lanex.controller import history


def _step(run: Path, name: str, metrics=None, runtime=None, rss=None, done=True):
    d = run / name
    d.mkdir(parents=True)
    (d / "state_in.json").write_text("{}")
    if done:
        (d / "state_out.json").write_text(json.dumps({"metrics": metrics or {}}))
    if runtime is not None:
        (d / "runtime.txt").write_text(runtime)
    if rss is not None:
        stem = name.split("-", 1)[1]
        (d / f"{stem}.process_stats.json").write_text(json.dumps({"peak_resources": {"memory_rss": rss}}))
    return d


def _run(tmp_path: Path) -> Path:
    run = tmp_path / "design" / "runs" / "RUN_1"
    run.mkdir(parents=True)
    (run / "config.json").write_text(json.dumps({
        "DESIGN_NAME": "spm", "PDK": "sky130A", "STD_CELL_LIBRARY": "sky130_fd_sc_hd",
        "CLOCK_PERIOD": 10, "CLOCK_PORT": "clk", "meta": {"flow": "Classic"},
    }))
    (run / "flow.log").write_text(
        "Starting…\n"
        "Running 'Yosys.Synthesis' at 'runs/RUN_1/01-yosys-synthesis'…\n"
        "Running 'OpenROAD.STAMidPNR-1' at 'runs/RUN_1/02-openroad-stamidpnr-1'…\n"
        "Running 'OpenROAD.DetailedRouting' at 'runs/RUN_1/03-openroad-detailedrouting'…\n"
    )
    return run


def test_changed_metrics_runtime_memory_and_ids(tmp_path):
    run = _run(tmp_path)
    _step(run, "01-yosys-synthesis", {"design__instance__count": 222}, "00:00:00.913", "65MiB")
    _step(run, "02-openroad-stamidpnr-1", {"design__instance__count": 222, "timing__setup__ws": 5.3},
          "00:01:02.500", "1.5GiB")
    out = history.run_stages(run)
    assert out["design_name"] == "spm" and out["clock_period"] == 10 and out["flow"] == "Classic"
    s1, s2 = out["steps"]
    assert s1["id"] == "Yosys.Synthesis" and s1["status"] == "done"
    assert s1["changed"] == {"design__instance__count": 222}
    assert s1["runtime_s"] == 0.913 and s1["peak_rss_mib"] == 65.0
    # only what changed since the previous step
    assert s2["changed"] == {"timing__setup__ws": 5.3}
    assert s2["id"] == "OpenROAD.STAMidPNR-1"
    assert s2["runtime_s"] == 62.5 and s2["peak_rss_mib"] == 1536.0


def test_stopped_step_and_incomplete_run(tmp_path):
    run = _run(tmp_path)
    _step(run, "01-yosys-synthesis", {"design__instance__count": 222})
    _step(run, "03-openroad-detailedrouting", done=False)
    out = history.run_stages(run)
    assert out["completed"] is False
    assert [s["status"] for s in out["steps"]] == ["done", "stopped"]
    assert out["steps"][1]["changed"] == {}


def test_no_flow_log_and_no_steps(tmp_path):
    run = tmp_path / "runs" / "empty"
    run.mkdir(parents=True)
    out = history.run_stages(run)
    assert out["steps"] == [] and out["completed"] is False
    _step(run, "01-yosys-synthesis", {})
    assert history.run_stages(run)["steps"][0]["id"] is None


def test_route_is_registered():
    from lanex.server.routes import ROUTES
    assert any(p == "/api/run-stages" for p, _ in ROUTES)
