// reportcard.js — the run report card: how a finished run went, in one card.
//
// The verdict is Verify's (verify-model.js verdictCopy), so Flow, Verify, the
// toast and the notification use the same words for the same run. The
// numbers are the run's own final metrics with the change against the run it
// is compared with; the warnings are counted by code (ORFS's stage summaries
// do the same: "warn 1002 (STA-1212 x1001, GPL-0302 x1)"), new codes first.

import { fmt } from "./api.js";
import { icon } from "./icons.js";
import * as V from "./verify-model.js";
import { fixChipHtml, problemLine } from "./problems.js";

const esc = (s) => fmt.escape(s == null ? "" : String(s));

export function fmtDur(s) {
  if (s == null || !Number.isFinite(s)) return "";
  if (s < 10) return (Math.round(s * 10) / 10) + " s";
  s = Math.round(s);
  if (s < 60) return s + " s";
  const m = Math.floor(s / 60);
  if (m < 60) return m + " min" + (s % 60 ? " " + (s % 60) + " s" : "");
  return Math.floor(m / 60) + " h " + (m % 60) + " min";
}

// The verdict of a finished run, as Verify words it: {tone, title, short, sub}.
export function verdictOf(vf, rx) {
  if (vf && vf.verdict) return V.verdictCopy(vf);
  if (rx && rx.kind === "clean") return { tone: "pass", title: "Clean", short: "clean", sub: "No step failed. Reading the sign-off checks…" };
  return null;
}

// Final metrics: the running total of what each step changed.
export function finalMetrics(rs) {
  let acc = {};
  for (const s of (rs && rs.steps) || []) if (s.changed) acc = { ...acc, ...s.changed };
  return acc;
}

const n = (m, k) => (m && typeof m[k] === "number" && Number.isFinite(m[k]) && Math.abs(m[k]) < 1e20 ? m[k] : null);
function bbox(m) {
  const b = String((m && m["design__die__bbox"]) || "").split(/\s+/).map(Number);
  return b.length === 4 && b.every(Number.isFinite) ? [b[2] - b[0], b[3] - b[1]] : null;
}
const um = (v) => String(Math.round(v * 10) / 10);
function power(w) {
  if (w == null) return null;
  return w >= 1 ? [w.toFixed(2), "W"] : w >= 1e-3 ? [(w * 1e3).toFixed(2), "mW"] : [(w * 1e6).toFixed(1), "µW"];
}

// A short line with the numbers (toast, notification, window title).
// `name` turns a step id into its human name (Flow's stepLabel) when given.
export function runSummary({ tag, design, rx, vf, rs, name = (id) => id }) {
  const v = verdictOf(vf, rx);
  const m = finalMetrics(rs);
  // A resumed run's time is its own steps', not the ones it reused.
  const secs = ((rs && rs.steps) || []).filter((s) => !s.from).reduce((a, s) => a + (s.runtime_s || 0), 0);
  const who = (design ? design + " · " : "") + tag;
  if (!rx) return { ok: false, title: who + " finished", body: "" };
  if (rx.kind === "clean" || rx.kind === "checks-failed") {
    const parts = [];
    const ws = n(m, "timing__setup__ws");
    if (ws != null) parts.push("setup " + (ws >= 0 ? "+" : "−") + Math.abs(ws).toFixed(2) + " ns");
    const d = bbox(m);
    if (d) parts.push(um(d[0]) + " × " + um(d[1]) + " µm");
    if (secs) parts.push(fmtDur(secs));
    if (rx.kind === "clean") {
      // Verify's words when it has answered: a run with warnings isn't plain clean.
      if (v && v.tone === "warn" && v.warned) {
        return { ok: true, tone: "warn", title: who + " is c" + v.title.slice(1), body: v.warned.join(", ") + (parts.length ? " · " + parts.join(" · ") : "") };
      }
      return { ok: true, tone: "pass", title: who + " is clean", body: parts.join(" · ") };
    }
    return { ok: false, tone: "fail", title: who + ": " + ((v && v.short) || "checks failed"), body: (v && v.sub) || parts.join(" · ") };
  }
  if (rx.kind === "stopped") return { ok: false, tone: "warn", title: who + ": you stopped it", body: "" };
  const c = rx.card || {};
  const at = rx.step ? (rx.step.id ? name(rx.step.id) : rx.step.dir) : "";
  return { ok: false, tone: "fail", title: who + " stopped" + (at ? " at " + at : ""),
    short: c.title || "", body: c.title ? c.title + (c.plain ? ". " + c.plain.split(". ")[0].replace(/\.$/, "") + "." : "") : ((rx.errors || [])[0] || "") };
}

