// runs.js — left-side history list, plus diff controls wiring.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { confirmDialog, alertDialog, checklistDialog, choiceDialog, promptDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { gatherRunsScoped, normDir, getRunScope, setRunScope, setRun, contextRun, contextDesign, onContext } from "./context.js";
import { go } from "./nav.js";
import * as FS from "./flowstages.js";

// The last step of a stage in the Classic flow (matches setup.js's --to).
function lastStepOfStage(stageId) {
  const flow = (state.flows || []).find((f) => f.name === "Classic");
  const ids = (flow && flow.steps) || [];
  const st = FS.stagesOf(ids.map((id) => ({ id })));
  let last = "";
  st.forEach((s, i) => { if (s === stageId) last = ids[i]; });
  return last;
}
import { icon } from "./icons.js";

// Lightweight "make this run's design active" — needed before any run-scoped
// call (delete / files) since they resolve against the server's active design
// dir. Unlike openRun() this does NOT fetch the run or switch tabs, so a delete
// click no longer yanks the user to the Preview tab.
async function focusDesign(designDir) {
  if (designDir && normDir(designDir) !== normDir(state.designDir)) {
    try { await api.setDesignDir(designDir); state.designDir = designDir; } catch (_e) {}
  }
}

const getScope = getRunScope;

// The design dir a run belongs to: <design>/runs/<tag> → strip the last 2 parts.
function designOfRun(run) {
  const rd = run.run_dir || "";
  const parts = rd.split(/[/\\]/);
  return parts.slice(0, -2).join("/");
}
function designLabel(dir) { return (dir || "").split(/[/\\]/).filter(Boolean).pop() || dir; }

let _scopeWired = false;
let _filterText = "";
let _filterStatus = "";
let _filterPinned = false;
// Runs ticked for batch delete, keyed "<designDir>\u0000<tag>" so the same tag
// in two designs can't collide in the "All designs" scope.
const _picked = new Set();
function pickKey(designDir, tag) { return (designDir || "") + "\u0000" + tag; }

function wireScope() {
  if (_scopeWired) return;
  _scopeWired = true;
  document.querySelectorAll(".runs-scope[data-scope]").forEach((b) =>
    b.addEventListener("click", () => {
      setRunScope(b.dataset.scope);
      renderRuns();
    }));
  // The run the results pages show is marked here; it follows a pick anywhere.
  onContext(() => paintViewing());
  const fi = document.getElementById("runs-filter");
  if (fi) fi.addEventListener("input", () => { _filterText = fi.value.toLowerCase(); renderRuns(); });
  const sf = document.getElementById("runs-status-filter");
  if (sf) sf.addEventListener("change", () => { _filterStatus = sf.value; renderRuns(); });
  const pf = document.getElementById("runs-pin-filter");
  if (pf) pf.addEventListener("click", () => {
    _filterPinned = !_filterPinned;
    pf.classList.toggle("runs-scope-active", _filterPinned);
    pf.setAttribute("aria-pressed", _filterPinned ? "true" : "false");
    renderRuns();
  });
  const bd = document.getElementById("runs-batch-delete");
  if (bd) bd.addEventListener("click", () => batchDelete());
  const im = document.getElementById("runs-import");
  if (im) im.addEventListener("click", () => importRunFlow());
}

function syncBatchButton() {
  const bd = document.getElementById("runs-batch-delete");
  if (!bd) return;
  const n = _picked.size;
  bd.hidden = n === 0;
  bd.innerHTML = icon("trash", { size: 13 }) + " Delete selected (" + n + ")";
}

function matchesFilter(run) {
  if (_filterPinned && !run.pinned) return false;
  if (_filterStatus === "pass" && !run.success) return false;
  if (_filterStatus === "fail" && run.success) return false;
  if (!_filterText) return true;
  const hay = (run.tag + " " + (run.pdk || "") + " " + (run.scl || "")).toLowerCase();
  return hay.includes(_filterText);
}

// Run gathering (this design vs all designs, de-dup by run_dir) is shared with
// the run bar — see context.js.
const gatherRuns = gatherRunsScoped;

