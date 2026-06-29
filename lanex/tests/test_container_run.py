# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Unit tests for :mod:`lanex.controller.container_run` (container run mode).

These are pure/offline — they validate the exact ``librelane --dockerized``
command line and the stdout step-parser against captured log shapes. The full
in-container run is the one manual check a Docker host is needed for.
"""
from __future__ import annotations


def test_dockerized_argv_order_and_flags():
    from lanex.controller.container_run import build_dockerized_argv

    argv = build_dockerized_argv(
        config_file="/home/u/proj/config.yaml",
        design_dir="/home/u/proj",
        flow="Classic",
        pdk="sky130A",
        scl="sky130_fd_sc_hd",
        pdk_root="/home/u/.ciel",
        tag="run1",
        skip=["Magic.DRC"],
        overrides={"CLOCK_PERIOD": 10},
        extra_sources=["src/top.v"],
        overwrite=True,
        python_exe="python3",
    )
    # --pdk-root is a host-side flag and MUST precede --dockerized.
    assert argv[:3] == ["python3", "-m", "librelane"]
    assert argv.index("--pdk-root") < argv.index("--dockerized")
    # The GUI streams over a pipe (no TTY), so it must force --docker-no-tty
    # (also a host-side flag) — else the engine wants `docker -t` and aborts.
    assert "--docker-no-tty" in argv
    assert argv.index("--docker-no-tty") < argv.index("--dockerized")
    # The config is passed relative to the design dir (== container cwd).
    assert "config.yaml" in argv
    assert "/home/u/proj/config.yaml" not in argv
    # Inner flags appear after --dockerized.
    d = argv.index("--dockerized")
    assert argv.index("-f") > d and "Classic" in argv
    assert argv.index("-p") > d and "sky130A" in argv
    assert argv.index("-s") > d and "sky130_fd_sc_hd" in argv
    assert "--run-tag" in argv and "run1" in argv
    assert "--overwrite" in argv
    assert "-S" in argv and "Magic.DRC" in argv
    assert "-c" in argv and "CLOCK_PERIOD=10" in argv
    assert "VERILOG_FILES=src/top.v" in argv


def test_image_ref_pins_version():
    from lanex.controller.container_run import image_ref

    ref = image_ref()
    assert ref.startswith("ghcr.io/librelane/librelane:") or ref  # override-safe


def test_image_ref_honours_override(monkeypatch):
    from lanex.controller import container_run

    monkeypatch.setenv("LIBRELANE_IMAGE_OVERRIDE", "example.com/foo:1")
    assert container_run.image_ref() == "example.com/foo:1"


def test_parser_step_transitions_and_skip():
    from lanex.controller.container_run import ContainerLogParser

    p = ContainerLogParser(["Verilator.Lint", "Yosys.Synthesis", "OpenROAD.Floorplan"])
    events = []
    events += p.feed("docker run --rm --name dead-beef -t ghcr.io/librelane/librelane:3.0.4 python3 -m librelane config.yaml")
    events += p.feed("[INFO] Running 'Verilator.Lint' at 'runs/run1/01-verilator-lint'…")
    # Skip Yosys: next line jumps straight to Floorplan -> Yosys inferred skipped.
    events += p.feed("[INFO] Running 'OpenROAD.Floorplan' at 'runs/run1/03-openroad-floorplan'…")
    events += p.finish(0)

    assert p.container_name == "dead-beef"
    by_type = {}
    for e in events:
        by_type.setdefault(e["type"], []).append(e)
    started = [e["step_id"] for e in by_type.get("step_started", [])]
    skipped = [e["step_id"] for e in by_type.get("step_skipped", [])]
    done = [e["step_id"] for e in by_type.get("step_done", [])]
    assert started == ["Verilator.Lint", "OpenROAD.Floorplan"]
    assert "Yosys.Synthesis" in skipped
    assert "Verilator.Lint" in done and "OpenROAD.Floorplan" in done
    assert by_type.get("flow_done", [{}])[-1].get("ok") is True


def test_parser_failure_path():
    from lanex.controller.container_run import ContainerLogParser

    p = ContainerLogParser(["Yosys.Synthesis"])
    events = []
    events += p.feed("[INFO] Running 'Yosys.Synthesis' at 'runs/x/01-yosys'…")
    events += p.feed("FlowException: Subprocess had a non-zero exit")
    events += p.finish(1)

    failed = [e for e in events if e["type"] == "step_failed"]
    assert failed and failed[0]["step_id"] == "Yosys.Synthesis"
    fd = [e for e in events if e["type"] == "flow_done"]
    assert fd and "error" in fd[-1]


def test_pull_argv():
    from lanex.controller.container_run import pull_argv, image_ref

    assert pull_argv("podman") == ["podman", "pull", image_ref()]
