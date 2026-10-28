// analytics-charts.js — small, dependency-free chart pieces for the Analytics
// tab. Each returns an HTML/SVG string drawn with CSS custom properties, so the
// charts follow the light/dark theme without re-rendering.
//
// Conventions (kept in every piece): one value axis per chart, hairline solid
// gridlines, 2px lines, >=8px markers with a surface ring, thin bars with a
// rounded data end, text in text tokens (never the series colour), and every
// value reachable as text (direct label, table or the hover tip that is also
// shown on keyboard focus).

import { fmt } from "./api.js";
import { localeNum } from "./intlcache.js";

const esc = (s) => fmt.escape(s == null ? "" : String(s));

// ---------- hover tip (one per page, delegated) ------------------------------

let _tip = null;
function tipEl() {
  if (_tip) return _tip;
  _tip = document.createElement("div");
  _tip.className = "an-tip";
  _tip.setAttribute("role", "presentation");
  _tip.hidden = true;
  document.body.appendChild(_tip);
  return _tip;
}

function zoom() {
  const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ll-zoom"));
  return v > 0 ? v : 1;
}

function showTip(target, x, y) {
  const txt = target.getAttribute("data-an-tip");
  if (!txt) return;
  const t = tipEl();
  t.textContent = "";
  const lines = txt.split("\n");
  lines.forEach((ln, i) => {
    const d = document.createElement("div");
    if (i === 0) d.className = "an-tip-h";
    else if (/^[a-z0-9_]+__\S+$/.test(ln) || /^\d+-[a-z]/.test(ln)) d.className = "an-tip-k";   // metric key / step dir
    d.textContent = ln;
    t.appendChild(d);
  });
  t.hidden = false;
  const z = zoom();
  const r = target.getBoundingClientRect();
  const px = (x == null ? r.left + r.width / 2 : x) / z;
  const py = (y == null ? r.top : y) / z;
  const tw = t.offsetWidth, th = t.offsetHeight;
  let left = px + 14, top = py - th - 10;
  if (left + tw > window.innerWidth / z - 8) left = px - tw - 14;
  if (top < 8) top = py + 18;
  t.style.left = Math.max(8, Math.round(left)) + "px";
  t.style.top = Math.round(top) + "px";
}

function hideTip() { if (_tip) _tip.hidden = true; }

export function wireTips(root) {
  if (!root || root._anTips) return;
  root._anTips = true;
  root.addEventListener("mousemove", (e) => {
    const el = e.target.closest && e.target.closest("[data-an-tip]");
    if (el && root.contains(el)) showTip(el, e.clientX, e.clientY); else hideTip();
  });
  root.addEventListener("mouseleave", hideTip);
  root.addEventListener("focusin", (e) => {
    const el = e.target.closest && e.target.closest("[data-an-tip]");
    if (el) showTip(el); else hideTip();
  });
  root.addEventListener("focusout", hideTip);
  window.addEventListener("scroll", hideTip, true);
}

// ---------- sparkline ---------------------------------------------------------

