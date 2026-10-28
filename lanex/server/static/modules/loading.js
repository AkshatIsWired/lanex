// loading.js — one loading look for every page, and the rules for when it shows.
//
//   - Feedback on a click is immediate (the page itself, a pressed button).
//   - Nothing extra shows for the first ~300 ms: most loads finish by then.
//   - A page loading for the first time, with nothing to show yet, gets a
//     skeleton shaped like the page (not an empty state: "No runs" is only
//     said once the list has come back empty).
//   - A page refreshing what it already shows keeps showing it.
//   - The region says aria-busy while it loads, and one polite announcement
//     says when it is ready. prefers-reduced-motion gets still blocks.
//
//   const job = loadingStart(el, { skeleton: skel.hero() + skel.rows(6) });
//   ... await the data, paint ...
//   job.done();
//
// The blocks use the MASK ROOM surface tokens (skeleton.css, class prefix ld-).

export const SKELETON_DELAY_MS = 300;

// Should a placeholder show now? Only for a region with nothing on it yet,
// once the load has taken longer than the delay.
export function skeletonDue(elapsedMs, { hasContent = false, delay = SKELETON_DELAY_MS } = {}) {
  return !hasContent && elapsedMs >= delay;
}

// ---------------------------------------------------------------- blocks

const pct = (w) => Math.max(8, Math.min(100, Math.round(w))) + "%";
const line = (w, cls = "") => "<span class='ld-line" + (cls ? " " + cls : "") + "' style='width:" + pct(w) + "'></span>";

export const skel = {
  // A text line, or several (widths in % of the box).
  line,
  lines: (widths) => (widths || [80, 64, 72]).map((w) => line(w)).join(""),
  // A page header: eyebrow, title, a line or two of lede, and its actions.
  hero: ({ lede = 2, actions = 1 } = {}) =>
    "<div class='ld-hero'><div class='ld-hero-main'>" + line(14, "is-eyebrow") + line(46, "is-title") +
    Array.from({ length: lede }, (_, i) => line(i ? 52 : 78)).join("") + "</div>" +
    "<div class='ld-hero-act'>" + Array.from({ length: actions }, () => "<span class='ld-btn'></span>").join("") + "</div></div>",
  // A row of tiles (the Flow strip has seven).
  tiles: (n = 7) => "<div class='ld-tiles' style='--n:" + n + "'>" +
    Array.from({ length: n }, () => "<div class='ld-tile'><span class='ld-pic'></span>" + line(70) + line(45) + "</div>").join("") + "</div>",
  // Table-like rows.
  rows: (n = 6, cols = 4) => "<div class='ld-rows'>" + Array.from({ length: n }, (_, r) =>
    "<div class='ld-row'>" + Array.from({ length: cols }, (_, c) => line(c ? 40 + ((r * 7 + c * 13) % 45) : 90)).join("") + "</div>").join("") + "</div>",
  // Cards in a grid, each a title and a few lines.
  cards: (n = 3) => "<div class='ld-cards'>" + Array.from({ length: n }, (_, i) =>
    "<div class='ld-card'>" + line(40 + (i * 11) % 30, "is-title") + line(85) + line(70) + line(55) + "</div>").join("") + "</div>",
  // A block of a given height (a chart, a picture).
  block: (h = 180) => "<div class='ld-block' style='height:" + Math.max(24, h) + "px'></div>",
  // Two panes side by side (Flow's steps and output, the IDE).
  panes: (h = 320) => "<div class='ld-panes'><div class='ld-block' style='height:" + h + "px'></div><div class='ld-block' style='height:" + h + "px'></div></div>",
};

// A skeleton shaped like each page, for a page whose code or data is still
// on its way. Pages with their own skeleton (Tools, Cells' layout) keep it.
export function pageSkeleton(tab) {
  switch (tab) {
    case "pipeline": return skel.hero({ lede: 2, actions: 2 }) + skel.tiles(7) + skel.panes(300);
    case "runs": return skel.hero({ lede: 2, actions: 2 }) + skel.rows(8, 6);
    case "analytics": return skel.hero({ lede: 2, actions: 2 }) + skel.cards(3) + skel.block(200);
    case "verify": return skel.hero({ lede: 2, actions: 1 }) + skel.cards(4) + skel.rows(5, 4);
    case "layout": return skel.tiles(7) + skel.block(420);
    case "cells": return skel.hero({ lede: 2, actions: 0 }) + skel.cards(3) + skel.rows(6, 4);
    case "ide": return skel.panes(420);
    case "tools": return skel.hero({ lede: 1, actions: 1 }) + skel.cards(3);
    case "setup": return skel.hero({ lede: 2, actions: 2 }) + skel.cards(2);
    default: return skel.hero() + skel.rows(5, 3);
  }
}

