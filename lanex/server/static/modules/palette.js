// palette.js — command palette (⌘K / Ctrl-K).
// A single fuzzy-searchable launcher for every action in the app: switch
// tabs, run/stop, install, toggle theme/density, jump to docs. The power-user
// fast path; also a discoverability aid for beginners (everything is here).

import { activate } from "./tabs.js";
import { toggleTheme } from "./theme.js";
import { toggleDensity } from "./density.js";
import { toggleRunMode, getRunMode } from "./runmode.js";
import { icon } from "./icons.js";

let _el = null;
let _input = null;
let _list = null;
let _items = [];
let _filtered = [];
let _sel = 0;

function click(id) {
  document.getElementById(id)?.click();
}

function tab(name) {
  document.querySelector('.side-tab[data-tab="' + name + '"]')?.click() || activate(name);
}

// Action registry. `when` (optional) hides actions that aren't applicable.
function actions() {
  return [
    { id: "go-setup", title: "Go to Setup", hint: "tab", icon: icon("folder"), run: () => tab("setup") },
    { id: "go-pipeline", title: "Go to Pipeline", hint: "tab", icon: icon("flow"), run: () => tab("pipeline") },
    { id: "go-runs", title: "Go to Runs", hint: "tab", icon: icon("clock"), run: () => tab("runs") },
    { id: "go-preview", title: "Go to Preview", hint: "tab", icon: icon("image"), run: () => tab("preview") },
    { id: "go-tools", title: "Go to Tools", hint: "tab", icon: icon("tools"), run: () => tab("tools") },
    { id: "go-analytics", title: "Go to Analytics", hint: "tab", icon: icon("chart"), run: () => tab("analytics") },
    { id: "run", title: "Run flow", hint: "action", icon: icon("play"), run: () => click("btn-run") },
    { id: "stop", title: "Stop the run", hint: "action", icon: icon("stop"), run: () => click("btn-cancel") },
    { id: "resume", title: "Resume / next step", hint: "action", icon: icon("play"), run: () => click("btn-resume") },
    { id: "preflight", title: "Check my setup (preflight)", hint: "action", icon: icon("check"), run: () => click("btn-preflight") },
    { id: "runmode", title: "Switch run engine (Container / Local tools)", hint: "action", icon: icon("refresh"), run: () => toggleRunMode() },
    { id: "spm", title: "Load the SPM example", hint: "action", icon: icon("plus"), run: () => click("btn-load-spm") },
    { id: "theme", title: "Toggle dark / light theme", hint: "view", icon: icon("moon"), run: () => toggleTheme() },
    { id: "density", title: "Toggle compact density", hint: "view", icon: icon("grid"), run: () => toggleDensity() },
    { id: "shortcuts", title: "Keyboard shortcuts", hint: "help", icon: icon("command"), run: () => document.getElementById("help-dialog")?.showModal?.() },
    { id: "docs", title: "Open LibreLane docs", hint: "help", icon: icon("arrowUp"), run: () => window.open("https://librelane.readthedocs.io/", "_blank", "noopener") },
  ];
}

function score(q, text) {
  // Lightweight subsequence fuzzy score; -1 = no match.
  q = q.toLowerCase();
  text = text.toLowerCase();
  if (!q) return 0;
  if (text.includes(q)) return 100 - text.indexOf(q);
  let qi = 0;
  for (let i = 0; i < text.length && qi < q.length; i++) {
    if (text[i] === q[qi]) qi++;
  }
  return qi === q.length ? 1 : -1;
}

function build() {
  _el = document.createElement("div");
  _el.className = "cmdk";
  _el.hidden = true;
  _el.innerHTML =
    '<div class="cmdk-backdrop"></div>' +
    '<div class="cmdk-panel" role="dialog" aria-label="Command palette">' +
    '<input class="cmdk-input" type="text" placeholder="Type a command…  (Esc to close)" autocomplete="off" spellcheck="false"/>' +
    '<div class="cmdk-list" role="listbox"></div>' +
    '<div class="cmdk-foot"><kbd>↑</kbd><kbd>↓</kbd> navigate · <kbd>↵</kbd> run · <kbd>esc</kbd> close</div>' +
    "</div>";
  document.body.appendChild(_el);
  _input = _el.querySelector(".cmdk-input");
  _list = _el.querySelector(".cmdk-list");
  _el.querySelector(".cmdk-backdrop").addEventListener("click", close);
  _input.addEventListener("input", () => { _sel = 0; refresh(); });
  _input.addEventListener("keydown", onKey);
}

function onKey(e) {
  if (e.key === "ArrowDown") { _sel = Math.min(_sel + 1, _filtered.length - 1); paint(); e.preventDefault(); }
  else if (e.key === "ArrowUp") { _sel = Math.max(_sel - 1, 0); paint(); e.preventDefault(); }
  else if (e.key === "Enter") { runSel(); e.preventDefault(); }
  else if (e.key === "Escape") { close(); e.preventDefault(); }
}

function refresh() {
  const q = _input.value.trim();
  _filtered = _items
    .map((a) => ({ a, s: score(q, a.title + " " + a.hint) }))
    .filter((x) => x.s >= 0)
    .sort((x, y) => y.s - x.s)
    .map((x) => x.a);
  paint();
}

function paint() {
  _list.innerHTML = _filtered
    .map(
      (a, i) =>
        '<div class="cmdk-item' + (i === _sel ? " cmdk-item-sel" : "") + '" data-i="' + i + '">' +
        '<span class="cmdk-ico">' + a.icon + "</span>" +
        '<span class="cmdk-title">' + a.title + "</span>" +
        '<span class="cmdk-hint">' + a.hint + "</span>" +
        "</div>",
    )
    .join("") || '<div class="cmdk-empty">No matching command</div>';
  _list.querySelectorAll(".cmdk-item").forEach((el) => {
    el.addEventListener("click", () => { _sel = +el.dataset.i; runSel(); });
    el.addEventListener("mousemove", () => { _sel = +el.dataset.i; paint(); });
  });
  const sel = _list.querySelector(".cmdk-item-sel");
  if (sel) sel.scrollIntoView({ block: "nearest" });
}

function runSel() {
  const a = _filtered[_sel];
  if (!a) return;
  close();
  try { a.run(); } catch (e) { console.error("palette action failed", e); }
}

export function openPalette() {
  if (!_el) build();
  _items = actions();
  _input.value = "";
  _sel = 0;
  refresh();
  _el.hidden = false;
  requestAnimationFrame(() => _input.focus());
}

export function close() {
  if (_el) _el.hidden = true;
}

export function setupPalette() {
  window.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault();
      if (_el && !_el.hidden) close();
      else openPalette();
    }
  });
}
