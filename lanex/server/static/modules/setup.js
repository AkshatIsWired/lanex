// setup.js — design picker, PDK picker, run button, mode switch.

import { api } from "./api.js";
import { state, safeStorage } from "./state.js";
import { fmt } from "./api.js";
import { renderConfig } from "./config.js";
import { setupFolderBrowser, loadFilesFor } from "./fs.js";
import { toast } from "./toast.js";
import { renderPreflight } from "./preflight.js";
import { icon } from "./icons.js";
import { wireJump } from "./jumpnav.js";
import { pdkFacts, stackHtml } from "./pdkinfo.js";
import * as FS from "./flowstages.js";

const RECENT_KEY = "ll.recentDesigns";

function getRecentDesigns() {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]").filter(Boolean);
  } catch (_e) {
    return [];
  }
}

function rememberDesign(dir) {
  if (!dir) return;
  try {
    let list = getRecentDesigns().filter((d) => d !== dir);
    list.unshift(dir);
    list = list.slice(0, 6);
    localStorage.setItem(RECENT_KEY, JSON.stringify(list));
  } catch (_e) {}
}

// Recent projects live in the top-bar project switcher now; kept as a no-op so
// older callers stay valid.
export function renderRecentDesigns() {}

async function openIde(opts) {
  const { go } = await import("./nav.js");
  go("ide");
  const m = await import("./ide/main.js");
  await m.initIde({ designDir: state.designDir, runMode: state.runMode });
  await m.openInIde(opts || {});
}

function scrollToBlock(id) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

// Buttons anywhere on the Setup page that hand off to the project switcher,
// the RTL IDE or the file manager (data-open / data-step-act).
function wireSetupActions() {
  const sec = document.getElementById("sec-setup");
  if (!sec) return;
  sec.addEventListener("click", (e) => {
    const b = e.target.closest("[data-open], [data-step-act]");
    if (!b) return;
    const act = b.dataset.open || b.dataset.stepAct;
    if (act === "new-project" || (act === "project" && !state.designDir)) {
      document.getElementById("btn-new-project")?.click();
    } else if (act === "example") {
      import("./wizard.js").then((m) => m.openWizard({ template: "blinky" }));
    } else if (act === "project") {
      scrollToBlock("setup-design");
    } else if (act === "switch") {
      e.stopPropagation();
      document.getElementById("design-pill")?.click();
    } else if (act === "reveal") {
      document.getElementById("btn-reveal-project")?.click();
    } else if (act === "ide") {
      openIde({});
    } else if (act === "new-file") {
      if (!state.designDir) { toast.show("Open a project first.", "warn"); return; }
      openIde({ create: "src" });
    } else if (act === "edit") {
      openIde({ rel: b.dataset.rel });
    } else if (act === "pdk") {
      scrollToBlock("setup-pdk");
      document.getElementById("pdk-select")?.focus({ preventScroll: true });
    } else if (act === "run") {
      scrollToBlock("setup-run");
    } else if (act === "runs") {
      import("./nav.js").then((m) => m.go("runs"));
    }
  });
  // "Add files…" copies files from anywhere on the computer into the project,
  // so the project folder stays self-contained. The browser's file input opens
  // the operating system's own file dialog.
  const add = document.getElementById("btn-add-files");
  if (add) {
    const input = document.createElement("input");
    input.type = "file";
    input.multiple = true;
    input.hidden = true;
    add.after(input);
    add.addEventListener("click", () => {
      if (!state.designDir) { toast.show("Open a project first.", "warn"); return; }
      input.click();
    });
    input.addEventListener("change", async () => {
      const files = [...input.files];
      input.value = "";
      let ok = 0;
      const added = [];
      for (const f of files) {
        const name = f.name;
        const isTb = /(^tb_|_tb\.|testbench)/i.test(name);
        const isHdl = /\.(s?v|vh|svh)$/i.test(name);
        const rel = (isHdl ? (isTb ? "verify/" : "src/") : "") + name;
        try {
          const r = await api.fileWrite(rel, await f.text());
          if (r.ok) { ok++; added.push(rel); } else toast.show("Could not add " + name + ": " + (r.error || "refused"), "error");
        } catch (ex) {
          toast.show("Could not add " + name + ": " + (ex.message || ex), "error");
        }
      }
      if (ok) {
        toast.show("Added " + ok + " file" + (ok === 1 ? "" : "s") + " to the project.", "success");
        await loadFilesFor(state.designDir);
        const base = state.designDir.replace(/\/+$/, "") + "/";
        const design = added.filter((rel) => rel.startsWith("src/") && /\.s?v$/i.test(rel)).map((rel) => base + rel);
        if (design.length) {
          const { includeInConfig } = await import("./fs.js");
          includeInConfig(design);
        }
      }
    });
  }
  // Files created in the RTL IDE show up here without a manual rescan.
  document.addEventListener("g:sources_changed", () => {
    if (state.designDir) loadFilesFor(state.designDir);
  });
  // Design files added from the RTL IDE join the config's file list, like
  // the ones added here.
  document.addEventListener("g:sources_added", async (e) => {
    const files = (e.detail && e.detail.files) || [];
    if (!files.length || !state.designDir) return;
    await loadFilesFor(state.designDir);
    const { includeInConfig } = await import("./fs.js");
    includeInConfig(files);
  });
}

