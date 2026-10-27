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
"""A project's files, what each is for, and starter content for new ones.

``list_files`` sorts every file in a design folder into the roles a LibreLane
project uses (design RTL, testbenches, include headers, memory contents,
timing constraints, pin order, the config, anything else editable) and says
which config variable points at it. ``new_file`` writes a starter file of a
given kind and, when asked, points the config at it (through
:mod:`configedit`, so the config is only ever changed key by key).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import configedit
from .editor import EDITABLE_EXTS, _resolve_inside

_SKIP_DIRS = {".git", "runs", "tmp", "__pycache__", "build", "node_modules", "sim_build", "obj_dir"}
_TB_DIR_RX = re.compile(r"(^|/)(verify|tb|tbs|test|tests|sim|testbench|testbenches)/", re.I)
_TB_NAME_RX = re.compile(r"(^tb_|_tb\.|^test_|testbench)", re.I)
# Config variables that name a single project file, and what the UI calls them.
FILE_VARS = {
    "PNR_SDC_FILE": "timing constraints for place and route",
    "SIGNOFF_SDC_FILE": "timing constraints for signoff",
    "IO_PIN_ORDER_CFG": "pin order",
}


def is_testbench(rel: str) -> bool:
    """Same rule as the Setup page: lives in verify/, tb/, test/, sim/… or is
    named like a bench (tb_x, x_tb.v, test_x, …testbench…)."""
    rel = rel.replace("\\", "/")
    return bool(_TB_DIR_RX.search(rel) or _TB_NAME_RX.search(rel.rsplit("/", 1)[-1]))


def _role(rel: str, ext: str) -> str:
    name = rel.rsplit("/", 1)[-1]
    if "/" not in rel and name in configedit.CONFIG_NAMES:
        return "config"
    if ext in (".v", ".sv", ".verilog"):
        return "testbench" if is_testbench(rel) else "design"
    if ext in (".vh", ".svh"):
        return "header"
    if ext in (".mem", ".hex", ".bin"):
        return "memory"
    if ext == ".sdc":
        return "timing"
    if ext == ".cfg":
        return "pins"
    if ext in (".vhd", ".vhdl"):
        return "vhdl"
    return "other"


def _var_targets(design_dir: Path, data: Dict[str, Any]) -> Dict[str, List[str]]:
    """``{abspath: [VAR, ...]}`` for the single-file variables in *data*."""
    out: Dict[str, List[str]] = {}
    for var in FILE_VARS:
        v = data.get(var)
        if not isinstance(v, str) or not v:
            continue
        s = v[len("dir::"):] if v.startswith("dir::") else v
        if s.startswith(("ref::", "refg::", "expr::", "pdk_dir::")):
            continue
        p = Path(s) if os.path.isabs(s) else design_dir / s
        out.setdefault(str(p.resolve()), []).append(var)
    return out


def list_files(design_dir: str | Path, max_files: int = 2000) -> Dict[str, Any]:
    """Every project file with its role and the config variables using it.

    ``{files: [{rel, abs, ext, size, role, in_verilog_files, used_by}],
    config: {name, format, editable, reason}, sources: <resolve_sources>}``
    """
    d = Path(design_dir).resolve()
    info = configedit.read_config(d)
    sources = configedit.resolve_sources(d, info["data"]) if info["editable"] else \
        {"mode": "unknown" if info["path"] else "none", "entries": [], "files": [], "globbed": False,
         "reason": info["reason"]}
    in_vf = set(sources["files"])
    targets = _var_targets(d, info["data"])
    files: List[Dict[str, Any]] = []
    for root, dirs, names in os.walk(d):
        dirs[:] = sorted(x for x in dirs if x not in _SKIP_DIRS and not x.startswith("."))
        for n in sorted(names):
            if n.startswith("."):
                continue   # LanEx's own overlays and editor temp files
            p = Path(root) / n
            ext = p.suffix.lower()
            if ext not in EDITABLE_EXTS and ext not in (".bin", ".verilog"):
                continue
            rel = p.relative_to(d).as_posix()
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            ap = str(p.resolve())
            files.append({"rel": rel, "abs": ap, "ext": ext, "size": size,
                          "role": _role(rel, ext), "in_verilog_files": ap in in_vf,
                          "used_by": targets.get(ap, [])})
            if len(files) >= max_files:
                break
    return {"files": files,
            "config": {k: info[k] for k in ("name", "format", "editable", "reason")},
            "sources": sources}


# ------------------------------------------------------------------ ports

def _strip(text: str) -> str:
    return re.sub(r"//[^\n]*|/\*.*?\*/", " ", text, flags=re.S)


def _balanced(text: str, i: int) -> int:
    """Index just past the ``)`` matching the ``(`` at *i*."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    return len(text)


def _split_top(s: str) -> List[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return out


_DIR_RX = re.compile(r"\b(input|output|inout)\b")
_RANGE_RX = re.compile(r"\[[^\]]*\]")
_IDENT_RX = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_NOT_NAMES = {"input", "output", "inout", "wire", "reg", "logic", "var", "signed", "unsigned",
              "tri", "wand", "wor", "bit", "byte", "int", "integer", "shortint", "longint"}


def module_ports(text: str, module: str) -> List[Dict[str, Any]]:
    """``[{name, dir, bus}]`` for *module* in *text* (ANSI or classic port
    style). Best effort: returns [] when the module isn't found."""
    t = _strip(text)
    m = re.search(r"\bmodule\s+" + re.escape(module) + r"\b", t)
    if not m:
        return []
    i = m.end()
    rest = t[i:]
    j = 0
    while j < len(rest) and rest[j].isspace():
        j += 1
    if rest[j:j + 1] == "#":                     # parameter list #( ... )
        k = rest.find("(", j)
        j = _balanced(rest, k) if k != -1 else j
        while j < len(rest) and rest[j].isspace():
            j += 1
    if rest[j:j + 1] != "(":
        return []                                 # module foo; (no ports)
    end = _balanced(rest, j)
    header = rest[j + 1:end - 1]
    body = rest[end:]
    em = re.search(r"\bendmodule\b", body)
    body = body[:em.start()] if em else body
    ports: List[Dict[str, Any]] = []
    if _DIR_RX.search(header):                    # ANSI: directions in the header
        cur_dir, cur_range, cur_signed = None, "", False
        for item in _split_top(header):
            item = item.split("=", 1)[0]
            dm = _DIR_RX.search(item)
            if dm:
                # `input [7:0] a, b`: b continues a's direction and width.
                cur_dir = dm.group(1)
                rm = _RANGE_RX.search(item)
                cur_range = _squash(rm.group(0)) if rm else ""
                cur_signed = bool(re.search(r"\bsigned\b", item))
            names = [x for x in _IDENT_RX.findall(_RANGE_RX.sub(" ", item)) if x not in _NOT_NAMES]
            if not names or cur_dir is None:
                continue
            ports.append({"name": names[-1], "dir": cur_dir, "bus": bool(cur_range),
                          "range": cur_range, "signed": cur_signed})
        return ports
    names = [x.strip() for x in header.split(",") if x.strip()]
    decl: Dict[str, Dict[str, Any]] = {}
    for st in re.finditer(r"\b(input|output|inout)\b([^;]*);", body):
        seg = st.group(2)
        rm = _RANGE_RX.search(seg)
        rng = _squash(rm.group(0)) if rm else ""
        signed = bool(re.search(r"\bsigned\b", seg))
        for part in _split_top(_RANGE_RX.sub(" ", seg)):
            ids = [x for x in _IDENT_RX.findall(part.split("=", 1)[0]) if x not in _NOT_NAMES]
            if ids:
                decl[ids[-1]] = {"name": ids[-1], "dir": st.group(1), "bus": bool(rng),
                                 "range": rng, "signed": signed}
    for n in names:
        n = _IDENT_RX.findall(n)[-1] if _IDENT_RX.findall(n) else n
        ports.append(decl.get(n, {"name": n, "dir": "input", "bus": False, "range": "", "signed": False}))
    return ports


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s)


def module_params(text: str, module: str) -> List[Tuple[str, str]]:
    """``[(name, default)]`` for *module*'s parameters, from a ``#( ... )``
    header list or ``parameter X = v;`` lines in the body. A testbench copies
    them as localparams so port widths such as ``[W-1:0]`` still mean
    something there."""
    t = _strip(text)
    m = re.search(r"\bmodule\s+" + re.escape(module) + r"\b", t)
    if not m:
        return []
    rest = t[m.end():]
    em = re.search(r"\bendmodule\b", rest)
    rest = rest[:em.start()] if em else rest
    out: List[Tuple[str, str]] = []
    j = 0
    while j < len(rest) and rest[j].isspace():
        j += 1
    chunks: List[str] = []
    if rest[j:j + 1] == "#":
        k = rest.find("(", j)
        if k != -1:
            end = _balanced(rest, k)
            chunks += _split_top(rest[k + 1:end - 1])
            rest = rest[end:]
    chunks += [x.group(1) for x in re.finditer(r"\bparameter\b([^;]*);", rest)]
    for c in chunks:
        for part in _split_top(c):
            if "=" not in part:
                continue
            lhs, rhs = part.split("=", 1)
            ids = [x for x in _IDENT_RX.findall(_RANGE_RX.sub(" ", lhs))
                   if x not in _NOT_NAMES and x not in ("parameter", "localparam", "type")]
            if ids and rhs.strip():
                out.append((ids[-1], " ".join(rhs.split())))
    return out


# Declarations only: a body made of nothing else has no logic to build.
_DECL_ONLY_RX = re.compile(
    r"\b(input|output|inout|wire|reg|logic|bit|var|integer|genvar|parameter|localparam|"
    r"timeunit|timeprecision|`default_nettype)\b[^;]*;")


def module_is_empty(text: str, module: str) -> Optional[bool]:
    """True when *module* declares ports/nets but contains no logic at all
    (no assign, always, instance …), like a fresh starter module. A run of
    such a top stops at placement with nothing to place. ``None`` when the
    module isn't in *text*."""
    t = _strip(text)
    m = re.search(r"\bmodule\s+" + re.escape(module) + r"\b", t)
    if not m:
        return None
    rest = t[m.end():]
    j = 0
    while j < len(rest) and rest[j].isspace():
        j += 1
    if rest[j:j + 1] == "#":
        k = rest.find("(", j)
        j = _balanced(rest, k) if k != -1 else j
        while j < len(rest) and rest[j].isspace():
            j += 1
    if rest[j:j + 1] == "(":
        j = _balanced(rest, j)
    semi = rest.find(";", j)
    if semi == -1:
        return None
    body = rest[semi + 1:]
    em = re.search(r"\bendmodule\b", body)
    body = body[:em.start()] if em else body
    def keep(d: "re.Match[str]") -> str:
        # `wire y = a & b;` is logic; `parameter W = 8;` is not.
        return d.group(0) if "=" in d.group(0) and d.group(1) not in ("parameter", "localparam") else " "
    return not _DECL_ONLY_RX.sub(keep, body).strip()


def find_module_file(design_dir: str | Path, module: str, files: Optional[List[str]] = None) -> Optional[Path]:
    """The first source file (of *files*, or every .v/.sv in the project)
    that declares *module*."""
    d = Path(design_dir)
    cands = [Path(f) for f in files] if files else sorted(
        p for p in d.rglob("*") if p.suffix.lower() in (".v", ".sv") and "runs" not in p.relative_to(d).parts)
    for f in cands:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"\bmodule\s+" + re.escape(module) + r"\b", text):
            return f
    return None


