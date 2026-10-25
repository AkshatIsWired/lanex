// context.js — the run every results page is looking at, and the run it is
// compared with. One selection for the whole app, the way Vivado and the
// OpenROAD GUI keep one selection that every view follows: pick a run in
// Layout and Analytics and Verify show it too.
//
//   loadRuns()          the runs in the current scope, with run + baseline settled
//   contextRun()        the tag on screen (state.selectedRunTag mirrors it)
//   contextBaseline()   the tag it is compared with ("" = nothing)
//   setRun / setBaseline / setRunScope     change it; "g:context" says so
//     (detail.why: run | baseline | scope | project | run-finished | runs, and
//     loaded / settled after a load, which the pages that loaded ignore)
//
// Each project remembers its own run and baseline (localStorage ll.context).
// Without a remembered run the newest is shown; the baseline defaults to the
// newest finished run before it, until the user picks one. When a run finishes,
// the context follows it if the user was on the newest run when it started.
//
// Scope: "this design" or "all designs you have opened" (ll.runScope, shared
// by every run list, Runs included).

import { api } from "./api.js";
import { state, safeStorage } from "./state.js";

const SCOPE_KEY = "ll.runScope";   // "design" | "all"
const MEM_KEY = "ll.context";      // { [design dir]: { run, baseline, picked } }


const C = { design: "", run: null, baseline: "", picked: false, runs: [], follow: false };

export function contextRun() { return C.run; }
export function contextBaseline() { return C.baseline; }
export function contextDesign() { return C.design; }
// The runs of the last loadRuns(), newest first (all designs in "all" scope).
export function contextRuns() { return C.runs; }
export function contextRow(tag = C.run, design = C.design) {
  return C.runs.find((r) => r.tag === tag && normDir(r._design) === normDir(design)) ||
    C.runs.find((r) => r.tag === tag) || null;
}
// Runs of the context run's design other than itself: what it can be compared with.
export function baselineChoices() {
  return C.runs.filter((r) => normDir(r._design) === normDir(C.design) && r.tag !== C.run);
}

export function onContext(fn) {
  document.addEventListener("g:context", (e) => fn(e.detail || {}));
}

function emit(why) {
  state.selectedRunTag = C.run;
  document.dispatchEvent(new CustomEvent("g:context", {
    detail: { run: C.run, baseline: C.baseline, design: C.design, why },
  }));
}

// ---------------------------------------------------------------- memory
function memory() { return safeStorage.getJSON(MEM_KEY, {}) || {}; }
function remember() {
  // A list that came back empty must not erase the run the user picked.
  if (!C.design || !C.run) return;
  const m = memory();
  m[normDir(C.design)] = { run: C.run, baseline: C.baseline, picked: C.picked };
  // Keep the 30 most recent projects.
  const keys = Object.keys(m);
  for (const k of keys.slice(0, Math.max(0, keys.length - 30))) delete m[k];
  safeStorage.setJSON(MEM_KEY, m);
}
function recall(design) { return memory()[normDir(design)] || null; }

// ---------------------------------------------------------------- settle
// Keep the run if it still exists; else the remembered one; else the newest of
// the active design (or of any design, when this one has none).
function settle() {
  const runs = C.runs;
  if (!runs.length) { C.run = null; C.baseline = ""; return; }
  const exists = (tag, design) => runs.some((r) => r.tag === tag && normDir(r._design) === normDir(design));
  if (!C.run || !exists(C.run, C.design)) {
    const design = state.designDir || C.design;
    const mem = recall(design);
    const own = runs.filter((r) => normDir(r._design) === normDir(design));
    if (mem && mem.run && exists(mem.run, design)) {
      C.run = mem.run; C.design = design;
      C.baseline = mem.baseline || ""; C.picked = !!mem.picked;
    } else {
      const pick = own[0] || runs[0];
      C.run = pick.tag; C.design = pick._design || design;
      C.picked = false;
    }
  }
  settleBaseline();
}

function settleBaseline() {
  const same = C.runs.filter((r) => normDir(r._design) === normDir(C.design));
  const ok = (tag) => tag && tag !== C.run && same.some((r) => r.tag === tag);
  if (C.picked && (C.baseline === "" || ok(C.baseline))) return;   // the user's choice stands
  C.picked = false;
  const idx = same.findIndex((r) => r.tag === C.run);
  const prev = same.slice(idx + 1).find((r) => r.success);
  C.baseline = prev ? prev.tag : "";
}

// ---------------------------------------------------------------- loading
// A run list that fails to load (the server slow on /mnt/c, asleep, being
// restarted) is NOT an empty list: the last good one stays on every page and
// a retry is scheduled. Treating the failure as "no runs" is what made runs
// vanish from Runs, Layout and Analytics and come back a while later.
let _loading = null;
let _loadingKey = "";
let _gen = 0;
let _loadedKey = "";
let _loadedAt = 0;
let _failed = false;
let _retry = null;
const FRESH_FOR_MS = 1500;

