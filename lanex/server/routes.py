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
"""HTTP request handlers for the LanEx API.

Every public function here is a handler paired with a URL prefix in
``ROUTES``.  The :class:`LibreLaneGUIRequestHandler` dispatches to them.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..controller import (
    alerts,
    fsbrowser,
    history,
    installer,
    introspect,
    pdk as pdk_mod,
    platform_env,
    reports,
    scaffold,
    tools as tools_mod,
)
# Phase 1–4 controller modules (verify, compare, dse, reverify, editor, lint,
# simulate, layout2d, layout3d, cells, plugins) are imported lazily inside their
# handlers so each phase stays independently importable/testable.

_log = logging.getLogger("librelane.gui.routes")

# ---------------------------------------------------------------------------
# Global state (server-process-scoped).
# ---------------------------------------------------------------------------

_ACTIVE_DESIGN_DIR: List[str] = []


def _get_active_design_dir() -> Optional[str]:
    return _ACTIVE_DESIGN_DIR[0] if _ACTIVE_DESIGN_DIR else None


def _set_active_design_dir(path: str) -> None:
    _ACTIVE_DESIGN_DIR.clear()
    _ACTIVE_DESIGN_DIR.append(path)
    # Remember every design the user opens (server-side) so cross-design views
    # (Compare/DSE) find them even if the browser's localStorage is cleared.
    try:
        from ..controller import designs
        designs.remember(path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Static file root
# ---------------------------------------------------------------------------

def static_root() -> Path:
    return Path(__file__).resolve().parent / "static"


# ---------------------------------------------------------------------------
# Query-parameter helpers
# ---------------------------------------------------------------------------

def _query_param(path: str, key: str, default: str = "") -> str:
    if "?" not in path:
        return default
    qs = path.split("?", 1)[1]
    for part in qs.split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            if k == key:
                from urllib.parse import unquote_plus
                return unquote_plus(v)
    return default


def _path_after(prefix: str, path: str) -> str:
    p = path.split("?", 1)[0]
    if p.startswith(prefix):
        return p[len(prefix):]
    return ""


def _respond(handler: Any, data: Any, status: int = 200) -> None:
    if status >= 400:
        handler._send_json({"ok": False, "error": str(data)}, status)
    else:
        handler._send_json({"ok": True, "data": data}, status)


def _read_roots() -> List[Path]:
    """Directories the file-read endpoints (read-text / reports) may serve from.

    The active design dir (covers RTL sources + ``runs/`` artefacts) plus every
    known PDK root (so a PDK's LEF/lib can be previewed). Anything else is
    rejected — these endpoints must not be a general arbitrary-file reader.
    """
    roots: List[Path] = []
    dd = _get_active_design_dir()
    if dd:
        try:
            roots.append(Path(dd).resolve())
        except Exception:
            pass
    try:
        roots.extend(pdk_mod._candidate_pdk_roots())
    except Exception:
        pass
    return roots


def _path_within_roots(path: str) -> bool:
    """True if *path* resolves inside one of :func:`_read_roots` (symlink-safe)."""
    try:
        p = Path(os.path.expanduser(path)).resolve()
    except Exception:
        return False
    for root in _read_roots():
        try:
            if p == root or p.is_relative_to(root):
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# GET handlers
# ---------------------------------------------------------------------------

def h_health(handler: Any) -> None:
    from ..controller import compat
    try:
        probe = compat.probe_compat()
    except Exception:  # never let the probe break the health check
        probe = {"ok": True, "issues": []}
    _respond(handler, {"service": "lanex", "alive": True, "compat": probe})


def h_about(handler: Any) -> None:
    """Read-only product identity for the landing footer + License modal.

    Truth-in-UI: ``version``/``librelane`` come from installed package metadata
    (``None`` when unknown), and ``notice`` is the repo NOTICE file verbatim
    (``None`` when absent) — never a hardcoded copy that could drift. Sent as a
    plain object (not the ``{ok,data}`` envelope) so the frontend reads the
    fields at the top level.
    """
    import importlib.metadata as _md

    def _ver(pkg: str) -> Any:
        try:
            return _md.version(pkg)
        except Exception:
            return None

    notice = None
    try:
        for cand in (
            Path(__file__).resolve().parents[2] / "NOTICE",
            Path(__file__).resolve().parents[1] / "NOTICE",
        ):
            if cand.is_file():
                notice = cand.read_text(encoding="utf-8", errors="replace")
                break
    except Exception:
        notice = None
    if notice is None:
        # Wheel/pipx install: the repo-relative NOTICE doesn't exist, but the
        # file ships in the package's dist-info (pyproject license-files).
        try:
            dist = _md.distribution("lanex")
            for f in (dist.files or []):
                if f.name == "NOTICE":
                    notice = f.locate().read_text(encoding="utf-8", errors="replace")
                    break
        except Exception:
            notice = None

    handler._send_json({
        "name": "LanEx",
        "version": _ver("lanex"),
        "librelane": _ver("librelane"),
        "license": "Apache-2.0",
        "notice": notice,
    }, 200)


def h_steps(handler: Any) -> None:
    try:
        _respond(handler, introspect.list_steps())
    except Exception as ex:
        _log.exception("list_steps failed")
        _respond(handler, str(ex), 500)


def h_step(handler: Any) -> None:
    step_id = _path_after("/api/step/", handler.path)
    if not step_id:
        _respond(handler, "missing step id", 400)
        return
    try:
        data = introspect.get_step(step_id)
        if data is None:
            _respond(handler, f"step '{step_id}' not found", 404)
            return
        _respond(handler, data)
    except Exception as ex:
        _log.exception("get_step failed")
        _respond(handler, str(ex), 500)


def h_variables(handler: Any) -> None:
    try:
        _respond(handler, introspect.list_variables())
    except Exception as ex:
        _log.exception("list_variables failed")
        _respond(handler, str(ex), 500)


def h_design_formats(handler: Any) -> None:
    try:
        _respond(handler, introspect.list_design_formats())
    except Exception as ex:
        _log.exception("list_design_formats failed")
        _respond(handler, str(ex), 500)


def h_flows(handler: Any) -> None:
    try:
        _respond(handler, introspect.list_flows())
    except Exception as ex:
        _log.exception("list_flows failed")
        _respond(handler, str(ex), 500)


def h_pdks(handler: Any) -> None:
    try:
        _respond(handler, pdk_mod.list_pdks())
    except Exception as ex:
        _log.exception("list_pdks failed")
        _respond(handler, str(ex), 500)


def h_scls(handler: Any) -> None:
    pdk = _query_param(handler.path, "pdk")
    if not pdk:
        _respond(handler, "missing pdk query param", 400)
        return
    try:
        _respond(handler, pdk_mod.list_scls(pdk))
    except Exception as ex:
        _log.exception("list_scls failed")
        _respond(handler, str(ex), 500)


def h_pdk_ready(handler: Any) -> None:
    pdk = _query_param(handler.path, "pdk")
    scl = _query_param(handler.path, "scl")
    run_mode = "container" if _query_param(handler.path, "run_mode") == "container" else "local"
    if not pdk:
        _respond(handler, "missing pdk", 400)
        return
    try:
        _respond(handler, pdk_mod.check_pdk_ready(pdk, scl or None, run_mode))
    except Exception as ex:
        _log.exception("check_pdk_ready failed")
        _respond(handler, str(ex), 500)


def h_known_designs(handler: Any) -> None:
    """Design dirs the user has opened (server-remembered) + the active one — so
    cross-design pickers (Compare/DSE) find every design, not just localStorage's."""
    from ..controller import designs
    known = designs.list_designs()
    active = _get_active_design_dir()
    if active and active not in known:
        known = [active] + known
    _respond(handler, {"designs": known})


def h_runs(handler: Any) -> None:
    # Optional ?design_dir=<path> lists runs for a specific design instead of the
    # active one — used by the Runs tab's "All history" scope, which fans out over
    # the user's recent design dirs. Read-only metadata under <dir>/runs/.
    explicit = _query_param(handler.path, "design_dir")
    design_dir = explicit if (explicit and Path(explicit).expanduser().is_dir()) else _get_active_design_dir()
    if not design_dir:
        _respond(handler, [])
        return
    try:
        _respond(handler, history.list_runs(design_dir))
    except Exception as ex:
        _log.exception("list_runs failed")
        _respond(handler, str(ex), 500)


def h_run_step_log(handler: Any) -> None:
    """One step's log + reports, for click-to-inspect on the flow graph.

    ``step`` is the flow step id (e.g. ``OpenROAD.Floorplan``). ``tag`` selects
    the run; omitted -> newest run (which is the live/just-finished one).
    """
    step = _query_param(handler.path, "step")
    tag = _query_param(handler.path, "tag")
    if not step:
        _respond(handler, "missing step", 400)
        return
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    runs_dir = Path(design_dir) / "runs"
    run_dir = None
    if tag:
        cand = runs_dir / tag
        if cand.is_dir():
            run_dir = cand
    if run_dir is None:
        try:
            subdirs = [d for d in runs_dir.iterdir() if d.is_dir()]
            run_dir = max(subdirs, key=lambda d: d.stat().st_mtime) if subdirs else None
        except Exception:
            run_dir = None
    if run_dir is None:
        _respond(handler, "no runs found for this design", 404)
        return
    try:
        _respond(handler, history.get_step_output(str(run_dir), step))
    except Exception as ex:
        _log.exception("get_step_output failed")
        _respond(handler, str(ex), 500)


def h_run(handler: Any) -> None:
    tag = _path_after("/api/runs/", handler.path)
    if not tag:
        _respond(handler, "missing run tag", 400)
        return
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    run_path = Path(design_dir) / "runs" / tag
    if not run_path.is_dir():
        _respond(handler, f"run '{tag}' not found", 404)
        return
    try:
        _respond(handler, history.get_run(run_path))
    except Exception as ex:
        _log.exception("get_run failed")
        _respond(handler, str(ex), 500)


def h_tools(handler: Any) -> None:
    try:
        _respond(handler, tools_mod.check_tools())
    except Exception as ex:
        _log.exception("check_tools failed")
        _respond(handler, str(ex), 500)


def h_run_status(handler: Any) -> None:
    from ..server.app import get_runner
    r = get_runner()
    # A run cancelled before LibreLane created its run dir leaves status
    # pointing at a path that never came to exist, while /api/runs (rightly)
    # doesn't list it. Report None instead of a phantom path so the two
    # endpoints can't contradict each other.
    run_dir = r.run_dir
    if run_dir and not Path(run_dir).is_dir():
        run_dir = None
    _respond(handler, {
        "running": r.running,
        "cancelled": r.cancelled,
        "paused": r.paused,
        "run_dir": run_dir,
        "step_statuses": r.step_statuses,
    })


def h_reports_drc(handler: Any) -> None:
    path = _query_param(handler.path, "path")
    if not path:
        _respond(handler, "missing path", 400)
        return
    if not _path_within_roots(path):
        _respond(handler, "path is outside the active design / PDK directories", 403)
        return
    try:
        _respond(handler, reports.parse_drc(path))
    except Exception as ex:
        _log.exception("parse_drc failed")
        _respond(handler, str(ex), 500)


def h_reports_lvs(handler: Any) -> None:
    path = _query_param(handler.path, "path")
    if not path:
        _respond(handler, "missing path", 400)
        return
    if not _path_within_roots(path):
        _respond(handler, "path is outside the active design / PDK directories", 403)
        return
    try:
        _respond(handler, reports.parse_lvs(path))
    except Exception as ex:
        _log.exception("parse_lvs failed")
        _respond(handler, str(ex), 500)


def h_fs_roots(handler: Any) -> None:
    import platform
    roots: List[Dict[str, str]] = []
    system = platform.system()
    if system in ("Linux", "Darwin"):
        roots.append({"label": "/ (root)", "path": "/"})
        roots.append({"label": "Home", "path": str(Path.home())})
        roots.append({"label": "Current dir", "path": str(Path.cwd())})
    elif system == "Windows":
        for drive in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            p = Path(f"{drive}:\\")
            if p.exists():
                roots.append({"label": f"{drive}:\\", "path": str(p)})
        roots.append({"label": "Desktop", "path": str(Path.home() / "Desktop")})
    _respond(handler, {"roots": roots})


def h_fs_list(handler: Any) -> None:
    path = _query_param(handler.path, "path")
    if not path:
        _respond(handler, "missing path", 400)
        return
    try:
        _respond(handler, fsbrowser.list_dir(path))
    except Exception as ex:
        _log.exception("list_dir failed")
        _respond(handler, str(ex), 500)


def h_walk_sources(handler: Any) -> None:
    path = _query_param(handler.path, "path")
    if not path:
        _respond(handler, "missing path", 400)
        return
    try:
        _respond(handler, fsbrowser.walk_sources(path))
    except Exception as ex:
        _log.exception("walk_sources failed")
        _respond(handler, str(ex), 500)


def h_run_reports(handler: Any) -> None:
    design_dir = _query_param(handler.path, "design_dir")
    run_tag = _query_param(handler.path, "run_tag")
    if not design_dir or not run_tag:
        _respond(handler, "missing design_dir or run_tag", 400)
        return
    try:
        _respond(handler, fsbrowser.list_run_reports(design_dir, run_tag))
    except Exception as ex:
        _log.exception("list_run_reports failed")
        _respond(handler, str(ex), 500)


def h_read_text(handler: Any) -> None:
    path = _query_param(handler.path, "path")
    if not path:
        _respond(handler, "missing path", 400)
        return
    if not _path_within_roots(path):
        _respond(handler, "path is outside the active design / PDK directories", 403)
        return
    try:
        _respond(handler, fsbrowser.read_text(path))
    except Exception as ex:
        _log.exception("read_text failed")
        _respond(handler, str(ex), 500)


def _config_source_count(design_dir: Path, cfg_name: Optional[str]) -> Optional[int]:
    """How many files the config's ``VERILOG_FILES`` actually resolves to.

    Mirrors LibreLane's semantics for the common forms: a ``dir::`` prefix is
    relative to the config's directory, globs expand, lists and
    whitespace-separated strings both work. Returns ``None`` (pill stays
    count-only) when the config can't be read or has no VERILOG_FILES —
    a guessed number here would defeat the point of the label.
    """
    if not cfg_name:
        return None
    cfgp = design_dir / cfg_name
    try:
        if cfg_name.endswith(".json"):
            data = json.loads(cfgp.read_text(encoding="utf-8"))
        elif cfg_name.endswith((".yaml", ".yml")):
            import yaml as _yaml
            data = _yaml.safe_load(cfgp.read_text(encoding="utf-8"))
        else:
            return None
        if not isinstance(data, dict):
            return None
        vf = data.get("VERILOG_FILES")
        if vf is None:
            return None
        items = [str(x) for x in vf] if isinstance(vf, list) else str(vf).split()
        count = 0
        for s in items:
            if s.startswith("dir::"):
                s = s[len("dir::"):]
            if any(ch in s for ch in "*?["):
                count += sum(1 for m in design_dir.glob(s) if m.is_file())
            else:
                fp = Path(s) if os.path.isabs(s) else design_dir / s
                count += 1 if fp.is_file() else 0
        return count
    except Exception:
        return None


def h_design_summary(handler: Any) -> None:
    # C5 — decision (kept intentionally unconfined): this endpoint reads an
    # arbitrary directory the user is about to pick as their design. It is the
    # SAME trust class as the folder-browser endpoints (fs-roots / fs-list) — the
    # user must be able to inspect any directory before choosing it, so path
    # confinement here would break the picker. The exposure is bounded to the
    # local machine: after C1 the server binds loopback only unless the user
    # explicitly passes --allow-remote. It only ever lists source-file names and
    # config presence, never file contents. Do NOT "harden" this into a confined
    # path — that regresses the folder browser.
    path = _query_param(handler.path, "path")
    if not path:
        _respond(handler, "missing path", 400)
        return
    p = Path(path).resolve()
    if not p.is_dir():
        _respond(handler, "directory not found", 400)
        return
    try:
        srcs = fsbrowser.walk_sources(str(p))
        pills = [{"type": "info", "text": p.name}]
        cfg = next((f"config.{e}" for e in ("json", "yaml", "tcl") if (p / f"config.{e}").is_file()), None)
        if cfg:
            pills.append({"type": "pass", "text": f"{cfg} ✓"})
        v_count = 0
        if srcs.get("ok"):
            v_count = len(srcs.get("sources", []))
            mem_count = len(srcs.get("memories", []))
            # This is "HDL files found in the folder" (recursive, minus runs/),
            # NOT "files the config compiles" — testbenches outside src/ count
            # here but not in VERILOG_FILES. Say what it is so the number can't
            # be read as the flow's source list.
            cfg_count = _config_source_count(p, cfg)
            label = f"{v_count} HDL file{'s' if v_count != 1 else ''} found"
            if cfg_count is not None and cfg_count != v_count:
                label += f" (config uses {cfg_count})"
            pills.append({"type": "info", "text": label})
            if mem_count:
                pills.append({"type": "info", "text": f"{mem_count} memory files"})
        # Flag a missing config so the UI can offer "Auto-generate config" — but
        # only when there ARE sources to derive one from.
        config_missing = cfg is None
        if config_missing and v_count:
            pills.append({"type": "warn", "text": "no config — can auto-generate"})
        if _whitespace_path_error(str(p)):
            pills.append({"type": "warn", "text": "path contains spaces — runs will fail; use a space-free folder"})
        pills.append({"type": "pending", "text": str(p)})
        _respond(handler, {"pills": pills, "config_missing": config_missing,
                           "has_sources": bool(v_count)})
    except Exception as ex:
        _respond(handler, str(ex), 500)


def h_suggest_config(handler: Any) -> None:
    """Derive a suggested LibreLane config for a design that has none.

    Reads the design's RTL to guess the top module, clock port and source
    files, and folds in the PDK/SCL the user picked (query params). The result
    is an editable suggestion — :func:`h_write_config` does the actual write."""
    from ..controller import autoconfig
    body = getattr(handler, "_body", {}) or {}
    path = body.get("path") or _query_param(handler.path, "path") or _get_active_design_dir()
    if not path:
        _respond(handler, "missing path", 400)
        return
    p = Path(path).resolve()
    if not p.is_dir():
        _respond(handler, "directory not found", 400)
        return
    pdk = body.get("pdk") or _query_param(handler.path, "pdk") or None
    scl = body.get("scl") or _query_param(handler.path, "scl") or None
    # The tick-marked source list (POST body) restricts top-module detection to
    # exactly those files, so an unticked testbench is never picked (issue #1).
    files = body.get("files") if isinstance(body.get("files"), list) else None
    try:
        result = autoconfig.suggest_config(str(p), pdk=pdk, scl=scl, only_files=files or None)
        result["already_has_config"] = autoconfig.has_config(str(p))
        _respond(handler, result)
    except Exception as ex:
        _log.exception("suggest_config failed")
        _respond(handler, str(ex), 500)


def h_write_config(handler: Any) -> None:
    """Write an (auto-generated, user-confirmed) config into the design dir.

    Confined to the design dir; refuses to clobber an existing config unless
    ``overwrite`` is set. Only verified-real LibreLane variables are written."""
    from ..controller import autoconfig
    body = getattr(handler, "_body", {})
    path = body.get("path") or _get_active_design_dir()
    config = body.get("config")
    if not path:
        _respond(handler, "missing path", 400)
        return
    if not isinstance(config, dict):
        _respond(handler, "missing config object", 400)
        return
    result = autoconfig.write_config(
        path, config, fmt=body.get("format", "json"), overwrite=bool(body.get("overwrite"))
    )
    if not result.get("ok"):
        _respond(handler, result.get("error", "write failed"), 400)
        return
    _respond(handler, result)


# ---------------------------------------------------------------------------
# POST handlers
# ---------------------------------------------------------------------------

def h_get_design_dir(handler: Any) -> None:
    _respond(handler, {"design_dir": _get_active_design_dir()})


# Tools a full Classic RTL->GDS run shells out to, in flow order. ``required``
# means the flow cannot finish without it; the rest still block signoff.
_RUN_TOOLS = [
    ("verilator", "Verilator", "RTL lint", True),
    ("yosys", "Yosys", "synthesis", True),
    ("openroad", "OpenROAD", "place & route, STA", True),
    ("klayout", "KLayout", "DRC + layout render", True),
    ("magic", "Magic", "signoff DRC + GDS", True),
    ("netgen", "Netgen", "LVS", True),
]


# Short TTL cache for the preflight tool/engine probe. Preflight fires on every
# design-load and PDK change; the toolchain doesn't change between those, so a
# few seconds of caching turns repeated multi-second `check_tools()` calls into
# one. (check_tools() itself is also TTL-cached now — this outer layer predates
# that and stays as a cheap short-circuit; both invalidate within seconds.)
_PREFLIGHT_TOOLS_CACHE: Dict[str, Any] = {"t": 0.0, "v": None}


def _preflight_tools_cached(ttl: float = 8.0) -> Dict[str, Any]:
    import time
    now = time.time()
    cached = _PREFLIGHT_TOOLS_CACHE
    if cached["v"] is not None and (now - cached["t"]) < ttl:
        return cached["v"]
    try:
        v = tools_mod.check_tools()
    except Exception:
        v = {}
    cached["t"] = now
    cached["v"] = v
    return v


def h_preflight(handler: Any) -> None:
    """One call that answers 'can I press Run yet?' for absolute beginners.

    Checks the four things a run needs — a design folder, a config file,
    Verilog sources, a ready PDK, and the EDA tools — and returns a plain
    checklist with the exact blockers, so the user fixes them up front instead
    of watching a run fail cryptically half-way through.
    """
    pdk = _query_param(handler.path, "pdk")
    scl = _query_param(handler.path, "scl")
    run_mode = "container" if _query_param(handler.path, "run_mode") == "container" else "local"
    design_dir = _get_active_design_dir()

    blockers: List[str] = []

    # The two slow probes — PDK readiness (may touch ciel) and the tool/engine
    # check (subprocess version probes + `docker info`) — run concurrently with
    # the cheap design-folder checks below, so preflight (which fires on every
    # design-load AND PDK change) isn't a multi-second serial wait. The tools
    # probe is also TTL-cached since it doesn't change between those events.
    from concurrent.futures import ThreadPoolExecutor
    _pool = ThreadPoolExecutor(max_workers=2)
    _pdk_future = _pool.submit(
        (lambda: pdk_mod.check_pdk_ready(pdk, scl or None, run_mode)) if pdk
        else (lambda: {"ready": False, "missing": ["no PDK selected"]})
    )
    _tools_future = _pool.submit(_preflight_tools_cached)

    # 1) Design folder + config + sources.
    design_ok = bool(design_dir) and Path(design_dir).is_dir()
    config_file = None
    source_count = 0
    if design_ok:
        for ext in ("yaml", "yml", "json", "tcl"):
            cf = Path(design_dir) / f"config.{ext}"
            if cf.is_file():
                config_file = cf.name
                break
        try:
            srcs = fsbrowser.walk_sources(design_dir)
            source_count = len(srcs.get("sources", [])) if srcs.get("ok") else 0
        except Exception:
            source_count = 0
    if not design_ok:
        blockers.append("Pick a design folder (or click ‘Use the SPM example’).")
    elif not config_file:
        blockers.append("No config.yaml/json found in the design folder.")
    elif source_count == 0:
        blockers.append("No Verilog (.v/.sv) sources found in the design folder.")

    design_block = {
        "ok": bool(design_ok and config_file and source_count),
        "dir": design_dir,
        "config_file": config_file,
        "source_count": source_count,
    }

    # 2) PDK readiness (mode-aware: container needs the exact pinned version in
    #    a ciel store; local just needs the files present under pdk_root).
    try:
        pdk_block = _pdk_future.result()
    except Exception:
        pdk_block = {"ready": False, "missing": ["PDK check failed"]}
    pdk_block["pdk"] = pdk
    pdk_block["scl"] = scl
    if not pdk_block.get("ready"):
        miss = ", ".join(pdk_block.get("missing") or ["select a PDK + standard-cell library"])
        # If the only thing missing is a download the engine can do on its own
        # AND the release host is reachable, don't hard-block — it'll fetch on
        # the run. Offline + missing stays a real blocker (the run would die
        # mid-flight with a network traceback otherwise).
        if pdk_block.get("needs_download") and pdk_block.get("network_available"):
            pdk_block["note"] = (
                "Required PDK isn't local yet; LibreLane will download it on the first run "
                "(needs network, one-time)."
            )
        else:
            blockers.append(f"PDK not ready: {miss}.")

    # 3) Engine: in container mode the only host requirement is Docker/Podman
    #    (every EDA tool ships in the version-matched image). In local mode we
    #    probe the six native tools a Classic RTL->GDS run shells out to.
    try:
        tools_info = _tools_future.result()
    except Exception:
        tools_info = {}
    finally:
        _pool.shutdown(wait=False)

    if run_mode == "container":
        engine = tools_info.get("container") or tools_mod.container_engine()
        if not engine.get("available"):
            blockers.append(
                "Install Docker or Podman (one install gives you every EDA tool via the LibreLane image)."
            )
        elif not engine.get("daemon_ok"):
            eng = engine.get("engine") or "engine"
            blockers.append(
                f"{eng} is installed but not usable yet: {engine.get('daemon_msg') or 'daemon not reachable'}. "
                f"Start the service and ensure your user can run it (e.g. `sudo systemctl enable --now docker` "
                f"then `sudo usermod -aG docker $USER` and re-login)."
            )
        tools_block = {
            "ok": bool(engine.get("ready")),
            "mode": "container",
            "engine": engine,
        }
    else:
        installed = {t["key"]: t for t in tools_info.get("tools", [])}
        tool_rows = []
        missing_tools = []
        for key, label, role, required in _RUN_TOOLS:
            is_in = bool(installed.get(key, {}).get("installed"))
            tool_rows.append(
                {"key": key, "label": label, "role": role, "installed": is_in, "required": required}
            )
            if required and not is_in:
                missing_tools.append(label)
        if missing_tools:
            blockers.append(
                "Missing tools: " + ", ".join(missing_tools) + " (see the Tools tab)."
            )
        tools_block = {"ok": not missing_tools, "mode": "local", "tools": tool_rows, "missing": missing_tools}

    _respond(
        handler,
        {
            "ready": not blockers,
            "run_mode": run_mode,
            "blockers": blockers,
            "design": design_block,
            "pdk": pdk_block,
            "tools": tools_block,
        },
    )


def h_set_design_dir(handler: Any) -> None:
    body = getattr(handler, "_body", {})
    path = body.get("path", "")
    if not path:
        _respond(handler, "missing path", 400)
        return
    p = Path(path).resolve()
    if not p.is_dir():
        _respond(handler, "directory not found", 400)
        return
    _set_active_design_dir(str(p))
    out: Dict[str, Any] = {"design_dir": str(p)}
    ws_err = _whitespace_path_error(str(p))
    if ws_err:
        out["warning"] = ws_err
    _respond(handler, out)


def h_diff(handler: Any) -> None:
    body = getattr(handler, "_body", {})
    a = body.get("a", "")
    b = body.get("b", "")
    if not a or not b:
        _respond(handler, "need 'a' and 'b' run tags", 400)
        return
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    da = Path(design_dir) / "runs" / a
    db = Path(design_dir) / "runs" / b
    if not da.is_dir() or not db.is_dir():
        missing = ", ".join(t for t, d in ((a, da), (b, db)) if not d.is_dir())
        _respond(handler, f"run(s) not found: {missing}", 404)
        return
    try:
        _respond(handler, history.diff_runs(da, db))
    except Exception as ex:
        _log.exception("diff_runs failed")
        _respond(handler, str(ex), 500)


def h_explain(handler: Any) -> None:
    body = getattr(handler, "_body", {})
    message = body.get("message", "")
    if not message:
        _respond(handler, "missing message", 400)
        return
    try:
        _respond(handler, alerts.explain_alert(message))
    except Exception as ex:
        _log.exception("explain_alert failed")
        _respond(handler, str(ex), 500)


def h_explain_checker(handler: Any) -> None:
    body = getattr(handler, "_body", {})
    checker = body.get("checker", "")
    metric = body.get("metric")
    if not checker:
        _respond(handler, "missing checker", 400)
        return
    try:
        _respond(handler, alerts.explain_checker_failure(checker, metric))
    except Exception as ex:
        _log.exception("explain_checker failed")
        _respond(handler, str(ex), 500)


def _clean_overrides(overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Drop override keys with an empty / null / whitespace-only value so the GUI
    never passes a bare ``KEY=`` to LibreLane.

    A blank constraint field produced ``-c PDN_CORE_RING_VOFFSET=`` → the engine
    tried to parse ``""`` into a Decimal and crashed config validation instead of
    falling back to the PDK default. Stripping empties here makes "leave it blank"
    mean "use the default" (issue #11). Real falsy values (``0``, ``False``) and
    non-empty lists are preserved; only None / "" / all-whitespace / empty list go.
    """
    clean: Dict[str, Any] = {}
    for k, v in (overrides or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and v.strip() == "":
            continue
        if isinstance(v, (list, tuple)):
            items = [x for x in v if not (x is None or (isinstance(x, str) and x.strip() == ""))]
            if not items:
                continue
            clean[k] = list(items)
            continue
        clean[k] = v
    return clean


def _assemble_overrides(design_dir: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Single source of truth for the user-data payload of a run.

    Turns a run-request body into the pieces that carry USER-SUPPLIED data into
    LibreLane: cleaned overrides (with PDK/SCL pulled out as constructor
    kwargs), the per-run custom-cell overrides (``EXTRA_LEFS``/``…`` +
    ``EXTRA_EXCLUDED_CELLS``), and the hard-macro overlay config file. Used by
    BOTH :func:`h_run_start` and every DSE sweep point so a swept run is
    identical to the same run launched from Setup — DSE used to bypass override
    cleaning, custom cells and macros, silently sweeping a *different* design
    than the one shown in the UI (audit A2).

    Returns ``{pdk, scl, overrides, extra_sources, extra_extras,
    extra_config_files}``. Never mutates ``body``; never touches the user's
    ``config.json`` (all of this is per-run only).
    """
    overrides = dict(body.get("overrides") or {})
    pdk = overrides.pop("PDK", None) or body.get("pdk") or None
    scl = overrides.pop("STD_CELL_LIBRARY", None) or body.get("scl") or None
    # Strip blank/None overrides so a left-empty constraint field never becomes a
    # bare ``KEY=`` the engine can't type-parse (issue #11); real 0/False kept.
    overrides = _clean_overrides(overrides)
    # Fold in any custom standard cells configured for this design. Per-run only.
    try:
        from ..controller import customcells
        cc = customcells.build_overrides(design_dir)
        if cc:
            overrides = customcells.merge_into(overrides, cc)
    except Exception:
        _log.exception("custom-cell overrides failed (continuing without them)")
    # Custom hard macros (the MACROS variable) can't ride a ``-c KEY=VALUE``
    # override — a Dict would be misparsed as a flat Tcl list — so they go through
    # a JSON overlay config file merged by Config.load. Per-run only.
    extra_config_files: List[str] = []
    try:
        from ..controller import custommacros
        overlay = custommacros.write_overlay(design_dir)
        if overlay:
            extra_config_files.append(overlay)
    except Exception:
        _log.exception("custom-macro overlay failed (continuing without it)")
    return {
        "pdk": pdk,
        "scl": scl,
        "overrides": overrides,
        "extra_sources": body.get("sources") or None,
        "extra_extras": body.get("extras") or None,
        "extra_config_files": extra_config_files or None,
    }


def _hash_files(paths: Optional[List[str]]) -> Optional[str]:
    """SHA-256 over the content of the given files, or ``None`` if there are
    none. Used to snapshot the per-run macro overlay into ``gui-run.json`` so a
    later reproduce can detect that the regenerated overlay has drifted (A3)."""
    import hashlib
    files = [p for p in (paths or []) if p]
    if not files:
        return None
    h = hashlib.sha256()
    for p in files:
        try:
            with open(p, "rb") as fh:
                h.update(fh.read())
        except Exception:
            h.update(b"\0missing\0")
    return h.hexdigest()


def _whitespace_path_error(design_dir: str, pdk_root: Optional[str] = None) -> Optional[str]:
    """Refuse to launch a flow from a path LibreLane cannot handle.

    LibreLane's Yosys/Tcl scripts split file lists on whitespace, so a design
    dir (or PDK root) containing a space fails mid-flow with a misleading
    ``ERROR: File '/home/user/my' not found`` (proven live: the same design
    ran 76/76 green through a space-free symlink). Failing here, with the real
    reason, beats a cryptic Yosys error three steps in. Viewing/importing runs
    from spaced paths stays allowed — only *launching* a flow is blocked.
    """
    for label, p in (("design directory", design_dir), ("PDK root", pdk_root)):
        if p and any(ch.isspace() for ch in str(p)):
            return (
                f"the {label} path contains spaces ('{p}') — LibreLane's "
                "Yosys/Tcl scripts split paths on whitespace and the flow will "
                "fail with a misleading 'File not found'. Move/rename the "
                "folder to a space-free path (e.g. my_chip) and re-open it."
            )
    return None


def h_run_start(handler: Any) -> None:
    from ..server.app import get_runner
    body = getattr(handler, "_body", {})
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    ws_err = _whitespace_path_error(design_dir)
    if ws_err:
        _respond(handler, ws_err, 400)
        return
    config_file = None
    for ext in ["json", "yaml", "tcl"]:
        cf = Path(design_dir) / f"config.{ext}"
        if cf.is_file():
            config_file = cf
            break
    
    if config_file is None:
        _respond(handler, "no config.{json,yaml,tcl} found in design directory", 400)
        return
    r = get_runner()
    if r.running:
        _respond(handler, "already running", 400)
        return
    try:
        from librelane.flows import Flow
        flow_name = body.get("flow") or "Classic"
        flow_factory = Flow.factory.get(flow_name)
        if flow_factory is None:
            flows = list(getattr(Flow.factory, "_FlowFactory__registry", {}).values()) or \
                    list(getattr(Flow.factory, "_registry", {}).values())
            if flows:
                flow_factory = flows[0]
            else:
                _respond(handler, f"Flow '{flow_name}' not found", 500)
                return
        # PDK / SCL are construction-time options, not plain config variables.
        # The SPA folds the picker selection into ``overrides``; pull them back
        # out so they reach the Flow constructor as dedicated kwargs.
        run_mode = "container" if body.get("run_mode") == "container" else "local"
        # Assemble everything that carries USER DATA into LibreLane through the
        # ONE shared helper (override cleaning that preserves 0/False, custom-cell
        # overrides, the hard-macro overlay). The DSE sweep path calls the exact
        # same helper, so a swept run can never silently differ from this one.
        _asm = _assemble_overrides(design_dir, body)
        pdk, scl = _asm["pdk"], _asm["scl"]
        overrides = _asm["overrides"]
        extra_config_files: List[str] = list(_asm["extra_config_files"] or [])

        # Resolve the pdk_root that actually holds the files this mode needs, and
        # refuse a run that we already know will fail (PDK genuinely absent and
        # un-downloadable) so the user gets a clear message up front instead of a
        # cryptic network/ciel traceback half-way through the flow.
        pdk_root = os.environ.get("PDK_ROOT") or None
        if pdk:
            pf = pdk_mod.check_pdk_ready(pdk, scl or None, run_mode)
            pdk_root = pf.get("pdk_root") or pdk_root
            if not pf.get("ready"):
                will_download = pf.get("needs_download") and pf.get("network_available")
                if not will_download:
                    miss = "; ".join(pf.get("missing") or ["PDK not ready"])
                    rem = pf.get("remediation") or ""
                    _respond(
                        handler,
                        f"PDK not ready for {run_mode} mode: {miss}." + (f" {rem}" if rem else ""),
                        400,
                    )
                    return
        ws_err = _whitespace_path_error(design_dir, pdk_root)
        if ws_err:
            _respond(handler, ws_err, 400)
            return
        # Snapshot of exactly what the GUI launched, persisted into the run dir
        # as gui-run.json so the user can reproduce this run later (issue #4).
        # LibreLane writes the resolved config; this captures the GUI-only choices
        # (overrides as set, run mode, partial range, sources, the CLI command).
        gui_meta: Dict[str, Any] = {
            "flow": flow_name,
            "pdk": pdk,
            "scl": scl,
            "run_mode": run_mode,
            "mode": body.get("mode") or "full",
            "overrides": overrides,
            "frm": body.get("frm") or None,
            "to": body.get("to") or None,
            "skip": body.get("skip") or [],
            "sources": body.get("sources") or [],
            "extras": body.get("extras") or [],
            # Persist the macro-overlay config path(s) so the run is fully
            # reproducible — the overlay is regenerated per run, so also record a
            # content hash to let a later reproduce detect that it drifted (A3).
            "extra_config_files": list(extra_config_files or []),
            "extra_config_hash": _hash_files(extra_config_files),
            "config_file": str(config_file),
        }
        try:
            from ..controller import manualcmd
            gui_meta["cli_command"] = manualcmd.cli_command_for(
                design_dir=design_dir, config_file=str(config_file),
                flow=flow_name, pdk=pdk, scl=scl, pdk_root=pdk_root,
                run_mode=run_mode, tag=body.get("tag") or None,
                frm=body.get("frm") or None, to=body.get("to") or None,
                skip=body.get("skip") or [], overrides=overrides,
                extra_sources=body.get("sources") or None,
                extra_extras=body.get("extras") or None,
                extra_config_files=extra_config_files or None,
            )
        except Exception:
            _log.debug("cli_command_for failed for gui-run.json", exc_info=True)
        result = r.start(
            flow_factory=flow_factory,
            config_files=[str(config_file)],
            design_dir=design_dir,
            pdk=pdk,
            scl=scl,
            pdk_root=pdk_root,
            tag=body.get("tag") or None,
            frm=body.get("frm") or None,
            to=body.get("to") or None,
            skip=body.get("skip"),
            config_overrides=overrides,
            extra_sources=body.get("sources"),
            extra_extras=body.get("extras"),
            extra_config_files=extra_config_files or None,
            step_mode=(body.get("mode") == "semi"),
            run_mode=run_mode,
            flow_name=flow_name,
            gui_meta=gui_meta,
        )
        _respond(handler, result)
    except Exception as ex:
        _log.exception("run start failed")
        _respond(handler, str(ex), 500)


def _resolve_config_file(design_dir: str) -> Optional[Path]:
    for ext in ("json", "yaml", "tcl"):
        cf = Path(design_dir) / f"config.{ext}"
        if cf.is_file():
            return cf
    return None


def _recorded_cli_command(design_dir: str, tag: str) -> Optional[Dict[str, Any]]:
    """The CLI command recorded in an existing run's ``gui-run.json``, or None.

    Only returns a payload when the recorded dict has both command strings —
    a partial record falls through to live assembly rather than serving half
    an answer.
    """
    try:
        run_dir = Path(design_dir) / "runs" / tag
        meta_file = run_dir / "gui-run.json"
        if not meta_file.is_file():
            return None
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        cmd = meta.get("cli_command")
        if not isinstance(cmd, dict) or not (cmd.get("container") and cmd.get("local")):
            return None
        out = dict(cmd)
        out["recorded"] = True
        out["source"] = str(meta_file)
        return out
    except Exception:
        return None


def h_cli_command(handler: Any) -> None:
    """Return the exact ``librelane`` CLI equivalent to a GUI run config, so the
    user can copy it and run it themselves (manual mode). Read-only."""
    from ..controller import manualcmd
    body = getattr(handler, "_body", {})
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    # A tag naming an EXISTING run returns that run's recorded command verbatim
    # (gui-run.json, written at launch). Re-deriving it here would re-resolve
    # PDK_ROOT from the *current* env — if the env changed since the run, the
    # "reproduce" command would silently diverge from what actually ran.
    tag = body.get("tag") or ""
    if tag:
        recorded = _recorded_cli_command(design_dir, tag)
        if recorded is not None:
            _respond(handler, recorded)
            return
    config_file = _resolve_config_file(design_dir)
    if config_file is None:
        _respond(handler, "no config.{json,yaml,tcl} in design directory", 400)
        return
    run_mode = "container" if body.get("run_mode") == "container" else "local"
    # Assemble EXACTLY like a real run so the revealed command is faithful:
    # cleaned overrides + custom cells + macro overlay + picker sources (A3).
    asm = _assemble_overrides(design_dir, body)
    pdk, scl = asm["pdk"], asm["scl"]
    pdk_root = os.environ.get("PDK_ROOT") or None
    try:
        if pdk:
            pf = pdk_mod.check_pdk_ready(pdk, scl or None, run_mode)
            pdk_root = pf.get("pdk_root") or pdk_root
    except Exception:
        pass
    cmd = manualcmd.cli_command_for(
        design_dir=design_dir, config_file=str(config_file),
        flow=body.get("flow") or "Classic", pdk=pdk, scl=scl, pdk_root=pdk_root,
        run_mode=run_mode, tag=body.get("tag") or None,
        frm=body.get("frm") or None, to=body.get("to") or None,
        skip=body.get("skip") or [], overrides=asm["overrides"],
        extra_sources=asm["extra_sources"], extra_extras=asm["extra_extras"],
        extra_config_files=asm["extra_config_files"],
    )
    _respond(handler, cmd)


def h_manual_run(handler: Any) -> None:
    """Run an allow-listed LibreLane/EDA command from the GUI, streaming output
    over SSE (``manual_started``/``manual_line``/``manual_done``). NOT a shell —
    see controller/manualcmd.py for the allow-list + rejected operators."""
    from ..controller import manualcmd
    body = getattr(handler, "_body", {})
    command = body.get("command", "")
    cwd = _get_active_design_dir()
    result = manualcmd.get_job().start(command, cwd=cwd)
    if not result.get("ok"):
        _respond(handler, result.get("error", "could not run"), 400)
        return
    _respond(handler, result)


def h_manual_cancel(handler: Any) -> None:
    from ..controller import manualcmd
    _respond(handler, manualcmd.get_job().cancel())


def h_manual_result(handler: Any) -> None:
    from ..controller import manualcmd
    job = manualcmd.get_job()
    _respond(handler, {"running": job.running, "result": job.last_result})


def h_run_cancel(handler: Any) -> None:
    from ..server.app import get_runner
    get_runner().cancel()
    _respond(handler, {"status": "cancelled"})


def h_run_resume(handler: Any) -> None:
    from ..server.app import get_runner
    get_runner().resume()
    _respond(handler, {"status": "resumed"})


def h_reproducible(handler: Any) -> None:
    """Report how to create a reproducible test case for a step.

    ``Step.create_reproducible`` is an *instance* method that needs the step's
    resolved config + input state — it can only be produced from a completed
    run, not from the bare step class. (The previous implementation called it on
    the class, which always raised — an HTTP 500.) Rather than re-implement
    LibreLane's run/state loading (which would break the "no private APIs" moat),
    we validate the step and return the exact, supported CLI command instead of
    crashing.
    """
    body = getattr(handler, "_body", {})
    step_id = body.get("step_id", "")
    if not step_id:
        _respond(handler, "missing step_id", 400)
        return
    try:
        from librelane.steps import Step
        if Step.factory.get(step_id) is None:
            _respond(handler, f"step '{step_id}' not found", 404)
            return
    except Exception:
        pass
    design_dir = _get_active_design_dir() or "<design-dir>"
    cmd = f"librelane --dockerized {design_dir}/config.json --reproducible {step_id}"
    _respond(handler, {
        "ok": True,
        "supported": False,
        "step_id": step_id,
        "message": "A reproducible test case is built from a completed run's step "
                   "(it needs that step's resolved config + input state). Create it "
                   "with the LibreLane CLI:",
        "command": cmd,
    })


def h_tools_install(handler: Any) -> None:
    key = _path_after("/api/tools/install/", handler.path)
    if not key:
        _respond(handler, "missing tool key", 400)
        return
    try:
        # Async: a tool install can take minutes (source builds, slow mirrors) —
        # far past the frontend's request timeout, which used to fire a scary
        # "request timed out" popup over a perfectly healthy install. The route
        # returns {status:"started"} immediately; progress streams over SSE and
        # the final outcome arrives as an `installer_result` event.
        result = installer.install_tool_async(key)
        _respond(handler, result)
    except Exception as ex:
        _log.exception("install_tool failed")
        _respond(handler, str(ex), 500)


def h_tools_cancel(handler: Any) -> None:
    body = getattr(handler, "_body", {})
    key = body.get("key")
    if not key:
        _respond(handler, "missing key", 400)
        return
    try:
        result = installer.cancel_install(key)
        _respond(handler, result)
    except Exception as ex:
        _log.exception("cancel_install failed")
        _respond(handler, str(ex), 500)


def h_settings_pdk_root(handler: Any) -> None:
    if handler.command == "GET":
        pdk_root = os.environ.get("PDK_ROOT", os.path.expanduser("~/.ciel"))
        _respond(handler, {"ok": True, "pdk_root": pdk_root})
    elif handler.command == "POST":
        body = getattr(handler, "_body", {})
        new_root = body.get("pdk_root")
        if not new_root:
            _respond(handler, "missing pdk_root", 400)
            return
        os.environ["PDK_ROOT"] = os.path.expanduser(new_root)
        _respond(handler, {"ok": True, "pdk_root": os.environ["PDK_ROOT"]})
    else:
        _respond(handler, "Method Not Allowed", 405)


def h_tools_uninstall(handler: Any) -> None:
    key = _path_after("/api/tools/uninstall/", handler.path)
    if not key:
        _respond(handler, "missing tool key", 400)
        return
    try:
        result = installer.uninstall_tool(key)
        tools_mod._check_tools_cache.clear()
        _respond(handler, result)
    except Exception as ex:
        _log.exception("uninstall_tool failed")
        _respond(handler, str(ex), 500)


def h_pdk_uninstall(handler: Any) -> None:
    body = getattr(handler, "_body", {})
    pdk = body.get("pdk", "")
    if not pdk:
        _respond(handler, "missing pdk", 400)
        return
    try:
        result = installer.uninstall_pdk(pdk)
        tools_mod._check_tools_cache.clear()
        _respond(handler, result)
    except Exception as ex:
        _log.exception("uninstall_pdk failed")
        _respond(handler, str(ex), 500)


def h_pdk_fix_permissions(handler: Any) -> None:
    """Restore ownership of a root-owned ciel PDK store to the current user."""
    try:
        _respond(handler, installer.fix_ciel_permissions())
    except Exception as ex:
        _log.exception("fix_ciel_permissions failed")
        _respond(handler, str(ex), 500)


def h_container_pull(handler: Any) -> None:
    """Pre-pull the version-matched LibreLane image for container run mode."""
    try:
        _respond(handler, installer.pull_image())
    except Exception as ex:
        _log.exception("pull_image failed")
        _respond(handler, str(ex), 500)


def h_container_enable_docker(handler: Any) -> None:
    """Add the current user to the docker group (no re-login needed; uses sg)."""
    try:
        _respond(handler, installer.enable_docker_group())
    except Exception as ex:
        _log.exception("enable_docker_group failed")
        _respond(handler, str(ex), 500)


def h_metrics_catalog(handler: Any) -> None:
    """Authoritative metric definitions from LibreLane (names + flags)."""
    try:
        _respond(handler, introspect.list_metrics())
    except Exception as ex:
        _log.exception("list_metrics failed")
        _respond(handler, str(ex), 500)


def h_tools_install_ciel(handler: Any) -> None:
    body = getattr(handler, "_body", {})
    pdk = body.get("pdk", "sky130A")
    libraries = body.get("libraries")
    try:
        result = installer.install_pdk(pdk, libraries)
        _respond(handler, result)
    except Exception as ex:
        _log.exception("install_pdk failed")
        _respond(handler, str(ex), 500)


def _dir_empty_or_absent(p: Path) -> bool:
    """True when *p* doesn't exist yet or contains no entries (safe to fill)."""
    if not p.exists():
        return True
    try:
        return not any(p.iterdir())
    except Exception:
        return False


def h_copy_spm(handler: Any) -> None:
    body = getattr(handler, "_body", {})
    base_str = body.get("design_dir") or ""
    try:
        spm_src = Path(__file__).resolve().parent.parent.parent.parent / "spm"
        if not spm_src.is_dir():
            try:
                import librelane
                spm_src = Path(librelane.__file__).parent / "examples" / "spm"
            except ImportError:
                raise FileNotFoundError("SPM example not found")
            if not spm_src.is_dir():
                raise FileNotFoundError("SPM example not found in librelane")

        # The SPM example must never overwrite the user's design. SPM ships a
        # ``config.yaml`` (DESIGN_NAME: spm, VERILOG_FILES: dir::src/*.v) and a
        # ``src/spm.v``; copytree-ing those straight into a folder that already
        # holds another design silently bakes ``DESIGN_NAME=spm`` into it — after
        # which the user's own designs fail with "top-module 'spm' not found".
        # So: copy into the base only when it's already SPM or empty; otherwise
        # nest a fresh ``spm_example`` subdir so the user's files are untouched.
        base = Path(base_str).resolve() if base_str else Path.cwd()
        if base.name == "spm_example" or (base / "src" / "spm.v").is_file():
            target = base                      # already an SPM example — reuse it
        elif _dir_empty_or_absent(base):
            target = base                      # empty dir → it becomes the example
        else:
            target = base / "spm_example"      # has other content → don't pollute it
        target.mkdir(parents=True, exist_ok=True)
        shutil.copytree(str(spm_src), str(target), dirs_exist_ok=True)
        _set_active_design_dir(str(target))
        _respond(handler, {"design_dir": str(target)})
    except Exception as ex:
        _log.exception("copy_spm failed")
        _respond(handler, str(ex), 500)


# ---------------------------------------------------------------------------
# View serving
# ---------------------------------------------------------------------------

_CONTENT_TYPE_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
    ".gds": "application/octet-stream",
    ".gdsii": "application/octet-stream",
    ".def": "text/plain; charset=utf-8",
    ".lef": "text/plain; charset=utf-8",
    ".v": "text/plain; charset=utf-8",
    ".nl": "text/plain; charset=utf-8",
    ".spice": "text/plain; charset=utf-8",
    ".spef": "text/plain; charset=utf-8",
    ".sdf": "text/plain; charset=utf-8",
    ".lib": "text/plain; charset=utf-8",
    ".sdc": "text/plain; charset=utf-8",
    ".tcl": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".yaml": "text/plain; charset=utf-8",
    ".yml": "text/plain; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
}


def _read_view_file(path: Path) -> Optional[Dict[str, Any]]:
    if not path.is_file():
        return None
    ext = path.suffix.lower()
    content_type = _CONTENT_TYPE_MAP.get(ext, "application/octet-stream")
    try:
        blob = path.read_bytes()
        return {"blob": blob, "content_type": content_type}
    except Exception:
        return None


def _resolve_run_dir(tag: Optional[str]) -> Optional[Path]:
    """Run dir for *tag* under the active design (direct child of runs/ only)."""
    design_dir = _get_active_design_dir()
    if not design_dir or not tag:
        return None
    runs_root = (Path(design_dir) / "runs").resolve()
    run_dir = (runs_root / tag).resolve()
    if run_dir.is_dir() and run_dir.parent == runs_root:
        return run_dir
    return None


def serve_run_file(full_path: str) -> Optional[Dict[str, Any]]:
    """Serve ``?tag=&path=`` — any file *inside* a run dir, traversal-safe."""
    tag = _query_param(full_path, "tag")
    rel = _query_param(full_path, "path")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None or not rel:
        return None
    target = (run_dir / rel).resolve()
    if not target.is_relative_to(run_dir):
        return None
    if not target.is_file():
        return None
    return _read_view_file(target)


def h_run_files(handler: Any) -> None:
    """Recursive file listing of one run dir, for the per-run file browser."""
    tag = _query_param(handler.path, "tag")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    try:
        _respond(handler, {"tag": tag, "files": history.list_run_files(run_dir)})
    except Exception as ex:
        _log.exception("list_run_files failed")
        _respond(handler, str(ex), 500)


def h_run_images(handler: Any) -> None:
    """Every image artefact in a run (render PNGs etc.), grouped by step."""
    tag = _query_param(handler.path, "tag")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    try:
        _respond(handler, {"tag": tag, "images": history.list_run_images(run_dir)})
    except Exception as ex:
        _log.exception("list_run_images failed")
        _respond(handler, str(ex), 500)


def h_run_outputs(handler: Any) -> None:
    """Categorised output artefacts of a run (final/ deliverables) for Preview."""
    tag = _query_param(handler.path, "tag")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    try:
        _respond(handler, {"tag": tag, "outputs": history.list_run_outputs(run_dir)})
    except Exception as ex:
        _log.exception("list_run_outputs failed")
        _respond(handler, str(ex), 500)


def h_run_diagrams(handler: Any) -> None:
    """Graphviz DOT diagrams (Yosys synthesis schematics) a run produced."""
    tag = _query_param(handler.path, "tag")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    try:
        _respond(handler, {"tag": tag, "diagrams": history.list_run_diagrams(run_dir)})
    except Exception as ex:
        _log.exception("list_run_diagrams failed")
        _respond(handler, str(ex), 500)


def h_render_dot(handler: Any) -> None:
    """Render a run's .dot diagram to a cached SVG (served via /api/run-file)."""
    tag = _query_param(handler.path, "tag")
    rel = _query_param(handler.path, "path")
    force = (_query_param(handler.path, "force") or "").lower() in ("1", "true", "yes")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None or not rel:
        _respond(handler, "run not found", 404)
        return
    target = (run_dir / rel).resolve()
    if not target.is_relative_to(run_dir):
        _respond(handler, "invalid path", 400)
        return
    try:
        _respond(handler, history.render_dot(run_dir, rel, force=force))
    except Exception as ex:
        _log.exception("render_dot failed")
        _respond(handler, str(ex), 500)


def _reveal_in_file_manager(target: Path) -> Tuple[bool, str]:
    """Open the host's file manager at *target* (a localhost-only convenience).

    Cross-platform, stdlib only: macOS ``open -R`` and Windows ``explorer
    /select`` highlight the file; Linux tries the freedesktop FileManager1 D-Bus
    call (highlights in Nautilus/Dolphin/etc.) and falls back to ``xdg-open`` on
    the containing folder. Returns (ok, info-or-error). On a headless server
    (no DISPLAY / no file manager) it fails gracefully with a clear message.
    """
    import subprocess
    import sys

    t = str(target)
    parent = str(target.parent)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", t])
        elif os.name == "nt":
            subprocess.Popen(["explorer", "/select,", t])
        else:
            # WSL2: there's no Linux desktop, but Windows Explorer is reachable
            # through interop. Translate the path and select it there.
            from ..controller import platform_env
            if platform_env.is_wsl():
                win = platform_env.wsl_windows_path(t)
                if win:
                    subprocess.Popen(["explorer.exe", f"/select,{win}"])
                    return True, parent
                # fall through to xdg-open which WSL maps to the Windows opener
                subprocess.Popen(["xdg-open", parent])
                return True, parent
            if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
                return False, "no graphical session on the server host (headless)"
            try:
                subprocess.Popen([
                    "dbus-send", "--session", "--print-reply",
                    "--dest=org.freedesktop.FileManager1", "--type=method_call",
                    "/org/freedesktop/FileManager1",
                    "org.freedesktop.FileManager1.ShowItems",
                    f"array:string:file://{t}", "string:",
                ])
            except FileNotFoundError:
                subprocess.Popen(["xdg-open", parent])
        return True, parent
    except FileNotFoundError:
        return False, "no file manager available on the server host"
    except Exception as ex:  # pragma: no cover - platform dependent
        return False, str(ex)


def h_reveal(handler: Any) -> None:
    """Reveal a run file in the host file manager (traversal-guarded)."""
    body = getattr(handler, "_body", {})
    tag = body.get("tag")
    rel = body.get("path")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None or not rel:
        _respond(handler, "run not found", 404)
        return
    target = (run_dir / rel).resolve()
    if not target.is_relative_to(run_dir):
        _respond(handler, "invalid path", 400)
        return
    if not target.exists():
        _respond(handler, "file not found", 404)
        return
    ok, info = _reveal_in_file_manager(target)
    if ok:
        _respond(handler, {"ok": True, "opened": info})
    else:
        _respond(handler, info, 500)


def h_desktop_tools(handler: Any) -> None:
    """Which desktop layout viewers are installed on this host."""
    from ..controller import desktop
    _respond(handler, {"tools": desktop.available_tools()})


def h_container_tools(handler: Any) -> None:
    """Tools that can be launched *inside* the container (version-matched), plus
    whether a display is reachable and an engine is usable."""
    from ..controller import container_tools, tools as ctools
    disp = container_tools.display_available()
    engine_ready = False
    try:
        engine_ready = bool(ctools.resolve_engine().get("ready"))
    except Exception:
        pass
    _respond(handler, {
        "tools": container_tools.container_tools(),
        "display": disp,
        "engine_ready": engine_ready,
    })


def _final_odb(run_dir: "Path") -> Optional["Path"]:
    """The run's final OpenDB database (.odb), for OpenROAD GUI."""
    final = run_dir / "final"
    for sub in ("odb", "def"):
        d = final / sub
        if d.is_dir():
            hits = sorted(d.glob("*.odb"))
            if hits:
                return hits[0]
    hits = sorted(run_dir.rglob("*.odb"))
    return hits[-1] if hits else None


def h_open_in_tool(handler: Any) -> None:
    """Launch an EDA tool on a run file, on the HOST or inside the CONTAINER.

    ``location:"host"`` (default) uses the user's native KLayout/Magic/GDS3D via
    ``desktop.py``. ``location:"container"`` runs the tool inside the
    version-matched LibreLane image (KLayout/Magic/OpenROAD/Netgen) with X11
    forwarding — this is the fix for a host Magic too old for the PDK techfile.
    Defaults to the run's final GDS when no ``path`` is given. Traversal-guarded;
    only meaningful when the GUI runs on the user's own machine."""
    body = getattr(handler, "_body", {})
    tool = body.get("tool") or ""
    tag = body.get("tag")
    rel = body.get("path")
    location = body.get("location") or "host"
    run_dir = _resolve_run_dir(tag) if tag else _latest_run_dir()
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    target = None
    if rel:
        target = (run_dir / rel).resolve()
        if not target.is_relative_to(run_dir):
            _respond(handler, "invalid path", 400)
            return
    pdk, pdk_root = _run_pdk(run_dir)

    if location == "container":
        from ..controller import container_tools
        design_dir = _get_active_design_dir()
        gds = target if (target and target.suffix.lower() in (".gds", ".gz")) else _final_gds(run_dir)
        odb = _final_odb(run_dir) if tool == "openroad" else None
        if tool in ("magic", "klayout") and gds is None:
            _respond(handler, {"ok": False, "error": "this run has no final GDS to open"}, 200)
            return
        _respond(handler, container_tools.open_in_container_tool(
            tool, design_dir=design_dir or str(run_dir.parent.parent),
            work_dir=str(run_dir), gds=gds, odb=odb, pdk=pdk, pdk_root=pdk_root), 200)
        return

    # Host launch (desktop.py).
    from ..controller import desktop
    if target is None:
        gds = _final_gds(run_dir)
        if gds is None:
            _respond(handler, {"ok": False, "error": "this run has no final GDS to open"}, 200)
            return
        target = gds
    use_tech = body.get("use_tech", True) is not False
    _respond(handler, desktop.open_in_tool(tool, target, pdk=pdk, pdk_root=pdk_root, use_tech=use_tech), 200)


def _run_pdk(run_dir: "Path") -> Tuple[Optional[str], Optional[str]]:
    """Best-effort (PDK, PDK_ROOT) from a run's resolved/config JSON."""
    for name in ("resolved.json", "config.json"):
        f = run_dir / name
        if not f.is_file():
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            pdk = d.get("PDK")
            if pdk:
                return pdk, d.get("PDK_ROOT")
        except Exception:
            continue
    return None, None


def h_run_note(handler: Any) -> None:
    """Get (GET) or set (POST {tag, note}) a run's free-text note."""
    if getattr(handler, "command", "GET") == "POST":
        body = getattr(handler, "_body", {})
        tag = body.get("tag")
        run_dir = _resolve_run_dir(tag)
        if run_dir is None:
            _respond(handler, "run not found", 404)
            return
        _respond(handler, history.write_note(run_dir, body.get("note", "")))
        return
    tag = _query_param(handler.path, "tag")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    _respond(handler, {"tag": run_dir.name, "note": history.read_note(run_dir)})


def h_watch(handler: Any) -> None:
    """Get (GET ?design=) or set (POST {design, rules}) a design's metric
    watch-list (E4.2). The design path is the active design's own dir."""
    if getattr(handler, "command", "GET") == "POST":
        body = getattr(handler, "_body", {})
        design_dir = body.get("design") or _get_active_design_dir()
        if not design_dir or not Path(design_dir).is_dir():
            _respond(handler, "no such design", 404)
            return
        _respond(handler, history.write_watch(design_dir, body.get("rules") or []))
        return
    design_dir = _query_param(handler.path, "design") or _get_active_design_dir()
    if not design_dir or not Path(design_dir).is_dir():
        _respond(handler, {"rules": []})
        return
    _respond(handler, {"rules": history.read_watch(design_dir)})


def h_run_pin(handler: Any) -> None:
    """Pin/unpin a run (E4.5). POST {tag, pinned}."""
    body = getattr(handler, "_body", {})
    run_dir = _resolve_run_dir(body.get("tag"))
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    _respond(handler, history.set_pin(run_dir, bool(body.get("pinned"))))


def h_run_gui_meta(handler: Any) -> None:
    """Return the persisted ``gui-run.json`` for a run so Setup can reproduce it
    (E2). 404 (with a clear message) for runs made before reproduce support or
    outside the GUI — the caller degrades gracefully."""
    tag = _query_param(handler.path, "tag")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    meta_path = run_dir / "gui-run.json"
    if not meta_path.is_file():
        _respond(
            handler,
            "this run predates reproduce support or was made outside the GUI",
            404,
        )
        return
    try:
        _respond(handler, json.loads(meta_path.read_text(encoding="utf-8")))
    except Exception as ex:
        _log.exception("reading gui-run.json failed")
        _respond(handler, str(ex), 500)


def h_run_import_dir(handler: Any) -> None:
    """Adopt an existing LibreLane run directory into the active design's history
    (E1, mode 1). POST {path}. The path is intentionally external — same trust
    class as the folder picker — but the copy target is confined to the design."""
    body = getattr(handler, "_body", {})
    src = (body.get("path") or "").strip()
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design — set a design directory first", 400)
        return
    if not src:
        _respond(handler, "no run directory given", 400)
        return
    try:
        res = history.adopt_run(src, design_dir)
        _respond(handler, res)
    except FileNotFoundError as ex:
        _respond(handler, str(ex), 404)
    except ValueError as ex:
        _respond(handler, str(ex), 400)
    except Exception as ex:
        _log.exception("adopt_run failed")
        _respond(handler, str(ex), 500)


def h_run_import_bundle(handler: Any) -> None:
    """Import a LanEx export bundle (.zip) as a viewable partial run (E1, mode 2).
    POST {path} (server-side zip path — heavy bundles exceed the upload cap) or
    {data: <base64 zip>} for small bundles."""
    import base64
    import io

    from ..controller import bundle
    body = getattr(handler, "_body", {})
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design — set a design directory first", 400)
        return
    src_path = (body.get("path") or "").strip()
    data_b64 = body.get("data")
    try:
        if src_path:
            res = bundle.import_bundle(src_path, design_dir)
        elif data_b64:
            raw = base64.b64decode(data_b64)
            res = bundle.import_bundle(io.BytesIO(raw), design_dir)
        else:
            _respond(handler, "no bundle path or data given", 400)
            return
        _respond(handler, res)
    except FileNotFoundError as ex:
        _respond(handler, str(ex), 404)
    except ValueError as ex:
        _respond(handler, str(ex), 400)
    except Exception as ex:
        _log.exception("import_bundle failed")
        _respond(handler, str(ex), 500)


def h_run_bundle(handler: Any) -> None:
    """Stream a reproducibility/support .zip for a run (binary download).

    ``?tag=&include=config,sources,metrics_csv,settings_csv,analytics_csv,reports,logs``
    selects exactly what goes in (the download checklist). ``?mode=minimal|support``
    is the legacy fallback when no ``include`` is given.
    """
    import tempfile

    from ..controller import bundle
    tag = _query_param(handler.path, "tag")
    inc_raw = _query_param(handler.path, "include")
    mode = _query_param(handler.path, "mode")
    include = [p for p in inc_raw.split(",") if p] if inc_raw else None
    run_dir = _resolve_run_dir(tag)
    if run_dir is None:
        handler._send_json({"ok": False, "error": "run not found"}, 404)
        return
    # Spool the zip to a temp file (spills to disk past 32 MiB) so a heavy bundle
    # of GDS/netlists/images never has to materialise on the heap, then stream it
    # back in chunks. Cross-platform (tempfile); auto-deleted on close.
    try:
        spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024, suffix=".zip")
    except Exception as ex:
        _log.exception("bundle tempfile failed")
        handler._send_json({"ok": False, "error": str(ex)}, 500)
        return
    try:
        with spool:
            try:
                bundle.write_bundle(spool, run_dir, include=include, mode=mode)
            except Exception as ex:
                _log.exception("write_bundle failed")
                handler._send_json({"ok": False, "error": str(ex)}, 500)
                return
            total = spool.tell()
            spool.seek(0)
            name = f"{run_dir.name}-bundle.zip"
            handler.send_response(200)
            handler.send_header("Content-Type", "application/zip")
            handler.send_header("Content-Length", str(total))
            handler.send_header("Content-Disposition", f'attachment; filename="{name}"')
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            while True:
                chunk = spool.read(1024 * 1024)
                if not chunk:
                    break
                handler.wfile.write(chunk)
    except (BrokenPipeError, ConnectionError):
        pass  # client cancelled the download — benign


def h_trends(handler: Any) -> None:
    """Per-metric trend series across the active design's runs (for line charts)."""
    design_dir = _query_param(handler.path, "design_dir") or _get_active_design_dir()
    if not design_dir:
        _respond(handler, {"ok": True, "runs": [], "series": {}, "keys": []})
        return
    keys_q = _query_param(handler.path, "keys")
    keys = [k for k in keys_q.split(",") if k] if keys_q else None
    try:
        _respond(handler, history.metric_trends(design_dir, keys))
    except Exception as ex:
        _log.exception("metric_trends failed")
        _respond(handler, str(ex), 500)


def h_run_delete(handler: Any) -> None:
    """Delete one run dir (irreversible). Refuses the in-progress run."""
    body = getattr(handler, "_body", {})
    tag = body.get("tag")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    try:
        from ..server.app import get_runner

        live = getattr(get_runner(), "_run_dir", None)
        if live and Path(live).resolve() == run_dir:
            _respond(handler, "that run is still in progress — stop it first", 409)
            return
    except Exception:
        pass
    try:
        import shutil

        shutil.rmtree(run_dir)
        _respond(handler, {"ok": True, "deleted": tag})
    except Exception as ex:
        _log.exception("delete_run failed")
        _respond(handler, str(ex), 500)


def serve_view(spec: str) -> Optional[Dict[str, Any]]:
    if "/" in spec:
        tag, fmt = spec.split("/", 1)
    else:
        tag, fmt = "", spec

    design_dir = _get_active_design_dir()
    if not design_dir:
        return None

    runs_root = Path(design_dir) / "runs"

    if tag:
        run_dir = runs_root / tag
    else:
        if not runs_root.is_dir():
            return None
        dirs = sorted(
            (d for d in runs_root.iterdir() if d.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        run_dir = dirs[0] if dirs else None
        if run_dir is None:
            return None

    state_file = run_dir / "state_out.json"
    if state_file.is_file():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            target = state.get(fmt)
            if target:
                def _safe_serve(p: Path) -> Optional[Dict[str, Any]]:
                    try:
                        resolved = p.resolve()
                        if resolved.is_relative_to(Path(design_dir).resolve()):
                            if resolved.is_file():
                                return _read_view_file(resolved)
                    except Exception:
                        pass
                    return None

                r = _safe_serve(Path(target))
                if r: return r
                r = _safe_serve(run_dir / target)
                if r: return r
                r = _safe_serve(Path(design_dir) / target)
                if r: return r
        except Exception:
            pass

    final_dir = run_dir / "final" / fmt
    if final_dir.is_dir():
        files = sorted(final_dir.iterdir())
        for f in files:
            r = _read_view_file(f)
            if r:
                return r

    for step_dir in run_dir.iterdir():
        if not step_dir.is_dir() or "-" not in step_dir.name:
            continue
        for f in sorted(step_dir.iterdir()):
            if f.is_file() and f.suffix.lstrip(".").lower() == fmt:
                r = _read_view_file(f)
                if r:
                    return r

    return None


# ---------------------------------------------------------------------------
# Phase 0 — project wizard + run export
# ---------------------------------------------------------------------------

def h_templates(handler: Any) -> None:
    """List bundled new-project templates."""
    try:
        _respond(handler, scaffold.list_templates())
    except Exception as ex:
        _log.exception("list_templates failed")
        _respond(handler, str(ex), 500)


def h_project_new(handler: Any) -> None:
    """Scaffold a new design from a template, then make it the active design."""
    body = getattr(handler, "_body", {})
    dest = body.get("dest_dir") or ""
    template = body.get("template") or ""
    top = (body.get("top") or "").strip()
    pdk = (body.get("pdk") or "").strip()
    scl = (body.get("scl") or "").strip() or None
    clock_period = body.get("clock_period")
    if not dest or not template:
        _respond(handler, "missing dest_dir or template", 400)
        return
    try:
        cp = float(clock_period) if clock_period not in (None, "") else None
    except (TypeError, ValueError):
        cp = None
    try:
        result = scaffold.create_project(dest, template, top=top or template, pdk=pdk, scl=scl, clock_period=cp)
    except Exception as ex:
        _log.exception("create_project failed")
        _respond(handler, str(ex), 500)
        return
    if not result.get("ok"):
        _respond(handler, result.get("error") or "could not create project", 400)
        return
    # Adopt the freshly-created design (mirrors h_set_design_dir).
    _set_active_design_dir(result["design_dir"])
    _respond(handler, result)


def h_run_export(handler: Any) -> None:
    """Export a run as csv/md/html (Phase 0.4). Streams the artifact body."""
    tag = _query_param(handler.path, "tag")
    fmt = _query_param(handler.path, "fmt", "csv")
    run_dir = _resolve_run_dir(tag)
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    try:
        result = history.export_run(run_dir, fmt)
    except Exception as ex:
        _log.exception("export_run failed")
        _respond(handler, str(ex), 500)
        return
    if not result.get("ok"):
        _respond(handler, result.get("error") or "export failed", 400)
        return
    # Send as a downloadable text artifact (not the JSON envelope).
    handler._send_text(result["text"], 200, result["content_type"])


# ---------------------------------------------------------------------------
# Phase 1 — Verification Center + compare + cell usage
# ---------------------------------------------------------------------------

def _latest_run_dir() -> Optional[Path]:
    design_dir = _get_active_design_dir()
    if not design_dir:
        return None
    runs_dir = Path(design_dir) / "runs"
    try:
        subs = [d for d in runs_dir.iterdir() if d.is_dir()]
        return max(subs, key=lambda d: d.stat().st_mtime) if subs else None
    except Exception:
        return None


def h_verify(handler: Any) -> None:
    """Stage-organized signoff verdict for a run (default: latest)."""
    from ..controller import verify as verify_mod
    tag = _query_param(handler.path, "tag")
    run_dir = _resolve_run_dir(tag) if tag else _latest_run_dir()
    if run_dir is None:
        _respond(handler, "no run to verify", 404)
        return
    try:
        _respond(handler, verify_mod.verify_report(run_dir))
    except Exception as ex:
        _log.exception("verify_report failed")
        _respond(handler, str(ex), 500)


def h_compare(handler: Any) -> None:
    """Compare N runs by config + metrics (POST {tags:[...]} or {run_dirs:[...]})."""
    body = getattr(handler, "_body", {})
    tags = body.get("tags") or []
    run_dirs: List[str] = []
    seen: set = set()

    def _add(p: Path) -> None:
        s = str(p)
        if s not in seen:
            seen.add(s)
            run_dirs.append(s)

    for t in tags:
        rd = _resolve_run_dir(t)
        if rd is not None:
            _add(rd)
    # Accept explicit run_dirs that are a direct child of ANY `runs/` directory
    # (cross-design compare: the per-tab pickers can surface runs from other
    # designs the user opened). The path is still confined — it must be a real
    # run dir (named under a `runs/` parent) — not an arbitrary file reader.
    for rd in body.get("run_dirs") or []:
        try:
            p = Path(rd).resolve()
            if p.is_dir() and p.parent.name == "runs":
                _add(p)
        except Exception:
            continue
    if len(run_dirs) < 1:
        _respond(handler, "no valid runs to compare — pick at least two completed runs", 400)
        return
    try:
        _respond(handler, history.compare_runs(run_dirs))
    except Exception as ex:
        _log.exception("compare_runs failed")
        _respond(handler, str(ex), 500)


def h_timing_paths(handler: Any) -> None:
    """Structured STA timing paths (worst-paths table + slack histogram).

    ``?tag=&kind=setup|hold&limit=`` — parses the run's existing OpenSTA
    ``report_checks`` output (no extra tool run). Defaults to the latest run.
    """
    from ..controller import timing
    tag = _query_param(handler.path, "tag")
    kind = _query_param(handler.path, "kind") or "setup"
    try:
        limit = int(_query_param(handler.path, "limit") or "100")
    except Exception:
        limit = 100
    run_dir = _resolve_run_dir(tag) if tag else _latest_run_dir()
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    try:
        _respond(handler, timing.timing_paths(run_dir, kind=kind, limit=limit))
    except Exception as ex:
        _log.exception("timing_paths failed")
        _respond(handler, str(ex), 500)


def h_cell_usage(handler: Any) -> None:
    """Per-cell-type usage table for a run."""
    tag = _query_param(handler.path, "tag")
    run_dir = _resolve_run_dir(tag) if tag else _latest_run_dir()
    if run_dir is None:
        _respond(handler, "run not found", 404)
        return
    try:
        _respond(handler, {"tag": run_dir.name, "cells": history.cell_usage(run_dir)})
    except Exception as ex:
        _log.exception("cell_usage failed")
        _respond(handler, str(ex), 500)


# ---------------------------------------------------------------------------
# Phase 2 — targeted re-verify + DSE
# ---------------------------------------------------------------------------

def _config_file_for(design_dir: str) -> Optional[Path]:
    for ext in ("json", "yaml", "tcl"):
        cf = Path(design_dir) / f"config.{ext}"
        if cf.is_file():
            return cf
    return None


def _flow_factory(name: str) -> Any:
    from librelane.flows import Flow
    f = Flow.factory.get(name)
    if f is None:
        regs = list(getattr(Flow.factory, "_FlowFactory__registry", {}).values()) or \
               list(getattr(Flow.factory, "_registry", {}).values())
        f = regs[0] if regs else None
    return f


def _pdk_for_run(design_dir: str, run_tag: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Recover (pdk, scl) from an existing run's config (for a re-run)."""
    if run_tag:
        cfg = history._read_config(Path(design_dir) / "runs" / run_tag)
        pdk = cfg.get("PDK") if isinstance(cfg.get("PDK"), str) else None
        scl = cfg.get("STD_CELL_LIBRARY") if isinstance(cfg.get("STD_CELL_LIBRARY"), str) else None
        if pdk:
            return pdk, scl
    return None, None


def h_verify_rerun(handler: Any) -> None:
    """Re-run a single signoff step against an existing run (Phase 2.A)."""
    from ..controller import reverify
    from ..server.app import get_runner
    body = getattr(handler, "_body", {})
    step_id = (body.get("step_id") or "").strip()
    overrides = dict(body.get("overrides") or {})
    run_tag = body.get("run_tag") or body.get("tag")
    run_mode = "container" if body.get("run_mode") == "container" else "local"
    if not step_id:
        _respond(handler, "missing step_id", 400)
        return
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    v = reverify.validate(step_id, overrides)
    if not v.get("ok"):
        _respond(handler, v.get("error"), 400)
        return
    run_dir = _resolve_run_dir(run_tag) if run_tag else _latest_run_dir()
    if run_dir is None:
        _respond(handler, "no run to re-verify", 404)
        return
    config_file = _config_file_for(design_dir)
    if config_file is None:
        _respond(handler, "no config file in design dir", 400)
        return
    r = get_runner()
    if r.running:
        _respond(handler, "already running", 400)
        return
    pdk, scl = _pdk_for_run(design_dir, run_dir.name)
    pdk_root = os.environ.get("PDK_ROOT") or None
    if pdk:
        try:
            pf = pdk_mod.check_pdk_ready(pdk, scl, run_mode)
            pdk_root = pf.get("pdk_root") or pdk_root
        except Exception:
            pass
    kwargs = reverify.reverify_kwargs(run_dir, step_id, overrides=overrides)
    extra_config_files = []
    try:
        from ..controller import custommacros
        overlay = custommacros.write_overlay(design_dir)
        if overlay:
            extra_config_files.append(overlay)
    except Exception:
        _log.exception("custom-macro overlay failed (continuing without it)")
    try:
        result = r.start(
            flow_factory=_flow_factory(body.get("flow") or "Classic"),
            config_files=[str(config_file)],
            design_dir=design_dir,
            pdk=pdk, scl=scl, pdk_root=pdk_root,
            run_mode=run_mode, flow_name=body.get("flow") or "Classic",
            extra_config_files=extra_config_files or None,
            **kwargs,
        )
        result["run_tag"] = run_dir.name
        _respond(handler, result)
    except Exception as ex:
        _log.exception("verify rerun failed")
        _respond(handler, str(ex), 500)


def _dse_run_one_blocking(design_dir: str, config_file: Path, flow_name: str,
                          run_mode: str, base_overrides: Dict[str, Any],
                          dse_body: Optional[Dict[str, Any]] = None):
    """Return a ``start_one(tag, overrides)`` closure for the DSE queue that
    starts a run through the shared runner and blocks until it finishes.

    Each sweep point is assembled through the SAME ``_assemble_overrides`` helper
    as a Setup run (override cleaning, custom cells, macro overlay, picker
    sources/extras), so a swept run is identical to the same run launched from
    Setup instead of silently dropping that context (audit A2)."""
    import time
    from ..server.app import get_runner

    def start_one(tag: str, overrides: Dict[str, Any]) -> bool:
        r = get_runner()
        # Wait for any prior run to clear (defensive; queue is sequential).
        for _ in range(600):
            if not r.running:
                break
            time.sleep(0.5)
        # Fold the swept point onto the sweep's base overrides, THEN run it all
        # through the shared assembler so cleaning + custom cells + macro overlay
        # + picker sources apply exactly as they do for a Setup run.
        synthetic = dict(dse_body or {})
        synthetic["overrides"] = {**base_overrides, **overrides}
        asm = _assemble_overrides(design_dir, synthetic)
        pdk, scl = asm["pdk"], asm["scl"]
        # Resolve the pdk_root that actually holds this PDK for the run mode
        # (ciel homes, not just $PDK_ROOT) — otherwise a sky130 sweep on a box
        # whose $PDK_ROOT points elsewhere fails every config with "PDK not
        # found", exactly like the lint/run-start paths used to.
        pdk_root = os.environ.get("PDK_ROOT") or None
        if pdk:
            try:
                pf = pdk_mod.check_pdk_ready(pdk, scl, run_mode)
                pdk_root = pf.get("pdk_root") or pdk_root
            except Exception:
                pass
        res = r.start(
            flow_factory=_flow_factory(flow_name),
            config_files=[str(config_file)],
            design_dir=design_dir,
            pdk=pdk, scl=scl, pdk_root=pdk_root,
            tag=tag, overwrite=True,
            config_overrides=asm["overrides"],
            extra_sources=asm["extra_sources"],
            extra_extras=asm["extra_extras"],
            extra_config_files=asm["extra_config_files"],
            run_mode=run_mode, flow_name=flow_name,
        )
        if not res.get("ok"):
            return False
        # Block until this run completes.
        time.sleep(0.5)
        for _ in range(86400 * 2):  # generous upper bound; ~12h at 0.5s
            if not r.running:
                break
            time.sleep(0.5)
        # r.error is the real per-run failure signal (the old getattr(r,"error")
        # always read None because there was no such attribute → every run was
        # marked "done"). The `error` property now returns the last run's error.
        return not bool(r.error)

    return start_one


def h_dse_start(handler: Any) -> None:
    """Launch a DSE sweep: N runs of the active design under different configs."""
    from ..controller import dse
    body = getattr(handler, "_body", {})
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    ws_err = _whitespace_path_error(design_dir)
    if ws_err:
        _respond(handler, ws_err, 400)
        return
    config_file = _config_file_for(design_dir)
    if config_file is None:
        _respond(handler, "no config file in design dir", 400)
        return
    spec = {"axes": body.get("axes") or [], "mode": body.get("mode") or "grid"}
    try:
        overrides_list = dse.expand_sweep(spec)
    except ValueError as ex:
        _respond(handler, str(ex), 400)
        return
    base_overrides = dict(body.get("base_overrides") or {})
    run_mode = "container" if body.get("run_mode") == "container" else "local"
    flow_name = body.get("flow_name") or "Classic"
    base_tag = body.get("base_tag") or Path(design_dir).name
    # Don't clobber a prior sweep: bump the base until the target run dirs are
    # free (unless the caller explicitly opts into replacing them).
    if not body.get("replace"):
        base_tag = dse.unique_base_tag(design_dir, base_tag, len(overrides_list))
    tags = dse.dse_run_tags(base_tag, len(overrides_list))
    start_one = _dse_run_one_blocking(design_dir, config_file, flow_name, run_mode, base_overrides, body)
    result = dse.job.start(start_one=start_one, overrides_list=overrides_list, tags=tags)
    if not result.get("ok"):
        _respond(handler, result.get("error") or "could not start DSE", 400)
        return
    # Persist a manifest so the sweep is recoverable after a restart and the DSE
    # tab can list past sweeps without parsing run-tag regexes.
    sweep_id = dse.new_sweep_id()
    dse.record_sweep(design_dir, {
        "id": sweep_id,
        "base": base_tag,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "axes": spec["axes"],
        "mode": spec["mode"],
        "run_mode": run_mode,
        "flow": flow_name,
        "base_overrides": base_overrides,
        "tags": tags,
        "count": len(tags),
    })
    result = dict(result)
    result["sweep_id"] = sweep_id
    result["base_tag"] = base_tag
    _respond(handler, result)


def h_dse_sweeps(handler: Any) -> None:
    """List recorded DSE sweep manifests for the active design (newest first)."""
    from ..controller import dse
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, {"sweeps": []})
        return
    _respond(handler, {"sweeps": dse.load_sweeps(design_dir)})


def h_dse_cancel(handler: Any) -> None:
    from ..controller import dse
    from ..server.app import get_runner
    dse.job.cancel()
    try:
        get_runner().cancel()
    except Exception:
        pass
    _respond(handler, {"ok": True})


def h_dse_status(handler: Any) -> None:
    from ..controller import dse
    _respond(handler, dse.job.status())


def h_system_resources(handler: Any) -> None:
    """Host RAM/CPU snapshot so the GUI can warn before a memory-heavy DSE sweep
    (each config is a full RTL→GDS run). Read-only; psutil is a LibreLane dep."""
    from ..controller import dse
    _respond(handler, dse.system_resources())


# ---------------------------------------------------------------------------
# Phase 3 — editor + lint + simulation
# ---------------------------------------------------------------------------

def h_file_write(handler: Any) -> None:
    """Guarded write of a source/config file inside the active design dir."""
    from ..controller import editor
    body = getattr(handler, "_body", {})
    rel = body.get("rel_path") or ""
    content = body.get("content")
    if content is None:
        _respond(handler, "missing content", 400)
        return
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    result = editor.write_text(design_dir, rel, content)
    if not result.get("ok"):
        _respond(handler, result.get("error"), 400)
        return
    _respond(handler, result)


def h_file_delete(handler: Any) -> None:
    """Guarded delete of a single source/testbench file inside the design dir."""
    from ..controller import editor
    body = getattr(handler, "_body", {})
    rel = body.get("rel_path") or ""
    if not rel:
        _respond(handler, "missing rel_path", 400)
        return
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    result = editor.delete_file(design_dir, rel)
    if not result.get("ok"):
        _respond(handler, result.get("error"), 400)
        return
    _respond(handler, result)


def h_lint(handler: Any) -> None:
    """Lint the active design with a standalone ``verilator --lint-only`` job.

    This is intentionally NOT the hardening flow: it writes no ``runs/`` dir,
    needs no PDK, and emits dedicated ``lint_started``/``lint_done`` events, so
    "Check syntax" never masquerades as an RTL→GDS run (and works for any PDK).
    """
    from ..controller import lint
    body = getattr(handler, "_body", {})
    run_mode = "container" if body.get("run_mode") == "container" else "local"
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    if lint.job.running:
        _respond(handler, "a lint is already running", 400)
        return

    # Source list: prefer what the IDE sends; otherwise discover the design's
    # Verilog (excluding testbenches, which the user lints separately).
    sources = [s for s in (body.get("sources") or []) if s]
    if not sources:
        try:
            walked = fsbrowser.walk_sources(design_dir)
            sources = [s["relpath"] for s in (walked.get("sources") or [])
                       if str(s.get("relpath", "")).lower().endswith((".v", ".sv"))]
        except Exception:
            sources = []
    if not sources:
        _respond(handler, "no Verilog sources found to lint", 400)
        return

    # Engine: host verilator if present (what the flow uses too), else the
    # LibreLane container image. iverilog/PDK are irrelevant to linting.
    # usable_which (not shutil.which) so a Windows verilator on the WSL /mnt/c
    # PATH is ignored — only a real Linux build counts as "host verilator".
    has_host = bool(platform_env.usable_which("verilator"))
    engine_name = None
    env: Dict[str, str] = {}
    if run_mode == "container" or not has_host:
        eng = tools_mod.resolve_engine()
        if has_host and not eng.get("ready"):
            run_mode = "local"
        elif eng.get("ready"):
            run_mode, engine_name, env = "container", eng["engine"], (eng.get("env") or {})
        elif not has_host:
            _respond(handler, "Verilator isn't installed and no container engine is available. "
                              "Install Verilator from the Tools tab (or Docker/Podman).", 400)
            return
        else:
            run_mode = "local"

    argv = lint.build_lint_command(
        design_dir, sources=sources, top=(body.get("top") or "").strip() or None,
        include_dirs=body.get("include_dirs") or [], defines=body.get("defines") or {},
        run_mode=run_mode, engine=engine_name or "docker",
    )
    if run_mode == "container" and engine_name and tools_mod.resolve_engine().get("sg_wrap"):
        argv = tools_mod.sg_wrap_argv(argv)
    try:
        result = lint.job.start(argv, design_dir=design_dir, env=env)
        if not result.get("ok"):
            _respond(handler, result.get("error"), 400)
            return
        result["engine"] = "container" if run_mode == "container" else "verilator"
        _respond(handler, result)
    except Exception as ex:
        _log.exception("lint start failed")
        _respond(handler, str(ex), 500)


def h_lint_result(handler: Any) -> None:
    """Return the most recent standalone lint's parsed diagnostics."""
    from ..controller import lint
    _respond(handler, lint.job.last_result)


def h_sim_testbenches(handler: Any) -> None:
    from ..controller import simulate
    design_dir = _query_param(handler.path, "design_dir") or _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    _respond(handler, {"testbenches": simulate.find_testbenches(design_dir)})


def h_sim_start(handler: Any) -> None:
    """Build + launch a Verilator simulation of a testbench (Phase 3.5)."""
    from ..controller import simulate
    body = getattr(handler, "_body", {})
    design_dir = _get_active_design_dir()
    if not design_dir:
        _respond(handler, "no active design dir", 400)
        return
    if simulate.job.running:
        _respond(handler, "a simulation is already running", 400)
        return
    top = (body.get("top") or "").strip()
    testbench = (body.get("testbench") or "").strip()
    sources = body.get("sources") or []
    if not testbench:
        _respond(handler, "missing testbench", 400)
        return
    # Auto-derive the elaboration top from the testbench when the user didn't
    # give one — typing the DUT name instead of the bench module is the usual
    # cause of "ran but no VCD" (the bench's $dumpvars never executes).
    if not top:
        top = simulate.top_module_of(design_dir, testbench) or ""
    if not top:
        _respond(handler, "could not determine the testbench top module — open the "
                          "testbench and ensure it declares `module <name>;`", 400)
        return
    trace = "fst" if body.get("trace") == "fst" else "vcd"
    # The RTL-IDE simulator is an INDEPENDENT tool — it is NOT the hardening flow,
    # so it does not follow the flow's container/local engine toggle. We pick the
    # best place to run each engine on its own:
    #   • iverilog : event-driven, 4-state, great for classic testbenches. Runs on
    #                the HOST (it isn't in the LibreLane image). Works regardless
    #                of the flow's run mode, as long as iverilog is installed.
    #   • verilator: host verilator if present, else the LibreLane container image.
    #   • auto     : iverilog → host verilator → container verilator.
    req_engine = (body.get("sim_engine") or "auto").lower()
    # usable_which skips Windows binaries on the WSL /mnt/c PATH so we never pick
    # a Windows iverilog/verilator the Linux flow can't run.
    has_iverilog = bool(platform_env.usable_which("iverilog") and platform_env.usable_which("vvp"))
    has_verilator = bool(platform_env.usable_which("verilator"))
    eng_info = tools_mod.resolve_engine()
    has_container = bool(eng_info.get("ready"))

    if req_engine == "iverilog":
        if not has_iverilog:
            _respond(handler, "Icarus Verilog (iverilog/vvp) isn't installed on this machine. "
                              "Install it from the Tools tab, then retry.", 400)
            return
        sim_engine, run_mode = "iverilog", "local"
    elif req_engine == "verilator":
        if has_verilator:
            sim_engine, run_mode = "verilator", "local"
        elif has_container:
            sim_engine, run_mode = "verilator", "container"
        else:
            _respond(handler, "Verilator isn't on this machine and no container engine is "
                              "available. Install Verilator/Docker, or pick Icarus.", 400)
            return
    else:  # auto
        if has_iverilog:
            sim_engine, run_mode = "iverilog", "local"
        elif has_verilator:
            sim_engine, run_mode = "verilator", "local"
        elif has_container:
            sim_engine, run_mode = "verilator", "container"
        else:
            _respond(handler, "No simulator found. Install Icarus Verilog or Verilator from the "
                              "Tools tab (or Docker/Podman for container Verilator).", 400)
            return

    # Local sim builds + runs via `bash -lc` — fine on Linux/macOS/WSL2, but not
    # native Windows. Fail with guidance instead of a cryptic FileNotFoundError.
    if run_mode == "local" and not platform_env.usable_which("bash"):
        _respond(handler, "Local simulation needs a POSIX shell (bash), which isn't available here. "
                          "Use WSL2, or switch the engine to Container mode.", 400)
        return

    engine = None
    env: Dict[str, str] = {}
    container_name = None
    if run_mode == "container":
        engine = eng_info["engine"]
        env = eng_info.get("env") or {}
        import uuid as _uuid
        container_name = "ll-sim-" + _uuid.uuid4().hex[:12]
    argv = simulate.build_sim_command(
        design_dir, top=top, sources=sources, testbench=testbench,
        defines=body.get("defines") or {}, include_dirs=body.get("include_dirs") or [],
        trace=trace, run_mode=run_mode, engine=engine or "docker", container_name=container_name,
        sim_engine=sim_engine,
    )
    # iverilog always emits VCD; Verilator honours the requested trace format.
    vcd_name = "dump.fst" if (trace == "fst" and sim_engine == "verilator") else "dump.vcd"
    result = simulate.job.start(argv, design_dir=design_dir, run_mode=run_mode, env=env,
                                vcd_name=vcd_name, container_name=container_name, engine=engine)
    if not result.get("ok"):
        _respond(handler, result.get("error"), 400)
        return
    result["sim_engine"] = sim_engine
    result["top"] = top
    _respond(handler, result)


def h_sim_cancel(handler: Any) -> None:
    from ..controller import simulate
    simulate.job.cancel()
    _respond(handler, {"ok": True})


def h_waveform(handler: Any) -> None:
    """Stream a VCD/FST from inside the active design dir (traversal-guarded)."""
    rel = _query_param(handler.path, "path")
    design_dir = _get_active_design_dir()
    if not design_dir or not rel:
        _respond(handler, "missing design dir or path", 400)
        return
    base = Path(design_dir).resolve()
    target = (base / rel).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        _respond(handler, "not found", 404)
        return
    try:
        handler._send_bytes(target.read_bytes(), 200, "application/octet-stream")
    except Exception as ex:
        _respond(handler, str(ex), 500)


# ---------------------------------------------------------------------------
# Phase 4 — 2D/3D viewers + cells + plugins
# ---------------------------------------------------------------------------

def _final_gds(run_dir: Path) -> Optional[Path]:
    final = run_dir / "final"
    for sub in ("gds", "klayout_gds", "mag_gds"):
        d = final / sub
        if d.is_dir():
            gds = sorted(d.glob("*.gds")) + sorted(d.glob("*.gds.gz"))
            if gds:
                return gds[0]
    return None


# NOTE: the in-browser klayout 2D/3D render endpoints were removed. They relied
# on passing data to a klayout ``-r`` script via argv, which klayout consumes
# itself (IndexError in the script), so they never worked. The Layout tab now
# uses the flow's already-rendered KLayout PNG plus "Open in desktop tool"
# (KLayout/Magic/GDS3D via controller/desktop.py) — see viewer2d.js/viewer3d.js.


def _custom_cells_dir(handler: Any) -> Optional[str]:
    """Design dir for custom-cell endpoints (body/query override → active)."""
    body = getattr(handler, "_body", {}) or {}
    return body.get("design_dir") or _query_param(handler.path, "design_dir") or _get_active_design_dir()


def h_custom_cells(handler: Any) -> None:
    """List the active design's custom standard cells."""
    from ..controller import customcells
    dd = _custom_cells_dir(handler)
    if not dd:
        _respond(handler, "no active design dir", 400)
        return
    _respond(handler, customcells.list_cells(dd))


def h_custom_cell_save(handler: Any) -> None:
    """Save/replace a custom cell (uploaded views + swap-out list) for a run."""
    from ..controller import customcells
    body = getattr(handler, "_body", {})
    dd = _custom_cells_dir(handler)
    if not dd:
        _respond(handler, "no active design dir", 400)
        return
    result = customcells.save_cell(
        dd, body.get("name", ""),
        swap_out=body.get("swap_out") or [],
        views=body.get("views") or {},
        enabled=body.get("enabled", True),
    )
    if not result.get("ok"):
        _respond(handler, result.get("error", "save failed"), 400)
        return
    _respond(handler, result)


def h_custom_cell_remove(handler: Any) -> None:
    from ..controller import customcells
    body = getattr(handler, "_body", {})
    dd = _custom_cells_dir(handler)
    if not dd:
        _respond(handler, "no active design dir", 400)
        return
    _respond(handler, customcells.remove_cell(dd, body.get("name", "")))


def h_custom_cell_enable(handler: Any) -> None:
    from ..controller import customcells
    body = getattr(handler, "_body", {})
    dd = _custom_cells_dir(handler)
    if not dd:
        _respond(handler, "no active design dir", 400)
        return
    result = customcells.set_enabled(dd, body.get("name", ""), bool(body.get("enabled")))
    if not result.get("ok"):
        _respond(handler, result.get("error", "not found"), 400)
        return
    _respond(handler, result)


def h_custom_macros(handler: Any) -> None:
    """List the active design's custom hard macros."""
    from ..controller import custommacros
    dd = _custom_cells_dir(handler)
    if not dd:
        _respond(handler, "no active design dir", 400)
        return
    _respond(handler, custommacros.list_macros(dd))


def h_custom_macro_save(handler: Any) -> None:
    """Save/replace a custom macro (uploaded views + instances) for a run."""
    from ..controller import custommacros
    body = getattr(handler, "_body", {})
    dd = _custom_cells_dir(handler)
    if not dd:
        _respond(handler, "no active design dir", 400)
        return
    result = custommacros.save_macro(
        dd, body.get("name", ""),
        instances=body.get("instances") or [],
        views=body.get("views") or {},
        enabled=body.get("enabled", True),
    )
    if not result.get("ok"):
        _respond(handler, result.get("error", "save failed"), 400)
        return
    _respond(handler, result)


def h_custom_macro_remove(handler: Any) -> None:
    from ..controller import custommacros
    body = getattr(handler, "_body", {})
    dd = _custom_cells_dir(handler)
    if not dd:
        _respond(handler, "no active design dir", 400)
        return
    _respond(handler, custommacros.remove_macro(dd, body.get("name", "")))


def h_custom_macro_enable(handler: Any) -> None:
    from ..controller import custommacros
    body = getattr(handler, "_body", {})
    dd = _custom_cells_dir(handler)
    if not dd:
        _respond(handler, "no active design dir", 400)
        return
    result = custommacros.set_enabled(dd, body.get("name", ""), bool(body.get("enabled")))
    if not result.get("ok"):
        _respond(handler, result.get("error", "not found"), 400)
        return
    _respond(handler, result)


def h_cells(handler: Any) -> None:
    from ..controller import cells
    pdk = _query_param(handler.path, "pdk")
    scl = _query_param(handler.path, "scl")
    _respond(handler, cells.list_pdk_cells(pdk, scl or None))


def h_plugins_registry(handler: Any) -> None:
    from ..controller import plugins
    _respond(handler, {"plugins": plugins.fetch_registry()})


def h_plugins_installed(handler: Any) -> None:
    from ..controller import plugins
    _respond(handler, {"installed": plugins.list_installed()})


def h_plugins_install(handler: Any) -> None:
    from ..controller import plugins
    body = getattr(handler, "_body", {})
    pid = body.get("id")
    if not pid:
        _respond(handler, "missing id", 400)
        return
    manifest = next((m for m in plugins.fetch_registry() if m.get("id") == pid), None)
    if manifest is None:
        _respond(handler, "plugin not in curated registry", 404)
        return
    result = plugins.install(manifest)
    if not result.get("ok"):
        if result.get("in_progress"):
            _respond(handler, result)
            return
        _respond(handler, result.get("error"), 400)
        return
    _respond(handler, result)


def h_plugins_remove(handler: Any) -> None:
    from ..controller import plugins
    body = getattr(handler, "_body", {})
    pid = body.get("id")
    if not pid:
        _respond(handler, "missing id", 400)
        return
    result = plugins.remove(pid)
    if not result.get("ok"):
        _respond(handler, result.get("error"), 400)
        return
    _respond(handler, result)


def h_plugins_enable(handler: Any) -> None:
    from ..controller import plugins
    body = getattr(handler, "_body", {})
    pid = body.get("id")
    enabled = bool(body.get("enabled"))
    if not pid:
        _respond(handler, "missing id", 400)
        return
    result = plugins.set_enabled(pid, enabled)
    if not result.get("ok"):
        _respond(handler, result.get("error"), 400)
        return
    _respond(handler, result)


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------

ROUTES: List[Tuple[str, Any]] = [
    ("/api/templates", h_templates),
    ("/api/project/new", h_project_new),
    ("/api/run-export", h_run_export),
    ("/api/verify/rerun", h_verify_rerun),
    ("/api/verify", h_verify),
    ("/api/compare", h_compare),
    ("/api/cell-usage", h_cell_usage),
    ("/api/timing-paths", h_timing_paths),
    ("/api/dse/start", h_dse_start),
    ("/api/dse/cancel", h_dse_cancel),
    ("/api/dse/sweeps", h_dse_sweeps),
    ("/api/dse/status", h_dse_status),
    ("/api/system-resources", h_system_resources),
    ("/api/file/write", h_file_write),
    ("/api/file/delete", h_file_delete),
    ("/api/lint", h_lint),
    ("/api/lint-result", h_lint_result),
    ("/api/sim/testbenches", h_sim_testbenches),
    ("/api/sim/start", h_sim_start),
    ("/api/sim/cancel", h_sim_cancel),
    ("/api/waveform", h_waveform),
    ("/api/cells", h_cells),
    ("/api/custom-cells/save", h_custom_cell_save),
    ("/api/custom-cells/remove", h_custom_cell_remove),
    ("/api/custom-cells/enable", h_custom_cell_enable),
    ("/api/custom-cells", h_custom_cells),
    ("/api/custom-macros/save", h_custom_macro_save),
    ("/api/custom-macros/remove", h_custom_macro_remove),
    ("/api/custom-macros/enable", h_custom_macro_enable),
    ("/api/custom-macros", h_custom_macros),
    ("/api/plugins/registry", h_plugins_registry),
    ("/api/plugins/installed", h_plugins_installed),
    ("/api/plugins/install", h_plugins_install),
    ("/api/plugins/remove", h_plugins_remove),
    ("/api/plugins/enable", h_plugins_enable),
    ("/api/health", h_health),
    ("/api/about", h_about),
    ("/api/steps", h_steps),
    ("/api/variables", h_variables),
    ("/api/design-formats", h_design_formats),
    ("/api/flows", h_flows),
    ("/api/pdks", h_pdks),
    ("/api/scls", h_scls),
    ("/api/pdk-ready", h_pdk_ready),
    ("/api/runs", h_runs),
    ("/api/known-designs", h_known_designs),
    ("/api/run-step-log", h_run_step_log),
    ("/api/run-files", h_run_files),
    ("/api/run-images", h_run_images),
    ("/api/run-outputs", h_run_outputs),
    ("/api/run-diagrams", h_run_diagrams),
    ("/api/render-dot", h_render_dot),
    ("/api/run-note", h_run_note),
    ("/api/watch", h_watch),
    ("/api/run-pin", h_run_pin),
    ("/api/run-gui-meta", h_run_gui_meta),
    ("/api/run-import-dir", h_run_import_dir),
    ("/api/run-import-bundle", h_run_import_bundle),
    ("/api/run-bundle", h_run_bundle),
    ("/api/trends", h_trends),
    ("/api/run-delete", h_run_delete),
    ("/api/reveal", h_reveal),
    ("/api/desktop-tools", h_desktop_tools),
    ("/api/container-tools", h_container_tools),
    ("/api/open-in-tool", h_open_in_tool),
    ("/api/runs/", h_run),
    ("/api/tools", h_tools),
    ("/api/metrics-catalog", h_metrics_catalog),
    ("/api/run/status", h_run_status),
    ("/api/reports/drc", h_reports_drc),
    ("/api/reports/lvs", h_reports_lvs),
    ("/api/fs/roots", h_fs_roots),
    ("/api/fs/list", h_fs_list),
    ("/api/walk-sources", h_walk_sources),
    ("/api/run-reports", h_run_reports),
    ("/api/read-text", h_read_text),
    ("/api/design-summary", h_design_summary),
    ("/api/suggest-config", h_suggest_config),
    ("/api/write-config", h_write_config),
    ("/api/step/", h_step),
    ("/api/design-dir", h_get_design_dir),
    ("/api/preflight", h_preflight),
    ("/api/set-design-dir", h_set_design_dir),
    ("/api/diff", h_diff),
    ("/api/explain", h_explain),
    ("/api/explain-checker", h_explain_checker),
    ("/api/cli-command", h_cli_command),
    ("/api/manual/run", h_manual_run),
    ("/api/manual/cancel", h_manual_cancel),
    ("/api/manual/result", h_manual_result),
    ("/api/run/start", h_run_start),
    ("/api/run/cancel", h_run_cancel),
    ("/api/run/resume", h_run_resume),
    ("/api/reproducible", h_reproducible),
    ("/api/tools/install-ciel", h_tools_install_ciel),
    ("/api/container/pull", h_container_pull),
    ("/api/container/enable-docker-group", h_container_enable_docker),
    ("/api/tools/cancel", h_tools_cancel),
    ("/api/settings/pdk-root", h_settings_pdk_root),
    ("/api/tools/install/", h_tools_install),
    ("/api/tools/uninstall/", h_tools_uninstall),
    ("/api/pdk/uninstall", h_pdk_uninstall),
    ("/api/pdk/fix-permissions", h_pdk_fix_permissions),
    ("/api/copy-spm", h_copy_spm),
]

__all__ = [
    "ROUTES",
    "serve_view",
    "static_root",
]