def find_module_ports(design_dir: str | Path, module: str, files: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    d = Path(design_dir)
    cands = [Path(f) for f in files] if files else sorted(
        p for p in d.rglob("*") if p.suffix.lower() in (".v", ".sv") and "runs" not in p.relative_to(d).parts)
    for f in cands:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r"\bmodule\s+" + re.escape(module) + r"\b", text):
            return module_ports(text, module)
    return []


# ------------------------------------------------------------------ templates

_RESET_RX = re.compile(r"^(rst|reset|rst_?n|resetn|reset_?n|arst|arst_?n|rst_i|rst_ni|nrst|n_reset)$", re.I)


def _base_sdc() -> str:
    """LibreLane's own default SDC (what runs use when no SDC is set), read
    from the installed LibreLane so the template always matches it."""
    try:
        import librelane
        p = Path(librelane.__file__).parent / "scripts" / "base.sdc"
        return p.read_text(encoding="utf-8")
    except Exception:
        return _FALLBACK_SDC


_FALLBACK_SDC = """\
set clock_port [lindex $::env(CLOCK_PORT) 0]
create_clock [get_ports $clock_port] -name $clock_port -period $::env(CLOCK_PERIOD)
set clk_input [get_port $clock_port]
set clk_indx [lsearch [all_inputs] $clk_input]
set all_inputs_wo_clk [lreplace [all_inputs] $clk_indx $clk_indx ""]
set io_delay [expr $::env(CLOCK_PERIOD) * $::env(IO_DELAY_CONSTRAINT) / 100]
set_input_delay $io_delay -clock [get_clocks $clock_port] $all_inputs_wo_clk
set_output_delay $io_delay -clock [get_clocks $clock_port] [all_outputs]
set_clock_uncertainty $::env(CLOCK_UNCERTAINTY_CONSTRAINT) [get_clocks $clock_port]
set_clock_transition $::env(CLOCK_TRANSITION_CONSTRAINT) [get_clocks $clock_port]
set_propagated_clock [all_clocks]
"""


