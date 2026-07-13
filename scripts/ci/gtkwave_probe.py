#!/usr/bin/env python3
# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""GTKWave handoff probe — end-to-end fidelity of the waveform pipeline.

Proves, against a REAL simulation and a REAL GTKWave, that:

  G1  the product's own sim endpoint produces a fresh VCD for the design,
  G2  that VCD's data is truthful (an independent parser — NOT waveview.py —
      recovers exactly the counter sequence the testbench computes),
  G3  the product parser (waveview.vcd_signals) agrees with the independent
      parser on every signal name and width,
  G4  the save file the /api/ide/open-wave endpoint generates references the
      exact dump and lists every signal,
  G5  the endpoint actually launches GTKWave (a real process on the display),
  G6  REAL GTKWave, launched with the product's own argv, displays the same
      traces and — sampled at 5 marker times — the same VALUES the simulator
      wrote. This is the "what the user sees in GTKWave == what the simulator
      computed" gate; nothing here trusts LanEx's own code to check itself.

Needs: iverilog + gtkwave on PATH, a display (CI: `xvfb-run -a`), and the repo
importable (PYTHONPATH or `pip install .`). Stdlib only. Exit 0 = all gates
pass. Writes a GitHub Actions step summary when GITHUB_STEP_SUMMARY is set.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[2]

# The known-answer design: a 4-bit counter, reset for 12 ns, clock period
# 10 ns, $finish at 100 ns → q steps 0,1,2,…,9 at successive posedges. The
# expected VALUES are arithmetic, so no oracle file can drift.
COUNTER_V = """\
module counter(input clk, input rst, output reg [3:0] q);
  always @(posedge clk) begin
    if (rst) q <= 4'd0;
    else     q <= q + 4'd1;
  end
endmodule
"""
TB_V = """\
`timescale 1ns/1ns
module tb_counter;
  reg clk = 1'b0;
  reg rst = 1'b1;
  wire [3:0] q;
  counter dut(.clk(clk), .rst(rst), .q(q));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("dump.vcd");
    $dumpvars(0, tb_counter);
    #12 rst = 1'b0;
    #88 $finish;
  end
endmodule
"""

# Sample the DUT register between posedges (posedge at 15+10k ⇒ settle at 16+10k).
SAMPLE_TIMES = [16, 36, 56, 76, 96]
Q_FULL = "tb_counter.dut.q[3:0]"

# After alias-dedupe (what waveview and the save file carry). iverilog maps
# tb_counter.clk/dut.clk (and rst) to ONE id code each — one value stream,
# two hierarchical names; the first name wins.
EXPECTED_SIGNALS: List[Tuple[str, int]] = [
    ("tb_counter.q[3:0]", 4),
    ("tb_counter.clk", 1),
    ("tb_counter.rst", 1),
    ("tb_counter.dut.q[3:0]", 4),
]

# Every $var as written, aliases included (what the raw header really holds).
EXPECTED_ALL_NAMES = {
    "tb_counter.q[3:0]", "tb_counter.clk", "tb_counter.rst",
    "tb_counter.dut.clk", "tb_counter.dut.rst", "tb_counter.dut.q[3:0]",
}


# ---------------------------------------------------------------------------
# Independent VCD parser (deliberately NOT waveview.py — this is the second
# opinion the differential needs). Header + full value-change timeline.
# ---------------------------------------------------------------------------

