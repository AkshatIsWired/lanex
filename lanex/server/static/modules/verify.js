// verify.js — the Verify tab: did this run pass sign-off, and if not, why.
//
// Read top-down, the way sign-off reviews go in the commercial tools: one
// verdict (Vivado's run status / Calibre's summary), the four areas that
// decide tape-out, then every check in flow order with failures opened
// (Calibre RVE / KLayout's marker browser: rule, count, description,
// location), then the evidence per area: timing per corner (PrimeTime's
// global timing), DRC by rule, LVS counts, antenna and power, and the raw
// reports. Every verdict is LibreLane's own (controller/verify.py mirrors its
// Checker steps and the run's ERROR_ON_* switches); every number links to
// the file it came from.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import * as ctx from "./context.js";
import { mountRunBar } from "./runbar.js";
import { wireScrollSpy } from "./jumpnav.js";
import { icon } from "./icons.js";
import { provBtnHtml, wireProvBtns } from "./provenance.js";
import { renderFileText, fileActionsHtml, wireFileActions } from "./fileview.js";
import { renderTimingPaths } from "./timing.js";
import { toast } from "./toast.js";
import * as AM from "./analytics-model.js";
import * as V from "./verify-model.js";
import { wireTips } from "./analytics-charts.js";

const esc = (s) => fmt.escape(s == null ? "" : String(s));

let _tag = "";
let _baseTag = "";
let _rep = null;          // this run's /api/verify payload
let _base = null;         // baseline's payload (or null)
let _diff = null;         // V.statusDiff(_rep, _base)
let _filter = "all";      // all | problems | passed | unchecked
let _open = new Set();    // expanded check ids
let _token = 0;

// ---------- formatting -----------------------------------------------------------

function n(v) { return AM.num(v); }

function ns(v) {
  if (!V.isNum(v)) return AM.num(v);
  if (Math.abs(v) >= 1e12) return "no path";
  return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(3);
}

function mark(status) {
  const s = status === "partial" ? "pass" : status;
  return "<span class='vf-mark is-" + esc(s) + "' aria-hidden='true'></span>";
}

function statusPill(c) {
  const st = V.STATUS[c.status] || V.STATUS.not_run;
  let sub = "";
  if (c.status === "fail") sub = c.gate === "blocks" ? "blocks tape-out" : "";
  else if (c.status === "warn") sub = c.gate === "info" ? "not checked by LibreLane" : "LibreLane only warns";
  else if (c.status === "info" || (c.gate === "info" && c.status === "pass")) sub = "for information";
  return "<span class='vf-pill is-" + esc(c.status) + "'>" + esc(st.label) + "</span>" +
    (sub ? "<small class='vf-pill-sub'>" + esc(sub) + "</small>" : "");
}

// The headline value of one check, in its natural form.
function valueText(c) {
  if (c.status === "not_run") return "—";
  if (c.id === "setup" || c.id === "hold") {
    const parts = [];
    if (c.value !== null && c.value !== undefined && c.metric && c.metric.endsWith("vio__count")) {
      // The total covers every corner; say how many are in the corners that fail the run.
      const gated = (c.corners || []).filter((r) => r.gating && V.isNum(r.value)).reduce((a, r) => a + r.value, 0);
      const someWarnOnly = (c.corners || []).some((r) => !r.gating && V.isNum(r.value) && r.value > 0);
      parts.push(n(c.value) + " violating" + (someWarnOnly && c.value > 0 ? " (" + n(gated) + " in checked corners)" : ""));
    }
    if (V.isNum(c.worst)) parts.push("worst " + ns(c.worst) + " ns");
    return parts.join(" · ") || "—";
  }
  if (c.id === "antenna" && c.breakdown && c.breakdown.length) {
    const nets = c.breakdown.find((b) => b.metric === "antenna__violating__nets");
    const pins = c.breakdown.find((b) => b.metric === "antenna__violating__pins");
    return n(nets ? nets.value : c.value) + " nets · " + n(pins ? pins.value : 0) + " pins";
  }
  if (c.value === null || c.value === undefined) {
    if (c.status === "skipped") return "off";
    if (c.status === "fail") return "error raised";
    return "—";
  }
  if (typeof c.value === "string") return c.value;
  return n(c.value) + (c.unit ? " " + c.unit : "");
}

function provFor(c, key) {
  key = key || c.metric;
  // Only for a value LibreLane actually recorded.
  if (!key || !_tag || !(c.values && Object.keys(c.values).length)) return "";
  return provBtnHtml({ kind: "metric", key, tag: _tag }, "Show '" + key + "' in this run's metrics.json");
}

function head(eyebrow, title, lede, actions = "") {
  return "<header class='an-head'><div><div class='an-eyebrow'>" + esc(eyebrow) + "</div>" +
    "<h2 class='an-title'>" + title + "</h2>" + (lede ? "<p class='an-lede'>" + lede + "</p>" : "") + "</div>" +
    (actions ? "<div class='an-head-act'>" + actions + "</div>" : "") + "</header>";
}

function btn(label, attrs, { ic = "", primary = false } = {}) {
  return "<button class='btn " + (primary ? "btn-primary" : "btn-ghost") + " btn-sm' " + attrs + ">" +
    (ic ? icon(ic, { size: 13 }) + " " : "") + esc(label) + "</button>";
}

function stepLabel(ref) {
  if (!ref) return "";
  return (ref.n != null ? "step " + ref.n + " · " : "") + ref.id;
}

const byId = () => new Map((_rep.checks || []).map((c) => [c.id, c]));

// ---------- page entry ------------------------------------------------------------

// The run on screen is the app's (context.js); this page follows it.
let _rendering = null;
export function renderVerify() {
  _rendering = render();
  return _rendering;
}

async function render() {
  const body = document.getElementById("vf-body");
  if (!body) return;
  wireOnce();
  const runs = await ctx.loadRuns();
  const empty = document.getElementById("vf-empty");
  if (!runs.length || !ctx.contextRun()) {
    body.classList.add("is-empty");
    empty.hidden = false;
    return;
  }
  body.classList.remove("is-empty");
  empty.hidden = true;
  if (ctx.contextRun() !== _tag) _open.clear();
  await selectRun(ctx.contextRun());
}

// A link to one check (nav.js go("verify", { check })): open its row.
export async function revealCheck(id) {
  if (_rendering) await _rendering;
  jumpTo("vf-checks", id);
}

