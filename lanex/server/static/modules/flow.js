// flow.js — the Flow page (rail "Flow", data-tab "pipeline"): one run, stage by stage.
//
//   head      what happened, first: the live step, why it stopped (failure
//             card), or the run report card when it finished
//   strip     the seven stages (flowstages.js): state, time against the run it
//             is compared with, one number from the end of the stage, and the
//             layout at that stage
//   steps     every step in flow order, under its stage's heading, never folded:
//             the list keeps the running step in view while a run goes (until
//             you scroll it yourself), so the flow can be watched step by step
//   output    beside it, one pane of the same height: the run's output as it
//             prints (Vivado and Quartus dock their log the same way), or the
//             picked step's log, what it does and its reports
//
// Maximised, the page is one screen: the two panes take the height that is
// left and scroll inside themselves. The page updates in place (rows, tiles,
// the head's text) instead of redrawing, so nothing jumps while a run goes.
//
// It shows the run on the results pages (context.js), or the live run while
// one is going. Nothing here computes a silicon number; values come from the
// run's files through the server.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { icon } from "./icons.js";
import { toast } from "./toast.js";
import * as ctx from "./context.js";
import { mountRunBar } from "./runbar.js";
import * as FS from "./flowstages.js";
import * as AM from "./analytics-model.js";
import { LogView } from "./logview.js";
import { fileActionsHtml, wireFileActions } from "./fileview.js";
import { liveLines, liveRows, onLiveLog } from "./logs.js";
import { reportCardHtml, verdictOf, fmtDur } from "./reportcard.js";
import { fixListHtml, problemsOf } from "./problems.js";
import { loadingStart, pageSkeleton } from "./loading.js";
import "./fixsheet.js";

const esc = (s) => fmt.escape(s == null ? "" : String(s));
const $ = (id) => document.getElementById(id);
const STAGE_NO = Object.fromEntries(FS.STAGES.map((s, i) => [s.id, i + 1]));
const BG = { dark: "#06080d", light: "#ffffff" };
const MARK = { done: "pass", failed: "fail", stopped: "warn", running: "run", skipped: "skipped", not_run: "not_run", pending: "not_run" };
const two = (n) => String(n).padStart(2, "0");

// Tool colour per step prefix (the same accents the old Pipeline used).
const TOOL = {
  Yosys: "#d29922", Verilator: "#3fb950", Checker: "#58a6ff", OpenROAD: "#bc8cff", Odb: "#bc8cff",
  Magic: "#f778ba", Netgen: "#39c5cf", KLayout: "#79c0ff", Misc: "#8b98ad",
};
const TOOL_LABEL = { Odb: "OpenDB" };

const F = {
  wired: false,
  tag: "", design: "",      // the run on screen
  live: false,              // it is the run that is going now
  pinned: false,            // the user picked another run while one is live
  keep: "",                 // a run that just ended, shown while the run list catches up
  flows: null,              // {name: [step ids]} from /api/flows
  rs: null, rx: null, vf: null, src: null,   // run-stages, run-explain, verify, layout sources
  px: null,                 // the run's problems (problems.js), for a run whose checks failed
  psrc: null,               // a resumed run's parent: its layout sources (the reused stages' pictures)
  base: null,               // compared-with run's run-stages (times)
  sel: null,                // the step in the output pane: an id, "" for none, null to choose
  tab: "log",               // the output pane's tab: log | about | reports | time
  follow: true,             // the step list keeps the running step in view
  followed: "",             // the step it last scrolled to
  tok: 0,
  log: null, logSrc: "",    // the LogView, and what it shows
  stepMeta: null,           // { key, dir, rel, reports } of the step log on screen
  stepInfo: new Map(),      // id -> /api/steps entry
  rows: new Map(), heads: new Map(),   // step rows and stage headings, by id
  raf: 0,
  loaded: false,            // the run list has come back once (before that: skeleton)
  job: null,                // the first open's loading state (loading.js)
};

// A Run click (setup.js): "starting" paints at once, "started" makes the new
// run the live one, "refused" says why with the way back.
if (typeof document !== "undefined") {
  document.addEventListener("g:run_start", (e) => {
    if (!visible()) return;
    if (F.job) { F.job.done(); F.job = null; }
    const phase = e.detail && e.detail.phase;
    if (phase === "started") { F.pinned = false; renderFlow(); } else paint();
  });
  // A refusal is said once: leaving Flow puts it away.
  document.addEventListener("g:tab_activated", (e) => {
    const tab = e.detail && e.detail.tab;
    if (tab !== "pipeline" && state.runStart && state.runStart.error) state.runStart = null;
  });
}

// ------------------------------------------------------------------ entry points

export async function renderFlow() {
  wireOnce();
  const tok = ++F.tok;
  const live = liveTag();
  if (!live) F.pinned = false;
  // A run being started shows at once; the first open of the page shows its
  // skeleton (after a moment) until the run list is in, never "No run yet"
  // before it has been asked. A later open keeps what it showed meanwhile.
  if (state.runStart && !live) paint();
  else if (!F.loaded && !F.job) {
    F.job = loadingStart($("sec-pipeline"), { skeleton: pageSkeleton("pipeline"), hasContent: () => !!state.runStart });
  }
  await ctx.loadRuns().catch(() => {});
  F.loaded = true;
  if (F.job) { F.job.done(); F.job = null; }
  if (tok !== F.tok) return;
  const tag = (!F.pinned && live) ? live : (F.keep || ctx.contextRun());
  const wasLive = F.live;
  F.live = !!live && tag === live;
  if (tag !== F.tag || ctx.contextDesign() !== F.design) {
    F.tag = tag || ""; F.design = ctx.contextDesign();
    F.rs = F.rx = F.vf = F.src = F.base = F.px = F.psrc = null;
    F.sel = (F.reveal && F.reveal.step) || null;
    F.tab = "log"; F.follow = !F.sel; F.followed = ""; F.logSrc = ""; F.stepMeta = null;
  } else if (wasLive && !F.live) {
    // The run just ended: its output now comes from its files.
    F.logSrc = "";
  }
  paint();
  if (!F.tag) return;
  await load(tok);
}

// A link to a step or a stage (nav.js go("pipeline", { step }) / { stage }).
// The page may still be loading the run: the list scrolls there once its
// rows exist (paintSteps).
export async function revealInFlow(p) {
  F.reveal = p;
  if (p.step) { F.sel = p.step; F.tab = "log"; F.follow = false; }
  paint();
}

// SSE events (app.js): repaint while visible; a finished step brings new runtimes.
let _rsTimer = 0;
export function flowEvent(ev) {
  if (ev.type === "info" && Array.isArray(ev.step_graph)) {
    F.pinned = false;
    if (visible()) renderFlow();
    return;
  }
  if (ev.type === "flow_done") {
    // The run being watched here is the one the results pages show from now on
    // (watching it is picking it); elsewhere context.js's follow rule decides.
    const watched = visible() && F.live ? F.tag : "";
    if (watched) {
      // Keep showing it while the run list catches up, then make it the run.
      F.keep = watched;
      renderFlow();
      ctx.waitForRun(watched).then((ok) => (ok ? ctx.setRun(watched) : null)).catch(() => {})
        .finally(() => { F.keep = ""; renderFlow(); });
    } else {
      F.live = false;
      if (visible()) setTimeout(() => renderFlow(), 600);
    }
    return;
  }
  if (!visible()) return;
  // A run started (its first event may be a "preparing" phase): show it.
  if (!F.live) { if (liveTag() && !F.pinned) renderFlow(); return; }
  if (ev.type === "step_done" || ev.type === "step_failed" || ev.type === "step_skipped") {
    clearTimeout(_rsTimer);
    _rsTimer = setTimeout(async () => {
      if (!F.live || !F.tag) return;
      // New step times, and the chip as each finished stage left it.
      const [rs, src] = await Promise.all([api.runStages(F.tag).catch(() => null), api.layoutSources(F.tag).catch(() => null)]);
      if (rs) F.rs = rs;
      if (src && src.stages) F.src = src;
      const parent = rs && rs.branched_from && rs.branched_from.dir ? rs.branched_from.tag : "";
      if (parent && !F.psrc) F.psrc = await api.layoutSources(parent).catch(() => null);
      schedule();
    }, 900);
  }
  schedule();
}

