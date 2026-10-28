// editor.js — the RTL IDE's code editor: CodeMirror 6 (vendor/codemirror.js,
// bundled so it works offline) set up for Verilog and SystemVerilog the way
// VS Code and the FPGA tools behave: line numbers, folding, bracket matching
// and auto-closing, auto-indent, real undo history per file, find and replace
// with case/regex/word options, multiple cursors, Ctrl+/ comments, Alt+↑/↓
// to move lines, Verilator's diagnostics as squiggles with the message on
// hover, and completion of keywords, system tasks, the file's own names and
// the usual blocks (module, always_ff, case, a testbench clock …).
//
// The rest of the IDE talks to it through a small API: open/load, getValue,
// setMarkers, gotoLine, openFind, forget; callbacks onChange, onCursor, onSave.
import {
  EditorState, Compartment, EditorSelection, Prec,
  EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter, drawSelection,
  dropCursor, rectangularSelection, crosshairCursor, highlightSpecialChars, hoverTooltip,
  history, defaultKeymap, historyKeymap, indentWithTab, toggleComment,
  foldGutter, foldKeymap, indentOnInput, bracketMatching, syntaxHighlighting, HighlightStyle,
  StreamLanguage, indentUnit, foldService, tags,
  autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap, snippetCompletion, completeAnyWord,
  searchKeymap, highlightSelectionMatches, openSearchPanel, search,
  setDiagnostics, lintGutter, lintKeymap,
  verilog, tcl, yaml, json,
} from "../../vendor/codemirror.js";

// ------------------------------------------------------------------ languages

const VERILOG = StreamLanguage.define(verilog);
const TCL = StreamLanguage.define(tcl);
const YAML = StreamLanguage.define(yaml);

export function languageOf(relPath) {
  const ext = (String(relPath || "").match(/\.[^./\\]+$/) || [""])[0].toLowerCase();
  if ([".v", ".sv", ".vh", ".svh", ".verilog", ".vlt"].includes(ext)) return "verilog";
  if ([".sdc", ".tcl", ".xdc"].includes(ext)) return "tcl";
  if ([".yaml", ".yml"].includes(ext)) return "yaml";
  if (ext === ".json") return "json";
  return "text";
}

// Colours come from the app's syntax tokens, so both themes follow.
const HIGHLIGHT = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--syntax-kw)" },
  { tag: [tags.comment, tags.lineComment, tags.blockComment], color: "var(--syntax-com)", fontStyle: "italic" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--syntax-str)" },
  { tag: [tags.number, tags.bool, tags.null], color: "var(--syntax-num)" },
  { tag: tags.definition(tags.variableName), color: "var(--syntax-pp)" },      // `define, #delay
  { tag: tags.meta, color: "var(--syntax-sys)" },                               // $display …
  { tag: [tags.propertyName, tags.attributeName], color: "var(--syntax-num)" }, // JSON / YAML keys
  { tag: tags.bracket, color: "var(--text-muted)" },
  { tag: tags.invalid, color: "var(--fail)" },
]);

// ------------------------------------------------------------------ folding

// Block keywords and what closes them. The Verilog mode has no syntax tree,
// so the folds come from matching these words, skipping comments and strings.
const CLOSERS = {
  begin: ["end"], module: ["endmodule"], macromodule: ["endmodule"], case: ["endcase"], casez: ["endcase"],
  casex: ["endcase"], randcase: ["endcase"], function: ["endfunction"], task: ["endtask"],
  generate: ["endgenerate"], fork: ["join", "join_any", "join_none"], interface: ["endinterface"],
  package: ["endpackage"], class: ["endclass"], specify: ["endspecify"], property: ["endproperty"],
  sequence: ["endsequence"], clocking: ["endclocking"], covergroup: ["endgroup"],
};
const CLOSE_OF = {};
for (const [open, closes] of Object.entries(CLOSERS)) for (const c of closes) (CLOSE_OF[c] = CLOSE_OF[c] || []).push(open);
const WORD_RX = /\/\/[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\\n])*"|`?[A-Za-z_][\w$]*/g;

const _folds = new WeakMap();