function wireOnce() {
  const sec = document.getElementById("sec-verify");
  if (!sec || sec._vfWired) return;
  sec._vfWired = true;
  wireTips(sec);
  mountRunBar(document.getElementById("verify-runbar"), { baseline: true });
  ctx.onContext(async (d) => {
    if (!sec.classList.contains("section-active") || d.why === "loaded" || d.why === "settled") return;   // it renders when shown
    if (d.why === "baseline") { _baseTag = ctx.contextBaseline(); await loadBase(); paint(); return; }
    renderVerify();
  });
  document.getElementById("btn-verify-refresh").addEventListener("click", () => renderVerify());
  document.getElementById("btn-verify-settings").addEventListener("click", async () => {
    const { openResolvedSettings } = await import("./finalsettings.js");
    openResolvedSettings(_tag);
  });
  document.getElementById("btn-verify-klayout").addEventListener("click", (e) => openKlayout(e.currentTarget));
  document.getElementById("btn-verify-copy").addEventListener("click", copySummary);
  const nav = document.getElementById("verify-jump");
  nav.addEventListener("click", (e) => {
    const b = e.target.closest("[data-jump]");
    if (!b) return;
    document.getElementById(b.dataset.jump)?.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  wireScrollSpy(nav);

  sec.addEventListener("click", (e) => {
    const t = e.target;
    const go = t.closest("[data-vf-jump]");
    if (go) { jumpTo(go.dataset.vfJump, go.dataset.vfOpen); return; }
    const row = t.closest("[data-vf-toggle]");
    if (row) { toggleRow(row.dataset.vfToggle); return; }
    const f = t.closest("[data-vf-filter]");
    if (f) { _filter = f.dataset.vfFilter; renderChecks(); wireProvBtns(document.getElementById("vf-checks")); return; }
    const view = t.closest("[data-vf-view]");
    if (view) { viewReport(view.dataset.vfView, view.dataset.vfTitle); return; }
    const log = t.closest("[data-vf-log]");
    if (log) { showLog(log.dataset.vfLog); return; }
    const rr = t.closest("[data-vf-rerun]");
    if (rr) { rerun(rr.dataset.vfRerun); return; }
    const kl = t.closest("[data-vf-klayout]");
    if (kl) { openKlayout(kl); return; }
    const more = t.closest("[data-vf-more]");
    if (more) {
      const box = more.closest(".vf-more-box");
      box?.classList.toggle("show-all");
      more.textContent = box?.classList.contains("show-all") ? "Show fewer" : more.dataset.vfMore;
    }
  });
}

async function selectRun(tag) {
  const my = ++_token;
  _tag = tag;
  _baseTag = ctx.contextBaseline();
  const body = document.getElementById("vf-body");
  body.classList.add("is-loading");
  let rep = null;
  try { rep = await api.verify(tag); } catch (_e) { rep = null; }
  if (my !== _token) return;
  _rep = rep;
  await loadBase();
  if (my !== _token) return;
  body.classList.remove("is-loading");
  if (!_rep) {
    document.getElementById("vf-overview").innerHTML = "<div class='empty'><span class='ico'>" + icon("alert", { size: 40 }) +
      "</span><h3>Could not read " + esc(tag) + "</h3><p>The run folder may have been moved or deleted. Refresh, or pick another run.</p></div>";
    for (const id of ["vf-checks", "vf-timing-body", "vf-drc", "vf-lvs", "vf-rel", "vf-reports-body"]) {
      const el = document.getElementById(id); if (el) el.innerHTML = "";
    }
    return;
  }
  // Problems open by default: that is what the user came to read.
  if (!_open.size) for (const c of _rep.checks || []) if (c.status === "fail") _open.add(c.id);
  paint();
  renderTimingPaths(tag);
}

async function loadBase() {
  _base = null;
  if (_baseTag) {
    try { _base = await api.verify(_baseTag); } catch (_e) { _base = null; }
  }
  _diff = V.statusDiff(_rep, _base);
}

function paint() {
  if (!_rep) return;
  renderOverview();
  renderChecks();
  renderTiming();
  renderDrc();
  renderLvs();
  renderRel();
  renderReports();
  const sec = document.getElementById("vf-body");
  wireProvBtns(sec);
  wireFileActions(sec);
  // The page height just changed under the jump bar: let its scroll-spy re-read.
  requestAnimationFrame(() => document.querySelector("main.work")?.dispatchEvent(new Event("scroll")));
}

function jumpTo(id, openCheck) {
  if (openCheck) {
    _open.add(openCheck);
    if (_filter !== "all") _filter = "all";
    renderChecks();
    wireProvBtns(document.getElementById("vf-checks"));
    id = "vf-row-" + openCheck;
  }
  const el = document.getElementById(id);
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: openCheck ? "center" : "start" });
  if (openCheck) { el.classList.add("is-flash"); setTimeout(() => el.classList.remove("is-flash"), 1400); }
}

// ---------- 1. overview -------------------------------------------------------------

function verdictCopy() {
  const v = _rep.verdict, f = _rep.flow_state || {};
  const by = byId();
  const names = (ids) => ids.map((id) => (by.get(id) || {}).name || id);
  const ran = (_rep.checks || []).filter((c) => ["pass", "fail", "warn", "info"].includes(c.status)).length;
  const stop = f.stopped_step;
  if (v.state === "blocked") {
    const k = v.blocker_ids.length;
    const title = (f.state === "stopped" && stop)
      ? "Stopped at step " + stop.n + ": " + names(v.blocker_ids).join(", ")
      : k + (k === 1 ? " problem blocks" : " problems block") + " tape-out";
    let sub = (f.state === "stopped")
      ? "LibreLane stopped the flow on this check, so nothing after it was built or checked."
      : "Fix them from the top: a problem early in the flow often causes the ones after it.";
    if (f.state === "deferred_errors") sub = "LibreLane finished every step, then failed the run on these. " + sub;
    return { tone: "fail", title, sub };
  }
  if (v.state === "stopped") {
    return { tone: "fail", title: "The flow stopped at step " + (stop ? stop.n : "?"),
      sub: (stop ? (stop.id || stop.dir) + " didn't finish. " : "") + ran + " of " + v.total + " checks ran before it stopped. The run log has the reason." };
  }
  if (v.state === "incomplete") {
    const miss = v.missing_core.map((id) => id === "drc" ? "DRC" : ((by.get(id) || {}).name || id));
    const off = (v.skipped_core || []).map((id) => (by.get(id) || {}).name || id);
    return { tone: "warn", title: "Not enough to call it",
      sub: "No result for " + miss.join(", ") + "." + (off.length ? " Turned off in this run's config: " + off.join(", ") + "." : "") +
        " Nothing failed, but these have to pass before the layout can go to a foundry." };
  }
  const w = v.warning_ids.length;
  return { tone: "pass", title: "Tape-out ready",
    sub: "Every check LibreLane makes on this layout passed" + (w ? "; " + w + (w === 1 ? " warning doesn't" : " warnings don't") + " block it." : ".") };
}

function renderOverview() {
  const el = document.getElementById("vf-overview");
  const v = _rep.verdict, f = _rep.flow_state || {};
  const cp = verdictCopy();
  const checks = _rep.checks || [];
  const cnt = (s) => checks.filter((c) => c.status === s).length;
  // One cell per check, in flow order: the whole run at a glance.
  const strip = "<div class='vf-strip' role='img' aria-label='" + esc(cnt("pass") + " passed, " + cnt("fail") + " failed, " + cnt("warn") + " warnings") + "'>" +
    checks.map((c) => "<button class='vf-cell is-" + esc(c.status) + "' data-vf-jump='vf-checks' data-vf-open='" + esc(c.id) +
      "' data-an-tip='" + esc(c.name + ": " + (V.STATUS[c.status] || {}).label + "\n" + valueText(c)) + "' aria-label='" + esc(c.name) + "'></button>").join("") +
    "</div>";
  const tally = [["pass", "passed"], ["fail", "failed"], ["warn", "warnings"], ["info", "info"], ["not_run", "not checked"], ["skipped", "turned off"]]
    .filter(([s]) => cnt(s)).map(([s, l]) => "<span class='vf-tally is-" + s + "'>" + mark(s) + "<b>" + cnt(s) + "</b> " + l + "</span>").join("");
  const meta = [
    _rep.design ? "<b>" + esc(_rep.design) + "</b>" : "",
    _rep.pdk ? esc(_rep.pdk) + (_rep.scl ? " / " + esc(_rep.scl) : "") : "",
    _rep.flow ? esc(_rep.flow) + " flow" : "",
    _rep.librelane_version ? "LibreLane " + esc(_rep.librelane_version) : "",
    f.steps_total ? esc(f.steps_done + " / " + f.steps_total + " steps") : "",
  ].filter(Boolean).join("<span class='sep'>/</span>");
  let flowNote = "";
  if (f.partial) flowNote = "<p class='vf-note'>Partial run (" + esc((f.frm ? "from " + f.frm : "") + (f.to ? " to " + f.to : "")) + "): only the steps in that range ran.</p>";
  if (f.state === "stopped" && f.error_log && f.error_log.length) {
    flowNote += "<pre class='vf-errlog'>" + esc(f.error_log.slice(0, 6).join("\n")) + "</pre>";
  }
  if (_rep.metrics_from) flowNote += "<p class='vf-note'>This run has no final metrics, so the values are the ones LibreLane saved after step " + esc(_rep.metrics_from.n + " (" + (_rep.metrics_from.id || _rep.metrics_from.dir) + ")") + ", the last step that finished.</p>";
  if (_rep.has_config === false) flowNote += "<p class='vf-note'>This run has no resolved.json, so LibreLane's defaults were assumed for which checks fail the run.</p>";
  const acts = (f.state === "stopped" ? btn("Open the run log", "data-go='runs'") : "") +
    (v.blocker_ids.length ? btn("Go to first problem", "data-vf-jump='vf-checks' data-vf-open='" + esc(v.blocker_ids[0]) + "'", { primary: true }) : "");
  const verdict =
    "<div class='an-verdict vf-verdict is-" + cp.tone + "'>" +
      "<div class='an-verdict-main'><div class='an-eyebrow'>Run " + esc(_rep.tag) + "</div>" +
        "<h2 class='an-title'>" + esc(cp.title) + "</h2>" +
        "<p class='an-lede'>" + esc(cp.sub) + "</p>" +
        "<div class='an-runmeta'>" + meta + "</div>" + flowNote +
      "</div>" +
      "<div class='vf-verdict-side'>" +
        "<div class='vf-tallies'>" + tally + "</div>" + strip +
        (acts ? "<div class='vf-verdict-acts'>" + acts + "</div>" : "") +
      "</div>" +
    "</div>";

  el.innerHTML = verdict + diffStrip() + "<div class='vf-pillars'>" + V.PILLARS.map(pillar).join("") + "</div>" +
    "<p class='an-foot'>Verdicts are LibreLane's own: each check is one of its Checker steps, judged with this run's settings (the ERROR_ON_… switches in resolved.json). " +
    "LanEx is not a sign-off tool: before fabrication, verify with the foundry's own rule decks.</p>";
}

