// runs.js — the Runs page: one dense, sortable table of every run, where runs
// are managed, compared and swept. A row is one run; a sweep is one collapsible
// parent row with its points under it (sweeps.js draws the sheet and summary).
//
//   click a row        it becomes the run every results page shows
//   open a row (▸)     its report card and one row of actions
//   ★                  the design's baseline: every number is coloured better
//                      or worse than it (direction from the metric registry)
//   tick 2–6 rows      Compare (Analytics › Compare, pre-filled) or Delete

import { api, fmt } from "./api.js";
import { state, safeStorage } from "./state.js";
import { confirmDialog, alertDialog, checklistDialog, choiceDialog, promptDialog } from "./dialog.js";
import { toast } from "./toast.js";
import { gatherRunsScoped, normDir, getRunScope, setRunScope, setRun, setBaseline, contextRun, contextDesign, onContext, designLabel } from "./context.js";
import { go } from "./nav.js";
import * as FS from "./flowstages.js";
import { icon } from "./icons.js";
import { reportCardHtml, fmtDur } from "./reportcard.js";

// The last step of a stage in the Classic flow (matches setup.js's --to).
function lastStepOfStage(stageId) {
  const flow = (state.flows || []).find((f) => f.name === "Classic");
  const ids = (flow && flow.steps) || [];
  const st = FS.stagesOf(ids.map((id) => ({ id })));
  let last = "";
  st.forEach((s, i) => { if (s === stageId) last = ids[i]; });
  return last;
}

// Lightweight "make this run's design active" — needed before any run-scoped
// call (delete / files) since they resolve against the server's active design
// dir. It does not switch tabs.
async function focusDesign(designDir) {
  if (designDir && normDir(designDir) !== normDir(state.designDir)) {
    try { await api.setDesignDir(designDir); state.designDir = designDir; } catch (_e) {}
  }
}

const esc = (s) => fmt.escape(s == null ? "" : String(s));
const num = (v) => (typeof v === "number" && Number.isFinite(v) && Math.abs(v) < 1e20 ? v : null);
const km = (r, k) => num((r.key_metrics || {})[k]);
// "|" joins them: a NUL would not survive an HTML attribute (data-key).
const keyOf = (r) => normDir(r._design) + "|" + r.tag;

// ------------------------------------------------------------------ columns
// dir: +1 higher is better, -1 lower is better, 0 no direction (no colour).
// Directions follow LibreLane's metric registry (compare.js higher_is_better).
function checksOf(r) {
  const m = r.key_metrics || {};
  const drc = ["magic__drc_error__count", "klayout__drc_error__count", "route__drc_errors"]
    .map((k) => num(m[k])).filter((v) => v != null);
  const lvs = num(m.design__lvs_error__count), ant = num(m.antenna__violating__nets);
  if (!drc.length && lvs == null && ant == null) return null;
  const d = drc.length ? Math.max(...drc) : null;
  return { drc: d, lvs, ant, total: (d || 0) + (lvs || 0) + (ant || 0) };
}
const COLS = [
  { id: "name", label: "Run", fixed: true, sort: (r) => r.tag.toLowerCase() },
  { id: "verdict", label: "Result", fixed: true, sort: (r) => VERDICT_ORDER[verdictOf(r).state] ?? 9 },
  { id: "when", label: "When", sort: (r) => r.started_at || "", def: true },
  { id: "origin", label: "Origin", sort: (r) => originText(r), def: 2000 },
  { id: "design", label: "Design", sort: (r) => designLabel(r._design), allOnly: true, def: true },
  { id: "pdk", label: "PDK", sort: (r) => r.pdk || "", def: false },
  { id: "wns", label: "Setup WNS", unit: "ns", dir: 1, get: (r) => km(r, "timing__setup__ws"), f: (v) => signed(v), def: true,
    tip: "Worst setup slack in any corner (ns). Positive: the design meets its clock." },
  { id: "tns", label: "Setup TNS", unit: "ns", dir: 1, get: (r) => km(r, "timing__setup__tns"), f: (v) => signed(v), def: 1500,
    tip: "Total negative setup slack (ns). 0 when every path meets timing." },
  { id: "hold", label: "Hold WNS", unit: "ns", dir: 1, get: (r) => km(r, "timing__hold__ws"), f: (v) => signed(v), def: 1500,
    tip: "Worst hold slack in any corner (ns)." },
  { id: "die", label: "Die area", unit: "µm²", dir: -1, get: (r) => km(r, "design__die__area"), f: (v) => grp(v), def: 1500,
    tip: "design__die__area: the whole die, in µm²." },
  { id: "cells", label: "Std-cell area", unit: "µm²", dir: -1, get: (r) => km(r, "design__instance__area__stdcell"), f: (v) => grp(v), def: true,
    tip: "design__instance__area__stdcell: the standard cells' area in µm², without fill, tap or decap cells." },
  { id: "util", label: "Util", unit: "%", dir: 0, get: (r) => { const u = km(r, "design__instance__utilization"); return u == null ? null : u * 100; },
    f: (v) => (Math.round(v * 10) / 10).toFixed(1), def: true, tip: "How full the core is with cells at the end (design__instance__utilization)." },
  { id: "power", label: "Power", unit: "mW", dir: -1, get: (r) => { const p = km(r, "power__total"); return p == null ? null : p * 1e3; },
    f: (v) => (v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(3)), def: true, tip: "Total power OpenROAD estimated (power__total), in mW." },
  { id: "checks", label: "DRC · LVS · Ant", dir: -1, get: (r) => { const c = checksOf(r); return c ? c.total : null; }, def: true,
    tip: "Design-rule errors (worst of Magic, KLayout and the router), LVS errors and antenna violations. Not checked: blank." },
  { id: "runtime", label: "Runtime", dir: -1, get: (r) => num(r.wall_time_s), f: (v) => fmtDur(v), def: 1300, tip: "The sum of every step's time." },
  { id: "changed", label: "Changed vs baseline", sort: (r) => (CHANGES.get(keyOf(r)) || []).length, def: true },
  { id: "note", label: "Note", sort: (r) => r.note || "", def: 2100 },
];
const VERDICT_ORDER = { running: 0, passed: 1, warning: 2, incomplete: 3, stopped: 4, failed: 5 };
const signed = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(2);
const grp = (v) => Math.round(v).toLocaleString("en-US");

const COLS_KEY = "ll.runsCols", SORT_KEY = "ll.runsSort", BASE_KEY = "ll.runsBaseline", OPEN_KEY = "ll.runsOpenSweeps";
function visibleCols(scope) {
  const saved = safeStorage.getJSON(COLS_KEY, null);
  return COLS.filter((c) => (c.allOnly ? scope === "all" : true) &&
    (c.fixed || (saved && saved[c.id] != null ? saved[c.id] : defOn(c))));
}
// A column whose default is a width shows by default only when the table has
// that much room, so the default set fits the screen (1366: the essentials).
function defOn(c) {
  if (typeof c.def !== "number") return !!c.def;
  const w = document.getElementById("sec-runs")?.clientWidth || window.innerWidth;
  return w >= c.def - 120;
}

// ------------------------------------------------------------------ verdict
// The run's verdict (agent TRUST adds run.verdict from Verify's own reading);
// until then: passed / failed (at a stage, once its reason is read) / stopped /
// running, from the summary and the run's explanation.
const RX = new Map();          // keyOf(run) -> runExplain result (failed runs only)
function verdictOf(r) {
  if (r.verdict && r.verdict.state) return r.verdict;
  if (state.status && state.status.running && state.liveTag && r.tag === state.liveTag && normDir(r._design) === normDir(state.designDir)) {
    return { state: "running", label: "running" };
  }
  if (r.success) return { state: "passed", label: "passed" };
  const rx = RX.get(keyOf(r));
  if (rx) {
    if (rx.kind === "stopped") return { state: "stopped", label: "stopped" };
    if (rx.kind === "incomplete") return { state: "incomplete", label: "incomplete" };
    if (rx.kind === "checks-failed") return { state: "failed", label: "checks failed", stage: "signoff" };
    if (rx.stage) return { state: "failed", label: "failed at " + FS.stageLabel(rx.stage), stage: rx.stage };
  }
  return { state: "failed", label: "failed" };
}
const VERDICT_TONE = { passed: "pass", warning: "warn", failed: "fail", stopped: "warn", incomplete: "warn", running: "live" };