def parse_vcd(text: str) -> Dict[str, object]:
    """Return {"signals": [(full_name, width)…], "timeline": {full_name: [(t, int|None)…]}}.

    Vector values parse to ints (None for x/z); aliased id codes attach the
    SAME timeline to every name that shares the code (that's what an alias
    means in a VCD — one value stream, many hierarchical names)."""
    head, sep, changes = text.partition("$enddefinitions")
    if not sep:
        raise ValueError("not a VCD: no $enddefinitions")
    scopes: List[str] = []
    id_names: Dict[str, List[str]] = {}
    id_width: Dict[str, int] = {}
    signals: List[Tuple[str, int]] = []
    toks = head.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "$scope":
            scopes.append(toks[i + 2])
            while toks[i] != "$end":
                i += 1
        elif t == "$upscope":
            scopes.pop()
            while toks[i] != "$end":
                i += 1
        elif t == "$var":
            j = i + 1
            fields: List[str] = []
            while toks[j] != "$end":
                fields.append(toks[j])
                j += 1
            width, ident, ref = int(fields[1]), fields[2], "".join(fields[3:])
            full = ".".join(scopes + [ref])
            id_names.setdefault(ident, []).append(full)
            id_width[ident] = width
            signals.append((full, width))
            i = j
        i += 1

    timeline: Dict[str, List[Tuple[int, Optional[int]]]] = {n: [] for n, _ in signals}

    def push(ident: str, t: int, val: Optional[int]) -> None:
        for name in id_names.get(ident, []):
            tl = timeline[name]
            if tl and tl[-1][0] == t:
                tl[-1] = (t, val)
            else:
                tl.append((t, val))

    now = 0
    for line in changes.splitlines():
        s = line.strip()
        if not s or s.startswith("$"):
            continue
        if s[0] == "#":
            now = int(s[1:])
        elif s[0] in "01xzXZ":
            c = s[0].lower()
            push(s[1:], now, None if c in "xz" else int(c))
        elif s[0] in "bB":
            bits, _, ident = s[1:].partition(" ")
            try:
                val: Optional[int] = int(bits, 2)
            except ValueError:
                val = None  # contains x/z
            push(ident.strip(), now, val)
    return {"signals": signals, "timeline": timeline}


def value_at(timeline: List[Tuple[int, Optional[int]]], t: int) -> Optional[int]:
    """The signal's value at time *t* (last change at or before t)."""
    v: Optional[int] = None
    for ct, cv in timeline:
        if ct > t:
            break
        v = cv
    return v


def dedupe_by_first_alias(signals: List[Tuple[str, int]],
                          vcd_text: str) -> List[Tuple[str, int]]:
    """What waveview's id-dedupe SHOULD produce: first name per id code."""
    head = vcd_text.partition("$enddefinitions")[0]
    seen: set = set()
    out: List[Tuple[str, int]] = []
    scopes: List[str] = []
    toks = head.split()
    i = 0
    while i < len(toks):
        t = toks[i]
        if t == "$scope":
            scopes.append(toks[i + 2])
            while toks[i] != "$end":
                i += 1
        elif t == "$upscope":
            scopes.pop()
            while toks[i] != "$end":
                i += 1
        elif t == "$var":
            j = i + 1
            fields: List[str] = []
            while toks[j] != "$end":
                fields.append(toks[j])
                j += 1
            ident = fields[2]
            if ident not in seen:
                seen.add(ident)
                out.append((".".join(scopes + ["".join(fields[3:])]), int(fields[1])))
            i = j
        i += 1
    return out


def leaf(name: str) -> str:
    """GTKWave's trace pane shows leaf names (`q[3:0]`, not `tb.q[3:0]`)."""
    return name.rsplit(".", 1)[-1]


VERIFY_TCL = """\
puts "PROBE dumpfile=[gtkwave::getDumpFileName]"
set nt [gtkwave::getTotalNumTraces]
puts "PROBE numtraces=$nt"
for {set i 0} {$i < $nt} {incr i} {
    puts "PROBE trace=[gtkwave::getTraceNameFromIndex $i]"
}
foreach t {%s} {
    gtkwave::setMarker $t
    set v [gtkwave::getTraceValueAtMarkerFromName "%s"]
    puts "PROBE value@$t=$v"
}
exit
"""


def make_verify_tcl(sample_times: List[int], full_name: str) -> str:
    esc = full_name.replace("[", "\\[").replace("]", "\\]")
    return VERIFY_TCL % (" ".join(str(t) for t in sample_times), esc)


def parse_probe_output(text: str) -> Dict[str, object]:
    """PROBE lines → {"dumpfile", "traces": […], "values": {t: int}}."""
    out: Dict[str, object] = {"dumpfile": None, "traces": [], "values": {}}
    for line in text.splitlines():
        if not line.startswith("PROBE "):
            continue
        body = line[len("PROBE "):]
        key, _, val = body.partition("=")
        if key == "dumpfile":
            out["dumpfile"] = val
        elif key == "trace":
            out["traces"].append(val)  # type: ignore[union-attr]
        elif key.startswith("value@"):
            t = int(key[len("value@"):])
            # Traces are loaded with the hex flag (@22) — GTKWave reports the
            # marker value in that radix.
            try:
                out["values"][int(t)] = int(val.strip(), 16)  # type: ignore[index]
            except ValueError:
                out["values"][int(t)] = None  # type: ignore[index]
    return out


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

