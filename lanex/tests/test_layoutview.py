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
"""The Layout tab's engine (controller/layoutview.py).

Pure parts (stage picking, layer naming, marker databases, terminal commands,
the GDS3D process file) always run. The KLayout round trip (open, render,
probe, instances, 3D mesh) runs where the ``klayout`` package is installed,
which is everywhere LibreLane is.
"""

import json
import struct
from pathlib import Path

import pytest

from lanex.controller import layoutview as lv


def _run(tmp_path: Path) -> Path:
    run = tmp_path / "design" / "runs" / "RUN_1"
    for name in ("13-openroad-floorplan", "19-openroad-tapendcapinsertion", "21-openroad-generatepdn",
                 "28-openroad-globalplacement", "34-openroad-detailedplacement", "35-openroad-cts",
                 "36-openroad-stamidpnr-1", "39-openroad-globalrouting", "44-openroad-detailedrouting",
                 "65-klayout-drc"):
        (run / name).mkdir(parents=True)
    for name in ("13-openroad-floorplan", "19-openroad-tapendcapinsertion", "21-openroad-generatepdn",
                 "28-openroad-globalplacement", "34-openroad-detailedplacement", "35-openroad-cts",
                 "39-openroad-globalrouting", "44-openroad-detailedrouting"):
        (run / name / "top.def").write_text("VERSION 5.8 ;\n")
    (run / "final" / "gds").mkdir(parents=True)
    (run / "final" / "gds" / "top.gds").write_bytes(b"")
    (run / "resolved.json").write_text(json.dumps({"PDK": "sky130A", "DESIGN_NAME": "top"}))
    return run


def test_stages_pick_the_last_step_of_each_phase(tmp_path):
    run = _run(tmp_path)
    src = lv.sources(run)
    by_id = {s["id"]: s for s in src["stages"]}
    assert [s["id"] for s in src["stages"]] == ["floorplan", "pdn", "placement", "cts", "routing", "final"]
    assert by_id["floorplan"]["source"] == "19-openroad-tapendcapinsertion"
    assert by_id["placement"]["source"] == "34-openroad-detailedplacement"
    assert by_id["routing"]["path"] == "44-openroad-detailedrouting/top.def"
    assert by_id["final"]["kind"] == "gds"
    # every step that wrote a DEF is offered too; a step without one is not
    assert "36-openroad-stamidpnr-1" not in [s["source"] for s in src["steps"]]
    assert len(src["steps"]) == 8


def test_stopped_run_has_no_final_stage(tmp_path):
    run = _run(tmp_path)
    (run / "final" / "gds" / "top.gds").unlink()
    ids = [s["id"] for s in lv.sources(run)["stages"]]
    assert ids[-1] == "routing" and "final" not in ids


def test_source_path_refuses_escapes(tmp_path):
    run = _run(tmp_path)
    assert lv._source_path(run, "../../etc")[0] is None
    assert lv._source_path(run, "final:../../x")[0] is None
    p, kind = lv._source_path(run, "35-openroad-cts")
    assert kind == "def" and p.name == "top.def"


@pytest.mark.parametrize("name,expect", [
    ("35-openroad-cts", "openroad-cts"),
    ("36-openroad-stamidpnr-1", "openroad-stamidpnr"),
    ("44-openroad-detailedrouting", "openroad-detailedrouting"),
])
def test_step_key(name, expect):
    assert lv._step_key(name) == expect


def test_layer_names_groups_and_words():
    assert lv._split_name("met1.drawing - 68/20") == ("met1", "drawing", "68/20")
    assert lv._group_of("met3", "drawing") == "metal"
    assert lv._group_of("via2", "drawing") == "metal"
    assert lv._group_of("li1", "drawing") == "local"
    assert lv._group_of("mcon", "drawing") == "local"
    assert lv._group_of("poly", "drawing") == "device"
    assert lv._group_of("nwell", "drawing") == "well"
    assert lv._group_of("nsdm", "drawing") == "well"
    assert lv._group_of("met2", "pin") == "pin"
    assert lv._group_of("prBoundary", "boundary") == "misc"
    assert "metal wiring layer 4" in lv._layer_words("met4")
    assert lv._layer_words("poly").startswith("polysilicon")
    # higher in the stack reports first on a click
    assert lv._z_rank("met5", "drawing") > lv._z_rank("via4", "drawing") > lv._z_rank("met4", "drawing")
    assert lv._z_rank("met1", "drawing") > lv._z_rank("li1", "drawing") > lv._z_rank("poly", "drawing")


