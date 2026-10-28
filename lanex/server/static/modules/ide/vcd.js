// vcd.js — a small, dependency-free VCD parser and the value helpers the
// waveform viewer (waves.js) and the CSV export share. VCD is a simple text
// format: a header of $scope/$var declarations, then timestamped value
// changes. Pure, so node can test it against the same golden dump the Python
// parsers read.

// parseVCD(text) -> {
//   timescale: "1ns",                   // as written in the header
//   tick: { mult: 1, unit: "ns", exp: -9 },  // the same, as numbers
//   end: <last time>,
//   signals: [{ id, name, width, scope:[...], type }],   // one per id, declaration order
//   vars: [{ id, name, base, width, scope:[...], type, path }],  // every declaration, aliases too
//   byId: { <id>: { id, name, width, changes:[[t, value], ...] } },
//   scopes: { name, kind, children:[...], signals:[...] }   // tree for the signal picker
// }
export function parseVCD(text) {
  const out = {
    timescale: "",
    tick: { mult: 1, unit: "s", exp: 0 },
    end: 0,
    signals: [],
    vars: [],
    byId: Object.create(null),
    scopes: { name: "(root)", kind: "root", children: [], signals: [] },
  };
  const scopeStack = [out.scopes];
  const lines = (text || "").split(/\r?\n/);
  let time = 0;
  let headerDone = false;

  const tokensOf = (line) => line.trim().split(/\s+/).filter(Boolean);

  for (let i = 0; i < lines.length; i++) {
    const t = lines[i].trim();
    if (!t) continue;

    if (!headerDone && t[0] === "$") {
      const toks = tokensOf(t);
      const kw = toks[0];
      if (kw === "$timescale") {
        // The value may sit on the same line or the next ones, up to $end.
        let parts = toks.slice(1);
        while (!parts.includes("$end") && i + 1 < lines.length) {
          i++; parts = parts.concat(tokensOf(lines[i]));
        }
        out.timescale = parts.filter((p) => p !== "$end").join(" ").trim();
        out.tick = parseTimescale(out.timescale);
        continue;
      }
      if (kw === "$scope") {
        const node = { name: toks[2] || toks[1] || "scope", kind: toks[2] ? toks[1] : "module", children: [], signals: [] };
        scopeStack[scopeStack.length - 1].children.push(node);
        scopeStack.push(node);
        continue;
      }
      if (kw === "$upscope") {
        if (scopeStack.length > 1) scopeStack.pop();
        continue;
      }
      if (kw === "$var") {
        // $var wire 8 # data [7:0] $end   (type width id name [range])
        const width = parseInt(toks[2], 10) || 1;
        const id = toks[3];
        const base = toks[4] || id;
        let name = base;
        if (toks[5] && toks[5] !== "$end") name += toks[5]; // bit range, e.g. [7:0]
        const scopePath = scopeStack.slice(1).map((s) => s.name);
        const sig = { id, name, width, type: toks[1], scope: scopePath };
        if (!out.byId[id]) {
          out.byId[id] = { id, name, width, changes: [] };
          out.signals.push(sig);
        }
        out.vars.push({ ...sig, base, path: scopePath.concat([name]).join(".") });
        scopeStack[scopeStack.length - 1].signals.push(sig);
        continue;
      }
      if (kw === "$enddefinitions") { headerDone = true; continue; }
      // $date / $version / $comment: skip their text up to $end.
      if ((kw === "$date" || kw === "$version" || kw === "$comment") && !toks.includes("$end")) {
        while (i + 1 < lines.length && !lines[i + 1].includes("$end")) i++;
        i++;
      }
      continue;
    }

    // Value-change section. Simulators write one change per line, but the
    // format only asks for whitespace between them (some tools put a whole
    // `$dumpvars 0! b1010 " $end` on one line), so read it as tokens.
    if (t.indexOf(" ") < 0 && t.indexOf("\t") < 0) { time = valueToken(out, t, null, time); continue; }
    const toks = tokensOf(t);
    for (let k = 0; k < toks.length; k++) {
      const c = toks[k][0];
      if ((c === "b" || c === "B" || c === "r" || c === "R") && k + 1 < toks.length) {
        time = valueToken(out, toks[k], toks[k + 1], time);
        k++;
      } else time = valueToken(out, toks[k], null, time);
    }
  }
  return out;
}

