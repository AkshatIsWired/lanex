// analytics.js — the Analytics tab: one run's results, read top-down.
//
// Order follows what designers check after a flow (and what the commercial
// QoR dashboards lead with): is the run clean -> PPA headline -> timing per
// corner -> area -> power -> routing -> how the flow got there (per-stage QoR,
// runtime, warnings) -> trend across runs -> compare -> every raw metric.
// Each number is LibreLane's own value from metrics.json (or a step's
// state_out.json), shown in its natural unit; the exact value is one hover
// away and the source file one click away. Deltas are against a baseline run
// the user picks (default: the previous clean run of the same design), and
// better/worse colouring is used only when LibreLane's metric registry says
// which direction is better.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import * as ctx from "./context.js";
import { normDir } from "./context.js";
import { mountRunBar } from "./runbar.js";
import { toast } from "./toast.js";
import { toCsv, downloadCsv } from "./csvutil.js";
import { wireScrollSpy } from "./jumpnav.js";
import { icon } from "./icons.js";
import { provBtnHtml, wireProvBtns } from "./provenance.js";
import * as M from "./analytics-model.js";
import * as V from "./verify-model.js";
import { fmtDur } from "./reportcard.js";
import * as C from "./analytics-charts.js";
import { localeNum, localeDateTime } from "./intlcache.js";
import { loadingStart, skel } from "./loading.js";

const esc = (s) => fmt.escape(s == null ? "" : String(s));

// ---------- state ---------------------------------------------------------------

let _meta = new Map();          // LibreLane metric registry: name -> {higher_is_better, critical}
let _tag = "";                  // the run on screen (the app's, context.js)
let _baseTag = "";              // what it is compared with ("" = nothing)
let _v = {};                    // selected run's metrics
let _b = null;                  // baseline metrics (or null)
let _ctx = null;                // everything the sections render from
let _token = 0;                 // guards against out-of-order loads
let _job = null;                // the first load's skeleton (loading.js), until the first paint
function loadDone() { if (_job) { _job.done(); _job = null; } }
const _trendCache = new Map();  // design dir -> trends payload
let _allFilter = "all";         // All metrics: all | problems | changed
let _partial = null;            // {n, name, dir} when values come from a step's state_out.json

async function loadMeta() {
  if (_meta.size) return _meta;
  try {
    const list = await api.metricsCatalog();
    _meta = new Map(list.map((m) => [m.name, m]));
  } catch (_e) { _meta = new Map(); }
  return _meta;
}

const has = (k) => _v[k] !== undefined && _v[k] !== null;
const g = (k) => _v[k];

// ---------- small renderers -------------------------------------------------------

// A value in its natural unit. Exact raw value in the title.
function vh(key, v, { cls = "" } = {}) {
  if (v === undefined) v = _v[key];
  const s = M.show(key, v);
  return "<span class='an-v " + cls + "' title='" + esc(s.title) + "'>" + esc(s.text) + "</span>" +
    (s.unit ? "<span class='an-u'>" + esc(s.unit) + "</span>" : "");
}

// The source of a metric on screen: its line in final/metrics.json, or for a
// run that stopped, in the state_out.json of the step it was read from (the
// last finished one, or *step* for a per-stage value).
function provBtn(key, tag, step) {
  if (!key || !(tag || _tag)) return "";
  step = step || (_partial && !tag ? _partial.dir : "");
  return provBtnHtml(step ? { kind: "metric", key, tag: tag || _tag, step } : { kind: "metric", key, tag: tag || _tag },
    "Show '" + key + "' in " + (step ? step + "/state_out.json" : "this run's metrics.json") + " (the raw LibreLane value)");
}

// The source of a setting: its line in the run's resolved.json.
function varBtn(name) {
  if (!name || !_tag) return "";
  return provBtnHtml({ kind: "var", key: name, tag: _tag }, "Show " + name + " in this run's resolved.json (the value LibreLane used)");
}

// Change vs the baseline for one metric. Unit-aware: slack in ns, ratios in
// percentage points, power with an SI prefix, the rest as a difference plus %.
function deltaHtml(key, { short = false } = {}) {
  if (!_b) return "";
  const a = _v[key], b = _b[key];
  const dir = M.directionOf(_meta, key);
  const d = M.delta(a, b, dir);
  if (!d) return "";
  const { base } = M.parseKey(key);
  const u = M.unitOf(base);
  const bs = M.show(key, b);
  const tip = "vs " + _baseTag + ": " + bs.text + (bs.unit ? " " + bs.unit : "") +
    (dir ? "\n" + (dir > 0 ? "Higher" : "Lower") + " is better (LibreLane's metric registry)" : "\nLibreLane doesn't say which direction is better, so this isn't coloured");
  if (d.verdict === "same") return short ? "" : "<span class='an-delta same' data-an-tip='" + esc(tip) + "' tabindex='0'>no change vs " + esc(_baseTag) + "</span>";
  let txt;
  if (u === "ns") txt = M.signed(d.diff, 3) + " ns";
  else if (u === "ratio") txt = M.signed(d.diff * 100, 1) + " pts";
  else if (u === "W") { const r = M.si(Math.abs(d.diff), "W"); txt = (d.diff > 0 ? "+" : "−") + r.text + " " + r.unit; }
  else if (u === "V") txt = M.signed(d.diff * 1000, 3) + " mV";
  else {
    const n = Number.isInteger(d.diff) ? M.num(Math.abs(d.diff)) : M.num(Math.abs(Number(d.diff.toPrecision(6))));
    txt = (d.diff > 0 ? "+" : "−") + n;
    if (d.pct !== null && Math.abs(d.pct) >= 0.05 && !short) txt += " (" + (d.pct > 0 ? "+" : "−") + Math.abs(d.pct).toFixed(Math.abs(d.pct) >= 10 ? 0 : 1) + "%)";
  }
  const arrow = d.diff > 0 ? "▲" : "▼";
  return "<span class='an-delta " + d.verdict + "' data-an-tip='" + esc(tip) + "' tabindex='0'><span aria-hidden='true'>" + arrow + "</span> " + esc(txt) + "</span>";
}

function sectionHead(eyebrow, title, lede, actions = "") {
  return "<header class='an-head'><div><div class='an-eyebrow'>" + esc(eyebrow) + "</div>" +
    "<h2 class='an-title'>" + title + "</h2>" + (lede ? "<p class='an-lede'>" + lede + "</p>" : "") + "</div>" +
    (actions ? "<div class='an-head-act'>" + actions + "</div>" : "") + "</header>";
}

function goBtn(tab, label, section = "") {
  return "<button class='btn btn-ghost btn-sm' data-go='" + tab + "'" + (section ? " data-go-section='" + section + "'" : "") + ">" +
    esc(label) + " " + icon("chevron", { size: 13 }) + "</button>";
}

function notReached(what) {
  return "<div class='an-none'>" + esc(what) + "</div>";
}

function fact(label, key, { tip = "", value, extra = "", delta = true } = {}) {
  if (value === undefined && !has(key)) return "";
  return "<div class='an-fact'><dt" + (tip ? " data-an-tip='" + esc(tip) + "' tabindex='0' class='has-tip'" : "") + ">" + esc(label) + "</dt>" +
    "<dd>" + (value !== undefined ? value : vh(key)) + extra + (delta && key ? " " + deltaHtml(key, { short: true }) : "") + (key ? provBtn(key) : "") + "</dd></div>";
}

// ---------- page entry ---------------------------------------------------------------

export async function renderAnalyticsFull() {
  const body = document.getElementById("an-body");
  if (!body) return;
  wireOnce();
  _trendCache.clear();   // a run may have finished since the tab was last shown
  // First visit: a skeleton of the sections after 300 ms (never an empty state before the runs came back).
  loadDone();
  if (!_ctx) _job = loadingStart(body, { skeleton: skel.cards(3) + skel.block(200), label: "Analytics" });
  await loadMeta();
  const runs = await ctx.loadRuns();
  // The list could not be loaded at all (LanEx busy or asleep): leave the page
  // as it is; context.js retries and the page repaints when runs arrive.
  if (!runs.length && ctx.runsLoadFailed()) { loadDone(); return; }
  if (!runs.length || !ctx.contextRun()) {
    loadDone();
    body.classList.add("is-empty");
    document.getElementById("an-empty").hidden = false;
    return;
  }
  body.classList.remove("is-empty");
  document.getElementById("an-empty").hidden = true;
  await selectRun(ctx.contextRun());
}

