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
"""The standard-cell library as the flow sees it (the Cells tab).

Everything here reads files the installed PDK already ships, with the stdlib
only:

* **Liberty** (``libs.ref/<scl>/lib/*.lib``): function, area, leakage, pin
  capacitance, flip-flop/latch behaviour and the NLDM delay tables. The typical
  corner is used, the same one LibreLane synthesises against (``LIB_SYNTH``).
* **LEF** (``libs.ref/<scl>/lef``): footprint size, site, pin shapes.
* **Verilog models**: the PDK's one-line description of each cell
  (``* a21oi: 2-input AND into first input of 2-input NOR.``).
* **GDS** + the KLayout layer file: the real layout polygons of one cell.
* **The PDK's LibreLane config** (``libs.tech/{librelane,openlane}``): which
  cells the flow inserts by itself (fill, tap, tie, CTS buffers…) and which it
  will never use (the synthesis and PnR exclusion lists).

Parsed results are cached in memory keyed on (path, mtime, size), so the tab is
fast after the first open and picks up a PDK reinstall by itself. Nothing here
raises to the caller: each public function returns ``{ok: False, error}``.
"""
from __future__ import annotations

import fnmatch
import math
import os
import re
import struct
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

_LOCK = threading.Lock()
_CACHE: "OrderedDict[Tuple[str, str], Tuple[Tuple[Any, ...], Any]]" = OrderedDict()
# Parsed files kept in memory, per kind, least recently used dropped first.
# A parsed Liberty library is ~100 MB and a cell GDS is read whole, so opening
# every library of three PDKs took the server from 50 MB to 600+ MB for good.
_CACHE_LIMITS = {"lib": 2, "gds": 2, "lef": 2, "desc": 4}
_CACHE_LIMIT_DEFAULT = 8


def _stamp(paths: Iterable[Path]) -> Tuple[Any, ...]:
    out = []
    for p in paths:
        try:
            st = p.stat()
            out.append((str(p), st.st_mtime_ns, st.st_size))
        except OSError:
            out.append((str(p), 0, 0))
    return tuple(out)


def _cached(kind: str, key: str, paths: List[Path], build):
    stamp = _stamp(paths)
    with _LOCK:
        hit = _CACHE.get((kind, key))
        if hit and hit[0] == stamp:
            _CACHE.move_to_end((kind, key))
            return hit[1]
    val = build(stamp) if getattr(build, "wants_stamp", False) else build()
    with _LOCK:
        _CACHE[(kind, key)] = (stamp, val)
        _CACHE.move_to_end((kind, key))
        limit = _CACHE_LIMITS.get(kind, _CACHE_LIMIT_DEFAULT)
        same = [k for k in _CACHE if k[0] == kind]
        for k in same[:max(0, len(same) - limit)]:
            del _CACHE[k]
    return val


# A parsed Liberty file is also kept on disk (LANEX_HOME/cache/celllib), as
# the compact form the tab uses (cell summaries + timing arcs), so a restarted
# server opens the Cells tab without re-reading a 100 MB library. Keyed by the
# file's path, mtime and size, the Python version and this format version.
_DISK_FORMAT = 1


def _disk_path(kind: str, stamp: Tuple[Any, ...]) -> Optional[Path]:
    try:
        import hashlib
        import sys
        from . import platform_env
        key = repr((kind, stamp, sys.version_info[:3], _DISK_FORMAT)).encode("utf-8")
        return platform_env.home() / "cache" / "celllib" / (hashlib.sha256(key).hexdigest()[:32] + ".marshal")
    except Exception:
        return None


def _disk_load(kind: str, stamp: Tuple[Any, ...]) -> Any:
    import marshal
    p = _disk_path(kind, stamp)
    if p is None or not p.is_file():
        return None
    try:
        with open(p, "rb") as f:
            return marshal.load(f)
    except Exception:
        return None


def _disk_store(kind: str, stamp: Tuple[Any, ...], value: Any) -> None:
    import marshal
    p = _disk_path(kind, stamp)
    if p is None:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Only the newest few libraries are kept on disk.
        olds = sorted(p.parent.glob("*.marshal"), key=lambda q: q.stat().st_mtime)
        for q in olds[:max(0, len(olds) - 15)]:
            q.unlink(missing_ok=True)
        tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
        with open(tmp, "wb") as f:
            marshal.dump(value, f)
        os.replace(tmp, p)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Locating the library on disk
# --------------------------------------------------------------------------- #
def _pdk_roots() -> List[Path]:
    roots: List[Path] = []
    try:
        from . import pdk as _pdk
        roots.extend(_pdk._candidate_pdk_roots())
    except Exception:
        pass
    env = os.environ.get("PDK_ROOT")
    if env:
        roots.append(Path(env))
    seen, out = set(), []
    for r in roots:
        if str(r) not in seen:
            seen.add(str(r))
            out.append(r)
    return out


def pdk_dir(pdk: str) -> Optional[Path]:
    """``<PDK_ROOT>/<pdk>`` for an installed PDK variant (sky130A, gf180mcuD…)."""
    if not pdk or "/" in pdk or "\\" in pdk or pdk.startswith("."):
        return None
    for root in _pdk_roots():
        d = root / pdk
        if (d / "libs.ref").is_dir():
            return d
    return None


def scl_dir(pdk: str, scl: str) -> Optional[Path]:
    d = pdk_dir(pdk)
    if d is None or not scl or "/" in scl or "\\" in scl or scl.startswith("."):
        return None
    s = d / "libs.ref" / scl
    return s if s.is_dir() else None


def _tech_dir(pdk: str, scl: Optional[str] = None) -> Optional[Path]:
    """The PDK's LibreLane config dir (``libs.tech/librelane``, else the legacy
    ``libs.tech/openlane``), or the SCL sub-dir of it when *scl* is given."""
    d = pdk_dir(pdk)
    if d is None:
        return None
    for name in ("librelane", "openlane"):
        t = d / "libs.tech" / name
        if scl:
            t = t / scl
        if (t / "config.tcl").is_file():
            return t
    return None


# --------------------------------------------------------------------------- #
# The PDK's LibreLane config (Tcl ``set ::env(KEY) value`` lines)
# --------------------------------------------------------------------------- #
_SET_RX = re.compile(r"^\s*set\s+(::env\((\w+)\)|\w+)\s+(.+?)\s*(?:;\s*#.*)?$")
_ENV_REF = re.compile(r"\$(?:::env\((\w+)\)|\{::env\((\w+)\)\}|\{(\w+)\}|(\w+))")


def _tcl_value(raw: str, env: Dict[str, str], local: Dict[str, str]) -> str:
    v = raw.strip()
    if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "{" and v[-1] == "}")):
        v = v[1:-1]

    def sub(m: "re.Match[str]") -> str:
        if m.group(1) or m.group(2):
            return env.get(m.group(1) or m.group(2), "")
        return local.get(m.group(3) or m.group(4), "")
    return _ENV_REF.sub(sub, v)


def _parse_tcl_env(path: Path, env: Dict[str, str]) -> Dict[str, str]:
    """Best-effort: every top-level ``set ::env(K) V``; later wins, as in Tcl.
    Lines inside ``if`` blocks are read too (the PDK configs only branch on
    things like the optional OPT library, which do not change cell roles)."""
    out: Dict[str, str] = {}
    local: Dict[str, str] = {"current_folder": str(path.parent)}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        m = _SET_RX.match(line)
        if not m:
            continue
        key, raw = m.group(2), m.group(3)
        if "[" in raw and "]" in raw and not raw.strip().startswith('"'):
            continue      # a Tcl command substitution we can't evaluate
        merged = dict(env)
        merged.update(out)
        val = _tcl_value(raw, merged, local)
        if key:
            out[key] = val
        else:
            local[m.group(1)] = val
    return out


