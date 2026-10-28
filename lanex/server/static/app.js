// app.js — front-end entry. Bootstraps everything.

import { api, sse, fmt } from "./modules/api.js";
import { state, safeStorage } from "./modules/state.js";
import { setupTabs } from "./modules/tabs.js";
import { setupNav, startAt, go, bootTab, hashTab } from "./modules/nav.js";
import { noteRunStarted, noteRunFinished, loadRuns as loadContextRuns } from "./modules/context.js";
import { setupSetup, populatePdkPicker, paintRunning, paintDesignPill, paintPdkPill, paintOnboardChecklist } from "./modules/setup.js";
import { setupTheme, toggleTheme } from "./modules/theme.js";
import { setupHotkeys } from "./modules/hotkeys.js";
import { setupDensity } from "./modules/density.js";
import { setupShell, paintProgress } from "./modules/shell.js";
import { setupZoom } from "./modules/zoom.js";
import { setupPalette, openPalette } from "./modules/palette.js";
import { setupRunMode } from "./modules/runmode.js";
import { renderConfig } from "./modules/config.js";
import { runStarted, runProgress, runFinished } from "./modules/runend.js";
import { renderLogs } from "./modules/logs.js";
import { loadingStart, pageSkeleton } from "./modules/loading.js";
import { help } from "./modules/help.js";
import { toast } from "./modules/toast.js";
import { setupWizard } from "./modules/wizard.js";
import { icon } from "./modules/icons.js";
import { setupFullscreen } from "./modules/fullscreen.js";
import { setupTooltips } from "./modules/tooltip.js";

// ---------------------------------------------------------------- pages on demand
// Each page's code loads the first time it is needed (its tab opens, or an
// event it must hear arrives once it is loaded), so the first paint only waits
// for the shell and Setup. After boot, Flow and Runs (the pages a run lands
// on) load in idle time, and any tab loads while the pointer rests on it.
const PAGES = {
  flow: () => import("./modules/flow.js"),
  runs: () => import("./modules/runs.js"),
  tools: () => import("./modules/tools.js"),
  analytics: () => import("./modules/analytics.js"),
  verify: () => import("./modules/verify.js"),
  layout: () => import("./modules/layout.js"),
  cells: () => import("./modules/cells.js"),
  ide: () => import("./modules/ide/main.js"),
};
const TAB_PAGE = { pipeline: "flow", runs: "runs", tools: "tools", analytics: "analytics", verify: "verify", layout: "layout", cells: "cells", ide: "ide" };
const _mods = {};      // name -> the module, once loaded
const _modP = {};      // name -> its loading promise
function page(name) {
  if (!_modP[name]) {
    _modP[name] = PAGES[name]().then((m) => (_mods[name] = m), (e) => { delete _modP[name]; throw e; });
  }
  return _modP[name];
}
// Call into a page's module only if it is loaded (an event for a page that
// has never shown needs nothing: it reads the state when it first renders).
function ifLoaded(name, fn) {
  const m = _mods[name];
  if (m) R(name, () => fn(m));
}
function prefetch(names) {
  const idle = window.requestIdleCallback || ((f) => setTimeout(f, 200));
  const next = () => {
    const n = names.shift();
    if (!n) return;
    idle(() => page(n).catch(() => {}).finally(next), { timeout: 3000 });
  };
  next();
}

