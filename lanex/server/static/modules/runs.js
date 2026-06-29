// runs.js — left-side history list, plus diff controls wiring.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { confirmDialog, alertDialog, checklistDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { gatherRunsScoped, normDir } from "./runscope.js";

// Lightweight "make this run's design active" — needed before any run-scoped
// call (delete / files) since they resolve against the server's active design
// dir. Unlike openRun() this does NOT fetch the run or switch tabs, so a delete
// click no longer yanks the user to the Preview tab.
async function focusDesign(designDir) {
  if (designDir && normDir(designDir) !== normDir(state.designDir)) {
    try { await api.setDesignDir(designDir); state.designDir = designDir; } catch (_e) {}
  }
}

const SCOPE_KEY = "ll.runsScope";
function getScope() {
  try { return localStorage.getItem(SCOPE_KEY) === "all" ? "all" : "design"; } catch (_e) { return "design"; }
}
function setScope(s) { try { localStorage.setItem(SCOPE_KEY, s); } catch (_e) {} }

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
// Runs ticked for batch delete, keyed "<designDir>\u0000<tag>" so the same tag
// in two designs can't collide in the "All history" scope.
const _picked = new Set();
function pickKey(designDir, tag) { return (designDir || "") + "\u0000" + tag; }

function wireScope() {
  if (_scopeWired) return;
  _scopeWired = true;
  document.querySelectorAll(".runs-scope").forEach((b) =>
    b.addEventListener("click", () => {
      setScope(b.dataset.scope);
      renderRuns();
    }));
  const fi = document.getElementById("runs-filter");
  if (fi) fi.addEventListener("input", () => { _filterText = fi.value.toLowerCase(); renderRuns(); });
  const sf = document.getElementById("runs-status-filter");
  if (sf) sf.addEventListener("change", () => { _filterStatus = sf.value; renderRuns(); });
  const bd = document.getElementById("runs-batch-delete");
  if (bd) bd.addEventListener("click", () => batchDelete());
}

function syncBatchButton() {
  const bd = document.getElementById("runs-batch-delete");
  if (!bd) return;
  const n = _picked.size;
  bd.hidden = n === 0;
  bd.textContent = "🗑 Delete selected (" + n + ")";
}

function matchesFilter(run) {
  if (_filterStatus === "pass" && !run.success) return false;
  if (_filterStatus === "fail" && run.success) return false;
  if (!_filterText) return true;
  const hay = (run.tag + " " + (run.pdk || "") + " " + (run.scl || "")).toLowerCase();
  return hay.includes(_filterText);
}

// Run gathering (this-design vs all-history, de-dup by run_dir) is shared with
// the per-tab pickers — see runscope.js.
const gatherRuns = gatherRunsScoped;

