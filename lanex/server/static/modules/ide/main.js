// main.js — the RTL IDE. Runs both as the standalone /ide page and embedded as
// the "RTL IDE" tab in the cockpit. The layout follows the editors and FPGA
// tools people already know: an explorer with the project's files sorted by
// what they are for (design, simulation, constraints, project), open-file tabs
// over a syntax-highlighting editor, and a full-width bottom panel with the
// Verilator syntax check (Problems), the simulator's output and the waveform.
// The day-to-day loop is write → Check syntax → Simulate, before the long
// RTL-to-GDS run. Shares api.js + SSE; no bundler.
import { api, sse, fmt } from "../api.js";
import { Editor } from "./editor.js";
import { parseVCD, vcdToCSV } from "./vcd.js";
import { WaveView, defaultLanes } from "./waves.js";
import { setupFullscreen } from "../fullscreen.js";
import { applyZoom, currentZoom } from "../zoom.js";

const state = {
  designDir: null, files: [], top: null, topAbs: null,
  tabs: [], active: null, explicitOpen: false, diags: [],
  runMode: "container", wave: null, lastWavePath: null, gtkwaveInstallArmed: false,
};
let _inited = false;

// The standalone /ide page hardcodes `theme-dark` and doesn't run the main
// app's setupTheme(), so a pop-out always opened dark even when the user picked
// light. Apply the persisted `ll.theme` here, and live-sync if it changes in the
// main window (cross-window `storage` event). Idempotent for the embedded tab.
function applyTheme() {
  let light = false;
  try { light = localStorage.getItem("ll.theme") === "light"; } catch (_e) {}
  document.body.classList.toggle("theme-light", light);
  document.body.classList.toggle("theme-dark", !light);
}
function setupThemeSync() {
  applyTheme();
  applyZoom(currentZoom());            // pop-out matches the cockpit's UI zoom
  window.addEventListener("storage", (e) => {
    if (!e || e.key === "ll.theme") {
      applyTheme();
      document.dispatchEvent(new CustomEvent("g:theme_changed", { detail: { dark: !document.body.classList.contains("theme-light") } }));
    }
    if (!e || e.key === "ll.zoom") applyZoom(currentZoom());
  });
}

// Entry point. opts.designDir/runMode override discovery (the embedded tab knows
// them from the main app); the standalone page discovers them itself.
export async function initIde(opts = {}) {
  setupThemeSync();
  if (_inited) {
    // Re-activated tab: another project means a fresh set of tabs; the same
    // project just picks up files made elsewhere (Setup's New file, Add files).
    if (opts.designDir && opts.designDir !== state.designDir) {
      state.designDir = opts.designDir;
      state.tabs = [];
      state.active = null;
      state.explicitOpen = false;
      setDesignLabel();
      renderTabs();
    }
    await loadTree();
    await loadTestbenches();
    autoOpen();
    return;
  }
  _inited = true;

  if (opts.designDir) {
    state.designDir = opts.designDir;
  } else {
    try { const dd = await api.designDir(); state.designDir = dd && dd.design_dir; } catch (_e) {}
    const qd = new URLSearchParams(location.search).get("design_dir");
    if (qd) { try { await api.setDesignDir(qd); state.designDir = qd; } catch (_e) {} }
  }
  try { state.runMode = opts.runMode || localStorage.getItem("ll.runMode") || "container"; } catch (_e) {}

  setDesignLabel();
  setupFullscreen();   // idempotent; needed on the standalone /ide page too
  window.ideEditor = new Editor(document.getElementById("ide-editor"));
  wireEditor();
  byId("ide-save", (b) => b.addEventListener("click", saveFile));
  byId("ide-lint", (b) => b.addEventListener("click", lint));
  setupAutoLint();
  byId("ide-sim", (b) => b.addEventListener("click", simulate));
  byId("ide-sim-stop", (b) => b.addEventListener("click", stopSim));
  byId("ide-find", (b) => b.addEventListener("click", () => window.ideEditor.openFind()));
  byId("ide-wave-csv", (b) => b.addEventListener("click", exportWaveCsv));
  byId("ide-wave-png", (b) => b.addEventListener("click", exportWavePng));
  byId("ide-wave-gtkwave", (b) => b.addEventListener("click", openInGtkwave));
  byId("ide-wave-zoomin", (b) => b.addEventListener("click", () => state.wave && state.wave.zoomIn()));
  byId("ide-wave-zoomout", (b) => b.addEventListener("click", () => state.wave && state.wave.zoomOut()));
  byId("ide-wave-fit", (b) => b.addEventListener("click", () => state.wave && state.wave.fit()));
  byId("ide-new-file", (b) => b.addEventListener("click", () => newFile()));
  wireUpload();
  wireTree();
  wireTabs();
  wirePanel();
  document.querySelectorAll(".wave-radix").forEach((b) =>
    b.addEventListener("click", () => {
      if (state.wave) state.wave.setRadix(b.dataset.radix);
      document.querySelectorAll(".wave-radix").forEach((x) => x.classList.toggle("is-on", x === b));
    }));
  document.querySelector('.wave-radix[data-radix="hex"]')?.classList.add("is-on");
  byId("ide-tb", (sel) => sel.addEventListener("change", deriveTopFromTb));

  sse.open();
  sse.on(onEvent);
  await loadTree();
  await loadTestbenches();
  autoOpen();
}

function byId(id, fn) { const el = document.getElementById(id); if (el) fn(el); }

