// cells-view.js — the Cells tab's real layout viewer and 3D view of one cell.
//
// The Layout card's quick drawing (cells.js) is the default. "Viewer" and "3D"
// open a KLayout session on the library's GDS with the selected cell as the
// top (controller/layoutview.open_cell_session) and reuse the Layout tab's own
// LayoutCanvas and Layout3D on it. One view is live at a time: switching cell,
// library, mode or tab tears it down, closes the server session and gives the
// WebGL context back.

import { api } from "./api.js";
import { esc } from "./cells-model.js";

const BG = "#0c1017";           // the card's drawing background, in every theme
const SCHEME_KEY = "ll.lx.scheme";   // the 3D colours, shared with the Layout tab
const SCHEMES = [["lanex", "LanEx"], ["metallic", "Metallic"], ["pdk", "PDK"]];

const V = {
  tok: 0,
  sid: "",
  info: null,
  canvas: null,
  three: null,
  vis: new Set(),
  host: null,
  reopened: 0,
};

function pref(d) { try { return localStorage.getItem(SCHEME_KEY) || d; } catch (_e) { return d; } }
function setPref(v) { try { localStorage.setItem(SCHEME_KEY, v); } catch (_e) {} }

// Close whatever is open. Safe to call at any time, as often as needed.
export function teardown() {
  V.tok++;
  if (V.canvas) { V.canvas.destroy(); V.canvas = null; }
  if (V.three) { V.three.destroy(); V.three = null; }
  if (V.sid) { api.cellViewClose(V.sid).catch(() => {}); V.sid = ""; }
  V.info = null;
  V.host = null;
}

// Show the cell in `host` as the viewer ("view") or the 3D stack ("3d").
// `hidden` is the card's set of switched-off layer names, shared with the
// drawing so a layer turned off stays off in every view.
export async function show(host, mode, { pdk, scl, cell, hidden }) {
  teardown();
  const tok = V.tok;
  V.host = host;
  host.innerHTML = "<div class='cl-lv-frame'><div class='cl-lay-skel cl-lv-skel'></div></div>" +
    "<p class='cl-dims'>Opening " + esc(cell) + " in KLayout…</p>";
  let info;
  try { info = await api.cellView(pdk, scl, cell); }
  catch (ex) { info = { ok: false, error: (ex && ex.message) || String(ex) }; }
  if (tok !== V.tok) {
    // The person moved on while it opened: let the server forget it too.
    if (info && info.ok && info.sid) api.cellViewClose(info.sid).catch(() => {});
    return;
  }
  if (!info || !info.ok) { unavailable(host, info); return; }
  V.sid = info.sid;
  V.info = info;
  V.vis = new Set(info.layers.filter((L) => L.visible && !hidden.has(L.label)).map((L) => L.id));
  if (mode === "3d") mount3d(host, tok, hidden);
  else mount2d(host, tok, hidden);
}

function unavailable(host, info) {
  const why = (info && info.error) || "the server did not answer";
  const lead = info && info.need === "klayout"
    ? "The layout viewer needs KLayout's Python package, which comes with LibreLane, and it isn't installed here (" + why + ")."
    : "The layout viewer can't show this cell: " + why + ".";
  host.innerHTML = "<p class='muted cl-p cl-lv-why'>" + esc(lead) + " The drawing still works: choose Drawing above.</p>";
}

function frame(is3d) {
  return "<div class='cl-lv-frame'><div class='lx-view cl-lv" + (is3d ? " is-3d" : "") + "'></div></div>";
}

function legend(hidden, colorOf) {
  return "<div class='cl-legend cl-lv-legend'>" + V.info.layers.map((L) =>
    "<button class='cl-lg" + (V.vis.has(L.id) ? "" : " is-off") + "' data-lvl='" + L.id + "' title='Show or hide " + esc(L.label) +
    (L.about ? ": " + esc(L.about) : "") + "'><i style='--f:" + esc(colorOf(L)) + "'></i>" + esc(L.label.replace(/\.drawing$/, "")) + "</button>").join("") + "</div>";
}

function wireLegend(host, hidden, onChange) {
  host.querySelector(".cl-lv-legend")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-lvl]");
    if (!b) return;
    const id = +b.dataset.lvl;
    const L = V.info.layers.find((x) => x.id === id);
    const on = !V.vis.has(id);
    if (on) V.vis.add(id); else V.vis.delete(id);
    if (L) { if (on) hidden.delete(L.label); else hidden.add(L.label); }
    b.classList.toggle("is-off", !on);
    onChange();
  });
}

// ------------------------------------------------------------------ 2D
async function mount2d(host, tok, hidden) {
  const { LayoutCanvas } = await import("./layoutcanvas.js");
  if (!V.info || V.host !== host || tok !== V.tok) return;
  const info = V.info;
  host.innerHTML = frame(false) + legend(hidden, (L) => L.fill) +
    "<div class='cl-lv-bar'><span class='cl-dims'>Drag to pan, scroll to zoom, F fits the cell, M measures. Drawn by KLayout" +
    (info.klayout ? " " + esc(info.klayout) : "") + " from " + esc(info.file) + " in the PDK's layer colours.</span>" +
    "<button class='btn btn-ghost btn-sm' data-lv-fit>Fit</button></div>";
  const view = host.querySelector(".cl-lv");
  const cv = new LayoutCanvas(view, {
    renderUrl: (box, w, h, dpr, o = {}) => renderUrl(box, w, h, o.backdrop ? 1 : 1 / dpr) + (o.os > 1 ? "&os=" + o.os : ""),
    bg: () => BG,
    onError: (ex) => {
      if (!ex || V.canvas !== cv) return;
      // The server dropped the session (restart, cache): reopen once, quietly.
      if (ex.status === 410 && Date.now() - V.reopened > 5000) { V.reopened = Date.now(); reopen(); return; }
      host.querySelector(".cl-lv-bar .cl-dims").textContent = "KLayout could not draw this view: " + (ex.message || ex);
    },
  });
  V.canvas = cv;
  cv.setLayout(info.bbox);
  wireLegend(host, hidden, () => cv.restyle());
  host.querySelector("[data-lv-fit]").addEventListener("click", () => { cv.fit(); cv.over.focus({ preventScroll: true }); });
}

