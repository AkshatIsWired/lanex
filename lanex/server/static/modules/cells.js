// cells.js — the Cells & macros tab.
//
// One page, three jobs, in the order a design meets them:
//   Library     every standard cell the flow can build with: what it does
//               (function, gate diagram, truth table), what it looks like
//               (the real GDS), how fast each drive strength is, and whether
//               this design's flow is allowed to use it. Usage (the run on the results pages) on top.
//   Macros      pre-built blocks (PDK SRAMs, a block hardened in another
//               project, files from a vendor) with the checks that catch a
//               first macro's usual mistakes before a run does (cells-macros.js).
//   Flow rules  the cells the flow refuses, the ones it inserts by itself, and
//               your own swaps (cells-rules.js).
//
// Everything comes from files the PDK ships (controller/celllib.py); nothing
// here is hard-coded per PDK.

import { api } from "./api.js";
import { state, safeStorage } from "./state.js";
import { toast } from "./toast.js";
import { icon } from "./icons.js";
import { wireJump } from "./jumpnav.js";
import * as M from "./cells-model.js";
import * as runCtx from "./context.js";
import { localeNum } from "./intlcache.js";

const esc = M.esc;
const LS = "lanex.cells.view";

const S = {
  pdk: "", scl: "",
  lib: null,              // /api/celllib response
  fams: [],               // [{fam, cat, desc, cells:[row]}]
  byName: new Map(),      // cell -> row
  sel: null,              // selected cell name
  detail: new Map(),      // cell -> /api/celllib/cell
  layout: new Map(),      // cell -> /api/celllib/layout
  hidden: new Set(),      // layout layer keys switched off
  token: 0,
  view: Object.assign({ q: "", cat: "", used: false, hideEx: false, sort: "name" }, safeStorage.getJSON(LS, {}) || {}),
};
S.view.q = "";            // a search never survives a reload

function saveView() {
  const { cat, used, hideEx, sort } = S.view;
  safeStorage.set(LS, JSON.stringify({ cat, used, hideEx, sort }));
}

// ---------------------------------------------------------------- entry ----
let _wired = false;
export async function renderCells(opts = {}) {
  const sec = document.getElementById("sec-cells");
  if (!sec) return;
  if (!_wired) { wire(sec); _wired = true; }
  const want = pickLibrary(opts.pdk, opts.scl);
  paintPicker(want);
  if (!want) {
    document.getElementById("cl-summary").innerHTML = "";
    document.getElementById("cl-lib").innerHTML = emptyHtml("No PDK installed",
      "Install a PDK from the Tools tab. Its standard cells, SRAMs and flow rules show up here.", "tools", "Go to Tools");
    return;
  }
  // usage, exclusions and roles depend on the open project too
  if (!S.lib || S.pdk !== want.pdk || S.scl !== want.scl || S.dd !== (state.designDir || "") || opts.force) await load(want.pdk, want.scl, opts.cell);
  else if (opts.cell) select(opts.cell, { scroll: true });
  import("./cells-macros.js").then((m) => m.renderMacros(ctx())).catch((e) => console.error(e));
  import("./cells-rules.js").then((m) => m.renderRules(ctx())).catch((e) => console.error(e));
}

// Open one cell from anywhere (Analytics cell table, timing reports…).
export async function openCell(name, { pdk, scl } = {}) {
  const { go } = await import("./nav.js");
  go("cells", { cell: name, pdk, scl });
}

// The context the sibling modules share.
function ctx() {
  return {
    pdk: S.pdk, scl: S.scl, lib: S.lib, byName: S.byName,
    projectPdk: state.selectedPdk, projectScl: state.selectedScl,
    reload: () => load(S.pdk, S.scl, S.sel, { keepScroll: true }),
    openCell: (n) => { select(n, { scroll: true }); document.getElementById("cl-library")?.scrollIntoView({ behavior: "smooth", block: "start" }); },
    setUserExcluded,
  };
}

function pickLibrary(pdk, scl) {
  const pdks = (state.pdks || []).filter((p) => p.ready !== false);
  if (!pdks.length) return null;
  const has = (p, s) => pdks.some((x) => x.name === p && (x.variants || []).some((v) => v[0] === s));
  if (pdk && scl && has(pdk, scl)) return { pdk, scl };
  if (S.pdk && S.scl && has(S.pdk, S.scl) && !S.followProject) return { pdk: S.pdk, scl: S.scl };
  if (has(state.selectedPdk, state.selectedScl)) return { pdk: state.selectedPdk, scl: state.selectedScl };
  const p = pdks.find((x) => x.name === state.selectedPdk) || pdks[0];
  const v = (p.variants || [])[0];
  return v ? { pdk: p.name, scl: v[0] } : null;
}

function paintPicker(want) {
  const sel = document.getElementById("cl-libpick");
  if (!sel) return;
  const pdks = (state.pdks || []).filter((p) => p.ready !== false);
  sel.innerHTML = pdks.map((p) => "<optgroup label='" + esc(p.name) + "'>" +
    (p.variants || []).map((v) => {
      const val = p.name + "|" + v[0];
      const mine = !!state.designDir && p.name === state.selectedPdk && v[0] === state.selectedScl;
      return "<option value='" + esc(val) + "'" + (want && want.pdk === p.name && want.scl === v[0] ? " selected" : "") + ">" +
        esc(v[0]) + (mine ? "  (this project)" : "") + "</option>";
    }).join("") + "</optgroup>").join("");
  const note = document.getElementById("cl-libnote");
  if (note) {
    const other = want && state.selectedScl && (want.pdk !== state.selectedPdk || want.scl !== state.selectedScl);
    note.innerHTML = other
      ? "<span class='cl-note-warn'>" + icon("eye", { size: 13 }) + " Browsing another library. This project builds with <b>" + esc(state.selectedScl) + "</b>.</span> <button class='btn btn-ghost btn-sm' id='cl-back'>Back to the project's</button>"
      : (want ? "<span class='muted'>" + (state.designDir ? "The library this project's runs use. Change it on Setup." : "The library Setup has selected. Open a project to see its usage and rules.") + "</span>" : "");
    note.querySelector("#cl-back")?.addEventListener("click", () => { S.followProject = true; renderCells({ force: true }); S.followProject = false; });
  }
}

function wire(sec) {
  wireJump(sec);
  sec.addEventListener("change", (e) => {
    if (e.target.id === "cl-libpick") {
      const [pdk, scl] = e.target.value.split("|");
      S.sel = null;
      renderCells({ pdk, scl });
    }
  });
  document.getElementById("cl-refresh")?.addEventListener("click", () => {
    S.detail.clear(); S.layout.clear();
    renderCells({ force: true, cell: S.sel });
  });
  sec.addEventListener("click", (e) => {
    const jump = e.target.closest("[data-cl-jump]");
    if (jump) { document.getElementById(jump.dataset.clJump)?.scrollIntoView({ behavior: "smooth", block: "start" }); }
  });
  // A config change elsewhere (Settings card, All settings) can change the
  // exclusions or roles; a finished run changes usage.
  const stale = () => { if (S.lib) S.stale = true; };
  document.addEventListener("g:config_changed", stale);
  document.addEventListener("g:flow_done", stale);
  // Usage is the run every results page shows (context.js): follow it.
  runCtx.onContext((d) => {
    if (d.why === "loaded" || d.why === "baseline" || !S.lib) return;
    if (!sec.classList.contains("section-active")) { S.stale = true; return; }
    if (d.why !== "settled") renderCells({ force: true, cell: S.sel });
  });
  document.addEventListener("g:active_design_changed", () => { S.lib = null; S.sel = null; });
  document.addEventListener("g:tab_activated", (e) => {
    if (e.detail && e.detail.tab === "cells" && S.stale) { S.stale = false; S.lib = null; }
  });
}

