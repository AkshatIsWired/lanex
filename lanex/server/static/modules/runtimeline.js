// runtimeline.js — the live RTL→GDS run timeline.
//
// A visually prominent "now running" hero (which tool, which step, since when,
// for how long) plus a per-step timeline with tool badges, timestamps and
// durations. Driven entirely by the SSE events app.js already receives
// (step_started / step_done / step_skipped / step_failed / progress) — it
// derives the tool from the step id prefix (e.g. `OpenROAD.Floorplan` → OpenROAD)
// and the human name from the introspected step metadata. No backend changes.

import { fmt } from "./api.js";
import { state } from "./state.js";
import { icon } from "./icons.js";

// Per-tool presentation. The tool is the part of the step id before the dot.
// `ic` is an icons.js name; toolMeta resolves it to an inline SVG so the badge
// renders identically on every OS and inherits the per-tool accent colour.
const TOOL = {
  Yosys:     { label: "Yosys",     ic: "tools",    accent: "#d29922", blurb: "Logic synthesis" },
  Verilator: { label: "Verilator", ic: "check",    accent: "#3fb950", blurb: "RTL lint" },
  Checker:   { label: "Checker",   ic: "search",   accent: "#58a6ff", blurb: "Sanity checks" },
  OpenROAD:  { label: "OpenROAD",  ic: "layers",   accent: "#bc8cff", blurb: "Floorplan · place · route · STA" },
  Odb:       { label: "OpenDB",    ic: "database", accent: "#bc8cff", blurb: "Layout DB transforms" },
  Magic:     { label: "Magic",     ic: "cpu",      accent: "#f778ba", blurb: "Signoff DRC · GDS · extraction" },
  Netgen:    { label: "Netgen",    ic: "diff",     accent: "#39c5cf", blurb: "LVS" },
  KLayout:   { label: "KLayout",   ic: "image",    accent: "#79c0ff", blurb: "DRC · render · XOR" },
  OpenSTA:   { label: "OpenSTA",   ic: "clock",    accent: "#d29922", blurb: "Static timing" },
};

function toolMeta(id) {
  const t = (id || "").split(".")[0];
  const m = TOOL[t] || { label: t || "Step", ic: "cube", accent: "var(--text-muted)", blurb: "" };
  return { ...m, icon: icon(m.ic, { size: 14 }) };
}

function longName(id) {
  const s = (state.steps || []).find((x) => x.id === id);
  if (s && s.long_name && s.long_name !== id) return s.long_name;
  // Fall back to the part after the dot, spaced out.
  const tail = (id || "").split(".").slice(1).join(".") || id || "";
  return tail.replace(/([a-z])([A-Z])/g, "$1 $2");
}

function fmtDuration(ms) {
  if (ms == null) return "";
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return s + "s";
  const m = Math.floor(s / 60);
  return m + "m " + (s % 60) + "s";
}

function fmtClock(ts) {
  if (!ts) return "";
  try { return new Date(ts).toLocaleTimeString(); } catch (_e) { return ""; }
}

// Seconds → coarse "Xm" / "Xh Ym" for an ETA (rounded, never false-precise).
function fmtEta(secs) {
  const s = Math.round(secs);
  if (s < 60) return s + "s";
  const m = Math.round(s / 60);
  if (m < 60) return m + " min";
  const h = Math.floor(m / 60);
  return h + "h " + (m % 60) + "m";
}

let _timer = null;

// Ordered list of step ids: prefer the seeded flow graph (real flow order),
// else the introspected step list.
function orderedIds() {
  if (state.pipeline && state.pipeline.length) return state.pipeline.map((p) => p.id);
  return (state.steps || []).map((s) => s.id);
}