// values: number|null per run (oldest -> newest). `sel` index is ringed;
// `bad` indexes (failed runs) get a hollow marker.
export function sparkline(values, { sel = -1, bad = [], w = 120, h = 30, tips = [], runTags = null } = {}) {
  w = Math.max(60, Math.round(w));
  const pts = values.map((v, i) => [i, typeof v === "number" && Number.isFinite(v) ? v : null]);
  const ys = pts.filter((p) => p[1] !== null).map((p) => p[1]);
  if (ys.length < 1 || values.length < 2) return "";
  let lo = Math.min(...ys), hi = Math.max(...ys);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = 4;
  const X = (i) => pad + (i * (w - 2 * pad)) / Math.max(1, values.length - 1);
  const Y = (v) => h - pad - ((v - lo) * (h - 2 * pad)) / (hi - lo);
  let d = "";
  let pen = false;
  for (const [i, v] of pts) {
    if (v === null) { pen = false; continue; }
    d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1);
    pen = true;
  }
  const dots = pts.map(([i, v]) => {
    if (v === null) return "";
    const isSel = i === sel;
    const isBad = bad.includes(i);
    const cls = isSel ? "sp-sel" : isBad ? "sp-bad" : "sp-pt";
    return "<circle class='" + cls + "' cx='" + X(i).toFixed(1) + "' cy='" + Y(v).toFixed(1) + "' r='" + (isSel ? 4 : isBad ? 3 : 2) + "'/>";
  }).join("");
  const hits = tips.length ? pts.map(([i]) => {
    const x0 = i === 0 ? 0 : (X(i - 1) + X(i)) / 2;
    const x1 = i === values.length - 1 ? w : (X(i) + X(i + 1)) / 2;
    return "<rect class='sp-hit' x='" + x0.toFixed(1) + "' y='0' width='" + (x1 - x0).toFixed(1) + "' height='" + h + "' data-an-tip='" + esc(tips[i] || "") + "'" + (runTags && runTags[i] ? " data-an-run='" + esc(runTags[i]) + "'" : "") + "/>";
  }).join("") : "";
  return "<svg class='an-spark' width='" + w + "' height='" + h + "' viewBox='0 0 " + w + " " + h + "' aria-hidden='true'>" +
    "<path class='sp-line' d='" + d + "' vector-effect='non-scaling-stroke'/>" + dots + hits + "</svg>";
}

// ---------- line chart (categorical x, one value axis) ----------------------------

// series: [{name, cls, values:[number|null]}]; xs: [{label, sub, tip}]
// W is the real pixel width of the host, so text stays at its CSS size.
export function lineChart({ xs, series, unit = "", height = 200, zero = false, fmtY = (v) => String(v), label = "", W = 640 }) {
  W = Math.max(280, Math.round(W));
  const H = height, L = 48, R = 18, T = 12, B = 44;
  const all = [];
  for (const s of series) for (const v of s.values) if (typeof v === "number" && Number.isFinite(v)) all.push(v);
  if (!all.length) return "";
  let lo = Math.min(...all), hi = Math.max(...all);
  if (zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (hi === lo) { hi += Math.abs(hi) * 0.1 || 1; lo -= Math.abs(lo) * 0.1 || 1; }
  const ticks = niceTicks(lo, hi, 4);
  lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
  const n = xs.length;
  const X = (i) => L + (n === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (n - 1));
  const Y = (v) => T + ((hi - v) * (H - T - B)) / (hi - lo);
  let g = "";
  for (const t of ticks) {
    g += "<line class='lc-grid" + (t === 0 ? " lc-zero" : "") + "' x1='" + L + "' x2='" + (W - R) + "' y1='" + Y(t).toFixed(1) + "' y2='" + Y(t).toFixed(1) + "'/>" +
      "<text class='lc-yt' x='" + (L - 8) + "' y='" + (Y(t) + 4).toFixed(1) + "' text-anchor='end'>" + esc(fmtY(t)) + "</text>";
  }
  let xl = "";
  xs.forEach((x, i) => {
    xl += "<text class='lc-xt' x='" + X(i).toFixed(1) + "' y='" + (H - B + 18) + "' text-anchor='middle'>" + esc(x.label) + "</text>";
    if (x.sub) xl += "<text class='lc-xs' x='" + X(i).toFixed(1) + "' y='" + (H - B + 32) + "' text-anchor='middle'>" + esc(x.sub) + "</text>";
  });
  let lines = "", dots = "";
  for (const s of series) {
    let d = "", pen = false;
    s.values.forEach((v, i) => {
      if (typeof v !== "number" || !Number.isFinite(v)) { pen = false; return; }
      d += (pen ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1);
      pen = true;
      dots += "<circle class='lc-dot " + s.cls + "' cx='" + X(i).toFixed(1) + "' cy='" + Y(v).toFixed(1) + "' r='4'/>";
    });
    lines += "<path class='lc-line " + s.cls + "' d='" + d + "'/>";
  }
  // hover columns: crosshair + tip listing every series at that x
  let hits = "";
  xs.forEach((x, i) => {
    const x0 = i === 0 ? L : (X(i - 1) + X(i)) / 2;
    const x1 = i === n - 1 ? W - R : (X(i) + X(i + 1)) / 2;
    const tip = [x.tip || x.label].concat(series.map((s) => {
      const v = s.values[i];
      return s.name + ": " + (typeof v === "number" && Number.isFinite(v) ? fmtY(v, true) + (unit ? " " + unit : "") : "not measured here");
    })).join("\n");
    hits += "<g class='lc-hx'><line class='lc-guide' x1='" + X(i).toFixed(1) + "' x2='" + X(i).toFixed(1) + "' y1='" + T + "' y2='" + (H - B) + "'/>" +
      "<rect x='" + x0.toFixed(1) + "' y='" + T + "' width='" + Math.max(1, x1 - x0).toFixed(1) + "' height='" + (H - T - B) + "' fill='transparent' tabindex='0' data-an-tip='" + esc(tip) + "'/></g>";
  });
  return "<svg class='an-line' width='" + W + "' height='" + H + "' viewBox='0 0 " + W + " " + H + "' role='img' aria-label='" + esc(label) + "'>" + g + xl + lines + dots + hits + "</svg>";
}

export function niceTicks(lo, hi, count) {
  const span = hi - lo;
  const raw = span / Math.max(1, count);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= count) || 10 * mag;
  const start = Math.floor(lo / step) * step;
  const out = [];
  for (let v = start; v <= hi + step * 1e-9; v += step) out.push(Number(v.toFixed(10)));
  if (out[out.length - 1] < hi) out.push(Number((out[out.length - 1] + step).toFixed(10)));
  return out;
}