// Map each side-nav tab to a line-style SVG icon (replaces per-OS emoji glyphs).
const TAB_ICONS = {
  setup: "folder", pipeline: "flow", runs: "clock",
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
    setupNav();
    setupTheme();
    setupDensity();
    setupZoom();
    // Wire the status-line Logs button so install output can always be reopened.
    import("./modules/logdrawer.js").then((d) => d.setupLogDrawer()).catch(() => {});
    // The Console drawer (Ctrl+` and the status-line Console button).
    import("./modules/console.js").then((m) => m.setupConsole()).catch((e) => console.error("console", e));
    setupPalette();
    setupRunMode();
    setupSetup();
    setupShell();
    setupHotkeys();
    setupWizard();
    setupFullscreen();
    setupTooltips();
    import("./modules/problems.js").then((m) => m.wireProblemCount()).catch(() => {});
    import("./modules/fixsheet.js").catch(() => {});
    paintNavIcons();
    help.bind();
    document.getElementById("ide-popout")?.addEventListener("click", () => {
      const dd = state.designDir ? "?design_dir=" + encodeURIComponent(state.designDir) : "";
      window.open("/ide" + dd, "_blank", "noopener");
    });
    document.getElementById("tools-icon")?.addEventListener("click", () => go("tools", {}, { link: false }));
    document.getElementById("palette-btn")?.addEventListener("click", openPalette);
    document.getElementById("theme-btn")?.addEventListener("click", toggleTheme);

    // Everything boot asks the server goes out at once: the compatibility
    // check, the flow metadata, and which project to open. None waits for
    // another.
    api.health().then((h) => maybeWarnCompat(h && h.compat)).catch(() => {});
    setStatus("loading flow metadata…");
    const metaP = Promise.all([
      api.steps(),
      api.variables(),
      api.designFormats(),
      api.flows(),
      api.pdks(),
    ]);
    // Adopt a design directory so the GUI opens ready to run AND the Runs tab
    // shows that design's history immediately. Prefer one the server already
    // knows (e.g. `librelane-gui --design-dir`); otherwise re-adopt the most
    // recent design the user opened (persisted in localStorage `ll.recentDesigns`).
    // Runs are scoped to the active design dir server-side, so without this the
    // Runs tab stays empty until the user re-picks a source.
    const designP = (async () => {
      const dd = await api.designDir().catch(() => null);
      if (dd && dd.design_dir) return { adopt: dd.design_dir, serverKnew: true };
      try {
        const recent = JSON.parse(localStorage.getItem("ll.recentDesigns") || "[]").filter(Boolean);
        if (recent.length) {
          // Tell the server about it before adopting (it's not active yet).
          const res = await api.setDesignDir(recent[0]);
          return { adopt: res && res.design_dir, serverKnew: false };
        }
      } catch (_e) { /* stale/removed recent dir — ignore */ }
      return { adopt: null, serverKnew: false };
    })();
    const [[steps, vars, formats, flows, pdks], proj] = await Promise.all([metaP, designP]);
    state.steps = steps;
    state.variables = vars;
    state.designFormats = formats;
    state.flows = flows;
    state.pdks = pdks;
    state.selectedPdk = (state.pdks[0] && state.pdks[0].name) || "";
    if (state.steps.length) {
      state.selectedStepId = state.steps[0].id;
    }

    // Subscribe to the event stream. SSE is optional; don't block boot.
    try {
      sse.open();
    } catch (_e) { /* ignore */ }
    try {
      sse.on(handle);
    } catch (_e) { /* ignore */ }

    // The project: what every page needs before it draws (the server's
    // active project, its card, the config's PDK). Its files, runs and
    // summary are read after the window shows (finishAdopt).
    const setupMod = await import("./modules/setup.js");
    let opened = false;
    if (proj.adopt) {
      const input = document.getElementById("design-dir-input");
      if (input) input.value = proj.adopt;
      // Boot adoption is implicit: scope Runs/Preview but keep the Setup file
      // selector hidden (history/recents stay shown) until the user explicitly
      // loads a design. See adoptDesignDir({explicit}).
      try { opened = await setupMod.openDesignQuick(proj.adopt, { explicit: proj.serverKnew }); } catch (_e) { opened = false; }
    }
    // The PDK picker, already following the project's config.
    await populatePdkPicker(pdks);
    setStatus("rendering panels…");
    renderConfig();
    // The shared run list every results page reads: asked for now, used by
    // whichever page shows first (they share the one request).
    loadContextRuns().then(() => {
      if (!state.selectedRunTag && state.runs && state.runs.length) state.selectedRunTag = state.runs[0].tag;
    }).catch(() => {});
    if (opened) {
      setupMod.finishAdopt(proj.adopt, { explicit: proj.serverKnew })
        .then(() => paintOnboardChecklist())
        .catch((e) => console.error("adopt", e));
    }
    paintOnboardChecklist();  // E5.1 — reflect the real design/PDK/run state now

    // Open on Setup (the design/PDK/run entry point) for a bare address,
    // whatever tab was last visited; an address that names a page (#ide after
    // a reload, a pasted #verify) opens that page instead.
    const asked = hashTab();
    // Hide splash and reveal the app (then take the splash out of the
    // document: a hidden spinner still animates every frame).
    setStatus("ready");
    document.getElementById("app").style.display = "";
    startAt(bootTab());
    if (asked && !document.getElementById("sec-" + asked)) go(asked);
    if (splash) {
      splash.classList.add("hide");
      const gone = () => { splash.hidden = true; };
      splash.addEventListener("transitionend", gone, { once: true });
      setTimeout(gone, 400);
    }
    // First launch: the Press Start card; mid-guide: offer to carry on (guide.js).
    import("./modules/guide.js").then((m) => m.setupGuide()).catch((e) => console.error("guide", e));
    // The pages a run lands on, in idle time; any tab while the pointer rests on it.
    prefetch(["flow", "runs"]);
    document.querySelectorAll(".side-tab").forEach((t) => {
      const name = TAB_PAGE[t.dataset.tab];
      if (name) t.addEventListener("pointerenter", () => page(name).catch(() => {}), { once: true });
    });
  } catch (err) {
    failUI(err);
  }
}