// The words of one line that matter for folding, as WORD_RX reads the whole
// text, cached by the line's text: each keystroke on a 2000-line file used to
// rescan everything (8 ms a key on a slow laptop); now only changed lines are
// read again. A line is read in one of three modes: "n" normal, "b" starting
// inside a block comment, "x" after a "/*" that nothing closes (WORD_RX then
// skips the "/*" and reads on, so no block comment exists from there).
const LINE_RX_N = /\/\/[^\n]*|\/\*[\s\S]*?\*\/|\/\*|"(?:\\.|[^"\\\n])*"|`?[A-Za-z_][\w$]*/g;
const LINE_RX_X = /\/\/[^\n]*|"(?:\\.|[^"\\\n])*"|`?[A-Za-z_][\w$]*/g;
const _lineCache = { n: new Map(), b: new Map(), x: new Map() };

// -> { toks: [[word, offset, prevInLine|undefined]], last, tail, rest }
//    tail: offset of a "/*" not closed on this line (mode n); rest: the line
//    after it read in mode x (made when first needed).
function scanLine(text, from, rx) {
  const toks = [];
  let last, m, tail = -1;
  rx.lastIndex = from;
  while ((m = rx.exec(text)) !== null) {
    const w = m[0];
    if (w === "/*") { tail = m.index; break; }
    if (w[0] === "/" || w[0] === '"' || w[0] === "`") continue;
    if (CLOSERS[w] || CLOSE_OF[w]) toks.push([w, m.index, last]);
    last = w;
  }
  return { toks, last, tail, rest: null };
}
function lineInfo(mode, text) {
  const cache = _lineCache[mode];
  let e = cache.get(text);
  if (e) return e;
  if (mode === "b") {
    const end = text.indexOf("*/");
    e = end < 0 ? { toks: [], last: undefined, tail: -1, rest: null, open: true } : scanLine(text, end + 2, LINE_RX_N);
  } else e = scanLine(text, 0, mode === "x" ? LINE_RX_X : LINE_RX_N);
  if (cache.size > 50000) cache.clear();
  cache.set(text, e);
  return e;
}

// Line number -> position of the line holding its block's closing keyword.
// The same answer as one WORD_RX pass over the whole text (tests compare them).
export function blockPairs(doc) {
  let map = _folds.get(doc);
  if (map) return map;
  map = new Map();
  const lines = [];
  for (const it = doc.iterLines(); !it.next().done;) lines.push(it.value);
  // A "/*" is a comment only if some "*/" comes after it: the last line holding one.
  let lastClose = -1;
  for (let i = lines.length - 1; i >= 0; i--) if (lines[i].indexOf("*/") >= 0) { lastClose = i; break; }
  const stack = [];
  let prev = "", mode = "n", pos = 0;
  const take = (toks, ln, base) => {
    for (const [w, off, p0] of toks) {
      const pv = p0 === undefined ? prev : p0;
      const at = base + off;
      // "wait fork" / "disable fork" and prototypes ("extern function") close nothing.
      if (CLOSERS[w] && !(w === "fork" && (pv === "wait" || pv === "disable")) &&
          !((w === "function" || w === "task") && (pv === "extern" || pv === "import" || pv === "export" || pv === "pure"))) {
        stack.push({ w, ln });
      } else if (CLOSE_OF[w]) {
        for (let i = stack.length - 1; i >= 0; i--) {
          if (CLOSE_OF[w].includes(stack[i].w)) {
            const ol = stack[i].ln;
            stack.length = i;
            // The outermost block wins when one line opens several.
            if (ln > ol + 1 && !(map.has(ol) && map.get(ol) > at)) map.set(ol, at);
            break;
          }
        }
      }
    }
  };
  for (let i = 0; i < lines.length; i++) {
    const text = lines[i], ln = i + 1;
    const e = lineInfo(mode, text);
    take(e.toks, ln, pos);
    if (e.last !== undefined) prev = e.last;
    if (e.open) { /* the whole line is inside the comment */ }
    else if (e.tail >= 0) {
      if (lastClose > i) mode = "b";            // closed further down: a comment until then
      else {
        // Never closed: WORD_RX skips the "/*" and reads the rest as code.
        if (!e.rest) e.rest = scanLine(text, e.tail + 2, LINE_RX_X);
        take(e.rest.toks.map(([w, off, p0]) => [w, off, p0 === undefined ? (e.last !== undefined ? e.last : undefined) : p0]), ln, pos);
        if (e.rest.last !== undefined) prev = e.rest.last;
        mode = "x";
      }
    } else if (mode === "b") mode = "n";
    pos += text.length + 1;
  }
  _folds.set(doc, map);
  return map;
}