class Gate:
    def __init__(self, key: str, what: str, proves: str) -> None:
        self.key, self.what, self.proves = key, what, proves
        self.ok: Optional[bool] = None
        self.detail = ""

    def set(self, ok: bool, detail: str = "") -> None:
        self.ok = ok
        self.detail = detail
        print(f"[{'PASS' if ok else 'FAIL'}] {self.key}: {self.what}"
              + (f" — {detail}" if detail else ""), flush=True)


GATES = [
    Gate("G1", "product sim endpoint produces a fresh VCD",
         "The IDE's Simulate button really runs the simulator and reports the dump it wrote."),
    Gate("G2", "VCD data is truthful (independent parse == the arithmetic the RTL computes)",
         "The dump handed to viewers contains the values the simulator computed — checked without any LanEx parser."),
    Gate("G3", "waveview.vcd_signals == independent parser (names + widths)",
         "The product's VCD header parser can't drop, rename, or mis-size a signal."),
    Gate("G4", "endpoint save file references the exact dump + lists every signal",
         "GTKWave is pointed at the right file with the right signal list — no stale/foreign data."),
    Gate("G5", "endpoint launches a real GTKWave process",
         "The one-click 'Open in GTKWave' genuinely opens the viewer on a real display."),
    Gate("G6", "REAL GTKWave shows the same traces and marker VALUES the simulator wrote",
         "What the user reads in GTKWave equals the simulation data — the full in/out fidelity proof."),
]


def summary(gates: List[Gate]) -> str:
    ok_all = all(g.ok for g in gates)
    lines = [
        "## GTKWave handoff probe (real sim → real GTKWave)",
        "",
        ("**✓ all gates passed**" if ok_all else "**✗ FAILING**")
        + " — a 4-bit counter is simulated through LanEx's own sim endpoint; the dump, "
          "the generated save file, and GTKWave's on-screen traces/values are then "
          "cross-checked against an independent VCD parse.",
        "",
        "| Gate | Check | Result | What it proves |",
        "|---|---|---|---|",
    ]
    for g in gates:
        res = "✓ pass" if g.ok else ("✗ FAIL" if g.ok is False else "– skipped")
        det = f" — {g.detail}" if (g.detail and not g.ok) else ""
        lines.append(f"| {g.key} | {g.what}{det} | {res} | {g.proves} |")
    lines.append("")
    return "\n".join(lines) + "\n"