def pdk_config(pdk: str, scl: str) -> Dict[str, Any]:
    """The PDK+SCL LibreLane variables, migrated to current LibreLane names
    (``FP_WELLTAP_CELL`` → ``WELLTAP_CELL`` etc.) when LibreLane is importable."""
    d = pdk_dir(pdk)
    top = _tech_dir(pdk)
    sub = _tech_dir(pdk, scl)
    if d is None or top is None:
        return {}
    files = [top / "config.tcl"] + ([sub / "config.tcl"] if sub else [])

    def build() -> Dict[str, Any]:
        base = {"PDK_ROOT": str(d.parent), "PDK": pdk, "STD_CELL_LIBRARY": scl,
                "PDKPATH": str(d)}
        env: Dict[str, str] = {}
        for f in files:
            merged = dict(base)
            merged.update(env)
            env.update(_parse_tcl_env(f, merged))
        cfg: Dict[str, Any] = dict(env)
        try:
            from librelane.config.pdk_compat import migrate_old_config  # type: ignore
            cfg = migrate_old_config(cfg)
        except Exception:
            # Hand-migrate the few names the Cells tab reads.
            ren = {"FP_WELLTAP_CELL": "WELLTAP_CELL", "FP_ENDCAP_CELL": "ENDCAP_CELL",
                   "FILL_CELL": "FILL_CELLS", "DECAP_CELL": "DECAP_CELLS",
                   "CTS_CLK_BUFFER_LIST": "CTS_CLK_BUFFERS",
                   "NO_SYNTH_CELL_LIST": "SYNTH_EXCLUDED_CELL_FILE",
                   "DRC_EXCLUDE_CELL_LIST": "PNR_EXCLUDED_CELL_FILE"}
            for old, new in ren.items():
                if old in cfg and new not in cfg:
                    cfg[new] = cfg.pop(old)
            for old, new in (("SYNTH_TIEHI_PORT", "SYNTH_TIEHI_CELL"),
                             ("SYNTH_TIELO_PORT", "SYNTH_TIELO_CELL"),
                             ("SYNTH_MIN_BUF_PORT", "SYNTH_BUFFER_CELL")):
                if old in cfg:
                    cfg[new] = "/".join(str(cfg.pop(old)).split())
            if "SYNTH_DRIVING_CELL_PIN" in cfg and "SYNTH_DRIVING_CELL" in cfg:
                cfg["SYNTH_DRIVING_CELL"] = f"{cfg['SYNTH_DRIVING_CELL']}/{cfg.pop('SYNTH_DRIVING_CELL_PIN')}"
            if "DIODE_CELL_PIN" in cfg and "DIODE_CELL" in cfg:
                cfg["DIODE_CELL"] = f"{cfg['DIODE_CELL']}/{cfg.pop('DIODE_CELL_PIN')}"
        return cfg

    return _cached("pdkcfg", f"{pdk}/{scl}", files, build)


def _list_file(path: Optional[str]) -> List[str]:
    if not path:
        return []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        ln = ln.split("#", 1)[0].strip()
        for tok in ln.split():
            if tok not in out:
                out.append(tok)
    return out


def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [x for x in str(v).replace(",", " ").split() if x]


def matches(name: str, patterns: Iterable[str]) -> List[str]:
    """The patterns (LibreLane wildcards, ``fnmatch`` semantics) that hit *name*."""
    return [p for p in patterns if fnmatch.fnmatchcase(name, p)]


# --------------------------------------------------------------------------- #
# Liberty
# --------------------------------------------------------------------------- #
_TOK = re.compile(r'/\*.*?\*/|"(?:[^"\\]|\\.)*"|\\\r?\n|[(){}:;,]|[^\s(){}:;,"]+', re.S)


def _parse_liberty_block(text: str) -> List[Dict[str, Any]]:
    """Parse Liberty text into a list of nodes.

    A group is ``{"g": name, "a": [args], "c": [children]}``; a simple attribute
    ``{"k": name, "v": value}``; a complex attribute ``{"k": name, "args": [...]}``.
    Quotes are stripped from values."""
    toks = [t for t in _TOK.findall(text) if not t.startswith("/*") and not t.startswith("\\")]
    pos = 0
    n = len(toks)

    def unq(t: str) -> str:
        return t[1:-1] if len(t) >= 2 and t[0] == '"' and t[-1] == '"' else t

    def parse_list(end: str) -> List[Dict[str, Any]]:
        nonlocal pos
        out: List[Dict[str, Any]] = []
        while pos < n:
            t = toks[pos]
            if t == end:
                pos += 1
                return out
            if t in (";", ","):
                pos += 1
                continue
            name = t
            pos += 1
            if pos >= n:
                break
            nxt = toks[pos]
            if nxt == ":":
                pos += 1
                vals = []
                while pos < n and toks[pos] not in (";", "}"):
                    vals.append(unq(toks[pos]))
                    pos += 1
                if pos < n and toks[pos] == ";":
                    pos += 1
                out.append({"k": name, "v": " ".join(vals)})
            elif nxt == "(":
                pos += 1
                args = []
                while pos < n and toks[pos] != ")":
                    if toks[pos] != ",":
                        args.append(unq(toks[pos]))
                    pos += 1
                pos += 1  # ")"
                if pos < n and toks[pos] == "{":
                    pos += 1
                    out.append({"g": name, "a": args, "c": parse_list("}")})
                else:
                    if pos < n and toks[pos] == ";":
                        pos += 1
                    out.append({"k": name, "args": args})
            else:
                # stray token; skip
                continue
        return out

    return parse_list("\0")


def _attr(node: Dict[str, Any], key: str, default: Any = None) -> Any:
    for c in node.get("c", []):
        if c.get("k") == key and "v" in c:
            return c["v"]
    return default


def _cattr(node: Dict[str, Any], key: str) -> Optional[List[str]]:
    for c in node.get("c", []):
        if c.get("k") == key and "args" in c:
            return c["args"]
    return None