export async function renderRuns() {
  const root = document.getElementById("runs-list");
  if (!root) return;
  wireScope();
  const scope = getScope();
  document.querySelectorAll(".runs-scope[data-scope]").forEach((b) =>
    b.classList.toggle("runs-scope-active", b.dataset.scope === scope));
  let runs = [];
  try { runs = await gatherRuns(scope); } catch (_e) { runs = []; }
  // Keep state.runs scoped to the active design (other views rely on api.run()
  // which is active-dir-scoped); the "all" list is display-only here.
  if (scope !== "all") state.runs = runs;
  const shown = runs.filter(matchesFilter);
  root.innerHTML = "";
  if (!runs.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.innerHTML = scope === "all"
      ? "<span class='ico'>⏱</span><h3>No runs in your history</h3><p>Open a design and run the flow.</p>"
      : "<span class='ico'>⏱</span><h3>No runs yet</h3><p>Run the flow once and your history appears here.</p>";
    root.appendChild(li);
    return;
  }
  if (!shown.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.innerHTML = "<span class='ico'>" + icon("search") + "</span><h3>No runs match</h3><p>Clear the filter to see all " + runs.length + " runs.</p>";
    root.appendChild(li);
    return;
  }
  for (const run of shown) {
    const li = document.createElement("li");
    // Pass/fail left border for at-a-glance scanning (the status word is the
    // colour-blind-safe redundant cue).
    li.className = run.success ? "run-pass" : "run-fail";
    li.dataset.tag = run.tag;
    li.dataset.design = run._design || "";
    const designRow = scope === "all"
      ? "<div class='row2 muted'>" + icon("folder", { size: 13 }) + " " + fmt.escape(designLabel(run._design)) + "</div>"
      : "";
    const pkey = pickKey(run._design, run.tag);
    li.innerHTML =
      "<div class='row1'>" +
      "<input type='checkbox' class='run-pick' title='Select for batch delete'" + (_picked.has(pkey) ? " checked" : "") + "/>" +
      "<button class='run-pin" + (run.pinned ? " pinned" : "") + "' data-act='pin' aria-pressed='" +
        (run.pinned ? "true" : "false") + "' title='" + (run.pinned ? "Unpin" : "Pin") +
        " this run' aria-label='Pin run'>" + (run.pinned ? "<svg viewBox='0 0 24 24' width='14' height='14' fill='currentColor' stroke='currentColor' stroke-width='1' stroke-linejoin='round' aria-hidden='true'><path d='M12 3l2.6 5.9 6.4.6-4.8 4.3 1.4 6.3L12 17l-5.6 3.4 1.4-6.3L3 9.5l6.4-.6z'/></svg>" : "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M12 3l2.6 5.9 6.4.6-4.8 4.3 1.4 6.3L12 17l-5.6 3.4 1.4-6.3L3 9.5l6.4-.6z'/></svg>") + "</button>" +
      "<span class='tag'>" + fmt.escape(run.tag) + "</span>" +
      "<span class='run-viewing' title='Layout, Analytics and Verify show this run'>On the results pages</span>" +
      (run.success
        ? "<span class='pill pill-pass'><span class='text'>passed</span></span>"
        : "<span class='pill pill-fail'><span class='text'>failed</span></span>") +
      (run.imported ? "<span class='pill pill-pending' title='Imported from an external source (partial run)'>imported</span>" : "") +
      "</div>" +
      designRow +
      "<div class='row2'>" +
      "PDK " + fmt.escape(run.pdk || "?") + " · SCL " + fmt.escape(run.scl || "?") +
      " · " + (run.steps_done || 0) + "/" + (run.step_count || 0) + " steps" +
      (run.wall_time_s != null ? " · " + run.wall_time_s.toFixed(1) + "s" : "") +
      "</div>" +
      "<div class='run-note-row' data-note-row hidden></div>" +
      "<div class='row3 run-actions'>" +
      "<button class='btn btn-ghost run-act' data-act='open' title='Show this run in Layout'>" + icon("grid", { size: 13 }) + " Open in Layout</button>" +
      "<button class='btn btn-ghost run-act' data-act='reproduce' title='Load this run's settings into Setup'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M21 12a9 9 0 1 1-3-6.7M21 4v4h-4'/></svg> Reproduce</button>" +
      "<button class='btn btn-ghost run-act' data-act='files'>" + icon("folder", { size: 13 }) + " Files</button>" +
      "<button class='btn btn-ghost run-act' data-act='note'>" + icon("file", { size: 13 }) + " Note</button>" +
      "<button class='btn btn-ghost run-act' data-act='bundle' title='Download a .zip bundle with selected deliverables'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M12 3v12M7 11l5 4 5-4M5 21h14'/></svg> Bundle</button>" +
      "<button class='btn btn-ghost run-act' data-act='export' title='Download a run report (CSV / Markdown / HTML)'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M12 3v12M7 11l5 4 5-4M5 21h14'/></svg> Export</button>" +
      "<button class='btn btn-ghost run-act run-del' data-act='delete'>" + icon("trash", { size: 13 }) + " Delete</button>" +
      "</div>";
    const designDir = run._design;
    li.querySelector('[data-act="open"]').addEventListener("click", (e) => { e.stopPropagation(); openRun(run.tag, designDir); });
    li.querySelector('[data-act="reproduce"]').addEventListener("click", (e) => { e.stopPropagation(); focusDesign(designDir).then(() => reproduceRun(run.tag)); });
    li.querySelector('[data-act="files"]').addEventListener("click", (e) => { e.stopPropagation(); focusDesign(designDir).then(() => showFilesModal(run.tag)); });
    li.querySelector('[data-act="note"]').addEventListener("click", (e) => { e.stopPropagation(); toggleNote(li, run.tag, designDir); });
    li.querySelector('[data-act="delete"]').addEventListener("click", (e) => { e.stopPropagation(); focusDesign(designDir).then(() => deleteRunFlow(run.tag)); });
    li.querySelector('[data-act="bundle"]').addEventListener("click", (e) => { e.stopPropagation(); focusDesign(designDir).then(() => bundleDownloadFlow(run.tag)); });
    li.querySelector('[data-act="export"]').addEventListener("click", (e) => { e.stopPropagation(); focusDesign(designDir).then(() => exportRunFlow(run.tag)); });
    li.querySelector('[data-act="pin"]').addEventListener("click", (e) => { e.stopPropagation(); togglePin(run.tag, designDir, !run.pinned); });
    const pick = li.querySelector(".run-pick");
    pick.addEventListener("click", (e) => e.stopPropagation());
    pick.addEventListener("change", () => {
      if (pick.checked) _picked.add(pkey); else _picked.delete(pkey);
      syncBatchButton();
    });
    // A click picks the run for the results pages; it no longer leaves Runs.
    li.addEventListener("click", () => setRun(run.tag, designDir));
    root.appendChild(li);
  }
  syncBatchButton();
  paintViewing();
}

