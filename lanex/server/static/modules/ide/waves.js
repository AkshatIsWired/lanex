// waves.js — the RTL IDE's waveform viewer. Laid out the way GTKWave, Surfer,
// Vivado's Wave window and DVT's viewer all are, so nobody has to learn it:
//
//   toolbar   zoom · fit · previous/next change · number format · cursor,
//             marker and the time between them · PNG / CSV / GTKWave
//   signals   every scope and signal in the dump, searchable; click to add
//   names     the signals on screen; select, drag to reorder, right-click for
//             number format, colour, go to declaration, remove
//   values    each signal's value at the cursor (or under the mouse)
//   plot      a time ruler in real units, the waves, the cursor and marker
//   overview  the whole run with the visible window, drag to move it
//
// Mouse: click sets the cursor (snapping to a nearby change), right-click or
// Shift+click sets the marker, drag zooms into a range, Ctrl+wheel zooms,
// Shift+wheel pans, the wheel scrolls the signal list. A name is selected by
// clicking it and let go by clicking it again, clicking the empty space under
// the list, or Esc. Keys: ← → jump to the previous/next change, + − F zoom,
// Delete removes, M drops the marker.
//
// Canvas drawing is hi-DPI aware and draws only what is in view, with binary
// search into each signal's changes, so a long dump stays smooth.
import { formatValue, formatTime, indexAt, valueAt, vcdToCSV } from "./vcd.js";

const RH = 24;                 // row height (CSS px), names and plot alike
const VALS_W = 104;            // value column
const RADIXES = [["hex", "Hex"], ["dec", "Decimal"], ["signed", "Signed decimal"], ["bin", "Binary"], ["oct", "Octal"], ["ascii", "ASCII"]];
const QUICK_RADIX = ["hex", "dec", "signed", "bin"];
const COLORS = ["--wave-1", "--wave-2", "--wave-3", "--wave-4", "--wave-5", "--wave-6"];
const CONST_TYPES = new Set(["parameter", "localparam", "specparam"]);
// Integers and parameters read as numbers; everything else defaults to hex.
const DEC_TYPES = new Set(["integer", "parameter", "localparam", "int", "shortint", "longint", "byte", "real", "realtime", "time"]);
const CLOCK_RX = /^(clk|clock)|(_clk|clk_i|clk_in)$/i;
const RESET_RX = /^(rst|reset|rstn|rst_n|resetn|reset_n|nrst|arst|arst_n)$|(_rst|_rst_n|_reset)$/i;

