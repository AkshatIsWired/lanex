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
"""Auto-detect a LibreLane config for a design that has none.

When a user points the GUI at a folder of RTL with no ``config.{json,yaml,tcl}``,
LibreLane has nothing to run. This module derives a *minimal, valid* config by
reading the Verilog/SystemVerilog sources:

* the **top module** (declared but never instantiated by any other module),
* its **clock port** (a port whose name looks like a clock), and
* the **source files** to compile.

It only emits **verified-real** LibreLane variables — every key is cross-checked
against :func:`introspect.list_variables` in ``test_autoconfig.py`` — so a
generated config always passes config resolution. Pure stdlib; no new
dependency, no private LibreLane API, cross-platform via ``pathlib``.

The detection is a lightweight lexical scan, *not* a full Verilog parser: it
strips comments and matches ``module <name>`` declarations and instantiations.
That is enough to pick a top module for the common case and is always presented
to the user as an editable suggestion they confirm — never written silently.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Source extensions we read for module detection (Verilog + SystemVerilog).
_RTL_EXTS = (".v", ".sv", ".verilog")
# VHDL is supported by LibreLane via the (optional) GHDL plugin; we still detect
# its entities so the top guess is reasonable, but the common flow is Verilog.
_VHDL_EXTS = (".vhd", ".vhdl")

_CONFIG_NAMES = ("config.json", "config.yaml", "config.yml", "config.tcl")

# Variables we are willing to emit. Kept to the canonical verified-real set so a
# generated config always resolves. (Locked in test_autoconfig.py.)
_EMIT_VARS = (
    "DESIGN_NAME",
    "VERILOG_FILES",
    "VHDL_FILES",
    "CLOCK_PORT",
    "CLOCK_PERIOD",
    "PDK",
    "STD_CELL_LIBRARY",
)

# A port name that looks like a clock. Ordered most- to least-specific so the
# best candidate wins when a module has several.
_CLOCK_HINTS = (
    re.compile(r"^(i_)?clk$", re.I),
    re.compile(r"^(i_)?clock$", re.I),
    re.compile(r"^clk_?i$", re.I),
    re.compile(r"^clock_?i$", re.I),
    re.compile(r"^(sys|core|main|ref|hclk|pclk|aclk)_?clk", re.I),
    re.compile(r"clk", re.I),
    re.compile(r"clock", re.I),
)

_COMMENT_RX = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_MODULE_DECL_RX = re.compile(r"\bmodule\s+(\\?[A-Za-z_][A-Za-z0-9_$]*)", re.I)
_VHDL_ENTITY_RX = re.compile(r"\bentity\s+([A-Za-z_][A-Za-z0-9_]*)\s+is", re.I)

# A file/module name that looks like a simulation testbench (NOT synthesisable
# RTL): it must never be picked as the design top, nor be listed in
# VERILOG_FILES (the synthesis source list) — doing either is the #1 reason the
# generated flow fails ("multiple/ambiguous top", or synth chokes on `initial`/
# `$finish`/`$display` in a bench). Benches belong in verify/ and feed the sim.
_TB_NAME_RX = re.compile(r"(^|[_\W])(tb|testbench|test|sim|stim|tester)([_\W]|$)", re.I)
# Simulation-only constructs a synthesisable module never contains.
_SIM_ONLY_RX = re.compile(r"\$(finish|stop|dumpvars|dumpfile|display|monitor|readmemh|readmemb|fwrite|fopen|time|random)\b", re.I)


def _module_has_ports(text: str, name: str) -> bool:
    """True if module *name* declares a port list — ``module foo (`` — vs a
    classic bench ``module foo;`` which has none."""
    m = re.search(r"\bmodule\s+" + re.escape(name) + r"\s*([;(])", text)
    return bool(m and m.group(1) == "(")


def _testbench_modules(text: str, declared_here: List[str]) -> set:
    """Of the modules *declared_here* (in one file's *text*), the ones that look
    like a simulation testbench: a port-less module, or a module whose name reads
    like a bench, in a file that uses sim-only system tasks."""
    out: set = set()
    sim_only = bool(_SIM_ONLY_RX.search(text))
    for nm in declared_here:
        nameish = bool(_TB_NAME_RX.search(nm))
        portless = not _module_has_ports(text, nm)
        # Port-less module that drives stimulus, or a clearly-named bench.
        if (portless and sim_only) or (nameish and (sim_only or portless)):
            out.add(nm)
    return out


def has_config(design_dir: str | Path) -> bool:
    """True if *design_dir* already holds a LibreLane config file."""
    d = Path(design_dir)
    return any((d / n).is_file() for n in _CONFIG_NAMES)


def _strip_comments(text: str) -> str:
    return _COMMENT_RX.sub(" ", text)


def _module_header(text: str, name: str) -> str:
    """Return the port-declaration region of module *name* (decl → first ``;``),
    used to scan for the clock port. Best-effort; empty string if not found."""
    m = re.search(r"\bmodule\s+" + re.escape(name) + r"\b", text)
    if not m:
        return ""
    rest = text[m.end():]
    semi = rest.find(";")
    return rest[:semi] if semi != -1 else rest[:2000]


def _ports_of(text: str, name: str) -> List[str]:
    """Identifiers that appear in module *name*'s header — a superset of its
    ports. Good enough to find a clock-like name."""
    header = _module_header(text, name)
    # Drop parameter section #( ... ) so parameter names don't masquerade as ports.
    header = re.sub(r"#\s*\(.*?\)", " ", header, flags=re.S)
    idents = re.findall(r"[A-Za-z_][A-Za-z0-9_$]*", header)
    skip = {"module", "input", "output", "inout", "reg", "wire", "logic",
            "signed", "unsigned", "parameter", "localparam"}
    seen: set = set()
    out: List[str] = []
    for tok in idents:
        if tok.lower() in skip or tok == name:
            continue
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out


def _detect_clock_port(text: str, top: str) -> Optional[str]:
    """Pick the most clock-like port of *top* (or any clock-like input as a
    fallback when the header scan misses it)."""
    ports = _ports_of(text, top)
    for rx in _CLOCK_HINTS:
        for p in ports:
            if rx.match(p):
                return p
    # Fallback: scan input declarations across the whole text for a clk name.
    for rx in _CLOCK_HINTS:
        for m in re.finditer(r"\binput\b[^;]*?\b([A-Za-z_][A-Za-z0-9_$]*)\b", text):
            if rx.match(m.group(1)):
                return m.group(1)
    return None


def _normalise_only(design_dir: Path, only_files: Optional[Sequence[str]]) -> Optional[set]:
    """Turn the GUI's *only_files* (abs or design-relative paths, the user's
    tick-marked sources) into a set of design-relative POSIX strings, or None
    when no restriction was given. Paths outside the design dir are dropped."""
    if not only_files:
        return None
    keep: set = set()
    for raw in only_files:
        if not raw:
            continue
        p = Path(raw)
        try:
            rel = p.resolve().relative_to(design_dir) if p.is_absolute() else Path(raw)
        except ValueError:
            continue
        keep.add(rel.as_posix())
    return keep or None


def scan_sources(
    design_dir: str | Path,
    *,
    only_files: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Read the RTL under *design_dir* and return module/top analysis.

    *only_files* (the user's tick-marked sources, abs or design-relative paths)
    restricts the scan to exactly those files — so a testbench the user left
    unticked is never considered. When omitted, every RTL file is scanned and
    testbench-looking files are detected heuristically.

    Returns ``{verilog:[rel...], vhdl:[rel...], modules:[...], instantiated:set,
    top_candidates:[...], top, clock_port, testbench_files:[...],
    testbench_modules:[...], errors:[...]}``. Never raises.
    """
    d = Path(design_dir).resolve()
    only = _normalise_only(d, only_files)
    verilog: List[str] = []
    vhdl: List[str] = []
    declared: List[str] = []
    declared_files: Dict[str, str] = {}
    instantiated: set = set()
    tb_modules: set = set()
    tb_files: set = set()
    combined = ""
    errors: List[str] = []
    skip_dirs = {".git", "runs", "tmp", "__pycache__", "build", "node_modules"}

    files: List[Path] = []
    try:
        for f in sorted(d.rglob("*")):
            if not f.is_file():
                continue
            if any(part in skip_dirs for part in f.relative_to(d).parts[:-1]):
                continue
            ext = f.suffix.lower()
            rel = str(f.relative_to(d))
            if only is not None and Path(rel).as_posix() not in only:
                continue
            if ext in _RTL_EXTS:
                verilog.append(rel)
                files.append(f)
            elif ext in _VHDL_EXTS:
                vhdl.append(rel)
                files.append(f)
    except Exception as ex:  # pragma: no cover - fs dependent
        errors.append(str(ex))

    synth_text = ""  # corpus of NON-testbench files only (for instantiation)
    for f in files:
        rel = str(f.relative_to(d))
        try:
            raw = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        text = _strip_comments(raw)
        combined += "\n" + text
        if f.suffix.lower() in _VHDL_EXTS:
            synth_text += "\n" + text
            for m in _VHDL_ENTITY_RX.finditer(text):
                nm = m.group(1)
                if nm not in declared:
                    declared.append(nm)
                    declared_files[nm] = rel
            continue
        here: List[str] = []
        for m in _MODULE_DECL_RX.finditer(text):
            nm = m.group(1).lstrip("\\")
            here.append(nm)
            if nm not in declared:
                declared.append(nm)
                declared_files[nm] = rel
        # Flag testbench modules in this file (and the file itself when *every*
        # module it declares is a bench → pure simulation file, not RTL source).
        benches = _testbench_modules(text, here)
        tb_modules |= benches
        if here and all(m in benches for m in here):
            tb_files.add(rel)
        else:
            synth_text += "\n" + text

    # Instantiation detection over the SYNTHESISABLE corpus only: a testbench
    # instantiates the DUT, so counting its instantiations would (wrongly) mark
    # the real top as "instantiated" and drop it from the candidates (issue #1).
    for nm in declared:
        inst_rx = re.compile(
            r"\b" + re.escape(nm) + r"\b\s*(#\s*\(.*?\))?\s+[A-Za-z_][A-Za-z0-9_$]*\s*\(",
            re.S,
        )
        for m in inst_rx.finditer(synth_text):
            # Exclude the declaration site (preceded by the `module` keyword).
            pre = synth_text[max(0, m.start() - 12):m.start()]
            if re.search(r"\bmodule\s*$", pre):
                continue
            instantiated.add(nm)
            break

    # Top candidate = declared, never instantiated, AND not a testbench. (A bench
    # is "never instantiated" by definition, so without this filter it would be
    # the prime — wrong — top guess. This is issue #1.)
    top_candidates = [m for m in declared
                      if m not in instantiated and m not in tb_modules]
    top = _pick_top(top_candidates, declared, d.name, tb_modules)
    clock_port = _detect_clock_port(combined, top) if top else None
    # VERILOG_FILES must exclude pure-testbench files (synthesis can't take them).
    synth_verilog = [p for p in verilog if p not in tb_files]
    return {
        "design_dir": str(d),
        "verilog": synth_verilog,
        "all_verilog": verilog,
        "vhdl": vhdl,
        "modules": declared,
        "module_files": declared_files,
        "instantiated": sorted(instantiated),
        "testbench_modules": sorted(tb_modules),
        "testbench_files": sorted(tb_files),
        "top_candidates": top_candidates,
        "top": top,
        "clock_port": clock_port,
        "restricted": only is not None,
        "errors": errors,
    }


def _pick_top(candidates: List[str], declared: List[str], dirname: str,
              tb_modules: Optional[set] = None) -> Optional[str]:
    """Choose the single best top module from the never-instantiated, non-bench
    set. Testbench modules are excluded even from the last-resort fallback so a
    bench can never become the design top (issue #1)."""
    tb = tb_modules or set()
    synth_declared = [m for m in declared if m not in tb]
    if not synth_declared:
        return None
    if len(candidates) == 1:
        return candidates[0]
    pool = candidates or synth_declared
    # Prefer a module whose name matches the design folder.
    dl = dirname.lower()
    for m in pool:
        if m.lower() == dl:
            return m
    for m in pool:
        if dl and (m.lower() in dl or dl in m.lower()):
            return m
    # Otherwise the first never-instantiated module (declaration order), else
    # the last declared synthesisable module (often the wrapper in a 1-file design).
    return pool[0] if candidates else synth_declared[-1]


def suggest_config(
    design_dir: str | Path,
    *,
    pdk: Optional[str] = None,
    scl: Optional[str] = None,
    clock_period: Optional[float] = 10.0,
    only_files: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Build a suggested config dict from the design's RTL.

    *only_files* (the GUI's tick-marked sources) restricts top-module / source
    detection to exactly those files, so an unticked testbench is ignored.

    Returns ``{ok, config, meta}`` where ``meta`` explains each guess (so the UI
    can show *why*). ``config`` contains only verified-real variables and is the
    editable starting point — it is never written by this function.
    """
    scan = scan_sources(design_dir, only_files=only_files)
    if not scan["verilog"] and not scan["vhdl"]:
        return {
            "ok": False,
            "error": "no Verilog/SystemVerilog/VHDL sources found in this folder",
            "meta": scan,
        }
    top = scan["top"]
    cfg: Dict[str, Any] = {}
    if top:
        cfg["DESIGN_NAME"] = top
    # Explicit, design-dir-relative paths via the dir:: prefix (resolves relative
    # to the config dir in both local and container runs; no host-absolute paths).
    if scan["verilog"]:
        cfg["VERILOG_FILES"] = ["dir::" + p for p in scan["verilog"]]
    if scan["vhdl"]:
        cfg["VHDL_FILES"] = ["dir::" + p for p in scan["vhdl"]]
    if scan["clock_port"]:
        cfg["CLOCK_PORT"] = scan["clock_port"]
        if clock_period is not None:
            cfg["CLOCK_PERIOD"] = float(clock_period)
    if pdk:
        cfg["PDK"] = pdk
    if scl:
        cfg["STD_CELL_LIBRARY"] = scl

    notes: List[str] = []
    if top:
        if len(scan["top_candidates"]) > 1:
            notes.append(
                f"Multiple top candidates ({', '.join(scan['top_candidates'])}); "
                f"picked '{top}'. Change DESIGN_NAME if that's wrong."
            )
        elif not scan["top_candidates"]:
            notes.append(
                f"Every module is instantiated by another (no clear top); "
                f"guessed '{top}'."
            )
    else:
        notes.append("Could not detect a top module — set DESIGN_NAME manually.")
    if scan["testbench_files"]:
        notes.append(
            "Excluded testbench file(s) from synthesis sources: "
            + ", ".join(scan["testbench_files"]) +
            ". Benches belong in verify/ and feed simulation, not the flow."
        )
    elif scan["testbench_modules"]:
        notes.append(
            "Ignored testbench module(s) when picking the top: "
            + ", ".join(scan["testbench_modules"]) + "."
        )
    if scan.get("restricted"):
        notes.append("Analysed only the files you ticked in the source list.")
    if not scan["clock_port"]:
        notes.append(
            "No clock port detected. If the design is combinational, leave "
            "CLOCK_PORT unset; otherwise add CLOCK_PORT/CLOCK_PERIOD."
        )
    meta = {
        "top": top,
        "top_candidates": scan["top_candidates"],
        "modules": scan["modules"],
        "clock_port": scan["clock_port"],
        "verilog_count": len(scan["verilog"]),
        "vhdl_count": len(scan["vhdl"]),
        "testbench_files": scan["testbench_files"],
        "testbench_modules": scan["testbench_modules"],
        "restricted": scan.get("restricted", False),
        "notes": notes,
    }
    return {"ok": True, "config": _validated(cfg), "meta": meta}


def _validated(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Drop any key that isn't a real LibreLane variable (defence in depth so a
    future edit here can't emit a hallucinated var). Falls back to the static
    allow-list when the registry can't be loaded."""
    valid = set(_EMIT_VARS)
    try:
        from . import introspect

        names = set()
        for v in introspect.list_variables():
            n = v.get("name") if isinstance(v, dict) else getattr(v, "name", None)
            if n:
                names.add(n)
        if names:
            valid &= names | {"VERILOG_FILES", "DESIGN_NAME"}  # always allow core
    except Exception:
        pass
    return {k: v for k, v in cfg.items() if k in valid}


def write_config(
    design_dir: str | Path,
    config: Dict[str, Any],
    *,
    fmt: str = "json",
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Write *config* into *design_dir* as ``config.<fmt>`` (json or yaml).

    Confined to *design_dir*; refuses to clobber an existing config unless
    *overwrite*. Only verified-real keys are written. Returns
    ``{ok, path}`` or ``{ok: False, error}``. Never raises.
    """
    d = Path(design_dir).expanduser().resolve()
    if not d.is_dir():
        return {"ok": False, "error": "design directory not found"}
    fmt = (fmt or "json").lower()
    if fmt in ("yml", "yaml"):
        fname = "config.yaml"
    elif fmt == "json":
        fname = "config.json"
    else:
        return {"ok": False, "error": f"unsupported format '{fmt}'"}
    target = (d / fname).resolve()
    try:
        target.relative_to(d)
    except ValueError:  # pragma: no cover - defence in depth
        return {"ok": False, "error": "refusing to write outside the design dir"}
    if target.exists() and not overwrite:
        return {"ok": False, "error": f"{fname} already exists (set overwrite to replace it)"}
    clean = _validated(dict(config or {}))
    if not clean.get("DESIGN_NAME"):
        return {"ok": False, "error": "DESIGN_NAME is required"}
    try:
        if fname == "config.json":
            text = json.dumps(clean, indent=2) + "\n"
        else:
            text = _to_yaml(clean)
        target.write_text(text, encoding="utf-8")
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    return {"ok": True, "path": str(target), "config": clean}


def _to_yaml(cfg: Dict[str, Any]) -> str:
    """Tiny YAML emitter for the flat config dict (scalars + string lists).

    LibreLane already depends on a YAML parser, but the GUI's moat forbids
    importing third-party libs in the controller, so we hand-emit the simple
    shape we produce here (no nesting, no anchors)."""
    lines: List[str] = []
    for k, v in cfg.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {json.dumps(item)}")
        elif isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {json.dumps(v)}")
    return "\n".join(lines) + "\n"