function schedule() {
  if (F.raf) return;
  F.raf = requestAnimationFrame(() => { F.raf = 0; paint(); });
}

const visible = () => $("sec-pipeline")?.classList.contains("section-active");

function liveTag() {
  if (!(state.status && state.status.running)) return "";
  return state.liveTag || "";
}

// ------------------------------------------------------------------ data

async function load(tok) {
  const tag = F.tag;
  const base = baseTag();
  const finished = !F.live;
  // A newer load of the same run doesn't make these answers wrong (a run
  // that just ended is re-rendered a few times while the run list catches
  // up): use whichever lands first, never an older one over a newer.
  const ok = () => F.tag === tag && F.live === !finished && tok >= (F.applied || 0) && ((F.applied = tok), true);
  // Verify's verdict can take a few seconds on a run it hasn't read yet: the
  // outcome (run-explain) shows first, the verdict fills in when it lands.
  const vfP = finished ? api.verify(tag).catch(() => null) : Promise.resolve(null);
  const [rs, rx, flows] = await Promise.all([
    api.runStages(tag).catch(() => null),
    finished ? api.runExplain(tag, base).catch(() => null) : Promise.resolve(null),
    F.flows ? Promise.resolve(null) : api.flows().catch(() => null),
  ]);
  if (!ok()) return;
  F.rs = rs; F.rx = rx;
  vfP.then((vf) => { if (ok()) { F.vf = vf; paint(); } });
  // A run whose checks failed leads with its problems (diagnosis and fixes).
  if (rx && rx.kind === "checks-failed") problemsOf(tag).then((px) => { if (ok()) { F.px = px; paint(); } });
  if (flows) F.flows = Object.fromEntries((Array.isArray(flows) ? flows : []).map((f) => [f.name, f.steps || []]));
  if (!F.stepInfo.size) for (const s of state.steps || []) F.stepInfo.set(s.id, s);
  paint();
  // A failed step is shown in the list (GitHub Actions opens it the same way).
  const failed = rx && rx.step && rx.step.id && ["halted", "stopped", "incomplete"].includes(rx.kind) ? rx.step.id : "";
  if (failed && F.sel == null) requestAnimationFrame(() => scrollListTo(F.rows.get(failed), false));
  // Second wave: the compared-with run's step times, and the layout pictures
  // (a resumed run's reused stages show the run they came from).
  const parent = rs && rs.branched_from && rs.branched_from.dir ? rs.branched_from.tag : "";
  const [b, src, psrc] = await Promise.all([
    base ? api.runStages(base).catch(() => null) : Promise.resolve(null),
    api.layoutSources(tag).catch(() => null),
    parent ? api.layoutSources(parent).catch(() => null) : Promise.resolve(null),
  ]);
  if (!ok()) return;
  F.base = b; F.src = src; F.psrc = psrc;
  paint();
}

// The run times are compared with: the run the results pages compare with, or
// for the live run, the newest earlier run of this design that finished.
function baseTag() {
  if (F.live) {
    const prev = (ctx.contextRuns() || []).find((r) => r.tag !== F.tag && r.success &&
      ctx.normDir(r._design) === ctx.normDir(F.design || state.designDir));
    return prev ? prev.tag : "";
  }
  const b = ctx.contextBaseline();
  return b && b !== F.tag ? b : "";
}

// ------------------------------------------------------------------ the model

// Every step of the run, in flow order, with its stage and status.
function model() {
  const disk = new Map(((F.rs && F.rs.steps) || []).filter((s) => s.id).map((s) => [s.id, s]));
  const st = state.stepStatuses || {};
  const tm = state.stepTiming || {};
  let ids;
  if (F.live && state.pipeline && state.pipeline.length) ids = state.pipeline.map((p) => p.id);
  else {
    const flowName = (F.vf && F.vf.flow) || "Classic";
    ids = (F.flows && F.flows[flowName]) || [];
    if (!ids.length) ids = [...disk.keys()];
  }
  const stages = FS.stagesOf(ids.map((id) => ({ id })));
  const lastRan = Math.max(-1, ...ids.map((id, i) => (disk.has(id) ? i : -1)));
  const rx = F.rx || {};
  const offIds = new Set((!F.live && F.vf && F.vf.flow_state && F.vf.flow_state.steps_off) || []);
  const steps = ids.map((id, i) => {
    const d = disk.get(id);
    let status;
    // Live: the events say what runs; a step whose folder has its runtime is
    // done whatever the events said (they can arrive late or out of order).
    if (F.live) status = d && d.status === "done" && d.runtime_s != null ? "done" : st[id] || (d ? "running" : "pending");
    else if (d) status = d.status === "done" ? "done" : "failed";
    // A step past where the run ended that its config turns off is "turned
    // off", not "not reached": the total is the flow's (FS.stepCounts).
    else status = i < lastRan || offIds.has(id) ? "skipped" : "not_run";
    if (!F.live && d && d.status !== "done" && rx.kind === "stopped") status = "stopped";
    if (!F.live && d && d.status !== "done" && rx.kind === "incomplete") status = "stopped";
    const t = tm[id] || {};
    let secs = d && d.runtime_s != null ? d.runtime_s : null;
    if (secs == null && F.live && t.start) secs = ((t.end || Date.now()) - t.start) / 1000;
    return { id, i, stage: stages[i], status, secs, dir: d ? d.dir : "", n: d ? d.n : null,
      changed: d ? d.changed : null, peak: d ? d.peak_rss_mib : null, from: (d && d.from) || "" };
  });
  // LibreLane runs one step at a time: a step still marked running behind the
  // newest one missed its "done" event, so it is done.
  if (F.live) {
    let last = -1;
    steps.forEach((s, i) => { if (s.status !== "pending") last = i; });
    for (let i = 0; i < last; i++) {
      if (steps[i].status !== "running") continue;
      steps[i].status = "done";
      steps[i].secs = disk.get(steps[i].id)?.runtime_s ?? null;
    }
  }
  // Number each step as its run folder is numbered (NN-step-id), the number
  // Verify, the failure card and the folder use. A step with no folder yet gets
  // the number it will have if nothing more is skipped; a skipped step has no
  // folder and no number (FS.stepNumbers is the same rule without folders).
  let next = 1;
  for (const s of steps) {
    const n = Number(s.n);
    if (s.n != null && Number.isFinite(n)) { s.no = n; next = n + 1; }
    else s.no = s.status === "skipped" ? null : next++;
  }
  // Metrics as of the end of each step (the server sends what changed).
  let acc = {};
  for (const s of steps) { if (s.changed) acc = { ...acc, ...s.changed }; s.metrics = acc; }
  return steps;
}

function stageSummary(steps) {
  const base = new Map((((F.base && F.base.steps) || [])).filter((s) => s.id).map((s) => [s.id, s]));
  return FS.STAGES.map((st) => {
    const own = steps.filter((s) => s.stage === st.id);
    const stat = own.map((s) => s.status);
    let status = "pending";
    if (stat.some((x) => x === "failed")) status = "failed";
    else if (stat.some((x) => x === "running")) status = "running";
    else if (stat.some((x) => x === "stopped")) status = "stopped";
    else if (own.length && stat.every((x) => x === "done" || x === "skipped")) status = stat.every((x) => x === "skipped") ? "skipped" : "done";
    else if (stat.some((x) => x === "done")) status = F.live ? "running" : "stopped";
    else if (!F.live && F.tag && stat.every((x) => x === "not_run")) status = "not_run";
    const secs = own.reduce((a, s) => a + (s.secs || 0), 0);
    const bsecs = own.reduce((a, s) => a + ((base.get(s.id) || {}).runtime_s || 0), 0);
    const last = [...own].reverse().find((s) => s.status === "done");
    // A resumed run took this stage from the run it was resumed from.
    const from = own.length && own.every((s) => s.from) ? own[0].from : "";
    return { ...st, n: STAGE_NO[st.id], status, steps: own, secs, bsecs: base.size ? bsecs : null,
      metrics: last ? last.metrics : null, from };
  });
}

