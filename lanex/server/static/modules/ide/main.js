// main.js — the RTL IDE (Phase 3). Runs both as the standalone /ide page AND
// embedded as the "RTL IDE" tab in the main cockpit. File tree + syntax-
// highlighting editor (guarded saves, find & replace) + multi-file upload for
// sources and testbenches + inline Verilator lint + functional simulation →
// VCD → canvas waveform (with CSV export). Shares api.js + SSE; no bundler.
import { api, sse, fmt } from "../api.js";
import { Editor } from "./editor.js";
import { parseVCD, vcdToCSV } from "./vcd.js";
import { WaveView } from "./waves.js";
import { setupFullscreen } from "../fullscreen.js";
import { applyZoom, currentZoom } from "../zoom.js";

const state = { designDir: null, files: [], openAbs: null, runMode: "container", wave: null,
                lastWavePath: null, gtkwaveInstallArmed: false };
let _inited = false;

// Entry point. opts.designDir/runMode override discovery (the embedded tab knows
// them from the main app); the standalone page discovers them itself.
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

export async function initIde(opts = {}) {
  setupThemeSync();                    // match the user's chosen theme on the pop-out
  if (_inited) {                       // re-activated tab: just refresh listings
    if (opts.designDir && opts.designDir !== state.designDir) {
      state.designDir = opts.designDir;
      setDesignLabel();
      await loadTree();
      await loadTestbenches();
    }
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
  wireUpload("ide-upload-src", "src");
  wireUpload("ide-upload-tb", "verify");
  document.querySelectorAll(".wave-radix").forEach((b) =>
    b.addEventListener("click", () => { if (state.wave) state.wave.setRadix(b.dataset.radix); }));

  // Re-fit the waveform canvas when its panel goes (out of) fullscreen.
  document.addEventListener("g:panel_fullscreen", (e) => {
    if (e.detail && e.detail.id === "ide-wave-host" && state.wave && state.wave.vcd) {
      const canvas = document.getElementById("ide-wave");
      const host = document.getElementById("ide-wave-host");
      if (canvas && host) {
        canvas.width = host.clientWidth - 4;
        canvas.height = e.detail.on
          ? Math.max(200, host.clientHeight - 16)
          : Math.max(120, Math.min(600, state.wave.vcd.signals.length * 26 + 20));
        state.wave.load(state.wave.vcd);
      }
    }
  });

  sse.open();
  sse.on(onEvent);
  await loadTree();
  await loadTestbenches();
}

function byId(id, fn) { const el = document.getElementById(id); if (el) fn(el); }
function setDesignLabel() {
  byId("ide-design", (el) => { el.textContent = state.designDir || "(no design loaded)"; });
}

async function loadTree() {
  const tree = document.getElementById("ide-tree");
  if (!tree) return;
  if (!state.designDir) { tree.innerHTML = "<p class='muted'>No design loaded. Open one in Setup first.</p>"; return; }
  let res;
  try { res = await api.walkSources(state.designDir); } catch (_e) { return; }
  state.files = (res.sources || []).concat(res.memories || []);
  tree.innerHTML = state.files.map((f) =>
    "<div class='ide-file-row'>" +
    "<button class='ide-file' data-abs='" + fmt.escape(f.abspath) + "' data-rel='" +
    fmt.escape(f.relpath) + "'>" + fmt.escape(f.relpath) + "</button>" +
    "<button class='ide-file-del' title='Delete this file' data-rel='" +
    fmt.escape(f.relpath) + "'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button></div>").join("") ||
    "<p class='muted'>No source files found. Upload some below.</p>";
  tree.querySelectorAll(".ide-file").forEach((b) =>
    b.addEventListener("click", () => openFile(b.dataset.abs, b.dataset.rel)));
  tree.querySelectorAll(".ide-file-del").forEach((b) =>
    b.addEventListener("click", (e) => { e.stopPropagation(); deleteFile(b.dataset.rel); }));
}

// Remove a source/testbench from the design (guarded server-side delete). The
// IDE's uploads add files but there was no way to take one back out.
async function deleteFile(rel) {
  if (!rel) return;
  const { confirmDialog } = await import("../dialog.js");
  const ok = await confirmDialog({
    title: "Delete file", danger: true, confirmText: "Delete",
    body: "Delete " + rel + " from the design folder? This cannot be undone.",
  });
  if (!ok) return;
  try {
    const r = await api.fileDelete(rel);
    if (!r.ok) throw new Error(r.error || "refused");
    note("Deleted " + rel);
    // If the open file was the one deleted, clear the editor label.
    if (window.ideEditor && window.ideEditor.relPath === rel) {
      byId("ide-open", (el) => { el.textContent = "(no file open)"; });
    }
    await loadTree();
    await loadTestbenches();
  } catch (ex) {
    note("Delete failed: " + (ex.message || ex), true);
  }
}

async function openFile(abs, rel) {
  try {
    const r = await api.readText(abs);
    if (r.text === undefined) throw new Error(r.error || "unreadable");
    state.openAbs = abs;
    window.ideEditor.load(rel, r.text);
    byId("ide-open", (el) => { el.textContent = rel; });
  } catch (ex) {
    note("Could not open: " + (ex.message || ex), true);
  }
}

async function saveFile() {
  const ed = window.ideEditor;
  if (!ed.relPath) { note("Open a file first.", true); return; }
  try {
    const r = await api.fileWrite(ed.relPath, ed.getValue());
    if (!r.ok) throw new Error(r.error || "write refused");
    note("Saved " + ed.relPath + " (" + r.bytes + " bytes)");
  } catch (ex) {
    note("Save failed: " + (ex.message || ex), true);
  }
}

// Opt-in auto-lint: a moment after the user stops typing, silently save the
// current Verilog buffer and re-run the standalone Verilator lint so markers
// stay current. Off by default, persisted. Reuses the same lint.LintJob path
// (no new endpoint/dep). Saving is explicit because lint reads files on disk.
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
  if (!ed || !ed.relPath) return;
  try {
    const w = await api.fileWrite(ed.relPath, ed.getValue());  // silent save
    if (!w.ok) return;
  } catch (_e) { return; }
  lint();
}

