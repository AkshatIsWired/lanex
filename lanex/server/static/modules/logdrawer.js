// logdrawer.js — the Logs panel: streamed output from work that happens outside
// a run (tool / PDK / GDS3D installs, removals, the engine). It rises from the status
// line, and like every overlay it closes when you click anywhere else or press
// Esc. The status-line "Logs" button reopens it; the last output stays until
// cleared, and a count shows how many lines arrived while it was closed.

import { openOverlay, releaseOverlay, isOverlayOpen } from "./shell.js";

let _el = null;
let _unseen = 0;

function body() {
  return _el ? _el.querySelector(".log-panel-body") : null;
}

function bodyText() {
  const b = body();
  return b ? b.textContent : "";
}

function syncBtn() {
  const btn = document.getElementById("logs-btn");
  const count = document.getElementById("logs-count");
  if (!btn) return;
  const open = !!_el && !_el.hidden;
  if (open) _unseen = 0;
  btn.setAttribute("aria-pressed", open ? "true" : "false");
  btn.classList.toggle("has-activity", _unseen > 0);
  if (count) {
    count.hidden = _unseen === 0;
    count.textContent = _unseen > 99 ? "99+" : String(_unseen);
  }
}

function hide() {
  if (!_el) return;
  _el.hidden = true;
  syncBtn();
}

function show() {
  const d = ensure();
  if (d.hidden) {
    d.hidden = false;
    openOverlay(d, document.getElementById("logs-btn"), hide);
  }
  syncBtn();
}

function ensure() {
  if (_el) return _el;
  const d = document.createElement("section");
  d.className = "log-panel";
  d.id = "log-panel";
  d.hidden = true;
  d.setAttribute("aria-label", "Logs");
  d.innerHTML =
    "<div class='log-panel-head'>" +
    "<span class='log-panel-title'>Logs</span><span class='log-panel-sub' id='log-panel-sub'>Installs and tool output</span>" +
    "<span class='log-panel-spacer'></span>" +
    "<button class='btn btn-ghost btn-sm' data-act='copy'>Copy</button>" +
    "<button class='btn btn-ghost btn-sm' data-act='clear'>Clear</button>" +
    "<button class='iconbtn' data-act='close' aria-label='Close logs (Esc)'>" +
    "<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button>" +
    "</div>" +
    "<pre class='log-panel-body'></pre>";
  document.body.appendChild(d);
  const b = d.querySelector(".log-panel-body");
  d.querySelector("[data-act='close']").addEventListener("click", () => { releaseOverlay(d); hide(); });
  d.querySelector("[data-act='clear']").addEventListener("click", () => { b.textContent = ""; _unseen = 0; syncBtn(); });
  d.querySelector("[data-act='copy']").addEventListener("click", () => {
    try { navigator.clipboard.writeText(b.textContent); } catch (_e) {}
  });
  _el = d;
  return d;
}

export function openDrawer(title) {
  ensure();
  if (title) _el.querySelector("#log-panel-sub").textContent = title;
  show();
}

export function appendDrawer(line) {
  if (line == null) return;
  const d = ensure();
  const b = d.querySelector(".log-panel-body");
  const stick = b.scrollTop + b.clientHeight >= b.scrollHeight - 4;
  b.textContent += line + "\n";
  if (stick) b.scrollTop = b.scrollHeight;
  if (d.hidden) _unseen += 1;
  syncBtn();
}

export function clearDrawer() {
  const b = body();
  if (b) { b.textContent = ""; _unseen = 0; syncBtn(); }
}

export function closeDrawer() {
  if (_el) { releaseOverlay(_el); hide(); }
}

export function toggleDrawer() {
  const d = ensure();
  if (!d.hidden && isOverlayOpen(d)) { releaseOverlay(d); hide(); return false; }
  show();
  return true;
}

export function hasContent() {
  return bodyText().trim().length > 0;
}

export function setupLogDrawer() {
  const btn = document.getElementById("logs-btn");
  if (btn && !btn._wired) {
    btn._wired = true;
    btn.addEventListener("click", () => toggleDrawer());
  }
  syncBtn();
}
