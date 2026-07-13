// config.js — Constraints form, grouped & comprehensive.
// - Groups variables by stage
// - Sticky nav to jump between groups
// - Presets: Default / Low Power / Performance / Sky130 special / Min area
// - Auto-applies "hide non-PDK variables" when a PDK is selected

import { api, fmt } from "./api.js";
import { state, safeStorage } from "./state.js";
import { toast } from "./toast.js";

const STAGE_GROUPS = [
  {
    id: "pdk",
    name: "Tech / PDK",
    description: "Process design kit version, standard cell library, IO pads.",
    pdk_only: true,
  },
  {
    id: "synth",
    name: "Synthesis",
    description: "Yosys: how aggressively to optimise for delay vs area vs power.",
    keys: ["SYNTH_", "YOSYS_", "VERILOG_", "EXTRA_VERILOG_"],
  },
  {
    id: "lint",
    name: "Linting",
    description: "Verilator static checks (latch inference, blocking in always_ff, widths).",
    keys: ["LINT_"],
  },
  {
    id: "floorplan",
    name: "Floorplan",
    description: "Die/core area, utilisation, aspect ratio, macro placement.",
    keys: ["FP_"],
  },
  {
    id: "pdn",
    name: "Power Delivery",
    description: "Strap widths / spacing on the VDD/VSS grid.",
    keys: ["PDN_"],
  },
  {
    id: "placement",
    name: "Placement",
    description: "Where standard cells go (global + detailed placement).",
    keys: ["PL_", "GLOBAL_PLACEMENT", "PLACE_", "IO_"],
  },
  {
    id: "cts",
    name: "Clock Tree",
    description: "Clock buffer insertion strategy, CTS branch allowance, target skew.",
    keys: ["CTS_", "CLOCK_"],
  },
  {
    id: "antenna",
    name: "Antenna & Diodes",
    description: "Charge-discharge protection on long routes.",
    keys: ["DIODE_", "ANTENNA_"],
  },
  {
    id: "routing",
    name: "Routing",
    description: "Global + detailed router settings; design-rule-aware.",
    keys: ["RT_", "ROUTING_"],
  },
  {
    id: "sta",
    name: "Static Timing",
    description: "STA corners, slack targets, clock periods, hold/setup expectations.",
    keys: ["STA_", "TIMING_", "RCX_"],
  },
  {
    id: "signoff",
    name: "Signoff",
    description: "DRC, LVS, XOR, IR drop, density — what gets reported at the end.",
    // NB: no "LVS_" here — LVS_* vars belong to the dedicated "lvs" group below.
    // Listing it in both made the first-match win send every LVS_* to Signoff and
    // left the LVS group empty (B5).
    keys: ["DRC_", "XOR_", "KI_", "MAGIC_"],
  },
  {
    id: "lvs",
    name: "LVS",
    description: "Layout-vs-Schematic verification.",
    keys: ["LVS_"],
  },
  {
    id: "ir",
    name: "IR Drop",
    description: "Voltage drop on the power grid.",
    keys: ["IR_"],
  },
  {
    id: "clockgating",
    name: "Clock gating / retention",
    description: "Optional low-power cells (sky130 hs variants etc).",
    keys: ["CLOCK_GATING", "RETENTION"],
  },
  {
    id: "misc",
    name: "Misc",
    description: "Log thresholds, exporter options, and other rare knobs.",
    keys: [],
  },
];

// Presets only set REAL LibreLane variables (verified against the live
// variable registry). PL_TARGET_DENSITY_PCT is a percentage (0–100), FP_CORE_UTIL
// is a percentage, SYNTH_STRATEGY is the Literal 'AREA n' / 'DELAY n', and
// DIODE_ON_PORTS is the Literal 'none|in|out|both'. "Default" clears overrides so
// every field falls back to LibreLane's own defaults.
const PRESETS = {
  default: {
    label: "Default",
    reset: true,
    values: {},
  },
  lowpower: {
    // Honest label: these are AREA-optimising knobs. Smaller area tends to lower
    // dynamic power (shorter wires), but LibreLane 3.0.4 has no direct
    // power-driven synthesis strategy — calling it "Low Power" overstated it (B2).
    label: "Area-lean (lower power)",
    values: {
      SYNTH_STRATEGY: "AREA 2",
      FP_CORE_UTIL: 40,
      PL_TARGET_DENSITY_PCT: 55,
    },
  },
  perfpush: {
    label: "Performance",
    values: {
      SYNTH_STRATEGY: "DELAY 3",
      FP_CORE_UTIL: 60,
      PL_TARGET_DENSITY_PCT: 60,
    },
  },
  minimalarea: {
    label: "Min area",
    values: {
      SYNTH_STRATEGY: "AREA 3",
      FP_CORE_UTIL: 70,
      PL_TARGET_DENSITY_PCT: 78,
    },
  },
  antenna: {
    label: "Antenna-hardened",
    values: {
      DIODE_ON_PORTS: "both",
      // 5 > the LibreLane default of 3 — a genuinely stronger antenna-repair
      // pass. (At the default value this preset member was a no-op, B1.)
      GRT_ANTENNA_REPAIR_ITERS: 5,
    },
  },
};

