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
"""The Cells tab backend: library readers (Liberty, LEF, GDS, PDK config),
the macro catalog and RTL checks, and the per-run macro overlay extras."""
from __future__ import annotations

import json
import struct
from pathlib import Path

from lanex.controller import celllib, custommacros, customcells, macrolib

LIB = r'''
library (tiny) {
  time_unit : "1ns";
  leakage_power_unit : "1nW";
  capacitive_load_unit (1.0, pf);
  cell ("t__nand2_1") {
    area : 3.75;
    cell_leakage_power : 0.002;
    pin ("A") { direction : "input"; capacitance : 0.0023; }
    pin ("B") { direction : "input"; capacitance : 0.0024; }
    pin ("Y") {
      direction : "output";
      function : "(!A) | (!B)";
      timing () {
        related_pin : "A";
        timing_sense : "negative_unate";
        cell_rise ("delay_template") {
          index_1 ("0.01, 0.1");
          index_2 ("0.001, 0.01");
          values ("0.05, 0.10", "0.07, 0.12");
        }
      }
    }
  }
  cell ("t__dfrtp_1") {
    area : 25.0;
    ff ("IQ", "IQ_N") { clocked_on : "CLK"; next_state : "D"; clear : "!RESET_B"; }
    pin ("CLK") { direction : "input"; clock : "true"; capacitance : 0.002; }
    pin ("D") { direction : "input"; capacitance : 0.002; }
    pin ("RESET_B") { direction : "input"; capacitance : 0.002; }
    pin ("Q") { direction : "output"; function : "IQ"; }
  }
}
'''

LEF = '''VERSION 5.7 ;
PROPERTYDEFINITIONS
  MACRO CatenaDesignType STRING ;
END PROPERTYDEFINITIONS
SITE unit
  CLASS CORE ;
  SIZE 0.46 BY 2.72 ;
END unit
MACRO t__nand2_1
  CLASS CORE ;
  SIZE 1.38 BY 2.72 ;
  SITE unit ;
  PIN A
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER li1 ;
        RECT 0.1 0.1 0.3 0.5 ;
    END
  END A
  PIN VPWR
    DIRECTION INOUT ;
    USE POWER ;
  END VPWR
END t__nand2_1
END LIBRARY
'''


def _gds(path: Path, cell: str) -> None:
    """A minimal GDS: one structure with one boundary on 68/20 and a text."""
    def rec(rt, dt, payload=b""):
        return struct.pack(">HBB", 4 + len(payload), rt, dt) + payload

    def real8(x):
        # GDS excess-64 base-16 real
        if x == 0:
            return b"\0" * 8
        exp = 64
        while x >= 1:
            x /= 16
            exp += 1
        while x < 1 / 16:
            x *= 16
            exp -= 1
        return bytes([exp]) + int(x * (1 << 56)).to_bytes(7, "big")
    name = cell.encode() + (b"\0" if len(cell) % 2 else b"")
    xy = struct.pack(">10i", 0, 0, 1000, 0, 1000, 2720, 0, 2720, 0, 0)
    data = (rec(0x00, 0x02, struct.pack(">h", 600)) + rec(0x01, 0x02, b"\0" * 24) +
            rec(0x02, 0x06, b"lib\0") + rec(0x03, 0x05, real8(1e-3) + real8(1e-9)) +
            rec(0x05, 0x02, b"\0" * 24) + rec(0x06, 0x06, name) +
            rec(0x08, 0x00) + rec(0x0D, 0x02, struct.pack(">h", 68)) + rec(0x0E, 0x02, struct.pack(">h", 20)) +
            rec(0x10, 0x03, xy) + rec(0x11, 0x00) +
            rec(0x0C, 0x00) + rec(0x0D, 0x02, struct.pack(">h", 67)) + rec(0x16, 0x02, struct.pack(">h", 5)) +
            rec(0x10, 0x03, struct.pack(">2i", 200, 300)) + rec(0x19, 0x06, b"A\0") + rec(0x11, 0x00) +
            rec(0x07, 0x00) + rec(0x04, 0x00))
    path.write_bytes(data)