// ---------------------------------------------------------------- load -----
async function load(pdk, scl, wantCell, { keepScroll = false } = {}) {
  const my = ++S.token;
  S.pdk = pdk; S.scl = scl; S.dd = state.designDir || "";
  const host = document.getElementById("cl-lib");
  if (!keepScroll) host.innerHTML = "<div class='cl-loading'><span class='spinner'></span> Reading " + esc(scl) + " (Liberty, LEF and the PDK's flow config)…</div>";
  let res;
  try { res = await api.cellLibrary(pdk, scl, state.designDir); } catch (ex) { res = { ok: false, error: ex.message || String(ex) }; }
  if (my !== S.token) return;
  // The server counts the newest run with a cell report; show the run on the
  // results pages instead when it has one for this library.
  if (res && res.ok !== false && state.designDir) {
    await runCtx.loadRuns().catch(() => {});
    const row = runCtx.contextRow();
    if (row && row.tag !== (res.usage || {}).tag && runCtx.normDir(row._design) === runCtx.normDir(state.designDir) && (!row.scl || row.scl === scl)) {
      try {
        const u = await api.cellUsage(row.tag);
        const named = ((u && u.cells) || []).filter((x) => typeof x.cell === "string" && x.count != null && !/^(design__|class:)/.test(x.cell));
        if (named.length) res.usage = { tag: row.tag, cells: Object.fromEntries(named.map((x) => [x.cell, x.count])) };
      } catch (_e) { /* keep the server's pick */ }
      if (my !== S.token) return;
    }
  }
  if (!res || res.ok === false) {
    S.lib = null;
    host.innerHTML = emptyHtml("Couldn't read " + scl, (res && res.error) || "unknown error", null);
    document.getElementById("cl-summary").innerHTML = "";
    return;
  }
  S.lib = res;
  S.byName = new Map(res.cells.map((c) => [c.cell, c]));
  const used = (res.usage && res.usage.cells) || {};
  for (const c of res.cells) c.used = used[c.cell] || 0;
  buildFamilies();
  paintSummary();
  paintLibraryShell();
  paintList();
  const first = wantCell && S.byName.has(wantCell) ? wantCell
    : (S.sel && S.byName.has(S.sel) ? S.sel : defaultCell());
  if (first) select(first, { scroll: !!wantCell });
}

function defaultCell() {
  // Something a beginner recognises: the 2-input NAND, else the first logic gate.
  const pref = ["nand2", "nand2b", "a21oi", "inv"];
  for (const p of pref) {
    const f = S.fams.find((x) => x.fam === p);
    if (f) return pickDrive(f).cell;
  }
  return S.fams[0] ? pickDrive(S.fams[0]).cell : null;
}

function pickDrive(f) {
  return f.cells.find((c) => c.used) || f.cells.find((c) => !isExcluded(c) && c.drive === "1") ||
    f.cells.find((c) => !isExcluded(c)) || f.cells[0];
}

function buildFamilies() {
  const map = new Map();
  for (const c of S.lib.cells) {
    const key = c.family + "\u0000" + (c.cell.startsWith(S.lib.prefix) ? "" : c.cell.slice(0, c.cell.length - c.family.length - c.drive.length));
    let f = map.get(key);
    if (!f) {
      const lib = c.cell.startsWith(S.lib.prefix) ? "" : c.cell.slice(0, c.cell.lastIndexOf(c.family)).replace(/_+$/, "");
      f = { fam: c.family, lib, cat: c.category, desc: c.desc, cells: [] };
      map.set(key, f);
    }
    f.cells.push(c);
    if (!f.desc && c.desc) f.desc = c.desc;
  }
  for (const f of map.values()) {
    f.cells.sort((a, b) => M.driveKey(a.drive) - M.driveKey(b.drive) || a.cell.localeCompare(b.cell));
    f.used = f.cells.reduce((s, c) => s + (c.used || 0), 0);
    if (!f.desc) {
      const out = (f.cells[0].outputs || [])[0];
      const ast = out && (M.headerFormulas(f.cells[0].formula)[out.name] || M.parseFunction(out.function));
      f.desc = f.cells[0].seq ? (f.cells[0].seq.kind === "ff" ? "Flip-flop" : "Latch") : (ast ? M.classify(ast) : (S.lib.categories[f.cat] || ""));
      f.descGenerated = true;
    }
    f.search = (f.fam + " " + f.desc + " " + (S.lib.categories[f.cat] || "") + " " +
      f.cells.map((c) => c.cell).join(" ") + " " + f.cells.flatMap((c) => (c.outputs || []).map((o) => o.function || "")).join(" ")).toLowerCase();
  }
  S.fams = [...map.values()];
}

export function isExcluded(c) {
  const e = c.excluded || {};
  return !!(e.synth || e.pnr || e.user || e.swap);
}

// ---------------------------------------------------------------- summary --
function paintSummary() {
  const L = S.lib;
  const cells = L.cells;
  const logic = cells.filter((c) => c.category !== "physical" && c.has_lib);
  const ex = cells.filter(isExcluded);
  const pdkEx = ex.filter((c) => c.excluded.synth || c.excluded.pnr).length;
  const userEx = ex.filter((c) => c.excluded.user || c.excluded.swap).length;
  const usable = logic.filter((c) => !isExcluded(c) && !c.dont_use).length;
  const u = L.usage || {};
  const types = cells.filter((c) => c.used).length;
  const inst = cells.reduce((s, c) => s + (c.used || 0), 0);
  const corner = (L.corner || "").replace(/_/g, " ");
  const tile = (k, v, sub, attrs = "") =>
    "<button class='cl-tile' " + attrs + "><span class='cl-tile-k'>" + esc(k) + "</span><span class='cl-tile-v'>" + v + "</span>" +
    "<span class='cl-tile-s'>" + sub + "</span></button>";
  document.getElementById("cl-summary").innerHTML =
    "<div class='cl-tiles'>" +
    tile("Library", esc(String(cells.length)), esc(S.fams.length + " families · " + (corner || "corner unknown")), "data-cl-jump='cl-library'") +
    tile("Synthesis can use", esc(String(usable)), "of " + logic.length + " logic cells", "data-cl-filter='usable'") +
    tile("Never used", esc(String(ex.length)), esc(pdkEx + " by the PDK" + (userEx ? " · " + userEx + " by you" : "")), "data-cl-jump='cl-rules'") +
    (types
      ? tile("Used by run", esc(String(types)) + " <small>types</small>", esc(localeNum(inst) + " instances · " + (u.tag || "")), "data-cl-filter='used'")
      : tile("Used by run", "–", state.designDir ? "Run the flow to see which cells it picked" : "Open a project to see usage", "data-go='setup'")) +
    "<button class='cl-tile' data-cl-jump='cl-macros' id='cl-tile-macros'><span class='cl-tile-k'>Macros</span><span class='cl-tile-v'>–</span><span class='cl-tile-s'>SRAMs and pre-built blocks</span></button>" +
    "</div>";
  document.querySelectorAll("[data-cl-filter]").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.clFilter === "used") { S.view.used = true; S.view.hideEx = false; }
    if (b.dataset.clFilter === "usable") { S.view.hideEx = true; S.view.used = false; if (S.view.cat === "physical") S.view.cat = ""; }
    saveView(); paintFilters(); paintList();
    document.getElementById("cl-library")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }));
}

export function setMacroTile(count, attention) {
  const t = document.getElementById("cl-tile-macros");
  if (!t) return;
  t.querySelector(".cl-tile-v").textContent = String(count);
  t.querySelector(".cl-tile-s").innerHTML = count
    ? (attention ? "<span class='cl-warn-t'>" + attention + " need" + (attention === 1 ? "s" : "") + " attention</span>" : "all wired up")
    : "SRAMs and pre-built blocks";
}