def test_marker_geometry_kinds():
    g = lv._marker_geom("box: (1,2;3,4)")
    assert g["kind"] == "box" and g["bbox"] == [1.0, 2.0, 3.0, 4.0] and len(g["rings"][0]) == 4
    g = lv._marker_geom("edge-pair: (30.1,40.2;30.5,40.2)/(30.1,40.32;30.5,40.32)")
    assert g["kind"] == "edge-pair" and len(g["rings"]) == 2 and g["bbox"] == [30.1, 40.2, 30.5, 40.32]
    g = lv._marker_geom("polygon: (0,0;2,0;2,1;0,1)")
    assert g["kind"] == "polygon" and g["bbox"] == [0.0, 0.0, 2.0, 1.0]
    assert lv._marker_geom("text: 'None'") is None or lv._marker_geom("text: 'None'")["rings"] == []


def test_parse_rdb_reads_categories_items_and_utf8_spelling(tmp_path):
    # Magic's report writer declares encoding='utf8' (KLayout's own reader
    # rejects that spelling) and rule names carry an escaped '<'.
    f = tmp_path / "drc.magic.lyrdb"
    f.write_text(
        "<?xml version='1.0' encoding='utf8'?>\n<report-database><cells><cell><name>top</name></cell></cells>"
        "<categories><category><name>Metal1 width &lt; 0.14um (met1.1)</name><description>width</description>"
        "</category></categories><items>"
        "<item><category>'Metal1 width &lt; 0.14um (met1.1)'</category><cell>top</cell>"
        "<values><value>polygon: (1,1;2,1;2,2;1,2)</value></values></item>"
        "<item><category>'Metal1 width &lt; 0.14um (met1.1)'</category><cell>top</cell>"
        "<values><value>box: (5,5;6,6)</value></values></item>"
        "</items></report-database>", encoding="utf-8")
    r = lv.parse_rdb(f)
    assert r["ok"] and r["total"] == 2
    assert r["categories"][0]["name"] == "Metal1 width < 0.14um (met1.1)"
    assert r["categories"][0]["count"] == 2
    assert r["items"][1]["bbox"] == [5.0, 5.0, 6.0, 6.0]


def test_markers_take_each_tools_report(tmp_path):
    run = _run(tmp_path)
    rep = run / "65-klayout-drc" / "reports"
    rep.mkdir()
    (rep / "drc.klayout.lyrdb").write_text(
        "<?xml version='1.0' encoding='utf-8'?><report-database><categories><category><name>m1.2</name>"
        "</category></categories><items><item><category>'m1.2'</category><values>"
        "<value>edge-pair: (0,0;1,0)/(0,0.1;1,0.1)</value></values></item></items></report-database>")
    m = lv.markers(run)
    assert [s["id"] for s in m["sources"]] == ["klayout-drc"]
    assert m["sources"][0]["total"] == 1 and m["sources"][0]["path"] == "65-klayout-drc/reports/drc.klayout.lyrdb"


def test_viewer_commands_reuse_the_runs_own_cli(tmp_path):
    run = _run(tmp_path)
    (run / "gui-run.json").write_text(json.dumps({
        "run_mode": "container",
        "cli_command": {"container": "librelane --dockerized config.yaml -f Classic -p sky130A "
                                     "-c 'VERILOG_FILES=/a.v /b.v'"}}))
    c = lv.viewer_commands(run, "RUN_1")
    assert c["klayout_flow"] == "librelane --dockerized config.yaml -p sky130A --run-tag RUN_1 --flow OpenInKLayout"
    assert c["openroad_flow"].endswith("--flow OpenInOpenROAD")
    assert c["cwd"].endswith("design")


def test_gds3d_stack_parses_heights_in_um(tmp_path, monkeypatch):
    tf = tmp_path / "proc.txt"
    tf.write_text("# x\nLayerStart: Substrate\nLayer: 255\nDatatype: 0\nHeight: -10000\nThickness: 10000\nLayerEnd\n"
                  "LayerStart: Metal 1\nLayer: 68\nDatatype: 20\nHeight: 1376.1\nThickness: 360.0\n"
                  "Red: 1\nGreen: 0.5\nBlue: 0\nMetal: 1\nShow: 1\nLayerEnd\n"
                  "LayerStart: Hidden\nLayer: 1\nDatatype: 0\nHeight: 0\nThickness: 10\nShow: 0\nLayerEnd\n")
    import lanex.controller.desktop as desktop
    monkeypatch.setattr(desktop, "gds3d_process_file", lambda pdk: str(tf))
    stack, path = lv._gds3d_stack("sky130A")
    assert path == str(tf)
    assert set(stack) == {"68/20"}          # substrate and hidden layers are left out
    m1 = stack["68/20"]
    assert m1["z0"] == pytest.approx(1.3761) and m1["z1"] == pytest.approx(1.7361)
    assert m1["color"] == "#ff8000" and m1["metal"] is True


