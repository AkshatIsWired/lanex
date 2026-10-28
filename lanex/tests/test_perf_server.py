# Copyright 2026 LanEx Contributors
"""Performance pass (2026-10-28): faster paths must give the same answers.

Each test runs the old implementation (kept here verbatim) and the new one on
the same fixture and compares the results exactly.
"""
from __future__ import annotations

import json
import os
import random
import time
from pathlib import Path

import pytest

from lanex.controller import autoconfig, fastscan, history, projectfiles, simulate


# --------------------------------------------------------------- fixtures

def _tree(root: Path) -> Path:
    """A project with everything a scan must skip or keep."""
    d = root / "proj"
    files = {
        "config.yaml": "DESIGN_NAME: top\n",
        "src/top.v": "module top(input clk, output y); sub u(.a(clk)); endmodule\n",
        "src/sub.sv": "module sub(input a); endmodule\n",
        "src/pkg.vhd": "entity ent is end ent;\n",
        "src/.hidden.v": "module hidden; endmodule\n",
        "src/deep/er/leaf.v": "module leaf; endmodule\n",
        "verify/top_tb.v": "module top_tb; top dut(); endmodule\n",
        "verify/tb_other.sv": "module tb_other; endmodule\n",
        "tb/mytestbench.v": "module mytestbench; endmodule\n",
        "runs/r1/01-yosys/top.v": "module top; endmodule\n",
        "runs/r1/02-x/a_tb.v": "module a_tb; endmodule\n",
        "runs/r1/final/render.png": "x",
        "runs_old/x_tb.v": "module x_tb; endmodule\n",
        "runsfoo_tb.v": "module runsfoo_tb; endmodule\n",
        "myruns/y_tb.v": "module y_tb; endmodule\n",
        "a/runs/b.v": "module b; endmodule\n",
        "a/runs/c_tb.v": "module c_tb; endmodule\n",
        "build/gen.v": "module gen; endmodule\n",
        ".git/objects/x.v": "module gitjunk; endmodule\n",
        "node_modules/m.v": "module m; endmodule\n",
        "sim_build/obj_dir/v.v": "module v; endmodule\n",
        "tmp/t.v": "module t; endmodule\n",
        "notes.txt": "hi",
    }
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (d / "dir_tb.v").mkdir()                      # a folder whose name looks like a bench
    (d / "src" / "deep" / "empty").mkdir()
    try:
        os.symlink(d / "src", d / "linked_src")    # listed, never entered
        os.symlink(d / "missing.v", d / "broken_tb.v")
    except (OSError, NotImplementedError):
        pass
    return d


def _old_find_testbenches(design_dir):
    base = Path(design_dir)
    found, seen = [], set()

    def add(p):
        try:
            rel = str(p.relative_to(base))
        except ValueError:
            return
        if "runs/" in rel or rel.startswith("runs"):
            return
        if rel not in seen:
            seen.add(rel)
            found.append(rel)

    for pat in simulate._TB_PATTERNS:
        for p in sorted(base.glob("verify/" + pat)):
            add(p)
    for pat in simulate._TB_PATTERNS:
        for p in sorted(base.rglob(pat)):
            add(p)
    return found


def _old_list_run_files(run_dir, max_entries=5000):
    run = Path(run_dir)
    out = []
    for p in sorted(run.rglob("*"), key=lambda x: str(x.relative_to(run))):
        rel = p.relative_to(run)
        is_dir = p.is_dir()
        try:
            size = p.stat().st_size if not is_dir else 0
        except Exception:
            size = 0
        out.append({"path": str(rel), "dir": is_dir, "size": size})
        if len(out) >= max_entries:
            break
    return out


def _old_list_run_images(run_dir):
    run = Path(run_dir)
    out = []
    for p in sorted(run.rglob("*")):
        if p.is_file() and p.suffix.lower() in history._IMAGE_EXTS:
            rel = p.relative_to(run)
            parts = rel.parts
            top = parts[0] if parts else ""
            if top == "final":
                step = "final"
            elif history._is_step_dir(top):
                step = "-".join(top.split("-")[1:])
            else:
                step = top
            out.append({"path": str(rel), "name": p.name, "step": step})
    return out


# --------------------------------------------------------------- scans