function diffStrip() {
  if (!_base) return "";
  const d = _diff;
  const chip = (c, cls) => "<button class='vf-chip " + cls + "' data-vf-jump='vf-checks' data-vf-open='" + esc(c.id) + "'>" + mark(c.status) + esc(c.name) + "</button>";
  if (!d.regressed.length && !d.fixed.length) {
    return "<p class='an-basenote vf-diff'>" + icon("check", { size: 13 }) + " Same results as <b>" + esc(_baseTag) + "</b>" +
      (d.changed.size ? " (" + d.changed.size + " value" + (d.changed.size === 1 ? "" : "s") + " moved, no check changed state)." : ".") + "</p>";
  }
  return "<div class='vf-diff'><span class='vf-diff-h'>Since <b>" + esc(_baseTag) + "</b></span>" +
    (d.regressed.length ? "<span class='vf-diff-g'><span>New problems</span>" + d.regressed.map((c) => chip(c, "is-worse")).join("") + "</span>" : "") +
    (d.fixed.length ? "<span class='vf-diff-g'><span>Fixed</span>" + d.fixed.map((c) => chip(c, "is-better")).join("") + "</span>" : "") +
    "</div>";
}

function pillar(p) {
  const by = byId();
  const cs = p.checks.map((id) => by.get(id)).filter(Boolean);
  const st = V.worstStatus(cs.filter((c) => c.gate !== "info"));
  const d = _rep.details || {};
  let hero = "", rows = [];
  if (p.id === "timing") {
    const s = by.get("setup"), h = by.get("hold");
    const corners = (d.timing && d.timing.source === "signoff" && d.timing.corners) || [];
    hero = s && s.status !== "not_run" && V.isNum(s.worst) ? "<span class='vf-hero-v'>" + esc(ns(s.worst)) + "</span><span class='an-u'>ns setup slack</span>" : "<span class='vf-hero-v'>—</span>";
    rows = [
      ["Worst hold slack", h && h.status !== "not_run" && V.isNum(h.worst) ? ns(h.worst) + " ns" : "—", h],
      ["Setup / hold violations", (s && s.value != null ? n(s.value) : "—") + " / " + (h && h.value != null ? n(h.value) : "—"), null],
      ["Corners analysed", corners.length ? String(corners.length) : "—", null],
    ];
  } else if (p.id === "drc") {
    const mg = by.get("magic_drc"), kl = by.get("klayout_drc"), rt = by.get("route_drc");
    const vals = [mg, kl, rt].filter((c) => c && V.isNum(c.value)).map((c) => c.value);
    hero = vals.length ? "<span class='vf-hero-v'>" + esc(n(vals.reduce((a, b) => a + b, 0))) + "</span><span class='an-u'>errors</span>" : "<span class='vf-hero-v'>—</span>";
    rows = [["Magic", mg ? valueText(mg) : "—", mg], ["KLayout", kl ? valueText(kl) : "—", kl], ["Router", rt ? valueText(rt) : "—", rt]];
  } else if (p.id === "lvs") {
    const lv = by.get("lvs"), x = by.get("xor"), dp = by.get("disc_pin");
    const res = d.lvs && d.lvs.result;
    const ok = lv && lv.status === "pass";
    hero = "<span class='vf-hero-v vf-hero-word'>" + esc(lv && lv.status !== "not_run" && lv.status !== "skipped" ? (ok ? "Match" : "Mismatch") : "—") + "</span>";
    rows = [["Netgen", res || (lv && V.isNum(lv.value) ? n(lv.value) + " errors" : "—"), lv],
      ["XOR differences", x ? valueText(x) : "—", x], ["Disconnected pins", dp ? valueText(dp) : "—", dp]];
  } else {
    const an = by.get("antenna"), pd = by.get("pdn");
    const ir = (d.ir && d.ir.nets) || [];
    const worstPct = ir.filter((r) => V.isNum(r.pct)).reduce((m, r) => Math.max(m, r.pct), -1);
    hero = an && an.value != null ? "<span class='vf-hero-v'>" + esc(n(an.value)) + "</span><span class='an-u'>antenna nets</span>" : "<span class='vf-hero-v'>—</span>";
    rows = [["Antenna pins", an && an.breakdown && an.breakdown[1] ? n(an.breakdown[1].value) : "—", null],
      ["Power-grid issues", pd ? valueText(pd) : "—", pd],
      ["Worst IR drop", worstPct >= 0 ? worstPct + " % of supply" : "—", null]];
  }
  const stLabel = { pass: "Clean", partial: "Clean so far", fail: "Failing", warn: "Warnings", not_run: "Not checked", skipped: "Turned off" }[st] || "";
  return "<button class='vf-pillar is-" + esc(st) + "' data-vf-jump='" + p.jump + "'>" +
    "<span class='vf-pillar-top'><span class='an-kpi-t'>" + esc(p.title) + "</span><span class='vf-pillar-st'>" + mark(st) + esc(stLabel) + "</span></span>" +
    "<span class='vf-pillar-hero'>" + hero + "</span>" +
    "<span class='vf-pillar-rows'>" + rows.map(([l, val, c]) =>
      "<span class='vf-pr" + (c && (c.status === "fail" || c.status === "warn") ? " is-" + c.status : "") + "'><span>" + esc(l) + "</span><b>" + esc(val) + "</b></span>").join("") + "</span>" +
    "</button>";
}

// ---------- 2. checks ----------------------------------------------------------------

function filterMatch(c) {
  if (_filter === "problems") return c.status === "fail" || c.status === "warn";
  if (_filter === "passed") return c.status === "pass" || c.status === "info";
  if (_filter === "unchecked") return c.status === "not_run" || c.status === "skipped";
  return true;
}