// ------------------------------------------------------------------ origin
let SWEEPS = [];               // this design's sweep manifests (newest first)
// run.origin (history.run_origin), else the summary's branched_from (TRUST).
function originOf(r) {
  if (r.origin && r.origin.kind) return r.origin;
  // The run summary carries branched_from as the parent's tag (a string).
  const b = r.branched_from;
  if (typeof b === "string" && b) return { kind: "fix", parent: b, changes: [] };
  if (b && b.tag) return { kind: "fix", parent: b.tag, stage: b.stage, changes: b.changes || [] };
  return {};
}
function sweepOf(r) {
  const o = originOf(r);
  if (o.kind === "sweep") return SWEEPS.find((s) => s.id === o.sweep_id) || { id: o.sweep_id, axes: [], tags: [], _design: r._design };
  if (normDir(r._design) !== normDir(state.designDir)) return null;
  return SWEEPS.find((s) => (s.tags || []).includes(r.tag)) || null;
}
function pointValues(r, sw) {
  const o = originOf(r);
  if (o.kind === "sweep" && o.values && Object.keys(o.values).length) return o.values;
  if (sw) {
    const i = (sw.tags || []).indexOf(r.tag);
    if (sw.points && sw.points[i]) return sw.points[i];
    if (i >= 0 && sw.axes && sw.axes.length) {
      // Old manifests carry axes only: a one-axis sweep maps index -> value.
      if (sw.axes.length === 1) return { [sw.axes[0].var]: sw.axes[0].values[i] };
    }
  }
  return null;
}
const valuesText = (v) => Object.entries(v || {}).map(([k, x]) => k + " " + x).join(", ");
function originText(r) {
  const o = originOf(r);
  if (o.kind === "fix") return "fix of " + o.parent;
  if (sweepOf(r)) return "sweep";
  if (r.imported) return "imported";
  return "manual";
}
function lineageHtml(r) {
  const o = originOf(r);
  if (o.kind !== "fix") return "";
  const ch = (o.changes || []).map((c) => c.var + " " + c.from + "→" + c.to).join(", ");
  return "<span class='rn-lineage' title='Resumed from " + esc(o.parent) + (o.stage ? " at " + esc(FS.stageLabel(o.stage)) : "") +
    " with a changed setting'>fix of " + esc(o.parent) + (ch ? " · " + esc(ch) : "") + "</span>";
}

// ------------------------------------------------------------------ state
let _wired = false;
const F = { q: "", status: "", origin: "", pdk: "" };
const _picked = new Set();     // keyOf(run)
let _open = null;              // keyOf(run) whose report row is open
let _openSweeps = new Set(safeStorage.getJSON(OPEN_KEY, []) || []);
let _sort = safeStorage.getJSON(SORT_KEY, null) || { col: "when", dir: -1 };
let _shown = { key: "", runs: [] };
let _renderSeq = 0;
const CHANGES = new Map();     // keyOf(run) -> [{var, from, to}] vs the baseline
let _changesKey = "";

function baselineTag(design) { return (safeStorage.getJSON(BASE_KEY, {}) || {})[normDir(design)] || ""; }
function setBaselineTag(design, tag) {
  const m = safeStorage.getJSON(BASE_KEY, {}) || {};
  if (tag) m[normDir(design)] = tag; else delete m[normDir(design)];
  safeStorage.setJSON(BASE_KEY, m);
}

function wire() {
  if (_wired) return;
  _wired = true;
  document.querySelectorAll("#sec-runs .runs-scope[data-scope]").forEach((b) =>
    b.addEventListener("click", () => { setRunScope(b.dataset.scope); renderRuns(); }));
  onContext(() => paintViewing());
  const fi = document.getElementById("runs-filter");
  if (fi) fi.addEventListener("input", () => { F.q = fi.value.toLowerCase(); renderRuns({ cached: true }); });
  document.getElementById("runs-import")?.addEventListener("click", () => importRunFlow());
  document.getElementById("runs-new-sweep")?.addEventListener("click", () => import("./sweeps.js").then((m) => m.openSweepSheet()));
  const cb = document.getElementById("rn-cols-btn"), cp = document.getElementById("rn-cols");
  cb?.addEventListener("click", (e) => {
    e.stopPropagation();
    cp.hidden = !cp.hidden; cb.setAttribute("aria-expanded", cp.hidden ? "false" : "true");
    if (!cp.hidden) paintColPicker();
  });
  document.addEventListener("click", (e) => { if (cp && !cp.hidden && !e.target.closest(".rn-cols-wrap")) { cp.hidden = true; cb.setAttribute("aria-expanded", "false"); } });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && cp && !cp.hidden) { cp.hidden = true; cb.setAttribute("aria-expanded", "false"); } });
  // A sweep running anywhere shows its progress here.
  // Default columns follow the room the table has.
  let rz = 0;
  window.addEventListener("resize", () => { clearTimeout(rz); rz = setTimeout(() => { if (document.getElementById("sec-runs")?.classList.contains("section-active")) renderRuns({ cached: true }); }, 250); });
  document.addEventListener("g:sweep", () => {
    if (document.getElementById("sec-runs")?.classList.contains("section-active")) renderRuns();
  });
}

function paintColPicker() {
  const cp = document.getElementById("rn-cols");
  const saved = safeStorage.getJSON(COLS_KEY, {}) || {};
  cp.innerHTML = "<div class='rn-cols-h'>Columns</div>" + COLS.filter((c) => !c.fixed && !c.allOnly).map((c) => {
    const on = saved[c.id] != null ? saved[c.id] : defOn(c);
    return "<label class='rn-col-opt'><input type='checkbox' data-col='" + c.id + "'" + (on ? " checked" : "") + "/> " + esc(c.label) + "</label>";
  }).join("") + "<button class='btn btn-ghost btn-xs' data-cols-reset>Reset</button>";
  cp.querySelectorAll("input[data-col]").forEach((i) => i.addEventListener("change", () => {
    const m = safeStorage.getJSON(COLS_KEY, {}) || {};
    m[i.dataset.col] = i.checked;
    safeStorage.setJSON(COLS_KEY, m);
    renderRuns({ cached: true });
  }));
  cp.querySelector("[data-cols-reset]").addEventListener("click", () => { safeStorage.remove(COLS_KEY); paintColPicker(); renderRuns({ cached: true }); });
}