function wireOnce() {
  const sec = document.getElementById("sec-analytics");
  if (!sec || sec._anWired) return;
  sec._anWired = true;
  C.wireTips(sec);
  mountRunBar(document.getElementById("analytics-runbar"), { baseline: true });
  ctx.onContext(async (d) => {
    if (!sec.classList.contains("section-active") || d.why === "loaded" || d.why === "settled") return;   // it renders when shown
    if (d.why === "baseline") { _baseTag = ctx.contextBaseline(); await loadBaseline(); paint(); return; }
    renderAnalyticsFull();
  });
  document.getElementById("btn-refresh-analytics").addEventListener("click", () => renderAnalyticsFull());
  document.getElementById("btn-analytics-csv").addEventListener("click", exportCsv);
  document.getElementById("btn-analytics-settings").addEventListener("click", async () => {
    const { openResolvedSettings } = await import("./finalsettings.js");
    openResolvedSettings(_tag);
  });
  // Jump bar: scroll + spy.
  const nav = document.getElementById("analytics-jump");
  nav.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-jump]");
    if (!btn) return;
    const t = document.getElementById(btn.dataset.jump);
    if (!t) return;
    if (t.tagName === "DETAILS") t.open = true;
    t.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  wireScrollSpy(nav);
  // Delegated actions inside the rendered sections.
  sec.addEventListener("click", (e) => {
    // a used cell opens in the Cells library (function, layout, drive strengths)
    const cellRow = e.target.closest("#an-cells-rows .an-bar-row");
    if (cellRow) {
      const name = (cellRow.dataset.anTip || "").split("\n")[0];
      if (name) import("./cells.js").then((m) => m.openCell(name));
      return;
    }
    const pick = e.target.closest("[data-an-run]");
    if (pick && ctx.contextRow(pick.dataset.anRun)) {
      ctx.setRun(pick.dataset.anRun);
      document.getElementById("an-overview")?.scrollIntoView({ behavior: "smooth", block: "start" });
      return;
    }
    const exp = e.target.closest("[data-an-expand]");
    if (exp) { toggleKids(exp); return; }
    const more = e.target.closest("[data-an-more]");
    if (more) { more.closest(".an-card")?.classList.toggle("show-all"); more.textContent = more.closest(".an-card")?.classList.contains("show-all") ? "Show fewer" : more.dataset.anMore; return; }
    const f = e.target.closest("[data-an-filter]");
    if (f) { _allFilter = f.dataset.anFilter; renderAll(); return; }
  });
  sec.addEventListener("input", (e) => {
    if (e.target.id === "an-all-search") renderAllRows();
    if (e.target.id === "an-cells-search") renderCellRows();
  });
}

async function selectRun(tag) {
  const my = ++_token;
  const row = ctx.contextRow(tag);
  _tag = tag;
  _baseTag = ctx.contextBaseline();
  const body = document.getElementById("an-body");
  body.classList.add("is-loading");

  const designDir = (row && row._design) || state.designDir;
  const [view, stages, cells, trends, signoff] = await Promise.all([
    api.run(tag).catch(() => null),
    api.runStages(tag).catch(() => null),
    api.cellUsage(tag).then((r) => (r && r.cells) || []).catch(() => []),
    loadTrends(designDir),
    api.verify(tag).catch(() => null),
  ]);
  if (my !== _token) return;
  _v = (view && view.metrics && view.metrics.values) || {};
  await loadBaseline();
  if (my !== _token) return;
  const steps = stages && Array.isArray(stages.steps) ? M.accumulate(M.stageSteps(stages.steps)) : [];
  // A run that stopped has no final metrics.json; LibreLane still saved the
  // metrics as of each finished step, so show the last finished step's set
  // (and say so) instead of an empty page.
  _partial = null;
  if (!Object.keys(_v).length) {
    const last = [...steps].reverse().find((s) => s.status === "done" && s.metrics && Object.keys(s.metrics).length);
    if (last) { _v = last.metrics; _partial = { n: last.n, name: M.stepName(last), dir: last.dir }; }
  }
  _ctx = { row: row || {}, view: view || {}, stages: stages || {}, steps, cells, trends, designDir, signoff };
  body.classList.remove("is-loading");
  loadDone();             // before drawing: the charts measure their boxes
  if (!view && !_partial) {
    document.getElementById("an-overview").innerHTML = "<div class='empty'><span class='ico'>" + icon("alert", { size: 40 }) +
      "</span><h3>Could not load " + esc(tag) + "</h3><p>The run folder may have been moved or deleted. Refresh, or pick another run.</p></div>";
    return;
  }
  paint();
}

async function loadBaseline() {
  _b = null;
  if (!_baseTag) return;
  try {
    const bv = await api.run(_baseTag);
    _b = (bv && bv.metrics && bv.metrics.values) || null;
  } catch (_e) { _b = null; }
}

const TREND_KEYS = [
  "timing__setup__ws", "timing__hold__ws", "design__instance__utilization",
  "design__instance__area__stdcell", "power__total", "route__wirelength", "route__drc_errors",
];

async function loadTrends(dir) {
  const k = normDir(dir || "");
  if (_trendCache.has(k)) return _trendCache.get(k);
  let t = null;
  try { t = await api.trends(dir || undefined, TREND_KEYS); } catch (_e) { t = null; }
  _trendCache.set(k, t);
  return t;
}

// The first screen (overview, timing) is drawn at once; the sections below it
// follow one per task, so no single task builds all 9k nodes (half a second
// on a slow laptop). A newer paint drops the rest of an older one.
let _paintSeq = 0;
function paint() {
  if (!_ctx) return;
  const seq = ++_paintSeq;
  const body = document.getElementById("an-body");
  C.resetCharts();
  renderOverview();
  renderTiming();
  C.drawCharts(body);
  const rest = [renderArea, renderPower, renderRouting, renderFlow, renderHistory, renderAll];
  const next = () => {
    if (seq !== _paintSeq || !_ctx) return;
    const fn = rest.shift();
    if (fn) { fn(); setTimeout(next, 0); return; }
    wireProvBtns(body);
    C.drawCharts(body);
    C.watchResize(body);
  };
  setTimeout(next, 0);
}

// ---------- 1. Overview ---------------------------------------------------------------------

function stoppedStep() {
  const s = (_ctx.stages.steps || []).find((x) => x.status === "stopped");
  return s ? _ctx.steps.find((x) => x.n === s.n) || s : null;
}

