# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License").
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0

"""Smoke tests for the HTTP layer.

Run a real ``ThreadingHTTPServer`` on a free port and exercise the JSON API
with stdlib ``urllib``. We don't make assertions about LibreLane's runtime
correctness; we assert the wiring (routes are wired, JSON works, SSE
returns at least a hello event).
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.parse
import urllib.request
import urllib.error
import contextlib
from http.client import HTTPConnection
from pathlib import Path

import pytest


def _pick_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(port: int, timeout: float = 5.0):
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=1)
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            if resp.status == 200:
                resp.read()
                conn.close()
                return
            conn.close()
        except Exception as ex:
            last_err = ex
        time.sleep(0.05)
    raise RuntimeError(f"server not ready on port {port}: {last_err}")


@pytest.fixture(scope="module")
def server():
    from lanex.server.app import make_server

    port = _pick_port()
    httpd, actual = make_server(host="127.0.0.1", port=port)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    _wait_ready(actual)
    yield actual
    httpd.shutdown()
    httpd.server_close()


def test_health_ok(server):
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/health")
    body = json.loads(resp.read())
    assert body["ok"] is True
    assert body["data"]["service"] == "lanex"


def test_variables_endpoint_returns_list(server):
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/variables")
    body = json.loads(resp.read())
    assert body["ok"]
    assert isinstance(body["data"], list)
    if body["data"]:
        for v in body["data"][:3]:
            assert "name" in v and "type" in v


def test_steps_endpoint_returns_list(server):
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/steps")
    body = json.loads(resp.read())
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 50


def test_design_formats(server):
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/design-formats")
    body = json.loads(resp.read())
    ids = {d["id"] for d in body["data"]}
    assert "def" in ids and "gds" in ids


def test_flows(server):
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/flows")
    body = json.loads(resp.read())
    assert isinstance(body["data"], list)


def test_drc_reports_missing(tmp_path: Path, server):
    # The reports endpoint is confined to the active design dir / PDK roots, so
    # point it at tmp_path first; a missing report file inside it parses to empty.
    sd = json.dumps({"path": str(tmp_path)}).encode()
    urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{server}/api/set-design-dir", data=sd, method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    ))
    qs = urllib.parse.urlencode({"path": str(tmp_path / "missing.drc")})
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/reports/drc?{qs}")
    body = json.loads(resp.read())
    assert body["ok"]
    assert body["data"]["bbox_count"] == 0


def test_read_text_rejects_path_outside_design(tmp_path: Path, server):
    # Confinement (security): an absolute path outside the design/PDK roots is refused.
    sd = json.dumps({"path": str(tmp_path)}).encode()
    urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{server}/api/set-design-dir", data=sd, method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    ))
    qs = urllib.parse.urlencode({"path": "/etc/passwd"})
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{server}/api/read-text?{qs}")
        assert False, "expected 403 for path outside the design dir"
    except urllib.error.HTTPError as e:
        assert e.code == 403


def test_post_routes_json_body(server, tmp_path: Path):
    # POST /api/set-design-dir with bad path -> 400 JSON
    data = json.dumps({"path": "/this/really/does/not/exist"}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{server}/api/set-design-dir",
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    try:
        urllib.request.urlopen(req)
        pytest.fail("expected exception for non-existent design dir")
    except urllib.error.HTTPError as ex:
        assert ex.code == 400
        body = json.loads(ex.read())
        assert "error" in body


def test_static_index_served(server):
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/")
    text = resp.read().decode("utf-8")
    assert "LanEx" in text


def test_static_module_served(server):
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/static/modules/api.js")
    text = resp.read().decode("utf-8")
    assert "export const api" in text


def test_sse_sends_hello(server, timeout=2.5):
    """Connect to /api/events, read at least one chunk before idle."""
    try:
        import io

        resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/events", timeout=1)
        assert resp.status == 200
        assert resp.headers.get("Content-Type", "").startswith("text/event-stream")
        # Iterate line-wise — that's what browsers do. urllib handles chunked.
        body_chunks = []
        deadline = time.time() + timeout
        for line in resp:
            body_chunks.append(line.decode("utf-8", errors="replace"))
            if any("hello" in chunk for chunk in body_chunks):
                break
            if time.time() > deadline:
                break
        body = "".join(body_chunks)
        assert "hello" in body or "ping" in body, f"no SSE event received; got: {body!r}"
    finally:
        with contextlib.suppress(Exception):
            resp.close()


def test_tools_endpoint_returns_inventory(server):
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/tools")
    body = json.loads(resp.read())
    assert body["ok"]
    tools = body["data"]["tools"]
    keys = {t["key"] for t in tools}
    assert "yosys" in keys and "openroad" in keys and "klayout" in keys


def test_design_summary_on_missing_dir_returns_400(server):
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{server}/api/design-summary?path=/no/such/dir",
        )
        pytest.fail("expected 400")
    except urllib.error.HTTPError as ex:
        assert ex.code == 400


def test_design_summary_for_real_spm_design(server, tmp_path):
    spm = Path("/tmp/librelane/librelane/examples/spm")
    if not spm.is_dir():
        pytest.skip("SPM example missing")
    qs = urllib.parse.urlencode({"path": str(spm)})
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/design-summary?{qs}")
    s = resp.read().decode("utf-8")
    assert "spm.v" in s or "spm" in s


def test_copy_spm_into_empty_dir(tmp_path, server):
    target = tmp_path / "my-spm"
    payload = json.dumps({"design_dir": str(target)}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{server}/api/copy-spm",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    try:
        urllib.request.urlopen(req)
    except urllib.error.HTTPError as ex:
        if ex.code == 500 and b"get_librelane_root" in ex.read():
            pytest.skip("librelane env lookup not available")
        raise
    assert target.is_dir()
    assert (target / "config.yaml").is_file()


def test_copy_spm_does_not_overwrite_existing_design(tmp_path, server):
    # A folder that already holds a design must NOT be overwritten by the SPM
    # example (that bakes DESIGN_NAME=spm into it). The example must land in a
    # nested spm_example/ subdir, leaving the user's config + sources intact.
    design = tmp_path / "my-design"
    design.mkdir()
    (design / "config.yaml").write_text("DESIGN_NAME: my_cpu\n", encoding="utf-8")
    (design / "cpu.v").write_text("module cpu(); endmodule\n", encoding="utf-8")
    payload = json.dumps({"design_dir": str(design)}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{server}/api/copy-spm",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    try:
        resp = json.loads(urllib.request.urlopen(req).read())
    except urllib.error.HTTPError as ex:
        if ex.code == 500 and b"get_librelane_root" in ex.read():
            pytest.skip("librelane env lookup not available")
        raise
    # The user's design is untouched.
    assert (design / "config.yaml").read_text(encoding="utf-8").strip() == "DESIGN_NAME: my_cpu"
    assert (design / "cpu.v").is_file()
    # SPM landed in the nested subdir, which is now the active design.
    nested = design / "spm_example"
    assert nested.is_dir() and (nested / "config.yaml").is_file()
    assert resp["data"]["design_dir"] == str(nested)


def test_json_safe_makes_non_finite_strict_parseable():
    # LibreLane metrics like timing__setup_r2r__ws are +inf when a design has no
    # register-to-register paths. Python's json.dumps emits bare ``Infinity``,
    # which the browser's JSON.parse rejects -> every metrics payload silently
    # breaks. _json_safe must turn the response into STRICT JSON.
    from lanex.server.app import _json_safe

    payload = {
        "ok": True,
        "data": {
            "metrics": {"values": {
                "timing__setup_r2r__ws": float("inf"),
                "x__neg": float("-inf"),
                "x__nan": float("nan"),
                "design__instance__area": 8051.47,
                "design__instance__count": 4096,
                "flag": True,
            }},
            "names": ["a", "b"],
        },
    }
    encoded = json.dumps(_json_safe(payload), allow_nan=False)  # would raise on bare inf/nan
    # Strict parser (no NaN/Infinity constants) — mirrors the browser.
    reparsed = json.loads(encoded, parse_constant=_reject_constant)
    vals = reparsed["data"]["metrics"]["values"]
    assert vals["timing__setup_r2r__ws"] == "Infinity"
    assert vals["x__neg"] == "-Infinity"
    assert vals["x__nan"] == "NaN"
    assert vals["design__instance__area"] == 8051.47
    assert vals["design__instance__count"] == 4096  # ints untouched
    assert vals["flag"] is True                      # bools untouched


def _reject_constant(_c):
    raise AssertionError("payload still contains a non-standard JSON constant")


def test_run_view_metrics_endpoint_is_strict_json(server, tmp_path: Path):
    # End-to-end: a run whose metrics.json contains Infinity must serialize as
    # strict JSON (browser JSON.parse equivalent), not bare ``Infinity``.
    run = tmp_path / "runs" / "RUN"
    (run / "final").mkdir(parents=True)
    (run / "06-yosys-synthesis").mkdir(parents=True)
    (run / "06-yosys-synthesis" / "state_out.json").write_text("{}")
    (run / "final" / "metrics.json").write_text(
        json.dumps({"timing__setup_r2r__ws": float("inf"),
                    "design__instance__area": 100.0}, allow_nan=True)
    )
    # Point the server at this design.
    req = urllib.request.Request(
        f"http://127.0.0.1:{server}/api/set-design-dir",
        data=json.dumps({"path": str(tmp_path)}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    urllib.request.urlopen(req)
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/runs/RUN")
    raw = resp.read().decode()
    # Strict parse must succeed and the inf metric must be the string token.
    body = json.loads(raw, parse_constant=_reject_constant)
    assert body["ok"]
    assert body["data"]["metrics"]["values"]["timing__setup_r2r__ws"] == "Infinity"


def test_reveal_rejects_path_traversal(server, tmp_path: Path):
    # Reveal must never act on a path outside the run dir.
    run = tmp_path / "runs" / "RUN"
    (run / "final").mkdir(parents=True)
    (run / "final" / "metrics.json").write_text("{}")
    set_req = urllib.request.Request(
        f"http://127.0.0.1:{server}/api/set-design-dir",
        data=json.dumps({"path": str(tmp_path)}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    urllib.request.urlopen(set_req)
    bad = urllib.request.Request(
        f"http://127.0.0.1:{server}/api/reveal",
        data=json.dumps({"tag": "RUN", "path": "../../../../etc/passwd"}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    try:
        urllib.request.urlopen(bad)
        raise AssertionError("traversal path should have been rejected")
    except urllib.error.HTTPError as ex:
        assert ex.code in (400, 404)


def test_run_outputs_endpoint_lists_final(server, tmp_path: Path):
    run = tmp_path / "runs" / "RUN"
    (run / "final" / "gds").mkdir(parents=True)
    (run / "final" / "gds" / "spm.gds").write_bytes(b"GDS")
    set_req = urllib.request.Request(
        f"http://127.0.0.1:{server}/api/set-design-dir",
        data=json.dumps({"path": str(tmp_path)}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"},
    )
    urllib.request.urlopen(set_req)
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/run-outputs?tag=RUN")
    body = json.loads(resp.read())
    assert body["ok"]
    outs = body["data"]["outputs"]
    assert any(o["format"] == "gds" and o["category"] == "Layout" for o in outs)


def test_preflight_reports_blockers_with_no_design(server):
    # With nothing loaded, preflight must return a clear, non-empty blocker list
    # and a structured breakdown — never a 500.
    resp = urllib.request.urlopen(f"http://127.0.0.1:{server}/api/preflight?pdk=&scl=")
    body = json.loads(resp.read())
    assert body["ok"]
    data = body["data"]
    assert data["ready"] is False
    assert isinstance(data["blockers"], list) and data["blockers"]
    assert "design" in data and "pdk" in data and "tools" in data
    assert isinstance(data["tools"]["tools"], list)


def _post(server, path, body, extra_headers=None):
    headers = {"Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(
        f"http://127.0.0.1:{server}{path}", data=body, method="POST", headers=headers)
    return urllib.request.urlopen(req)


def test_post_without_xrw_is_rejected(server):
    req = urllib.request.Request(
        f"http://127.0.0.1:{server}/api/set-design-dir", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"})  # no X-Requested-With
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(req)
    assert ei.value.code == 403


def test_post_cross_origin_rejected(server):
    # Present-but-mismatched Origin → 403 (same-origin guard).
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(server, "/api/set-design-dir", b'{"path":"/tmp"}',
              {"Origin": "http://evil.example.com"})
    assert ei.value.code == 403


def test_post_same_origin_allowed(server):
    # Matching Origin (host:port) → allowed.
    resp = _post(server, "/api/set-design-dir", b'{"path":"/tmp"}',
                 {"Origin": f"http://127.0.0.1:{server}"})
    assert resp.status == 200


def test_post_malformed_json_400(server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(server, "/api/set-design-dir", b"{not json")
    assert ei.value.code == 400


def test_make_server_refuses_remote_bind_without_flag():
    from lanex.server.app import make_server
    with pytest.raises(RuntimeError):
        make_server(host="192.168.1.50", port=0)