// One token of the value section (with the id that follows a vector/real).
// Returns the current time, which a `#<time>` token moves.
function valueToken(out, tok, id, time) {
  const c = tok[0];
  if (c === "#") {
    const t = Number(tok.slice(1));
    if (!Number.isFinite(t)) return time;
    if (t > out.end) out.end = t;
    return t;
  }
  if (c === "0" || c === "1" || c === "x" || c === "z" || c === "X" || c === "Z") {
    // scalar: <value><id>
    pushChange(out, tok.slice(1), time, c.toLowerCase());
  } else if (c === "b" || c === "B") {
    // vector: b<bits> <id>
    if (id) pushChange(out, id, time, tok.slice(1).toLowerCase());
  } else if (c === "r" || c === "R") {
    // real: r<value> <id>
    if (id) pushChange(out, id, time, tok.slice(1));
  }
  // $dumpvars / $dumpall / $dumpon / $dumpoff / $end and comments: nothing to keep.
  return time;
}

function pushChange(out, id, time, value) {
  const sig = out.byId[id];
  if (!sig) return;
  const last = sig.changes[sig.changes.length - 1];
  if (last && last[0] === time) last[1] = value;     // same-time overwrite
  else if (!last || last[1] !== value) sig.changes.push([time, value]);
}

const UNIT_EXP = { s: 0, ms: -3, us: -6, ns: -9, ps: -12, fs: -15 };

// "1ns", "10 ps", "100fs" -> { mult, unit, exp } (exp: the unit's power of ten).
export function parseTimescale(ts) {
  const m = String(ts || "").trim().match(/^(\d+)\s*([munpf]?s)$/i);
  if (!m) return { mult: 1, unit: "s", exp: 0 };
  const unit = m[2].toLowerCase();
  return { mult: parseInt(m[1], 10) || 1, unit, exp: UNIT_EXP[unit] ?? 0 };
}

// A time in ticks as a readable duration in the best-fitting unit, e.g.
// 87402 ticks of 1ps -> "87.402 ns". `step` (ticks) sets how many decimals are
// worth showing, so ruler labels stay short.
const UNITS = [["s", 0], ["ms", -3], ["us", -6], ["ns", -9], ["ps", -12], ["fs", -15]];
// Icarus writes "$timescale 1s" when no source file sets a `timescale: those
// ticks are plain simulation time units, not seconds (no real design uses 1 s).
export function plainTicks(tick) {
  return !!tick && tick.unit === "s" && tick.mult === 1;
}
export function formatTime(ticks, tick, step) {
  const t = tick || { mult: 1, exp: 0 };
  if (!ticks) return "0";
  if (plainTicks(tick)) return String(Math.round(ticks * 1e6) / 1e6);
  // The largest unit in which the amount is at least 1.
  const ref = Math.abs(ticks) * t.mult;
  let pick = UNITS[UNITS.length - 1];
  for (const u of UNITS) {
    if (ref * Math.pow(10, t.exp - u[1]) >= 1 - 1e-9) { pick = u; break; }
  }
  const scale = t.mult * Math.pow(10, t.exp - pick[1]);
  const v = ticks * scale;
  let s;
  if (step) {
    // Ruler labels: as many decimals as the tick spacing needs.
    const sv = Math.abs(step * scale);
    s = v.toFixed(sv >= 1 ? 0 : Math.min(6, Math.ceil(-Math.log10(sv) - 1e-9)));
  } else {
    // Readouts: exact to the dump's own resolution, trailing zeros dropped.
    s = v.toFixed(Math.min(9, Math.max(0, pick[1] - t.exp)));
    if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  }
  return s + " " + (pick[0] === "us" ? "µs" : pick[0]);
}

// Index of the last change at or before `time` (-1 if none). Binary search,
// so a cursor sweep over a long dump stays cheap.
export function indexAt(changes, time) {
  let lo = 0, hi = changes.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (changes[mid][0] <= time) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans;
}

export function valueAt(sig, time) {
  const i = indexAt(sig.changes, time);
  return i < 0 ? "x" : sig.changes[i][1];
}