function paintViewing() {
  const run = contextRun(), design = normDir(contextDesign());
  document.querySelectorAll("#runs-list > li[data-tag]").forEach((li) =>
    li.classList.toggle("is-viewing", li.dataset.tag === run && normDir(li.dataset.design) === design));
}

// Batch delete every ticked run. Grouped by design dir so each run resolves
// against the right active design before deletion. One typed confirm for the
// whole set (per-run typing would be unusable at scale).
async function batchDelete() {
  const items = [];
  const byDesign = new Map();
  for (const r of (state.runs || [])) {
    const key = pickKey(r._design, r.tag);
    if (_picked.has(key)) {
      items.push(r);
      if (!byDesign.has(r._design)) byDesign.set(r._design, []);
      byDesign.get(r._design).push(r.tag);
    }
  }
  // The "All designs" scope holds runs not in state.runs; fall back to keys.
  if (!items.length && _picked.size) {
    for (const key of _picked) {
      const sp = key.indexOf(" ");
      const designDir = key.slice(0, sp); const tag = key.slice(sp + 1);
      if (!byDesign.has(designDir)) byDesign.set(designDir, []);
      byDesign.get(designDir).push(tag);
    }
  }
  const n = _picked.size;
  if (!n) return;
  const ok = await confirmDialog({
    title: "Delete " + n + " run" + (n === 1 ? "" : "s") + "?", danger: true,
    confirmText: "Delete " + n + " run" + (n === 1 ? "" : "s"),
    body: "This permanently deletes " + n + " run" + (n === 1 ? "" : "s") + " and all their files. This cannot be undone.",
  });
  if (!ok) return;
  let failed = 0, done = 0;
  for (const [designDir, tags] of byDesign) {
    await focusDesign(designDir);
    for (const tag of tags) {
      try {
        await api.deleteRun(tag);
        if (state.selectedRunTag === tag) state.selectedRunTag = null;
        done++;
      } catch (_e) { failed++; }
    }
  }
  _picked.clear();
  await renderRuns();
  if (failed) await alertDialog({ title: "Some deletes failed", body: failed + " run(s) could not be deleted." });
  else toast.show("Deleted " + done + " run" + (done === 1 ? "" : "s") + ".", "success");
}

