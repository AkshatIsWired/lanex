// verify-model.js — words and small pure helpers for the Verify tab.
//
// The verdicts themselves come from the server (controller/verify.py), which
// mirrors LibreLane's own Checker steps. This file only explains them: what
// each check looks at, why it matters, and what to change when it fails.
// Every variable named in a fix exists in LibreLane 3 (checked against
// /api/variables); defaults quoted are LibreLane's.

export const STATUS = {
  pass: { label: "Passed", order: 4 },
  fail: { label: "Failed", order: 0 },
  warn: { label: "Warning", order: 1 },
  info: { label: "Info", order: 3 },
  skipped: { label: "Turned off", order: 5 },
  not_run: { label: "Not checked", order: 2 },
};

export const GATE = {
  blocks: { label: "Blocks tape-out", tip: "LibreLane fails the run when this check fails." },
  warns: { label: "Warning only", tip: "LibreLane prints a warning and carries on. Worth a look, but it does not fail the run." },
  info: { label: "Not checked by LibreLane", tip: "LibreLane records this number but no step judges it. LanEx shows it because it usually points at a real problem." },
};

// The five stages, in flow order. `lede` is what a beginner needs to know.
export const GROUPS = {
  rtl: { n: 1, title: "RTL lint", tool: "Verilator", lede: "Verilator reads your Verilog before anything is built and flags code that is wrong or won't synthesize the way it simulates." },
  synth: { n: 2, title: "Synthesis", tool: "Yosys", lede: "Yosys turns the RTL into a netlist of standard cells. These checks catch logic it could not map or that is likely a mistake." },
  pnr: { n: 3, title: "Place & route", tool: "OpenROAD", lede: "OpenROAD places the cells, builds the power grid and routes every wire. These checks catch wiring the router couldn't finish cleanly." },
  timing: { n: 4, title: "Timing sign-off", tool: "OpenSTA", lede: "Static timing analysis on the finished layout, in every process/voltage/temperature corner. Setup: is the logic fast enough for the clock? Hold: is it too fast?" },
  physical: { n: 5, title: "Physical verification", tool: "Magic · KLayout · Netgen", lede: "The final GDS is checked against the foundry's design rules (DRC), compared with your netlist (LVS), and the two GDS writers are compared with each other (XOR)." },
};

// One line under each check's name.
export const SHORT = {
  lint_errors: "Errors Verilator found in your RTL",
  lint_timing_constructs: "Simulation-only delays (#10, …) in synthesizable code",
  lint_warnings: "Warnings Verilator found in your RTL",
  unmapped: "Logic synthesis couldn't map to a standard cell",
  synth_check: "Combinational loops or undriven wires",
  assign: "assign statements left in the gate netlist",
  latch: "Latches inferred from the RTL",
  eqy: "Formal proof the netlist does what the RTL does",
  pdn: "Cells not connected to the power grid",
  route_drc: "Rule errors the detailed router couldn't fix",
  disc_pin: "Cell pins left unconnected after routing",
  wire_length: "The longest routed wire",
  antenna: "Long wires that could damage gates during fabrication",
  setup: "Paths too slow for the clock",
  hold: "Paths too fast after the clock edge",
  slew: "Signals switching too slowly",
  cap: "Nets driving too much load",
  fanout: "Nets driving too many inputs",
  xor: "Magic's GDS vs. KLayout's GDS, layer by layer",
  magic_drc: "Foundry design rules, checked by Magic",
  klayout_drc: "Foundry design rules, checked by KLayout",
  overlap: "Overlapping cells found while extracting the layout",
  lvs: "Layout vs. schematic: does the layout match the netlist?",
  klayout_density: "Metal density rules, checked by KLayout",
  klayout_antenna: "Antenna rules, checked by KLayout",
};

