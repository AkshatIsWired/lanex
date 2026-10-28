// help.js — per-window help catalog.
// Every tab / side-panel / modal gets a button + dialog with copy that
// explains what the tool does, sample values, and common mistakes.

import { fmt } from "./api.js";

const CATALOG = {
  setup: {
    title: "Setup",
    goal: "Everything a run needs, in the order every RTL-to-GDS flow uses: the project, its sources, the process, a few settings, a readiness check and the Run button.",
    how: [
      "<b>Project</b>: one design folder. With none open, start a new one (blank or an example) or open a folder that already has your Verilog or a LibreLane/OpenLane config. The top module, clock port and clock period are saved straight into <code>config.json</code>.",
      "<b>Sources</b> sorts the files the way FPGA tools do: design files (ticked ones are built into the chip), testbenches (simulation only) and constraint files (SDC timing, pin order). <b>New file</b> and <b>Edit</b> open the RTL IDE.",
      "Before the long run, write and simulate in the <b>RTL IDE</b>: Check syntax, then Simulate a testbench and read the waveform. Minutes saved per mistake.",
      "<b>PDK</b>: sky130A with <code>sky130_fd_sc_hd</code> is the usual first choice and is set by default.",
      "<b>Settings</b> holds the handful of LibreLane variables most projects change, each with when to change it. They're saved in <code>config.json</code>, so a terminal run of the same folder builds the same chip.",
      "When <b>Ready to run?</b> is green, press <b>Run flow</b> (or Run in the top bar, from any tab) and follow it on the Flow page.",
      "<b>All settings</b> lists every LibreLane variable by stage. Values there go with LanEx's runs as overrides and leave <code>config.json</code> alone, which suits one-off experiments.",
    ],
    samples: [
      { key: "CLOCK_PERIOD", sample: "10 (ns, which is 100 MHz)" },
      { key: "FP_CORE_UTIL", sample: "50 (% of the core filled with cells)" },
      { key: "PL_TARGET_DENSITY_PCT", sample: "raise it if placement fails with GPL-0302" },
    ],
    pitfalls: [
      "A very small design (a few dozen cells) on a utilization-sized die can fail placement (DPL-0036 or GPL-0302). A fixed die area in Settings, such as 0 0 150 150, gives it room.",
      "A folder path with spaces breaks LibreLane runs. New projects are always created without them.",
      "The top module's name has to match DESIGN_NAME in the config. The project card keeps the two in step.",
      "A ticked testbench is sent to synthesis. Leave testbenches unticked; they belong in the RTL IDE's simulator.",
      "A library that isn't installed can't be picked; add it from the Tools tab.",
    ],
  },
  pipeline: {
    title: "Flow",
    goal: "Watch a run stage by stage, and when it stops, see why and what to change.",
    how: [
      "The seven tiles are the stages every page uses: Synthesis, Floorplan, Power grid, Placement, Clock tree, Routing, Sign-off. Each shows its time (against the run it is compared with), one number from the end of the stage, and the chip at that point.",
      "Below them is every step in flow order, under its stage, and beside it the run's output as LibreLane prints it. While a run goes the list keeps the running step in view; scroll it yourself and a chip brings you back. Pick a step to see only its log, what it does, the settings it reads and its reports.",
      "A run that stops says why first, in plain words, with the line from the log and what to change. A run that finishes shows its report card: the verdict, the key numbers, and its warnings counted by code.",
      "The Run menu can stop a run after any stage: Synthesis alone gives the cell count and area in seconds.",
    ],
    samples: [
      { key: "Run up to", sample: "Synthesis" },
      { key: "Step ID", sample: "OpenROAD.GlobalPlacement" },
    ],
    pitfalls: [
      "A run started elsewhere (your own terminal) shows here once it has finished; Flow follows runs LanEx started.",
      "Clean means LibreLane's checks passed. It does not cover gate-level simulation, a shuttle's precheck or the foundry's own decks.",
    ],
  },
  runs: {
    title: "Runs",
    goal: "Every run of the design in one table: find, compare and sweep runs, and pick the one the results pages show.",
    how: [
      "One row per run: result, origin (manual, sweep, fix of another run), setup and hold slack, die and std-cell area, utilisation, power in mW, DRC, LVS and antenna, and runtime. Click a heading to sort; Columns picks what shows.",
      "Click a row to show that run on Flow, Layout, Analytics and Verify. The chevron opens its report card and actions: open it on a page, run again with changes, copy its command, pin, bundle, files, delete.",
      "Star a run as the baseline: every number turns green or red against it, and Changed vs baseline lists the settings that differ.",
      "Tick two to six runs, then Compare: Analytics opens its Compare section with them picked.",
      "New sweep runs the design at several values of one to three settings, one run per point. A sweep folds into one row; Summary shows the best for timing and for area, what failed and where, and Use this configuration.",
    ],
    samples: [
      { key: "Sweep values", sample: "35, 50, 65  or  35:65:15" },
      { key: "Sweep run names", sample: "sweep-util-65" },
    ],
    pitfalls: [
      "Sweep after the RTL and constraints are right. A sweep finds a better setting; it does not fix a design, and two or three values usually show the trend.",
      "Each sweep point is a full RTL-to-GDS run. A 3 x 3 grid is nine runs.",
      "Passed means LibreLane finished with every check clean. LanEx is not a sign-off tool.",
    ],
  },
  layout: {
    title: "Layout tab",
    goal: "See the chip a run built, stage by stage and layer by layer, and open it in the desktop viewers.",
    how: [
      "Pick a run at the top. The layout is drawn by KLayout itself, with the PDK's layer colours, at any zoom. Drag to pan, scroll to zoom, double-click to zoom in, right-drag to zoom to a box. F fits the chip.",
      "The strip above the view steps through the flow: Floorplan, Power grid, Placement, Clock tree, Routing and the Final GDS. Your zoom stays put when you switch, so you can watch one spot change. Play the flow animates them; Other snapshot opens any step that wrote a DEF.",
      "Click anything to see what it is: the layer in plain words, its size, and the standard cell it belongs to, with buttons to highlight every copy of that cell or open it in the Cells tab.",
      "Layers: tick layers on and off, Alt-click (or 'only') to see one alone, or use the presets Wiring and Transistors. Cells: every cell type placed, grouped by what it does; click one to highlight all of them. Find: jump to a pin or label by name. Checks: DRC and XOR markers from the run, drawn on the layout; click one to zoom to it.",
      "M measures (rulers snap to straight and 45-degree lines; Alt for any angle), L hides labels, O draws cells as named outlines, [ and ] step through the stages.",
      "Open in KLayout / OpenROAD GUI / Magic / GDS3D starts the full tool in its own window, inside the LibreLane container when possible. OpenROAD opens the stage on screen. Command copies the LibreLane or KLayout command that does the same from a terminal. Save image writes this view, or the whole chip at 4K or 8K.",
      "Run files, under the viewer, lists every output in final/, shows any design format as text, and renders the Yosys synthesis diagrams.",
    ],
    pitfalls: [
      "Stage snapshots before the final GDS come from each step's DEF, so cells are drawn as their LEF outlines and pins. Only the Final GDS has the transistor-level shapes.",
      "A run that stopped early shows the last stage it reached. If there is no stage at all, the run stopped before the floorplan; the Flow page says where and why.",
      "The picture is what the tools wrote. It is not a sign-off; check Verify and the foundry decks before tape-out.",
    ],
  },
  tools: {
    title: "Tools tab",
    goal: "Verify required EDA toolchains and manage container and native dependencies.",
    how: [
      "Each tile displays green when installed. Click the version indicator to view the parsed output of the binary's --version flag.",
      "Python packages (librelane, ciel) provide direct in-app installation with stdout streamed to Live Logs.",
      "Non-pip tools (Yosys, OpenROAD, KLayout, Magic, Netgen, Verilator) display OS-specific package commands and repository links.",
      "The PDK store section pulls sky130, gf180mcu, and related PDK variants via ciel.",
    ],
    samples: [
      { key: "Ciel pull", sample: "ciel pull sky130A" },
      { key: "OpenROAD install", sample: "apt:openroad or GitHub release tarball" },
    ],
    pitfalls: [
      "Avoid installing packages directly into system Python; use a virtual environment when running pip outside container mode.",
    ],
  },
  analytics: {
    title: "Analytics tab",
    goal: "See how a run went, from \"is it clean?\" down to every number LibreLane recorded.",
    how: [
      "Pick a run at the top. Compare with picks a second run of the same design (by default the previous clean one); every change on the page is measured against it.",
      "Overview: the verdict, each check LibreLane ran (hover a chip for what it means), and the four headline numbers: setup slack, area, power and wirelength.",
      "Timing shows setup and hold side by side, slack in every PVT corner (the outlined row is the worst), and how slack moved at each timing check from synthesis to signoff.",
      "Area, Power and Routing break those numbers down: floorplan to scale, area by cell type, the cells used, power split, IR drop per supply net, wire and router convergence.",
      "Flow shows the design at the end of each stage, where the runtime went, and tool warnings by message code. History plots the same numbers over this design's runs; click a point to open that run.",
      "All metrics lists every value with its raw key. Rows with corners or nets open with the arrow. The magnifier opens the tool's own file at that line.",
    ],
    pitfalls: [
      "Green and red deltas follow LibreLane's own direction for each metric. Metrics without a known direction are never coloured.",
      "A run that stopped has no final metrics.json; the page then shows the metrics saved by the last step that finished, and says so.",
      "Power is OpenSTA's estimate with default switching activity, and none of this is a sign-off. Check Verify and the foundry decks before tape-out.",
    ],
  },
  files: {
    title: "Design files",
    goal: "Verify HDL sources and memory initialization files processed by the flow.",
    how: [
      "Files are grouped into Verilog sources (.v, .sv, .vh) and memory contents (.mem, .hex, .bin).",
      "Detected files are selected by default. Deselect items that should be excluded from synthesis (such as simulation testbenches).",
      "Additional files (such as pin_order.cfg or custom scripts) can be specified as a comma-separated list in the extra files input.",
      "Click \u21bb Rescan after modifying files in the design directory.",
    ],
    pitfalls: [
      "Unchecking required memory initialization files causes affected registers to remain uninitialized (X state).",
    ],
  },
  ide: {
    title: "RTL IDE tab",
    goal: "Write, check and simulate the design before the long RTL-to-GDS run: the same loop as in any HDL editor or FPGA tool.",
    how: [
      "The explorer sorts the project's files by what they're for: Design (built into the chip), Simulation (testbenches), Constraints (SDC, pin order) and Project. The + on each group makes that kind of file; a new testbench is wired to the top module's ports and clock. Right-click a file (or its ⋯) to make one of its modules the top, build it into the chip or leave it out, or simulate a testbench.",
      "The editor works like VS Code: Ctrl S saves, Ctrl F finds and replaces (case, regex, whole word), Ctrl / comments a line, Alt ↑/↓ moves it, Ctrl D adds the next match, Ctrl Z undoes per file. Typing offers keywords, system tasks and blocks (module, always_ff, case, a testbench clock); Tab accepts.",
      "Check syntax runs Verilator in lint-only mode over every design and testbench file, and runs again on each save while Check on save is ticked. Problems groups what it finds by file; a click jumps to the line and explains the warning code. Style notes in testbenches are folded away.",
      "Simulate saves every changed file, builds the testbench named on the button (its arrow picks another) with the design files, and says how it went: ran to the end, reported failures, didn't build. File:line in the output is a link.",
      "Waveform: Signals lists everything in the dump; click one to add it, click it again to take it off. Click a name to select it (click it again, the empty space below, or Esc to let it go). Click the waves for the cursor, right-click for the marker (Δ shows the time and frequency between them), drag across to zoom in, Ctrl+wheel to zoom, Shift+wheel to pan, ←/→ to jump between changes, F to fit. Right-click a name for its number format and colour; double-click it to open its declaration. The signal list is kept per testbench.",
      "GTKWave opens the same dump in the desktop viewer with the signals on screen already loaded.",
    ],
    samples: [
      { key: "Simulator", sample: "Auto (Icarus if installed, else Verilator)" },
      { key: "Top module", sample: "left blank: taken from the testbench" },
      { key: "Waveform dump", sample: "$dumpfile(\"dump.vcd\"); $dumpvars(0, counter_tb);" },
    ],
    pitfalls: [
      "No waveform means the testbench has no $dumpfile/$dumpvars, or the top module is set to the design instead of the testbench. Leave Top module blank to take it from the testbench.",
      "A testbench with a free-running clock needs $finish, or the simulation stops at the 120 s limit with a partial waveform.",
      "A clean syntax check doesn't prove the logic is right. Simulate it, and check the waveform against what you expect.",
    ],
  },
  verify: {
    title: "Verify tab",
    goal: "See whether a run passes sign-off, and if not, which check failed, why, and what to change. Every verdict is LibreLane's own, judged with that run's settings.",
    how: [
      "Pick a run. The top banner gives the verdict; the strip of squares is every check in flow order (click one to jump to it).",
      "Compare with picks an earlier run: checks that broke or got fixed since then are called out.",
      "The four tiles (Timing, Design rules, Layout matches netlist, Antenna & power) open their detail sections.",
      "In Checks, click a row to see what it checks, why it matters, what to try, the exact value (with the source file one click away), the step that checked it, and the report.",
      "Timing shows every corner: setup and hold slack, violations, and which corners fail the run versus only warn.",
      "DRC lists each broken rule with the PDK's description and a location in µm; Open in KLayout loads the layout with the markers.",
      "Copy summary puts a plain-text checklist on the clipboard for an issue or a review.",
    ],
    pitfalls: [
      "Not checked is not a pass: the run stopped first, or the step isn't in this flow. Turned off means a RUN_ setting disabled it.",
      "Warning only means LibreLane prints a warning and carries on (for example max slew, or anything whose ERROR_ON_ switch is off). Check them anyway.",
      "LanEx is not a sign-off tool. Before fabrication, verify with the foundry's own rule decks.",
    ],
  },
  dse: {
    title: "Sweeps (in Runs)",
    goal: "Design-space exploration is now sweeps inside Runs: New sweep on the Runs page.",
    how: ["Open Runs and click New sweep, or press the old DSE shortcut: both open the same sheet."],
  },
  layout: {
    title: "Layout tab",
    goal: "View final layouts in the embedded viewer or launch desktop layout tools (KLayout, Magic, GDS3D).",
    how: [
      "Select a run to view the 2D layout rendering generated by the flow.",
      "Click Open in KLayout or Open in Magic to launch local layout viewers with target PDK techfiles.",
      "Opening in the container runs the version-matched tool from the LibreLane image with X11 display forwarding, useful when host binaries are out of date.",
      "3D launches GDS3D to inspect multi-layer physical metal stacks.",
    ],
    pitfalls: [
      "A blank viewer window typically indicates the PDK techfile was not located. Keep 'PDK layer colours' enabled or launch via the container.",
      "External desktop and container tool launches require running the GUI on a host with an active display server.",
    ],
  },
  cells: {
    title: "Cells & macros tab",
    goal: "Know the cells your design is built from, add memories and pre-built blocks, and control which cells the flow may use.",
    how: [
      "Library: every cell of the project's library, grouped by family with its drive strengths (_1, _2, _4…). Search by name, by function (\"flip-flop\", \"xor\") or paste a name from a report. Green drives were used by the last run; struck-out ones the flow won't use.",
      "Pick a cell to see what it does (formula, gate diagram, truth table or flip-flop behaviour), its real layout from the PDK's GDS, how each drive strength trades area for speed (delay versus load at the typical corner), its pins and timing arcs, and whether this project's flow may use it.",
      "Macros: add an SRAM the PDK ships, a block hardened in another LanEx project (its finished run is copied in), or files you were given. Each macro is checked: instantiated in the RTL under the right flattened name, its behavioural model kept out of synthesis, a timing model present, power pins hooked to the grid, and a position inside the die.",
      "Flow rules: the PDK's own exclusion lists, your EXTRA_EXCLUDED_CELLS (with a live preview of what a wildcard catches), the cells LibreLane inserts by itself (fill, taps, ties, clock buffers) and custom cells swapped in for library ones.",
    ],
    pitfalls: [
      "LibreLane has no automatic macro placer: every macro instance needs a position, or the run stops at the power grid with \"Design has unplaced macros\". Use Arrange for me, then drag on the sketch.",
      "Most designs with macros need FP_SIZING absolute and a DIE_AREA big enough for the blocks and their halos.",
      "Custom standard cells must be a whole number of placement sites wide and exactly the row height tall.",
    ],
  },
  manual: {
    title: "Manual / CLI tab",
    goal: "Inspect equivalent command-line invocations or execute approved EDA tool commands directly.",
    how: [
      "Reveal CLI generates the exact command line for the current design, configuration, and overrides, allowing reproduction in an external terminal.",
      "The console executes allow-listed tools (librelane, openroad, yosys, magic, klayout, netgen, iverilog, verilator, ciel, docker, podman, dot) and streams outputs live.",
      "This console is not an interactive shell. Piped commands, redirects, semicolons, backticks, and sudo are blocked; Python execution is restricted to '-m librelane'.",
    ],
    samples: [
      { key: "Allowed", sample: "openroad -version" },
      { key: "Rejected", sample: "sudo … / cmd | cmd / rm …" },
    ],
    pitfalls: [
      "Commands run sequentially; click Stop to cancel an active process.",
    ],
  },
};