function renderOverview() {
  const el = document.getElementById("an-overview");
  const { row, stages } = _ctx;
  // Each check's status is the Verify tab's (controller/verify.py mirrors
  // LibreLane's checkers and the run's ERROR_ON_* switches), so the two pages
  // can never disagree; the metric-only rule is the fallback.
  const checks = M.withSignoff(M.evalChecks(_v, _meta), _ctx.signoff);
  const fails = checks.filter((c) => c.status === "fail");
  const warns = checks.filter((c) => c.status === "warn");
  const ran = checks.filter((c) => c.status !== "absent");
  const stopped = stoppedStep();
  const completed = stages.completed !== undefined ? stages.completed : row.success;

  let tone, title, lede;
  if (!completed || stopped) {
    tone = "fail";
    title = stopped
      ? "Run stopped at " + esc(M.stepName(stopped)) + " <span class='an-title-sub'>step " + stopped.n + " · " + esc(stopped.stage || "") + "</span>"
      : "Run did not finish";
    lede = (_partial
      ? "There is no final metrics.json, so the numbers below are the metrics LibreLane saved after step " + _partial.n + " (" + esc(_partial.name) + "), the last step that finished."
      : "The numbers below come from the steps that finished.") + " The step's log says why it stopped.";
  } else if (fails.length) {
    tone = "fail";
    title = fails.length + " check" + (fails.length === 1 ? "" : "s") + " failed";
    lede = "LibreLane treats these as errors. Fix them before you use this layout.";
  } else if (warns.length) {
    tone = "warn";
    title = "Finished, with " + warns.length + " warning" + (warns.length === 1 ? "" : "s");
    lede = "No errors. The amber checks are not fatal for LibreLane, but they are worth a look.";
  } else {
    tone = "pass";
    title = "Clean run: all " + ran.length + " checks passed";
    lede = "Every check LibreLane ran on this layout came back at zero.";
  }
  // The headline is Verify's verdict whenever Verify answered: one verdict
  // for the run on every page (Runs, the run bar, Verify, Analytics). The grid
  // below is the subset of Verify's checks that write a metric, and says so.
  const so = _ctx.signoff;
  const vTotal = so && so.verdict ? so.verdict.total : 0;
  if (so && so.verdict) {
    const vc = V.verdictCopy(so);
    tone = vc.tone;
    title = esc(vc.title);
    const stopLede = (!completed || stopped) && _partial
      ? " The numbers below are the metrics LibreLane saved after step " + _partial.n + " (" + esc(_partial.name) + "), the last step that finished."
      : "";
    lede = esc(vc.sub) + stopLede;
  }
  const subsetNote = vTotal
    ? "<p class='an-foot'>These are " + checks.length + " of Verify's " + vTotal + " checks: the ones LibreLane writes a metric for. Verify has every check, with its limit and report.</p>"
    : "";

  const groups = [];
  const shownChecks = (stopped || !completed) ? checks.filter((c) => c.status !== "absent") : checks;
  for (const c of shownChecks) {
    let gp = groups.find((x) => x.name === c.group);
    if (!gp) groups.push(gp = { name: c.group, items: [] });
    gp.items.push(c);
  }
  const strip = !groups.length
    ? "<p class='an-checks-none'>The checks run near the end of the flow; this run stopped before reaching them.</p>"
    : "<div class='an-checks'>" + groups.map((gp) =>
    "<div class='an-check-group'><div class='an-check-gname'>" + esc(gp.name) + "</div><div class='an-check-items'>" +
    gp.items.map((c) => {
      const val = c.status === "absent" ? "not run" : M.num(c.value);
      const meaning = c.status === "absent" ? "This run has no value for it (the check didn't run, or the run stopped first)."
        : c.status === "pass" ? "Zero: passed."
        : c.status === "fail" ? "Non-zero, and LibreLane treats it as an error."
        : "Non-zero; LibreLane doesn't treat it as fatal.";
      return "<span class='an-check is-" + c.status + "' tabindex='0' data-an-tip='" + esc(c.label + ": " + val + "\n" + c.tip + "\n" + meaning + "\n" + c.key) + "'>" +
        "<i class='an-check-mark' aria-hidden='true'></i><span class='an-check-l'>" + esc(c.label) + "</span>" +
        "<span class='an-check-v'>" + esc(val) + "</span></span>";
    }).join("") + "</div></div>").join("") + "</div>";

  const meta = [];
  if (stages.design_name) meta.push("<b>" + esc(stages.design_name) + "</b>");
  if (row.pdk || stages.pdk) meta.push(esc((row.pdk || stages.pdk) + (row.scl || stages.scl ? " / " + (row.scl || stages.scl) : "")));
  if (row.started_at) {
    const d = new Date(row.started_at);
    if (!Number.isNaN(d.getTime())) meta.push(esc(localeDateTime(d, undefined, { dateStyle: "medium", timeStyle: "short" })));
  }
  if (Number.isFinite(row.wall_time_s)) meta.push(esc(fmtDur(row.wall_time_s)) + " of step time");
  // Verify's step totals (V.stepTotals): the same "34 of 76" Flow shows.
  const nst = V.stepTotals(_ctx.signoff && _ctx.signoff.flow_state) ||
    (row.step_count ? { done: row.steps_done, total: row.step_count } : null);
  if (nst) meta.push(esc(nst.done + " of " + nst.total + " steps done" + (row.steps_reused ? " (" + row.steps_reused + " reused from " + (row.branched_from || "its parent") + ")" : "")));

  el.innerHTML =
    "<div class='an-verdict is-" + tone + "'>" +
      "<div class='an-verdict-main'><div class='an-eyebrow'>Run " + esc(_tag) + "</div>" +
      "<h2 class='an-title'>" + title + "</h2><p class='an-lede'>" + lede + "</p>" +
      "<div class='an-runmeta'>" + meta.join("<span class='sep'>·</span>") + "</div></div>" +
      "<div class='an-verdict-act'>" + (stopped || !completed ? goBtn("runs", "Open the run log") : goBtn("verify", "Details in Verify")) +
      "<span class='an-disclaim'>LanEx shows what LibreLane's tools reported. It is not a sign-off.</span></div>" +
    "</div>" + strip + subsetNote +
    "<div class='an-kpis'>" + kpiTiming() + kpiArea() + kpiPower() + kpiRouting() + "</div>" +
    (_b ? "<p class='an-basenote'>" + icon("diff", { size: 13 }) + " Changes are against <b>" + esc(_baseTag) + "</b>. Green is better and red is worse, by LibreLane's own direction for each metric.</p>"
        : "<p class='an-basenote'>" + icon("diff", { size: 13 }) + " Pick a run under <b>Compare with</b> to see what changed.</p>");
}


// History series for one metric, aligned to the trend runs. Highlights the
// selected run; failed runs get a hollow marker.
function trendSpark(key, { h = 30 } = {}) {
  const t = _ctx.trends;
  if (!t || !t.series || !t.series[key] || (t.runs || []).length < 2) return "";
  const runs = t.runs;
  const vals = t.series[key].map((v) => (typeof v === "number" && Number.isFinite(v) ? v : null));
  const sel = runs.findIndex((r) => r.tag === _tag);
  const bad = runs.map((r, i) => (r.success ? -1 : i)).filter((i) => i >= 0);
  const tips = runs.map((r, i) => {
    const s = M.show(key, t.series[key][i]);
    return r.tag + (r.success ? "" : " (failed)") + "\n" + (vals[i] === null ? "no value" : s.text + (s.unit ? " " + s.unit : ""));
  });
  return C.chartHost((cw) => C.sparkline(vals, { sel, bad, w: cw, h, tips }), "an-spark-host");
}

function kpi({ title, tip, hero, heroKey, tone = "", rows = "", spark = "", sparkLabel = "", empty = "" }) {
  return "<article class='an-kpi" + (tone ? " is-" + tone : "") + "'>" +
    "<div class='an-kpi-top'><span class='an-kpi-t' tabindex='0' data-an-tip='" + esc(tip) + "'>" + esc(title) + "</span>" + (heroKey ? provBtn(heroKey) : "") + "</div>" +
    (empty ? "<div class='an-kpi-empty'>" + esc(empty) + "</div>"
      : "<div class='an-kpi-hero'>" + hero + "</div>" + (heroKey ? "<div class='an-kpi-delta'>" + deltaHtml(heroKey) + "</div>" : "") +
        "<dl class='an-kpi-rows'>" + rows + "</dl>" +
        (spark ? "<div class='an-kpi-spark'>" + spark + "<span>" + esc(sparkLabel) + "</span></div>" : "")) +
    "</article>";
}

function kpiRow(label, html, tip = "") {
  return "<div><dt" + (tip ? " tabindex='0' data-an-tip='" + esc(tip) + "' class='has-tip'" : "") + ">" + esc(label) + "</dt><dd>" + html + "</dd></div>";
}

function kpiTiming() {
  const k = "timing__setup__ws";
  const cp = _ctx.stages.clock_period;
  const clock = Number.isFinite(Number(cp)) && Number(cp) > 0
    ? esc(M.num(Number(cp))) + "<span class='an-u'>ns</span> <span class='muted'>(" + esc(M.num(Number((1000 / Number(cp)).toPrecision(4)))) + " MHz)</span>"
    : "";
  if (!has(k)) return kpi({ title: "Timing", tip: "", empty: "No timing yet: the run stopped before static timing analysis." });
  const ws = g(k);
  const tone = M.isNum(ws) ? (ws >= 0 ? "pass" : "fail") : "";
  const rows =
    (has("timing__hold__ws") ? kpiRow("Hold slack", vh("timing__hold__ws", undefined, { cls: M.isNum(g("timing__hold__ws")) && g("timing__hold__ws") < 0 ? "is-neg" : "" }) + " " + deltaHtml("timing__hold__ws", { short: true }) + provBtn("timing__hold__ws"),
      "Worst hold slack across corners. Below zero means a signal changes too soon after the clock edge.") : "") +
    (clock ? kpiRow("Clock period", clock + varBtn("CLOCK_PERIOD"), "CLOCK_PERIOD from this run's resolved config.") : "") +
    (has("timing__setup_vio__count") ? kpiRow("Setup / hold violations", esc(M.num(g("timing__setup_vio__count"))) + provBtn("timing__setup_vio__count") + " / " +
      esc(M.num(g("timing__hold_vio__count"))) + provBtn("timing__hold_vio__count"), "Violating paths across all corners.") : "");
  return kpi({
    title: "Timing (setup slack)", heroKey: k, tone,
    tip: "Worst setup slack across every corner: the spare time on the slowest path. Positive means the design meets the clock.",
    hero: vh(k, undefined, { cls: tone === "fail" ? "is-neg" : "" }),
    rows, spark: trendSpark(k), sparkLabel: "setup slack, recent runs",
  });
}

function kpiArea() {
  const die = C.bbox(g("design__die__bbox"));
  if (!has("design__die__area") && !has("design__instance__area")) return kpi({ title: "Area", tip: "", empty: "No area yet: the run stopped before the floorplan." });
  const util = g("design__instance__utilization");
  const meter = M.isNum(util)
    ? "<span class='an-meter' role='img' aria-label='Utilization " + esc(M.show("design__instance__utilization", util).text) + "%'><i style='width:" + Math.min(100, util * 100).toFixed(1) + "%'></i></span>"
    : "";
  const rows =
    (die ? kpiRow("Die size", esc(trimNum(die[2] - die[0])) + " × " + esc(trimNum(die[3] - die[1])) + "<span class='an-u'>µm</span>" + provBtn("design__die__bbox"), "Width × height of the whole chip (design__die__bbox).") : "") +
    (M.isNum(util) ? kpiRow("Utilization", meter + vh("design__instance__utilization") + " " + deltaHtml("design__instance__utilization", { short: true }) + provBtn("design__instance__utilization"),
      "Share of the core area covered by standard cells (fill cells not counted).") : "") +
    (has("design__instance__area__stdcell") ? kpiRow("Std-cell area", vh("design__instance__area__stdcell") + " " + deltaHtml("design__instance__area__stdcell", { short: true }) + provBtn("design__instance__area__stdcell"),
      "Area of the cells that make up your logic (plus taps), without fill cells.") : "");
  const heroKey = has("design__die__area") ? "design__die__area" : "design__instance__area";
  return kpi({
    title: "Area", heroKey,
    tip: "Die area: the full rectangle of silicon this design occupies.",
    hero: vh(heroKey), rows,
    spark: trendSpark("design__instance__area__stdcell"), sparkLabel: "std-cell area, recent runs",
  });
}

