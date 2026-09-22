// setup.js — design picker, PDK picker, run button, mode switch.

import { api } from "./api.js";
import { state, safeStorage } from "./state.js";
import { fmt } from "./api.js";
import { renderConfig } from "./config.js";
import { setupFolderBrowser, loadFilesFor } from "./fs.js";
import { toast } from "./toast.js";
import { renderPreflight, lastPreflight } from "./preflight.js";
import { icon } from "./icons.js";
import { wireJump } from "./jumpnav.js";

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
  renderRecentDesigns();
}

export function renderRecentDesigns() {
  const root = document.getElementById("recent-designs");
  if (!root) return;
  const list = getRecentDesigns().filter((d) => d !== state.designDir);
  if (!list.length) {
    root.innerHTML = "";
    return;
  }
  root.innerHTML =
    "<span class='muted' style='font-size:var(--t-xs);margin-right:var(--s-2)'>Recent:</span>" +
    list
      .map(
        (d) =>
          "<button class='chip chip-clickable recent-chip' data-dir='" +
          fmt.escape(d) +
          "' title='" + fmt.escape(d) + "'>" +
          fmt.escape(d.split(/[/\\]/).pop() || d) +
          "</button>",
      )
      .join("");
  root.querySelectorAll(".recent-chip").forEach((b) => {
    b.addEventListener("click", async () => {
      const dir = b.dataset.dir;
      const input = document.getElementById("design-dir-input");
      if (input) input.value = dir;
      try {
        const res = await api.setDesignDir(dir);
        await adoptDesignDir(res.design_dir);
      } catch (ex) {
        toast.show("Could not open " + dir + ": " + ex.message, "error");
      }
    });
  });
}

export function setupSetup() {
  setupFolderBrowser();
  renderRecentDesigns();
  // Section-jump bar — the Setup tab is long (design → PDK → preflight → run →
  // constraints), so give it the same "Jump to section" chip bar the other tabs
  // have. Constraints is a <details>; wireJump opens it before scrolling.
  wireJump(document.getElementById("sec-setup"));
  // Second tier: the Constraints category milestones (Tech PDK, Synthesis, …)
  // are populated by config.js and revealed only while the Constraints card is
  // open — progressive disclosure so the jump bar stays clean until you need them.
  const cfgCard = document.getElementById("cfg-card");
  const cfgSub = document.getElementById("setup-jump-config");
  if (cfgCard && cfgSub) {
    const syncSub = () => { cfgSub.hidden = !(cfgCard.open && cfgSub.childElementCount > 0); };
    cfgCard.addEventListener("toggle", syncSub);
    syncSub();
  }
  document.getElementById("btn-set-design")?.addEventListener("click", onLoadDesign);
  document.getElementById("design-dir-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") onLoadDesign();
  });
  document.getElementById("btn-load-spm")?.addEventListener("click", onLoadSpmExample);
  document.getElementById("btn-quickstart")?.addEventListener("click", showOnboarding);

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
    btn.addEventListener("click", () => setFlowMode(btn.dataset.mode));
  });
  setFlowMode(state.mode || "auto");

  // Invalidate and recompute preflight on engine or source changes
  document.addEventListener("lanex:runmode-changed", async () => {
    await renderPreflight();
    paintRunButton();
  });
  document.addEventListener("lanex:sources-changed", async () => {
    await renderPreflight();
    paintRunButton();
  });
  document.addEventListener("lanex:preflight-done", () => {
    paintRunButton();
  });
}