// ---------------------------------------------------------------- the pattern

// A region is loading: aria-busy now; after the delay, if it still has
// nothing to show, a skeleton (an overlay element, so the page's own markup
// is never touched). done() takes it away and announces `ready` (optional).
export function loadingStart(region, { skeleton = "", delay = SKELETON_DELAY_MS, hasContent = null, label = "" } = {}) {
  if (!region) return { done() {}, get shown() { return false; } };
  const t0 = now();
  let el = null, timer = 0, over = false;
  region.setAttribute("aria-busy", "true");
  const has = () => (typeof hasContent === "function" ? !!hasContent() : !!hasContent);
  const show = () => {
    timer = 0;
    if (over || !skeleton || has()) return;
    el = document.createElement("div");
    el.className = "ld-skel";
    el.setAttribute("aria-hidden", "true");
    el.innerHTML = skeleton;
    region.classList.add("ld-loading");
    // After the region's own bars that stay (class ld-keep: a run bar).
    const keep = [...region.children].filter((c) => c.classList.contains("ld-keep")).pop();
    if (keep) keep.after(el); else region.prepend(el);
  };
  if (skeletonDue(0, { hasContent: has(), delay })) show();
  else if (skeleton) timer = setTimeout(show, Math.max(0, delay));
  // A page measures its boxes as it draws: call done() before drawing (the
  // skeleton hides the region's children while it shows).
  const job = {
    get shown() { return !!el; },
    done(ready = "") {
      if (over) return;
      over = true;
      if (timer) clearTimeout(timer);
      if (el) { el.remove(); el = null; }
      // Another loading state on the same region (the page's own) keeps it busy.
      if (!region.querySelector(":scope > .ld-skel")) {
        region.removeAttribute("aria-busy");
        region.classList.remove("ld-loading");
      }
      if (ready || label) announce(ready || (label + " loaded"));
      return now() - t0;
    },
  };
  return job;
}

// The same around a promise: the region shows the pattern until it settles.
export function withLoading(region, promise, opts = {}) {
  const job = loadingStart(region, opts);
  return Promise.resolve(promise).finally(() => job.done());
}

// One polite live region for the whole app.
export function announce(text) {
  if (typeof document === "undefined" || !text) return;
  let el = document.getElementById("ld-live");
  if (!el) {
    el = document.createElement("div");
    el.id = "ld-live";
    el.className = "ld-sr";
    el.setAttribute("role", "status");
    el.setAttribute("aria-live", "polite");
    document.body.appendChild(el);
  }
  el.textContent = "";
  // A change of text after a tick is what screen readers pick up.
  setTimeout(() => { el.textContent = text; }, 30);
}

function now() {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

// ---------------------------------------------------------------- loaders

// A loader that runs once: every caller shares the first call's promise; a
// failed load is forgotten so the next caller tries again.
export function onceLoader(load) {
  let p = null;
  return () => {
    if (!p) p = Promise.resolve().then(load).catch((e) => { p = null; throw e; });
    return p;
  };
}

// ECharts (1 MB) only when a chart is first drawn: compare, timing and the bar
// charts ask for it; nothing else does.
const ECHARTS_SRC = "/static/vendor/echarts.min.js";
export const loadECharts = onceLoader(() => {
  if (typeof window === "undefined") return Promise.reject(new Error("no window"));
  if (window.echarts) return window.echarts;
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = ECHARTS_SRC;
    s.async = true;
    s.onload = () => (window.echarts ? resolve(window.echarts) : reject(new Error("ECharts did not load")));
    s.onerror = () => { s.remove(); reject(new Error("Couldn't load the chart library")); };
    document.head.appendChild(s);
  });
});