def _pdk(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "pdks"
    scl = root / "tinyA" / "libs.ref" / "t"
    for sub in ("lib", "lef", "gds", "verilog"):
        (scl / sub).mkdir(parents=True)
    (scl / "lib" / "t__tt_025C_1v80.lib").write_text(LIB)
    (scl / "lef" / "t.lef").write_text(LEF)
    _gds(scl / "gds" / "t.gds", "t__nand2_1")
    (scl / "verilog" / "t.v").write_text(
        "/**\n * nand2: 2-input NAND.\n *\n *        Y = !(A & B)\n *\n * Verilog top module.\n */\n")
    tech = root / "tinyA" / "libs.tech" / "librelane"
    (tech / "t").mkdir(parents=True)
    (tech / "config.tcl").write_text('set ::env(VDD_PIN) "VPWR"\nset ::env(GND_PIN) "VGND"\n')
    (tech / "t" / "config.tcl").write_text(
        'set tmp $::env(STD_CELL_LIBRARY)\n'
        'set ::env(PLACE_SITE) "unit"\n'
        'set ::env(FP_WELLTAP_CELL) "t__tap_1"\n'
        'set ::env(SYNTH_EXCLUDED_CELL_FILE) "$::env(PDK_ROOT)/$::env(PDK)/libs.tech/librelane/$tmp/synth_exclude.cells"\n')
    (tech / "t" / "synth_exclude.cells").write_text("# comment\nt__dfrtp_*\nt__dfrtp_*\n")
    monkeypatch.setattr("lanex.controller.pdk._candidate_pdk_roots", lambda: [root])
    celllib._CACHE.clear()
    return root


def test_library_reads_liberty_lef_desc_and_rules(tmp_path, monkeypatch):
    _pdk(tmp_path, monkeypatch)
    lib = celllib.library("tinyA", "t")
    assert lib["ok"], lib
    rows = {c["cell"]: c for c in lib["cells"]}
    nand = rows["t__nand2_1"]
    assert nand["family"] == "nand2" and nand["drive"] == "1"
    assert nand["desc"] == "2-input NAND." and nand["formula"] == ["Y = !(A & B)"]
    assert nand["sites"] == 3 and abs(nand["in_cap"] - 2.4) < 1e-9          # pF -> fF
    assert nand["category"] == "logic" and not nand["excluded"]
    # PROPERTYDEFINITIONS "MACRO …" is not a cell
    assert "CatenaDesignType" not in rows
    ff = rows["t__dfrtp_1"]
    assert ff["category"] == "flipflop"
    # Tcl locals ($tmp) resolve, duplicate list entries collapse
    assert ff["excluded"]["synth"] == ["t__dfrtp_*"]
    roles = {r["key"]: r for r in lib["rules"]["roles"]}
    assert roles["WELLTAP_CELL"]["cells"] == ["t__tap_1"]      # FP_WELLTAP_CELL migrated
    assert lib["rules"]["vdd"] == "VPWR" and lib["site"]["w"] == 0.46


def test_cell_detail_and_layout(tmp_path, monkeypatch):
    _pdk(tmp_path, monkeypatch)
    d = celllib.cell_detail("tinyA", "t", "t__nand2_1")
    assert d["ok"] and d["arcs"][0]["from"] == "A"
    # values come back in ps: 0.05 ns -> 50 ps
    assert abs(d["arcs"][0]["cell_rise"]["values"][0][0] - 50) < 1e-6
    lay = celllib.cell_layout("tinyA", "t", "t__nand2_1")
    assert lay["ok"], lay
    assert lay["bbox"] == [0, 0, 1.0, 2.72]
    assert lay["layers"][0]["key"] == "68/20" and lay["labels"][0]["text"] == "A"


def test_user_exclusions_come_from_the_design_config(tmp_path, monkeypatch):
    _pdk(tmp_path, monkeypatch)
    design = tmp_path / "proj"
    design.mkdir()
    (design / "config.json").write_text(json.dumps({"DESIGN_NAME": "top", "EXTRA_EXCLUDED_CELLS": ["t__nand2*"]}))
    lib = celllib.library("tinyA", "t", str(design))
    rows = {c["cell"]: c for c in lib["cells"]}
    assert rows["t__nand2_1"]["excluded"]["user"] == ["t__nand2*"]


def test_custom_cell_swap_keeps_config_exclusions(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"EXTRA_EXCLUDED_CELLS": ["mine_*"], "EXTRA_LEFS": ["dir::a.lef"]}))
    import base64
    r = customcells.save_cell(str(tmp_path), "c1", swap_out=["lib_nand2_1"],
                              views={"lef": {"filename": "c1.lef", "content_b64": base64.b64encode(b"MACRO c1").decode()}})
    assert r["ok"], r
    ov = customcells.build_overrides(str(tmp_path))
    # a -c override replaces the config value, so the config's own entries must ride along
    assert ov["EXTRA_EXCLUDED_CELLS"].split() == ["mine_*", "lib_nand2_1"]
    assert ov["EXTRA_LEFS"].split()[0] == "dir::a.lef"


