# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Version- and mode-aware PDK readiness (the OpenROAD/sky130 container fix).

Container mode goes through ``librelane --dockerized`` -> the CLI's
``pdk_resolve_wrapper`` -> ``ciel.fetch``, which demands the **exact** pinned
PDK version. A different installed version (the symptom that produced a mid-run
``httpx.ReadTimeout``) must be reported as *not ready* with the right
remediation, and the resolved ``pdk_root`` must point at the store that holds
the required version. Local mode stays version-agnostic (the Flow uses
``pdk_root`` directly, no ``ciel.fetch``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

ciel = pytest.importorskip("ciel")


def _seed_store(home: str, family: str, version: str, variant: str, scl: str) -> Path:
    """Create a ciel-store layout ciel.Version.is_installed() will recognise."""
    ver = ciel.Version(name=version, pdk=family)
    vdir = Path(ver.get_dir(ciel.get_ciel_home(home)))
    scl_dir = vdir / variant / "libs.ref" / scl
    scl_dir.mkdir(parents=True, exist_ok=True)
    (scl_dir / f"{scl}__tt.lib").write_text("/* dummy liberty */\n")
    (scl_dir / f"{variant}.lef").write_text("VERSION 5.8 ;\n")
    (scl_dir / f"{variant}.gds").write_text("")
    return scl_dir


def _isolate(monkeypatch, tmp_path: Path, store: Path) -> None:
    monkeypatch.setenv("PDK_ROOT", str(store))
    # Keep ~/.ciel and ~/pdk out of the candidate roots so the test is hermetic.
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path / "nohome")
    # Deterministic: pretend we're offline (no accidental 2.5s socket probe).
    from lanex.controller import pdk as pdk_mod

    monkeypatch.setattr(pdk_mod, "network_can_reach_pdk_source", lambda timeout=2.5: False)


def test_container_ready_when_pinned_version_present(monkeypatch, tmp_path: Path):
    from lanex.controller import pdk

    store = tmp_path / "pdks"
    store.mkdir()
    _isolate(monkeypatch, tmp_path, store)

    required = pdk.required_pdk_version("sky130")
    assert required, "librelane must expose a pinned sky130 hash"
    scl_dir = _seed_store(str(store), "sky130", required, "sky130A", "sky130_fd_sc_hd")

    info = pdk.check_pdk_ready("sky130A", "sky130_fd_sc_hd", "container")
    assert info["ready"] is True
    assert info["version_match"] is True
    assert info["needs_download"] is False
    # The resolved root is the ciel home that actually holds the right version.
    assert Path(info["pdk_root"]) == Path(ciel.get_ciel_home(str(store)))
    assert Path(info["where"][0]) == scl_dir


def test_container_not_ready_on_version_mismatch(monkeypatch, tmp_path: Path):
    """The exact bug from the field: a *different* sky130 version is installed."""
    from lanex.controller import pdk

    store = tmp_path / "pdks"
    store.mkdir()
    _isolate(monkeypatch, tmp_path, store)

    wrong = "0" * 40
    _seed_store(str(store), "sky130", wrong, "sky130A", "sky130_fd_sc_hd")

    info = pdk.check_pdk_ready("sky130A", "sky130_fd_sc_hd", "container")
    assert info["ready"] is False
    assert info["version_match"] is False
    assert info["needs_download"] is True
    assert wrong in info["installed_versions"]
    required = pdk.required_pdk_version("sky130")
    assert required in info["remediation"]  # tells the user the exact version
    assert "ciel enable" in info["remediation"]


def test_container_not_ready_when_absent(monkeypatch, tmp_path: Path):
    from lanex.controller import pdk

    store = tmp_path / "pdks"
    store.mkdir()
    _isolate(monkeypatch, tmp_path, store)

    info = pdk.check_pdk_ready("sky130A", "sky130_fd_sc_hd", "container")
    assert info["ready"] is False
    assert info["needs_download"] is True
    assert info["installed_versions"] == []


def test_local_mode_is_version_agnostic(monkeypatch, tmp_path: Path):
    """Local runs use pdk_root directly; any present version with libs works."""
    from lanex.controller import pdk

    store = tmp_path / "pdks"
    scl_dir = store / "sky130A" / "libs.ref" / "sky130_fd_sc_hd"
    scl_dir.mkdir(parents=True)
    (scl_dir / "x__tt.lib").write_text("/* lib */")
    (scl_dir / "x.lef").write_text("VERSION 5.8 ;")
    _isolate(monkeypatch, tmp_path, store)

    info = pdk.check_pdk_ready("sky130A", "sky130_fd_sc_hd", "local")
    assert info["ready"] is True
    assert Path(info["pdk_root"]) == store


