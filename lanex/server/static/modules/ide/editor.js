// editor.js — a dependency-free code editor with Verilog/SystemVerilog syntax
// highlighting, a line-number gutter, lint markers, and find & replace.
//
// Technique (no npm, no CodeMirror): a transparent <textarea> for editing sits
// on top of a <pre> that shows the syntax-highlighted text. Both share the exact
// same font/padding/scroll, so the colored layer tracks the caret perfectly.
// Keeps the same load()/getValue()/setMarkers()/gotoLine() API the rest of the
// IDE already calls, so this is a drop-in upgrade.

// Verilog + SystemVerilog keyword set (highlight only — not a parser).
const KEYWORDS = new Set((
  "module endmodule input output inout wire reg logic integer genvar parameter " +
  "localparam assign always always_comb always_ff always_latch initial begin end " +
  "if else case casez casex endcase default for while repeat forever generate " +
  "endgenerate function endfunction task endtask posedge negedge or and not nand " +
  "nor xor xnor buf signed unsigned typedef struct union enum packed bit byte " +
  "shortint int longint real time string void return break continue " +
  "package endpackage import export interface endinterface modport class endclass " +
  "virtual extends pure local protected static automatic const ref " +
  "wait fork join join_any join_none disable assert assume cover property " +
  "endproperty sequence endsequence clocking endclocking default_nettype " +
  "specify endspecify defparam supply0 supply1 tri triand trior wand wor"
).split(/\s+/));

const COMPILER = new Set("define ifdef ifndef endif else elsif include timescale default_nettype undef".split(" "));

function esc(s) {
  return s.replace(/[&<>]/g, (c) => (c === "&" ? "&amp;" : c === "<" ? "&lt;" : "&gt;"));
}

// One tokenizing regex pass: comments, strings, (compiler) directives, numbers,
// identifiers/keywords. Everything else passes through escaped (operators etc.).
const TOKEN_RX = new RegExp([
  "(\\/\\/[^\\n]*)",                         // 1 line comment
  "(\\/\\*[\\s\\S]*?\\*\\/)",                // 2 block comment
  "(\"(?:\\\\.|[^\"\\\\])*\")",             // 3 string
  "(`[A-Za-z_][A-Za-z0-9_]*)",              // 4 compiler directive `define etc.
  "(\\b\\d+'[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_]+)", // 5 sized literal 8'hFF
  "(\\b\\d[\\d_.]*\\b)",                     // 6 number
  "([A-Za-z_][A-Za-z0-9_$]*)",              // 7 identifier / keyword
].join("|"), "g");

function highlight(code) {
  let out = "";
  let last = 0;
  let m;
  TOKEN_RX.lastIndex = 0;
  while ((m = TOKEN_RX.exec(code)) !== null) {
    if (m.index > last) out += esc(code.slice(last, m.index));
    const [full, lineC, blockC, str, dir, sized, num, ident] = m;
    if (lineC || blockC) out += "<span class='tk-com'>" + esc(full) + "</span>";
    else if (str) out += "<span class='tk-str'>" + esc(full) + "</span>";
    else if (dir) out += "<span class='tk-pp'>" + esc(full) + "</span>";
    else if (sized || num) out += "<span class='tk-num'>" + esc(full) + "</span>";
    else if (ident) {
      const cls = KEYWORDS.has(ident) ? "tk-kw" : null;
      out += cls ? "<span class='" + cls + "'>" + esc(ident) + "</span>" : esc(ident);
    } else out += esc(full);
    last = m.index + full.length;
  }
  if (last < code.length) out += esc(code.slice(last));
  // Trailing newline keeps the <pre> height in step with the textarea.
  return out + "\n";
}