def sdc_template(top: str) -> str:
    return (
        f"# Timing constraints for {top}.\n"
        "#\n"
        "# This starts as an exact copy of LibreLane's default constraints, the ones a\n"
        "# run uses when no SDC file is set. It reads the clock port and period from\n"
        "# your config (CLOCK_PORT, CLOCK_PERIOD) and the I/O delay, load and\n"
        "# uncertainty from their LibreLane settings, so it behaves exactly like the\n"
        "# default until you change something. Typical edits: fixed input/output\n"
        "# delays for specific ports, set_false_path for a slow reset, a second clock.\n"
        "#\n\n" + _base_sdc())


def pins_template(top: str, ports: List[Dict[str, Any]], clock: Optional[str]) -> str:
    sides: Dict[str, List[str]] = {"S": [], "W": [], "E": [], "N": []}
    for p in ports:
        n = p["name"]
        if n == clock or _RESET_RX.match(n):
            sides["S"].append(n)
        elif p["dir"] == "input":
            sides["W"].append(n)
        elif p["dir"] == "output":
            sides["E"].append(n)
        else:
            sides["N"].append(n)
    # No comments: LibreLane's pin-file parser has none, and a line such as
    # "# Every port..." would even be read as the direction token #E.
    lines: List[str] = []
    for side in ("N", "S", "E", "W"):
        if not sides[side]:
            continue
        lines.append("#" + side)
        lines += [re.escape(n) + r"(\[\d+\])?" for n in sides[side]]
        lines.append("")
    return "\n".join(lines)