// Inline run-note editor: expands a textarea under the row; saves on blur.
async function toggleNote(li, tag, designDir) {
  const row = li.querySelector("[data-note-row]");
  if (!row) return;
  if (!row.hidden) { row.hidden = true; return; }
  row.hidden = false;
  row.innerHTML = "<span class='muted'>loading note…</span>";
  // Ensure this run's design is active so the note resolves to the right run.
  if (designDir && designDir !== state.designDir) {
    try { await api.setDesignDir(designDir); } catch (_e) {}
  }
  let note = "";
  try { note = (await api.runNote(tag)).note || ""; } catch (_e) {}
  row.innerHTML = "<textarea class='run-note-ta' rows='2' placeholder='Add a note for this run…'></textarea>";
  const ta = row.querySelector("textarea");
  ta.value = note;
  ta.addEventListener("click", (e) => e.stopPropagation());
  ta.addEventListener("blur", async () => {
    try { await api.setRunNote(tag, ta.value); } catch (ex) { console.error("save note", ex); }
  });
  ta.focus();
}

// Download a support bundle — the user ticks exactly what goes in. Keys match
// bundle.ALL_PARTS on the backend.
const BUNDLE_PARTS = [
  { key: "config", label: "Used config", hint: "config.json + resolved.json + GUI overrides/preset" },
  { key: "sources", label: "RTL source files" },
  { key: "metrics_csv", label: "Metrics CSV" },
  { key: "settings_csv", label: "Settings / constraints / PDK CSV" },
  { key: "analytics_csv", label: "Analytics CSV", hint: "summary + report counts + all metrics" },
  { key: "reports", label: "Signoff reports", hint: ".rpt / .drc / .lvs" },
  { key: "logs", label: "Step logs" },
  // Heavy binary deliverables — off by default (each can be tens–hundreds of MB).
  { key: "gds", label: "GDSII layout", hint: "final .gds / OASIS stream", checked: false },
  { key: "layout_views", label: "Other layout views", hint: "DEF / LEF / OpenDB / Magic", checked: false },
  { key: "netlists", label: "Netlists", hint: "gate-level + powered Verilog, SPICE/CDL, JSON header", checked: false },
  { key: "timing", label: "Timing models", hint: "Liberty .lib / SDF / SPEF / SDC", checked: false },
  { key: "images", label: "Layout images", hint: "KLayout render(s), PNG/SVG", checked: false },
  { key: "diagrams", label: "Yosys diagrams", hint: ".dot schematics + rendered .svg", checked: false },
];
async function bundleDownloadFlow(tag) {
  const picked = await checklistDialog({
    title: "Download bundle: " + tag,
    body: "Select components to include in the .zip archive. Text and report data are selected by default. " +
      "Binary deliverables like GDS, netlists, timing models, and images are large, so select only what you need.",
    items: BUNDLE_PARTS,
    confirmText: "Download .zip",
  });
  if (!picked || !picked.length) return;
  const url = api.runBundleUrl(tag, picked);
  const a = document.createElement("a");
  a.href = url; a.download = tag + "-bundle.zip";
  document.body.appendChild(a); a.click(); a.remove();
  toast.show("Preparing bundle…", "info");
}

// E3 — download a formatted run report (CSV / Markdown / HTML). The backend
// (history.export_run + /api/run-export) already exists; this is the UI for it.
async function exportRunFlow(tag) {
  const fmt = await choiceDialog({
    title: "Export run report: " + tag,
    body: "Download a formatted report for this run. (For the raw metrics table, use Analytics > Metrics CSV.)",
    choices: [
      { label: "CSV", value: "csv" },
      { label: "Markdown", value: "md" },
      { label: "HTML", value: "html" },
    ],
  });
  if (!fmt) return;
  const a = document.createElement("a");
  a.href = api.runExportUrl(tag, fmt);
  a.download = tag + "-report." + fmt;
  document.body.appendChild(a); a.click(); a.remove();
}