// Segmented filter chips (no native <select>), counts from the unfiltered list.
function paintChips(runs) {
  const chip = (host, key, opts) => {
    const el = document.getElementById(host);
    if (!el) return;
    el.hidden = opts.length <= 2;
    el.innerHTML = opts.map(([v, label, n]) =>
      "<button class='rn-segb" + (F[key] === v ? " is-on" : "") + "' data-v='" + esc(v) + "' aria-pressed='" + (F[key] === v) + "'>" +
      esc(label) + (n != null ? " <span class='rn-n'>" + n + "</span>" : "") + "</button>").join("");
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { F[key] = b.dataset.v; renderRuns({ cached: true }); }));
  };
  const cnt = (fn) => runs.filter(fn).length;
  chip("rn-status", "status", [["", "All", runs.length], ["passed", "Passed", cnt((r) => verdictOf(r).state === "passed")],
    ["warning", "Warnings", cnt((r) => verdictOf(r).state === "warning")], ["failed", "Failed", cnt((r) => verdictOf(r).state === "failed")], ["stopped", "Stopped", cnt((r) => /stopped|incomplete/.test(verdictOf(r).state))],
    ["pinned", "Pinned", cnt((r) => r.pinned)]]);
  chip("rn-origin", "origin", [["", "Any origin", null], ["manual", "Manual", cnt((r) => originText(r) === "manual")],
    ["sweep", "Sweeps", cnt((r) => originText(r) === "sweep")], ["fix", "Fixes", cnt((r) => originOf(r).kind === "fix")]]);
  const pdks = [...new Set(runs.map((r) => r.pdk).filter(Boolean))];
  chip("rn-pdk", "pdk", pdks.length > 1 ? [["", "Any PDK", null], ...pdks.map((p) => [p, p, cnt((r) => r.pdk === p)])] : []);
  document.querySelectorAll("#sec-runs .runs-scope[data-scope]").forEach((b) =>
    b.classList.toggle("is-on", b.dataset.scope === getRunScope()));
}

function matches(r) {
  const v = verdictOf(r).state;
  if (F.status === "pinned" && !r.pinned) return false;
  if (F.status === "passed" && v !== "passed") return false;
  if (F.status === "failed" && v !== "failed") return false;
  if (F.status === "warning" && v !== "warning") return false;
  if (F.status === "stopped" && !/stopped|incomplete/.test(v)) return false;
  if (F.origin === "fix" && originOf(r).kind !== "fix") return false;
  if (F.origin && F.origin !== "fix" && originText(r) !== F.origin) return false;
  if (F.pdk && r.pdk !== F.pdk) return false;
  if (!F.q) return true;
  const sw = sweepOf(r);
  const hay = [r.tag, r.pdk, r.scl, r.note, originText(r), designLabel(r._design), valuesText(pointValues(r, sw)),
    (CHANGES.get(keyOf(r)) || []).map((c) => c.var).join(" ")].join(" ").toLowerCase();
  return hay.includes(F.q);
}

function sortRuns(list) {
  const col = COLS.find((c) => c.id === _sort.col) || COLS[2];
  const val = col.sort || col.get || (() => 0);
  return list.slice().sort((a, b) => {
    const x = val(a), y = val(b);
    if (x == null && y == null) return 0;
    if (x == null) return 1;          // blanks last, either way
    if (y == null) return -1;
    return (x < y ? -1 : x > y ? 1 : 0) * _sort.dir;
  });
}

// ------------------------------------------------------------------ render
export async function renderRuns({ cached = false } = {}) {
  const table = document.getElementById("runs-table");
  if (!table) return;
  wire();
  const scope = getRunScope();
  const key = scope + "\0" + normDir(state.designDir);
  const my = ++_renderSeq;
  let runs;
  if (cached && _shown.key === key) runs = _shown.runs;
  else {
    try {
      const [rs, sw] = await Promise.all([gatherRunsScoped(scope, { strict: true }),
        state.designDir ? api.dseSweeps().catch(() => null) : Promise.resolve(null)]);
      runs = rs;
      if (sw) SWEEPS = (sw.data || sw).sweeps || [];
    } catch (_e) {
      if (my !== _renderSeq) return;
      if (_shown.key === key && _shown.runs.length) { note("Couldn't refresh the list. Trying again…"); setTimeout(() => { if (my === _renderSeq) renderRuns(); }, 4000); return; }
      runs = null;
    }
  }
  if (my !== _renderSeq) return;
  const empty = document.getElementById("rn-empty"), wrap = document.getElementById("rn-wrap");
  const title = document.getElementById("rn-title");
  if (title) title.textContent = scope === "all" ? "Every run of every design you've opened" : (state.designDir ? "Every run of " + designLabel(state.designDir) : "Runs");
  if (runs === null) {
    wrap.hidden = true; empty.hidden = false;
    empty.innerHTML = "<h3>Couldn't load your runs</h3><p>LanEx didn't answer in time. Trying again…</p>";
    setTimeout(() => { if (my === _renderSeq) renderRuns(); }, 4000);
    return;
  }
  note("");
  _shown = { key, runs };
  if (scope !== "all") state.runs = runs;
  paintChips(runs);
  paintLive();
  if (!runs.length) {
    wrap.hidden = true; empty.hidden = false;
    empty.innerHTML = state.designDir || scope === "all"
      ? "<h3>No runs yet</h3><p>Run the flow once and every run appears here, one row each, with its timing, area, power and checks.</p>" +
        "<button class='btn btn-primary' data-go='setup'>Go to Setup</button>"
      : "<h3>Open a project first</h3><p>Runs lists the runs of the project you have open.</p><button class='btn btn-primary' data-go='setup'>Go to Setup</button>";
    syncSelection();
    return;
  }
  const shown = runs.filter(matches);
  if (!shown.length) {
    wrap.hidden = true; empty.hidden = false;
    empty.innerHTML = "<h3>No runs match</h3><p>Clear the search or the filters to see all " + runs.length + " runs.</p>";
    syncSelection();
    return;
  }
  wrap.hidden = false; empty.hidden = true;
  const cols = visibleCols(scope);
  table.innerHTML = headHtml(cols) + "<tbody>" + bodyHtml(sortRuns(shown), cols) + "</tbody>";
  wireTable(table, runs);
  syncSelection();
  paintViewing();
  explainFailed(runs);
  loadChanges(runs);
}

function note(text) {
  const el = document.getElementById("runs-note");
  if (!el) return;
  el.hidden = !text;
  el.textContent = text || "";
}

function headHtml(cols) {
  const th = (c) => {
    const on = _sort.col === c.id;
    return "<th scope='col' class='rn-th rn-c-" + c.id + (c.dir != null || c.get ? " is-num" : "") + "'" +
      (on ? " aria-sort='" + (_sort.dir > 0 ? "ascending" : "descending") + "'" : "") +
      "><button class='rn-sort" + (on ? " is-on" : "") + "' data-sort='" + c.id + "' title='" + esc(c.tip || "Sort by " + c.label) + "'>" +
      esc(c.label) + (c.unit ? " <small>" + esc(c.unit) + "</small>" : "") +
      "<span class='rn-arrow' aria-hidden='true'>" + (on ? (_sort.dir > 0 ? "▲" : "▼") : "") + "</span></button></th>";
  };
  return "<thead><tr><th class='rn-th rn-c-pick'><span class='sr-only'>Select</span></th>" +
    "<th class='rn-th rn-c-base' title='Baseline: every number is coloured against it'>★</th>" + cols.map(th).join("") + "</tr></thead>";
}

// Rows: sweeps fold under one parent row (in the position of their newest point).
function bodyHtml(list, cols) {
  const groups = new Map();
  const order = [];
  for (const r of list) {
    const sw = sweepOf(r);
    if (sw) {
      const gk = normDir(r._design) + "|sweep:" + sw.id;
      if (!groups.has(gk)) { groups.set(gk, { sw, runs: [] }); order.push({ group: gk }); }
      groups.get(gk).runs.push(r);
    } else order.push({ run: r });
  }
  return order.map((o) => {
    if (o.run) return rowHtml(o.run, cols, {});
    const g = groups.get(o.group);
    const open = _openSweeps.has(o.group);
    return sweepRowHtml(g, cols, o.group, open) + (open ? g.runs.map((r) => rowHtml(r, cols, { child: g.sw })).join("") : "");
  }).join("");
}

function baselineRowFor(r) {
  const t = baselineTag(r._design);
  if (!t || t === r.tag) return null;
  return _shown.runs.find((x) => x.tag === t && normDir(x._design) === normDir(r._design)) || null;
}