export async function renderRuns() {
  const root = document.getElementById("runs-list");
  if (!root) return;
  wireScope();
  const scope = getScope();
  document.querySelectorAll(".runs-scope").forEach((b) =>
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
    li.innerHTML = "<span class='ico'>🔍</span><h3>No runs match</h3><p>Clear the filter to see all " + runs.length + " runs.</p>";
    root.appendChild(li);
    return;
  }
  for (const run of shown) {
    const li = document.createElement("li");
    // Pass/fail left border for at-a-glance scanning (status text + ✓/✗ glyph
    // give a colour-blind-safe redundant cue).
    li.className = run.success ? "run-pass" : "run-fail";
    const designRow = scope === "all"
      ? "<div class='row2 muted'>📁 " + fmt.escape(designLabel(run._design)) + "</div>"
      : "";
    const pkey = pickKey(run._design, run.tag);
    li.innerHTML =
      "<div class='row1'>" +
      "<input type='checkbox' class='run-pick' title='Select for batch delete'" + (_picked.has(pkey) ? " checked" : "") + "/>" +
      "<span class='tag'>" + fmt.escape(run.tag) + "</span>" +
      (run.success
        ? "<span class='pill pill-pass'><span class='d'></span><span class='text'>✓ passed</span></span>"
        : "<span class='pill pill-fail'><span class='d'></span><span class='text'>✗ failed</span></span>") +
      "</div>" +
      designRow +
      "<div class='row2'>" +
      "PDK " + fmt.escape(run.pdk || "?") + " · SCL " + fmt.escape(run.scl || "?") +
      " · " + (run.steps_done || 0) + "/" + (run.step_count || 0) + " steps" +
      (run.wall_time_s != null ? " · " + run.wall_time_s.toFixed(1) + "s" : "") +
      "</div>" +
      "<div class='run-note-row' data-note-row hidden></div>" +
      "<div class='row3 run-actions'>" +
      "<button class='btn btn-ghost run-act' data-act='open'>Open</button>" +
      "<button class='btn btn-ghost run-act' data-act='files'>📁 Files</button>" +
      "<button class='btn btn-ghost run-act' data-act='note'>📝 Note</button>" +
      "<button class='btn btn-ghost run-act' data-act='bundle' title='Download a .zip — pick what to include'>⬇ Bundle</button>" +
      "<button class='btn btn-ghost run-act run-del' data-act='delete'>🗑 Delete</button>" +
      "</div>";
    const designDir = run._design;
    li.querySelector('[data-act="open"]').addEventListener("click", (e) => { e.stopPropagation(); openRun(run.tag, designDir); });
    li.querySelector('[data-act="files"]').addEventListener("click", (e) => { e.stopPropagation(); focusDesign(designDir).then(() => showFilesModal(run.tag)); });
    li.querySelector('[data-act="note"]').addEventListener("click", (e) => { e.stopPropagation(); toggleNote(li, run.tag, designDir); });
    li.querySelector('[data-act="delete"]').addEventListener("click", (e) => { e.stopPropagation(); focusDesign(designDir).then(() => deleteRunFlow(run.tag)); });
    li.querySelector('[data-act="bundle"]').addEventListener("click", (e) => { e.stopPropagation(); focusDesign(designDir).then(() => bundleDownloadFlow(run.tag)); });
    const pick = li.querySelector(".run-pick");
    pick.addEventListener("click", (e) => e.stopPropagation());
    pick.addEventListener("change", () => {
      if (pick.checked) _picked.add(pkey); else _picked.delete(pkey);
      syncBatchButton();
    });
    li.addEventListener("click", () => openRun(run.tag, designDir));
    root.appendChild(li);
  }
  syncBatchButton();
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
  // The "All history" scope holds runs not in state.runs; fall back to keys.
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
    title: "Download bundle — “" + tag + "”",
    body: "Tick what to include in the .zip. The text/data parts are on by default; " +
      "the binary deliverables (GDS, netlists, timing, images…) are large, so tick only what you need.",
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

async function deleteRunFlow(tag) {
  const ok = await confirmDialog({
    title: "Delete run “" + tag + "”?", danger: true, confirmText: "Delete run",
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
    "  <span class='smodal-spacer'></span><button class='btn btn-ghost' id='files-close'>✕</button></div>" +
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
  ov.querySelector("#files-title").textContent = "Files — " + tag;
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
    "<div class='muted' style='margin-bottom:8px'>" + rows.length + " files — click to open/download</div>" +
    rows.join("");
}

async function openRun(tag, designDir) {
  // Opening a run from another design (All-history scope): make it the active
  // design first, since /api/runs/<tag> and the run-scoped views resolve against
  // the active design dir.
  if (designDir && designDir !== state.designDir) {
    try {
      const res = await api.setDesignDir(designDir);
      const { adoptDesignDir } = await import("./setup.js");
      await adoptDesignDir(res.design_dir, { explicit: true });
    } catch (_e) { /* fall through; open may still work if dirs coincide */ }
  }
  state.selectedRunTag = tag;
  try {
    const view = await api.run(tag);
    state.pipeline = (view.summaries || []).map((line) => {
      const id = line.split(":")[0] || "";
      return { id, status: line.includes("ok") ? "done" : "failed" };
    });
    const mod = await import("./pipeline.js");
    mod.renderPipeline();
    // Pull metrics for analytics tab.
    state.metrics = view.metrics?.values || {};
    const modM = await import("./analytics.js");
    modM.renderAnalytics();
    const modA = await import("./timingAdvisor.js");
    modA.renderTimingAdvisor();
    document.querySelector(".side-tab[data-tab='preview']")?.click();
    const modP = await import("./preview.js");
    modP.selectRun(tag);
    const modV = await import("./violations.js");
    modV.populateReportsList(view.design_dir || state.designDir, tag);
  } catch (ex) {
    console.error("openRun", ex);
  }
}

// (The old Runs-tab metric-diff UI was removed; run comparison now lives in the
// Analytics → "Compare runs" panel. The /api/diff endpoint is retained server-side.)
