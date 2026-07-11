// app.js — front-end entry. Bootstraps everything.

import { api, sse, fmt } from "./modules/api.js";
import { state, safeStorage } from "./modules/state.js";
import { setupTabs, activate } from "./modules/tabs.js";
import { setupSetup, populatePdkPicker, paintRunning, paintDesignPill, paintPdkPill, paintOnboardChecklist } from "./modules/setup.js";
import { setupTheme, toggleTheme } from "./modules/theme.js";
import { setupHotkeys } from "./modules/hotkeys.js";
import { setupDensity, toggleDensity } from "./modules/density.js";
import { setupZoom } from "./modules/zoom.js";
import { setupPalette, openPalette } from "./modules/palette.js";
import { setupRunMode } from "./modules/runmode.js";
import { renderConfig } from "./modules/config.js";
import { renderRuntimeline, noteStepEvent, resetTimeline, notePhase } from "./modules/runtimeline.js";
import { renderRuns } from "./modules/runs.js";
import { renderPreview } from "./modules/preview.js";
import { renderTools, updatePullProgress, finishPull } from "./modules/tools.js";
import { renderAdvisor } from "./modules/advisor.js";
import { renderTimingAdvisor } from "./modules/timingAdvisor.js";
import { renderAnalyticsFull } from "./modules/analytics.js";
import { renderLogs, setupLogs } from "./modules/logs.js";
import { setupStepOutput } from "./modules/stepoutput.js";
import { populateReportsList, setupViolations } from "./modules/violations.js";
import { help } from "./modules/help.js";
import { toast } from "./modules/toast.js";
import { setupWizard } from "./modules/wizard.js";
import { setupLearn } from "./modules/learn.js";
import { icon } from "./modules/icons.js";
import { setupFullscreen } from "./modules/fullscreen.js";
import { showAbout } from "./modules/about.js";
import { setupTooltips } from "./modules/tooltip.js";

// Map each side-nav tab to a line-style SVG icon (replaces per-OS emoji glyphs).
const TAB_ICONS = {
  setup: "folder", pipeline: "flow", runs: "clock", preview: "image",
  ide: "code", tools: "tools", analytics: "chart", verify: "check",
  dse: "beaker", layout: "grid", cells: "layers", manual: "command",
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
    // Hygiene: the Simple/Pro tier system was removed — drop its orphaned keys.
    safeStorage.remove("ll.tier");
    safeStorage.remove("ll.onboarded");
    setupTabs();
    setupTheme();
    setupDensity();
    setupZoom();
    // The standalone app window has no browser reload button; F5/Ctrl+R still
    // work, but give staleness an obvious escape hatch.
    document.getElementById("reload-btn")?.addEventListener("click", () => location.reload());
    setupPalette();
    setupRunMode();
    setupLogs();
    setupStepOutput();
    setupSetup();
    setupHotkeys();
    setupViolations();
    setupWizard();
    setupLearn();
    setupFullscreen();
    setupTooltips();
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
    // Help-dialog quick links + the topbar Legal button (static markup; wired once).
    document.getElementById("help-license")?.addEventListener("click", showAbout);
    document.getElementById("legal-btn")?.addEventListener("click", showAbout);
    // The "Parse" button is wired once by setupViolations() (smart kind
    // detection). The old inline handler here double-bound it — removed.

    try {
      const health = await api.health();
      maybeWarnCompat(health && health.compat);
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
    renderRuntimeline();
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

    paintOnboardChecklist();  // E5.1 — reflect the real design/PDK/run state now

    // Always open on Setup (the design/PDK/run entry point), regardless of which
    // tab was last visited — boot should land the user at the start of the flow.
    activate("setup");

    // Hide splash and reveal the app.
    setStatus("ready");
    if (splash) splash.classList.add("hide");
    document.getElementById("app").style.display = "";
  } catch (err) {
    failUI(err);
  }
}