export function setupSetup() {
  setupFolderBrowser();
  renderRecentDesigns();
  // Page header links; the Constraints categories have their own tabs inside
  // that card (config.js), so they never crowd this bar.
  wireJump(document.getElementById("sec-setup"));
  wireSetupActions();
  import("./projectcard.js").then((m) => m.wireDesignRow()).catch(() => {});
  import("./mostused.js").then((m) => m.wireSettings()).catch(() => {});
  // A change made elsewhere (the fix sheet's Apply or Undo, Cells) must show
  // here at once: the Design row and the Settings card read the config again.
  // (The Design row's own edits announce themselves without keys: it is
  // already showing them.)
  document.addEventListener("g:config_changed", (e) => {
    const d = (e && e.detail) || {};
    if (!d.keys && !d.from) return;
    if (!state.designDir) return;
    import("./projectcard.js").then((m) => m.paintDesignRow()).catch(() => {});
    import("./mostused.js").then((m) => m.paintSettings()).catch(() => {});
  });
  // The project card's "Last run" line follows a run that just ended.
  const lastRun = () => {
    if (!state.designDir) return;
    summariseFacts(state.designDir);
  };
  document.addEventListener("g:flow_done", () => setTimeout(lastRun, 1500));
  document.addEventListener("g:runs_state", lastRun);
  // The server refused a run, resume or sweep: the folder is gone (api.js).
  document.addEventListener("g:design_missing", () => {
    if (state.designDir && state.designMissing !== state.designDir) showMissingProject(state.designDir);
  });
  document.getElementById("btn-set-design")?.addEventListener("click", onLoadDesign);
  document.getElementById("design-dir-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") onLoadDesign();
  });

  document.getElementById("pdk-select")?.addEventListener("change", onPdkSelected);
  document.getElementById("scl-select")?.addEventListener("change", onSclSelected);

  // Setup's own Run flow shows the run; the top-bar Run leaves you where you are.
  document.getElementById("btn-run")?.addEventListener("click", () => onRunClick({ show: true }));
  document.getElementById("btn-cancel")?.addEventListener("click", () => api.cancelRun().catch(() => {}));
  // Global topbar Run/Stop: start the flow, or stop a running one, from any tab —
  // no need to navigate back to Setup. Reuses the same start/cancel paths.
  document.getElementById("btn-run-global")?.addEventListener("click", () => {
    if (state.status && state.status.running) { api.cancelRun().catch(() => {}); }
    else { onRunClick({ show: false }); }
  });
  document.getElementById("btn-resume")?.addEventListener("click", () => api.resumeRun().catch(() => {}));
  document.getElementById("btn-preflight")?.addEventListener("click", () => renderPreflight());

  wireRunMenu();

  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".mode-btn").forEach((b) =>
        b.classList.toggle("mode-btn-active", b === btn),
      );
      state.mode = btn.dataset.mode;
      import("./shell.js").then((m) => m.paintRunSettings()).catch(() => {});
    });
  });
}

async function onLoadDesign() {
  const input = document.getElementById("design-dir-input");
  const designDir = (input?.value || "").trim();
  if (!designDir) {
    toast.show("Please paste the path to your design folder.", "warn");
    return;
  }
  try {
    const res = await api.setDesignDir(designDir);
    await adoptDesignDir(res.design_dir);
  } catch (ex) {
    toast.show("Could not load that folder: " + ex.message, "error");
  }
}

// Populate the UI for a design directory the server already considers active.
// Shared by manual "Load design", the SPM example, and `--design-dir` boot.
// `opts.explicit` (default true) records that the person chose this project,
// as opposed to boot re-opening the last one ({explicit:false}).
export async function adoptDesignDir(designDir, opts = {}) {
  const explicit = opts.explicit !== false;
  state.designDir = designDir;
  state.designExplicit = explicit;
  rememberDesign(designDir);
  paintOnboardChecklist();  // step 1 (project open) is now satisfied
  paintProjectBlock();
  // Keep the SERVER's active design dir in lock-step with the frontend's. Every
  // run-scoped endpoint (/api/runs, /api/runs/<tag>, cell-usage, run-images,
  // verify, …) resolves against the server's active dir. If it ever drifts from
  // state.designDir, the per-tab run dropdowns come back empty until the user
  // opens a run from the Runs window (which re-syncs it). Syncing here makes
  // every tab show the runs immediately, no manual Open needed.
  try {
    await api.setDesignDir(designDir);
    state.designMissing = null;
  } catch (ex) {
    // A folder that was moved or deleted: say so plainly instead of loading
    // a blank project, and keep Run off.
    if (/not found/i.test((ex && ex.message) || "")) { showMissingProject(designDir); return; }
  }
  paintMissing();
  // The PDK the project's config names is the one LibreLane builds for: the
  // picker shows it, rather than whatever was used last.
  await syncPdkFromConfig();
  paintDesignPill("loading…");
  const summaryEl = document.getElementById("design-summary");
  if (summaryEl) summaryEl.innerHTML = await summariseDir(designDir);
  paintDesignPill(fmt.shortPath(designDir));
  await loadFilesFor(designDir);
  const { renderRuns } = await import("./runs.js");
  try { state.runs = await api.runs(designDir); } catch (_e) { state.runs = []; }
  // The results pages show what this project showed last time, else its
  // newest run (context.js).
  (await import("./context.js")).openProject(designDir);
  if (!state.selectedRunTag && state.runs && state.runs.length) state.selectedRunTag = state.runs[0].tag;
  renderRuns();
  paintRunButton();
  renderPreflight();
  // Offer to auto-generate a config when the folder has sources but no config.
  try {
    const { maybeOfferAutoConfig } = await import("./autoconfig.js");
    maybeOfferAutoConfig(designDir);
  } catch (_e) { /* non-fatal */ }
  // The person opened a project (not boot re-opening the last one). After the
  // caller's own page change (the wizard goes to Setup when this returns).
  if (explicit) setTimeout(() => document.dispatchEvent(new CustomEvent("g:project_opened", { detail: { dir: designDir } })), 0);
}

