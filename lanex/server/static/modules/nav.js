// nav.js — moving between pages: go(tab, params), Back and Forward, the rail.
//
//   go("verify", { check: "magic-drc" })     a page, and a place on it
//   go("ide", { rel: "src/spm.v", line })    go("cells", { cell })
//   go("setup", { section: "setup-pdk" })    go("pipeline", { pane: "stepout" })
//
// Every page change is one browser history entry (bare #tab), so Alt+← / Alt+→
// and the mouse's back and forward buttons work the way they do in a browser.
// Rules, from VS Code's navigation history and the OpenROAD inspector:
//   - only a page change adds an entry; a second go() to the page you are on
//     replaces it, and panels, filters, sorting and layers never add one;
//   - each page keeps its own scroll position, and Back restores it;
//   - a link from another page shows a "Back to <page · section>" chip in the
//     top bar (the inspector's "Navigate back" appears only after following a
//     link); going anywhere else by the rail drops it;
//   - in the code editor, Alt+← / Alt+→ stay the editor's own (CodeMirror
//     handles them first).
// The last eight places are kept for the palette's "Recent places".

import { activate, currentTab } from "./tabs.js";
import { state } from "./state.js";
import { icon } from "./icons.js";

const RECENT_MAX = 8;
const _scroll = {};          // tab -> scrollTop of the work area when last left
const _entryScroll = {};     // history entry id -> scrollTop when it was left
let _cur = null;             // the entry on screen
let _seq = 0;
const _recent = [];

const work = () => document.querySelector("main.work");

// What each page does with the params of a link (the page itself is already
// showing and rendering when these run).
const FOCUS = {
  ide: async (p) => {
    if (!p.rel && !p.newFile) return;
    const m = await import("./ide/main.js");
    await m.initIde({ designDir: state.designDir, runMode: state.runMode });
    if (p.newFile) m.newFile(p.newFile);
    else await m.openInIde({ rel: p.rel, line: p.line });
  },
  cells: async (p) => {
    if (!p.cell) return;
    const m = await import("./cells.js");
    await m.renderCells({ pdk: p.pdk, scl: p.scl, cell: p.cell });
    document.getElementById("cl-library")?.scrollIntoView({ block: "start" });
  },
  pipeline: async (p) => {
    if (!p.step && !p.stage) return;
    const m = await import("./flow.js");
    await m.revealInFlow(p);
  },
  layout: async (p) => {
    if (!p.source && !p.box) return;
    const m = await import("./layout.js");
    if (p.box) await m.revealBox(p.box);
    else await m.revealSource(p.source);
  },
  setup: async (p) => {
    if (!p.setting) return;
    const m = await import("./config.js");
    await m.revealSetting(p.setting);
  },
  verify: async (p) => {
    if (!p.check && !p.filter) return;
    const m = await import("./verify.js");
    if (p.check) await m.revealCheck(p.check);
    else await m.revealProblems();
  },
  tools: async (p) => {
    if (!p.item) return;
    const m = await import("./tools.js");
    await m.focusTools(p);
  },
};

export function tabLabel(tab) {
  return document.querySelector('.side-tab[data-tab="' + tab + '"] .label')?.textContent.trim() || tab;
}

// "Verify · Checks": the page and the section of it in view.
function here() {
  const tab = currentTab();
  const cur = document.querySelector("#sec-" + tab + " .section-jump .is-current");
  const sec = cur && cur.textContent.trim();
  return tabLabel(tab) + (sec && !/^(overview|project)$/i.test(sec) ? " · " + sec : "");
}

function describe(e) {
  const p = e.params || {};
  const sec = p.section && document.querySelector('#sec-' + e.tab + ' [data-jump="' + p.section + '"]');
  const what = p.cell || p.rel || p.check || p.setting || p.step || p.label || (sec ? sec.textContent.trim() : "");
  return tabLabel(e.tab) + (what ? " · " + what : "");
}