function renderChecks() {
  const el = document.getElementById("vf-checks");
  const checks = _rep.checks || [];
  const count = (f) => { const keep = _filter; _filter = f; const k = checks.filter(filterMatch).length; _filter = keep; return k; };
  const seg = [["all", "All"], ["problems", "Problems"], ["passed", "Passed"], ["unchecked", "Not checked"]]
    .map(([f, l]) => "<button class='seg-btn" + (_filter === f ? " is-active" : "") + "' data-vf-filter='" + f + "' aria-pressed='" + (_filter === f) + "'>" +
      esc(l) + " <span class='vf-seg-n'>" + count(f) + "</span></button>").join("");
  const groups = (_rep.groups || []).map((g) => {
    const meta = V.GROUPS[g.id] || { title: g.title, n: "", lede: "" };
    const cs = g.checks.map((id) => checks.find((c) => c.id === id)).filter(Boolean);
    const shown = cs.filter(filterMatch);
    if (!shown.length) return "";
    const st = V.worstStatus(cs.filter((c) => c.gate !== "info" || c.status === "warn"));
    const passed = cs.filter((c) => c.status === "pass").length;
    return "<section class='vf-group is-" + esc(st) + "'>" +
      "<header class='vf-group-h'><span class='vf-step-n'>" + esc(meta.n) + "</span>" +
        "<div><h3>" + esc(meta.title) + " <small>" + esc(meta.tool || g.tool || "") + "</small></h3>" +
        "<p>" + esc(meta.lede) + "</p></div>" +
        "<span class='vf-group-st'>" + mark(st) + esc(passed + " of " + cs.length + " passed") + "</span></header>" +
      "<div class='vf-rows'>" + shown.map(rowHtml).join("") + "</div></section>";
  }).join("");
  el.innerHTML = head("Checks", "Every check, in flow order",
      "Each row is one of LibreLane's checks on this run. Click a row to see what it looks at, the numbers behind it and what to change. Problems are open already.",
      "<div class='seg vf-seg' role='group' aria-label='Filter checks'>" + seg + "</div>") +
    (groups ? "<div class='vf-groups'>" + groups + "</div>" : "<div class='an-none'>" + (_filter === "problems" ? "No problems in this run." : "Nothing to show for this filter.") + "</div>");
}

function rowHtml(c) {
  const open = _open.has(c.id);
  const ch = _diff && _diff.changed.get(c.id);
  let was = "";
  const real = (st) => st !== "not_run" && st !== "skipped";
  if (ch && !real(c.status)) { /* nothing to compare against */ }
  else if (ch && ch.from.status !== c.status && real(ch.from.status)) was = "<span class='vf-was' data-an-tip='" + esc("In " + _baseTag + ": " + (V.STATUS[ch.from.status] || {}).label + ", " + valueText(ch.from)) + "' tabindex='0'>was " + esc((V.STATUS[ch.from.status] || {}).label.toLowerCase()) + "</span>";
  else if (ch && String(ch.from.value) !== String(c.value) && ch.from.value != null) was = "<span class='vf-was' data-an-tip='" + esc("Value in " + _baseTag) + "' tabindex='0'>was " + esc(valueText(ch.from)) + "</span>";
  return "<div class='vf-row is-" + esc(c.status) + (open ? " is-open" : "") + "' id='vf-row-" + esc(c.id) + "'>" +
    "<button class='vf-row-main' data-vf-toggle='" + esc(c.id) + "' aria-expanded='" + open + "'>" +
      mark(c.status) +
      "<span class='vf-row-name'><b>" + esc(c.name) + "</b><small>" + esc(V.SHORT[c.id] || "") + "</small></span>" +
      "<span class='vf-row-val'><span>" + esc(valueText(c)) + "</span>" + (c.limit && c.status !== "skipped" ? "<small>" + esc(limitText(c.limit)) + "</small>" : "") + was + "</span>" +
      "<span class='vf-row-st'>" + statusPill(c) + "</span>" +
      "<span class='vf-chev' aria-hidden='true'>" + icon("chevron", { size: 14 }) + "</span>" +
    "</button>" +
    (open ? "<div class='vf-detail'>" + detailHtml(c) + "</div>" : "") +
    "</div>";
}

function limitText(l) {
  if (/^(no |0 expected)/.test(l)) return l;
  if (l === "proven") return "must be proven";
  return "limit " + l;
}

function toggleRow(id) {
  if (_open.has(id)) _open.delete(id); else _open.add(id);
  const row = document.getElementById("vf-row-" + id);
  const c = (_rep.checks || []).find((x) => x.id === id);
  if (!row || !c) return;
  const tmp = document.createElement("div");
  tmp.innerHTML = rowHtml(c);
  const fresh = tmp.firstElementChild;
  row.replaceWith(fresh);
  wireProvBtns(fresh);
}

function detailHtml(c) {
  const h = V.HELP[c.id] || {};
  const problem = c.status === "fail" || c.status === "warn";
  const explain =
    "<div class='vf-explain'>" +
      (h.what ? "<p><span class='vf-k'>What it checks</span>" + esc(h.what) + "</p>" : "") +
      (h.why ? "<p><span class='vf-k'>Why it matters</span>" + esc(h.why) + "</p>" : "") +
      (c.detail ? "<p class='vf-callout is-" + esc(c.status) + "'>" + esc(c.detail) + "</p>" : "") +
      (c.note ? "<p class='vf-callout is-warn'>" + esc(c.note) + "</p>" : "") +
      (h.fix && h.fix.length && (problem || c.status === "skipped")
        ? "<div class='vf-fix'><span class='vf-k'>" + (c.status === "skipped" ? "To turn it on" : "What to try") + "</span><ol>" + h.fix.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ol></div>"
        : (h.fix && h.fix.length ? "<details class='vf-fix-later'><summary>If this ever fails</summary><ol>" + h.fix.map((x) => "<li>" + esc(x) + "</li>").join("") + "</ol></details>" : "")) +
    "</div>";
  const gate = V.GATE[c.gate] || V.GATE.blocks;
  const ck = c.checker, tl = c.tool;
  const outcome = { passed: "passed", warned: "warned", raised: "raised an error", skipped: "skipped (no limit set)" };
  const dl = [
    ["Value", "<b>" + esc(valueText(c)) + "</b>" + provFor(c)],
    c.limit ? ["Limit", esc(c.limit)] : null,
    ["Decides", "<span class='has-tip' tabindex='0' data-an-tip='" + esc(gate.tip) + "'>" + esc(gate.label) + "</span>" + (c.gate_note ? "<small>" + esc(c.gate_note) + "</small>" : "")],
    ck ? ["Checked by", ck.dir ? esc(stepLabel(ck)) + (ck.outcome ? " · <b>" + esc(outcome[ck.outcome] || ck.outcome) + "</b>" : "") : esc(ck.id) + " · <span class='muted'>did not run</span>"] : null,
    tl ? ["Measured by", tl.dir ? esc(stepLabel(tl)) : esc(tl.id) + " · <span class='muted'>did not run</span>"] : null,
  ].filter(Boolean);
  let table = "";
  if (c.breakdown && c.breakdown.length) {
    table += "<table class='vf-mini'><tbody>" + c.breakdown.map((b) =>
      "<tr" + (V.isNum(b.value) && b.value > 0 && c.id !== "antenna" && !/iteration|diodes|all, incl/.test(b.label) ? " class='is-bad'" : "") + "><th scope='row'>" + esc(b.label) + "</th><td>" + esc(n(b.value)) +
      provBtnHtml({ kind: "metric", key: b.metric, tag: _tag }, "Show '" + b.metric + "' in metrics.json") + "</td></tr>").join("") + "</tbody></table>";
  }
  if (c.corners && c.corners.length) {
    table += "<table class='vf-mini'><thead><tr><th>Corner</th><th>Count</th><th>Fails the run?</th></tr></thead><tbody>" +
      [...c.corners].sort((a, b) => V.cornerSortKey(a.corner) - V.cornerSortKey(b.corner)).map((r) =>
        "<tr" + (V.isNum(r.value) && r.value > 0 ? " class='is-" + (r.gating ? "bad" : "warnrow") + "'" : "") + "><th scope='row'><span data-an-tip='" + esc(AM.cornerLabel(r.corner)) + "' tabindex='0'>" + esc(r.corner) + "</span></th><td>" + esc(n(r.value)) + "</td><td>" + (r.gating ? "yes" : "<span class='muted'>warns</span>") + "</td></tr>").join("") +
      "</tbody></table>";
  }
  const acts = [
    ...(c.reports || []).map((r) => btn("View " + r.label, "data-vf-view='" + esc(r.rel) + "' data-vf-title='" + esc(r.label) + "'", { ic: "eye" })),
    (tl && tl.dir) || (ck && ck.dir) ? btn("Step log", "data-vf-log='" + esc((tl && tl.dir) ? tl.id : ck.id) + "'", { ic: "file" }) : "",
    c.rerun && _rep.flow_state.state !== "stopped" ? btn("Re-run " + c.rerun, "data-vf-rerun='" + esc(c.rerun) + "'", { ic: "refresh" }) : "",
    sectionFor(c.id) ? btn("Details", "data-vf-jump='" + sectionFor(c.id) + "'", { ic: "chevron" }) : "",
  ].filter(Boolean).join("");
  return explain +
    "<div class='vf-evidence'><dl class='vf-dl'>" + dl.map(([k, v]) => "<div><dt>" + esc(k) + "</dt><dd>" + v + "</dd></div>").join("") + "</dl>" +
    table + (acts ? "<div class='vf-acts'>" + acts + "</div>" : "") + "</div>";
}

