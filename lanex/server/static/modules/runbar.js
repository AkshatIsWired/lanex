// runbar.js — the run picker at the top of Layout, Analytics and Verify: which
// run the page shows and, where the page measures changes, the run it is
// compared with. One component and one selection (context.js), so picking a
// run here picks it on every page.
//
//   mountRunBar(host, { baseline: true })
//
// Each field is a button showing the run's verdict, name and time; it opens a
// list of runs (verdict, runtime, setup slack, when), filterable when long,
// with the "All designs" scope inside it. Keyboard: arrows, Home/End, Enter,
// Esc; typing filters.

import { fmt } from "./api.js";
import { state } from "./state.js";
import { icon } from "./icons.js";
import * as ctx from "./context.js";

const esc = (s) => fmt.escape(String(s ?? ""));
let _seq = 0;

export function mountRunBar(host, { baseline = false } = {}) {
  if (!host) return null;
  if (host._rb) return host._rb;
  const id = "rb" + (++_seq);
  host.classList.add("rb");
  host.innerHTML =
    field(id, "run", "Run", "The run this page shows. Every results page shows the same one.") +
    (baseline ? field(id, "base", "Compared with", "Every change on this page is measured against this run.") : "") +
    "<div class='rb-pop' id='" + id + "-pop' role='dialog' hidden></div>";
  const pop = host.querySelector(".rb-pop");
  const S = { which: null, items: [], active: 0, q: "" };

  const paint = () => {
    paintPick(host.querySelector("[data-rb='run']"), ctx.contextRow(), { empty: "No runs yet" });
    const b = host.querySelector("[data-rb='base']");
    if (b) {
      const tag = ctx.contextBaseline();
      const row = tag ? ctx.contextRow(tag) : null;
      b.closest(".rb-field").hidden = !ctx.contextRun();
      paintPick(b, row, { empty: "Nothing", hint: ctx.baselineChoices().length ? "" : "no other run" });
    }
  };

  // ------------------------------------------------------------ the list
  const open = (which) => {
    S.which = which; S.q = ""; S.active = -1;
    const btn = host.querySelector("[data-rb='" + which + "']");
    host.querySelectorAll(".rb-pick").forEach((x) => x.setAttribute("aria-expanded", x === btn ? "true" : "false"));
    pop.style.left = btn.offsetLeft + "px";
    pop.hidden = false;
    fill();
    const cur = S.items.findIndex((it) => it.cur);
    S.active = cur >= 0 ? cur : 0;
    paintActive();
    (pop.querySelector(".rb-q") || pop.querySelector(".rb-list")).focus();
    setTimeout(() => document.addEventListener("pointerdown", outside, true), 0);
  };
  const close = (focusBack = true) => {
    if (pop.hidden) return;
    pop.hidden = true;
    document.removeEventListener("pointerdown", outside, true);
    const btn = host.querySelector("[data-rb='" + S.which + "']");
    host.querySelectorAll(".rb-pick").forEach((x) => x.setAttribute("aria-expanded", "false"));
    if (focusBack && btn) btn.focus();
  };
  const outside = (e) => { if (!host.contains(e.target)) close(false); };

  const fill = () => {
    const runs = ctx.contextRuns();
    const all = ctx.getRunScope() === "all";
    if (S.which === "run") {
      const designs = groupByDesign(runs);
      S.items = [];
      for (const [dir, list] of designs) {
        const newest = list[0] && list[0].tag;
        for (const r of list) S.items.push({ row: r, design: dir, newest: r.tag === newest, cur: isCur(r), base: isBase(r) });
      }
      const n = runs.length;
      pop.innerHTML =
        "<div class='rb-pop-head'><div><b>" + (all ? "Runs of every design" : "Runs of " + esc(ctx.designLabel(state.designDir) || "this project")) + "</b>" +
        "<span>" + n + " run" + (n === 1 ? "" : "s") + ". The one you pick shows on every results page.</span></div>" +
        "<label class='rb-scope'><input type='checkbox' class='rb-all'" + (all ? " checked" : "") + "/> All designs</label></div>" +
        (n > 7 ? "<input class='rb-q inp' type='search' placeholder='Filter runs' aria-label='Filter runs' autocomplete='off' spellcheck='false'/>" : "") +
        "<div class='rb-list' role='listbox' tabindex='-1' aria-label='Runs'></div>" +
        "<div class='rb-pop-foot'><button class='linklike' data-rb-runs>Notes, files and every run in Runs " + icon("chevron", { size: 12 }) + "</button></div>";
    } else {
      const choices = ctx.baselineChoices();
      S.items = [{ none: true, cur: !ctx.contextBaseline() }]
        .concat(choices.map((r) => ({ row: r, design: r._design, cur: r.tag === ctx.contextBaseline() })));
      pop.innerHTML =
        "<div class='rb-pop-head'><div><b>Compare with</b><span>Changes on this page are measured against this run. " +
        "By default it is the last run before this one that passed.</span></div></div>" +
        "<div class='rb-list' role='listbox' tabindex='-1' aria-label='Compare with'></div>";
    }
    paintList();
  };

  const visible = () => {
    const q = S.q.trim().toLowerCase();
    if (!q) return S.items;
    return S.items.filter((it) => it.none || (it.row.tag + " " + ctx.designLabel(it.design) + " " + (it.row.pdk || "")).toLowerCase().includes(q));
  };

  const paintList = () => {
    const list = pop.querySelector(".rb-list");
    const items = visible();
    const all = ctx.getRunScope() === "all" && S.which === "run";
    let last = null, html = "";
    items.forEach((it, i) => {
      if (all && it.design !== last) {
        last = it.design;
        html += "<div class='rb-group' role='presentation'>" + icon("folder", { size: 12 }) + " " + esc(ctx.designLabel(it.design)) + "</div>";
      }
      html += optionHtml(id, it, i);
    });
    list.innerHTML = html || "<div class='rb-none'>No run matches “" + esc(S.q) + "”.</div>";
    S.visible = items;
    if (S.active >= items.length) S.active = items.length - 1;
    paintActive();
  };

  const paintActive = () => {
    const list = pop.querySelector(".rb-list");
    if (!list) return;
    list.querySelectorAll(".rb-opt").forEach((o) => o.classList.toggle("is-active", +o.dataset.i === S.active));
    const a = list.querySelector(".rb-opt.is-active");
    if (a) { list.setAttribute("aria-activedescendant", a.id); a.scrollIntoView({ block: "nearest" }); }
  };

  const choose = async (i) => {
    const it = (S.visible || [])[i];
    if (!it) return;
    close();
    if (S.which === "base") ctx.setBaseline(it.none ? "" : it.row.tag);
    else await ctx.setRun(it.row.tag, it.design);
  };

  // ------------------------------------------------------------ wiring
  host.addEventListener("click", (e) => {
    const pick = e.target.closest(".rb-pick");
    if (pick) { if (!pop.hidden && S.which === pick.dataset.rb) close(); else open(pick.dataset.rb); return; }
    const opt = e.target.closest(".rb-opt");
    if (opt) { choose(+opt.dataset.i); return; }
    if (e.target.closest("[data-rb-runs]")) {
      close(false);
      import("./nav.js").then((m) => m.go("runs"));
    }
  });
  host.addEventListener("change", (e) => {
    if (e.target.classList.contains("rb-all")) {
      ctx.setRunScope(e.target.checked ? "all" : "design");
      ctx.loadRuns().then(() => { if (!pop.hidden) { fill(); } });
    }
  });
  host.addEventListener("input", (e) => {
    if (e.target.classList.contains("rb-q")) { S.q = e.target.value; S.active = 0; paintList(); }
  });
  host.addEventListener("pointermove", (e) => {
    const opt = e.target.closest(".rb-opt");
    if (opt && +opt.dataset.i !== S.active) { S.active = +opt.dataset.i; paintActive(); }
  });
  host.addEventListener("keydown", (e) => {
    if (pop.hidden) {
      if (e.target.closest(".rb-pick") && (e.key === "ArrowDown" || e.key === "ArrowUp")) { e.preventDefault(); open(e.target.closest(".rb-pick").dataset.rb); }
      return;
    }
    const n = (S.visible || []).length;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); S.active = Math.min(n - 1, S.active + 1); paintActive(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); S.active = Math.max(0, S.active - 1); paintActive(); }
    else if (e.key === "Home" && !e.target.classList.contains("rb-q")) { e.preventDefault(); S.active = 0; paintActive(); }
    else if (e.key === "End" && !e.target.classList.contains("rb-q")) { e.preventDefault(); S.active = n - 1; paintActive(); }
    else if (e.key === "Enter") { e.preventDefault(); choose(S.active); }
    else if (e.key === "Tab") close(false);
  });

  ctx.onContext(() => { paint(); if (!pop.hidden) fill(); });
  const api = { paint, close };
  host._rb = api;
  paint();
  return api;
}