// ---------------------------------------------------------------- go
// `link: false` for the rail, number keys and the palette: the user picked the
// page itself, so there is no "Back to" chip (Back still works).
export function go(tab, params = {}, { link = true } = {}) {
  if (!document.getElementById("sec-" + tab)) return;
  const from = currentTab();
  saveScroll();
  if (_cur && tab === _cur.tab) {
    // Same page: a new place on it replaces the entry (VS Code merges nearby
    // moves the same way), so Back never steps through every click.
    _cur = { ..._cur, params: { ...params } };
    history.replaceState({ lx: _cur }, "", "#" + tab);
    show(_cur, { fresh: true });
    return;
  }
  const via = link && from !== tab ? here() : null;
  _cur = { id: ++_seq, tab, params: { ...params }, via };
  history.pushState({ lx: _cur }, "", "#" + tab);
  show(_cur, { fresh: true });
}

// The browser's Back and Forward (Alt+←, mouse buttons, the chip).
// (At popstate the browser already shows the entry popped to, so the one being
// left is only noted in memory, never written back.)
function onPop(e) {
  const entry = e.state && e.state.lx;
  saveScroll();
  _cur = entry || { id: ++_seq, tab: "setup", params: {}, via: null };
  show(_cur, { fresh: false });
}

function show(entry, { fresh }) {
  const changed = currentTab() !== entry.tab || !document.querySelector(".section.section-active");
  if (changed) {
    activate(entry.tab);
    document.dispatchEvent(new CustomEvent("g:tab_activated", { detail: { tab: entry.tab } }));
  }
  paintBack();
  remember(entry);
  const p = entry.params || {};
  const focus = FOCUS[entry.tab];
  const done = Promise.resolve(focus && fresh ? focus(p) : null).catch((e) => console.error("nav focus", e));
  // A focus handler may answer with the id of the element it found (a setting's
  // row): that is held in view like a section while the page fills in.
  if (fresh && (p.section || p.setting)) {
    done.then((id) => revealSection(entry.tab, p.section || id));
  } else if (changed && !(fresh && (p.cell || p.check || p.rel || p.setting || p.step || p.stage || p.box || p.filter || p.item))) {
    restoreScroll(!fresh && _entryScroll[entry.id] != null ? _entryScroll[entry.id] : (_scroll[entry.tab] || 0));
  }
}

// ---------------------------------------------------------------- scroll
function saveScroll() {
  const w = work();
  if (!w || !_cur) return;
  _scroll[_cur.tab] = w.scrollTop;
  _entryScroll[_cur.id] = w.scrollTop;
}

