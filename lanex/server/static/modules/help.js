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
      "When <b>Ready to run?</b> is green, press <b>Run flow</b> (or Run in the top bar, from any tab) and follow it on the Pipeline tab.",
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
    title: "Pipeline tab",
    goal: "Monitor flow step execution in real time or execute targeted flow stages.",
    how: [
      "The timeline lists each flow step (such as Yosys.Synthesis or OpenROAD.Placement) and updates its status live. Click any step row to inspect its log output.",
      "The From, To, and Skip inputs accept step IDs to bound flow execution (passed to flow.start).",
      "Step-by-step mode pauses execution after each flow stage, allowing intermediate log and output inspection.",
    ],
    samples: [
      { key: "From", sample: "Yosys.JsonHeader" },
      { key: "To", sample: "Magic.StreamOut" },
    ],
    pitfalls: [
      "Skipping earlier steps requires pre-existing intermediate deliverables. The flow cannot proceed without required inputs.",
    ],
  },
  runs: {
    title: "Runs tab",
    goal: "Review historical flow runs and load detailed metrics and deliverables.",
    how: [
      "Each row reports the PDK, SCL, completed steps, final status, and elapsed execution time.",
      "Click Open to load a run's signoff metrics into Analytics and preview its generated layouts.",
      "Select multiple runs in the Analytics Compare card to view delta tables and configuration differences.",
      "Use Import to adopt external run directories or LanEx bundles; each row also provides Files, Notes, Bundle, and Reproduce actions.",
    ],
    samples: [
      { key: "Tag format", sample: "RUN_2025-01-19_14-30-00" },
    ],
    pitfalls: [
      "A passed run indicates flow checkers completed without error flags; review the Advisor and Verify tabs to inspect timing and signoff margins.",
    ],
  },
  preview: {
    title: "Preview tab",
    goal: "Inspect generated GDS layouts, DEF floorplans, and rendered preview images.",
    how: [
      "Select a run and choose a DesignFormat (render, gds, def, nl, lef).",
      "Click Render Layout to execute KLayout.Render for the selected run. Rendered PNGs stream back upon completion.",
      "Netlist and constraint files display syntax-highlighted text; layout images render inline.",
    ],
    pitfalls: [
      "If final/gds/ contains no files, the flow did not reach detailed routing or streaming out. Inspect the Pipeline tab to identify failures.",
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
    title: "Verification Center tab",
    goal: "Review consolidated signoff reports: lint, logic equivalence, static timing analysis, DRC, LVS, and antenna checks.",
    how: [
      "Select a run from the dropdown. Stage cards display verdicts evaluated directly from that run's metrics.",
      "Expand any card to view detailed diagnostics, download report files, or open matching logs.",
      "A green verdict indicates that all signoff checks passed without violations for the selected run. Expand each card to review underlying reports.",
    ],
    pitfalls: [
      "Stages marked 'No data' indicate steps omitted from the run (such as a bounded From/To execution) rather than passing checks.",
    ],
  },
  dse: {
    title: "Design-Space Exploration tab",
    goal: "Sweep configuration parameters across specified values to analyze tradeoffs on a Pareto plot.",
    how: [
      "Add a sweep axis: select a configuration variable, provide comma-separated values, and click Add axis.",
      "Grid executes the Cartesian product of all values; List pairs axis values index-by-index.",
      "Run sweep launches combinations sequentially. Completed runs plot on the Pareto chart (cell area versus setup slack).",
      "Use the Runs selector to pick which iterations populate the Pareto plot and comparison tables.",
    ],
    samples: [
      { key: "FP_CORE_UTIL", sample: "40,50,60,70" },
      { key: "Combinations", sample: "Grid 3×3 = 9 runs" },
    ],
    pitfalls: [
      "Each sweep point executes a full RTL-to-GDSII flow run. A 4x4 parameter grid executes 16 complete iterations.",
      "Sweeps inherit the base configuration from the active design's config.json; only swept parameters change.",
    ],
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
    title: "Standard-cell library tab",
    goal: "Browse standard cells by category, area, and pin count, or configure custom replacement cells for subsequent runs.",
    how: [
      "Select a PDK and SCL to inspect the cell catalog, with filtering by cell type and cell footprint.",
      "The Custom cells panel allows uploading cell views (LEF, LIB, GDS, SPICE, Verilog) to replace standard cells via runtime configuration.",
      "Click the help button in the Custom cells panel for view requirements and exclusion syntax.",
    ],
    pitfalls: [
      "An error indicating the SCL LEF was not found means standard-cell libraries are missing for the selected PDK. Install them from the Tools tab.",
      "Custom standard cells must align with manufacturing pitch grids to prevent routing and placement errors.",
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
