// app.js — front-end entry. Bootstraps everything.

import { api, sse, fmt } from "./modules/api.js";
import { state } from "./modules/state.js";
import { setupTabs, activate } from "./modules/tabs.js";
import { setupSetup, populatePdkPicker, paintRunning, paintDesignPill, paintPdkPill } from "./modules/setup.js";
import { setupTheme, toggleTheme } from "./modules/theme.js";
import { setupHotkeys } from "./modules/hotkeys.js";
import { setupDensity, toggleDensity } from "./modules/density.js";
import { setupPalette, openPalette } from "./modules/palette.js";
import { setupRunMode, applyServerDefault } from "./modules/runmode.js";
import { renderConfig } from "./modules/config.js";
import { renderPipeline } from "./modules/pipeline.js";
import { renderRuntimeline, noteStepEvent, resetTimeline, notePhase } from "./modules/runtimeline.js";
import { renderRuns } from "./modules/runs.js";
import { renderPreview } from "./modules/preview.js";
import { renderTools, updatePullProgress, finishPull } from "./modules/tools.js";
import { renderAdvisor } from "./modules/advisor.js";
import { renderTimingAdvisor } from "./modules/timingAdvisor.js";
import { renderAnalytics, renderAnalyticsFull } from "./modules/analytics.js";
import { renderLogs, setupLogs } from "./modules/logs.js";
import { setupStepOutput } from "./modules/stepoutput.js";
import { populateReportsList, setupViolations } from "./modules/violations.js";
import { help } from "./modules/help.js";
import { toast } from "./modules/toast.js";
import { setupTier } from "./modules/tier.js";
import { setupWizard } from "./modules/wizard.js";
import { setupLearn } from "./modules/learn.js";
import { loadEnabledPlugins } from "./modules/plugins.js";
import { icon } from "./modules/icons.js";
import { setupFullscreen } from "./modules/fullscreen.js";

// Map each side-nav tab to a line-style SVG icon (replaces per-OS emoji glyphs).
const TAB_ICONS = {
  setup: "folder", pipeline: "flow", runs: "clock", preview: "image",
  ide: "code", tools: "tools", analytics: "chart", verify: "check", compare: "diff",
  dse: "beaker", layout: "grid", cells: "layers", plugins: "plug", manual: "command",
};
function paintNavIcons() {
  document.querySelectorAll(".side-tab").forEach((tab) => {
    const name = TAB_ICONS[tab.dataset.tab];
    const ico = tab.querySelector(".ico");
    if (ico) {
      // Decorative — the .label is the accessible name. Swap the emoji
      // placeholder for the theme-correct SVG (the placeholder is rendered at
      // font-size:0 in CSS so it never visibly flashes before this runs).
      ico.setAttribute("aria-hidden", "true");
      if (name) ico.innerHTML = icon(name, { size: 18 });
    }
  });
  document.body.classList.add("nav-painted");
}