// what: what the check does. why: why it matters. fix: what to try, in order.
export const HELP = {
  lint_errors: {
    what: "Verilator lints every RTL file before synthesis: syntax errors, undeclared signals, port mismatches and other problems it treats as errors.",
    why: "The flow stops right here when there are lint errors (ERROR_ON_LINTER_ERRORS, on by default), so nothing after this was built.",
    fix: ["Open the RTL IDE: its Problems list shows each error with file and line.",
      "Fix them and run again; the flow can't get past this check until lint is clean."],
  },
  lint_timing_constructs: {
    what: "Looks for delays such as #10 and other timing constructs in code that will be synthesized.",
    why: "Synthesis ignores delays, so the chip would behave differently from your simulation. LibreLane always stops on these.",
    fix: ["Remove the delays from synthesizable modules, or wrap them in `ifdef SIMULATION … `endif (LibreLane's own advice)."],
  },
  lint_warnings: {
    what: "Verilator's warnings: unused signals, width mismatches, implicit nets and similar.",
    why: "They don't stop the flow (ERROR_ON_LINTER_WARNINGS is off by default), but width mismatches and implicit nets are a common source of real bugs.",
    fix: ["Read them in the RTL IDE's Problems list; most are fixed by matching widths or declaring signals explicitly."],
  },
  unmapped: {
    what: "Counts cells Yosys could not map to the standard-cell library after synthesis.",
    why: "An unmapped cell has no layout, so the design can't be built. LibreLane stops immediately (ERROR_ON_UNMAPPED_CELLS).",
    fix: ["Usually a module that is instantiated but never defined, or a simulation/vendor primitive. The synthesis report names the cell.",
      "Add the missing module's file to VERILOG_FILES, or replace the primitive with plain RTL."],
  },
  synth_check: {
    what: "Yosys' check pass: combinational loops and wires with no driver.",
    why: "Both make the hardware unpredictable. LibreLane stops immediately (ERROR_ON_SYNTH_CHECKS).",
    fix: ["The pre-synthesis check report names the net. Drive every wire, and break loops with a register."],
  },
  assign: {
    what: "Scans the synthesized gate netlist for assign statements.",
    why: "Some place-and-route steps mishandle them, so LibreLane stops when it finds one (ERROR_ON_NL_ASSIGN_STATEMENTS).",
    fix: ["The step's message in warning.log/error.log gives the netlist line.",
      "They usually come from a port wired straight to another port or a constant; buffer it in the RTL."],
  },
  latch: {
    what: "How many latches Yosys inferred from your RTL.",
    why: "A latch appears when a combinational always block doesn't assign a signal on every path. It is rarely intended and makes timing much harder. LibreLane doesn't stop on it.",
    fix: ["Give every signal a default at the top of the always block, add the missing else, or add a default branch to the case.",
      "In SystemVerilog, always_comb makes the tools warn about this directly."],
  },
  eqy: {
    what: "Yosys EQY formally proves the gate netlist is equivalent to your RTL.",
    why: "It catches synthesis bugs simulation can miss. LibreLane leaves it off by default because it can be slow.",
    fix: ["Set RUN_EQY to true in your config to run it."],
  },
  pdn: {
    what: "OpenROAD checks that every cell's power and ground pins reach the power grid (VPWR/VGND).",
    why: "A cell with no power doesn't work. LibreLane's own note: you may ignore this if LVS passes, because LVS checks power connections too.",
    fix: ["Check the power-grid settings (PDN_VPITCH, PDN_HPITCH, PDN_CFG) suit your die size; a very small die can leave cells between straps.",
      "Macros need PDN_CONNECT_MACROS_TO_GRID (on by default) and the right power pin names."],
  },
  route_drc: {
    what: "Spacing, width and via rules the detailed router (TritonRoute) couldn't satisfy after all its passes.",
    why: "Routing DRC errors become real DRC errors in the final layout. LibreLane fails the run (ERROR_ON_TR_DRC).",
    fix: ["Give the router room: lower FP_CORE_UTIL (default 50) or PL_TARGET_DENSITY_PCT.",
      "Raise DRT_OPT_ITERS (default 64) so the router keeps trying longer.",
      "The DRC section below lists each violation type and where it is."],
  },
  disc_pin: {
    what: "Cell pins that matter (not spare or unused outputs) left unconnected after routing.",
    why: "An unconnected input floats and the logic is broken. LibreLane stops immediately (ERROR_ON_DISCONNECTED_PINS).",
    fix: ["Usually congestion: lower FP_CORE_UTIL or PL_TARGET_DENSITY_PCT and run again.",
      "The step log lists each pin."],
  },
  wire_length: {
    what: "The length of the longest routed wire.",
    why: "Very long wires are slow and pick up noise. LibreLane only judges this when the PDK sets WIRE_LENGTH_THRESHOLD.",
    fix: ["Set WIRE_LENGTH_THRESHOLD (µm) to have LibreLane check it; DESIGN_REPAIR_MAX_WIRE_LENGTH makes the resizer buffer long wires."],
  },
  antenna: {
    what: "During fabrication, a long metal wire collects charge before the layers above connect it, and can discharge through (and damage) the transistor gate it ends on.",
    why: "LibreLane's manufacturability report marks any remaining antenna violation as Failed, even though the flow itself carries on.",
    fix: ["Raise GRT_ANTENNA_REPAIR_ITERS (default 3) or GRT_ANTENNA_REPAIR_MARGIN (default 10 %) so global routing repairs more.",
      "For violations on top-level pins, set DIODE_ON_PORTS to in (or both).",
      "DRT_ANTENNA_REPAIR_ITERS repairs again during detailed routing."],
  },
  setup: {
    what: "A setup violation: data leaves one register and arrives at the next too late for the clock edge.",
    why: "The chip would compute wrong results at this clock speed. LibreLane fails the run for violations in the corners it checks (TIMING_VIOLATION_CORNERS); other corners only warn.",
    fix: ["The direct fix is a slower clock: raise CLOCK_PERIOD (ns).",
      "Shorten the slowest paths in the RTL: fewer logic levels between registers, or add a pipeline stage. The worst paths below name them.",
      "Have synthesis favour speed: SYNTH_STRATEGY \"DELAY 0\" … \"DELAY 4\".",
      "Lower PL_TARGET_DENSITY_PCT so cells sit closer to what they talk to."],
  },
  hold: {
    what: "A hold violation: new data reaches a register too soon after the clock edge and overwrites the value it was capturing.",
    why: "Hold problems don't go away with a slower clock. LibreLane checks every corner (HOLD_VIOLATION_CORNERS = *) and fails the run.",
    fix: ["LibreLane inserts hold buffers after clock-tree synthesis. Raise PL_RESIZER_HOLD_SLACK_MARGIN (default 0.1 ns) and GRT_RESIZER_HOLD_SLACK_MARGIN (default 0.05 ns) so it repairs with more margin.",
      "Check the clock in your SDC: CLOCK_UNCERTAINTY_CONSTRAINT and the input delays shift hold checks.",
      "The fast (ff) corners are usually the worst for hold; see the corner table."],
  },
  slew: {
    what: "Signals whose rise/fall time is slower than the library allows (MAX_TRANSITION_CONSTRAINT).",
    why: "Slow edges add delay and power and make timing less exact. LibreLane only warns: MAX_SLEW_VIOLATION_CORNERS matches no corner by default.",
    fix: ["They are usually in the slow (ss) corner. Design repair after placement fixes most; DESIGN_REPAIR_MAX_SLEW_PCT (default 20 %) adds margin.",
      "A net with very high fanout is the usual cause; buffering it in the RTL helps."],
  },
  cap: {
    what: "Nets driving more capacitance than their driver is rated for (MAX_CAPACITANCE_CONSTRAINT).",
    why: "An overloaded driver is slow and wears out faster. LibreLane only warns by default (MAX_CAP_VIOLATION_CORNERS matches no corner).",
    fix: ["DESIGN_REPAIR_MAX_CAP_PCT (default 20 %) gives design repair more margin.",
      "Split high-fanout nets in the RTL or let synthesis buffer them."],
  },
  fanout: {
    what: "Nets driving more inputs than MAX_FANOUT_CONSTRAINT.",
    why: "High fanout makes a net slow. LibreLane records the count but doesn't check it.",
    fix: ["Lower MAX_FANOUT_CONSTRAINT to make design repair buffer these nets, or restructure the logic."],
  },
  xor: {
    what: "Magic and KLayout each write the final GDS; KLayout XORs the two, layer by layer.",
    why: "A difference means one of the writers changed the geometry, so the GDS you'd send may not be what was verified. LibreLane fails the run (ERROR_ON_XOR_ERROR).",
    fix: ["The XOR section lists the layers that differ. It is almost always a tool or PDK version problem, not your design: check the PDK version and the run's tool versions.",
      "Open xor.xml in KLayout to see exactly where."],
  },
  magic_drc: {
    what: "Magic checks the final layout against the PDK's design rules: widths, spacings, enclosures and so on.",
    why: "The foundry rejects a layout that breaks its rules. LibreLane fails the run (ERROR_ON_MAGIC_DRC).",
    fix: ["The DRC section lists each broken rule with its description and location. Open the layout in KLayout with the markers loaded to see them.",
      "Errors inside a macro or custom cell need fixing in that cell's layout.",
      "Errors on routing usually go away with more room: lower FP_CORE_UTIL or PL_TARGET_DENSITY_PCT."],
  },
  klayout_drc: {
    what: "KLayout checks the final GDS against the PDK's KLayout rule deck.",
    why: "A second, independent DRC: the foundry rejects a layout that breaks its rules. LibreLane fails the run (ERROR_ON_KLAYOUT_DRC).",
    fix: ["The DRC section lists each broken rule with its description and location; open the layout in KLayout with the markers loaded.",
      "Errors inside a macro or custom cell need fixing in that cell's layout."],
  },
  overlap: {
    what: "While extracting the layout for LVS, Magic reports cells that overlap illegally.",
    why: "LibreLane's own note: illegal overlaps can hide real shorts. It fails the run (ERROR_ON_ILLEGAL_OVERLAPS).",
    fix: ["The extraction log names the cells. Overlaps usually come from manually placed macros; check their placement and halos."],
  },
  lvs: {
    what: "Netgen extracts a transistor netlist from the layout and compares it with the netlist from synthesis: same devices, same nets, same pins, connected the same way.",
    why: "If they differ, the layout isn't the circuit you designed: a short, an open, or a missing cell. LibreLane fails the run (ERROR_ON_LVS_ERROR).",
    fix: ["Start with pins, then nets, then devices: a short between two nets shows up as one fewer net in the layout, and fixing it often clears the device errors too.",
      "The LVS section compares the counts; the Netgen report has the full partition of what didn't match.",
      "Power pins that aren't connected (see Power-grid connections) also break LVS."],
  },
  klayout_density: {
    what: "KLayout checks metal density windows against the PDK's rules.",
    why: "Too little or too much metal in an area causes problems in polishing during fabrication.",
    fix: ["Fill insertion (RUN_FILL_INSERTION) adds metal fill; check it ran."],
  },
  klayout_antenna: {
    what: "KLayout's antenna check on the final GDS.",
    why: "Antenna violations can damage gates during fabrication.",
    fix: ["See the antenna advice above: GRT_ANTENNA_REPAIR_ITERS, DIODE_ON_PORTS."],
  },
};

