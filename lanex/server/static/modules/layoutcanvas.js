// layoutcanvas.js — the Layout tab's interactive viewer surface.
//
// KLayout draws the pictures on the server (controller/layoutview.py); this
// module owns the camera and the interaction, the way a map viewer does:
//   * every pan / zoom moves the last picture instantly (no waiting), and a
//     sharp one for the new viewport is asked for once the hand stops;
//   * a whole-chip backdrop sits under it, so zooming out never shows a void;
//   * markers, highlights, the ruler and the selection are drawn here, on an
//     overlay canvas, so they react at frame rate and stay clickable.
// World coordinates are layout µm with y up; screen is CSS px with y down.

const ZOOM_STEP = 1.25;
const MAX_ZOOM_UM_PER_PX = 1e4;
const MIN_ZOOM_UM_PER_PX = 0.0005;   // 0.5 nm per pixel: far below any rule

export class LayoutCanvas {
  constructor(wrap, opts) {
    this.wrap = wrap;
    this.opts = opts;            // { renderUrl(box,w,h,dpr), onView(), onClick(x,y,ev), onHover(x,y), onBusy(b), bg() }
    this.base = document.createElement("canvas");
    this.base.className = "lx-cv";
    this.over = document.createElement("canvas");
    this.over.className = "lx-cv lx-cv-over";
    this.over.tabIndex = 0;
    this.over.setAttribute("role", "application");
    this.over.setAttribute("aria-label", "Layout view. Drag to pan, scroll to zoom, F to fit, M to measure.");
    wrap.prepend(this.over);
    wrap.prepend(this.base);
    this.bbox = null;            // layout extent (µm)
    this.cx = 0; this.cy = 0; this.scale = 1;   // camera: centre (µm) and µm per CSS px
    this.W = 1; this.H = 1; this.dpr = 1;
    this.img = null;             // { bm, box } sharp picture of a viewport
    this.backdrop = null;        // { bm, box } whole-chip picture
    this.seq = 0;
    this.inflight = false;
    this.dirty = false;
    this.timer = 0;
    this.mode = "pan";           // "pan" | "measure"
    this.rulers = [];            // [{a:[x,y], b:[x,y]}]
    this.drawOverlay = null;     // (ctx, view) => void, set by the page
    this._ptr = null;
    this._wire();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(wrap);
    this._resize();
  }

  // ---------------------------------------------------------------- geometry
  w2s(x, y) { return [this.W / 2 + (x - this.cx) / this.scale, this.H / 2 - (y - this.cy) / this.scale]; }
  s2w(sx, sy) { return [this.cx + (sx - this.W / 2) * this.scale, this.cy - (sy - this.H / 2) * this.scale]; }
  viewBox() {
    const hw = (this.W / 2) * this.scale, hh = (this.H / 2) * this.scale;
    return [this.cx - hw, this.cy - hh, this.cx + hw, this.cy + hh];
  }
  view() { return { w2s: (x, y) => this.w2s(x, y), s2w: (x, y) => this.s2w(x, y), scale: this.scale, W: this.W, H: this.H, box: this.viewBox() }; }

  setLayout(bbox, { keepView = false } = {}) {
    const had = this.bbox;
    this.bbox = bbox;
    this.img = null;
    this.backdrop = null;
    if (!keepView || !had || !this._overlaps(this.viewBox(), bbox)) this.fit(false);
    this.invalidate(true);
  }

  _overlaps(a, b) { return a[0] < b[2] && a[2] > b[0] && a[1] < b[3] && a[3] > b[1]; }

  fit(render = true) {
    if (!this.bbox) return;
    this.zoomToBox(this.bbox, 0.075, render);   // room for the I/O names round the die
  }

  zoomToBox(b, pad = 0.12, render = true) {
    const bw = Math.max(b[2] - b[0], 1e-3), bh = Math.max(b[3] - b[1], 1e-3);
    const px = this.W * (1 - 2 * pad), py = this.H * (1 - 2 * pad);
    this.cx = (b[0] + b[2]) / 2;
    this.cy = (b[1] + b[3]) / 2;
    this.scale = this._clampScale(Math.max(bw / Math.max(px, 10), bh / Math.max(py, 10)));
    this._changed(render);
  }

  zoomAt(sx, sy, factor) {
    const [wx, wy] = this.s2w(sx, sy);
    const ns = this._clampScale(this.scale / factor);
    this.cx = wx - (sx - this.W / 2) * ns;
    this.cy = wy + (sy - this.H / 2) * ns;
    this.scale = ns;
    this._changed(true);
  }

  zoom(factor) { this.zoomAt(this.W / 2, this.H / 2, factor); }

  panBy(dx, dy) {           // screen px
    this.cx -= dx * this.scale;
    this.cy += dy * this.scale;
    this._changed(true);
  }