async function boot() {
  const splash = document.getElementById("splash");
  const splashStatus = document.getElementById("splash-status");
  const setStatus = (msg) => {
    if (splashStatus) splashStatus.textContent = msg;
  };
  function failUI(err) {
    setStatus("boot failed");
    if (splash) {
      const errEl = document.createElement("div");
      errEl.className = "splash-error";
      errEl.innerHTML =
        "<h3>Could not boot LanEx</h3>" +
        "<pre style='white-space:pre-wrap;margin:0;font-family:var(--mono);font-size:11px;color:var(--text);'>" +
        fmt.escape(err.stack || String(err)) +
        "</pre>";
      const inner = splash.querySelector(".splash-inner");
      if (inner) inner.appendChild(errEl);
      if (inner) inner.style.maxHeight = "90vh";
      if (inner) inner.style.overflow = "auto";
    }
    console.error(err);
    toast.show("Boot failed: " + String(err), "error");
  }

  try {
    setStatus("setup…");
    setupTabs();
    setupTheme();
    setupDensity();
    setupPalette();
    setupRunMode();
    setupLogs();
    setupStepOutput();
    setupSetup();
    setupHotkeys();
    setupViolations();
    setupTier();
    setupWizard();
    setupLearn();
    setupFullscreen();
    paintNavIcons();
    help.bind();
    document.getElementById("ide-popout")?.addEventListener("click", () => {
      const dd = state.designDir ? "?design_dir=" + encodeURIComponent(state.designDir) : "";
      window.open("/ide" + dd, "_blank", "noopener");
    });
    document.getElementById("btn-learn")?.addEventListener("click", () =>
      import("./modules/learn.js").then((m) => m.openLearnIndex()));
    document.getElementById("btn-view2d")?.addEventListener("click", () =>
      import("./modules/viewer2d.js").then((m) => m.renderViewer2d(layoutRunTag())));
    document.getElementById("btn-view3d")?.addEventListener("click", () =>
      import("./modules/viewer3d.js").then((m) => m.renderViewer3d(layoutRunTag())));
    document.getElementById("tools-icon")?.addEventListener("click", () => {
      document.querySelector('.side-tab[data-tab="tools"]')?.click();
    });
    document.getElementById("palette-btn")?.addEventListener("click", openPalette);
    document.getElementById("theme-btn")?.addEventListener("click", toggleTheme);
    document.getElementById("density-btn")?.addEventListener("click", toggleDensity);
    // The "Parse" button is wired once by setupViolations() (smart kind
    // detection). The old inline handler here double-bound it — removed.

    try {
      const h = await api.health();
      if (h && h.default_run_mode) applyServerDefault(h.default_run_mode);
    } catch (_) {}

    setStatus("loading flow metadata…");
    // Boot metadata in parallel.
    const [steps, vars, formats, flows, pdks] = await Promise.all([
      api.steps(),
      api.variables(),
      api.designFormats(),
      api.flows(),
      api.pdks(),
    ]);
    state.steps = steps;
    state.variables = vars;
    state.designFormats = formats;
    state.flows = flows;
    state.pdks = pdks;
    state.selectedPdk = (state.pdks[0] && state.pdks[0].name) || "";

    await populatePdkPicker();
    setStatus("rendering panels…");
    renderConfig();
    renderPipeline();
    renderRuntimeline();
    renderAnalytics();
    renderTimingAdvisor();

    // Subscribe to the event stream. SSE is optional; don't block boot.
    try {
      sse.open();
    } catch (_e) { /* ignore */ }
    try {
      sse.on(handle);
    } catch (_e) { /* ignore */ }
    renderLogs.setStepsInfo(state.steps);

    if (state.steps.length) {
      state.selectedStepId = state.steps[0].id;
      renderPipeline();
    }

    // Adopt a design directory so the GUI opens ready to run AND the Runs tab
    // shows that design's history immediately. Prefer one the server already
    // knows (e.g. `librelane-gui --design-dir`); otherwise re-adopt the most
    // recent design the user opened (persisted in localStorage `ll.recentDesigns`).
    // Runs are scoped to the active design dir server-side, so without this the
    // Runs tab stays empty until the user re-picks a source.
    try {
      let adopt = null;
      const dd = await api.designDir();
      if (dd && dd.design_dir) {
        adopt = dd.design_dir;
      } else {
        try {
          const recent = JSON.parse(localStorage.getItem("ll.recentDesigns") || "[]").filter(Boolean);
          if (recent.length) {
            // Tell the server about it before adopting (it's not active yet).
            const res = await api.setDesignDir(recent[0]);
            adopt = res && res.design_dir;
          }
        } catch (_e) { /* stale/removed recent dir — ignore */ }
      }
      if (adopt) {
        const input = document.getElementById("design-dir-input");
        if (input) input.value = adopt;
        // Boot adoption is implicit: scope Runs/Preview but keep the Setup file
        // selector hidden (history/recents stay shown) until the user explicitly
        // loads a design. See adoptDesignDir({explicit}).
        const serverKnew = !!(dd && dd.design_dir);
        await import("./modules/setup.js").then((m) => m.adoptDesignDir(adopt, { explicit: serverKnew }));
      }
    } catch (_e) {}

    // Adopt the most recent run as the default selection so every run-scoped
    // view (Preview, Verify, Analytics, Layout viewers, step output) works
    // without first clicking "Open" on the Runs tab.
    try {
      state.runs = await api.runs(state.designDir);
      if (!state.selectedRunTag && state.runs && state.runs.length) {
        state.selectedRunTag = state.runs[0].tag;
      }
    } catch (_e) {}

    // Always open on Setup (the design/PDK/run entry point), regardless of which
    // tab was last visited — boot should land the user at the start of the flow.
    activate("setup");

    // Hide splash and reveal the app.
    setStatus("ready");
    if (splash) splash.classList.add("hide");
    document.getElementById("app").style.display = "";

    setTimeout(showOnboardingOnce, 600);
    // Load any enabled front-end plugins through the SDK surface (best-effort).
    loadEnabledPlugins();
  } catch (err) {
    failUI(err);
  }
}