// ------------------------------------------------------------------ the card
// ctx: { tag, rx, vf, steps, stages, base, baseRs }
export function reportCardHtml(c) {
  const v = verdictOf(c.vf, c.rx) || { tone: "warn", title: "Finished", sub: "" };
  const failed = c.rx.kind === "checks-failed";
  const m = c.steps.length ? c.steps[c.steps.length - 1].metrics || {} : {};
  const b = c.baseRs ? finalMetrics(c.baseRs) : null;
  const secs = c.steps.filter((s) => !s.from).reduce((a, s) => a + (s.secs || 0), 0);
  const bsecs = c.baseRs ? ((c.baseRs.steps || []).filter((s) => !s.from).reduce((a, s) => a + (s.runtime_s || 0), 0)) : null;
  const kpis = [
    kpi("Setup slack", n(m, "timing__setup__ws"), b && n(b, "timing__setup__ws"), { unit: "ns", signed: true, better: 1, tip: "Worst setup slack in any corner, after routing. Positive: the design meets its clock." }),
    kpi("Hold slack", n(m, "timing__hold__ws"), b && n(b, "timing__hold__ws"), { unit: "ns", signed: true, better: 1, tip: "Worst hold slack in any corner." }),
    dieKpi(m, b),
    kpi("Power", n(m, "power__total"), b && n(b, "power__total"), { power: true, better: -1, tip: "Total power OpenSTA estimated in the OpenROAD.STAPostPNR step (internal, switching and leakage), with default switching activity." }),
    kpi("Wire", n(m, "route__wirelength"), b && n(b, "route__wirelength"), { wire: true, better: -1, tip: "Total routed wire length." }),
    kpi("Run time", secs || null, bsecs || null, { time: true, better: -1, tip: "The sum of every step's time" +
      (c.steps.some((s) => s.from) ? ", without the steps it reused from the run it was resumed from." : ".") }),
  ].filter(Boolean).join("");
  const w = c.rx.warnings || { total: 0, by_code: [] };
  const acts = failed
    ? "<button class='btn btn-primary btn-sm' data-go='verify' data-go-section='vf-checks'>" + icon("alert", { size: 13 }) + " Show the problems</button>" +
      "<button class='btn btn-ghost btn-sm' data-go='layout'>" + icon("grid", { size: 13 }) + " See the chip</button>"
    : "<button class='btn btn-primary btn-sm' data-go='layout'>" + icon("grid", { size: 13 }) + " See your chip</button>" +
      "<button class='btn btn-ghost btn-sm' data-go='verify'>" + icon("check", { size: 13 }) + " Sign-off details</button>";
  // Three parts that sit side by side on a wide page (flow.css .fl-split):
  // the verdict, the numbers, and the warnings under both.
  return "<div class='an-verdict fl-hero fl-report is-" + esc(v.tone) + "'><div class='an-verdict-main fl-split'>" +
    "<div class='fl-split-a'><div class='an-eyebrow'>Run " + esc(c.tag) + (c.base ? " <span class='fl-vs'>compared with " + esc(c.base) + "</span>" : "") + "</div>" +
    "<h2 class='an-title'>" + esc(failed ? "The layout is done, but " + (v.short || "checks failed") : v.title) + "</h2>" +
    (c.branch || "") +
    "<p class='an-lede'>" + esc(v.sub || "") + "</p>" + (failed ? failedHtml(c) : "") +
    "<details class='fl-covers'><summary>What “clean” covers</summary><p>Clean means every check LibreLane runs on the layout passed: " +
      "design rules in Magic and KLayout, layout against netlist (LVS), the two GDS writers against each other (XOR), antenna rules, " +
      "and timing in every corner it checks. It does not cover simulating the finished netlist with its real delays (gate-level " +
      "simulation), a shuttle's own precheck, or the foundry's sign-off decks: LanEx is not a sign-off tool.</p></details></div>" +
    "<div class='fl-split-b'><div class='fl-kpis'>" + kpis + "</div></div>" +
    (w.total ? "<div class='fl-split-c'>" + warningsHtml(w) + "</div>" : "") +
    "</div><div class='an-verdict-act'>" + acts +
    "<button class='btn btn-ghost btn-sm' data-go='analytics'>" + icon("chart", { size: 13 }) + " Metrics</button></div></div>";
}

// What failed, worst first (problems.js): each problem's title, how bad it is,
// and its setting fixes as buttons that open the fix sheet.
function failedHtml(c) {
  const list = ((c.px && c.px.problems) || []).filter((p) => p.severity === "fail").slice(0, 3);
  if (!c.px) return "<div class='fl-failed is-loading'><span class='muted'>Reading what failed…</span></div>";
  if (!list.length) return "";
  return "<div class='fl-failed'><div class='fl-fixes-h'>What failed</div>" + list.map((p) => {
    const fixes = (p.fixes || []).filter((f) => f.kind === "setting").slice(0, 3);
    const check = (p.where && p.where.check) || "";
    return "<div class='fl-prob'><div class='fl-prob-h'><span class='vf-mark is-fail'></span><b>" + esc(p.title) + "</b></div>" +
      (problemLine(p) ? "<div class='fl-prob-n'>" + esc(problemLine(p)) + "</div>" : "") +
      "<div class='fl-prob-fix'>" + fixes.map((f, i) => fixChipHtml(f, { tag: c.tag, title: p.title, primary: i === 0 })).join("") +
        "<button class='fl-prob-more' data-go='verify' data-go-check='" + esc(check) + "'>Why, in Verify " + icon("chevron", { size: 11 }) + "</button></div></div>";
  }).join("") + "</div>";
}