export function setFlowMode(mode) {
  const m = mode === "semi" ? "semi" : "auto";
  state.mode = m;
  document.querySelectorAll(".mode-btn").forEach((b) => {
    const isActive = b.dataset.mode === m;
    b.classList.toggle("mode-btn-active", isActive);
    b.setAttribute("aria-pressed", isActive ? "true" : "false");
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
// `opts.explicit` (default true) means the *user* chose this dir, so show its
// scoped file list. Boot auto-adopt passes {explicit:false}: it scopes Runs /
// Preview but leaves the Setup file selector hidden (the history / recent
// designs stay visible) until the user explicitly loads a design.
export async function adoptDesignDir(designDir, opts = {}) {
  const explicit = opts.explicit !== false;
  state.designDir = designDir;
  state.designExplicit = explicit;
  rememberDesign(designDir);
  paintOnboardChecklist();  // E5.1 — step 1 (design chosen) is now satisfied
  // Keep the SERVER's active design dir in lock-step with the frontend's. Every
  // run-scoped endpoint (/api/runs, /api/runs/<tag>, cell-usage, run-images,
  // verify, …) resolves against the server's active dir. If it ever drifts from
  // state.designDir, the per-tab run dropdowns come back empty until the user
  // opens a run from the Runs window (which re-syncs it). Syncing here makes
  // every tab show the runs immediately, no manual Open needed.
  try { await api.setDesignDir(designDir); } catch (_e) { /* best-effort */ }
  paintDesignPill("loading…");
  const summaryEl = document.getElementById("design-summary");
  if (summaryEl) summaryEl.innerHTML = explicit ? await summariseDir(designDir) : "";
  const pill = document.getElementById("design-pill");
  if (pill) {
    pill.classList.remove("pill-warn");
    pill.classList.add("pill-pass");
  }
  paintDesignPill(fmt.shortPath(designDir));
  await loadFilesFor(designDir, { show: explicit });
  const { renderRuns } = await import("./runs.js");
  const { renderPreview } = await import("./preview.js");
  try { state.runs = await api.runs(designDir); } catch (_e) { state.runs = []; }
  // Default the run selection to the most recent run so run-scoped views
  // (Preview/Analytics/Verify/Layout) have something selected without the user
  if (state.runs && state.runs.length &&
      !state.runs.some((r) => r.tag === state.selectedRunTag)) {
    state.selectedRunTag = state.runs[0].tag;
  }
  renderRuns();
  renderPreview();
  const btnSet = document.getElementById("btn-set-design");
  if (btnSet) {
    btnSet.classList.remove("btn-primary");
    btnSet.classList.add("btn-ghost");
    btnSet.textContent = "Loaded";
  }
  paintRunButton();
  renderPreflight();
  // Offer to auto-generate a config when the folder has sources but no config.
  try {
    const { maybeOfferAutoConfig } = await import("./autoconfig.js");
    maybeOfferAutoConfig(designDir);
  } catch (_e) { /* non-fatal */ }
}

async function onLoadSpmExample() {
  try {
    const res = await api.copySpm(state.designDir || undefined);
    const input = document.getElementById("design-dir-input");
    if (input) input.value = res.design_dir;
    await adoptDesignDir(res.design_dir);
    toast.show("SPM example copied to " + fmt.shortPath(res.design_dir) + ". Click Run flow to begin hardening.", "success");
  } catch (ex) {
    toast.show("Could not copy the SPM example: " + ex.message, "error");
  }
}

async function summariseDir(path) {
  // Scan the directory for .v/.sdc/config and render the result as pills.
  const src = "/api/design-summary?path=" + encodeURIComponent(path);
  const pillClass = { pass: "pill-pass", fail: "pill-fail", pending: "pill-pending", info: "pill-info" };
  try {
    const r = await fetch(src, { headers: { "X-Requested-With": "XMLHttpRequest" } });
    const body = await r.json();
    if (!r.ok || body.ok === false) throw new Error(body.error || "scan failed");
    const pills = (body.data && body.data.pills) || [];
    if (!pills.length) return "<span class='pill pill-pending'>empty folder</span>";
    return pills
      .map((p) => `<span class='pill ${pillClass[p.type] || "pill-info"}'>${fmt.escape(p.text)}</span>`)
      .join(" ");
  } catch (_e) {
    return "<span class='pill pill-fail'>could not scan directory</span>";
  }
}


export function paintDesignPill(text) {
  document.querySelector("#design-pill .text").textContent = text;
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

// E5.1 — the hero's 3-step guide reflects REAL state, not static prose. Each step
// is only ticked when its condition is genuinely true (design chosen / PDK ready /
// a successful run exists), so it never claims progress the user hasn't made.
export function paintOnboardChecklist() {
  const list = document.getElementById("onboard-checklist");
  if (!list) return;
  const pill = document.getElementById("pdk-pill");
  const status = {
    design: !!state.designDir,
    // The PDK pill is painted green only by the honest readiness probe.
    pdk: !!(pill && pill.classList.contains("pill-pass")),
    // A genuinely completed run for this design — not merely "Run was pressed".
    run: (state.runs || []).some((r) => r && r.success),
  };
  list.querySelectorAll("li[data-ck]").forEach((li) => {
    const done = !!status[li.dataset.ck];
    li.classList.toggle("ck-done", done);
    const mark = li.querySelector(".ck-mark");
    if (mark) mark.innerHTML = done ? icon("check", { size: 14 }) : icon("dot", { size: 14 });
  });
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
    // Restore the previously-used SCL if it's offered for this PDK.
    const wantScl = safeStorage.get("ll.recentScl", "");
    if (wantScl && Array.from(sclSel.options).some((o) => o.value === wantScl)) {
      sclSel.value = wantScl;
    }
    state.selectedScl = sclSel.value || "";
    refreshPdkReadiness();
  } catch (ex) {
    paintPdkPill("error", "pill-fail");
  }
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
    } else if (r.supported === false) {
      paintPdkPill("PDK: unsupported target", "pill-fail");
    } else if (r.needs_download && r.network_available) {
      paintPdkPill("PDK: will download on first run", "pill-warn");
    } else {
      paintPdkPill("PDK: " + state.selectedPdk + " (missing " + (r.missing.join(", ") || "files") + ")", "pill-warn");
    }
  } catch (_e) {
    paintPdkPill("PDK: check failed", "pill-fail");
  }
  await renderPreflight();
  paintRunButton();
}

export async function populatePdkPicker() {
  try {
    const pdks = await api.pdks();
    const sel = document.getElementById("pdk-select");
    if (!sel) return;
    sel.innerHTML = "";
    sel.appendChild((() => {
      const o = document.createElement("option");
      o.value = "";
      o.textContent = "Select a PDK";
      return o;
    })());

    const supportedPdks = pdks.filter((p) => p.supported !== false);
    const unsupportedPdks = pdks.filter((p) => p.supported === false);

    if (supportedPdks.length) {
      const g1 = document.createElement("optgroup");
      g1.label = "Supported PDKs";
      for (const p of supportedPdks) {
        const o = document.createElement("option");
        o.value = p.name;
        o.textContent = p.name + (p.ready ? "" : " (no libs)");
        g1.appendChild(o);
      }
      sel.appendChild(g1);
    }

    if (unsupportedPdks.length) {
      const g2 = document.createElement("optgroup");
      g2.label = "Installed (Unsupported by LibreLane flow)";
      for (const p of unsupportedPdks) {
        const o = document.createElement("option");
        o.value = p.name;
        o.textContent = p.name + " (unsupported flow target)";
        g2.appendChild(o);
      }
      sel.appendChild(g2);
    }

    // Restore the project PDK or previously-used PDK if it's still installed.
    // Respect the project's explicit PDK before recent UI preferences.
    const projectPdk = state.projectConfig?.PDK || state.config?.PDK || "";
    const wantPdk = (projectPdk && Array.from(sel.options).some((o) => o.value === projectPdk))
      ? projectPdk
      : safeStorage.get("ll.recentPdk", "");
    if (wantPdk && Array.from(sel.options).some((o) => o.value === wantPdk)) {
      sel.value = wantPdk;
      await onPdkSelected();   // repopulates SCLs + restores the SCL + readiness
    } else if (supportedPdks.length) {
      sel.value = supportedPdks[0].name;
      await onPdkSelected();
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
  const pf = lastPreflight();
  const isReady = !!(state.designDir && pf && pf.ready);
  const canRun = !!state.designDir;

  if (g && !running) {
    g.disabled = !canRun;
    g.classList.toggle("topbar-run-ready", isReady);
    g.title = isReady
      ? "Start the flow, or stop a running one, from any tab"
      : !state.designDir
        ? "Load a design folder first"
        : "Preflight has issues: " + ((pf?.blockers || []).join("; ") || "check setup");
  }
  if (!b) return;

  b.disabled = !canRun;
  b.classList.toggle("btn-cta-ready", isReady);
  b.classList.toggle("btn-cta-unready", !isReady);

  const hintEl = b.querySelector(".hint");
  if (!state.designDir) {
    b.title = "Pick or load a design folder first";
    if (hintEl) hintEl.textContent = "Pick or load a design folder first.";
  } else if (!isReady) {
    const blk = (pf?.blockers || []).join("; ");
    b.title = blk ? "Cannot run yet: " + blk : "Checking setup readiness…";
    if (hintEl) hintEl.textContent = blk ? "Not ready: " + blk : "Checking prerequisites…";
  } else {
    b.title = "All checks passed. Ready to run flow.";
    if (hintEl) hintEl.textContent = "Compiles your HDL → GDSII. Takes 5–60 minutes.";
  }
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
  // Optional extras.
  const sources = (state.selectedFiles || []).filter(Boolean);
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
    if (c) c.disabled = false;
    if (c2) c2.disabled = false;
    if (g) { g.disabled = false; g.innerHTML = icon("stop", { size: 15 }) + "<span>Stop</span>"; g.classList.add("is-stop"); }
    pill?.classList.remove("pill-pending");
    pill?.classList.add("pill-running");
    if (pill) pill.textContent = "running";
  } else {
    if (b) b.disabled = !state.designDir;
    if (c) c.disabled = true;
    if (c2) c2.disabled = true;
    if (g) { g.disabled = !state.designDir; g.innerHTML = icon("play", { size: 15 }) + "<span>Run</span>"; g.classList.remove("is-stop"); }
    pill?.classList.add("pill-pending");
    pill?.classList.remove("pill-running");
    if (pill) pill.textContent = "idle";
  }
}

export async function showOnboarding() {
  const { customDialog } = await import("./dialog.js");
  const html =
    "<div class='onboard-guide'>" +
    "<p style='margin-top:0;font-size:var(--t-md);color:var(--text);line-height:1.5;'>" +
    "Navigate your first silicon hardening flow with these interactive steps:" +
    "</p>" +
    "<div style='display:grid;gap:var(--s-3);margin:var(--s-4) 0;'>" +
    "<div style='background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:var(--s-3);display:flex;align-items:center;justify-content:space-between;gap:var(--s-3);'>" +
    "<div><strong style='color:var(--text-strong);display:block;'>1. Design HDL Folder</strong><span style='color:var(--text-muted);font-size:var(--t-sm);'>Load the built-in SPM multiplier or browse your Verilog folder.</span></div>" +
    "<button class='btn btn-ghost btn-sm' id='ob-act-spm'>Use SPM</button>" +
    "</div>" +
    "<div style='background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:var(--s-3);display:flex;align-items:center;justify-content:space-between;gap:var(--s-3);'>" +
    "<div><strong style='color:var(--text-strong);display:block;'>2. Process &amp; Cell Library (PDK)</strong><span style='color:var(--text-muted);font-size:var(--t-sm);'>Select SkyWater 130nm or GlobalFoundries 180nm.</span></div>" +
    "<button class='btn btn-ghost btn-sm' id='ob-act-pdk'>Jump to PDK</button>" +
    "</div>" +
    "<div style='background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:var(--s-3);display:flex;align-items:center;justify-content:space-between;gap:var(--s-3);'>" +
    "<div><strong style='color:var(--text-strong);display:block;'>3. Preflight &amp; Run</strong><span style='color:var(--text-muted);font-size:var(--t-sm);'>Verify tools, PDK, and sources before launching synthesis.</span></div>" +
    "<button class='btn btn-ghost btn-sm' id='ob-act-pf'>Check setup</button>" +
    "</div>" +
    "</div>" +
    "</div>";

  const res = await customDialog({
    title: "Guided Tour: RTL to GDSII Flow",
    bodyHtml: html,
    buttons: [
      { label: "Load SPM Example", value: "spm", cls: "btn-primary" },
      { label: "Browse Folder…", value: "browse", cls: "btn-ghost" },
      { label: "Close", value: "close", cls: "btn-ghost" },
    ],
    onMount: (back, close) => {
      back.querySelector("#ob-act-spm")?.addEventListener("click", () => close("spm"));
      back.querySelector("#ob-act-pdk")?.addEventListener("click", () => close("pdk"));
      back.querySelector("#ob-act-pf")?.addEventListener("click", () => close("preflight"));
    },
  });

  if (res === "spm") {
    await onLoadSpmExample();
  } else if (res === "pdk") {
    document.getElementById("setup-pdk")?.scrollIntoView({ behavior: "smooth" });
    document.getElementById("pdk-select")?.focus();
  } else if (res === "preflight") {
    document.getElementById("setup-preflight")?.scrollIntoView({ behavior: "smooth" });
    renderPreflight();
  } else if (res === "browse") {
    document.getElementById("btn-browse-folder")?.click();
  } else {
    document.getElementById("design-dir-input")?.focus();
  }
}

