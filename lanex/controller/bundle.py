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
"""Build a reproducibility / support bundle (a single .zip) for one run.

One file to hand a collaborator or a LibreLane maintainer. The caller chooses
*what* goes in (a checklist in the UI), so the same endpoint produces anything
from "just the final metrics CSV" to "every deliverable". Contents the user can
pick — light text/data parts first, then heavy binary deliverables:

  * ``config``       — the used config: ``config.json`` + ``resolved.json``
                       (every variable LibreLane actually applied) + the GUI's
                       ``gui-run.json`` (chosen preset/overrides, PDK, SCL, CLI).
  * ``sources``      — the RTL source files the run consumed (``VERILOG_FILES``).
  * ``metrics_csv``  — every recorded metric, one row each, sorted.
  * ``settings_csv`` — every resolved setting/constraint/PDK/library value, with
                       a flag for the ones the user set explicitly.
  * ``analytics_csv``— a single results CSV: the curated design summary +
                       report-summary counts + all raw metrics.
  * ``reports``      — the signoff reports (``*.rpt/*.drc/*.lvs``) per step.
  * ``logs``         — per-step ``*.log`` + ``warnings.log`` / ``error.log``.
  * ``gds``          — the final layout stream: GDSII (``*.gds``) + OASIS, the
                       single most-asked deliverable (tape-out / macro reuse).
  * ``layout_views`` — the other physical views under ``final/``: DEF, LEF, the
                       OpenDB (``*.odb``) database, Magic ``*.mag``.
  * ``netlists``     — gate-level + powered Verilog netlists, SPICE/CDL, the
                       design JSON header (everything to re-simulate / re-LVS).
  * ``timing``       — Liberty (``*.lib``), SDF delays, SPEF parasitics, the SDC
                       constraints (everything to re-time the block downstream).
  * ``images``       — every rendered image artefact in the run: the KLayout
                       layout render(s) (PNG/SVG) and any per-step renders.
  * ``diagrams``     — the Yosys synthesis schematics: the ``*.dot`` sources and
                       (best-effort, when graphviz is present) rendered ``*.svg``.

The heavy binary parts are **opt-in only**: the bare default and the legacy
``mode`` shortcuts emit just the light text/data parts, so an unattended call
can never produce a multi-hundred-MB zip by surprise. Tick them (or pass the
``all`` token) to include them.

Pure stdlib (``zipfile`` + ``csv`` + ``tempfile``); no new dependency, nothing
leaves the machine. Cross-platform. Files too big for the caps are recorded in a
``SKIPPED.json`` member (never silently dropped) so the user knows to grab them
individually via the per-run Files browser.
"""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import platform
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Dict, Iterable, List, Optional, Set

# Light text/data parts — cheap, always safe; the default bundle.
TEXT_PARTS: List[str] = [
    "config", "sources", "metrics_csv", "settings_csv", "analytics_csv",
    "reports", "logs",
]
# Heavy binary deliverables — opt-in only (can be hundreds of MB each).
HEAVY_PARTS: List[str] = [
    "gds", "layout_views", "netlists", "timing", "images", "diagrams",
]
# Everything the checklist can toggle. The bare default is TEXT_PARTS only;
# the ``all``/``everything`` token (or ticking the boxes) pulls HEAVY_PARTS too.
ALL_PARTS: List[str] = TEXT_PARTS + HEAVY_PARTS

_PER_FILE_CAP = 4 * 1024 * 1024          # 4 MiB per text/report/log/source file
_BINARY_FILE_CAP = 256 * 1024 * 1024     # 256 MiB per heavy binary deliverable
_TOTAL_CAP = 80 * 1024 * 1024            # 80 MiB ceiling for a text-only bundle
_HEAVY_TOTAL_CAP = 1024 * 1024 * 1024    # 1 GiB ceiling once a heavy part is in
_REPORT_EXTS = (".rpt", ".drc", ".lvs", ".spef")
_LOG_NAMES_ROOT = ["warnings.log", "error.log"]
# DesignFormat ids (under final/) that are a layout STREAM → the ``gds`` part.
_GDS_FORMATS = {"gds", "klayout_gds", "mag_gds"}
_GDS_EXTS = (".gds", ".gds.gz", ".gdsii", ".oas", ".oas.gz", ".oasis")