  centerOn(x, y) { this.cx = x; this.cy = y; this._changed(true); }

  _clampScale(s) {
    let max = MAX_ZOOM_UM_PER_PX;
    if (this.bbox) max = Math.max((this.bbox[2] - this.bbox[0]) / 40, (this.bbox[3] - this.bbox[1]) / 40, 1e-3);
    return Math.min(Math.max(s, MIN_ZOOM_UM_PER_PX), max);
  }

  _changed(render) {
    this.paint();
    this.opts.onView && this.opts.onView(this.view());
    if (render) this.invalidate();
  }

  // ---------------------------------------------------------------- rendering
  // Ask for a sharp picture once interaction pauses. One request in flight at
  // a time; the newest viewport wins.
  invalidate(withBackdrop = false) {
    if (withBackdrop) this._loadBackdrop();
    clearTimeout(this.timer);
    clearTimeout(this._refineT);
    this.seq++;                 // a refine pass already in flight is now stale
    this.timer = setTimeout(() => this._render(), 70);
  }

  // Layer visibility, depth or colours changed: everything drawn is stale.
  restyle() {
    this._loadBackdrop();
    this.invalidate();
  }

  async _loadBackdrop() {
    if (!this.bbox) return;
    const bb = this.bbox;
    const bw = bb[2] - bb[0], bh = bb[3] - bb[1];
    const longSide = 1600;
    const pad = 0.02;
    const box = [bb[0] - bw * pad, bb[1] - bh * pad, bb[2] + bw * pad, bb[3] + bh * pad];
    const ar = (box[2] - box[0]) / Math.max(box[3] - box[1], 1e-6);
    const w = ar >= 1 ? longSide : Math.round(longSide * ar);
    const h = ar >= 1 ? Math.round(longSide / ar) : longSide;
    const token = (this._bdTok = (this._bdTok || 0) + 1);
    try {
      const bm = await this._fetch(this.opts.renderUrl(box, w, h, 1, { backdrop: true, os: 2 }));
      if (token !== this._bdTok) return;
      this.backdrop = { bm, box };
      this.paint();
      this.opts.onView && this.opts.onView(this.view());   // the minimap draws from it
    } catch (_e) { /* the sharp render reports errors */ }
  }

  // Two passes: a fast one as soon as the hand stops, then (if the view stays
  // put) an antialiased one: KLayout's oversampling blends the dense layers
  // the way a die photo looks instead of a moiré of stipples.
  async _render(refine = false) {
    if (!this.bbox || this.W < 4 || this.H < 4) return;
    if (this.inflight) { this.dirty = true; return; }
    clearTimeout(this._refineT);
    this.inflight = true;
    this.dirty = false;
    const seq = ++this.seq;
    const box = this.viewBox();
    const dpr = this.dpr;
    const w = Math.round(this.W * dpr), h = Math.round(this.H * dpr);
    // Oversampling costs ~os² of the pixels; keep the refined pass near a second.
    const os = refine ? (w * h <= 2.2e6 ? 3 : 2) : 1;
    if (!refine) this.opts.onBusy && this.opts.onBusy(true);
    try {
      const bm = await this._fetch(this.opts.renderUrl(box, w, h, dpr, { os }));
      if (seq === this.seq) {
        if (this.img && this.img.bm && this.img.bm.close) this.img.bm.close();
        this.img = { bm, box };
        this.paint();
        if (!refine && this.refine !== false) this._refineT = setTimeout(() => this._render(true), 260);
      }
      this.opts.onError && this.opts.onError(null);
    } catch (ex) {
      this.opts.onError && this.opts.onError(ex);
    } finally {
      this.inflight = false;
      if (!refine) this.opts.onBusy && this.opts.onBusy(false);
      if (this.dirty) this._render();
    }
  }

  async _fetch(url) {
    const r = await fetch(url);
    if (!r.ok) {
      let msg = "HTTP " + r.status;
      try { const j = await r.json(); msg = j.error || msg; } catch (_e) {}
      const err = new Error(msg);
      err.status = r.status;
      throw err;
    }
    const blob = await r.blob();
    return await createImageBitmap(blob);
  }

  _resize() {
    const r = this.wrap.getBoundingClientRect();
    const W = Math.max(1, Math.round(r.width)), H = Math.max(1, Math.round(r.height));
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    if (W === this.W && H === this.H && dpr === this.dpr) return;
    const first = this.W <= 1;
    this.W = W; this.H = H; this.dpr = dpr;
    for (const c of [this.base, this.over]) {
      c.width = Math.round(W * dpr);
      c.height = Math.round(H * dpr);
      c.style.width = W + "px";
      c.style.height = H + "px";
    }
    if (first && this.bbox) this.fit(false);
    this.paint();
    if (this.bbox) this.invalidate();
  }