// The original whole-text reading, kept for the tests to compare against.
export function blockPairsFull(doc) {
  const map = new Map();
  const text = doc.toString();
  const stack = [];
  let prev = "", m;
  WORD_RX.lastIndex = 0;
  while ((m = WORD_RX.exec(text)) !== null) {
    const w = m[0];
    if (w[0] === "/" || w[0] === '"' || w[0] === "`") { continue; }
    if (CLOSERS[w] && !(w === "fork" && (prev === "wait" || prev === "disable")) &&
        !((w === "function" || w === "task") && (prev === "extern" || prev === "import" || prev === "export" || prev === "pure"))) {
      stack.push({ w, pos: m.index });
    } else if (CLOSE_OF[w]) {
      for (let i = stack.length - 1; i >= 0; i--) {
        if (CLOSE_OF[w].includes(stack[i].w)) {
          const open = stack[i];
          stack.length = i;
          const ol = doc.lineAt(open.pos).number, cl = doc.lineAt(m.index).number;
          if (cl > ol + 1 && !(map.has(ol) && map.get(ol) > m.index)) map.set(ol, m.index);
          break;
        }
      }
    }
    prev = w;
  }
  return map;
}

const VERILOG_FOLDING = foldService.of((state, lineStart) => {
  const line = state.doc.lineAt(lineStart);
  const close = blockPairs(state.doc).get(line.number);
  if (close === undefined) return null;
  const closeLine = state.doc.lineAt(close);
  return { from: line.to, to: closeLine.from - 1 };
});

// ------------------------------------------------------------------ completion

const KW = (
  "module endmodule input output inout wire reg logic integer genvar parameter localparam assign " +
  "always always_comb always_ff always_latch initial begin end if else case casez casex endcase " +
  "default for while repeat forever generate endgenerate function endfunction task endtask posedge " +
  "negedge or signed unsigned typedef struct union enum packed bit byte int shortint longint real " +
  "string void return break continue package endpackage import interface endinterface modport " +
  "automatic const unique unique0 priority assert assume cover property endproperty sequence " +
  "endsequence default_nettype timescale define include ifdef ifndef endif elsif"
).split(" ");
const SYS = (
  "$display $write $strobe $monitor $finish $stop $time $realtime $stime $dumpfile $dumpvars $dumpoff " +
  "$dumpon $random $urandom $urandom_range $readmemh $readmemb $writememh $clog2 $signed $unsigned $bits " +
  "$countones $onehot $onehot0 $isunknown $error $fatal $warning $info $fopen $fclose $fwrite $fdisplay " +
  "$sformatf $rose $fell $stable $past $value$plusargs $test$plusargs"
).split(" ");