// The step the output pane shows: the one picked, else (a run that stopped)
// the step it stopped at, else none (the run's own output).
function shownStep(steps) {
  if (F.sel) return steps.find((x) => x.id === F.sel) || null;
  if (F.sel === "" || F.live) return null;
  if (F.rx && ["halted", "stopped", "incomplete"].includes(F.rx.kind)) {
    // A checker that raised writes no log: show the tool step it read.
    const at = F.rx.at && F.rx.at.step && steps.find((x) => x.id === F.rx.at.step);
    if (at) return at;
    return steps.find((x) => x.status === "failed" || x.status === "stopped") || null;
  }
  return null;
}

// ------------------------------------------------------------------ paint

// Replace an element's markup only when it changed (a button that is redrawn
// under the pointer loses the click).
function setHTML(el, html) {
  if (el && el._html !== html) { el.innerHTML = html; el._html = html; }
}

function paint() {
  const sec = $("sec-pipeline");
  if (!sec) return;
  // Before the run list has come back once there is nothing true to draw
  // ("No run yet" would be a guess): the skeleton stays.
  if (!F.loaded && !state.runStart) return;
  // The page draws now: the skeleton goes first (the boxes must show to be measured).
  if (F.job) { F.job.done(); F.job = null; }
  const strip = $("fl-strip"), body = $("fl-body");
  $("fl-live").hidden = !(liveTag() && !F.live);
  F.rb?.paint();
  if (state.runStart && !F.live && !liveTag()) {
    // Run was pressed: starting, or refused (with why and the way back).
    const head = $("fl-head");
    head._key = "";
    setHTML(head, startHtml(state.runStart));
    if (strip._key !== "idle") { strip.innerHTML = stripIdle(); strip._key = "idle"; }
    body.hidden = true;
    return;
  }
  if (!F.tag) {
    paintHead(null, null);
    if (strip._key !== "idle") { strip.innerHTML = stripIdle(); strip._key = "idle"; }
    body.hidden = true;
    return;
  }
  const steps = model();
  const stages = stageSummary(steps);
  paintHead(steps, stages);
  paintStrip(stages);
  body.hidden = false;
  paintSteps(steps, stages);
  paintPane(steps);
}

function emptyHtml() {
  const has = (ctx.contextRuns() || []).length;
  return "<div class='an-verdict fl-hero is-idle'><div class='an-verdict-main'>" +
    "<div class='an-eyebrow'>Flow</div>" +
    "<h2 class='an-title'>" + (state.designDir ? (has ? "Pick a run to see it here" : "No run yet") : "Open a project first") + "</h2>" +
    "<p class='an-lede'>A run turns the Verilog into a chip in seven stages. Each stage fills in below as it goes: " +
    "the time it took, its key number, and a picture of the chip at that point.</p></div>" +
    "<div class='an-verdict-act'>" + (state.designDir
      ? "<button class='btn btn-primary' data-fl='run'>" + icon("play", { size: 14 }) + " Run the flow</button>"
      : "<button class='btn btn-primary' data-go='setup'>Go to Setup</button>") + "</div></div>";
}

// The head while a Run click's start request is out, or after the server
// refused it.
function startHtml(rs) {
  if (rs.error) {
    const from = rs.from && rs.from !== "pipeline" ? rs.from : "setup";
    const label = document.querySelector('.side-tab[data-tab="' + from + '"] .label')?.textContent.trim() || "Setup";
    return "<div class='an-verdict fl-hero is-fail' role='alert'><div class='an-verdict-main'>" +
      "<div class='an-eyebrow'>Run</div><h2 class='an-title'>The run didn't start</h2>" +
      "<p class='an-lede'>" + esc(rs.error.reason) + "</p></div>" +
      "<div class='an-verdict-act'>" +
      "<button class='btn btn-primary' data-go='" + esc(from) + "'>Back to " + esc(label) + "</button>" +
      (rs.error.mismatch ? "" : "<button class='btn btn-ghost' data-fl='run'>" + icon("play", { size: 14 }) + " Try again</button>") +
      "</div></div>";
  }
  return "<div class='an-verdict fl-hero is-live'><div class='an-verdict-main'>" +
    "<div class='an-eyebrow'><span class='fl-live-dot'></span>Starting</div>" +
    "<h2 class='an-title'>" + (rs.cancel ? "Stopping the run…" : "Starting the run…") + "</h2>" +
    "<p class='an-lede'>Asking LibreLane to start. The first start of the container can take a minute.</p>" +
    "<div class='fl-bar' role='progressbar' aria-label='Steps done' aria-valuemin='0' aria-valuemax='100' aria-valuenow='0'><span style='transform:scaleX(0)'></span></div>" +
    "</div><div class='an-verdict-act'>" +
    "<button class='btn btn-warn' data-fl='stop-start'" + (rs.cancel ? " disabled" : "") + ">" + icon("stop", { size: 13 }) + " Stop</button></div></div>";
}

function stripIdle() {
  return FS.STAGES.map((s) => "<li class='fl-tile is-pending'><div class='fl-pic'><span class='fl-pic-n'>" + two(STAGE_NO[s.id]) +
    "</span></div><div class='fl-tile-txt'><b>" + esc(s.label) + "</b><span class='fl-tile-sub'>" + esc(s.blurb) + "</span></div></li>").join("");
}

// ---- head: live / why it stopped / report card

function paintHead(steps, stages) {
  const head = $("fl-head");
  if (!steps) { head._key = ""; setHTML(head, emptyHtml()); return; }
  if (F.live) { paintLive(head, steps, stages); return; }
  head._key = "";
  setHTML(head, headHtml(steps, stages));
}

function headHtml(steps, stages) {
  const rx = F.rx;
  if (!rx) return "<div class='an-verdict fl-hero'><div class='an-verdict-main'><div class='an-eyebrow'>Run " + esc(F.tag) + "</div><h2 class='an-title'>Reading the run…</h2></div></div>";
  if (rx.kind === "halted") return failHtml(rx, stages);
  if (rx.kind === "clean" || rx.kind === "checks-failed") {
    return reportCardHtml({ tag: F.tag, rx, vf: F.vf, steps, stages, base: baseTag(), baseRs: F.base, runs: ctx.contextRuns() || [],
      branch: branchHtml(), px: rx.kind === "checks-failed" ? F.px : null });
  }
  const at = rx.step ? (stepLabel(rx.step.id) + " (step " + rx.step.n + ")") : "";
  const title = rx.kind === "stopped" ? "You stopped this run" : "This run ended before the last step";
  // Resume picks up at the stage the run was in: its earlier stages are reused.
  const rstage = rx.step ? FS.stagesOf([{ id: rx.step.id }])[0] : null;
  const canResume = rstage && FS.STAGES.findIndex((s) => s.id === rstage) > 0;
  const sub = rx.kind === "stopped"
    ? "It stopped at " + at + ". Everything before it is kept: resume to reuse it, or run again from the start."
    : "Its folder ends at " + at + " with no error: LanEx may have been closed while it ran. Resume or run it again to finish.";
  return "<div class='an-verdict fl-hero is-warn'><div class='an-verdict-main'><div class='an-eyebrow'>Run " + esc(F.tag) + "</div>" +
    "<h2 class='an-title'>" + esc(title) + "</h2><p class='an-lede'>" + esc(sub) + "</p></div>" +
    "<div class='an-verdict-act'>" +
    (canResume ? "<button class='btn btn-primary' data-fl='resume-from' data-stage='" + esc(rstage) + "'>" + icon("play", { size: 14 }) + " Resume from " + esc(FS.stageLabel(rstage)) + "</button>" : "") +
    "<button class='btn btn-ghost' data-fl='run'>" + icon("play", { size: 14 }) + " Run again</button></div></div>";
}