// ---------------------------------------------------------------- pieces
function field(id, which, label, tip) {
  return "<div class='rb-field'><span class='rb-label' id='" + id + "-" + which + "-l' data-tip='" + esc(tip) + "'>" + esc(label) + "</span>" +
    "<button class='rb-pick' data-rb='" + which + "' aria-haspopup='listbox' aria-expanded='false' aria-labelledby='" + id + "-" + which + "-l " + id + "-" + which + "-v'>" +
    "<span class='rb-mark' aria-hidden='true'></span>" +
    "<span class='rb-val' id='" + id + "-" + which + "-v'><b class='rb-name'></b><span class='rb-meta'></span></span>" +
    "<span class='rb-tags'></span>" +
    "<span class='rb-chev' aria-hidden='true'>" + icon("chevronDown", { size: 14 }) + "</span></button></div>";
}

function paintPick(btn, row, { empty, hint = "" }) {
  if (!btn) return;
  const mark = btn.querySelector(".rb-mark");
  mark.className = "rb-mark" + (row ? " is-" + verdict(row).cls : " is-none");
  btn.querySelector(".rb-name").textContent = row ? row.tag : empty;
  btn.querySelector(".rb-meta").textContent = row ? verdict(row).word + " · " + when(row) : hint;
  const all = ctx.getRunScope() === "all";
  btn.querySelector(".rb-tags").innerHTML =
    (row && all && ctx.normDir(row._design) !== ctx.normDir(state.designDir) ? "<span class='rb-tag'>" + esc(ctx.designLabel(row._design)) + "</span>" : "") +
    (row && isNewest(row) && btn.dataset.rb === "run" ? "<span class='rb-tag is-new'>newest</span>" : "");
  btn.disabled = btn.dataset.rb === "run" ? !row : !ctx.baselineChoices().length && !row;
}