// ---------- horizontal bar list ------------------------------------------------------

// rows: [{label, value, text, sub, tone, tip, mono}] — bars scaled to the max
// |value|. tone: "" (series), "muted", "fail", "warn".
export function barList(rows, { max } = {}) {
  const m = max || Math.max(0, ...rows.map((r) => Math.abs(r.value || 0))) || 1;
  return "<div class='an-bars'>" + rows.map((r) => {
    const pct = Math.max(0, Math.min(100, (Math.abs(r.value || 0) / m) * 100));
    return "<div class='an-bar-row'" + (r.tip ? " data-an-tip='" + esc(r.tip) + "'" : "") + ">" +
      "<span class='an-bar-label" + (r.mono ? " mono" : "") + "' title='" + esc(r.label) + "'>" + esc(r.label) +
      (r.sub ? " <span class='an-bar-sub'>" + esc(r.sub) + "</span>" : "") + "</span>" +
      "<span class='an-bar-track'><span class='an-bar-fill " + (r.tone || "") + "' style='width:" + (pct > 0 ? Math.max(pct, 0.8).toFixed(2) : 0) + "%'></span></span>" +
      "<span class='an-bar-val'>" + r.text + "</span></div>";
  }).join("") + "</div>";
}

// ---------- stacked bar ------------------------------------------------------------------

// segs: [{label, value, cls, text, src}] -> one bar + a legend with values
// (src: optional HTML after a value, e.g. its source button).
export function stackBar(segs, { legend = true } = {}) {
  const total = segs.reduce((s, x) => s + Math.max(0, x.value || 0), 0) || 1;
  const bar = "<div class='an-stack' role='img' aria-label='" + esc(segs.map((s) => s.label + " " + s.text).join(", ")) + "'>" +
    segs.filter((s) => s.value > 0).map((s) => {
      const pct = (s.value / total) * 100;
      return "<span class='an-stack-seg " + s.cls + "' style='flex-basis:" + Math.max(pct, 0.6).toFixed(3) + "%' data-an-tip='" +
        esc(s.label + "\n" + s.text + " · " + pctText(pct)) + "'></span>";
    }).join("") + "</div>";
  if (!legend) return bar;
  return bar + "<div class='an-legend'>" + segs.map((s) =>
    "<span class='an-leg'><i class='an-key " + s.cls + "'></i>" + esc(s.label) +
    " <b>" + s.text + "</b> <span class='muted'>" + pctText((Math.max(0, s.value) / total) * 100) + "</span>" + (s.src || "") + "</span>").join("") + "</div>";
}