def test_family_name_resolves_to_default_variant(monkeypatch, tmp_path: Path):
    """Passing the family ('sky130') resolves to its default variant on disk."""
    from lanex.controller import pdk

    store = tmp_path / "pdks"
    store.mkdir()
    _isolate(monkeypatch, tmp_path, store)

    required = pdk.required_pdk_version("sky130")
    _seed_store(str(store), "sky130", required, "sky130A", "sky130_fd_sc_hd")

    info = pdk.check_pdk_ready("sky130", "sky130_fd_sc_hd", "container")
    assert info["ready"] is True


def test_installed_pdk_versions_is_read_only(monkeypatch, tmp_path: Path):
    from lanex.controller import pdk

    store = tmp_path / "pdks"
    store.mkdir()
    _isolate(monkeypatch, tmp_path, store)
    required = pdk.required_pdk_version("sky130")
    _seed_store(str(store), "sky130", required, "sky130A", "sky130_fd_sc_hd")

    found = pdk.installed_pdk_versions("sky130A")
    assert (required, ciel.get_ciel_home(str(store))) in found


def test_uninstall_pdk_passes_version_and_root(monkeypatch, tmp_path: Path):
    """Regression: ``ciel rm`` MUST include the positional <VERSION> + the root
    the PDK actually lives in (the field bug omitted the version entirely)."""
    from lanex.controller import installer, pdk

    store = tmp_path / "pdks"
    store.mkdir()
    _isolate(monkeypatch, tmp_path, store)
    required = pdk.required_pdk_version("sky130")
    _seed_store(str(store), "sky130", required, "sky130A", "sky130_fd_sc_hd")
    home = ciel.get_ciel_home(str(store))

    captured = []
    monkeypatch.setattr(installer, "_check_cmd", lambda name: True)
    monkeypatch.setattr(
        installer, "_run_argv",
        lambda argv, label, key: captured.append(argv) or {"ok": True, "rc": 0, "output": []},
    )
    # Pretend the version is gone after rm so the recheck confirms removal.
    monkeypatch.setattr(ciel.Version, "is_installed", lambda self, pdk_root: False)

    res = installer.uninstall_pdk("sky130A")
    assert res["ok"] is True
    assert len(captured) == 1
    argv = captured[0]
    assert argv[:2] == ["ciel", "rm"]
    assert required in argv  # the previously-missing positional VERSION
    assert "--pdk-family" in argv and "sky130" in argv
    assert "--pdk-root" in argv and home in argv
    assert "--yes" in argv


def test_uninstall_manual_install_is_honest(monkeypatch, tmp_path: Path):
    """A non-ciel (manual) install can't be ciel-removed -> clear message, not a
    silent success."""
    from lanex.controller import installer

    store = tmp_path / "pdks"
    (store / "sky130A" / "libs.ref").mkdir(parents=True)  # manual layout, no ciel store
    _isolate(monkeypatch, tmp_path, store)
    monkeypatch.setattr(installer, "_check_cmd", lambda name: True)

    res = installer.uninstall_pdk("sky130A")
    assert res["ok"] is False
    assert "not ciel-managed" in res["reason"]
    assert str(store / "sky130A") in res["reason"]


def test_installer_targets_pinned_version_not_newest():
    """Regression: reinstall must fetch the version LibreLane pins (so container
    mode sees it), not whatever `ciel ls-remote` reports as newest."""
    from lanex.controller import installer, pdk

    for family in ("sky130", "gf180mcu", "ihp-sg13g2"):
        pinned = pdk.required_pdk_version(family)
        assert pinned, f"no pinned hash for {family}"
        assert installer._get_pdk_version(family) == pinned
        fetch = installer._ciel_fetch_cmd("/tmp/r", family, ["x"])
        assert fetch and pinned in fetch
        script = installer._ciel_provision_script("/tmp/r", family, ["x"])
        assert pinned in script and "ls-remote" not in script


def test_strip_ansi_and_progress_bar_filter():
    from lanex.controller.container_run import strip_ansi, is_progress_bar

    # A Rich progress-bar redraw (block glyphs) -> recognised, dropped.
    bar = "\x1b[2KClassic - Stage 68 - DRC \x1b[91m━━━━━\x1b[0m╺━━ \x1b[32m67/80\x1b[0m 0:01:48"
    cleaned = strip_ansi(bar)
    assert "\x1b" not in cleaned
    assert is_progress_bar(cleaned)
    # Real tool output survives, no ANSI, not flagged as a bar.
    real = "\x1b[34mINFO\x1b[0m Check for KLayout DRC errors clear."
    rc = strip_ansi(real)
    assert rc == "INFO Check for KLayout DRC errors clear."
    assert not is_progress_bar(rc)