export function renderRuntimeline() {
  const root = document.getElementById("run-timeline");
  if (!root) return;
  const ids = orderedIds();
  const timing = state.stepTiming || {};
  const statuses = state.stepStatuses || {};
  const running = state.status && state.status.running;

  if (!ids.length) {
    root.innerHTML =
      "<div class='rt-empty'><span class='rt-empty-ico'>" + icon('flow',{size:32}) + "</span>" +
      "<div><strong>No flow loaded yet</strong><div class='hint'>Pick a design and press Run — each step will light up here with the tool and timing.</div></div></div>";
    stopTimer();
    return;
  }

  const total = ids.length;
  const failed = ids.find((id) => statuses[id] === "failed");
  // Once the flow reports a real step (or finishes), the preparing phase is over.
  if (state.prepPhase && (statuses && Object.values(statuses).some((s) => s !== "pending"))) {
    state.prepPhase = null;
  }
  // Only treat a step as "currently running" while the flow is actually
  // running — otherwise a step whose step_done lagged would keep the hero
  // spinning and the bar stuck at 99% after the flow already finished.
  const currentId = running ? [...ids].reverse().find((id) => statuses[id] === "running") : null;
  let done = ids.filter((id) => ["done", "skipped"].includes(statuses[id])).length;
  if (!running && !failed) done = total;  // finished cleanly => all done
  const pct = total ? Math.round((done / total) * 100) : 0;
  if (!running) stopTimer();

  // ---- hero ----
  let hero;
  if (currentId) {
    const m = toolMeta(currentId);
    const t = timing[currentId] || {};
    const elapsed = t.start ? fmtDuration(Date.now() - t.start) : "";
    const eta = state.runProgress && state.runProgress.eta_seconds;
    const etaTxt = (typeof eta === "number" && eta > 0) ? " · ~" + fmtEta(eta) + " left" : "";
    hero =
      "<div class='rt-hero rt-running'>" +
      "<span class='rt-badge' style='--tool:" + m.accent + "'>" + m.icon + " " + fmt.escape(m.label) + "</span>" +
      "<div class='rt-hero-main'>" +
      "<div class='rt-hero-step'>" + fmt.escape(longName(currentId)) + "</div>" +
      "<div class='rt-hero-sub'>" + fmt.escape(m.blurb) +
      (t.start ? " · started " + fmtClock(t.start) : "") + "</div>" +
      "</div>" +
      "<div class='rt-hero-time'><span class='rt-elapsed' id='rt-elapsed'>" + elapsed + "</span>" +
      "<span class='rt-hero-pct'>step " + (done + 1) + " / " + total + " · " + pct + "%" + etaTxt + "</span></div>" +
      "</div>";
  } else if (failed && !running) {
    const m = toolMeta(failed);
    hero =
      "<div class='rt-hero rt-failed'>" +
      "<span class='rt-badge' style='--tool:#f85149'>" + m.icon + " " + fmt.escape(m.label) + "</span>" +
      "<div class='rt-hero-main'><div class='rt-hero-step'>Stopped at " + fmt.escape(longName(failed)) + "</div>" +
      "<div class='rt-hero-sub'>See the failed step below and the Live Logs for the tool error.</div></div>" +
      "<div class='rt-hero-time'><span class='rt-hero-pct'>" + done + " / " + total + " done</span></div></div>";
  } else if (running && !currentId && done === 0 && state.prepPhase) {
    // Container mode does a lot before the first step (start the container,
    // verify the PDK, load the config) — and the inner process block-buffers
    // its stdout, so the pipeline can look frozen. Show what's happening with a
    // live timer so the silence is explained, not alarming.
    const elapsed = state.prepStart ? fmtDuration(Date.now() - state.prepStart) : "";
    hero =
      "<div class='rt-hero rt-preparing'>" +
      "<span class='rt-badge rt-badge-spin' style='--tool:var(--accent)'>⟳ Preparing</span>" +
      "<div class='rt-hero-main'>" +
      "<div class='rt-hero-step'>" + fmt.escape(state.prepPhase) + "</div>" +
      "<div class='rt-hero-sub'>The flow hasn't reported a step yet. First container start can take a minute.</div>" +
      "</div>" +
      "<div class='rt-hero-time'><span class='rt-elapsed' id='rt-prep-elapsed'>" + elapsed + "</span></div></div>";
  } else if (done >= total && total > 0) {
    hero =
      "<div class='rt-hero rt-complete'>" +
      "<span class='rt-badge' style='--tool:#3fb950'>" + icon('check',{size:14}) + " Complete</span>" +
      "<div class='rt-hero-main'><div class='rt-hero-step'>RTL → GDSII finished</div>" +
      "<div class='rt-hero-sub'>All " + total + " steps done. The GDS is on the Preview tab.</div></div></div>";
  } else {
    hero =
      "<div class='rt-hero'>" +
      "<span class='rt-badge' style='--tool:var(--text-muted)'>idle</span>" +
      "<div class='rt-hero-main'><div class='rt-hero-step'>Ready to run</div>" +
      "<div class='rt-hero-sub'>" + total + " steps in this flow. Press ▶ Run flow.</div></div></div>";
  }

  // ---- progress bar ----
  const bar =
    "<div class='rt-bar'><div class='rt-bar-fill' style='width:" + pct + "%'></div></div>";

  // ---- step rows ----
  const rows = ids.map((id) => {
    const m = toolMeta(id);
    const st = statuses[id] || "pending";
    const t = timing[id] || {};
    let dur = "";
    if (st === "running") dur = "running…";
    else if (st === "skipped") dur = "skipped";
    else if (t.start && t.end) dur = fmtDuration(t.end - t.start);
    const at = t.start ? fmtClock(t.start) : "";
    return (
      "<div class='rt-row rt-clickable rt-" + st + (id === currentId ? " rt-row-current" : "") +
      "' data-id='" + fmt.escape(id) + "' title='Click to see this step's log + reports below'>" +
      "<span class='rt-dot'></span>" +
      "<span class='rt-row-badge' style='--tool:" + m.accent + "' title='" + fmt.escape(m.label) + "'>" + m.icon + "</span>" +
      "<span class='rt-row-name'>" + fmt.escape(longName(id)) + "</span>" +
      "<span class='rt-row-tool'>" + fmt.escape(m.label) + "</span>" +
      "<span class='rt-row-at'>" + at + "</span>" +
      "<span class='rt-row-dur'>" + dur + "</span>" +
      "</div>"
    );
  }).join("");

  root.innerHTML = hero + bar + "<div class='rt-list'>" + rows + "</div>";

  // Click a step row → show its log/reports in the console (g:step_selected is
  // handled by stepoutput.js, which renders into the Step Output console).
  root.querySelectorAll(".rt-row[data-id]").forEach((row) =>
    row.addEventListener("click", () => {
      const id = row.dataset.id;
      if (id) document.dispatchEvent(new CustomEvent("g:step_selected", { detail: { id } }));
    }));

  // Auto-scroll the current step into view.
  const cur = root.querySelector(".rt-row-current");
  if (cur) cur.scrollIntoView({ block: "nearest" });

  if (currentId || (running && state.prepPhase)) startTimer(); else stopTimer();
}