function groupFor(name, v) {
  if (v?.pdk && STAGE_GROUPS[0].pdk_only) return "pdk";
  // Longest-matching-key wins, NOT first-match. First-match sent e.g.
  // CLOCK_GATING_* to "Clock Tree" (it matched the shorter "CLOCK_") instead of
  // "Clock gating" (B5). The LVS/Signoff duplicate is fixed at the data level
  // above (only the lvs group carries "LVS_").
  const upper = name.toUpperCase();
  let best = null, bestLen = 0;
  for (const g of STAGE_GROUPS) {
    for (const k of (g.keys || [])) {
      const ku = k.toUpperCase();
      if (upper.includes(ku) && ku.length > bestLen) {
        best = g.id;
        bestLen = ku.length;
      }
    }
  }
  return best || "misc";
}

let _searchTerm = "";

export function renderConfig() {
  const root = document.getElementById("vars-form");
  if (!root) return;
  const search = document.getElementById("var-search");
  search?.addEventListener("input", () => {
    _searchTerm = search.value.toUpperCase();
    paint();
  });
  document.querySelectorAll(".chip-clickable").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const p = PRESETS[btn.dataset.preset];
      if (!p) return;  // user-defined chips are handled by paintUserPresets()
      const { confirmDialog } = await import("./dialog.js");
      // B3 — preview exactly what the preset changes BEFORE applying it, so a
      // preset can never silently overwrite a field the user tuned by hand.
      const changes = [];
      if (p.reset) {
        const nOv = Object.keys(state.varsValues || {}).length;
        changes.push(nOv ? ("clear " + nOv + " current override(s) → LibreLane defaults")
                         : "nothing to clear — no overrides set");
      }
      for (const [k, v] of Object.entries(p.values)) {
        const cur = state.varsValues[k];
        const from = (cur === undefined || cur === "") ? "default" : String(cur);
        changes.push(k + ": " + from + " → " + String(v));
      }
      const ok = await confirmDialog({
        title: "Apply preset “" + (p.label || btn.dataset.preset) + "”?",
        body: "This preset will " + changes.join("; ") + "." +
          (p.reset ? "" : " Overrides not listed here are kept."),
        confirmText: "Apply preset",
      });
      if (!ok) return;
      document.querySelectorAll(".chip-clickable").forEach((b) => b.classList.remove("chip-active"));
      btn.classList.add("chip-active");
      if (p.reset) state.varsValues = {};
      for (const [k, v] of Object.entries(p.values)) state.varsValues[k] = String(v);
      syncReportToggles();
      paint();
      renderOverridesSummary();
    });
  });
  // "Save preset": persist the current overrides as a named, reusable preset
  // (localStorage, per-browser). Cheap QoL — a returning user re-applies their
  // own recipe in one click instead of re-typing fields.
  const saveBtn = document.getElementById("config-save-preset");
  if (saveBtn && !saveBtn._wired) {
    saveBtn._wired = true;
    saveBtn.addEventListener("click", async () => {
      const ov = activeOverrides();
      if (!Object.keys(ov).length) { toast.show("Set at least one override first.", "warn"); return; }
      const { promptDialog } = await import("./dialog.js");
      const name = await promptDialog({ title: "Save preset", label: "Preset name", defaultValue: "" });
      if (!name || !name.trim()) return;
      const presets = userPresets();
      presets[name.trim()] = { values: ov };
      safeStorage.setJSON(USER_PRESETS_KEY, presets);
      paintUserPresets();
      toast.show("Saved preset '" + name.trim() + "'.", "success");
    });
  }
  paintUserPresets();
  // Quick SYNTH_SHOW toggle (surfaces the most-asked-for diagram knob without
  // hunting the full variable list). Drives the same override the form would.
  const ss = document.getElementById("cfg-synth-show");
  if (ss && !ss._wired) {
    ss._wired = true;
    ss.addEventListener("change", () => {
      state.varsValues.SYNTH_SHOW = ss.checked;
      const formInput = document.getElementById("var-SYNTH_SHOW");
      if (formInput) formInput.value = ss.checked ? "true" : "false";
      renderOverridesSummary();
    });
  }
  syncReportToggles();
  paint();
  renderOverridesSummary();
}