// /mnt/c/Users/... is C:\Users\... to a Windows user.
function shownPath(p) {
  const m = String(p || "").match(/^\/mnt\/([a-z])(\/.*)?$/);
  return m ? m[1].toUpperCase() + ":" + (m[2] || "/").replace(/\//g, "\\") : String(p || "");
}

function setDesignLabel() {
  byId("ide-design", (el) => {
    el.textContent = state.designDir ? shownPath(state.designDir) : "No project open";
    el.title = state.designDir || "";
  });
}

// ------------------------------------------------------------------ new files

// Every kind of file a LibreLane project uses. The server writes the starter
// content (controller/projectfiles.py) and, for the kinds the flow reads
// through a config variable, points the config at the new file.
const KINDS = [
  { group: "Design", items: [
    { kind: "module_v", label: "Verilog module (.v)", ph: "alu", help: "Goes in src/ and into the chip. A new module joins the config's file list." },
    { kind: "module_sv", label: "SystemVerilog module (.sv)", ph: "alu", help: "Goes in src/ and into the chip. LibreLane reads it as SystemVerilog." },
  ] },
  { group: "Simulation", items: [
    { kind: "tb_v", label: "Verilog testbench (.v)", ph: "alu_tb", help: "Goes in verify/. Simulation only, never built into the chip." },
    { kind: "tb_sv", label: "SystemVerilog testbench (.sv)", ph: "alu_tb", help: "Goes in verify/. Simulation only, never built into the chip." },
  ] },
  { group: "Constraints", items: [
    { kind: "sdc", label: "Timing constraints (.sdc)", ph: "timing", use: true,
      help: "Starts as LibreLane's own default constraints, so nothing changes until you edit it." },
    { kind: "pins", label: "Pin order (.cfg)", ph: "pin_order", use: true,
      help: "Lists every port of the top module on a chip edge: clock and reset at the bottom, inputs left, outputs right." },
  ] },
  { group: "Other", items: [
    { kind: "header_vh", label: "Include file (.vh)", ph: "defs", help: "Shared `define macros, pulled in with `include. Not listed in the config." },
    { kind: "header_svh", label: "SystemVerilog include (.svh)", ph: "defs", help: "Shared `define macros, pulled in with `include. Not listed in the config." },
    { kind: "memory", label: "Memory contents (.hex)", ph: "rom", help: "Initial contents for a memory, loaded with $readmemh." },
    { kind: "other", label: "Other text file", ph: "notes.md", help: "Any file LanEx can edit: .md, .txt, .tcl, .json, .yaml …" },
  ] },
];
const ALL = KINDS.flatMap((g) => g.items);
const LEGACY = { src: "module_v", tb: "tb_v" };

export async function newFile(kind) {
  if (!state.designDir) { note("Open a project first (Setup tab).", true); return; }
  kind = LEGACY[kind] || kind || "module_v";
  if (!ALL.some((k) => k.kind === kind)) kind = "module_v";
  const { customDialog } = await import("../dialog.js");
  let picked = null;
  const opts = KINDS.map((g) => "<optgroup label='" + g.group + "'>" +
    g.items.map((k) => "<option value='" + k.kind + "'" + (k.kind === kind ? " selected" : "") + ">" + fmt.escape(k.label) + "</option>").join("") +
    "</optgroup>").join("");
  const res = await customDialog({
    title: "New file",
    bodyHtml:
      "<div class='newfile'>" +
      "<label class='wiz-field'><span>Kind</span><select id='nf-kind'>" + opts + "</select>" +
      "<span class='wiz-help' id='nf-help'></span></label>" +
      "<label class='wiz-field'><span id='nf-name-label'>Name</span><input id='nf-name' type='text' spellcheck='false' autocomplete='off'/></label>" +
      "<label class='nf-use' id='nf-use-row'><input type='checkbox' id='nf-use' checked/> <span id='nf-use-text'></span></label>" +
      "</div>",
    buttons: [
      { label: "Cancel", value: null, cls: "btn-ghost" },
      { label: "Create", value: "ok", cls: "btn-primary" },
    ],
    onMount: (back) => {
      const sel = back.querySelector("#nf-kind");
      const input = back.querySelector("#nf-name");
      const create = back.querySelector(".btn-primary");
      const paint = () => {
        const k = ALL.find((x) => x.kind === sel.value);
        back.querySelector("#nf-help").textContent = k.help;
        back.querySelector("#nf-name-label").textContent = /^(module|tb)/.test(k.kind) ? "Module name" : "File name";
        if (!input.dataset.touched) input.value = k.kind.startsWith("tb") && state.top ? state.top + "_tb" : k.ph;
        back.querySelector("#nf-use-row").hidden = !k.use;
        back.querySelector("#nf-use-text").textContent = k.kind === "sdc"
          ? "Use it for this project's runs (sets PNR_SDC_FILE and SIGNOFF_SDC_FILE in the config)"
          : "Use it for this project's runs (sets IO_PIN_ORDER_CFG in the config)";
      };
      sel.addEventListener("change", paint);
      input.addEventListener("input", () => { input.dataset.touched = "1"; });
      paint();
      // Read the fields before the dialog closes and removes them.
      create?.addEventListener("click", () => {
        picked = { kind: sel.value, name: (input.value || "").trim(), use: back.querySelector("#nf-use").checked };
      }, true);
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); create?.click(); }
      });
      setTimeout(() => { input.focus(); input.select(); }, 0);
    },
  });
  if (res !== "ok" || !picked) return;
  if (!picked.name) { note("Give the file a name.", true); return; }
  // SDC and pin files are written for the top module named in the config.
  let top = null, clock = null;
  if (picked.kind === "sdc" || picked.kind === "pins" || picked.kind.startsWith("tb")) {
    try {
      const info = await api.designInfo({ design_dir: state.designDir });
      top = (info.values && info.values.DESIGN_NAME) || info.suggested_top || null;
      const cp = info.values && info.values.CLOCK_PORT;
      clock = Array.isArray(cp) ? cp[0] : cp || null;
    } catch (_e) { /* the server says what's missing */ }
  }
  try {
    const r = await api.newProjectFile({ design_dir: state.designDir, kind: picked.kind, name: picked.name,
      top, clock, use: picked.use });
    await loadTree();
    await loadTestbenches();
    await openFile(r.abs, r.rel);
    const cfg = r.config && r.config.changed && r.config.changed.length
      ? " and updated " + r.config.name + " (" + r.config.changed.join(", ") + ")" : "";
    note(r.config_error ? "Created " + r.rel + ", but the config wasn't updated: " + r.config_error
      : "Created " + r.rel + cfg + ".", !!r.config_error);
    document.dispatchEvent(new CustomEvent("g:sources_changed"));
  } catch (ex) {
    note("Could not create the file: " + (ex.message || ex), true);
  }
}

