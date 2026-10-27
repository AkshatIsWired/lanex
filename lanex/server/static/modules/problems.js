// problems.js — the problems of a run, one shape for every page.
//
// The server's knowledge base (controller/problems.py) reads the run and says,
// for the step that stopped it and every failing or warning check: a plain
// title, what happened with the run's own numbers, the diagnosis (timing:
// where it first failed and what fails; DRC: rules and places) and the fixes.
// A setting fix names the variable, its value in that run, the value to try,
// why, and the first step that reads it (where a resumed run starts). Flow,
// Verify and the status bar all show these; Apply opens the fix sheet.

import { api, fmt } from "./api.js";
import { icon } from "./icons.js";
import * as FS from "./flowstages.js";
import * as ctx from "./context.js";

const esc = (s) => fmt.escape(s == null ? "" : String(s));
const _cache = new Map();          // tag -> { p: Promise, at }
const _subs = new Set();

// The problems of one run (remembered; `fresh` asks again).
export function problemsOf(tag, { fresh = false } = {}) {
  if (!tag) return Promise.resolve(null);
  const hit = _cache.get(tag);
  if (hit && !fresh && Date.now() - hit.at < 120000) return hit.p;
  const p = api.problems(tag).catch(() => null);
  _cache.set(tag, { p, at: Date.now() });
  p.then((r) => { if (r) for (const fn of _subs) fn(tag, r); });
  return p;
}

// Called with (tag, problems) whenever a run's problems arrive.
export function onProblems(fn) { _subs.add(fn); return () => _subs.delete(fn); }

export function forgetProblems(tag) { if (tag) _cache.delete(tag); else _cache.clear(); }

// "resumes at Floorplan" / "resumes at Synthesis, step 6" for a setting fix.
export function resumeText(r) {
  if (!r) return "runs the whole flow";
  const st = FS.stageLabel(r.stage);
  return "resumes at " + st + (r.n && !r.stage_start ? ", step " + r.n : "");
}

// One fix, as a row: the change and why, then Apply (a setting) or the link
// (anything else). `n` numbers it; `primary` marks the one to try first.
export function fixRowHtml(f, { tag, title, n = 0, primary = false } = {}) {
  if (f.kind === "setting") {
    const r = f.resume;
    return "<li class='px-fix'>" + (n ? "<span class='px-fix-n'>" + n + "</span>" : "") +
      "<div class='px-fix-main'>" +
        "<div class='px-fix-what'>" + (f.label ? "<b>" + esc(f.label) + "</b>" : "") +
          "<span class='px-chg'><code>" + esc(f.var) + "</code> <span class='px-from'>" + esc(f.from || "unset") + "</span>" +
          icon("chevron", { size: 11 }) + "<span class='px-to'>" + esc(f.to) + "</span></span></div>" +
        "<div class='px-fix-why'>" + esc(f.why) + "</div>" +
        "<div class='px-fix-at' title='The first step of the flow that reads " + esc(f.var) + "'>" + icon("refresh", { size: 11 }) + " " + esc(resumeText(r)) + "</div>" +
      "</div>" +
      "<button class='btn " + (primary ? "btn-primary" : "btn-ghost") + " btn-sm' data-fix-tag='" + esc(tag) + "' data-fix-var='" + esc(f.var) +
        "' data-fix-to='" + esc(f.to) + "' data-fix-title='" + esc(title || "") + "' data-fix-why='" + esc(f.why || "") + "'>Apply…</button></li>";
  }
  if (f.kind === "open" && f.go) {
    const attrs = Object.entries(f.go).map(([k, v]) => k === "tab" ? "data-go='" + esc(v) + "'" : "data-go-" + esc(k) + "='" + esc(v) + "'").join(" ");
    return "<li class='px-fix is-open'>" + (n ? "<span class='px-fix-n'>" + n + "</span>" : "") +
      "<div class='px-fix-main'><div class='px-fix-what'><b>" + esc(f.label) + "</b></div>" +
      (f.why ? "<div class='px-fix-why'>" + esc(f.why) + "</div>" : "") + "</div>" +
      "<button class='btn btn-ghost btn-sm' " + attrs + ">" + esc(shortOpen(f.label)) + " " + icon("chevron", { size: 12 }) + "</button></li>";
  }
  return "";
}
const shortOpen = (label) => (/layout/i.test(label) ? "Show" : /paths/i.test(label) ? "Show" : "Open");