// ---- User-defined presets (localStorage, per-browser) ---------------------
const USER_PRESETS_KEY = "ll.userPresets";
function userPresets() {
  const p = safeStorage.getJSON(USER_PRESETS_KEY, {});
  return (p && typeof p === "object") ? p : {};
}
function applyOverrideSet(values, { reset = true } = {}) {
  if (reset) state.varsValues = {};
  for (const [k, v] of Object.entries(values || {})) state.varsValues[k] = (typeof v === "boolean") ? v : String(v);
  syncReportToggles();
  paint();
  renderOverridesSummary();
}
function paintUserPresets() {
  const host = document.getElementById("config-user-presets");
  if (!host) return;
  const presets = userPresets();
  const names = Object.keys(presets).sort();
  host.innerHTML = names.map((n) =>
    "<span class='chip chip-clickable user-preset' data-uname='" + fmt.escape(n) + "'>" + fmt.escape(n) +
    "<button class='user-preset-del' data-del='" + fmt.escape(n) + "' title='Delete preset' aria-label='Delete preset " + fmt.escape(n) + "'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button></span>").join("");
  host.querySelectorAll(".user-preset").forEach((el) => {
    el.addEventListener("click", (e) => {
      if (e.target.closest(".user-preset-del")) return;
      document.querySelectorAll(".chip-clickable").forEach((b) => b.classList.remove("chip-active"));
      el.classList.add("chip-active");
      const p = userPresets()[el.dataset.uname];
      if (p) applyOverrideSet(p.values);
    });
  });
  host.querySelectorAll(".user-preset-del").forEach((b) => {
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const presets = userPresets();
      delete presets[b.dataset.del];
      safeStorage.setJSON(USER_PRESETS_KEY, presets);
      paintUserPresets();
    });
  });
}

// What will actually be sent to the engine. A preset only seeds these values;
// any field you then edit is layered on top — so the run uses the preset's
// values PLUS your edits (blanks excluded → those fall back to the PDK/tool
// default). Showing the merged set removes the "preset or my edits?" ambiguity
// (issue #7). Fields you never touch are NOT here and use LibreLane's defaults.
export function activeOverrides() {
  const out = {};
  for (const [k, v] of Object.entries(state.varsValues || {})) {
    if (v === null || v === undefined) continue;
    if (typeof v === "string" && v.trim() === "") continue;
    if (typeof v === "boolean") { out[k] = v; continue; }
    out[k] = v;
  }
  return out;
}

export function renderOverridesSummary() {
  const el = document.getElementById("config-overrides-summary");
  if (!el) return;
  const ov = activeOverrides();
  const keys = Object.keys(ov).sort();
  // The design's own config file, viewable as-is (input-side transparency:
  // see exactly what LanEx reads and never edits).
  const viewCfg = "<button class='btn btn-ghost' id='ov-view-config' " +
    "title='Open your design&#39;s own config file, exactly as it is on disk'>View config file</button>";
  const wireViewCfg = () => {
    el.querySelector("#ov-view-config")?.addEventListener("click", async () => {
      const { openProvenance } = await import("./provenance.js");
      openProvenance({ kind: "input", key: "" },
        { title: "Your design's config file (as on disk — LanEx never edits it)" });
    });
  };
  if (!keys.length) {
    el.innerHTML =
      "<span class='ov-none'>No overrides set — every variable uses LibreLane's default for this PDK. " +
      "Pick a preset or edit a field to override.</span> " + viewCfg;
    wireViewCfg();
    return;
  }
  const chips = keys
    .map((k) => "<button class='ov-chip ov-chip-btn' data-ovvar='" + fmt.escape(k) +
      "' title='Where does this setting go? Click for the exact file/line trail.'><code>" +
      fmt.escape(k) + "</code>=<b>" + fmt.escape(String(ov[k])) + "</b></button>")
    .join("");
  el.innerHTML =
    "<div class='ov-head'><strong>" + keys.length + " override" + (keys.length === 1 ? "" : "s") +
    " will be sent</strong> <span class='muted'>(preset values + your edits; unset fields use defaults — click a chip to trace where it goes)</span> " +
    viewCfg + "</div>" +
    "<div class='ov-chips'>" + chips + "</div>";
  wireViewCfg();
  el.querySelectorAll("[data-ovvar]").forEach((b) => {
    if (b._wired) return;
    b._wired = true;
    b.addEventListener("click", () => showOverrideTrail(b.dataset.ovvar, activeOverrides()[b.dataset.ovvar]));
  });
}

