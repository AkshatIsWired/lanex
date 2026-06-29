# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Round-20 lock-in tests for the user-reported batch:

* #1a  A runaway simulation (a free-running clock / no $finish) is killed by the
       SimJob wall-clock timeout, so ``job.running`` frees itself and a SECOND
       sim can start — the cause of "it keeps saying simulating".
* #1b  A source/testbench can be deleted from the design (editor.delete_file),
       and the delete is confined to the design dir.
* #3   The support bundle's ``sources`` part is EXACTLY the run's resolved
       VERILOG_FILES (the user's selection) — never a blanket folder glob — and
       it strips LibreLane path prefixes, expands globs, and de-duplicates.
* #4   /api/compare resolves runs passed as absolute ``run_dirs`` (cross-design),
       not only tags under the active design — fixing "no valid runs to compare".

Pure/stdlib + an in-process server; no OpenROAD, Docker, PDK, or network."""
from __future__ import annotations

import contextlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from lanex.controller import bundle, editor, events, simulate


# ----------------------------------------------------------- #1a sim timeout
def test_sim_timeout_frees_job_and_emits_timed_out():
    cur = events.bus.max_seq
    # An "infinite" sim stands in for a free-running-clock testbench.
    r1 = simulate.job.start(
        ["bash", "-lc", "while true; do sleep 0.1; done"],
        design_dir="/tmp", run_mode="local", timeout=2,
    )
    assert r1["ok"] is True
    # The watchdog must kill it and free the job within a few seconds.
    deadline = time.time() + 10
    while simulate.job.running and time.time() < deadline:
        time.sleep(0.05)
    assert simulate.job.running is False, "runaway sim left job.running stuck True"

    done = [e for e in events.bus.events_since(cur) if e.get("type") == "sim_done"]
    assert done and done[-1].get("timed_out") is True

    # And a second sim can now start (the bug: it couldn't).
    r2 = simulate.job.start(["bash", "-lc", "exit 0"], design_dir="/tmp", run_mode="local", timeout=5)
    assert r2["ok"] is True
    while simulate.job.running:
        time.sleep(0.02)


# ----------------------------------------------------------- #1b file delete
def test_editor_delete_file_confined(tmp_path: Path):
    design = tmp_path / "design"
    (design / "src").mkdir(parents=True)
    f = design / "src" / "junk.v"
    f.write_text("module junk; endmodule\n")
    assert editor.delete_file(design, "src/junk.v")["ok"] is True
    assert not f.exists()
    # missing file
    assert editor.delete_file(design, "src/junk.v")["ok"] is False
    # traversal is refused — never deletes outside the design dir
    outside = tmp_path / "secret.txt"
    outside.write_text("keep me")
    assert editor.delete_file(design, "../secret.txt")["ok"] is False
    assert outside.exists()


# ----------------------------------------------------------- #3 bundle sources
def test_bundle_sources_are_resolved_selection_only(tmp_path: Path):
    design = tmp_path / "d"
    (design / "src").mkdir(parents=True)
    run = design / "runs" / "t"
    run.mkdir(parents=True)
    for n in ("a.v", "b.v", "c.v", "unused.v"):
        (design / "src" / n).write_text("module x; endmodule\n")
    # Resolved config selects a.v, b.v, c.v via a mix of prefix + glob + abs dup;
    # unused.v is in the folder but NOT selected, so must NOT be bundled.
    resolved = {"VERILOG_FILES": ["dir::src/a.v", "src/b.v",
                                   str((design / "src" / "c.v").resolve()),
                                   str((design / "src" / "c.v").resolve())]}  # dup
    files = bundle._source_files(run, resolved)
    names = sorted(p.name for p in files)
    assert names == ["a.v", "b.v", "c.v"]            # selection only, deduped
    assert "unused.v" not in names                    # never a blanket folder glob

    # Glob spec expands to exactly the matching files.
    g = bundle._source_files(run, {"VERILOG_FILES": ["src/*.v"]})
    assert sorted(p.name for p in g) == ["a.v", "b.v", "c.v", "unused.v"]


def test_strip_ll_prefix():
    assert bundle._strip_ll_prefix("dir::src/a.v") == "src/a.v"
    assert bundle._strip_ll_prefix("refg::x/y.v") == "x/y.v"
    assert bundle._strip_ll_prefix("/abs/path.v") == "/abs/path.v"


# ----------------------------------------------------------- #4 compare run_dirs
@pytest.fixture()
def _server():
    from lanex.server.app import make_server
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        base = s.getsockname()[1]
    httpd, port = make_server(host="127.0.0.1", port=base)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    # Wait until the listener actually accepts connections (avoids a startup race).
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1).read()
            break
        except Exception:
            time.sleep(0.05)
    try:
        yield port
    finally:
        httpd.shutdown()
        httpd.server_close()


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _fake_run(run_dir: Path, area: float):
    (run_dir / "final").mkdir(parents=True, exist_ok=True)
    (run_dir / "final" / "metrics.json").write_text(
        json.dumps({"design__instance__area": area, "design__instance__count": 10})
    )
    (run_dir / "config.json").write_text(json.dumps({"DESIGN_NAME": run_dir.name}))


def test_compare_accepts_cross_design_run_dirs(tmp_path: Path, _server):
    port = _server
    # Active design A with one run; a SECOND design B with its own run.
    a = tmp_path / "A"
    b = tmp_path / "B"
    _fake_run(a / "runs" / "a1", 100.0)
    _fake_run(b / "runs" / "b1", 200.0)
    _post(port, "/api/set-design-dir", {"path": str(a)})

    # Tag-only would only resolve under A; passing absolute run_dirs lets B's run
    # in too (the cross-design fix). No valid run → 400 used to fire here.
    st, resp = _post(port, "/api/compare", {
        "tags": ["a1"],
        "run_dirs": [str((b / "runs" / "b1").resolve())],
    })
    assert st == 200, resp
    tags = sorted(r["tag"] for r in resp["data"]["runs"])
    assert tags == ["a1", "b1"]

    # A path that is NOT a direct child of a runs/ dir is rejected (confinement).
    st2, resp2 = _post(port, "/api/compare", {"tags": [], "run_dirs": [str(tmp_path)]})
    assert st2 == 400