def _gui_version() -> str:
    try:
        import importlib.metadata as md
        return md.version("librelane-gui")
    except Exception:
        return "unknown"


def _librelane_version() -> str:
    try:
        import importlib.metadata as md
        return md.version("librelane")
    except Exception:
        try:
            import librelane  # type: ignore
            return getattr(librelane, "__version__", "unknown")
        except Exception:
            return "unknown"


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def manifest(run_dir: Path) -> Dict[str, Any]:
    """The environment + reproduction context recorded in the bundle."""
    gui_meta = _read_json(run_dir / "gui-run.json")
    return {
        "run_tag": run_dir.name,
        "gui_version": _gui_version(),
        "librelane_version": _librelane_version(),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cli_command": gui_meta.get("cli_command"),
        "run_mode": gui_meta.get("run_mode"),
        "pdk": gui_meta.get("pdk"),
        "scl": gui_meta.get("scl"),
        "flow": gui_meta.get("flow"),
        "container_image": gui_meta.get("image"),
    }


# --------------------------------------------------------------------------- #
# CSV builders (stdlib csv; return text)
# --------------------------------------------------------------------------- #
def _metrics_csv(metrics: Dict[str, Any]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["metric", "value"])
    for k in sorted(metrics.keys()):
        w.writerow([k, metrics[k]])
    return out.getvalue()


def _settings_csv(resolved: Dict[str, Any], gui_meta: Dict[str, Any]) -> str:
    """Every resolved setting/constraint/PDK/library value, newest semantics
    first; flags the ones the user set in the GUI."""
    user_overrides = {}
    ov = gui_meta.get("overrides")
    if isinstance(ov, dict):
        user_overrides = ov
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["setting", "value", "user_set"])
    # The GUI-level choices first (PDK/SCL/flow/mode), then the full resolved set.
    # Track the upper-cased labels we emit here so a resolved key with the same
    # name (e.g. "PDK") isn't written twice.
    emitted: Set[str] = set()
    for label in ("pdk", "scl", "flow", "run_mode"):
        if gui_meta.get(label) is not None:
            w.writerow([label.upper(), gui_meta.get(label), "yes"])
            emitted.add(label.upper())
    for k in sorted(resolved.keys()):
        if k.upper() in emitted:
            continue
        v = resolved[k]
        if isinstance(v, (dict, list)):
            v = json.dumps(v)
        w.writerow([k, v, "yes" if k in user_overrides else ""])
    return out.getvalue()


def _analytics_csv(run_dir: Path, metrics: Dict[str, Any]) -> str:
    """One results file: curated summary + report-summary counts + all metrics."""
    rows: List[List[Any]] = []
    try:
        from . import history
        for r in history.design_summary(run_dir, metrics):
            rows.append(["summary", r.get("label"), r.get("value"),
                         r.get("unit", ""), r.get("status", "")])
    except Exception:
        pass
    # Report-summary counts straight from the (real) LibreLane metric names — no
    # fabrication. Keys verified against a real run's metrics.json.
    for label, key in (
        ("DRC violations (Routing)", "route__drc_errors"),
        ("DRC violations (Magic)", "magic__drc_error__count"),
        ("DRC violations (KLayout)", "klayout__drc_error__count"),
        ("LVS errors", "design__lvs_error__count"),
        ("Antenna violations", "route__antenna_violation__count"),
        ("Setup violations", "timing__setup_vio__count"),
        ("Hold violations", "timing__hold_vio__count"),
    ):
        if key in metrics:
            rows.append(["report", label, metrics[key], "", ""])
    for k in sorted(metrics.keys()):
        rows.append(["metric", k, metrics[k], "", ""])
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["category", "name", "value", "unit", "status"])
    for r in rows:
        w.writerow(r)
    return out.getvalue()


# --------------------------------------------------------------------------- #
def _strip_ll_prefix(item: str) -> str:
    """Drop LibreLane path-spec prefixes (``dir::``, ``refg::``, ``ref::`` …).

    A resolved ``VERILOG_FILES`` entry can carry these scheme prefixes; left in,
    the path would never resolve and the source would be silently dropped."""
    s = str(item)
    for pre in ("dir::", "refg::", "ref::"):
        if s.startswith(pre):
            return s[len(pre):]
    return s


