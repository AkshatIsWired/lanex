// help.js — per-window help catalog.
// Every tab / side-panel / modal gets a button + dialog with copy that
// explains what the tool does, sample values, and common mistakes.

import { fmt } from "./api.js";

const CATALOG = {
  setup: {
    title: "Setup tab",
    goal: "Specify the design directory and target process design kit.",
    how: [
      "Click \ud83d\udcc1 Browse\u2026 to select the directory containing your Verilog sources, SDC constraints, and optional config.yaml.",
      "Select a PDK and standard-cell library. The indicator beside the SCL picker confirms whether cell libraries are installed locally.",
      "In the Configuration card, select a Preset to apply baseline parameters, or search to inspect and override specific variables.",
    ],
    samples: [
      { key: "CLOCK_PERIOD", sample: "10 (ns)" },
      { key: "FP_CORE_UTIL", sample: "50 (%)" },
      { key: "STREAM_OUT_RESOLUTION", sample: "(per PDK)" },
    ],
    pitfalls: [
      "Selecting an uninstalled SCL causes an immediate failure; install required libraries from the Tools tab first.",
      "An incorrect VERILOG_FILES glob produces a 'module not found' error during synthesis.",
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
    goal: "Examine flow metrics from metrics.json grouped by physical design stage.",
    how: [
      "Select runs from the dropdown to update metric tables and trend charts.",
      "Tiles indicate status based on standard signoff criteria: WNS \u2265 0, LVS errors == 0, and valid density ranges.",
      "Multi-corner and directional metrics are presented as structured key-value pairs.",
      "The metric reference table explains each category with sample values to assist in diagnosing failed bounds.",
    ],
    pitfalls: [
      "A red metric indicator denotes an out-of-bound value, which may be non-blocking. Check the step log in the Pipeline tab for context.",
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
    goal: "Edit Verilog and SystemVerilog sources, run lint checks, and simulate testbenches directly within the GUI.",
    how: [
      "The file tree lists design sources. Click any file to open it in the editor with syntax highlighting (Ctrl/⌘F for search).",
      "Upload Sources saves files to the design root; Upload Testbench saves to verify/ to keep testbenches out of synthesis.",
      "Check syntax invokes Verilator in lint-only mode on active sources and populates the Problems panel; click any diagnostic to jump to the file and line.",
      "Simulate selects an execution engine (Icarus, Verilator, or Auto) and runs the chosen testbench, streaming waveforms to the viewer.",
      "GTKWave opens the generated dump in the desktop viewer with signal lists preconfigured via an auto-generated save file.",
    ],
    samples: [
      { key: "Sim engine", sample: "Auto (Icarus → host Verilator → container)" },
      { key: "Testbench top", sample: "left blank → auto-derived from the bench" },
    ],
    pitfalls: [
      "A missing waveform indicates the testbench lacks $dumpfile and $dumpvars calls, or the top module is set to the DUT instead of the testbench. Leaving the top field blank auto-detects the testbench.",
      "Static lint checks only verify syntax and rule compliance without proving functional correctness. Run a simulation to verify logic behavior.",
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

function openHelp(key) {
  const def = CATALOG[key];
  const title = def ? def.title : key;
  const lastFocused = document.activeElement;
  const body =
    (def ? "<p><strong>Goal:</strong> " + def.goal + "</p>" : "") +
    (def && def.how && def.how.length
      ? "<h3 style='margin:var(--s-3) 0 var(--s-2)'>How to use</h3><ol style='margin:0;padding-left:1.2em'>" +
        def.how.map((x) => "<li style='margin-bottom:4px'>" + x + "</li>").join("") + "</ol>"
      : "") +
    (def && def.samples && def.samples.length
      ? "<h3 style='margin:var(--s-3) 0 var(--s-2)'>Sample values</h3><pre class='code'>" +
        def.samples.map((s) => s.key + ": " + s.sample).join("\n") + "</pre>"
      : "") +
    (def && def.pitfalls && def.pitfalls.length
      ? "<h3 style='margin:var(--s-3) 0 var(--s-2)'>Pitfalls</h3><ul style='margin:0;padding-left:1.2em'>" +
        def.pitfalls.map((x) => "<li style='margin-bottom:4px'>" + x + "</li>").join("") + "</ul>"
      : "");
  const back = document.createElement("div");
  back.className = "dlg-backdrop";
  back.innerHTML =
    "<div class='dlg' style='max-width:680px' role='dialog' aria-modal='true' aria-labelledby='help-dlg-title'>" +
    "<div class='dlg-head' style='display:flex;align-items:center;justify-content:space-between;gap:var(--s-3)'>" +
    "<span id='help-dlg-title'>" + title + "</span>" +
    "<button class='iconbtn dlg-x' aria-label='Close' style='margin:-4px -6px'>\u00d7</button></div>" +
    "<div class='dlg-body'>" + body + "</div>" +
    "</div>";

  const closeBtn = back.querySelector(".dlg-x");
  const dlg = back.querySelector(".dlg");

  function close() {
    back.remove();
    document.removeEventListener("keydown", onKey);
    if (lastFocused && typeof lastFocused.focus === "function") {
      lastFocused.focus();
    }
  }

  function onKey(e) {
    if (e.key === "Escape") {
      e.preventDefault();
      close();
      return;
    }
    if (e.key === "Tab") {
      const focusables = dlg.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  back.addEventListener("click", (e) => {
    if (e.target === back || e.target.closest(".dlg-x")) close();
  });
  document.addEventListener("keydown", onKey);
  document.body.appendChild(back);
  if (closeBtn) {
    closeBtn.focus();
  }
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
    document.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        const pill = e.target.closest("[data-help]");
        if (pill) {
          e.preventDefault();
          openHelp(pill.dataset.help);
        }
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
          span.setAttribute("aria-hidden", "true");
          span.setAttribute("tabindex", "-1");
          tab.appendChild(span);
        }
      });
    }, 600);
  },
};