// Isolate one view's render from another: a throw in one page's render must not
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
      // Every open window shows Stop, not only the one Run was pressed in: the
      // top-bar button stops a running flow, so "Run" on it would mislead.
      if (!state.runStart) paintRunning(true);   // (a start pressed here paints itself)
      // Reset per-step statuses to the fresh graph (all pending). Without this
      // the timeline kept the PREVIOUS run's statuses (all "done")
      // until each new step event arrived — so a fresh run (especially a DSE
      // config, which reuses the runner back-to-back) looked like it was showing
      // the previous run's progress. Seeding pending here fixes that immediately.
      state.stepStatuses = {};
      state.lastFlow = null;
      state.paused = false;
      for (const s of ev.step_graph) state.stepStatuses[s.id] = s.status || "pending";
      resetTimings();         // a fresh run is starting; clear old step timings
      renderLogs.clear();
      ifLoaded("runs", (m) => m.renderRuns());  // surface the just-created run dir immediately
      // setup.js shows Flow when a run starts, unless the Run menu says to stay
      // on the page you're on.
      noteRunStarted();
      // The clock started when Run was pressed (setup.js), not now.
      const t0 = ev.tag && state.runStartedFor === ev.tag ? state.runStartedAt : 0;
      runStarted(ev.tag);
      if (t0) state.runStartedAt = t0;
      state.runStartedFor = "";
      ifLoaded("flow", (m) => m.flowEvent(ev));
    }
    if (ev.message) {
      renderLogs.append(ev);
      // Step by step: the runner waits for "Next step".
      if (/^paused/.test(ev.message)) { state.paused = true; ifLoaded("flow", (m) => m.flowEvent(ev)); }
    }
  } else if (ev.type === "phase") {
    // Container pre-step milestone — show the "preparing" hero with a timer.
    state.status.running = true;
    if (!state.runStart) paintRunning(true);
    if (!state.prepStart) state.prepStart = Date.now();
    state.prepPhase = ev.label || "Preparing…";
    if (ev.tag) state.liveTag = ev.tag;
    if (ev.label) renderLogs.append({ type: "log", payload: { message: "• " + ev.label } });
    ifLoaded("flow", (m) => m.flowEvent(ev));
  } else if (ev.type === "log") {
    renderLogs.append(ev);
  } else if (ev.type === "dse_config_started") {
    // A new DSE config is starting: clear the previous config's step statuses
    // immediately so the pipeline/timeline don't keep showing it as "done" while
    // the next container spins up (its step_graph arrives a few seconds later).
    for (const p of (state.pipeline || [])) state.stepStatuses[p.id] = "pending";
    state.status.running = true;
    resetTimings();
    state.prepStart = Date.now();
    state.prepPhase = "Sweep run " + (((ev.index || 0) + 1)) + " of " + (ev.total || "?") + (ev.tag ? " (" + ev.tag + ")" : "") + ": preparing…";
    ifLoaded("flow", (m) => m.flowEvent(ev));
    // A sweep point is a run: the top bar shows Stop and the status bar "running".
    import("./modules/setup.js").then((m) => m.paintRunning(true)).catch(() => {});
    document.dispatchEvent(new CustomEvent("g:sweep", { detail: ev }));
  } else if (ev.type === "dse_config_done" || ev.type === "dse_done") {
    // Runs shows each point's real outcome as it lands.
    document.dispatchEvent(new CustomEvent("g:sweep", { detail: ev }));
  } else if (ev.type === "manual_started" || ev.type === "manual_line" || ev.type === "manual_done") {
    import("./modules/console.js").then((m) => m.onManualEvent(ev));
  } else if (ev.type === "installer_result") {
    // Final outcome of an async tool install (the POST returned "started"
    // immediately; this event carries the real result). tools.js toasts it,
    // logs the guidance, chains the engine→image pull, and re-probes the tab.
    import("./modules/tools.js").then((m) => m.onInstallerResult && m.onInstallerResult(ev));
  } else if (ev.type === "installer_line" || ev.type === "installer_started" || ev.type === "installer_done" || ev.type === "installer_error" || ev.type === "installer_info") {
    const isImagePull = ev.key === "container:image";
    if (isImagePull && ev.type === "installer_line") {
      page("tools").then((m) => m.updatePullProgress(ev.line)).catch(() => {});   // heartbeat on the runtime card
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
      // What Setup's "Ready to run?" check read has changed.
      document.dispatchEvent(new CustomEvent("g:tools_changed", { detail: { key: ev.key || "" } }));
      if (isImagePull) {
        // The pull owns the runtime card; finishPull re-probes + reports.
        const rc = ev.type === "installer_done" ? (ev.rc ?? 0) : (typeof ev.rc === "number" ? ev.rc : 1);
        page("tools").then((m) => m.finishPull(rc)).catch(() => {});
      } else {
        // The Tools page probes again if it has been shown (it probes on every visit).
        ifLoaded("tools", (m) => m.renderTools());
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
    paintProgress(Math.min(ev.done || 0, ev.total || 0), ev.total || 0);
    runProgress();
    ifLoaded("flow", (m) => m.flowEvent(ev));
  } else if (ev.type === "run_status_resync") {
    // The SSE stream dropped and reconnected past events the server's ring had
    // already evicted (e.g. laptop sleep during a verbose flow) — our step
    // history is now incomplete. Re-hydrate the live pipeline from the
    // authoritative /api/run/status so the timeline can't show stale step
    // states behind a green "connected" chip (N3, Fear F). Disk-derived tabs
    // already re-read truth; this fixes the live view.
    state.stepStatuses = state.stepStatuses || {};
    if (ev.step_statuses && typeof ev.step_statuses === "object") {
      for (const [id, st] of Object.entries(ev.step_statuses)) {
        if (st) state.stepStatuses[id] = st;
      }
    }
    if (typeof ev.running === "boolean") state.status.running = ev.running;
    if (typeof ev.paused === "boolean") state.paused = ev.paused;
    if (ev.run_dir) state.liveTag = String(ev.run_dir).split(/[\\/]/).pop();
    ifLoaded("flow", (m) => m.flowEvent(ev));
    ifLoaded("runs", (m) => m.renderRuns());
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
      noteTiming(ev.type, id);
      // What the run prints next belongs to this step (Flow shows it live).
      if (ev.type === "step_started") { renderLogs.markStep(id); state.paused = false; state.prepPhase = null; }
      if (ev.tag) state.liveTag = ev.tag;
      runProgress();
      ifLoaded("flow", (m) => m.flowEvent(ev));
    }
    // A failed step is told once, when the run ends, with the reason (runend.js).
  } else if (ev.type === "flow_done") {
    // Reset run state + re-enable the Run button FIRST, before any rendering.
    // A throw in one of the renders below must never leave the button disabled
    // (that is exactly what made "a failed run blocks the next run": a render
    // error on flow_done skipped paintRunning(false), wedging the UI).
    state.status.running = false;
    state.lastFlow = { error: ev.error || null, cancelled: !!ev.cancelled };
    paintRunning(false);
    document.dispatchEvent(new CustomEvent("g:flow_done", { detail: ev }));
    const pill = document.getElementById("run-pill");
    if (pill) {
      pill.classList.remove("pill-running", "pill-pass", "pill-fail");
      pill.classList.add(ev.error ? "pill-fail" : ev.cancelled ? "pill-pending" : "pill-pass");
      pill.textContent = ev.error ? "failed" : ev.cancelled ? "stopped" : "done";
    }
    // The toast, the window title and the notification say how it ended (runend.js).
    runFinished(ev).catch((e) => console.error("run end", e));
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
      refreshMetrics();
      ifLoaded("runs", (m) => m.renderRuns());
      ifLoaded("flow", (m) => m.flowEvent(ev));
      // Results pages follow the new run if the user was on the newest one.
      noteRunFinished(ev.tag).catch(() => {});
      paintOnboardChecklist();
      if (!ev.error && !ev.cancelled) {
        import("./modules/watch.js").then((m) => m.checkAfterRun()).catch(() => {});
      }
    } catch (e) {
      console.error("flow_done render", e);
    }
  }
}

