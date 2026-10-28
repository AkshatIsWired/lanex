# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""A project folder renamed or deleted while LanEx is open.

Before: Run said "no config.{json,yaml,tcl} found in design directory" and
the fix sheet's Resume tried to plan from a run folder that was gone. Now
starting, resuming (fix plan/apply) and sweeping all refuse with one plain
message whose prefix the UI turns into the "Project folder not found" card.
"""
from __future__ import annotations

from pathlib import Path

from lanex.server import routes


def test_missing_design_error_only_for_a_gone_folder(tmp_path: Path) -> None:
    assert routes._missing_design_error(str(tmp_path)) is None
    gone = tmp_path / "renamed-away"
    msg = routes._missing_design_error(str(gone))
    assert msg and msg.startswith(routes.MISSING_DESIGN_PREFIX + str(gone))
    assert "Locate it" in msg


def test_start_run_refuses_a_missing_folder(tmp_path: Path, monkeypatch) -> None:
    gone = tmp_path / "chip"
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(gone))
    data, status = routes._start_run({})
    assert status == 404
    assert data.startswith(routes.MISSING_DESIGN_PREFIX)


def test_resume_plan_refuses_a_missing_folder(tmp_path: Path, monkeypatch) -> None:
    gone = tmp_path / "chip"
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(gone))
    data, status = routes._fix_plan({"tag": "run-1", "sets": {"CLOCK_PERIOD": 20}})
    assert status == 404
    assert data.startswith(routes.MISSING_DESIGN_PREFIX)


def test_resume_apply_refuses_a_missing_folder(tmp_path: Path, monkeypatch) -> None:
    gone = tmp_path / "chip"
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(gone))
    got = {}
    monkeypatch.setattr(routes, "_respond", lambda h, payload, code=200: got.update(payload=payload, code=code))

    class _Runner:
        running = False

    import lanex.server.app as app
    monkeypatch.setattr(app, "get_runner", lambda: _Runner())
    routes._apply_fix(object(), {"tag": "run-1", "sets": {}, "start": "auto"})
    assert got["code"] == 404
    assert got["payload"].startswith(routes.MISSING_DESIGN_PREFIX)
    assert not gone.exists()


def test_sweep_refuses_a_missing_folder(tmp_path: Path, monkeypatch) -> None:
    gone = tmp_path / "chip"
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(gone))
    got = {}
    monkeypatch.setattr(routes, "_respond", lambda h, payload, code=200: got.update(payload=payload, code=code))

    class _H:
        _body = {"axes": [{"var": "CLOCK_PERIOD", "values": [10, 20]}]}

    routes.h_dse_start(_H())
    assert got["code"] == 404
    assert got["payload"].startswith(routes.MISSING_DESIGN_PREFIX)