# ----------------------------------------------------------------- KLayout round trip
klayout_ok = lv.available()["ok"]


@pytest.mark.skipif(not klayout_ok, reason="klayout Python package not installed")
def test_open_render_probe_instances_and_mesh(tmp_path):
    import klayout.db as kdb

    run = _run(tmp_path)
    ly = kdb.Layout()
    ly.dbu = 0.001
    inv = ly.create_cell("lib__inv_1")
    m1 = ly.layer(68, 20)
    inv.shapes(m1).insert(kdb.Box(0, 0, 460, 2720))
    top = ly.create_cell("top")
    for i in range(3):
        top.insert(kdb.CellInstArray(inv.cell_index(), kdb.Trans(kdb.Point(i * 1000, 0))))
    top.shapes(ly.layer(68, 5)).insert(kdb.Text("clk", kdb.Trans(kdb.Point(0, 1000))))
    ly.write(str(run / "final" / "gds" / "top.gds"))

    info = lv.open_session(run, "final")
    assert info["ok"], info
    assert info["top"] == "top" and info["bbox"] == pytest.approx([0, 0, 2.46, 2.72])
    assert [c["name"] for c in info["cells"]] == ["lib__inv_1"] and info["cells"][0]["count"] == 3
    assert any(lbl["text"] == "clk" for lbl in info["labels"])

    png = lv.render(info["sid"], box=None, w=200, h=150)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"

    hits = lv.probe(info["sid"], 0.2, 1.0, 0.01)
    assert hits and hits[0]["cell"] == "lib__inv_1" and hits[0]["cell_box"] == pytest.approx([0, 0, 0.46, 2.72])

    inst = lv.instances(info["sid"], "lib__inv_1")
    assert inst["total"] == 3 and len(inst["boxes"]) == 3

    blob = lv.mesh(info["sid"], None, None)
    n = struct.unpack("<I", blob[:4])[0]
    head = json.loads(blob[4:4 + n])
    assert head["layers"], head          # metal1 drawn, even with the generic stack
    L = head["layers"][0]
    assert L["tris"] == 3 * 2 and L["edges"] == 3 * 4
    assert len(blob) == 4 + n + 4 * (head["triFloats"] + head["edgeFloats"])

    # a session that was never opened (or was dropped) answers None, not an error
    assert lv.render("nope", box=None, w=10, h=10) is None


@pytest.mark.skipif(not klayout_ok, reason="klayout Python package not installed")
def test_mesh_too_big_keeps_the_top_of_the_stack(tmp_path, monkeypatch):
    """A whole big chip over the 3D budget keeps the wiring on top and names
    the lower layers it left out; nothing fitting at all is still too_big."""
    import klayout.db as kdb

    run = _run(tmp_path)
    ly = kdb.Layout()
    ly.dbu = 0.001
    top = ly.create_cell("top")
    for i in range(3):                                   # met1: 3 boxes = 6 tris + 12 edges = 30 prims
        top.shapes(ly.layer(68, 20)).insert(kdb.Box(i * 1000, 0, i * 1000 + 460, 2720))
    top.shapes(ly.layer(69, 20)).insert(kdb.Box(0, 0, 2460, 400))   # met2 above: 10 prims
    ly.write(str(run / "final" / "gds" / "top.gds"))
    info = lv.open_session(run, "final")
    assert info["ok"], info

    def head(blob):
        n = struct.unpack("<I", blob[:4])[0]
        return json.loads(blob[4:4 + n])

    full = head(lv.mesh(info["sid"], None, None))
    if not full["stack"].startswith("gds3d:"):
        pytest.skip("no sky130 GDS3D process file here")
    assert {L["name"] for L in full["layers"]} == {"met1", "met2"} and full["dropped"] == []

    monkeypatch.setattr(lv, "_MAX_3D_PRIMS", 20)
    part = head(lv.mesh(info["sid"], None, None))
    assert [L["name"] for L in part["layers"]] == ["met2"]
    assert part["dropped"] == ["met1"]

    monkeypatch.setattr(lv, "_MAX_3D_PRIMS", 5)
    with pytest.raises(ValueError, match="too_big"):
        lv.mesh(info["sid"], None, None)
