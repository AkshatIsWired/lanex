// logview.js — a log viewer that stays fast on a 50 000-line routing log.
//
// Only the lines in view are in the DOM (fixed line height, a spacer for the
// rest): web log viewers that render every line freeze or stop scrolling on
// logs this size (I. Duncan on GitHub Actions, 2026; spec 5.5). Errors and
// warnings are marked in the gutter and counted in the toolbar, with "next"
// buttons that jump from one to the next; a filter keeps only matching lines;
// "Problems" keeps only errors and warnings; Follow sticks to the bottom while
// a run is writing. Rows are text only (textContent), never HTML from the log;
// the page may add heading rows of its own (where each step starts).

import { icon } from "./icons.js";
import { localeNum } from "./intlcache.js";

const ROW = 20;          // CSS px per line (flow.css .lv-row)
const OVER = 30;         // extra rows rendered above and below the view

// A live run updates the toolbar every flush: unchanged text is left alone.
function setText(el, t) { if (el.textContent !== t) el.textContent = t; }

export function lineKind(s) {
  // LibreLane's console rules a line with the step's name as each one starts.
  if (/^\s*─{4,}.*\S.*─{4,}\s*$/.test(s)) return "head";
  // "[ERROR GPL-0301] …" (OpenROAD), "[15:43:11] ERROR    …" (LibreLane's console), "Error: …" (Tcl).
  if (/\[ERROR\b|^ERROR\b|\]\s+ERROR\s|\bERROR:|^Error:|\[CRITICAL\]|\bFAILED\b|Traceback \(most recent/.test(s)) return "err";
  if (/\[WARNING\b|^WARNING\b|\]\s+WARNING\s|\bWARNING:|^Warning:|\[WARN\]/.test(s)) return "warn";
  return "";
}

export class LogView {
  // host: an element to fill. opts: { follow, onOpenRaw, rawHref, emptyText }
  constructor(host, opts = {}) {
    this.host = host;
    this.opts = opts;
    this.lines = [];       // [{t, k}]
    this.view = [];        // indexes into lines after filter
    this.q = "";
    this.problems = false;
    this.follow = !!opts.follow;
    this.hit = -1;         // highlighted line (index into lines)
    this._raf = 0;
    host.classList.add("lv");
    host.innerHTML =
      "<div class='lv-bar'>" +
        "<label class='lv-q'>" + icon("search", { size: 13 }) +
          "<input type='search' placeholder='Filter this log' aria-label='Filter this log' spellcheck='false'/></label>" +
        "<button class='lv-chip is-err' data-lv='err' hidden title='Next error'></button>" +
        "<button class='lv-chip is-warn' data-lv='warn' hidden title='Next warning'></button>" +
        "<label class='lv-tog' title='Only errors and warnings'><input type='checkbox' data-lv='problems'/> Problems</label>" +
        "<label class='lv-tog lv-follow' title='Stay at the newest line'><input type='checkbox' data-lv='follow'/> Follow</label>" +
        "<span class='lv-count' aria-live='polite'></span>" +
        "<span class='lv-acts'>" +
          "<button class='btn btn-ghost btn-xs' data-lv='copy' title='Copy the lines shown'>" + icon("file", { size: 12 }) + " Copy</button>" +
          "<a class='btn btn-ghost btn-xs' data-lv='raw' target='_blank' rel='noopener' hidden>" + icon("popout", { size: 12 }) + " Raw log</a>" +
        "</span>" +
      "</div>" +
      "<div class='lv-scroll' tabindex='0' role='log' aria-label='Log'><div class='lv-spacer'><div class='lv-rows'></div></div>" +
        "<div class='lv-empty' hidden></div></div>";
    this.$ = (s) => host.querySelector(s);
    this.scroll = this.$(".lv-scroll");
    this.rows = this.$(".lv-rows");
    this.spacer = this.$(".lv-spacer");
    this.$("[data-lv=follow]").checked = this.follow;
    this.$("input[type=search]").addEventListener("input", (e) => { this.q = e.target.value.toLowerCase(); this._refilter(); });
    this.$("[data-lv=problems]").addEventListener("change", (e) => { this.problems = e.target.checked; this._refilter(); });
    this.$("[data-lv=follow]").addEventListener("change", (e) => { this.follow = e.target.checked; if (this.follow) this._toEnd(); });
    this.$("[data-lv=err]").addEventListener("click", () => this.next("err"));
    this.$("[data-lv=warn]").addEventListener("click", () => this.next("warn"));
    this.$("[data-lv=copy]").addEventListener("click", (e) => this._copy(e.currentTarget));
    this.scroll.addEventListener("scroll", () => {
      // Scrolling up by hand stops Follow, as in every terminal. (Not while new
      // lines wait for the next frame to be scrolled to: the gap is ours.)
      if (this.follow && !this._wantEnd && this.scroll.scrollTop + this.scroll.clientHeight < this.scroll.scrollHeight - ROW * 2) {
        this.follow = false; this.$("[data-lv=follow]").checked = false;
      }
      this._paint();
    }, { passive: true });
    new ResizeObserver(() => this._paint()).observe(this.scroll);
    this.setRaw(opts.rawHref || "");
  }

  setRaw(href) {
    const a = this.$("[data-lv=raw]");
    a.hidden = !href;
    if (href) a.href = href; else a.removeAttribute("href");
  }

  setFollowable(on) { this.$(".lv-follow").hidden = !on; if (!on) this.setFollow(false); }

  setFollow(on) {
    this.follow = !!on;
    this.$("[data-lv=follow]").checked = this.follow;
    if (this.follow) this._toEnd();
  }

  // Replace everything (a finished step's log).
  setText(text, opts = {}) {
    const rows = String(text || "").replace(/\r/g, "").split("\n");
    if (rows.length && rows[rows.length - 1] === "") rows.pop();
    this.setRows(rows, opts);
  }

  // Replace everything with rows: a line of text, or { t, k: "head" } for a
  // heading the page adds (where a step starts in the run's output).
  setRows(rows, { empty = "" } = {}) {
    this.lines = [];
    this._n = 0;
    this._ne = 0; this._nw = 0;
    for (const r of rows) this._push(r);
    this.hit = -1;
    this._empty = empty;
    this._refilter({ keepTop: false });
  }

  _push(r) {
    const l = typeof r === "string" ? { t: r, k: lineKind(r) } : { t: r.t, k: r.k || lineKind(r.t) };
    if (l.k !== "head") l.n = ++this._n;
    if (l.k === "err") this._ne = (this._ne || 0) + 1; else if (l.k === "warn") this._nw = (this._nw || 0) + 1;
    this.lines.push(l);
  }

  // Add lines while a run writes them.
  append(texts) {
    if (!texts.length) return;
    const start = this.lines.length;
    // One event may carry several lines ("a\nb", batched by the server): one row each.
    for (const t of texts) {
      if (typeof t === "string" && t.indexOf("\n") >= 0) { for (const part of t.replace(/\r/g, "").split("\n")) this._push(part); }
      else this._push(t);
    }
    const add = [];
    for (let i = start; i < this.lines.length; i++) if (this._keep(this.lines[i])) add.push(i);
    this.view.push(...add);
    this._counts();
    this._size();
    if (this.follow) this._toEnd(); else this._paint();
  }

  // Scroll so line `i` (0-based, into all lines) sits a third down, and mark it.
  reveal(i) {
    if (i == null || i < 0) return;
    if (!this.view.includes(i)) { this.q = ""; this.problems = false; this.$("input[type=search]").value = ""; this.$("[data-lv=problems]").checked = false; this._refilter(); }
    this.hit = i;
    this._ver = (this._ver || 0) + 1;     // the marked row changes: redraw the rows
    this.follow = false; this.$("[data-lv=follow]").checked = false;
    const pos = this.view.indexOf(i);
    // The viewer may not be laid out yet (a step just picked): wait until it
    // has a height, then put the line a third of the way down.
    let tries = 0;
    const place = () => {
      const h = this.scroll.clientHeight;
      if (!h && tries++ < 30) { requestAnimationFrame(place); return; }
      this.scroll.scrollTop = Math.max(0, pos * ROW - (h || 300) / 3);
      this._paint();
    };
    place();
  }

  firstOf(kind) { return this.lines.findIndex((l) => l.k === kind); }

  // Show the newest lines (a finished run's output ends with how it went).
  end() { this.scroll.scrollTop = this.scroll.scrollHeight; this._paint(); }

  next(kind) {
    const pos = this.view.indexOf(this.hit);
    const cand = this.view.filter((i) => this.lines[i].k === kind);
    if (!cand.length) return;
    const after = cand.find((i) => this.view.indexOf(i) > pos);
    this.reveal(after != null ? after : cand[0]);
  }

  _keep(l) {
    if (this.problems && l.k !== "err" && l.k !== "warn") return false;
    return !this.q || l.t.toLowerCase().includes(this.q);
  }

  _refilter({ keepTop = true } = {}) {
    this._ver = (this._ver || 0) + 1;     // rows at a position may differ now
    this.view = [];
    for (let i = 0; i < this.lines.length; i++) if (this._keep(this.lines[i])) this.view.push(i);
    this._counts();
    this._size();
    if (!keepTop) this.scroll.scrollTop = 0;
    if (this.follow) this._toEnd(); else this._paint();
  }

  _counts() {
    // Kept as lines arrive (_push): no pass over a 50 000-line log per flush.
    const e = this._ne || 0, w = this._nw || 0;
    const eb = this.$("[data-lv=err]"), wb = this.$("[data-lv=warn]");
    eb.hidden = !e; wb.hidden = !w;
    setText(eb, e + (e === 1 ? " error" : " errors"));
    // Lines of this log marked WARNING (a tool can print one warning on
    // several lines, or repeat it); the run's warning count elsewhere is
    // LibreLane's warning.log, one entry per warning, so the words differ.
    setText(wb, w + (w === 1 ? " warning line" : " warning lines"));
    wb.title = "Next warning. Counts the lines of this log marked as a warning; the run's warning count (from warning.log) lists each warning once.";
    const n = this.lines.length, shown = this.view.length;
    const lines = (k) => localeNum(k) + (k === 1 ? " line" : " lines");
    setText(this.$(".lv-count"), shown === n ? lines(this._n || n) : localeNum(shown) + " of " + lines(this._n || n));
    const em = this.$(".lv-empty");
    em.hidden = this.view.length > 0;
    setText(em, n ? "No line matches." : (this._empty || "Nothing here yet."));
  }

  _size() { this.spacer.style.height = this.view.length * ROW + "px"; }

  // Scroll to the newest line in the next frame, with the rows (one layout).
  _toEnd() {
    this._wantEnd = true;
    this._paint();
  }

  _row(p) {
    const i = this.view[p];
    const l = this.lines[i];
    const row = document.createElement("div");
    row.className = "lv-row" + (l.k ? " is-" + l.k : "") + (i === this.hit ? " is-hit" : "");
    const n = document.createElement("span");
    n.className = "lv-n"; n.textContent = l.n ? String(l.n) : "";
    const t = document.createElement("span");
    t.className = "lv-t"; t.textContent = l.t || " ";
    row.append(n, t);
    return row;
  }

  // The rows in view (and OVER either side). Rows already drawn for the same
  // positions stay: a live run's flush adds its new lines at the bottom and
  // drops as many from the top, instead of rebuilding ~90 rows each time.
  _paint() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => {
      this._raf = 0;
      if (this._wantEnd) { this._wantEnd = false; this.scroll.scrollTop = this.scroll.scrollHeight; }
      const top = this.scroll.scrollTop, h = this.scroll.clientHeight || 400;
      const a = Math.max(0, Math.floor(top / ROW) - OVER);
      const b = Math.min(this.view.length, Math.ceil((top + h) / ROW) + OVER);
      const ver = this._ver || 0;
      const ra = this._ra, rb = this._rb;
      if (ver === this._rver && a === ra && b === rb) return;
      this.rows.style.transform = "translateY(" + a * ROW + "px)";
      if (ver !== this._rver || ra == null || b <= ra || a >= rb) {
        const frag = document.createDocumentFragment();
        for (let p = a; p < b; p++) frag.appendChild(this._row(p));
        this.rows.replaceChildren(frag);
      } else {
        const kids = this.rows.children;
        for (let k = ra; k < Math.min(a, rb); k++) kids[0].remove();
        for (let k = rb; k > Math.max(b, a); k--) this.rows.lastElementChild.remove();
        if (a < ra) { const f = document.createDocumentFragment(); for (let p = a; p < ra; p++) f.appendChild(this._row(p)); this.rows.prepend(f); }
        if (b > rb) { const f = document.createDocumentFragment(); for (let p = rb; p < b; p++) f.appendChild(this._row(p)); this.rows.append(f); }
      }
      this._ra = a; this._rb = b; this._rver = ver;
    });
  }

  async _copy(btn) {
    const text = this.view.map((i) => this.lines[i].t).join("\n");
    try { await navigator.clipboard.writeText(text); btn.lastChild.textContent = " Copied"; }
    catch (_e) { btn.lastChild.textContent = " Copy failed"; }
    setTimeout(() => { btn.lastChild.textContent = " Copy"; }, 1400);
  }
}
