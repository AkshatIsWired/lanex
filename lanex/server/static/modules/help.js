// help.js — per-window help catalog.
// Every tab / side-panel / modal gets a button + dialog with copy that
// explains what the tool does, sample values, and common mistakes.

import { fmt } from "./api.js";

const CATALOG = {
  setup: {
    title: "Setup tab",
    goal: "Tell LibreLane which design to harden, on which PDK.",
    how: [
      "Click \ud83d\udcc1 Browse\u2026 to navigate the filesystem and pick the folder that contains your Verilog sources, SDC, and (optionally) config.yaml.",
      "Pick a PDK + standard-cell library. Most beginners use sky130A / sky130_fd_sc_hd. The green/pill on the right of the SCL picker reflects whether the libs are installed locally.",
      "In the Configuration card, hit a Preset to apply sane defaults, or copy values verbatim from an example. Search to find any variable by name.",
    ],
    samples: [
      { key: "CLOCK_PERIOD", sample: "10 (ns)" },
      { key: "FP_CORE_UTIL", sample: "50 (%)" },
      { key: "STREAM\\_OUT\\_RESOLUTION", sample: "(per PDK)" },
    ],
    pitfalls: [
      "Picking a SCL that isn't installed yields a fast failure; install via the Tools tab first.",
      "Wrong VERILOG_FILES glob here shows up as 'module not found' in the synthesis log.",
    ],
  },
  pipeline: {
    title: "Pipeline tab",
    goal: "Visualise the 80-step Classic flow and run a sub-section of it.",
    how: [
      "Each node = one Step (Yosys.Synthesis, OpenROAD.Placement, etc.). Hover for syntax; click to copy the step id.",
      "Right-click a node for actions: Run from here, Run to here, Skip, Reproducible, Help \u2014 all wired into flow.start(frm=, to=, skip=).",
      "The From / To / Skip fields at the top take the same step ids. Range-select \u21d2 partial flow.",
    ],
    samples: [
      { key: "From", sample: "Yosys.JsonHeader" },
      { key: "To", sample: "Magic.StreamOut" },
    ],
    pitfalls: [
      "Skipping a step depends on what earlier steps produced. LibreLane won't refabricate inputs.",
      "Right-click on a Node only works once the pipeline graph has loaded.",
    ],
  },
  runs: {
    title: "Runs tab",
    goal: "Every past invocation of the flow; pick one to inspect deeply.",
    how: [
      "Each row tells you PDK, SCL, total steps, passed/failed, and wall-clock time.",
      "Click a row to load its metrics into the Analytics tab and its final views into the Preview tab.",
      "Diff rows from the right-pane Advisor to see what changed between two runs.",
    ],
    samples: [
      { key: "Tag format", sample: "RUN\\_2025-01-19\\_14-30-00" },
    ],
    pitfalls: [
      "A 'passed' chip means every checker hit 0; it doesn't guarantee silicon-clean. Read the Advisor tab.",
    ],
  },
  preview: {
    title: "Preview tab",
    goal: "Inspect the GDS, DEF netlist, and rendered PNG of the latest run.",
    how: [
      "Pick a run, then a DesignFormat (render, gds, def, nl, lef, etc.).",
      "Click Render Layout to (re-)run KLayout.Render for the selected run. PNGs stream back once generated.",
      "Files fall back to text preview for netlists / SDC; images render inline.",
    ],
    pitfalls: [
      "If final/gds/ is empty, the run never reached OpenROAD.DetailedRouting. Use Pipeline to see what failed.",
    ],
  },
  tools: {
    title: "Tools tab",
    goal: "Verify the EDA toolchain LibreLane needs; install anything missing with one click.",
    how: [
      "Each tile is green if installed. Click the version link \u2014 it parses the binary's --version output.",
      "pip-installable tools (librelane, ciel) get an in-place install button: we stream stdout into the Live Logs panel on the right.",
      "Non-pip tools (yosys/openroad/klayout/magic/netgen/verilator) display the OS-specific install recipe in a modal \u2014 follow the URLs or apt commands.",
      "Use the PDK store row at the bottom to pull a sky130/gf180mcu variant via ciel.",
    ],
    samples: [
      { key: "Ciel pull", sample: "ciel pull sky130A" },
      { key: "OpenROAD install", sample: "apt:openroad or GitHub release tarball" },
    ],
    pitfalls: [
      "Don't pull into system Python; use a venv when running pip outside a container.",
    ],
  },
  analytics: {
    title: "Analytics tab",
    goal: "Every metric LibreLane persisted in metrics.json, grouped by stage.",
    how: [
      "Switch runs from the dropdown at the top \u2014 metrics reflow.",
      "Tiles turn green/red based on OpenLane heuristics: WNS \u2265 0, LVS errors == 0, density \u2208 [0, 1]. Negative violations are red.",
      "Per-corner / per-direction metrics arrive as nested objects; we render them as key:value pairs compressed into one line.",
      "The Advisory glossary at the bottom explains every category with a sample value \u2014 use it as a Bayes' table when something fails.",
    ],
    pitfalls: [
      "A red tile doesn't always mean failure \u2014 it can be non-blocking. Read the matching step's log via the Pipeline tab.",
    ],
  },
  files: {
    title: "Files (after you click \ud83d\udcc1 Browse\u2026)",
    goal: "Confirm every source/memory file LibreLane will read.",
    how: [
      "Files are deduped and grouped: Sources (.v/.sv/.vh) and Memory files (.mem/.hex/.bin).",
      "Items are checked by default. Untick anything LibreLane should ignore (e.g. a Testbench that belongs to simulation only).",
      "Extra files \u2014 pin\\_order.cfg, readme.txt, etc. \u2014 go in the bottom input field as a comma-separated list.",
      "Click \u21bb Rescan after adding new .v files to the directory.",
    ],
    pitfalls: [
      "Memory files misclicked as unchecked will silently leave initial regs at X.",
    ],
  },
  metrics: {
    title: "Metrics (Live, side pane)",
    goal: "Latest run only as a hero strip.",
    how: [
      "Same heuristic painting rules as Analytics; this view always reflects state.metrics, which is updated when flow_dones.",
      "Click the Metrics heading to expand the Analytics tab for the full breakdown.",
    ],
  },
  advisor: {
    title: "Advisor (right pane)",
    goal: "Plain-English explanations for failed steps + one-click fixes.",
    how: [
      "Cards auto-populate when a step fails or an OpenROADAlert is emitted \u2014 the matcher is in gui.controller.alerts.",
      "Card fields: What happened, Why it matters, ranked Try\u2026 list, and Apply buttons that overlay config fixes on the form.",
      "Timing closure mini-card at the top reads current WNS/TNS and suggests which variable to tune next.",
      "Below: per-run DRC/LVS report picker (auto-detected from runs/<tag>/<step>/).",
    ],
    pitfalls: [
      "Clicking 'Apply' writes to state.varsValues \u2014 to actually send, hit Run again.",
    ],
  },
  topbar: {
    title: "Top bar",
    goal: "Project status at a glance + global controls.",
    how: [
      "Design / PDK pills turn green when set.",
      "Mode switch: Full Auto for end-to-end runs; Step-by-step reserves the next step for manual inspection.",
      "Tools \u2699 badge warns about any missing EDA binary.",
      "Help icon opens the keyboard-shortcut dialog.",
    ],
  },
  wizard: {
    title: "First-run wizard",
    goal: "A ten-minute guided trip from RTL to GDS using the SPM example.",
    how: [
      "Follow the five prompts in order. Each ties to a specific tab.",
      "Skip with the X. The wizard only reappears if you clear site storage.",
    ],
  },
  ide: {
    title: "RTL IDE tab",
    goal: "Edit your Verilog/SystemVerilog, lint it, and simulate a testbench to a waveform — without leaving the GUI.",
    how: [
      "The file tree on the left lists the design's sources. Click a file to open it in the editor (syntax highlighting; Ctrl/⌘F = find & replace).",
      "Upload Sources lands files in the design root; Upload Testbench lands them in verify/ (so the flow won't try to synthesise them).",
      "Check syntax runs Verilator --lint-only on the current sources — no run dir, no PDK — and lists problems in the Problems panel; click a diagnostic to jump to the line.",
      "Simulate picks an engine (Icarus for classic `initial`/`#delay` benches, Verilator for speed, or Auto) and runs the selected testbench; $dumpvars output renders in the waveform viewer (zoom with the wheel, click to lock a cursor, export PNG/CSV).",
    ],
    samples: [
      { key: "Sim engine", sample: "Auto (Icarus → host Verilator → container)" },
      { key: "Testbench top", sample: "left blank → auto-derived from the bench" },
    ],
    pitfalls: [
      "No waveform usually means the testbench has no $dumpfile/$dumpvars, or the top is the DUT not the bench — leave the top field blank to auto-pick the bench.",
      "Lint is static only; it never proves functional correctness — run a sim for that.",
    ],
  },
  verify: {
    title: "Verification Center tab",
    goal: "A tape-out readiness verdict for a finished run: lint, synthesis equivalence, timing, and DRC / LVS / antenna, plus the signoff reports.",
    how: [
      "Pick a run from the dropdown. Each stage card turns green / amber / red from that run's own metrics (no invented numbers).",
      "Expand a card to read why; use View / Download / Locate on any signoff report (DRC, LVS, antenna, STA).",
      "A green verdict means every gating checker hit zero in THIS run — read the cards before trusting it.",
    ],
    pitfalls: [
      "“No data” for a stage means that step didn't run (e.g. a partial From/To run) — not that it passed.",
    ],
  },
  dse: {
    title: "Design-Space Exploration tab",
    goal: "Sweep one or more config variables across a range of values, run each combination, and compare the results on a Pareto plot.",
    how: [
      "Add an axis: pick a variable, type comma-separated values (e.g. 40,50,60), Add axis. Repeat for more dimensions.",
      "Grid = every combination (cartesian); List = zip the axes index-by-index. The counter shows how many runs that is.",
      "Run sweep launches them sequentially on one engine. Watch the queue; on completion the runs are plotted (area vs setup slack).",
      "Use the Runs picker to choose which runs go on the Pareto / compare — it pre-selects the sweep's runs and survives a page reload.",
    ],
    samples: [
      { key: "FP_CORE_UTIL", sample: "40,50,60,70" },
      { key: "Combinations", sample: "Grid 3×3 = 9 runs" },
    ],
    pitfalls: [
      "Each point is a full RTL→GDS run — a 4×4 grid is 16 runs. Start small.",
      "Sweeps share the active design's config.json as the base; only the swept vars change.",
    ],
  },
  layout: {
    title: "Layout tab",
    goal: "View the run's final layout and open it in your own desktop tools (KLayout / Magic / GDS3D), or in the version-matched container.",
    how: [
      "Pick a run; the 2D view is the KLayout PNG the flow already rendered (pan / zoom). No klayout subprocess in the browser.",
      "Open in KLayout / Magic launches your installed tool on the run's GDS; toggle “PDK layer colours” for the techfile view vs the tool's plain default.",
      "Open in the container runs the matched-version tool from the LibreLane image (forwards your X11 display) — use this when your host tool is too old for the PDK techfile.",
      "3D opens GDS3D (a desktop app) on the layer stack; install it from Tools if missing.",
    ],
    pitfalls: [
      "A blank Magic/KLayout window usually means the PDK techfile didn't load — keep “PDK layer colours” on, or use the container launch.",
      "Desktop / container tool launches only work when the GUI runs on your own machine with a display.",
    ],
  },
  cells: {
    title: "Standard-cell library tab",
    goal: "Browse the PDK's standard cells — their kind, area and pins — and register your own custom cells for a swap.",
    how: [
      "Pick a PDK + SCL (independent of the Setup tab). The table lists every cell; search and sort by kind/area.",
      "The Custom cells panel lets you upload cell views (LEF required, plus LIB/GDS/SPICE/Verilog) to swap a stock cell for your own — applied per-run via EXTRA_LEFS/LIBS/… + EXTRA_EXCLUDED_CELLS, never written into config.json.",
      "Its own “?” button opens a full guide to views, the swap-out list, and caveats.",
    ],
    pitfalls: [
      "“Could not locate the SCL's LEF” means the chosen SCL isn't installed for that PDK — pull it from Tools.",
      "A custom cell needs an on-grid LEF or placement/routing will reject it.",
    ],
  },
  manual: {
    title: "Manual / CLI tab",
    goal: "Run LibreLane or an EDA tool yourself, and copy the exact CLI command equivalent to your GUI run.",
    how: [
      "Reveal CLI builds the precise `librelane` command (container or local) for the current design + config + overrides — copy it to reproduce the run in a terminal.",
      "The console runs an allow-listed command (librelane, openroad, yosys, magic, klayout, netgen, iverilog, verilator, ciel, docker/podman, dot) and streams its output here.",
      "It is NOT a shell: sudo / pipes / redirects / ; / backticks are rejected, and python is only allowed as `-m librelane`.",
    ],
    samples: [
      { key: "Allowed", sample: "openroad -version" },
      { key: "Rejected", sample: "sudo … / cmd | cmd / rm …" },
    ],
    pitfalls: [
      "One command at a time; cancel stops the running process.",
    ],
  },
};

