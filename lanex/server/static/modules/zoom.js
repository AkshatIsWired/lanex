// zoom.js — in-app UI zoom for the standalone app window.
//
// The `--app=` window has no browser chrome, so the menu zoom control is gone
// (Ctrl +/- and Ctrl+wheel still work — they change the BROWSER zoom, which is
// independent of this). This control scales the UI with the CSS `zoom`
// property on <html> (supported by every Chromium the app window can run in,
// and by Firefox 126+ for the tab fallback), persisted per machine so both the
// cockpit and the IDE page come back at the chosen size.

const KEY = "ll.zoom";
const MIN = 0.5;
const MAX = 2.0;
const STEP = 0.1;

export function clampZoom(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return 1;
  // Snap to one decimal so repeated +/- can't accumulate float dust.
  return Math.min(MAX, Math.max(MIN, Math.round(n * 10) / 10));
}

// Effective-space thresholds (CSS px available AFTER dividing the viewport by the
// zoom factor). Below these the toolbars can't hold their full chrome, so shed
// it in two stages instead of scrolling. Mirrors the @media breakpoints in
// styles.css; height thresholds drive the vertical rail compaction.
const ZC1_W = 1320, ZC1_H = 900;   // stage 1: drop labels / group headers, tighten gaps
const ZC2_W = 1080, ZC2_H = 680;   // stage 2: icon-only switches + rail, logo mark only

// Pure + testable: which compaction stage (0/1/2) does this zoom + viewport need?
// Gated to zoom-IN only — at 100%/zoom-out the @media breakpoints in styles.css
// already handle a genuinely small window, and firing here at z<=1 would strip
// labels on a common short laptop (e.g. 1366x768) at default zoom.
export function compactionLevel(z, w, h) {
  if (!(z > 1)) return 0;
  const ew = w / z, eh = h / z;
  if (ew < ZC2_W || eh < ZC2_H) return 2;
  if (ew < ZC1_W || eh < ZC1_H) return 1;
  return 0;
}

function applyCompaction(z) {
  try {
    const lvl = compactionLevel(z, window.innerWidth, window.innerHeight);
    const cl = document.documentElement.classList;
    cl.toggle("zc1", lvl >= 1);
    cl.toggle("zc2", lvl >= 2);
  } catch (_e) {}
}

export function currentZoom() {
  try {
    return clampZoom(localStorage.getItem(KEY) || 1);
  } catch (_e) {
    return 1;
  }
}

export function applyZoom(z) {
  const v = clampZoom(z);
  try {
    document.documentElement.style.zoom = v === 1 ? "" : String(v);
    // CSS `zoom` scales layout, but vw/vh units keep resolving against the
    // REAL viewport — so a `height:100vh` shell renders v× too tall/short
    // (zoom in → scrollbars, zoom out → dead space). Stylesheets divide
    // their viewport units by this variable to compensate.
    if (v === 1) document.documentElement.style.removeProperty("--ll-zoom");
    else document.documentElement.style.setProperty("--ll-zoom", String(v));
  } catch (_e) {}
  try {
    if (v === 1) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, String(v));
  } catch (_e) {}
  applyCompaction(v);
  const pct = document.getElementById("zoom-pct");
  if (pct) pct.textContent = `${Math.round(v * 100)}%`;
  return v;
}

export function zoomBy(delta) {
  return applyZoom(currentZoom() + delta);
}

export function setupZoom() {
  applyZoom(currentZoom());
  document.getElementById("zoom-out-btn")?.addEventListener("click", () => zoomBy(-STEP));
  document.getElementById("zoom-in-btn")?.addEventListener("click", () => zoomBy(+STEP));
  // Clicking the readout resets to 100% (the app-window stand-in for Ctrl+0).
  document.getElementById("zoom-pct")?.addEventListener("click", () => applyZoom(1));
  // Resizing the window changes the effective space too — re-evaluate compaction.
  window.addEventListener("resize", () => applyCompaction(currentZoom()));
}