def _source_files(run_dir: Path, resolved: Dict[str, Any]) -> List[Path]:
    """Resolve VERILOG_FILES to real on-disk paths (design-dir or run-relative).

    Bundles EXACTLY the run's resolved source list (which the GUI builds from the
    user's tick-marked sources, testbenches already excluded by autoconfig) — it
    is never a blanket glob of every ``*.v`` in the folder. Glob patterns that
    appear in the list ARE expanded (so a ``src/*.v`` spec still maps to the real
    files it selected), and results are de-duplicated by resolved path.
    """
    vf = resolved.get("VERILOG_FILES")
    if not vf:
        return []
    if isinstance(vf, str):
        vf = vf.split()
    design_dir = run_dir.parent.parent          # <design>/runs/<tag>
    bases = [design_dir, run_dir, Path.cwd()]
    found: List[Path] = []
    seen: Set[str] = set()

    def _take(p: Path) -> None:
        try:
            rp = p.resolve()
        except OSError:
            return
        key = str(rp)
        if rp.is_file() and key not in seen:
            seen.add(key)
            found.append(rp)

    for raw in vf:
        item = _strip_ll_prefix(raw)
        p = Path(item)
        if any(ch in item for ch in "*?["):     # a glob pattern, not a literal path
            if p.is_absolute():
                import glob as _glob
                for m in _glob.glob(item):
                    _take(Path(m))
            else:
                for b in bases:
                    for m in b.glob(item):
                        _take(m)
            continue
        cands = [p] if p.is_absolute() else [b / p for b in bases]
        for c in cands:
            try:
                if c.is_file():
                    _take(c)
                    break
            except OSError:
                continue
    return found


def _normalize_parts(include: Optional[Iterable[str]]) -> Set[str]:
    # No explicit selection → the light text/data parts only. Heavy binary
    # deliverables (gds/layout/netlists/timing/images/diagrams) are opt-in so a
    # bare or unattended call can never emit a giant zip by surprise.
    if not include:
        return set(TEXT_PARTS)
    want = {str(x).strip() for x in include if str(x).strip()}
    # "all"/"everything" shortcut = literally everything, heavy parts included.
    if want & {"all", "everything"}:
        return set(ALL_PARTS)
    return want & set(ALL_PARTS) or set(TEXT_PARTS)


# --------------------------------------------------------------------------- #
# Heavy deliverable resolvers — reuse history's canonical final/ categorisation
# so new LibreLane DesignFormats flow in automatically (no second source of
# truth). Each returns ``[(arcname, Path), ...]`` rooted at the part's folder.
# --------------------------------------------------------------------------- #
def _output_rows(run_dir: Path) -> List[Dict[str, Any]]:
    try:
        from . import history
        return history.list_run_outputs(run_dir)
    except Exception:
        return []


def _is_gds_row(row: Dict[str, Any]) -> bool:
    if row.get("format") in _GDS_FORMATS:
        return True
    return str(row.get("name", "")).lower().endswith(_GDS_EXTS)


def _gds_files(run_dir: Path) -> List["tuple[str, Path]"]:
    out: List["tuple[str, Path]"] = []
    for r in _output_rows(run_dir):
        if _is_gds_row(r):
            p = run_dir / r["path"]
            if p.is_file():
                out.append((f"gds/{Path(r['path']).name}", p))
    return out


def _flatten(rel: str) -> str:
    """Flatten an OS-native run-relative path into one ``__``-joined arc segment
    (cross-platform: handles both ``/`` and Windows ``\\`` separators)."""
    return rel.replace("\\", "/").replace("/", "__")


def _under_final(rel: str) -> str:
    """The sub-path beneath ``final/`` as a forward-slash arcname (cross-platform:
    ``list_run_outputs`` paths are OS-native, so split on parts, not a string)."""
    parts = Path(rel).parts
    if parts and parts[0] == "final":
        parts = parts[1:]
    return "/".join(parts)