// ---------------------------------------------------------------- list -----
function paintLibraryShell() {
  const L = S.lib;
  const cats = M.CATEGORY_ORDER.filter((k) => S.fams.some((f) => f.cat === k));
  document.getElementById("cl-lib").innerHTML =
    "<div class='cl-browser'>" +
      "<div class='cl-listpane'>" +
        "<div class='cl-search'>" + icon("search", { size: 15 }) +
          "<input id='cl-q' type='search' autocomplete='off' spellcheck='false' placeholder='Search " + L.cells.length + " cells: a21oi, flip-flop, mux, xor…' value='" + esc(S.view.q) + "'>" +
          "<kbd>/</kbd></div>" +
        "<div class='cl-cats' role='tablist' aria-label='Cell kind'>" +
          "<button class='cl-cat' data-cat='' role='tab'>All</button>" +
          cats.map((k) => "<button class='cl-cat' data-cat='" + k + "' role='tab' title='" + esc(M.CATEGORY_TIPS[k] || "") + "'>" +
            esc(L.categories[k] || k) + " <span>" + S.fams.filter((f) => f.cat === k).length + "</span></button>").join("") +
        "</div>" +
        "<div class='cl-opts'>" +
          "<label class='cl-chk'><input type='checkbox' id='cl-used'> Used in the run</label>" +
          "<label class='cl-chk'><input type='checkbox' id='cl-hideex'> Hide cells the flow won't use</label>" +
          "<span class='bar-spacer'></span>" +
          "<label class='cl-sort'>Sort <select id='cl-sort'><option value='name'>Name</option><option value='area'>Smallest</option>" +
            "<option value='speed'>Fastest</option><option value='usage'>Most used</option></select></label>" +
        "</div>" +
        "<div class='cl-count muted' id='cl-count'></div>" +
        "<div class='cl-list' id='cl-list' tabindex='0' role='listbox' aria-label='Cell families'></div>" +
      "</div>" +
      "<div class='cl-detail' id='cl-detail' aria-live='polite'></div>" +
    "</div>";
  const q = document.getElementById("cl-q");
  let t = null;
  q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(() => { S.view.q = q.value; paintList(); }, 90); });
  q.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); moveSel(1); document.getElementById("cl-list").focus(); }
    if (e.key === "Enter") { const first = document.querySelector("#cl-list .cl-fam"); if (first) first.click(); }
    if (e.key === "Escape" && q.value) { q.value = ""; S.view.q = ""; paintList(); }
  });
  document.querySelector(".cl-cats").addEventListener("click", (e) => {
    const b = e.target.closest(".cl-cat");
    if (!b) return;
    S.view.cat = b.dataset.cat; saveView(); paintFilters(); paintList();
  });
  document.getElementById("cl-used").addEventListener("change", (e) => { S.view.used = e.target.checked; saveView(); paintList(); });
  document.getElementById("cl-hideex").addEventListener("change", (e) => { S.view.hideEx = e.target.checked; saveView(); paintList(); });
  document.getElementById("cl-sort").addEventListener("change", (e) => { S.view.sort = e.target.value; saveView(); paintList(); });
  const list = document.getElementById("cl-list");
  list.addEventListener("click", (e) => {
    const d = e.target.closest("[data-cell]");
    if (d) { select(d.dataset.cell); return; }
    const f = e.target.closest(".cl-fam");
    if (f) select(f.dataset.first);
  });
  list.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); moveSel(e.key === "ArrowDown" ? 1 : -1); }
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); moveDrive(e.key === "ArrowRight" ? 1 : -1); }
  });
  paintFilters();
}

function paintFilters() {
  document.querySelectorAll(".cl-cat").forEach((b) => b.classList.toggle("is-on", b.dataset.cat === (S.view.cat || "")));
  const u = document.getElementById("cl-used"); if (u) { u.checked = !!S.view.used; u.disabled = !(S.lib && S.lib.cells.some((c) => c.used)); }
  const h = document.getElementById("cl-hideex"); if (h) h.checked = !!S.view.hideEx;
  const s = document.getElementById("cl-sort"); if (s) s.value = S.view.sort || "name";
}

function visibleFamilies() {
  const q = (S.view.q || "").trim().toLowerCase();
  const terms = q.split(/\s+/).filter(Boolean);
  let fams = S.fams.filter((f) => (!S.view.cat || f.cat === S.view.cat) && terms.every((t) => f.search.includes(t)));
  fams = fams.map((f) => {
    let cells = f.cells;
    if (S.view.hideEx) cells = cells.filter((c) => !isExcluded(c) && !c.dont_use);
    if (S.view.used) cells = cells.filter((c) => c.used);
    return cells.length ? Object.assign({}, f, { shown: cells }) : null;
  }).filter(Boolean);
  const first = (f) => f.shown[0];
  const sorters = {
    name: (a, b) => a.fam.localeCompare(b.fam),
    area: (a, b) => (first(a).area || 1e9) - (first(b).area || 1e9),
    speed: (a, b) => (minDelay(a) || 1e9) - (minDelay(b) || 1e9),
    usage: (a, b) => (b.used - a.used) || a.fam.localeCompare(b.fam),
  };
  // an exact cell-name search floats its family to the top
  fams.sort(sorters[S.view.sort] || sorters.name);
  if (q) {
    const exact = fams.findIndex((f) => f.fam.toLowerCase() === q || f.cells.some((c) => c.cell.toLowerCase() === q));
    if (exact > 0) fams.unshift(fams.splice(exact, 1)[0]);
  }
  return fams;
}
function minDelay(f) { const ds = f.shown.map((c) => c.delay).filter(Number.isFinite); return ds.length ? Math.min(...ds) : null; }

function paintList() {
  const list = document.getElementById("cl-list");
  if (!list || !S.lib) return;
  const fams = visibleFamilies();
  const ncells = fams.reduce((s, f) => s + f.shown.length, 0);
  document.getElementById("cl-count").textContent = fams.length
    ? fams.length + " famil" + (fams.length === 1 ? "y" : "ies") + " · " + ncells + " cell" + (ncells === 1 ? "" : "s")
    : "";
  if (!fams.length) {
    list.innerHTML = "<div class='cl-none'>No cells match" + (S.view.q ? " “" + esc(S.view.q) + "”" : "") + ". " +
      "<button class='btn btn-ghost btn-sm' id='cl-clear'>Clear filters</button></div>";
    list.querySelector("#cl-clear").addEventListener("click", () => {
      S.view = Object.assign(S.view, { q: "", cat: "", used: false, hideEx: false });
      document.getElementById("cl-q").value = ""; saveView(); paintFilters(); paintList();
    });
    return;
  }
  const maxUse = Math.max(1, ...fams.map((f) => f.used));
  list.innerHTML = fams.map((f) => {
    const selFam = S.sel && f.cells.some((c) => c.cell === S.sel);
    const drives = f.shown.map((c) => {
      const cls = ["cl-dr"];
      if (c.used) cls.push("is-used");
      if (isExcluded(c) || c.dont_use) cls.push("is-ex");
      if (c.cell === S.sel) cls.push("is-sel");
      const tip = c.cell + (c.used ? "\nUsed " + c.used + "× in " + ((S.lib.usage || {}).tag || "the run") : "") +
        (isExcluded(c) ? "\nThe flow won't use it (" + exWhy(c).join(", ") + ")" : "") +
        (Number.isFinite(c.area) ? "\n" + M.fmtArea(c.area) : "");
      return "<span class='" + cls.join(" ") + "' data-cell='" + esc(c.cell) + "' title='" + esc(tip) + "'>" + esc(c.drive || "·") + "</span>";
    }).join("");
    const bar = f.used ? "<span class='cl-usebar' style='--w:" + Math.max(4, Math.round((f.used / maxUse) * 100)) + "%' title='" + f.used + " instances in " + esc((S.lib.usage || {}).tag || "the run") + "'></span>" : "";
    return "<div class='cl-fam" + (selFam ? " is-sel" : "") + "' role='option' aria-selected='" + (selFam ? "true" : "false") + "' data-first='" + esc(pickDrive({ cells: f.shown }).cell) + "'>" +
      "<span class='cl-fam-top'><span class='cl-fam-name'>" + esc(f.fam) + "</span>" +
        (f.lib ? "<span class='cl-fam-lib' title='From the sister library " + esc(f.lib) + "'>" + esc(f.lib.replace(/^[a-z0-9]+_/, "")) + "</span>" : "") +
        "<span class='cl-drives'>" + drives + "</span></span>" +
      "<span class='cl-fam-desc" + (f.descGenerated ? " is-gen" : "") + "'>" + esc(f.desc) + "</span>" + bar +
      "</div>";
  }).join("");
}

function exWhy(c) {
  const e = c.excluded || {};
  const out = [];
  if (e.synth) out.push("PDK synthesis list");
  if (e.pnr) out.push("PDK placement list");
  if (e.user) out.push("your EXTRA_EXCLUDED_CELLS");
  if (e.swap) out.push("swapped for your custom cell");
  return out;
}