// E2 — load a run's saved settings back into Setup so it can be re-run. Reads
// gui-run.json (persisted per run); never auto-starts the run.
async function reproduceRun(tag) {
  let meta;
  try {
    meta = await api.runGuiMeta(tag);
  } catch (ex) {
    await alertDialog({
      title: "Can't reproduce this run",
      body: (ex && ex.message) ||
        "No saved settings found for this run. It was created before reproduce support was available or generated outside the GUI.",
    });
    return;
  }
  const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ""; };
  // PDK / SCL — set state + the pickers; refresh the SCL list off the PDK.
  if (meta.pdk) {
    state.selectedPdk = meta.pdk;
    const ps = document.getElementById("pdk-select");
    if (ps) { ps.value = meta.pdk; ps.dispatchEvent(new Event("change")); }
  }
  if (meta.scl) {
    state.selectedScl = meta.scl;
    // The PDK change above repopulates SCLs asynchronously; set after a tick.
    setTimeout(() => { const sc = document.getElementById("scl-select"); if (sc) sc.value = meta.scl; }, 0);
  }
  if (meta.run_mode) state.runMode = meta.run_mode;
  // Config overrides.
  state.varsValues = {};
  for (const [k, v] of Object.entries(meta.overrides || {})) {
    state.varsValues[k] = (typeof v === "boolean") ? v : String(v);
  }
  // Where it stopped: the Run menu's "Run up to" stage, when --to was a stage's
  // last step. (--from and --skip are no longer set from LanEx; see below.)
  const stopSel = document.getElementById("run-stop-after");
  if (stopSel) {
    stopSel.value = "";
    if (meta.to) for (const o of stopSel.options) if (o.value && lastStepOfStage(o.value) === meta.to) stopSel.value = o.value;
    stopSel.dispatchEvent(new Event("change"));
  }
  // Full-auto vs step-by-step.
  const modeVal = meta.mode === "semi" ? "semi" : "auto";
  document.querySelectorAll(".mode-btn").forEach((b) =>
    b.classList.toggle("mode-btn-active", b.dataset.mode === modeVal));
  // Run name.
  const rn = (meta.tag || tag) + "-repro";
  setVal("run-name-input", rn);
  // Sources (best-effort — files may have moved/been deleted since the run).
  if (Array.isArray(meta.sources) && meta.sources.length) state.selectedFiles = meta.sources.slice();
  // Repaint the config panel + jump to Setup.
  try { const cfg = await import("./config.js"); cfg.renderConfig(); } catch (_e) { /* ignore */ }
  go("setup");
  const summary = "Loaded " + Object.keys(meta.overrides || {}).length + " override(s), " +
    (meta.sources || []).length + " source(s), " + (meta.run_mode || "container") +
    " mode, flow " + (meta.flow || "Classic") + ". Review your settings in Setup, then click Run flow when ready. " +
    "Nothing has started yet." +
    (meta.frm || (meta.skip || []).length ? " That run also used --from or --skip; LanEx runs the whole flow (or up to a stage) instead." : "");
  // E4.4 — offer the EXACT CLI command this run was launched with (persisted in
  // gui-run.json, not rebuilt), so a terminal user can reproduce it verbatim.
  // gui-run.json keeps the command per engine ({container, local, recommended}).
  const cc = meta.cli_command;
  const cli = String((cc && typeof cc === "object" ? (cc[cc.recommended] || cc.container || cc.local) : cc) || "").trim();
  const choices = cli ? [{ label: "Copy the run's CLI command", value: "copy" }] : [];
  const pick = await choiceDialog({
    title: "Loaded " + tag + " into Setup",
    body: summary + (cli ? "\n\nThat run's exact command:\n" + cli : ""),
    choices,
  });
  if (pick === "copy" && cli) {
    try { await navigator.clipboard.writeText(cli); toast.show("CLI command copied.", "success"); }
    catch (_e) { toast.show("Copy failed. Select and copy the command in the Manual tab.", "warn"); }
  }
}

// E4.5 — pin/star a run so it's easy to find in a long history. Just a bookmark
// marker; never touches run data.
async function togglePin(tag, designDir, pinned) {
  try {
    await focusDesign(designDir);
    await api.setRunPin(tag, pinned);
    await renderRuns();
  } catch (ex) {
    toast.show("Could not " + (pinned ? "pin" : "unpin") + ": " + (ex.message || ex), "error");
  }
}

