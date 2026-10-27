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
"""Where hard macros come from, and whether one is wired up right.

Three sources, matching how people actually get a macro:

* **The PDK.** sky130, gf180mcu and IHP all ship ready SRAM blocks under
  ``libs.ref`` (``sky130_sram_macros``, ``gf180mcu_fd_ip_sram``, ``sg13g2_sram``).
  They are referenced in place with ``pdk_dir::`` paths, so nothing is copied
  and the config stays portable.
* **Another LanEx project.** The hierarchical flow: harden a block on its own,
  then drop its finished run (``final/gds``, ``lef``, ``nl``, ``spef``, ``lib``)
  into the parent. The views are copied, so deleting the old run can't break
  the parent.
* **Files** someone hands you (uploaded through :mod:`custommacros`).

And the checks that catch the usual first-macro failures before a 20-minute
run does: the module is never instantiated, the instance name is wrong (the
flattened path is ``u_core.u_sram``), the behavioural model is also in the
design's sources (so synthesis builds the SRAM out of flip-flops), or the
macro's power pins are not hooked to the grid.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import celllib

_SKIP_DIR = re.compile(r"(_sc_|stdcell|_pr$|_pr_|_io$|_io_|_ef_io|_osu_|_ml_)", re.I)


# --------------------------------------------------------------------------- #
# LEF pins -> buses, power, instantiation template
# --------------------------------------------------------------------------- #
_BIT_RX = re.compile(r"^(.*?)\[(\d+)\]$")


def group_pins(pins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse ``din0[0]..din0[31]`` into one bus ``din0[31:0]``. Keeps LEF order."""
    out: List[Dict[str, Any]] = []
    buses: Dict[str, Dict[str, Any]] = {}
    for p in pins:
        m = _BIT_RX.match(p["name"])
        if m:
            base, bit = m.group(1), int(m.group(2))
            b = buses.get(base)
            if b is None:
                b = buses[base] = {"name": base, "dir": p.get("dir") or "", "use": p.get("use") or "signal",
                                   "lo": bit, "hi": bit, "bus": True}
                out.append(b)
            b["lo"], b["hi"] = min(b["lo"], bit), max(b["hi"], bit)
        else:
            out.append({"name": p["name"], "dir": p.get("dir") or "", "use": p.get("use") or "signal",
                        "bus": False})
    for b in out:
        b["width"] = (b["hi"] - b["lo"] + 1) if b["bus"] else 1
    return out