def module_template(name: str, sv: bool) -> str:
    if sv:
        return (f"module {name} (\n"
                "    input  logic clk,\n"
                "    input  logic rst_n\n"
                ");\n\n"
                "  always_ff @(posedge clk or negedge rst_n) begin\n"
                "    if (!rst_n) begin\n"
                "      // reset values\n"
                "    end else begin\n"
                "      // your logic\n"
                "    end\n"
                "  end\n\n"
                "endmodule\n")
    return (f"module {name} (\n"
            "    input  wire clk,\n"
            "    input  wire rst_n\n"
            ");\n\n"
            "  // Your logic here.\n\n"
            "endmodule\n")


def testbench_template(name: str, sv: bool, dut: Optional[str],
                       ports: Optional[List[Dict[str, Any]]] = None, clock: Optional[str] = None,
                       period: Optional[float] = None, params: Optional[List[Tuple[str, str]]] = None) -> str:
    """A testbench for *dut*. Given the DUT's ports it is ready to simulate:
    every input driven from a variable, every output on a wire, the clock
    toggling at the config's period, the reset held for two cycles, and a
    VCD dump for the waveform. Without them it is a commented skeleton."""
    t = "logic" if sv else "reg"
    head = ("`timescale 1ns/1ps\n\n"
            f"// Testbench for {dut or 'your design'}. It only runs in simulation: it lives in\n"
            "// verify/ and is never built into the chip. Simulate in the RTL IDE runs it\n"
            "// and shows the waveform.\n"
            f"module {name};\n")
    if not dut or not ports:
        inst = (f"  // {dut} dut (.clk(clk), .rst_n(rst_n));" if dut
                else "  // my_design dut (.clk(clk), .rst_n(rst_n));")
        return (head +
                f"  {t} clk = 0;\n"
                f"  {t} rst_n = 0;\n"
                "  always #5 clk = ~clk;\n\n"
                "  // Instantiate your design here, for example:\n"
                f"{inst}\n\n"
                "  initial begin\n"
                f"    $dumpfile(\"{name}.vcd\");\n"
                f"    $dumpvars(0, {name});\n"
                "    #20 rst_n = 1;\n"
                "    #1000 $finish;\n"
                "  end\n"
                "endmodule\n")
    clk = clock if clock and any(p["name"] == clock for p in ports) else next(
        (p["name"] for p in ports
         if p["dir"] == "input" and re.fullmatch(r"(clk|clock|clk_i|i_clk)", p["name"], re.I)), None)
    rst = next((p["name"] for p in ports if p["dir"] == "input" and _RESET_RX.match(p["name"])), None)
    active_low = bool(rst and re.search(r"n$|_n$|ni$", rst, re.I))
    half = float(period) / 2 if period else 5.0

    def num(x: float) -> str:
        return ("%f" % x).rstrip("0").rstrip(".")

    out = [head]
    if params:
        out.append("  // The design's parameters, so its port widths mean the same here.\n")
        out += [f"  localparam {n} = {v};\n" for n, v in params]
        out.append("\n")
    shapes = {p["name"]: ("signed " if p.get("signed") else "") + p.get("range", "") for p in ports}
    sw = max(len(x) for x in shapes.values())
    for p in ports:
        kind = t if p["dir"] == "input" else ("logic" if sv else "wire")
        if p["dir"] == "inout":
            kind = "wire"
        shape = shapes[p["name"]].ljust(sw)
        out.append(("  " + kind.ljust(5) + " " + (shape + " " if sw else "") + p["name"] + ";\n"))
    nw = max(len(p["name"]) for p in ports)
    conns = ",\n".join(f"    .{p['name'].ljust(nw)}({p['name']})" for p in ports)
    out.append(f"\n  {dut} dut (\n{conns}\n  );\n\n")
    if clk:
        out.append(f"  always #{num(half)} {clk} = ~{clk};   // {num(500.0 / half)} MHz, the config's clock period\n\n")
    out.append("  initial begin\n"
               f"    $dumpfile(\"{name}.vcd\");\n"
               f"    $dumpvars(0, {name});\n")
    # Start values here rather than on the declarations: Verilator warns
    # about a variable that has both (PROCASSINIT).
    for p in ports:
        if p["dir"] == "input":
            out.append(f"    {p['name']} = {1 if p['name'] == rst and not active_low else 0};\n")
    if rst:
        out.append(f"    #{num(4 * half)} {rst} = {1 if active_low else 0};   // release the reset after two clock cycles\n")
    ins = [p for p in ports if p["dir"] == "input" and p["name"] not in (clk, rst)]
    outs = [p for p in ports if p["dir"] == "output"]
    out.append("    // Drive the inputs and check the outputs, for example:\n")
    if ins:
        out.append(f"    // {ins[0]['name']} = 1;  #{num(2 * half)};\n")
    if outs:
        o = outs[0]["name"]
        out.append(f"    // if ({o} !== 1) $display(\"FAIL: {o} = %h\", {o});\n")
    out.append(f"    #{num(100 * half)};\n")
    if outs:
        # Print every output once at the end, so the run says something.
        fmt_ = ", ".join(f"{p['name']} = %h" for p in outs)
        out.append(f"    $display(\"{dut} at the end: {fmt_}\", {', '.join(p['name'] for p in outs)});\n")
    out.append("    $finish;\n"
               "  end\n"
               "endmodule\n")
    return "".join(out)