def _layout_view_files(run_dir: Path) -> List["tuple[str, Path]"]:
    # Layout-category artefacts that are NOT the GDS stream and NOT the PNG
    # render (those have their own parts: ``gds`` and ``images``).
    out: List["tuple[str, Path]"] = []
    for r in _output_rows(run_dir):
        if r.get("category") != "Layout":
            continue
        if r.get("format") == "render" or _is_gds_row(r):
            continue
        p = run_dir / r["path"]
        if p.is_file():
            out.append((f"layout/{_under_final(r['path'])}", p))
    return out


def _category_files(run_dir: Path, category: str, folder: str) -> List["tuple[str, Path]"]:
    out: List["tuple[str, Path]"] = []
    for r in _output_rows(run_dir):
        if r.get("category") != category:
            continue
        p = run_dir / r["path"]
        if p.is_file():
            out.append((f"{folder}/{_under_final(r['path'])}", p))
    return out


def _image_files(run_dir: Path) -> List["tuple[str, Path]"]:
    try:
        from . import history
        rows = history.list_run_images(run_dir)
    except Exception:
        rows = []
    out: List["tuple[str, Path]"] = []
    seen: Set[str] = set()
    for r in rows:
        rel = r.get("path", "")
        # A rendered graphviz diagram (``<name>.dot.svg``) is not a layout image
        # — it belongs to the ``diagrams`` part, so don't double-list it here.
        if rel.lower().endswith(".dot.svg"):
            continue
        p = run_dir / rel
        if not p.is_file() or rel in seen:
            continue
        seen.add(rel)
        out.append((f"images/{_flatten(rel)}", p))
    return out


def _diagram_files(run_dir: Path) -> List["tuple[str, Path]"]:
    """Yosys synthesis schematics: every ``.dot`` source plus, best-effort, its
    rendered ``.svg`` AND ``.png`` (graphviz via :func:`history.render_dot` /
    :func:`history.render_dot_png`; gracefully skips when graphviz is absent or
    the diagram is too big to render safely). The PNG is the drop-in raster image
    a user can open anywhere; the SVG stays for zoomable inspection."""
    try:
        from . import history
        rows = history.list_run_diagrams(run_dir)
    except Exception:
        return []
    out: List["tuple[str, Path]"] = []
    for r in rows:
        rel = r.get("path", "")
        dot = run_dir / rel
        if not dot.is_file():
            continue
        flat = _flatten(rel)
        out.append((f"diagrams/{flat}", dot))
        try:
            res = history.render_dot(run_dir, rel)
            if res.get("ok") and res.get("svg"):
                svg = run_dir / res["svg"]
                if svg.is_file():
                    out.append((f"diagrams/{flat}.svg", svg))
        except Exception:
            pass
        try:
            res = history.render_dot_png(run_dir, rel)
            if res.get("ok") and res.get("png"):
                png = run_dir / res["png"]
                if png.is_file():
                    out.append((f"diagrams/{flat}.png", png))
        except Exception:
            pass
    return out


# Maps each heavy part key to the resolver that yields its (arcname, path) pairs.
def _heavy_files(part: str, run_dir: Path) -> List["tuple[str, Path]"]:
    if part == "gds":
        return _gds_files(run_dir)
    if part == "layout_views":
        return _layout_view_files(run_dir)
    if part == "netlists":
        return _category_files(run_dir, "Netlist", "netlists")
    if part == "timing":
        return _category_files(run_dir, "Timing", "timing")
    if part == "images":
        return _image_files(run_dir)
    if part == "diagrams":
        return _diagram_files(run_dir)
    return []


def _resolve_parts(include: Optional[Iterable[str]], mode: Optional[str]) -> Set[str]:
    """Map (include, legacy mode) to the concrete set of parts to emit."""
    if include is None and mode is not None:
        include = (["config", "settings_csv", "metrics_csv", "analytics_csv", "reports"]
                   if mode == "minimal" else None)
    return _normalize_parts(include)