// A project whose folder is gone (moved, renamed or deleted): its card says
// so, with the two ways out, and Run stays off until it is found or removed.
export function showMissingProject(dir) {
  state.designDir = dir;
  state.designMissing = dir;
  paintProjectBlock();
  paintMissing();
  paintRunButton();
  paintDesignPill(fmt.shortPath(dir));
}

function paintMissing() {
  const card = document.getElementById("project-open");
  if (!card) return;
  const dir = state.designMissing;
  card.classList.toggle("is-missing", !!dir);
  let box = document.getElementById("proj-missing");
  if (!dir) { if (box) box.remove(); return; }
  if (!box) {
    box = document.createElement("div");
    box.id = "proj-missing";
    box.className = "proj-missing";
    box.setAttribute("role", "alert");
    card.querySelector(".proj-path")?.after(box);
    box.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-miss]");
      if (!b) return;
      const gone = state.designMissing;
      if (b.dataset.miss === "locate") {
        (await import("./shell.js")).openFolder();
        return;
      }
      try { await api.projectForget(gone); } catch (_e) { /* the local list still drops it */ }
      try {
        const list = JSON.parse(localStorage.getItem("ll.recentDesigns") || "[]").filter((d) => d !== gone);
        localStorage.setItem("ll.recentDesigns", JSON.stringify(list));
      } catch (_e) { /* storage may be off */ }
      state.designMissing = null;
      state.designDir = null;
      state.runs = [];
      paintProjectBlock();
      paintMissing();
      paintRunButton();
      paintDesignPill("");
      toast.show("Removed it from the list. Nothing on disk was touched.", "success");
    });
  }
  box.innerHTML = "<p class='proj-missing-h'>" + icon("alert", { size: 15 }) + "<b>Project folder not found</b></p>" +
    "<p class='proj-missing-p'><code>" + fmt.escape(dir) + "</code></p>" +
    "<p class='muted proj-missing-p'>It may have been moved, renamed or deleted. Point LanEx at its new place, or take it off the list.</p>" +
    "<div class='picker-actions'><button class='btn btn-primary' data-miss='locate'>Locate…</button>" +
    "<button class='btn btn-ghost' data-miss='forget'>Remove from list</button></div>";
  const sum = document.getElementById("design-summary");
  if (sum) sum.innerHTML = "";
}

// The Project block: an empty state with the two ways in, or the open
// project's name, where it lives and what it contains.
function paintProjectBlock() {
  const open = !!state.designDir;
  const empty = document.getElementById("project-empty");
  const card = document.getElementById("project-open");
  if (empty) empty.hidden = open;
  if (card) card.hidden = !open;
  const sw = document.getElementById("hub-switch");
  if (sw) sw.hidden = !open;
  document.getElementById("hub-current-label")?.replaceChildren(open ? "Open project" : "Get started");
  // Sources and Settings belong to a project; with none open they'd only say so.
  document.getElementById("sec-setup")?.classList.toggle("no-project", !open);
  if (!open) { document.dispatchEvent(new CustomEvent("g:projects_changed")); return; }
  const dir = state.designDir;
  const name = dir.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || dir;
  const n = document.getElementById("proj-name");
  const p = document.getElementById("proj-path");
  if (n) n.textContent = name;
  import("./shell.js").then((m) => { if (p) { p.textContent = m.displayPath(dir); p.title = dir; } }).catch(() => {});
  document.dispatchEvent(new CustomEvent("g:projects_changed"));
}

// Under the Design row: one line about the newest run, and a warning line for
// anything that will stop a run (no config, spaces in the path).
function ago(sec) {
  const s = Math.max(0, Date.now() / 1000 - sec);
  if (s < 90) return "just now";
  if (s < 3600) return Math.round(s / 60) + " min ago";
  if (s < 86400) return Math.round(s / 3600) + " h ago";
  const d = Math.round(s / 86400);
  return d === 1 ? "yesterday" : d + " days ago";
}

function paintLastRun(facts) {
  const el = document.getElementById("proj-lastrun");
  if (!el) return;
  const last = facts && facts.last_run;
  if (!facts || !facts.runs || !last) { el.innerHTML = "No runs yet."; return; }
  el.innerHTML = "Last run " + (last.finished ? "finished" : "didn't finish") + " " + fmt.escape(ago(last.at)) +
    " · <button type='button' class='linklike' data-open='runs'>" +
    (facts.runs === 1 ? "View it" : "View all " + facts.runs + " runs") + "</button>";
}

// Only the "Last run" line, read again (after a run ends).
let _factsTok = 0;
async function summariseFacts(path) {
  const tok = ++_factsTok;
  try {
    const r = await fetch("/api/design-summary?path=" + encodeURIComponent(path), { headers: { "X-Requested-With": "XMLHttpRequest" } });
    const body = await r.json();
    if (tok !== _factsTok || path !== state.designDir || !r.ok || body.ok === false) return;
    paintLastRun((body.data || {}).facts || null);
  } catch (_e) { /* keep what it says */ }
}

async function summariseDir(path) {
  const src = "/api/design-summary?path=" + encodeURIComponent(path);
  try {
    const r = await fetch(src, { headers: { "X-Requested-With": "XMLHttpRequest" } });
    const body = await r.json();
    if (!r.ok || body.ok === false) throw new Error(body.error || "scan failed");
    const data = body.data || {};
    paintLastRun(data.facts || null);
    const warns = (data.pills || []).filter((x) => x.type === "warn" || x.type === "fail");
    return warns.map((x) =>
      "<p class='proj-note'>" + icon("alert", { size: 14 }) + "<span>" + fmt.escape(x.text) + "</span></p>").join("");
  } catch (_e) {
    paintLastRun(null);
    return "<p class='proj-note is-fail'>" + icon("alert", { size: 14 }) + "<span>Could not read this folder.</span></p>";
  }
}