// "\t" in a snippet is one indent unit (CodeMirror expands it per file).
const SNIPPETS = [
  ["module", "module ${name} (\n\tinput  wire clk,\n\tinput  wire rst,\n\t${}\n);\n\nendmodule", "module … endmodule"],
  ["always @(posedge clk)", "always @(posedge ${clk}) begin\n\tif (${rst}) begin\n\t\t${}\n\tend else begin\n\t\t\n\tend\nend", "clocked block with reset"],
  ["always @(*)", "always @(*) begin\n\t${}\nend", "combinational block"],
  ["always_ff", "always_ff @(posedge ${clk}) begin\n\tif (${rst}) begin\n\t\t${}\n\tend else begin\n\t\t\n\tend\nend", "SystemVerilog clocked block"],
  ["always_comb", "always_comb begin\n\t${}\nend", "SystemVerilog combinational block"],
  ["case", "case (${sel})\n\t${value}: ${};\n\tdefault: ;\nendcase", "case … endcase"],
  ["if", "if (${cond}) begin\n\t${}\nend", "if … end"],
  ["ifelse", "if (${cond}) begin\n\t${}\nend else begin\n\t\nend", "if … else … end"],
  ["for", "for (${i} = 0; ${i} < ${N}; ${i} = ${i} + 1) begin\n\t${}\nend", "for loop"],
  ["generate for", "genvar ${g};\ngenerate\n\tfor (${g} = 0; ${g} < ${N}; ${g} = ${g} + 1) begin : ${gen_block}\n\t\t${}\n\tend\nendgenerate", "generate loop"],
  ["initial", "initial begin\n\t${}\nend", "initial block"],
  ["clock", "always #${5} ${clk} = ~${clk};", "testbench clock (period = 2 × delay)"],
  ["dumpvars", "initial begin\n\t$dumpfile(\"dump.vcd\");\n\t$dumpvars(0, ${tb});\nend", "write a waveform"],
  ["function", "function ${[7:0]} ${name}(input ${[7:0]} ${a});\n\t${name} = ${};\nendfunction", "function … endfunction"],
  ["task", "task ${name};\n\tbegin\n\t\t${}\n\tend\nendtask", "task … endtask"],
  ["localparam", "localparam ${NAME} = ${value};", "constant"],
  ["assign", "assign ${lhs} = ${rhs};", "continuous assignment"],
];

const VERILOG_COMPLETIONS = [
  ...SNIPPETS.map(([label, tpl, detail]) => snippetCompletion(tpl, { label, detail, type: "text", boost: 2 })),
  ...KW.map((k) => ({ label: k, type: "keyword" })),
  ...SYS.map((k) => ({ label: k, type: "function" })),
];

// Words already in the file, minus the keywords the list above has.
const KW_SET = new Set(KW.concat(SYS));
async function fileWords(context) {
  const r = await completeAnyWord(context);
  if (r && r.options) r.options = r.options.filter((o) => !KW_SET.has(o.label));
  return r;
}

function verilogSource(context) {
  const word = context.matchBefore(/[$`]?[\w$]*/);
  if (!word || (word.from === word.to && !context.explicit)) return null;
  // Not inside a comment or a string.
  const line = context.state.doc.lineAt(context.pos);
  const before = line.text.slice(0, context.pos - line.from);
  if (/\/\//.test(before) || (before.split('"').length % 2 === 0)) return null;
  return { from: word.from, options: VERILOG_COMPLETIONS, validFor: /^[$`]?[\w$]*$/ };
}

// ------------------------------------------------------------------ theme