// Called from the Setup tab: open a project file (or start a new one) here.
export async function openInIde({ rel = "", create = "" } = {}) {
  if (rel && state.designDir) {
    state.explicitOpen = true;
    await loadTree();
    await openFile(state.designDir.replace(/\/+$/, "") + "/" + rel, rel);
  } else if (create) {
    state.explicitOpen = true;
    await newFile(create);
  }
}

// ------------------------------------------------------------------ explorer

// The explorer's groups, in the order a design is built: what goes into the
// chip, what only simulates it, what constrains it, and the project itself.
const GROUPS = [
  { name: "Design", roles: ["design", "header", "memory", "vhdl"], add: "module_v", addLabel: "New design module" },
  { name: "Simulation", roles: ["testbench"], add: "tb_v", addLabel: "New testbench",
    empty: "No testbench yet. <button class='linklike' data-new='tb_v'>Write one</button> to simulate the design before the long run." },
  { name: "Constraints", roles: ["timing", "pins"], add: "sdc", addLabel: "New constraints file",
    empty: "Timing comes from the clock period in the config. <button class='linklike' data-new='sdc'>Create an SDC file</button> for I/O delays, false paths or more clocks." },
  { name: "Project", roles: ["config", "other"], add: "other", addLabel: "New text file" },
];
const PLUS = "<svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' aria-hidden='true'><path d='M12 5v14M5 12h14'/></svg>";
const XMARK = "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg>";

async function loadTree() {
  const tree = document.getElementById("ide-tree");
  if (!tree) return;
  if (!state.designDir) {
    state.files = [];
    tree.innerHTML = "<p class='muted'>No project open. Open or create one on the Setup tab.</p>";
    renderStart();
    return;
  }
  let res;
  try { res = await api.projectFiles(state.designDir); } catch (_e) { return; }
  state.files = (res.files || []).map((f) => ({ relpath: f.rel, abspath: f.abs, role: f.role, built: !!f.in_verilog_files }));
  // The top module's file gets a tag, and is what the IDE opens first.
  try {
    const info = await api.designInfo({});
    state.top = (info.values && info.values.DESIGN_NAME) || info.suggested_top || null;
    state.topAbs = (state.top && (info.module_files || {})[state.top]) || null;
  } catch (_e) { state.top = null; state.topAbs = null; }
  renderTree();
}

function fileRow(f) {
  const cut = f.relpath.lastIndexOf("/");
  const dir = cut >= 0 ? f.relpath.slice(0, cut + 1) : "";
  const base = f.relpath.slice(cut + 1);
  const out = f.role === "design" && !f.built && state.files.some((x) => x.built);
  const tags = (f.abspath === state.topAbs ? "<span class='tag is-top'>top</span>" : "") +
    (out ? "<span class='tag' title='Not in the config&#39;s file list, so it isn&#39;t built into the chip. Tick it under Sources on the Setup tab.'>not built</span>" : "");
  return "<div class='ide-file-row" + (f.abspath === state.active ? " is-active" : "") + (out ? " is-out" : "") +
    "' data-abs='" + fmt.escape(f.abspath) + "'>" +
    "<button class='ide-file' data-abs='" + fmt.escape(f.abspath) + "' data-rel='" + fmt.escape(f.relpath) + "' title='" + fmt.escape(f.relpath) + "'>" +
    "<span class='fn'><span class='dir'>" + fmt.escape(dir) + "</span>" + fmt.escape(base) + "</span>" + tags + "</button>" +
    "<button class='ide-file-del' title='Delete " + fmt.escape(f.relpath) + "' aria-label='Delete " + fmt.escape(f.relpath) +
    "' data-rel='" + fmt.escape(f.relpath) + "'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3'/></svg></button></div>";
}

function renderTree() {
  const tree = document.getElementById("ide-tree");
  if (!tree) return;
  tree.innerHTML = GROUPS.map((g) => {
    const files = state.files.filter((f) => g.roles.includes(f.role));
    if (!files.length && !g.empty && g.name !== "Design") return "";
    const body = files.length ? files.map(fileRow).join("")
      : "<p class='ide-group-empty'>" + (g.empty || "No design files yet. <button class='linklike' data-new='module_v'>Write a module</button>.") + "</p>";
    return "<div class='ide-group'><span class='ide-group-name'>" + g.name + "</span>" +
      "<button class='ide-group-add' data-new='" + g.add + "' title='" + g.addLabel + "' aria-label='" + g.addLabel + "'>" + PLUS + "</button></div>" + body;
  }).join("");
}

function wireTree() {
  const tree = document.getElementById("ide-tree");
  if (!tree) return;
  tree.addEventListener("click", (e) => {
    const n = e.target.closest("[data-new]");
    if (n) { newFile(n.dataset.new); return; }
    const del = e.target.closest(".ide-file-del");
    if (del) { e.stopPropagation(); deleteFile(del.dataset.rel); return; }
    const f = e.target.closest(".ide-file");
    if (f) openFile(f.dataset.abs, f.dataset.rel);
  });
}

// Remove a file from the project (guarded server-side delete).
async function deleteFile(rel) {
  if (!rel) return;
  const { confirmDialog } = await import("../dialog.js");
  const ok = await confirmDialog({
    title: "Delete file", danger: true, confirmText: "Delete",
    body: "Delete " + rel + " from the project folder? This cannot be undone.",
  });
  if (!ok) return;
  try {
    const r = await api.fileDelete(rel);
    if (!r.ok) throw new Error(r.error || "refused");
    note("Deleted " + rel);
    const t = state.tabs.find((x) => x.rel === rel);
    if (t) { t.saved = t.text; closeTab(t.abs, { force: true }); }
    await loadTree();
    await loadTestbenches();
    document.dispatchEvent(new CustomEvent("g:sources_changed"));
  } catch (ex) {
    note("Delete failed: " + (ex.message || ex), true);
  }
}

// ------------------------------------------------------------------ tabs

function activeTab() { return state.tabs.find((t) => t.abs === state.active) || null; }

