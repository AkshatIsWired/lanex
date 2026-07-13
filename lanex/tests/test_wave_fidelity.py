# Copyright 2026 LanEx Contributors
"""Waveform-data fidelity against the committed golden VCD.

``goldens/sim_run/dump.vcd`` is a REAL Icarus Verilog dump of the bundled
4-bit-counter testbench (sources sit next to it for provenance). These tests
prove — hermetically, no simulator needed — that every parser in the waveform
pipeline recovers exactly the data the simulator wrote:

* the independent reference parser (scripts/ci/gtkwave_probe.py — used by the
  CI probe as the second opinion) reads the true counter sequence,
* the product's GTKWave-handoff parser (controller/waveview.py) agrees with it
  on every signal name and width,
* the generated ``.gtkw`` save file carries those exact signals and the exact
  dump path.

The in-browser viewer's parser (modules/ide/vcd.js) is held to the same golden
by frontend_test.mjs — so the canvas viewer, the GTKWave handoff, and the CI
reference all read ONE fixture and must agree.
"""
from __future__ import annotations

import sys
from pathlib import Path

from lanex.controller import waveview

_SC = Path(__file__).resolve().parents[2] / "scripts" / "ci"
if str(_SC) not in sys.path:
    sys.path.insert(0, str(_SC))

import gtkwave_probe  # noqa: E402

GOLDEN = Path(__file__).parent / "goldens" / "sim_run" / "dump.vcd"

# What the RTL computes: reset drives q to 0, then +1 per posedge until
# $finish — arithmetic, so the oracle can't drift.
EXPECTED_Q = list(range(0, 10))

EXPECTED_DEDUPED = [
    ("tb_counter.q[3:0]", 4),
    ("tb_counter.clk", 1),
    ("tb_counter.rst", 1),
    ("tb_counter.dut.q[3:0]", 4),
]


def test_golden_fixture_exists_and_is_a_vcd():
    text = GOLDEN.read_text()
    assert "$enddefinitions" in text and "$var" in text


def test_independent_parser_recovers_the_simulated_sequence():
    ind = gtkwave_probe.parse_vcd(GOLDEN.read_text())
    tl = ind["timeline"]["tb_counter.dut.q[3:0]"]
    got = [v for _, v in tl if v is not None]
    assert got == EXPECTED_Q, f"golden dump no longer carries the counter data: {got}"
    # The clock really toggles: strictly alternating 0/1 after the initial value.
    clk = [v for _, v in ind["timeline"]["tb_counter.clk"] if v is not None]
    assert all(a != b for a, b in zip(clk, clk[1:])) and len(clk) >= 10


def test_product_parser_agrees_with_independent_reference():
    prod = waveview.vcd_signals(GOLDEN)
    ind = gtkwave_probe.parse_vcd(GOLDEN.read_text())
    ref = gtkwave_probe.dedupe_by_first_alias(ind["signals"], GOLDEN.read_text())
    assert prod == ref == EXPECTED_DEDUPED


def test_alias_dedupe_keeps_one_stream_per_id():
    # The raw header holds 6 $var entries (dut.clk/dut.rst alias the tb nets);
    # the product must show 4 — one per value stream — or the wave pane
    # duplicates every aliased net.
    ind = gtkwave_probe.parse_vcd(GOLDEN.read_text())
    assert len(ind["signals"]) == 6
    assert len(waveview.vcd_signals(GOLDEN)) == 4


def test_save_file_for_golden_names_the_exact_dump(tmp_path):
    sigs = waveview.vcd_signals(GOLDEN)
    out = waveview.write_gtkw(tmp_path / "g.gtkw", GOLDEN, sigs)
    body = Path(out).read_text()
    assert f'[dumpfile] "{GOLDEN.resolve()}"' in body
    for name, _ in EXPECTED_DEDUPED:
        assert name in body


def test_value_at_semantics():
    # value_at is the oracle the CI probe compares GTKWave's markers against —
    # it must implement "last change at or before t" exactly.
    tl = [(5, 0), (15, 1), (25, 2)]
    va = gtkwave_probe.value_at
    assert va(tl, 4) is None and va(tl, 5) == 0 and va(tl, 16) == 1 and va(tl, 99) == 2


def test_probe_output_parser_and_tcl_shape():
    tcl = gtkwave_probe.make_verify_tcl([16, 36], "tb.q[3:0]")
    assert "gtkwave::setMarker" in tcl and "tb.q\\[3:0\\]" in tcl and "exit" in tcl
    parsed = gtkwave_probe.parse_probe_output(
        "PROBE dumpfile=dump.vcd\nPROBE numtraces=2\nPROBE trace=clk\n"
        "PROBE trace=q[3:0]\nPROBE value@16=1\nPROBE value@36=a\nnoise\n")
    assert parsed["dumpfile"] == "dump.vcd"
    assert parsed["traces"] == ["clk", "q[3:0]"]
    assert parsed["values"] == {16: 1, 36: 10}  # hex radix (@22 traces)