// The newest run's metrics, for the watch list (watch.js).
async function refreshMetrics() {
  try {
    // The open project's runs, not whichever design the server last saw.
    state.runs = await api.runs(state.designDir || undefined);
    const target = state.runs[0] && state.runs[0].tag;
    if (!target) return;
    const view = await api.run(target);
    state.metrics = view.metrics?.values || {};
  } catch (_e) {}
}

// Per-step wall time for the live run (Flow shows it until the step's own
// runtime.txt is written).
function resetTimings() {
  state.stepTiming = {};
  state.prepPhase = null;
  state.prepStart = null;
}
function noteTiming(type, id) {
  state.stepTiming = state.stepTiming || {};
  const rec = state.stepTiming[id] || (state.stepTiming[id] = {});
  if (type === "step_started") { rec.start = Date.now(); rec.end = null; }
  else { if (!rec.start) rec.start = Date.now(); rec.end = Date.now(); }
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
  // A page opened while a run (or a sweep point) is going shows Stop and
  // "running", not Run and "idle": the run's start event came before the page.
  Promise.resolve(boot()).then(() => api.runStatus()).then((s) => {
    if (!s || !s.running) return;
    state.status.running = true;
    if (s.run_dir) state.liveTag = String(s.run_dir).split(/[\\/]/).pop();
    paintRunning(true);
  }).catch(() => {});
});