// Input-side transparency: for one override, show exactly (a) how it reaches
// the flow (a `-c VAR=VALUE` argument — the design's own config file is never
// edited), (b) the config file + line it supersedes, quoted, or the honest
// statement that the file doesn't set it and nothing is inserted anywhere,
// and (c) after a run, the resolved.json line proving the value LibreLane
// ACTUALLY used. Both lookups are fetched up front so the dialog STATES the
// file names, line numbers and exact lines instead of hiding them behind
// buttons; the buttons then open each file at that highlighted line.
async function showOverrideTrail(varName, value) {
  const { customDialog } = await import("./dialog.js");
  const { openProvenance } = await import("./provenance.js");
  const runTag = state.selectedRunTag ||
    (Array.isArray(state.runs) && state.runs[0] && state.runs[0].tag) || null;

  const safeLookup = async (params) => {
    try { return await api.provenance(params); }
    catch (ex) { return { ok: false, reason: "lookup failed: " + (ex.message || ex) }; }
  };
  const [inp, run] = await Promise.all([
    safeLookup({ kind: "input", key: varName }),
    runTag ? safeLookup({ kind: "var", key: varName, tag: runTag }) : Promise.resolve(null),
  ]);

  const lineRow = (r) =>
    "<pre class='code ov-trail-line'>" + fmt.escape(r.text || "") + "</pre>";
  let cfgHtml;
  if (inp && inp.ok) {
    cfgHtml =
      "<p><b>" + fmt.escape(inp.rel) + "</b> sets it on <b>line " + inp.line + "</b> — " +
      "your override supersedes this line for the run (the file is not touched):</p>" +
      lineRow(inp);
  } else if (inp && inp.rel) {
    cfgHtml =
      "<p><b>" + fmt.escape(inp.rel) + "</b> does <b>not</b> set <code>" + fmt.escape(varName) +
      "</code> — nothing is inserted into your file at any line. The override simply adds " +
      "the value for the run; without it the flow would use the PDK/flow default.</p>";
  } else {
    cfgHtml = "<p class='muted'>" +
      fmt.escape((inp && inp.reason) || "no config file found in the design folder") + "</p>";
  }
  let runHtml;
  if (run && run.ok) {
    runHtml =
      "<p>Run <b>" + fmt.escape(runTag) + "</b> recorded the value it actually used in " +
      "<b>resolved.json</b> (LibreLane's own record), <b>line " + run.line + "</b>:</p>" +
      lineRow(run);
  } else if (runTag) {
    runHtml = "<p class='muted'>Run " + fmt.escape(runTag) + ": " +
      fmt.escape((run && run.reason) || "no resolved.json") + "</p>";
  } else {
    runHtml = "<p class='muted'>No runs yet — after a run, LibreLane's <code>resolved.json</code> " +
      "records the value the flow actually used, and it will be traceable here.</p>";
  }

  const choice = await customDialog({
    title: "Where does " + fmt.escape(varName) + " go?",
    bodyHtml:
      "<p>This setting rides the run command as an override argument — your design's " +
      "config file is <b>never edited</b>:</p>" +
      "<pre class='code'>-c " + fmt.escape(varName) + "=" + fmt.escape(String(value)) + "</pre>" +
      cfgHtml + runHtml,
    buttons: [
      (inp && inp.ok) ? { label: "Open " + inp.rel + " at line " + inp.line,
                          value: "input", cls: "btn-ghost" } : null,
      (run && run.ok) ? { label: "Open resolved.json at line " + run.line,
                          value: "var", cls: "btn-ghost" } : null,
      { label: "Close", value: undefined, cls: "btn-ghost" },
    ].filter(Boolean),
  });
  if (choice === "input") {
    openProvenance({ kind: "input", key: varName },
      { title: "Your config's own " + varName + " line (superseded by the override)" });
  } else if (choice === "var") {
    openProvenance({ kind: "var", key: varName, tag: runTag },
      { title: varName + " as run '" + runTag + "' actually used it (resolved.json)" });
  }
}

