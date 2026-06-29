// waves.js — canvas digital-waveform renderer (Phase 3.6). Draws one lane per
// signal from a parsed VCD (vcd.js), with zoom/pan, a movable cursor with value
// readout, radix toggle, and signal search. In-house (no heavyweight dep).
import { formatValue } from "./vcd.js";

export class WaveView {
  constructor(canvas, { laneHeight = 26, labelWidth = 160 } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.laneHeight = laneHeight;
    this.labelWidth = labelWidth;
    this.vcd = null;
    this.visible = [];        // signal ids shown, top to bottom
    this.radix = "hex";
    this.t0 = 0;              // left edge time
    this.pxPerTime = 1;       // zoom
    this.cursorTime = 0;
    this._locked = false;     // click to lock the cursor so values stay put
    this._bindEvents();
  }

  load(vcd, visibleIds) {
    this.vcd = vcd;
    this.visible = visibleIds || vcd.signals.slice(0, 12).map((s) => s.id);
    const span = Math.max(1, vcd.end);
    const plotW = Math.max(100, this.canvas.width - this.labelWidth);
    this.pxPerTime = plotW / span;
    this.t0 = 0;
    this.draw();
  }

  setRadix(r) { this.radix = r; this.draw(); }
  setVisible(ids) { this.visible = ids; this.draw(); }

  zoom(factor, anchorPx) {
    const anchorTime = this.t0 + (anchorPx - this.labelWidth) / this.pxPerTime;
    this.pxPerTime = Math.max(1e-6, this.pxPerTime * factor);
    this.t0 = anchorTime - (anchorPx - this.labelWidth) / this.pxPerTime;
    if (this.t0 < 0) this.t0 = 0;
    this.draw();
  }

  // Toolbar-driven zoom (anchored at the plot centre) + fit-to-window.
  zoomIn() { this.zoom(1.3, this.labelWidth + (this.canvas.width - this.labelWidth) / 2); }
  zoomOut() { this.zoom(1 / 1.3, this.labelWidth + (this.canvas.width - this.labelWidth) / 2); }
  fit() {
    if (!this.vcd) return;
    const span = Math.max(1, this.vcd.end);
    this.pxPerTime = Math.max(1e-6, (this.canvas.width - this.labelWidth) / span);
    this.t0 = 0;
    this.draw();
  }

  // Export the current waveform view as a PNG data-URL (for download).
  toPNG() {
    try { return this.canvas.toDataURL("image/png"); } catch (_e) { return null; }
  }