// Isolate one view's render from another: a throw in renderRuntimeline must not
// skip renderRuns for the same event. (The SSE loop itself is
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
      // the timeline kept the PREVIOUS run's statuses (all "done")
      // until each new step event arrived — so a fresh run (especially a DSE
      // config, which reuses the runner back-to-back) looked like it was showing
      // the previous run's progress. Seeding pending here fixes that immediately.
      state.stepStatuses = {};
      for (const s of ev.step_graph) state.stepStatuses[s.id] = s.status || "pending";
      resetTimeline();        // a fresh run is starting; clear old step timings
      R("runtimeline", renderRuntimeline);
      R("runs", renderRuns);  // surface the just-created run dir immediately
      // Land the user on the live Pipeline view (timeline) and focus
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
    renderRuntimeline();
  } else if (ev.type === "manual_started" || ev.type === "manual_line" || ev.type === "manual_done") {
    import("./modules/manual.js").then((m) => m.onManualEvent(ev));
  } else if (ev.type === "installer_result") {
    // Final outcome of an async tool install (the POST returned "started"
    // immediately; this event carries the real result). tools.js toasts it,
    // logs the guidance, chains the engine→image pull, and re-probes the tab.
    import("./modules/tools.js").then((m) => m.onInstallerResult && m.onInstallerResult(ev));
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
    // A root-owned ciel store blocks the PDK download and can't self-heal. Offer
    // a one-click fix (escalated `chown` scoped to ~/.ciel) beside the message.
    if (ev.type === "installer_info" && ev.needs_root && ev.fix) {
      showActionBanner(ev.message, ev.fix.label || "Fix permissions", () => {
        clearActionBanner();
        api.fixPdkPermissions().catch((e) => toast.show(e.message || "fix failed", "err"));
      });
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
        // A finished PDK install changes what Setup can offer — re-fetch the
        // PDK list and repopulate the picker so the new PDK appears without a
        // manual page reload (the app window has no browser refresh button).
        if (ev.type === "installer_done" && typeof ev.key === "string" && ev.key.startsWith("pdk:")) {
          api.pdks().then((p) => { state.pdks = p; }).catch(() => {});
          populatePdkPicker().catch(() => {});
        }
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
      renderRuntimeline();
      renderPreview();
      paintOnboardChecklist();
      if (!ev.error && !ev.cancelled) {
        maybeShowPostRunPanel();
        import("./modules/watch.js").then((m) => m.checkAfterRun()).catch(() => {});
      }
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
  const ico = document.createElement("span");
  ico.className = "pw-banner-ico";
  ico.innerHTML = icon("alert", { size: 16 });
  const msg = document.createElement("span");
  msg.textContent = message;
  const close = document.createElement("button");
  close.className = "pw-banner-close";
  close.setAttribute("aria-label", "Dismiss");
  close.textContent = "Dismiss";
  close.addEventListener("click", clearPasswordBanner);
  el.appendChild(ico);
  el.appendChild(msg);
  el.appendChild(close);
  el.hidden = false;
}

function clearPasswordBanner() {
  const el = document.getElementById("pw-banner");
  if (el) el.hidden = true;
}

// Like the password banner, but with an action button (e.g. "Fix permissions"
// for a root-owned ciel store). Reuses the .pw-banner chrome; separate element
// so an installer_error's clearPasswordBanner() doesn't wipe it.
function showActionBanner(message, actionLabel, onAction) {
  let el = document.getElementById("action-banner");
  if (!el) {
    el = document.createElement("div");
    el.id = "action-banner";
    el.className = "pw-banner";
    el.setAttribute("role", "alert");
    document.body.appendChild(el);
  }
  el.innerHTML = "";
  const ico = document.createElement("span");
  ico.className = "pw-banner-ico";
  ico.innerHTML = icon("alert", { size: 16 });
  const msg = document.createElement("span");
  msg.textContent = message;
  const act = document.createElement("button");
  act.className = "pw-banner-close";
  act.textContent = actionLabel;
  act.addEventListener("click", () => { if (onAction) onAction(); });
  const close = document.createElement("button");
  close.className = "pw-banner-close";
  close.setAttribute("aria-label", "Dismiss");
  close.textContent = "Dismiss";
  close.addEventListener("click", clearActionBanner);
  el.appendChild(ico);
  el.appendChild(msg);
  el.appendChild(act);
  el.appendChild(close);
  el.hidden = false;
}

function clearActionBanner() {
  const el = document.getElementById("action-banner");
  if (el) el.hidden = true;
}

// E5.2 — after the FIRST successful run, a one-time card points the newcomer at
// the three things to look at next (real tabs; no invented content). Shown once,
// dismissible; never after a failed/cancelled run.
function maybeShowPostRunPanel() {
  if (safeStorage.get("ll.postRunSeen") === "1") return;
  if (document.getElementById("postrun-card")) return;
  safeStorage.set("ll.postRunSeen", "1");
  const el = document.createElement("div");
  el.id = "postrun-card";
  el.className = "postrun-card";
  el.setAttribute("role", "status");
  el.innerHTML =
    "<div class='postrun-head'><strong>Run complete — what now?</strong>" +
    "<button class='postrun-close' aria-label='Dismiss'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button></div>" +
    "<span class='muted'>See the layout, check sign-off, or dig into the numbers.</span>" +
    "<div class='postrun-actions'>" +
      "<button class='btn btn-ghost' data-go='preview'>View GDS</button>" +
      "<button class='btn btn-ghost' data-go='verify'>Check sign-off</button>" +
      "<button class='btn btn-ghost' data-go='analytics'>See metrics</button>" +
    "</div>";
  el.addEventListener("click", (e) => {
    const t = e.target;
    const go = t.getAttribute && t.getAttribute("data-go");
    if (go) { document.querySelector('.side-tab[data-tab="' + go + '"]')?.click(); el.remove(); }
    if (t.classList && t.classList.contains("postrun-close")) el.remove();
  });
  document.body.appendChild(el);
}

// I2 — warn (never block) when running against an unvalidated librelane. LanEx
// reaches past librelane's public CLI, so a version outside the known-good range
// or a failed private-API probe can misbehave; make that visible instead of
// letting it surface as a cryptic mid-run failure.
function maybeWarnCompat(compat) {
  if (!compat || (compat.ok && compat.known_good)) return;
  let msg;
  if (compat.issues && compat.issues.length) {
    msg = "LanEx may not work with this librelane (" + (compat.version || "?") + "): " +
      compat.issues.join("; ") + ". Known-good: " + (compat.range || "") + ".";
  } else {
    msg = "LanEx has not been validated against librelane " + (compat.version || "?") +
      " (known-good " + (compat.range || "") + "). Things may misbehave; " +
      "pin with `pip install 'librelane~=3.0'` for a tested version.";
  }
  let el = document.getElementById("compat-banner");
  if (!el) {
    el = document.createElement("div");
    el.id = "compat-banner";
    el.className = "pw-banner";
    el.setAttribute("role", "alert");
    document.body.appendChild(el);
  }
  el.innerHTML = "";
  const ico = document.createElement("span");
  ico.className = "pw-banner-ico";
  ico.innerHTML = icon("alert", { size: 16 });
  const span = document.createElement("span");
  span.textContent = msg;
  const close = document.createElement("button");
  close.className = "pw-banner-close";
  close.setAttribute("aria-label", "Dismiss");
  close.textContent = "Dismiss";
  close.addEventListener("click", () => { el.hidden = true; });
  el.appendChild(ico);
  el.appendChild(span);
  el.appendChild(close);
  el.hidden = false;
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
  }
  if (e.detail?.tab === "analytics") {
    import("./modules/analytics.js").then((m) => m.renderAnalyticsFull());
    import("./modules/compare.js").then((m) => m.renderCompare());
    import("./modules/watch.js").then((m) => m.renderWatch());
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