def test_iter_entries_is_rglob_minus_pruned(tmp_path):
    d = _tree(tmp_path)
    skip = fastscan.SOURCE_SKIP_DIRS
    old = sorted(p for p in d.rglob("*")
                 if not any(part in skip for part in p.relative_to(d).parts[:-1]))
    new = sorted(p for p in fastscan.iter_entries(d, fastscan.prune_names(skip))
                 if not any(part in skip for part in p.relative_to(d).parts[:-1]))
    assert new == old
    # Nothing pruned: exactly rglob.
    assert sorted(fastscan.iter_entries(d, lambda parts: False)) == sorted(d.rglob("*"))


def test_scan_sources_same_as_rglob(tmp_path, monkeypatch):
    d = _tree(tmp_path)
    new = autoconfig.scan_sources(d)
    monkeypatch.setattr(autoconfig, "iter_entries", lambda root, prune: Path(root).rglob("*"))
    old = autoconfig.scan_sources(d)
    assert new == old
    assert "src/top.v" in new["verilog"]
    assert not any(v.startswith("runs/") or "/runs/" in v for v in new["all_verilog"])


def test_project_verilog_same_as_rglob(tmp_path):
    d = _tree(tmp_path)
    old = sorted(p for p in d.rglob("*")
                 if p.suffix.lower() in (".v", ".sv") and "runs" not in p.relative_to(d).parts)
    assert projectfiles._project_verilog(d) == old
    assert projectfiles.find_module_file(d, "leaf") == d / "src" / "deep" / "er" / "leaf.v"
    assert projectfiles.find_module_file(d, "b") is None          # only under a/runs/


def test_find_testbenches_same_as_rglob(tmp_path):
    d = _tree(tmp_path)
    assert simulate.find_testbenches(d) == _old_find_testbenches(d)
    assert simulate.find_testbenches(str(d)) == _old_find_testbenches(str(d))


def test_run_file_listings_same_as_rglob(tmp_path):
    d = _tree(tmp_path)
    run = d / "runs" / "r1"
    (run / "final" / "nested").mkdir(parents=True)
    (run / "final" / "nested" / "pic.SVG").write_text("<svg/>")
    (run / "01-yosys" / "x.png").write_text("png")
    (run / ".png").write_text("dot file, no suffix")
    (run / "file.").write_text("")
    try:
        os.symlink(run / "01-yosys", run / "link-step")
    except (OSError, NotImplementedError):
        pass
    assert history.list_run_files(run) == _old_list_run_files(run)
    assert history.list_run_files(run, max_entries=3) == _old_list_run_files(run, 3)
    assert history.list_run_images(run) == _old_list_run_images(run)


@pytest.mark.parametrize("n_chars", [1, 7, 50, 1000])
def test_read_text_tail_same_as_read_text(tmp_path, n_chars):
    rng = random.Random(n_chars)
    pieces = ["a", "é", "€", "😀", "\r\n", "\r", "\n", "\x1b[31m", "x" * 13]
    for trial in range(30):
        blob = "".join(rng.choice(pieces) for _ in range(rng.randint(0, 3000))).encode("utf-8")
        if trial % 3 == 0 and blob:   # invalid bytes and a cut multi-byte char
            cut = rng.randint(0, len(blob) - 1)
            blob = blob[:cut] + b"\xff\xfe" + blob[cut:] + "😀".encode()[:2]
        p = tmp_path / f"log{trial}.txt"
        p.write_bytes(blob)
        data = p.read_text(encoding="utf-8", errors="replace")
        want = (data[-n_chars:], True) if len(data) > n_chars else (data, False)
        assert history._read_text_tail(p, n_chars) == want, trial


# --------------------------------------------------------------- run summaries

def _good_run(d: Path, tag: str) -> Path:
    run = d / "runs" / tag
    (run / "final").mkdir(parents=True)
    (run / "final" / "metrics.json").write_text(json.dumps({"timing__setup__ws": 0.5}))
    (run / "resolved.json").write_text(json.dumps({"PDK": "sky130A", "DESIGN_NAME": "top"}))
    for i, name in enumerate(["yosys-synthesis", "openroad-floorplan"], 1):
        s = run / f"{i}-{name}"
        s.mkdir()
        (s / "state_in.json").write_text("{}")
        (s / "state_out.json").write_text("{}")
    return run


def _age(path: Path, seconds: float) -> None:
    for p in [path, *path.rglob("*")]:
        t = os.stat(p, follow_symlinks=False).st_mtime - seconds
        os.utime(p, (t, t), follow_symlinks=False)