// Isolate one view's render from another: a throw in renderPipeline must not
// skip renderRuntimeline/renderRuns for the same event. (The SSE loop itself is
// already protected by api._broadcast's per-handler try/catch.)
function R(label, fn) {
  try { fn(); } catch (e) { console.error("render:" + label, e); }
}

function handle(ev) {
  if (!ev || !ev.type) return;

  if (ev.type === "info") {
    if (Array.isArray(ev.step_graph)) {
      state.pipeline = ev.step_graph;
      state.status.running = true;
      // Reset per-step statuses to the fresh graph (all pending). Without this
      // the timeline + pipeline kept the PREVIOUS run's statuses (all "done")
      // until each new step event arrived — so a fresh run (especially a DSE
      // config, which reuses the runner back-to-back) looked like it was showing
      // the previous run's progress. Seeding pending here fixes that immediately.
      state.stepStatuses = {};
      for (const s of ev.step_graph) state.stepStatuses[s.id] = s.status || "pending";
      resetTimeline();        // a fresh run is starting; clear old step timings
      R("pipeline", renderPipeline);
      R("runtimeline", renderRuntimeline);
      R("runs", renderRuns);  // surface the just-created run dir immediately
      // Land the user on the live Pipeline view (graph + timeline) and focus
      // the log pane, so they immediately see steps light up + terminal output.
      document.querySelector('.side-tab[data-tab="pipeline"]')?.click();
      document.querySelector('.side-pane-tab[data-itab="logs"]')?.click();
    }
    if (ev.message) renderLogs.append(ev);
  } else if (ev.type === "phase") {
    // Container pre-step milestone — show the "preparing" hero with a timer.
    state.status.running = true;
    notePhase(ev.label || "Preparing…");
    if (ev.label) renderLogs.append({ type: "log", payload: { message: "• " + ev.label } });
  } else if (ev.type === "log") {
    renderLogs.append(ev);
  } else if (ev.type === "dse_config_started") {
    // A new DSE config is starting: clear the previous config's step statuses
    // immediately so the pipeline/timeline don't keep showing it as "done" while
    // the next container spins up (its step_graph arrives a few seconds later).
    for (const p of (state.pipeline || [])) state.stepStatuses[p.id] = "pending";
    state.status.running = true;
    resetTimeline();
    notePhase("DSE config " + (((ev.index || 0) + 1)) + "/" + (ev.total || "?") + " — preparing…");
    renderPipeline();
    renderRuntimeline();
  } else if (ev.type === "manual_started" || ev.type === "manual_line" || ev.type === "manual_done") {
    import("./modules/manual.js").then((m) => m.onManualEvent(ev));
  } else if (ev.type === "installer_line" || ev.type === "installer_started" || ev.type === "installer_done" || ev.type === "installer_error" || ev.type === "installer_info") {
    if (ev.line) {
      renderLogs.append({ type: "installer_line", payload: { message: ev.line } });
    }
    const isImagePull = ev.key === "container:image";
    if (isImagePull && ev.type === "installer_line") {
      updatePullProgress(ev.line);   // heartbeat on the runtime card
    }
    // A privileged install needs a password: sudo prompts in the terminal the
    // GUI was launched from (or a pkexec dialog). The browser can't host that
    // prompt, so make the "go enter your password" message impossible to miss —
    // a persistent banner plus a toast — otherwise the install silently waits.
    if (ev.type === "installer_info" && ev.needs_password && ev.message) {
      showPasswordBanner(ev.message);
      toast.show(ev.message, "warn");
    }
    // Surface non-pipeline streamed output (tool/PDK/GDS3D installs) in a
    // closeable right-side drawer, since these can be triggered from any tab.
    if (!isImagePull) {
      import("./modules/logdrawer.js").then((d) => {
        if (ev.type === "installer_started") { d.openDrawer("Installing " + (ev.key || "tool") + "…"); }
        if (ev.type === "installer_info" && ev.message) d.appendDrawer(ev.message);
        if (ev.line) d.appendDrawer(ev.line);
        if (ev.type === "installer_done") d.appendDrawer("Finished (exit " + (ev.rc ?? 0) + ")");
        if (ev.type === "installer_error") d.appendDrawer((ev.message || ev.error || "install failed"));
      });
    }
    if (ev.type === "installer_done" || ev.type === "installer_error") clearPasswordBanner();
    if (ev.type === "installer_done" || ev.type === "installer_error") {
      if (ev.key) delete state.installJobs[ev.key];
      if (isImagePull) {
        // The pull owns the runtime card; finishPull re-probes + reports.
        finishPull(ev.type === "installer_done" ? (ev.rc ?? 0) : (typeof ev.rc === "number" ? ev.rc : 1));
      } else {
        if (ev.type === "installer_done" && ev.rc !== undefined) {
          logInstallerLine("→ installer rc=" + ev.rc + " (recheck Tools tab)");
        }
        renderTools();
      }
    }
  } else if (ev.type === "progress") {
    state.runProgress = {
      done: ev.done || 0, total: ev.total || 0, current: ev.current || "",
      eta_seconds: (ev.eta_seconds === undefined ? null : ev.eta_seconds),
      elapsed_seconds: (ev.elapsed_seconds === undefined ? null : ev.elapsed_seconds),
    };
    setRunProgress(ev.done || 0, ev.total || 0, ev.current || "");
    R("runtimeline", renderRuntimeline);
  } else if (
    ev.type === "step_started" ||
    ev.type === "step_done" ||
    ev.type === "step_skipped" ||
    ev.type === "step_failed"
  ) {
    const id = ev.step_id || ev.id || ev.payload?.step_id;
    const statusMap = {
      step_started: "running",
      step_done: "done",
      step_skipped: "skipped",
      step_failed: "failed",
    };
    if (id) {
      state.stepStatuses[id] = statusMap[ev.type];
      noteStepEvent(ev.type, id);
      // Drop a navigable divider into the Live Logs at each step's start so the
      // log can later be jumped to that tool's instantiation point (issue #8b).
      if (ev.type === "step_started") {
        renderLogs.markStep(id, ev.long_name || ev.label || ev.payload?.long_name);
      }
      R("pipeline", renderPipeline);
      R("runtimeline", renderRuntimeline);
    }
    if (ev.type === "step_failed") {
      toast.show("Step failed: " + (ev.message || id || "Unknown error"), "error");
      renderAdvisor.pushFromAlert({ payload: { message: ev.message || "" } });
    }
  } else if (ev.type === "flow_done") {
    // Reset run state + re-enable the Run button FIRST, before any rendering.
    // A throw in one of the renders below must never leave the button disabled
    // (that is exactly what made "a failed run blocks the next run": a render
    // error on flow_done skipped paintRunning(false), wedging the UI).
    state.status.running = false;
    paintRunning(false);
    document.dispatchEvent(new CustomEvent("g:flow_done", { detail: ev }));
    const pill = document.getElementById("run-pill");
    if (pill) {
      pill.classList.remove("pill-running", "pill-pass", "pill-fail");
      if (ev.error) {
        pill.classList.add("pill-fail");
        pill.textContent = "failed";
        toast.show("Flow failed: " + ev.error, "error");
      } else if (ev.cancelled) {
        pill.classList.add("pill-pending");
        pill.textContent = "cancelled";
        toast.show("Flow cancelled", "warn");
      } else {
        pill.classList.add("pill-pass");
        pill.textContent = "done";
        toast.show("Flow completed — GDS is on the Preview tab", "success");
      }
    }
    try {
      // On a clean finish, make sure every non-failed step shows done — guards
      // against a final step_done that never arrived (bar would stick at 99%).
      if (!ev.error && !ev.cancelled) {
        const graph = state.pipeline || [];
        graph.forEach((p) => {
          if (state.stepStatuses[p.id] !== "failed") state.stepStatuses[p.id] = "done";
        });
        const total = graph.length || state.runProgress?.total || 0;
        if (total) state.runProgress = { done: total, total, current: "" };
      }
      renderAdvisorAndRefreshMetrics();
      renderRuns();
      renderPipeline();
      renderRuntimeline();
      renderPreview();
    } catch (e) {
      console.error("flow_done render", e);
    }
  }
}