// Export a parsed VCD to CSV: one row per distinct time, one column per signal,
// each cell the signal's value at that time (radix-formatted). `ids` restricts
// to the visible signals; defaults to all. `radixOf(id)` may pick a radix per
// signal. Pure string — the caller downloads it.
export function vcdToCSV(vcd, ids, radix, radixOf, nameOf) {
  if (!vcd) return "";
  const sigIds = (ids && ids.length ? ids : vcd.signals.map((s) => s.id)).filter((id) => vcd.byId[id]);
  const sigs = sigIds.map((id) => vcd.byId[id]);
  // Union of all change timestamps across the chosen signals.
  const times = new Set([0]);
  for (const s of sigs) for (const [t] of s.changes) times.add(t);
  const ordered = [...times].sort((a, b) => a - b);
  const cell = (s, v) => {
    if (v === undefined || v === null) return "";
    if (s.width > 1) return formatValue(v, (radixOf && radixOf(s.id)) || radix || "hex", s.width);
    return v;
  };
  const esc = (x) => {
    const str = String(x);
    return /[",\n]/.test(str) ? '"' + str.replace(/"/g, '""') + '"' : str;
  };
  const header = ["time" + (vcd.timescale ? " (" + vcd.timescale + ")" : "")]
    .concat(sigs.map((s, i) => (nameOf ? nameOf(sigIds[i]) : s.name)));
  const rows = [header.map(esc).join(",")];
  for (const t of ordered) {
    rows.push([t].concat(sigs.map((s) => cell(s, valueAt(s, t)))).map(esc).join(","));
  }
  return rows.join("\n") + "\n";
}

// A VCD bit string as text in a radix: "hex" (default), "dec", "signed",
// "bin", "oct" or "ascii". BigInt throughout, so a 64-bit bus is exact.
// Bits the simulator didn't know stay visible: a hex digit whose nibble holds
// an x shows as "x" ("z" when the whole nibble floats), and decimal views of
// such a value show "x" / "z". Width (when given) pads the short strings VCD
// writes (leading zeros are dropped in the dump).
export function formatValue(bits, radix, width) {
  if (bits === undefined || bits === null) return "";
  bits = String(bits);
  if (/^[-+]?\d*\.\d*(e[-+]?\d+)?$/i.test(bits) && bits.includes(".")) return bits;   // real
  const w = Math.max(width || 0, bits.length);
  // VCD drops leading digits: pad with x/z when the value starts with one,
  // else with 0 (IEEE 1364 left-extension).
  const fill = bits[0] === "x" || bits[0] === "z" ? bits[0] : "0";
  if (bits.length < w) bits = fill.repeat(w - bits.length) + bits;
  if (radix === "bin") return bits;
  if (bits.length === 1) return bits;
  const unknown = /[xz]/.test(bits);
  if (radix === "hex" || !radix || radix === "oct") {
    const g = radix === "oct" ? 3 : 4;
    const pad = (g - (bits.length % g)) % g;
    const b = (bits[0] === "x" || bits[0] === "z" ? bits[0] : "0").repeat(pad) + bits;
    let s = "";
    for (let i = 0; i < b.length; i += g) {
      const nib = b.slice(i, i + g);
      if (/^z+$/.test(nib)) s += "z";
      else if (/[xz]/.test(nib)) s += "x";
      else s += parseInt(nib, 2).toString(g === 4 ? 16 : 8);
    }
    return g === 4 ? s.toUpperCase().replace(/X/g, "x").replace(/Z/g, "z") : s;
  }
  if (unknown) return /^z+$/.test(bits) ? "z" : "x";
  const n = BigInt("0b" + bits);
  if (radix === "dec") return n.toString();
  if (radix === "signed") {
    const top = 1n << BigInt(bits.length - 1);
    return (n >= top ? n - (top << 1n) : n).toString();
  }
  if (radix === "ascii") {
    // Verilog strings are packed 8 bits a character, first character on the
    // left; leading NUL bytes are the unused part of the register.
    const b = "0".repeat((8 - (bits.length % 8)) % 8) + bits;
    let s = "";
    for (let i = 0; i < b.length; i += 8) {
      const code = parseInt(b.slice(i, i + 8), 2);
      if (code === 0 && !s) continue;
      s += code >= 32 && code < 127 ? String.fromCharCode(code) : ".";
    }
    return '"' + s + '"';
  }
  return n.toString(16).toUpperCase();
}