// The live head is built once per run and then only its text changes, so
// Stop stays under the pointer while the steps race by.
function paintLive(head, steps, stages) {
  const key = "live|" + F.tag + "|" + (state.paused ? "p" : "");
  if (head._key !== key) {
    head._key = key; head._html = null;
    head.innerHTML = "<div class='an-verdict fl-hero is-live'><div class='an-verdict-main'>" +
      "<div class='an-eyebrow'><span class='fl-live-dot'></span>Running · " + esc(F.tag) + "</div>" +
      "<h2 class='an-title fl-h-title'></h2><div class='fl-h-branch'></div><p class='an-lede fl-h-sub'></p>" +
      "<p class='fl-h-slow muted' hidden>This step can take several minutes on bigger designs. The run is still going.</p>" +
      "<div class='fl-bar' role='progressbar' aria-label='Steps done' aria-valuemin='0' aria-valuemax='100'><span></span></div>" +
      "</div><div class='an-verdict-act'>" +
      "<span class='fl-elapsed' id='fl-elapsed'></span>" +
      (state.paused ? "<button class='btn btn-primary' data-fl='resume'>" + icon("play", { size: 14 }) + " Next step</button>" : "") +
      "<button class='btn btn-warn' data-fl='stop'>" + icon("stop", { size: 13 }) + " Stop</button></div></div>";
  }
  // FS.stepCounts: the same done/total the status bar and title use.
  const nc = FS.stepCounts(steps.map((s) => s.status));
  const done = nc.done;
  const total = nc.total || 1;
  const pct = Math.min(100, Math.round((done / total) * 100));
  // "Step N of M" counts this run's own steps, as its folders (01-…) and the
  // status bar do; a resumed run's reused steps are not its own.
  const own = FS.stepCounts(steps.filter((s) => !s.from).map((s) => s.status));
  const started = steps.filter((s) => s.status !== "pending");
  const lastStarted = started.length ? started[started.length - 1].i : -1;
  const next = steps.slice(lastStarted + 1).find((s) => s.status === "pending") || null;
  // Between two steps (a moment, or longer in step-by-step mode) the next
  // one is the one to name.
  const cur = steps.filter((s) => s.status === "running").pop() || (done > 0 && !state.paused ? next : null);
  const stg = cur ? stages.find((x) => x.id === cur.stage) : null;
  const left = etaSecs(steps);
  const prep = !cur && state.prepPhase;
  // After the last step LibreLane still writes the final views and metrics,
  // and the container stops: a few seconds with no step running.
  const ending = !cur && done > 0 && !state.paused;
  const paused = !cur && state.paused ? next : null;
  const title = cur ? esc(stg.label) + " <span class='fl-sep'>›</span> " + esc(stepLabel(cur.id))
    : paused ? "Paused <span class='fl-sep'>›</span> next: " + esc(stepLabel(paused.id))
    : esc(ending ? "Finishing the run…" : prep || "Starting the run…");
  const sub = cur
    ? "Step " + own.current + " of " + own.total + (cur.status === "pending" ? " · starting" : "") +
      (left != null ? " · about " + fmtDur(left) + " left" : "") +
      (stg && stg.bsecs ? " · " + stg.label + " took " + fmtDur(stg.bsecs) + " last time" : "")
    : paused ? "Step by step: " + done + " of " + total + " done. Next step runs it."
    : ending ? "No step is running: LibreLane is writing its final results. The report card follows in a moment."
    : "The flow hasn't reported a step yet. The first start of the container can take a minute.";
  setHTML(head.querySelector(".fl-h-title"), title);
  setHTML(head.querySelector(".fl-h-branch"), branchHtml());
  setHTML(head.querySelector(".fl-h-sub"), esc(sub));
  const bar = head.querySelector(".fl-bar");
  bar.setAttribute("aria-valuenow", pct);
  bar.firstChild.style.transform = "scaleX(" + (pct / 100) + ")";
  tickElapsed();
}

function tickElapsed() {
  const el = $("fl-elapsed");
  if (!el) return;
  const t0 = state.runStartedAt;
  const e = t0 ? (Date.now() - t0) / 1000 : state.runProgress && state.runProgress.elapsed_seconds;
  el.textContent = e != null ? fmtDur(e) : "";
}

// Seconds left: the steps not done yet, at the speed of the compared-with run.
function etaSecs(steps) {
  const base = new Map((((F.base && F.base.steps) || [])).filter((s) => s.id).map((s) => [s.id, s.runtime_s || 0]));
  if (!base.size) {
    const e = state.runProgress && state.runProgress.eta_seconds;
    return typeof e === "number" && e > 0 ? e : null;
  }
  let left = 0;
  for (const s of steps) {
    if (s.status === "done" || s.status === "skipped") continue;
    const b = base.get(s.id) || 0;
    left += s.status === "running" ? Math.max(0, b - (s.secs || 0)) : b;
  }
  return left;
}

// The shared run verdict ({state, label, stage}) for the shown run: Verify's
// copy once it is read, else the run list's.
function runVerdict() {
  if (F.vf && F.vf.run_verdict) return F.vf.run_verdict;
  const row = (ctx.contextRuns() || []).find((r) => r.tag === F.tag &&
    (!F.design || !r._design || ctx.normDir(r._design) === ctx.normDir(F.design)));
  return (row && row.verdict) || null;
}

function failHtml(rx, stages) {
  const c = rx.card || {};
  // The word and stage are the shared run verdict's (Runs, the run bar and
  // Analytics say the same): a step that raised is "Failed", not "Stopped".
  const rv = runVerdict();
  const word = rv && rv.state === "stopped" ? "Stopped" : "Failed";
  const stg = stages.find((s) => s.id === ((rv && rv.stage) || rx.stage));
  const where = (stg ? stg.label + " · " : "") + stepLabel(rx.step && rx.step.id) + (rx.step ? " (step " + rx.step.n + ")" : "");
  const title = c.title || (word + " at " + stepLabel(rx.step && rx.step.id));
  const plain = c.plain || "The tool reported the error below. The step's log has the lines around it.";
  // A checker that raised names only a count; the card brings the tool's own lines.
  const ev = ((c.evidence && c.evidence.length ? c.evidence : rx.errors) || []).slice(0, 3).join("\n") || (rx.at && rx.at.text) || "";
  const fixes = (c.fixes || []).length ? fixListHtml(c.fixes, { tag: F.tag, title }) : "";
  const layoutSrc = stageSource(rx.stage, true);
  return "<div class='an-verdict fl-hero fl-fail is-fail'><div class='an-verdict-main" + (fixes ? " fl-split" : "") + "'>" +
    "<div class='fl-split-a'><div class='an-eyebrow'>" + word + " · " + esc(where) + "</div>" +
    "<h2 class='an-title'>" + esc(title) + "</h2>" + branchHtml() +
    "<p class='an-lede'>" + esc(plain) + "</p>" +
    (ev ? "<div class='fl-ev'><pre>" + esc(ev) + "</pre>" + (c.code ? "<span class='fl-code'>" + esc(c.code) + "</span>" : "") + "</div>" : "") +
    "</div>" +
    (fixes ? "<div class='fl-split-b'><div class='fl-fixes-h'>What to change</div>" + fixes +
      ((c.fixes || []).some((f) => f.kind === "setting")
        ? "<p class='fl-fix-note'>Apply shows the change, where it is saved and where the new run starts. Nothing is written until you confirm.</p>" : "") + "</div>" : "") +
    "</div><div class='an-verdict-act'>" +
    // The recommended fix is the primary action; the log is for reading.
    (rx.at ? "<button class='btn " + (fixes ? "btn-ghost" : "btn-primary") + " btn-sm' data-fl='at-error'>" + icon("file", { size: 13 }) + " Show it in the log</button>" : "") +
    (layoutSrc ? "<button class='btn btn-ghost btn-sm' data-go='layout' data-go-source='" + esc(layoutSrc.source) + "' title='The last picture before it stopped'>" + icon("grid", { size: 13 }) + " Layout at " + esc(layoutSrc.label) + "</button>" : "") +
    "<button class='btn btn-ghost btn-sm' data-fl='run'>" + icon("play", { size: 13 }) + " Run again</button></div></div>";
}

// A resumed run: the run it was resumed from, where, and what changed.
function branchHtml() {
  const b = F.rs && F.rs.branched_from;
  if (!b) return "";
  const ch = (b.changes || []).map((c) => "<code>" + esc(c.var) + "</code> " + esc(c.from || "unset") + " → " + esc(c.to) +
    (c.saved === "run" ? " <span class='muted'>(this run only)</span>" : "")).join(", ");
  return "<p class='fl-branch'>" + icon("refresh", { size: 12 }) + "<span>Resumed from " +
    (b.dir ? "<button class='fl-branch-run' data-fl='parent' data-tag='" + esc(b.tag) + "' title='Show " + esc(b.tag) + "'>" + esc(b.tag) + "</button>"
      : "<b>" + esc(b.tag) + "</b> <span class='muted'>(deleted since)</span>") +
    " at " + esc(FS.stageLabel(b.stage)) + (ch ? " · " + ch : "") + "</span></p>";
}