export function pctText(p) {
  if (p === 0) return "0%";
  if (p < 0.1) return "<0.1%";
  return (p >= 10 ? p.toFixed(0) : p.toFixed(1)) + "%";
}

// ---------- diverging bars (slack per corner) ---------------------------------------------

// rows: [{label, sub, value, text, worst}] around a zero axis. Negative values
// are failures (status colour + the sign in the text), positive ones use the
// series colour. `scale` = max |value| shared across sibling charts.
export function divergingBars(rows, { scale, cls = "s1" } = {}) {
  const m = scale || Math.max(1e-9, ...rows.map((r) => (Number.isFinite(r.value) ? Math.abs(r.value) : 0)));
  const anyNeg = rows.some((r) => Number.isFinite(r.value) && r.value < 0);
  return "<div class='an-div" + (anyNeg ? " has-neg" : "") + "'>" + rows.map((r) => {
    const fin = Number.isFinite(r.value);
    const pct = fin ? Math.min(100, (Math.abs(r.value) / m) * 100) : 0;
    const neg = fin && r.value < 0;
    return "<div class='an-div-row" + (r.worst ? " is-worst" : "") + "' data-an-tip='" + esc(r.tip || "") + "'>" +
      "<span class='an-div-label'>" + esc(r.label) + (r.sub ? "<small>" + esc(r.sub) + "</small>" : "") + "</span>" +
      "<span class='an-div-plot'>" +
      (anyNeg ? "<span class='an-div-neg'>" + (neg ? "<span class='an-div-bar fail' style='width:" + Math.max(pct, 1).toFixed(2) + "%'></span>" : "") + "</span>" : "") +
      "<span class='an-div-pos'>" + (!neg && fin ? "<span class='an-div-bar " + cls + "' style='width:" + Math.max(pct, 0.8).toFixed(2) + "%'></span>" : "") + "</span>" +
      "</span><span class='an-div-val" + (neg ? " is-neg" : "") + "'>" + r.text + "</span></div>";
  }).join("") + "</div>";
}

// ---------- floorplan (to scale) ------------------------------------------------------------

// die/core: [x0, y0, x1, y1] in µm. Draws die and core rectangles to scale.
export function floorplan(die, core, { label = "" } = {}) {
  if (!die) return "";
  const [dx0, dy0, dx1, dy1] = die;
  const dw = dx1 - dx0, dh = dy1 - dy0;
  if (!(dw > 0 && dh > 0)) return "";
  const S = 220 / Math.max(dw, dh);
  const pad = 30;
  const W = dw * S + pad * 2, H = dh * S + pad * 2;
  const X = (x) => pad + (x - dx0) * S;
  const Y = (y) => pad + (dy1 - y) * S;   // layout y grows upward
  let core_ = "";
  if (core) {
    const [cx0, cy0, cx1, cy1] = core;
    core_ = "<rect class='fp-core' x='" + X(cx0).toFixed(1) + "' y='" + Y(cy1).toFixed(1) + "' width='" + ((cx1 - cx0) * S).toFixed(1) +
      "' height='" + ((cy1 - cy0) * S).toFixed(1) + "' data-an-tip='" + esc("Core (where cells are placed)\n" + num2(cx1 - cx0) + " × " + num2(cy1 - cy0) + " µm") + "'/>" +
      "<text class='fp-tag' x='" + (X(cx0) + 6).toFixed(1) + "' y='" + (Y(cy1) + 14).toFixed(1) + "'>core</text>";
  }
  return "<svg class='an-fp' viewBox='0 0 " + W.toFixed(0) + " " + H.toFixed(0) + "' role='img' aria-label='" + esc(label) + "'>" +
    "<rect class='fp-die' x='" + pad + "' y='" + pad + "' width='" + (dw * S).toFixed(1) + "' height='" + (dh * S).toFixed(1) + "' data-an-tip='" + esc("Die (the whole chip area)\n" + num2(dw) + " × " + num2(dh) + " µm") + "'/>" +
    core_ +
    "<text class='fp-dim' x='" + (pad + (dw * S) / 2).toFixed(1) + "' y='" + (pad - 10) + "' text-anchor='middle'>" + num2(dw) + " µm</text>" +
    "<text class='fp-dim' x='" + (pad - 10) + "' y='" + (pad + (dh * S) / 2).toFixed(1) + "' text-anchor='middle' transform='rotate(-90 " + (pad - 10) + " " + (pad + (dh * S) / 2).toFixed(1) + ")'>" + num2(dh) + " µm</text>" +
    "</svg>";
}