// The top-bar project switcher names the open project (folder name; full path
// on hover). While a design is being opened it says so.
export function paintDesignPill(text) {
  if (text === "loading…") {
    const t = document.querySelector("#design-pill .text");
    if (t) t.textContent = "Opening…";
    return;
  }
  import("./shell.js").then((m) => m.paintProject()).catch(() => {});
}

export function paintPdkPill(text, kind) {
  const pill = document.getElementById("pdk-pill");
  pill.classList.remove("pill-warn", "pill-pass", "pill-fail");
  if (kind) pill.classList.add(kind);
  document.querySelector("#pdk-pill .text").textContent = text;
  // Mirror onto the inline readiness pill beside the PDK selects (D5): it used to
  // sit frozen at "checking…" because nothing ever repainted it.
  const inline = document.getElementById("pdk-readiness");
  if (inline) {
    inline.classList.remove("pill-pending", "pill-warn", "pill-pass", "pill-fail");
    if (kind) inline.classList.add(kind);
    inline.textContent = text.replace(/^PDK:\s*/, "");
  }
  paintOnboardChecklist();
}

// The hero's three steps look the same whatever the progress; only the first
// step's button follows state (New project until one is open).
export function paintOnboardChecklist() {
  const list = document.getElementById("onboard-checklist");
  if (!list) return;
  const first = list.querySelector('[data-step-act="project"]');
  if (first) first.textContent = state.designDir ? "View project" : "New project";
  first?.classList.toggle("btn-ghost", !!state.designDir);
  // Live progress for the open project: a tick on what's done, the next step
  // marked (the same progress the first-chip guide follows). The simulation
  // tick is set by guide.js when a simulation of this project runs to the end.
  const dd = state.designDir;
  const done = {
    design: !!dd,
    rtl: !!dd && safeStorage.get("ll.simok." + dd, "") === "1",
    pdk: !!dd && !!document.getElementById("pdk-readiness")?.classList.contains("pill-pass"),
    run: !!dd && (state.runs || []).length > 0,
  };
  let next = null;
  list.querySelectorAll("li[data-ck]").forEach((li) => {
    const ok = !!done[li.dataset.ck];
    li.classList.toggle("is-done", ok);
    li.classList.remove("is-next");
    if (!ok && !next) next = li;
  });
  next?.classList.add("is-next");
}

// ---------- the project's PDK ---------------------------------------------------
//
// LibreLane builds for the PDK and library the config file names, whatever
// -p/-s say (librelane/config/config.py reads the config's PDK first). So the
// picker follows the config when a project opens, a change to it is saved to
// the config, and a run whose picker and config disagree is refused by the
// server with both values named (configedit.pdk_mismatch).

let _cfgPdk = null;   // {dir, pdk, scl, name, editable}: what the config names

// The usual general-purpose library of each PDK family (pdk_catalog.py).
export const USUAL_SCL = ["sky130_fd_sc_hd", "gf180mcu_fd_sc_mcu7t5v0", "sg13g2_stdcell"];

function hasOpt(sel, v) { return !!v && Array.from(sel.options).some((o) => o.value === v); }

function addOpt(sel, v, label) {
  const o = document.createElement("option");
  o.value = v;
  o.textContent = label;
  sel.appendChild(o);
}

async function readConfigPdk() {
  _cfgPdk = null;
  if (!state.designDir) { paintPdkSrc(); return null; }
  try {
    const info = await api.designInfo({ keys: ["PDK", "STD_CELL_LIBRARY"] });
    const s = (info && info.settings) || {};
    const str = (v) => (typeof v === "string" ? v.trim() : "");
    _cfgPdk = {
      dir: state.designDir, pdk: str(s.PDK), scl: str(s.STD_CELL_LIBRARY),
      name: (info.config && info.config.name) || "the config", editable: !!(info.config && info.config.editable),
    };
  } catch (_e) { /* no config yet: nothing to follow */ }
  paintPdkSrc();
  return _cfgPdk;
}

// The PDK and library pickers' source buttons: the config's line for each.
function paintPdkSrc() {
  const c = cfgFor();
  import("./provenance.js").then((m) => m.paintConfigSrc(document.getElementById("setup-pdk"),
    (k) => !!(c && (k === "PDK" ? c.pdk : c.scl)))).catch(() => {});
}

const cfgFor = () => (_cfgPdk && _cfgPdk.dir === state.designDir ? _cfgPdk : null);

// Point the picker at the PDK the open project's config names. A PDK that
// isn't installed is still shown (and said), so the picker never pretends.
export async function syncPdkFromConfig() {
  const c = await readConfigPdk();
  const sel = document.getElementById("pdk-select");
  if (!c || !c.pdk || !sel) return;
  const installed = (state.pdks || []).some((p) => p.name === c.pdk);
  if (!hasOpt(sel, c.pdk)) addOpt(sel, c.pdk, c.pdk + " (not installed)");
  sel.value = c.pdk;
  await onPdkSelected();
  if (!installed) {
    toast.show("This project is set up for " + c.pdk + ", which isn't installed. Install it in Tools, or pick an installed PDK here " +
      "and LanEx saves it to " + c.name + ".", "warn", 10000, { label: "Open Tools", run: () => import("./nav.js").then((m) => m.go("tools")) });
  }
}