function trimNum(x) { return localeNum(Number(x.toFixed(3)), "en-US", { maximumFractionDigits: 3 }); }

function kpiPower() {
  const k = "power__total";
  if (!has(k)) return kpi({ title: "Power", tip: "", empty: "No power estimate yet: it comes from static timing analysis." });
  const parts = [["power__internal__total", "Internal", "s1"], ["power__switching__total", "Switching", "s2"], ["power__leakage__total", "Leakage", "s3"]]
    .filter(([key]) => M.isNum(g(key)));
  const stack = parts.length ? C.stackBar(parts.map(([key, label, cls]) => {
    const s = M.show(key, g(key));
    return { label, value: g(key), cls, text: s.text + " " + s.unit, src: provBtn(key) };
  })) : "";
  return kpi({
    title: "Power", heroKey: k,
    tip: "Total power OpenSTA estimated in the OpenROAD.STAPostPNR step: internal + switching + leakage. It assumes the tool's default switching activity, so treat it as an estimate.",
    hero: vh(k), rows: stack ? "<div class='an-kpi-stack'>" + stack + "</div>" : "",
    spark: trendSpark(k), sparkLabel: "total power, recent runs",
  });
}

function kpiRouting() {
  const k = "route__wirelength";
  if (!has(k)) {
    const est = has("route__wirelength__estimated");
    return kpi({ title: "Routing", tip: "", empty: est ? "Not routed yet. Placement estimated " + M.show("route__wirelength__estimated", g("route__wirelength__estimated")).text + " µm of wire." : "Not routed yet." });
  }
  const drc = g("route__drc_errors");
  const rows =
    (has("route__vias") ? kpiRow("Vias", vh("route__vias") + " " + deltaHtml("route__vias", { short: true }) + provBtn("route__vias"), "Connections between metal layers.") : "") +
    (has("route__drc_errors") ? kpiRow("Router DRC errors", "<span class='an-v " + (drc ? "is-neg" : "") + "'>" + esc(M.num(drc)) + "</span>" + provBtn("route__drc_errors"), "Rule errors left after detailed routing. Should be 0.") : "") +
    (has("route__wirelength__max") ? kpiRow("Longest net", vh("route__wirelength__max") + provBtn("route__wirelength__max"), "The single longest routed net.") : "");
  return kpi({
    title: "Wirelength", heroKey: k,
    tip: "Total length of routed signal wire after detailed routing.",
    hero: vh(k), rows, spark: trendSpark(k), sparkLabel: "routed wirelength, recent runs",
  });
}

// ---------- 2. Timing ------------------------------------------------------------------------

function renderTiming() {
  const el = document.getElementById("an-timing");
  const head = sectionHead("Timing", "Does it meet the clock?",
    "Slack is the spare time on a path. Positive everywhere means the design meets its clock in every corner; the worst corner decides.",
    goBtn("verify", "Worst paths in Verify", "vf-timing"));
  if (!has("timing__setup__ws") && !has("timing__hold__ws")) {
    el.innerHTML = head + notReached("This run has no timing results: it stopped before static timing analysis.");
    return;
  }
  // Vivado/PrimeTime-style summary: setup and hold side by side.
  const rows = [
    ["Worst slack", "ws", "The smallest slack of any path. Positive means met."],
    ["WNS", "wns", "Worst negative slack: the worst failing path, or 0 when nothing fails."],
    ["TNS", "tns", "Total negative slack: all failing slack added up. 0 when nothing fails."],
    ["Violations", "_vio__count", "How many paths fail."],
    ["Reg-to-reg slack", "_r2r__ws", "Worst slack between two flip-flops (ignores I/O paths). ∞ means there are no such paths."],
  ];
  const cell = (kind, suf) => {
    const key = suf.startsWith("_") ? "timing__" + kind + suf : "timing__" + kind + "__" + suf;
    if (!has(key)) return "<td class='muted'>—</td>";
    const v = g(key);
    const neg = M.isNum(v) && v < 0;
    const isCount = /count$/.test(key);
    return "<td" + (neg || (isCount && v > 0) ? " class='is-bad'" : "") + ">" + vh(key) + (suf === "ws" ? " " + deltaHtml(key, { short: true }) : "") + provBtn(key) + "</td>";
  };
  const table = "<table class='an-ttable'><thead><tr><th></th><th>Setup <small>(max delay)</small></th><th>Hold <small>(min delay)</small></th></tr></thead><tbody>" +
    rows.map(([label, suf, tip]) => "<tr><th scope='row'><span tabindex='0' class='has-tip' data-an-tip='" + esc(tip) + "'>" + esc(label) + "</span></th>" + cell("setup", suf) + cell("hold", suf) + "</tr>").join("") +
    "</tbody></table>";

  // Per-corner slack.
  const corners = (base) => {
    const list = M.byCorner(_v, base);
    const order = { ss: 0, tt: 1, ff: 2 }, rc = { max: 0, nom: 1, min: 2 };
    list.sort((a, b) => {
      const pa = M.parseCorner(a.corner), pb = M.parseCorner(b.corner);
      return ((order[pa.proc] ?? 9) - (order[pb.proc] ?? 9)) || ((rc[pa.rc] ?? 9) - (rc[pb.rc] ?? 9)) || a.corner.localeCompare(b.corner);
    });
    return list;
  };
  const cornerChart = (base, cls, title) => {
    const list = corners(base);
    if (!list.length) return "";
    const fin = list.filter((x) => M.isNum(x.value));
    const worst = fin.length ? fin.reduce((a, b) => (b.value < a.value ? b : a)) : null;
    return "<div class='an-corner-col'><div class='an-sub'>" + esc(title) + "</div>" + C.divergingBars(list.map((x) => {
      const s = M.show(base, x.value);
      return {
        label: M.cornerShort(x.corner), sub: x.corner, value: M.isNum(x.value) ? x.value : NaN,
        text: esc(s.text) + provBtn(base + "__corner:" + x.corner), worst: worst && x.corner === worst.corner,
        tip: title.replace(/ by corner$/, "") + ": " + s.text + " " + s.unit + "\n" + M.cornerLabel(x.corner) + (worst && x.corner === worst.corner ? " (worst corner)" : "") + "\n" + base + "__corner:" + x.corner,
      };
    }), { cls }) + "</div>";
  };
  const cset = cornerChart("timing__setup__ws", "s1", "Setup slack by corner");
  const chold = cornerChart("timing__hold__ws", "s2", "Hold slack by corner");
  const ncorners = corners("timing__setup__ws").length;

  // Electrical checks per corner: only list corners with violations.
  const elec = [["design__max_slew_violation__count", "Max slew"], ["design__max_cap_violation__count", "Max capacitance"], ["design__max_fanout_violation__count", "Max fanout"]];
  const elecLines = elec.filter(([k]) => has(k)).map(([k, label]) => {
    const total = g(k);
    if (!total) return "<li><span class='an-ok'>" + esc(label) + ": 0</span>" + provBtn(k) + (ncorners ? " in all " + ncorners + " corners" : "") + "</li>";
    const bad = M.byCorner(_v, k).filter((x) => x.value > 0);
    return "<li><span class='an-bad'>" + esc(label) + ": " + esc(M.num(total)) + "</span>" + provBtn(k) + " — " +
      bad.map((x) => esc(x.corner + " (" + x.value + ")") + provBtn(k + "__corner:" + x.corner)).join(", ") + "</li>";
  });
  const skew = ["clock__skew__worst_setup", "clock__skew__worst_hold"].filter(has);
  const other = [
    ...elecLines,
    skew.length ? "<li><span tabindex='0' class='has-tip' data-an-tip='The worst difference in clock arrival time between two related flip-flops.'>Worst clock skew</span>: setup " + vh("clock__skew__worst_setup") + provBtn("clock__skew__worst_setup") +
      ", hold " + vh("clock__skew__worst_hold") + provBtn("clock__skew__worst_hold") + "</li>" : "",
    has("timing__unannotated_net__count") ? "<li><span tabindex='0' class='has-tip' data-an-tip='Nets the timer had no extracted parasitics for. Non-zero makes the timing less exact.'>Nets without parasitics</span>: " + esc(M.num(g("timing__unannotated_net__count"))) + provBtn("timing__unannotated_net__count") + "</li>" : "",
  ].filter(Boolean).join("");

  const flow = timingThroughFlow();
  el.innerHTML = head +
    "<div class='an-grid an-grid-timing'>" +
      "<div class='an-card'><div class='an-card-h'>Summary <span class='muted'>worst over all corners</span></div>" + table +
        (other ? "<ul class='an-notes'>" + other + "</ul>" : "") + "</div>" +
      (cset || chold ? "<div class='an-card'><div class='an-card-h'>By corner <span class='muted'>" + ncorners + " PVT corners: process, temperature, voltage, wire RC</span></div>" +
        "<div class='an-corners'>" + cset + chold + "</div>" +
        "<p class='an-foot'>Bars grow right for positive slack; red bars left of the line fail. The outlined row is the worst corner.</p></div>" : "") +
    "</div>" + flow;
}