// Reflect the current SYNTH_SHOW override into the quick toggle (e.g. after a
// preset reset cleared it).
function syncReportToggles() {
  const ss = document.getElementById("cfg-synth-show");
  if (ss) ss.checked = state.varsValues.SYNTH_SHOW === true || state.varsValues.SYNTH_SHOW === "true";
}

function paint() {
  const root = document.getElementById("vars-form");
  if (!root) return;
  const nav = document.getElementById("config-nav");
  if (!nav) return;
  nav.innerHTML = "";
  root.innerHTML = "";
  // Mirror the same category milestones into the Setup jump bar's second tier
  // (revealed when the Constraints card is open — see setup.js).
  const subnav = document.getElementById("setup-jump-config");
  if (subnav) subnav.innerHTML = "";

  const buckets = new Map(STAGE_GROUPS.map((g) => [g.id, []]));
  const sorted = [...state.variables].sort((a, b) => a.name.localeCompare(b.name));
  for (const v of sorted) {
    if (_searchTerm && !v.name.toUpperCase().includes(_searchTerm) && !(v.description || "").toUpperCase().includes(_searchTerm))
      continue;
    buckets.get(groupFor(v.name, v)).push(v);
  }
  for (const [stageId, vs] of buckets) {
    if (!vs.length) continue;
    const def = STAGE_GROUPS.find((g) => g.id === stageId);
    const heading = document.createElement("h3");
    heading.id = "cfg-section-" + stageId;
    heading.className = "config-anchor";
    heading.textContent = def.name + " · " + vs.length;
    if (def.description) {
      const sub = document.createElement("div");
      sub.className = "hint";
      sub.style.marginBottom = "var(--s-3)";
      sub.textContent = def.description;
      root.appendChild(heading);
      root.appendChild(sub);
    } else {
      root.appendChild(heading);
    }
    const navChip = document.createElement("button");
    navChip.className = "nav-chip";
    navChip.type = "button";
    navChip.textContent = def.name + " (" + vs.length + ")";
    navChip.addEventListener("click", () => jumpToSection(stageId, navChip));
    nav.appendChild(navChip);
    if (subnav) {
      const c2 = document.createElement("button");
      c2.className = "chip chip-clickable";
      c2.type = "button";
      c2.textContent = def.name + " (" + vs.length + ")";
      // From the top-of-page milestone rail: make sure the Constraints card is
      // open, then scroll to that category.
      c2.addEventListener("click", () => openConstraintsAndJump(stageId));
      subnav.appendChild(c2);
    }
    const grid = document.createElement("div");
    grid.className = "vars-form";
    for (const v of vs) grid.appendChild(buildRow(v));
    root.appendChild(grid);
  }
  annotateConfigLines(root);
}

// ---- the "your config" tier -------------------------------------------
// Between LibreLane's default and any override sits the design's OWN config
// file. Annotate each field with what that file sets, as written, so
// "default: 50" can never be misread when config.json/.yaml sets 45 — the
// untouched-field value is the config's, not the default. One bulk lookup;
// chips appear when it lands (the form never waits on it). Scoped
// (pdk::/scl::) entries are labelled conditional: LanEx never resolves
// whether a scope applies — that is LibreLane's job, and resolved.json is
// the post-run proof. No chip = the file does not set that variable.
let _cfgMapSeq = 0;
async function annotateConfigLines(root) {
  const seq = ++_cfgMapSeq;
  let map = null, prov = null;
  try {
    map = await api.provenance({ kind: "input-map" });
    prov = await import("./provenance.js");
  } catch { /* no chip = no claim */ }
  if (seq !== _cfgMapSeq || !map || !prov || map.ok === false || !map.vars) return;
  root.querySelectorAll(".var-row[data-var]").forEach((row) => {
    const e = map.vars[row.dataset.var];
    if (!e || row.querySelector(".vconfig")) return;
    const spec = prov.configChipSpec(e, map.rel);
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "vconfig" + (spec.scoped ? " vconfig-scoped" : "");
    chip.title = spec.title;
    chip.textContent = spec.text;  // textContent: file bytes can't inject HTML
    chip.addEventListener("click", () =>
      prov.openProvenance({ kind: "input", key: row.dataset.var },
        { title: "Your config's own " + row.dataset.var + " line" }));
    row.querySelector(".vname")?.appendChild(chip);
  });
}

function jumpToSection(id, navChip) {
  const target = document.getElementById("cfg-section-" + id);
  if (!target) return;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  document.querySelectorAll(".config-nav .nav-chip").forEach((c) => c.classList.remove("nav-active"));
  if (navChip) navChip.classList.add("nav-active");
}