function moveSel(dir) {
  const rows = [...document.querySelectorAll("#cl-list .cl-fam")];
  if (!rows.length) return;
  let i = rows.findIndex((r) => r.classList.contains("is-sel"));
  i = i < 0 ? 0 : Math.max(0, Math.min(rows.length - 1, i + dir));
  select(rows[i].dataset.first);
  rows[i].scrollIntoView({ block: "nearest" });
}
function moveDrive(dir) {
  const row = document.querySelector("#cl-list .cl-fam.is-sel");
  if (!row) return;
  const ds = [...row.querySelectorAll("[data-cell]")];
  const i = ds.findIndex((d) => d.dataset.cell === S.sel);
  const n = ds[Math.max(0, Math.min(ds.length - 1, i + dir))];
  if (n) select(n.dataset.cell);
}

// ---------------------------------------------------------------- detail ---
function select(name, { scroll = false } = {}) {
  if (!S.byName.has(name)) return;
  S.sel = name;
  document.querySelectorAll("#cl-list .cl-fam").forEach((r) => {
    const on = [...r.querySelectorAll("[data-cell]")].some((d) => d.dataset.cell === name);
    r.classList.toggle("is-sel", on);
    r.setAttribute("aria-selected", on ? "true" : "false");
    r.querySelectorAll("[data-cell]").forEach((d) => d.classList.toggle("is-sel", d.dataset.cell === name));
    if (on && scroll) r.scrollIntoView({ block: "nearest" });
  });
  if (scroll && !document.querySelector("#cl-list .cl-fam.is-sel")) {
    // filtered out: clear filters so the cell shows
    S.view = Object.assign(S.view, { q: "", cat: "", used: false, hideEx: false });
    const q = document.getElementById("cl-q"); if (q) q.value = "";
    paintFilters(); paintList(); return select(name, { scroll });
  }
  paintDetail(name);
}

function familyOf(name) {
  const c = S.byName.get(name);
  return S.fams.find((f) => f.cells.includes(c));
}

async function paintDetail(name) {
  const host = document.getElementById("cl-detail");
  if (!host) return;
  const c = S.byName.get(name);
  const fam = familyOf(name);
  // Two stacks, not rows: each card is as tall as what it holds, so a short
  // card never sits in a box stretched to its neighbour's height.
  host.innerHTML = headHtml(c, fam) + "<div class='cl-cards'>" +
    "<div class='cl-col'>" +
    "<section class='cl-card' id='cl-c-fn'>" + functionHtml(c) + "</section>" +
    "<section class='cl-card' id='cl-c-drive'><div class='cl-card-h'>Drive strengths</div><div class='cl-lay-skel short'></div></section>" +
    "</div><div class='cl-col'>" +
    "<section class='cl-card' id='cl-c-layout'><div class='cl-card-h'>Layout <span class='muted'>loading…</span></div><div class='cl-lay-skel'></div></section>" +
    "<section class='cl-card' id='cl-c-flow'>" + flowHtml(c) + "</section>" +
    "</div>" +
    "<section class='cl-card cl-card-pro' id='cl-c-pins'><div class='cl-card-h'>Pins &amp; timing arcs</div><div class='cl-lay-skel short'></div></section>" +
    "</div>";
  wireDetail(host, c);
  const key = S.pdk + "|" + S.scl + "|" + name;
  const [det, lay] = await Promise.all([
    S.detail.get(key) || api.cellDetail(S.pdk, S.scl, name).catch((e) => ({ ok: false, error: e.message })),
    S.layout.get(key) || api.cellLayout(S.pdk, S.scl, name).catch((e) => ({ ok: false, error: e.message })),
  ]);
  if (S.sel !== name) return;
  if (det && det.ok) S.detail.set(key, det);
  if (lay && lay.ok) S.layout.set(key, lay);
  const lc = document.getElementById("cl-c-layout");
  if (lc) { lc.innerHTML = layoutHtml(c, lay, det); wireLayout(lc); }
  const dc = document.getElementById("cl-c-drive");
  if (dc) { dc.innerHTML = driveHtml(c, fam, det); wireDrive(dc); }
  const pc = document.getElementById("cl-c-pins");
  if (pc) { pc.innerHTML = pinsHtml(c, det); wirePins(pc, det); }
  const fc = document.getElementById("cl-c-fn");
  if (fc && det && det.ok && det.liberty) { fc.innerHTML = functionHtml(c, det); }
}

function headHtml(c, fam) {
  const L = S.lib;
  const chips = [];
  if (c.used) {
    const total = L.cells.reduce((s, x) => s + (x.used || 0), 0);
    chips.push("<span class='cl-chip is-used'>" + icon("check", { size: 12 }) + " Used " + localeNum(c.used) + "× in " + esc((S.lib.usage || {}).tag || "the run") +
      (total ? " <span>(" + (100 * c.used / total).toFixed(1) + "% of cells)</span>" : "") + "</span>");
  }
  if (c.excluded.synth || c.excluded.pnr) chips.push("<span class='cl-chip is-ex'>" + icon("ban", { size: 12 }) + " PDK keeps it out of " + (c.excluded.pnr ? "synthesis and placement" : "synthesis") + "</span>");
  if (c.excluded.user) chips.push("<span class='cl-chip is-ex'>" + icon("ban", { size: 12 }) + " Excluded by you</span>");
  if (c.excluded.swap) chips.push("<span class='cl-chip is-ex'>" + icon("ban", { size: 12 }) + " Swapped for your custom cell</span>");
  if (c.dont_use) chips.push("<span class='cl-chip is-ex'>Liberty marks it dont_use</span>");
  for (const r of c.roles || []) chips.push("<span class='cl-chip is-role' title='The flow places this cell by itself'>" + icon("tools", { size: 12 }) + " Flow inserts it: " + esc(r) + "</span>");
  const drives = fam && fam.cells.length > 1
    ? "<div class='cl-drivetabs' role='tablist' aria-label='Drive strength'>" + fam.cells.map((x) =>
        "<button class='cl-dt" + (x.cell === c.cell ? " is-on" : "") + (isExcluded(x) ? " is-ex" : "") + "' data-pick='" + esc(x.cell) + "' role='tab'>" +
        "<b>" + esc(x.drive || "·") + "</b>" + (x.used ? "<i>" + x.used + "×</i>" : "") + "</button>").join("") +
      "<span class='cl-dt-help has-tip' title='The number after the name is the drive strength: how hard the output pushes. Bigger drives are faster into heavy loads but are larger, load their own inputs more and leak more. Synthesis and the resizer choose per instance.'>drive</span></div>"
    : "";
  const desc = fam && fam.desc ? "<p class='cl-desc" + (fam.descGenerated ? " is-gen" : "") + "'>" + esc(fam.desc) + "</p>" : "";
  return "<header class='cl-head'>" +
    "<div class='an-eyebrow'>" + esc(L.categories[c.category] || c.category) + " · " + esc(c.family) + " family</div>" +
    "<div class='cl-title-row'><h3 class='cl-title'>" + esc(c.cell) + "</h3>" +
      "<button class='btn btn-ghost btn-sm cl-copy' data-copy='" + esc(c.cell) + "' title='Copy the cell name'>" + icon("file", { size: 13 }) + " Copy</button></div>" +
    desc +
    (chips.length ? "<div class='cl-chips'>" + chips.join("") + "</div>" : "") +
    drives +
    "<dl class='cl-facts'>" +
      fact("Area", M.fmtArea(c.area), "Cell footprint from the Liberty file") +
      fact("Size", Number.isFinite(c.w) ? c.w.toFixed(2) + " × " + c.h.toFixed(2) + " µm" : "–", "Width × height from the LEF") +
      fact("Width", c.sites ? c.sites + " sites" : "–", "Placement sites wide (" + esc(L.site.name || "site") + (L.site.w ? " = " + L.site.w + " µm" : "") + ")") +
      fact("Delay @ FO4", c.delay ? M.fmtPs(c.delay) : "–", "Slowest arc driving four times the smallest inverter's input (" + M.fmtCap(L.fo4.load_ff) + "), " + (L.corner || "typical") + " corner") +
      fact("Input cap", c.in_cap ? M.fmtCap(c.in_cap) : "–", "Largest input pin capacitance: what this cell costs whoever drives it") +
      fact("Leakage", c.leakage != null ? M.fmtPower(c.leakage) : "–", "Static power, averaged over input states") +
    "</dl></header>";
}
function fact(k, v, tip) {
  return "<div class='cl-fact' title='" + esc(tip) + "'><dt>" + esc(k) + "</dt><dd>" + esc(v) + "</dd></div>";
}