// Upload one or more local files into the design (guarded server-side write).
// `subdir` is where they land: src/ for sources, verify/ for testbenches.
function wireUpload(btnId, subdir) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  const input = document.createElement("input");
  input.type = "file";
  input.multiple = true;
  input.accept = ".v,.sv,.vh,.svh,.vhd,.mem,.hex,.sdc";
  input.style.display = "none";
  btn.parentNode.appendChild(input);
  btn.addEventListener("click", () => input.click());
  input.addEventListener("change", async () => {
    const files = [...input.files];
    input.value = "";
    if (!files.length) return;
    if (!state.designDir) { note("Open a design first (Setup tab).", true); return; }
    let ok = 0;
    for (const f of files) {
      try {
        const text = await f.text();
        const rel = subdir + "/" + f.name;
        const r = await api.fileWrite(rel, text);
        if (r.ok) { ok++; } else { note("Refused " + f.name + ": " + (r.error || "?"), true); }
      } catch (ex) { note("Upload failed for " + f.name + ": " + (ex.message || ex), true); }
    }
    if (ok) note("Uploaded " + ok + " file" + (ok === 1 ? "" : "s") + " to " + subdir + "/");
    await loadTree();
    await loadTestbenches();
  });
}

async function lint() {
  note("Linting via Verilator…");
  setLintBusy(true);
  armLintSafety();
  // Lint the current source set (the testbench is linted as a source too) — a
  // standalone verilator --lint-only job, NOT the hardening flow.
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

// Apply diagnostics straight from the lint_done event payload (falls back to a
// fetch of the last result if called without one).
async function applyLint(diags) {
  try {
    if (!Array.isArray(diags)) {
      const r = await fetch("/api/lint-result", { headers: { "X-Requested-With": "XMLHttpRequest" } });
      const body = await r.json();
      diags = (body.data && body.data.diagnostics) || [];
    }
    const ed = window.ideEditor;
    const mine = diags.filter((d) => ed.relPath && (d.file.endsWith(ed.relPath) || ed.relPath.endsWith(d.file)));
    ed.setMarkers(mine.map((d) => ({ line: d.line, col: d.col, severity: d.severity, msg: d.msg })));
    const errors = diags.filter((d) => d.severity === "error").length;
    const warnings = diags.filter((d) => d.severity === "warning").length;
    note("Lint: " + errors + " errors, " + warnings + " warnings");
    renderDiagnostics(diags);
  } catch (_e) {}
}

function renderDiagnostics(diags) {
  const host = document.getElementById("ide-diags");
  const count = document.getElementById("ide-problems-count");
  if (count) {
    const errors = diags.filter((d) => d.severity === "error").length;
    const warnings = diags.filter((d) => d.severity === "warning").length;
    count.innerHTML = diags.length
      ? "<span class='pcount-err'>" + errors + " error" + (errors === 1 ? "" : "s") + "</span> · " +
        "<span class='pcount-warn'>" + warnings + " warning" + (warnings === 1 ? "" : "s") + "</span>"
      : "no problems";
  }
  if (!host) return;
  host.innerHTML = diags.length
    ? diags.map((d) =>
        "<div class='ide-diag ide-diag-" + d.severity + "' data-line='" + d.line +
        "' data-file='" + fmt.escape(d.file) + "'>" +
        fmt.escape(d.file) + ":" + d.line + " — " + fmt.escape(d.msg) + "</div>").join("")
    : "<p class='muted'>No lint messages.</p>";
  host.querySelectorAll(".ide-diag").forEach((el) =>
    el.addEventListener("click", () => {
      const ln = parseInt(el.dataset.line, 10);
      if (ln && window.ideEditor) window.ideEditor.gotoLine(ln);
    }));
}

async function loadTestbenches() {
  const sel = document.getElementById("ide-tb");
  if (!sel) return;
  try {
    const r = await api.simTestbenches(state.designDir);
    const tbs = r.testbenches || [];
    sel.innerHTML = tbs.map((t) => "<option value='" + fmt.escape(t) + "'>" + fmt.escape(t) + "</option>").join("")
      || "<option value=''>(no testbench found)</option>";
    if (!sel._wiredTop) { sel._wiredTop = true; sel.addEventListener("change", deriveTopFromTb); }
    deriveTopFromTb();
  } catch (_e) {}
}

// Toggle the Build & run / Stop buttons. While a sim runs the primary button is
// disabled so a second "Build & run" can't race the first (which the server
// rejects anyway) — and a Stop button appears so a runaway bench can be killed.
function setSimBusy(busy) {
  const run = document.getElementById("ide-sim");
  const stop = document.getElementById("ide-sim-stop");
  if (run) { run.disabled = !!busy; run.textContent = busy ? "Running…" : "Build & run"; }
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
// reconnect gap — the button must NOT stay stuck on "Running…"/"Checking…"
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
    note("No result received — the simulator may have wedged. Try again, or Stop and check the log.", true);
  }, SIM_SAFETY_MS);
}
function armLintSafety() {
  clearTimeout(_lintSafety);
  _lintSafety = setTimeout(() => {
    setLintBusy(false);
    note("No lint result received — the linter may have wedged. Try again.", true);
  }, LINT_SAFETY_MS);
}