// Setup/hold slack at each STA checkpoint the flow ran (pre-PnR, mid-PnR …,
// signoff). Values are those steps' own metrics.
function timingThroughFlow() {
  const sta = _ctx.steps.filter((s) => /^sta/.test(M.stepCore(s.id || s.dir)) && s.status === "done" && s.changed && (("timing__setup__ws" in s.changed) || ("timing__hold__ws" in s.changed)));
  if (sta.length < 2) return "";
  const xs = sta.map((s) => ({ label: s.stage, sub: "step " + s.n, tip: M.stepName(s) + " · step " + s.n + " · " + s.stage }));
  const chart = (key, name, cls) => {
    const values = sta.map((s) => num0(s.metrics[key]));
    return "<div class='an-flowchart'><div class='an-sub'><i class='an-key line " + cls + "'></i> " + esc(name) + " <span class='muted'>(ns)</span></div>" +
      C.chartHost((w) => C.lineChart({ xs, series: [{ name, cls, values }], unit: "ns", height: 190, zero: true, W: w,
        fmtY: (v, full) => (full ? M.signed(v, 3) : M.num(v)), label: name + " at each static timing checkpoint" })) + "</div>";
  };
  return "<div class='an-card an-card-wide'><div class='an-card-h'>Through the flow <span class='muted'>slack at each timing check the flow ran, synthesis to signoff</span></div>" +
    "<div class='an-flowcharts'>" + chart("timing__setup__ws", "Setup slack", "s1") + chart("timing__hold__ws", "Hold slack", "s2") + "</div>" +
    "<p class='an-foot'>Each chart has its own scale and always includes zero (the pass line). Early checkpoints use estimated wires; signoff uses extracted parasitics, so a drop at the end is normal.</p></div>";
}

function num0(v) { return typeof v === "number" && Number.isFinite(v) ? v : null; }

// ---------- 3. Area ------------------------------------------------------------------------

const PHYSICAL_ONLY = /^(fill|tap|endcap|welltap|decap|antenna|tie|spacer|filler)/;

function renderArea() {
  const el = document.getElementById("an-area");
  const head = sectionHead("Area", "How big is it, and what fills it?",
    "The die is the whole chip; the core is the part inside it where cells are placed. Utilization is how much of the core your cells use.");
  const die = C.bbox(g("design__die__bbox"));
  const core = C.bbox(g("design__core__bbox"));
  if (!die && !has("design__instance__area")) { el.innerHTML = head + notReached("No area data: the run stopped before the floorplan."); return; }
  const facts =
    fact("Die area", "design__die__area", { tip: "The full rectangle of silicon." }) +
    fact("Core area", "design__core__area", { tip: "The placeable region inside the die (die minus the I/O ring margin)." }) +
    fact("Utilization", "design__instance__utilization", { tip: "Standard-cell area ÷ core area (fill cells not counted)." }) +
    fact("Standard cells", "design__instance__count__stdcell", { tip: "Cells in the layout, without fill cells." }) +
    fact("All instances", "design__instance__count", { tip: "Every instance, including fill cells." }) +
    fact("Macros", "design__instance__count__macros") +
    fact("I/O pins", "design__io", { tip: "Top-level pins placed on the die edge." }) +
    fact("Placement rows", "design__rows");
  const fp = die ? "<div class='an-fp-wrap'>" + C.floorplan(die, core, { label: "Floorplan to scale: die and core outlines" }) + "</div>" : "";

  // Instance area by cell class (LibreLane's design__instance__area__class:*).
  const classes = Object.keys(_v).filter((k) => k.startsWith("design__instance__area__class:"))
    .map((k) => {
      const cls = k.split(":")[1];
      return { cls, area: g(k), count: g("design__instance__count__class:" + cls), key: k };
    }).filter((c) => M.isNum(c.area)).sort((a, b) => b.area - a.area);
  const totalArea = g("design__instance__area");
  const classCard = classes.length ? "<div class='an-card'><div class='an-card-h'>Instance area by cell type <span class='muted'>share of all instance area</span></div>" +
    C.barList(classes.map((c) => {
      const phys = PHYSICAL_ONLY.test(c.cls);
      const pct = M.isNum(totalArea) && totalArea > 0 ? (c.area / totalArea) * 100 : null;
      return {
        label: c.cls.replace(/_/g, " "), value: c.area, tone: phys ? "muted" : "s1",
        sub: phys ? "physical only" : "",
        text: esc(M.num(c.area)) + "<span class='an-u'>µm²</span>" + (pct !== null ? " <span class='muted'>" + C.pctText(pct) + "</span>" : "") + provBtn(c.key),
        tip: c.cls + "\n" + M.num(c.area) + " µm²" + (M.isNum(c.count) ? " in " + M.num(c.count) + " cells" : "") + (pct !== null ? "\n" + C.pctText(pct) + " of all instance area" : "") + "\n" + c.key,
      };
    })) + "<p class='an-foot'>Grey rows are physical-only cells (fill, taps): they complete the rows and wells and carry no logic.</p></div>" : "";

  el.innerHTML = head +
    "<div class='an-grid an-grid-area'>" +
      "<div class='an-card an-fp-card'><div class='an-card-h'>Floorplan <span class='muted'>to scale</span></div><div class='an-fp-body'>" + fp + "<dl class='an-facts'>" + facts + "</dl></div></div>" +
      classCard +
    "</div>" + cellsCard();
  renderCellRows();
}

function cellsCard() {
  const cells = (_ctx.cells || []).filter((c) => Number.isFinite(Number(c.count)));
  if (!cells.length) return "";
  return "<div class='an-card an-card-wide an-cells' id='an-cells-card'><div class='an-card-h'>Standard cells used <span class='muted' id='an-cells-count'></span>" +
    "<span class='muted'>Click a cell to see what it is in Cells.</span>" +
    "<input type='search' id='an-cells-search' class='an-search' placeholder='Filter cells' aria-label='Filter cells' /></div>" +
    "<div id='an-cells-rows'></div></div>";
}

function renderCellRows() {
  const host = document.getElementById("an-cells-rows");
  if (!host) return;
  const cells = (_ctx.cells || []).filter((c) => Number.isFinite(Number(c.count)));
  const total = cells.reduce((s, c) => s + Number(c.count), 0) || 1;
  const q = (document.getElementById("an-cells-search")?.value || "").trim().toLowerCase();
  const list = q ? cells.filter((c) => String(c.cell).toLowerCase().includes(q)) : cells;
  const cnt = document.getElementById("an-cells-count");
  const pfx = commonPrefix(cells.map((c) => String(c.cell)));
  if (cnt) cnt.textContent = cells.length + " cell types · " + localeNum(total) + " instances" + (pfx ? " · names without the " + pfx + " prefix" : "") + " · from the Cells by Master report";
  const LIMIT = 12;
  const max = Math.max(...cells.map((c) => Number(c.count)));
  const pre = commonPrefix(cells.map((c) => String(c.cell)));
  host.innerHTML = C.barList(list.map((c, i) => ({
    label: pre ? String(c.cell).slice(pre.length) : c.cell, mono: true, value: Number(c.count), tone: PHYSICAL_ONLY.test(String(c.cell).replace(/^.*__/, "")) ? "muted" : "s1",
    text: esc(localeNum(Number(c.count))) + " <span class='muted'>" + C.pctText((Number(c.count) / total) * 100) + "</span>",
    tip: c.cell + "\n" + localeNum(Number(c.count)) + " instances · " + C.pctText((Number(c.count) / total) * 100) + " of all",
    _i: i,
  })), { max }) + (!q && list.length > LIMIT ? "<button class='btn btn-ghost btn-sm an-more' data-an-more='Show all " + list.length + "'>Show all " + list.length + "</button>" : "") +
    (q && !list.length ? "<p class='muted'>No cell matches “" + esc(q) + "”.</p>" : "");
  host.closest(".an-card")?.classList.toggle("is-filtered", !!q);
}

// "sky130_fd_sc_hd__a21o_2", "sky130_fd_sc_hd__fill_1" -> "sky130_fd_sc_hd__"
function commonPrefix(names) {
  if (names.length < 2) return "";
  let p = names[0];
  for (const n of names) while (p && !n.startsWith(p)) p = p.slice(0, -1);
  const cut = p.lastIndexOf("__");
  return cut > 0 ? p.slice(0, cut + 2) : "";
}

// ---------- 4. Power -----------------------------------------------------------------------