// Keep the editor's text in its tab before showing another file.
function stash() {
  const t = activeTab();
  const ed = window.ideEditor;
  if (t && ed && ed.relPath === t.rel) t.text = ed.getValue();
}

// Tabs are keyed by the project-relative path: the server's resolved path
// and one built from the design folder can differ, the relative one can't.
// Two opens of the same file in flight share one read.
const _opening = new Map();
async function openFile(abs, rel) {
  let t = state.tabs.find((x) => x.rel === rel);
  if (!t) {
    if (!_opening.has(rel)) {
      _opening.set(rel, api.readText(abs).finally(() => _opening.delete(rel)));
    }
    try {
      const r = await _opening.get(rel);
      if (r.text === undefined) throw new Error(r.error || "unreadable");
      t = state.tabs.find((x) => x.rel === rel);
      if (!t) {
        const f = state.files.find((x) => x.relpath === rel);
        t = { abs: f ? f.abspath : abs, rel, text: r.text, saved: r.text };
        state.tabs.push(t);
      }
    } catch (ex) {
      note("Could not open: " + (ex.message || ex), true);
      return;
    }
  }
  activate(t);
}

function activate(t) {
  stash();
  state.active = t.abs;
  const ed = window.ideEditor;
  ed.load(t.rel, t.text);
  applyMarkers();
  byId("ide-open", (el) => { el.textContent = t.rel; el.title = shownPath(t.abs); });
  renderTabs();
  renderStart();
  document.querySelectorAll("#ide-tree .ide-file-row").forEach((r) => r.classList.toggle("is-active", r.dataset.abs === t.abs));
  // Opening a testbench makes it the one Simulate runs.
  const f = state.files.find((x) => x.abspath === t.abs);
  if (f && f.role === "testbench") {
    byId("ide-tb", (sel) => {
      if ([...sel.options].some((o) => o.value === f.relpath)) { sel.value = f.relpath; byId("ide-top", (x) => { x.value = ""; }); deriveTopFromTb(); }
    });
  }
}

async function closeTab(abs, { force = false } = {}) {
  stash();
  const i = state.tabs.findIndex((x) => x.abs === abs);
  if (i < 0) return;
  const t = state.tabs[i];
  if (!force && t.text !== t.saved) {
    const { confirmDialog } = await import("../dialog.js");
    const ok = await confirmDialog({ title: "Close without saving?", danger: true, confirmText: "Close",
      body: t.rel + " has changes that aren't saved. Close it and lose them?" });
    if (!ok) return;
  }
  state.tabs.splice(i, 1);
  if (state.active === abs) {
    state.active = null;
    const next = state.tabs[i] || state.tabs[i - 1];
    if (next) activate(next);
    else {
      window.ideEditor.load(null, "");
      byId("ide-open", (el) => { el.textContent = "No file open"; el.title = ""; });
      document.querySelectorAll("#ide-tree .ide-file-row").forEach((r) => r.classList.remove("is-active"));
    }
  }
  renderTabs();
  renderStart();
}

function renderTabs() {
  const host = document.getElementById("ide-tabs");
  if (!host) return;
  host.innerHTML = state.tabs.map((t) => {
    const name = t.rel.split("/").pop();
    return "<div class='ide-tab" + (t.abs === state.active ? " is-on" : "") + (t.text !== t.saved ? " is-dirty" : "") +
      "' role='tab' aria-selected='" + (t.abs === state.active) + "' tabindex='0' data-abs='" + fmt.escape(t.abs) + "' title='" + fmt.escape(t.rel) + "'>" +
      "<span class='fn'>" + fmt.escape(name) + "</span>" +
      "<span class='x' role='button' aria-label='Close " + fmt.escape(name) + "' data-close='" + fmt.escape(t.abs) + "'>" + XMARK + "</span></div>";
  }).join("");
}

function wireTabs() {
  const host = document.getElementById("ide-tabs");
  if (!host) return;
  host.addEventListener("click", (e) => {
    const x = e.target.closest("[data-close]");
    if (x) { closeTab(x.dataset.close); return; }
    const tab = e.target.closest(".ide-tab");
    const t = tab && state.tabs.find((y) => y.abs === tab.dataset.abs);
    if (t && t.abs !== state.active) activate(t);
  });
  host.addEventListener("auxclick", (e) => {     // middle-click closes, as in every editor
    const tab = e.target.closest(".ide-tab");
    if (tab && e.button === 1) closeTab(tab.dataset.abs);
  });
  host.addEventListener("keydown", (e) => {
    const tab = e.target.closest(".ide-tab");
    if (tab && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); tab.click(); }
  });
}

// Typing marks the tab unsaved; Ctrl+S saves, as anywhere else.
function wireEditor() {
  const ed = window.ideEditor;
  ed.area.addEventListener("input", () => {
    const t = activeTab();
    if (!t) return;
    t.text = ed.getValue();
    const el = document.querySelector("#ide-tabs .ide-tab.is-on");
    if (el) el.classList.toggle("is-dirty", t.text !== t.saved);
  });
  ed.area.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); saveFile(); }
  });
}

// Open the top module (or the first design file) when nothing is open yet.
function autoOpen() {
  if (state.tabs.length || state.explicitOpen || !state.designDir) { renderStart(); return; }
  const first = state.topAbs ? state.files.find((f) => f.abspath === state.topAbs)
    : state.files.find((f) => f.role === "design");
  if (first) openFile(first.abspath, first.relpath);
  else renderStart();
}

