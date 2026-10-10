// layout.js — the Layout tab: see the chip.
//
// One page replaces the old Preview + Layout pair:
//   * the run's layout drawn live by KLayout (PDK colours, any zoom), with a
//     stage strip to step through floorplan → power grid → placement → clock
//     tree → routing → final GDS (the way a P&R tool shows the database at
//     each step);
//   * a side panel shaped after KLayout / Virtuoso: layers (visibility, solo,
//     presets), the cells placed (counts by kind, highlight every instance),
//     find (pins, labels, cell types) and checks (DRC / XOR markers on the
//     layout, as Calibre RVE cross-probes into the layout);
//   * click anything to see what it is, in plain words;
//   * the desktop viewers (KLayout, OpenROAD GUI, Magic, GDS3D) one click away,
//     each saying what it is for, plus the exact terminal commands.
// The engine is controller/layoutview.py; the camera is layoutcanvas.js.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { icon } from "./icons.js";
import * as ctx from "./context.js";
import { mountRunBar } from "./runbar.js";
import { STAGES as FLOW_STAGES } from "./flowstages.js";
import { LayoutCanvas, fmtUm, niceLength } from "./layoutcanvas.js";
import { Layout3D } from "./layout3d.js";
import { setRunFilesTag } from "./runfiles.js";
import { toolRoutes, launchTool } from "./layouttools.js";

const BG = { dark: "#06080d", light: "#ffffff" };
const KINDS = {
  sequential: { label: "Flip-flops and latches", hint: "store your design's state, one bit each", color: "#4da3ff" },
  combinational: { label: "Logic gates", hint: "AND, OR, XOR and friends: the logic itself", color: "#e879c9" },
  inverter: { label: "Inverters", hint: "flip a signal; also strengthen it", color: "#d6446f" },
  buffer: { label: "Buffers and delays", hint: "drive long wires and the clock tree, or fix hold timing", color: "#f2c14e" },
  mux: { label: "Multiplexers", hint: "pick one of several inputs", color: "#38d6c8" },
  arithmetic: { label: "Adders", hint: "full and half adders", color: "#ff7a45" },
  physical: { label: "Fill, taps and decaps", hint: "no logic: they fill gaps, tie the wells to power and steady the supply", color: "#6d7d94" },
  other: { label: "Other cells and macros", hint: "", color: "#8ea6c4" },
};
const KIND_ORDER = ["sequential", "combinational", "inverter", "buffer", "mux", "arithmetic", "other", "physical"];

const S = {
  wired: false,
  tag: "", design: "",  // the run on screen (the app's, context.js)
  src: null,          // sources() reply for the run
  source: "",         // current source id
  info: null,         // open_session() reply
  vis: new Set(),     // visible layer ids
  labels: pref("labels", "1") === "1",
  outlines: false,
  bg: pref("bg", "dark"),
  hl: null,           // { cell, boxes, total }
  sel: null,          // { hits, x, y }
  pin: null,          // { x, y, t } a found label
  markers: null,      // markers() reply
  showMarkers: true,
  activeMarker: null,
  rulers: 0,
  canvas: null,
  playing: 0,
  three: null,        // Layout3D, made on first use
  mode3d: false,
  meshKey: "",
  commands: null,
  openToken: 0,
};

function pref(k, d) { try { return localStorage.getItem("ll.lx." + k) ?? d; } catch (_e) { return d; } }
function setPref(k, v) { try { localStorage.setItem("ll.lx." + k, v); } catch (_e) {} }
const $ = (id) => document.getElementById(id);
const STAGE_NO = Object.fromEntries(FLOW_STAGES.map((s, i) => [s.id, i + 1]));
const esc = (s) => fmt.escape(String(s ?? ""));

// ------------------------------------------------------------------ entry points
export async function renderLayout() {
  wireOnce();
  await loadRuns();
}

// ------------------------------------------------------------------ runs
// The run is the app's (context.js): Runs, the run bar on any results page and
// a finished run all change it, and this page follows.
async function loadRuns() {
  const runs = await ctx.loadRuns();
  const tag = ctx.contextRun();
  const empty = !runs.length || !tag;
  $("lx-empty").hidden = !empty;
  $("lx-page").hidden = empty;
  for (const id of ["lx-openin", "lx-save", "lx-cmd"]) { const el = $(id); if (el) el.closest(".lx-split").hidden = empty; }
  if (empty) {
    S.tag = ""; S.design = "";
    setRunFilesTag("");
    return;
  }
  if (tag !== S.tag || ctx.contextDesign() !== S.design || !S.info) { stopPlay(); await openRun(tag); }
}

async function openRun(tag) {
  const tok = ++S.openToken;
  S.tag = tag;
  S.design = ctx.contextDesign();
  S.commands = null;
  S.markers = null;
  S.hl = null; S.sel = null; S.pin = null; S.activeMarker = null;
  hideInspector();
  setRunFilesTag(tag);
  renderDesk();
  let src = null;
  try { src = await api.layoutSources(tag); } catch (ex) { src = { error: ex.message || String(ex), status: ex.status, stages: [] }; }
  if (tok !== S.openToken) return;
  S.src = src;
  if (src.status === 404 && !/run not found/i.test(src.error || "")) {
    // The page is newer than the server process (the UI files update live,
    // the Python server only on restart).
    renderStages();
    showMsg("<h3>Restart LanEx to finish the update</h3><p>This page is newer than the running LanEx server, which " +
      "doesn't know the layout viewer yet. Close LanEx and open it again.</p>");
    return;
  }
  const stages = (src && src.stages) || [];
  if (!stages.length) {
    S.source = "";
    S.info = null;
    renderStages();
    showMsg("<h3>Nothing to draw yet</h3><p>This run stopped before the floorplan was written, so it has no layout. " +
      "The Pipeline tab shows where it stopped.</p>" +
      "<button class='btn btn-ghost btn-sm' data-go='pipeline'>Open Pipeline</button>");
    setNote("");
    return;
  }
  const final = stages.find((s) => s.id === "final");
  const pick = final || stages[stages.length - 1];
  renderStages();
  await openSource(pick.source, { keepView: false });
  if (!final) setNote("This run stopped before the final GDS. Showing the last stage it reached: <b>" + esc(pick.label) + "</b>.");
  loadMarkers(tag);
}

// ------------------------------------------------------------------ sources
async function openSource(source, { keepView = true } = {}) {
  const tag = S.tag;
  const eng = (S.src && S.src.engine) || {};
  S.source = source;
  paintStageSelection();
  if (!eng.ok) {
    renderFallback(eng.reason);
    return;
  }
  setBusy(true);
  let info;
  try { info = await api.layoutOpen(tag, source); }
  catch (ex) { info = { ok: false, error: ex.message || String(ex) }; }
  setBusy(false);
  if (tag !== S.tag || source !== S.source) return;
  if (!info || info.ok === false) {
    S.info = null;
    showMsg("<h3>KLayout could not draw this</h3><p>" + esc((info && info.error) || "unknown error") + "</p>" +
      "<p class='muted'>The desktop viewers below may still open it.</p>");
    return;
  }
  hideMsg();
  const prevLayers = S.info ? S.info.layers : null;
  S.info = info;
  // What was clicked belongs to the previous picture.
  S.sel = null;
  hideInspector();
  S.vis = carryVisibility(prevLayers, info.layers);
  S.hl = S.hl && info.cells.some((c) => c.name === S.hl.cell) ? S.hl : null;
  if (S.hl) highlightCell(S.hl.cell, { quiet: true });
  ensureCanvas();
  S.canvas.setLayout(info.bbox, { keepView });
  renderLayers();
  renderCells();
  renderFind();
  paintBadge();
  if (S.mode3d) load3d();
  const stage = (S.src.stages || []).find((s) => s.source === source);
  const other = !stage && [...(S.src.steps || []), ...(S.src.variants || [])].find((s) => s.source === source);
  const notes = (info.notes || []).map(esc).join(" ");
  setNote((stage ? esc(stage.blurb) : other ? "Step snapshot <code>" + esc(other.path) + "</code>." : "") +
    (info.kind === "def" ? " <span class='muted'>Cells are drawn as their LEF outlines and pins, as LibreLane's <code>OpenInKLayout</code> shows a DEF.</span>" : "") +
    (notes ? " <span class='muted'>" + notes + "</span>" : ""));
}

// Keep the user's layer choices when switching stage: match by layer name.
function carryVisibility(prev, next) {
  const out = new Set();
  if (!prev || S._visTouched !== true) {
    for (const L of next) if (L.visible) out.add(L.id);
    return out;
  }
  const was = new Map(prev.map((L) => [L.label, S.vis.has(L.id)]));
  for (const L of next) {
    const v = was.has(L.label) ? was.get(L.label) : L.visible;
    if (v) out.add(L.id);
  }
  return out;
}

function renderFallback(reason) {
  const r = S.src && S.src.render;
  showMsg("<h3>The live viewer isn't available</h3><p>" + esc(reason || "KLayout's Python package could not be loaded.") +
    " Install LibreLane's Python packages (they include KLayout) to draw layouts here.</p>" +
    (r ? "<img class='lx-static' src='" + api.runFileUrl(S.tag, r) + "' alt='Rendered layout'/>" : "") +
    "<p class='muted'>The desktop viewers below still work.</p>");
}