function renderUrl(box, w, h, res) {
  const q = new URLSearchParams();
  q.set("sid", V.sid);
  if (box) q.set("box", box.map((v) => +v.toFixed(5)).join(","));
  q.set("w", String(w));
  q.set("h", String(h));
  q.set("vis", [...V.vis].join(","));
  q.set("labels", "1");
  q.set("bg", BG);
  if (res && res !== 1) q.set("res", String(+res.toFixed(4)));
  return "/api/layout/render?" + q.toString();
}

// Open the same cell again in the same view (after the server forgot it).
async function reopen() {
  const host = V.host, info = V.info;
  if (!host || !info) return;
  const is3d = !!V.three;
  const cell = info.top;
  const [, pdk, scl] = String(info.sid).split("::");
  const hidden = new Set(info.layers.filter((L) => !V.vis.has(L.id)).map((L) => L.label));
  if (pdk && scl) await show(host, is3d ? "3d" : "view", { pdk, scl, cell, hidden });
}

// ------------------------------------------------------------------ 3D
async function mount3d(host, tok, hidden) {
  const { Layout3D, schemeColor } = await import("./layout3d.js");
  if (!V.info || V.host !== host || tok !== V.tok) return;
  host.innerHTML = frame(true) + "<div class='cl-lv-legend-slot'></div>" +
    "<div class='cl-lv-bar'><span class='cl-lv-k' id='cl-lv-schemek'>Colours</span>" +
    "<span class='seg' role='group' aria-labelledby='cl-lv-schemek'>" + SCHEMES.map(([k, l]) =>
      "<button class='seg-btn' data-scheme='" + k + "' aria-pressed='false'>" + l + "</button>").join("") + "</span>" +
    "<span class='cl-dims cl-lv-note'>Building the 3D model…</span>" +
    "<button class='btn btn-ghost btn-sm' data-lv-fit>Reset view</button></div>";
  const view = host.querySelector(".cl-lv");
  const three = new Layout3D(view, {});
  if (!three.ok) {
    three.destroy();
    host.innerHTML = "<p class='muted cl-p cl-lv-why'>This browser can't draw WebGL, so the 3D view isn't available. The drawing and the viewer still work.</p>";
    return;
  }
  V.three = three;
  three.setBg(BG);
  three.setScheme(pref("lanex"));
  three.show(true);
  const paintScheme = () => host.querySelectorAll("[data-scheme]").forEach((b) => {
    const on = b.dataset.scheme === three.scheme;
    b.setAttribute("aria-pressed", on ? "true" : "false");
    b.classList.toggle("is-active", on);
  });
  paintScheme();
  const note = host.querySelector(".cl-lv-note");
  let head = null;
  try {
    const r = await fetch("/api/layout/mesh?sid=" + encodeURIComponent(V.sid));
    if (!r.ok) {
      let msg = "HTTP " + r.status;
      try { msg = (await r.json()).error || msg; } catch (_e) {}
      throw new Error(msg);
    }
    const buf = await r.arrayBuffer();
    if (tok !== V.tok) return;
    head = three.load(buf, { animate: true });
  } catch (ex) {
    if (tok !== V.tok) return;
    note.textContent = "The 3D model could not be built: " + ((ex && ex.message) || ex) + ".";
    return;
  }
  three.setVisible(V.vis);
  // Only layers that have a height in the stack are in 3D: list those.
  const ids = new Set(head.layers.map((L) => L.id));
  const colorOf = (L) => { const m = three.layers.find((x) => x.id === L.id); return m ? m.hex : schemeColor(three.scheme, { name: L.name, color: L.fill }); };
  const keep = V.info.layers;
  V.info = Object.assign({}, V.info, { layers: keep.filter((L) => ids.has(L.id)) });
  host.querySelector(".cl-lv-legend-slot").outerHTML = legend(hidden, colorOf);
  V.info = Object.assign({}, V.info, { layers: keep });
  wireLegend(host, hidden, () => three.setVisible(V.vis));
  const stack = String(head.stack || "");
  note.textContent = "Drag to turn, right-drag to move, scroll to zoom. " +
    (stack.startsWith("gds3d") ? "Heights from the PDK's GDS3D process file, stretched so the thin layers read."
      : stack.startsWith("d25") ? "Heights from the PDK's KLayout 2.5D stack, stretched so the thin layers read."
      : "This PDK has no 3D stack file, so the layers are evenly spaced in their real order.");
  host.querySelector(".cl-lv-bar .seg").addEventListener("click", (e) => {
    const b = e.target.closest("[data-scheme]");
    if (!b) return;
    setPref(b.dataset.scheme);
    three.setScheme(b.dataset.scheme);
    paintScheme();
    host.querySelectorAll(".cl-lv-legend [data-lvl]").forEach((btn) => {
      const m = three.layers.find((x) => x.id === +btn.dataset.lvl);
      if (m) btn.querySelector("i").style.setProperty("--f", m.hex);
    });
  });
  host.querySelector("[data-lv-fit]").addEventListener("click", () => { three.reset(true, { animate: true }); three.cv.focus({ preventScroll: true }); });
}