// The layout source for a stage: its own snapshot, or (for a stage that
// stopped) the last one before it, which is what the failure grew from.
function stageSource(stageId, before = false) {
  const list = (F.src && F.src.stages) || [];
  const hit = list.find((s) => s.id === stageId);
  if (hit || !before) return hit || null;
  const order = FS.STAGES.map((s) => s.id);
  const i = order.indexOf(stageId);
  for (let j = i - 1; j >= 0; j--) { const h = list.find((s) => s.id === order[j]); if (h) return h; }
  return null;
}

// ---- strip: built once per run, then each tile changes in place (its
// picture only when there is a new one).

function paintStrip(stages) {
  const strip = $("fl-strip");
  const key = "run|" + F.tag;
  if (strip._key !== key) {
    strip._key = key;
    strip.innerHTML = stages.map((st) =>
      "<li><button class='fl-tile' data-stage='" + st.id + "' title='" + esc(st.blurb) + "'>" +
        "<span class='fl-pic'><span class='fl-pic-n'>" + two(st.n) + "</span></span>" +
        "<span class='fl-tile-txt'></span></button></li>").join("");
  }
  const eng = (F.src && F.src.engine) || {};
  const bg = encodeURIComponent(document.body.classList.contains("theme-light") ? BG.light : BG.dark);
  for (const st of stages) {
    const tile = strip.querySelector(".fl-tile[data-stage='" + st.id + "']");
    if (!tile) continue;
    const cls = "fl-tile is-" + st.status;
    if (tile.className !== cls) tile.className = cls;
    const own = stageSource(st.id) || (st.id === "signoff" ? stageSource("final") : null);
    // A stage a resumed run reused: the picture is in the run it came from.
    const par = !own && st.from && F.psrc ? (F.psrc.stages || []).find((s) => s.id === st.id) : null;
    const src = own || par;
    const url = src && eng.ok && (st.status === "done" || st.status === "failed")
      ? "/api/layout/thumb?tag=" + encodeURIComponent(own ? F.tag : st.from) + "&source=" + encodeURIComponent(src.source) + "&w=320&h=200&bg=" + bg : "";
    const pic = tile.firstChild;
    if ((pic.dataset.src || "") !== url) {
      pic.dataset.src = url;
      pic.querySelector("img")?.remove();
      pic.classList.toggle("has-img", !!url);
      if (url) {
        const img = new Image();
        img.alt = ""; img.decoding = "async";
        img.onload = () => img.classList.add("is-in");
        img.onerror = () => { img.remove(); pic.classList.remove("has-img"); };
        img.src = url;
        pic.prepend(img);
      }
    }
    setHTML(tile.lastChild, tileText(st));
  }
}

function tileText(st) {
  if (st.from) {
    return "<span class='fl-tile-h'><span class='vf-mark is-" + MARK[st.status] + "'></span><b>" + esc(st.label) + "</b></span>" +
      "<span class='fl-tile-sub'>" + esc(keyNumber(st)) + "</span>" +
      "<span class='fl-tile-time is-reused' title='This run took the stage from " + esc(st.from) + " instead of running it again'>from " + esc(st.from) + "</span>";
  }
  const time = st.secs ? fmtDur(st.secs) : (st.status === "skipped" ? "skipped" : "");
  const d = st.secs && st.bsecs ? st.secs - st.bsecs : null;
  const slow = d != null && st.bsecs > 2 && d > Math.max(2, st.bsecs * 0.25);
  const cmp = st.bsecs && st.status !== "running" ? "<span class='fl-was" + (slow ? " is-slow" : "") + "' title='The same stage in the run this one is compared with'>was " + fmtDur(st.bsecs) + "</span>" : "";
  return "<span class='fl-tile-h'><span class='vf-mark is-" + MARK[st.status] + "'></span><b>" + esc(st.label) + "</b></span>" +
    "<span class='fl-tile-sub'>" + esc(keyNumber(st) || (st.status === "running" ? "running…" : st.status === "not_run" ? "not reached" : "")) + "</span>" +
    "<span class='fl-tile-time'>" + esc(time) + cmp + "</span>";
}

// One number from the end of the stage, read from the run's own metrics.
function keyNumber(st) {
  const m = st.metrics || {};
  const n = (k) => (typeof m[k] === "number" ? m[k] : null);
  const int = (v) => Math.round(v).toLocaleString("en-US");
  if (st.status !== "done" && st.status !== "stopped" && st.id !== "signoff") return "";
  switch (st.id) {
    case "synthesis": return n("design__instance__count") != null ? int(n("design__instance__count")) + " cells" : "";
    case "floorplan": {
      const bb = String(m["design__die__bbox"] || "").split(/\s+/).map(Number);
      return bb.length === 4 && bb.every(Number.isFinite) ? "die " + fmtUm(bb[2] - bb[0]) + " × " + fmtUm(bb[3] - bb[1]) + " µm" : "";
    }
    case "pdn": {
      // The run's own net names (VPWR/VGND on sky130 and IHP, VDD/VSS on gf180).
      const pn = (F.rs && F.rs.power_nets) || {};
      const nets = [...(pn.vdd || []), ...(pn.gnd || [])];
      return st.status === "done" ? (nets.length ? nets.join(" / ") + " rails" : "power rails") : "";
    }
    case "placement": return n("design__instance__utilization") != null ? "core " + Math.round(n("design__instance__utilization") * 100) + " % full" : "";
    case "cts": return n("clock__skew__worst_setup") != null ? "clock skew " + Math.abs(n("clock__skew__worst_setup") * 1000).toFixed(0) + " ps" : "";
    case "routing": return n("route__wirelength") != null ? fmtWire(n("route__wirelength")) + " of wire" + (n("route__drc_errors") ? " · " + int(n("route__drc_errors")) + " route DRC" : "") : "";
    case "signoff": {
      if (st.status !== "done" && st.status !== "failed") return "";
      const v = verdictOf(F.vf, F.rx);
      return v ? v.short : "";
    }
  }
  return "";
}
const fmtUm = (v) => (Math.round(v * 10) / 10).toString();
const fmtWire = (um) => (um >= 1000 ? (um / 1000).toFixed(um >= 10000 ? 0 : 1) + " mm" : Math.round(um) + " µm");

// ---- steps: every step under its stage's heading, built once per run and
// then updated row by row.

