// zoom.js — in-app UI zoom for the standalone app window.
//
// The `--app=` window has no browser chrome, so the menu zoom control is gone
// (Ctrl +/- and Ctrl+wheel still work — they change the BROWSER zoom, which is
// independent of this). This control scales the UI with the CSS `zoom`
// property on <html> (supported by every Chromium the app window can run in,
// and by Firefox 126+ for the tab fallback), persisted per machine so both the
// cockpit and the IDE page come back at the chosen size.
//
// Until the user picks a size, the UI sizes itself for the screen. The layout
// was made for a laptop (about 1536 × 864 CSS px); on a 27-inch 1440p screen,
// or a 4K one at 125–150 % Windows scaling, it would otherwise be a thin strip
// of small text stretched across a wide desk-distance monitor. The factor comes
// from the SCREEN, so text keeps its size while the window moves or resizes;
// it only gives way when the window gets too small to lay the UI out at
// 1536 × 900 zoomed px. That floor matters: media queries see the real window,
// not the zoomed one, and every width breakpoint in the stylesheets is at or
// below 1500 px, so above the floor they agree with what is on screen.

const KEY = "ll.zoom";
const MIN = 0.5;
const MAX = 2.0;
const STEP = 0.1;

// A screen this big (CSS px) shows the UI at 100 %; bigger ones scale it up.
const REF_W = 2048;
const REF_H = 1152;
const AUTO_MAX = 1.5;
// The smallest window the automatic size lays the UI out in (zoomed px).
const FLOOR_W = 1536;
const FLOOR_H = 900;

export function clampZoom(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return 1;
  // Snap to one decimal so repeated +/- can't accumulate float dust.
  return Math.min(MAX, Math.max(MIN, Math.round(n * 10) / 10));
}

// The automatic size for a screen and window (all in CSS px), in 0.05 steps,
// rounded down so text never ends up bigger than the window can lay out.
export function autoZoom(screenW, screenH, winW, winH) {
  const z = Math.min(screenW / REF_W, screenH / REF_H, winW / FLOOR_W, winH / FLOOR_H, AUTO_MAX);
  if (!Number.isFinite(z) || z <= 1) return 1;
  return Math.floor(z * 20 + 1e-6) / 20;
}

function stored() {
  try {
    const s = localStorage.getItem(KEY);
    return s === null || s === "" ? null : clampZoom(s);
  } catch (_e) {
    return null;
  }
}

export function isAutoZoom() {
  return stored() === null;
}

function autoNow() {
  try {
    return autoZoom(screen.width, screen.height, window.innerWidth, window.innerHeight);
  } catch (_e) {
    return 1;
  }
}

export function currentZoom() {
  const s = stored();
  return s === null ? autoNow() : s;
}

// The zoom the page is drawn at right now (1 = none). Canvases use it to keep
// their backing store sharp and to turn client coordinates into CSS px.
export function appliedZoom() {
  const v = parseFloat(document.documentElement.style.zoom);
  return v > 0 ? v : 1;
}

// Draw the page at `z` (no saving). Exported for the IDE pop-out, which mirrors
// the cockpit's size.
export function applyZoom(z) {
  const v = Math.min(MAX, Math.max(MIN, Number(z) > 0 ? Number(z) : 1));
  const before = appliedZoom();
  try {
    document.documentElement.style.zoom = v === 1 ? "" : String(v);
    // CSS `zoom` scales layout, but vw/vh units keep resolving against the
    // REAL viewport — so a `height:100vh` shell renders v× too tall/short
    // (zoom in → scrollbars, zoom out → dead space). Stylesheets divide
    // their viewport units by this variable to compensate.
    if (v === 1) document.documentElement.style.removeProperty("--ll-zoom");
    else document.documentElement.style.setProperty("--ll-zoom", String(v));
  } catch (_e) {}
  paintReadout(v);
  if (before !== v) {
    try { window.dispatchEvent(new CustomEvent("g:zoom", { detail: { zoom: v } })); } catch (_e) {}
  }
  return v;
}

function paintReadout(v) {
  const pct = document.getElementById("zoom-pct");
  if (!pct) return;
  const auto = isAutoZoom();
  pct.textContent = `${Math.round(v * 100)}%`;
  pct.classList.toggle("is-auto", auto);
  const tip = auto
    ? `Sized for this screen (${Math.round(v * 100)}%). Use − and + to change it.`
    : "Back to the size for this screen";
  pct.dataset.tip = tip;
  pct.setAttribute("aria-label", auto ? tip : `Interface size ${Math.round(v * 100)}%. ${tip}`);
}

// A size the user chose: saved, and it stays until they reset it.
export function setZoom(z) {
  const v = clampZoom(z);
  try { localStorage.setItem(KEY, String(v)); } catch (_e) {}
  return applyZoom(v);
}

// Back to the automatic size for this screen.
export function resetZoom() {
  try { localStorage.removeItem(KEY); } catch (_e) {}
  return applyZoom(autoNow());
}

export function zoomBy(delta) {
  // Step along the 10 % grid, so 125 % (an automatic size) goes to 130 or 120.
  const z = currentZoom();
  const next = delta > 0 ? Math.floor(z * 10 + 1e-6) / 10 + STEP : Math.ceil(z * 10 - 1e-6) / 10 - STEP;
  return setZoom(next);
}

export function setupZoom() {
  applyZoom(currentZoom());
  document.getElementById("zoom-out-btn")?.addEventListener("click", () => zoomBy(-1));
  document.getElementById("zoom-in-btn")?.addEventListener("click", () => zoomBy(+1));
  // Clicking the readout goes back to the automatic size (the app-window
  // stand-in for Ctrl+0).
  document.getElementById("zoom-pct")?.addEventListener("click", () => resetZoom());
  // The automatic size follows the window (moved to another screen, or made
  // too small for the current size).
  let t = 0;
  window.addEventListener("resize", () => {
    if (!isAutoZoom()) return;
    clearTimeout(t);
    t = setTimeout(() => applyZoom(autoNow()), 120);
  });
  // Another window (the IDE pop-out) changed the size.
  window.addEventListener("storage", (e) => { if (!e || e.key === KEY) applyZoom(currentZoom()); });
}