// ------------------------------------------------------------------ canvas
function ensureCanvas() {
  if (S.canvas) return;
  const view = $("lx-view");
  S.canvas = new LayoutCanvas(view, {
    renderUrl: (box, w, h, dpr, o = {}) => renderUrl(box, w, h, o.backdrop ? 1 : 1 / dpr) + (o.os > 1 ? "&os=" + o.os : ""),
    bg: () => BG[S.bg] || BG.dark,
    onView: (v) => { paintHud(v); paintMini(v); },
    onHover: (x, y) => paintXY(x, y),
    onClick: (x, y, p) => probeAt(x, y, p),
    onBusy: (b) => setBusy(b),
    onError: (ex) => {
      if (!ex) return;
      // The server dropped the session (restart, cache): reopen once, quietly.
      if (ex.status === 410 && S.tag && Date.now() - (S._reopened || 0) > 5000) {
        S._reopened = Date.now();
        openSource(S.source);
        return;
      }
      toast.show("Layout render failed: " + (ex.message || ex), "error");
    },
    onRulers: (r) => { S.rulers = r.length; },
    onKey: (k) => keyCmd(k),
  });
  S.canvas.drawOverlay = drawOverlay;
  view.classList.toggle("is-light", S.bg === "light");
  // First visit: the gesture hint shows on hover until the first interaction.
  if (pref("hinted", "0") !== "1") {
    $("lx-hint").classList.add("is-first");
    S.canvas.over.addEventListener("pointerdown", () => { $("lx-hint").classList.remove("is-first"); setPref("hinted", "1"); }, { once: true });
  }
}

function renderUrl(box, w, h, res) {
  const q = new URLSearchParams();
  q.set("sid", S.info.sid);
  if (box) q.set("box", box.map((v) => +v.toFixed(5)).join(","));
  q.set("w", String(w));
  q.set("h", String(h));
  q.set("vis", [...S.vis].join(","));
  if (S.outlines) q.set("depth", "1");
  q.set("labels", S.labels ? "1" : "0");
  q.set("bg", BG[S.bg] || BG.dark);
  if (res && res !== 1) q.set("res", String(+res.toFixed(4)));
  return "/api/layout/render?" + q.toString();
}

function restyle() {
  if (S.canvas && S.info) S.canvas.restyle();
  if (S.three) S.three.setVisible(S.vis);
}

function keyCmd(k) {
  if (k === "measure") { toggleMeasure(); return true; }
  if (k === "escape") { clearSelection(); if (S.canvas.mode === "measure") toggleMeasure(false); return true; }
  if (k === "l" || k === "L") { toggleLabels(); return true; }
  if (k === "o" || k === "O") { toggleOutlines(); return true; }
  if (k === "[" || k === "]") { stepStage(k === "]" ? 1 : -1); return true; }
  if (k === "3") { toggle3d(); return true; }
  return false;
}

// ------------------------------------------------------------------ overlay
function drawOverlay(ctx, v) {
  const strokeBox = (b, style, fill, dash, minPx = 0) => {
    let [x1, y1] = v.w2s(b[0], b[3]);
    let [x2, y2] = v.w2s(b[2], b[1]);
    if (x2 - x1 < minPx) { const c = (x1 + x2) / 2; x1 = c - minPx / 2; x2 = c + minPx / 2; }
    if (y2 - y1 < minPx) { const c = (y1 + y2) / 2; y1 = c - minPx / 2; y2 = c + minPx / 2; }
    if (x2 < 0 || y2 < 0 || x1 > v.W || y1 > v.H) return;
    ctx.save();
    if (fill) { ctx.fillStyle = fill; ctx.fillRect(x1, y1, x2 - x1, y2 - y1); }
    ctx.strokeStyle = style;
    ctx.lineWidth = 1.5;
    if (dash) ctx.setLineDash(dash);
    ctx.strokeRect(Math.round(x1) + 0.5, Math.round(y1) + 0.5, Math.round(x2 - x1), Math.round(y2 - y1));
    ctx.restore();
  };
  if (S.labels) drawIoPins(ctx, v);
  // highlighted cell type
  if (S.hl && S.hl.boxes.length) {
    // Highlight and dim (as P&R tools do): veil the rest, punch the cells through.
    ctx.save();
    ctx.fillStyle = S.bg === "light" ? "rgba(255,255,255,0.62)" : "rgba(4,6,10,0.62)";
    ctx.fillRect(0, 0, v.W, v.H);
    for (const b of S.hl.boxes) {
      const [x1, y1] = v.w2s(b[0], b[3]);
      const [x2, y2] = v.w2s(b[2], b[1]);
      if (x2 < 0 || y2 < 0 || x1 > v.W || y1 > v.H) continue;
      ctx.clearRect(x1, y1, Math.max(x2 - x1, 2), Math.max(y2 - y1, 2));
    }
    ctx.restore();
    for (const b of S.hl.boxes) strokeBox(b, "#38d6c8", null, null, 3);
  }
  // markers
  if (S.markers && S.showMarkers) {
    for (const src of S.markers.sources || []) {
      if (src.hidden) continue;
      for (const it of src.items || []) {
        const active = it === S.activeMarker;
        for (const g of it.geoms) drawGeom(ctx, v, g, active);
      }
    }
  }
  // the selection
  if (S.sel && S.sel.hits.length) {
    const h = S.sel.hits[0];
    if (h.cell_box) strokeBox(h.cell_box, "#4da3ff", "rgba(77,163,255,0.10)", null);
    strokeBox(h.box, "#ffffff", null, [4, 3]);
  }
  // a found pin / label
  if (S.pin) {
    const [x, y] = v.w2s(S.pin.x, S.pin.y);
    const age = (performance.now() - S.pin.t) / 1000;
    ctx.save();
    ctx.strokeStyle = "#f2c14e";
    ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(x, y, 9, 0, Math.PI * 2); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(x - 16, y); ctx.lineTo(x - 5, y); ctx.moveTo(x + 5, y); ctx.lineTo(x + 16, y);
    ctx.moveTo(x, y - 16); ctx.lineTo(x, y - 5); ctx.moveTo(x, y + 5); ctx.lineTo(x, y + 16); ctx.stroke();
    if (age < 1.6) {
      ctx.globalAlpha = 1 - age / 1.6;
      ctx.beginPath(); ctx.arc(x, y, 9 + age * 30, 0, Math.PI * 2); ctx.stroke();
      requestAnimationFrame(() => S.canvas && S.canvas.paintOverlay());
    }
    ctx.restore();
  }
}

// The chip's I/O pins, named at a readable size around the die edge (KLayout's
// own labels scale with the zoom, so at "fit" they would be specks).
const POWER = /^(VPWR|VGND|VPB|VNB|vccd\d?|vssd\d?|vdda\d?|vssa\d?|VDD|VSS|VCC|GND)$/i;
function ioPins() {
  if (!S.info) return [];
  if (S.info._io) return S.info._io;
  const bb = S.info.bbox;
  const tol = Math.max(bb[2] - bb[0], bb[3] - bb[1]) * 0.012;
  const seen = new Set();
  const out = [];
  for (const l of S.info.labels || []) {
    if (POWER.test(l.text)) continue;
    let side = "";
    if (l.x - bb[0] < tol) side = "w";
    else if (bb[2] - l.x < tol) side = "e";
    else if (l.y - bb[1] < tol) side = "s";
    else if (bb[3] - l.y < tol) side = "n";
    if (!side) continue;
    const key = l.text + "@" + side;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ ...l, side });
  }
  S.info._io = out;
  return out;
}

function drawIoPins(ctx, v) {
  const pins = ioPins();
  if (!pins.length) return;
  const light = S.bg === "light";
  ctx.save();
  ctx.font = "500 11px " + (getComputedStyle(document.body).getPropertyValue("--mono") || "monospace");
  ctx.textBaseline = "middle";
  const placed = { n: -1e9, s: -1e9, e: -1e9, w: -1e9 };
  const sorted = pins.slice().sort((a, b) => (a.side === "n" || a.side === "s") ? a.x - b.x : b.y - a.y);
  for (const p of sorted) {
    const [x, y] = v.w2s(p.x, p.y);
    if (x < -40 || y < -40 || x > v.W + 40 || y > v.H + 40) continue;
    const along = p.side === "n" || p.side === "s" ? x : y;
    // Vertical text on n/s sides needs ~13 px between pins, horizontal on e/w too.
    if (along - placed[p.side] < 13) continue;
    placed[p.side] = along;
    ctx.fillStyle = "#38d6c8";
    ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = light ? "#0b5f58" : "#bff3ee";
    ctx.shadowColor = light ? "rgba(255,255,255,0.9)" : "rgba(0,0,0,0.95)";
    ctx.shadowBlur = 3;
    if (p.side === "n" || p.side === "s") {
      ctx.save();
      ctx.translate(x, y + (p.side === "n" ? -7 : 7));
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = p.side === "n" ? "left" : "right";
      ctx.fillText(p.text, 0, 0);
      ctx.restore();
    } else {
      ctx.textAlign = p.side === "w" ? "right" : "left";
      ctx.fillText(p.text, x + (p.side === "w" ? -7 : 7), y);
    }
    ctx.shadowBlur = 0;
  }
  ctx.restore();
}