function startTimer() {
  if (_timer) return;
  _timer = setInterval(() => {
    const ids = orderedIds();
    const statuses = state.stepStatuses || {};
    const currentId = [...ids].reverse().find((id) => statuses[id] === "running");
    // Preparing-phase timer (before any step runs).
    const prepEl = document.getElementById("rt-prep-elapsed");
    if (prepEl && state.prepStart) {
      prepEl.textContent = fmtDuration(Date.now() - state.prepStart);
      return;
    }
    const el = document.getElementById("rt-elapsed");
    if (!currentId || !el) { stopTimer(); return; }
    const t = (state.stepTiming || {})[currentId] || {};
    if (t.start) el.textContent = fmtDuration(Date.now() - t.start);
  }, 1000);
}

function stopTimer() {
  if (_timer) { clearInterval(_timer); _timer = null; }
}

// Record timing from the SSE stream. Called by app.js for each step event.
export function noteStepEvent(type, id) {
  if (!id) return;
  state.stepTiming = state.stepTiming || {};
  const rec = state.stepTiming[id] || (state.stepTiming[id] = {});
  if (type === "step_started") { rec.start = Date.now(); rec.end = null; }
  else if (type === "step_done" || type === "step_failed" || type === "step_skipped") {
    if (!rec.start) rec.start = Date.now();
    rec.end = Date.now();
  }
}

export function resetTimeline() {
  state.stepTiming = {};
  state.prepPhase = null;
  state.prepStart = null;
}

// A container pre-step milestone (image pull / container start / PDK / config).
// Surfaced as the "preparing" hero with a live timer until the first step runs.
export function notePhase(label) {
  if (!label) return;
  if (!state.prepStart) state.prepStart = Date.now();
  state.prepPhase = label;
  renderRuntimeline();
}