function optionHtml(id, it, i) {
  if (it.none) {
    return "<div class='rb-opt" + (it.cur ? " is-cur" : "") + "' role='option' id='" + id + "-o" + i + "' data-i='" + i + "' aria-selected='" + (it.cur ? "true" : "false") + "'>" +
      "<span class='rb-mark is-none'></span><span class='rb-o-name'>Nothing</span><span class='rb-o-facts'>no comparison, no changes shown</span><span class='rb-o-when'></span>" +
      "<span class='rb-o-cur'>" + (it.cur ? icon("check", { size: 13 }) : "") + "</span></div>";
  }
  const r = it.row, v = verdict(r);
  const facts = [v.word];
  if (r.wall_time_s != null && v.cls !== "run") facts.push(dur(r.wall_time_s));
  const ws = r.key_metrics && r.key_metrics.timing__setup__ws;
  if (typeof ws === "number" && Number.isFinite(ws) && Math.abs(ws) < 1e20) facts.push("setup " + (ws >= 0 ? "+" : "") + ws.toFixed(2) + " ns");
  const tags = (it.newest ? "<span class='rb-tag is-new'>newest</span>" : "") +
    (it.base ? "<span class='rb-tag'>compared with</span>" : "") +
    (r.pinned ? "<span class='rb-tag'>pinned</span>" : "");
  return "<div class='rb-opt" + (it.cur ? " is-cur" : "") + "' role='option' id='" + id + "-o" + i + "' data-i='" + i + "' aria-selected='" + (it.cur ? "true" : "false") + "'>" +
    "<span class='rb-mark is-" + v.cls + "'></span>" +
    "<span class='rb-o-name'>" + esc(r.tag) + tags + "</span>" +
    "<span class='rb-o-facts'>" + esc(facts.join(" · ")) + "</span>" +
    "<span class='rb-o-when'>" + esc(when(r)) + "</span>" +
    "<span class='rb-o-cur'>" + (it.cur ? icon("check", { size: 13 }) : "") + "</span></div>";
}

function groupByDesign(runs) {
  const m = new Map();
  const cur = ctx.normDir(state.designDir);
  // The active design first, then the others in order of their newest run.
  const sorted = runs.slice().sort((a, b) => (ctx.normDir(b._design) === cur) - (ctx.normDir(a._design) === cur));
  for (const r of sorted) {
    const k = r._design || "";
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(r);
  }
  return m;
}

const isCur = (r) => r.tag === ctx.contextRun() && ctx.normDir(r._design) === ctx.normDir(ctx.contextDesign());
const isBase = (r) => r.tag === ctx.contextBaseline() && ctx.normDir(r._design) === ctx.normDir(ctx.contextDesign());
function isNewest(r) {
  const same = ctx.contextRuns().filter((x) => ctx.normDir(x._design) === ctx.normDir(r._design));
  return !!same.length && same[0].tag === r.tag;
}

// The Runs tab's words: a run passed or failed; the newest run of the active
// design is "running" while the flow is live.
function verdict(r) {
  if (state.status && state.status.running && !r.success && isNewest(r) && ctx.normDir(r._design) === ctx.normDir(state.designDir)) {
    return { cls: "run", word: "running" };
  }
  return r.success ? { cls: "pass", word: "passed" } : { cls: "fail", word: "failed" };
}

function when(r) {
  const d = r.started_at ? new Date(r.started_at) : null;
  if (!d || Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate());
  if (day === 0) return "today " + time;
  if (day === 86400000) return "yesterday " + time;
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}) }) + ", " + time;
}

function dur(s) {
  s = Math.round(s);
  if (s < 60) return s + " s";
  const m = Math.floor(s / 60);
  if (m < 60) return m + " min " + (s % 60) + " s";
  return Math.floor(m / 60) + " h " + (m % 60) + " min";
}