def header_template(name: str) -> str:
    guard = re.sub(r"\W", "_", name).upper() + "_VH"
    return (f"`ifndef {guard}\n`define {guard}\n\n"
            "// Shared `define macros and parameters. Pull this file in with\n"
            f"// `include \"{name}\" from the modules that need it.\n\n"
            "`endif\n")


def memory_template(name: str) -> str:
    return ("// Initial memory contents, one word per line in hex.\n"
            f"// Load it from Verilog with $readmemh(\"{name}\", mem);\n"
            "00\n")


# kind -> (folder, extension or None for "name has its own", role)
KINDS = {
    "module_v": ("src", ".v"),
    "module_sv": ("src", ".sv"),
    "tb_v": ("verify", ".v"),
    "tb_sv": ("verify", ".sv"),
    "header_vh": ("src", ".vh"),
    "header_svh": ("src", ".svh"),
    "sdc": ("src", ".sdc"),
    "pins": ("", ".cfg"),
    "memory": ("src", ".hex"),
    "other": ("", None),
}
_NAME_RX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FILE_RX = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]*$")


def new_file(design_dir: str | Path, kind: str, name: str, *, top: Optional[str] = None,
             clock: Optional[str] = None, use: bool = True) -> Dict[str, Any]:
    """Create a starter file of *kind* named *name* and, with *use*, point the
    config at it: a new design module joins VERILOG_FILES (unless a glob
    already covers it), an SDC becomes PNR_SDC_FILE and SIGNOFF_SDC_FILE,
    a pin file becomes IO_PIN_ORDER_CFG.

    Returns ``{ok, rel, abs, config: {changed, name}|None, config_error}``.
    """
    if kind not in KINDS:
        return {"ok": False, "error": f"unknown kind '{kind}'"}
    folder, ext = KINDS[kind]
    name = (name or "").strip()
    if kind.startswith(("module", "tb")):
        if not _NAME_RX.match(name):
            return {"ok": False, "error": "Module names use letters, digits and _, and can't start with a digit."}
        fname = name + ext
    else:
        if ext and name.lower().endswith(ext):
            name = name[: -len(ext)]
        fname = name + (ext or "")
        if not _FILE_RX.match(fname) or (ext is None and Path(fname).suffix.lower() not in EDITABLE_EXTS):
            return {"ok": False, "error": "Use letters, digits, - _ and . in the file name"
                    + ("" if ext else ", with an extension LanEx can edit (.txt, .md, .tcl, .json, .yaml …).")}
    rel = f"{folder}/{fname}" if folder else fname
    target = _resolve_inside(design_dir, rel)
    if target is None:
        return {"ok": False, "error": "That path is outside the project."}
    if target.exists():
        return {"ok": False, "error": f"{rel} already exists."}

    if kind in ("module_v", "module_sv"):
        content = module_template(name, kind == "module_sv")
    elif kind in ("tb_v", "tb_sv"):
        # Instantiate the real top module, ports and all, so the bench runs
        # as soon as it's created.
        src = find_module_file(design_dir, top) if top else None
        ports, params, period = [], [], None
        if src is not None:
            text = src.read_text(encoding="utf-8", errors="replace")
            ports, params = module_ports(text, top), module_params(text, top)
        try:
            p = configedit.read_config(design_dir)["data"].get("CLOCK_PERIOD")
            period = float(p) if isinstance(p, (int, float)) and p > 0 else None
        except Exception:
            period = None
        content = testbench_template(name, kind == "tb_sv", top, ports, clock, period, params)
    elif kind.startswith("header"):
        content = header_template(fname)
    elif kind == "sdc":
        content = sdc_template(top or "this design")
    elif kind == "pins":
        ports = find_module_ports(design_dir, top) if top else []
        if not ports:
            return {"ok": False, "error": "LanEx needs the top module's ports to write a pin order. "
                    "Set the top module on the Setup page first."}
        content = pins_template(top, ports, clock)
    elif kind == "memory":
        content = memory_template(fname)
    else:
        content = ""

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    out: Dict[str, Any] = {"ok": True, "rel": rel, "abs": str(target), "config": None, "config_error": None}
    if not use:
        return out
    try:
        if kind in ("module_v", "module_sv"):
            info = configedit.read_config(design_dir)
            cur = configedit.resolve_sources(design_dir, info["data"]) if info["editable"] else None
            if cur and cur["mode"] == "list":
                if str(target.resolve()) in cur["files"]:   # a glob already covers it
                    out["config"] = {"changed": [], "name": info["name"]}
                else:
                    res = configedit.set_sources(design_dir, cur["files"] + [str(target)])
                    out["config"] = {"changed": res["changed"], "name": res["name"]}
        elif kind == "sdc":
            v = "dir::" + rel
            res = configedit.set_keys(design_dir, {"PNR_SDC_FILE": v, "SIGNOFF_SDC_FILE": v})
            out["config"] = {"changed": res["changed"], "name": res["name"]}
        elif kind == "pins":
            res = configedit.set_keys(design_dir, {"IO_PIN_ORDER_CFG": "dir::" + rel})
            out["config"] = {"changed": res["changed"], "name": res["name"]}
    except configedit.ConfigEditError as ex:
        out["config_error"] = str(ex)
    return out