const THEME = EditorView.theme({
  "&": { height: "100%", fontSize: "13px", color: "var(--text)", backgroundColor: "var(--bg)" },
  "&.cm-focused": { outline: "none" },
  ".cm-scroller": { fontFamily: "var(--mono)", lineHeight: "1.55", fontVariantLigatures: "none" },
  ".cm-content": { padding: "8px 0", caretColor: "var(--text-strong)" },
  ".cm-line": { padding: "0 12px 0 10px" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--text-strong)", borderLeftWidth: "2px" },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection":
    { backgroundColor: "var(--editor-sel)" },
  ".cm-activeLine": { backgroundColor: "var(--editor-line)" },
  ".cm-gutters": { backgroundColor: "var(--bg)", color: "var(--text-disabled)", border: "none", borderRight: "1px solid var(--border)" },
  ".cm-lineNumbers .cm-gutterElement": { padding: "0 8px 0 12px", minWidth: "32px" },
  ".cm-activeLineGutter": { backgroundColor: "var(--editor-line)", color: "var(--text-strong)" },
  ".cm-foldGutter .cm-gutterElement": { width: "16px", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-muted)", cursor: "pointer" },
  ".cm-foldPlaceholder": { backgroundColor: "var(--surface-3)", border: "1px solid var(--border-strong)", color: "var(--text-muted)", padding: "0 6px", borderRadius: "3px" },
  ".cm-matchingBracket": { backgroundColor: "var(--editor-match)", outline: "1px solid var(--border-strong)", color: "inherit" },
  "&.cm-focused .cm-matchingBracket": { backgroundColor: "var(--editor-match)" },
  ".cm-nonmatchingBracket": { color: "var(--fail)" },
  ".cm-selectionMatch": { backgroundColor: "var(--editor-match)" },
  ".cm-searchMatch": { backgroundColor: "var(--warn-soft)", outline: "1px solid var(--warn)" },
  ".cm-searchMatch.cm-searchMatch-selected": { backgroundColor: "var(--accent-glow)", outline: "1px solid var(--met1)" },
  ".cm-panels": { backgroundColor: "var(--surface)", color: "var(--text)" },
  ".cm-panels.cm-panels-top": { borderBottom: "1px solid var(--border)" },
  ".cm-panels.cm-panels-bottom": { borderTop: "1px solid var(--border)" },
  ".cm-search": { display: "flex", flexWrap: "wrap", alignItems: "center", gap: "6px", padding: "8px 10px", fontSize: "13px" },
  ".cm-search br": { flexBasis: "100%", height: 0, content: "''" },
  ".cm-search label": { display: "inline-flex", alignItems: "center", gap: "4px", color: "var(--text-muted)", fontSize: "12.5px" },
  ".cm-search .cm-textfield": { height: "28px", padding: "3px 8px", fontSize: "13px", fontFamily: "var(--mono)", color: "var(--text)",
    backgroundColor: "var(--bg)", border: "1px solid var(--border)", borderRadius: "4px", minWidth: "200px" },
  ".cm-search .cm-textfield:focus": { outline: "none", borderColor: "var(--accent)" },
  ".cm-search .cm-button": { height: "28px", padding: "0 10px", fontSize: "12.5px", color: "var(--text)", backgroundImage: "none",
    backgroundColor: "var(--surface-2)", border: "1px solid var(--border)", borderRadius: "4px", textTransform: "none" },
  ".cm-search .cm-button:hover": { borderColor: "var(--border-strong)", color: "var(--text-strong)" },
  ".cm-search button[name=close]": { position: "static", marginLeft: "auto", fontSize: "18px", padding: "0 8px", color: "var(--text-muted)", background: "none", border: "0" },
  ".cm-tooltip": { backgroundColor: "var(--surface-2)", color: "var(--text)", border: "1px solid var(--border-strong)", borderRadius: "4px", boxShadow: "var(--sh-2)" },
  ".cm-tooltip-autocomplete > ul": { fontFamily: "var(--mono)", fontSize: "12.5px", maxHeight: "16em" },
  ".cm-tooltip-autocomplete > ul > li": { padding: "2px 10px 2px 6px", lineHeight: "1.6" },
  ".cm-tooltip-autocomplete > ul > li[aria-selected]": { backgroundColor: "var(--accent-soft)", color: "var(--text-strong)" },
  ".cm-completionDetail": { marginLeft: "12px", fontStyle: "normal", fontFamily: "var(--sans)", color: "var(--text-muted)" },
  ".cm-completionMatchedText": { textDecoration: "none", color: "var(--met1)" },
  ".cm-completionIcon": { opacity: "0.7", width: "1.2em" },
  ".cm-tooltip-lint": { padding: "2px 0" },
  ".cm-diagnostic": { padding: "4px 10px", fontFamily: "var(--mono)", fontSize: "12.5px", whiteSpace: "pre-wrap", maxWidth: "640px" },
  ".cm-diagnostic-error": { borderLeft: "3px solid var(--fail)" },
  ".cm-diagnostic-warning": { borderLeft: "3px solid var(--warn)" },
  ".cm-lintRange-error": { backgroundImage: "none", textDecoration: "underline wavy var(--fail)", textDecorationSkipInk: "none", textUnderlineOffset: "3px" },
  ".cm-lintRange-warning": { backgroundImage: "none", textDecoration: "underline wavy var(--warn)", textDecorationSkipInk: "none", textUnderlineOffset: "3px" },
  ".cm-lint-marker": { width: "0.8em", height: "0.8em" },
  ".cm-gutter-lint": { width: "1.1em" },
  ".cm-gutter-lint .cm-gutterElement": { padding: "0 0 0 4px" },
  ".cm-flash-line": { backgroundColor: "var(--accent-soft)", transition: "background-color 1.2s ease" },
});