function renderPower() {
  const el = document.getElementById("an-power");
  const head = sectionHead("Power", "How much power does it draw?",
    "Internal power is burned inside cells when they switch, switching power charges the wires, and leakage flows even when nothing changes.");
  if (!has("power__total")) { el.innerHTML = head + notReached("No power estimate: it comes from static timing analysis, which this run didn't reach."); return; }
  const parts = [["power__internal__total", "Internal", "s1"], ["power__switching__total", "Switching", "s2"], ["power__leakage__total", "Leakage", "s3"]].filter(([k]) => M.isNum(g(k)));
  const breakdown = "<div class='an-card'><div class='an-card-h'>Breakdown " + provBtn("power__total") + "</div>" +
    "<div class='an-power-total'>" + vh("power__total") + " " + deltaHtml("power__total") + "</div>" +
    C.stackBar(parts.map(([k, label, cls]) => { const s = M.show(k, g(k)); return { label, value: g(k), cls, text: s.text + " " + s.unit }; })) +
    "<p class='an-foot'>OpenSTA's estimate with default switching activity, not a measured or simulated figure.</p></div>";

  // IR drop per supply net.
  const nets = new Set();
  for (const k of Object.keys(_v)) { const m = /^design_powergrid__\w+?__net:([^_]+(?:_[^_]+)*?)(?:__|$)/.exec(k); if (m) nets.add(m[1]); }
  const corner = (Object.keys(_v).find((k) => /^design_powergrid__drop__average__net:.*__corner:/.test(k)) || "").split("__corner:")[1] || "";
  const netRows = [...nets].sort().map((net) => {
    const wk = "design_powergrid__drop__worst__net:" + net;
    const vk = "design_powergrid__voltage__worst__net:" + net;
    return "<tr><th scope='row'>" + esc(net) + "</th><td>" + (has(wk) ? vh(wk) + " " + deltaHtml(wk, { short: true }) + provBtn(wk) : "—") + "</td><td>" + (has(vk) ? vh(vk) + provBtn(vk) : "—") + "</td></tr>";
  }).join("");
  const ir = netRows ? "<div class='an-card'><div class='an-card-h'>IR drop <span class='muted'>" + (corner ? "at " + esc(corner) : "power grid") + "</span></div>" +
    "<table class='an-ttable'><thead><tr><th>Net</th><th><span class='has-tip' tabindex='0' data-an-tip='The largest voltage lost across the power grid before reaching a cell on this net.'>Worst drop</span></th><th><span class='has-tip' tabindex='0' data-an-tip='Supply net: the lowest voltage any cell sees. Ground net: the highest (ground bounce).'>Worst voltage</span></th></tr></thead><tbody>" + netRows + "</tbody></table>" +
    "<dl class='an-facts'>" + fact("Power-grid violations", "design__power_grid_violation__count", { tip: "Cells not connected to the power grid." }) + "</dl>" +
    "<p class='an-foot'>From OpenROAD's static IR-drop analysis. A few millivolts on a small design is typical.</p></div>"
    : (has("ir__drop__worst") ? "<div class='an-card'><div class='an-card-h'>IR drop</div><dl class='an-facts'>" + fact("Worst IR drop", "ir__drop__worst") + fact("Average IR drop", "ir__drop__avg") + fact("Worst voltage", "ir__voltage__worst") + "</dl></div>" : "");
  el.innerHTML = head + "<div class='an-grid'>" + breakdown + ir + "</div>";
}

// ---------- 5. Routing ---------------------------------------------------------------------

function renderRouting() {
  const el = document.getElementById("an-routing");
  const head = sectionHead("Routing", "How did routing go?",
    "The router connects every cell with metal wires and vias. Placement estimates the wire, global routing plans it, and detailed routing draws it.");
  if (!has("route__wirelength") && !has("global_route__wirelength") && !has("route__wirelength__estimated")) {
    el.innerHTML = head + notReached("No routing data: the run stopped before placement finished.");
    return;
  }
  const wl = "<div class='an-card'><div class='an-card-h'>Wire</div><dl class='an-facts'>" +
    fact("Estimated (after placement)", "route__wirelength__estimated", { tip: "Placement's estimate of total wirelength." }) +
    fact("Global route", "global_route__wirelength", { tip: "Wirelength planned by the global router." }) +
    fact("Routed", "route__wirelength", { tip: "Final wirelength drawn by the detailed router." }) +
    fact("Longest net", "route__wirelength__max") +
    fact("Routed nets", "route__net") +
    fact("Power nets", "route__net__special", { tip: "Special nets routed by the power grid, not the signal router." }) +
    fact("Vias", "route__vias") +
    fact("Single-cut / multi-cut", "route__vias__singlecut", { value: has("route__vias__singlecut") ? esc(M.num(g("route__vias__singlecut"))) + " / " + esc(M.num(g("route__vias__multicut"))) : undefined, delta: false }) +
    fact("I/O half-perimeter WL", "design__io__hpwl") +
    "</dl></div>";
  // A run cut off before the antenna check after detailed routing: what it
  // has is the global-routing estimate (before antenna repair), said so.
  const antChk = ((_ctx.signoff && _ctx.signoff.checks) || []).find((c) => c.id === "antenna");
  const antEst = !!(antChk && antChk.status === "not_run" && antChk.interim != null);
  const estTip = antEst ? " This run ended before the check after detailed routing: this is the estimate at global routing, before antenna repair, not a result." : "";
  const ant = "<div class='an-card'><div class='an-card-h'>Antenna and placement" + (antEst ? " <span class='muted'>antenna: estimate only</span>" : "") + "</div><dl class='an-facts'>" +
    fact("Antenna violations" + (antEst ? " (estimate)" : ""), "route__antenna_violation__count", { delta: !antEst, tip: "Long wires that can damage transistor gates while the chip is being made." + estTip }) +
    fact("Violating nets / pins" + (antEst ? " (estimate)" : ""), "antenna__violating__nets", { tip: estTip.trim(), value: has("antenna__violating__nets") ? esc(M.num(g("antenna__violating__nets"))) + " / " + esc(M.num(g("antenna__violating__pins"))) : undefined, delta: false }) +
    fact("Antenna diodes inserted", "antenna_diodes_count", { tip: "Diodes the flow added to protect gates from antenna effects." }) +
    fact("Max displacement", "design__instance__displacement__max", { tip: "How far detailed placement had to move a cell to make it legal." }) +
    fact("Mean displacement", "design__instance__displacement__mean") +
    "</dl></div>";

  // Detailed-router convergence (route__drc_errors__iter:N).
  const iters = Object.keys(_v).filter((k) => /^route__drc_errors__iter:\d+$/.test(k))
    .map((k) => ({ i: Number(k.split(":")[1]), k })).sort((a, b) => a.i - b.i);
  let conv = "";
  if (iters.length) {
    const cols = iters.map(({ i, k }) => {
      const wk = "route__wirelength__iter:" + i;
      return { label: String(i), value: g(k), text: M.num(g(k)), src: provBtn(k), tip: "Iteration " + i + "\n" + M.num(g(k)) + " DRC errors" + (has(wk) ? "\n" + M.num(g(wk)) + " µm of wire" : "") };
    });
    const last = cols[cols.length - 1];
    conv = "<div class='an-card'><div class='an-card-h'>Detailed-router convergence <span class='muted'>DRC errors after each pass</span></div>" +
      C.columns(cols) +
      "<p class='an-foot'>" + (last.value === 0 ? "Clean after " + cols.length + " pass" + (cols.length === 1 ? "" : "es") + "." : last.value + " errors left after the last pass.") + " The router repeats until the errors reach zero or it gives up.</p></div>";
  }
  el.innerHTML = head + "<div class='an-grid an-grid-3'>" + wl + ant + conv + "</div>";
}

// ---------- 6. Flow ------------------------------------------------------------------------

// Per-stage QoR table (the Innovus/Genus "QoR by stage" view): a cell shows a
// value only when a step in that stage wrote it; "·" means unchanged.
const FLOW_ROWS = [
  ["Standard cells", [["design__instance__count__stdcell"], ["design__instance__count", "Synthesis"]], "At synthesis this is Yosys' cell count; from the floorplan on, LibreLane's standard-cell count (fill cells excluded)."],
  ["Std-cell area", [["design__instance__area__stdcell"], ["design__instance__area", "Synthesis"]], "At synthesis this is Yosys' cell area; from the floorplan on, standard-cell area without fill cells."],
  ["Utilization", [["design__instance__utilization"]], ""],
  ["Timing-repair buffers", [["design__instance__count__class:timing_repair_buffer"]], "Buffers the resizer added to fix timing and slew."],
  ["Clock buffers", [["design__instance__count__class:clock_buffer"]], "Buffers clock-tree synthesis added."],
  ["Fill cells", [["design__instance__count__class:fill_cell"]], "Physical-only cells that complete the rows."],
  ["Wire (placement estimate)", [["route__wirelength__estimated"]], ""],
  ["Wire (global route)", [["global_route__wirelength"]], ""],
  ["Wire (routed)", [["route__wirelength"]], ""],
  ["Setup slack", [["timing__setup__ws"]], ""],
  ["Hold slack", [["timing__hold__ws"]], ""],
  ["Power", [["power__total"]], ""],
  ["Router DRC errors", [["route__drc_errors"]], ""],
];

