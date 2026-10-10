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

// Switch to another tab and run something there once it has rendered.
function goTab(name) {
  document.querySelector('.side-tab[data-tab="' + name + '"]')?.click();
}

async function openIde(opts) {
  goTab("ide");
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
      goTab("runs");
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
  document.getElementById("btn-set-design")?.addEventListener("click", onLoadDesign);
  document.getElementById("design-dir-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") onLoadDesign();
  });

  document.getElementById("pdk-select")?.addEventListener("change", onPdkSelected);
  document.getElementById("scl-select")?.addEventListener("change", onSclSelected);

  document.getElementById("btn-run")?.addEventListener("click", onRunClick);
  document.getElementById("btn-cancel")?.addEventListener("click", () => api.cancelRun().catch(() => {}));
  document.getElementById("btn-cancel-2")?.addEventListener("click", () => api.cancelRun().catch(() => {}));
  // Global topbar Run/Stop: start the flow, or stop a running one, from any tab —
  // no need to navigate back to Setup. Reuses the same start/cancel paths.
  document.getElementById("btn-run-global")?.addEventListener("click", () => {
    if (state.status && state.status.running) { api.cancelRun().catch(() => {}); }
    else { onRunClick(); }
  });
  document.getElementById("btn-resume")?.addEventListener("click", () => api.resumeRun().catch(() => {}));
  document.getElementById("btn-resume-2")?.addEventListener("click", () => api.resumeRun().catch(() => {}));
  document.getElementById("btn-preflight")?.addEventListener("click", () => renderPreflight());

  // D11: the Setup "Run name" and the Pipeline-bar "run tag" are two inputs for
  // the same value — mirror each into the other so they can never silently disagree.
  const nameA = document.getElementById("run-name-input");
  const nameB = document.getElementById("run-tag-input");
  if (nameA && nameB) {
    nameA.addEventListener("input", () => { nameB.value = nameA.value; });
    nameB.addEventListener("input", () => { nameA.value = nameB.value; });
  }

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
  try { await api.setDesignDir(designDir); } catch (_e) { /* best-effort */ }
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
}

async function onPdkSelected() {
  const sel = document.getElementById("pdk-select");
  state.selectedPdk = sel.value;
  if (!sel.value) return;
  safeStorage.set("ll.recentPdk", sel.value);   // remember for next session
  try {
    const scls = await api.scls(sel.value);
    const sclSel = document.getElementById("scl-select");
    sclSel.innerHTML = "";
    for (const s of scls) {
      const opt = document.createElement("option");
      opt.value = s.variants[0]?.[1] || "";
      opt.textContent = s.variants[0]?.[0] || "(unknown)";
      sclSel.appendChild(opt);
    }
    // The last-used library if this PDK offers it; otherwise the family's usual
    // general-purpose one (sky130_fd_sc_hd, the 7-track gf180 cells).
    const wantScl = safeStorage.get("ll.recentScl", "");
    const offered = (v) => Array.from(sclSel.options).some((o) => o.value === v);
    const usual = ["sky130_fd_sc_hd", "gf180mcu_fd_sc_mcu7t5v0", "sg13g2_stdcell"].find(offered);
    if (offered(wantScl)) sclSel.value = wantScl;
    else if (usual) sclSel.value = usual;
    state.selectedScl = sclSel.value || "";
    paintPdkAbout(sel.value);
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

async function onSclSelected() {
  const sel = document.getElementById("scl-select");
  state.selectedScl = sel.value;
  if (sel.value) safeStorage.set("ll.recentScl", sel.value);
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
    // Restore the project PDK or previously-used PDK if it's still installed.
    // Respect the project's explicit PDK before recent UI preferences.
    const projectPdk = state.projectConfig?.PDK || state.config?.PDK || "";
    const has = (v) => !!v && Array.from(sel.options).some((o) => o.value === v);
    const recent = safeStorage.get("ll.recentPdk", "");
    // The project's own PDK, then the last one used, then sky130A for beginners.
    const wantPdk = has(projectPdk) ? projectPdk : has(recent) ? recent
      : has("sky130A") ? "sky130A" : (pdks[0] && pdks[0].name) || "";
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
  if (g && !running) g.disabled = !state.designDir;
  if (!b) return;
  b.disabled = !state.designDir;
}

async function onRunClick() {
  if (!state.designDir) {
    toast.show("Pick a design folder first.", "warn");
    return;
  }
  // Preflight: catch missing tools / PDK before a long run fails half-way.
  try {
    const pf = await renderPreflight();
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
  try {
    const res = await api.startRun(payload);
    if (!res.ok) {
      toast.show("Run refused: " + (res.reason || "unknown"), "error");
      return;
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
    openLogsTab();
  } catch (ex) {
    toast.show("Run failed: " + ex.message, "error");
  }
}

function openLogsTab() {
  document.querySelector('.side-pane-tab[data-itab="logs"]')?.click();
}

export function collectRunPayload() {
  // Prefer the Setup-tab "Run name" (visible at run time); fall back to the
  // Pipeline tab's run-tag field. Sanitised to a filesystem-safe run-dir name.
  const rawName = (document.getElementById("run-name-input")?.value || "").trim() ||
    (document.getElementById("run-tag-input")?.value || "").trim();
  const tag = rawName ? rawName.replace(/[^A-Za-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") : "";
  const frm = (document.getElementById("run-from")?.value || "").trim();
  const to = (document.getElementById("run-to")?.value || "").trim();
  const skipRaw = (document.getElementById("run-skip")?.value || "").trim();
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
    frm: frm || null,
    to: to || null,
    skip: skipRaw ? skipRaw.split(",").map((x) => x.trim()).filter(Boolean) : [],
    overrides,
    sources,
    extras,
    mode: state.mode,
    run_mode: state.runMode,
  };
}

export function paintRunning(running) {
  const b = document.getElementById("btn-run");
  const c = document.getElementById("btn-cancel");
  const c2 = document.getElementById("btn-cancel-2");
  const r = document.getElementById("btn-resume");
  const r2 = document.getElementById("btn-resume-2");
  const pill = document.getElementById("run-pill");
  // Resume/Next is only meaningful in Step-by-step mode.
  const showResume = running && state.mode === "semi";
  if (r) r.hidden = !showResume;
  if (r2) r2.hidden = !showResume;
  const g = document.getElementById("btn-run-global");
  if (running) {
    if (b) b.disabled = true;
    if (c) { c.disabled = false; c.hidden = false; }
    if (c2) c2.disabled = false;
    if (g) { g.disabled = false; g.innerHTML = icon("stop", { size: 15 }) + "<span>Stop</span>"; g.classList.add("is-stop"); }
    pill?.classList.remove("pill-pending");
    pill?.classList.add("pill-running");
    if (pill) pill.textContent = "running";
  } else {
    if (b) b.disabled = !state.designDir;
    if (c) { c.disabled = true; c.hidden = true; }   // Stop shows only while a run is live
    if (c2) c2.disabled = true;
    if (g) { g.disabled = !state.designDir; g.innerHTML = icon("play", { size: 15 }) + "<span>Run</span>"; g.classList.remove("is-stop"); }
    pill?.classList.add("pill-pending");
    pill?.classList.remove("pill-running");
    if (pill) pill.textContent = "idle";
  }
}

