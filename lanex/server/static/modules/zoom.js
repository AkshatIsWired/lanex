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

// Measure-and-fit compaction. Fixed px/@media thresholds can't cover every
// screen × zoom × font × content combination (a 1850px window at 110% still
// overflowed while 120% compacted; a loaded design widens the pills), so instead
// MEASURE whether the real rendered topbar/rail overflow and shed chrome in
// stages only as much as needed. Reset-then-escalate so it also UN-compacts when
// there's room again. .zc1/.zc2 in styles.css define what each stage hides.
function chromeOverflows() {
  const tb = document.querySelector(".topbar");
  const rail = document.querySelector(".side-tabs");
  // +2px guards against sub-pixel rounding jitter causing a false overflow.
  const tbOver = !!tb && tb.scrollWidth > tb.clientWidth + 2;
  const railOver = !!rail && rail.scrollHeight > rail.clientHeight + 2;
  return tbOver || railOver;
}

// Escalate compaction until the chrome fits (0 = full; 1 = low-value labels;
// 2 = wordmark + icon-only switches + pill dots; 3 = shrink + hide low-value
// buttons + icon-only rail). Lowest-value chrome goes first, so the brand
// wordmark only drops when a stage-1 shed wasn't enough — no dropping the whole
// logo lockup for a few px of overflow. Returns the stage it settled on.
export function fitChrome() {
  try {
    const cl = document.documentElement.classList;
    cl.remove("zc1", "zc2", "zc3");
    if (!chromeOverflows()) return 0;
    cl.add("zc1");
    if (!chromeOverflows()) return 1;
    cl.add("zc2");
    if (!chromeOverflows()) return 2;
    cl.add("zc3");
    return 3;
  } catch (_e) {
    return 0;
  }
}

let _fitScheduled = false;
function scheduleFit() {
  if (_fitScheduled) return;
  _fitScheduled = true;
  const run = () => { _fitScheduled = false; fitChrome(); };
  (window.requestAnimationFrame || window.setTimeout)(run);
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
  // Zoom changes the rendered chrome size → re-fit synchronously (reading
  // scrollWidth after the zoom change forces an up-to-date layout).
  fitChrome();
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
  // Re-fit when the window resizes (available width changes) and when the topbar's
  // own content changes (the design/PDK pills widen when a design is loaded).
  window.addEventListener("resize", scheduleFit);
  try {
    const tb = document.querySelector(".topbar");
    if (tb && window.MutationObserver) {
      new MutationObserver(scheduleFit).observe(tb, {
        subtree: true, childList: true, characterData: true,
      });
    }
  } catch (_e) {}
  // A late-loading webfont can reflow the text wider than the fallback measured.
  try { document.fonts && document.fonts.ready.then(scheduleFit); } catch (_e) {}
  scheduleFit();
}