const FOLD_OPEN = () => {
  const s = document.createElement("span");
  s.innerHTML = "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M6 9l6 6 6-6'/></svg>";
  return s;
};
const FOLD_SHUT = () => {
  const s = document.createElement("span");
  s.innerHTML = "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M9 6l6 6-6 6'/></svg>";
  return s;
};

// The indent a file already uses (2 or 4 spaces, or tabs), so new lines match.
function detectIndent(text) {
  const lines = String(text || "").split("\n").slice(0, 400);
  if (lines.filter((l) => /^\t+\S/.test(l)).length > lines.filter((l) => /^ +\S/.test(l)).length) return "\t";
  const counts = { 2: 0, 4: 0 };
  let prev = 0;
  for (const l of lines) {
    const m = l.match(/^( *)\S/);
    if (!m) continue;
    const d = Math.abs(m[1].length - prev);
    if (d === 2 || d === 4) counts[d]++;
    prev = m[1].length;
  }
  return counts[2] > counts[4] ? "  " : "    ";
}

export class Editor {
  constructor(host, { onChange, onCursor, onSave } = {}) {
    this.host = host;
    this.relPath = null;
    this.onChange = onChange || (() => {});
    this.onCursor = onCursor || (() => {});
    this.onSave = onSave || (() => {});
    this.states = new Map();       // relPath -> { state, scroll }
    this.lang = new Compartment();
    this.tabSize = new Compartment();
    this.readOnly = new Compartment();
    host.classList.add("editor", "cm-host");
    this.view = new EditorView({ parent: host, state: this._state("", null) });
  }

  _extensions(relPath, text) {
    const kind = languageOf(relPath);
    const langExt = kind === "verilog" ? [VERILOG, VERILOG_FOLDING, this._valueHover(), autocompletion({ override: [verilogSource, fileWords], activateOnTyping: true })]
      : kind === "tcl" ? [TCL, autocompletion({ override: [completeAnyWord] })]
      : kind === "yaml" ? [YAML, autocompletion({ override: [completeAnyWord] })]
      : kind === "json" ? [json(), autocompletion({ override: [completeAnyWord] })]
      : [autocompletion({ override: [completeAnyWord] })];
    const unit = detectIndent(text);
    return [
      lineNumbers(),
      foldGutter({ markerDOM: (open) => (open ? FOLD_OPEN() : FOLD_SHUT()) }),
      lintGutter(),
      highlightActiveLineGutter(),
      highlightSpecialChars(),
      history(),
      drawSelection(),
      dropCursor(),
      EditorState.allowMultipleSelections.of(true),
      indentOnInput(),
      bracketMatching(),
      closeBrackets(),
      rectangularSelection(),
      crosshairCursor(),
      highlightActiveLine(),
      highlightSelectionMatches(),
      search({ top: true }),
      syntaxHighlighting(HIGHLIGHT),
      this.lang.of(langExt),
      this.tabSize.of([indentUnit.of(unit), EditorState.tabSize.of(unit === "\t" ? 4 : unit.length)]),
      this.readOnly.of([EditorState.readOnly.of(relPath === null), EditorView.editable.of(relPath !== null)]),
      Prec.highest(keymap.of([
        { key: "Mod-s", preventDefault: true, run: () => { this.onSave(); return true; } },
        { key: "Mod-/", run: toggleComment },
        { key: "Mod-h", preventDefault: true, run: () => { this.openFind(true); return true; } },
      ])),
      keymap.of([
        ...closeBracketsKeymap, ...defaultKeymap, ...searchKeymap, ...historyKeymap, ...foldKeymap,
        ...completionKeymap, ...lintKeymap, indentWithTab,
      ]),
      THEME,
      EditorState.phrases.of({
        "Find": "Find", "Replace": "Replace", "next": "Next", "previous": "Previous", "all": "All",
        "match case": "Match case", "regexp": "Regex", "by word": "Whole word", "replace": "Replace",
        "replace all": "Replace all", "close": "Close", "Go to line": "Go to line", "go": "Go",
        "Folded lines": "Folded lines", "Unfolded lines": "Unfolded lines", "Fold line": "Fold", "Unfold line": "Unfold",
      }),
      EditorView.updateListener.of((u) => {
        if (u.docChanged) this.onChange(u.state.doc.toString());
        if (u.selectionSet || u.docChanged) this._cursor(u.state);
      }),
    ];
  }