def test_get_step_output_reads_step_log(tmp_path):
    from lanex.controller import history

    run = tmp_path / "runs" / "tag1"
    step_dir = run / "66-checker-magicdrc"
    (step_dir / "reports").mkdir(parents=True)
    (step_dir / "checker-magicdrc.log").write_text("\x1b[32mDRC clean\x1b[0m\nline2\n")
    (step_dir / "state_out.json").write_text("{}")
    (step_dir / "reports" / "drc.rpt").write_text("ok")

    # Match by the real flow step id (Checker.MagicDRC -> checker-magicdrc).
    out = history.get_step_output(str(run), "Checker.MagicDRC")
    assert out["ok"] is True
    assert out["dir"] == "66-checker-magicdrc"
    assert "DRC clean" in out["log"] and "\x1b" not in out["log"]  # ANSI stripped
    assert out["completed"] is True
    assert "reports/drc.rpt" in out["reports"]

    missing = history.get_step_output(str(run), "OpenROAD.Floorplan")
    assert missing["ok"] is False


def _fake_run(root, *, with_final=True, metrics=None, steps=("06-yosys-synthesis",)):
    run = root / "runs" / "tagX"
    for s in steps:
        (run / s).mkdir(parents=True)
        (run / s / "state_out.json").write_text("{}")
        (run / s / "runtime.txt").write_text("00:00:02.500")
    if with_final:
        (run / "final").mkdir(parents=True)
        import json
        (run / "final" / "metrics.json").write_text(json.dumps(metrics or {"design__instance__area": 8051.47}))
    return run


def test_run_success_and_metrics_from_final(tmp_path):
    from lanex.controller import history

    run = _fake_run(tmp_path, metrics={"design__instance__area": 100.0, "design__lvs_error__count": 0})
    runs = history.list_runs(str(tmp_path))
    assert len(runs) == 1
    r = runs[0]
    assert r["success"] is True                 # final/ present, no errors
    assert r["wall_time_s"] and r["wall_time_s"] > 0   # summed from runtime.txt
    view = history.get_run(str(run))
    assert view["metrics"]["values"]["design__instance__area"] == 100.0


def test_run_failed_when_no_final_or_errors(tmp_path):
    from lanex.controller import history

    # No final/ -> not completed -> failed.
    nofinal = _fake_run(tmp_path, with_final=False)
    assert history.list_runs(str(tmp_path))[0]["success"] is False

    # final/ present but a hard-error metric > 0 -> failed.
    import shutil
    shutil.rmtree(tmp_path / "runs")
    _fake_run(tmp_path, metrics={"design__lvs_error__count": 3})
    assert history.list_runs(str(tmp_path))[0]["success"] is False


def test_list_run_images_groups_by_step(tmp_path):
    from lanex.controller import history

    run = tmp_path / "runs" / "t"
    (run / "59-klayout-render").mkdir(parents=True)
    (run / "59-klayout-render" / "spm.png").write_bytes(b"\x89PNG")
    (run / "final" / "render").mkdir(parents=True)
    (run / "final" / "render" / "spm.png").write_bytes(b"\x89PNG")
    imgs = history.list_run_images(run)
    steps = {i["step"] for i in imgs}
    assert "klayout-render" in steps and "final" in steps


def test_serve_run_file_blocks_traversal(tmp_path, monkeypatch):
    from lanex.server import routes

    run = tmp_path / "runs" / "t"
    (run / "final").mkdir(parents=True)
    (run / "final" / "metrics.json").write_text("{}")
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(tmp_path))

    ok = routes.serve_run_file("/api/run-file?tag=t&path=final/metrics.json")
    assert ok is not None
    bad = routes.serve_run_file("/api/run-file?tag=t&path=../../../etc/passwd")
    assert bad is None


def test_parser_translates_pdk_download_failure():
    from lanex.controller.container_run import ContainerLogParser, _PDK_DL_MSG

    parser = ContainerLogParser(["Yosys.Synthesis", "OpenROAD.Floorplan"])
    parser.feed("Version 8afc not found locally, attempting to download…")
    events = parser.feed("Traceback (most recent call last):")
    failed = [e for e in events if e["type"] == "step_failed"]
    assert failed and failed[0]["message"] == _PDK_DL_MSG


def test_parser_pdk_failure_on_nonzero_exit_without_traceback():
    from lanex.controller.container_run import ContainerLogParser, _PDK_DL_MSG

    parser = ContainerLogParser(["Yosys.Synthesis"])
    parser.feed("httpx.ReadTimeout: timed out")
    out = parser.finish(1)
    failed = [e for e in out if e["type"] == "step_failed"]
    done = [e for e in out if e["type"] == "flow_done"]
    assert failed and failed[0]["message"] == _PDK_DL_MSG
    assert done and "offline" in done[0]["error"]