// Open the (collapsed-by-default) Constraints card, then jump to a category.
// Used by the Setup jump bar's milestone rail, which lives above the card.
function openConstraintsAndJump(id) {
  const card = document.getElementById("cfg-card");
  if (card && !card.open) {
    card.open = true;
    // Let the <details> lay out before scrolling to the now-visible section.
    requestAnimationFrame(() => jumpToSection(id, null));
  } else {
    jumpToSection(id, null);
  }
}

function buildRow(v) {
  const row = document.createElement("div");
  row.className = "var-row";
  row.dataset.var = v.name;
  const id = "var-" + v.name;
  // B4: show LibreLane's own default for every field so a pre-filled value is
  // never mistaken for something the user typed. Empty default => explicit
  // "no default" (required / PDK-derived), which is itself information.
  const defStr = (v.default === undefined || v.default === null) ? "" : String(v.default);
  const defaultChip = defStr !== ""
    ? "<span class='vdefault' title='LibreLane default'>default: " + fmt.escape(defStr) + "</span>"
    : "<span class='vdefault vdefault-none' title='No LibreLane default (required, or derived from the PDK/flow)'>no default</span>";
  row.innerHTML =
    "<div class='vname'>" +
    "<span class='name'>" + fmt.escape(v.name) + "</span>" +
    (v.type ? "<span class='type'>" + fmt.escape(v.type) + "</span>" : "") +
    (v.pdk ? "<span class='flag'>PDK</span>" : "") +
    (v.units ? "<span class='units'>" + fmt.escape(v.units) + "</span>" : "") +
    defaultChip +
    "</div>" +
    "<div class='vdesc'>" + fmt.escape(v.description || "") + "</div>" +
    inputFor(v, id) +
    "<button type='button' class='var-reset' title='Reset to LibreLane default' aria-label='Reset " +
      fmt.escape(v.name) + " to default'>↺</button>";
  const input = row.querySelector("#" + cssEscape(id));
  const resetBtn = row.querySelector(".var-reset");
  const syncReset = () => { if (resetBtn) resetBtn.hidden = state.varsValues[v.name] === undefined; };
  // "modified" = the current value is an explicit override that differs from the
  // default; the CSS gives it an accent left-border so the form scannably shows
  // exactly what you are overriding.
  const syncModified = () => {
    const cur = state.varsValues[v.name];
    row.classList.toggle("modified", cur !== undefined && String(cur) !== defStr);
  };
  if (input) {
    input.addEventListener("input", (e) => {
      const value = v.type === "bool" ? e.target.value === "true" : e.target.value;
      state.varsValues[v.name] = value;
      syncReset();
      syncModified();
      renderOverridesSummary();
    });
  }
  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      // Drop the override so the field falls back to LibreLane's own default.
      delete state.varsValues[v.name];
      const def = v.default;
      if (input) input.value = (def === undefined || def === null) ? "" : String(def);
      syncReset();
      syncModified();
      renderOverridesSummary();
    });
  }
  syncReset();
  syncModified();
  return row;
}

function inputFor(v, id) {
  const cur = state.varsValues[v.name] !== undefined ? state.varsValues[v.name] : v.default;
  const str = cur === null || cur === undefined ? "" : String(cur);
  if (v.type === "bool" || v.type === "Boolean") {
    return (
      "<select id='" + id + "'>" +
      "<option value='true'" + (str === "true" ? " selected" : "") + ">true</option>" +
      "<option value='false'" + (str === "false" ? " selected" : "") + ">false</option>" +
      "</select>"
    );
  }
  // Literal / Enum variables expose their allowed values in `choices` (from the
  // backend's typing introspection). Render a real dropdown so users can't enter
  // an invalid value. An optional variable gets a blank "(default)" entry.
  if (Array.isArray(v.choices) && v.choices.length) {
    const blank = v.optional
      ? "<option value=''" + (str === "" ? " selected" : "") + ">(default)</option>"
      : "";
    const opts = v.choices
      .map((s) => "<option value='" + fmt.escape(s) + "'" + (str === String(s) ? " selected" : "") + ">" + fmt.escape(s) + "</option>")
      .join("");
    return "<select id='" + id + "'>" + blank + opts + "</select>";
  }
  return "<input type='text' id='" + id + "' value='" + fmt.escape(str) + "' />";
}

function cssEscape(s) {
  const _ = typeof CSS !== "undefined" && CSS.escape;
  if (_) return CSS.escape(s);
  return String(s).replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c);
}