// Save the picker's PDK and library to the config, when the config names
// one (a config that names neither builds for whatever the picker sends).
async function saveTargetToConfig() {
  const c = cfgFor();
  if (!c || (!c.pdk && !c.scl)) return;
  const set = {};
  if (state.selectedPdk && state.selectedPdk !== c.pdk) set.PDK = state.selectedPdk;
  if (state.selectedScl && state.selectedScl !== c.scl) set.STD_CELL_LIBRARY = state.selectedScl;
  if (!Object.keys(set).length) return;
  if (!c.editable) {
    toast.show(c.name + " names " + (c.pdk || c.scl) + " and LanEx can't edit it. Change it there too: a run stops until the two agree.", "warn", 9000);
    return;
  }
  try {
    const r = await api.configSet(set, [], { pdk: state.selectedPdk || null, scl: state.selectedScl || null });
    if (state.varsValues) { delete state.varsValues.PDK; delete state.varsValues.STD_CELL_LIBRARY; }
    _cfgPdk = Object.assign({}, c, { pdk: set.PDK || c.pdk, scl: set.STD_CELL_LIBRARY || c.scl });
    paintPdkSrc();
    if (r.changed && r.changed.length) {
      const what = [set.PDK, set.STD_CELL_LIBRARY].filter(Boolean).join(" / ");
      const undo = r.undo && r.undo.backup ? { label: "Undo", run: () => undoTarget(r.undo, r.name) } : null;
      toast.show("Saved " + what + " to " + r.name + ".", "success", 6000, undo);
    }
    document.dispatchEvent(new CustomEvent("g:config_changed"));
  } catch (ex) {
    toast.show("Couldn't save the PDK to " + c.name + ": " + (ex.message || ex) + ". A run stops until the two agree.", "error", 9000);
  }
}

async function undoTarget(u, name) {
  try {
    await api.configUndo({ backup: u.backup, after: u.after });
    toast.show(name + " is back as it was.", "success", 4000);
    document.dispatchEvent(new CustomEvent("g:config_changed"));
  } catch (ex) {
    toast.show("Undo: " + (ex.message || ex), "warn", 8000);
  }
  await syncPdkFromConfig();
}

// The one-click fixes for a run (or the checklist) refused because the
// picker and the config disagree: save the picker's choice to the config,
// or set the picker to what the config says.
export async function resolvePdkMismatch(mm, how) {
  if (!mm) return false;
  if (how === "save") {
    try {
      const r = await api.configSet(mm.fix || {}, [], { pdk: state.selectedPdk || null, scl: state.selectedScl || null });
      const what = [mm.fix.PDK, mm.fix.STD_CELL_LIBRARY].filter(Boolean).join(" / ");
      const undo = r.undo && r.undo.backup ? { label: "Undo", run: () => undoTarget(r.undo, r.name) } : null;
      toast.show("Saved " + what + " to " + r.name + ".", "success", 6000, undo);
      await readConfigPdk();
      document.dispatchEvent(new CustomEvent("g:config_changed"));
      return true;
    } catch (ex) {
      toast.show("Couldn't save to " + (mm.name || "the config") + ": " + (ex.message || ex), "error", 9000);
      return false;
    }
  }
  await syncPdkFromConfig();
  const ss = document.getElementById("scl-select");
  if (mm.config.scl && ss) {
    if (!hasOpt(ss, mm.config.scl)) addOpt(ss, mm.config.scl, mm.config.scl + " (not installed)");
    ss.value = mm.config.scl;
    state.selectedScl = mm.config.scl;
    refreshPdkReadiness();
  }
  toast.show("The PDK picker now follows " + (mm.name || "the config") + ".", "success", 4000);
  return true;
}

async function onPdkSelected(e) {
  const user = !!(e && e.type === "change");
  const sel = document.getElementById("pdk-select");
  state.selectedPdk = sel.value;
  if (!sel.value) return;
  safeStorage.set("ll.recentPdk", sel.value);   // remember for next session
  try {
    const scls = await api.scls(sel.value);
    const sclSel = document.getElementById("scl-select");
    const keep = state.selectedScl;
    sclSel.innerHTML = "";
    for (const s of scls) {
      const opt = document.createElement("option");
      opt.value = s.variants[0]?.[1] || "";
      opt.textContent = s.variants[0]?.[0] || "(unknown)";
      sclSel.appendChild(opt);
    }
    // The config's library when it names one for this PDK; then the one in
    // use if this PDK offers it too (sky130A and sky130B share libraries), the
    // last-used one, and the family's usual general-purpose one
    // (sky130_fd_sc_hd, the 7-track gf180 cells).
    const offered = (v) => hasOpt(sclSel, v);
    const c = cfgFor();
    const cfgScl = c && c.scl && (c.pdk === sel.value || offered(c.scl)) ? c.scl : "";
    if (cfgScl && !offered(cfgScl)) addOpt(sclSel, cfgScl, cfgScl + " (not installed)");
    const wantScl = safeStorage.get("ll.recentScl", "");
    const usual = USUAL_SCL.find(offered);
    if (cfgScl) sclSel.value = cfgScl;
    else if (offered(keep)) sclSel.value = keep;
    else if (offered(wantScl)) sclSel.value = wantScl;
    else if (usual) sclSel.value = usual;
    state.selectedScl = sclSel.value || "";
    paintPdkAbout(sel.value);
    if (user) await saveTargetToConfig();
    if (user) document.dispatchEvent(new CustomEvent("g:pdk_confirmed", { detail: { pdk: sel.value } }));
    import("./projectcard.js").then((m) => m.paintDesignRow()).catch(() => {});
    refreshPdkReadiness();
  } catch (ex) {
    paintPdkPill("error", "pill-fail");
  }
}