function loadKey() { return getRunScope() + "\0" + normDir(state.designDir); }

// True while the newest attempt to list runs failed (pages say "couldn't
// refresh" instead of "no runs yet").
export function runsLoadFailed() { return _failed; }

export async function loadRuns({ fresh = false } = {}) {
  const key = loadKey();
  // Pages that open together, and tab switches in quick succession, share one
  // listing instead of each asking the server for the same thing.
  if (_loading && _loadingKey === key) return _loading;
  if (!fresh && !_failed && key === _loadedKey && Date.now() - _loadedAt < FRESH_FOR_MS) return C.runs;
  const gen = ++_gen;
  const p = (async () => {
    let runs;
    try {
      runs = await gatherRunsScoped(undefined, { strict: true });
    } catch (_e) {
      if (gen !== _gen) return C.runs;
      _failed = true;
      scheduleRetry();
      // Not a "g:context" change (pages reload on those, which would retry
      // in a tight loop): run bars listen for this to say "couldn't refresh".
      document.dispatchEvent(new CustomEvent("g:runs_state", { detail: { failed: true } }));
      // Same project and scope: keep what is on screen. Another project: we
      // know nothing about it yet, so nothing is shown rather than its runs.
      return _loadedKey === key ? C.runs : [];
    }
    // A slower answer for a project the user has since left is dropped.
    if (gen !== _gen || key !== loadKey()) return runs;
    if (_failed) document.dispatchEvent(new CustomEvent("g:runs_state", { detail: { failed: false } }));
    _failed = false;
    _loadedKey = key;
    _loadedAt = Date.now();
    if (getRunScope() === "design") state.runs = runs;
    C.runs = runs;
    const before = C.run + "\0" + C.design + "\0" + C.baseline;
    settle();
    if (C.run) await ensureActiveDesignFor(contextRow());
    remember();
    // Run bars repaint; pages ignore "loaded" / "settled" (they asked for it).
    emit(before !== C.run + "\0" + C.design + "\0" + C.baseline ? "settled" : "loaded");
    return runs;
  })();
  _loading = p;
  _loadingKey = key;
  try { return await p; } finally { if (_loading === p) { _loading = null; _loadingKey = ""; } }
}

// LanEx came back after being unreachable (api.js): list again.
if (typeof document !== "undefined") {
  document.addEventListener("g:server_back", () => {
    if (_loadedKey || _failed) loadRuns({ fresh: true }).then(() => { if (!_failed) emit("runs"); });
  });
}

// After a failed listing, try again by itself; pages repaint on "runs".
function scheduleRetry() {
  if (_retry) return;
  _retry = setTimeout(async () => {
    _retry = null;
    await loadRuns({ fresh: true });
    if (!_failed) emit("runs");
  }, 4000);
}

// ---------------------------------------------------------------- changes
export async function setRun(tag, design) {
  const row = contextRow(tag, design || C.design);
  if (!row) return;
  if (row.tag === C.run && normDir(row._design) === normDir(C.design)) return;
  await ensureActiveDesignFor(row);
  const otherDesign = normDir(row._design) !== normDir(C.design);
  C.run = row.tag;
  C.design = row._design || state.designDir;
  if (otherDesign) C.picked = false;
  settleBaseline();
  remember();
  emit("run");
}

export function setBaseline(tag) {
  C.baseline = tag || "";
  C.picked = true;
  remember();
  emit("baseline");
}

// A project was opened: show what it was showing last time.
export function openProject(designDir) {
  if (normDir(designDir) === normDir(C.design)) return;
  const mem = recall(designDir);
  C.design = designDir;
  C.run = mem ? mem.run : null;
  C.baseline = mem ? mem.baseline || "" : "";
  C.picked = !!(mem && mem.picked);
  state.selectedRunTag = C.run;
  emit("project");
}

// A run started: follow it when it ends if the user is on the newest run now.
export function noteRunStarted() {
  const own = C.runs.filter((r) => normDir(r._design) === normDir(state.designDir));
  C.follow = !C.run || !own.length || (own[0].tag === C.run && normDir(C.design) === normDir(state.designDir));
}

// A run finished: reload, and move to it when the user was following.
export async function noteRunFinished(tag) {
  const follow = C.follow;
  C.follow = false;
  await waitForRun(tag);
  const newest = (tag && contextRow(tag, state.designDir)) || C.runs.find((r) => normDir(r._design) === normDir(state.designDir));
  if (follow && newest) {
    C.run = newest.tag;
    C.design = newest._design || state.designDir;
    settleBaseline();          // a baseline the user picked stays
    remember();
  }
  emit(follow ? "run-finished" : "runs");
}