  _bindEvents() {
    const c = this.canvas;
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      // Wheel zooms the time axis (no modifier needed — the common expectation);
      // Shift+wheel pans. Ctrl/Cmd+wheel still zooms too.
      if (e.shiftKey) { this.t0 += (e.deltaY / this.pxPerTime); if (this.t0 < 0) this.t0 = 0; this.draw(); }
      else this.zoom(e.deltaY < 0 ? 1.2 : 1 / 1.2, e.offsetX);
    }, { passive: false });
    c.addEventListener("mousemove", (e) => {
      if (this._locked) return;             // cursor pinned by a click
      this.cursorTime = this.t0 + (e.offsetX - this.labelWidth) / this.pxPerTime;
      this.draw();
    });
    // Click locks/unlocks the cursor at that time so the per-signal value
    // readout stays put while you inspect it.
    c.addEventListener("click", (e) => {
      this.cursorTime = this.t0 + (e.offsetX - this.labelWidth) / this.pxPerTime;
      this._locked = !this._locked;
      this.draw();
    });
    c.style.cursor = "crosshair";
  }

  _color(name) {
    try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888"; }
    catch (_e) { return "#888"; }
  }

  draw() {
    const ctx = this.ctx;
    if (!ctx || !this.vcd) return;
    const W = this.canvas.width, H = this.canvas.height;
    const lh = this.laneHeight, lw = this.labelWidth;
    const accent = this._color("--accent") || "#8b5cf6";
    const text = this._color("--text") || "#c9d1d9";
    const border = this._color("--border") || "#30363d";
    const fail = this._color("--fail") || "#f85149";
    ctx.clearRect(0, 0, W, H);
    ctx.font = "11px ui-monospace, monospace";
    ctx.textBaseline = "middle";

    const cursorInView = (lw + (this.cursorTime - this.t0) * this.pxPerTime) >= lw;
    this.visible.forEach((id, row) => {
      const sig = this.vcd.byId[id];
      if (!sig) return;
      const y = row * lh;
      // label
      ctx.fillStyle = text;
      ctx.fillText(sig.name.slice(0, 22), 6, y + lh / 2);
      ctx.strokeStyle = border;
      ctx.beginPath(); ctx.moveTo(lw, y + lh); ctx.lineTo(W, y + lh); ctx.stroke();
      this._drawSignal(sig, y, W, accent, fail, text);
      // Per-signal value AT the cursor time — shown as a chip at the right edge
      // so clicking anywhere tells you every signal's value at that instant.
      if (cursorInView) {
        const val = formatValue(this._valueAt(sig, this.cursorTime), sig.width === 1 ? "bin" : this.radix);
        const txt = "=" + val;
        const tw = ctx.measureText(txt).width + 8;
        ctx.fillStyle = this._color("--surface-2") || "#161b22";
        ctx.fillRect(W - tw - 2, y + 3, tw, lh - 6);
        ctx.fillStyle = accent;
        ctx.fillText(txt, W - tw + 2, y + lh / 2);
      }
    });

    // cursor line + time label (brighter when locked)
    const cx = lw + (this.cursorTime - this.t0) * this.pxPerTime;
    if (cx >= lw && cx <= W) {
      ctx.strokeStyle = accent;
      ctx.lineWidth = this._locked ? 1.6 : 1;
      ctx.setLineDash(this._locked ? [] : [3, 3]);
      ctx.beginPath(); ctx.moveTo(cx, 0); ctx.lineTo(cx, H); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = accent;
      const label = "t=" + Math.round(this.cursorTime) + (this._locked ? " (locked)" : "");
      ctx.fillText(label, Math.min(cx + 4, W - 70), 8);
    }
  }

  _valueAt(sig, time) {
    let v = "x";
    for (const [t, val] of sig.changes) { if (t <= time) v = val; else break; }
    return v;
  }

  _drawSignal(sig, y, W, accent, fail, text) {
    const ctx = this.ctx;
    const lh = this.laneHeight, lw = this.labelWidth;
    const top = y + 4, bot = y + lh - 4, mid = y + lh / 2;
    const xOf = (t) => lw + (t - this.t0) * this.pxPerTime;
    ctx.strokeStyle = accent; ctx.lineWidth = 1.4; ctx.beginPath();
    let prev = "x", started = false;
    const draw = (t, val) => {
      const x = Math.max(lw, xOf(t));
      if (sig.width === 1) {
        const yv = val === "1" ? top : bot;
        if (!started) { ctx.moveTo(x, yv); started = true; }
        else {
          const yprev = prev === "1" ? top : bot;
          ctx.lineTo(x, yprev); ctx.lineTo(x, yv);
        }
      }
      prev = val;
    };
    for (const [t, val] of sig.changes) {
      if (xOf(t) > W) break;
      draw(t, val);
    }
    if (sig.width === 1) {
      const yv = prev === "1" ? top : bot;
      ctx.lineTo(W, yv);
    }
    ctx.stroke();

    if (sig.width > 1) {
      // bus: draw hex/dec labels in segments between changes
      ctx.fillStyle = text;
      let last = this.t0;
      let lastVal = this._valueAt(sig, this.t0);
      const segs = sig.changes.filter(([t]) => t >= this.t0);
      const ends = segs.map(([t]) => t).concat([this.t0 + (W - lw) / this.pxPerTime]);
      ctx.strokeStyle = accent; ctx.beginPath();
      ctx.moveTo(lw, top); ctx.lineTo(W, top); ctx.moveTo(lw, bot); ctx.lineTo(W, bot); ctx.stroke();
      let vi = 0;
      for (const e of ends) {
        const x0 = Math.max(lw, xOf(last)), x1 = Math.min(W, xOf(e));
        if (x1 - x0 > 24) {
          ctx.fillText(formatValue(lastVal, this.radix), x0 + 4, mid);
        }
        last = e;
        if (vi < segs.length) lastVal = segs[vi][1];
        vi++;
      }
    }
  }
}