function drawGeom(ctx, v, g, active) {
  ctx.save();
  ctx.strokeStyle = "#ff3b5c";
  ctx.fillStyle = active ? "rgba(255,59,92,0.42)" : "rgba(255,59,92,0.24)";
  ctx.lineWidth = active ? 2.5 : 1.5;
  const [bx1, by1] = v.w2s(g.bbox[0], g.bbox[3]);
  const [bx2, by2] = v.w2s(g.bbox[2], g.bbox[1]);
  if (bx2 - bx1 < 6 && by2 - by1 < 6) {
    // too small to see: a ring the size of a fingertip
    const cx = (bx1 + bx2) / 2, cy = (by1 + by2) / 2;
    ctx.beginPath(); ctx.arc(cx, cy, active ? 9 : 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
  } else if (g.kind === "edge-pair" && g.rings.length === 2 && g.rings[0].length === 2 && g.rings[1].length === 2) {
    // The violation is the gap between the two edges (spacing) or across them
    // (width): shade that quad, then draw the edges themselves.
    const [a, b] = g.rings;
    const pts = [a[0], a[1], b[1], b[0]].map((p) => v.w2s(p[0], p[1]));
    ctx.beginPath();
    pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.fill();
    ctx.lineWidth = active ? 3 : 2;
    for (const e of g.rings) {
      const [x1, y1] = v.w2s(e[0][0], e[0][1]);
      const [x2, y2] = v.w2s(e[1][0], e[1][1]);
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    }
  } else {
    for (const ring of g.rings) {
      ctx.beginPath();
      ring.forEach((p, i) => { const [x, y] = v.w2s(p[0], p[1]); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
      if (g.kind === "polygon" || g.kind === "box") { ctx.closePath(); ctx.fill(); }
      ctx.stroke();
    }
  }
  if (active) {
    // Corner brackets: find it at a glance, whatever the layers around it.
    const pad = 10, L = 10;
    const x1 = Math.min(bx1, bx2) - pad, y1 = Math.min(by1, by2) - pad;
    const x2 = Math.max(bx1, bx2) + pad, y2 = Math.max(by1, by2) + pad;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(0,0,0,0.9)";
    ctx.shadowBlur = 4;
    ctx.beginPath();
    for (const [cx, cy, dx, dy] of [[x1, y1, 1, 1], [x2, y1, -1, 1], [x1, y2, 1, -1], [x2, y2, -1, -1]]) {
      ctx.moveTo(cx + dx * L, cy); ctx.lineTo(cx, cy); ctx.lineTo(cx, cy + dy * L);
    }
    ctx.stroke();
  }
  ctx.restore();
}

// ------------------------------------------------------------------ HUD, minimap
function paintHud(v) {
  const el = $("lx-scale");
  if (!el) return;
  const target = v.scale * 110;
  const len = niceLength(target);
  const px = len / v.scale;
  el.querySelector("i").style.width = Math.round(px) + "px";
  el.querySelector("span").textContent = fmtUm(len);
}

function paintXY(x, y) {
  const el = $("lx-xy");
  if (!el) return;
  el.textContent = x == null ? "" : "x " + x.toFixed(3) + "  y " + y.toFixed(3) + " µm";
}

function paintMini(v) {
  const c = $("lx-mini");
  if (!c || !S.canvas || !S.info) return;
  const bb = S.info.bbox;
  const vb = v.box;
  const all = vb[0] <= bb[0] && vb[1] <= bb[1] && vb[2] >= bb[2] && vb[3] >= bb[3];
  c.classList.toggle("is-on", !all);
  const ctx = c.getContext("2d");
  const W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  const bw = bb[2] - bb[0], bh = bb[3] - bb[1];
  const k = Math.min((W - 12) / bw, (H - 12) / bh);
  const ox = (W - bw * k) / 2, oy = (H - bh * k) / 2;
  const tx = (x) => ox + (x - bb[0]) * k, ty = (y) => H - oy - (y - bb[1]) * k;
  const bd = S.canvas.backdrop;
  ctx.fillStyle = BG[S.bg] || BG.dark;
  ctx.fillRect(0, 0, W, H);
  if (bd) {
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(bd.bm, tx(bd.box[0]), ty(bd.box[3]), (bd.box[2] - bd.box[0]) * k, (bd.box[3] - bd.box[1]) * k);
  }
  ctx.strokeStyle = "#4da3ff";
  ctx.lineWidth = 1.5;
  ctx.fillStyle = "rgba(77,163,255,0.14)";
  const x1 = Math.max(0, tx(vb[0])), y1 = Math.max(0, ty(vb[3]));
  const x2 = Math.min(W, tx(vb[2])), y2 = Math.min(H, ty(vb[1]));
  ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
  ctx.strokeRect(x1 + 0.5, y1 + 0.5, Math.max(2, x2 - x1 - 1), Math.max(2, y2 - y1 - 1));
  c._map = { tx, ty, k, ox, oy, bb, H };
}

function miniJump(e) {
  const c = $("lx-mini");
  const m = c._map;
  if (!m || !S.canvas) return;
  const r = c.getBoundingClientRect();
  const sx = (e.clientX - r.left) * (c.width / r.width), sy = (e.clientY - r.top) * (c.height / r.height);
  const x = m.bb[0] + (sx - m.ox) / m.k;
  const y = m.bb[1] + (m.H - m.oy - sy) / m.k;
  S.canvas.centerOn(x, y);
}

function setBusy(b) {
  const el = $("lx-busy");
  if (!el) return;
  clearTimeout(el._t);
  if (b) el._t = setTimeout(() => { el.hidden = false; }, 160);
  else el.hidden = true;
}

function paintBadge() {
  const el = $("lx-badge");
  if (!el || !S.info) return;
  const st = (S.src.stages || []).find((s) => s.source === S.source);
  const bb = S.info.bbox;
  el.innerHTML = "<b>" + esc(st ? st.label : S.source) + "</b><span>" + esc(S.info.top) + " · " +
    fmtUm(bb[2] - bb[0]) + " × " + fmtUm(bb[3] - bb[1]) + "</span>";
}

function showMsg(html) {
  const el = $("lx-msg");
  el.innerHTML = "<div class='lx-msg-in'>" + html + "</div>";
  el.hidden = false;
}
function hideMsg() { const el = $("lx-msg"); if (el) el.hidden = true; }
function setNote(html) { const el = $("lx-note"); if (el) el.innerHTML = html; }

// ------------------------------------------------------------------ stages
function renderStages() {
  const ol = $("lx-stages");
  if (!ol) return;
  const stages = (S.src && S.src.stages) || [];
  const extra = [...((S.src && S.src.steps) || []), ...((S.src && S.src.variants) || [])];
  const thumbH = 64, thumbW = 96;
  const bg = encodeURIComponent(BG[S.bg] || BG.dark);
  const eng = (S.src && S.src.engine) || {};
  ol.innerHTML = stages.map((st, i) =>
    "<li><button class='lx-stage' data-src='" + esc(st.source) + "' title='" + esc(st.blurb) + "'>" +
    "<span class='lx-stage-pic'>" + (eng.ok ? "<img alt='' loading='lazy' src='/api/layout/thumb?tag=" + encodeURIComponent(S.tag) +
      "&source=" + encodeURIComponent(st.source) + "&w=" + thumbW * 2 + "&h=" + thumbH * 2 + "&bg=" + bg + "'/>" : "") + "</span>" +
    // The stage's number in the flow (flowstages.js), the same on every page.
    "<span class='lx-stage-txt'><span class='lx-stage-n'>" + (st.id === "final" ? "GDS" : String(STAGE_NO[st.id] || i + 1).padStart(2, "0")) + "</span>" +
    "<b>" + esc(st.label) + "</b></span></button></li>").join("") +
    stageControls(stages, extra, eng);
  ol.querySelectorAll(".lx-stage").forEach((b) => b.addEventListener("click", () => { stopPlay(); openSource(b.dataset.src); }));
  $("lx-play")?.addEventListener("click", togglePlay);
  $("lx-more")?.addEventListener("change", (e) => { const v = e.target.value; if (v) { stopPlay(); openSource(v); } });
  paintStageSelection();
}

function stageControls(stages, extra, eng) {
  if (!eng.ok) return "";
  const play = stages.length > 1
    ? "<button class='btn btn-ghost btn-sm' id='lx-play' title='Step through every stage, keeping the current view'>" +
      "<svg viewBox='0 0 24 24' width='13' height='13' fill='currentColor' aria-hidden='true'><path d='M7 4l13 8-13 8z'/></svg> <span>Play<span class='lx-play-x'> the flow</span></span></button>"
    : "";
  const more = extra.length
    ? "<select id='lx-more' class='lx-more' aria-label='Any step snapshot' title='Any step that wrote a DEF, or the separate KLayout and Magic stream-outs'>" +
      "<option value=''>Other snapshot…</option>" +
      (S.src.steps.length ? "<optgroup label='Steps'>" + S.src.steps.map((s) => "<option value='" + esc(s.source) + "'>" + esc(s.step) + "</option>").join("") + "</optgroup>" : "") +
      (S.src.variants.length ? "<optgroup label='Final GDS files'>" + S.src.variants.map((s) => "<option value='" + esc(s.source) + "'>" + esc(s.label) + " · " + esc(s.path.split("/").pop()) + "</option>").join("") + "</optgroup>" : "") +
      "</select>"
    : "";
  return play || more ? "<li class='lx-stage-ctl'>" + play + more + "</li>" : "";
}

function paintStageSelection() {
  document.querySelectorAll("#lx-stages .lx-stage").forEach((b) => {
    const on = b.dataset.src === S.source;
    b.classList.toggle("is-on", on);
    b.setAttribute("aria-current", on ? "step" : "false");
  });
  const more = $("lx-more");
  if (more) more.value = (S.src.stages || []).some((s) => s.source === S.source) ? "" : S.source;
}

function stepStage(d) {
  const st = (S.src && S.src.stages) || [];
  const i = st.findIndex((s) => s.source === S.source);
  const j = Math.max(0, Math.min(st.length - 1, (i < 0 ? st.length - 1 : i) + d));
  if (st[j] && st[j].source !== S.source) openSource(st[j].source);
}

function togglePlay() { if (S.playing) stopPlay(); else startPlay(); }
function startPlay() {
  const st = (S.src && S.src.stages) || [];
  if (st.length < 2) return;
  let i = 0;
  const btn = $("lx-play");
  if (btn) btn.innerHTML = "<svg viewBox='0 0 24 24' width='13' height='13' fill='currentColor' aria-hidden='true'><path d='M6 5h4v14H6zM14 5h4v14h-4z'/></svg> Stop";
  const tick = async () => {
    if (!S.playing) return;
    await openSource(st[i].source);
    i += 1;
    if (i >= st.length) { stopPlay(); return; }
    S.playing = setTimeout(tick, 1500);
  };
  S.playing = setTimeout(tick, 0);
}
function stopPlay() {
  clearTimeout(S.playing);
  S.playing = 0;
  const btn = $("lx-play");
  if (btn) btn.innerHTML = "<svg viewBox='0 0 24 24' width='13' height='13' fill='currentColor' aria-hidden='true'><path d='M7 4l13 8-13 8z'/></svg> <span>Play<span class='lx-play-x'> the flow</span></span>";
}

// ------------------------------------------------------------------ layers pane
function swatchStyle(L) {
  const c = L.fill, f = L.frame;
  const d = L.dither | 0;
  let bgimg;
  if (d === 0) bgimg = "linear-gradient(" + c + "," + c + ")";
  else if (d === 1) bgimg = "none";
  else {
    const ang = [45, 135, 90, 0][d % 4];
    const gap = 3 + (d % 3);
    bgimg = "repeating-linear-gradient(" + ang + "deg," + c + " 0 1.5px,transparent 1.5px " + gap + "px)";
  }
  return "background-image:" + bgimg + ";border-color:" + f;
}

function renderLayers() {
  const host = $("lx-pane-layers");
  if (!host || !S.info) return;
  const layers = S.info.layers;
  const groups = S.info.groups.filter((g) => layers.some((L) => L.group === g.id));
  const presets = [
    ["all", "Everything", "Every layer the PDK's layer file shows by default"],
    ["wiring", "Wiring", "Only the metal layers, vias and pins: how signals travel"],
    ["devices", "Transistors", "Only diffusion, poly, wells and local interconnect: where the transistors are"],
  ];
  host.innerHTML =
    "<div class='lx-presets' role='group' aria-label='Layer presets'>" +
    presets.map(([id, l, t]) => "<button class='chip chip-clickable' data-preset='" + id + "' title='" + esc(t) + "'>" + l + "</button>").join("") +
    "</div>" +
    groups.map((g) => {
      const ls = layers.filter((L) => L.group === g.id);
      const on = ls.filter((L) => S.vis.has(L.id)).length;
      return "<div class='lx-lgroup' data-group='" + g.id + "'>" +
        "<div class='lx-lgroup-h'><label class='lx-check'><input type='checkbox' data-gtoggle='" + g.id + "'" +
        (on === ls.length ? " checked" : "") + (on && on < ls.length ? " data-mixed='1'" : "") + "/><span>" + esc(g.label) + "</span></label>" +
        "<span class='lx-n'>" + on + "/" + ls.length + "</span></div>" +
        ls.map((L) =>
          "<div class='lx-layer" + (S.vis.has(L.id) ? "" : " is-off") + "' data-lid='" + L.id + "' title='" + esc((L.about ? L.about + ". " : "") + "GDS layer " + L.src + ". Alt-click shows only this layer.") + "'>" +
          "<label class='lx-check'><input type='checkbox' data-lid='" + L.id + "'" + (S.vis.has(L.id) ? " checked" : "") + "/>" +
          "<i class='lx-sw' style='" + swatchStyle(L) + "'></i><span class='lx-ln'>" + esc(L.name) +
          (L.purpose ? "<em>." + esc(L.purpose) + "</em>" : "") + "</span></label>" +
          "<span class='lx-src'>" + esc(L.src) + "</span>" +
          "<button class='lx-solo' data-solo='" + L.id + "' title='Show only this layer' aria-label='Show only " + esc(L.label) + "'>only</button></div>").join("") +
        "</div>";
    }).join("");
  host.querySelectorAll("[data-mixed]").forEach((cb) => { cb.indeterminate = true; });
}

function onLayersClick(e) {
  const t = e.target;
  const preset = t.closest("[data-preset]");
  if (preset) { applyPreset(preset.dataset.preset); return; }
  const solo = t.closest("[data-solo]");
  if (solo) { soloLayer(+solo.dataset.solo); return; }
  const row = t.closest(".lx-layer");
  if (row && e.altKey) { e.preventDefault(); soloLayer(+row.dataset.lid); }
}

function onLayersChange(e) {
  const t = e.target;
  if (t.dataset.gtoggle) {
    for (const L of S.info.layers) if (L.group === t.dataset.gtoggle) t.checked ? S.vis.add(L.id) : S.vis.delete(L.id);
  } else if (t.dataset.lid) {
    const id = +t.dataset.lid;
    t.checked ? S.vis.add(id) : S.vis.delete(id);
  } else return;
  S._visTouched = true;
  renderLayers();
  restyle();
}

function soloLayer(id) {
  const only = S.vis.size === 1 && S.vis.has(id);
  S.vis = only ? new Set(S.info.layers.filter((L) => L.visible).map((L) => L.id)) : new Set([id]);
  S._visTouched = !only;
  renderLayers();
  restyle();
}

function applyPreset(p) {
  const Ls = S.info.layers;
  const keepMisc = (L) => L.group === "misc" && /boundary/i.test(L.name) && L.visible;
  let pick;
  if (p === "wiring") pick = Ls.filter((L) => L.group === "metal" || (L.group === "pin" && L.visible) || keepMisc(L) || (L.group === "local" && /^li/i.test(L.name)));
  else if (p === "devices") pick = Ls.filter((L) => ["device", "local", "well"].includes(L.group) || keepMisc(L));
  else pick = Ls.filter((L) => L.visible);
  S.vis = new Set(pick.map((L) => L.id));
  S._visTouched = p !== "all";
  renderLayers();
  restyle();
}

// ------------------------------------------------------------------ cells pane
function shortCell(n) { const i = n.indexOf("__"); return i >= 0 ? n.slice(i + 2) : n; }
function libOf(n) { const i = n.indexOf("__"); return i >= 0 ? n.slice(0, i) : ""; }

// Plain words for a standard-cell name (sky130/gf180/ihp share most stems).
export function describeCell(name) {
  const s = shortCell(name).toLowerCase();
  const m = s.match(/^(.*?)(?:_(\d+))?$/);
  const base = m[1], drive = m[2];
  const D = [
    [/^dfrtp/, "D flip-flop with reset"], [/^dfrtn/, "D flip-flop (falling edge) with reset"], [/^dfstp/, "D flip-flop with set"],
    [/^dfbbp|^dfbbn/, "D flip-flop with set and reset"], [/^dfxtp|^dfxbp/, "D flip-flop"], [/^edf/, "D flip-flop with enable"],
    [/^sdf|^sedf/, "scan flip-flop (testable)"], [/^df/, "D flip-flop"], [/^dlx|^dlr|^dlatch|^dlclkp|^sdlclkp/, /clkp/.test(base) ? "clock gate" : "latch"],
    [/^clkinv/, "clock inverter"], [/^inv/, "inverter"], [/^clkbuf/, "clock buffer"], [/^clkdlybuf|^dlygate|^dlymetal|^clkdly/, "delay cell (fixes hold timing)"],
    [/^buf/, "buffer"], [/^xnor(\d)/, "$1-input XNOR"], [/^xor(\d)/, "$1-input XOR"], [/^nand(\d)/, "$1-input NAND"], [/^nor(\d)/, "$1-input NOR"],
    [/^and(\d)/, "$1-input AND"], [/^or(\d)/, "$1-input OR"], [/^a(\d+)oi/, "AND-OR-invert ($1)"], [/^o(\d+)ai/, "OR-AND-invert ($1)"],
    [/^a(\d+)o/, "AND-OR ($1)"], [/^o(\d+)a/, "OR-AND ($1)"], [/^mux(\d)/, "$1-to-1 multiplexer"], [/^fah|^fa/, "full adder"], [/^ha/, "half adder"],
    [/^maj/, "majority gate"], [/^decap/, "decoupling capacitor: steadies the supply"], [/^fill/, "filler: closes a gap in the row"],
    [/^tap/, "well tap: ties the wells to power"], [/^conb/, "constant 0 and 1"], [/^diode/, "antenna diode: protects gates during manufacturing"],
    [/^endcap/, "end cap: closes a row"],
  ];
  for (const [rx, words] of D) {
    const mm = base.match(rx);
    if (mm) return words.replace("$1", mm[1] || "") + (drive ? ", drive strength " + drive : "");
  }
  return "";
}

function renderCells(filter) {
  const host = $("lx-pane-cells");
  if (!host || !S.info) return;
  const cells = S.info.cells || [];
  const q = (filter ?? host.querySelector("#lx-cell-q")?.value ?? "").trim().toLowerCase();
  const total = cells.reduce((a, c) => a + c.count, 0);
  const byKind = {};
  for (const c of cells) (byKind[c.kind] = byKind[c.kind] || []).push(c);
  const logic = total - (byKind.physical || []).reduce((a, c) => a + c.count, 0);
  const bar = KIND_ORDER.filter((k) => byKind[k]).map((k) => {
    const n = byKind[k].reduce((a, c) => a + c.count, 0);
    return "<i style='flex:" + n + ";background:" + KINDS[k].color + "' title='" + esc(KINDS[k].label + ": " + n) + "'></i>";
  }).join("");
  const keepQ = host.querySelector("#lx-cell-q")?.value || "";
  host.innerHTML =
    "<div class='lx-census'><div class='lx-census-n'><b>" + total.toLocaleString() + "</b> cells placed" +
    (logic !== total ? "<span class='muted'> · " + logic.toLocaleString() + " doing logic</span>" : "") + "</div>" +
    "<div class='lx-census-bar'>" + bar + "</div></div>" +
    "<div class='lx-find'><input type='search' id='lx-cell-q' placeholder='Filter cells' value='" + esc(keepQ) + "' aria-label='Filter cells' spellcheck='false'/></div>" +
    (S.hl ? "<div class='lx-hl'><span>Highlighting <b>" + S.hl.total + "</b> × " + esc(shortCell(S.hl.cell)) + "</span><button class='btn btn-ghost btn-sm' data-hl-clear>Clear</button></div>" : "") +
    KIND_ORDER.filter((k) => byKind[k]).map((k) => {
      const list = byKind[k].filter((c) => !q || c.name.toLowerCase().includes(q) || describeCell(c.name).toLowerCase().includes(q));
      if (!list.length) return "";
      const n = list.reduce((a, c) => a + c.count, 0);
      return "<details class='lx-kind'" + (q || k !== "physical" ? " open" : "") + "><summary><i style='background:" + KINDS[k].color + "'></i>" +
        "<b>" + esc(KINDS[k].label) + "</b><span class='lx-n'>" + n.toLocaleString() + "</span></summary>" +
        (KINDS[k].hint ? "<p class='lx-kind-hint'>" + esc(KINDS[k].hint) + "</p>" : "") +
        list.map((c) => "<button class='lx-cell" + (S.hl && S.hl.cell === c.name ? " is-on" : "") + "' data-cell='" + esc(c.name) + "' title='" +
          esc(c.name + (describeCell(c.name) ? " — " + describeCell(c.name) : "") + ". " + c.w + " × " + c.h + " µm. Click to highlight every one.") + "'>" +
          "<span class='lx-cell-n'>" + esc(shortCell(c.name)) + "</span><span class='lx-cell-d'>" + esc(describeCell(c.name)) + "</span>" +
          "<span class='lx-n'>" + c.count + "</span></button>").join("") +
        "</details>";
    }).join("");
  const inp = host.querySelector("#lx-cell-q");
  if (keepQ && document.activeElement?.id === "lx-cell-q") { inp.focus(); inp.setSelectionRange(keepQ.length, keepQ.length); }
}

async function highlightCell(name, { quiet = false, zoom = false } = {}) {
  if (!S.info) return;
  if (S.hl && S.hl.cell === name && !quiet) { S.hl = null; renderCells(); S.canvas.paintOverlay(); return; }
  let r;
  try { r = await api.layoutInstances(S.info.sid, name); } catch (ex) { toast.show("Couldn't find the cells: " + (ex.message || ex), "warn"); return; }
  S.hl = { cell: name, boxes: r.boxes || [], total: r.total || 0 };
  renderCells();
  if (zoom === "ifHidden" && S.hl.boxes.length && S.canvas) {
    const vb = S.canvas.viewBox();
    const seen = S.hl.boxes.some((b) => b[0] < vb[2] && b[2] > vb[0] && b[1] < vb[3] && b[3] > vb[1]);
    zoom = !seen;
  }
  if (zoom && S.hl.boxes.length) {
    const b = S.hl.boxes.reduce((a, x) => [Math.min(a[0], x[0]), Math.min(a[1], x[1]), Math.max(a[2], x[2]), Math.max(a[3], x[3])], [Infinity, Infinity, -Infinity, -Infinity]);
    S.canvas.zoomToBox(b, 0.08);
  }
  S.canvas && S.canvas.paintOverlay();
  if (!quiet && r.truncated) toast.show("Showing the first " + r.boxes.length + " of " + r.total + ".", "info");
}

// ------------------------------------------------------------------ find pane
function renderFind() {
  const res = $("lx-find-res");
  if (!res || !S.info) return;
  const q = ($("lx-find-q")?.value || "").trim().toLowerCase();
  const labels = S.info.labels || [];
  if (!q) {
    // Without a query: the top-level pins, deduplicated (bus bits collapse).
    const seen = new Map();
    for (const l of labels) {
      const key = l.text.replace(/\[\d+\]$/, "[…]");
      if (!seen.has(key)) seen.set(key, { ...l, n: 0, key });
      seen.get(key).n += 1;
    }
    const pins = [...seen.values()].filter((l) => !/^(VPWR|VGND|VPB|VNB|vccd\d?|vssd\d?|VDD|VSS)$/i.test(l.text));
    res.innerHTML = labels.length
      ? "<div class='lx-res-h'>Pins and labels <span class='lx-n'>" + labels.length + "</span></div>" +
        pins.slice(0, 200).map((l) => "<button class='lx-res' data-x='" + l.x + "' data-y='" + l.y + "' data-q='" + esc(l.key.includes("[…]") ? l.key.replace("[…]", "[") : "") + "'>" +
          "<span class='lx-res-t'>" + esc(l.key) + "</span><span class='lx-res-s'>" + (l.n > 1 ? l.n + " labels" : esc(l.layer)) + "</span></button>").join("")
      : "<p class='muted lx-pad'>This view has no text labels. Type a cell name to find cells.</p>";
    return;
  }
  const hitsL = labels.filter((l) => l.text.toLowerCase().includes(q)).slice(0, 300);
  const hitsC = (S.info.cells || []).filter((c) => c.name.toLowerCase().includes(q) || describeCell(c.name).toLowerCase().includes(q)).slice(0, 100);
  res.innerHTML =
    (hitsL.length ? "<div class='lx-res-h'>Pins and labels <span class='lx-n'>" + hitsL.length + "</span></div>" +
      hitsL.map((l) => "<button class='lx-res' data-x='" + l.x + "' data-y='" + l.y + "'><span class='lx-res-t'>" + esc(l.text) +
        "</span><span class='lx-res-s'>" + esc(l.layer) + " · " + l.x.toFixed(2) + ", " + l.y.toFixed(2) + "</span></button>").join("") : "") +
    (hitsC.length ? "<div class='lx-res-h'>Cell types <span class='lx-n'>" + hitsC.length + "</span></div>" +
      hitsC.map((c) => "<button class='lx-res' data-fcell='" + esc(c.name) + "'><span class='lx-res-t'>" + esc(shortCell(c.name)) +
        "</span><span class='lx-res-s'>" + c.count + " placed" + (describeCell(c.name) ? " · " + esc(describeCell(c.name)) : "") + "</span></button>").join("") : "") +
    (!hitsL.length && !hitsC.length ? "<p class='muted lx-pad'>Nothing matches “" + esc(q) + "”.</p>" : "");
}

function onFindClick(e) {
  const b = e.target.closest(".lx-res");
  if (!b) return;
  if (b.dataset.fcell) { highlightCell(b.dataset.fcell, { zoom: true }); return; }
  if (b.dataset.q) { const inp = $("lx-find-q"); inp.value = b.dataset.q; renderFind(); return; }
  const x = +b.dataset.x, y = +b.dataset.y;
  const span = Math.max(4, Math.min(30, ((S.info.bbox[2] - S.info.bbox[0]) / 12)));
  S.canvas.zoomToBox([x - span / 2, y - span / 2, x + span / 2, y + span / 2], 0);
  S.pin = { x, y, t: performance.now() };
  S.canvas.paintOverlay();
}

// ------------------------------------------------------------------ checks pane
async function loadMarkers(tag) {
  const host = $("lx-pane-checks");
  if (host) host.innerHTML = "<p class='muted lx-pad'>Reading the run's check reports…</p>";
  let m;
  try { m = await api.layoutMarkers(tag); } catch (_e) { m = { sources: [] }; }
  if (tag !== S.tag) return;
  S.markers = m;
  renderChecks();
  S.canvas && S.canvas.paintOverlay();
}

function renderChecks() {
  const host = $("lx-pane-checks");
  const badge = $("lx-checks-n");
  if (!host) return;
  const srcs = (S.markers && S.markers.sources) || [];
  const total = srcs.reduce((a, s) => a + (s.total || 0), 0);
  if (badge) { badge.hidden = !total; badge.textContent = total > 999 ? "999+" : String(total); }
  if (!srcs.length) {
    host.innerHTML = "<p class='muted lx-pad'>This run has no DRC or XOR reports, so there are no markers to show. The checks run after routing; the Verify tab says which ran.</p>";
    return;
  }
  if (!total) {
    host.innerHTML = "<div class='lx-clean'><span class='vf-mark is-pass'></span><div><b>No markers</b>" +
      "<p>" + srcs.map((s) => esc(s.label)).join(", ") + " found nothing to flag in this run.</p></div></div>" +
      "<p class='muted lx-pad'>When a check does flag something, each marker shows up here and on the layout; click one to zoom to it.</p>" +
      "<button class='btn btn-ghost btn-sm lx-pad' data-go='verify' data-go-section='vf-drc'>Full sign-off in Verify " + icon("chevron", { size: 13 }) + "</button>";
    return;
  }
  host.innerHTML =
    "<label class='lx-check lx-pad'><input type='checkbox' id='lx-mk-show'" + (S.showMarkers ? " checked" : "") + "/><span>Show markers on the layout</span></label>" +
    srcs.map((s, si) => {
      if (!s.total) return "<div class='lx-mk-src is-clean'><span class='vf-mark is-pass'></span><b>" + esc(s.label) + "</b><span class='lx-n'>0</span></div>";
      return "<div class='lx-mk-src'><label class='lx-check'><input type='checkbox' data-mk-src='" + si + "'" + (s.hidden ? "" : " checked") + "/>" +
        "<span class='vf-mark is-fail'></span><b>" + esc(s.label) + "</b></label><span class='lx-n'>" + s.total + "</span></div>" +
        s.categories.map((c) => {
          const items = (s.items || []).filter((it) => it.cat === c.name);
          return "<details class='lx-kind'><summary><b class='lx-mk-cat'>" + esc(c.name) + "</b><span class='lx-n'>" + c.count + "</span></summary>" +
            (c.description ? "<p class='lx-kind-hint'>" + esc(c.description) + "</p>" : "") +
            items.slice(0, 300).map((it, ii) => "<button class='lx-res' data-mk='" + si + ":" + (s.items.indexOf(it)) + "'><span class='lx-res-t'>#" + (ii + 1) +
              "</span><span class='lx-res-s'>at " + it.bbox[0].toFixed(2) + ", " + it.bbox[1].toFixed(2) + " µm</span></button>").join("") +
            (items.length < c.count ? "<p class='muted lx-pad'>" + (c.count - items.length) + " more are in the report file.</p>" : "") +
            "</details>";
        }).join("") +
        "<p class='lx-pad'><a class='btn btn-ghost btn-sm' href='" + api.runFileUrl(S.tag, s.path) + "' download>" + esc(s.path.split("/").pop()) + "</a></p>";
    }).join("");
}

function onChecksClick(e) {
  const b = e.target.closest("[data-mk]");
  if (!b) return;
  const [si, ii] = b.dataset.mk.split(":").map(Number);
  const it = S.markers.sources[si].items[ii];
  if (!it) return;
  S.activeMarker = it;
  S.showMarkers = true;
  const bb = it.bbox, w = bb[2] - bb[0], h = bb[3] - bb[1];
  const pad = Math.max(w, h, 0.6) * 2;
  S.canvas.zoomToBox([bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad], 0);
  document.querySelectorAll("#lx-pane-checks [data-mk]").forEach((x) => x.classList.toggle("is-on", x === b));
}

function onChecksChange(e) {
  if (e.target.id === "lx-mk-show") S.showMarkers = e.target.checked;
  else if (e.target.dataset.mkSrc) S.markers.sources[+e.target.dataset.mkSrc].hidden = !e.target.checked;
  S.canvas && S.canvas.paintOverlay();
}

// ------------------------------------------------------------------ probe / inspector
async function probeAt(x, y, p) {
  if (!S.info || S.canvas.mode === "measure") return;
  const r = Math.max(S.canvas.scale * 3, 0.002);
  let res;
  try { res = await api.layoutProbe(S.info.sid, x, y, r); } catch (_e) { return; }
  const hits = (res && res.hits) || [];
  S.sel = { hits, x, y };
  S.canvas.paintOverlay();
  showInspector(p.sx, p.sy);
}

function showInspector(sx, sy) {
  const el = $("lx-inspect");
  const hits = S.sel.hits;
  if (!hits.length) {
    el.innerHTML = "<button class='lx-x' aria-label='Close'>×</button><p class='muted'>Nothing on the visible layers here.</p>" +
      "<p class='lx-mono'>" + S.sel.x.toFixed(3) + ", " + S.sel.y.toFixed(3) + " µm</p>";
  } else {
    const h = hits[0];
    const others = [...new Set(hits.slice(1).map((x) => x.layer))].filter((l) => l !== h.layer).slice(0, 8);
    const cell = h.cell;
    const kind = cell ? (S.info.cells.find((c) => c.name === cell) || {}) : null;
    const desc = cell ? describeCell(cell) : "";
    const w = h.box[2] - h.box[0], hh = h.box[3] - h.box[1];
    el.innerHTML =
      "<button class='lx-x' aria-label='Close'>×</button>" +
      "<div class='lx-in-layer'><i class='lx-sw' style='background:" + esc(h.fill) + ";border-color:" + esc(h.fill) + "'></i><b>" + esc(h.layer) + "</b><span class='lx-src'>" + esc(h.src) + "</span></div>" +
      (h.about ? "<p class='lx-in-about'>" + esc(h.about[0].toUpperCase() + h.about.slice(1)) + ".</p>" : "") +
      (h.text ? "<p class='lx-in-row'><span>Label</span><b>" + esc(h.text) + "</b></p>" : "<p class='lx-in-row'><span>Shape</span><b>" + fmtUm(w) + " × " + fmtUm(hh) + "</b></p>") +
      (cell ? "<div class='lx-in-cell'><div class='lx-in-row'><span>In cell</span><b title='" + esc(cell) + "'>" + esc(shortCell(cell)) + "</b></div>" +
        (desc ? "<p class='lx-in-about'>" + esc(desc[0].toUpperCase() + desc.slice(1)) + ".</p>" : "") +
        (kind && kind.count ? "<p class='lx-in-row'><span>Used</span><b>" + kind.count + " times</b></p>" : "") +
        "<div class='lx-in-act'>" +
        "<button class='btn btn-ghost btn-sm' data-in='hl'>Highlight all " + (kind && kind.count ? kind.count : "") + "</button>" +
        "<button class='btn btn-ghost btn-sm' data-in='zoom'>Zoom to cell</button>" +
        (libOf(cell) ? "<button class='btn btn-ghost btn-sm' data-in='lib' title='Pins, timing and power of this cell in the PDK library'>In Cells " + icon("chevron", { size: 12 }) + "</button>" : "") +
        "</div></div>" : "<p class='lx-in-row'><span>In</span><b>top level (" + esc(S.info.top) + ")</b></p>") +
      (others.length ? "<p class='lx-in-also'>Also here: " + others.map(esc).join(", ") + "</p>" : "");
  }
  el.hidden = false;
  const vw = $("lx-view"), view = { width: vw.clientWidth, height: vw.clientHeight };   // CSS px, like sx/sy
  const W = el.offsetWidth, H = el.offsetHeight;
  let left = sx + 16, top = sy + 16;
  if (left + W > view.width - 8) left = Math.max(8, sx - W - 16);
  if (top + H > view.height - 8) top = Math.max(8, view.height - H - 8);
  el.style.left = left + "px";
  el.style.top = top + "px";
}

function onInspectClick(e) {
  if (e.target.closest(".lx-x")) { clearSelection(); return; }
  const b = e.target.closest("[data-in]");
  if (!b || !S.sel || !S.sel.hits.length) return;
  const h = S.sel.hits[0];
  if (b.dataset.in === "hl") highlightCell(h.cell, { quiet: true });
  else if (b.dataset.in === "zoom" && h.cell_box) S.canvas.zoomToBox(h.cell_box, 0.25);
  else if (b.dataset.in === "lib") {
    const pdk = S.src && S.src.pdk, scl = S.src && (S.src.scl || libOf(h.cell));
    import("./cells.js").then((m) => m.openCell(h.cell, { pdk, scl })).catch(() => toast.show("The Cells tab couldn't open.", "warn"));
  }
}

function hideInspector() { const el = $("lx-inspect"); if (el) el.hidden = true; }
function clearSelection() {
  S.sel = null; S.pin = null; S.activeMarker = null;
  hideInspector();
  S.canvas && S.canvas.paintOverlay();
}

// ------------------------------------------------------------------ 3D
function toggle3d(on) {
  const want = on ?? !S.mode3d;
  if (want && !S.info) return;
  if (want && !S.three) {
    S.three = new Layout3D($("lx-view"), { onKey: (k) => keyCmd(k) });
    if (!S.three.ok) {
      toast.show("This browser can't draw WebGL, so the 3D view isn't available. GDS3D (below) shows the stack in 3D.", "warn");
      S.three.destroy(); S.three = null;
      return;
    }
    S.three.setBg(BG[S.bg] || BG.dark);
    S.three.setVisible(S.vis);
    const z = $("lx-3d-z"), sp = $("lx-3d-s");
    z.addEventListener("input", () => { S.three.setZScale(+z.value); $("lx-3d-zv").textContent = "×" + z.value; });
    sp.addEventListener("input", () => S.three.setSpread(+sp.value));
    $("lx-3d-reset").addEventListener("click", () => S.three.reset());
  }
  S.mode3d = want;
  $("lx-view").classList.toggle("is-3d", want);
  $("lx-3dctl").hidden = !want;
  document.querySelector("[data-lx='3d']")?.setAttribute("aria-pressed", want ? "true" : "false");
  document.querySelector("[data-lx='2d']")?.setAttribute("aria-pressed", want ? "false" : "true");
  hideInspector();
  if (want) {
    S.three.show(true);
    load3d();
    S.three.cv.focus({ preventScroll: true });
  } else {
    S.three && S.three.show(false);
    S.canvas.over.focus({ preventScroll: true });
    paintBadge();
  }
}

async function load3d() {
  if (!S.three || !S.info) return;
  const bb = S.info.bbox;
  const vb = S.canvas.viewBox();
  const zoomed = (vb[2] - vb[0]) < (bb[2] - bb[0]) * 0.9 || (vb[3] - vb[1]) < (bb[3] - bb[1]) * 0.9;
  const box = zoomed ? vb.map((v) => +v.toFixed(4)) : null;
  const key = S.info.sid + "|" + (box ? box.join(",") : "all");
  if (key === S.meshKey && S.three.layers.length) { S.three.show(true); paint3dBadge(); return; }
  S.meshKey = key;
  setBusy(true);
  hideMsg();
  try {
    const r = await fetch("/api/layout/mesh?sid=" + encodeURIComponent(S.info.sid) + (box ? "&box=" + box.join(",") : ""));
    if (!r.ok) {
      let msg = "HTTP " + r.status;
      try { msg = (await r.json()).error || msg; } catch (_e) {}
      S.meshKey = "";
      showMsg("<h3>3D isn't drawn for this view</h3><p>" + esc(msg) + "</p><button class='btn btn-ghost btn-sm' data-back2d>Back to 2D</button>");
      $("lx-msg").querySelector("[data-back2d]")?.addEventListener("click", () => { hideMsg(); toggle3d(false); });
      return;
    }
    const buf = await r.arrayBuffer();
    if (key !== S.meshKey) return;
    const head = S.three.load(buf);
    S.three.setVisible(S.vis);
    S._3dhead = head;
    paint3dBadge();
    if (!head.layers.length) showMsg("<h3>No layers to stack</h3><p>None of this view's layers are in the PDK's 3D stack.</p>");
  } catch (ex) {
    S.meshKey = "";
    toast.show("3D failed: " + (ex.message || ex), "error");
  } finally {
    setBusy(false);
  }
}

function paint3dBadge() {
  const el = $("lx-badge");
  const h = S._3dhead;
  if (!el || !h) return;
  const w = h.extent[2] - h.extent[0], hh = h.extent[3] - h.extent[1];
  el.innerHTML = "<b>3D · " + (h.clipped ? "this view" : "whole chip") + "</b><span>" + fmtUm(w) + " × " + fmtUm(hh) +
    " · " + (h.stack.startsWith("gds3d:") ? "real stack heights" : "generic heights") + "</span>";
  el.title = h.stack.startsWith("gds3d:") ? "Layer heights from GDS3D's process file " + h.stack.slice(6) :
    "No GDS3D process file for this PDK is installed, so layers are evenly spaced in stacking order.";
}

// ------------------------------------------------------------------ toolbar
function toggleMeasure(on) {
  const m = on ?? S.canvas.mode !== "measure";
  S.canvas.setMode(m ? "measure" : "pan");
  const b = document.querySelector("[data-lx='measure']");
  if (b) b.setAttribute("aria-pressed", m ? "true" : "false");
  if (m) { hideInspector(); flashHint("Drag to measure. It snaps to straight and 45° lines; hold Alt for any angle. Esc clears."); }
}
function toggleLabels() {
  S.labels = !S.labels;
  setPref("labels", S.labels ? "1" : "0");
  document.querySelector("[data-lx='labels']")?.setAttribute("aria-pressed", S.labels ? "true" : "false");
  restyle();
  S.canvas && S.canvas.paintOverlay();
}
function toggleOutlines() {
  S.outlines = !S.outlines;
  document.querySelector("[data-lx='detail']")?.setAttribute("aria-pressed", S.outlines ? "true" : "false");
  restyle();
}
function toggleBg() {
  S.bg = S.bg === "dark" ? "light" : "dark";
  setPref("bg", S.bg);
  $("lx-view").classList.toggle("is-light", S.bg === "light");
  restyle();
  if (S.three) S.three.setBg(BG[S.bg] || BG.dark);
  renderStages();
}
function toggleSide() {
  const ws = $("lx-ws");
  const off = !ws.classList.contains("side-off");
  ws.classList.toggle("side-off", off);
  setPref("side", off ? "0" : "1");
  document.querySelector("[data-lx='side']")?.setAttribute("aria-pressed", off ? "false" : "true");
}
function toggleFull() {
  const ws = $("lx-ws");
  if (document.fullscreenElement) document.exitFullscreen();
  else ws.requestFullscreen?.().catch(() => ws.classList.toggle("is-max"));
}

function flashHint(text) {
  const el = $("lx-hint");
  if (!el) return;
  el.textContent = text;
  el.classList.add("is-on");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("is-on"), 4200);
}

function onToolbar(e) {
  const b = e.target.closest("[data-lx]");
  if (!b || !S.canvas) { if (b && b.dataset.lx === "side") toggleSide(); return; }
  const a = b.dataset.lx;
  if (S.mode3d && S.three && ["fit", "zin", "zout"].includes(a)) {
    if (a === "fit") S.three.reset();
    else { S.three.cam.dist *= a === "zin" ? 1 / 1.4 : 1.4; S.three.draw(); }
    S.three.cv.focus({ preventScroll: true });
    return;
  }
  if (a === "fit") S.canvas.fit();
  else if (a === "zin") S.canvas.zoom(1.5);
  else if (a === "zout") S.canvas.zoom(1 / 1.5);
  else if (a === "measure") toggleMeasure();
  else if (a === "labels") toggleLabels();
  else if (a === "detail") toggleOutlines();
  else if (a === "bg") toggleBg();
  else if (a === "side") toggleSide();
  else if (a === "full") toggleFull();
  else if (a === "3d" || a === "2d") { if ((a === "3d") !== !!S.mode3d) toggle3d(a === "3d"); return; }
  (S.mode3d && S.three ? S.three.cv : S.canvas.over).focus({ preventScroll: true });
}

// ------------------------------------------------------------------ desktop viewers
const DESK = [
  { key: "klayout", name: "KLayout", for: "Inspect and measure", what: "The standard GDS viewer: every layer, rulers, cross-sections, and the DRC marker browser with this run's reports loaded." },
  { key: "openroad", name: "OpenROAD GUI", for: "Timing and congestion", what: "The place-and-route database: critical timing paths drawn on the chip, placement and routing heat maps, the clock tree." },
  { key: "magic", name: "Magic", for: "Edit transistors", what: "Edit the layout at transistor level with design rules checked as you draw, and extract a SPICE netlist." },
  { key: "gds3d", name: "GDS3D", for: "See it in 3D", what: "Fly through the real layer stack in 3D: metals, vias and devices at their true heights." },
];

let _routes = null;
async function renderDesk() {
  const host = $("lx-desk");
  if (!host) return;
  try { _routes = await toolRoutes(); } catch (_e) { _routes = {}; }
  const last = pref("tool", "klayout");
  host.innerHTML = DESK.map((t) => {
    const r = _routes[t.key] || { where: "install" };
    const status = { container: "Ready · runs in the LanEx container", host: "Ready · installed on this machine",
      nodisplay: "No display for windows", install: "Not installed" }[r.where];
    const ok = r.where === "container" || r.where === "host";
    return "<div class='lx-dcard" + (ok ? "" : " is-off") + (t.key === last ? " is-last" : "") + "'>" +
      "<div class='lx-dcard-top'><b>" + t.name + "</b><span class='lx-dfor'>" + t.for + "</span></div>" +
      "<p>" + t.what + "</p>" +
      "<div class='lx-dcard-foot'><span class='lx-dstat lt-" + r.where + "' title='" + esc(r.title || "") + "'>" + status + "</span>" +
      "<button class='btn btn-sm " + (ok ? "btn-ghost" : "btn-ghost") + "' data-desk='" + t.key + "'>" +
      (r.where === "install" ? "Set up in Tools" : "Open") + "</button></div></div>";
  }).join("");
  paintOpenMain();
}

function paintOpenMain() {
  const last = pref("tool", "klayout");
  const t = DESK.find((d) => d.key === last) || DESK[0];
  const lbl = $("lx-open-label");
  if (lbl) lbl.textContent = "Open in " + t.name;
  const menu = $("lx-open-menu");
  if (menu) menu.innerHTML = DESK.map((d) => {
    const r = (_routes || {})[d.key] || { where: "install" };
    return "<button role='menuitem' data-open='" + d.key + "'>" + d.name + "<span>" + d.for +
      (r.where === "install" ? " · not installed" : r.where === "nodisplay" ? " · no display" : "") + "</span></button>";
  }).join("");
}

// OpenROAD opens the ODB of the stage on screen (when that step wrote one).
function stagePath(tool) {
  if (tool !== "openroad" || !S.source || S.source === "final" || S.source.startsWith("final:")) return undefined;
  const st = [...(S.src.stages || []), ...(S.src.steps || [])].find((s) => s.source === S.source);
  if (!st) return undefined;
  if (!st.odb) {
    toast.show("This step's OpenROAD database wasn't kept on disk, so OpenROAD opens the final one.", "info");
    return undefined;
  }
  return st.odb;
}

async function openTool(tool) {
  setPref("tool", tool);
  paintOpenMain();
  document.querySelectorAll(".lx-dcard").forEach((c) => c.classList.toggle("is-last", c.querySelector("[data-desk]")?.dataset.desk === tool));
  if (!S.tag) return;
  await launchTool(tool, S.tag, { path: stagePath(tool) });
}

// ------------------------------------------------------------------ menus
function wireMenu(btnId, menuId, onPick, onOpen) {
  const btn = $(btnId), menu = $(menuId);
  if (!btn || !menu) return;
  const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
  btn.addEventListener("click", async (e) => {
    e.stopPropagation();
    const open = menu.hidden;
    document.querySelectorAll(".lx-menu").forEach((m) => { m.hidden = true; });
    if (open) { if (onOpen) await onOpen(menu); menu.hidden = false; btn.setAttribute("aria-expanded", "true"); menu.querySelector("button")?.focus(); }
    else close();
  });
  menu.addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { close(); onPick(b); } });
  menu.addEventListener("keydown", (e) => {
    const items = [...menu.querySelectorAll("button")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "Escape") { close(); btn.focus(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length]?.focus(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length]?.focus(); }
  });
  document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) close(); });
}