function paintSteps(steps, stages) {
  const host = $("fl-steps");
  const key = F.tag + "|" + steps.map((s) => s.id + (s.from ? "*" : "")).join(",");
  if (host._key !== key) {
    // The same run with a new step list (it just ended) keeps its place.
    const built = !!host._key;
    const keep = built && host._key.split("|")[0] === F.tag ? host.scrollTop : 0;
    host._key = key;
    host.innerHTML = stages.filter((st) => st.steps.length).map((st) =>
      "<div class='fl-stage' data-grp='" + st.id + "'><div class='fl-stage-h'><span class='vf-mark'></span>" +
        "<span class='fl-grp-n'>" + two(st.n) + "</span><b>" + esc(st.label) + "</b><span class='fl-grp-meta'></span></div>" +
        st.steps.map(rowHtml).join("") + "</div>").join("");
    F.rows = new Map([...host.querySelectorAll(".fl-step")].map((el) => [el.dataset.step, el]));
    F.heads = new Map([...host.querySelectorAll(".fl-stage")].map((el) => [el.dataset.grp, el]));
    // A resumed run: a line where its own steps begin.
    const first = steps.find((s, i) => i > 0 && !s.from && steps[i - 1].from);
    if (first && F.rows.get(first.id)) {
      const line = document.createElement("div");
      line.className = "fl-resumed";
      line.innerHTML = icon("refresh", { size: 11 }) + " <span>Resumed here · the steps above are from <b>" + esc(steps[first.i - 1].from) + "</b></span>";
      F.rows.get(first.id).before(line);
    }
    // Writing scrollTop right after a rebuild forces a layout: the very first
    // list starts at the top anyway, so it is written only after that.
    if (built) host.scrollTop = keep;
    F.followed = "";
  }
  const shown = shownStep(steps);
  for (const s of steps) {
    const el = F.rows.get(s.id);
    if (!el) continue;
    const cls = "fl-step is-" + s.status + (s.from ? " is-reused" : "") + (shown && shown.id === s.id ? " is-sel" : "");
    if (el.className !== cls) {
      el.className = cls; el.firstChild.className = "vf-mark is-" + (MARK[s.status] || "not_run");
      el.title = s.from ? "From " + s.from + ": this run started after it" : "";
    }
    const no = stepNo(s), noEl = el.querySelector(".fl-step-no");
    if (noEl && noEl.textContent !== no) noEl.textContent = no;
    const time = s.from ? "reused" : s.status === "skipped" ? "skipped" : s.status === "not_run" || s.status === "pending" ? "" : s.secs != null ? fmtDur(s.secs) : "";
    if (el.lastChild.textContent !== time) el.lastChild.textContent = time;
  }
  for (const st of stages) {
    const el = F.heads.get(st.id);
    if (!el) continue;
    const cls = "fl-stage is-" + st.status;
    if (el.className !== cls) { el.className = cls; el.querySelector(".vf-mark").className = "vf-mark is-" + MARK[st.status]; }
    const meta = (st.from ? "reused · " : st.secs ? fmtDur(st.secs) + " · " : "") + st.steps.length + " steps";
    const m = el.querySelector(".fl-grp-meta");
    if (m.textContent !== meta) m.textContent = meta;
  }
  const nc = FS.stepCounts(steps.map((s) => s.status));
  const reused = steps.filter((s) => s.from && s.status === "done").length;
  const running = F.live ? steps.find((s) => s.status === "running") : null;
  setHTML($("fl-steps-h"), "<b>Steps</b><span class='fl-pane-sub' title='Steps turned off in the config are not counted'>" +
    nc.done + " of " + nc.total + " done" + (reused ? " (" + reused + " reused)" : "") +
    (nc.skipped ? " · " + nc.skipped + " turned off" : "") + "</span>" +
    (F.live ? "<label class='lv-tog fl-follow' title='Keep the running step in view'><input type='checkbox' data-fl='follow'" + (F.follow ? " checked" : "") + "/> Follow</label>" : ""));
  // Keep the running step in view, as the old timeline did, unless the user
  // scrolled the list themselves: then a chip offers the way back.
  if (running && F.follow && F.followed !== running.id) {
    const first = !F.followed;
    F.followed = running.id;
    scrollListTo(F.rows.get(running.id), !first);
  }
  const now = $("fl-now");
  const off = !!running && !F.follow;
  now.hidden = !off;
  if (off) setHTML(now, icon("chevron", { size: 12 }) + " Now: " + esc(stepNo(running) + " · " + stepLabel(running.id)));
  // A link to a step or stage (revealInFlow), once its row is there.
  const r = F.reveal;
  const target = r && (r.step ? F.rows.get(r.step) : F.heads.get(r.stage));
  if (target) {
    F.reveal = null;
    requestAnimationFrame(() => scrollListTo(target, false, r.step ? 0.4 : 0));
  }
}

// The step's run-folder number ("–" for a step the run skipped).
function stepNo(s) { return s.no != null ? two(s.no) : "–"; }

function rowHtml(s) {
  const tool = s.id.split(".")[0];
  return "<button class='fl-step' data-step='" + esc(s.id) + "'>" +
    "<span class='vf-mark'></span>" +
    "<span class='fl-step-no'>" + stepNo(s) + "</span>" +
    "<span class='fl-step-name'>" + esc(stepLabel(s.id)) + "</span>" +
    "<span class='fl-step-tool' style='--tool:" + (TOOL[tool] || "var(--text-muted)") + "'>" + esc(TOOL_LABEL[tool] || tool) + "</span>" +
    "<span class='fl-step-time'></span></button>";
}

// Scroll the list (only the list, never the page) so `el` sits a little above
// the middle; a stage heading goes to the top.
function scrollListTo(el, smooth, at = 0.4) {
  const sc = $("fl-steps");
  if (!el || !sc || !sc.clientHeight) return;
  const top = Math.max(0, el.offsetTop - (at ? sc.clientHeight * at : 0));
  const calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  F.autoScroll = Date.now();
  sc.scrollTo({ top, behavior: smooth && !calm ? "smooth" : "auto" });
}

// ---- output pane: the run's output, or one step

function paintPane(steps) {
  const s = shownStep(steps);
  const head = $("fl-insp-h");
  const page = $("fl-page");
  if (!s) {
    // The run's own output: live as it prints, or LibreLane's flow.log after.
    if (F.tab !== "log" && F.tab !== "time") F.tab = "log";
    const watched = !F.live && F.tag === state.liveTag && liveRows().length > 0;
    const tabs = F.live ? "" : tabsHtml([["log", watched ? "Output" : "Run log"], ["time", "Where the time went"]]);
    const [title, sub] = F.live ? ["Live output", "the whole run as LibreLane prints it · pick a step for only its log"]
      : watched ? ["Run output", "the whole run as LibreLane printed it · pick a step for its log"]
      : ["Run log", "flow.log, LibreLane's own messages · pick a step for its tool's full log"];
    setHTML(head, "<div class='fl-insp-top'>" + (F.live ? "<span class='fl-live-dot'></span>" : "") +
      "<h3>" + title + "</h3><span class='fl-pane-sub'>" + sub + "</span>" + tabs + "</div>");
    if (F.tab === "time") { showPage(true); setHTML(page, timeSpentHtml(steps)); return; }
    showPage(false);
    if (F.live) setLogSource("live", { live: true });
    else if (watched) setLogSource("stream:" + F.tag, {});
    else setLogSource("run:" + F.tag, {});
    return;
  }
  const runningLive = F.live && s.status === "running";
  const nRep = F.stepMeta && F.stepMeta.key === F.tag + "|" + s.id ? (F.stepMeta.reports || []).length : 0;
  if (F.tab === "time" || (F.tab === "reports" && !nRep)) F.tab = "log";
  const back = F.live ? "Live output" : "Run log";
  setHTML(head, "<div class='fl-insp-top'>" +
      "<button class='fl-back' data-fl='unpick' title='Back to the " + (F.live ? "live output" : "run log") + "'>" + icon("chevron", { size: 12 }) + " " + back + "</button>" +
      "<span class='vf-mark is-" + (MARK[s.status] || "not_run") + "'></span><h3>" + esc(stepLabel(s.id)) + "</h3>" +
      toolTag(s.id) +
      tabsHtml([["log", "Log"], ["about", "About this step"]].concat(nRep ? [["reports", "Reports " + nRep]] : [])) + "</div>" +
    "<div class='fl-insp-meta'>" + stepMetaHtml(s) + "</div>");
  if (F.tab === "about") { showPage(true); setHTML(page, aboutHtml(s)); return; }
  if (F.tab === "reports") { showPage(true); setHTML(page, reportsHtml()); wireFileActions(page); return; }
  showPage(false);
  if (runningLive) setLogSource("live:" + s.id, { live: true });
  else setLogSource("step:" + F.tag + "|" + s.id + "|" + s.status, { step: s });
}

function showPage(on) {
  $("fl-page").hidden = !on;
  $("fl-log").hidden = on;
}

function tabsHtml(tabs) {
  return "<span class='fl-tabs' role='tablist'>" + tabs.map(([id, label]) =>
    "<button role='tab' data-fl-tab='" + id + "' aria-selected='" + (F.tab === id) + "'>" + esc(label) + "</button>").join("") + "</span>";
}

function toolTag(id) {
  const tool = String(id).split(".")[0];
  return "<span class='fl-step-tool' style='--tool:" + (TOOL[tool] || "var(--text-muted)") + "'>" + esc(TOOL_LABEL[tool] || tool) + "</span>";
}