// One plain line about the chosen process, and its layer stack in the hero.
function paintPdkAbout(pdk) {
  const about = document.getElementById("pdk-about");
  const facts = pdkFacts(pdk);
  if (about) about.textContent = facts.about;
  const fig = document.getElementById("layer-stack");
  const html = stackHtml(pdk);
  // Unknown PDK: keep the sky130 stack the page ships with.
  if (fig && html) fig.innerHTML = html;
}

async function onSclSelected(e) {
  const sel = document.getElementById("scl-select");
  state.selectedScl = sel.value;
  if (sel.value) safeStorage.set("ll.recentScl", sel.value);
  if (e && e.type === "change") await saveTargetToConfig();
  refreshPdkReadiness();
}

async function refreshPdkReadiness() {
  if (!state.selectedPdk) return;
  try {
    const r = await api.pdkReady(state.selectedPdk, state.selectedScl, state.runMode);
    if (r.ready) {
      paintPdkPill("PDK ready", "pill-pass");
    } else if (r.needs_download && r.network_available) {
      paintPdkPill("PDK: will download on first run", "pill-warn");
    } else {
      paintPdkPill("PDK: " + state.selectedPdk + " (missing " + (r.missing.join(", ") || "files") + ")", "pill-warn");
    }
  } catch (_e) {
    paintPdkPill("PDK: check failed", "pill-fail");
  }
  renderPreflight();
}

export async function populatePdkPicker() {
  try {
    const pdks = await api.pdks();
    const sel = document.getElementById("pdk-select");
    sel.innerHTML = "";
    if (!pdks.length) {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "No PDK installed";
      sel.appendChild(o);
    }
    for (const p of pdks) {
      const o = document.createElement("option");
      o.value = p.name;
      o.textContent = p.name + (p.ready ? "" : " (no libs)");
      sel.appendChild(o);
    }
    // The PDK the open project's config names (shown even when it isn't
    // installed), then the last one used if it's ready, then a ready sky130A,
    // then the first ready PDK: an empty leftover folder is never the default.
    const projectPdk = (cfgFor() || {}).pdk || "";
    if (projectPdk && !hasOpt(sel, projectPdk)) addOpt(sel, projectPdk, projectPdk + " (not installed)");
    const has = (v) => hasOpt(sel, v);
    const ready = (v) => pdks.some((p) => p.name === v && p.ready);
    const recent = safeStorage.get("ll.recentPdk", "");
    const firstReady = ["sky130A", "gf180mcuD", "ihp-sg13g2"].find(ready) || (pdks.find((p) => p.ready) || pdks[0] || {}).name || "";
    const wantPdk = has(projectPdk) ? projectPdk : ready(recent) ? recent : firstReady;
    if (wantPdk && Array.from(sel.options).some((o) => o.value === wantPdk)) {
      sel.value = wantPdk;
      await onPdkSelected();   // repopulates SCLs + restores the SCL + readiness
    } else if (pdks.length) {
      paintPdkPill("PDK: pick one", "pill-warn");
    } else {
      paintPdkPill("No PDKs installed", "pill-fail");
    }
  } catch (_e) {
    paintPdkPill("PDK: probe failed", "pill-fail");
  }
}

export function paintRunButton() {
  const b = document.getElementById("btn-run");
  const g = document.getElementById("btn-run-global");
  // Don't fight paintRunning while a run is live (the global button is "Stop").
  const running = state.status && state.status.running;
  const off = !state.designDir || !!state.designMissing;
  if (g && !running) g.disabled = off;
  if (!b) return;
  b.disabled = off;
}

async function onRunClick({ show = false, fixed = false } = {}) {
  if (!state.designDir) {
    toast.show("Pick a design folder first.", "warn");
    return;
  }
  if (state.designMissing) {
    toast.show("Project folder not found: " + state.designMissing + ". Locate it or remove it from the list on Setup.", "warn");
    return;
  }
  // Preflight: catch missing tools / PDK before a long run fails half-way.
  try {
    const pf = await renderPreflight();
    const mm = pf && pf.pdk && pf.pdk.mismatch;
    if (mm && !fixed) { await offerPdkFix(mm, show); return; }
    if (pf && !pf.ready) {
      const { confirmDialog } = await import("./dialog.js");
      const go = await confirmDialog({
        title: "Not everything is ready",
        body: "Blockers: " + pf.blockers.join("; ") +
          ". Run anyway? The flow will likely stop at the first missing piece.",
        confirmText: "Run anyway", danger: true,
      });
      if (!go) {
        toast.show("Run cancelled. Review the 'Ready to run?' checklist for details.", "warn");
        return;
      }
    }
  } catch (_e) { /* preflight is best-effort; don't block the run on it */ }
  const payload = collectRunPayload();
  const rsel = document.getElementById("run-resume-from");
  if (rsel && rsel.value && rsel.dataset.tag) {
    // Resume from a stage of the run on the results pages: the server plans it
    // (and starts earlier if something those stages read has changed since).
    payload.branch_from = { tag: rsel.dataset.tag, step: rsel.value };
  }
  try {
    const res = await api.startRun(payload);
    if (!res.ok || res.started === false) {
      if (res.pdk_mismatch && !fixed) { await offerPdkFix(res.pdk_mismatch, show); return; }
      toast.show("Run refused: " + (res.reason || res.error || "unknown"), "error");
      return;
    }
    if (payload.branch_from) {
      const r = res.resume;
      const asked = FS.stagesOf([{ id: payload.branch_from.step }])[0];
      toast.show("Resuming " + payload.branch_from.tag + " from " + (r ? FS.stageLabel(r.stage) : "the start") + " as " + res.tag +
        (r && r.reasons && r.reasons.includes("earlier") ? ", earlier than " + FS.stageLabel(asked) + ": something it reads changed since" : "") + ".", "success", 9000);
      rsel.value = "";
      paintRunLabel();
    }
    if (res.warning) toast.show(res.warning, "warn");
    // TOCTOU (N7): if the user opened the Final-settings preview and then the
    // config file changed before this run, the preview no longer matches what
    // ran. Compare the previewed config hash to the one the run actually used.
    if (state.previewedConfigHash && res.config_hash &&
        res.config_hash !== state.previewedConfigHash) {
      toast.show("The configuration file changed after your preview. Flow execution used the updated file on disk.", "warn");
    }
    state.previewedConfigHash = null;
    paintRunning(true);
    document.dispatchEvent(new CustomEvent("g:run_started", { detail: { tag: res.tag || payload.tag || null } }));
    // Pressing Run shows the run on Flow, unless the user turned that off in
    // the Run menu (then the status line shows it, and this says so). Setup's
    // Run flow and the very first run always show it.
    const first = !safeStorage.get("ll.ranOnce") && !(state.runs || []).length;
    safeStorage.set("ll.ranOnce", "1");
    const { go } = await import("./nav.js");
    const { currentTab } = await import("./tabs.js");
    if (show || first || safeStorage.get("ll.showFlowOnRun") !== "0") go("pipeline", {}, { link: false });
    else if (currentTab() !== "pipeline") {
      toast.show((payload.tag ? "Run " + payload.tag + " started" : "The run started") +
        ". It keeps going in the background; the status bar shows how far it is.", "info", 7000,
        { label: "Watch it", run: () => go("pipeline") });
    }
  } catch (ex) {
    toast.show("Run failed: " + ex.message, "error");
  }
}

