"""The seven flow stages every LanEx page names the same way.

Synthesis, Floorplan, Power grid, Placement, Clock tree, Routing, Sign-off: a
grouping of LibreLane's Classic steps in the order the flow reaches them. A
label only; nothing is computed from it. The browser's copy is
``server/static/modules/flowstages.js``; ``tests/test_flowstages.py`` keeps the
two equal.

Step names are written without the tool: ``OpenROAD.GeneratePDN`` and the
folder ``21-openroad-generatepdn`` are both ``generatepdn``. A step that is not
listed belongs to the stage of the step before it.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

STAGES: List[Dict[str, str]] = [
    {"id": "synthesis", "label": "Synthesis",
     "blurb": "Yosys turns your Verilog into a netlist of standard cells, after a lint check.",
     "steps": "lint linttimingconstructs linterrors lintwarnings jsonheader synthesis yosysunmappedcells "
              "yosyssynthchecks netlistassignstatements checksdcfiles checkmacroinstances staprepnr"},
    {"id": "floorplan", "label": "Floorplan",
     "blurb": "The die and the core area, the rows the cells will sit in, and the tap and end-cap cells.",
     "steps": "floorplan dumprcvalues checkmacroantennaproperties setpowerconnections manualmacroplacement "
              "macroplacement cutrows tapendcapinsertion"},
    {"id": "pdn", "label": "Power grid",
     "blurb": "The power distribution network: the power and ground straps and rails every cell connects to (VPWR / VGND on sky130 and IHP, VDD / VSS on gf180).",
     "steps": "addpdnobstructions generatepdn removepdnobstructions"},
    {"id": "placement", "label": "Placement",
     "blurb": "The pins on the die edge, then every standard cell on a legal row site. Wires come later.",
     "steps": "addroutingobstructions globalplacementskipio ioplacement customioplacement applydeftemplate "
              "globalplacement writeverilogheader powergridviolations repairdesignpostgpl manualglobalplacement "
              "detailedplacement"},
    {"id": "cts", "label": "Clock tree",
     "blurb": "Clock buffers added so the clock reaches every flip-flop at nearly the same time.",
     "steps": "cts resizertimingpostcts"},
    {"id": "routing", "label": "Routing",
     "blurb": "All signal wires drawn on the metal layers, with vias between them.",
     "steps": "globalrouting checkantennas diodesonports heuristicdiodeinsertion repairantennas resizertimingpostgrt "
              "detailedrouting removeroutingobstructions trdrc reportdisconnectedpins disconnectedpins "
              "reportwirelength wirelength fillinsertion"},
    {"id": "signoff", "label": "Sign-off",
     "blurb": "Final timing, the GDS, and the checks: DRC, LVS, antenna, XOR, timing violations.",
     "steps": "cellfrequencytables rcx stapostpnr irdropreport streamout render writelef "
              "checkdesignantennaproperties xor drc magicdrc klayoutdrc spiceextraction illegaloverlap lvs "
              "setupviolations holdviolations maxslewviolations maxcapviolations reportmanufacturability "
              "timingviolations eqy equivalence"},
]

_BY_STEP = {n: st["id"] for st in STAGES for n in st["steps"].split()}
_BY_ID = {st["id"]: st for st in STAGES}


def step_core(id_or_dir: str) -> str:
    """``OpenROAD.STAMidPNR-3`` and ``43-openroad-stamidpnr-3`` -> ``stamidpnr``."""
    s = str(id_or_dir or "")
    if re.match(r"^\d+-", s):
        s = re.sub(r"^\d+-[a-z]+-", "", s, flags=re.I)
    else:
        s = ".".join(s.split(".")[1:]) or s
    return re.sub(r"-\d+$", "", s.lower())


def listed_stage(id_or_dir: str) -> Optional[str]:
    """The stage a step is listed under, or None (it then inherits)."""
    return _BY_STEP.get(step_core(id_or_dir))


def stage(stage_id: str) -> Dict[str, str]:
    return _BY_ID[stage_id]


def stages_of(steps: Iterable[str]) -> List[str]:
    """The stage id of each step of an ordered list (unlisted steps inherit)."""
    cur = STAGES[0]["id"]
    out = []
    for s in steps:
        cur = listed_stage(s) or cur
        out.append(cur)
    return out