export function fixListHtml(fixes, { tag, title } = {}) {
  const set = (fixes || []).filter((f) => f.kind === "setting");
  const firstSetting = set.length ? fixes.indexOf(set[0]) : -1;
  let n = 0;
  return "<ol class='px-fixes'>" + (fixes || []).map((f, i) =>
    fixRowHtml(f, { tag, title, n: f.kind === "setting" ? ++n : 0, primary: i === firstSetting })).join("") + "</ol>";
}

// A setting fix as one button that opens the sheet ("Slow the clock 1.5 → 2.4").
export function fixChipHtml(f, { tag, title, primary = false } = {}) {
  if (f.kind !== "setting") return "";
  return "<button class='px-chip" + (primary ? " is-primary" : "") + "' data-fix-tag='" + esc(tag) + "' data-fix-var='" + esc(f.var) +
    "' data-fix-to='" + esc(f.to) + "' data-fix-title='" + esc(title || "") + "' data-fix-why='" + esc(f.why || "") +
    "' title='" + esc(f.var + ": " + (f.from || "unset") + " → " + f.to + ". " + (f.why || "") + " (" + resumeText(f.resume) + ")") + "'>" +
    "<b>" + esc(f.label || f.var) + "</b><span class='px-chip-v'>" + esc(f.from || "unset") + " → " + esc(f.to) + "</span></button>";
}

const ns = (v) => (typeof v === "number" ? (v < 0 ? "−" : "+") + Math.abs(v).toFixed(2) + " ns" : "");

// The numbers that say how bad a problem is, in one line.
export function problemLine(p) {
  const d = p.diag || {};
  if (d.kind === "setup" || d.kind === "hold") {
    const parts = [ns(d.ws) + " worst" + (d.corner ? " (" + d.corner + ")" : "")];
    if (d.endpoints != null) parts.push(d.endpoints + " failing endpoint" + (d.endpoints === 1 ? "" : "s"));
    if (typeof d.tns === "number") parts.push("TNS " + ns(d.tns));
    return parts.join(" · ");
  }
  if (d.kind === "drc") {
    const s = (d.sources || []).filter((x) => x.total);
    return s.map((x) => x.label + " " + x.total).join(" · ");
  }
  if (d.kind === "check" && d.value != null) return String(d.value) + (d.limit ? " (limit " + d.limit + ")" : "");
  return "";
}

// The problems a check row in Verify shows (by the check's id).
export function problemForCheck(res, checkId) {
  const list = (res && res.problems) || [];
  return list.find((p) => p.where && p.where.check === checkId) ||
    (["magic_drc", "klayout_drc", "route_drc"].includes(checkId) ? list.find((p) => p.id === "drc") : null) || null;
}

export function countText(res) {
  const c = (res && res.counts) || {};
  const n = (c.fail || 0) + (c.warn || 0);
  return n ? n + " problem" + (n === 1 ? "" : "s") : "";
}

// The status bar's count for the run on the results pages: "3 problems in
// try-2", a link to Verify filtered to them. Hidden when there are none.
export function wireProblemCount() {
  const b = document.getElementById("st-problems");
  if (!b) return;
  let tok = 0;
  const paint = async (fresh = false) => {
    const tag = ctx.contextRun();
    const my = ++tok;
    if (!tag) { b.hidden = true; return; }
    const res = await problemsOf(tag, { fresh });
    if (my !== tok) return;
    const text = countText(res);
    b.hidden = !text;
    if (!text) return;
    const fail = (res.counts || {}).fail > 0;
    b.className = "st-item st-problems is-" + (fail ? "fail" : "warn");
    b.querySelector(".st-problems-t").textContent = text + " in " + tag;
    const top = (res.problems || [])[0];
    b.dataset.tip = (top ? top.title + ". " : "") + "Open them in Verify.";
  };
  ctx.onContext((d) => paint(d.why === "run-finished" || d.why === "runs"));
  // The run list loads when a results page first shows; the count is wanted
  // from any page, so load it once the project is known.
  setTimeout(() => { if (!ctx.contextRun()) ctx.loadRuns().catch(() => {}); else paint(); }, 1500);
}