// Pages render after they show (data arrives later): keep asking for the
// position until the page is tall enough, for up to two seconds, and give up
// the moment the user scrolls.
let _restoreTok = 0;
function restoreScroll(top) {
  const w = work();
  if (!w) return;
  const tok = ++_restoreTok;
  w.scrollTop = top;
  if (!top) return;
  const t0 = performance.now();
  const stop = () => { _restoreTok++; };
  w.addEventListener("wheel", stop, { once: true, passive: true });
  w.addEventListener("keydown", stop, { once: true });
  w.addEventListener("pointerdown", stop, { once: true });
  const step = () => {
    if (tok !== _restoreTok) return;
    if (Math.abs(w.scrollTop - top) > 2) w.scrollTop = top;
    if (Math.abs(w.scrollTop - top) <= 2 && w.scrollHeight - w.clientHeight >= top) return;
    if (performance.now() - t0 < 2000) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// A link to a section: put it just under the page's sticky header, and keep it
// there while the page fills in above it (its data arrives after it shows),
// for up to two and a half seconds or until the user scrolls.
function revealSection(tab, id) {
  const w = work();
  if (!w) return;
  const tok = ++_restoreTok;
  const t0 = performance.now();
  const stop = () => { _restoreTok++; };
  w.addEventListener("wheel", stop, { once: true, passive: true });
  w.addEventListener("keydown", stop, { once: true });
  w.addEventListener("pointerdown", stop, { once: true });
  const step = () => {
    if (tok !== _restoreTok) return;
    const el = document.getElementById(id);
    if (el && el.offsetParent !== null) {
      const box = w.getBoundingClientRect();
      const k = box.height / (w.offsetHeight || 1) || 1;          // client px per CSS px (UI zoom)
      const head = document.querySelector("#sec-" + tab + " .section-jump-stack, #sec-" + tab + " > .section-jump");
      const line = head ? (head.getBoundingClientRect().bottom - box.top) / k : 0;
      const want = Math.max(0, w.scrollTop + (el.getBoundingClientRect().top - box.top) / k - line - 12);
      const max = w.scrollHeight - w.clientHeight;
      if (Math.abs(Math.min(want, max) - w.scrollTop) > 3) w.scrollTop = want;
    }
    if (performance.now() - t0 < 2500) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

// ---------------------------------------------------------------- Back chip
function paintBack() {
  const b = document.getElementById("nav-back");
  if (!b) return;
  const via = _cur && _cur.via;
  b.hidden = !via;
  if (via) {
    b.querySelector(".nav-back-to").textContent = via;
    b.setAttribute("aria-label", "Back to " + via);
    b.dataset.tip = "Back to " + via + " (Alt+←)";
  }
}

// ---------------------------------------------------------------- recents
function remember(e) {
  const key = e.tab + JSON.stringify(e.params || {});
  const i = _recent.findIndex((r) => r.key === key);
  if (i >= 0) _recent.splice(i, 1);
  _recent.unshift({ key, tab: e.tab, params: { ...(e.params || {}) }, label: describe(e) });
  _recent.length = Math.min(_recent.length, RECENT_MAX + 4);
}
// The places visited before this one, newest first (a bare visit to the page
// you are on is no place to go).
export function recentPlaces() {
  const here = _cur && _cur.tab;
  return _recent.slice(1).filter((r) => r.tab !== here || Object.keys(r.params).length).slice(0, RECENT_MAX);
}

// ---------------------------------------------------------------- setup
export function setupNav() {
  window.addEventListener("popstate", onPop);
  window.addEventListener("keydown", (e) => {
    if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    const t = e.target;
    if (e.defaultPrevented || (t && (t.isContentEditable || /input|textarea|select/i.test(t.tagName || "") ||
        (t.closest && t.closest(".cm-editor, .wv"))))) return;
    e.preventDefault();
    if (e.key === "ArrowLeft") history.back(); else history.forward();
  });
  // Any [data-go="tab"] is a link to that page; data-go-<name>="value" adds a
  // param (data-go-section, -setting, -source, -step, -stage, -check).
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("[data-go]");
    if (!a || a.disabled) return;
    e.preventDefault();
    const params = {};
    for (const [k, v] of Object.entries(a.dataset)) {
      if (k.length > 2 && k.startsWith("go")) params[k[2].toLowerCase() + k.slice(3)] = v;
    }
    go(a.dataset.go, params);
  });
  const b = document.getElementById("nav-back");
  if (b) {
    b.insertAdjacentHTML("afterbegin", icon("chevron", { size: 14 }).replace("<svg", "<svg class='nav-back-ico'"));
    b.addEventListener("click", () => history.back());
  }
  // Number keys follow the rail: say so on each tab.
  railKeys().forEach(([key, tab]) => {
    const t = document.querySelector('.side-tab[data-tab="' + tab + '"]');
    if (t && t.dataset.tip && !/\(\d\)$/.test(t.dataset.tip)) t.dataset.tip += " (" + key + ")";
  });
}

// The first page: Setup, as one history entry the rest build on.
export function startAt(tab) {
  _cur = { id: ++_seq, tab, params: {}, via: null };
  history.replaceState({ lx: _cur }, "", "#" + tab);
  activate(tab);
  remember(_cur);
}

// [key, tab] in rail order: 1–9 then 0.
export function railKeys() {
  const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"];
  return Array.from(document.querySelectorAll(".side-tabs .side-tab")).slice(0, 10)
    .map((t, i) => [keys[i], t.dataset.tab]);
}