function stepMetaHtml(s) {
  const bs = ((F.base && F.base.steps) || []).find((x) => x.id === s.id);
  const src = (F.src && [...(F.src.stages || []), ...(F.src.steps || [])].find((x) => x.step === s.dir)) || null;
  const odb = s.dir && /^(OpenROAD|Odb)\./.test(s.id) && s.status === "done" && F.rs && F.rs.design_name ? s.dir + "/" + F.rs.design_name + ".odb" : "";
  return "<button class='fl-id' data-fl='copy-id' data-id='" + esc(s.id) + "' title='Copy the step ID'>" + esc(s.id) + " " + icon("file", { size: 11 }) + "</button>" +
    "<span>" + esc(FS.stageLabel(s.stage)) + (s.no == null ? " · turned off" : " · step " + s.no) + "</span>" +
    (s.secs != null && s.status !== "running" ? "<span>" + fmtDur(s.secs) + (bs && bs.runtime_s ? " <span class='muted'>(was " + fmtDur(bs.runtime_s) + ")</span>" : "") + "</span>" : "") +
    (s.peak ? "<span>" + Math.round(s.peak) + " MiB peak</span>" : "") +
    "<span class='fl-insp-acts'>" +
      (src ? "<button class='btn btn-ghost btn-xs' data-go='layout' data-go-source='" + esc(src.source) + "'>" + icon("grid", { size: 12 }) + " Show in Layout</button>" : "") +
      (odb ? "<button class='btn btn-ghost btn-xs' data-fl='openroad' data-path='" + esc(odb) + "' title='Open the design as this step left it'>" + icon("popout", { size: 12 }) + " Open in OpenROAD</button>" : "") +
    "</span>";
}

// What a step does (LibreLane's own docstring), what it changed, the
// settings it reads.
function aboutHtml(s) {
  const info = F.stepInfo.get(s.id.replace(/-\d+$/, "")) || {};
  const what = docOf(info.help_md);
  const vars = rankVars(info.config_vars || [], s.stage);
  const changed = Object.entries(s.changed || {}).filter(([k]) => !/__corner:|__iter:|__per_|__class:|__type:/.test(k)).slice(0, 10);
  return (what ? "<p class='fl-what'>" + esc(what) + "</p>" : "<p class='fl-what muted'>LibreLane has no description for this step.</p>") +
    (changed.length ? "<div class='an-sub'>What it changed</div><dl class='fl-kv'>" + changed.map(([k, v]) => {
      const sh = AM.show(k, v);
      return "<div><dt title='" + esc(k) + "'>" + esc(AM.labelOf(k)) + "</dt><dd>" + esc(sh.text) + (sh.unit ? " <small>" + esc(sh.unit) + "</small>" : "") + "</dd></div>";
    }).join("") + "</dl>" : "") +
    (vars.length ? "<div class='an-sub'>Settings it reads <span class='muted'>(" + vars.length + ")</span></div><div class='fl-vars'>" + vars.map((v) =>
      "<button class='fl-var' data-go='setup' data-go-setting='" + esc(v) + "' title='Find " + esc(v) + " in Setup'>" + esc(v) + "</button>").join("") + "</div>" : "");
}

function reportsHtml() {
  const m = F.stepMeta || {};
  return "<div class='an-sub'>Reports this step wrote</div>" + (m.reports || []).map((p) =>
    "<div class='report-row'><span class='rname'>" + esc(p) + "</span>" + fileActionsHtml(F.tag, (m.dir ? m.dir + "/" : "") + p) + "</div>").join("");
}

// Where the time went (ORFS ends its report the same way), each row a way
// into that step.
function timeSpentHtml(steps) {
  const ran = steps.filter((s) => s.secs > 0);
  const total = ran.reduce((a, s) => a + s.secs, 0);
  const top = ran.slice().sort((a, b) => b.secs - a.secs).slice(0, 12);
  const max = top.length ? top[0].secs : 1;
  return "<div class='fl-insp-meta'><span>" + fmtDur(total) + " over " + ran.length + " steps</span></div>" +
    (top.length ? "<ol class='fl-time'>" + top.map((s) =>
      "<li><button class='fl-time-row' data-step='" + esc(s.id) + "'><span class='fl-time-name'>" + esc(stepLabel(s.id)) +
        " <span class='muted'>" + esc(FS.stageLabel(s.stage)) + "</span></span>" +
        "<span class='fl-time-bar'><span style='width:" + Math.max(2, Math.round((s.secs / max) * 100)) + "%'></span></span>" +
        "<span class='fl-time-v'>" + fmtDur(s.secs) + " <small>" + Math.round((s.secs / (total || 1)) * 100) + " %</small></span></button></li>").join("") + "</ol>" : "");
}

// ---- the log on screen

async function setLogSource(src, { live = false, step = null } = {}) {
  if (F.logSrc === src) return;
  F.logSrc = src;
  const L = F.log;
  L.setFollowable(live);
  if (src === "live" || src.startsWith("stream:")) {
    // The whole run as it printed; after it ends the same lines stay (the
    // run you just watched), ending at how it went.
    L.setRaw("");
    L.setText(liveLines().join("\n"), { empty: "The run's output appears here as it goes." });
    if (live) L.setFollow(true); else L.end();
    return;
  }
  if (src.startsWith("live:")) {
    L.setRaw("");
    L.setText(liveLines(src.slice(5)).join("\n"), { empty: "The step's output appears here as it runs." });
    L.setFollow(true);
    return;
  }
  if (src.startsWith("run:")) {
    L.setText("", { empty: "Loading the run log…" });
    const url = api.runFileUrl(F.tag, "flow.log");
    let text = "";
    try { const r = await fetch(url); if (r.ok) text = await r.text(); } catch (_e) {}
    if (F.logSrc !== src) return;
    L.setRaw(text ? url : "");
    // Rich's markup tags are left in the file ("[repr.filename]…"): drop them.
    L.setText(text.replace(/\[\/?repr\.[a-z_]+\]/g, ""), { empty: "This run has no flow.log." });
    const at = F.rx && F.rx.kind === "halted" ? L.firstOf("err") : -1;
    if (at >= 0) L.reveal(at);
    return;
  }
  // One step's log file.
  const s = step;
  L.setRaw("");
  if (s.status === "not_run" || s.status === "skipped" || s.status === "pending") {
    L.setText("", { empty: s.status === "skipped" ? "The flow skipped this step (a setting turns it off)." : "This step hasn't run." });
    return;
  }
  L.setText("", { empty: "Loading the log…" });
  let r = null;
  try { r = await api.runStepLog(s.dir || s.id, F.tag); } catch (_e) { r = null; }
  if (F.logSrc !== src) return;
  if (!r || r.ok === false) { L.setText("", { empty: (r && r.reason) || "No log for this step." }); return; }
  const rel = r.dir && r.log_file ? r.dir + "/" + r.log_file : "";
  L.setRaw(rel ? api.runFileUrl(F.tag, rel) : "");
  let text = r.log || "";
  // The server sends the tail of a long log; read the whole file for the viewer.
  if (r.truncated && rel) {
    try { const res = await fetch(api.runFileUrl(F.tag, rel)); if (res.ok) text = await res.text(); } catch (_e) {}
    if (F.logSrc !== src) return;
  }
  L.setText(text, { empty: "This step wrote no log." });
  F.stepMeta = { key: F.tag + "|" + s.id, dir: r.dir || "", reports: (r.reports || []).slice(0, 24) };
  // A failed step opens its log at the first error.
  const at = F.rx && F.rx.at && rel && F.rx.at.path === rel ? F.rx.at.line - 1 : -1;
  const first = at >= 0 ? at : (s.status === "failed" ? L.firstOf("err") : -1);
  if (first >= 0) L.reveal(first);
  if (F.stepMeta.reports.length) schedule();   // the Reports tab can show now
}