function functionHtml(c, det) {
  const lib = det && det.liberty;
  const outs = (lib ? lib.pins.filter((p) => p.dir === "output") : (c.outputs || []).map((o) => ({ name: o.name, function: o.function })));
  const ins = lib ? lib.pins.filter((p) => p.dir === "input").map((p) => p.name) : (c.inputs || []);
  const seq = (lib && lib.seq) || c.seq;
  let body = "";
  if (!outs.length) {
    const why = {
      physical: "This cell has no logic. The flow drops it into the rows by itself: fill and decap close the gaps, taps bias the wells, end caps finish each row and diodes fix antenna violations. You never instantiate it.",
    }[c.category] || "No output pins in the Liberty file.";
    body = "<p class='cl-p'>" + esc(why) + "</p>";
  } else if (seq) {
    const lines = M.seqDescription(seq, outs);
    body = "<ul class='cl-seq'>" + lines.map((l) => "<li>" + esc(l) + "</li>").join("") + "</ul>" +
      "<div class='cl-pinline'>" + pinChips(ins, outs) + "</div>";
  } else if (lib && lib.clock_gate) {
    body = "<p class='cl-p'>An integrated clock gate: the output clock runs only while the enable is high, and the enable is latched so the gated clock never glitches. CTS and clock-gating passes insert these.</p><div class='cl-pinline'>" + pinChips(ins, outs) + "</div>";
  } else {
    // Prefer the PDK's readable header formula; Liberty states the same
    // function flattened to sum-of-products (a21oi as (!A1&!B1)|(!A2&!B1)).
    const hdr = M.headerFormulas(c.formula);
    const parsed = outs.map((o) => ({ name: o.name, ast: hdr[o.name] || M.parseFunction(o.function), z: o.three_state ? M.parseFunction(o.three_state) : null, raw: o.function }));
    const main = parsed[0];
    let eq = parsed.map((p) => "<div class='cl-formula'><code>" + esc(p.name) + " = " + esc(p.ast ? M.astText(p.ast) : (p.raw || "?")) + "</code>" +
      (p.z ? "<span class='muted'> · floats (Z) when " + esc(M.astWords(p.z)) + "</span>" : "") + "</div>").join("");
    let gd = "";
    if (main.ast) {
      eq += "<p class='cl-words'>" + esc(main.name) + " = " + esc(M.astWords(main.ast)) + " <span class='cl-class'>" + esc(M.classify(main.ast)) + "</span></p>";
      const svg = parsed.length === 1 ? M.gateDiagram(main.ast, main.name) : "";
      // --gw: the drawing's own width, so it can grow to fill the card without
      // ballooning a two-input gate.
      const gw = svg ? +(/viewBox='0 0 ([\d.]+)/.exec(svg) || [0, 300])[1] : 0;
      if (svg) gd = "<div class='cl-gd' style='--gw:" + gw + "'>" + svg + "</div>";
    }
    const vars = ins.length ? ins : [...new Set(parsed.flatMap((p) => [...M.astVars(p.ast)]))];
    const tt = parsed.every((p) => p.ast) ? M.truthTable(vars, parsed) : null;
    // A short truth table (up to 8 rows) stands open beside the drawing; a long
    // one folds under it, and the drawing gets the room.
    const small = !!tt && tt.length <= 8;
    let ttHtml = "";
    if (tt && vars.length) {
      ttHtml = "<details class='cl-tt'" + (small ? " open" : "") + "><summary>Truth table <span class='muted'>" + tt.length + " rows</span></summary>" +
        "<div class='cl-tt-wrap'><table><thead><tr>" + vars.map((v) => "<th>" + esc(v) + "</th>").join("") +
        "<th class='cl-tt-sep'></th>" + parsed.map((p) => "<th class='cl-tt-o'>" + esc(p.name) + "</th>").join("") + "</tr></thead><tbody>" +
        tt.map((r) => "<tr>" + r.ins.map((v) => "<td>" + v + "</td>").join("") + "<td class='cl-tt-sep'></td>" +
          r.outs.map((v) => "<td class='cl-tt-o v" + v + "'>" + v + "</td>").join("") + "</tr>").join("") +
        "</tbody></table></div></details>";
    } else if (vars.length > 6) {
      ttHtml = "<p class='muted cl-p'>" + vars.length + " inputs: a truth table would have " + (1 << vars.length) + " rows, so it is left out.</p>";
    }
    body += "<div class='cl-fn-eq'>" + eq + "</div>" +
      (gd || ttHtml ? "<div class='cl-fn-vis" + (gd && small && ttHtml ? " is-pair" : "") + "'>" + gd + ttHtml + "</div>" : "");
  }
  return "<div class='cl-card-h'>What it does</div>" + body;
}

function pinChips(ins, outs) {
  return ins.map((p) => "<span class='cl-pin in'>" + esc(p) + "</span>").join("") + "<span class='cl-arrow'>→</span>" +
    outs.map((p) => "<span class='cl-pin out'>" + esc(p.name) + "</span>").join("");
}

// ---------------------------------------------------------------- layout ---
function layoutHtml(c, lay, det) {
  const head = "<div class='cl-card-h'>Layout <span class='muted'>" +
    (lay && lay.ok ? esc(lay.gds) + " · drawn from the PDK's GDS" : "") + "</span></div>";
  if (!lay || !lay.ok) {
    const lef = det && det.lef;
    if (lef && lef.w) return head + footprintSvg(lef) + "<p class='muted cl-p'>" + esc((lay && lay.error) || "No GDS for this cell") + ". Showing the LEF abstract instead (outline and pins).</p>";
    return head + "<p class='muted cl-p'>" + esc((lay && lay.error) || "No layout available.") + "</p>";
  }
  const [x0, y0, x1, y1] = lay.bbox;
  const w = x1 - x0, h = y1 - y0;
  const pad = Math.max(w, h) * 0.04;
  const area = Math.max(1e-9, w * h);
  const groups = lay.layers.map((L) => {
    const a = L.polys.reduce((s, p) => s + polyArea(p), 0);
    const blanket = a / area > 0.45;   // wells and implants cover the cell: draw them faint
    const d = L.polys.map((p) => { let s = "M" + p[0] + " " + p[1]; for (let k = 2; k < p.length; k += 2) s += "L" + p[k] + " " + p[k + 1]; return s + "Z"; }).join("");
    const off = S.hidden.has(L.name) ? " is-off" : "";
    return "<path class='cl-ly" + (blanket ? " is-blanket" : "") + off + "' data-ly='" + esc(L.name) + "' d='" + d +
      "' style='--f:" + esc(L.fill) + ";--s:" + esc(L.frame) + "'/>";
  }).join("");
  const fs = Math.max(h / 16, 0.12);
  // One label per pin: the same text sits on several layers (li1, met1, pin
  // purposes) and the cell's own name is stamped in the corner.
  const seen = [];
  const near = Math.max(w, h) * 0.4;
  const wanted = (lay.labels || []).filter((l) => {
    // pin names only: drop the cell-name stamp and annotations ("Metric 1.00")
    if (/\s/.test(l.text) || l.text.length > 16 || (l.text.length > 4 && c.cell.includes(l.text))) return false;
    if (seen.some((s) => s.text === l.text && Math.hypot(s.x - l.x, s.y - l.y) < near)) return false;
    seen.push(l);
    return true;
  });
  // Different pins can sit on the same spot (VPWR/VPB on the top rail, VGND/VNB
  // on the bottom one): slide each label sideways until it clears the ones
  // already placed, so the names never print on top of each other.
  const halfW = (t) => t.length * fs * 0.34 + fs * 0.15;
  const placed = [];
  const labels = wanted.slice().sort((a, b) => (b.y - a.y) || (a.x - b.x)).map((l) => {
    const hw = halfW(l.text);
    const lo = Math.min(x0 + hw, (x0 + x1) / 2), hi = Math.max(x1 - hw, (x0 + x1) / 2);
    const clash = (x) => placed.some((p) => Math.abs(p.x - x) < p.hw + hw && Math.abs(p.y - l.y) < fs * 1.15);
    let x = Math.min(hi, Math.max(lo, l.x));
    for (let k = 1; clash(x) && k <= 80; k++) {
      const step = fs * 0.4 * Math.ceil(k / 2) * (k % 2 ? 1 : -1);
      const t = Math.min(hi, Math.max(lo, l.x + step));
      if (!clash(t)) { x = t; break; }
    }
    placed.push({ x, y: l.y, hw });
    return "<text class='cl-lbl' x='" + x.toFixed(3) + "' y='" + (-l.y) + "' font-size='" + fs.toFixed(3) + "'>" + esc(l.text) + "</text>";
  }).join("");
  const svg = "<div class='cl-lay'><svg viewBox='" + (x0 - pad) + " " + (-(y1 + pad)) + " " + (w + 2 * pad) + " " + (h + 2 * pad) + "' preserveAspectRatio='xMidYMid meet' role='img' aria-label='Layout of " + esc(c.cell) + "'>" +
    "<g transform='scale(1,-1)'>" + groups + "</g><g class='cl-lbls'>" + labels + "</g></svg></div>";
  const legend = "<div class='cl-legend'>" + lay.layers.map((L) =>
    "<button class='cl-lg" + (S.hidden.has(L.name) ? " is-off" : "") + "' data-ly='" + esc(L.name) + "' title='Show or hide " + esc(L.name) + "'><i style='--f:" + esc(L.fill) + "'></i>" + esc(L.name.replace(/\.drawing$/, "")) + "</button>").join("") +
    "<button class='cl-lg cl-lg-lbl' data-lbls='1'>labels</button></div>";
  const dims = Number.isFinite(c.w)
    ? "<p class='cl-dims'><b>" + c.w.toFixed(2) + " × " + c.h.toFixed(2) + " µm</b>" + (c.sites ? " · " + c.sites + " sites wide" : "") +
      " · every cell in the library is " + c.h.toFixed(2) + " µm tall, so cells abut in rows and share the power rails along the top and bottom edges.</p>"
    : "";
  return head + svg + legend + dims;
}

function polyArea(p) {
  let a = 0;
  for (let k = 0; k < p.length; k += 2) {
    const x1 = p[k], y1 = p[k + 1], x2 = p[(k + 2) % p.length], y2 = p[(k + 3) % p.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

function footprintSvg(lef) {
  const w = lef.w, h = lef.h, pad = Math.max(w, h) * 0.05;
  const pins = (lef.pins || []).flatMap((p) => (p.rects || []).map((r) =>
    "<rect class='cl-fp-pin " + esc(p.use || "") + "' x='" + r[1] + "' y='" + (-r[4]) + "' width='" + (r[3] - r[1]) + "' height='" + (r[4] - r[2]) + "'><title>" + esc(p.name + " (" + r[0] + ")") + "</title></rect>")).join("");
  return "<div class='cl-lay'><svg viewBox='" + (-pad) + " " + (-(h + pad)) + " " + (w + 2 * pad) + " " + (h + 2 * pad) + "'>" +
    "<rect class='cl-fp-box' x='0' y='" + (-h) + "' width='" + w + "' height='" + h + "'/>" + pins + "</svg></div>";
}

function wireLayout(card) {
  card.addEventListener("click", (e) => {
    const b = e.target.closest(".cl-lg");
    if (!b) return;
    if (b.dataset.lbls) { b.classList.toggle("is-off"); card.querySelector(".cl-lbls")?.classList.toggle("is-off"); return; }
    const n = b.dataset.ly;
    if (S.hidden.has(n)) S.hidden.delete(n); else S.hidden.add(n);
    b.classList.toggle("is-off");
    card.querySelectorAll("[data-ly='" + CSS.escape(n) + "']").forEach((p) => p.classList.toggle("is-off", S.hidden.has(n)));
  });
}

// ---------------------------------------------------------------- drives ---
function driveHtml(c, fam, det) {
  const cells = fam ? fam.cells : [c];
  const head = "<div class='cl-card-h'>Drive strengths <span class='muted'>" + esc((S.lib.corner || "").replace(/_/g, " ")) + "</span></div>";
  const rows = cells.map((x) => "<tr class='" + (x.cell === c.cell ? "is-sel" : "") + (isExcluded(x) ? " is-ex" : "") + "' data-pick='" + esc(x.cell) + "'>" +
    "<td class='mono' title='" + esc(isExcluded(x) ? "The flow won't use it: " + exWhy(x).join(", ") : x.cell) + "'>" + esc(x.drive || "·") + "</td><td>" + M.fmtArea(x.area) + "</td>" +
    "<td>" + (x.delay ? M.fmtPs(x.delay) : "–") + "</td><td>" + (x.in_cap ? M.fmtCap(x.in_cap) : "–") + "</td>" +
    "<td>" + (x.leakage != null ? M.fmtPower(x.leakage) : "–") + "</td><td>" + (x.used ? localeNum(x.used) : "–") + "</td></tr>").join("");
  const table = "<div class='cl-tblwrap'><table class='cl-tbl'><thead><tr><th>Drive</th><th>Area</th><th title='At a fan-out-of-4 load'>Delay</th><th>In cap</th><th>Leakage</th><th>Used</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
  const cv = det && det.ok && det.curves;
  let chart = "";
  if (cv && cv.series && cv.series.length && cv.loads_ff && cv.loads_ff.length) {
    chart = "<div class='cl-chart' data-chart></div><p class='cl-foot'>Delay from " + esc(cv.series[0].from) + " to " + esc(cv.series[0].to) +
      " as the load grows, input slew " + M.fmtPs(cv.slew_ps) + ". The dashed line is a fan-out-of-4 load (" + M.fmtCap(cv.fo4_ff) + "). " +
      (cells.length > 1 ? "Where the lines cross, the bigger drive starts paying for its extra area." : "") + "</p>";
  }
  return head + chart + table;
}

function wireDrive(card) {
  card.addEventListener("click", (e) => {
    const r = e.target.closest("[data-pick]");
    if (r) select(r.dataset.pick);
  });
  const host = card.querySelector("[data-chart]");
  if (!host) return;
  const key = S.pdk + "|" + S.scl + "|" + S.sel;
  const det = S.detail.get(key);
  if (!det) return;
  drawCurves(host, det.curves);
}

const SERIES = ["s1", "s2", "s3", "s4", "s5", "s6"];
function drawCurves(host, cv) {
  const W = Math.max(300, Math.round(host.clientWidth || 520)), H = 210, L = 52, R = 14, T = 12, B = 34;
  const xs = cv.loads_ff;
  const all = cv.series.flatMap((s) => s.delay.filter(Number.isFinite));
  if (!all.length) { host.innerHTML = ""; return; }
  const hiY = Math.max(...all) * 1.05, loY = 0;
  const hiX = xs[xs.length - 1] || 1;
  const X = (v) => L + (v / hiX) * (W - L - R);
  const Y = (v) => T + (1 - (v - loY) / (hiY - loY)) * (H - T - B);
  const ticks = (hi, n) => { const step = niceStep(hi / n); const out = []; for (let v = 0; v <= hi + 1e-9; v += step) out.push(v); return out; };
  let g = "";
  for (const t of ticks(hiY, 4)) g += "<line class='cl-grid' x1='" + L + "' x2='" + (W - R) + "' y1='" + Y(t) + "' y2='" + Y(t) + "'/><text class='cl-yt' x='" + (L - 6) + "' y='" + (Y(t) + 4) + "' text-anchor='end'>" + esc(M.fmtPs(t)) + "</text>";
  for (const t of ticks(hiX, 5)) g += "<text class='cl-xt' x='" + X(t) + "' y='" + (H - B + 16) + "' text-anchor='middle'>" + esc(t.toFixed(t < 10 ? 1 : 0)) + "</text>";
  g += "<text class='cl-xt' x='" + (W - R) + "' y='" + (H - 4) + "' text-anchor='end'>load (fF)</text>";
  if (cv.fo4_ff && cv.fo4_ff < hiX) g += "<line class='cl-fo4' x1='" + X(cv.fo4_ff) + "' x2='" + X(cv.fo4_ff) + "' y1='" + T + "' y2='" + (H - B) + "'/><text class='cl-fo4t' x='" + (X(cv.fo4_ff) + 4) + "' y='" + (T + 10) + "'>FO4</text>";
  const lines = cv.series.map((s, k) => {
    let d = "", pen = false;
    s.delay.forEach((v, i) => { if (!Number.isFinite(v)) { pen = false; return; } d += (pen ? "L" : "M") + X(xs[i]).toFixed(1) + " " + Y(v).toFixed(1); pen = true; });
    const sel = s.cell === S.sel;
    return "<path class='cl-line " + SERIES[k % SERIES.length] + (sel ? " is-sel" : "") + "' d='" + d + "'/>" +
      "<text class='cl-lend " + SERIES[k % SERIES.length] + "' x='" + (W - R - 2) + "' y='" + (Y(s.delay[s.delay.length - 1]) - 4).toFixed(1) + "' text-anchor='end'>_" + esc(s.drive || "?") + "</text>";
  }).join("");
  host.innerHTML = "<svg width='" + W + "' height='" + H + "' viewBox='0 0 " + W + " " + H + "' role='img' aria-label='Delay versus load per drive strength'>" + g + lines +
    "<line class='cl-guide' y1='" + T + "' y2='" + (H - B) + "' x1='-10' x2='-10'/></svg><div class='cl-tip' hidden></div>";
  const svg = host.querySelector("svg"), guide = host.querySelector(".cl-guide"), tip = host.querySelector(".cl-tip");
  svg.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect();
    const px = (e.clientX - r.left) * (W / (r.width || W));   // client px → chart units (UI zoom)
    if (px < L || px > W - R) { tip.hidden = true; guide.setAttribute("x1", -10); guide.setAttribute("x2", -10); return; }
    const load = ((px - L) / (W - L - R)) * hiX;
    let i = 0; let best = Infinity;
    xs.forEach((x, k) => { const dd = Math.abs(x - load); if (dd < best) { best = dd; i = k; } });
    guide.setAttribute("x1", X(xs[i])); guide.setAttribute("x2", X(xs[i]));
    tip.hidden = false;
    tip.innerHTML = "<b>" + M.fmtCap(xs[i]) + "</b>" + cv.series.map((s, k) => "<div><i class='" + SERIES[k % SERIES.length] + "'></i>_" + esc(s.drive) + " " + M.fmtPs(s.delay[i]) + "</div>").join("");
    tip.style.left = Math.min(W - 130, X(xs[i]) + 10) + "px";
  });
  svg.addEventListener("mouseleave", () => { tip.hidden = true; guide.setAttribute("x1", -10); guide.setAttribute("x2", -10); });
}
function niceStep(raw) {
  const p = Math.pow(10, Math.floor(Math.log10(raw || 1)));
  const f = raw / p;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p;
}

// ---------------------------------------------------------------- pins -----
function pinsHtml(c, det) {
  if (!det || !det.ok || !det.liberty) return "<div class='cl-card-h'>Pins &amp; timing arcs</div><p class='muted cl-p'>" + esc((det && det.error) || "No Liberty data for this cell.") + "</p>";
  const lib = det.liberty;
  const fo4 = S.lib.fo4 || {};
  const pins = lib.pins.map((p) => "<tr><td class='mono'>" + esc(p.name) + "</td><td>" + esc(p.dir) + (p.clock ? " · clock" : "") + "</td>" +
    "<td>" + (p.cap != null ? M.fmtCap(p.cap) : "–") + "</td><td class='mono cl-fnc'>" + esc(p.function || "") + "</td></tr>").join("") +
    (lib.pg_pins || []).map((p) => "<tr class='is-pg'><td class='mono'>" + esc(p.name) + "</td><td>" + esc((p.type || "").replace(/_/g, " ")) + "</td><td>–</td><td></td></tr>").join("");
  const arcs = (det.arcs || []).map((a, k) => {
    const at = (t) => t ? lookup(t, fo4.slew_ps, fo4.load_ff) : null;
    const isC = /setup|hold|recovery|removal|width|period/.test(a.type || "");
    const r = isC ? at(a.rise_constraint) : at(a.cell_rise);
    const f = isC ? at(a.fall_constraint) : at(a.cell_fall);
    return "<tr data-arc='" + k + "'><td class='mono'>" + esc(a.from) + " → " + esc(a.to) + "</td><td>" + esc((a.type || "combinational").replace(/_/g, " ")) +
      (a.sense ? " · " + esc(a.sense.replace(/_/g, " ")) : "") + (a.when ? "<span class='muted'> when " + esc(a.when) + "</span>" : "") + "</td>" +
      "<td>" + (r != null ? M.fmtPs(r) : "–") + "</td><td>" + (f != null ? M.fmtPs(f) : "–") + "</td>" +
      "<td><button class='btn btn-ghost btn-xs' data-table='" + k + "'>Table</button></td></tr>";
  }).join("");
  return "<div class='cl-card-h'>Pins &amp; timing arcs <span class='muted'>" + esc(det.corner || "") + "</span></div>" +
    "<div class='cl-tblwrap'><table class='cl-tbl'><thead><tr><th>Pin</th><th>Direction</th><th>Cap</th><th>Function</th></tr></thead><tbody>" + pins + "</tbody></table></div>" +
    (arcs ? "<div class='cl-tblwrap'><table class='cl-tbl'><thead><tr><th>Arc</th><th>Kind</th><th title='At the FO4 operating point'>Rise</th><th>Fall</th><th></th></tr></thead><tbody>" + arcs + "</tbody></table></div><div id='cl-nldm'></div>" : "") +
    "<div class='cl-pro-acts'><button class='btn btn-ghost btn-sm' id='cl-copy-inst'>" + icon("code", { size: 13 }) + " Copy an instance</button>" +
    "<span class='muted'>for hand-placed cells (clock gates, delay lines, sync flops). Synthesis keeps a hand-instantiated cell as-is.</span></div>";
}

function lookup(t, slew, load) {
  if (!t || !t.values || !t.values.length) return null;
  const i1 = t.index_1, i2 = t.index_2, v = t.values;
  const interp = (xs, ys, x) => {
    if (xs.length < 2) return ys[0];
    let i = 0; while (i < xs.length - 2 && xs[i + 1] < x) i++;
    return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / ((xs[i + 1] - xs[i]) || 1);
  };
  if (!i2.length) return interp(i1, v.length === 1 ? v[0] : v.map((r) => r[0]), slew);
  const col = v.map((r) => interp(i2, r, load));
  return i1.length === col.length ? interp(i1, col, slew) : col[0];
}

function wirePins(card, det) {
  card.addEventListener("click", (e) => {
    const b = e.target.closest("[data-table]");
    if (b) {
      const a = det.arcs[+b.dataset.table];
      const host = card.querySelector("#cl-nldm");
      const t = a.cell_rise || a.rise_constraint || a.cell_fall || a.fall_constraint;
      if (!t) { host.innerHTML = "<p class='muted cl-p'>No table on this arc.</p>"; return; }
      const flat = t.values.flat();
      const lo = Math.min(...flat), hi = Math.max(...flat);
      const isC = !a.cell_rise && !a.cell_fall;
      host.innerHTML = "<div class='cl-nldm'><div class='cl-nldm-h'><b>" + esc(a.from + " → " + a.to) + "</b> " + (isC ? "rise constraint" : "cell rise delay") +
        " <span class='muted'>rows: input slew, columns: " + (isC ? "related pin slew" : "output load") + "</span><button class='btn btn-ghost btn-xs' data-close>Close</button></div>" +
        "<div class='cl-tblwrap'><table class='cl-heat'><thead><tr><th></th>" + t.index_2.map((x) => "<th>" + esc(isC ? M.fmtPs(x) : M.fmtCap(x)) + "</th>").join("") + "</tr></thead><tbody>" +
        t.values.map((row, i) => "<tr><th>" + esc(M.fmtPs(t.index_1[i])) + "</th>" + row.map((v) =>
          "<td style='--h:" + ((v - lo) / ((hi - lo) || 1)).toFixed(3) + "'>" + esc(M.fmtNum(v, 0)) + "</td>").join("") + "</tr>").join("") +
        "</tbody></table></div><p class='cl-foot'>Values in ps. STA interpolates between these points for every instance; outside the table it extrapolates, which is where library timing gets least trustworthy.</p></div>";
      host.querySelector("[data-close]").addEventListener("click", () => { host.innerHTML = ""; });
      return;
    }
    if (e.target.closest("#cl-copy-inst")) {
      const lib = det.liberty;
      const sig = lib.pins.filter((p) => p.dir !== "internal");
      const pg = lib.pg_pins || [];
      const inst = "u_" + (S.byName.get(S.sel)?.family || "cell");
      const w = Math.max(4, ...sig.concat(pg).map((p) => p.name.length));
      const lines = [S.sel + " " + inst + " ("];
      if (pg.length) {
        lines.push("`ifdef USE_POWER_PINS");
        pg.forEach((p) => lines.push("    ." + p.name.padEnd(w) + " (" + (p.type && p.type.includes("ground") || p.type === "pwell" ? S.lib.rules.gnd : S.lib.rules.vdd) + "),"));
        lines.push("`endif");
      }
      sig.forEach((p, k) => lines.push("    ." + p.name.padEnd(w) + " ()" + (k < sig.length - 1 ? "," : "") + "  // " + p.dir));
      lines.push(");");
      copyText(lines.join("\n"), "Instance copied");
    }
  });
}

// ---------------------------------------------------------------- flow -----
function flowHtml(c) {
  const L = S.lib;
  const e = c.excluded || {};
  const cfg = L.config || {};
  const rows = [];
  const mark = (ok) => "<span class='vf-mark " + (ok ? "is-pass" : "is-warn") + "'></span>";
  if (c.category === "physical") {
    rows.push("<li>" + "<span class='vf-mark is-info'></span>" + " Physical-only cell. " + (c.roles.length ? "This flow inserts it as <b>" + esc(c.roles.join(", ")) + "</b>." : "The flow doesn't insert this one by default.") + "</li>");
  } else if (!isExcluded(c) && !c.dont_use) {
    rows.push("<li>" + mark(true) + " Synthesis and the resizer may pick it.</li>");
  }
  if (e.synth) rows.push("<li>" + mark(false) + " On the PDK's synthesis exclusion list (<code>" + esc(e.synth.join(", ")) + "</code>). The PDK maintainers keep it out because it fails DRC, has an awkward pin layout, or is meant for special use.</li>");
  if (e.pnr) rows.push("<li>" + mark(false) + " On the PDK's placement exclusion list, so the resizer won't add it either.</li>");
  if (e.user) rows.push("<li>" + mark(false) + " Excluded by your <code>EXTRA_EXCLUDED_CELLS</code> (" + esc(e.user.join(", ")) + ").</li>");
  if (e.swap) rows.push("<li>" + mark(false) + " Swapped out for one of your custom cells (Flow rules).</li>");
  if (c.dont_use) rows.push("<li>" + mark(false) + " The Liberty file marks it <code>dont_use</code>.</li>");
  if (c.used) rows.push("<li><span class='vf-mark is-pass'></span> " + localeNum(c.used) + " instances in run <b>" + esc((L.usage || {}).tag || "") + "</b>. <button class='btn btn-ghost btn-xs' data-go='analytics' data-go-section='an-area'>Area breakdown</button></li>");
  else if ((L.usage || {}).tag && c.category !== "physical") rows.push("<li><span class='vf-mark is-not_run'></span> Not used in run <b>" + esc(L.usage.tag) + "</b>.</li>");
  let act = "";
  if (c.category !== "physical" && state.designDir) {
    const exact = (e.user || []).includes(c.cell);
    const byPattern = e.user && !exact;
    if (!cfg.editable) {
      act = "<p class='muted cl-p'>" + esc(cfg.reason || "This project's config can't be edited here.") + "</p>";
    } else if (exact) {
      act = "<button class='btn btn-sm' data-ex-off='" + esc(c.cell) + "'>Let the flow use it again</button>";
    } else if (byPattern) {
      act = "<p class='muted cl-p'>Your pattern <code>" + esc(e.user[0]) + "</code> catches it. Edit it under <a href='#' data-cl-jump='cl-rules'>Flow rules</a>.</p>";
    } else if (!e.synth && !e.pnr) {
      const fam = familyOf(c.cell);
      act = "<button class='btn btn-sm' data-ex-on='" + esc(c.cell) + "'>" + icon("ban", { size: 13 }) + " Don't use this cell</button>" +
        (fam && fam.cells.length > 1 ? " <button class='btn btn-ghost btn-sm' data-ex-on='" + esc(c.cell.slice(0, c.cell.length - c.drive.length) + "*") + "'>…or the whole " + esc(c.family) + " family</button>" : "");
    }
    if (act) act = "<div class='cl-flow-act'>" + act + "<span class='muted'>Saved to " + esc(cfg.name || "the config") + " as <code>EXTRA_EXCLUDED_CELLS</code>; applies from the next run.</span></div>";
  }
  return "<div class='cl-card-h'>In this design's flow</div><ul class='cl-flow'>" + rows.join("") + "</ul>" + act;
}

async function setUserExcluded(patterns) {
  const list = [...new Set(patterns.filter(Boolean))];
  try {
    if (list.length) await api.configSet({ EXTRA_EXCLUDED_CELLS: list }, []);
    else await api.configSet({}, ["EXTRA_EXCLUDED_CELLS"]);
  } catch (ex) {
    toast.show("Couldn't save: " + (ex.message || ex), "error");
    return false;
  }
  document.dispatchEvent(new CustomEvent("g:config_changed", { detail: { keys: ["EXTRA_EXCLUDED_CELLS"] } }));
  S.stale = false;
  await load(S.pdk, S.scl, S.sel, { keepScroll: true });
  import("./cells-rules.js").then((m) => m.renderRules(ctx()));
  return true;
}

function wireDetail(host, c) {
  if (host._clWired) return;
  host._clWired = true;
  host.addEventListener("click", async (e) => {
    const p = e.target.closest("[data-pick]");
    if (p && !e.target.closest(".cl-tbl")) { select(p.dataset.pick); return; }
    const cp = e.target.closest("[data-copy]");
    if (cp) { copyText(cp.dataset.copy, "Copied " + cp.dataset.copy); return; }
    const on = e.target.closest("[data-ex-on]");
    if (on) {
      const cur = S.lib.rules.user.patterns || [];
      on.disabled = true;
      if (await setUserExcluded(cur.concat([on.dataset.exOn]))) toast.show("The flow won't use " + on.dataset.exOn + " from the next run.", "success");
      return;
    }
    const off = e.target.closest("[data-ex-off]");
    if (off) {
      const cur = (S.lib.rules.user.patterns || []).filter((x) => x !== off.dataset.exOff);
      off.disabled = true;
      if (await setUserExcluded(cur)) toast.show(off.dataset.exOff + " is allowed again.", "success");
    }
  });
  void c;
}

export function copyText(text, msg) {
  const done = () => toast.show(msg || "Copied", "success", 1800);
  if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
  else fallbackCopy(text, done);
}
function fallbackCopy(text, done) {
  const t = document.createElement("textarea");
  t.value = text; t.style.position = "fixed"; t.style.opacity = "0";
  document.body.appendChild(t); t.select();
  try { document.execCommand("copy"); done(); } catch (_e) { toast.show("Copy failed", "error"); }
  t.remove();
}

function emptyHtml(title, body, go, label) {
  return "<div class='empty'><span class='ico'>" + icon("layers", { size: 40 }) + "</span><h3>" + esc(title) + "</h3><p>" + esc(body) + "</p>" +
    (go ? "<button class='btn btn-primary' data-go='" + go + "'>" + esc(label) + "</button>" : "") + "</div>";
}

// "/" focuses the cell search while the tab is open.
document.addEventListener("keydown", (e) => {
  if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
  const sec = document.getElementById("sec-cells");
  if (!sec || !sec.classList.contains("section-active")) return;
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  const q = document.getElementById("cl-q");
  if (q) { e.preventDefault(); q.focus(); q.select(); }
});
