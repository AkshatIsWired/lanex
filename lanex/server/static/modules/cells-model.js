// cells-model.js — pure helpers for the Cells tab (no DOM).
//
// Liberty boolean functions -> AST -> truth table, plain-English description and
// a gate diagram; flip-flop / latch behaviour in words; unit formatting; the
// LibreLane wildcard semantics (fnmatch) used by the exclusion lists.

// ---------- Liberty function parser ------------------------------------------
// Grammar (Liberty user guide): NOT is prefix ! or postfix ', AND is & or * or
// juxtaposition, XOR is ^, OR is | or +. Precedence NOT > AND > XOR > OR.

export function parseFunction(src) {
  const s = String(src || "").trim();
  if (!s) return null;
  const toks = [];
  const rx = /\s*([A-Za-z_][A-Za-z0-9_\[\]\.]*|[01]|[!'&*|+^()])/y;
  let m;
  rx.lastIndex = 0;
  while (rx.lastIndex < s.length && (m = rx.exec(s))) toks.push(m[1]);
  if (rx.lastIndex < s.replace(/\s+$/, "").length && !toks.length) return null;
  let i = 0;
  const peek = () => toks[i];
  const isAtomStart = (t) => t !== undefined && (t === "(" || t === "!" || /^[A-Za-z_01]/.test(t));

  function atom() {
    const t = toks[i];
    if (t === "!") { i++; return post({ op: "not", a: atom() }); }
    if (t === "(") {
      i++;
      const e = orE();
      if (toks[i] === ")") i++;
      return post(e);
    }
    if (t === "0" || t === "1") { i++; return post({ op: "const", v: t === "1" }); }
    if (t && /^[A-Za-z_]/.test(t)) { i++; return post({ op: "var", name: t }); }
    throw new Error("bad function: " + s);
  }
  function post(n) {
    while (toks[i] === "'") { i++; n = { op: "not", a: n }; }
    return n;
  }
  function andE() {
    const xs = [atom()];
    for (;;) {
      if (peek() === "&" || peek() === "*") { i++; xs.push(atom()); continue; }
      if (isAtomStart(peek())) { xs.push(atom()); continue; }   // juxtaposition
      break;
    }
    return flat("and", xs);
  }
  function xorE() {
    const xs = [andE()];
    while (peek() === "^") { i++; xs.push(andE()); }
    return flat("xor", xs);
  }
  function orE() {
    const xs = [xorE()];
    while (peek() === "|" || peek() === "+") { i++; xs.push(xorE()); }
    return flat("or", xs);
  }
  function flat(op, xs) {
    if (xs.length === 1) return xs[0];
    const out = [];
    for (const x of xs) { if (x.op === op) out.push(...x.args); else out.push(x); }
    return { op, args: out };
  }
  try {
    const e = orE();
    return i >= toks.length ? simplify(e) : null;
  } catch (_e) { return null; }
}

function simplify(n) {
  if (!n) return n;
  if (n.op === "not") {
    const a = simplify(n.a);
    if (a.op === "not") return a.a;
    return { op: "not", a };
  }
  if (n.args) {
    const args = n.args.map(simplify);
    // De Morgan: Liberty writes a NAND as "!A | !B" and a NOR as "!A & !B";
    // fold an all-inverted AND/OR back into the inverted gate people draw.
    if ((n.op === "and" || n.op === "or") && args.length > 1 && args.every((a) => a.op === "not")) {
      return { op: "not", a: factor({ op: n.op === "and" ? "or" : "and", args: args.map((a) => a.a) }) };
    }
    return factor({ op: n.op, args });
  }
  return n;
}

// Pull a term shared by every operand out: (A1|B)&(A2|B) -> (A1&A2)|B and
// (A&B)|(A&C) -> A&(B|C). Liberty files state functions flattened; this gives
// back the AOI/OAI shape a datasheet shows.
function factor(n) {
  if ((n.op !== "and" && n.op !== "or") || n.args.length < 2) return n;
  const inner = n.op === "and" ? "or" : "and";
  if (!n.args.every((a) => a.op === inner)) return n;
  const key = (a) => astText(a, false);
  const sets = n.args.map((a) => new Set(a.args.map(key)));
  const common = n.args[0].args.filter((t) => sets.every((s) => s.has(key(t))));
  if (!common.length) return n;
  const ck = new Set(common.map(key));
  const rests = n.args.map((a) => a.args.filter((t) => !ck.has(key(t))));
  if (rests.some((r) => !r.length)) return common.length === 1 ? common[0] : { op: inner, args: common };
  const restNode = { op: n.op, args: rests.map((r) => (r.length === 1 ? r[0] : { op: inner, args: r })) };
  return { op: inner, args: [restNode, ...common] };
}

// "Y = !((A1 & A2) | B1)" lines from the PDK's Verilog headers -> {Y: ast}
export function headerFormulas(lines) {
  const out = {};
  for (const l of lines || []) {
    const m = /^\s*([A-Za-z_]\w*)\s*=\s*(.+?)\s*$/.exec(l);
    if (!m) continue;
    const ast = parseFunction(m[2].replace(/~/g, "!"));
    if (ast) out[m[1]] = ast;
  }
  return out;
}

export function evalAst(n, env) {
  switch (n.op) {
    case "var": return !!env[n.name];
    case "const": return n.v;
    case "not": return !evalAst(n.a, env);
    case "and": return n.args.every((a) => evalAst(a, env));
    case "or": return n.args.some((a) => evalAst(a, env));
    case "xor": return n.args.reduce((acc, a) => acc !== evalAst(a, env), false);
    default: return false;
  }
}

export function astVars(n, out = new Set()) {
  if (!n) return out;
  if (n.op === "var") out.add(n.name);
  if (n.a) astVars(n.a, out);
  if (n.args) n.args.forEach((a) => astVars(a, out));
  return out;
}

const OPS = { and: " & ", or: " | ", xor: " ^ " };
export function astText(n, top = true) {
  if (!n) return "";
  switch (n.op) {
    case "var": return n.name;
    case "const": return n.v ? "1" : "0";
    case "not": {
      const a = n.a;
      return "!" + (a.op === "var" || a.op === "const" ? astText(a, false) : "(" + astText(a, true) + ")");
    }
    default: {
      const inner = n.args.map((a) => (a.args && a.op !== n.op ? "(" + astText(a, true) + ")" : astText(a, false))).join(OPS[n.op]);
      return top ? inner : "(" + inner + ")";
    }
  }
}

const WORDS = { and: " AND ", or: " OR ", xor: " XOR " };
export function astWords(n) {
  if (!n) return "";
  switch (n.op) {
    case "var": return n.name;
    case "const": return n.v ? "1" : "0";
    case "not": return "NOT " + (n.a.op === "var" ? n.a.name : "(" + astWords(n.a) + ")");
    default: return n.args.map((a) => (a.args ? "(" + astWords(a) + ")" : astWords(a))).join(WORDS[n.op]);
  }
}

// A short class name for common shapes: "3-input NAND", "AND-OR-Invert"…
export function classify(n) {
  if (!n) return "";
  const allVars = (xs) => xs.every((x) => x.op === "var" || (x.op === "not" && x.a.op === "var"));
  const gate = { and: "AND", or: "OR", xor: "XOR" };
  if (n.op === "var") return "Buffer";
  if (n.op === "const") return n.v ? "Tie high" : "Tie low";
  if (n.op === "not" && n.a.op === "var") return "Inverter";
  if (n.args && allVars(n.args)) return n.args.length + "-input " + gate[n.op];
  if (n.op === "not" && n.a.args && allVars(n.a.args)) return n.a.args.length + "-input " + { and: "NAND", or: "NOR", xor: "XNOR" }[n.a.op];
  const inner = n.op === "not" ? n.a : n;
  const inv = n.op === "not";
  if (inner.op === "or" && inner.args.some((a) => a.op === "and")) return inv ? "AND-OR-Invert (AOI)" : "AND-OR";
  if (inner.op === "and" && inner.args.some((a) => a.op === "or")) return inv ? "OR-AND-Invert (OAI)" : "OR-AND";
  if (isMux(inner)) return inv ? "Inverting 2-to-1 multiplexer" : "2-to-1 multiplexer";
  if (inner.op === "xor" || inner.op === "or" && inner.args.some((a) => a.op === "xor")) return "XOR-based logic";
  return "Complex gate";
}

function isMux(n) {
  if (n.op !== "or" || n.args.length !== 2) return false;
  const [a, b] = n.args;
  if (a.op !== "and" || b.op !== "and") return false;
  const sel = (t) => t.args.find((x) => x.op === "not" && x.a.op === "var");
  const s = sel(a) || sel(b);
  return !!s;
}

// ---------- truth table --------------------------------------------------------
export function truthTable(inputs, outputs) {
  // outputs: [{name, ast, z: ast|null}]
  const n = inputs.length;
  if (n > 6) return null;
  const rows = [];
  for (let k = 0; k < (1 << n); k++) {
    const env = {};
    inputs.forEach((p, j) => { env[p] = !!(k & (1 << (n - 1 - j))); });
    rows.push({
      ins: inputs.map((p) => (env[p] ? 1 : 0)),
      outs: outputs.map((o) => {
        if (o.z && evalAst(o.z, env)) return "Z";
        return o.ast ? (evalAst(o.ast, env) ? 1 : 0) : "?";
      }),
    });
  }
  return rows;
}

// ---------- sequential behaviour, in words ------------------------------------
function edgeOf(expr) {
  const a = parseFunction(expr);
  if (!a) return { pin: expr, rising: true };
  if (a.op === "not" && a.a.op === "var") return { pin: a.a.name, rising: false };
  if (a.op === "var") return { pin: a.name, rising: true };
  return { pin: astText(a), rising: true };
}
function lowOrHigh(expr) {
  const a = parseFunction(expr);
  if (!a) return expr;
  if (a.op === "not" && a.a.op === "var") return a.a.name + " low";
  if (a.op === "var") return a.name + " high";
  return astWords(a) + " true";
}

export function seqDescription(seq, outs) {
  if (!seq) return [];
  const st = seq.state || [];
  const q = (outs || []).find((o) => String(o.function || "").replace(/[()\s]/g, "") === st[0]);
  const qn = (outs || []).find((o) => String(o.function || "").replace(/[()\s]/g, "") === st[1]);
  const qName = q ? q.name : "the output";
  const lines = [];
  if (seq.kind === "ff") {
    const e = edgeOf(seq.clocked_on || "CLK");
    const ns = parseFunction(seq.next_state || "D");
    lines.push("On each " + (e.rising ? "rising" : "falling") + " edge of " + e.pin + ", " + qName +
      " takes " + (ns && ns.op === "var" ? ns.name : "(" + astWords(ns) + ")") + ".");
    if (ns && ns.op !== "var") {
      if (/SCE|SE\b|SCD|SI\b/.test(seq.next_state || "")) lines.push("That mux on the data input is the scan chain: with the scan enable high it loads the scan input instead of D, so a tester can shift values in and out.");
      else if (/DE\b/.test(seq.next_state || "")) lines.push("The extra input is a data enable: when it is low the flop keeps its value.");
    }
  } else {
    const en = lowOrHigh(seq.enable || "GATE");
    lines.push("While " + en + ", " + qName + " follows " + (seq.data_in || "D") + "; otherwise it holds its last value (a level-sensitive latch).");
  }
  if (seq.clear) lines.push(lowOrHigh(seq.clear).replace(/ (low|high)$/, (m) => " " + m.trim()) + " forces " + qName + " to 0 at once, without waiting for the clock (asynchronous reset).");
  if (seq.preset) lines.push(lowOrHigh(seq.preset) + " forces " + qName + " to 1 at once (asynchronous set).");
  if (qn) lines.push(qn.name + " is the inverted copy of " + qName + ".");
  return lines;
}

// ---------- gate diagram -------------------------------------------------------
// Returns an SVG string drawing the expression as a tree of gates, inputs on the
// left and the output on the right. Shared inputs are drawn once per use.
export function gateDiagram(ast, outName, { maxLeaves = 14 } = {}) {
  if (!ast) return "";
  const leaves = countLeaves(ast);
  if (leaves > maxLeaves) return "";
  const ROW = 26, COL = 92, GW = 44, PADL = 46, PADR = 44, PADT = 12;
  // depth of gates
  const depthOf = (n) => (n.op === "var" || n.op === "const") ? 0 : 1 + Math.max(...kids(n).map(depthOf));
  const D = depthOf(ast);
  const W = PADL + Math.max(1, D) * COL + PADR;
  const H = PADT * 2 + leaves * ROW;
  let row = 0;
  const parts = [];
  // place(n, level) -> {x (output x), y}
  function place(n, level) {
    if (n.op === "var" || n.op === "const") {
      const y = PADT + row * ROW + ROW / 2;
      row++;
      const label = n.op === "var" ? n.name : (n.v ? "1" : "0");
      parts.push("<text class='gd-in' x='" + (PADL - 8) + "' y='" + (y + 4) + "' text-anchor='end'>" + esc(label) + "</text>");
      return { x: PADL, y };
    }
    const g = gateOf(n);
    const ins = g.inputs.map((c) => place(c, level - 1));
    const y = (ins[0].y + ins[ins.length - 1].y) / 2;
    const gx = PADL + (level - 1) * COL + (COL - GW);   // gate's left edge
    const gh = Math.max(24, g.inputs.length * 12 + 8);
    const top = y - gh / 2;
    // input wires: elbow from the child output to the gate's pin
    ins.forEach((p, k) => {
      const py = g.inputs.length === 1 ? y : top + 6 + (k * (gh - 12)) / (g.inputs.length - 1);
      const mid = gx - 12 - (g.inputs.length > 1 ? (k % 2) * 6 : 0);
      parts.push("<path class='gd-wire' d='M" + p.x + " " + p.y + "H" + mid + "V" + py.toFixed(1) + "H" + (gx + (g.kind === "or" || g.kind === "xor" ? 6 : 0)) + "'/>");
    });
    parts.push(gateShape(g.kind, gx, top, GW, gh, g.neg));
    const ox = gx + GW + (g.neg ? 8 : 0);
    return { x: ox, y };
  }
  const out = place(ast, D || 1);
  parts.push("<path class='gd-wire' d='M" + out.x + " " + out.y + "H" + (W - PADR + 10) + "'/>");
  parts.push("<text class='gd-out' x='" + (W - PADR + 14) + "' y='" + (out.y + 4) + "'>" + esc(outName || "Y") + "</text>");
  return "<svg class='gd' viewBox='0 0 " + W + " " + H + "' width='" + W + "' height='" + H + "' role='img' aria-label='Logic diagram'>" + parts.join("") + "</svg>";
}

function kids(n) { return n.op === "not" ? [n.a] : (n.args || []); }
function countLeaves(n) { return (n.op === "var" || n.op === "const") ? 1 : kids(n).reduce((s, k) => s + countLeaves(k), 0); }
function gateOf(n) {
  if (n.op === "not") {
    if (n.a.args) return { kind: n.a.op, inputs: n.a.args, neg: true };
    return { kind: "buf", inputs: [n.a], neg: true };
  }
  return { kind: n.op, inputs: n.args, neg: false };
}

function gateShape(kind, x, y, w, h, neg) {
  const r = h / 2, cx = x, cy = y + r;
  let d;
  if (kind === "and") {
    d = "M" + x + " " + y + "H" + (x + w - r) + "A" + r + " " + r + " 0 0 1 " + (x + w - r) + " " + (y + h) + "H" + x + "Z";
  } else if (kind === "or" || kind === "xor") {
    d = "M" + x + " " + y + "Q" + (x + w * 0.55) + " " + y + " " + (x + w) + " " + cy +
      "Q" + (x + w * 0.55) + " " + (y + h) + " " + x + " " + (y + h) + "Q" + (x + w * 0.28) + " " + cy + " " + x + " " + y + "Z";
  } else {
    d = "M" + (x + 6) + " " + y + "L" + (x + w) + " " + cy + "L" + (x + 6) + " " + (y + h) + "Z";
  }
  let s = "<path class='gd-gate' d='" + d + "'/>";
  if (kind === "xor") s += "<path class='gd-gate gd-x' d='M" + (x - 6) + " " + y + "Q" + (x + w * 0.28 - 6) + " " + cy + " " + (x - 6) + " " + (y + h) + "'/>";
  if (neg) s += "<circle class='gd-gate' cx='" + (x + w + 4) + "' cy='" + cy + "' r='4'/>";
  return s;
  void cx;
}

// ---------- wildcards (LibreLane uses fnmatch) ---------------------------------
export function globToRegex(p) {
  let r = "^";
  for (const ch of String(p)) {
    if (ch === "*") r += ".*";
    else if (ch === "?") r += ".";
    else r += ch.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp(r + "$");
}
export function globMatch(name, pats) {
  return (pats || []).filter((p) => globToRegex(p).test(name));
}

// ---------- formatting ---------------------------------------------------------
export function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || !Number.isFinite(Number(v))) return "–";
  const n = Number(v);
  const a = Math.abs(n);
  if (a >= 1000) return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (a >= 100) return n.toFixed(0);
  if (a >= 10) return n.toFixed(1);
  return n.toFixed(digits);
}
export function fmtPs(v) {
  if (!Number.isFinite(Number(v))) return "–";
  const n = Number(v);
  return n >= 1000 ? (n / 1000).toFixed(2) + " ns" : n.toFixed(0) + " ps";
}
export function fmtPower(nW) {
  if (!Number.isFinite(Number(nW))) return "–";
  const n = Number(nW);
  if (n === 0) return "0 W";
  const a = Math.abs(n);
  if (a >= 1e6) return (n / 1e6).toFixed(2) + " mW";
  if (a >= 1e3) return (n / 1e3).toFixed(2) + " µW";
  if (a >= 1) return n.toFixed(2) + " nW";
  if (a >= 1e-3) return (n * 1e3).toFixed(2) + " pW";
  return (n * 1e6).toFixed(1) + " fW";
}
export function fmtCap(fF) {
  if (!Number.isFinite(Number(fF))) return "–";
  return Number(fF).toFixed(Number(fF) >= 100 ? 0 : 2) + " fF";
}
export function fmtArea(a) {
  if (!Number.isFinite(Number(a))) return "–";
  const n = Number(a);
  return (n >= 1e6 ? (n / 1e6).toFixed(3) + " mm²" : fmtNum(n) + " µm²");
}

export function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// drive suffix sort: "0" < "1" < "2" < "4" < "16" < "lp" …
export function driveKey(d) {
  const n = parseInt(d, 10);
  return Number.isFinite(n) ? n : 1000;
}

// Categories in display order (labels come from the server).
export const CATEGORY_ORDER = ["logic", "inverter", "buffer", "flipflop", "latch", "mux", "arith",
  "clock", "delay", "tristate", "tie", "power", "physical", "other"];

// Plain-language meaning of each category, for the empty search hint and tips.
export const CATEGORY_TIPS = {
  logic: "AND, OR, NAND, NOR, XOR and the combined AND-OR-Invert shapes synthesis maps your logic onto.",
  inverter: "Flip a signal. The smallest, fastest cells in the library.",
  buffer: "Pass a signal through unchanged, with more drive. The resizer inserts them on long or heavily loaded nets.",
  flipflop: "Store one bit on a clock edge. Every register in your RTL becomes one of these.",
  latch: "Store one bit while an enable is active. Usually a sign of an unintended latch in RTL.",
  mux: "Pick one of several inputs with a select signal.",
  arith: "Full and half adders: one cell instead of a handful of gates for + and -.",
  clock: "Clock buffers, inverters and clock gates, balanced for the clock tree.",
  delay: "Deliberately slow buffers, used to fix hold violations.",
  tristate: "Outputs that can float (Z), for shared buses.",
  tie: "Constant 0 and 1 sources.",
  power: "Isolation, level-shifting and retention cells for designs with several power domains.",
  physical: "No logic: fill, decap, well taps, end caps and antenna diodes the flow places itself.",
  other: "Everything else.",
};