function sectionFor(id) {
  if (["setup", "hold", "slew", "cap", "fanout"].includes(id)) return "vf-timing";
  if (["magic_drc", "klayout_drc", "route_drc", "overlap"].includes(id)) return "vf-drc";
  if (["lvs", "xor"].includes(id)) return "vf-lvs";
  if (["antenna", "pdn", "wire_length"].includes(id)) return "vf-rel";
  return "";
}

// ---------- 3. timing ----------------------------------------------------------------

function renderTiming() {
  const el = document.getElementById("vf-timing-body");
  const t = (_rep.details && _rep.details.timing) || {};
  const by = byId();
  const rows = [...(t.corners || [])].sort((a, b) => V.cornerSortKey(a.corner) - V.cornerSortKey(b.corner));
  const sr = t.setup_rule || {}, hr = t.hold_rule || {};
  const rule = (r) => r.wildcards == null ? "every corner (rule unknown)" : !r.wildcards.length ? "no corner (warnings only)" :
    r.wildcards.length === 1 && r.wildcards[0] === "*" ? "every corner" : "corners matching " + r.wildcards.join(", ");
  const clk = V.isNum(t.clock_period) ? t.clock_period : Number(t.clock_period);
  const lede = rows.length
    ? "OpenSTA timed the routed layout in " + rows.length + " corners" + (Number.isFinite(clk) ? " against a " + clk + " ns clock (" + +(1000 / clk).toFixed(2) + " MHz)" : "") +
      ". LibreLane fails the run on setup violations in " + esc(rule(sr)) + " (" + esc(sr.var || "TIMING_VIOLATION_CORNERS") + ") and on hold violations in " + esc(rule(hr)) + "; slew and capacitance only warn."
    : "";
  if (!rows.length) {
    const s = by.get("setup");
    el.innerHTML = head("Timing", "Timing in every corner", "") +
      "<div class='an-none'>" + esc((s && s.detail) || "This run has no per-corner timing.") + "</div>";
    return;
  }
  const worst = (k, lo) => rows.reduce((m, r) => (V.isNum(r[k]) && (m === null || (lo ? r[k] < m : r[k] > m)) ? r[k] : m), null);
  const wS = worst("setup_ws", true), wH = worst("hold_ws", true);
  const cell = (r, k, { slack = false, gate = null } = {}) => {
    const v = r[k];
    if (v === undefined || v === null) return "<td class='muted'>—</td>";
    const bad = slack ? (V.isNum(v) && v < 0) : (V.isNum(v) && v > 0);
    const isW = slack && ((k === "setup_ws" && v === wS) || (k === "hold_ws" && v === wH));
    const cls = [bad ? (gate === false ? "is-warncell" : "is-bad") : "", isW ? "is-worst" : ""].filter(Boolean).join(" ");
    const txt = slack ? ns(v) : n(v);
    const tip = (slack ? k.startsWith("setup") ? "Setup" : "Hold" : k) + " · " + r.corner + "\n" + txt + (slack ? " ns" : "") +
      (gate === false && bad ? "\nThis corner only warns" : "") + (isW ? "\nWorst of all corners" : "");
    return "<td class='" + cls + "' data-an-tip='" + esc(tip) + "'>" + esc(txt) + "</td>";
  };
  const gateDot = (on, what) => on === undefined ? "" : "<span class='vf-gdot" + (on ? " is-on" : "") + "' data-an-tip='" + esc(on ? what + " violations here fail the run" : what + " violations here only warn") + "' tabindex='0'>" + (on ? "●" : "○") + "</span>";
  const body = rows.map((r) => {
    const g = r.gates || {};
    return "<tr" + (r.corner === t.default_corner ? " class='is-default'" : "") + ">" +
      "<th scope='row'><span class='vf-corner'><b>" + esc(AM.cornerShort(r.corner)) + "</b><small>" + esc(r.corner) + (r.corner === t.default_corner ? " · default" : "") + "</small></span></th>" +
      "<td class='vf-gcol'>" + gateDot(g.setup, "Setup") + "</td>" +
      cell(r, "setup_ws", { slack: true, gate: g.setup }) + cell(r, "setup_tns", { slack: true, gate: g.setup }) + cell(r, "setup_vio", { gate: g.setup }) +
      "<td class='vf-gcol'>" + gateDot(g.hold, "Hold") + "</td>" +
      cell(r, "hold_ws", { slack: true, gate: g.hold }) + cell(r, "hold_tns", { slack: true, gate: g.hold }) + cell(r, "hold_vio", { gate: g.hold }) +
      cell(r, "slew", { gate: false }) + cell(r, "cap", { gate: false }) + cell(r, "fanout", { gate: false }) +
      "</tr>";
  }).join("");
  const table = "<div class='vf-tscroll'><table class='an-ttable vf-ttable'><thead>" +
    "<tr><th rowspan='2' scope='col'>Corner</th><th colspan='4' class='vf-th-grp'>Setup <small>(max delay)</small></th><th colspan='4' class='vf-th-grp'>Hold <small>(min delay)</small></th><th colspan='3' class='vf-th-grp'>Electrical <small>(violations)</small></th></tr>" +
    "<tr><th class='vf-gcol'><span class='has-tip' tabindex='0' data-an-tip='● this corner fails the run on a violation; ○ it only warns'>gate</span></th><th><span class='has-tip' tabindex='0' data-an-tip='Worst slack (ns). Negative means a path misses the clock.'>WNS</span></th><th><span class='has-tip' tabindex='0' data-an-tip='Total negative slack (ns): the sum over every failing endpoint.'>TNS</span></th><th>Viol.</th>" +
    "<th class='vf-gcol'>gate</th><th>WHS</th><th>THS</th><th>Viol.</th><th>Slew</th><th>Cap</th><th>Fanout</th></tr>" +
    "</thead><tbody>" + body + "</tbody></table></div>";
  const facts = "<div class='vf-facts'>" +
    [["Setup", by.get("setup")], ["Hold", by.get("hold")], ["Max slew", by.get("slew")], ["Max cap", by.get("cap")]].map(([l, c]) => c
      ? "<button class='vf-fact is-" + esc(c.status) + "' data-vf-jump='vf-checks' data-vf-open='" + esc(c.id) + "'>" + mark(c.status) + "<span>" + esc(l) + "</span><b>" + esc(valueText(c)) + "</b></button>" : "").join("") +
    "</div>";
  const est = t.source === "estimate"
    ? "<p class='vf-callout is-warn'>Sign-off timing (OpenROAD.STAPostPNR) didn't run in this run. These are the last estimates an earlier timing step left behind, before routing finished; they are not a sign-off result.</p>" : "";
  el.innerHTML = head("Timing", "Timing in every corner", lede,
      btn("Timing charts in Analytics", "data-go='analytics' data-go-section='an-timing'", { ic: "chevron" })) +
    est + facts + "<div class='an-card vf-card-flush'>" + table + "</div>" +
    "<p class='an-foot'>A corner is a process (tt typical, ss slow, ff fast), temperature and voltage, with wire parasitics at their min, nominal or max. Worst values are outlined; red fails the run, amber only warns.</p>";
}

// ---------- 4. DRC -------------------------------------------------------------------