// The run list, once it has `tag`: right after a run ends the server can list
// runs before it lists the one that just finished, so ask again for a few
// seconds rather than follow the run before it.
export async function waitForRun(tag) {
  await loadRuns({ fresh: true });
  for (let i = 0; tag && i < 8 && !contextRow(tag, state.designDir); i++) {
    await new Promise((r) => setTimeout(r, 700));
    await loadRuns({ fresh: true });
  }
  return !tag || !!contextRow(tag, state.designDir);
}

// ---------------------------------------------------------------- scope
export function getRunScope() {
  // Runs used to keep its own scope key; adopt it the first time.
  const old = safeStorage.get("ll.runsScope");
  if (old !== null) {
    if (safeStorage.get(SCOPE_KEY) === null) safeStorage.set(SCOPE_KEY, old === "all" ? "all" : "design");
    safeStorage.remove("ll.runsScope");
  }
  return safeStorage.get(SCOPE_KEY) === "all" ? "all" : "design";
}
export function setRunScope(s) {
  safeStorage.set(SCOPE_KEY, s === "all" ? "all" : "design");
  emit("scope");
}

// Two spellings of the same folder (trailing slash, separators) are one design.
export function normDir(d) {
  return String(d || "").replace(/[\\/]+$/, "").replace(/\\/g, "/");
}
export function designLabel(dir) {
  return (dir || "").split(/[/\\]/).filter(Boolean).pop() || dir || "";
}

// Runs for `scope` (default: the preference). "all" merges the recent designs
// (ll.recentDesigns), the ones the server remembers and the active one, de-duped
// by run_dir, each row tagged with `_design`. Newest first.
// `strict`: a failed listing throws (callers keep their last good list)
// instead of quietly coming back empty.
export async function gatherRunsScoped(scope, { strict = false } = {}) {
  scope = scope || getRunScope();
  const byRunDir = new Map();
  const add = (runs, dir) => {
    for (const r of runs || []) {
      const key = r.run_dir || (normDir(dir) + "/runs/" + r.tag);
      if (byRunDir.has(key)) continue;
      r._design = dir;
      byRunDir.set(key, r);
    }
  };
  if (scope !== "all") {
    try { add(await runsOnce(state.designDir || undefined), state.designDir); } catch (e) { if (strict) throw e; }
    return Array.from(byRunDir.values());
  }
  let dirs = [];
  try { dirs = JSON.parse(localStorage.getItem("ll.recentDesigns") || "[]").filter(Boolean); } catch (_e) {}
  try { dirs = dirs.concat((await api.knownDesigns()).designs || []); } catch (_e) {}
  if (state.designDir) dirs.unshift(state.designDir);
  const seen = new Set();
  for (const dir of dirs) {
    const nd = normDir(dir);
    if (seen.has(nd)) continue;
    seen.add(nd);
    try {
      add(await runsOnce(dir), dir);
    } catch (e) {
      // A removed folder answers 404 quickly; a slow or failing server keeps
      // that design's runs from the last good list.
      if (e && e.status === 404) continue;
      add(C.runs.filter((r) => normDir(r._design) === nd), dir);
    }
  }
  const all = Array.from(byRunDir.values());
  all.sort((a, b) => String(b.started_at || "").localeCompare(String(a.started_at || "")));
  return all;
}

// One retry: a request that timed out behind a busy moment usually answers
// the second time, now that the server keeps run summaries.
async function runsOnce(dir) {
  try { return await api.runs(dir); } catch (e) {
    if (e && e.status >= 400 && e.status < 500) throw e;
    await new Promise((r) => setTimeout(r, 1200));
    return api.runs(dir);
  }
}

// Run-scoped endpoints resolve against the server's active design: switch it
// when the run lives elsewhere (and tell the top bar).
export async function ensureActiveDesignFor(run) {
  const dir = run && run._design;
  if (dir && normDir(dir) !== normDir(state.designDir)) {
    try {
      await api.setDesignDir(dir);
      state.designDir = dir;
      document.dispatchEvent(new CustomEvent("g:active_design_changed", { detail: { dir } }));
    } catch (_e) {}
  }
  return state.designDir;
}

// DSE's own multi-run picker still carries a scope box (it joins Runs later).
export function scopeToggleHtml(id) {
  return "<label class='run-scope-toggle' title=\"Show runs from every design you've opened recently, not just the active one\">" +
    "<input type='checkbox' id='" + id + "'" + (getRunScope() === "all" ? " checked" : "") + "/> All designs</label>";
}
export function wireScopeToggle(id, onChange) {
  const cb = document.getElementById(id);
  if (!cb || cb._wired) return;
  cb._wired = true;
  cb.addEventListener("change", () => { setRunScope(cb.checked ? "all" : "design"); if (onChange) onChange(); });
}