async function renderAdvisorAndRefreshMetrics() {
  try {
    state.runs = await api.runs();
    const target = state.selectedRunTag || (state.runs[0] && state.runs[0].tag);
    if (!target) return;
    const view = await api.run(target);
    state.metrics = view.metrics?.values || {};
    populateReportsList(state.designDir, target);
    import("./modules/analytics.js").then((mod) => mod.renderAnalytics());
    renderTimingAdvisor();
  } catch (_e) {}
}

// The run tag chosen on the Layout tab (falls back to the global selection).
function layoutRunTag() {
  const sel = document.getElementById("layout-run");
  return (sel && sel.value) || state.selectedRunTag || "";
}

// Fill the Layout tab's run dropdown, default to the most recent, and render the
// 2D view for it — so the viewers work without first clicking Open on a run.
async function populateLayoutRuns() {
  const sel = document.getElementById("layout-run");
  if (!sel) return;
  const { gatherRunsScoped, getRunScope, runOptionsHtml, scopeToggleHtml, wireScopeToggle, ensureActiveDesignFor } =
    await import("./modules/runscope.js");
  let runs = [];
  try { runs = await gatherRunsScoped(); } catch (_e) {}
  if (getRunScope() === "design") state.runs = runs;
  const idx = {};
  for (const r of runs) idx[r.tag] = r;
  sel._idx = idx;   // the once-wired change listener reads the latest index here
  // Scope toggle next to the run select (shared global pref).
  if (!sel.parentNode.querySelector("#layout-run-scope")) {
    sel.insertAdjacentHTML("afterend", " " + scopeToggleHtml("layout-run-scope"));
    wireScopeToggle("layout-run-scope", () => populateLayoutRuns());
  }
  const prev = sel.value || state.selectedRunTag;
  sel.innerHTML = runs.length
    ? runOptionsHtml(runs, prev, (s) => fmt.escape(s))
    : "<option value=''>(no runs yet — run the flow first)</option>";
  if (prev && idx[prev]) sel.value = prev;
  else if (runs.length) sel.value = runs[0].tag;
  if (!sel._wired) {
    sel._wired = true;
    sel.addEventListener("change", async () => {
      await ensureActiveDesignFor((sel._idx || {})[sel.value]);
      state.selectedRunTag = sel.value;
      import("./modules/viewer2d.js").then((m) => m.renderViewer2d(sel.value));
      renderLayoutTools(sel.value);
    });
  }
  if (sel.value) {
    await ensureActiveDesignFor(idx[sel.value]);
    state.selectedRunTag = state.selectedRunTag || sel.value;
    import("./modules/viewer2d.js").then((m) => m.renderViewer2d(sel.value));
  }
  renderLayoutTools(sel.value);
}