export class Editor {
  constructor(host) {
    this.host = host;
    this.relPath = null;
    this.markers = [];
    host.classList.add("editor", "hl-editor");
    host.innerHTML =
      "<div class='ed-find' hidden>" +
      "  <input class='ed-find-q' type='text' placeholder='Find' />" +
      "  <input class='ed-find-r' type='text' placeholder='Replace' />" +
      "  <button class='btn btn-ghost ed-find-next' title='Find next (Enter)'>Next</button>" +
      "  <button class='btn btn-ghost ed-find-rep'>Replace</button>" +
      "  <button class='btn btn-ghost ed-find-all'>All</button>" +
      "  <span class='ed-find-count muted'></span>" +
      "  <button class='btn btn-ghost ed-find-x' title='Close (Esc)'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button>" +
      "</div>" +
      "<div class='hl-wrap'>" +
      "  <div class='ed-gutter' aria-hidden='true'></div>" +
      "  <pre class='hl-pre' aria-hidden='true'><code class='hl-code'></code></pre>" +
      "  <textarea class='ed-area' spellcheck='false' wrap='off'></textarea>" +
      "</div>";
    this.findBar = host.querySelector(".ed-find");
    this.gutter = host.querySelector(".ed-gutter");
    this.pre = host.querySelector(".hl-code");
    this.area = host.querySelector(".ed-area");

    this.area.addEventListener("input", () => { this._repaint(); this._updateStatus(); });
    this.area.addEventListener("scroll", () => this._syncScroll());
    this.area.addEventListener("keyup", () => this._updateStatus());
    this.area.addEventListener("click", () => this._updateStatus());
    this.area.addEventListener("select", () => this._updateStatus());
    this.area.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") { e.preventDefault(); this.openFind(); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "h") { e.preventDefault(); this.openFind(true); }
      if (e.key === "Tab") {                       // insert two spaces, don't tab out
        e.preventDefault();
        const s = this.area.selectionStart, en = this.area.selectionEnd;
        this.area.setRangeText("  ", s, en, "end");
        this._repaint();
      }
    });
    this._wireFind();
  }

  load(relPath, text) {
    this.relPath = relPath;
    this.area.value = text || "";
    this.markers = [];
    this._repaint();
    this._updateStatus();
  }

  getValue() { return this.area.value; }

  setMarkers(markers) {
    this.markers = markers || [];
    this._paintGutter();
  }

  gotoLine(line) {
    const lines = this.area.value.split("\n");
    let pos = 0;
    for (let i = 0; i < line - 1 && i < lines.length; i++) pos += lines[i].length + 1;
    this.area.focus();
    this.area.setSelectionRange(pos, pos + (lines[line - 1] ? lines[line - 1].length : 0));
    // Scroll the line roughly into view.
    const lh = parseFloat(getComputedStyle(this.area).lineHeight) || 18;
    this.area.scrollTop = Math.max(0, (line - 3) * lh);
    this._syncScroll();
  }

  _repaint() {
    this.pre.innerHTML = highlight(this.area.value);
    this._paintGutter();
    this._syncScroll();
  }

  // Report "Ln X, Col Y" to an optional #ide-cursor status element, and mark the
  // caret's line number in the gutter so the user always knows where they are.
  _updateStatus() {
    const upto = this.area.value.slice(0, this.area.selectionStart);
    const line = upto.split("\n").length;
    const col = upto.length - upto.lastIndexOf("\n");
    const el = document.getElementById("ide-cursor");
    if (el) el.textContent = "Ln " + line + ", Col " + col;
    this._highlightActiveLine(line);
  }

  // Toggle the .ed-ln-active class onto the current line's gutter cell only.
  _highlightActiveLine(line) {
    if (this._activeLineEl) this._activeLineEl.classList.remove("ed-ln-active");
    const el = this.gutter.children[line - 1];
    if (el) { el.classList.add("ed-ln-active"); this._activeLineEl = el; }
  }

  _syncScroll() {
    this.pre.parentElement.scrollTop = this.area.scrollTop;
    this.pre.parentElement.scrollLeft = this.area.scrollLeft;
    this.gutter.scrollTop = this.area.scrollTop;
  }

  _paintGutter() {
    const n = this.area.value.split("\n").length;
    const markByLine = {};
    for (const m of this.markers) markByLine[m.line] = m.severity;
    let html = "";
    for (let i = 1; i <= n; i++) {
      const sev = markByLine[i];
      html += "<div class='ed-ln" + (sev ? " ed-ln-" + sev : "") + "'>" + i + "</div>";
    }
    this.gutter.innerHTML = html;
    // The rebuild dropped the active-line marker — re-apply it for the caret line.
    this._activeLineEl = null;
    const cur = this.area.value.slice(0, this.area.selectionStart).split("\n").length;
    this._highlightActiveLine(cur);
  }

  // ---- find & replace ----
  openFind(focusReplace) {
    this.findBar.hidden = false;
    const q = this.findBar.querySelector(".ed-find-q");
    const sel = this.area.value.substring(this.area.selectionStart, this.area.selectionEnd);
    if (sel && sel.length < 80) q.value = sel;
    (focusReplace ? this.findBar.querySelector(".ed-find-r") : q).focus();
    q.select();
    this._countMatches();
  }
  closeFind() { this.findBar.hidden = true; this.area.focus(); }

  _wireFind() {
    const q = this.findBar.querySelector(".ed-find-q");
    const r = this.findBar.querySelector(".ed-find-r");
    this.findBar.querySelector(".ed-find-next").addEventListener("click", () => this._findNext());
    this.findBar.querySelector(".ed-find-rep").addEventListener("click", () => this._replaceOne());
    this.findBar.querySelector(".ed-find-all").addEventListener("click", () => this._replaceAll());
    this.findBar.querySelector(".ed-find-x").addEventListener("click", () => this.closeFind());
    q.addEventListener("input", () => this._countMatches());
    q.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); this._findNext(); }
      if (e.key === "Escape") { e.preventDefault(); this.closeFind(); }
    });
    r.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); this._replaceOne(); }
      if (e.key === "Escape") { e.preventDefault(); this.closeFind(); }
    });
  }

  _query() { return this.findBar.querySelector(".ed-find-q").value; }

  _countMatches() {
    const q = this._query();
    const el = this.findBar.querySelector(".ed-find-count");
    if (!q) { el.textContent = ""; return; }
    const n = this.area.value.split(q).length - 1;
    el.textContent = n + (n === 1 ? " match" : " matches");
  }

  _findNext() {
    const q = this._query();
    if (!q) return;
    const from = this.area.selectionEnd;
    let idx = this.area.value.indexOf(q, from);
    if (idx === -1) idx = this.area.value.indexOf(q, 0);   // wrap
    if (idx === -1) return;
    this.area.focus();
    this.area.setSelectionRange(idx, idx + q.length);
    const lh = parseFloat(getComputedStyle(this.area).lineHeight) || 18;
    const line = this.area.value.slice(0, idx).split("\n").length;
    this.area.scrollTop = Math.max(0, (line - 3) * lh);
    this._syncScroll();
  }

  _replaceOne() {
    const q = this._query();
    const rep = this.findBar.querySelector(".ed-find-r").value;
    if (!q) return;
    const s = this.area.selectionStart, e = this.area.selectionEnd;
    if (this.area.value.substring(s, e) === q) {
      this.area.setRangeText(rep, s, e, "end");
      this._repaint();
    }
    this._findNext();
    this._countMatches();
  }

  _replaceAll() {
    const q = this._query();
    const rep = this.findBar.querySelector(".ed-find-r").value;
    if (!q) return;
    this.area.value = this.area.value.split(q).join(rep);
    this._repaint();
    this._countMatches();
  }
}