function ruleList(cats, { empty, total } = {}) {
  if (!cats || !cats.length) return "<p class='vf-clean'>" + mark("pass") + esc(empty || "No rule broken.") + "</p>";
  const items = cats.map((c, i) =>
    "<li class='vf-rule" + (i >= 6 ? " vf-extra" : "") + "'><div class='vf-rule-h'><code>" + esc(c.name) + (c.layer ? " · " + esc(c.layer) : "") + "</code><b>" + esc(n(c.count)) + "</b></div>" +
    (c.description && c.description !== c.name ? "<p>" + esc(c.description) + "</p>" : "") +
    (c.samples && c.samples.length ? "<small class='vf-loc'>at " + c.samples.slice(0, 3).map((b) => "(" + b[0].toFixed(2) + ", " + b[1].toFixed(2) + ")").join(", ") + " µm" + (c.count > 3 ? " …" : "") + "</small>" : "") +
    "</li>").join("");
  return "<div class='vf-more-box'><ul class='vf-rules'>" + items + "</ul>" +
    (cats.length > 6 ? "<button class='btn btn-ghost btn-sm' data-vf-more='Show all " + cats.length + " rules'>Show all " + cats.length + " rules</button>" : "") +
    (total ? "<p class='an-foot'>" + esc(total) + "</p>" : "") + "</div>";
}

function toolCard(title, c, body, rel, { sub = "" } = {}) {
  const st = c ? c.status : "not_run";
  return "<div class='an-card vf-tool is-" + esc(st) + "'>" +
    "<div class='vf-tool-h'><div><span class='an-kpi-t'>" + esc(title) + "</span>" + (sub ? "<small>" + esc(sub) + "</small>" : "") + "</div>" +
      "<span class='vf-pillar-st'>" + mark(st) + esc((V.STATUS[st] || {}).label || "") + "</span></div>" +
    "<div class='vf-tool-hero'><span class='vf-hero-v'>" + esc(c ? valueText(c) : "—") + "</span>" + (c && V.isNum(c.value) ? "<span class='an-u'>" + (c.value === 1 ? "error" : "errors") + "</span>" + provFor(c) : "") + "</div>" +
    (c && (c.status === "not_run" || c.status === "skipped") ? "<p class='vf-callout is-" + esc(st) + "'>" + esc(c.detail || "") + "</p>" : body) +
    (rel ? "<div class='vf-acts'>" + btn("View report", "data-vf-view='" + esc(rel) + "' data-vf-title='" + esc(title) + "'", { ic: "eye" }) + "</div>" : "") +
    "</div>";
}

function renderDrc() {
  const el = document.getElementById("vf-drc");
  const d = _rep.details || {};
  const by = byId();
  const mg = d.magic_drc, kl = d.klayout_drc, rt = d.route_drc;
  const iters = (rt && rt.iterations) || [];
  let iterHtml = "";
  if (iters.length) {
    const max = Math.max(1, ...iters.map((i) => V.isNum(i.count) ? i.count : 0));
    iterHtml = "<div class='vf-iters' role='img' aria-label='" + esc("Router DRC errors per pass: " + iters.map((i) => i.count).join(", ")) + "'>" +
      iters.map((i) => "<span class='vf-iter' data-an-tip='" + esc("Pass " + i.iter + ": " + n(i.count) + " violations") + "'><i style='height:" + Math.max(2, Math.round(100 * (i.count || 0) / max)) + "%'></i><small>" + esc(n(i.count)) + "</small></span>").join("") +
      "</div><p class='an-foot'>Violations left after each detailed-routing pass" + (iters[iters.length - 1].count === 0 ? ": the router cleared them all." : ".") + "</p>";
  }
  const markers = [mg && mg.markers, kl && kl.markers, rt && rt.markers].filter(Boolean).length;
  el.innerHTML = head("Design rules", "DRC: does the layout follow the foundry's rules?",
      "Two independent checkers read the final GDS (Magic and KLayout) and the router reports what it couldn't fix. Each broken rule is listed with the PDK's own description and where it is (µm from the die's origin).",
      markers ? btn("Open in KLayout with markers", "data-vf-klayout='1'", { ic: "layers" }) : "") +
    "<div class='an-grid an-grid-3'>" +
      toolCard("Magic DRC", by.get("magic_drc"), ruleList(mg && mg.categories, { empty: "No rule broken." }), mg && mg.report) +
      toolCard("KLayout DRC", by.get("klayout_drc"), ruleList(kl && kl.categories, { empty: kl && kl.rules ? "All " + kl.rules + " rules in the deck pass." : "No rule broken." }), kl && kl.report,
        { sub: kl && kl.rules ? kl.rules + " rules in the deck" : "" }) +
      toolCard("Router DRC", by.get("route_drc"), iterHtml + ruleList(rt && rt.categories, { empty: "Nothing left to fix." }), rt && rt.report) +
    "</div>" +
    (by.get("overlap") ? "<p class='an-foot'>Illegal overlaps found during extraction: <b>" + esc(valueText(by.get("overlap"))) + "</b>.</p>" : "");
}

// ---------- 5. LVS + XOR --------------------------------------------------------------

function renderLvs() {
  const el = document.getElementById("vf-lvs");
  const d = _rep.details || {};
  const by = byId();
  const lv = d.lvs, c = by.get("lvs"), x = d.xor, xc = by.get("xor");
  let lvsBody = "";
  if (lv && lv.layout && lv.netlist) {
    const row = (label, k, tip) => {
      const a = lv.layout[k], b = lv.netlist[k];
      const same = a === b;
      return "<tr" + (same ? "" : " class='is-bad'") + "><th scope='row'><span class='has-tip' tabindex='0' data-an-tip='" + esc(tip) + "'>" + esc(label) + "</span></th><td>" + esc(n(a)) + "</td><td>" + esc(n(b)) + "</td><td>" + (same ? mark("pass") : mark("fail")) + "</td></tr>";
    };
    lvsBody = "<table class='an-ttable vf-lvs-t'><thead><tr><th></th><th>Layout <small>(extracted)</small></th><th>Netlist <small>(from synthesis)</small></th><th></th></tr></thead><tbody>" +
      row("Devices", "devices", "Cell instances, including fill, tap and decap cells.") +
      row("Nets", "nets", "Distinct electrical nodes.") +
      row("Pins", "pins", "Top-level ports, power included.") +
      "</tbody></table>";
    if (lv.device_diffs && lv.device_diffs.length) {
      lvsBody += "<p class='vf-k'>Device counts that differ</p><table class='vf-mini'><thead><tr><th>Layout</th><th></th><th>Netlist</th><th></th></tr></thead><tbody>" +
        lv.device_diffs.map((r) => "<tr class='is-bad'><td><code>" + esc(r.layout) + "</code></td><td>" + esc(n(r.layout_n)) + "</td><td><code>" + esc(r.netlist) + "</code></td><td>" + esc(n(r.netlist_n)) + "</td></tr>").join("") + "</tbody></table>";
    }
    if (lv.pin_diffs && lv.pin_diffs.length) {
      lvsBody += "<p class='vf-k'>Pins that don't match</p><table class='vf-mini'><tbody>" +
        lv.pin_diffs.map((r) => "<tr class='is-bad'><td><code>" + esc(r.layout) + "</code></td><td>↔</td><td><code>" + esc(r.netlist) + "</code></td></tr>").join("") + "</tbody></table>";
    }
  }
  if (c && c.breakdown && c.breakdown.length) {
    lvsBody += "<table class='vf-mini'><tbody>" + c.breakdown.map((b) => "<tr" + (V.isNum(b.value) && b.value > 0 ? " class='is-bad'" : "") + "><th scope='row'>" + esc(b.label) + "</th><td>" + esc(n(b.value)) + provBtnHtml({ kind: "metric", key: b.metric, tag: _tag }, "Show in metrics.json") + "</td></tr>").join("") + "</tbody></table>";
  }
  const result = lv && lv.result
    ? "<p class='vf-lvs-result is-" + (c && c.status === "pass" ? "pass" : "fail") + "'>" + mark(c && c.status === "pass" ? "pass" : "fail") + "Netgen: <b>" + esc(lv.result) + "</b></p>" : "";
  const lvsCard = "<div class='an-card vf-tool is-" + esc(c ? c.status : "not_run") + "'>" +
    "<div class='vf-tool-h'><div><span class='an-kpi-t'>LVS · Netgen</span><small>Layout vs. schematic</small></div><span class='vf-pillar-st'>" + mark(c ? c.status : "not_run") + esc(c ? (V.STATUS[c.status] || {}).label : "") + "</span></div>" +
    (c && (c.status === "not_run" || c.status === "skipped") ? "<p class='vf-callout is-" + esc(c.status) + "'>" + esc(c.detail || "") + "</p>" : result + lvsBody) +
    (c && c.status === "fail" ? "<p class='vf-callout is-warn'>Work through it in this order: pins, then nets, then devices. A short between two nets shows up as one fewer net in the layout, and fixing it often clears the device errors too.</p>" : "") +
    (lv && lv.report ? "<div class='vf-acts'>" + btn("View Netgen report", "data-vf-view='" + esc(lv.report) + "' data-vf-title='Netgen LVS report'", { ic: "eye" }) + "</div>" : "") +
    "</div>";
  const xorBody = x
    ? "<p class='vf-big'><span class='vf-hero-v'>" + esc(xc ? valueText(xc) : n(x.total)) + "</span><span class='an-u'>differences</span>" + (xc ? provFor(xc) : "") + "</p>" +
      "<p class='an-lede vf-small'>" + esc(V.isNum(x.layers) ? x.layers + " GDS layers compared between Magic's and KLayout's stream-out." : "Magic's and KLayout's stream-outs compared layer by layer.") + "</p>" +
      ruleList((x.categories || []).map((cat) => ({ ...cat, name: "layer " + cat.name })), { empty: "Every layer is identical." })
    : "";
  const xorCard = "<div class='an-card vf-tool is-" + esc(xc ? xc.status : "not_run") + "'>" +
    "<div class='vf-tool-h'><div><span class='an-kpi-t'>Mask XOR · KLayout</span><small>Magic GDS vs. KLayout GDS</small></div><span class='vf-pillar-st'>" + mark(xc ? xc.status : "not_run") + esc(xc ? (V.STATUS[xc.status] || {}).label : "") + "</span></div>" +
    (xc && (xc.status === "not_run" || xc.status === "skipped") ? "<p class='vf-callout is-" + esc(xc.status) + "'>" + esc(xc.detail || "") + "</p>" : xorBody) +
    (x && x.report ? "<div class='vf-acts'>" + btn("View xor.xml", "data-vf-view='" + esc(x.report) + "' data-vf-title='XOR report'", { ic: "eye" }) + "</div>" : "") +
    "</div>";
  el.innerHTML = head("Connectivity", "LVS & XOR: is the layout the circuit you designed?",
      "LVS rebuilds the circuit from the drawn shapes and compares it with your netlist. XOR checks that the two GDS files LibreLane writes are the same shapes.") +
    "<div class='an-grid vf-grid-lvs'>" + lvsCard + xorCard + "</div>";
}