function openHelp(key) {
  const def = CATALOG[key];
  const dlg = document.createElement("div");
  dlg.className = "onboard";
  dlg.innerHTML =
    "<div class='onboard-card' style='max-width:680px'>" +
    "<button class='onboard-close' aria-label='Close'>\u00d7</button>" +
    "<h2>" + (def ? def.title : key) + "</h2>" +
    (def ? "<p><strong>Goal:</strong> " + def.goal + "</p>" : "") +
    (def && def.how && def.how.length
      ? "<h3 style='margin-top:var(--s-4)'>How to use</h3><ol>" + def.how.map((x) => "<li>" + x + "</li>").join("") + "</ol>"
      : "") +
    (def && def.samples && def.samples.length
      ? "<h3 style='margin-top:var(--s-4)'>Sample values</h3><pre class='code'>" +
        def.samples.map((s) => s.key + ": " + s.sample).join("\n") +
      "</pre>"
      : "") +
    (def && def.pitfalls && def.pitfalls.length
      ? "<h3 style='margin-top:var(--s-4)'>Pitfalls</h3><ul>" + def.pitfalls.map((x) => "<li>" + x + "</li>").join("") + "</ul>"
      : "") +
    "</div>";
  dlg.addEventListener("click", (e) => {
    if (e.target === dlg || e.target.classList.contains("onboard-close")) dlg.remove();
  });
  document.body.appendChild(dlg);
  // Esc closes
  document.addEventListener("keydown", function _once(e) {
    if (e.key === "Escape") {
      dlg.remove();
      document.removeEventListener("keydown", _once);
    }
  });
}

export const help = {
  catalog: CATALOG,
  open: openHelp,
  bind() {
    // Event delegation — catches both static and dynamically created pills.
    document.addEventListener("click", (e) => {
      const pill = e.target.closest("[data-help]");
      if (pill) {
        e.preventDefault();
        openHelp(pill.dataset.help);
      }
    });
    // Side-tab help icons (rendered dynamically).
    setInterval(() => {
      document.querySelectorAll(".side-tab").forEach((tab) => {
        if (!tab.querySelector(".help-pill")) {
          const span = document.createElement("span");
          span.className = "help-pill";
          span.dataset.help = tab.dataset.tab;
          span.textContent = "?";
          span.title = "What does this tab do?";
          tab.appendChild(span);
        }
      });
    }, 600);
  },
};