def power_pins(pins: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    pw = [p["name"] for p in pins if (p.get("use") or "") == "power"]
    gd = [p["name"] for p in pins if (p.get("use") or "") == "ground"]
    return pw, gd


def instantiation(module: str, inst: str, pins: List[Dict[str, Any]]) -> str:
    """A ready-to-paste instance with power pins behind ``USE_POWER_PINS`` (what
    LibreLane's docs ask for) and each signal commented with its direction."""
    grouped = group_pins(pins)
    pw = [p for p in grouped if p["use"] in ("power", "ground")]
    sig = [p for p in grouped if p["use"] not in ("power", "ground")]
    w = max([len(p["name"]) for p in grouped] + [4])
    lines = [f"{module} {inst} ("]
    if pw:
        lines.append("`ifdef USE_POWER_PINS")
        for p in pw:
            lines.append(f"    .{p['name'].ljust(w)} ({p['name']}),")
        lines.append("`endif")
    for k, p in enumerate(sig):
        rng = f" [{p['hi']}:{p['lo']}]" if p["bus"] else ""
        d = (p["dir"] or "inout").replace("input", "input ").replace("output", "output")
        comma = "," if k < len(sig) - 1 else ""
        lines.append(f"    .{p['name'].ljust(w)} (){comma}  // {d.strip()}{rng}")
    if not sig and pw:
        lines[-2] = lines[-2].rstrip(",")
    lines.append(");")
    return "\n".join(lines)


def _capacity(name: str, grouped: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Words x bits of a memory, from its address and data buses (falls back to
    the ``NxM`` in its name)."""
    sig = [p for p in grouped if p["use"] not in ("power", "ground")]
    addr = [p for p in sig if p["bus"] and re.search(r"addr|^a$|_a$|^adr|_addr", p["name"], re.I) and p["dir"] == "input"]
    data = [p for p in sig if p["bus"] and re.search(r"dout|^q$|_q$|dout0|rdata|_dout", p["name"], re.I)]
    words = 2 ** addr[0]["width"] if addr else None
    bits = data[0]["width"] if data else None
    m = re.search(r"(\d+)x(\d+)", name)
    if (words is None or bits is None) and m:
        a, b = int(m.group(1)), int(m.group(2))
        words, bits = (max(a, b), min(a, b)) if words is None and bits is None else (words or a, bits or b)
    ports = None
    pm = re.search(r"(\d+rw\d*r?|\dP)(?:_|$)", name, re.I)
    if pm:
        ports = pm.group(1)
    kbits = (words * bits / 1024) if words and bits else None
    return {"words": words, "bits": bits, "kbits": kbits, "ports": ports}


# --------------------------------------------------------------------------- #
# PDK catalog
# --------------------------------------------------------------------------- #
def _view_files(lib_dir: Path, stem: str) -> Dict[str, Any]:
    """The files of one macro inside a PDK ``libs.ref/<ip>`` dir."""
    def find(sub: str, exts: Tuple[str, ...]) -> List[Path]:
        d = lib_dir / sub
        if not d.is_dir():
            return []
        out = []
        for p in sorted(d.iterdir()):
            if p.is_file() and p.name.lower().endswith(exts) and (p.name.startswith(stem + ".") or p.name.startswith(stem + "_") or p.stem == stem):
                out.append(p)
        return out
    views: Dict[str, Any] = {}
    gds = find("gds", (".gds", ".gds.gz"))
    if gds:
        views["gds"] = gds[0]
    lef = find("lef", (".lef",))
    if lef:
        views["lef"] = lef[0]
    libs = find("lib", (".lib",))
    if libs:
        views["libs"] = libs
    vh = find("verilog", (".v",))
    if vh:
        views["vh"] = vh[0]
    sp = find("spice", (".spice", ".sp", ".cir")) or find("cdl", (".cdl",))
    if sp:
        views["spice"] = sp[0]
    return views


def _typical_lib(libs: List[Path], scl_lib: Optional[str]) -> Optional[Path]:
    """The macro lib closest to the SCL's typical corner (TT, nominal voltage)."""
    if not libs:
        return None
    volt = None
    if scl_lib:
        m = re.search(r"(\d)v(\d+)", scl_lib)
        if m:
            volt = (m.group(1), m.group(2)[:1])
    def score(p: Path) -> Tuple[int, int, int]:
        n = p.name.lower()
        tt = 0 if re.search(r"(^|_)(tt|typ)", n) else 1
        v = 1
        if volt:
            if re.search(volt[0] + r"[pv]" + volt[1], n):
                v = 0
        t = 0 if re.search(r"(25c|025c|_25_)", n) else 1
        return (tt, v, t)
    return sorted(libs, key=score)[0]


def catalog(pdk: str, scl: Optional[str] = None) -> Dict[str, Any]:
    """Hard macros the installed *pdk* ships (SRAMs, mostly), with size and
    capacity so a beginner can pick by "how much memory"."""
    try:
        d = celllib.pdk_dir(pdk)
        if d is None:
            return {"ok": False, "error": f"{pdk or 'This PDK'} is not installed.", "macros": []}
        scl_lib = None
        if scl:
            lp = celllib._main_lib(pdk, scl)
            scl_lib = lp.name if lp else None
        out: List[Dict[str, Any]] = []
        for lib_dir in sorted((d / "libs.ref").iterdir()):
            if not lib_dir.is_dir() or _SKIP_DIR.search(lib_dir.name):
                continue
            lef_dir = lib_dir / "lef"
            if not lef_dir.is_dir():
                continue
            for lef in sorted(lef_dir.glob("*.lef")):
                try:
                    parsed = celllib.parse_lef(lef.read_text(encoding="utf-8", errors="replace"), shapes=False)
                except OSError:
                    continue
                for name, m in parsed["macros"].items():
                    if not str(m.get("class", "")).upper().startswith("BLOCK"):
                        continue
                    views = _view_files(lib_dir, lef.stem)
                    if "gds" not in views:
                        continue
                    grouped = group_pins(m["pins"])
                    pw, gd = power_pins(m["pins"])
                    lib = _typical_lib(views.get("libs", []), scl_lib)
                    rel = lambda p: "pdk_dir::" + str(p.relative_to(d)).replace("\\", "/")
                    out.append({
                        "name": name, "library": lib_dir.name,
                        "w": m.get("w"), "h": m.get("h"),
                        "capacity": _capacity(name, grouped),
                        "pins": len([p for p in grouped if p["use"] not in ("power", "ground")]),
                        "power": {"vdd": pw, "gnd": gd},
                        "views": {
                            "gds": rel(views["gds"]), "lef": rel(views["lef"]) if "lef" in views else rel(lef),
                            **({"lib": rel(lib)} if lib else {}),
                            **({"vh": rel(views["vh"])} if "vh" in views else {}),
                            **({"spice": rel(views["spice"])} if "spice" in views else {}),
                        },
                        "lib_corner": lib.stem if lib else None,
                        "corners": len(views.get("libs", [])),
                    })
        out.sort(key=lambda x: (x["library"], (x["capacity"].get("kbits") or 0), x["name"]))
        return {"ok": True, "pdk": pdk, "macros": out}
    except Exception as ex:
        return {"ok": False, "error": f"could not read the PDK's macros: {ex}", "macros": []}


def resolve_view(path: str, design_dir: Optional[str], pdk: Optional[str]) -> Optional[Path]:
    """A ``dir::`` / ``pdk_dir::`` / absolute view path → a file on disk."""
    if not path:
        return None
    if path.startswith("dir::"):
        return Path(design_dir or ".") / path[5:] if design_dir else None
    if path.startswith("pdk_dir::"):
        d = celllib.pdk_dir(pdk or "")
        return d / path[9:] if d else None
    return Path(path)


def macro_pins(lef_path: Path, name: str) -> Dict[str, Any]:
    """Pins (bus-collapsed), power pins, size and an instantiation template for
    *name* as defined in *lef_path*."""
    try:
        parsed = celllib.parse_lef(lef_path.read_text(encoding="utf-8", errors="replace"), shapes=True)
    except OSError as ex:
        return {"ok": False, "error": str(ex)}
    m = parsed["macros"].get(name)
    if m is None:
        names = list(parsed["macros"])
        if len(names) == 1:
            m = parsed["macros"][names[0]]
            name = names[0]
        else:
            return {"ok": False, "error": f"{lef_path.name} has no MACRO {name}", "macros": names}
    pw, gd = power_pins(m["pins"])
    # pin centres along the outline, for the floorplan sketch
    marks = []
    for p in m["pins"]:
        if not p["rects"]:
            continue
        r = max(p["rects"], key=lambda r: (r[3] - r[1]) * (r[4] - r[2]))
        marks.append({"name": p["name"], "use": p.get("use"), "x": (r[1] + r[3]) / 2, "y": (r[2] + r[4]) / 2})
    return {"ok": True, "name": name, "w": m.get("w"), "h": m.get("h"), "class": m.get("class"),
            "pins": group_pins(m["pins"]), "power": {"vdd": pw, "gnd": gd},
            "marks": marks[:400], "template": instantiation(name, "u_" + _short(name), m["pins"])}


def _short(name: str) -> str:
    n = name.lower()
    if "sram" in n or "ram" in n:
        return "sram"
    parts = [p for p in re.split(r"_+", n) if p]
    return parts[-1] if parts and not parts[-1].isdigit() else (parts[0] if parts else "macro")


# --------------------------------------------------------------------------- #
# Another LanEx project's run as a macro
# --------------------------------------------------------------------------- #
def _final_views(run_dir: Path) -> Dict[str, Any]:
    f = run_dir / "final"
    if not f.is_dir():
        return {}

    def first(sub: str, pats: Tuple[str, ...]) -> Optional[Path]:
        d = f / sub
        if not d.is_dir():
            return None
        for pat in pats:
            got = sorted(d.glob(pat))
            if got:
                return got[0]
        return None

    def cornered(sub: str, pat: str) -> Dict[str, Path]:
        d = f / sub
        out: Dict[str, Path] = {}
        if not d.is_dir():
            return out
        for c in sorted(d.iterdir()):
            if c.is_dir():
                got = sorted(c.glob(pat))
                if got:
                    out[c.name] = got[0]
            elif c.is_file() and c.name.endswith(pat.lstrip("*")):
                out["*"] = c
        return out
    v: Dict[str, Any] = {}
    g = first("gds", ("*.gds", "*.gds.gz")) or first("klayout_gds", ("*.gds",))
    if g:
        v["gds"] = g
    lef = first("lef", ("*.lef",))
    if lef:
        v["lef"] = lef
    nl = first("nl", ("*.nl.v", "*.v"))
    if nl:
        v["nl"] = nl
    pnl = first("pnl", ("*.pnl.v", "*.v"))
    if pnl:
        v["pnl"] = pnl
    spef = cornered("spef", "*.spef")
    if spef:
        v["spef"] = spef
    lib = cornered("lib", "*.lib")
    if lib:
        v["lib"] = lib
    return v


def project_sources(exclude_dir: Optional[str] = None) -> Dict[str, Any]:
    """Every known project with a finished run that produced GDS + LEF — the
    blocks that can be dropped into another design as a macro."""
    try:
        from . import designs
    except Exception as ex:
        return {"ok": False, "error": str(ex), "projects": []}
    ex_res = None
    try:
        ex_res = str(Path(exclude_dir).resolve()) if exclude_dir else None
    except OSError:
        ex_res = None
    out = []
    for d in designs.list_designs():
        try:
            dres = str(Path(d).resolve())
        except OSError:
            continue
        if ex_res and dres == ex_res:
            continue
        # A lean walk, not history.list_runs: summarising every run (metrics,
        # step dirs) takes seconds per project on a Windows-mounted folder.
        try:
            run_dirs = sorted((p for p in (Path(d) / "runs").iterdir() if p.is_dir() and not p.name.startswith(".")),
                              key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            run_dirs = []
        usable = []
        for rd in run_dirs:
            if len(usable) >= 8:
                break
            v = _final_views(rd)
            if "gds" not in v or "lef" not in v:
                continue
            meta = _run_meta(rd)
            usable.append({
                "tag": rd.name, "success": (rd / "final" / "metrics.json").is_file(),
                "pdk": meta.get("PDK"), "scl": meta.get("STD_CELL_LIBRARY"),
                "when": _mtime_iso(rd),
                "views": sorted(v.keys()),
                "module": meta.get("DESIGN_NAME") or Path(v["lef"]).stem,
            })
        if usable:
            out.append({"design_dir": d, "name": Path(d).name, "runs": usable[:8]})
    return {"ok": True, "projects": out}


def _run_meta(run_dir: Path) -> Dict[str, Any]:
    import json
    for f in (run_dir / "resolved.json", run_dir / "config.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return {k: doc.get(k) for k in ("DESIGN_NAME", "PDK", "STD_CELL_LIBRARY") if isinstance(doc.get(k), str)}
        except Exception:
            continue
    return {}


def _mtime_iso(p: Path) -> Optional[str]:
    import datetime
    try:
        return datetime.datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
    except OSError:
        return None


def _design_name(run_dir: Path) -> Optional[str]:
    import json
    for f in (run_dir / "resolved.json", run_dir / "config.json"):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and isinstance(doc.get("DESIGN_NAME"), str):
                return doc["DESIGN_NAME"]
        except Exception:
            continue
    return None


def run_views(design_dir: str, tag: str) -> Dict[str, Any]:
    """Absolute files of one run's final views (for the copy into the parent)."""
    if not tag or "/" in tag or "\\" in tag or tag.startswith("."):
        return {"ok": False, "error": "run not found"}
    rd = Path(design_dir) / "runs" / tag
    try:
        from . import history
        for r in history.list_runs(design_dir):
            if r.get("tag") == tag and r.get("run_dir"):
                rd = Path(r["run_dir"])
                break
    except Exception:
        pass
    if not rd.is_dir():
        return {"ok": False, "error": "run not found"}
    v = _final_views(rd)
    if "gds" not in v or "lef" not in v:
        return {"ok": False, "error": "that run has no final GDS and LEF (it may have stopped early)"}
    return {"ok": True, "module": _design_name(rd) or Path(v["lef"]).stem, "views": v, "run_dir": str(rd)}


# --------------------------------------------------------------------------- #
# RTL: is the macro instantiated, and under which flattened name?
# --------------------------------------------------------------------------- #
_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_MODULE = re.compile(r"\bmodule\s+([A-Za-z_][\w$]*)")
_KEYWORDS = {"module", "endmodule", "input", "output", "inout", "wire", "reg", "logic", "assign",
             "always", "always_ff", "always_comb", "always_latch", "initial", "if", "else", "for",
             "case", "begin", "end", "function", "task", "generate", "genvar", "parameter",
             "localparam", "integer", "typedef", "struct", "enum", "return", "posedge", "negedge",
             "or", "and", "not", "default", "import", "export", "interface", "modport", "bit", "int"}


def _modules(files: List[str]) -> Dict[str, Dict[str, Any]]:
    mods: Dict[str, Dict[str, Any]] = {}
    for f in files:
        try:
            t = _COMMENT.sub(" ", Path(f).read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for m in _MODULE.finditer(t):
            end = t.find("endmodule", m.end())
            body = t[m.end(): end if end != -1 else len(t)]
            mods.setdefault(m.group(1), {"file": f, "body": body})
    return mods


def _instances(body: str, wanted: set) -> List[Tuple[str, str]]:
    """``(module, instance)`` pairs in a module body, for modules in *wanted*."""
    out = []
    rx = re.compile(r"\b([A-Za-z_][\w$]*)\s*(#\s*\()?")
    i = 0
    while True:
        m = rx.search(body, i)
        if not m:
            break
        i = m.end()
        mod = m.group(1)
        if mod in _KEYWORDS or mod not in wanted:
            continue
        j = m.end()
        if m.group(2):                       # skip #( ... )
            depth = 1
            while j < len(body) and depth:
                if body[j] == "(":
                    depth += 1
                elif body[j] == ")":
                    depth -= 1
                j += 1
        im = re.match(r"\s*([A-Za-z_][\w$]*)\s*(\[[^\]]*\])?\s*\(", body[j:])
        if im:
            out.append((mod, im.group(1) + (im.group(2) or "").replace(" ", "")))
            i = j + im.end()
    return out


def find_instances(design_dir: str, top: Optional[str], macro_modules: List[str]) -> Dict[str, Any]:
    """Flattened instance paths of each macro module under *top*, and whether a
    macro's module is *defined* in the design's own sources (its behavioural
    model sneaking into synthesis)."""
    try:
        from . import configedit
        info = configedit.read_config(design_dir)
        data = info.get("data") or {}
        top = top or data.get("DESIGN_NAME")
        src = configedit.resolve_sources(design_dir, data)
        files = [f for f in src.get("files", []) if Path(f).suffix.lower() in (".v", ".sv", ".vh", ".svh")]
    except Exception as ex:
        return {"ok": False, "error": str(ex)}
    mods = _modules(files)
    wanted = set(mods) | set(macro_modules)
    found: Dict[str, List[str]] = {m: [] for m in macro_modules}
    seen_paths = 0

    def walk(mod: str, prefix: str, depth: int) -> None:
        nonlocal seen_paths
        if depth > 32 or seen_paths > 5000 or mod not in mods:
            return
        for sub, inst in _instances(mods[mod]["body"], wanted):
            seen_paths += 1
            path = prefix + inst
            if sub in found:
                found[sub].append(path)
            elif sub in mods:
                walk(sub, path + ".", depth + 1)
    if top:
        walk(top, "", 0)
    defined = {m: mods[m]["file"] for m in macro_modules if m in mods}
    return {"ok": True, "top": top, "top_found": bool(top and top in mods), "instances": found,
            "top_file": mods[top]["file"] if top and top in mods else None,
            "defined_in_sources": defined, "files": len(files)}
