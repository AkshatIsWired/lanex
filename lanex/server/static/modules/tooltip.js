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

function place(target) {
  const txt = target.getAttribute("data-tip");
  if (!txt) return;
  const t = ensure();
  t.textContent = txt;
  t.hidden = false;                       // unhide to measure (same task → no flash)
  const r = target.getBoundingClientRect();
  const tr = t.getBoundingClientRect();
  let top = r.top - tr.height - 8;         // prefer above
  let below = false;
  if (top < 4) { top = r.bottom + 8; below = true; }   // flip below when clipped
  let left = r.left + r.width / 2 - tr.width / 2;
  left = Math.max(6, Math.min(left, window.innerWidth - tr.width - 6));
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