function renderFlow() {
  const el = document.getElementById("an-flow");
  const head = sectionHead("Flow", "How did the flow get there?",
    "Each stage changes the design: synthesis makes the netlist, placement and clock-tree synthesis add buffers, routing adds wire. Timing gets more exact as the flow goes on.");
  const steps = _ctx.steps;
  if (!steps.length) { el.innerHTML = head + notReached("No step data for this run."); return; }
  const stages = M.STAGES.filter((st) => steps.some((s) => s.stage === st));
  const lastIn = (st, keys) => {
    let hit = null;
    for (const s of steps) {
      if (s.stage !== st || !s.changed) continue;
      for (const [k, only] of keys) if ((!only || only === st) && k in s.changed) { hit = { s, k, v: s.changed[k] }; break; }
    }
    return hit;
  };
  const stopped = stoppedStep();
  const thead = "<tr><th></th>" + stages.map((st) => "<th>" + esc(st) + (stopped && stopped.stage === st ? " <span class='an-stop' title='The run stopped in this stage'>stopped</span>" : "") + "</th>").join("") + "</tr>";
  const tbody = FLOW_ROWS.map(([label, keys, tip]) => {
    const cells = stages.map((st) => {
      const h = lastIn(st, keys);
      if (!h) return "<td class='an-same' aria-label='unchanged'>·</td>";
      const s = M.show(h.k, h.v);
      const neg = (/slack/.test(label) && M.isNum(h.v) && h.v < 0) || (/DRC/.test(label) && h.v > 0);
      return "<td" + (neg ? " class='is-bad'" : "") + " tabindex='0' data-an-tip='" + esc(label + " · " + st + "\n" + s.text + " " + s.unit + "\nset by step " + h.s.n + " " + M.stepName(h.s) + "\n" + h.k) + "'>" +
        "<span class='an-v'>" + esc(s.text) + "</span>" + (s.unit ? "<span class='an-u'>" + esc(s.unit) + "</span>" : "") + provBtn(h.k, h.s.run || "", h.s.dir) + "</td>";
    });
    if (cells.every((c) => c.includes("an-same"))) return "";
    return "<tr><th scope='row'>" + (tip ? "<span class='has-tip' tabindex='0' data-an-tip='" + esc(tip) + "'>" + esc(label) + "</span>" : esc(label)) + "</th>" + cells.join("") + "</tr>";
  }).join("");
  const qor = "<div class='an-card an-card-wide'><div class='an-card-h'>Quality by stage <span class='muted'>value at the end of each stage, as the steps wrote it; · = unchanged in that stage</span></div>" +
    "<div class='an-scrollx'><table class='an-ttable an-qor'><thead>" + thead + "</thead><tbody>" + tbody + "</tbody></table></div></div>";

  // Runtime by stage + slowest steps + peak memory.
  const timed = steps.filter((s) => M.isNum(s.runtime_s));
  let rt = "";
  if (timed.length) {
    const total = timed.reduce((a, s) => a + s.runtime_s, 0);
    const byStage = stages.map((st) => {
      const ss = timed.filter((s) => s.stage === st);
      return { st, t: ss.reduce((a, s) => a + s.runtime_s, 0), n: ss.length };
    });
    const slow = [...timed].sort((a, b) => b.runtime_s - a.runtime_s).slice(0, 6);
    const mem = steps.filter((s) => M.isNum(s.peak_rss_mib));
    const peak = mem.length ? mem.reduce((a, b) => (b.peak_rss_mib > a.peak_rss_mib ? b : a)) : null;
    rt = "<div class='an-card'><div class='an-card-h'>Runtime <span class='muted'>" + esc(fmtDur(total)) + " across " + timed.length + " steps</span></div>" +
      C.barList(byStage.map((x) => ({ label: x.st, value: x.t, text: esc(fmtDur(x.t)) + " <span class='muted'>" + C.pctText(total ? (x.t / total) * 100 : 0) + "</span>", tip: x.st + "\n" + fmtDur(x.t) + " in " + x.n + " steps" }))) +
      "<div class='an-sub'>Slowest steps</div>" +
      C.barList(slow.map((s) => ({ label: M.stepName(s), sub: "step " + s.n, value: s.runtime_s, text: esc(fmtDur(s.runtime_s)), tip: s.dir + "\n" + fmtDur(s.runtime_s) + (M.isNum(s.peak_rss_mib) ? "\npeak memory " + M.num(s.peak_rss_mib) + " MiB" : "") }))) +
      (peak ? "<p class='an-foot'>Peak memory: <b>" + esc(M.num(peak.peak_rss_mib)) + " MiB</b> in " + esc(M.stepName(peak)) + " (step " + peak.n + "). Step time is each step's own runtime.txt.</p>" : "") +
      "</div>";
  }

  // Warnings by message code.
  const codes = Object.keys(_v).filter((k) => /^flow__warnings__count:/.test(k)).map((k) => ({ code: k.split(":")[1], n: g(k), k })).filter((x) => M.isNum(x.n)).sort((a, b) => b.n - a.n);
  const lintW = g("design__lint_warning__count");
  const warn = (codes.length || M.isNum(lintW)) ? "<div class='an-card'><div class='an-card-h'>Warnings <span class='muted'>by tool message code</span></div>" +
    (codes.length ? C.barList(codes.map((c) => ({ label: c.code, mono: true, value: c.n, tone: "s3", text: esc(M.num(c.n)) + provBtn(c.k), tip: c.code + ": " + c.n + " times\n" + c.k }))) : "<p class='muted'>No tool warnings were counted.</p>") +
    "<dl class='an-facts'>" + fact("Lint warnings (Verilator)", "design__lint_warning__count") + fact("Timing constructs in RTL", "design__lint_timing_construct__count") + fact("Flow errors", "flow__errors__count") + "</dl>" +
    "<p class='an-foot'>Codes like DRT-0349 are OpenROAD message IDs; search the step logs (Runs) for the full text.</p></div>" : "";

  el.innerHTML = head + qor + "<div class='an-grid'>" + rt + warn + "</div>";
}

// ---------- 7. History ---------------------------------------------------------------------

const HISTORY = [
  ["timing__setup__ws", "Setup slack"],
  ["timing__hold__ws", "Hold slack"],
  ["design__instance__utilization", "Utilization"],
  ["design__instance__area__stdcell", "Std-cell area"],
  ["power__total", "Total power"],
  ["route__wirelength", "Routed wirelength"],
  ["route__drc_errors", "Router DRC errors"],
];

function renderHistory() {
  const el = document.getElementById("an-history-body");
  const t = _ctx.trends;
  const runs = (t && t.runs) || [];
  if (runs.length < 2) {
    el.innerHTML = notReached("Trends need at least two runs of this design. Change a setting and run again to see how the numbers move.");
    return;
  }
  const sel = runs.findIndex((r) => r.tag === _tag);
  const bad = runs.map((r, j) => (r.success ? -1 : j)).filter((j) => j >= 0);
  const tags = runs.map((r) => r.tag);
  const tiles = HISTORY.filter(([k]) => t.series && t.series[k]).map(([k, label]) => {
    const vals = t.series[k].map(num0);
    const cur = sel >= 0 ? t.series[k][sel] : null;
    const s = M.show(k, cur);
    const fin = vals.filter((v) => v !== null);
    const lo = Math.min(...fin), hi = Math.max(...fin);
    const rs = (v) => { const x = M.show(k, v); return x.text + (x.unit ? " " + x.unit : ""); };
    const range = !fin.length ? "no values yet"
      : lo === hi ? "the same in all " + fin.length + " runs with a value"
      : "range " + rs(lo) + " to " + rs(hi);
    const tips = runs.map((r, j) => r.tag + (r.success ? "" : " (failed)") + "\n" + (vals[j] === null ? "no value" : rs(t.series[k][j])) + (r.tag === _tag ? "\nthe run shown on this page" : "\nclick to open this run"));
    return "<div class='an-hist'><div class='an-hist-h'>" + esc(label) + "<span>" + (cur == null ? "—" : esc(s.text) + " <small>" + esc(s.unit) + "</small>") + "</span></div>" +
      C.chartHost((w) => C.sparkline(vals, { sel, bad, w, h: 56, tips, runTags: tags }), "an-hist-plot") +
      "<div class='an-hist-range'>" + esc(range) + "</div></div>";
  }).join("");
  el.innerHTML = "<p class='an-foot an-hist-legend'><i class='an-key dot sel'></i> this run <i class='an-key dot bad'></i> failed run <span class='sep'>·</span> oldest on the left, " + runs.length + " runs <span class='sep'>·</span> click a point to open that run</p>" +
    "<div class='an-hists'>" + tiles + "</div>";
}