function cellHtml(c, r, base) {
  if (c.id === "verdict") {
    const v = verdictOf(r);
    return "<td class='rn-c-verdict'><span class='rn-v is-" + (VERDICT_TONE[v.state] || "warn") + "'><i aria-hidden='true'></i>" + esc(v.label || v.state) + "</span></td>";
  }
  if (c.id === "name") return "";        // drawn by rowHtml
  if (c.id === "when") return "<td class='rn-c-when' title='" + esc(r.started_at || "") + "'>" + esc(when(r.started_at)) + "</td>";
  if (c.id === "origin") return "<td class='rn-c-origin'>" + esc(originText(r) === "fix" ? "fix" : originText(r)) + "</td>";
  if (c.id === "design") return "<td class='rn-c-design'>" + esc(designLabel(r._design)) + "</td>";
  if (c.id === "pdk") return "<td class='rn-c-pdk'>" + esc(r.pdk || "") + "</td>";
  if (c.id === "note") return "<td class='rn-c-note' title='" + esc(r.note || "") + "'>" + esc((r.note || "").split("\n")[0]) + "</td>";
  if (c.id === "changed") {
    const ch = CHANGES.get(keyOf(r));
    if (!baselineTag(r._design)) return "<td class='rn-c-changed muted'></td>";
    if (baselineTag(r._design) === r.tag) return "<td class='rn-c-changed'><span class='rn-basetag'>baseline</span></td>";
    if (!ch) return "<td class='rn-c-changed muted'>…</td>";
    if (!ch.length) return "<td class='rn-c-changed muted'>same settings</td>";
    const txt = ch.slice(0, 2).map((x) => x.var + " " + short(x.from) + "→" + short(x.to)).join(", ") + (ch.length > 2 ? " +" + (ch.length - 2) : "");
    return "<td class='rn-c-changed' title='" + esc(ch.map((x) => x.var + ": " + x.from + " → " + x.to).join("\n")) + "'>" + esc(txt) + "</td>";
  }
  if (c.id === "checks") {
    const k = checksOf(r);
    if (!k) return "<td class='rn-c-checks is-num muted'></td>";
    if (!k.total) return "<td class='rn-c-checks is-num'><span class='rn-clean'>clean</span></td>";
    const parts = [k.drc ? "DRC " + k.drc : "", k.lvs ? "LVS " + k.lvs : "", k.ant ? "ant " + k.ant : ""].filter(Boolean);
    return "<td class='rn-c-checks is-num'><span class='rn-bad'>" + esc(parts.join(" · ")) + "</span></td>";
  }
  const v = c.get(r);
  if (v == null) return "<td class='rn-c-" + c.id + " is-num muted'></td>";
  let cls = "", delta = "";
  // Only finished runs are measured against the baseline (a stopped run is "faster").
  if (c.dir && base && /passed|warning/.test(verdictOf(r).state)) {
    const b = c.get(base);
    if (b != null) {
      const d = v - b;
      const same = Math.abs(d) <= Math.max(Math.abs(b) * 5e-4, c.id === "runtime" ? 1 : 0.005);
      if (!same) {
        cls = (d > 0) === (c.dir > 0) ? " is-better" : " is-worse";
        delta = " (baseline " + (c.f ? c.f(b) : b) + ")";
      }
    }
  }
  const neg = (c.id === "wns" || c.id === "tns" || c.id === "hold") && v < 0 ? " is-neg" : "";
  return "<td class='rn-c-" + c.id + " is-num" + cls + neg + "' title='" + esc(c.label + ": " + v + (c.unit ? " " + c.unit : "") + delta) + "'>" + esc(c.f ? c.f(v) : v) + "</td>";
}
const short = (s) => { s = String(s ?? "—"); return s.length > 14 ? s.slice(0, 13) + "…" : s; };

function rowHtml(r, cols, { child = null } = {}) {
  const k = keyOf(r);
  const base = baselineRowFor(r);
  const isBase = baselineTag(r._design) === r.tag;
  const vals = child ? pointValues(r, child) : null;
  const name = "<td class='rn-c-name'><div class='rn-name'>" +
    "<button class='rn-exp' data-act='expand' aria-expanded='" + (_open === k) + "' title='Report and actions'>" + icon("chevron", { size: 12 }) + "</button>" +
    "<span class='rn-tag'>" + esc(r.tag) + "</span>" +
    (vals ? "<span class='rn-val'>" + esc(valuesText(vals)) + "</span>" : "") +
    (r.pinned ? "<span class='rn-pin' title='Pinned'>" + icon("star", { size: 11 }) + "</span>" : "") +
    (r.imported ? "<span class='rn-chip'>imported</span>" : "") +
    (r.note && !cols.some((c) => c.id === "note") ? "<span class='rn-hasnote' title='" + esc(r.note) + "'>" + icon("file", { size: 11 }) + "</span>" : "") +
    "<span class='rn-viewing' title='Flow, Layout, Analytics and Verify show this run'>shown</span></div>" + lineageHtml(r) + "</td>";
  const cells = cols.map((c) => (c.id === "name" ? name : cellHtml(c, r, base))).join("");
  const n = cols.length + 2;
  return "<tr class='rn-row" + (child ? " is-child" : "") + (_picked.has(k) ? " is-picked" : "") + "' data-key='" + esc(k) + "' data-tag='" + esc(r.tag) + "' data-design='" + esc(r._design || "") + "'>" +
    "<td class='rn-c-pick'><input type='checkbox' class='rn-pick' aria-label='Select " + esc(r.tag) + "'" + (_picked.has(k) ? " checked" : "") + "/></td>" +
    "<td class='rn-c-base'><button class='rn-star" + (isBase ? " is-on" : "") + "' data-act='base' aria-pressed='" + isBase + "' title='" +
      (isBase ? "The baseline of " + esc(designLabel(r._design)) + ". Click to clear." : "Make this the baseline") + "'>" + icon("star", { size: 13 }) + "</button></td>" +
    cells + "</tr>" +
    (_open === k ? "<tr class='rn-detail' data-detail='" + esc(k) + "'><td colspan='" + n + "'><div class='rn-card' id='rn-card'>" +
      "<p class='muted'>Reading the run…</p></div></td></tr>" : "");
}

function sweepRowHtml(g, cols, gk, open) {
  const sw = g.sw, rs = g.runs;
  const axes = (sw.axes || []).map((a) => {
    const vs = (a.values || []).map(String);
    const nums = vs.map(Number);
    const range = nums.every(Number.isFinite) && vs.length > 2 ? Math.min(...nums) + "–" + Math.max(...nums) : vs.join(", ");
    return a.var + " " + range;
  }).join(" × ") || "settings";
  const failed = rs.filter((r) => verdictOf(r).state === "failed");
  const reasons = [...new Set(failed.map((r) => failCode(r)).filter(Boolean))];
  const passed = rs.filter((r) => verdictOf(r).state === "passed");
  const bestW = passed.map((r) => km(r, "timing__setup__ws")).filter((v) => v != null);
  const running = rs.some((r) => verdictOf(r).state === "running");
  const n = cols.length + 2;
  return "<tr class='rn-sweep" + (open ? " is-open" : "") + "' data-group='" + esc(gk) + "'><td class='rn-c-pick'></td><td class='rn-c-base'></td>" +
    "<td colspan='" + (n - 2) + "'><div class='rn-sw'>" +
    "<button class='rn-exp' data-act='group' aria-expanded='" + open + "'>" + icon("chevron", { size: 12 }) + "</button>" +
    "<b>Sweep " + esc(axes) + "</b><span class='rn-sw-m'>" + rs.length + " run" + (rs.length === 1 ? "" : "s") +
    (running ? " · running" : "") +
    (failed.length ? " · <span class='rn-bad'>" + failed.length + " failed" + (reasons.length ? " (" + esc(reasons.join(", ")) + ")" : "") + "</span>" : "") +
    (bestW.length ? " · best WNS " + esc(signed(Math.max(...bestW))) + " ns" : "") + "</span>" +
    "<span class='rn-sw-when'>" + esc(when(sw.created_at)) + "</span>" +
    "<button class='btn btn-ghost btn-xs' data-act='sweep-summary'>Summary</button></div>" +
    (open ? "<div class='rn-sw-sum' data-sum='" + esc(gk) + "'></div>" : "") + "</td></tr>";
}