// ---------- 6. antenna, power, wires -----------------------------------------------------

function renderRel() {
  const el = document.getElementById("vf-rel");
  const d = _rep.details || {};
  const by = byId();
  const an = by.get("antenna"), pd = by.get("pdn"), wl = by.get("wire_length");
  const ant = d.antenna;
  let antBody = "";
  if (an && an.breakdown && an.breakdown.length) {
    antBody = "<dl class='vf-dl vf-dl-compact'>" + an.breakdown.map((b) => "<div><dt>" + esc(b.label) + "</dt><dd><b>" + esc(n(b.value)) + "</b>" + provBtnHtml({ kind: "metric", key: b.metric, tag: _tag }, "Show in metrics.json") + "</dd></div>").join("") + "</dl>";
  }
  if (ant && ant.rows && ant.rows.length) {
    antBody += "<div class='vf-tscroll'><table class='vf-mini'><thead><tr><th>Net</th><th>Pin</th><th>Layer</th><th><span class='has-tip' tabindex='0' data-an-tip='Partial antenna ratio over the required ratio. Over 1 is a violation.'>Ratio</span></th></tr></thead><tbody>" +
      ant.rows.map((r) => "<tr class='is-bad'><td><code>" + esc(r.net) + "</code></td><td><code>" + esc(r.pin) + "</code></td><td>" + esc(r.layer) + "</td><td>" + esc(r.partial) + " / " + esc(r.required) + "</td></tr>").join("") +
      "</tbody></table></div>" + (ant.more ? "<p class='an-foot'>" + ant.more + " more in the report.</p>" : "");
  } else if (an && an.status === "pass") {
    antBody += "<p class='vf-clean'>" + mark("pass") + "No net or pin over the antenna ratio after repair.</p>";
  }
  const antCard = "<div class='an-card vf-tool is-" + esc(an ? an.status : "not_run") + "'>" +
    "<div class='vf-tool-h'><div><span class='an-kpi-t'>Antenna · OpenROAD</span><small>Final check after routing</small></div><span class='vf-pillar-st'>" + mark(an ? an.status : "not_run") + esc(an ? (V.STATUS[an.status] || {}).label : "") + "</span></div>" +
    (an && an.status === "not_run" ? "<p class='vf-callout is-not_run'>" + esc(an.detail || "") + "</p>" : antBody) +
    (ant && ant.report ? "<div class='vf-acts'>" + btn("View antenna report", "data-vf-view='" + esc(ant.report) + "' data-vf-title='Antenna summary'", { ic: "eye" }) + "</div>" : "") +
    "</div>";

  const ir = (d.ir && d.ir.nets) || [];
  const irRows = ir.map((r) => {
    const pct = V.isNum(r.pct) ? r.pct : null;
    const mv = (x) => V.isNum(x) ? (x * 1000).toFixed(x * 1000 >= 10 ? 1 : 3) + " mV" : "—";
    return "<tr><th scope='row'>" + esc(r.net) + "</th><td>" + mv(r.worst_drop) + "</td><td>" + mv(r.avg_drop) + "</td>" +
      "<td><span class='vf-bar'><i style='width:" + Math.min(100, (pct || 0) * 10) + "%'></i></span>" + (pct !== null ? esc(pct + " %") : "—") + "</td></tr>";
  }).join("");
  const pdnBody = (pd && pd.breakdown && pd.breakdown.length
      ? "<dl class='vf-dl vf-dl-compact'>" + pd.breakdown.map((b) => "<div><dt>Unconnected, " + esc(b.label) + "</dt><dd><b>" + esc(n(b.value)) + "</b>" + provBtnHtml({ kind: "metric", key: b.metric, tag: _tag }, "Show in metrics.json") + "</dd></div>").join("") + "</dl>"
      : (pd && pd.status === "pass" ? "<p class='vf-clean'>" + mark("pass") + "Every cell reaches the power grid.</p>" : "")) +
    (irRows ? "<p class='vf-k'>IR drop" + (ir[0] && ir[0].corner ? " · " + esc(ir[0].corner) : "") + "</p><table class='vf-mini vf-ir'><thead><tr><th>Net</th><th>Worst</th><th>Average</th><th><span class='has-tip' tabindex='0' data-an-tip='Worst drop as a share of the supply voltage. The bar is full at 10 %.'>Of supply</span></th></tr></thead><tbody>" + irRows + "</tbody></table>" +
      "<p class='an-foot'>LibreLane reports IR drop but doesn't judge it; a few percent of the supply is a common budget.</p>" : "");
  const pdnCard = "<div class='an-card vf-tool is-" + esc(pd ? pd.status : "not_run") + "'>" +
    "<div class='vf-tool-h'><div><span class='an-kpi-t'>Power grid · OpenROAD</span><small>Connections and IR drop</small></div><span class='vf-pillar-st'>" + mark(pd ? pd.status : "not_run") + esc(pd ? (V.STATUS[pd.status] || {}).label : "") + "</span></div>" +
    pdnBody +
    (d.ir && d.ir.report ? "<div class='vf-acts'>" + btn("View IR report", "data-vf-view='" + esc(d.ir.report) + "' data-vf-title='IR drop report'", { ic: "eye" }) + "</div>" : "") +
    "</div>";
  const wire = wl && wl.value != null
    ? "<p class='an-foot'>Longest routed wire: <b>" + esc(valueText(wl)) + "</b>" + provFor(wl) + " · " + esc(wl.gate_note || "") + ".</p>" : "";
  el.innerHTML = head("Reliability", "Antenna & power: will it survive fabrication and power up?",
      "Antenna violations can damage transistors while the chip is being made; the power grid has to reach every cell without losing too much voltage on the way.") +
    "<div class='an-grid'>" + antCard + pdnCard + "</div>" + wire;
}