@pytest.fixture
def probe(monkeypatch):
    """A registered live probe (as the server does) reporting *live[0]*."""
    live = [None]
    monkeypatch.setattr(history, "_LIVE_PROBE", lambda: live[0])
    history._SUMMARY_CACHE.clear()
    history._START_CACHE.clear()
    history._RUN_RESULTS.clear()
    yield live
    history._SUMMARY_CACHE.clear()
    history._RUN_RESULTS.clear()


def test_list_runs_identical_with_fast_signatures(tmp_path, probe, monkeypatch):
    d = tmp_path / "d"
    for i in range(12):
        _good_run(d, f"r{i:02d}")
    _age(d / "runs", 600)
    cold = history.list_runs(d)
    # Every quiet, not-live run now carries a fast signature...
    assert all(history._SUMMARY_CACHE[r["run_dir"]][2] is not None for r in cold)
    # ...and the fast listing never reads a step folder.
    calls = []
    real = history._run_signature
    monkeypatch.setattr(history, "_run_signature", lambda run: calls.append(run) or real(run))
    warm = history.list_runs(d)
    assert warm == cold and calls == []
    # The same answer as a fresh, uncached listing.
    history._SUMMARY_CACHE.clear()
    history._START_CACHE.clear()
    assert history.list_runs(d) == cold


def test_fast_signature_follows_annotations(tmp_path, probe):
    d = tmp_path / "d"
    run = _good_run(d, "r1")
    _age(d / "runs", 600)
    assert history.list_runs(d)[0]["pinned"] is False
    history.set_pin(run, True)
    assert history.list_runs(d)[0]["pinned"] is True
    st = os.stat(run)
    history.set_pin(run, False)
    os.utime(run, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert history.list_runs(d)[0]["pinned"] is False
    history.write_note(run, "first")
    assert history.list_runs(d)[0]["note"] == "first"
    st = os.stat(run)
    time.sleep(0.05)                         # file times are coarse (a few ms)
    history.write_note(run, "second")        # rewritten in place
    os.utime(run, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert history.list_runs(d)[0]["note"] == "second"
    (run / "final" / "metrics.json").write_text(json.dumps({"timing__setup__ws": -1.0}))
    assert history.list_runs(d)[0]["key_metrics"]["timing__setup__ws"] == -1.0


def test_live_and_fresh_runs_use_the_full_signature(tmp_path, probe):
    d = tmp_path / "d"
    run = _good_run(d, "r1")
    _age(d / "runs", 600)
    history.list_runs(d)
    # The run controller's live run: a step finishing inside a step folder
    # (the run folder's mtime does not move) shows at once.
    probe[0] = str(run)
    step = run / "3-openroad-placement"
    step.mkdir()
    (step / "state_in.json").write_text("{}")
    _age(run, 600)
    assert history.list_runs(d)[0]["steps_done"] == 2
    (step / "state_out.json").write_text("{}")
    assert history.list_runs(d)[0]["steps_done"] == 3
    # Not live any more, but written moments ago (another program): still
    # read on the full signature.
    probe[0] = None
    step4 = run / "4-x"
    step4.mkdir()
    (step4 / "state_in.json").write_text("{}")
    assert history.list_runs(d)[0]["steps_done"] == 3
    time.sleep(0.02)
    (step4 / "state_out.json").write_text("{}")
    assert history.list_runs(d)[0]["steps_done"] == 4


def test_unknown_liveness_never_trusts_the_fast_signature(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "_LIVE_PROBE", None)
    history._SUMMARY_CACHE.clear()
    d = tmp_path / "d"
    _good_run(d, "r1")
    _age(d / "runs", 600)
    history.list_runs(d)
    assert history._SUMMARY_CACHE[str(d.resolve() / "runs" / "r1")][2] is None


def test_cached_run_result_reuse_and_invalidation(tmp_path, probe):
    d = tmp_path / "d"
    run = _good_run(d, "r1")
    _age(d / "runs", 600)
    n = [0]

    def compute():
        n[0] += 1
        return history.list_run_files(run)

    first = history.cached_run_result("files", run, compute)
    assert history.cached_run_result("files", run, compute) == first and n[0] == 1
    # LanEx writing into the run (a rendered diagram) forgets the answer.
    (run / "1-yosys-synthesis" / "g.dot.svg").write_text("<svg/>")
    history.touch_run(run)
    again = history.cached_run_result("files", run, compute)
    assert n[0] == 2 and any(f["path"].endswith("g.dot.svg") for f in again)
    # The live run is always computed.
    probe[0] = str(run)
    history.cached_run_result("files", run, compute)
    history.cached_run_result("files", run, compute)
    assert n[0] == 4


def test_disk_cache_round_trips_fast_signatures(tmp_path, probe, monkeypatch):
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))
    d = tmp_path / "d"
    _good_run(d, "r1")
    _age(d / "runs", 600)
    first = history.list_runs(d)
    monkeypatch.setattr(history, "_cache_loaded", False)
    history._SUMMARY_CACHE.clear()
    history._load_disk_cache()
    ent = history._SUMMARY_CACHE[first[0]["run_dir"]]
    assert ent[2] is not None and isinstance(ent[2], tuple)
    assert history.list_runs(d) == first