// The settings a step reads, the ones for its own stage first (and any a fix
// names), so Global placement leads with PL_ and FP_ rather than the alphabet.
const STAGE_VARS = {
  synthesis: /^(SYNTH_|CLOCK_|MAX_FANOUT|VERILOG_)/, floorplan: /^(FP_|DIE_AREA|CORE_AREA|BOTTOM_MARGIN|TOP_MARGIN|LEFT_MARGIN|RIGHT_MARGIN)/,
  pdn: /^(PDN_|FP_PDN_)/, placement: /^(PL_|GPL_|DPL_|FP_CORE_UTIL|IO_)/, cts: /^(CTS_|CLOCK_)/,
  routing: /^(GRT_|DRT_|ROUTING|RT_|DIODE_)/, signoff: /^(MAGIC_|KLAYOUT_|LVS_|STA_|RCX_|ERROR_ON_)/,
};
function rankVars(vars, stage) {
  const fix = new Set((((F.rx && F.rx.card) || {}).fixes || []).map((x) => x.var));
  const rx = STAGE_VARS[stage];
  const rank = (v) => (fix.has(v) ? 0 : rx && rx.test(v) ? 1 : 2);
  return vars.filter((v) => !/^(DESIGN_NAME|PDK|STD_CELL_LIBRARY|.*_LIBS?|.*_LEFS?)$/.test(v))
    .sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

// LibreLane's docstring for a step: the text of its first eval-rst block.
function docOf(md) {
  const m = /```\{eval-rst\}\s*([\s\S]*?)```/.exec(md || "");
  if (!m) return "";
  return m[1].replace(/`([^`<]+?)\s*<[^>]+>`_+/g, "$1").replace(/``([^`]+)``/g, "$1").replace(/:[a-z]+:`([^`]+)`/g, "$1")
    .replace(/\s+/g, " ").trim().slice(0, 900);
}

// "OpenROAD.GlobalPlacement" -> "Global Placement" (LibreLane's own title when
// it has one, else Analytics' name for it, so both pages agree).
export function stepLabel(id) {
  if (!id) return "";
  const info = F.stepInfo.get(String(id).replace(/-\d+$/, "")) || (state.steps || []).find((x) => x.id === String(id).replace(/-\d+$/, ""));
  const rep = /-(\d+)$/.exec(id);
  const t = info && /###\s+(.+)/.exec(info.help_md || "");
  if (t) return t[1].trim() + (rep ? " (" + (Number(rep[1]) + 1) + ")" : "");
  return AM.stepName({ id });
}

// ------------------------------------------------------------------ wiring

function wireOnce() {
  if (F.wired) return;
  F.wired = true;
  const sec = $("sec-pipeline");
  F.rb = mountRunBar($("flow-runbar"), { baseline: true, live: () => (F.live ? F.tag : "") });
  F.log = new LogView($("fl-log"), { follow: false });
  ctx.onContext((d) => {
    if (!visible() || d.why === "loaded" || d.why === "settled") return;
    if (d.why === "run" || d.why === "project" || d.why === "scope") F.pinned = !!liveTag();
    if (d.why === "baseline") { F.base = null; load(++F.tok); return; }
    renderFlow();
  });
  onLiveLog((batch) => {
    if (!F.log || !F.logSrc.startsWith("live")) return;
    if (F.logSrc === "live") F.log.append(batch.map((l) => l.t));
    else {
      const id = F.logSrc.slice(5);
      F.log.append(batch.filter((l) => l.step === id).map((l) => l.t));
    }
  });
  $("fl-live")?.addEventListener("click", () => { F.pinned = false; renderFlow(); });
  // Scrolling the list by hand stops it following the run (as in a terminal).
  const list = $("fl-steps");
  const stopFollow = () => { if (F.live && F.follow) { F.follow = false; schedule(); } };
  list.addEventListener("wheel", stopFollow, { passive: true });
  list.addEventListener("touchmove", stopFollow, { passive: true });
  list.addEventListener("keydown", (e) => { if (/^(Arrow|Page|Home|End)/.test(e.key)) stopFollow(); });
  list.addEventListener("pointerdown", (e) => { if (e.offsetX > list.clientWidth) stopFollow(); });
  $("fl-now").addEventListener("click", () => { F.follow = true; F.followed = ""; schedule(); });
  sec.addEventListener("change", (e) => {
    if (e.target.matches("[data-fl=follow]")) { F.follow = e.target.checked; F.followed = ""; schedule(); }
  });
  sec.addEventListener("click", (e) => {
    const t = e.target;
    const tile = t.closest(".fl-tile[data-stage]");
    if (tile) { scrollListTo(F.heads.get(tile.dataset.stage), true, 0); if (F.live) F.follow = false; schedule(); return; }
    const tab = t.closest("[data-fl-tab]");
    if (tab) { F.tab = tab.dataset.flTab; paint(); return; }
    const row = t.closest(".fl-step[data-step], .fl-time-row[data-step]");
    if (row) {
      const id = row.dataset.step;
      const running = F.live && row.classList.contains("is-running");
      F.sel = id;
      if (F.tab === "time") F.tab = "log";
      // Picking a step that is not the running one stops the list following.
      if (F.live) F.follow = running;
      paint();
      if (row.classList.contains("fl-time-row")) scrollListTo(F.rows.get(id), true);
      return;
    }
    const a = t.closest("[data-fl]");
    if (!a) return;
    const act = a.dataset.fl;
    if (act === "run") document.getElementById("btn-run-global")?.click();
    else if (act === "stop") api.cancelRun().catch(() => {});
    else if (act === "stop-start") import("./setup.js").then((m) => { if (!m.cancelStart()) api.cancelRun().catch(() => {}); paint(); });
    else if (act === "resume") api.resumeRun().catch(() => {});
    else if (act === "resume-from") {
      import("./setup.js").then((m) => m.resumeFrom(a.dataset.stage))
        .then((why) => { if (why) toast.show(why, "warn", 9000); })
        .catch((e) => toast.show("Couldn't resume: " + (e.message || e), "error"));
    }
    else if (act === "parent") ctx.setRun(a.dataset.tag);
    else if (act === "unpick") { F.sel = ""; F.tab = "log"; if (F.live) { F.follow = true; F.followed = ""; } paint(); }
    else if (act === "at-error") {
      // The log with the first error: the stopped step's, or the tool step a
      // checker read (Verilator.Lint behind Checker.LintErrors).
      const st = F.rx && F.rx.at && F.rx.at.step ? { id: F.rx.at.step } : F.rx && F.rx.step;
      if (st) {
        F.sel = st.id; F.tab = "log"; F.logSrc = "";
        paint();
        scrollListTo(F.rows.get(st.id), true);
        $("fl-body")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    } else if (act === "copy-id") {
      navigator.clipboard?.writeText(a.dataset.id).then(() => toast.show("Copied " + a.dataset.id, "success", 1800)).catch(() => {});
    } else if (act === "openroad") {
      import("./layouttools.js").then((m) => m.launchTool("openroad", F.tag, { path: a.dataset.path }));
    } else if (act === "command") copyCommand();
  });
  $("fl-copy-cmd")?.addEventListener("click", copyCommand);
  // The page takes the window's height: the panes get what the run bar, the
  // head and the strip leave (flow.css reads --fl-h and data-fit).
  const work = sec.closest(".work");
  if (work && window.ResizeObserver) {
    new ResizeObserver(() => {
      const h = work.clientHeight;
      sec.style.setProperty("--fl-h", h + "px");
      sec.dataset.fit = h < 720 ? "short" : "tall";
    }).observe(work);
  }
  // The clocks tick without repainting the page: elapsed, and the running step.
  setInterval(() => {
    if (!F.live || !visible()) return;
    tickElapsed();
    const st = state.stepStatuses || {};
    const id = (state.pipeline || []).map((p) => p.id).reverse().find((k) => st[k] === "running");
    const t = id && (state.stepTiming || {})[id];
    const el = id && F.rows.get(id);
    if (el && t && t.start) el.lastChild.textContent = fmtDur((Date.now() - t.start) / 1000);
    // A step past a minute gets a calm line, so a long one doesn't look stuck.
    const slow = document.querySelector("#fl-head .fl-h-slow");
    if (slow) slow.hidden = !(t && t.start && !t.end && Date.now() - t.start > 60000);
  }, 1000);
}

async function copyCommand() {
  let cmd = "";
  try {
    const m = await api.runGuiMeta(F.tag);
    const c = (m && (m.cli_command || (m.meta && m.meta.cli_command))) || {};
    cmd = c[c.recommended || "container"] || c.container || c.local || "";
  } catch (_e) {}
  if (!cmd) { toast.show("This run has no recorded command (it was not started from LanEx).", "warn"); return; }
  try { await navigator.clipboard.writeText(cmd); toast.show("Copied the command for " + F.tag, "success", 2500); }
  catch (_e) { toast.show(cmd, "info", 0); }
}