// The page guide shown at the top of the help sheet's Learn tab: what this tab
// is for, how to use it, sample values and pitfalls. Catalog strings are
// trusted literals from this file.
export function guideHtml(key) {
  const def = CATALOG[key];
  if (!def) return "";
  const list = (tag, items) => "<" + tag + " class='guide-list'>" + items.map((x) => "<li>" + x + "</li>").join("") + "</" + tag + ">";
  return "<section class='guide'>" +
    "<div class='sheet-lane'>This page</div>" +
    "<h2>" + def.title + "</h2>" +
    (def.goal ? "<p>" + def.goal + "</p>" : "") +
    (def.how && def.how.length ? "<h3>How to use it</h3>" + list("ol", def.how) : "") +
    (def.samples && def.samples.length
      ? "<h3>Example values</h3><dl class='guide-samples'>" +
        def.samples.map((x) => "<dt>" + x.key + "</dt><dd><code>" + x.sample + "</code></dd>").join("") + "</dl>"
      : "") +
    (def.pitfalls && def.pitfalls.length ? "<h3>Watch out for</h3>" + list("ul", def.pitfalls) : "") +
    "</section>";
}

async function openHelp(key) {
  const [{ openHelp: openSheet }, learn] = await Promise.all([import("./shell.js"), import("./learn.js")]);
  const body = openSheet("learn", { render: false });
  learn.renderGlossary(body, { pageKey: key });
}

export const help = {
  catalog: CATALOG,
  open: openHelp,
  bind() {
    // Event delegation: any [data-help] affordance opens that page's guide.
    document.addEventListener("click", (e) => {
      const pill = e.target.closest("[data-help]");
      if (pill) {
        e.preventDefault();
        openHelp(pill.dataset.help);
      }
    });
  },
};