const ICON = {
  list: "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' aria-hidden='true'><path d='M4 6h16M4 12h10M4 18h13'/></svg>",
  minus: "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' aria-hidden='true'><path d='M5 12h14'/></svg>",
  plus: "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' aria-hidden='true'><path d='M12 5v14M5 12h14'/></svg>",
  fit: "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5M8 12h8'/></svg>",
  prev: "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M5 5v14M19 7l-7 5 7 5'/></svg>",
  next: "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M19 5v14M5 7l7 5-7 5'/></svg>",
  span: "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M5 4v16M19 4v16M8 12h8M10 9l-3 3 3 3M14 9l3 3-3 3'/></svg>",
  wave: "<svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M3 12h3l2-7 4 14 3-10 2 3h4'/></svg>",
  x: "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg>",
  caret: "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M9 6l6 6-6 6'/></svg>",
  addAll: "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' aria-hidden='true'><path d='M12 5v14M5 12h14'/></svg>",
  rmAll: "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' aria-hidden='true'><path d='M5 12h14'/></svg>",
};

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Every declaration in the dump, aliases included (a port shows up in the
// testbench and in the design under test with the same id).
function varsOf(vcd) {
  if (vcd.vars && vcd.vars.length) return vcd.vars;
  return vcd.signals.map((s) => ({ ...s, base: s.name.replace(/\[.*$/, ""), path: s.scope.concat([s.name]).join(".") }));
}

// The signals shown before anyone picks: the testbench's own (what it drives
// and watches), clocks first and resets next, then the design's internal
// signals that aren't just the same ports again. Returns var paths.
export function defaultLanes(vcd, max = 24) {
  // Parameters are constants: useful to look up, noise in the first view.
  const vars = varsOf(vcd).filter((v) => !CONST_TYPES.has(v.type));
  if (!vars.length) return [];
  const depth = (v) => (v.scope || []).length;
  const top = Math.min(...vars.map(depth));
  const outer = vars.filter((v) => depth(v) === top);
  const seen = new Set(outer.map((v) => v.id));
  const names = new Set(outer.map((v) => v.base || v.name));
  const inner = [];
  for (const v of vars) {
    if (depth(v) <= top || seen.has(v.id) || names.has(v.base || v.name)) continue;
    seen.add(v.id);
    inner.push(v);
  }
  const rank = (v) => (CLOCK_RX.test(v.base || v.name) ? 0 : RESET_RX.test(v.base || v.name) ? 1 : 2);
  const ordered = outer.map((v, i) => [v, i]).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map((x) => x[0]);
  return ordered.concat(inner).slice(0, max).map((v) => v.path);
}

// 1, 2 or 5 times a power of ten, at least one tick.
function niceStep(raw) {
  if (!(raw > 0)) return 1;
  const e = Math.floor(Math.log10(raw));
  const f = raw / Math.pow(10, e);
  const n = f < 1.5 ? 1 : f < 3.5 ? 2 : f < 7.5 ? 5 : 10;
  return Math.max(1, n * Math.pow(10, e));
}

function readStore(key) {
  try { return JSON.parse(localStorage.getItem(key) || "null"); } catch (_e) { return null; }
}
function writeStore(key, val) {
  try { localStorage.setItem(key, JSON.stringify(val)); } catch (_e) { /* private window */ }
}

export class WaveView {
  // opts: { idPrefix, layoutKey(): string, onGoto(row), onGtkwave(), onSimulate(), onNote(msg, bad) }
  constructor(host, opts = {}) {
    this.host = host;
    this.opts = opts;
    this.vcd = null;
    this.rows = [];              // [{ path, id, radix, color }]
    this.sel = new Set();        // row paths
    this.anchor = null;          // shift-click range start
    this.radix = "hex";          // default for rows without their own
    this.t0 = 0;
    this.ppt = 1;                // CSS px per tick
    this.cursor = null;
    this.marker = null;
    this.hover = null;           // { x, row }
    this.drag = null;
    this.namesW = 210;
    this.treeOpen = null;
    this.treeFlip = new Set();   // scope paths opened/closed against the default (open to depth 2)
    this.colors = {};
    this._build();
    this._bind();
    this.showEmpty(true);
  }

  // ------------------------------------------------------------ public API

  // Load a parsed dump. The signal list and number formats come back from the
  // last time this testbench was open, so a re-run after an edit shows the
  // same picture with new data.
  load(vcd) {
    const key = this._layoutKey();
    const same = this.vcd && key === this._loadedKey;
    const keepZoom = same && this.vcd.end === vcd.end && this.rows.length && !this._fitted;
    this.vcd = vcd;
    this.vars = varsOf(vcd);
    this.varByPath = new Map(this.vars.map((v) => [v.path, v]));
    const saved = key ? readStore(key) : null;
    let rows = null;
    if (same && this.rows.length) {
      rows = this.rows.filter((r) => this.varByPath.has(r.path));
    } else if (saved && Array.isArray(saved.rows)) {
      rows = saved.rows.filter((r) => this.varByPath.has(r.p)).map((r) => ({ path: r.p, radix: r.r || null, color: r.c || null }));
      if (saved.radix) this.radix = saved.radix;
      if (saved.namesW) this.namesW = saved.namesW;
    }
    if (!rows || !rows.length) rows = defaultLanes(vcd).map((p) => ({ path: p, radix: null, color: null }));
    this.rows = rows.map((r) => ({ ...r, id: this.varByPath.get(r.path).id }));
    this.sel = same ? new Set([...this.sel].filter((p) => this.varByPath.has(p))) : new Set();
    if (!this.anchor || !this.sel.has(this.anchor)) this.anchor = null;
    if (!same) this.treeFlip.clear();
    this.hover = null;
    this.drag = null;
    this._closeMenu();
    if (this.treeOpen === null) this.treeOpen = saved && typeof saved.tree === "boolean" ? saved.tree : this.host.clientWidth > 1000;
    this._loadedKey = key;
    this._restoreEmpty();
    this.showEmpty(false);
    this._readColors();
    this._applyWidths();
    this._renderTree();
    this._renderRows();
    this._syncRadixButtons();
    this._layout();
    if (!keepZoom) {
      if (!same || (this.cursor !== null && this.cursor > vcd.end)) { this.cursor = null; this.marker = null; }
      this.fit();
    } else this.redraw();
    this._times();
  }

  showEmpty(on) {
    this.host.classList.toggle("is-empty", !!on);
  }

  // Back to "no waveform yet" (another project was opened): nothing of the
  // old dump stays on screen or answers a hover in the code.
  clear() {
    this.vcd = null;
    this.vars = [];
    this.varByPath = new Map();
    this.rows = [];
    this.sel = new Set();
    this.anchor = null;
    this.cursor = null;
    this.marker = null;
    this.hover = null;
    this.drag = null;
    this._loadedKey = null;
    this._fitted = false;
    this.treeFlip.clear();
    this._closeMenu();
    this._restoreEmpty();
    this.el.rowsEl.innerHTML = "";
    this.el.treeList.innerHTML = "";
    this.el.search.value = "";
    this.showEmpty(true);
  }

  _restoreEmpty() {
    if (!this._emptyHtml) return;
    this.host.querySelector(".wv-empty-body").innerHTML = this._emptyHtml;
    this._emptyHtml = null;
  }

  // A dump the built-in viewer can't show (too big, or FST): say so and
  // offer GTKWave instead.
  showTooBig(mb) {
    this._showElsewhere("<h4>This dump is " + mb + " MB</h4>" +
      "<p>That's more than the built-in viewer reads comfortably. GTKWave opens it fine; or dump fewer signals, " +
      "for example <code>$dumpvars(1, tb)</code> for the top level only, or <code>$dumpvars(0, tb.dut.core)</code> for one block.</p>");
  }
  showFst(name) {
    this._showElsewhere("<h4>" + esc(name) + " is an FST dump</h4>" +
      "<p>The built-in viewer reads VCD. GTKWave opens FST; or have the testbench write <code>$dumpfile(\"dump.vcd\")</code>.</p>");
  }
  _showElsewhere(html) {
    const keep = this.treeOpen;
    this.clear();
    this.treeOpen = keep;
    const body = this.host.querySelector(".wv-empty-body");
    this._emptyHtml = body.innerHTML;
    body.innerHTML = html + "<button class='btn btn-primary btn-sm' data-act='gtkwave'>Open in GTKWave</button>";
  }

  fit() {
    if (!this.vcd) return;
    // Hidden (another panel tab is showing): fit once there's a width.
    if (!this.host.clientWidth) { this._fitPending = true; return; }
    const span = Math.max(1, this.vcd.end);
    this.ppt = Math.max(1e-9, (this.plotW - 12) / span);
    this.t0 = 0;
    this._fitted = true;
    this.redraw();
  }
  zoomIn() { this._zoomAt(1.5, this.plotW / 2); }
  zoomOut() { this._zoomAt(1 / 1.5, this.plotW / 2); }

  // Whole view as an image: names, values at the cursor, ruler and every
  // row (not just the visible ones), at twice the screen's resolution.
  toPNG() {
    if (!this.vcd) return null;
    const left = this.namesW + VALS_W, W = left + this.plotW, H = 26 + this.rows.length * RH + 8;
    const c = document.createElement("canvas");
    const k = 2;
    c.width = Math.round(W * k); c.height = Math.round(H * k);
    const ctx = c.getContext("2d");
    ctx.scale(k, k);
    ctx.fillStyle = this.colors.bg; ctx.fillRect(0, 0, W, H);
    ctx.font = "12px " + this.colors.mono;
    ctx.textBaseline = "middle";
    const tShow = this.cursor ?? null;
    this.rows.forEach((r, i) => {
      const y = 26 + i * RH, v = this.varByPath.get(r.path);
      ctx.fillStyle = this.colors.text;
      ctx.fillText(this._label(v), 8, y + RH / 2, this.namesW - 12);
      if (tShow !== null) {
        ctx.fillStyle = this.colors.muted;
        ctx.fillText(this._fmt(r, valueAt(this.vcd.byId[r.id], tShow)), this.namesW + 4, y + RH / 2, VALS_W - 8);
      }
      ctx.strokeStyle = this.colors.grid; ctx.beginPath(); ctx.moveTo(0, y + RH - 0.5); ctx.lineTo(W, y + RH - 0.5); ctx.stroke();
    });
    ctx.save(); ctx.translate(left, 0); this._drawRuler(ctx, this.plotW, false); ctx.restore();
    ctx.save(); ctx.translate(left, 26); ctx.beginPath(); ctx.rect(0, 0, this.plotW, H - 26); ctx.clip();
    this._drawRows(ctx, 0, this.rows.length, 0, false);
    this._drawMarks(ctx, H - 26);
    ctx.restore();
    try { return c.toDataURL("image/png"); } catch (_e) { return null; }
  }

  toCSV() {
    if (!this.vcd) return "";
    return vcdToCSV(this.vcd, this.rows.map((r) => r.id), this.radix,
      (id) => { const r = this.rows.find((x) => x.id === id); return r && this._radixOf(r, this.varByPath.get(r.path)); },
      (id) => { const r = this.rows.find((x) => x.id === id); return r ? this._label(this.varByPath.get(r.path)) : id; });
  }

  get visible() { return this.rows.map((r) => r.id); }

  // Add a signal (by path) and bring it into view. It flashes rather than
  // becoming the selection, so the number format buttons and ← → keep
  // applying to what the person selected (or to every signal).
  addSignal(path, { select = false } = {}) {
    const v = this.varByPath && this.varByPath.get(path);
    if (!v) return false;
    if (!this.rows.some((r) => r.path === path)) this.rows.push({ path, id: v.id, radix: null, color: null });
    if (select) { this.sel = new Set([path]); this.anchor = path; }
    this._changed();
    this._syncRadixButtons();
    const i = this.rows.findIndex((r) => r.path === path);
    this._scrollToRow(i);
    this._flash([i]);
    return true;
  }

  _flash(indexes) {
    for (const i of indexes) {
      const row = this.el.rowsEl.querySelector(".wv-row[data-i='" + i + "']");
      if (!row) continue;
      row.classList.remove("is-new");
      void row.offsetWidth;          // restart the animation
      row.classList.add("is-new");
    }
  }

  // ------------------------------------------------------------ DOM

  _build() {
    const p = this.opts.idPrefix || "wv-";
    this.host.classList.add("wv");
    this.host.tabIndex = -1;
    this.host.innerHTML =
      "<div class='wv-bar' role='toolbar' aria-label='Waveform'>" +
        "<button class='wv-btn wv-tree-btn' data-act='tree' aria-pressed='false' title='Every scope and signal in the dump. Click one to add it.'>" + ICON.list + "<span>Signals</span></button>" +
        "<span class='wv-sep' aria-hidden='true'></span>" +
        "<button class='wv-btn wv-ic' data-act='zoomout' id='" + p + "zoomout' title='Zoom out (−)' aria-label='Zoom out'>" + ICON.minus + "</button>" +
        "<button class='wv-btn wv-ic' data-act='zoomin' id='" + p + "zoomin' title='Zoom in (+)' aria-label='Zoom in'>" + ICON.plus + "</button>" +
        "<button class='wv-btn' data-act='fit' id='" + p + "fit' title='Show the whole run (F)'>" + ICON.fit + "<span>Fit</span></button>" +
        "<button class='wv-btn wv-ic' data-act='span' title='Zoom to the time between the cursor and the marker' aria-label='Zoom to cursor and marker'>" + ICON.span + "</button>" +
        "<span class='wv-sep' aria-hidden='true'></span>" +
        "<button class='wv-btn wv-ic' data-act='prev' title='Previous change of the selected signals (←)' aria-label='Previous change'>" + ICON.prev + "</button>" +
        "<button class='wv-btn wv-ic' data-act='next' title='Next change of the selected signals (→)' aria-label='Next change'>" + ICON.next + "</button>" +
        "<span class='wv-seg' role='group' aria-label='Number format (selected signals, or all)'>" +
          QUICK_RADIX.map((r) => "<button class='wv-btn wave-radix' data-radix='" + r + "' title='" +
            RADIXES.find((x) => x[0] === r)[1] + " (selected signals, or all of them)'>" + r + "</button>").join("") +
        "</span>" +
        "<span class='wv-times' aria-live='polite'>" +
          "<span class='wv-t wv-t-cur' title='Cursor: click the waveform to place it'><i></i><em>Cursor</em><b>–</b></span>" +
          "<span class='wv-t wv-t-mk' title='Marker: right-click (or Shift+click) to place it'><i></i><em>Marker</em><b>–</b></span>" +
          "<span class='wv-t wv-t-d' title='Time from the marker to the cursor, and that as a frequency'>Δ<b>–</b><small class='wv-freq'></small></span>" +
        "</span>" +
        "<span class='wv-spacer'></span>" +
        "<button class='wv-btn' data-act='png' id='" + p + "png' title='Save the waveform as an image'>PNG</button>" +
        "<button class='wv-btn' data-act='csv' id='" + p + "csv' title='Save the signals on screen as CSV'>CSV</button>" +
        "<button class='wv-btn' data-act='gtkwave' id='" + p + "gtkwave' title='Open this dump in GTKWave with these signals'>" + ICON.wave + "<span>GTKWave</span></button>" +
      "</div>" +
      "<div class='wv-main'>" +
        "<aside class='wv-tree' aria-label='Signals in the dump'>" +
          "<div class='wv-tree-head'><input class='wv-search' type='search' placeholder='Find a signal' spellcheck='false' aria-label='Find a signal'/></div>" +
          "<div class='wv-tree-list' role='tree'></div>" +
        "</aside>" +
        "<div class='wv-view'>" +
          "<div class='wv-hleft'><span class='wv-hname'>Signal <span class='wv-count'></span></span><span class='wv-hval'>Value</span></div>" +
          "<canvas class='wv-ruler' aria-hidden='true'></canvas>" +
          "<div class='wv-body'>" +
            "<div class='wv-scroll'><div class='wv-rows' role='listbox' aria-multiselectable='true' aria-label='Signals on screen'></div></div>" +
            "<div class='wv-stage'><canvas class='wv-plot' aria-label='Waveform'></canvas><canvas class='wv-over' aria-hidden='true'></canvas></div>" +
            "<div class='wv-drop' hidden></div>" +
          "</div>" +
          "<div class='wv-foot'>Drag: zoom in · Ctrl+wheel: zoom · Shift+wheel: pan</div>" +
          "<canvas class='wv-overview' title='The whole run. Drag to move the view.'></canvas>" +
          "<div class='wv-resize' role='separator' aria-orientation='vertical' aria-label='Resize the signal column' tabindex='0'></div>" +
        "</div>" +
      "</div>" +
      "<div class='wv-empty'><div class='wv-empty-body'>" +
        "<h4>No waveform yet</h4>" +
        "<p>Simulate a testbench and its signals show here. The testbench has to write a dump:</p>" +
        "<pre><code>initial begin\n  $dumpfile(\"dump.vcd\");\n  $dumpvars(0, " + "&lt;testbench&gt;" + ");\nend</code></pre>" +
        "<p class='wv-empty-note'>New testbenches from the + next to Simulation already do this.</p>" +
        "<button class='btn btn-primary btn-sm' data-act='simulate'>Simulate</button>" +
      "</div></div>" +
      "<div class='wv-menu' hidden role='menu'></div>";
    const q = (s) => this.host.querySelector(s);
    this.el = {
      bar: q(".wv-bar"), tree: q(".wv-tree"), treeList: q(".wv-tree-list"), search: q(".wv-search"),
      view: q(".wv-view"), rowsEl: q(".wv-rows"), scroll: q(".wv-scroll"), stage: q(".wv-stage"),
      plot: q(".wv-plot"), over: q(".wv-over"), ruler: q(".wv-ruler"), overview: q(".wv-overview"),
      count: q(".wv-count"), hval: q(".wv-hval"), drop: q(".wv-drop"), resize: q(".wv-resize"),
      menu: q(".wv-menu"), treeBtn: q(".wv-tree-btn"),
      tCur: q(".wv-t-cur b"), tMk: q(".wv-t-mk b"), tD: q(".wv-t-d b"),
    };
    this.ctx = this.el.plot.getContext("2d");
    this.octx = this.el.over.getContext("2d");
    this.rctx = this.el.ruler.getContext("2d");
    this.vctx = this.el.overview.getContext("2d");
  }

  _bind() {
    const el = this.el;
    // Toolbar
    el.bar.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.radix) { this._setRadix(b.dataset.radix); return; }
      this._act(b.dataset.act);
    });
    this.host.querySelector(".wv-empty").addEventListener("click", (e) => {
      if (e.target.closest("[data-act='simulate']")) this.opts.onSimulate && this.opts.onSimulate();
      if (e.target.closest("[data-act='gtkwave']")) this.opts.onGtkwave && this.opts.onGtkwave([]);
    });
    // Signal tree
    el.search.addEventListener("input", () => this._renderTree());
    el.search.addEventListener("keydown", (e) => {
      // Enter shows the first match (and never takes one off, as a click would).
      if (e.key === "Enter") {
        const first = el.treeList.querySelector(".wv-tv");
        if (first) this.addSignal(first.dataset.path);
      }
      if (e.key === "Escape" && el.search.value) { e.preventDefault(); el.search.value = ""; this._renderTree(); }
    });
    el.treeList.addEventListener("click", (e) => {
      const all = e.target.closest("[data-addall]");
      if (all) {
        e.stopPropagation();
        const node = this._scopeAt(all.dataset.addall);
        if (!node) return;
        const paths = node.signals.map((s) => s.scope.concat([s.name]).join("."));
        // Every one already on screen: the same button takes them off again.
        const on = new Set(this.rows.map((r) => r.path));
        if (paths.length && paths.every((p) => on.has(p))) this._remove(paths);
        else this._addMany(paths);
        return;
      }
      const sc = e.target.closest(".wv-ts");
      if (sc) {
        const open = sc.parentElement.classList.toggle("is-open");
        const p = sc.dataset.scope, depth = +sc.dataset.depth;
        if (open === (depth < 2)) this.treeFlip.delete(p); else this.treeFlip.add(p);
        return;
      }
      // A signal in the list toggles: click adds it, click again takes it off.
      const tv = e.target.closest(".wv-tv");
      if (!tv) return;
      if (this.rows.some((r) => r.path === tv.dataset.path)) this._remove([tv.dataset.path]);
      else this.addSignal(tv.dataset.path);
    });
    // Names / values
    this._bindRows();
    // Plot
    this._bindPlot();
    // Overview: as wide as the ruler (the plot plus the list's scrollbar),
    // so positions on it are fractions of its own width.
    const ovMove = (e) => {
      if (!this.vcd) return;
      const w = el.overview.clientWidth || this.plotW;
      const x = Math.max(0, Math.min(w, this._localX(el.overview, e)));
      const span = this.plotW / this.ppt;
      this.t0 = (x / w) * Math.max(1, this.vcd.end) - span / 2;
      this._clampT0();
      this.redraw();
    };
    el.overview.addEventListener("pointerdown", (e) => {
      if (!this.vcd || e.button !== 0) return;
      this._capture(el.overview, e, ovMove);
      ovMove(e);
    });
    // Column resize
    el.resize.addEventListener("pointerdown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      const startX = e.clientX, startW = this.namesW;
      const z = this._zoomOf(el.view);
      this._capture(el.resize, e,
        (ev) => { this.namesW = Math.max(110, Math.min(520, startW + (ev.clientX - startX) / z)); this._applyWidths(); this._relayout(); },
        () => this._save());
    });
    el.resize.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        this.namesW = Math.max(110, Math.min(520, this.namesW + (e.key === "ArrowLeft" ? -16 : 16)));
        this._applyWidths(); this._relayout(); this._save();
      }
    });
    // Keyboard, when the viewer has focus
    this.host.addEventListener("keydown", (e) => this._onKey(e));
    // Menu dismissal
    document.addEventListener("pointerdown", (e) => {
      if (!el.menu.hidden && !el.menu.contains(e.target)) this._closeMenu();
    });
    // Size and theme
    if ("ResizeObserver" in window) {
      let raf = 0;
      new ResizeObserver(() => {
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => {
          if (!this.host.clientWidth) return;
          this._layout();
          // A view that showed the whole run keeps showing it at the new size.
          if (this.vcd && (this._fitPending || this._fitted)) { this._fitPending = false; this.fit(); }
          else this.redraw();
        });
      }).observe(this.host);
    }
    new MutationObserver(() => { this._readColors(); this.redraw(); })
      .observe(document.body, { attributes: true, attributeFilter: ["class"] });
  }

  // Follow one pointer gesture on `node` until it ends, however it ends
  // (released, cancelled by the system, or capture lost), so no gesture is
  // ever left half-done. onEnd(ev, cancelled) runs exactly once.
  _capture(node, e, onMove, onEnd) {
    try { node.setPointerCapture(e.pointerId); } catch (_e) { /* pointer already gone */ }
    let over = false;
    const mv = (ev) => { if (ev.pointerId === e.pointerId) onMove(ev); };
    const end = (ev) => {
      if (over || ev.pointerId !== e.pointerId) return;
      over = true;
      node.removeEventListener("pointermove", mv);
      node.removeEventListener("pointerup", end);
      node.removeEventListener("pointercancel", end);
      node.removeEventListener("lostpointercapture", end);
      if (onEnd) onEnd(ev, ev.type !== "pointerup");
    };
    node.addEventListener("pointermove", mv);
    node.addEventListener("pointerup", end);
    node.addEventListener("pointercancel", end);
    node.addEventListener("lostpointercapture", end);
  }

  _act(act) {
    if (act === "tree") { this.treeOpen = !this.treeOpen; this._applyWidths(); this._relayout(); this._save(); if (this.treeOpen) this.el.search.focus(); }
    else if (act === "zoomin") this.zoomIn();
    else if (act === "zoomout") this.zoomOut();
    else if (act === "fit") this.fit();
    else if (act === "span") this._zoomSpan();
    else if (act === "prev") this._jump(-1);
    else if (act === "next") this._jump(1);
    else if (act === "png") this._exportPNG();
    else if (act === "csv") this._exportCSV();
    else if (act === "gtkwave") this.opts.onGtkwave && this.opts.onGtkwave(this.rows.map((r) => r.path));
  }

  _note(msg, bad) { if (this.opts.onNote) this.opts.onNote(msg, bad); }

  _layoutKey() { return this.opts.layoutKey ? this.opts.layoutKey() : null; }

  _save() {
    const k = this._layoutKey();
    if (!k || !this.vcd) return;
    writeStore(k, {
      rows: this.rows.map((r) => ({ p: r.path, r: r.radix || undefined, c: r.color || undefined })),
      radix: this.radix, namesW: Math.round(this.namesW), tree: !!this.treeOpen,
    });
  }

  _changed() {
    this._renderRows();
    this._renderTreeMarks();
    this._layout();
    this.redraw();
    this._save();
  }

  // After the plot's width changed: a view that showed the whole run keeps doing so.
  _relayout() {
    this._layout();
    if (this.vcd && this._fitted) this.fit(); else this.redraw();
  }

  _applyWidths() {
    this.host.style.setProperty("--wv-names", Math.round(this.namesW) + "px");
    this.host.style.setProperty("--wv-vals", VALS_W + "px");
    this.host.classList.toggle("tree-open", !!this.treeOpen);
    this.el.treeBtn.setAttribute("aria-pressed", this.treeOpen ? "true" : "false");
  }

  // ------------------------------------------------------------ signal tree

  _scopeAt(pathStr) {
    let node = this.vcd && this.vcd.scopes;
    for (const part of pathStr.split(".")) {
      node = node && node.children.find((c) => c.name === part);
    }
    return node || null;
  }

  _renderTree() {
    const list = this.el.treeList;
    if (!this.vcd) { list.innerHTML = ""; return; }
    const q = this.el.search.value.trim().toLowerCase();
    const onScreen = new Set(this.rows.map((r) => r.path));
    const varRow = (v, label) =>
      "<button class='wv-tv" + (onScreen.has(v.path) ? " is-on" : "") + "' role='treeitem' aria-pressed='" + onScreen.has(v.path) + "' data-path='" + esc(v.path) + "' title='" +
      esc(v.path + " · " + v.width + (v.width === 1 ? " bit" : " bits") + " · " + v.type + "\nClick to show it; click again to take it off.") + "'>" +
      "<span class='wv-tv-n'>" + label + "</span>" +
      (v.width > 1 ? "<span class='wv-tv-w'>" + v.width + "</span>" : "") + "</button>";
    if (q) {
      const hits = this.vars.filter((v) => v.path.toLowerCase().includes(q)).slice(0, 300);
      list.innerHTML = hits.length
        ? hits.map((v) => varRow(v, "<span class='wv-dim'>" + esc(v.scope.slice(1).map((s) => s + ".").join("")) + "</span>" + esc(v.name))).join("")
        : "<p class='wv-tree-none'>No signal matches “" + esc(q) + "”.</p>";
      return;
    }
    const scope = (node, path, depth) => {
      const kids = node.children.map((c) => scope(c, path.concat([c.name]), depth + 1)).join("");
      const sigs = node.signals.map((s) => varRow({ ...s, path: path.concat([s.name]).join(".") }, esc(s.name))).join("");
      const ps = path.join(".");
      const open = (depth < 2) !== this.treeFlip.has(ps);
      const all = node.signals.length > 0 && node.signals.every((s) => onScreen.has(path.concat([s.name]).join(".")));
      const what = (all ? "Take every signal in " : "Add every signal in ") + node.name + (all ? " off the view" : "");
      return "<div class='wv-tnode" + (open ? " is-open" : "") + "' role='group'>" +
        "<div class='wv-ts' role='treeitem' aria-expanded='" + open + "' data-scope='" + esc(ps) + "' data-depth='" + depth + "'><span class='wv-caret'>" + ICON.caret + "</span>" +
        "<span class='wv-ts-n'>" + esc(node.name) + "</span>" +
        (node.kind && node.kind !== "module" ? "<span class='wv-ts-k'>" + esc(node.kind) + "</span>" : "") +
        (node.signals.length ? "<button class='wv-addall" + (all ? " is-all" : "") + "' data-addall='" + esc(ps) + "' title='" + esc(what) + "' aria-label='" + esc(what) + "'>" + (all ? ICON.rmAll : ICON.addAll) + "</button>" : "") +
        "</div><div class='wv-tkids'>" + sigs + kids + "</div></div>";
    };
    list.innerHTML = this.vcd.scopes.children.map((c) => scope(c, [c.name], 0)).join("") ||
      "<p class='wv-tree-none'>The dump declares no signals.</p>";
  }

  // After rows came or went: the tree's on/off marks and its scope buttons
  // follow, without rebuilding the tree (which would lose its scroll).
  _renderTreeMarks() {
    const on = new Set(this.rows.map((r) => r.path));
    this.el.treeList.querySelectorAll(".wv-tv").forEach((b) => {
      const yes = on.has(b.dataset.path);
      b.classList.toggle("is-on", yes);
      b.setAttribute("aria-pressed", yes ? "true" : "false");
    });
    this.el.treeList.querySelectorAll("[data-addall]").forEach((b) => {
      const node = this._scopeAt(b.dataset.addall);
      if (!node) return;
      const all = node.signals.length > 0 && node.signals.every((s) => on.has(s.scope.concat([s.name]).join(".")));
      if (all === b.classList.contains("is-all")) return;
      const what = (all ? "Take every signal in " : "Add every signal in ") + node.name + (all ? " off the view" : "");
      b.classList.toggle("is-all", all);
      b.title = what;
      b.setAttribute("aria-label", what);
      b.innerHTML = all ? ICON.rmAll : ICON.addAll;
    });
  }

  _addMany(paths) {
    let n = 0;
    for (const p of paths) {
      const v = this.varByPath.get(p);
      if (v && !this.rows.some((r) => r.path === p)) { this.rows.push({ path: p, id: v.id, radix: null, color: null }); n++; }
    }
    if (n) {
      this._changed();
      this._scrollToRow(this.rows.length - 1);
      this._flash(Array.from({ length: n }, (_x, k) => this.rows.length - n + k));
    }
  }

  // ------------------------------------------------------------ names + values

  // "dut.count[4:0]": scope inside the testbench dimmed, then the name, then
  // the bit range dimmed.
  _labelHtml(v) {
    const scope = (v.scope || []).slice(1);
    const m = v.name.match(/^(.*?)(\[[^\]]*\])?$/);
    return (scope.length ? "<span class='wv-scope'>" + esc(scope.join(".") + ".") + "</span>" : "") +
      "<span class='wv-nm'>" + esc(m[1]) + "</span>" + (m[2] ? "<span class='wv-rng'>" + esc(m[2]) + "</span>" : "");
  }
  _label(v) { return (v.scope || []).slice(1).concat([v.name]).join("."); }

  _renderRows() {
    const el = this.el;
    el.count.textContent = this.rows.length ? String(this.rows.length) : "";
    el.rowsEl.innerHTML = this.rows.map((r, i) => {
      const v = this.varByPath.get(r.path);
      const sel = this.sel.has(r.path);
      return "<div class='wv-row" + (sel ? " is-sel" : "") + "' role='option' aria-selected='" + sel + "' data-i='" + i + "' title='" +
        esc(r.path + " · " + v.width + (v.width === 1 ? " bit" : " bits") + "\nDouble-click: go to the declaration. Right-click: format, colour.") + "'>" +
        "<span class='wv-ncell'><span class='wv-sw' style='background:" + esc(this._colorOf(r)) + "'></span>" +
        "<span class='wv-name'>" + this._labelHtml(v) + "</span>" +
        "<button class='wv-x' data-rm='" + i + "' aria-label='Remove " + esc(v.name) + "' title='Remove from the view'>" + ICON.x + "</button></span>" +
        "<span class='wv-val'></span></div>";
    }).join("") + (this.rows.length ? "" :
      "<p class='wv-rows-none'>No signals on screen. Open <b>Signals</b> and click one to add it.</p>");
    this._values();
  }

  _bindRows() {
    const el = this.el;
    el.rowsEl.addEventListener("click", (e) => {
      const rm = e.target.closest("[data-rm]");
      if (rm) { e.stopPropagation(); this._remove([this.rows[+rm.dataset.rm].path]); return; }
    });
    el.rowsEl.addEventListener("dblclick", (e) => {
      const row = e.target.closest(".wv-row");
      if (!row || e.target.closest("[data-rm]")) return;
      // The second press of the double-click let the row go; keep it chosen.
      const p = this.rows[+row.dataset.i].path;
      this.sel = new Set([p]); this.anchor = p; this._paintSel();
      if (this.opts.onGoto) this.opts.onGoto(this.varByPath.get(p));
    });
    el.rowsEl.addEventListener("contextmenu", (e) => {
      const row = e.target.closest(".wv-row");
      if (!row) return;
      e.preventDefault();
      const p = this.rows[+row.dataset.i].path;
      if (!this.sel.has(p)) { this.sel = new Set([p]); this.anchor = p; this._paintSel(); }
      this._openMenu(e, +row.dataset.i);
    });
    // Select on press; drag (past a few px) to reorder. A plain click on a row
    // that is already the whole selection lets it go again; a click on the
    // empty space under the rows clears the selection.
    el.rowsEl.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || e.target.closest("[data-rm]")) return;
      this.host.focus({ preventScroll: true });
      const row = e.target.closest(".wv-row");
      if (!row) {
        if (this.sel.size && !e.shiftKey && !e.ctrlKey && !e.metaKey) this._selectNone();
        return;
      }
      const i = +row.dataset.i, p = this.rows[i].path;
      const plain = !e.shiftKey && !e.ctrlKey && !e.metaKey;
      const wasOnly = plain && this.sel.size === 1 && this.sel.has(p);
      if (e.shiftKey && this.anchor && this.rows.some((r) => r.path === this.anchor)) {
        const a = this.rows.findIndex((r) => r.path === this.anchor);
        const [lo, hi] = a < i ? [a, i] : [i, a];
        this.sel = new Set(this.rows.slice(lo, hi + 1).map((r) => r.path));
      } else if (e.ctrlKey || e.metaKey) {
        if (this.sel.has(p)) this.sel.delete(p); else this.sel.add(p);
        this.anchor = p;
      } else if (!this.sel.has(p)) {
        this.sel = new Set([p]); this.anchor = p;
      }
      this._paintSel();
      const startY = e.clientY;
      let dragging = false, target = null;
      const z = this._zoomOf(el.rowsEl);
      // On the window, so a release outside the list still ends the gesture.
      const mv = (ev) => {
        if (ev.pointerId !== e.pointerId) return;
        if (!dragging && Math.abs(ev.clientY - startY) > 4) dragging = true;
        if (!dragging) return;
        const r = el.rowsEl.getBoundingClientRect();
        const y = (ev.clientY - r.top) / z;
        target = Math.max(0, Math.min(this.rows.length, Math.round(y / RH)));
        el.drop.hidden = false;
        el.drop.style.top = (target * RH - el.scroll.scrollTop - 1) + "px";
      };
      const done = (ev) => {
        if (ev.pointerId !== e.pointerId) return;
        window.removeEventListener("pointermove", mv);
        window.removeEventListener("pointerup", done);
        window.removeEventListener("pointercancel", done);
        el.drop.hidden = true;
        if (ev.type === "pointercancel") return;
        if (dragging && target !== null) this._moveSelected(target);
        else if (!dragging && plain && wasOnly) this._selectNone();
        else if (!dragging && plain && this.sel.size > 1) { this.sel = new Set([p]); this.anchor = p; this._paintSel(); }
      };
      window.addEventListener("pointermove", mv);
      window.addEventListener("pointerup", done);
      window.addEventListener("pointercancel", done);
    });
    el.scroll.addEventListener("scroll", () => { this._closeMenu(); this.redraw(); });
  }

  _selectNone() {
    this.sel = new Set();
    this.anchor = null;
    this._paintSel();
  }

  _paintSel() {
    this.el.rowsEl.querySelectorAll(".wv-row").forEach((r) => {
      const on = this.sel.has(this.rows[+r.dataset.i].path);
      r.classList.toggle("is-sel", on);
      r.setAttribute("aria-selected", on ? "true" : "false");
    });
    this._syncRadixButtons();
    this.redraw();
  }

  _moveSelected(target) {
    const moving = this.rows.filter((r) => this.sel.has(r.path));
    if (!moving.length) return;
    const before = this.rows.slice(0, target).filter((r) => !this.sel.has(r.path)).length;
    const rest = this.rows.filter((r) => !this.sel.has(r.path));
    rest.splice(before, 0, ...moving);
    this.rows = rest;
    this._changed();
  }

  _remove(paths) {
    const rm = new Set(paths);
    this.rows = this.rows.filter((r) => !rm.has(r.path));
    for (const p of rm) this.sel.delete(p);
    if (rm.has(this.anchor)) this.anchor = null;
    this._changed();
    this._syncRadixButtons();
  }

  _scrollToRow(i) {
    if (i < 0) return;
    const sc = this.el.scroll, y = i * RH;
    if (y < sc.scrollTop) sc.scrollTop = y;
    else if (y + RH > sc.scrollTop + sc.clientHeight) sc.scrollTop = y + RH - sc.clientHeight;
  }

  // Value column: at the cursor, or under the mouse while hovering the plot.
  _values() {
    const el = this.el;
    if (!this.vcd) return;
    const t = this.hover ? this.hover.t : this.cursor;
    el.hval.textContent = t === null || t === undefined ? "Value" : "@ " + formatTime(Math.round(t), this.vcd.tick);
    el.hval.classList.toggle("is-hover", !!this.hover);
    const cells = el.rowsEl.querySelectorAll(".wv-row");
    cells.forEach((rowEl) => {
      const r = this.rows[+rowEl.dataset.i];
      const cell = rowEl.lastElementChild;
      if (t === null || t === undefined) { cell.textContent = ""; cell.className = "wv-val"; return; }
      const sig = this.vcd.byId[r.id];
      const i = indexAt(sig.changes, t);
      const v = i < 0 ? "x" : sig.changes[i][1];
      const txt = this._fmt(r, v);
      cell.textContent = txt;
      cell.title = txt;
      cell.className = "wv-val" + (/x/.test(v) && !/^z+$/.test(v) ? " is-x" : /^z+$/.test(v) ? " is-z" : "") +
        (i >= 0 && Math.round(sig.changes[i][0]) === Math.round(t) && this.cursor !== null && !this.hover ? " is-edge" : "");
    });
  }

  _fmt(r, v) {
    const vv = this.varByPath.get(r.path);
    const w = vv ? vv.width : 1;
    if (w === 1 && /^[01xz]$/.test(v)) return v;
    if (vv && vv.type === "real") return v;
    return formatValue(v, this._radixOf(r, vv), w);
  }

  _radixOf(r, v) {
    if (r.radix) return r.radix;
    if (v && DEC_TYPES.has(v.type) && this.radix === "hex") return "signed";
    return this.radix;
  }

  _setRadix(radix) {
    const targets = this.sel.size ? this.rows.filter((r) => this.sel.has(r.path)) : null;
    if (targets) targets.forEach((r) => { r.radix = radix; });
    else { this.radix = radix; this.rows.forEach((r) => { r.radix = null; }); }
    this._syncRadixButtons();
    this._values();
    this.redraw();
    this._save();
  }

  _syncRadixButtons() {
    let cur = this.radix;
    if (this.sel.size) {
      const set = new Set(this.rows.filter((r) => this.sel.has(r.path)).map((r) => r.radix || this.radix));
      cur = set.size === 1 ? [...set][0] : null;
    }
    this.el.bar.querySelectorAll(".wave-radix").forEach((b) => {
      b.classList.toggle("is-on", b.dataset.radix === cur);
      b.setAttribute("aria-pressed", b.dataset.radix === cur ? "true" : "false");
    });
  }

  // ------------------------------------------------------------ context menu

  _openMenu(e, i) {
    const m = this.el.menu, r = this.rows[i], v = this.varByPath.get(r.path);
    const many = this.sel.size > 1;
    const cur = r.radix || this.radix;
    m.innerHTML =
      "<div class='wv-mh'>" + (many ? this.sel.size + " signals" : esc(this._label(v))) + "</div>" +
      (v.width > 1 ? "<div class='wv-mg'>Number format</div><div class='wv-mradix'>" + RADIXES.map(([k, label]) =>
        "<button role='menuitemradio' aria-checked='" + (k === cur) + "' data-mradix='" + k + "' title='" + label + "'>" + k + "</button>").join("") + "</div>" : "") +
      "<div class='wv-mg'>Colour</div><div class='wv-swatches'>" + COLORS.map((c, ci) =>
        "<button class='wv-swb" + ((r.color || COLORS[0]) === c ? " is-on" : "") + "' data-mcolor='" + c + "' aria-label='Colour " + (ci + 1) + "' style='background:var(" + c + ")'></button>").join("") + "</div>" +
      "<div class='wv-msep'></div>" +
      (!many ? "<button data-mact='goto'>Go to declaration</button>" : "") +
      "<button data-mact='marker'>Put the marker at the cursor</button>" +
      "<button data-mact='remove'>Remove" + (many ? " " + this.sel.size + " signals" : "") + "</button>" +
      "<button data-mact='clear'>Remove all signals</button>";
    m.hidden = false;
    const hr = this.host.getBoundingClientRect(), z = this._zoomOf(this.host);
    let x = (e.clientX - hr.left) / z, y = (e.clientY - hr.top) / z;
    const mw = m.offsetWidth, mh = m.offsetHeight;
    x = Math.min(x, this.host.clientWidth - mw - 6);
    y = Math.min(y, this.host.clientHeight - mh - 6);
    m.style.left = Math.max(4, x) + "px";
    m.style.top = Math.max(4, y) + "px";
    m.onclick = (ev) => {
      const b = ev.target.closest("button");
      if (!b) return;
      const targets = this.rows.filter((x2) => this.sel.has(x2.path));
      if (b.dataset.mradix) { targets.forEach((x2) => { x2.radix = b.dataset.mradix; }); this._syncRadixButtons(); this._values(); this.redraw(); this._save(); }
      else if (b.dataset.mcolor) { targets.forEach((x2) => { x2.color = b.dataset.mcolor === COLORS[0] ? null : b.dataset.mcolor; }); this._renderRows(); this.redraw(); this._save(); }
      else if (b.dataset.mact === "goto") { this.opts.onGoto && this.opts.onGoto(v); }
      else if (b.dataset.mact === "marker") { if (this.cursor !== null) { this.marker = this.cursor; this._overlay(); this._times(); } }
      else if (b.dataset.mact === "remove") this._remove(targets.map((x2) => x2.path));
      else if (b.dataset.mact === "clear") this._remove(this.rows.map((x2) => x2.path));
      this._closeMenu();
    };
    m.querySelector("button")?.focus();
  }
  _closeMenu() { this.el.menu.hidden = true; }

  // ------------------------------------------------------------ geometry

  _zoomOf(node) {
    const r = node.getBoundingClientRect();
    return node.clientWidth && r.width ? r.width / node.clientWidth : 1;
  }
  _localX(node, e) { const r = node.getBoundingClientRect(); return (e.clientX - r.left) / this._zoomOf(node); }
  _localY(node, e) { const r = node.getBoundingClientRect(); return (e.clientY - r.top) / this._zoomOf(node); }

  // Backing store at the screen's real pixel density (Windows scaling and the
  // app's own zoom included), so lines and text stay sharp. `fixed` canvases
  // get their CSS size from here; the ruler and overview stretch with CSS.
  _size(c, ctx, w, h, fixed = true) {
    const k = (window.devicePixelRatio || 1) * this._zoomOf(c.parentElement || c);
    const W = Math.max(1, Math.round(w * k)), H = Math.max(1, Math.round(h * k));
    if (c.width !== W || c.height !== H) { c.width = W; c.height = H; }
    if (fixed) { c.style.width = w + "px"; c.style.height = h + "px"; }
    ctx.setTransform(k, 0, 0, k, 0, 0);
  }

  _layout() {
    const el = this.el;
    // The plot sits beside the scrolling name list and leaves its scrollbar visible.
    const sb = el.scroll.offsetWidth - el.scroll.clientWidth;
    el.stage.style.right = sb + "px";
    this.plotW = Math.max(40, el.stage.clientWidth);
    this.plotH = Math.max(20, el.stage.clientHeight);
    this._size(el.plot, this.ctx, this.plotW, this.plotH);
    this._size(el.over, this.octx, this.plotW, this.plotH);
    this._size(el.ruler, this.rctx, el.ruler.clientWidth || this.plotW, 26, false);
    this._size(el.overview, this.vctx, el.overview.clientWidth || this.plotW, 20, false);
    el.rowsEl.style.minHeight = "max(100%, " + this.rows.length * RH + "px)";
  }

  _readColors() {
    const cs = getComputedStyle(this.host);
    const g = (n, d) => (cs.getPropertyValue(n) || "").trim() || d;
    this.colors = {
      bg: g("--wave-bg", "#04060a"), text: g("--text", "#c2cee0"), muted: g("--text-muted", "#7e8ea7"),
      grid: g("--wave-grid", "rgba(255,255,255,0.06)"), rowSel: g("--wave-row-sel", "rgba(77,163,255,0.08)"),
      x: g("--wave-x", "#e5484d"), z: g("--wave-z", "#f2c14e"), cursor: g("--wave-cursor", "#4da3ff"),
      marker: g("--wave-marker", "#e879c9"), hover: g("--wave-hover", "rgba(194,206,224,0.35)"),
      onCursor: g("--wave-on-cursor", "#06121f"), mono: g("--mono", "monospace"),
      border: g("--border", "rgba(194,206,224,0.14)"),
    };
    this.palette = {};
    for (const c of COLORS) this.palette[c] = g(c, "#36d399");
  }
  _colorOf(r) { return this.palette ? this.palette[r.color || COLORS[0]] || this.palette[COLORS[0]] : "#36d399"; }

  _X(t) { return (t - this.t0) * this.ppt; }
  _T(x) { return this.t0 + x / this.ppt; }

  // Every zoom and pan goes through here, so the view is no longer "fit".
  _clampT0() {
    this._fitted = false;
    const end = Math.max(1, this.vcd ? this.vcd.end : 1);
    const span = this.plotW / this.ppt;
    const maxT0 = Math.max(0, end - span) + span * 0.04;
    this.t0 = Math.min(Math.max(-span * 0.02, this.t0), maxT0);
    if (span >= end) this.t0 = Math.min(this.t0, 0);
  }

  _zoomAt(f, x) {
    if (!this.vcd) return;
    const end = Math.max(1, this.vcd.end);
    const ta = this._T(x);
    const minP = (this.plotW / end) * 0.5, maxP = 400;
    this.ppt = Math.min(maxP, Math.max(minP, this.ppt * f));
    this.t0 = ta - x / this.ppt;
    this._clampT0();
    this.redraw();
  }

  _zoomTo(ta, tb) {
    if (tb - ta <= 0) return;
    this.ppt = Math.min(400, this.plotW / (tb - ta));
    this.t0 = ta;
    this._clampT0();
    this.redraw();
  }

  _zoomSpan() {
    if (this.cursor === null || this.marker === null) {
      this._note("Place the cursor (click) and the marker (right-click) first, then zoom to the time between them.");
      return;
    }
    const a = Math.min(this.cursor, this.marker), b = Math.max(this.cursor, this.marker);
    const pad = (b - a) * 0.08 || 1;
    this._zoomTo(a - pad, b + pad);
  }

  // Move the cursor to the previous/next change of the selected signals (all
  // on screen when none is selected), and keep it in view.
  _jump(dir) {
    if (!this.vcd || !this.rows.length) return;
    const rows = this.sel.size ? this.rows.filter((r) => this.sel.has(r.path)) : this.rows;
    const from = this.cursor ?? (dir > 0 ? this.t0 - 1 : this._T(this.plotW));
    let best = null;
    for (const r of rows) {
      const ch = this.vcd.byId[r.id].changes;
      const i = indexAt(ch, from);
      let t = null;
      if (dir > 0) t = i + 1 < ch.length ? ch[i + 1][0] : null;
      else {
        let j = i;
        if (j >= 0 && ch[j][0] >= from) j--;
        t = j >= 0 ? ch[j][0] : null;
      }
      if (t !== null && (best === null || (dir > 0 ? t < best : t > best))) best = t;
    }
    if (best === null) { this._note(dir > 0 ? "No later change." : "No earlier change."); return; }
    this.cursor = best;
    const x = this._X(best);
    if (x < 20 || x > this.plotW - 20) { this.t0 = best - (this.plotW / this.ppt) / 2; this._clampT0(); this.redraw(); }
    else { this._overlay(); this._values(); }
    this._times();
  }

  // Snap to a change of the row under the mouse when one is within 6 px.
  // Times outside the run (the view keeps a little room either side) read
  // as its first or last moment.
  _clampT(t) { return Math.max(0, Math.min(this.vcd ? this.vcd.end : 0, t)); }

  _snap(x, row) {
    const t = this._clampT(this._T(x));
    if (row === null || row === undefined || !this.rows[row]) return t;
    const ch = this.vcd.byId[this.rows[row].id].changes;
    const i = indexAt(ch, t);
    let best = t, bd = 7;
    for (const j of [i, i + 1]) {
      if (j < 0 || j >= ch.length) continue;
      const d = Math.abs(this._X(ch[j][0]) - x);
      if (d < bd) { bd = d; best = ch[j][0]; }
    }
    return best;
  }

  _rowAt(y) {
    const i = Math.floor((y + this.el.scroll.scrollTop) / RH);
    return i >= 0 && i < this.rows.length ? i : null;
  }

  _bindPlot() {
    const over = this.el.over;
    over.addEventListener("pointermove", (e) => {
      if (!this.vcd || this.drag) return;
      const x = this._localX(over, e), y = this._localY(over, e);
      this.hover = { x, t: this._clampT(this._T(x)), row: this._rowAt(y) };
      this._overlay();
      this._values();
    });
    over.addEventListener("pointerleave", () => {
      if (this.drag) return;
      this.hover = null;
      this._overlay();
      this._values();
    });
    over.addEventListener("pointerdown", (e) => {
      if (!this.vcd || e.button !== 0) return;
      this.host.focus({ preventScroll: true });
      const x0 = this._localX(over, e), y0 = this._localY(over, e);
      const d = this.drag = { x0, x1: x0, active: false };
      this._capture(over, e, (ev) => {
        const x = this._localX(over, ev);
        if (!d.active && Math.abs(x - x0) > 4) d.active = true;
        d.x1 = Math.max(0, Math.min(this.plotW, x));
        if (d.active) this._overlay();
      }, (ev, cancelled) => {
        if (this.drag === d) this.drag = null;
        if (cancelled || !this.vcd) { this._overlay(); return; }
        if (d.active && Math.abs(d.x1 - d.x0) > 4) {
          this._zoomTo(this._T(Math.min(d.x0, d.x1)), this._T(Math.max(d.x0, d.x1)));
        } else {
          const t = this._snap(x0, this._rowAt(y0));
          if (ev.shiftKey) this.marker = t; else this.cursor = t;
          this._overlay();
          this._values();
          this._times();
        }
      });
    });
    over.addEventListener("contextmenu", (e) => {
      if (!this.vcd) return;
      e.preventDefault();
      const x = this._localX(over, e), y = this._localY(over, e);
      this.marker = this._snap(x, this._rowAt(y));
      this._overlay();
      this._times();
    });
    // The plot isn't inside the scrolling list, so pass plain wheel turns on.
    const wheel = (e) => {
      if (!this.vcd) return;
      const node = e.currentTarget;
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const x = node === this.el.ruler || node === over ? this._localX(node, e) : this.plotW / 2;
        this._zoomAt(Math.pow(1.0018, -e.deltaY), x);
      } else if (e.shiftKey || Math.abs(e.deltaX) > Math.abs(e.deltaY)) {
        e.preventDefault();
        const d = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
        this.t0 += d / this.ppt;
        this._clampT0();
        this.redraw();
      } else if (node !== this.el.scroll) {
        e.preventDefault();
        this.el.scroll.scrollTop += e.deltaY;
      }
    };
    over.addEventListener("wheel", wheel, { passive: false });
    this.el.ruler.addEventListener("wheel", wheel, { passive: false });
    this.el.scroll.addEventListener("wheel", wheel, { passive: false });
    // Click on the ruler sets the cursor too, drag there pans.
    this.el.ruler.addEventListener("pointerdown", (e) => {
      if (!this.vcd || e.button !== 0) return;
      const r = this.el.ruler;
      const x0 = this._localX(r, e), t00 = this.t0;
      let moved = false;
      this._capture(r, e, (ev) => {
        const dx = this._localX(r, ev) - x0;
        if (Math.abs(dx) > 3) moved = true;
        if (moved && this.vcd) { this.t0 = t00 - dx / this.ppt; this._clampT0(); this.redraw(); }
      }, (_ev, cancelled) => {
        if (!moved && !cancelled && this.vcd) { this.cursor = this._clampT(this._T(x0)); this._overlay(); this._values(); this._times(); }
      });
    });
  }

  _onKey(e) {
    if (!this.vcd || e.target.closest("input, select, textarea")) return;
    const k = e.key;
    // An open menu takes the keys: arrows walk its items, Esc closes it.
    if (!this.el.menu.hidden && this.el.menu.contains(e.target)) {
      if (k === "ArrowDown" || k === "ArrowUp") {
        const items = [...this.el.menu.querySelectorAll("button")];
        const i = items.indexOf(document.activeElement);
        items[(i + (k === "ArrowDown" ? 1 : -1) + items.length) % items.length]?.focus();
        e.preventDefault();
      } else if (k === "Escape" || k === "Tab") {
        this._closeMenu();
        this.host.focus({ preventScroll: true });
        e.preventDefault();
      }
      return;
    }
    let done = true;
    if (k === "ArrowRight" && !e.shiftKey) this._jump(1);
    else if (k === "ArrowLeft" && !e.shiftKey) this._jump(-1);
    else if (k === "ArrowRight" || k === "ArrowLeft") { this.t0 += (k === "ArrowRight" ? 1 : -1) * (this.plotW / this.ppt) * 0.2; this._clampT0(); this.redraw(); }
    else if (k === "+" || k === "=") this.zoomIn();
    else if (k === "-" || k === "_") this.zoomOut();
    else if (k === "f" || k === "F") this.fit();
    else if (k === "Home") { this.cursor = 0; this.t0 = 0; this._clampT0(); this.redraw(); this._times(); }
    else if (k === "End") { this.cursor = this.vcd.end; this.t0 = this.vcd.end - (this.plotW / this.ppt) * 0.9; this._clampT0(); this.redraw(); this._times(); }
    else if (k === "m" || k === "M") { if (this.cursor !== null) { this.marker = this.cursor; this._overlay(); this._times(); } }
    else if ((k === "Delete" || k === "Backspace") && this.sel.size) this._remove([...this.sel]);
    else if ((k === "a" || k === "A") && (e.ctrlKey || e.metaKey)) { this.sel = new Set(this.rows.map((r) => r.path)); this._paintSel(); }
    else if (k === "ArrowDown" || k === "ArrowUp") {
      if (!this.rows.length) return;
      const cur = this.anchor ? this.rows.findIndex((r) => r.path === this.anchor) : -1;
      const i = Math.max(0, Math.min(this.rows.length - 1, cur + (k === "ArrowDown" ? 1 : -1)));
      this.sel = new Set([this.rows[i].path]); this.anchor = this.rows[i].path;
      this._paintSel(); this._scrollToRow(i);
    }
    else if (k === "Escape") {
      // One thing per press, the nearest first: menu, selection, marker.
      if (!this.el.menu.hidden) { this._closeMenu(); this.host.focus({ preventScroll: true }); }
      else if (this.sel.size) this._selectNone();
      else if (this.marker !== null) { this.marker = null; this._overlay(); this._times(); }
      else done = false;
    }
    else done = false;
    if (done) e.preventDefault();
  }

  _times() {
    const el = this.el, tk = this.vcd ? this.vcd.tick : null;
    el.tCur.textContent = this.cursor === null ? "–" : formatTime(Math.round(this.cursor), tk);
    el.tMk.textContent = this.marker === null ? "–" : formatTime(Math.round(this.marker), tk);
    // The span between them, and the frequency it would be as a period
    // (what a clock-period measurement wants to read).
    let d = "–", freq = "";
    if (this.cursor !== null && this.marker !== null) {
      const ticks = Math.round(Math.abs(this.cursor - this.marker));
      d = formatTime(ticks, tk);
      const secs = ticks * tk.mult * Math.pow(10, tk.exp);
      if (secs > 0) {
        const f = 1 / secs;
        freq = f >= 1e9 ? +(f / 1e9).toPrecision(4) + " GHz" : f >= 1e6 ? +(f / 1e6).toPrecision(4) + " MHz"
          : f >= 1e3 ? +(f / 1e3).toPrecision(4) + " kHz" : +f.toPrecision(4) + " Hz";
      }
    }
    el.tD.textContent = d;
    this.host.querySelector(".wv-freq").textContent = freq;
    this.host.classList.toggle("has-marker", this.marker !== null);
  }

  // ------------------------------------------------------------ drawing

  redraw() {
    if (!this.vcd) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.plotW, this.plotH);
    ctx.font = "11.5px " + this.colors.mono;
    ctx.textBaseline = "middle";
    // faint grid at the ruler's major ticks
    const step = niceStep(110 / this.ppt);
    ctx.strokeStyle = this.colors.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let t = Math.ceil(this.t0 / step) * step; this._X(t) <= this.plotW; t += step) {
      const x = Math.round(this._X(t)) + 0.5;
      ctx.moveTo(x, 0); ctx.lineTo(x, this.plotH);
    }
    ctx.stroke();
    const top = this.el.scroll.scrollTop;
    const first = Math.max(0, Math.floor(top / RH));
    const last = Math.min(this.rows.length, Math.ceil((top + this.plotH) / RH));
    this._drawRows(ctx, first, last, top, true);
    // end of the simulation
    const xe = this._X(this.vcd.end);
    if (xe < this.plotW) {
      ctx.fillStyle = this.colors.grid;
      ctx.fillRect(xe, 0, this.plotW - xe, this.plotH);
    }
    this._drawRuler(this.rctx, this.el.ruler.clientWidth || this.plotW, true);
    this._overlay();
    this._drawOverview();
    this._values();
  }

  _drawRows(ctx, first, last, scrollTop, withSel) {
    for (let i = first; i < last; i++) {
      const r = this.rows[i];
      const y = i * RH - scrollTop;
      if (withSel && this.sel.has(r.path)) { ctx.fillStyle = this.colors.rowSel; ctx.fillRect(0, y, this.plotW, RH); }
      ctx.strokeStyle = this.colors.grid;
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(0, y + RH - 0.5); ctx.lineTo(this.plotW, y + RH - 0.5); ctx.stroke();
      const v = this.varByPath.get(r.path);
      const sig = this.vcd.byId[r.id];
      if (v.width === 1 && v.type !== "real") this._drawBit(ctx, sig, y, this._colorOf(r));
      else this._drawBus(ctx, sig, y, this._colorOf(r), r, v);
    }
  }

  // Segments of a signal that overlap the view: [ta, tb, value, prevValue].
  * _segments(sig) {
    const ch = sig.changes;
    if (!ch.length) return;
    const t1 = this._T(this.plotW);
    let i = Math.max(0, indexAt(ch, this.t0));
    const end = this.vcd.end;
    for (; i < ch.length; i++) {
      const ta = ch[i][0];
      if (ta > t1) break;
      const tb = i + 1 < ch.length ? ch[i + 1][0] : Math.max(end, ta);
      yield [ta, tb, ch[i][1], i > 0 ? ch[i - 1][1] : null];
    }
  }

  _drawBit(ctx, sig, y, color) {
    const hi = y + 5, lo = y + RH - 5, mid = y + RH / 2;
    const W = this.plotW;
    const lvl = (v) => (v === "1" ? hi : v === "0" ? lo : v === "z" ? mid : null);
    ctx.lineWidth = 1.5;
    let dense = null;   // [xa, xb] of a run too fast to draw edge by edge
    const flushDense = () => {
      if (!dense) return;
      ctx.fillStyle = color;
      ctx.globalAlpha = 0.55;
      ctx.fillRect(dense[0], hi, Math.max(1, dense[1] - dense[0]), lo - hi);
      ctx.globalAlpha = 1;
      dense = null;
    };
    for (const [ta, tb, v, pv] of this._segments(sig)) {
      let xa = this._X(ta), xb = this._X(tb);
      if (xb - xa < 2 && tb !== ta) { dense = dense ? [dense[0], xb] : [xa, xb]; continue; }
      flushDense();
      xa = Math.max(-2, xa); xb = Math.min(W + 2, xb);
      if (xb <= xa) continue;
      if (v === "1") {
        ctx.fillStyle = color; ctx.globalAlpha = 0.14;
        ctx.fillRect(xa, hi, xb - xa, lo - hi);
        ctx.globalAlpha = 1;
      }
      if (v === "x" || lvl(v) === null) {
        ctx.fillStyle = this.colors.x; ctx.globalAlpha = 0.28;
        ctx.fillRect(xa, hi, xb - xa, lo - hi);
        ctx.globalAlpha = 1;
        ctx.strokeStyle = this.colors.x;
        ctx.beginPath(); ctx.moveTo(xa, hi); ctx.lineTo(xb, hi); ctx.moveTo(xa, lo); ctx.lineTo(xb, lo); ctx.stroke();
      } else {
        ctx.strokeStyle = v === "z" ? this.colors.z : color;
        const yv = lvl(v);
        ctx.beginPath();
        // the edge into this value
        const yp = pv === null ? null : lvl(pv);
        if (ta >= this.t0 && yp !== null && yp !== yv) { ctx.moveTo(xa, yp); ctx.lineTo(xa, yv); }
        else ctx.moveTo(xa, yv);
        ctx.lineTo(xb, yv);
        ctx.stroke();
      }
    }
    flushDense();
  }

  _drawBus(ctx, sig, y, color, r, v) {
    const top = y + 4, bot = y + RH - 4, mid = y + RH / 2;
    const W = this.plotW;
    const cw = ctx.measureText("0").width || 7;
    ctx.lineWidth = 1.25;
    let dense = null;
    const flushDense = () => {
      if (!dense) return;
      ctx.fillStyle = color; ctx.globalAlpha = 0.5;
      ctx.fillRect(dense[0], top, Math.max(1, dense[1] - dense[0]), bot - top);
      ctx.globalAlpha = 1;
      dense = null;
    };
    for (const [ta, tb, val] of this._segments(sig)) {
      const xa0 = this._X(ta), xb0 = this._X(tb);
      if (xb0 - xa0 < 3 && tb !== ta) { dense = dense ? [dense[0], xb0] : [xa0, xb0]; continue; }
      flushDense();
      if (Math.min(xb0, W + 10) <= Math.max(xa0, -10)) continue;
      const isZ = /^z+$/.test(val), isX = !isZ && /[xz]/.test(val);
      const stroke = isX ? this.colors.x : isZ ? this.colors.z : color;
      const c = Math.min(4, (xb0 - xa0) / 2);
      // Off-screen ends are cut square (far outside the canvas), on-screen
      // ends get the usual bus chevron.
      const L = Math.max(xa0, -10), R = Math.min(xb0, W + 10);
      const lc = L === xa0, rc = R === xb0;
      if (isZ) {
        ctx.strokeStyle = stroke;
        ctx.beginPath(); ctx.moveTo(L, mid); ctx.lineTo(R, mid); ctx.stroke();
      } else {
        ctx.beginPath();
        if (lc) { ctx.moveTo(L, mid); ctx.lineTo(L + c, top); } else ctx.moveTo(L, top);
        if (rc) { ctx.lineTo(R - c, top); ctx.lineTo(R, mid); ctx.lineTo(R - c, bot); } else { ctx.lineTo(R, top); ctx.lineTo(R, bot); }
        if (lc) ctx.lineTo(L + c, bot); else ctx.lineTo(L, bot);
        ctx.closePath();
        ctx.fillStyle = stroke; ctx.globalAlpha = isX ? 0.22 : 0.08;
        ctx.fill(); ctx.globalAlpha = 1;
        ctx.strokeStyle = stroke;
        ctx.stroke();
      }
      // The label stays inside the visible part of the segment.
      const va = Math.max(0, xa0) + c + 3, vb = Math.min(W, xb0) - c - 3;
      const avail = vb - va;
      if (avail < cw * 1.5) continue;
      let txt = v.type === "real" ? val : formatValue(val, this._radixOf(r, v), v.width);
      const fits = Math.floor(avail / cw);
      if (txt.length > fits) txt = fits >= 2 ? txt.slice(0, fits - 1) + "…" : "";
      if (!txt) continue;
      const tw = txt.length * cw;
      ctx.fillStyle = isX ? this.colors.x : isZ ? this.colors.z : this.colors.text;
      ctx.fillText(txt, va + Math.max(0, (avail - tw) / 2), mid + 0.5);
    }
    flushDense();
  }

  _drawRuler(ctx, w, interactive) {
    const H = 26;
    ctx.clearRect(0, 0, w, H);
    if (!interactive) { ctx.fillStyle = this.colors.bg; ctx.fillRect(0, 0, w, H); }
    ctx.font = "11px " + this.colors.mono;
    ctx.textBaseline = "middle";
    const step = niceStep(110 / this.ppt);
    const minor = step / 5 >= 1 ? step / 5 : step / 2 >= 1 ? step / 2 : 0;
    ctx.strokeStyle = this.colors.muted;
    ctx.globalAlpha = 0.5;
    ctx.lineWidth = 1;
    ctx.beginPath();
    if (minor && minor * this.ppt >= 6) {
      for (let t = Math.ceil(this.t0 / minor) * minor; this._X(t) <= w; t += minor) {
        const x = Math.round(this._X(t)) + 0.5;
        ctx.moveTo(x, H - 4); ctx.lineTo(x, H);
      }
    }
    ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.beginPath();
    ctx.fillStyle = this.colors.muted;
    for (let t = Math.ceil(this.t0 / step) * step; this._X(t) <= w; t += step) {
      const x = Math.round(this._X(t)) + 0.5;
      ctx.moveTo(x, H - 9); ctx.lineTo(x, H);
      ctx.fillText(formatTime(t, this.vcd.tick, step), x + 4, 9);
    }
    ctx.stroke();
    // The ruler's bottom edge is drawn here, not as a CSS border, so the
    // canvas keeps its full 26 px and stays sharp.
    ctx.strokeStyle = this.colors.border;
    ctx.beginPath(); ctx.moveTo(0, H - 0.5); ctx.lineTo(w, H - 0.5); ctx.stroke();
    if (!interactive) {
      if (this.cursor !== null) this._flag(ctx, this.cursor, this.colors.cursor, H, w);
      if (this.marker !== null) this._flag(ctx, this.marker, this.colors.marker, H, w);
      return;
    }
    if (this.hover && !this.drag) this._flag(ctx, this.hover.t, this.colors.hover, H, w, true);
    if (this.marker !== null) this._flag(ctx, this.marker, this.colors.marker, H, w);
    if (this.cursor !== null) this._flag(ctx, this.cursor, this.colors.cursor, H, w);
  }

  // A time label on the ruler, sitting on its line.
  _flag(ctx, t, color, H, w, faint) {
    const x = this._X(t);
    if (x < -1 || x > w + 1) return;
    const txt = formatTime(Math.round(t), this.vcd.tick);
    ctx.font = "600 11px " + this.colors.mono;
    const tw = ctx.measureText(txt).width + 10;
    const bx = Math.max(0, Math.min(w - tw, x - tw / 2));
    ctx.fillStyle = faint ? this.colors.bg : color;
    ctx.globalAlpha = faint ? 0.92 : 1;
    ctx.fillRect(bx, 2, tw, H - 6);
    ctx.globalAlpha = 1;
    if (faint) { ctx.strokeStyle = this.colors.hover; ctx.strokeRect(bx + 0.5, 2.5, tw - 1, H - 7); }
    ctx.fillStyle = faint ? this.colors.text : this.colors.onCursor;
    ctx.fillText(txt, bx + 5, (H - 4) / 2 + 1);
    ctx.font = "11px " + this.colors.mono;
  }

  _drawMarks(ctx, h) {
    const line = (t, color, dash, width) => {
      const x = Math.round(this._X(t)) + 0.5;
      if (x < 0 || x > this.plotW) return;
      ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash);
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      ctx.setLineDash([]);
    };
    if (this.marker !== null) line(this.marker, this.colors.marker, [4, 3], 1.25);
    if (this.cursor !== null) line(this.cursor, this.colors.cursor, [], 1.5);
  }

  _overlay() {
    const ctx = this.octx;
    if (!ctx || !this.vcd) return;
    ctx.clearRect(0, 0, this.plotW, this.plotH);
    if (this.hover && !this.drag) {
      const x = Math.round(this.hover.x) + 0.5;
      ctx.strokeStyle = this.colors.hover; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, this.plotH); ctx.stroke();
      if (this.hover.row !== null) {
        const y = this.hover.row * RH - this.el.scroll.scrollTop;
        ctx.fillStyle = this.colors.hover; ctx.globalAlpha = 0.12;
        ctx.fillRect(0, y, this.plotW, RH);
        ctx.globalAlpha = 1;
      }
    }
    if (this.marker !== null && this.cursor !== null) {
      const a = this._X(Math.min(this.cursor, this.marker)), b = this._X(Math.max(this.cursor, this.marker));
      ctx.fillStyle = this.colors.marker; ctx.globalAlpha = 0.06;
      ctx.fillRect(a, 0, b - a, this.plotH);
      ctx.globalAlpha = 1;
    }
    this._drawMarks(ctx, this.plotH);
    if (this.drag && this.drag.active) {
      const a = Math.min(this.drag.x0, this.drag.x1), b = Math.max(this.drag.x0, this.drag.x1);
      ctx.fillStyle = this.colors.cursor; ctx.globalAlpha = 0.14;
      ctx.fillRect(a, 0, b - a, this.plotH);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = this.colors.cursor; ctx.lineWidth = 1;
      ctx.strokeRect(a + 0.5, 0.5, b - a - 1, this.plotH - 1);
      ctx.font = "600 11px " + this.colors.mono;
      ctx.fillStyle = this.colors.text;
      ctx.textBaseline = "top";
      ctx.fillText(formatTime(Math.round(this._T(b) - this._T(a)), this.vcd.tick), a + 4, 4);
      ctx.textBaseline = "middle";
    }
    this._drawRuler(this.rctx, this.el.ruler.clientWidth || this.plotW, true);
  }

  _drawOverview() {
    const ctx = this.vctx, w = this.el.overview.clientWidth || this.plotW, h = 20;
    ctx.clearRect(0, 0, w, h);
    ctx.strokeStyle = this.colors.border; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, 0.5); ctx.lineTo(w, 0.5); ctx.stroke();
    const end = Math.max(1, this.vcd.end);
    const k = w / end;
    ctx.fillStyle = this.colors.grid;
    ctx.fillRect(0, 6, w, h - 12);
    const a = Math.max(0, this.t0 * k), b = Math.min(w, this._T(this.plotW) * k);
    ctx.fillStyle = this.colors.cursor; ctx.globalAlpha = 0.22;
    ctx.fillRect(a, 2, Math.max(3, b - a), h - 4);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = this.colors.cursor; ctx.lineWidth = 1;
    ctx.strokeRect(a + 0.5, 2.5, Math.max(3, b - a) - 1, h - 5);
    const tick = (t, color) => { const x = Math.round(t * k) + 0.5; ctx.strokeStyle = color; ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); };
    if (this.marker !== null) tick(this.marker, this.colors.marker);
    if (this.cursor !== null) tick(this.cursor, this.colors.cursor);
  }

  _exportPNG() {
    const url = this.toPNG();
    if (!url) { this._note("Could not export the waveform image.", true); return; }
    const a = document.createElement("a");
    a.href = url; a.download = "waveform.png";
    document.body.appendChild(a); a.click(); a.remove();
    this._note("Saved waveform.png");
  }

  _exportCSV() {
    const csv = this.toCSV();
    if (!csv) return;
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url; a.download = "waveform.csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    this._note("Saved waveform.csv (" + this.rows.length + " signals)");
  }
}