// With no file open, the editor area shows the loop this IDE is for.
function renderStart() {
  const el = document.getElementById("ide-start");
  if (!el) return;
  el.hidden = state.tabs.length > 0;
  byId("ide-cursor", (c) => { c.hidden = !state.tabs.length; });
  if (!el.hidden) {
    const top = state.topAbs && state.files.find((f) => f.abspath === state.topAbs);
    const hasTb = state.files.some((f) => f.role === "testbench");
    el.innerHTML = !state.designDir
      ? "<h3>No project open</h3><p>Open or create a project on the Setup tab, and its files appear here.</p>"
      : "<h3>Nothing open</h3><p>Pick a file on the left, or start here. The usual loop: write the design, check its syntax, " +
        "simulate it with a testbench, and only then run the RTL-to-GDS flow, which takes minutes rather than seconds.</p>" +
        "<div class='ide-start-acts'>" +
        (top ? "<button class='btn btn-primary btn-sm' data-start='open-top'>Open " + fmt.escape(top.relpath) + "</button>" : "") +
        "<button class='btn btn-sm" + (top ? "" : " btn-primary") + "' data-new='module_v'>New design module</button>" +
        "<button class='btn btn-sm' data-new='tb_v'>" + (hasTb ? "New testbench" : "Write a testbench") + "</button></div>" +
        "<ol class='ide-path'>" +
        "<li><b><span>1</span>Write</b><small>Design modules go in <code>src/</code> and into the chip.</small></li>" +
        "<li><b><span>2</span>Check syntax</b><small>Verilator reads every file; errors land in Problems with their line.</small></li>" +
        "<li><b><span>3</span>Simulate</b><small>A testbench in <code>verify/</code> drives the design; the waveform shows below.</small></li>" +
        "<li><b><span>4</span>Run the flow</b><small>Setup checks the project, PDK and engine, then Run builds the GDS.</small></li></ol>";
  }
  if (!el._wired) {
    el._wired = true;
    el.addEventListener("click", (e) => {
      const n = e.target.closest("[data-new]");
      if (n) { newFile(n.dataset.new); return; }
      if (e.target.closest("[data-start='open-top']")) {
        const f = state.files.find((x) => x.abspath === state.topAbs);
        if (f) openFile(f.abspath, f.relpath);
      }
    });
  }
}

// ------------------------------------------------------------------ save

async function saveFile() {
  const ed = window.ideEditor;
  const t = activeTab();
  if (!t || !ed.relPath) { note("Open a file first.", true); return; }
  const text = ed.getValue();
  try {
    const r = await api.fileWrite(t.rel, text);
    if (!r.ok) throw new Error(r.error || "write refused");
    t.text = text;
    t.saved = text;
    renderTabs();
    note("Saved " + t.rel);
    // The Setup page reads the config and the file list; let it catch up.
    document.dispatchEvent(new CustomEvent("g:sources_changed"));
  } catch (ex) {
    note("Save failed: " + (ex.message || ex), true);
  }
}

// Opt-in auto-check: a moment after the user stops typing, save the current
// Verilog buffer and re-run the standalone Verilator lint so markers stay
// current. Off by default, persisted. Saving is needed because lint reads files
// on disk.
let _autoLintTimer = null;
function setupAutoLint() {
  const cb = document.getElementById("ide-autolint");
  const ed = window.ideEditor;
  if (!cb || !ed || !ed.area) return;
  try { cb.checked = localStorage.getItem("ll.autolint") === "1"; } catch (_e) {}
  cb.addEventListener("change", () => {
    try { localStorage.setItem("ll.autolint", cb.checked ? "1" : "0"); } catch (_e) {}
  });
  ed.area.addEventListener("input", () => {
    if (!cb.checked) return;
    if (!ed.relPath || !/\.s?v$/.test(ed.relPath)) return;   // Verilog/SV only
    clearTimeout(_autoLintTimer);
    _autoLintTimer = setTimeout(autoLint, 800);
  });
}

async function autoLint() {
  const ed = window.ideEditor;
  const t = activeTab();
  if (!ed || !ed.relPath || !t) return;
  try {
    const text = ed.getValue();
    const w = await api.fileWrite(t.rel, text);
    if (!w.ok) return;
    t.saved = text;
    renderTabs();
  } catch (_e) { return; }
  lint({ quiet: true });
}

// Add files from the computer: Verilog to src/, testbenches to verify/,
// anything else at the top of the project. New design files join the config's
// file list (the Setup page does that, through the same path as its ticks).
function wireUpload() {
  const btn = document.getElementById("ide-upload");
  if (!btn) return;
  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.accept = ".v,.sv,.vh,.svh,.vhd,.mem,.hex,.sdc,.cfg,.tcl,.json,.yaml,.yml,.txt,.md";
  input.hidden = true;
  btn.after(input);
  btn.addEventListener("click", () => {
    if (!state.designDir) { note("Open a project first (Setup tab).", true); return; }
    input.click();
  });
  input.addEventListener("change", async () => {
    const files = [...input.files];
    input.value = "";
    if (!files.length) return;
    const added = [];
    for (const f of files) {
      const isHdl = /\.(s?v|vh|svh)$/i.test(f.name);
      const isTb = /(^tb_|_tb\.|testbench)/i.test(f.name);
      const rel = (isHdl ? (isTb ? "verify/" : "src/") : "") + f.name;
      try {
        const r = await api.fileWrite(rel, await f.text());
        if (r.ok) added.push(rel); else note("Refused " + f.name + ": " + (r.error || "?"), true);
      } catch (ex) { note("Upload failed for " + f.name + ": " + (ex.message || ex), true); }
    }
    if (added.length) note("Added " + added.join(", "));
    const base = state.designDir.replace(/\/+$/, "") + "/";
    const design = added.filter((rel) => rel.startsWith("src/") && /\.s?v$/i.test(rel)).map((rel) => base + rel);
    if (design.length) document.dispatchEvent(new CustomEvent("g:sources_added", { detail: { files: design } }));
    document.dispatchEvent(new CustomEvent("g:sources_changed"));
    await loadTree();
    await loadTestbenches();
    if (added.length) {
      const f = state.files.find((x) => x.relpath === added[0]);
      if (f) openFile(f.abspath, f.relpath);
    }
  });
}

// ------------------------------------------------------------------ bottom panel

