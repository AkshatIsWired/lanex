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
"""Round-74 correctness locks — the residual gaps from the money-loss fear
audit (fears A/G/N/Q/S). Each test owns exactly one gap so a future refactor
that re-opens it fails here:

  * #1 (Fear Q/S) — every run records the toolchain that produced it
    (LanEx + LibreLane versions, container image), so "would I get the same
    numbers manually?" is answerable from the export alone.
  * #3 (Fear P)   — the reproduce command carries the run's inputs verbatim;
    re-parsing it yields the SAME overrides / PDK / SCL / sources (a structural
    round-trip; the metric-identical replay lives in the differential CI job).
  * #4 (Fear N)   — the DSE queue is strictly serial, so two runs can never
    coexist and cross-attribute steps or metrics.
  * #5 (Fear R)   — the raw metrics feeding the display derivations sit in
    physical range, so an upstream units flip (fraction→percent) is caught
    BEFORE the ``*100`` / ``*1000`` scaling silently doubles it.

Pure stdlib — no EDA tools, no container engine, no live librelane run.
"""
from __future__ import annotations

import json
import re
import shlex
import threading
import time
from pathlib import Path

import pytest


# --------------------------------------------------------------------------- #
# #1 — toolchain identity stamped into every run (Fear Q / Fear S)
# --------------------------------------------------------------------------- #
def test_toolchain_provenance_records_the_versions() -> None:
    from lanex.controller import runner, compat
    from lanex import _version as lanex_version

    tc = runner._toolchain_provenance("local")
    assert tc["run_mode"] == "local"
    # The versions come from the real detectors, not a hardcoded string.
    assert tc["librelane_version"] == compat.get_version()
    assert tc["lanex_version"] == lanex_version.get_version()
    # Local mode ran on the host toolchain — there is no container image to name,
    # so we must NOT fabricate one.
    assert "image" not in tc


def test_toolchain_provenance_names_the_container_image() -> None:
    from lanex.controller import runner, container_run

    tc = runner._toolchain_provenance("container")
    assert tc["run_mode"] == "container"
    # The image is the version-pinned tag the flow actually ran inside — the
    # toolset identity. It must match what the run path itself resolves.
    assert tc["image"] == container_run.image_ref()
    assert tc["image"], "container run recorded an empty image identity"


