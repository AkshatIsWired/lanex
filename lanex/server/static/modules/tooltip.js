// tooltip.js — one reusable tooltip for [data-tip] elements. Delegated, so it
// costs a handful of listeners for the whole app. Visual only: elements keep
// their aria-label for assistive tech; data-tip drives the on-screen bubble.
// Applied to bounded chrome (topbar iconbtns, rail tabs, seg buttons).

let tip = null;
let timer = 0;

function ensure() {
  if (tip) return tip;
  tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "presentation");
  tip.hidden = true;
  document.body.appendChild(tip);
  return tip;
}

function hide() {
  clearTimeout(timer);
  if (tip) tip.hidden = true;
}

// The UI-zoom control applies CSS `zoom` to <html>. Chromium's getBoundingClientRect
// returns coordinates in the ZOOMED space (position × zoom), but style.left/top on a
// body child are interpreted in UNZOOMED CSS px (then rendered × zoom) — so placing
// the bubble straight from a rect double-applies the zoom and lands it far off. Divide
// the measured geometry by the active zoom to work in CSS space; the bubble then paints
// exactly over its target at any zoom. (No-op at 100% where the factor is 1.)
function zoomFactor() {
  const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ll-zoom"));
  return v > 0 ? v : 1;
}

function place(target) {
  const txt = target.getAttribute("data-tip");
  if (!txt) return;
  const t = ensure();
  t.textContent = txt;
  t.hidden = false;                       // unhide to measure (same task → no flash)
  const z = zoomFactor();
  const r = target.getBoundingClientRect();
  const tr = t.getBoundingClientRect();
  const rl = r.left / z, rt = r.top / z, rb = r.bottom / z, rw = r.width / z;
  const tw = tr.width / z, th = tr.height / z;
  let top = rt - th - 8;                   // prefer above (all in CSS space)
  let below = false;
  if (top < 4) { top = rb + 8; below = true; }   // flip below when clipped
  let left = rl + rw / 2 - tw / 2;
  left = Math.max(6, Math.min(left, window.innerWidth - tw - 6));
  t.style.top = Math.round(top) + "px";
  t.style.left = Math.round(left) + "px";
  t.classList.toggle("tip-below", below);
}

function onOver(e) {
  const target = e.target.closest && e.target.closest("[data-tip]");
  if (!target) return;
  clearTimeout(timer);
  timer = setTimeout(() => place(target), 250);
}

function onOut(e) {
  if (e.target.closest && e.target.closest("[data-tip]")) hide();
}

export function setupTooltips() {
  document.addEventListener("mouseover", onOver);
  document.addEventListener("mouseout", onOut);
  document.addEventListener("focusin", onOver);
  document.addEventListener("focusout", onOut);
  window.addEventListener("scroll", hide, true);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
}