  // Hovering a name asks the IDE for its value in the simulation (Verdi-style
  // annotation); the IDE answers with a DOM node, or null for no tooltip.
  _valueHover() {
    return hoverTooltip(async (view, pos) => {
      if (!this.hoverProvider) return null;
      const w = view.state.wordAt(pos);
      if (!w) return null;
      const word = view.state.sliceDoc(w.from, w.to);
      if (!/^[A-Za-z_][\w$]*$/.test(word)) return null;
      const dom = await this.hoverProvider(word, this.relPath);
      if (!dom) return null;
      return { pos: w.from, end: w.to, above: true, create: () => ({ dom }) };
    }, { hoverTime: 350 });
  }

  _state(text, relPath) {
    return EditorState.create({ doc: text || "", extensions: this._extensions(relPath, text) });
  }

  _cursor(state) {
    const sel = state.selection.main;
    const line = state.doc.lineAt(sel.head);
    const n = sel.to - sel.from;
    this.onCursor({ line: line.number, col: sel.head - line.from + 1, selected: n, cursors: state.selection.ranges.length });
  }

  // Show a file. A file seen before comes back with its undo history,
  // selection and scroll position, as long as its text is what we left.
  open(relPath, text) {
    if (this.relPath !== null) {
      this.states.set(this.relPath, { state: this.view.state, scroll: this.view.scrollDOM.scrollTop });
    }
    this.relPath = relPath;
    const kept = relPath !== null && this.states.get(relPath);
    if (kept && kept.state.doc.toString() === (text || "")) {
      this.view.setState(kept.state);
      requestAnimationFrame(() => { this.view.scrollDOM.scrollTop = kept.scroll || 0; });
    } else {
      this.view.setState(this._state(text, relPath));
    }
    this._cursor(this.view.state);
  }
  load(relPath, text) { this.open(relPath, text); }

  // Drop a closed file's kept state.
  forget(relPath) { this.states.delete(relPath); }

  getValue() { return this.view.state.doc.toString(); }

  focus() { this.view.focus(); }

  // Verilator diagnostics: [{ line, col, severity, msg, code }] for this file.
  setMarkers(markers) {
    const doc = this.view.state.doc;
    const diags = [];
    for (const m of markers || []) {
      if (!m.line || m.line > doc.lines) continue;
      const line = doc.line(m.line);
      const from = Math.min(line.to, line.from + Math.max(0, (m.col || 1) - 1));
      // Underline the word at the column (or the rest of the line).
      const rest = line.text.slice(from - line.from);
      const w = rest.match(/^[\w$`'.]+/);
      const to = w ? from + w[0].length : line.to > from ? line.to : from;
      diags.push({
        from, to, severity: m.severity === "error" ? "error" : "warning",
        message: m.msg + (m.code ? "  [" + m.code + "]" : ""), source: "Verilator",
      });
    }
    this.view.dispatch(setDiagnostics(this.view.state, diags));
  }

  gotoLine(line, col) {
    const doc = this.view.state.doc;
    const n = Math.max(1, Math.min(doc.lines, line || 1));
    const l = doc.line(n);
    const pos = col ? Math.min(l.to, l.from + col - 1) : l.from;
    this.view.dispatch({
      selection: col ? EditorSelection.cursor(pos) : EditorSelection.range(l.from, l.to),
      effects: EditorView.scrollIntoView(pos, { y: "center" }),
    });
    this.view.focus();
  }

  openFind(replace) {
    openSearchPanel(this.view);
    if (replace) {
      requestAnimationFrame(() => this.host.querySelector(".cm-search input[name=replace]")?.focus());
    }
  }

  // Insert text at the cursor (used by the "insert dump block" helper).
  insert(text) {
    const sel = this.view.state.selection.main;
    this.view.dispatch({ changes: { from: sel.from, to: sel.to, insert: text }, selection: { anchor: sel.from + text.length } });
    this.view.focus();
  }
}