// ---------- 8. All metrics -----------------------------------------------------------------

function statusOf(key, v) {
  const { base } = M.parseKey(key);
  if (/(_vio__count|error[s]?__count|__errors$|_violation__count|drc_errors|illegal_overlap__count|unmatched_|_difference__count|disconnected_pin__count|inferred_latch__count|unmapped__count|property_fail__count|violating__)/.test(base)) {
    const n = Number(v);
    if (n === 0) return "pass";
    const m = _meta.get(base);
    return m && m.critical ? "fail" : (/drc_error|drc_errors/.test(base) ? "fail" : "warn");
  }
  if (/^timing__.*__(ws|wns|tns)$/.test(base) && M.isNum(v)) return v < 0 ? "fail" : "";
  return "";
}

function renderAll() {
  const el = document.getElementById("an-all-body");
  if (!el) return;
  const total = Object.keys(_v).length;
  el.innerHTML = "<div class='an-all-bar'>" +
    "<input type='search' id='an-all-search' class='an-search' placeholder='Filter by name or key, e.g. slack, area, lvs' aria-label='Filter metrics' value='" + esc(document.getElementById("an-all-search")?.value || "") + "'/>" +
    "<div class='seg' role='group' aria-label='Show'>" +
      [["all", "All"], ["problems", "Problems"], ["changed", "Changed"]].map(([id, l]) =>
        "<button class='seg-btn" + (_allFilter === id ? " is-active" : "") + "' data-an-filter='" + id + "'" + (id === "changed" && !_b ? " disabled title='Pick a run under Compare with first'" : "") + ">" + l + "</button>").join("") +
    "</div><span class='muted' id='an-all-count'></span></div>" +
    "<div id='an-all-rows'></div>" +
    "<p class='an-foot'>" + total + " values from " + (_partial ? esc(_partial.dir) + "/state_out.json (the last step that finished)" : "this run's metrics.json") + ". The magnifier opens the raw file at that line. Directions (higher or lower is better) come from LibreLane's metric registry.</p>";
  renderAllRows();
}

function renderAllRows() {
  const host = document.getElementById("an-all-rows");
  if (!host) return;
  if (_allFilter === "changed" && !_b) _allFilter = "all";
  const q = (document.getElementById("an-all-search")?.value || "").trim().toLowerCase();
  // Group keys by base metric; modifier variants hang under their base.
  const fams = new Map();
  for (const k of Object.keys(_v).sort()) {
    const { base, mods } = M.parseKey(k);
    if (!fams.has(base)) fams.set(base, { base, main: null, kids: [] });
    const f = fams.get(base);
    if (!Object.keys(mods).length) f.main = k; else f.kids.push(k);
  }
  const keep = (k) => {
    const v = _v[k];
    if (q && !(k.toLowerCase().includes(q) || (M.labelOf(k) || "").toLowerCase().includes(q))) return false;
    if (_allFilter === "problems") { const s = statusOf(k, v); return s === "fail" || s === "warn"; }
    if (_allFilter === "changed") { const b = _b[k]; return JSON.stringify(b) !== JSON.stringify(v); }
    return true;
  };
  const byCat = new Map(M.CATEGORIES.map(([id, title]) => [id, { title, rows: [], n: 0 }]));
  byCat.set("other", { title: "Other", rows: [], n: 0 });
  let shown = 0;
  for (const f of fams.values()) {
    const mainOk = f.main && keep(f.main);
    const kids = f.kids.filter(keep);
    if (!mainOk && !kids.length) continue;
    const cat = byCat.get(M.categoryOf(f.base)) || byCat.get("other");
    const open = !!q || _allFilter !== "all";
    const famId = "an-fam-" + f.base.replace(/[^a-z0-9_]/gi, "_");
    const kidsAll = open ? kids : f.kids;
    const toggle = kidsAll.length ? "<button class='an-exp' data-an-expand='" + famId + "' aria-expanded='" + (open ? "true" : "false") + "' aria-label='Show " + kidsAll.length + " " + kidNoun(kidsAll) + "' title='Show each " + kidNoun([kidsAll[0]]) + "'></button>" : "";
    const count = kidsAll.length ? kidsAll.length + " " + kidNoun(kidsAll) : "";
    cat.rows.push(rowHtml(f.main || null, f.base, toggle, false, "", false, count));
    for (const k of kidsAll) cat.rows.push(rowHtml(k, f.base, "", true, famId, !open));
    shown += (mainOk ? 1 : 0) + kids.length;
    cat.n += (mainOk ? 1 : 0) + kids.length;
  }
  const cnt = document.getElementById("an-all-count");
  if (cnt) cnt.textContent = shown + " of " + Object.keys(_v).length + " shown";
  const body = [...byCat.values()].filter((c) => c.rows.length).map((c) =>
    "<details class='an-cat' open><summary>" + esc(c.title) + " <span class='muted'>" + c.n + "</span></summary>" +
    "<table class='an-mtable'><thead><tr><th>Metric</th><th>Value</th>" + (_b ? "<th>" + esc(_baseTag) + "</th><th>Change</th>" : "") + "<th class='an-src'><span class='sr-only'>Source</span></th></tr></thead><tbody>" + c.rows.join("") + "</tbody></table></details>").join("");
  host.innerHTML = body || "<div class='an-none'>Nothing matches. Clear the filter to see every metric.</div>";
  wireProvBtns(host);
}

function kidNoun(keys) {
  const m = M.parseKey(keys[0]).mods;
  if (m.corner) return keys.length === 1 ? "corner" : "corners";
  if (m.net) return keys.length === 1 ? "net" : "nets";
  if (m.iter !== undefined) return keys.length === 1 ? "iteration" : "iterations";
  if (m.class) return keys.length === 1 ? "cell type" : "cell types";
  return keys.length === 1 ? "variant" : "variants";
}

function rowHtml(key, base, toggle, kid, famId, hidden, count = "") {
  const label = key ? M.labelOf(key) : (M.LABELS[base] || null);
  const v = key ? _v[key] : undefined;
  const st = key ? statusOf(key, v) : "";
  const m = _meta.get(base);
  const tag = m && m.critical ? "<span class='an-crit' data-an-tip='LibreLane marks this metric critical: a non-zero count fails the flow.' tabindex='0'>critical</span>" : "";
  const name = kid
    ? "<span class='an-kidname'>" + esc(key.slice(base.length).replace(/^__/, "").replace(/__/g, " · ")) + "</span>"
    : (label ? "<span class='an-mlabel'>" + esc(label) + "</span>" + tag + "<code>" + esc(key || base) + (count ? "<span class='an-mcount'> · " + esc(count) + "</span>" : "") + "</code>"
      : "<code class='an-mkey'>" + esc(key || base) + "</code>" + tag + (count ? "<span class='an-mcount'> · " + esc(count) + "</span>" : ""));
  const val = key ? "<td class='an-mval" + (st === "fail" ? " is-bad" : st === "warn" ? " is-warn" : "") + "'>" + (st ? "<i class='an-dot is-" + st + "' aria-hidden='true'></i>" : "") + vh(key, v) + "</td>" : "<td class='muted'>" + (toggle ? "" : "—") + "</td>";
  let bcells = "";
  if (_b) bcells = key ? "<td class='an-mval an-mbase'>" + (_b[key] !== undefined ? vh(key, _b[key]) : "—") + "</td><td>" + deltaHtml(key, { short: true }) + "</td>" : "<td></td><td></td>";
  return "<tr class='" + (kid ? "an-kid" : "an-fam") + "'" + (kid ? " data-fam='" + famId + "'" + (hidden ? " hidden" : "") : "") + ">" +
    "<th scope='row'><div class='an-mname'>" + (kid ? "" : "<span class='an-exp-slot'>" + toggle + "</span>") + "<div>" + name + "</div></div></th>" + val + bcells + "<td class='an-src'>" + (key ? provBtn(key) : "") + "</td></tr>";
}

function toggleKids(btn) {
  const id = btn.dataset.anExpand;
  const open = btn.getAttribute("aria-expanded") !== "true";
  btn.setAttribute("aria-expanded", open ? "true" : "false");
  btn.closest("table").querySelectorAll("tr[data-fam='" + id + "']").forEach((r) => { r.hidden = !open; });
}

// ---------- CSV ----------------------------------------------------------------------------

function exportCsv() {
  const keys = Object.keys(_v).sort();
  if (!keys.length) { toast.show("No metrics to export.", "warn"); return; }
  const head = ["metric", "label", "value", "unit"].concat(_b ? ["baseline (" + _baseTag + ")"] : []);
  const rows = [head].concat(keys.map((k) => {
    const u = M.unitOf(M.parseKey(k).base);
    return [k, M.labelOf(k) || "", _v[k], u === "ratio" ? "ratio" : u].concat(_b ? [_b[k] === undefined ? "" : _b[k]] : []);
  }));
  downloadCsv((_tag || "run") + "-metrics.csv", toCsv(rows));
}
