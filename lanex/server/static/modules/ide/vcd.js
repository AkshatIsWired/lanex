// vcd.js — a small, dependency-free VCD parser (Phase 3.6). VCD is a simple
// text format: a header of $scope/$var declarations, then timestamped value
// changes. We parse it into a signal tree + per-signal value-change lists the
// canvas waveform renderer (waves.js) consumes. Pure — node-testable.

// parseVCD(text) -> {
//   timescale: "1ns",
//   end: <last time>,
//   signals: [{ id, name, width, scope:[...], type }],   // declaration order
//   byId: { <id>: { id, name, width, changes:[[t, value], ...] } },
//   scopes: nested tree for the signal picker
// }
export function parseVCD(text) {
  const out = {
    timescale: "",
    end: 0,
    signals: [],
    byId: Object.create(null),
    scopes: { name: "(root)", children: [], signals: [] },
  };
  const scopeStack = [out.scopes];
  const lines = (text || "").split(/\r?\n/);
  let time = 0;
  let inDumpHeaderDone = false;

  const tokensOf = (line) => line.trim().split(/\s+/).filter(Boolean);

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    const t = line.trim();
    if (!t) continue;

    if (!inDumpHeaderDone && t.startsWith("$")) {
      const toks = tokensOf(t);
      const kw = toks[0];
      if (kw === "$timescale") {
        // value may be on same or next lines until $end
        let parts = toks.slice(1);
        while (!parts.includes("$end") && i + 1 < lines.length) {
          i++; parts = parts.concat(tokensOf(lines[i]));
        }
        out.timescale = parts.filter((p) => p !== "$end").join(" ").trim();
        continue;
      }
      if (kw === "$scope") {
        const node = { name: toks[2] || toks[1] || "scope", children: [], signals: [] };
        scopeStack[scopeStack.length - 1].children.push(node);
        scopeStack.push(node);
        continue;
      }
      if (kw === "$upscope") {
        if (scopeStack.length > 1) scopeStack.pop();
        continue;
      }
      if (kw === "$var") {
        // $var wire 8 # data $end   (type width id name)
        const width = parseInt(toks[2], 10) || 1;
        const id = toks[3];
        let name = toks[4] || id;
        if (toks[5] && toks[5] !== "$end") name += toks[5]; // bit-select e.g. [7:0]
        const scopePath = scopeStack.slice(1).map((s) => s.name);
        const sig = { id, name, width, type: toks[1], scope: scopePath };
        if (!out.byId[id]) {
          out.byId[id] = { id, name, width, changes: [] };
          out.signals.push(sig);
        }
        scopeStack[scopeStack.length - 1].signals.push(sig);
        continue;
      }
      if (kw === "$enddefinitions") { inDumpHeaderDone = true; continue; }
      // $dumpvars / $comment / $version / $date — skip to $end if multi-line
      continue;
    }

    // Value-change section.
    if (t[0] === "#") {
      time = parseInt(t.slice(1), 10) || 0;
      if (time > out.end) out.end = time;
      continue;
    }
    const c = t[0];
    if (c === "0" || c === "1" || c === "x" || c === "z" || c === "X" || c === "Z") {
      // scalar: <value><id>
      const val = c.toLowerCase();
      const id = t.slice(1);
      pushChange(out, id, time, val);
    } else if (c === "b" || c === "B" || c === "r" || c === "R") {
      // vector: b<bits> <id>  OR real: r<value> <id>
      const sp = t.indexOf(" ");
      const val = t.slice(1, sp < 0 ? undefined : sp);
      const id = sp < 0 ? "" : t.slice(sp + 1).trim();
      if (id) pushChange(out, id, time, (c === "r" || c === "R") ? val : val.toLowerCase());
    }
  }
  return out;
}

function pushChange(out, id, time, value) {
  const sig = out.byId[id];
  if (!sig) return;
  const last = sig.changes[sig.changes.length - 1];
  if (last && last[0] === time) last[1] = value;     // same-time overwrite
  else sig.changes.push([time, value]);
}

// Export a parsed VCD to CSV: one row per distinct time, one column per signal,
// each cell the signal's value at that time (radix-formatted). `ids` restricts
// to the visible signals; defaults to all. Pure string — caller Blob-downloads.
export function vcdToCSV(vcd, ids, radix) {
  if (!vcd) return "";
  const sigIds = (ids && ids.length ? ids : vcd.signals.map((s) => s.id)).filter((id) => vcd.byId[id]);
  const sigs = sigIds.map((id) => vcd.byId[id]);
  // Union of all change timestamps across the chosen signals.
  const times = new Set([0]);
  for (const s of sigs) for (const [t] of s.changes) times.add(t);
  const ordered = [...times].sort((a, b) => a - b);
  const valueAt = (s, time) => {
    let v = "x";
    for (const [t, val] of s.changes) { if (t <= time) v = val; else break; }
    return v;
  };
  const cell = (s, v) => {
    if (v === undefined || v === null) return "";
    if (s.width > 1) return formatValue(v, radix || "hex");
    return v;
  };
  const esc = (x) => {
    const str = String(x);
    return /[",\n]/.test(str) ? '"' + str.replace(/"/g, '""') + '"' : str;
  };
  const header = ["time" + (vcd.timescale ? " (" + vcd.timescale + ")" : "")]
    .concat(sigs.map((s) => s.name));
  const rows = [header.map(esc).join(",")];
  for (const t of ordered) {
    rows.push([t].concat(sigs.map((s) => cell(s, valueAt(s, t)))).map(esc).join(","));
  }
  return rows.join("\n") + "\n";
}

// Format a binary string value with a radix for the bus label.
export function formatValue(bits, radix) {
  if (bits === undefined || bits === null) return "";
  if (/[xz]/.test(bits)) return bits;
  if (radix === "bin") return "b" + bits;
  if (bits.length === 1) return bits;
  const n = parseInt(bits, 2);
  if (isNaN(n)) return bits;
  if (radix === "dec") return String(n);
  if (radix === "signed") {
    const w = bits.length;
    const signed = n >= (1 << (w - 1)) ? n - (1 << w) : n;
    return String(signed);
  }
  return "0x" + n.toString(16);   // hex default
}