function setPanel(name) {
  document.querySelectorAll(".ide-ptab").forEach((b) => {
    const on = b.dataset.ptab === name;
    b.classList.toggle("is-on", on);
    b.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".ide-pane").forEach((p) => p.classList.toggle("is-on", p.dataset.pane === name));
  setPanelOpen(true);
  if (name === "wave") requestAnimationFrame(fitWave);
}

function setPanelOpen(open) {
  const c = document.querySelector(".ide-center");
  if (!c) return;
  c.classList.toggle("panel-closed", !open);
  byId("ide-panel-toggle", (b) => b.setAttribute("aria-label", open ? "Hide the panel" : "Show the panel"));
  try { localStorage.setItem("ll.idePanelOpen", open ? "1" : "0"); } catch (_e) {}
}

function wirePanel() {
  const center = document.querySelector(".ide-center");
  if (!center) return;
  document.querySelectorAll(".ide-ptab").forEach((b) => b.addEventListener("click", () => setPanel(b.dataset.ptab)));
  byId("ide-panel-toggle", (b) => b.addEventListener("click", () =>
    setPanelOpen(center.classList.contains("panel-closed"))));
  let h = null, open = "1";
  try { h = localStorage.getItem("ll.idePanelH"); open = localStorage.getItem("ll.idePanelOpen") || "1"; } catch (_e) {}
  if (h && +h >= 15 && +h <= 80) center.style.setProperty("--ide-panel-h", h + "%");
  if (open === "0") center.classList.add("panel-closed");
  // Drag the bar between the editor and the panel to share the height.
  const split = document.getElementById("ide-split");
  if (split) {
    const setPct = (pct) => {
      pct = Math.max(15, Math.min(80, pct));
      center.style.setProperty("--ide-panel-h", pct.toFixed(1) + "%");
      try { localStorage.setItem("ll.idePanelH", pct.toFixed(1)); } catch (_e) {}
      fitWave();
    };
    split.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      split.setPointerCapture(e.pointerId);
      split.classList.add("is-drag");
      const move = (ev) => {
        const r = center.getBoundingClientRect();
        setPct(((r.bottom - ev.clientY) / r.height) * 100);
      };
      const up = () => {
        split.classList.remove("is-drag");
        split.removeEventListener("pointermove", move);
        split.removeEventListener("pointerup", up);
      };
      split.addEventListener("pointermove", move);
      split.addEventListener("pointerup", up);
    });
    split.addEventListener("keydown", (e) => {
      const cur = parseFloat(getComputedStyle(center).getPropertyValue("--ide-panel-h")) || 36;
      if (e.key === "ArrowUp") { e.preventDefault(); setPct(cur + 5); }
      if (e.key === "ArrowDown") { e.preventDefault(); setPct(cur - 5); }
    });
  }
  const host = document.getElementById("ide-wave-host");
  if (host && "ResizeObserver" in window) {
    let raf = 0;
    new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(fitWave); }).observe(host);
  }
}

// ------------------------------------------------------------------ syntax check

async function lint({ quiet = false } = {}) {
  note("Checking the syntax with Verilator…");
  setLintBusy(true);
  armLintSafety();
  if (!quiet) setPanel("problems");
  // Every design and testbench file (a testbench is linted as a source too) —
  // a standalone verilator --lint-only job, not the hardening flow.
  const sources = state.files.filter((f) => /\.s?v$/.test(f.relpath)).map((f) => f.relpath);
  try {
    const start = await api.lintStart({ run_mode: state.runMode, sources });
    if (!start.ok) { note("Lint refused: " + (start.reason || start.error || "?"), true); setLintBusy(false); }
  } catch (ex) {
    // A 400 "a lint is already running" throws here too: reset so the button is
    // usable, and tell the user how to recover instead of looking frozen.
    note("Lint failed: " + (ex.message || ex), true);
    setLintBusy(false);
  }
}

function applyMarkers() {
  const ed = window.ideEditor;
  if (!ed) return;
  const mine = state.diags.filter((d) => ed.relPath && (d.file.endsWith(ed.relPath) || ed.relPath.endsWith(d.file)));
  ed.setMarkers(mine.map((d) => ({ line: d.line, col: d.col, severity: d.severity, msg: d.msg })));
}

// Apply diagnostics straight from the lint_done event payload (falls back to a
// fetch of the last result if called without one).
async function applyLint(diags) {
  try {
    if (!Array.isArray(diags)) {
      const r = await fetch("/api/lint-result", { headers: { "X-Requested-With": "XMLHttpRequest" } });
      const body = await r.json();
      diags = (body.data && body.data.diagnostics) || [];
    }
    state.diags = diags;
    applyMarkers();
    const errors = diags.filter((d) => d.severity === "error").length;
    const warnings = diags.filter((d) => d.severity === "warning").length;
    note(errors || warnings ? "Syntax check: " + errors + " error" + (errors === 1 ? "" : "s") + ", " +
      warnings + " warning" + (warnings === 1 ? "" : "s") : "Syntax check: no problems.", errors > 0);
    renderDiagnostics(diags);
  } catch (_e) {}
}

function renderDiagnostics(diags) {
  const host = document.getElementById("ide-diags");
  const count = document.getElementById("ide-problems-count");
  const errors = diags.filter((d) => d.severity === "error").length;
  const warnings = diags.filter((d) => d.severity === "warning").length;
  if (count) {
    count.className = "pcount" + (errors ? " pcount-err" : warnings ? " pcount-warn" : "");
    count.textContent = diags.length ? errors + " · " + warnings : "0";
    count.title = errors + " error" + (errors === 1 ? "" : "s") + ", " + warnings + " warning" + (warnings === 1 ? "" : "s");
  }
  if (!host) return;
  host.innerHTML = diags.length
    ? diags.map((d) =>
        "<div class='ide-diag ide-diag-" + d.severity + "' data-line='" + d.line +
        "' data-file='" + fmt.escape(d.file) + "'>" +
        fmt.escape(d.file) + ":" + d.line + ": " + fmt.escape(d.msg) + "</div>").join("")
    : "<p class='muted'>No problems. Verilator read every design and testbench file without an error or warning.</p>";
  host.querySelectorAll(".ide-diag").forEach((el) =>
    el.addEventListener("click", async () => {
      const ln = parseInt(el.dataset.line, 10);
      const f = state.files.find((x) => el.dataset.file.endsWith(x.relpath) || x.relpath.endsWith(el.dataset.file));
      if (f && f.abspath !== state.active) await openFile(f.abspath, f.relpath);
      if (ln && window.ideEditor) window.ideEditor.gotoLine(ln);
    }));
}