# --------------------------------------------------------------- tool probe

from lanex.controller import tools  # noqa: E402


def test_fast_versions_match_the_probe_output():
    import shutil
    import sys
    rc, out, err = tools._shell_exec([sys.executable, "--version"])
    assert tools._fast_version(sys.executable, ["--version"]) == (out or err)
    ll = shutil.which("librelane")
    if ll and tools._same_venv_script(ll):
        rc, out, err = tools._shell_exec([ll, "--bare-version"], timeout=30)
        assert rc == 0 and tools._fast_version(ll, ["--bare-version"]) == out
    # Anything else still runs the probe.
    assert tools._fast_version("/usr/bin/yosys", ["--version"]) is None
    assert tools._fast_version(sys.executable, ["-V"]) is None


def test_check_tools_is_session_cached_with_background_refresh(monkeypatch):
    calls = []

    def fake():
        calls.append(1)
        return {"n": len(calls)}

    monkeypatch.setattr(tools, "_check_tools_uncached", fake)
    tools._check_tools_cache.clear()
    try:
        first = tools.check_tools()
        assert first == {"n": 1} and tools.check_tools() is first
        # Old answer: returned at once, a fresh one is probed in the background.
        ts, v = tools._check_tools_cache[0]
        tools._check_tools_cache[0] = (ts - 3600, v)
        assert tools.check_tools() is first
        for _ in range(200):
            if tools._check_tools_cache and tools._check_tools_cache[0][1] == {"n": 2}:
                break
            time.sleep(0.01)
        assert tools.check_tools() == {"n": 2}
        # Recheck probes now; an install (clear) forgets the answer.
        assert tools.check_tools(force=True) == {"n": 3}
        tools._check_tools_cache.clear()
        assert tools.check_tools() == {"n": 4}
    finally:
        tools._check_tools_cache.clear()


def test_a_clear_during_a_probe_is_not_overwritten(monkeypatch):
    def fake():
        tools._check_tools_cache.clear()      # an install finished meanwhile
        return {"stale": True}

    monkeypatch.setattr(tools, "_check_tools_uncached", fake)
    tools._check_tools_cache.clear()
    try:
        assert tools.check_tools() == {"stale": True}
        assert not tools._check_tools_cache
    finally:
        tools._check_tools_cache.clear()


def test_container_status_shares_the_invalidation(monkeypatch):
    n = []
    monkeypatch.setattr(tools, "container_engine", lambda: n.append(1) or {"ready": True, "n": len(n)})
    tools._check_tools_cache.clear()
    try:
        a = tools.container_status()
        assert tools.container_status() is a and len(n) == 1
        tools._check_tools_cache.clear()
        assert tools.container_status()["n"] == 2
    finally:
        tools._check_tools_cache.clear()


def test_preflight_container_mode_skips_host_tool_probes(monkeypatch):
    from lanex.server import routes
    monkeypatch.setattr(tools, "container_status", lambda force=False: {"ready": True, "engine": "docker"})
    warmed = []
    monkeypatch.setattr(tools, "warm_check_tools", lambda: warmed.append(1))
    monkeypatch.setattr(tools, "check_tools", lambda force=False: pytest.fail("host probes awaited"))
    assert routes._preflight_container_tools() == {"container": {"ready": True, "engine": "docker"}}
    assert warmed == [1]