// A per-tab run picker switched the active design to view a cross-design run:
// reflect it in the topbar pill so the user (and the global Run button) know
// which design is active now.
document.addEventListener("g:active_design_changed", (e) => {
  const dir = e.detail?.dir || "";
  const label = dir.split(/[/\\]/).filter(Boolean).pop() || dir;
  if (label) paintDesignPill(label);
});

// Each page renders when it shows (nav.js says so with g:tab_activated).
// The page's code loads the first time (its skeleton shows if that takes more
// than a moment, until the page draws).
const RENDER = {
  tools: (m) => m.renderTools(),
  analytics: (m) => {
    m.renderAnalyticsFull();
    import("./modules/compare.js").then((c) => c.renderCompare());
    import("./modules/watch.js").then((w) => w.renderWatch());
  },
  runs: (m) => m.renderRuns(),
  pipeline: (m) => m.renderFlow(),
  ide: (m) => m.initIde({ designDir: state.designDir, runMode: state.runMode }),
  layout: (m) => m.renderLayout(),
  verify: (m) => m.renderVerify(),
  cells: (m) => m.renderCells(),
};
document.addEventListener("g:tab_activated", (e) => {
  const tab = e.detail?.tab;
  const r = RENDER[tab];
  // g:tab_rendered says the page has drawn (the guide waits for it).
  const rendered = () => document.dispatchEvent(new CustomEvent("g:tab_rendered", { detail: { tab } }));
  if (!r) { rendered(); return; }
  const name = TAB_PAGE[tab];
  // The skeleton stands in while the page's code downloads; it goes before
  // the page draws (a page measures its boxes as it draws: they must show).
  const job = _mods[name] ? null : loadingStart(document.getElementById("sec-" + tab), { skeleton: pageSkeleton(tab) });
  page(name)
    .finally(() => job && job.done())
    .then((m) => r(m))
    .then(rendered)
    .catch((err) => console.error("render " + tab, err));
});
