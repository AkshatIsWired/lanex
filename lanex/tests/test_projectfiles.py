"""projectfiles: file roles, port parsing, starter files and config wiring."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

from lanex.controller import projectfiles


ANSI = """
// a comment with module fake(input x);
module alu #(parameter W = (8), parameter N = 2) (
    input  wire          clk,
    input  wire          rst_n,
    input  wire [W-1:0]  a, b,   // two buses
    input  logic signed [3:0] op,
    output reg  [W-1:0]  y,
    output wire          zero,
    inout  wire          sda
);
endmodule
"""

CLASSIC = """
module spm(clk, rst, x, a, y);
    parameter bits = 32;
    input clk, rst;
    input x;
    input [bits-1:0] a;
    output y;
endmodule
"""


def test_ansi_ports():
    got = projectfiles.module_ports(ANSI, "alu")
    assert [(p["name"], p["dir"], p["bus"]) for p in got] == [
        ("clk", "input", False), ("rst_n", "input", False), ("a", "input", True), ("b", "input", True),
        ("op", "input", True), ("y", "output", True), ("zero", "output", False), ("sda", "inout", False)]


def test_classic_ports():
    got = projectfiles.module_ports(CLASSIC, "spm")
    assert [(p["name"], p["dir"], p["bus"]) for p in got] == [
        ("clk", "input", False), ("rst", "input", False), ("x", "input", False),
        ("a", "input", True), ("y", "output", False)]


def test_missing_module_or_portless():
    assert projectfiles.module_ports(ANSI, "nope") == []
    assert projectfiles.module_ports("module tb; endmodule", "tb") == []


def _librelane_parser():
    try:
        import librelane
    except ImportError:
        return None
    p = Path(librelane.__file__).parent / "scripts" / "odbpy" / "ioplace_parser" / "parse.py"
    if not p.is_file():
        return None
    spec = importlib.util.spec_from_file_location("ll_ioplace_parse", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pin_template_matches_every_pin_exactly_once():
    ports = projectfiles.module_ports(ANSI, "alu")
    text = projectfiles.pins_template("alu", ports, "clk")
    pins = ["clk", "rst_n", "zero", "sda"] + [f"{n}[{i}]" for n in ("a", "b", "y") for i in range(8)] + \
        [f"op[{i}]" for i in range(4)]
    parser = _librelane_parser()
    if parser is not None:
        sides = parser.parse(text)          # LibreLane's own parser must accept it
        regexes = [r for s in sides.values() for r in s.pins]
        assert sides["S"].pins[:2] == [r"clk(\[\d+\])?", r"rst_n(\[\d+\])?"]
    else:
        regexes = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    # LibreLane anchors each regex (^...$) and errors if a pin matches two.
    for pin in pins:
        hits = [r for r in regexes if re.match(f"^{r}$", pin)]
        assert len(hits) == 1, (pin, hits)
    assert not any(re.match(f"^{r}$", "rst_n_sync") for r in regexes)


def test_sdc_template_is_librelane_default_with_a_header():
    text = projectfiles.sdc_template("alu")
    assert text.startswith("# Timing constraints for alu.")
    assert "create_clock" in text and "$::env(CLOCK_PERIOD)" in text


@pytest.fixture
def design(tmp_path):
    d = tmp_path / "chip"
    (d / "src").mkdir(parents=True)
    (d / "verify").mkdir()
    (d / "src" / "alu.v").write_text(ANSI)
    (d / "verify" / "alu_tb.v").write_text("module alu_tb; endmodule\n")
    (d / "config.yaml").write_text(
        "DESIGN_NAME: alu\nVERILOG_FILES:\n  - dir::src/alu.v\nCLOCK_PORT: clk\nCLOCK_PERIOD: 10\n")
    return d


def _cfg(d):
    return yaml.safe_load((d / "config.yaml").read_text())


def test_list_files_roles(design):
    (design / "src" / "defs.vh").write_text("")
    (design / "src" / "rom.hex").write_text("00\n")
    (design / ".gui-macros.json").write_text("{}")
    (design / "runs" / "r1").mkdir(parents=True)
    (design / "runs" / "r1" / "x.v").write_text("")
    got = {f["rel"]: f for f in projectfiles.list_files(design)["files"]}
    assert set(got) == {"config.yaml", "src/alu.v", "src/defs.vh", "src/rom.hex", "verify/alu_tb.v"}
    assert got["src/alu.v"]["role"] == "design" and got["src/alu.v"]["in_verilog_files"]
    assert got["verify/alu_tb.v"]["role"] == "testbench" and not got["verify/alu_tb.v"]["in_verilog_files"]
    assert got["src/defs.vh"]["role"] == "header" and got["src/rom.hex"]["role"] == "memory"
    assert got["config.yaml"]["role"] == "config"


def test_new_module_joins_explicit_source_list(design):
    res = projectfiles.new_file(design, "module_sv", "fifo")
    assert res["ok"] and res["rel"] == "src/fifo.sv" and res["config"]["changed"] == ["VERILOG_FILES"]
    assert _cfg(design)["VERILOG_FILES"] == ["dir::src/alu.v", "dir::src/fifo.sv"]
    assert "always_ff" in (design / "src" / "fifo.sv").read_text()


def test_new_module_under_a_glob_leaves_config_alone(design):
    (design / "config.yaml").write_text("DESIGN_NAME: alu\nVERILOG_FILES: dir::src/*.v\n")
    res = projectfiles.new_file(design, "module_v", "fifo")
    assert res["ok"] and res["config"]["changed"] == []
    assert _cfg(design)["VERILOG_FILES"] == "dir::src/*.v"


def test_new_testbench_never_touches_sources(design):
    res = projectfiles.new_file(design, "tb_v", "fifo_tb", top="alu")
    assert res["ok"] and res["rel"] == "verify/fifo_tb.v" and res["config"] is None
    assert _cfg(design)["VERILOG_FILES"] == ["dir::src/alu.v"]


def test_new_sdc_is_used_for_pnr_and_signoff(design):
    res = projectfiles.new_file(design, "sdc", "impl.sdc", top="alu")
    assert res["ok"] and res["rel"] == "src/impl.sdc"
    cfg = _cfg(design)
    assert cfg["PNR_SDC_FILE"] == cfg["SIGNOFF_SDC_FILE"] == "dir::src/impl.sdc"
    files = {f["rel"]: f for f in projectfiles.list_files(design)["files"]}
    assert files["src/impl.sdc"]["used_by"] == ["PNR_SDC_FILE", "SIGNOFF_SDC_FILE"]


def test_new_pin_order_from_top_ports(design):
    res = projectfiles.new_file(design, "pins", "pin_order", top="alu", clock="clk")
    assert res["ok"] and res["rel"] == "pin_order.cfg"
    assert _cfg(design)["IO_PIN_ORDER_CFG"] == "dir::pin_order.cfg"
    assert "#S" in (design / "pin_order.cfg").read_text()


def test_new_file_refusals(design):
    assert not projectfiles.new_file(design, "module_v", "1bad")["ok"]
    assert not projectfiles.new_file(design, "module_v", "alu")["ok"]          # exists
    assert not projectfiles.new_file(design, "pins", "p", top="nope")["ok"]    # no ports
    assert not projectfiles.new_file(design, "other", "../escape.txt")["ok"]
    assert not projectfiles.new_file(design, "other", "prog.exe")["ok"]
    assert not projectfiles.new_file(design, "bogus", "x")["ok"]
    assert projectfiles.new_file(design, "other", "notes.md")["ok"]


def test_use_false_writes_file_only(design):
    before = (design / "config.yaml").read_text()
    res = projectfiles.new_file(design, "sdc", "try", top="alu", use=False)
    assert res["ok"] and (design / "src" / "try.sdc").is_file()
    assert (design / "config.yaml").read_text() == before


def test_tcl_config_file_still_created_with_config_error(design):
    (design / "config.yaml").unlink()
    (design / "config.tcl").write_text("set ::env(DESIGN_NAME) alu\n")
    res = projectfiles.new_file(design, "sdc", "impl", top="alu")
    assert res["ok"] and res["config_error"] and "Tcl" in res["config_error"]