async function fillCommands(menu) {
  if (!S.commands && S.tag) {
    try { S.commands = await api.layoutCommands(S.tag); } catch (_e) { S.commands = {}; }
  }
  const c = S.commands || {};
  const rows = [
    ["klayout_flow", "LibreLane: open in KLayout", "Run from " + (c.cwd || "the design folder")],
    ["openroad_flow", "LibreLane: open in OpenROAD", "Same, with the OpenROAD GUI"],
    ["klayout", "KLayout directly", "The final GDS with the PDK's technology and layer colours"],
  ].filter(([k]) => c[k]);
  menu.innerHTML = rows.length
    ? rows.map(([k, t, s]) => "<button role='menuitem' data-copy='" + esc(c[k]) + "'>" + esc(t) + "<span>" + esc(s) + "</span><code>" + esc(c[k]) + "</code></button>").join("")
    : "<p class='muted lx-pad'>No commands for this run.</p>";
}

async function copy(text) {
  try { await navigator.clipboard.writeText(text); toast.show("Command copied", "success"); }
  catch (_e) { window.prompt("Copy the command:", text); }
}

function saveImage(kind) {
  if (!S.info || !S.canvas) return;
  if (S.mode3d && S.three && kind === "view") {
    const a = document.createElement("a");
    a.href = S.three.snapshot();
    a.download = (S.info.top || "layout") + "-3d.png";
    document.body.appendChild(a); a.click(); a.remove();
    return;
  }
  const st = (S.src.stages || []).find((s) => s.source === S.source);
  const base = (S.info.top || "layout") + "-" + (st ? st.id : "view");
  let url;
  if (kind === "view") {
    const dpr = S.canvas.dpr;
    url = renderUrl(S.canvas.viewBox(), Math.round(S.canvas.W * dpr), Math.round(S.canvas.H * dpr), 1 / dpr) + "&dl=" + encodeURIComponent(base + "-view.png");
  } else {
    const long = kind === "chip8k" ? 7680 : 3840;
    const bb = S.info.bbox, bw = bb[2] - bb[0], bh = bb[3] - bb[1];
    const pad = Math.max(bw, bh) * 0.03;
    const box = [bb[0] - pad, bb[1] - pad, bb[2] + pad, bb[3] + pad];
    const ar = (box[2] - box[0]) / (box[3] - box[1]);
    const w = ar >= 1 ? long : Math.round(long * ar), h = ar >= 1 ? Math.round(long / ar) : long;
    // res < 1 scales line widths and stipples up, so the picture reads like the
    // screen view instead of hairlines on a huge canvas.
    url = renderUrl(box, w, h, kind === "chip8k" ? 0.25 : 0.5) + (kind === "chip4k" ? "&os=2" : "") +
      "&dl=" + encodeURIComponent(base + "-" + (kind === "chip8k" ? "8k" : "4k") + ".png");
  }
  const a = document.createElement("a");
  a.href = url;
  a.download = "";
  document.body.appendChild(a);
  a.click();
  a.remove();
  toast.show("Saving the picture. Big ones take a few seconds.", "info");
}