// The run was refused because the PDK picker and the config disagree: say
// both values and offer the two ways to make them agree, then run.
async function offerPdkFix(mm, show) {
  const { choiceDialog } = await import("./dialog.js");
  const choices = [];
  // Short labels: the body already names both values.
  if (mm.editable) choices.push({ label: "Save to " + (mm.name || "the config") + " and run", value: "save" });
  if (mm.config.pdk) choices.push({ label: "Run on " + mm.config.pdk, value: "follow" });
  const how = await choiceDialog({ title: "The PDK picker and " + (mm.name || "the config") + " disagree", body: mm.message, choices });
  if (!how) return;
  if (await resolvePdkMismatch(mm, how)) onRunClick({ show, fixed: true });
}

export function collectRunPayload() {
  // Setup's "Run name", sanitised to a filesystem-safe run-dir name.
  const rawName = (document.getElementById("run-name-input")?.value || "").trim();
  const tag = rawName ? rawName.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") : "";
  // "Run up to" a stage (Run menu): LibreLane's --to, at that stage's last step.
  const to = lastStepOf(document.getElementById("run-stop-after")?.value || "");
  // Apply PDK + SCL overrides picked in setup. Drop any blank/empty value so a
  // left-empty constraint field never becomes a bare `KEY=` the engine can't
  // type-parse (issue #11) — blank means "use the default". The backend strips
  // these too; doing it here keeps the CLI-reveal/preview honest.
  const overrides = {};
  for (const [k, v] of Object.entries(state.varsValues || {})) {
    if (v === null || v === undefined) continue;
    if (typeof v === "string" && v.trim() === "") continue;
    overrides[k] = v;
  }
  if (state.selectedPdk) overrides.PDK = state.selectedPdk;
  if (state.selectedScl) overrides.STD_CELL_LIBRARY = state.selectedScl;
  // Sources: the config's VERILOG_FILES is the project's list. The ticks are
  // sent as a per-run override only when they differ from it (a Tcl config,
  // a config LanEx couldn't edit, or a run loaded from history).
  const ticked = (state.selectedFiles || []).filter(Boolean);
  const cfgSrc = state.configSources;
  const sameAsConfig = Array.isArray(cfgSrc) && cfgSrc.length > 0 && ticked.length === cfgSrc.length &&
    ticked.every((f) => cfgSrc.includes(f));
  const sources = sameAsConfig ? [] : ticked;
  const extras = (state.extrasFiles || []).filter(Boolean);
  return {
    tag: tag || null,
    frm: null,
    to: to || null,
    skip: [],
    overrides,
    sources,
    extras,
    mode: state.mode,
    run_mode: state.runMode,
  };
}

// The last step of a stage in the flow that runs (Classic unless told), for --to.
function lastStepOf(stageId) {
  if (!stageId) return "";
  const flow = (state.flows || []).find((f) => f.name === (state.flowName || "Classic"));
  const ids = (flow && flow.steps) || [];
  const stages = FS.stagesOf(ids.map((id) => ({ id })));
  let last = "";
  stages.forEach((s, i) => { if (s === stageId) last = ids[i]; });
  return last;
}