function kpi(label, a, b, o = {}) {
  if (a == null) return "";
  let text, unit = o.unit || "";
  if (o.signed) text = (a >= 0 ? "+" : "−") + Math.abs(a).toFixed(2);
  else if (o.power) [text, unit] = power(a);
  else if (o.wire) [text, unit] = a >= 1000 ? [(a / 1000).toFixed(a >= 10000 ? 1 : 2), "mm"] : [String(Math.round(a)), "µm"];
  else if (o.time) { text = fmtDur(a); unit = ""; }
  else text = String(a);
  let delta = "";
  if (b != null && Number.isFinite(b)) {
    const d = a - b;
    // "Same" when the change doesn't show at the precision the value is shown at.
    const same = o.time ? Math.abs(d) < 1 : o.signed ? Math.abs(d) < 0.005 : Math.abs(d) < Math.abs(b) * 5e-4 + 1e-12;
    const good = same ? "same" : (d > 0) === (o.better > 0) ? "better" : "worse";
    let dt;
    if (same) dt = "same";
    else if (o.signed) dt = (d > 0 ? "+" : "−") + Math.abs(d).toFixed(2) + " ns";
    else if (o.time) dt = (d > 0 ? "+" : "−") + fmtDur(Math.abs(d));
    else dt = (d > 0 ? "+" : "−") + Math.abs((d / (b || 1)) * 100).toFixed(1) + " %";
    delta = "<span class='fl-delta is-" + good + "'>" + esc(dt) + "</span>";
  }
  const bad = o.signed && a < 0;
  // The exact value stays one hover away (the precision rule of the results pages).
  const exact = o.time ? "" : "\nExact: " + a + (o.unit ? " " + o.unit : o.power ? " W" : o.wire ? " µm" : "") + (b != null ? " (was " + b + ")" : "");
  return "<div class='fl-kpi" + (bad ? " is-bad" : "") + "' title='" + esc((o.tip || "") + exact) + "'><span class='fl-kpi-k'>" + esc(label) + "</span>" +
    "<span class='fl-kpi-v'>" + esc(text) + (unit ? "<small>" + esc(unit) + "</small>" : "") + "</span>" + delta + "</div>";
}

function dieKpi(m, b) {
  const d = bbox(m);
  if (!d) return "";
  const u = n(m, "design__instance__utilization");
  const bd = b ? bbox(b) : null;
  const delta = bd && (Math.abs(bd[0] - d[0]) > 0.05 || Math.abs(bd[1] - d[1]) > 0.05)
    ? "<span class='fl-delta is-neutral'>was " + esc(um(bd[0]) + " × " + um(bd[1])) + "</span>" : (bd ? "<span class='fl-delta is-same'>same</span>" : "");
  return "<div class='fl-kpi' title='The die, and how full the core is with cells'><span class='fl-kpi-k'>Die</span>" +
    "<span class='fl-kpi-v'>" + esc(um(d[0]) + " × " + um(d[1])) + "<small>µm</small></span>" +
    (u != null ? "<span class='fl-kpi-s'>core " + Math.round(u * 100) + " % full at the end</span>" : "") + delta + "</div>";
}

// "33 warnings: GPL-0302 ×1 (new) · STA-1140 ×18 · DRT-0349 ×10 · 3 more"
export function warningsHtml(w) {
  const groups = w.by_code || [];
  const top = groups.slice(0, 4).map((g) =>
    "<span class='fl-w" + (g.new ? " is-new" : "") + "' title='" + esc(g.sample || "") + "'><code>" + esc(g.code) + "</code> ×" + g.count +
      (g.new ? " <b>new</b>" : "") + "</span>").join("");
  const more = groups.length - 4 + (w.other ? 1 : 0);
  const notes = groups.filter((g) => g.note).map((g) => "<li><code>" + esc(g.code) + "</code> " + esc(g.note) + "</li>").join("");
  const list = groups.map((g) => "<li><code>" + esc(g.code) + "</code> ×" + g.count + (g.new ? " <b>new</b>" : "") +
    " <span class='muted'>" + esc(g.sample || "") + "</span></li>").join("") +
    (w.other ? "<li><span class='muted'>" + w.other + " without a code</span></li>" : "");
  return "<div class='fl-warns'><div class='fl-warns-h'>" + icon("alert", { size: 13 }) + " <b>" + w.total + " warnings</b>" +
    (w.compared_with && groups.some((g) => g.new) ? " <span class='muted'>(new: not in " + esc(w.compared_with) + ")</span>" : "") + "</div>" +
    "<div class='fl-w-row'>" + top + (more > 0 ? "<span class='fl-w muted'>" + more + " more</span>" : "") + "</div>" +
    (notes ? "<ul class='fl-notes'>" + notes + "</ul>" : "") +
    "<details class='fl-w-all'><summary>Every warning code</summary><ul>" + list + "</ul></details></div>";
}