// "DPL-0036": the error code in the failed run's reason, else its stage.
function failCode(r) {
  const sw = sweepOf(r);
  const res = sw && sw.results && sw.results[r.tag];
  const rx = RX.get(keyOf(r));
  const text = (res && res.reason) || (rx && ((rx.card && rx.card.title) || (rx.errors || [])[0])) || "";
  const m = /\b([A-Z]{2,4}-\d{4})\b/.exec(text) || /\b([A-Z]{2,4}-\d{4})\b/.exec(((rx && rx.errors) || []).join(" "));
  if (m) return m[1];
  const st = (res && res.stage) || (rx && rx.stage);
  return st ? FS.stageLabel(st) : "";
}

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const now = new Date();
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.floor((new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5);
  if (days === 0) return "today " + hm;
  if (days === 1) return "yesterday " + hm;
  if (days < 7) return days + " days ago";
  return d.toLocaleDateString([], { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}

// ------------------------------------------------------------------ table events
function rowOf(el, runs) {
  const tr = el.closest("tr[data-key]");
  return tr ? runs.find((r) => keyOf(r) === tr.dataset.key) : null;
}

function wireTable(table, runs) {
  table.querySelectorAll("[data-sort]").forEach((b) => b.addEventListener("click", () => {
    const id = b.dataset.sort;
    _sort = _sort.col === id ? { col: id, dir: -_sort.dir } : { col: id, dir: ["name", "pdk", "origin", "design", "note"].includes(id) ? 1 : -1 };
    safeStorage.setJSON(SORT_KEY, _sort);
    renderRuns({ cached: true });
  }));
  table.onclick = (e) => {
    const t = e.target;
    if (t.closest(".rn-card")) return;
    const grp = t.closest("tr.rn-sweep");
    if (grp) {
      if (t.closest(".rn-sw-sum")) return;
      const gk = grp.dataset.group;
      if (_openSweeps.has(gk)) _openSweeps.delete(gk); else _openSweeps.add(gk);
      safeStorage.setJSON(OPEN_KEY, [..._openSweeps]);
      renderRuns({ cached: true });
      return;
    }
    const r = rowOf(t, runs);
    if (!r) return;
    if (t.closest(".rn-pick")) {
      const k = keyOf(r);
      if (t.checked) {
        if (_picked.size >= 6) { t.checked = false; toast.show("Compare takes up to six runs.", "info"); return; }
        _picked.add(k);
      } else _picked.delete(k);
      t.closest("tr").classList.toggle("is-picked", t.checked);
      syncSelection();
      return;
    }
    const act = t.closest("[data-act]")?.dataset.act;
    if (act === "base") {
      const isBase = baselineTag(r._design) === r.tag;
      setBaselineTag(r._design, isBase ? "" : r.tag);
      // The results pages compare with it too, when it isn't the run they show.
      if (!isBase && normDir(r._design) === normDir(contextDesign()) && r.tag !== contextRun()) setBaseline(r.tag);
      _changesKey = "";
      renderRuns({ cached: true });
      return;
    }
    if (act === "expand") { toggleOpen(r); return; }
    setRun(r.tag, r._design);
  };
  table.ondblclick = (e) => { const r = rowOf(e.target, runs); if (r && !e.target.closest(".rn-card, .rn-pick, [data-act]")) toggleOpen(r); };
  if (_open) paintCard(runs.find((r) => keyOf(r) === _open));
  table.querySelectorAll(".rn-sw-sum").forEach((el) => {
    const gk = el.dataset.sum;
    const g = [...table.querySelectorAll("tr.rn-row.is-child")].map((tr) => runs.find((r) => keyOf(r) === tr.dataset.key)).filter(Boolean)
      .filter((r) => { const sw = sweepOf(r); return sw && gk.endsWith("sweep:" + sw.id); });
    const sw = g.length ? sweepOf(g[0]) : null;
    if (sw) import("./sweeps.js").then((m) => m.paintSweepSummary(el, sw, g, { verdictOf, failCode, baseline: baselineTag(g[0]._design) }));
  });
}

function toggleOpen(r) {
  const k = keyOf(r);
  _open = _open === k ? null : k;
  if (_open) setRun(r.tag, r._design);
  renderRuns({ cached: true });
}

function paintViewing() {
  const run = contextRun(), design = normDir(contextDesign());
  document.querySelectorAll("#runs-table tr.rn-row").forEach((tr) =>
    tr.classList.toggle("is-viewing", tr.dataset.tag === run && normDir(tr.dataset.design) === design));
}

// ------------------------------------------------------------------ selection
function pickedRuns() { return _shown.runs.filter((r) => _picked.has(keyOf(r))); }
function syncSelection() {
  const bar = document.getElementById("rn-selbar");
  if (!bar) return;
  // Runs that are gone (deleted, filtered by scope) leave the selection.
  const live = new Set(_shown.runs.map(keyOf));
  for (const k of [..._picked]) if (!live.has(k)) _picked.delete(k);
  const n = _picked.size;
  bar.hidden = n === 0;
  if (!n) return;
  bar.innerHTML = "<b>" + n + " selected</b>" +
    "<button class='btn btn-primary btn-sm' data-sel='compare'" + (n < 2 ? " disabled title='Pick at least two'" : "") + ">" + icon("diff", { size: 13 }) + " Compare</button>" +
    "<button class='btn btn-ghost btn-sm' data-sel='delete'>" + icon("trash", { size: 13 }) + " Delete</button>" +
    "<button class='btn btn-ghost btn-sm' data-sel='clear'>Clear</button>" +
    (n < 2 ? "<span class='muted'>Tick one more to compare.</span>" : "");
  bar.querySelector("[data-sel='compare']").onclick = () => compareRuns(pickedRuns());
  bar.querySelector("[data-sel='delete']").onclick = () => batchDelete();
  bar.querySelector("[data-sel='clear']").onclick = () => { _picked.clear(); renderRuns({ cached: true }); };
}

export async function compareRuns(runs) {
  if (runs.length < 2) return;
  const m = await import("./compare.js");
  m.preselectCompare(runs.map((r) => r.run_dir).filter(Boolean));
  // Showing Analytics renders Compare, which ticks the pick and compares.
  go("analytics", { section: "analytics-compare" });
}

// ------------------------------------------------------------------ lazy facts
// Why each failed run failed (the same reading Flow uses), for "failed at
// Placement" and the sweep's "(DPL-0036)". Active design only (the endpoint
// resolves against it); a dozen at most per render.
let _rxBusy = false;
async function explainFailed(runs) {
  if (_rxBusy) return;
  const todo = runs.filter((r) => !r.success && !(r.verdict && r.verdict.stage) && !RX.has(keyOf(r)) &&
    normDir(r._design) === normDir(state.designDir)).slice(0, 12);
  if (!todo.length) return;
  _rxBusy = true;
  try {
    for (const r of todo) {
      try { RX.set(keyOf(r), await api.runExplain(r.tag)); } catch (_e) { RX.set(keyOf(r), {}); }
    }
  } finally { _rxBusy = false; }
  renderRuns({ cached: true });
}

// What each run changed against its design's baseline: one /api/compare over
// the design's runs (resolved configs), keys that are run paths left out.
const NOISE = /^(meta|DESIGN_DIR|.*_PATH|.*_FILE|.*_FILES|RUN_TAG|.*_DIR)$/;
async function loadChanges(runs) {
  const byDesign = new Map();
  for (const r of runs) {
    const b = baselineTag(r._design);
    if (!b) continue;
    if (!byDesign.has(r._design)) byDesign.set(r._design, []);
    byDesign.get(r._design).push(r);
  }
  const key = [...byDesign].map(([d, rs]) => d + ":" + baselineTag(d) + ":" + rs.map((r) => r.tag + r.started_at).join(",")).join("|");
  if (!key || key === _changesKey) return;
  _changesKey = key;
  for (const [d, rs] of byDesign) {
    const base = rs.find((r) => r.tag === baselineTag(d));
    if (!base) continue;
    const list = rs.slice(0, 40);
    try {
      const data = await api.compare(list.map((r) => r.tag), list.map((r) => r.run_dir));
      const diff = (data && (data.config_diff || (data.data || {}).config_diff)) || {};
      for (const r of list) {
        const out = [];
        for (const [k, per] of Object.entries(diff)) {
          if (NOISE.test(k)) continue;
          const a = per[r.run_dir], b = per[base.run_dir];
          if (JSON.stringify(a) !== JSON.stringify(b) && !/\/runs\//.test(JSON.stringify(a) + JSON.stringify(b))) out.push({ var: k, from: show(b), to: show(a) });
        }
        CHANGES.set(keyOf(r), out);
      }
    } catch (_e) { /* the column stays "…"; nothing else depends on it */ }
  }
  if (key === _changesKey) renderRuns({ cached: true });
}
const show = (v) => (v == null ? "unset" : typeof v === "object" ? JSON.stringify(v) : String(v));

// ------------------------------------------------------------------ live sweep
let _poll = null;
async function paintLive() {
  const el = document.getElementById("rn-live");
  if (!el) return;
  let st = null;
  try { st = await api.dseStatus(); st = st && (st.data || st); } catch (_e) { st = null; }
  if (!st || !st.active) {
    el.hidden = true;
    if (_poll) { clearInterval(_poll); _poll = null; renderRuns(); }
    return;
  }
  const done = (st.done || []).length + (st.failed || []).length;
  el.hidden = false;
  el.innerHTML = "<span class='rn-live-dot' aria-hidden='true'></span><b>Sweep running</b> · run " + Math.min(done + 1, st.total || done + 1) + " of " + (st.total || "?") +
    (st.running ? " · <code>" + esc(st.running) + "</code>" : "") +
    ((st.failed || []).length ? " · <span class='rn-bad'>" + st.failed.length + " failed</span>" : "") +
    "<span class='rn-spacer'></span><button class='btn btn-ghost btn-sm' data-go='pipeline'>Watch in Flow</button>" +
    "<button class='btn btn-ghost btn-sm' id='rn-sweep-stop'>" + icon("stop", { size: 13 }) + " Stop sweep</button>";
  el.querySelector("#rn-sweep-stop").onclick = async () => {
    if (!(await confirmDialog({ title: "Stop the sweep?", confirmText: "Stop sweep", danger: true,
      body: "The run that is going stops now and the rest are not run. Finished runs are kept." }))) return;
    try { await api.dseCancel(); toast.show("Sweep stopped.", "success"); } catch (ex) { toast.show("Couldn't stop: " + (ex.message || ex), "error"); }
    paintLive();
  };
  if (!_poll) _poll = setInterval(() => { if (document.getElementById("sec-runs")?.classList.contains("section-active")) paintLive(); }, 4000);
}

// ------------------------------------------------------------------ report card
async function paintCard(r) {
  const host = document.getElementById("rn-card");
  if (!host || !r) return;
  const base = baselineRowFor(r);
  const active = normDir(r._design) === normDir(state.designDir);
  let rx = RX.get(keyOf(r));
  // Verify's reading of the run, for the verdict words (the same as Flow and Verify).
  const [rx2, vfr] = await Promise.all([
    rx || !active ? Promise.resolve(rx || null) : api.runExplain(r.tag, base ? base.tag : undefined).catch(() => null),
    active && (r.success || (r.verdict && r.verdict.state !== "running")) ? api.verify(r.tag).catch(() => null) : Promise.resolve(null),
  ]);
  rx = rx2;
  const vf = vfr && (vfr.verdict ? vfr : vfr.data && vfr.data.verdict ? vfr.data : null);
  if (document.getElementById("rn-card") !== host) return;
  let card;
  if (rx && (rx.kind === "clean" || rx.kind === "checks-failed")) {
    // Flow's report card, fed with this run's final metrics (and the baseline's).
    card = reportCardHtml({ tag: r.tag, rx, vf, steps: [{ metrics: r.key_metrics || {}, secs: r.wall_time_s || 0 }],
      stages: [], base: base ? base.tag : "", baseRs: base ? { steps: [{ changed: base.key_metrics || {}, runtime_s: base.wall_time_s || 0 }] } : null });
  } else {
    const v = verdictOf(r);
    const c = (rx && rx.card) || {};
    const title = v.state === "stopped" ? "You stopped this run" : v.state === "incomplete" ? "This run ended before the last step"
      : c.title ? c.title : v.label;
    card = "<div class='an-verdict fl-hero is-" + (VERDICT_TONE[v.state] === "pass" ? "pass" : v.state === "failed" ? "fail" : "warn") + "'><div class='an-verdict-main'>" +
      "<div class='an-eyebrow'>Run " + esc(r.tag) + "</div><h2 class='an-title'>" + esc(title) + "</h2>" +
      (c.plain ? "<p class='an-lede'>" + esc(c.plain) + "</p>" : rx && rx.step ? "<p class='an-lede'>It stopped at " + esc(rx.step.id || rx.step.dir) + ".</p>" : "") +
      "</div><div class='an-verdict-act'>" + (v.state === "failed" ? "<button class='btn btn-primary btn-sm' data-go='pipeline'>" + icon("flow", { size: 13 }) + " Why, and how to fix it</button>" : "") + "</div></div>";
  }
  host.innerHTML = lineageHtml(r) + card + actionsHtml(r) + "<div class='rn-note-row'><label class='muted' for='rn-note-ta'>Note</label>" +
    "<textarea id='rn-note-ta' class='rn-note-ta' rows='2' placeholder='What you tried, what you saw…'></textarea></div>";
  // Verify didn't answer (another design, or it failed): don't promise a reading.
  if (!vf) host.querySelectorAll(".an-lede").forEach((p) => { if (/Reading the sign-off checks/.test(p.textContent)) p.textContent = "No step failed. Open Verify for the sign-off checks."; });
  const ta = host.querySelector("#rn-note-ta");
  ta.value = r.note || "";
  ta.addEventListener("blur", async () => {
    if (ta.value === (r.note || "")) return;
    try { await focusDesign(r._design); await api.setRunNote(r.tag, ta.value); r.note = ta.value; toast.show("Note saved.", "success", 2500); }
    catch (ex) { toast.show("Couldn't save the note: " + (ex.message || ex), "error"); }
  });
  host.querySelectorAll("[data-ra]").forEach((b) => b.addEventListener("click", (e) => { e.stopPropagation(); runAction(b.dataset.ra, r); }));
}

function actionsHtml(r) {
  const b = (id, label, ic, cls = "btn-ghost") => "<button class='btn " + cls + " btn-sm' data-ra='" + id + "'>" + (ic ? icon(ic, { size: 13 }) + " " : "") + esc(label) + "</button>";
  return "<div class='rn-actions'>" +
    "<span class='rn-act-g'>" + b("flow", "Flow", "flow") + b("layout", "Layout", "grid") + b("analytics", "Analytics", "chart") + b("verify", "Verify", "check") + "</span>" +
    "<span class='rn-act-g'>" + b("again", "Run again with changes", "play") + b("cmd", "Copy command", "command") + "</span>" +
    "<span class='rn-act-g'>" + b("pin", r.pinned ? "Unpin" : "Pin", "star") + b("bundle", "Bundle", "download") + b("export", "Report", "file") + b("files", "Files", "folder") + "</span>" +
    "<span class='rn-act-g'>" + b("delete", "Delete", "trash", "btn-ghost rn-del") + "</span></div>";
}

async function runAction(id, r) {
  const d = r._design;
  if (["flow", "layout", "analytics", "verify"].includes(id)) { await setRun(r.tag, d); go(id === "flow" ? "pipeline" : id); return; }
  await focusDesign(d);
  if (id === "again") return reproduceRun(r.tag);
  if (id === "cmd") return copyCommand(r.tag);
  if (id === "pin") return togglePin(r.tag, d, !r.pinned);
  if (id === "bundle") return bundleDownloadFlow(r.tag);
  if (id === "export") return exportRunFlow(r.tag);
  if (id === "files") return showFilesModal(r.tag);
  if (id === "delete") return deleteRunFlow(r.tag);
}

async function copyCommand(tag) {
  let meta;
  try { meta = await api.runGuiMeta(tag); } catch (_e) { meta = null; }
  const cc = meta && meta.cli_command;
  const cli = String((cc && typeof cc === "object" ? (cc[cc.recommended] || cc.container || cc.local) : cc) || "").trim();
  if (!cli) { await alertDialog({ title: "No saved command", body: "LanEx didn't record the command for " + tag + " (it was started elsewhere, or by a sweep before LanEx kept it)." }); return; }
  try { await navigator.clipboard.writeText(cli); toast.show("Command copied.", "success"); }
  catch (_e) { await alertDialog({ title: "The command of " + tag, body: cli }); }
}

// Batch delete every ticked run, grouped by design so each resolves against
// the right active design. One confirm for the whole set.
async function batchDelete() {
  const items = pickedRuns();
  const n = items.length;
  if (!n) return;
  const ok = await confirmDialog({
    title: "Delete " + n + " run" + (n === 1 ? "" : "s") + "?", danger: true,
    confirmText: "Delete " + n + " run" + (n === 1 ? "" : "s"),
    body: items.map((r) => r.tag).join(", ") + "\n\nThis permanently deletes " + (n === 1 ? "this run" : "these runs") + " and all their files. This cannot be undone.",
  });
  if (!ok) return;
  let failed = 0, done = 0;
  const byDesign = new Map();
  for (const r of items) { if (!byDesign.has(r._design)) byDesign.set(r._design, []); byDesign.get(r._design).push(r.tag); }
  for (const [designDir, tags] of byDesign) {
    await focusDesign(designDir);
    for (const tag of tags) {
      try { if (await deleteGuarded(tag)) { if (state.selectedRunTag === tag) state.selectedRunTag = null; done++; } }
      catch (_e) { failed++; }
    }
  }
  _picked.clear();
  await renderRuns();
  if (failed) await alertDialog({ title: "Some deletes failed", body: failed + " run(s) could not be deleted." });
  else toast.show("Deleted " + done + " run" + (done === 1 ? "" : "s") + ".", "success");
}

// Download a support bundle — the user ticks exactly what goes in. Keys match
// bundle.ALL_PARTS on the backend.
const BUNDLE_PARTS = [
  { key: "config", label: "Used config", hint: "config.json + resolved.json + GUI overrides/preset" },
  { key: "sources", label: "RTL source files" },
  { key: "metrics_csv", label: "Metrics CSV" },
  { key: "settings_csv", label: "Settings / constraints / PDK CSV" },
  { key: "analytics_csv", label: "Analytics CSV", hint: "summary + report counts + all metrics" },
  { key: "reports", label: "Signoff reports", hint: ".rpt / .drc / .lvs" },
  { key: "logs", label: "Step logs" },
  // Heavy binary deliverables — off by default (each can be tens–hundreds of MB).
  { key: "gds", label: "GDSII layout", hint: "final .gds / OASIS stream", checked: false },
  { key: "layout_views", label: "Other layout views", hint: "DEF / LEF / OpenDB / Magic", checked: false },
  { key: "netlists", label: "Netlists", hint: "gate-level + powered Verilog, SPICE/CDL, JSON header", checked: false },
  { key: "timing", label: "Timing models", hint: "Liberty .lib / SDF / SPEF / SDC", checked: false },
  { key: "images", label: "Layout images", hint: "KLayout render(s), PNG/SVG", checked: false },
  { key: "diagrams", label: "Yosys diagrams", hint: ".dot schematics + rendered .svg", checked: false },
];
async function bundleDownloadFlow(tag) {
  const picked = await checklistDialog({
    title: "Download bundle: " + tag,
    body: "Select components to include in the .zip archive. Text and report data are selected by default. " +
      "Binary deliverables like GDS, netlists, timing models, and images are large, so select only what you need.",
    items: BUNDLE_PARTS,
    confirmText: "Download .zip",
  });
  if (!picked || !picked.length) return;
  const url = api.runBundleUrl(tag, picked);
  const a = document.createElement("a");
  a.href = url; a.download = tag + "-bundle.zip";
  document.body.appendChild(a); a.click(); a.remove();
  toast.show("Preparing bundle…", "info");
}

// E3 — download a formatted run report (CSV / Markdown / HTML). The backend
// (history.export_run + /api/run-export) already exists; this is the UI for it.
async function exportRunFlow(tag) {
  const fmt = await choiceDialog({
    title: "Export run report: " + tag,
    body: "Download a formatted report for this run. (For the raw metrics table, use Analytics > Metrics CSV.)",
    choices: [
      { label: "CSV", value: "csv" },
      { label: "Markdown", value: "md" },
      { label: "HTML", value: "html" },
    ],
  });
  if (!fmt) return;
  const a = document.createElement("a");
  a.href = api.runExportUrl(tag, fmt);
  a.download = tag + "-report." + fmt;
  document.body.appendChild(a); a.click(); a.remove();
}

// E2 — load a run's saved settings back into Setup so it can be re-run. Reads
// gui-run.json (persisted per run); never auto-starts the run.
async function reproduceRun(tag) {
  let meta;
  try {
    meta = await api.runGuiMeta(tag);
  } catch (ex) {
    await alertDialog({
      title: "Can't reproduce this run",
      body: (ex && ex.message) ||
        "No saved settings found for this run. It was created before reproduce support was available or generated outside the GUI.",
    });
    return;
  }
  const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val || ""; };
  // PDK / SCL — set state + the pickers; refresh the SCL list off the PDK.
  if (meta.pdk) {
    state.selectedPdk = meta.pdk;
    const ps = document.getElementById("pdk-select");
    if (ps) { ps.value = meta.pdk; ps.dispatchEvent(new Event("change")); }
  }
  if (meta.scl) {
    state.selectedScl = meta.scl;
    // The PDK change above repopulates SCLs asynchronously; set after a tick.
    setTimeout(() => { const sc = document.getElementById("scl-select"); if (sc) sc.value = meta.scl; }, 0);
  }
  if (meta.run_mode) state.runMode = meta.run_mode;
  // Config overrides.
  state.varsValues = {};
  for (const [k, v] of Object.entries(meta.overrides || {})) {
    state.varsValues[k] = (typeof v === "boolean") ? v : String(v);
  }
  // Where it stopped: the Run menu's "Run up to" stage, when --to was a stage's
  // last step. (--from and --skip are no longer set from LanEx; see below.)
  const stopSel = document.getElementById("run-stop-after");
  if (stopSel) {
    stopSel.value = "";
    if (meta.to) for (const o of stopSel.options) if (o.value && lastStepOfStage(o.value) === meta.to) stopSel.value = o.value;
    stopSel.dispatchEvent(new Event("change"));
  }
  // Full-auto vs step-by-step.
  const modeVal = meta.mode === "semi" ? "semi" : "auto";
  document.querySelectorAll(".mode-btn").forEach((b) =>
    b.classList.toggle("mode-btn-active", b.dataset.mode === modeVal));
  // Run name.
  const rn = (meta.tag || tag) + "-repro";
  setVal("run-name-input", rn);
  // Sources (best-effort — files may have moved/been deleted since the run).
  if (Array.isArray(meta.sources) && meta.sources.length) state.selectedFiles = meta.sources.slice();
  // Repaint the config panel + jump to Setup.
  try { const cfg = await import("./config.js"); cfg.renderConfig(); } catch (_e) { /* ignore */ }
  go("setup");
  const summary = "Loaded " + Object.keys(meta.overrides || {}).length + " override(s), " +
    (meta.sources || []).length + " source(s), " + (meta.run_mode || "container") +
    " mode, flow " + (meta.flow || "Classic") + ". Review your settings in Setup, then click Run flow when ready. " +
    "Nothing has started yet." +
    (meta.frm || (meta.skip || []).length ? " That run also used --from or --skip; LanEx runs the whole flow (or up to a stage) instead." : "");
  // E4.4 — offer the EXACT CLI command this run was launched with (persisted in
  // gui-run.json, not rebuilt), so a terminal user can reproduce it verbatim.
  // gui-run.json keeps the command per engine ({container, local, recommended}).
  const cc = meta.cli_command;
  const cli = String((cc && typeof cc === "object" ? (cc[cc.recommended] || cc.container || cc.local) : cc) || "").trim();
  const choices = cli ? [{ label: "Copy the run's CLI command", value: "copy" }] : [];
  const pick = await choiceDialog({
    title: "Loaded " + tag + " into Setup",
    body: summary + (cli ? "\n\nThat run's exact command:\n" + cli : ""),
    choices,
  });
  if (pick === "copy" && cli) {
    try { await navigator.clipboard.writeText(cli); toast.show("CLI command copied.", "success"); }
    catch (_e) { toast.show("Copy failed. The command is shown above: select it and copy it.", "warn"); }
  }
}

// E4.5 — pin/star a run so it's easy to find in a long history. Just a bookmark
// marker; never touches run data.
async function togglePin(tag, designDir, pinned) {
  try {
    await focusDesign(designDir);
    await api.setRunPin(tag, pinned);
    await renderRuns();
  } catch (ex) {
    toast.show("Could not " + (pinned ? "pin" : "unpin") + ": " + (ex.message || ex), "error");
  }
}

// E1 — import a run from elsewhere: adopt a run directory, or restore a LanEx
// export bundle (.zip). Both land under the active design's runs/.
async function importRunFlow() {
  if (!state.designDir) {
    await alertDialog({
      title: "No active design",
      body: "Set a design directory first. Imported runs are saved into its runs directory.",
    });
    return;
  }
  const kind = await choiceDialog({
    title: "Import a run",
    body: "Adopt an existing LibreLane run directory, or restore a LanEx export bundle (.zip). It is copied into this design's runs/ so it survives deletion of the source.",
    choices: [
      { label: "Run folder", value: "dir" },
      { label: "LanEx bundle (.zip)", value: "bundle" },
    ],
  });
  if (!kind) return;
  const path = await promptDialog({
    title: kind === "dir" ? "Adopt a run directory" : "Import a bundle (.zip)",
    label: kind === "dir"
      ? "Absolute path to the run directory (a runs/<tag> folder):"
      : "Absolute path to the LanEx bundle (.zip):",
  });
  if (!path || !path.trim()) return;
  try {
    const res = kind === "dir"
      ? await api.importRunDir(path.trim())
      : await api.importRunBundle({ path: path.trim() });
    await renderRuns();
    let msg = "Imported as '" + res.tag + "'.";
    if (res.warnings && res.warnings.length) msg += " " + res.warnings.join(" ");
    toast.show(msg, "success");
  } catch (ex) {
    await alertDialog({ title: "Import failed", body: (ex && ex.message) || String(ex) });
  }
}

async function deleteRunFlow(tag) {
  const ok = await confirmDialog({
    title: "Delete run " + tag + "?", danger: true, confirmText: "Delete run",
    body: "This permanently deletes run '" + tag + "' and all its files. Consider downloading a bundle first. This cannot be undone.",
  });
  if (!ok) return;
  try {
    if (!(await deleteGuarded(tag))) return;
    if (state.selectedRunTag === tag) state.selectedRunTag = null;
    await renderRuns();
    toast.show("Deleted run '" + tag + "'.", "success");
  } catch (ex) {
    await alertDialog({ title: "Delete failed", body: ex.message || String(ex) });
  }
}

// Runs resumed from another one read that run's earlier steps from its folder:
// the server refuses to delete it while they exist, and this asks once more.
async function deleteGuarded(tag) {
  try {
    await api.deleteRun(tag);
    return true;
  } catch (ex) {
    const kids = ex && ex.status === 409 && ex.body && ex.body.children;
    if (!kids || !kids.length) throw ex;
    const ok = await confirmDialog({
      title: "Other runs were resumed from " + tag, danger: true, confirmText: "Delete it anyway",
      body: kids.join(", ") + (kids.length === 1 ? " was" : " were") + " resumed from '" + tag + "' and " + (kids.length === 1 ? "reads" : "read") +
        " its earlier steps from its folder. Deleted, " + (kids.length === 1 ? "that run" : "those runs") +
        " keep their own results and final GDS, but their earlier steps, pictures and checks go with it.",
    });
    if (!ok) return false;
    await api.deleteRun(tag, true);
    return true;
  }
}

let _filesOverlay = null;
function filesOverlay() {
  if (_filesOverlay) return _filesOverlay;
  const ov = document.createElement("div");
  ov.className = "smodal-backdrop";
  ov.hidden = true;
  ov.innerHTML =
    "<div class='smodal'>" +
    "  <div class='smodal-head'><span class='smodal-title' id='files-title'>Files</span>" +
    "  <span class='smodal-spacer'></span><button class='btn btn-ghost' id='files-close'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button></div>" +
    "  <div class='smodal-log' id='files-body' style='white-space:normal'></div>" +
    "</div>";
  document.body.appendChild(ov);
  ov.addEventListener("click", (e) => { if (e.target === ov) ov.hidden = true; });
  ov.querySelector("#files-close").addEventListener("click", () => { ov.hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !ov.hidden) ov.hidden = true; });
  _filesOverlay = ov;
  return ov;
}

function fmtBytes(n) {
  if (!n) return "";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}

async function showFilesModal(tag) {
  const ov = filesOverlay();
  ov.hidden = false;
  ov.querySelector("#files-title").textContent = "Files: " + tag;
  const body = ov.querySelector("#files-body");
  body.textContent = "loading…";
  let r;
  try {
    r = await api.runFiles(tag);
  } catch (ex) {
    body.textContent = "Could not list files: " + (ex.message || ex);
    return;
  }
  const files = (r && r.files) || [];
  // Group by top-level dir (step/final/…) for readability.
  const rows = files
    .filter((f) => !f.dir)
    .map((f) => {
      const url = api.runFileUrl(tag, f.path);
      return (
        "<div class='files-row'><a href='" + url + "' target='_blank' rel='noopener'>" +
        fmt.escape(f.path) + "</a> <span class='muted'>" + fmtBytes(f.size) + "</span></div>"
      );
    });
  body.innerHTML =
    "<div class='muted' style='margin-bottom:8px'>" + rows.length + " files: click to open or download</div>" +
    rows.join("");
}

