#!/usr/bin/env python3
"""Live-server API e2e CI driver: the audited lifecycle, re-proven per run.

Boots the real server (``python -m lanex --no-browser``) on the runner, drives
it over HTTP exactly like the manual accuracy audits did, with a container
engine available. Cases (all must pass; each prints PASS/FAIL + detail):

  E1  canary input fidelity — overrides land in resolved.json, design sources
      untouched outside runs/, flow completes with no failed step
  E2  metric passthrough over HTTP — API metrics == final/metrics.json, 0
      diffs (non-finite string tokens are the documented wire contract)
  E3  cancel kills the container — the live regression test for the
      cancel-orphan fix: container gone within seconds of /api/run/cancel, no
      further step dirs, next run startable
  E4  SSE honesty — step_started events == step dirs created; terminal event
  E5  export fidelity — CSV cross-checks numerically against metrics.json;
      MD uses the Infinity token spelling when non-finite metrics exist
  E6  bundle roundtrip — every non-generated member byte-EQUAL to disk;
      import of the bundle reproduces identical metrics
  E7  three-state verdicts — a mutilated (no final/) and a corrupt
      (truncated metrics.json) import must never read as ready
  E8  concurrency guard — second /api/run/start during a run → HTTP 400
  E9  spaces-in-path guard — set-design-dir warns, run/start blocks with the
      real reason
  E10 crash-restart honesty — kill -9 mid-run (bypasses the cancel path BY
      DESIGN, so the orphan container is expected and cleaned here), restart,
      the interrupted run lists honestly and is not "ready"
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SC = Path(__file__).resolve().parent
REPO = SC.parent.parent
sys.path.insert(0, str(SC))
sys.path.insert(0, str(REPO))

import compare_flat  # noqa: E402
import bundle_verify  # noqa: E402
import csv_cross  # noqa: E402
import sse_capture  # noqa: E402
from differential_run import PDK_ROOT, ensure_pdk  # noqa: E402
from flatten_metrics import flatten  # noqa: E402
from hash_tree import manifest  # noqa: E402

PORT = int(os.environ.get("LANEX_CI_PORT", "8763"))
# Mutable so a server (re)boot can move ports: the server auto-falls-back to
# the next free port when the preferred one is taken (app.py _bind), and a
# kill -9'd server's lingering SSE connection can hold the old port hostage —
# polling a fixed port then "times out" against a perfectly healthy server.
_CUR = {"base": f"http://127.0.0.1:{PORT}", "port": PORT}


def BASE() -> str:
    return _CUR["base"]
PDK = os.environ.get("LANEX_CI_PDK", "sky130A")
SCL = os.environ.get("LANEX_CI_SCL", "sky130_fd_sc_hd")
WORK = Path(os.environ.get("LANEX_CI_WORK", str(Path.cwd() / "ciwork"))).resolve()
FLOW_TIMEOUT = int(os.environ.get("LANEX_CI_LEG_TIMEOUT", "3600"))

_HDRS = {"X-Requested-With": "XMLHttpRequest", "Content-Type": "application/json"}


def log(msg: str) -> None:
    print(f"[e2e] {msg}", flush=True)


# ---------------------------------------------------------------------------
# HTTP + server plumbing
# ---------------------------------------------------------------------------

def http(method: str, path: str, body: Optional[Dict[str, Any]] = None,
         timeout: float = 60) -> Tuple[int, Any]:
    """Returns (http_status, unwrapped payload). The server wraps every JSON
    response as {"ok":…, "data"/"error": …}; we hand back data (or the error
    text) so cases assert on content, and the status code for the gate."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE() + path, data=data, method=method,
                                 headers=_HDRS if method == "POST" else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as ex:
        raw = ex.read()
        status = ex.code
    try:
        obj = json.loads(raw.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 - non-JSON body (binary endpoints use http_raw)
        return status, raw
    if isinstance(obj, dict) and "ok" in obj:
        return status, obj.get("data", obj.get("error"))
    return status, obj


def http_raw(path: str, timeout: float = 300) -> Tuple[int, bytes]:
    try:
        with urllib.request.urlopen(BASE() + path, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as ex:
        return ex.code, ex.read()


class Server:
    def __init__(self, pdk_root: Path) -> None:
        self.pdk_root = pdk_root
        self.proc: Optional[subprocess.Popen] = None
        self._boots = 0

    def start(self) -> None:
        # Fresh port per boot: nothing lingering from a previous (possibly
        # kill -9'd) instance can shadow it, and _CUR keeps callers pointed
        # at the live instance.
        port = PORT + self._boots
        self._boots += 1
        _CUR["port"] = port
        _CUR["base"] = f"http://127.0.0.1:{port}"
        env = dict(os.environ)
        env["PYTHONPATH"] = f"{REPO}:{env.get('PYTHONPATH', '')}"
        env["PDK_ROOT"] = str(self.pdk_root)
        # Isolated state home: the server persists user state (active design
        # dir etc.) under $LANEX_HOME (default ~/.lanex, platform_env.py) —
        # the test must not overwrite a real user's. Only LANEX_HOME is
        # overridden; overriding HOME itself would hide Python's user-site
        # packages (where librelane may live) from the server.
        home = WORK / "lanex-home"
        home.mkdir(parents=True, exist_ok=True)
        env["LANEX_HOME"] = str(home)
        logf = open(WORK / "server.log", "a", encoding="utf-8")
        # -X faulthandler: if boot ever wedges, the SIGABRT below makes the
        # server dump its own stack into server.log instead of dying silently.
        self.proc = subprocess.Popen(
            [sys.executable, "-X", "faulthandler", "-m", "lanex",
             "--no-browser", "--port", str(port)],
            cwd=REPO, env=env, stdout=logf, stderr=subprocess.STDOUT)
        for _ in range(120):
            time.sleep(1)
            try:
                status, _data = http("GET", "/api/health", timeout=5)
                if status == 200:
                    log(f"server up (pid {self.proc.pid}, port {port})")
                    return
            except Exception:  # noqa: BLE001
                continue
        try:
            os.kill(self.proc.pid, signal.SIGABRT)  # faulthandler → stack in log
            time.sleep(3)
        finally:
            self.proc.kill()
            self.proc = None
        tail = "\n".join((WORK / "server.log").read_text(
            encoding="utf-8", errors="replace").splitlines()[-40:])
        raise RuntimeError(f"server did not come up in 120s; log tail:\n{tail}")

    def kill9(self) -> None:
        if self.proc:
            os.kill(self.proc.pid, signal.SIGKILL)
            self.proc.wait(timeout=30)
            self.proc = None

    def stop(self) -> None:
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


def docker_ps() -> List[str]:
    out = subprocess.run(["docker", "ps", "-q"], capture_output=True,
                         text=True, timeout=30)
    return out.stdout.split()


def wait_for(pred, timeout: float, interval: float = 2.0, what: str = "") -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(interval)
    log(f"TIMEOUT waiting for {what or pred}")
    return False


def poll_flow_done(timeout: float) -> Dict[str, Any]:
    def done() -> bool:
        s, d = http("GET", "/api/run/status", timeout=30)
        return s == 200 and isinstance(d, dict) and d.get("running") is False
    if not wait_for(done, timeout, interval=10, what="flow completion"):
        raise RuntimeError("flow did not finish in time")
    _s, d = http("GET", "/api/run/status")
    return d


def start_run(tag: str, overrides: Dict[str, Any]) -> Tuple[int, Any]:
    body = {"tag": tag,
            "overrides": {"PDK": PDK, "STD_CELL_LIBRARY": SCL, **overrides},
            "sources": [], "extras": [], "mode": "full", "run_mode": "container"}
    return http("POST", "/api/run/start", body)


def run_tags() -> List[str]:
    _s, runs = http("GET", "/api/runs")
    return [r.get("tag", "") for r in runs] if isinstance(runs, list) else []


def flat_lines(obj: Any) -> str:
    return "".join(f"{k}\t{v}\n" for k, v in flatten(obj))


def metric_values(api_metrics: Any) -> Any:
    """The run-detail payload wraps the tool's numbers as {"path": <file>,
    "values": {...}}; `path` is per-run provenance (a copy's path differs by
    design), `values` is the passthrough under test."""
    if isinstance(api_metrics, dict) and isinstance(api_metrics.get("values"), dict):
        return api_metrics["values"]
    return api_metrics


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

class Ctx:
    """Artifacts shared by the ordered cases (E1 feeds most of the rest)."""
    canary_design: Path
    run_dir: Path
    hash_before: List[str]
    sse_log: Path
    e8_result: Optional[Tuple[int, Any]] = None


CTX = Ctx()


def case_e1_canary() -> str:
    design = WORK / "spm_canary"
    if design.exists():
        shutil.rmtree(design)
    shutil.copytree(REPO / "spm", design)
    with open(design / "src" / "spm.v", "a", encoding="utf-8") as fh:
        fh.write("// CANARY_MARKER_ci_e2e\n")
    CTX.canary_design = design
    CTX.hash_before = manifest(str(design), exclude=["runs"])

    s, d = http("POST", "/api/set-design-dir", {"path": str(design)})
    assert s == 200, f"set-design-dir → {s} {d}"

    CTX.sse_log = WORK / "sse.log"
    t = threading.Thread(
        target=sse_capture.capture,
        args=(f"{BASE()}/api/events", str(CTX.sse_log), FLOW_TIMEOUT + 120),
        daemon=True)
    t.start()
    time.sleep(2)

    s, d = start_run("canary", {"FP_CORE_UTIL": 41, "PL_TARGET_DENSITY_PCT": 47})
    assert s == 200, f"run/start → {s} {d}"
    # E8 rides inside E1's running window.
    CTX.e8_result = start_run("conc2", {})

    status = poll_flow_done(FLOW_TIMEOUT)
    failed = {k: v for k, v in (status.get("step_statuses") or {}).items()
              if v == "failed"}
    assert not failed, f"steps failed: {failed}"

    CTX.run_dir = design / "runs" / "canary"
    resolved = json.loads((CTX.run_dir / "resolved.json").read_text(encoding="utf-8"))
    # librelane may type the value int/float/Decimal-string; compare numerically.
    for key, want in (("FP_CORE_UTIL", 41.0), ("PL_TARGET_DENSITY_PCT", 47.0)):
        got = resolved.get(key)
        try:
            got_num = float(got)
        except (TypeError, ValueError):
            got_num = None
        assert got_num == want, f"{key} override lost: {got!r} (want {want})"

    after = manifest(str(design), exclude=["runs"])
    assert after == CTX.hash_before, "design tree changed outside runs/"

    gds = sorted(CTX.run_dir.glob("final/**/*.gds"))
    assert gds and gds[0].stat().st_size > 0, "no non-empty GDS"
    return "overrides in resolved.json; sources untouched; flow green"


def case_e2_passthrough() -> str:
    s, d = http("GET", "/api/runs/canary")
    assert s == 200 and isinstance(d, dict), f"run detail → {s}"
    api_metrics = metric_values(d.get("metrics"))
    assert isinstance(api_metrics, dict) and api_metrics, "no metrics in API payload"
    a = WORK / "api_metrics.flat"
    b = WORK / "disk_metrics.flat"
    a.write_text(flat_lines(api_metrics), encoding="utf-8")
    disk = json.loads((CTX.run_dir / "final" / "metrics.json").read_text(encoding="utf-8"))
    b.write_text(flat_lines(disk), encoding="utf-8")
    rc = compare_flat.main([str(b), str(a), "--canon-nonfinite"])
    assert rc == 0, "API metrics differ from final/metrics.json"
    return f"{len(disk)} top-level metric keys identical over HTTP"


def case_e4_sse() -> str:
    """Every step that materialized on disk was announced on the stream.

    disk ⊆ events, not ==: librelane also echoes "Running …" for repeat
    instances under their BASE id (disk dir `…checkantennas-1` streams as
    `OpenROAD.CheckAntennas`) and for NESTED substeps that write inside a
    parent step's dir (e.g. OpenROAD.DiodeInsertion under RepairAntennas) —
    the mirror faithfully repeats the tool, so extra events are honest."""
    text = CTX.sse_log.read_text(encoding="utf-8", errors="replace")
    started = re.findall(r'"step_id": "([^"]+)"[^\n]*"type": "step_started"', text)

    def base(name: str) -> str:
        return re.sub(r"-\d+$", "", name.lower().replace(".", "-"))

    from collections import Counter
    ev = Counter(base(s) for s in started)
    dirs = Counter(base(re.sub(r"^\d+-", "", p.name))
                   for p in CTX.run_dir.iterdir()
                   if p.is_dir() and re.match(r"^\d+-", p.name))
    missing = {k: v for k, v in dirs.items() if ev.get(k, 0) < v}
    assert not missing, f"step dirs with no step_started event: {missing}"
    assert '"flow_done"' in text, "no terminal flow_done event in SSE stream"
    return (f"{sum(dirs.values())} step dirs all announced "
            f"({len(started)} start events); terminal event seen")


def case_e5_exports() -> str:
    metrics_path = CTX.run_dir / "final" / "metrics.json"
    s, csv_bytes = http_raw("/api/run-export?tag=canary&fmt=csv")
    assert s == 200 and csv_bytes, f"csv export → {s}"
    csv_file = WORK / "export.csv"
    csv_file.write_bytes(csv_bytes)
    rc = csv_cross.main([str(csv_file), str(metrics_path),
                         "--strict", "--min-matched", "50"])
    assert rc == 0, "CSV export failed the numeric cross-check"

    s, md = http_raw("/api/run-export?tag=canary&fmt=md")
    assert s == 200 and md, f"md export → {s}"
    disk_text = metrics_path.read_text(encoding="utf-8")
    note = ""
    if "Infinity" in disk_text or "NaN" in disk_text:
        assert b"Infinity" in md or b"NaN" in md, \
            "non-finite metrics exist but MD export has no Infinity/NaN token"
        note = "; MD uses the token spelling"
    s, _html = http_raw("/api/run-export?tag=canary&fmt=html")
    assert s == 200, f"html export → {s}"
    return "CSV numerically equal to metrics.json" + note


def case_e6_bundle() -> str:
    s, blob = http_raw(
        "/api/run-bundle?tag=canary&include=config,sources,metrics_csv,"
        "settings_csv,analytics_csv,reports,logs,gds")
    assert s == 200 and blob[:2] == b"PK", f"bundle → {s} ({blob[:40]!r})"
    zpath = WORK / "bundle.zip"
    zpath.write_bytes(blob)
    n_members = len(zipfile.ZipFile(zpath).namelist())
    rc = bundle_verify.main([str(zpath), str(CTX.run_dir), "--strict",
                             "--root", str(CTX.canary_design)])
    assert rc == 0, "bundle members not byte-equal to run dir"

    before = set(run_tags())
    s, d = http("POST", "/api/run-import-bundle", {"path": str(zpath)})
    assert s == 200, f"import-bundle → {s} {d}"
    new = [t for t in run_tags() if t not in before]
    assert new, "imported run not visible in /api/runs"
    s, imp = http("GET", f"/api/runs/{new[0]}")
    assert s == 200 and isinstance(imp.get("metrics"), dict), "no metrics on import"
    a = WORK / "orig_api.flat"
    b = WORK / "import_api.flat"
    _s, orig = http("GET", "/api/runs/canary")
    a.write_text(flat_lines(metric_values(orig["metrics"])), encoding="utf-8")
    b.write_text(flat_lines(metric_values(imp["metrics"])), encoding="utf-8")
    rc = compare_flat.main([str(a), str(b)])
    assert rc == 0, "imported bundle metrics differ from the original run"
    return f"{n_members} members byte-verified; import roundtrip identical"


def _slim_run_copy(dest: Path) -> None:
    """Copy the canary run dir WITHOUT its step dirs (hundreds of MB) — the
    verdict reads run-root JSONs + final/, which is all these cases need."""
    def ignore(dirpath, names):
        if Path(dirpath) == CTX.run_dir:
            return [n for n in names if re.match(r"^\d+-", n) or n == "tmp"]
        return []
    shutil.copytree(CTX.run_dir, dest, ignore=ignore)


def case_e7_three_state() -> str:
    stash = WORK / "imports"
    stash.mkdir(exist_ok=True)
    mutilated = stash / "mutilated-run"
    corrupt = stash / "corrupt-run"
    for p in (mutilated, corrupt):
        if p.exists():
            shutil.rmtree(p)
    _slim_run_copy(mutilated)
    shutil.rmtree(mutilated / "final")
    _slim_run_copy(corrupt)
    m = corrupt / "final" / "metrics.json"
    m.write_bytes(m.read_bytes()[: m.stat().st_size // 2])

    verdicts = []
    for p in (mutilated, corrupt):
        before = set(run_tags())
        s, d = http("POST", "/api/run-import-dir", {"path": str(p)})
        assert s == 200, f"import-dir {p.name} → {s} {d}"
        new = [t for t in run_tags() if t not in before]
        assert new, f"{p.name} not visible after import"
        s, v = http("GET", f"/api/verify?tag={new[0]}")
        assert s == 200, f"verify {new[0]} → {s}"
        ready = v.get("ready") if isinstance(v, dict) else None
        assert ready is not True, f"{p.name} imported as READY — verdict lies green"
        verdicts.append(f"{p.name}: ready={ready!r}")
    s, _h = http("GET", "/api/health")
    assert s == 200, "server died on corrupt input"
    return "; ".join(verdicts)


def case_e3_cancel_kills() -> str:
    assert not docker_ps(), f"pre-existing containers: {docker_ps()}"
    s, d = start_run("cancelkill", {})
    assert s == 200, f"run/start → {s} {d}"
    assert wait_for(lambda: bool(docker_ps()), 300, 2, "flow container up"), \
        "container never appeared"
    time.sleep(10)  # let a couple of steps write
    s, d = http("POST", "/api/run/cancel")
    assert s == 200, f"cancel → {s} {d}"
    assert wait_for(lambda: not docker_ps(), 20, 1, "container removal"), \
        f"container still running 20s after cancel: {docker_ps()}"
    _s, status = http("GET", "/api/run/status")
    assert status.get("running") is False, "status still running after cancel"

    run_dir = CTX.canary_design / "runs" / "cancelkill"
    count = len(list(run_dir.glob("[0-9]*"))) if run_dir.is_dir() else 0
    time.sleep(20)
    count2 = len(list(run_dir.glob("[0-9]*"))) if run_dir.is_dir() else 0
    assert count2 == count, f"steps kept appearing after cancel ({count}→{count2})"

    # Post-cancel startability: a fresh run must start (and cancel) cleanly.
    s, d = start_run("postcancel", {})
    assert s == 200, f"post-cancel run/start refused: {s} {d}"
    time.sleep(5)
    http("POST", "/api/run/cancel")
    assert wait_for(lambda: not docker_ps(), 30, 1, "post-cancel cleanup")
    def idle() -> bool:
        _s, st = http("GET", "/api/run/status")
        return st.get("running") is False
    assert wait_for(idle, 60, 2, "runner idle")
    return f"container gone ≤20s post-cancel; no step growth; next run startable"


def case_e8_concurrency() -> str:
    s, d = CTX.e8_result
    assert s == 400, f"second run/start during a run → {s} (want 400): {d}"
    return f"second start rejected with 400: {str(d)[:80]}"


def case_e9_spaces_guard() -> str:
    spaced = WORK / "spm space"
    if spaced.exists():
        shutil.rmtree(spaced)
    shutil.copytree(REPO / "spm", spaced)
    s, d = http("POST", "/api/set-design-dir", {"path": str(spaced)})
    assert s == 200 and isinstance(d, dict) and d.get("warning"), \
        f"no warning for spaced path: {s} {d}"
    s, d = start_run("doomed", {})
    assert s == 400 and "space" in str(d).lower(), \
        f"spaced launch not blocked with the real reason: {s} {d}"
    s, _d = http("POST", "/api/set-design-dir", {"path": str(CTX.canary_design)})
    assert s == 200
    return "warning on open; launch blocked 400 with rename message"


def case_e10_crash_restart(server: Server) -> str:
    s, d = start_run("crashy", {})
    assert s == 200, f"run/start → {s} {d}"
    assert wait_for(lambda: bool(docker_ps()), 300, 2, "flow container up")
    time.sleep(10)
    server.kill9()
    time.sleep(3)
    orphans = docker_ps()
    # SIGKILL bypasses the cancel path BY DESIGN — an orphan here is expected,
    # and cleaning it is the operator's (this test's) job, not a bug.
    for cid in orphans:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=60)
    server.start()
    s, _d = http("POST", "/api/set-design-dir", {"path": str(CTX.canary_design)})
    assert s == 200
    tags = run_tags()
    assert "crashy" in tags, f"interrupted run vanished from /api/runs: {tags}"
    s, v = http("GET", "/api/verify?tag=crashy")
    assert s == 200 and (v.get("ready") is not True), \
        f"interrupted run reads READY: {v}"
    _s, status = http("GET", "/api/run/status")
    assert status.get("running") is False, "restarted server thinks a flow is running"
    return f"orphan(s) cleaned: {len(orphans)}; run listed post-restart, ready={v.get('ready')!r}"


# ---------------------------------------------------------------------------

def main() -> int:
    log("api_e2e driver r4")  # bump when editing: proves which code CI/logs ran
    WORK.mkdir(parents=True, exist_ok=True)
    pdk_root = PDK_ROOT
    ensure_pdk(pdk_root)
    server = Server(pdk_root)
    server.start()

    cases = [
        ("E1 canary input fidelity", case_e1_canary),
        ("E8 concurrency guard", case_e8_concurrency),
        ("E2 metric passthrough over HTTP", case_e2_passthrough),
        ("E4 SSE honesty", case_e4_sse),
        ("E5 export fidelity", case_e5_exports),
        ("E6 bundle roundtrip", case_e6_bundle),
        ("E7 three-state verdicts", case_e7_three_state),
        ("E9 spaces-in-path guard", case_e9_spaces_guard),
        ("E3 cancel kills the container", case_e3_cancel_kills),
        ("E10 crash-restart honesty", lambda: case_e10_crash_restart(server)),
    ]
    results: List[Tuple[str, bool, str]] = []
    try:
        for name, fn in cases:
            log(f"=== {name} ===")
            try:
                detail = fn()
                results.append((name, True, detail))
                log(f"PASS {name}: {detail}")
            except Exception as ex:  # noqa: BLE001
                traceback.print_exc()
                results.append((name, False, f"{type(ex).__name__}: {ex}"))
                log(f"FAIL {name}: {ex}")
    finally:
        server.stop()
        for cid in docker_ps():
            subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=60)

    lines = ["## API e2e", "", "| Case | Result | Detail |", "|---|---|---|"]
    for name, ok, detail in results:
        lines.append(f"| {name} | {'✓ pass' if ok else '✗ FAIL'} | {detail[:160]} |")
    text = "\n".join(lines) + "\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(text)

    failed = [n for n, ok, _ in results if not ok]
    if failed or len(results) < len(cases):
        log(f"FAILED cases: {failed}")
        return 1
    log("all cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