// ---------- 7. reports --------------------------------------------------------------------

async function renderReports() {
  const el = document.getElementById("vf-reports-body");
  if (!el) return;
  const tag = _tag;
  // The files each verdict was read from, named by what they prove.
  const key = [];
  const seen = new Set();
  const add = (rel, label, what) => { if (rel && !seen.has(rel)) { seen.add(rel); key.push({ rel, label, what }); } };
  const d = _rep.details || {};
  add(d.magic_drc && d.magic_drc.report, "Magic DRC report", "DRC");
  add(d.magic_drc && d.magic_drc.markers, "Magic DRC markers (KLayout database)", "DRC");
  add(d.klayout_drc && d.klayout_drc.report, "KLayout DRC counts per rule", "DRC");
  add(d.klayout_drc && d.klayout_drc.markers, "KLayout DRC markers (KLayout database)", "DRC");
  add(d.route_drc && d.route_drc.report, "Router DRC report", "DRC");
  add(d.lvs && d.lvs.report, "Netgen LVS report", "LVS");
  add(d.lvs && d.lvs.json, "Netgen LVS comparison (JSON)", "LVS");
  add(d.xor && d.xor.report, "XOR markers (KLayout database)", "XOR");
  add(d.antenna && d.antenna.report, "Antenna summary", "Antenna");
  add(d.ir && d.ir.report, "IR-drop report", "Power");
  for (const c of _rep.checks || []) for (const r of c.reports || []) add(r.rel, c.name + ": " + r.label, (V.GROUPS[c.group] || {}).title || "");
  const row = (rel, name, sub) => "<div class='vf-rep'><div class='vf-rep-n'><code title='" + esc(rel) + "'>" + esc(name) + "</code><small>" + esc(sub) + "</small></div>" +
    "<span class='vf-rep-a'>" + btn("View", "data-vf-view='" + esc(rel) + "' data-vf-title='" + esc(name) + "'", { ic: "eye" }) + fileActionsHtml(tag, rel) + "</span></div>";
  const keyHtml = key.length ? "<div class='vf-rep-g vf-rep-key'><span class='an-check-gname'>Sign-off evidence</span>" +
    key.map((k) => row(k.rel, k.label, k.rel)).join("") + "</div>" : "";
  el.innerHTML = "<div class='vf-reports'>" + keyHtml + "<div class='vf-rep-g'><span class='an-check-gname'>Tool logs</span><p class='muted'>Looking…</p></div></div>";
  wireFileActions(el);
  let reps = [];
  try {
    const r = await api.runReports((ctx.contextRow(tag) || {})._design || state.designDir, tag);
    reps = ((r && r.reports) || []).filter((x) => x.rel && !seen.has(x.rel));
  } catch (_e) {}
  if (tag !== _tag) return;
  const rest = reps.length
    ? "<div class='vf-rep-g'><span class='an-check-gname'>Tool logs and other reports</span>" +
      reps.map((r) => row(r.rel, r.name, (r.kind ? r.kind + " · " : "") + (r.step || ""))).join("") + "</div>"
    : "";
  el.innerHTML = "<div class='vf-reports'>" + keyHtml + rest + "</div>";
  if (!keyHtml && !rest) el.innerHTML = "<div class='an-none'>No report files found for this run.</div>";
  wireFileActions(el);
}

// ---------- actions -------------------------------------------------------------------------

async function viewReport(rel, title) {
  if (!rel) return;
  const { customDialog } = await import("./dialog.js");
  const tag = _tag;
  customDialog({
    title: esc(title || rel), wide: true,
    bodyHtml: "<div class='vf-viewer'><p class='muted'>Loading " + esc(rel) + "…</p></div>",
    onMount: async (dlg) => {
      const host = dlg.querySelector(".vf-viewer");
      try {
        const resp = await fetch(api.runFileUrl(tag, rel), { headers: { "X-Requested-With": "XMLHttpRequest" } });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        let text = await resp.text();
        const cap = 2 * 1024 * 1024;
        if (text.length > cap) text = text.slice(0, cap) + "\n\n… (first 2 MB shown; download the file for the rest)";
        renderFileText(host, text, { tag, path: rel, title: rel });
      } catch (ex) {
        host.innerHTML = "<p class='pill pill-fail'>Could not load: " + esc(ex.message || ex) + "</p>";
      }
    },
  });
}

// The step's own log, in place (no trip to Pipeline).
async function showLog(stepId) {
  const { customDialog } = await import("./dialog.js");
  const tag = _tag;
  customDialog({
    title: esc(stepId + " · log"), wide: true,
    bodyHtml: "<div class='vf-viewer'><p class='muted'>Loading the log…</p></div>",
    onMount: async (dlg) => {
      const host = dlg.querySelector(".vf-viewer");
      let r = null;
      try { r = await api.runStepLog(stepId, tag); } catch (ex) { r = { ok: false, reason: ex.message || String(ex) }; }
      if (!r || !r.ok) { host.innerHTML = "<p class='muted'>" + esc((r && r.reason) || "This step wrote no log.") + "</p>"; return; }
      const rel = (r.dir && r.log_file) ? r.dir + "/" + r.log_file : null;
      renderFileText(host, (r.truncated ? "… (the end of the log)\n\n" : "") + (r.log || "(empty log)"),
        { tag, path: rel, title: rel || stepId, emptyMsg: "(empty log)", scrollBottom: true });
    },
  });
}

async function rerun(stepId) {
  const { promptDialog } = await import("./dialog.js");
  const extra = await promptDialog({
    title: "Re-run " + stepId + " on " + _tag,
    label: "Runs only this step again, on this run's saved results, and updates its numbers. The checker after it doesn't run again, so this page re-judges the new value. " +
      "Optional setting overrides, as KEY=VALUE separated by commas:",
    defaultValue: "",
  });
  if (extra === null) return;
  const overrides = {};
  for (const pair of extra.split(",")) {
    const [k, val] = pair.split("=");
    if (k && k.trim() && val !== undefined) overrides[k.trim()] = val.trim();
  }
  try {
    const res = await api.verifyRerun({ step_id: stepId, overrides, run_tag: _tag, run_mode: state.runMode });
    if (res.ok) {
      toast.show("Re-running " + stepId + ". Follow it in Pipeline, then press Refresh here.", "success");
      import("./nav.js").then((m) => m.go("pipeline"));
    } else {
      toast.show("Re-run refused: " + (res.reason || res.error || "unknown"), "error");
    }
  } catch (ex) {
    toast.show("Re-run failed: " + (ex.message || ex), "error");
  }
}

async function openKlayout(btnEl) {
  if (!_tag) return;
  const { openRunInTool } = await import("./layouttools.js");
  if (btnEl) btnEl.disabled = true;
  try { await openRunInTool("klayout", _tag); } finally { if (btnEl) btnEl.disabled = false; }
}

// A plain-text checklist to paste into an issue, chat or review.
async function copySummary() {
  if (!_rep) return;
  const cp = verdictCopy();
  const sym = { pass: "PASS", fail: "FAIL", warn: "WARN", info: "INFO", not_run: "----", skipped: "OFF " };
  const lines = ["Sign-off: " + cp.title + " (" + _rep.tag + (_rep.design ? ", " + _rep.design : "") + (_rep.pdk ? ", " + _rep.pdk : "") + ")", ""];
  for (const g of _rep.groups || []) {
    lines.push((V.GROUPS[g.id] || g).title);
    for (const id of g.checks) {
      const c = _rep.checks.find((x) => x.id === id);
      if (c) lines.push("  [" + sym[c.status] + "] " + c.name + ": " + valueText(c));
    }
  }
  lines.push("", "Judged by LibreLane's checkers with this run's settings (LanEx).");
  try {
    await navigator.clipboard.writeText(lines.join("\n"));
    toast.show("Sign-off summary copied", "success");
  } catch (_e) {
    toast.show("Clipboard not available", "warn");
  }
}