  paint() {
    const ctx = this.base.getContext("2d");
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.fillStyle = (this.opts.bg && this.opts.bg()) || "#06080d";
    ctx.fillRect(0, 0, this.W, this.H);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    for (const pic of [this.backdrop, this.img]) {
      if (!pic) continue;
      const [x1, y1] = this.w2s(pic.box[0], pic.box[3]);
      const [x2, y2] = this.w2s(pic.box[2], pic.box[1]);
      ctx.drawImage(pic.bm, x1, y1, x2 - x1, y2 - y1);
    }
    this.paintOverlay();
  }

  paintOverlay() {
    const ctx = this.over.getContext("2d");
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.W, this.H);
    if (this.drawOverlay) this.drawOverlay(ctx, this.view());
    this._paintRulers(ctx);
    if (this._zbox) {
      const [a, b] = this._zbox;
      ctx.save();
      ctx.strokeStyle = "rgba(77,163,255,0.95)";
      ctx.fillStyle = "rgba(77,163,255,0.10)";
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1;
      ctx.fillRect(Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
      ctx.strokeRect(Math.min(a[0], b[0]) + 0.5, Math.min(a[1], b[1]) + 0.5, Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1]));
      ctx.restore();
    }
  }

  // ---------------------------------------------------------------- rulers
  _paintRulers(ctx) {
    const all = this._live ? this.rulers.concat([this._live]) : this.rulers;
    for (const r of all) {
      const [ax, ay] = this.w2s(r.a[0], r.a[1]);
      const [bx, by] = this.w2s(r.b[0], r.b[1]);
      ctx.save();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1.5;
      ctx.shadowColor = "rgba(0,0,0,0.85)";
      ctx.shadowBlur = 3;
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      // end ticks, perpendicular
      const len = Math.hypot(bx - ax, by - ay) || 1;
      const nx = -(by - ay) / len * 6, ny = (bx - ax) / len * 6;
      ctx.beginPath();
      ctx.moveTo(ax - nx, ay - ny); ctx.lineTo(ax + nx, ay + ny);
      ctx.moveTo(bx - nx, by - ny); ctx.lineTo(bx + nx, by + ny);
      ctx.stroke();
      const dx = r.b[0] - r.a[0], dy = r.b[1] - r.a[1];
      const d = Math.hypot(dx, dy);
      const label = fmtUm(d) + (Math.abs(dx) > 1e-9 && Math.abs(dy) > 1e-9 ? "  (Δx " + fmtUm(Math.abs(dx)) + ", Δy " + fmtUm(Math.abs(dy)) + ")" : "");
      ctx.font = "600 12px " + (getComputedStyle(document.body).getPropertyValue("--mono") || "monospace");
      const tw = ctx.measureText(label).width;
      const mx = (ax + bx) / 2, my = (ay + by) / 2;
      ctx.shadowBlur = 0;
      ctx.fillStyle = "rgba(6,8,13,0.86)";
      ctx.fillRect(mx - tw / 2 - 6, my - 22, tw + 12, 18);
      ctx.fillStyle = "#f2f7ff";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(label, mx, my - 13);
      ctx.restore();
    }
  }

  clearRulers() { this.rulers = []; this._live = null; this.paintOverlay(); }

  setMode(m) {
    this.mode = m;
    this.wrap.classList.toggle("is-measure", m === "measure");
  }

  // Snap ruler ends to 0/45/90 degrees (layout is Manhattan) unless Alt is held.
  _snapEnd(a, b, free) {
    if (free) return b;
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const adx = Math.abs(dx), ady = Math.abs(dy);
    if (adx > 2.4 * ady) return [b[0], a[1]];
    if (ady > 2.4 * adx) return [a[0], b[1]];
    const m = Math.max(adx, ady);
    return [a[0] + Math.sign(dx) * m, a[1] + Math.sign(dy) * m];
  }

  // ---------------------------------------------------------------- input
  _wire() {
    const el = this.over;
    el.addEventListener("contextmenu", (e) => e.preventDefault());
    el.addEventListener("wheel", (e) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      // Trackpad pinch arrives as ctrl+wheel with small deltas; mice send ±100.
      const dy = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      const f = Math.pow(1.0018, -dy * (e.ctrlKey ? 2.2 : 1));
      this.zoomAt(e.clientX - r.left, e.clientY - r.top, f);
    }, { passive: false });

    el.addEventListener("pointerdown", (e) => {
      el.focus({ preventScroll: true });
      const r = el.getBoundingClientRect();
      const sx = e.clientX - r.left, sy = e.clientY - r.top;
      el.setPointerCapture(e.pointerId);
      const zoomBox = e.button === 2 || (e.button === 0 && e.shiftKey);
      const measure = e.button === 0 && this.mode === "measure" && !zoomBox;
      this._ptr = { id: e.pointerId, sx, sy, lx: sx, ly: sy, moved: false, zoomBox, measure, button: e.button,
                    a: this.s2w(sx, sy) };
      if (e.button === 1) e.preventDefault();
    });
    el.addEventListener("pointermove", (e) => {
      const r = el.getBoundingClientRect();
      const sx = e.clientX - r.left, sy = e.clientY - r.top;
      this.opts.onHover && this.opts.onHover(...this.s2w(sx, sy));
      const p = this._ptr;
      if (!p || p.id !== e.pointerId) return;
      if (Math.hypot(sx - p.sx, sy - p.sy) > 3) p.moved = true;
      if (p.zoomBox) {
        this._zbox = [[p.sx, p.sy], [sx, sy]];
        this.paintOverlay();
      } else if (p.measure) {
        this._live = { a: p.a, b: this._snapEnd(p.a, this.s2w(sx, sy), e.altKey) };
        this.paintOverlay();
      } else if (p.moved) {
        this.wrap.classList.add("is-panning");
        this.cx -= (sx - p.lx) * this.scale;
        this.cy += (sy - p.ly) * this.scale;
        p.lx = sx; p.ly = sy;
        this.paint();
        this.opts.onView && this.opts.onView(this.view());
      }
    });
    const end = (e) => {
      const p = this._ptr;
      if (!p || p.id !== e.pointerId) return;
      this._ptr = null;
      this.wrap.classList.remove("is-panning");
      const r = el.getBoundingClientRect();
      const sx = e.clientX - r.left, sy = e.clientY - r.top;
      if (p.zoomBox) {
        this._zbox = null;
        if (p.moved && Math.abs(sx - p.sx) > 6 && Math.abs(sy - p.sy) > 6) {
          const a = this.s2w(p.sx, p.sy), b = this.s2w(sx, sy);
          this.zoomToBox([Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])], 0);
        } else if (p.button === 2) {
          this.zoomAt(sx, sy, 1 / ZOOM_STEP);     // right click: step out (as in KLayout)
        } else this.paintOverlay();
        return;
      }
      if (p.measure) {
        if (this._live && p.moved) this.rulers.push(this._live);
        this._live = null;
        this.paintOverlay();
        this.opts.onRulers && this.opts.onRulers(this.rulers);
        return;
      }
      if (p.moved) { this.invalidate(); return; }
      if (p.button === 0 && e.type === "pointerup") this.opts.onClick && this.opts.onClick(...this.s2w(sx, sy), { sx, sy, ev: e });
    };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
    el.addEventListener("dblclick", (e) => {
      const r = el.getBoundingClientRect();
      this.zoomAt(e.clientX - r.left, e.clientY - r.top, 2);
    });
    el.addEventListener("pointerleave", () => this.opts.onHover && this.opts.onHover(null, null));
    el.addEventListener("keydown", (e) => this._key(e));
  }

  _key(e) {
    if (e.ctrlKey || e.metaKey) return;
    const k = e.key;
    const step = Math.min(this.W, this.H) * 0.15;
    let handled = true;
    if (k === "f" || k === "F" || k === "F2" || k === "Home") this.fit();
    else if (k === "+" || k === "=") this.zoom(ZOOM_STEP);
    else if (k === "-" || k === "_") this.zoom(1 / ZOOM_STEP);
    else if (k === "ArrowLeft") this.panBy(step, 0);
    else if (k === "ArrowRight") this.panBy(-step, 0);
    else if (k === "ArrowUp") this.panBy(0, step);
    else if (k === "ArrowDown") this.panBy(0, -step);
    else if (k === "m" || k === "M") this.opts.onKey && this.opts.onKey("measure");
    else if (k === "Escape") { this.clearRulers(); this.opts.onKey && this.opts.onKey("escape"); }
    else if (this.opts.onKey && this.opts.onKey(k) === true) handled = true;
    else handled = false;
    if (handled) { e.preventDefault(); e.stopPropagation(); }
  }

  destroy() {
    this._ro.disconnect();
    this.base.remove();
    this.over.remove();
  }
}

// 1 decimal place of the most natural unit (nm below 1 µm, mm above 1000 µm).
export function fmtUm(v) {
  const a = Math.abs(v);
  if (a < 1) return +(v * 1000).toFixed(a < 0.1 ? 1 : 0) + " nm";
  if (a >= 1000) return +(v / 1000).toFixed(3) + " mm";
  return +v.toFixed(a < 10 ? 3 : a < 100 ? 2 : 1) + " µm";
}

// A "nice" scale-bar length (1, 2, 5 × 10^n µm) near `target` µm.
export function niceLength(target) {
  const p = Math.pow(10, Math.floor(Math.log10(target)));
  const m = target / p;
  return (m >= 5 ? 5 : m >= 2 ? 2 : 1) * p;
}