// ------------------------------------------------------------------ wiring
function wireOnce() {
  if (S.wired) return;
  S.wired = true;
  mountRunBar($("layout-runbar"));
  ctx.onContext((d) => { if ($("sec-layout")?.classList.contains("section-active") && d.why !== "loaded" && d.why !== "settled") loadRuns(); });
  document.querySelector("#sec-layout .lx-tools")?.addEventListener("click", onToolbar);
  for (const [id, b] of [["labels", S.labels], ["detail", S.outlines]]) document.querySelector("[data-lx='" + id + "']")?.setAttribute("aria-pressed", b ? "true" : "false");
  if (pref("side", "1") === "0") { $("lx-ws").classList.add("side-off"); document.querySelector("[data-lx='side']")?.setAttribute("aria-pressed", "false"); }
  // side tabs
  const tabs = document.querySelectorAll("#lx-side [data-lx-pane]");
  const showPane = (name) => {
    tabs.forEach((t) => { const on = t.dataset.lxPane === name; t.classList.toggle("is-on", on); t.setAttribute("aria-selected", on ? "true" : "false"); });
    document.querySelectorAll("#lx-side .lx-pane").forEach((p) => { p.hidden = p.id !== "lx-pane-" + name; });
    setPref("pane", name);
  };
  tabs.forEach((t) => t.addEventListener("click", () => showPane(t.dataset.lxPane)));
  showPane(pref("pane", "layers"));
  $("lx-pane-layers").addEventListener("click", onLayersClick);
  $("lx-pane-layers").addEventListener("change", onLayersChange);
  $("lx-pane-cells").addEventListener("click", (e) => {
    if (e.target.closest("[data-hl-clear]")) { S.hl = null; renderCells(); S.canvas && S.canvas.paintOverlay(); return; }
    const b = e.target.closest("[data-cell]");
    if (b) { clearSelection(); highlightCell(b.dataset.cell, { zoom: "ifHidden" }); }
  });
  $("lx-pane-cells").addEventListener("input", (e) => { if (e.target.id === "lx-cell-q") renderCells(e.target.value); });
  $("lx-find-q").addEventListener("input", renderFind);
  $("lx-find-res").addEventListener("click", onFindClick);
  $("lx-pane-checks").addEventListener("click", onChecksClick);
  $("lx-pane-checks").addEventListener("change", onChecksChange);
  $("lx-inspect").addEventListener("click", onInspectClick);
  const mini = $("lx-mini");
  let dragging = false;
  mini.addEventListener("pointerdown", (e) => { dragging = true; mini.setPointerCapture(e.pointerId); miniJump(e); });
  mini.addEventListener("pointermove", (e) => { if (dragging) miniJump(e); });
  mini.addEventListener("pointerup", () => { dragging = false; });
  // desktop viewers
  $("lx-desk").addEventListener("click", (e) => { const b = e.target.closest("[data-desk]"); if (b) openTool(b.dataset.desk); });
  $("lx-open-main").addEventListener("click", () => openTool(pref("tool", "klayout")));
  wireMenu("lx-open-pick", "lx-open-menu", (b) => openTool(b.dataset.open), () => paintOpenMain());
  wireMenu("lx-save", "lx-save-menu", (b) => saveImage(b.dataset.save));
  wireMenu("lx-cmd", "lx-cmd-menu", (b) => { if (b.dataset.copy) copy(b.dataset.copy); }, fillCommands);
  document.addEventListener("fullscreenchange", () => $("lx-ws").classList.toggle("is-full", document.fullscreenElement === $("lx-ws")));
}

// Tests and the console reach the page state through this.
export function _layoutState() { return S; }