// ------------------------------------------------------------------ simulation

async function loadTestbenches() {
  const sel = document.getElementById("ide-tb");
  if (!sel) return;
  if (!state.designDir) { sel.innerHTML = "<option value=''>(no project)</option>"; return; }
  try {
    const prev = sel.value;
    const r = await api.simTestbenches(state.designDir);
    const tbs = r.testbenches || [];
    sel.innerHTML = tbs.map((t) => "<option value='" + fmt.escape(t) + "'>" + fmt.escape(t) + "</option>").join("")
      || "<option value=''>(no testbench yet)</option>";
    if (prev && tbs.includes(prev)) sel.value = prev;
    deriveTopFromTb();
  } catch (_e) {}
}

// Toggle the Simulate / Stop buttons. While a sim runs Simulate is disabled so
// a second run can't race the first (the server rejects it anyway), and Stop
// appears so a runaway bench can be killed.
function setSimBusy(busy) {
  const run = document.getElementById("ide-sim");
  const stop = document.getElementById("ide-sim-stop");
  if (run) {
    run.disabled = !!busy;
    run.innerHTML = busy ? "Simulating…"
      : "<svg viewBox='0 0 24 24' width='13' height='13' fill='currentColor' aria-hidden='true'><path d='M7 4l13 8-13 8z'/></svg> Simulate";
  }
  if (stop) stop.hidden = !busy;
}

// Toggle the Check-syntax (lint) button so a wedged lint shows progress and a
// second click can't pile up before the first finishes.
function setLintBusy(busy) {
  const b = document.getElementById("ide-lint");
  if (b) { b.disabled = !!busy; b.textContent = busy ? "Checking…" : "Check syntax"; }
}

// Client-side safety nets. The server always emits sim_done / lint_done (the job
// has its own watchdog), but if that event is ever missed — dropped SSE frame, a
// reconnect gap — the button must NOT stay stuck on "Simulating…"/"Checking…"
// forever (the "works only once" symptom). These timers force the busy state off
// well after the server's own watchdog would have fired, as a last resort.
let _simSafety = 0;
let _lintSafety = 0;
const SIM_SAFETY_MS = 140000;   // > server DEFAULT_SIM_TIMEOUT (120s) + slack
const LINT_SAFETY_MS = 100000;  // > server DEFAULT_LINT_TIMEOUT (90s) + slack
function armSimSafety() {
  clearTimeout(_simSafety);
  _simSafety = setTimeout(() => {
    if (!document.getElementById("ide-sim")?.disabled) return;
    setSimBusy(false);
    note("No result received. The simulation process may be unresponsive. Try again or check the logs.", true);
  }, SIM_SAFETY_MS);
}
function armLintSafety() {
  clearTimeout(_lintSafety);
  _lintSafety = setTimeout(() => {
    setLintBusy(false);
    note("No lint result received. The linter may be unresponsive. Please try again.", true);
  }, LINT_SAFETY_MS);
}

async function simulate() {
  const tb = (document.getElementById("ide-tb") || {}).value;
  // The top is the *testbench* module; if the user left it blank the server
  // auto-derives it from the testbench (the common case), so it's optional.
  const top = (document.getElementById("ide-top")?.value || "").trim();
  const simEngine = (document.getElementById("ide-sim-engine") || {}).value || "auto";
  setPanel("sim");
  if (!tb) {
    note("There's no testbench to simulate yet. Use + next to Simulation in the explorer to write one.", true);
    return;
  }
  // Simulate what's on screen: save the open file first if it changed.
  const t = activeTab();
  stash();
  if (t && t.text !== t.saved) await saveFile();
  const sources = state.files.filter((f) => /\.s?v$/.test(f.relpath) && f.relpath !== tb && f.role !== "testbench")
    .map((f) => f.relpath);
  appendLog((document.getElementById("ide-log")?.textContent ? "\n" : "") + "── simulate " + tb + " ──");
  note("Building and running the simulation…");
  setSimBusy(true);
  armSimSafety();
  try {
    const r = await api.simStart({
      top, testbench: tb, sources, trace: "vcd", run_mode: state.runMode, sim_engine: simEngine,
    });
    if (!r.ok) { note("Sim refused: " + (r.error || "?"), true); setSimBusy(false); }
    else {
      if (r.top) { const x = document.getElementById("ide-top"); if (x && !x.value) x.placeholder = r.top; }
      note("Simulating with " + (r.sim_engine || simEngine) + " (top: " + (r.top || top) + ")…");
    }
  } catch (ex) {
    // A 400 "already running" lands here too — surface it and reset the button.
    note("Sim failed: " + (ex.message || ex), true);
    setSimBusy(false);
  }
}

async function stopSim() {
  note("Stopping simulation…");
  try { await api.simCancel(); } catch (_e) {}
  // sim_done will fire from the cancel and flip the button back; flip now too in
  // case the process was already gone.
  setSimBusy(false);
}

// Show the testbench module the server will pick, so nobody types the DUT's
// name by mistake (which gives no waveform).
function deriveTopFromTb() {
  const sel = document.getElementById("ide-tb");
  const topEl = document.getElementById("ide-top");
  if (!sel || !topEl || topEl.value.trim()) return;
  // Heuristic mirror of the server: <name>_tb.v → <name>_tb, tb_<name> → tb_<name>.
  const base = (sel.value || "").split(/[\\/]/).pop().replace(/\.s?v$/, "");
  topEl.placeholder = base || "from the testbench";
}