// The four headline areas on the overview, each owning some checks.
export const PILLARS = [
  { id: "timing", title: "Timing", jump: "vf-timing", checks: ["setup", "hold", "slew", "cap", "fanout"] },
  { id: "drc", title: "Design rules", jump: "vf-drc", checks: ["magic_drc", "klayout_drc", "route_drc", "overlap", "klayout_density"] },
  { id: "lvs", title: "Layout matches netlist", jump: "vf-lvs", checks: ["lvs", "xor", "disc_pin"] },
  { id: "rel", title: "Antenna & power", jump: "vf-rel", checks: ["antenna", "pdn", "klayout_antenna"] },
];

// Worst status of a set, for a stage or pillar. Checks that only inform
// never turn a pillar red.
export function worstStatus(checks) {
  const st = checks.map((c) => c.status);
  if (st.includes("fail")) return "fail";
  if (st.includes("warn")) return "warn";
  if (st.some((s) => s === "pass" || s === "info")) return st.includes("not_run") ? "partial" : "pass";
  if (st.includes("not_run")) return "not_run";
  return st.length ? "skipped" : "not_run";
}

export function isNum(v) { return typeof v === "number" && Number.isFinite(v); }

// Change of status from a baseline report to this one, per check id.
// -> { regressed: [check], fixed: [check], changed: Map(id -> {from, to}) }
export function statusDiff(cur, base) {
  const out = { regressed: [], fixed: [], changed: new Map() };
  if (!cur || !base) return out;
  const bmap = new Map((base.checks || []).map((c) => [c.id, c]));
  const bad = (s) => s === "fail" || s === "warn";
  for (const c of cur.checks || []) {
    const b = bmap.get(c.id);
    if (!b) continue;
    if (bad(c.status) && b.status === "pass") out.regressed.push(c);
    else if (c.status === "pass" && bad(b.status)) out.fixed.push(c);
    else if (c.status === "fail" && b.status === "warn") out.regressed.push(c);
    if (b.status !== c.status || String(b.value) !== String(c.value)) out.changed.set(c.id, { from: b, to: c });
  }
  return out;
}

// Sort key for the corner table: nom, min, max RC; then tt, ss, ff.
export function cornerSortKey(name) {
  const rc = { nom: 0, min: 1, max: 2 };
  const pr = { tt: 0, ss: 1, ff: 2, sf: 3, fs: 4 };
  let a = 9, b = 9;
  for (const t of String(name).split("_")) {
    if (t in rc) a = rc[t];
    if (t.toLowerCase() in pr) b = pr[t.toLowerCase()];
  }
  return a * 10 + b;
}