def test_toolchain_provenance_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # A failure gathering provenance must degrade to "unknown", never derail the
    # run persist (best-effort contract).
    from lanex.controller import runner, compat

    monkeypatch.setattr(compat, "get_version", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    tc = runner._toolchain_provenance("local")
    assert tc["librelane_version"] == "unknown"
    # lanex version still resolved independently.
    assert tc["run_mode"] == "local"


def test_persist_gui_meta_stamps_the_toolchain(tmp_path: Path) -> None:
    # The single choke point every run path funnels through must write the
    # toolchain block into gui-run.json.
    from lanex.controller.runner import FlowRunner

    run_dir = tmp_path / "runs" / "RUN_1"
    run_dir.mkdir(parents=True)
    r = FlowRunner()
    r._run_dir = str(run_dir)
    r._run_mode = "local"
    r._gui_meta = {"pdk": "sky130A", "overrides": {"FP_CORE_UTIL": 45}}
    r._persist_gui_meta()

    meta = json.loads((run_dir / "gui-run.json").read_text())
    assert "toolchain" in meta, "gui-run.json omits the toolchain identity"
    tc = meta["toolchain"]
    assert tc["run_mode"] == "local"
    assert "librelane_version" in tc and "lanex_version" in tc
    # The GUI-only context we already recorded must survive alongside it.
    assert meta["overrides"] == {"FP_CORE_UTIL": 45}
    assert meta["run_dir"] == str(run_dir)


# --------------------------------------------------------------------------- #
# #3 — reproduce command round-trips the run's inputs (Fear P)
# --------------------------------------------------------------------------- #
def _parse_local_cli(command: str) -> dict:
    """Re-parse a ``librelane`` local invocation back into its inputs, the way a
    user replaying the reproduce command would have LibreLane interpret it."""
    argv = shlex.split(command)
    assert argv[0] == "librelane"
    out: dict = {"overrides": {}, "pdk": None, "scl": None, "flow": None,
                 "positionals": []}
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "-c":
            k, _, v = argv[i + 1].partition("=")
            out["overrides"][k] = v
            i += 2
        elif a == "-p":
            out["pdk"] = argv[i + 1]; i += 2
        elif a == "-s":
            out["scl"] = argv[i + 1]; i += 2
        elif a == "-f":
            out["flow"] = argv[i + 1]; i += 2
        elif a == "--pdk-root":
            i += 2  # not asserted here
        else:
            out["positionals"].append(a); i += 1
    return out


def test_reproduce_command_round_trips_inputs() -> None:
    from lanex.controller import manualcmd

    cmds = manualcmd.cli_command_for(
        design_dir="/w/spm",
        config_file="/w/spm/config.json",
        flow="Classic",
        pdk="sky130A",
        scl="sky130_fd_sc_hd",
        run_mode="local",
        overrides={"FP_CORE_UTIL": 45, "CLOCK_PERIOD": 10},
        extra_sources=["/w/spm/src/spm.v", "/w/spm/src/mac.v"],
    )
    parsed = _parse_local_cli(cmds["local"])

    # PDK / SCL / flow survive verbatim.
    assert parsed["pdk"] == "sky130A"
    assert parsed["scl"] == "sky130_fd_sc_hd"
    assert parsed["flow"] == "Classic"
    # Every override the run used is re-emitted with its exact value.
    assert parsed["overrides"]["FP_CORE_UTIL"] == "45"
    assert parsed["overrides"]["CLOCK_PERIOD"] == "10"
    # The picker-synthesised source list becomes VERILOG_FILES, whitespace-joined
    # exactly as LibreLane parses list variables — so the replay runs the SAME
    # RTL, not a dropped or reordered set (the reproduce-metadata bug this guards).
    assert parsed["overrides"]["VERILOG_FILES"] == "/w/spm/src/spm.v /w/spm/src/mac.v"
    # The config file is a leading positional (CONFIG_FILES nargs=-1).
    assert "/w/spm/config.json" in parsed["positionals"]


def test_reproduce_container_form_is_non_interactive_and_dockerized() -> None:
    # A copied container command must run in a pipe/script (no TTY) or it aborts
    # "the input device is not a TTY" — the exact copy-paste failure this guards.
    from lanex.controller import manualcmd

    cmds = manualcmd.cli_command_for(
        design_dir="/w/spm", config_file="/w/spm/config.json",
        pdk="sky130A", run_mode="container",
    )
    assert "--dockerized" in cmds["container"]
    assert "--docker-no-tty" in cmds["container"]
    assert cmds["recommended"] == "container"


# --------------------------------------------------------------------------- #
# #4 — the DSE queue is strictly serial (Fear N: no cross-attribution)
# --------------------------------------------------------------------------- #
def test_dse_queue_never_overlaps_two_runs() -> None:
    from lanex.controller.dse import DseJob

    job = DseJob()
    live = {"now": 0, "max": 0}
    lock = threading.Lock()
    order: list = []

    def start_one(tag: str, overrides: dict) -> bool:
        with lock:
            live["now"] += 1
            live["max"] = max(live["max"], live["now"])
            order.append(tag)
        time.sleep(0.02)  # hold the "run" open so any overlap would be observed
        with lock:
            live["now"] -= 1
        return True

    tags = ["A", "B", "C", "D"]
    res = job.start(start_one=start_one,
                    overrides_list=[{"X": t} for t in tags], tags=tags)
    assert res["ok"] is True
    # Wait for the queue to drain.
    for _ in range(200):
        if not job.active:
            break
        time.sleep(0.02)
    assert not job.active, "DSE queue thread never finished"

    # The invariant: at most ONE run was ever in flight — no two runs coexisted
    # to cross-attribute steps/metrics — and every point ran, in queue order.
    assert live["max"] == 1, f"DSE ran {live['max']} runs concurrently"
    assert order == tags, "DSE did not run the sweep points in queue order"
    assert job.done == tags and job.failed == []


def test_dse_refuses_a_second_concurrent_sweep() -> None:
    from lanex.controller.dse import DseJob

    job = DseJob()
    gate = threading.Event()

    def slow_start_one(tag: str, overrides: dict) -> bool:
        gate.wait(timeout=2.0)  # keep the first sweep active
        return True

    first = job.start(start_one=slow_start_one, overrides_list=[{}], tags=["A"])
    assert first["ok"] is True
    # A second sweep while one is active must be refused, not silently overlapped.
    second = job.start(start_one=slow_start_one, overrides_list=[{}], tags=["B"])
    assert second["ok"] is False
    assert "already running" in second["error"]
    gate.set()
    for _ in range(200):
        if not job.active:
            break
        time.sleep(0.02)


# --------------------------------------------------------------------------- #
# #5 — raw derivation inputs sit in physical range (Fear R: units-flip guard)
# --------------------------------------------------------------------------- #
GOLDEN_METRICS = Path(__file__).parent / "goldens" / "display_run" / "metrics.json"


def _golden_metrics() -> dict:
    raw = GOLDEN_METRICS.read_text()
    tokened = re.sub(r'([:\[,]\s*)(-?Infinity|NaN)(\s*[,}\]])', r'\1"\2"\3', raw)
    return json.loads(tokened)


def test_utilization_fraction_is_in_range_before_scaling() -> None:
    # design_summary multiplies utilization by 100 to show a percent. That is
    # only correct if the raw value is a FRACTION in [0, 1]. If upstream ever
    # flips it to already-percent, the raw would exceed 1 and the display would
    # read "5000%". Lock the precondition against the golden so the flip is caught
    # here, not on a user's screen (Fear R).
    m = _golden_metrics()
    util = m.get("design__instance__utilization")
    assert isinstance(util, (int, float))
    assert 0.0 <= util <= 1.0, f"utilization {util} is not a fraction — units flip?"


def test_power_and_counts_are_physically_sane() -> None:
    m = _golden_metrics()
    # Power (W, scaled to mW for display) is non-negative.
    pw = m.get("power__total")
    if isinstance(pw, (int, float)) and pw == pw:  # skip NaN
        assert pw >= 0.0, f"total power {pw} is negative"
    # Every count-style signoff metric is a non-negative whole number — a
    # negative or fractional violation count would mean a mis-parsed field.
    for key, v in m.items():
        if key.endswith("__count") or key.endswith("_error__count") or key.endswith("_vio__count"):
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            if v != v:  # NaN — a real "unknown", handled elsewhere
                continue
            assert v >= 0, f"{key}={v} is a negative count"
            assert float(v).is_integer(), f"{key}={v} is not a whole count"