def write_summary(text: str) -> None:
    dest = os.environ.get("GITHUB_STEP_SUMMARY")
    if dest:
        with open(dest, "a", encoding="utf-8") as fh:
            fh.write(text)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:  # noqa: C901 - a linear script, kept in one place on purpose
    g1, g2, g3, g4, g5, g6 = GATES

    for tool in ("iverilog", "vvp", "gtkwave"):
        if not any(os.access(os.path.join(p, tool), os.X_OK)
                   for p in os.environ.get("PATH", "").split(os.pathsep) if p):
            print(f"missing tool: {tool} — install it before running this probe",
                  file=sys.stderr)
            return 2
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("no display — run under `xvfb-run -a`", file=sys.stderr)
        return 2

    sys.path.insert(0, str(REPO))
    from lanex.controller import desktop, simulate, waveview
    from lanex.server.app import make_server

    d = Path(tempfile.mkdtemp(prefix="lanex-gtkwave-probe-"))
    (d / "src").mkdir()
    (d / "src" / "counter.v").write_text(COUNTER_V)
    (d / "tb_counter.v").write_text(TB_V)

    httpd, port = make_server(port=8975)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def post(path: str, body: dict) -> dict:
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "X-Requested-With": "XMLHttpRequest"})
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read())
        return payload.get("data", payload)

    # --- G1: the product's own sim path produces the VCD -------------------
    post("/api/set-design-dir", {"path": str(d)})
    started = time.time()
    r = post("/api/sim/start", {"testbench": "tb_counter.v",
                                "sources": ["src/counter.v"],
                                "sim_engine": "iverilog"})
    if not r.get("ok"):
        g1.set(False, f"sim/start refused: {r}")
    else:
        for _ in range(120):
            if not simulate.job.running:
                break
            time.sleep(0.5)
        dump = d / "dump.vcd"
        fresh = dump.is_file() and dump.stat().st_mtime >= started - 1
        g1.set(bool(fresh), f"{dump} {'fresh' if fresh else 'missing/stale'}")
    if not g1.ok:
        write_summary(summary(GATES))
        return 1
    dump = d / "dump.vcd"
    vcd_text = dump.read_text()

    # --- G2: independent truth of the dump ---------------------------------
    ind = parse_vcd(vcd_text)
    tl = ind["timeline"][Q_FULL]  # type: ignore[index]
    got_seq = [v for _, v in tl if v is not None]
    want_seq = list(range(0, 10))  # reset → 0, then +1 per posedge to 9
    names_ok = set(n for n, _ in ind["signals"]) == EXPECTED_ALL_NAMES  # type: ignore[union-attr]
    g2.set(got_seq == want_seq and names_ok,
           f"q sequence {got_seq} vs {want_seq}; header {'ok' if names_ok else 'MISMATCH'}")

    # --- G3: product parser vs independent parser --------------------------
    prod = waveview.vcd_signals(dump)
    ref = dedupe_by_first_alias(ind["signals"], vcd_text)  # type: ignore[arg-type]
    g3.set(prod == ref, f"product {prod} vs independent {ref}")

    # --- G4 + G5: the endpoint --------------------------------------------
    r = post("/api/ide/open-wave", {"path": "dump.vcd"})
    save = d / ".lanex-wave.gtkw"
    if not r.get("ok"):
        g4.set(False, f"open-wave refused: {r}")
        g5.set(False, "endpoint failed")
    else:
        body = save.read_text() if save.is_file() else ""
        refs_dump = f'[dumpfile] "{dump.resolve()}"' in body
        has_all = all(name in body for name, _ in EXPECTED_SIGNALS)
        g4.set(refs_dump and has_all,
               f"dumpfile-ref={refs_dump} all-signals={has_all} signals={r.get('signals')}")
        time.sleep(2.5)
        pid = None
        try:
            out = subprocess.run(["pgrep", "-f", r"gtkwave.*\.lanex-wave\.gtkw"],
                                 capture_output=True, text=True).stdout.split()
            pid = int(out[0]) if out else None
        except Exception:
            pid = None
        g5.set(pid is not None, f"pid={pid}")
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    # --- G6: empirical — REAL gtkwave reports traces + marker values -------
    # Launch with the argv the PRODUCT builds (same code path as the endpoint),
    # plus a verification Tcl script that dumps what is actually on screen.
    tcl = d / "verify.tcl"
    tcl.write_text(make_verify_tcl(SAMPLE_TIMES, Q_FULL))
    argv = desktop._build_argv("gtkwave", "gtkwave", str(dump),
                               {"gtkw_save": str(save)}, False)
    argv += ["-S", str(tcl)]
    proc = subprocess.run(argv, cwd=str(d), capture_output=True, text=True,
                          timeout=120)
    probe = parse_probe_output(proc.stdout)
    exp_leafs = [leaf(n) for n, _ in EXPECTED_SIGNALS]
    traces_ok = probe["traces"] == exp_leafs
    dump_ok = Path(str(probe["dumpfile"] or "")).name == dump.name
    vals = probe["values"]  # type: ignore[assignment]
    exp_vals = {t: value_at(tl, t) for t in SAMPLE_TIMES}
    vals_ok = vals == exp_vals
    g6.set(bool(traces_ok and dump_ok and vals_ok),
           f"traces={probe['traces']} vs {exp_leafs}; "
           f"values={vals} vs {exp_vals}; dump={probe['dumpfile']}")

    write_summary(summary(GATES))
    return 0 if all(g.ok for g in GATES) else 1


if __name__ == "__main__":
    sys.exit(main())
