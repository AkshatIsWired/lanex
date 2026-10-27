"""The seven flow stages: the Python table and the browser's copy agree, and
the Classic flow walks through them in order."""

import re
from pathlib import Path

from lanex.controller import flowstages

JS = Path(__file__).resolve().parents[1] / "server" / "static" / "modules" / "flowstages.js"

# The step folders of a real LibreLane 3.0.4 Classic run (sky130A, spm).
CLASSIC = """01-verilator-lint 02-checker-linttimingconstructs 03-checker-linterrors 04-checker-lintwarnings
05-yosys-jsonheader 06-yosys-synthesis 07-checker-yosysunmappedcells 08-checker-yosyssynthchecks
09-checker-netlistassignstatements 10-openroad-checksdcfiles 11-openroad-checkmacroinstances 12-openroad-staprepnr
13-openroad-floorplan 14-openroad-dumprcvalues 15-odb-checkmacroantennaproperties 16-odb-setpowerconnections
17-odb-manualmacroplacement 18-openroad-cutrows 19-openroad-tapendcapinsertion 20-odb-addpdnobstructions
21-openroad-generatepdn 22-odb-removepdnobstructions 23-odb-addroutingobstructions 24-openroad-globalplacementskipio
25-openroad-ioplacement 26-odb-customioplacement 27-odb-applydeftemplate 28-openroad-globalplacement
29-odb-writeverilogheader 30-checker-powergridviolations 31-openroad-stamidpnr 32-openroad-repairdesignpostgpl
33-odb-manualglobalplacement 34-openroad-detailedplacement 35-openroad-cts 36-openroad-stamidpnr-1
37-openroad-resizertimingpostcts 38-openroad-stamidpnr-2 39-openroad-globalrouting 40-openroad-checkantennas
41-odb-diodesonports 42-openroad-repairantennas 43-openroad-stamidpnr-3 44-openroad-detailedrouting
45-odb-removeroutingobstructions 46-openroad-checkantennas-1 47-checker-trdrc 48-odb-reportdisconnectedpins
49-checker-disconnectedpins 50-odb-reportwirelength 51-checker-wirelength 52-openroad-fillinsertion
53-odb-cellfrequencytables 54-openroad-rcx 55-openroad-stapostpnr 56-openroad-irdropreport 57-magic-streamout
58-klayout-streamout 59-klayout-render 60-magic-writelef 61-odb-checkdesignantennaproperties 62-klayout-xor
63-checker-xor 64-magic-drc 65-klayout-drc 66-checker-magicdrc 67-checker-klayoutdrc 68-magic-spiceextraction
69-checker-illegaloverlap 70-netgen-lvs 71-checker-lvs 72-checker-setupviolations 73-checker-holdviolations
74-checker-maxslewviolations 75-checker-maxcapviolations 76-misc-reportmanufacturability""".split()


def _js_stages():
    src = JS.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r'\{ id: "([^"]+)", label: "([^"]+)",\s*blurb: "([^"]+)",\s*steps: "([^"]+)" \}', src):
        out.append({"id": m.group(1), "label": m.group(2), "blurb": m.group(3), "steps": m.group(4)})
    return out


def test_js_and_python_tables_agree():
    js = _js_stages()
    assert len(js) == 7
    py = [{k: st[k] for k in ("id", "label", "blurb")} | {"steps": " ".join(st["steps"].split())} for st in flowstages.STAGES]
    assert js == py


def test_classic_flow_walks_the_stages_in_order():
    ids = flowstages.stages_of(CLASSIC)
    order = [st["id"] for st in flowstages.STAGES]
    ranks = [order.index(i) for i in ids]
    assert ranks == sorted(ranks), "a step goes back to an earlier stage"
    assert set(ids) == set(order), "every stage is reached"
    assert ids[CLASSIC.index("21-openroad-generatepdn")] == "pdn"
    assert ids[CLASSIC.index("25-openroad-ioplacement")] == "placement"
    assert ids[CLASSIC.index("36-openroad-stamidpnr-1")] == "cts"      # checkpoints inherit
    assert ids[CLASSIC.index("55-openroad-stapostpnr")] == "signoff"


def test_equivalence_check_sits_where_it_runs():
    # Classic runs Yosys.EQY (when RUN_EQY is on) near the end, after LVS; listed
    # under Synthesis it pulled the run's last steps back into the first stage.
    with_eqy = CLASSIC[:-1] + ["77-yosys-eqy", CLASSIC[-1]]
    ids = flowstages.stages_of(with_eqy)
    assert ids[with_eqy.index("77-yosys-eqy")] == "signoff"
    assert flowstages.listed_stage("Yosys.EQY") == "signoff"


def test_step_ids_and_folders_name_the_same_step():
    assert flowstages.step_core("OpenROAD.STAMidPNR-3") == "stamidpnr"
    assert flowstages.step_core("43-openroad-stamidpnr-3") == "stamidpnr"
    assert flowstages.listed_stage("OpenROAD.GeneratePDN") == "pdn"
    assert flowstages.listed_stage("OpenROAD.STAMidPNR") is None


def test_layout_snapshots_use_the_shared_names():
    from lanex.controller import layoutview
    for st in layoutview.STAGES:
        assert st["label"] == flowstages.stage(st["id"])["label"]