def test_instantiation_template_and_bus_grouping():
    pins = [{"name": f"din[{i}]", "dir": "input", "use": "signal"} for i in range(4)] + [
        {"name": "clk", "dir": "input", "use": "signal"},
        {"name": "dout[0]", "dir": "output", "use": "signal"},
        {"name": "vccd1", "dir": "inout", "use": "power"},
        {"name": "vssd1", "dir": "inout", "use": "ground"}]
    g = macrolib.group_pins(pins)
    assert [p["name"] for p in g] == ["din", "clk", "dout", "vccd1", "vssd1"]
    assert g[0]["width"] == 4 and g[0]["hi"] == 3
    t = macrolib.instantiation("sram", "u_sram", pins)
    assert "`ifdef USE_POWER_PINS" in t and ".din " in t and "[3:0]" in t
    assert t.strip().endswith(");") and ",\n);" not in t.replace("  // output", "")


def test_find_instances_walks_hierarchy_and_flags_models(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "top.v").write_text(
        "module top(input clk);\n  core u_core(.clk(clk));\nendmodule\n"
        "module core(input clk);\n  // sram u_fake(...);\n  sram #(.W(8)) u_mem [1:0] (.clk(clk));\nendmodule\n")
    (tmp_path / "src" / "sram.v").write_text("module sram(input clk); endmodule\n")
    (tmp_path / "config.json").write_text(json.dumps({"DESIGN_NAME": "top", "VERILOG_FILES": "dir::src/*.v"}))
    r = macrolib.find_instances(str(tmp_path), None, ["sram"])
    assert r["ok"] and r["instances"]["sram"] == ["u_core.u_mem[1:0]"]
    assert r["defined_in_sources"]["sram"].endswith("sram.v")


def test_overlay_power_halo_and_corners(tmp_path):
    d = tmp_path
    (d / "config.json").write_text(json.dumps({"PDN_MACRO_CONNECTIONS": ["keep VPWR VGND VDD VSS"]}))
    # a finished-run macro: per-corner lib/spef copied in
    run = tmp_path / "other" / "final"
    for sub in ("gds", "lef", "spef/nom", "lib/nom_tt_025C_1v80"):
        (run / sub).mkdir(parents=True)
    (run / "gds" / "blk.gds").write_bytes(b"g")
    (run / "lef" / "blk.lef").write_text("MACRO blk\nEND blk\n")
    (run / "spef" / "nom" / "blk.nom.spef").write_text("*SPEF")
    (run / "lib" / "nom_tt_025C_1v80" / "blk.lib").write_text("library(blk){}")
    copies = {k: ({c: str(p) for c, p in v.items()} if isinstance(v, dict) else str(v))
              for k, v in macrolib._final_views(run.parent).items()}
    r = custommacros.save_macro(str(d), "blk", copies=copies,
                                instances=[{"name": "u_core.u_blk", "location": [10, 20], "orientation": "N"}],
                                power={"vdd_pin": "VPWR", "gnd_pin": "VGND", "vdd_net": "VPWR", "gnd_net": "VGND"},
                                source={"kind": "run", "label": "other"})
    assert r["ok"], r
    assert custommacros.set_settings(str(d), {"halo_h": "5", "halo_v": ""})["ok"]
    ov = json.loads(Path(custommacros.write_overlay(str(d))).read_text())
    m = ov["MACROS"]["blk"]
    assert m["spef"] == {"nom_*": ["dir::macros/blk/spef/nom/blk.nom.spef"]}
    assert list(m["lib"]) == ["nom_tt_025C_1v80"]
    assert ov["PDN_MACRO_CONNECTIONS"] == ["keep VPWR VGND VDD VSS", r"u_core\.u_blk VPWR VGND VPWR VGND"]
    assert ov["FP_MACRO_HORIZONTAL_HALO"] == 5.0 and "FP_MACRO_VERTICAL_HALO" not in ov


def test_pdk_refs_must_be_prefixed_paths(tmp_path):
    bad = custommacros.save_macro(str(tmp_path), "sram", refs={"gds": "/etc/passwd", "lef": "pdk_dir::x.lef"})
    assert not bad["ok"]
    ok = custommacros.save_macro(str(tmp_path), "sram", refs={"gds": "pdk_dir::a.gds", "lef": "pdk_dir::a.lef"})
    assert ok["ok"] and ok["macro"]["views"]["gds"] == "pdk_dir::a.gds"