def _groups(node: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
    return [c for c in node.get("c", []) if c.get("g") == name]


def _num(v: Any) -> Optional[float]:
    try:
        f = float(str(v).strip())
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _floats(s: str) -> List[float]:
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?", s or "")]


def _table(node: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not node:
        return None
    i1 = _cattr(node, "index_1")
    i2 = _cattr(node, "index_2")
    vals = _cattr(node, "values")
    if vals is None:
        return None
    rows = [_floats(v) for v in vals]
    return {"template": (node.get("a") or [""])[0],
            "index_1": _floats(" ".join(i1)) if i1 else [],
            "index_2": _floats(" ".join(i2)) if i2 else [],
            "values": rows}


_CELL_START = re.compile(r'^\s*cell\s*\(\s*"?([^")\s]+)"?\s*\)\s*\{', re.M)


def _split_cells(text: str) -> Tuple[str, List[Tuple[str, int, int]]]:
    """Return (library header text, [(cell, start, end)]) by brace matching.
    Quoted strings and comments may contain braces; they're skipped."""
    spans: List[Tuple[str, int, int]] = []
    first = None
    for m in _CELL_START.finditer(text):
        start = m.start()
        if spans and start < spans[-1][2]:
            continue
        if first is None:
            first = start
        i = m.end()
        depth = 1
        L = len(text)
        while i < L and depth:
            ch = text[i]
            if ch == '"':
                j = text.find('"', i + 1)
                while j != -1 and text[j - 1] == "\\":
                    j = text.find('"', j + 1)
                i = (j + 1) if j != -1 else L
                continue
            if ch == "/" and i + 1 < L and text[i + 1] == "*":
                j = text.find("*/", i + 2)
                i = (j + 2) if j != -1 else L
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            i += 1
        spans.append((m.group(1), start, i))
    header = text[: first] if first is not None else text
    return header, spans


def _units(header: str) -> Dict[str, Any]:
    def grab(key: str) -> Optional[str]:
        m = re.search(r"\b" + key + r"\s*:\s*\"?([^\";]+)\"?\s*;", header)
        return m.group(1).strip() if m else None
    cap = re.search(r"capacitive_load_unit\s*\(\s*([\d.]+)\s*,\s*\"?(\w+)\"?\s*\)", header)
    return {
        "time": grab("time_unit") or "1ns",
        "leakage": grab("leakage_power_unit") or "1nW",
        "cap": (cap.group(1) + cap.group(2)) if cap else "1pf",
        "voltage": grab("nom_voltage"),
        "temperature": grab("nom_temperature"),
        "process": grab("nom_process"),
    }


def _scale(unit: str, kind: str) -> float:
    """Factor turning a value in *unit* into ps (time), fF (cap) or nW (power)."""
    m = re.match(r"\s*([\d.]+)?\s*([a-zA-Z]+)", unit or "")
    if not m:
        return 1.0
    mult = float(m.group(1) or 1)
    u = m.group(2).lower()
    tables = {
        "time": {"s": 1e12, "ms": 1e9, "us": 1e6, "ns": 1e3, "ps": 1.0, "fs": 1e-3},
        "cap": {"f": 1e15, "mf": 1e12, "uf": 1e9, "nf": 1e6, "pf": 1e3, "ff": 1.0},
        "leakage": {"w": 1e9, "mw": 1e6, "uw": 1e3, "nw": 1.0, "pw": 1e-3, "fw": 1e-6},
    }
    return mult * tables[kind].get(u, 1.0)


def _interp1(xs: List[float], ys: List[float], x: float) -> Optional[float]:
    if not xs or not ys or len(xs) != len(ys):
        return None
    if len(xs) == 1:
        return ys[0]
    if x <= xs[0]:
        i = 0
    elif x >= xs[-1]:
        i = len(xs) - 2
    else:
        i = max(0, min(len(xs) - 2, next(k for k in range(len(xs) - 1) if xs[k + 1] >= x)))
    x0, x1 = xs[i], xs[i + 1]
    if x1 == x0:
        return ys[i]
    return ys[i] + (ys[i + 1] - ys[i]) * (x - x0) / (x1 - x0)


def table_at(t: Optional[Dict[str, Any]], slew: float, load: float) -> Optional[float]:
    """Bilinear lookup of an NLDM table (index_1 = input slew, index_2 = load,
    the usual delay_template order). Extrapolates linearly at the edges, as STA does."""
    if not t or not t.get("values"):
        return None
    i1, i2, v = t["index_1"], t["index_2"], t["values"]
    if not i2:
        # one-dimensional table: decide which index it is by the template name
        row = v[0] if len(v) == 1 else [r[0] for r in v]
        return _interp1(i1, row, load if "load" in (t.get("template") or "") else slew)
    col = [_interp1(i2, r, load) for r in v]
    if any(c is None for c in col):
        return None
    return _interp1(i1, col, slew) if len(i1) == len(col) else col[0]


def _pin_info(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": (p.get("a") or [""])[0],
        "dir": _attr(p, "direction", ""),
        "cap": _num(_attr(p, "capacitance")),
        "function": _attr(p, "function"),
        "clock": str(_attr(p, "clock", "false")).lower() == "true",
        "three_state": _attr(p, "three_state"),
        "max_cap": _num(_attr(p, "max_capacitance")),
    }


def _seq_info(cell: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for kind in ("ff", "latch", "ff_bank", "latch_bank"):
        gs = _groups(cell, kind)
        if gs:
            g = gs[0]
            out = {"kind": "latch" if kind.startswith("latch") else "ff",
                   "state": g.get("a") or []}
            for key in ("clocked_on", "next_state", "clear", "preset", "enable", "data_in",
                        "clear_preset_var1", "clocked_on_also"):
                v = _attr(g, key)
                if v is not None:
                    out[key] = v
            return out
    return None


def _leak(cell: Dict[str, Any]) -> Optional[float]:
    """``cell_leakage_power``, else the mean of the per-state values (gf180 and
    IHP only ship the per-state table)."""
    v = _num(_attr(cell, "cell_leakage_power"))
    if v is not None:
        return v
    vals = [x for x in (_num(_attr(g, "value")) for g in _groups(cell, "leakage_power")) if x is not None]
    return sum(vals) / len(vals) if vals else None


def _cell_summary(name: str, cell: Dict[str, Any]) -> Dict[str, Any]:
    pins = [_pin_info(p) for p in _groups(cell, "pin")]
    for b in _groups(cell, "bus"):
        bp = _pin_info(b)
        bp["bus"] = True
        pins.append(bp)
    pg = [{"name": (g.get("a") or [""])[0], "type": _attr(g, "pg_type", "")} for g in _groups(cell, "pg_pin")]
    out = {
        "cell": name,
        "area": _num(_attr(cell, "area")),
        "leakage": _leak(cell),
        "footprint": _attr(cell, "cell_footprint"),
        "dont_use": str(_attr(cell, "dont_use", "false")).lower() == "true",
        "is_clock_gate": _attr(cell, "clock_gating_integrated_cell") is not None,
        "pins": pins,
        "pg_pins": pg,
    }
    seq = _seq_info(cell)
    if seq:
        out["seq"] = seq
    if _groups(cell, "statetable"):
        out["statetable"] = True
    return out


def _arcs(cell: Dict[str, Any]) -> List[Dict[str, Any]]:
    arcs = []
    for p in _groups(cell, "pin") + _groups(cell, "bus"):
        pname = (p.get("a") or [""])[0]
        for t in _groups(p, "timing"):
            def pick(n: str) -> Optional[Dict[str, Any]]:
                g = _groups(t, n)
                return _table(g[0]) if g else None
            arcs.append({
                "to": pname,
                "from": _attr(t, "related_pin", ""),
                "sense": _attr(t, "timing_sense"),
                "type": _attr(t, "timing_type", "combinational"),
                "when": _attr(t, "when"),
                "cell_rise": pick("cell_rise"),
                "cell_fall": pick("cell_fall"),
                "rise_transition": pick("rise_transition"),
                "fall_transition": pick("fall_transition"),
                "rise_constraint": pick("rise_constraint"),
                "fall_constraint": pick("fall_constraint"),
            })
    return arcs


def _delay_arcs(arcs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [a for a in arcs if (a.get("cell_rise") or a.get("cell_fall"))
            and a.get("type") in (None, "", "combinational", "rising_edge", "falling_edge",
                                  "combinational_rise", "combinational_fall",
                                  "three_state_enable", "three_state_disable",
                                  "clear", "preset")]


def _main_lib(pdk: str, scl: str) -> Optional[Path]:
    """The Liberty file LibreLane synthesises against (``LIB_SYNTH`` / the
    default corner), else the typical-looking one, else the first."""
    s = scl_dir(pdk, scl)
    if s is None or not (s / "lib").is_dir():
        return None
    libs = sorted(p for p in (s / "lib").glob("*.lib") if "ccsnoise" not in p.name and "pwrlkg" not in p.name)
    if not libs:
        return None
    cfg = pdk_config(pdk, scl)
    for key in ("LIB_SYNTH", "LIB_TYPICAL"):
        v = cfg.get(key)
        if isinstance(v, str) and v:
            p = Path(v.split()[0])
            if p.is_file():
                return p
    lib = cfg.get("LIB")
    if isinstance(lib, dict):
        dc = str(cfg.get("DEFAULT_CORNER") or "")
        for pat, files in lib.items():
            if dc and fnmatch.fnmatchcase(dc, pat):
                for f in _as_list(files):
                    if Path(f).is_file():
                        return Path(f)
    for tok in ("tt_025C", "typ_", "tt_", "typ"):
        for p in libs:
            if tok in p.name:
                return p
    return libs[0]


def _liberty(path: Path) -> Dict[str, Any]:
    """Parse a whole Liberty file into what the tab uses: units, a summary of
    each cell, its timing arcs and its per-state leakage. The full parse trees
    (power tables and all) are not kept. Cached in memory and on disk."""
    def build(stamp: Tuple[Any, ...]) -> Dict[str, Any]:
        hit = _disk_load("lib", stamp)
        if isinstance(hit, dict) and hit.get("path") == str(path):
            return hit
        text = path.read_text(encoding="utf-8", errors="replace")
        header, spans = _split_cells(text)
        units = _units(header)
        cells: Dict[str, Dict[str, Any]] = {}
        arcs: Dict[str, List[Dict[str, Any]]] = {}
        leaks: Dict[str, List[Dict[str, Any]]] = {}
        for name, a, b in spans:
            nodes = _parse_liberty_block(text[a:b])
            node = next((x for x in nodes if x.get("g") == "cell"), None)
            if node is None:
                continue
            cells[name] = _cell_summary(name, node)
            arcs[name] = _arcs(node)
            leaks[name] = [{"when": _attr(g, "when"), "value": v}
                           for g in _groups(node, "leakage_power")
                           for v in [_num(_attr(g, "value"))] if v is not None]
        out = {"units": units, "cells": cells, "arcs": arcs, "leaks": leaks, "path": str(path)}
        _disk_store("lib", stamp, out)
        return out
    build.wants_stamp = True  # type: ignore[attr-defined]
    return _cached("lib", str(path), [path], build)


# --------------------------------------------------------------------------- #
# LEF
# --------------------------------------------------------------------------- #
def _lef_files(pdk: str, scl: str) -> List[Path]:
    s = scl_dir(pdk, scl)
    if s is None or not (s / "lef").is_dir():
        return []
    return sorted(p for p in (s / "lef").glob("*.lef"))


def _tech_lef_files(pdk: str, scl: str) -> List[Path]:
    s = scl_dir(pdk, scl)
    if s is None:
        return []
    out = []
    for sub in ("techlef", "lef"):
        d = s / sub
        if d.is_dir():
            out.extend(sorted(p for p in d.glob("*.tlef")))
            out.extend(sorted(p for p in d.glob("*tech*.lef")))
    return out


def parse_lef(text: str, *, shapes: bool = True) -> Dict[str, Any]:
    """MACROs (class, size, site, pins with use/direction and rects, OBS) and
    SITEs from LEF text. Units are microns, as LEF geometry is."""
    macros: Dict[str, Dict[str, Any]] = {}
    sites: Dict[str, Dict[str, Any]] = {}
    lines = text.splitlines()
    i, n = 0, len(lines)
    cur: Optional[Dict[str, Any]] = None
    pin: Optional[Dict[str, Any]] = None
    in_obs = False
    in_port = False
    layer = ""
    site: Optional[Dict[str, Any]] = None
    while i < n:
        raw = lines[i].split("#", 1)[0]
        i += 1
        toks = raw.replace(";", " ; ").split()
        if not toks:
            continue
        k = toks[0].upper()
        if site is not None:
            if k == "SIZE" and len(toks) >= 4:
                site["w"], site["h"] = _num(toks[1]), _num(toks[3])
            elif k == "CLASS" and len(toks) >= 2:
                site["class"] = toks[1]
            elif k == "END":
                site = None
            continue
        if cur is None:
            if k == "PROPERTYDEFINITIONS":
                while i < n and not lines[i].strip().upper().startswith("END PROPERTYDEFINITIONS"):
                    i += 1
                i += 1
                continue
            if k == "MACRO" and len(toks) >= 2:
                cur = {"name": toks[1], "class": "", "w": None, "h": None, "site": None,
                       "origin": [0.0, 0.0], "pins": [], "obs": [], "symmetry": ""}
                macros[toks[1]] = cur
            elif k == "SITE" and len(toks) >= 2:
                site = {"name": toks[1]}
                sites[toks[1]] = site
            continue
        if pin is not None:
            if k == "END" and len(toks) >= 2 and toks[1] == pin["name"]:
                pin = None
                in_port = False
                continue
            if k == "DIRECTION" and len(toks) >= 2:
                pin["dir"] = toks[1].lower()
            elif k == "USE" and len(toks) >= 2:
                pin["use"] = toks[1].lower()
            elif k == "PORT":
                in_port = True
            elif k == "END" and in_port:
                in_port = False
            elif k == "LAYER" and len(toks) >= 2:
                layer = toks[1]
            elif k == "RECT" and shapes:
                vals = [v for v in toks[1:] if v != ";" and v.upper() != "MASK"]
                vals = [v for v in vals if re.match(r"^-?[\d.]+$", v)]
                if len(vals) >= 4:
                    pin["rects"].append([layer] + [float(v) for v in vals[-4:]])
            continue
        if in_obs:
            if k == "END":
                in_obs = False
            elif k == "LAYER" and len(toks) >= 2:
                layer = toks[1]
            elif k == "RECT" and shapes:
                vals = [v for v in toks[1:] if re.match(r"^-?[\d.]+$", v)]
                if len(vals) >= 4:
                    cur["obs"].append([layer] + [float(v) for v in vals[-4:]])
            continue
        if k == "END" and len(toks) >= 2 and toks[1] == cur["name"]:
            cur = None
        elif k == "CLASS" and len(toks) >= 2:
            cur["class"] = " ".join(t for t in toks[1:] if t != ";")
        elif k == "SIZE" and len(toks) >= 4:
            cur["w"], cur["h"] = _num(toks[1]), _num(toks[3])
        elif k == "ORIGIN" and len(toks) >= 3:
            cur["origin"] = [_num(toks[1]) or 0.0, _num(toks[2]) or 0.0]
        elif k == "SITE" and len(toks) >= 2:
            cur["site"] = toks[1]
        elif k == "SYMMETRY":
            cur["symmetry"] = " ".join(t for t in toks[1:] if t != ";")
        elif k == "PIN" and len(toks) >= 2:
            pin = {"name": toks[1], "dir": "", "use": "signal", "rects": []}
            cur["pins"].append(pin)
        elif k == "OBS":
            in_obs = True
    return {"macros": macros, "sites": sites}


def _lef(pdk: str, scl: str) -> Dict[str, Any]:
    files = _lef_files(pdk, scl) + _tech_lef_files(pdk, scl)

    def build() -> Dict[str, Any]:
        macros: Dict[str, Any] = {}
        sites: Dict[str, Any] = {}
        for f in files:
            try:
                got = parse_lef(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            for k, v in got["macros"].items():
                macros.setdefault(k, v)
            for k, v in got["sites"].items():
                if v.get("w") or k not in sites:
                    sites[k] = v
        return {"macros": macros, "sites": sites}
    return _cached("lef", f"{pdk}/{scl}", files, build)


# --------------------------------------------------------------------------- #
# Verilog model descriptions
# --------------------------------------------------------------------------- #
_DESC_RX = re.compile(r"^\s*\*\s*([A-Za-z0-9_]+):\s*(.+?)\s*$")


def _descriptions(pdk: str, scl: str) -> Dict[str, str]:
    s = scl_dir(pdk, scl)
    if s is None or not (s / "verilog").is_dir():
        return {}
    files = sorted(p for p in (s / "verilog").glob("*.v") if "blackbox" not in p.name and p.name != "primitives.v")

    def build() -> Dict[str, str]:
        out: Dict[str, str] = {}
        for f in files:
            try:
                with f.open("r", encoding="utf-8", errors="replace") as fh:
                    pending: Optional[Tuple[str, List[str], List[str]]] = None
                    for line in fh:
                        if pending is not None:
                            st = line.strip()
                            body = st.lstrip("*").strip() if st.startswith("*") and not st.startswith("*/") else None
                            if body is not None and not body.startswith(("Verilog", "WARNING")):
                                if re.match(r"^[A-Za-z_]\w*\s*=\s*\S", body):
                                    pending[2].append(re.sub(r"\s+", " ", body))
                                elif body and not pending[2] and len(pending[1]) < 3:
                                    pending[1].append(body)
                                continue
                            key, parts, forms = pending
                            if key not in out:
                                out[key] = " ".join(parts).strip()
                                if forms:
                                    out["=" + key] = forms
                            pending = None
                        m = _DESC_RX.match(line)
                        if m and m.group(1) not in out:
                            pending = (m.group(1), [m.group(2)], [])
            except OSError:
                continue
        return out
    return _cached("desc", f"{pdk}/{scl}", files, build)


# --------------------------------------------------------------------------- #
# Naming: library prefix, family (base) and drive strength
# --------------------------------------------------------------------------- #
def _common_prefix(names: List[str]) -> str:
    if not names:
        return ""
    p = os.path.commonprefix(names)
    # cut back to a separator so "sky130_fd_sc_hd__a" -> "sky130_fd_sc_hd__"
    for sep in ("__", "_"):
        k = p.rfind(sep)
        if k >= 0:
            return p[: k + len(sep)]
    return ""


def lib_prefix(names: List[str], scl: str) -> str:
    """The prefix most cell names share: ``sky130_fd_sc_hd__``, ``sg13g2_``…"""
    for cand in (scl + "__", scl + "_"):
        if names and sum(1 for n in names if n.startswith(cand)) * 2 >= len(names):
            return cand
    from collections import Counter
    heads = Counter(n[: n.rfind("__") + 2] for n in names if "__" in n)
    if heads:
        head, cnt = heads.most_common(1)[0]
        if cnt * 2 >= len(names):
            return head
    firsts = Counter(n.split("_", 1)[0] + "_" for n in names if "_" in n)
    if firsts:
        head, cnt = firsts.most_common(1)[0]
        if cnt * 2 >= len(names):
            return head
    return _common_prefix(names)


_DRIVE_RX = re.compile(r"^(.*?)_(\d+|lp\d*|m)$")


def split_name(name: str, prefix: str) -> Tuple[str, str]:
    """``(family, drive)`` — ``sky130_fd_sc_hd__a21oi_2`` → ``("a21oi", "2")``.
    The drive is "" for cells without a numeric suffix."""
    rest = name[len(prefix):] if prefix and name.startswith(prefix) else name
    # cells from a sister library inside this one (sky130_ef_sc_hd__decap_12)
    if "__" in rest:
        rest = rest[rest.rfind("__") + 2:]
    m = _DRIVE_RX.match(rest)
    if m:
        return m.group(1), m.group(2)
    return rest, ""


def _category(name: str, fam: str, s: Optional[Dict[str, Any]], lef_class: str) -> str:
    """Coarse category for the filter chips. Liberty decides first, names refine."""
    f = fam.lower()
    if re.search(r"(^|_)(fill|decap|tap|endcap|diode|antenna|fakediode|filler|corner)", f) or lef_class.upper().startswith(("ENDCAP", "CORE WELLTAP", "CORE ANTENNACELL", "CORE SPACER")):
        return "physical"
    if s is None:
        return "other"
    outs = [p for p in s["pins"] if p["dir"] == "output"]
    if s.get("is_clock_gate") or re.search(r"(^|_)s?dlclkp|icg", f):
        return "clock"
    if s.get("seq"):
        return "flipflop" if s["seq"]["kind"] == "ff" else "latch"
    if not outs:
        return "physical"
    if re.search(r"(^|_)(lpflow|lsbuf|isobuf|inputiso|lvlshift|ls_)", f):
        return "power"
    if any(p.get("three_state") for p in outs) or re.search(r"(^|_)(ebuf|einv|tbuf|tinv)", f):
        return "tristate"
    func = (outs[0].get("function") or "").replace(" ", "").strip("()")
    if func in ("0", "1") or re.search(r"(^|_)(conb|tie)", f):
        return "tie"
    if re.search(r"(^|_)(dly|clkdly|dlygate|dlymetal|delay)", f):
        return "delay"
    if re.search(r"(^|_)clk", f):
        return "clock"
    if re.search(r"(^|_)(fa|ha|maj|fah|addf|addh)", f):
        return "arith"
    if re.search(r"mux", f):
        return "mux"
    inputs = [p["name"] for p in s["pins"] if p["dir"] == "input"]
    if len(inputs) == 1 and len(outs) == 1:
        if func.startswith("!") or func.endswith("'"):
            return "inverter"
        return "buffer"
    return "logic"


CATEGORY_LABELS = {
    "logic": "Logic gates", "inverter": "Inverters", "buffer": "Buffers",
    "flipflop": "Flip-flops", "latch": "Latches", "mux": "Multiplexers",
    "arith": "Adders", "clock": "Clock", "delay": "Delay", "tristate": "Tri-state",
    "tie": "Tie cells", "power": "Power / isolation", "physical": "Physical only",
    "other": "Other",
}


# --------------------------------------------------------------------------- #
# Flow roles and exclusions
# --------------------------------------------------------------------------- #
ROLE_KEYS = [
    # key, label, what it is for (plain language)
    ("FILL_CELLS", "Fill", "Plugs the gaps left in each row after placement so wells and rails are continuous."),
    ("DECAP_CELLS", "Decap", "Fills gaps with decoupling capacitance that steadies the supply."),
    ("WELLTAP_CELL", "Well tap", "Ties the wells to the supply at a fixed pitch so the transistors stay biased (latch-up rule)."),
    ("ENDCAP_CELL", "End cap", "Sits at both ends of every row to finish the wells cleanly."),
    ("DIODE_CELL", "Antenna diode", "Inserted next to gate inputs on long wires to fix antenna violations."),
    ("SYNTH_TIEHI_CELL", "Tie high", "Drives constant 1s; synthesis never ties a gate input straight to the supply."),
    ("SYNTH_TIELO_CELL", "Tie low", "Drives constant 0s."),
    ("SYNTH_BUFFER_CELL", "Buffer", "The buffer synthesis uses when it has to insert one (e.g. port to port)."),
    ("SYNTH_DRIVING_CELL", "Input driver", "Assumed to drive every input port in synthesis and timing analysis."),
    ("SYNTH_CLK_DRIVING_CELL", "Clock input driver", "Assumed to drive the clock port (falls back to the input driver)."),
    ("CTS_ROOT_BUFFER", "Clock tree root", "The strong buffer at the root of the clock tree."),
    ("CTS_CLK_BUFFERS", "Clock tree buffers", "Buffers the clock tree builder may use."),
]


def _cells_of(value: Any) -> List[str]:
    """Cell names (or wildcards) in a role value: ``cell/pin`` → ``cell``."""
    out = []
    for tok in _as_list(value):
        out.append(tok.split("/")[0])
    return out


def _design_config(design_dir: Optional[str]) -> Dict[str, Any]:
    if not design_dir:
        return {}
    try:
        from . import configedit
        info = configedit.read_config(design_dir)
        data = info.get("data") if isinstance(info, dict) else None
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _custom_swaps(design_dir: Optional[str]) -> List[str]:
    if not design_dir:
        return []
    try:
        from . import customcells
        out: List[str] = []
        for c in customcells.list_cells(design_dir).get("cells", []):
            if c.get("enabled", True):
                out.extend(c.get("swap_out") or [])
        return out
    except Exception:
        return []


def rules(pdk: str, scl: str, design_dir: Optional[str] = None,
          names: Optional[List[str]] = None) -> Dict[str, Any]:
    """Which cells the flow will refuse (exclusion lists) and which it inserts by
    itself (roles), with where each came from (PDK vs the design's config)."""
    cfg = pdk_config(pdk, scl)
    dcfg = _design_config(design_dir)
    synth_file = dcfg.get("SYNTH_EXCLUDED_CELL_FILE") or cfg.get("SYNTH_EXCLUDED_CELL_FILE")
    pnr_file = dcfg.get("PNR_EXCLUDED_CELL_FILE") or cfg.get("PNR_EXCLUDED_CELL_FILE")
    tech = _tech_dir(pdk, scl)
    if not synth_file and tech is not None:
        for nm in ("synth_exclude.cells", "no_synth.cells"):
            if (tech / nm).is_file():
                synth_file = str(tech / nm)
                break
    if not pnr_file and tech is not None:
        for nm in ("pnr_exclude.cells", "drc_exclude.cells"):
            if (tech / nm).is_file():
                pnr_file = str(tech / nm)
                break
    if isinstance(synth_file, str) and synth_file.startswith("dir::") and design_dir:
        synth_file = str(Path(design_dir) / synth_file[5:])
    if isinstance(pnr_file, str) and pnr_file.startswith("dir::") and design_dir:
        pnr_file = str(Path(design_dir) / pnr_file[5:])
    user = _as_list(dcfg.get("EXTRA_EXCLUDED_CELLS"))
    roles = []
    for key, label, why in ROLE_KEYS:
        mine = key in dcfg
        val = dcfg.get(key) if mine else cfg.get(key)
        if val in (None, "", []):
            if key == "SYNTH_CLK_DRIVING_CELL":
                continue
            if not mine and key not in cfg:
                continue
        cells = _cells_of(val)
        if names is not None:
            exp: List[str] = []
            for c in cells:
                if any(ch in c for ch in "*?["):
                    exp.extend(n for n in names if fnmatch.fnmatchcase(n, c))
                else:
                    exp.append(c)
            cells = exp
        roles.append({"key": key, "label": label, "why": why, "value": val,
                      "cells": cells, "source": "design" if mine else "pdk"})
    return {
        "synth": {"file": synth_file, "patterns": _list_file(synth_file)},
        "pnr": {"file": pnr_file, "patterns": _list_file(pnr_file)},
        "user": {"patterns": user, "config": bool(dcfg)},
        "swaps": {"patterns": _custom_swaps(design_dir)},
        "roles": roles,
        "site": dcfg.get("PLACE_SITE") or cfg.get("PLACE_SITE"),
        "vdd": (_as_list(dcfg.get("VDD_NETS")) or [cfg.get("VDD_PIN") or "VPWR"])[0],
        "gnd": (_as_list(dcfg.get("GND_NETS")) or [cfg.get("GND_PIN") or "VGND"])[0],
    }


# --------------------------------------------------------------------------- #
# The library summary (one row per cell)
# --------------------------------------------------------------------------- #
def _fo4(lib: Dict[str, Any], cells: Dict[str, Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    """(load, slew) of a fan-out-of-4 reference, in library units: four times the
    input cap of the smallest plain inverter, with that inverter's own output
    slew at that load. A fixed, comparable operating point across drive
    strengths — the number people quote."""
    invs = []
    for name, s in cells.items():
        ins = [p for p in s["pins"] if p["dir"] == "input"]
        outs = [p for p in s["pins"] if p["dir"] == "output"]
        if len(ins) == 1 and len(outs) == 1 and (outs[0].get("function") or "").replace(" ", "") in (
                "!" + ins[0]["name"], "(!" + ins[0]["name"] + ")", ins[0]["name"] + "'", "!(" + ins[0]["name"] + ")") \
                and ins[0].get("cap") and s.get("area") and not re.search(r"clk|lp|bleeder", name):
            invs.append((s["area"], name, ins[0]["cap"]))
    if not invs:
        return None, None
    invs.sort()
    _, inv, cap = invs[0]
    load = 4 * cap
    arcs = _delay_arcs(lib["arcs"][inv])
    slew = None
    if arcs:
        a = arcs[0]
        i1 = (a.get("rise_transition") or a.get("cell_rise") or {}).get("index_1") or []
        mid = i1[len(i1) // 2] if i1 else 0.1
        rt = table_at(a.get("rise_transition"), mid, load)
        ft = table_at(a.get("fall_transition"), mid, load)
        vals = [v for v in (rt, ft) if v is not None]
        slew = sum(vals) / len(vals) if vals else mid
    return load, slew


def _arc_delay(arc: Dict[str, Any], slew: float, load: float) -> Optional[float]:
    vals = [v for v in (table_at(arc.get("cell_rise"), slew, load),
                        table_at(arc.get("cell_fall"), slew, load)) if v is not None]
    return max(vals) if vals else None


def library(pdk: str, scl: str, design_dir: Optional[str] = None) -> Dict[str, Any]:
    """Every cell of *scl* with what a designer needs to choose between them."""
    try:
        return _library(pdk, scl, design_dir)
    except Exception as ex:  # never let a malformed PDK file 500 the tab
        return {"ok": False, "error": f"could not read the library: {ex}"}


def _library(pdk: str, scl: str, design_dir: Optional[str]) -> Dict[str, Any]:
    if scl_dir(pdk, scl) is None:
        return {"ok": False, "error": f"'{scl}' is not installed for {pdk or 'this PDK'}."}
    libp = _main_lib(pdk, scl)
    lef = _lef(pdk, scl)
    if libp is None and not lef["macros"]:
        return {"ok": False, "error": "this library has neither Liberty nor LEF files on disk."}
    lib = _liberty(libp) if libp else {"units": {}, "cells": {}, "arcs": {}, "leaks": {}, "path": None}
    descs = _descriptions(pdk, scl)
    names = sorted(set(lib["cells"]) | set(lef["macros"]))
    prefix = lib_prefix(names, scl)
    rl = rules(pdk, scl, design_dir, names)
    units = lib.get("units") or {}
    ts = _scale(units.get("time", "1ns"), "time")
    cs = _scale(units.get("cap", "1pf"), "cap")
    ls = _scale(units.get("leakage", "1nW"), "leakage")
    load, slew = _fo4(lib, lib["cells"]) if lib["cells"] else (None, None)
    site = rl.get("site")
    site_w = (lef["sites"].get(site) or {}).get("w") if site else None
    site_h = (lef["sites"].get(site) or {}).get("h") if site else None
    role_of: Dict[str, List[str]] = {}
    for r in rl["roles"]:
        for c in r["cells"]:
            role_of.setdefault(c, []).append(r["label"])
    rows = []
    for name in names:
        s = lib["cells"].get(name)
        m = lef["macros"].get(name) or {}
        fam, drive = split_name(name, prefix)
        cat = _category(name, fam, s, m.get("class", ""))
        delay = None
        if s and load is not None and slew is not None:
            ds = [d for d in (_arc_delay(a, slew, load) for a in _delay_arcs(lib["arcs"][name])) if d is not None]
            delay = max(ds) * ts if ds else None
        outs = [p for p in (s or {}).get("pins", []) if p["dir"] == "output"]
        ins = [p for p in (s or {}).get("pins", []) if p["dir"] == "input"]
        ex = {
            "synth": matches(name, rl["synth"]["patterns"]),
            "pnr": matches(name, rl["pnr"]["patterns"]),
            "user": matches(name, rl["user"]["patterns"]),
            "swap": matches(name, rl["swaps"]["patterns"]),
        }
        desc = descs.get(fam) or descs.get(name[len(prefix):] if name.startswith(prefix) else name) or ""
        rows.append({
            "cell": name, "family": fam, "drive": drive, "category": cat,
            "desc": desc if isinstance(desc, str) else "",
            # the PDK's own readable formula (sky130 headers: "Y = !((A1 & A2) | B1)");
            # Liberty states the same function in sum-of-products form
            "formula": descs.get("=" + fam) or [],
            "area": s.get("area") if s else ((m.get("w") or 0) * (m.get("h") or 0) or None),
            "w": m.get("w"), "h": m.get("h"),
            "sites": (round(m["w"] / site_w) if m.get("w") and site_w else None),
            "leakage": (s["leakage"] * ls) if s and s.get("leakage") is not None else None,
            "delay": delay,
            "inputs": [p["name"] for p in ins],
            "outputs": [{"name": p["name"], "function": p.get("function")} for p in outs],
            "in_cap": (max(p["cap"] for p in ins if p.get("cap") is not None) * cs) if any(p.get("cap") is not None for p in ins) else None,
            "seq": (s or {}).get("seq"),
            "dont_use": bool(s and s.get("dont_use")),
            "excluded": {k: v for k, v in ex.items() if v},
            "roles": role_of.get(name, []),
            "has_lib": s is not None, "has_lef": bool(m),
        })
    return {
        "ok": True, "pdk": pdk, "scl": scl, "prefix": prefix,
        "liberty": str(libp) if libp else None,
        "corner": Path(libp).stem.replace(scl, "").strip("_") if libp else None,
        "units": {"time": "ps", "cap": "fF", "leakage": "nW", "area": "µm²", "length": "µm"},
        "lib_units": units,
        "fo4": {"load_ff": load * cs if load else None, "slew_ps": slew * ts if slew else None},
        "site": {"name": site, "w": site_w, "h": site_h},
        "categories": CATEGORY_LABELS,
        "rules": rl,
        "cells": rows,
    }


# --------------------------------------------------------------------------- #
# One cell in depth
# --------------------------------------------------------------------------- #
def cell_detail(pdk: str, scl: str, cell: str) -> Dict[str, Any]:
    try:
        return _cell_detail(pdk, scl, cell)
    except Exception as ex:
        return {"ok": False, "error": f"could not read {cell}: {ex}"}


def _curve(arc: Dict[str, Any], slew: float, loads: List[float], ts: float) -> List[Optional[float]]:
    out = []
    for L in loads:
        d = _arc_delay(arc, slew, L)
        out.append(d * ts if d is not None else None)
    return out


def _cell_detail(pdk: str, scl: str, cell: str) -> Dict[str, Any]:
    libp = _main_lib(pdk, scl)
    lib = _liberty(libp) if libp else {"units": {}, "cells": {}, "arcs": {}, "leaks": {}}
    lef = _lef(pdk, scl)
    if cell not in lib["cells"] and cell not in lef["macros"]:
        return {"ok": False, "error": f"{cell} is not in {scl}"}
    units = lib.get("units") or {}
    ts = _scale(units.get("time", "1ns"), "time")
    cs = _scale(units.get("cap", "1pf"), "cap")
    ls = _scale(units.get("leakage", "1nW"), "leakage")
    s = lib["cells"].get(cell)
    has_lib = cell in lib["arcs"]
    arcs = lib["arcs"].get(cell) or []

    def conv_table(t: Optional[Dict[str, Any]], vscale: float) -> Optional[Dict[str, Any]]:
        if not t:
            return None
        tmpl = t.get("template") or ""
        # delay_template: index_1 = input transition (time), index_2 = load (cap);
        # constraint templates use related/constrained transitions (both time).
        i2_scale = cs if ("load" in tmpl or "delay" in tmpl or "template" in tmpl and "constraint" not in tmpl) else ts
        return {"index_1": [x * ts for x in t["index_1"]],
                "index_2": [x * i2_scale for x in t["index_2"]],
                "values": [[v * vscale for v in row] for row in t["values"]],
                "template": tmpl}
    out_arcs = []
    for a in arcs:
        out_arcs.append({
            "from": a["from"], "to": a["to"], "sense": a.get("sense"), "type": a.get("type"),
            "when": a.get("when"),
            **{k: conv_table(a.get(k), ts) for k in ("cell_rise", "cell_fall", "rise_transition",
                                                    "fall_transition", "rise_constraint", "fall_constraint")},
        })
    leak_states = [{"when": g["when"], "value": g["value"] * ls}
                   for g in (lib["leaks"].get(cell) or [])]
    # siblings: same family, every drive strength, delay-vs-load curves on the
    # first combinational arc (same from/to pins in every drive).
    names = sorted(set(lib["cells"]) | set(lef["macros"]))
    prefix = lib_prefix(names, scl)
    fam, _ = split_name(cell, prefix)
    sibs = [n for n in names if split_name(n, prefix)[0] == fam]
    load_ref, slew_ref = _fo4(lib, lib["cells"]) if lib["cells"] else (None, None)
    curves = []
    loads: List[float] = []
    if has_lib and load_ref:
        darcs = _delay_arcs(arcs)
        if darcs:
            pick = darcs[0]
            i2 = (pick.get("cell_rise") or pick.get("cell_fall") or {}).get("index_2") or []
            hi = max(i2) if i2 else load_ref * 8
            hi = min(hi, load_ref * 16) if load_ref else hi
            loads = [hi * k / 24 for k in range(0, 25)]
            for n in sibs:
                t = lib["arcs"].get(n)
                if t is None:
                    continue
                cand = [a for a in _delay_arcs(t) if a["from"] == pick["from"] and a["to"] == pick["to"]] \
                    or _delay_arcs(t)
                if not cand:
                    continue
                curves.append({"cell": n, "drive": split_name(n, prefix)[1], "from": cand[0]["from"],
                               "to": cand[0]["to"], "delay": _curve(cand[0], slew_ref, loads, ts)})
    m = lef["macros"].get(cell)
    return {
        "ok": True, "cell": cell, "family": fam, "prefix": prefix,
        "liberty": s and {
            "area": s.get("area"),
            "leakage": s["leakage"] * ls if s.get("leakage") is not None else None,
            "footprint": s.get("footprint"),
            "pins": [dict(p, cap=(p["cap"] * cs if p.get("cap") is not None else None),
                          max_cap=(p["max_cap"] * cs if p.get("max_cap") is not None else None))
                     for p in s["pins"]],
            "pg_pins": s.get("pg_pins"),
            "seq": s.get("seq"),
            "statetable": s.get("statetable", False),
            "clock_gate": s.get("is_clock_gate", False),
        },
        "arcs": out_arcs,
        "leakage_states": leak_states,
        "lef": m,
        "curves": {"loads_ff": [L * cs for L in loads], "slew_ps": slew_ref * ts if slew_ref else None,
                   "fo4_ff": load_ref * cs if load_ref else None, "series": curves},
        "corner": Path(libp).stem if libp else None,
    }


# --------------------------------------------------------------------------- #
# GDS: the real layout of one cell
# --------------------------------------------------------------------------- #
def _gds_real8(b: bytes) -> float:
    if len(b) != 8:
        return 0.0
    sign = -1.0 if b[0] & 0x80 else 1.0
    exp = (b[0] & 0x7F) - 64
    mant = int.from_bytes(b[1:], "big") / float(1 << 56)
    return sign * mant * (16.0 ** exp)


def _gds_index(path: Path) -> Dict[str, Any]:
    """Scan a GDS stream once: user units per micron and each structure's
    byte span. Cached."""
    def build() -> Dict[str, Any]:
        data = path.read_bytes()
        spans: Dict[str, Tuple[int, int]] = {}
        i, L = 0, len(data)
        db_per_um = 1000.0
        cur: Optional[str] = None
        start = 0
        while i + 4 <= L:
            ln, rt = struct.unpack(">HB", data[i:i + 3])
            if ln < 4:
                break
            if rt == 0x03 and ln >= 20:        # UNITS: user/db, meters/db
                m_per_db = _gds_real8(data[i + 12:i + 20])
                if m_per_db:
                    db_per_um = 1e-6 / m_per_db
            elif rt == 0x05:                   # BGNSTR
                start = i
            elif rt == 0x06:                   # STRNAME
                cur = data[i + 4:i + ln].rstrip(b"\0").decode("ascii", "replace")
            elif rt == 0x07 and cur is not None:  # ENDSTR
                spans[cur] = (start, i + ln)
                cur = None
            elif rt == 0x04:                   # ENDLIB
                break
            i += ln
        return {"data": data, "spans": spans, "db_per_um": db_per_um}
    return _cached("gds", str(path), [path], build)


def _gds_elements(idx: Dict[str, Any], name: str) -> List[Dict[str, Any]]:
    a, b = idx["spans"][name]
    data = idx["data"]
    i = a
    els: List[Dict[str, Any]] = []
    el: Optional[Dict[str, Any]] = None
    while i + 4 <= b:
        ln, rt, dt = struct.unpack(">HBB", data[i:i + 4])
        if ln < 4:
            break
        body = data[i + 4:i + ln]
        if rt in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x2D):   # BOUNDARY PATH SREF AREF TEXT BOX
            el = {"t": rt, "layer": 0, "dt": 0, "xy": [], "width": 0, "sname": "", "string": "",
                  "angle": 0.0, "mag": 1.0, "reflect": False, "colrow": (1, 1)}
        elif el is not None:
            if rt == 0x0D:
                el["layer"] = struct.unpack(">h", body[:2])[0]
            elif rt in (0x0E, 0x16, 0x2E):
                el["dt"] = struct.unpack(">h", body[:2])[0]
            elif rt == 0x0F:
                el["width"] = struct.unpack(">i", body[:4])[0]
            elif rt == 0x10:
                cnt = len(body) // 4
                el["xy"] = list(struct.unpack(">" + "i" * cnt, body[:cnt * 4]))
            elif rt == 0x12:
                el["sname"] = body.rstrip(b"\0").decode("ascii", "replace")
            elif rt == 0x19:
                el["string"] = body.rstrip(b"\0").decode("ascii", "replace")
            elif rt == 0x1A:
                el["reflect"] = bool(struct.unpack(">H", body[:2])[0] & 0x8000)
            elif rt == 0x1B:
                el["mag"] = _gds_real8(body[:8])
            elif rt == 0x1C:
                el["angle"] = _gds_real8(body[:8])
            elif rt == 0x13:
                el["colrow"] = struct.unpack(">hh", body[:4])
            elif rt == 0x11:                   # ENDEL
                els.append(el)
                el = None
        i += ln
    return els


def _xf(pts: List[Tuple[float, float]], ox: float, oy: float, ang: float, mag: float, refl: bool):
    c, s = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    out = []
    for x, y in pts:
        if refl:
            y = -y
        x, y = x * mag, y * mag
        out.append((ox + x * c - y * s, oy + x * s + y * c))
    return out


def _path_poly(xy: List[Tuple[float, float]], w: float) -> List[Tuple[float, float]]:
    if len(xy) < 2 or w <= 0:
        return []
    hw = w / 2.0
    left, right = [], []
    for k in range(len(xy)):
        p = xy[k]
        if k < len(xy) - 1:
            dx, dy = xy[k + 1][0] - p[0], xy[k + 1][1] - p[1]
        else:
            dx, dy = p[0] - xy[k - 1][0], p[1] - xy[k - 1][1]
        L = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / L * hw, dx / L * hw
        left.append((p[0] + nx, p[1] + ny))
        right.append((p[0] - nx, p[1] - ny))
    return left + right[::-1]


def _flatten(idx: Dict[str, Any], name: str, depth: int, xf, out_polys, out_text, budget: List[int]):
    if depth > 8 or budget[0] <= 0 or name not in idx["spans"]:
        return
    for el in _gds_elements(idx, name):
        if budget[0] <= 0:
            return
        xy = el["xy"]
        pts = [(xy[k], xy[k + 1]) for k in range(0, len(xy) - 1, 2)]
        if el["t"] in (0x08, 0x2D):
            if el["t"] == 0x08 and len(pts) > 1 and pts[0] == pts[-1]:
                pts = pts[:-1]
            out_polys.append((el["layer"], el["dt"], xf(pts)))
            budget[0] -= 1
        elif el["t"] == 0x09:
            poly = _path_poly(pts, float(el["width"]))
            if poly:
                out_polys.append((el["layer"], el["dt"], xf(poly)))
                budget[0] -= 1
        elif el["t"] == 0x0C and pts:
            out_text.append((el["layer"], el["dt"], el["string"], xf(pts[:1])[0]))
        elif el["t"] == 0x0A and pts:
            ox, oy = pts[0]
            a, m, r = el["angle"], el["mag"], el["reflect"]
            _flatten(idx, el["sname"], depth + 1,
                     lambda q, ox=ox, oy=oy, a=a, m=m, r=r: xf(_xf(q, ox, oy, a, m, r)),
                     out_polys, out_text, budget)
        elif el["t"] == 0x0B and len(pts) >= 3:
            cols, rows = el["colrow"]
            (x0, y0), (xc, yc), (xr, yr) = pts[:3]
            for ci in range(min(cols, 64)):
                for ri in range(min(rows, 64)):
                    ox = x0 + (xc - x0) * ci / max(cols, 1) + (xr - x0) * ri / max(rows, 1)
                    oy = y0 + (yc - y0) * ci / max(cols, 1) + (yr - y0) * ri / max(rows, 1)
                    a, m, r = el["angle"], el["mag"], el["reflect"]
                    _flatten(idx, el["sname"], depth + 1,
                             lambda q, ox=ox, oy=oy, a=a, m=m, r=r: xf(_xf(q, ox, oy, a, m, r)),
                             out_polys, out_text, budget)


# gf180mcu.lyp carries no layer names; the common front-end ones, from the
# GF180MCU layer map.
_GF_NAMES = {
    (0, 0): "PR boundary", (12, 0): "DNWELL", (21, 0): "Nwell", (22, 0): "COMP",
    (30, 0): "Poly2", (31, 0): "Pplus", (32, 0): "Nplus", (33, 0): "Contact",
    (34, 0): "Metal1", (34, 10): "Metal1 label", (35, 0): "Via1", (36, 0): "Metal2",
    (55, 0): "Dualgate", (204, 0): "LVS prBndry", (112, 1): "Metal1 pin",
}

_LYP_PROP = re.compile(r"<properties>(.*?)</properties>", re.S)


def _lyp(pdk: str) -> List[Dict[str, Any]]:
    d = pdk_dir(pdk)
    if d is None:
        return []
    kl = d / "libs.tech" / "klayout" / "tech"
    cands = sorted(kl.glob("*.lyp")) if kl.is_dir() else []
    if not cands:
        return []
    # prefer the PDK's main file (sky130A.lyp, gf180mcu.lyp, sg13g2.lyp)
    path = sorted(cands, key=lambda p: (0 if pdk.lower().startswith(p.stem.lower()[:5]) else 1, len(p.name)))[0]

    def build() -> List[Dict[str, Any]]:
        out = []
        txt = path.read_text(encoding="utf-8", errors="replace")
        for k, m in enumerate(_LYP_PROP.finditer(txt)):
            body = m.group(1)
            src = re.search(r"<source>(.*?)</source>", body)
            sm = re.search(r"(\d+)/(\d+)", src.group(1)) if src else None
            if not sm:
                continue
            def tag(t: str) -> str:
                g = re.search(r"<" + t + r">(.*?)</" + t + r">", body)
                return g.group(1).strip() if g else ""
            key = (int(sm.group(1)), int(sm.group(2)))
            nm = re.sub(r"\s*-?\s*\d+/\d+(@\d+)?\s*$", "", tag("name")).strip()
            if not nm:
                lead = re.match(r"\s*([A-Za-z][\w.]*)\s+\d+/\d+", src.group(1))
                nm = lead.group(1) if lead else _GF_NAMES.get(key, "") if pdk.startswith("gf180") else ""
            out.append({"layer": key[0], "dt": key[1], "order": k,
                        "name": nm or f"{key[0]}/{key[1]}",
                        "fill": tag("fill-color") or "#888888", "frame": tag("frame-color") or "#888888",
                        "dither": tag("dither-pattern"), "visible": tag("visible") != "false"})
        return out
    return _cached("lyp", str(path), [path], build)


def cell_layout(pdk: str, scl: str, cell: str, gds_path: Optional[str] = None,
                max_polys: int = 6000) -> Dict[str, Any]:
    """Polygons of *cell* by layer, in microns, ready to draw. Uses the SCL's GDS
    unless *gds_path* (e.g. a macro's) is given."""
    try:
        if gds_path:
            gp = Path(gds_path)
        else:
            s = scl_dir(pdk, scl)
            files = sorted((s / "gds").glob("*.gds")) if s and (s / "gds").is_dir() else []
            if not files:
                return {"ok": False, "error": "this library ships no GDS"}
            gp = files[0]
            # libraries split per cell: <cell>.gds
            for f in files:
                if f.stem == cell:
                    gp = f
                    break
        idx = _gds_index(gp)
        if cell not in idx["spans"]:
            return {"ok": False, "error": f"{cell} is not in {gp.name}"}
        polys: List[Any] = []
        texts: List[Any] = []
        budget = [max_polys]
        _flatten(idx, cell, 0, lambda q: q, polys, texts, budget)
        u = idx["db_per_um"] or 1000.0
        lyp = {(p["layer"], p["dt"]): p for p in _lyp(pdk)}
        layers: Dict[Tuple[int, int], Dict[str, Any]] = {}
        xs, ys = [], []
        for layer, dt, pts in polys:
            key = (layer, dt)
            info = lyp.get(key)
            if info is not None and not info.get("visible", True):
                continue
            L = layers.get(key)
            if L is None:
                L = layers[key] = {
                    "key": f"{layer}/{dt}",
                    "name": info["name"] if info else f"{layer}/{dt}",
                    "fill": info["fill"] if info else "#9aa4b1",
                    "frame": info["frame"] if info else "#9aa4b1",
                    "order": info["order"] if info else 10_000 + layer,
                    "known": info is not None,
                    "polys": [],
                }
            flat = []
            for x, y in pts:
                fx, fy = round(x / u, 4), round(y / u, 4)
                xs.append(fx)
                ys.append(fy)
                flat.extend((fx, fy))
            L["polys"].append(flat)
        labels = [{"text": t, "x": round(p[0] / u, 4), "y": round(p[1] / u, 4), "key": f"{l}/{d}"}
                  for l, d, t, p in texts if t]
        bbox = [min(xs), min(ys), max(xs), max(ys)] if xs else [0, 0, 0, 0]
        ordered = sorted(layers.values(), key=lambda L: L["order"])
        return {"ok": True, "cell": cell, "gds": gp.name, "bbox": bbox, "layers": ordered,
                "labels": labels, "truncated": budget[0] <= 0}
    except Exception as ex:
        return {"ok": False, "error": f"could not read the layout: {ex}"}