def test_windows_path_is_only_searched_without_a_linux_build(monkeypatch):
    from lanex.controller import platform_env
    monkeypatch.setattr(platform_env, "is_wsl", lambda: True)
    monkeypatch.setattr(platform_env, "linux_only_path", lambda path=None: "/usr/bin")
    monkeypatch.setattr(tools, "_windows_path", lambda: "/mnt/c/x")
    seen = []

    def which(c, path=None):
        seen.append(path)
        return "/usr/bin/" + c if path == "/usr/bin" and c == "here" else None

    monkeypatch.setattr(tools.shutil, "which", which)
    monkeypatch.setattr(tools, "_shell_exec", lambda argv, timeout=0: (0, "here 1.0", ""))
    assert tools._probe(["here"], ["--version"])["installed"] is True
    assert seen == ["/usr/bin"]
    seen.clear()
    assert tools._probe(["gone"], ["--version"])["installed"] is False
    assert seen == ["/usr/bin", "/mnt/c/x"]


def test_pdk_size_cached_by_mtime_and_on_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(tools, "_dir_size_cache", {})
    monkeypatch.setattr(tools, "_dir_size_disk_loaded", [False])
    tree = tmp_path / "pdk" / "sky130A"
    (tree / "libs.ref").mkdir(parents=True)
    (tree / "libs.ref" / "a.lib").write_bytes(b"x" * (3 * 1024 * 1024))
    walks = []
    real_scandir = os.scandir
    monkeypatch.setattr(tools.os, "scandir", lambda p: walks.append(p) or real_scandir(p))
    assert tools._dir_size_mb(tree) == 3
    n = len(walks)
    assert tools._dir_size_mb(tree) == 3 and len(walks) == n            # no second walk
    assert (tmp_path / "home" / "cache" / "pdk-sizes.json").is_file()
    # A fresh process reads the size from disk.
    monkeypatch.setattr(tools, "_dir_size_cache", {})
    monkeypatch.setattr(tools, "_dir_size_disk_loaded", [False])
    assert tools._dir_size_mb(tree) == 3 and len(walks) == n
    # The tree changed (its mtime moved): measured again.
    time.sleep(0.05)
    (tree / "b.lib").write_bytes(b"y" * (2 * 1024 * 1024))
    assert tools._dir_size_mb(tree) == 5 and len(walks) > n


# --------------------------------------------------------------- cell library

def test_liberty_compact_form_matches_the_parse_tree(tmp_path, monkeypatch):
    from lanex.controller import celllib
    from lanex.tests.test_cells_tab import LIB
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))
    lib_txt = LIB.replace('cell_leakage_power : 0.002;',
                          'leakage_power () { when : "A&B"; value : 0.004; }\n'
                          '    leakage_power () { when : "!A"; value : 0.001; }')
    p = tmp_path / "a.lib"
    p.write_text(lib_txt)
    celllib._CACHE.clear()
    lib = celllib._liberty(p)
    # Same arcs and leakage states as the full parse tree gives.
    header, spans = celllib._split_cells(lib_txt)
    for name, a, b in spans:
        node = next(x for x in celllib._parse_liberty_block(lib_txt[a:b]) if x.get("g") == "cell")
        assert lib["arcs"][name] == celllib._arcs(node)
        assert lib["cells"][name] == celllib._cell_summary(name, node)
    assert lib["leaks"]["t__nand2_1"] == [{"when": "A&B", "value": 0.004}, {"when": "!A", "value": 0.001}]
    # A restarted server reads it from disk, not the Liberty file.
    celllib._CACHE.clear()
    monkeypatch.setattr(Path, "read_text", lambda *a, **k: pytest.fail("Liberty re-read"))
    assert celllib._liberty(p) == lib


def test_parsed_library_cache_is_bounded(tmp_path, monkeypatch):
    from lanex.controller import celllib
    from lanex.tests.test_cells_tab import LIB
    monkeypatch.setenv("LANEX_HOME", str(tmp_path / "home"))
    celllib._CACHE.clear()
    paths = []
    for i in range(5):
        p = tmp_path / f"l{i}.lib"
        p.write_text(LIB)
        paths.append(p)
        celllib._liberty(p)
    kept = [k for k in celllib._CACHE if k[0] == "lib"]
    assert kept == [("lib", str(paths[3])), ("lib", str(paths[4]))]
    celllib._liberty(paths[3])                 # most recently used moves last
    celllib._liberty(paths[0])
    assert [k for k in celllib._CACHE if k[0] == "lib"] == [("lib", str(paths[3])), ("lib", str(paths[0]))]
    celllib._CACHE.clear()