// Top-level unified tool row on the Layout bar: ONE button per tool (KLayout /
// Magic / GDS3D / OpenROAD), each routing container→host→install. GDS3D is no
// longer buried in the 3D sub-view, and KLayout/Magic aren't listed three times.
async function renderLayoutTools(tag) {
  const host = document.getElementById("layout-tools");
  if (!host) return;
  const { renderLayoutTools: render } = await import("./modules/layouttools.js");
  await render(host, tag);
}

function setRunProgress(done, total, current) {
  const bar = document.getElementById("overall-progress");
  if (!bar) return;
  if (!total) {
    bar.textContent = "";
    return;
  }
  const pct = Math.round((done / total) * 100);
  bar.textContent = "step " + done + "/" + total + ":" + (current ? " " + current : "") + " (" + pct + "%)";
}

function showOnboardingOnce() {
  try {
    if (sessionStorage.getItem("ll.onboarded") === "1") return;
  } catch (_) {}
  const o = document.getElementById("onboard");
  if (!o) return;
  o.hidden = false;
  document.getElementById("onboard-close")?.addEventListener("click", dismiss);
  document.getElementById("onboard-done")?.addEventListener("click", dismiss);
}

function dismiss() {
  const o = document.getElementById("onboard");
  if (o) o.hidden = true;
  try { sessionStorage.setItem("ll.onboarded", "1"); } catch (_) {}
}