async function simulate() {
  const tb = (document.getElementById("ide-tb") || {}).value;
  // The top is the *testbench* module; if the user left it blank the server
  // auto-derives it from the testbench (the common case), so it's optional.
  const top = (document.getElementById("ide-top")?.value || "").trim();
  const simEngine = (document.getElementById("ide-sim-engine") || {}).value || "auto";
  if (!tb) { note("Pick a testbench first.", true); return; }
  const sources = state.files.filter((f) => /\.s?v$/.test(f.relpath) && f.relpath !== tb)
    .map((f) => f.relpath);
  note("Building + running simulation…");
  setSimBusy(true);
  armSimSafety();
  try {
    const r = await api.simStart({
      top, testbench: tb, sources, trace: "vcd", run_mode: state.runMode, sim_engine: simEngine,
    });
    if (!r.ok) { note("Sim refused: " + (r.error || "?"), true); setSimBusy(false); }
    else {
      if (r.top) { const t = document.getElementById("ide-top"); if (t && !t.value) t.value = r.top; }
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

// Auto-fill the top module from the selected testbench so the user doesn't have
// to type it (and doesn't accidentally type the DUT name → no waveform).
function deriveTopFromTb() {
  const sel = document.getElementById("ide-tb");
  const topEl = document.getElementById("ide-top");
  if (!sel || !topEl || topEl.value.trim()) return;
  // Heuristic mirror of the server: <name>_tb.v → <name>_tb, tb_<name> → tb_<name>.
  const base = (sel.value || "").split(/[\\/]/).pop().replace(/\.s?v$/, "");
  if (base) topEl.placeholder = base;
}

function onEvent(ev) {
  if (!ev || !ev.type) return;
  if (ev.type === "log" && ev.message) appendLog(ev.message);
  else if (ev.type === "lint_done") {                  // standalone lint finished
    clearTimeout(_lintSafety);
    setLintBusy(false);
    if (ev.timed_out)
      note("Lint hit the time limit and was stopped — on WSL a Windows Verilator on the "
           + "PATH can hang; install the Linux build from Tools.", true);
    applyLint(ev.diagnostics);
  }
  else if (ev.type === "sim_done") {
    clearTimeout(_simSafety);
    setSimBusy(false);                 // re-enable Build & run no matter the outcome
    if (ev.cancelled) note("Simulation stopped.", true);
    else if (ev.vcd) {
      loadWaveform(ev.vcd);
      if (ev.timed_out)
        note("Sim hit the time limit (free-running clock / no $finish) — showing the "
             + "partial waveform. Add $finish to the testbench for a full run.", true);
    }
    else if (ev.timed_out)
      note("Simulation hit the time limit and produced no waveform — add $finish to the "
           + "testbench (a free-running clock with no $finish never ends).", true);
    else if (ev.ok)
      note("Simulation ran but produced no waveform — check the testbench has "
           + "$dumpfile/$dumpvars and that the top is the testbench module (not the DUT).", true);
    else note("Simulation finished with errors — see the log below.", true);
  }
}

// Open the last simulation's dump in the desktop GTKWave (server pre-generates a
// .gtkw save file so the signals are on screen — see /api/ide/open-wave). When
// GTKWave isn't installed, the first click explains and arms the button; the
// second click starts the install through the normal Tools machinery (progress
// streams to the Install logs / log drawer).
async function openInGtkwave() {
  const path = state.lastWavePath;
  if (!path) { note("Run a simulation first — no waveform to open.", true); return; }
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
        note("Installing GTKWave — watch the install logs, then click GTKWave again.");
        const ir = await api.installTool("gtkwave");
        if (ir && ir.in_progress) note("A GTKWave install is already running — watch the install logs.");
        else if (ir && ir.ok === false) note(ir.guidance || ir.reason || "Couldn't install GTKWave automatically — see the Tools tab.", true);
      } else {
        state.gtkwaveInstallArmed = true;
        note((r.error || "GTKWave isn't installed.") + " Click GTKWave again to install it now.", true);
      }
      return;
    }
    note((r && r.error) || "Could not open GTKWave.", true);
  } catch (ex) {
    note("Could not open GTKWave: " + (ex.message || ex), true);
  }
}