function onEvent(ev) {
  if (!ev || !ev.type) return;
  if (ev.type === "log" && ev.message) appendLog(ev.message);
  else if (ev.type === "lint_done") {                  // standalone lint finished
    clearTimeout(_lintSafety);
    setLintBusy(false);
    if (ev.timed_out)
      note("Lint exceeded the time limit and was stopped. If running on WSL with Windows Verilator on PATH, "
           + "install the Linux binary from Tools.", true);
    applyLint(ev.diagnostics);
  }
  else if (ev.type === "sim_done") {
    clearTimeout(_simSafety);
    setSimBusy(false);                 // re-enable Simulate no matter the outcome
    if (ev.cancelled) note("Simulation stopped.", true);
    else if (ev.vcd) {
      loadWaveform(ev.vcd, ev.partial);
      if (ev.timed_out)
        note("Simulation reached the time limit (free-running clock without $finish). Displaying "
             + "partial waveform. Add $finish to your testbench for a complete run.", true);
    }
    else if (ev.timed_out)
      note("Simulation reached the time limit with no waveform generated. Add $finish to your "
           + "testbench so the simulation can terminate.", true);
    else if (ev.ok)
      note("Simulation ran but produced no waveform. Verify the testbench invokes "
           + "$dumpfile and $dumpvars, and that top is set to the testbench module.", true);
    else note("Simulation finished with errors. Review the log below for details.", true);
  }
}

// Open the last simulation's dump in the desktop GTKWave (server pre-generates a
// .gtkw save file so the signals are on screen — see /api/ide/open-wave). When
// GTKWave isn't installed, the first click explains and arms the button; the
// second click starts the install through the normal Tools machinery (progress
// streams to the Install logs / log drawer).
async function openInGtkwave() {
  const path = state.lastWavePath;
  if (!path) { note("Run a simulation first. No waveform available to open.", true); return; }
  try {
    const r = await api.openWave(path);
    if (r && r.ok) {
      state.gtkwaveInstallArmed = false;
      note("GTKWave launched on " + path + (r.signals ? " (" + r.signals + " signals preloaded)." : "."));
      return;
    }
    if (r && r.need === "gtkwave") {
      if (state.gtkwaveInstallArmed) {
        state.gtkwaveInstallArmed = false;
        note("Installing GTKWave. Monitor the install logs, then click GTKWave again when complete.");
        const ir = await api.installTool("gtkwave");
        if (ir && ir.in_progress) note("GTKWave installation in progress. Monitor the install logs for updates.");
        else if (ir && ir.ok === false) note(ir.guidance || ir.reason || "Could not install GTKWave automatically. See the Tools tab for manual setup.", true);
      } else {
        state.gtkwaveInstallArmed = true;
        note((r.error || "GTKWave is not installed.") + " Click GTKWave again to install it now.", true);
      }
      return;
    }
    note((r && r.error) || "Could not open GTKWave.", true);
  } catch (ex) {
    note("Could not open GTKWave: " + (ex.message || ex), true);
  }
}

// Show/hide the durable "partial waveform" badge on the Waveform tab. Kept
// separate from the transient note() so the disclosure survives later toasts and
// is visible in a screenshot of the pane (N2).
function setWavePartial(isPartial) {
  const badge = document.getElementById("ide-wave-partial");
  if (badge) badge.hidden = !isPartial;
}

// Size the canvas to its pane: the full panel width, and tall enough for every
// visible signal (the pane scrolls past that).
function fitWave() {
  const host = document.getElementById("ide-wave-host");
  const canvas = document.getElementById("ide-wave");
  if (!host || !canvas || !host.clientWidth) return;
  const rows = state.wave && state.wave.visible ? state.wave.visible.length : 0;
  const w = host.clientWidth;
  const h = Math.max(host.clientHeight - 2, rows * 26 + 24);
  if (canvas.width === w && canvas.height === h) return;
  canvas.width = w;
  canvas.height = h;
  if (state.wave && state.wave.vcd) state.wave.draw();
}

async function loadWaveform(vcdRel, partial) {
  state.lastWavePath = vcdRel;
  state.wavePartial = !!partial;
  note("Loading waveform " + vcdRel + "…");
  try {
    const r = await fetch(api.waveformUrl(vcdRel), { headers: { "X-Requested-With": "XMLHttpRequest" } });
    const text = await r.text();
    const vcd = parseVCD(text);
    setPanel("wave");
    const canvas = document.getElementById("ide-wave");
    byId("ide-wave-empty", (el) => { el.hidden = true; });
    if (!state.wave) state.wave = new WaveView(canvas);
    state.wave.visible = vcd.signals.length ? defaultLanes(vcd) : [];
    fitWave();
    state.wave.load(vcd, state.wave.visible);
    // A full (non-partial) load clears any prior badge; a partial load pins it.
    setWavePartial(!!partial);
    note("Waveform: " + vcd.signals.length + " signals, " + vcd.end + " " + (vcd.timescale || "ticks"));
  } catch (ex) {
    note("Could not load waveform: " + (ex.message || ex), true);
  }
}

function exportWavePng() {
  if (!state.wave || !state.wave.vcd) { note("Run a simulation first. No waveform available to export.", true); return; }
  const url = state.wave.toPNG();
  if (!url) { note("Could not export the waveform image.", true); return; }
  const a = document.createElement("a");
  a.href = url;
  a.download = "waveform.png";
  document.body.appendChild(a);
  a.click();
  a.remove();
  note("Exported waveform.png");
}

function exportWaveCsv() {
  if (!state.wave || !state.wave.vcd) { note("Run a simulation first. No waveform available to export.", true); return; }
  const csv = vcdToCSV(state.wave.vcd, state.wave.visible, state.wave.radix);
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "waveform.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
  note("Exported waveform.csv (" + state.wave.visible.length + " signals)");
}

function appendLog(line) {
  const el = document.getElementById("ide-log");
  if (!el) return;
  el.textContent += line + "\n";
  el.scrollTop = el.scrollHeight;
}

function note(msg, bad) {
  const el = document.getElementById("ide-note");
  if (!el) return;
  el.textContent = msg;
  el.title = msg;
  el.className = "ide-note" + (bad ? " ide-note-bad" : "");
}

// Standalone /ide page bootstrap. The embedded tab calls initIde() itself, so
// only auto-boot when this is the dedicated IDE document.
if (document.body && document.body.classList.contains("ide-body")) {
  window.addEventListener("DOMContentLoaded", () => initIde());
}
