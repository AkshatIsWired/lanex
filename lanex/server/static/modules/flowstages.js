// flowstages.js — the seven flow stages every page names the same way:
// Synthesis, Floorplan, Power grid, Placement, Clock tree, Routing, Sign-off.
//
// A grouping of LibreLane's Classic steps, in the order the flow reaches them
// (ORFS draws the same lines: IO placement belongs to placement, after the
// power grid). A label only: nothing is computed from it. The Python twin is
// lanex/controller/flowstages.py; tests/test_flowstages.py keeps them equal.
//
// `steps` are step names without the tool (`OpenROAD.GeneratePDN` and the
// folder `21-openroad-generatepdn` are both "generatepdn"). A step not listed
// (an STA checkpoint, a step from another flow) belongs to the stage of the
// step before it.

export const STAGES = [
  { id: "synthesis", label: "Synthesis",
    blurb: "Yosys turns your Verilog into a netlist of standard cells, after a lint check.",
    steps: "lint linttimingconstructs linterrors lintwarnings jsonheader synthesis yosysunmappedcells yosyssynthchecks netlistassignstatements checksdcfiles checkmacroinstances staprepnr eqy equivalence" },
  { id: "floorplan", label: "Floorplan",
    blurb: "The die and the core area, the rows the cells will sit in, and the tap and end-cap cells.",
    steps: "floorplan dumprcvalues checkmacroantennaproperties setpowerconnections manualmacroplacement macroplacement cutrows tapendcapinsertion" },
  { id: "pdn", label: "Power grid",
    blurb: "The power distribution network: the VPWR / VGND straps and rails every cell connects to.",
    steps: "addpdnobstructions generatepdn removepdnobstructions" },
  { id: "placement", label: "Placement",
    blurb: "The pins on the die edge, then every standard cell on a legal row site. Wires come later.",
    steps: "addroutingobstructions globalplacementskipio ioplacement customioplacement applydeftemplate globalplacement writeverilogheader powergridviolations repairdesignpostgpl manualglobalplacement detailedplacement" },
  { id: "cts", label: "Clock tree",
    blurb: "Clock buffers added so the clock reaches every flip-flop at nearly the same time.",
    steps: "cts resizertimingpostcts" },
  { id: "routing", label: "Routing",
    blurb: "All signal wires drawn on the metal layers, with vias between them.",
    steps: "globalrouting checkantennas diodesonports heuristicdiodeinsertion repairantennas resizertimingpostgrt detailedrouting removeroutingobstructions trdrc reportdisconnectedpins disconnectedpins reportwirelength wirelength fillinsertion" },
  { id: "signoff", label: "Sign-off",
    blurb: "Final timing, the GDS, and the checks: DRC, LVS, antenna, XOR, timing violations.",
    steps: "cellfrequencytables rcx stapostpnr irdropreport streamout render writelef checkdesignantennaproperties xor drc magicdrc klayoutdrc spiceextraction illegaloverlap lvs setupviolations holdviolations maxslewviolations maxcapviolations reportmanufacturability timingviolations" },
];

const BY_STEP = {};
for (const st of STAGES) for (const n of st.steps.split(" ")) BY_STEP[n] = st.id;
const BY_ID = Object.fromEntries(STAGES.map((s) => [s.id, s]));

// "OpenROAD.STAMidPNR-3" -> "stamidpnr"; the folder "43-openroad-stamidpnr-3" too.
export function stepCore(idOrDir) {
  let s = String(idOrDir || "");
  if (/^\d+-/.test(s)) s = s.replace(/^\d+-[a-z]+-/i, "");
  else s = s.split(".").slice(1).join(".") || s;
  return s.toLowerCase().replace(/-\d+$/, "");
}

// The stage a step is listed under, or null (then it inherits; see stageOf).
export function listedStage(idOrDir) {
  return BY_STEP[stepCore(idOrDir)] || null;
}

export function stage(id) { return BY_ID[id] || null; }
export function stageLabel(id) { return (BY_ID[id] || {}).label || id || ""; }

// Each step of an ordered list with its stage id (unlisted steps inherit).
export function stagesOf(steps, key = (s) => s.id || s.dir) {
  let cur = STAGES[0].id;
  return steps.map((s) => {
    const st = listedStage(key(s));
    if (st) cur = st;
    return cur;
  });
}