// The Run menu's run options: where to stop, and what to do when a run
// starts and ends (runend.js reads the same keys).
function wireRunMenu() {
  const sel = document.getElementById("run-stop-after");
  if (sel) {
    sel.innerHTML = "<option value=''>The whole flow, to the GDS</option>" +
      FS.STAGES.filter((s) => s.id !== "signoff").map((s, i) =>
        "<option value='" + s.id + "'>" + (i + 1) + ". " + fmt.escape(s.label) + (s.id === "synthesis" ? " (cells and area in seconds)" : "") + "</option>").join("");
    sel.addEventListener("change", () => paintRunLabel());
  }
  const pref = (id, key, onChange, on = false) => {
    const box = document.getElementById(id);
    if (!box) return;
    box.checked = on ? safeStorage.get(key) !== "0" : safeStorage.get(key) === "1";
    box.addEventListener("change", async () => {
      if (onChange) {
        const r = await onChange(box.checked);
        if (r && !r.ok) { box.checked = false; toast.show(r.why, "warn", 7000); }
      } else safeStorage.set(key, box.checked ? "1" : "0");
    });
  };
  // Resume from a stage of the run on the results pages (LibreLane's -i and
  // --from, as a new run): the stages it can resume from come from the server,
  // which knows how far that run got and what changed since.
  const res = document.getElementById("run-resume-from");
  if (res) {
    res.innerHTML = "<option value=''>The start (a fresh run)</option>";
    res.addEventListener("change", () => paintRunLabel());
    document.getElementById("run-opts-btn")?.addEventListener("click", () => fillResume());
    // It resumes the run on the results pages: picking another run disarms it.
    document.addEventListener("g:context", (e) => {
      if (res.value && res.dataset.tag !== (e.detail || {}).run) { res.value = ""; paintRunLabel(); }
    });
  }
  pref("run-pref-show", "ll.showFlowOnRun", null, true);
  pref("run-pref-notify", "ll.notifyRuns", async (on) => (await import("./runend.js")).enableNotifications(on));
  pref("run-pref-chime", "ll.runChime");
}

let _resumeTok = 0;
async function fillResume() {
  const sel = document.getElementById("run-resume-from");
  const note = document.getElementById("run-resume-note");
  if (!sel) return;
  const { contextRun } = await import("./context.js");
  const tag = contextRun();
  const keep = sel.value;
  const tok = ++_resumeTok;
  if (!tag) { sel.innerHTML = "<option value=''>The start (a fresh run)</option>"; if (note) note.textContent = "No run to resume from yet."; return; }
  if (note) note.textContent = "Reading " + tag + "…";
  let p = null;
  try { p = await api.fixPlan({ tag, sets: {}, start: "auto", run_mode: state.runMode }); } catch (ex) { p = { error: ex.message }; }
  if (tok !== _resumeTok) return;
  if (!p || p.error) { if (note) note.textContent = (p && p.error) || ""; return; }
  const opts = (p.stages || []).filter((s) => s.index > 0).map((s) => {
    const st = FS.stage(s.stage);
    const why = s.ok ? "" : s.index > (p.parent.stopped != null ? p.parent.stopped : p.parent.done + 1)
      ? " (" + tag + " didn't get there)" : " (something it reads changed)";
    return "<option value='" + fmt.escape(s.step) + "' data-stage='" + fmt.escape(s.stage) + "'" + (s.ok ? "" : " disabled") + ">" +
      (FS.STAGES.indexOf(st) + 1) + ". " + fmt.escape(st ? st.label : s.stage) + why + "</option>";
  });
  sel.innerHTML = "<option value=''>The start (a fresh run)</option>" + opts.join("");
  sel.value = [...sel.options].some((o) => o.value === keep && !o.disabled) ? keep : "";
  sel.dataset.tag = tag;
  const d = p.drift || {};
  const changed = (d.settings || []).map((x) => x.var).concat((d.files || []).map((f) => f.path));
  if (note) note.textContent = "Reuses " + tag + "'s results up to that stage." + (changed.length ? " Changed since: " + changed.slice(0, 3).join(", ") + "." : "");
  paintRunLabel();
}

// "Run", "Run to Placement" or "Resume from Placement": the button says what
// it will do.
function paintRunLabel() {
  const g = document.getElementById("btn-run-global");
  if (!g || (state.status && state.status.running)) return;
  const st = FS.stage(document.getElementById("run-stop-after")?.value || "");
  const rsel = document.getElementById("run-resume-from");
  const ropt = rsel && rsel.value ? rsel.options[rsel.selectedIndex] : null;
  const rst = ropt ? FS.stage(ropt.dataset.stage) : null;
  const span = g.querySelector("span");
  if (span) span.textContent = rst ? "Resume from " + rst.label + (st ? " to " + st.label : "") : st ? "Run to " + st.label : "Run";
  g.classList.toggle("is-partial", !!(st || rst));
  g.dataset.tip = rst ? "A new run that reuses " + rsel.dataset.tag + "'s results up to " + rst.label + " (r)" : "Run the flow on this project (r)";
}

export function paintRunning(running) {
  const b = document.getElementById("btn-run");
  const c = document.getElementById("btn-cancel");
  const r = document.getElementById("btn-resume");
  const pill = document.getElementById("run-pill");
  // Resume/Next is only meaningful in Step-by-step mode.
  const showResume = running && state.mode === "semi";
  if (r) r.hidden = !showResume;
  const g = document.getElementById("btn-run-global");
  if (running) {
    if (b) b.disabled = true;
    if (c) { c.disabled = false; c.hidden = false; }
    if (g) { g.disabled = false; g.innerHTML = icon("stop", { size: 15 }) + "<span>Stop</span>"; g.classList.add("is-stop"); }
    pill?.classList.remove("pill-pending");
    pill?.classList.add("pill-running");
    if (pill) pill.textContent = "running";
  } else {
    if (b) b.disabled = !state.designDir;
    if (c) { c.disabled = true; c.hidden = true; }   // Stop shows only while a run is live
    if (g) { g.disabled = !state.designDir; g.innerHTML = icon("play", { size: 15 }) + "<span>Run</span>"; g.classList.remove("is-stop"); paintRunLabel(); }
    pill?.classList.add("pill-pending");
    pill?.classList.remove("pill-running");
    if (pill) pill.textContent = "idle";
  }
}