def write_bundle(dest: BinaryIO, run_dir: str | Path, *,
                 include: Optional[Iterable[str]] = None,
                 mode: Optional[str] = None) -> Dict[str, Any]:
    """Write the .zip into the binary file object *dest* (streamed; the caller
    chooses the backing store — a :class:`tempfile.SpooledTemporaryFile` keeps
    even a 1 GiB bundle off the heap). Returns a small summary
    ``{parts, skipped}`` where ``skipped`` lists any file omitted by the caps so
    nothing is dropped silently. Raises ``FileNotFoundError`` if run is missing.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(str(run_dir))
    parts = _resolve_parts(include, mode)

    final = run_dir / "final"
    metrics = _read_json(final / "metrics.json")
    resolved = _read_json(run_dir / "resolved.json") or _read_json(run_dir / "config.json")
    gui_meta = _read_json(run_dir / "gui-run.json")

    # A heavier ceiling once a binary deliverable is requested; text-only stays
    # at the modest 80 MiB so a routine support zip can't balloon.
    heavy = bool(parts & set(HEAVY_PARTS))
    budget = [_HEAVY_TOTAL_CAP if heavy else _TOTAL_CAP]
    skipped: List[Dict[str, Any]] = []
    seen_arc: Set[str] = set()

    def add_file(arc: str, path: Path, *, cap: int = _PER_FILE_CAP) -> None:
        if arc in seen_arc:
            return
        try:
            size = path.stat().st_size
        except OSError:
            return
        if size > cap:
            skipped.append({"path": arc, "size": size, "reason": "exceeds per-file cap"})
            return
        if budget[0] - size < 0:
            skipped.append({"path": arc, "size": size, "reason": "exceeds bundle size budget"})
            return
        try:
            zf.write(path, arc)
            seen_arc.add(arc)
            budget[0] -= size
        except Exception:
            pass

    def add_text(arc: str, text: str) -> None:
        data = text.encode("utf-8")
        if budget[0] - len(data) < 0:
            return
        zf.writestr(arc, data)
        budget[0] -= len(data)

    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        add_text("MANIFEST.json", json.dumps(manifest(run_dir), indent=2))

        if "config" in parts:
            for name in ("gui-run.json", "config.json", "resolved.json"):
                f = run_dir / name
                if f.is_file():
                    add_file(f"config/{name}", f)
            # The canonical metrics file, byte-for-byte (NOT the derived CSV) so
            # an imported bundle reproduces the EXACT same metric values (E1).
            mj = final / "metrics.json"
            if mj.is_file():
                add_file("final/metrics.json", mj)

        if "metrics_csv" in parts and metrics:
            add_text("metrics.csv", _metrics_csv(metrics))
        if "settings_csv" in parts and (resolved or gui_meta):
            add_text("settings.csv", _settings_csv(resolved, gui_meta))
        if "analytics_csv" in parts and metrics:
            add_text("analytics.csv", _analytics_csv(run_dir, metrics))

        if "sources" in parts:
            for f in _source_files(run_dir, resolved):
                add_file(f"sources/{f.name}", f)

        if "logs" in parts:
            for name in _LOG_NAMES_ROOT:
                f = run_dir / name
                if f.is_file():
                    add_file(name, f)

        if "reports" in parts or "logs" in parts:
            for entry in sorted(run_dir.iterdir()):
                if not entry.is_dir():
                    continue
                prefix, sep, _ = entry.name.partition("-")
                if not prefix.isdigit() or not sep:
                    continue
                for f in sorted(entry.iterdir()):
                    if not f.is_file():
                        continue
                    low = f.name.lower()
                    is_report = low.endswith(_REPORT_EXTS)
                    is_log = low.endswith(".log")
                    if (is_report and "reports" in parts) or (is_log and "logs" in parts):
                        add_file(f"{entry.name}/{f.name}", f)
                    if budget[0] <= 0:
                        break

        # Heavy binary deliverables (opt-in). Each gets the larger per-file cap.
        for part in HEAVY_PARTS:
            if part not in parts:
                continue
            for arc, path in _heavy_files(part, run_dir):
                add_file(arc, path, cap=_BINARY_FILE_CAP)
                if budget[0] <= 0:
                    break

        # Honesty: record anything the caps omitted so the user can fetch it
        # individually from the per-run Files browser (never a silent drop).
        if skipped:
            add_text("SKIPPED.json", json.dumps(
                {"note": "These files were omitted to keep the bundle within its "
                         "size budget. Download them individually from the run's "
                         "Files browser.", "files": skipped}, indent=2))

    return {"parts": sorted(parts), "skipped": skipped}


def build_bundle(run_dir: str | Path, *, include: Optional[Iterable[str]] = None,
                 mode: Optional[str] = None) -> bytes:
    """Return a .zip (bytes) of *run_dir* containing the selected ``include`` parts.

    ``include`` is any subset of :data:`ALL_PARTS`. With neither ``include`` nor
    ``mode``, the default is the light text/data parts only (:data:`TEXT_PARTS`);
    pass the ``all`` token or tick the heavy boxes to add binary deliverables.
    ``mode`` is the legacy arg (``minimal`` → config+CSVs+reports; anything else
    → the text default). Raises ``FileNotFoundError`` if the run is missing.

    Convenience wrapper that buffers in memory — prefer :func:`write_bundle` for
    heavy parts so the zip can spill to disk instead of the heap.
    """
    buf = io.BytesIO()
    write_bundle(buf, run_dir, include=include, mode=mode)
    return buf.getvalue()


def import_bundle(src: "str | Path | BinaryIO", design_dir: str | Path) -> Dict[str, Any]:
    """Import a LanEx export bundle (.zip) as a *viewable partial run* under
    ``<design>/runs/`` (E1, mode 2). *src* is a filesystem path or a binary file
    object. Returns ``{"tag", "warnings"}``.

    An imported bundle only contains what was packed; every consumer already
    degrades gracefully on absent files, and ``warnings`` names what is missing.
    Zip-slip safe (any member whose path escapes the run dir is dropped) and the
    real ``final/metrics.json`` (packed byte-for-byte by :func:`write_bundle`) is
    restored verbatim, so the imported run reports the exact same metric values.
    """
    if isinstance(src, (str, Path)):
        src_path = Path(src).expanduser()
        if not src_path.is_file():
            raise FileNotFoundError(f"no such bundle: {src_path}")
        zf_src: Any = str(src_path)
    else:
        zf_src = src

    runs_root = Path(design_dir).resolve() / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    try:
        zf_ctx = zipfile.ZipFile(zf_src)
    except zipfile.BadZipFile as ex:
        raise ValueError(f"not a valid .zip bundle: {ex}") from ex

    with zf_ctx as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("empty or invalid bundle")
        base = "bundle"
        try:
            mani = json.loads(zf.read("MANIFEST.json"))
            if isinstance(mani, dict) and mani.get("run_tag"):
                base = str(mani["run_tag"])
        except (KeyError, ValueError):
            pass
        tag = f"{base}-imported"
        dest = runs_root / tag
        n = 2
        while dest.exists():
            tag = f"{base}-imported-{n}"
            dest = runs_root / tag
            n += 1
        dest_res = dest.resolve()

        def _target(arc: str) -> Optional[Path]:
            # ``config/<name>`` lands at the run root (where history reads the
            # config + metrics); every other member keeps its relative path.
            rel = arc[len("config/"):] if arc.startswith("config/") else arc
            if not rel or rel.endswith("/"):
                return None
            t = (dest / rel).resolve()
            try:
                t.relative_to(dest_res)  # zip-slip guard
            except ValueError:
                return None
            return t

        wrote_any = False
        for arc in names:
            t = _target(arc)
            if t is None:
                continue
            t.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(arc) as fsrc, open(t, "wb") as fdst:
                shutil.copyfileobj(fsrc, fdst)
            wrote_any = True

    if not wrote_any:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError("bundle had no usable members (all paths were unsafe)")

    manifest_hash = hashlib.sha256("\n".join(sorted(names)).encode()).hexdigest()[:16]
    try:
        (dest / "gui-imported.json").write_text(
            json.dumps(
                {"source": "bundle", "manifest": manifest_hash,
                 "imported_at": datetime.datetime.now().isoformat()},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    warnings: List[str] = []
    if not (dest / "final" / "metrics.json").is_file():
        warnings.append("no metrics.json in this bundle — Analytics will be empty.")
    if not any(dest.glob("gds/*")) and not any((dest / "final").glob("**/*.gds*")):
        warnings.append("no GDS in this bundle — the Preview layout will be empty.")
    if (dest / "SKIPPED.json").is_file():
        warnings.append("the source bundle omitted some large files (see SKIPPED.json).")
    return {"tag": tag, "warnings": warnings}