async function loadWaveform(vcdRel) {
  state.lastWavePath = vcdRel;
  note("Loading waveform " + vcdRel + "…");
  try {
    const r = await fetch(api.waveformUrl(vcdRel), { headers: { "X-Requested-With": "XMLHttpRequest" } });
    const text = await r.text();
    const vcd = parseVCD(text);
    const canvas = document.getElementById("ide-wave");
    canvas.width = canvas.parentElement.clientWidth - 4;
    canvas.height = Math.max(120, Math.min(600, vcd.signals.length * 26 + 20));
    state.wave = new WaveView(canvas);
    state.wave.load(vcd);
    note("Waveform: " + vcd.signals.length + " signals, " + vcd.end + " " + (vcd.timescale || "ticks"));
  } catch (ex) {
    note("Could not load waveform: " + (ex.message || ex), true);
  }
}

function exportWavePng() {
  if (!state.wave || !state.wave.vcd) { note("Run a simulation first — no waveform to export.", true); return; }
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
  if (!state.wave || !state.wave.vcd) { note("Run a simulation first — no waveform to export.", true); return; }
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
  el.className = "ide-note" + (bad ? " ide-note-bad" : "");
}

// Standalone /ide page bootstrap. The embedded tab calls initIde() itself, so
// only auto-boot when this is the dedicated IDE document.
if (document.body && document.body.classList.contains("ide-body")) {
  window.addEventListener("DOMContentLoaded", () => initIde());
}