function num2(v) {
  return localeNum(Number(v.toFixed(2)), "en-US", { maximumFractionDigits: 2 });
}

export function bbox(v) {
  if (!v) return null;
  const nums = (typeof v === "string" ? v.trim().split(/\s+/) : v).map(Number);
  return nums.length === 4 && nums.every(Number.isFinite) ? nums : null;
}

// ---------- columns (e.g. DRC per router iteration) ---------------------------------------

// cols: [{label, value, text, tip, src}] — single series, labels under, values on
// caps (src: optional HTML after the value, e.g. its source button).
export function columns(cols, { cls = "s1" } = {}) {
  const m = Math.max(1e-9, ...cols.map((c) => c.value || 0));
  return "<div class='an-cols'>" + cols.map((c) => {
    const pct = ((c.value || 0) / m) * 100;
    return "<div class='an-col' tabindex='0' data-an-tip='" + esc(c.tip || "") + "'>" +
      "<span class='an-col-val'>" + esc(c.text) + (c.src || "") + "</span>" +
      "<span class='an-col-track'><span class='an-col-bar " + (c.value ? cls : "zero") + "' style='height:" + (c.value ? Math.max(pct, 2).toFixed(2) : 0) + "%'></span></span>" +
      "<span class='an-col-label'>" + esc(c.label) + "</span></div>";
  }).join("") + "</div>";
}

// ---------- measured charts ----------------------------------------------------

// Charts are drawn at their host's real width so text keeps its CSS size.
// A section registers a draw function per host id; drawCharts() renders every
// host under `root`, and redraws on resize.
const _draw = new Map();
let _seq = 0;
export function chartHost(fn, cls = "") {
  const id = "anc" + (++_seq);
  _draw.set(id, fn);
  return "<div class='an-chart " + cls + "' data-chart='" + id + "'></div>";
}
export function drawCharts(root) {
  if (!root) return;
  // Every width is read first, then every chart written: reading a width
  // after a write forces a layout per chart.
  const todo = [];
  root.querySelectorAll(".an-chart[data-chart]").forEach((h) => {
    const fn = _draw.get(h.dataset.chart);
    if (fn) todo.push([h, fn, h.clientWidth]);
  });
  for (const [h, fn, w] of todo) if (w > 0 && h._w !== w) { h._w = w; h.innerHTML = fn(w); }
}
export function resetCharts() { _draw.clear(); }
let _ro = null;
export function watchResize(root) {
  if (_ro || !root || typeof ResizeObserver === "undefined") return;
  let t = 0;
  _ro = new ResizeObserver(() => { clearTimeout(t); t = setTimeout(() => drawCharts(root), 80); });
  _ro.observe(root);
}