// E1 — import a run from elsewhere: adopt a run directory, or restore a LanEx
// export bundle (.zip). Both land under the active design's runs/.
async function importRunFlow() {
  if (!state.designDir) {
    await alertDialog({
      title: "No active design",
      body: "Set a design directory first. Imported runs are saved into its runs directory.",
    });
    return;
  }
  const kind = await choiceDialog({
    title: "Import a run",
    body: "Adopt an existing LibreLane run directory, or restore a LanEx export bundle (.zip). It is copied into this design's runs/ so it survives deletion of the source.",
    choices: [
      { label: "Run folder", value: "dir" },
      { label: "LanEx bundle (.zip)", value: "bundle" },
    ],
  });
  if (!kind) return;
  const path = await promptDialog({
    title: kind === "dir" ? "Adopt a run directory" : "Import a bundle (.zip)",
    label: kind === "dir"
      ? "Absolute path to the run directory (a runs/<tag> folder):"
      : "Absolute path to the LanEx bundle (.zip):",
  });
  if (!path || !path.trim()) return;
  try {
    const res = kind === "dir"
      ? await api.importRunDir(path.trim())
      : await api.importRunBundle({ path: path.trim() });
    await renderRuns();
    let msg = "Imported as '" + res.tag + "'.";
    if (res.warnings && res.warnings.length) msg += " " + res.warnings.join(" ");
    toast.show(msg, "success");
  } catch (ex) {
    await alertDialog({ title: "Import failed", body: (ex && ex.message) || String(ex) });
  }
}

async function deleteRunFlow(tag) {
  const ok = await confirmDialog({
    title: "Delete run " + tag + "?", danger: true, confirmText: "Delete run",
    body: "This permanently deletes run '" + tag + "' and all its files. Consider downloading a bundle first. This cannot be undone.",
  });
  if (!ok) return;
  try {
    await api.deleteRun(tag);
    if (state.selectedRunTag === tag) state.selectedRunTag = null;
    await renderRuns();
    toast.show("Deleted run '" + tag + "'.", "success");
  } catch (ex) {
    await alertDialog({ title: "Delete failed", body: ex.message || String(ex) });
  }
}

let _filesOverlay = null;
function filesOverlay() {
  if (_filesOverlay) return _filesOverlay;
  const ov = document.createElement("div");
  ov.className = "smodal-backdrop";
  ov.hidden = true;
  ov.innerHTML =
    "<div class='smodal'>" +
    "  <div class='smodal-head'><span class='smodal-title' id='files-title'>Files</span>" +
    "  <span class='smodal-spacer'></span><button class='btn btn-ghost' id='files-close'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button></div>" +
    "  <div class='smodal-log' id='files-body' style='white-space:normal'></div>" +
    "</div>";
  document.body.appendChild(ov);
  ov.addEventListener("click", (e) => { if (e.target === ov) ov.hidden = true; });
  ov.querySelector("#files-close").addEventListener("click", () => { ov.hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !ov.hidden) ov.hidden = true; });
  _filesOverlay = ov;
  return ov;
}

function fmtBytes(n) {
  if (!n) return "";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}

async function showFilesModal(tag) {
  const ov = filesOverlay();
  ov.hidden = false;
  ov.querySelector("#files-title").textContent = "Files: " + tag;
  const body = ov.querySelector("#files-body");
  body.textContent = "loading…";
  let r;
  try {
    r = await api.runFiles(tag);
  } catch (ex) {
    body.textContent = "Could not list files: " + (ex.message || ex);
    return;
  }
  const files = (r && r.files) || [];
  // Group by top-level dir (step/final/…) for readability.
  const rows = files
    .filter((f) => !f.dir)
    .map((f) => {
      const url = api.runFileUrl(tag, f.path);
      return (
        "<div class='files-row'><a href='" + url + "' target='_blank' rel='noopener'>" +
        fmt.escape(f.path) + "</a> <span class='muted'>" + fmtBytes(f.size) + "</span></div>"
      );
    });
  body.innerHTML =
    "<div class='muted' style='margin-bottom:8px'>" + rows.length + " files: click to open or download</div>" +
    rows.join("");
}

async function openRun(tag, designDir) {
  await setRun(tag, designDir);
  go("layout");
}

// (The old Runs-tab metric-diff UI was removed; run comparison now lives in the
// Analytics → "Compare runs" panel. The /api/diff endpoint is retained server-side.)