function logInstallerLine(line) {
  renderLogs.append({ type: "installer_line", payload: { message: line } });
}

// A privileged install is waiting for a password it can only read from the
// launching terminal (or a system dialog). Show a fixed, dismissable banner so
// the user knows to act — the alternative is an install that looks frozen.
function showPasswordBanner(message) {
  let el = document.getElementById("pw-banner");
  if (!el) {
    el = document.createElement("div");
    el.id = "pw-banner";
    el.className = "pw-banner";
    el.setAttribute("role", "alert");
    document.body.appendChild(el);
  }
  el.innerHTML = "";
  const msg = document.createElement("span");
  msg.textContent = message;
  const close = document.createElement("button");
  close.className = "pw-banner-close";
  close.setAttribute("aria-label", "Dismiss");
  close.textContent = "Dismiss";
  close.addEventListener("click", clearPasswordBanner);
  el.appendChild(msg);
  el.appendChild(close);
  el.hidden = false;
}

function clearPasswordBanner() {
  const el = document.getElementById("pw-banner");
  if (el) el.hidden = true;
}

window.addEventListener("DOMContentLoaded", () => {
  // Boot is responsible for its own failure UI (writes into #splash).
  boot();
});

// Expose tools lazy-load — clicking the Tools tab will fetch fresh data.
// A per-tab run picker switched the active design to view a cross-design run:
// reflect it in the topbar pill so the user (and the global Run button) know
// which design is active now.
document.addEventListener("g:active_design_changed", (e) => {
  const dir = e.detail?.dir || "";
  const label = dir.split(/[/\\]/).filter(Boolean).pop() || dir;
  if (label) paintDesignPill(label);
});

document.addEventListener("g:tab_activated", (e) => {
  if (e.detail?.tab === "tools") {
    import("./modules/tools.js").then((m) => m.renderTools());
    // Add-ons / plugins now live inside the Tools tab.
    import("./modules/plugins.js").then((m) => m.renderPlugins());
  }
  if (e.detail?.tab === "analytics") {
    import("./modules/analytics.js").then((m) => m.renderAnalyticsFull());
    import("./modules/compare.js").then((m) => m.renderCompare());
    // The "Advisor & reports" card (failure advisor + DRC/LVS report parser)
    // used to populate only on flow_done, so after a reload it sat empty. Refill
    // it for the currently-selected run whenever Analytics is opened.
    const tag = state.selectedRunTag || (state.runs && state.runs[0] && state.runs[0].tag);
    if (tag && state.designDir) populateReportsList(state.designDir, tag);
    renderTimingAdvisor();
  }
});
// Lazy-load tabs that have heavy work on first display.
document.querySelectorAll(".side-tab").forEach((t) => {
  t.addEventListener("click", () => {
    const name = t.dataset.tab;
    document.dispatchEvent(new CustomEvent("g:tab_activated", { detail: { tab: name } }));
    if (name === "runs") renderRuns();
    if (name === "preview") renderPreview();
    if (name === "ide") import("./modules/ide/main.js").then((m) =>
      m.initIde({ designDir: state.designDir, runMode: state.runMode }));
    if (name === "layout") populateLayoutRuns();
    // tools + analytics are rendered by the g:tab_activated listener above; don't
    // double-render them here.
    if (name === "verify") import("./modules/verify.js").then((m) => m.renderVerify());
    if (name === "dse") import("./modules/dse.js").then((m) => m.renderDse());
    if (name === "cells") {
      import("./modules/custommacros.js").then((m) => m.renderCustomMacros());
      import("./modules/customcells.js").then((m) => m.renderCustomCells());
      import("./modules/cells.js").then((m) => m.renderCells());
    }
    if (name === "manual") import("./modules/manual.js").then((m) => m.renderManual());
  });
});
