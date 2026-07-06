# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Lock-in tests for the container-cancel fix.

The bug: cancel reported "cancelled" but the LibreLane container kept running
to completion, because the kill path only knew how to remove a container BY
NAME and librelane 3.0.4 never echoes the ``docker run --rm --name <uuid>``
line the parser watches for. The fix discovers the container by its design-dir
bind mount and force-removes it. All engine calls are faked here — no Docker
needed.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from lanex.controller import runner as runner_mod
from lanex.controller.runner import FlowRunner, _containers_mounting


class _FakeRun:
    """Records every subprocess.run argv and serves scripted outputs."""

    def __init__(self, design_dir: str, containers: Dict[str, str]):
        # containers: id -> mount source dir
        self.design_dir = design_dir
        self.containers = containers
        self.calls: List[List[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        out = ""
        if argv[1:2] == ["ps"]:
            out = "\n".join(self.containers) + "\n"
        elif argv[1:2] == ["inspect"]:
            cid = argv[-1]
            src = self.containers.get(cid, "/somewhere/else")
            out = json.dumps([{"Source": src, "Destination": src, "Type": "bind"}])
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")


def test_containers_mounting_matches_only_design_dir(tmp_path: Path, monkeypatch):
    design = tmp_path / "mychip"
    design.mkdir()
    other = tmp_path / "otherchip"
    other.mkdir()
    fake = _FakeRun(str(design), {"aaa111": str(design), "bbb222": str(other)})
    monkeypatch.setattr(runner_mod.subprocess, "run", fake)
    got = _containers_mounting("docker", str(design))
    assert got == ["aaa111"]


def test_containers_mounting_engine_down(monkeypatch, tmp_path):
    def boom(argv, **kw):
        raise OSError("engine unreachable")
    monkeypatch.setattr(runner_mod.subprocess, "run", boom)
    assert _containers_mounting("docker", str(tmp_path)) == []


def test_kill_container_discovers_by_mount(tmp_path: Path, monkeypatch):
    """The audit scenario: no container name captured, container running —
    cancel must find it via the design-dir mount and rm -f it."""
    design = tmp_path / "spm"
    run_dir = design / "runs" / "cancel-test"
    run_dir.mkdir(parents=True)
    fake = _FakeRun(str(design), {"deadbeef01": str(design)})
    monkeypatch.setattr(runner_mod.subprocess, "run", fake)
    monkeypatch.setattr(
        runner_mod.shutil, "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None)
    r = FlowRunner()
    r._run_dir = str(run_dir)
    r._container_name = None  # librelane 3.0.4: name never captured
    r._kill_container()
    rm_calls = [c for c in fake.calls if c[1:3] == ["rm", "-f"]]
    assert rm_calls == [["/usr/bin/docker", "rm", "-f", "deadbeef01"]]


def test_kill_container_by_name_still_first(tmp_path: Path, monkeypatch):
    design = tmp_path / "spm"
    run_dir = design / "runs" / "t"
    run_dir.mkdir(parents=True)
    fake = _FakeRun(str(design), {})  # discovery finds nothing extra
    monkeypatch.setattr(runner_mod.subprocess, "run", fake)
    monkeypatch.setattr(
        runner_mod.shutil, "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None)
    r = FlowRunner()
    r._run_dir = str(run_dir)
    r._container_name = "known-name-uuid"
    r._kill_container()
    rm_calls = [c for c in fake.calls if c[1:3] == ["rm", "-f"]]
    assert ["/usr/bin/docker", "rm", "-f", "known-name-uuid"] in rm_calls


def test_kill_container_no_run_dir_touches_nothing(monkeypatch):
    """Cancel before any run started: no design dir known -> no ps/inspect/rm
    beyond the (absent) name path; must not raise."""
    fake = _FakeRun("", {})
    monkeypatch.setattr(runner_mod.subprocess, "run", fake)
    monkeypatch.setattr(
        runner_mod.shutil, "which",
        lambda name: "/usr/bin/docker" if name == "docker" else None)
    r = FlowRunner()
    r._container_name = None
    r._kill_container()
    assert [c for c in fake.calls if c[1:3] == ["rm", "-f"]] == []


def test_design_dir_of_run_shapes(tmp_path: Path):
    r = FlowRunner()
    r._run_dir = str(tmp_path / "chip" / "runs" / "tag1")
    assert r._design_dir_of_run() == str((tmp_path / "chip").resolve())
    r._run_dir = None
    assert r._design_dir_of_run() is None
