// Copyright 2026 LanEx Contributors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Frontend behavioural test — the display layer the user actually reads.
//
// CI syntax-checks every JS file (`node --check`) but never EXECUTES it, so a
// bug in the number-formatting / escaping / CSV-quoting that turns tool output
// into what the user sees would pass unnoticed. This runs those pure display
// functions and asserts their behaviour. Zero dependencies (node:assert +
// dynamic import of the real product modules); runs on every PR.
//
//   node lanex/tests/frontend_test.mjs      → exit 0 = pass, 1 = fail

import assert from "node:assert/strict";
import { readFileSync, appendFileSync, readdirSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const MOD = resolve(HERE, "..", "server", "static", "modules");
const toUrl = (p) => pathToFileURL(p).href;

const { api, fmt } = await import(toUrl(resolve(MOD, "api.js")));
const { csvCell } = await import(toUrl(resolve(MOD, "csvutil.js")));
const { clampZoom } = await import(toUrl(resolve(MOD, "zoom.js")));
const toolsModule = await import(toUrl(resolve(MOD, "tools.js")));
const { normalizeUnavailableLibraries } = toolsModule;

let passed = 0;
const results = [];
function check(name, fn) {
  try {
    fn();
    passed += 1;
    results.push({ name, ok: true, msg: "" });
    console.log(`  ok   ${name}`);
  } catch (e) {
    results.push({ name, ok: false, msg: String(e.message || e) });
    console.error(`  FAIL ${name}: ${e.message}`);
    process.exitCode = 1;
  }
}

async function checkAsync(name, fn) {
  try {
    await fn();
    passed += 1;
    results.push({ name, ok: true, msg: "" });
    console.log(`  ok   ${name}`);
  } catch (e) {
    results.push({ name, ok: false, msg: String(e.message || e) });
    console.error(`  FAIL ${name}: ${e.message}`);
    process.exitCode = 1;
  }
}

// ------------------------------------------------- fmt.metric (F-1 + honesty)
check("metric: absent value shows the em-dash, never a number", () => {
  assert.equal(fmt.metric(null), "—");
  assert.equal(fmt.metric(undefined), "—");
});

check("metric: non-finite tokens humanise, never leak raw", () => {
  assert.equal(fmt.metric("Infinity"), "∞");
  assert.equal(fmt.metric("-Infinity"), "−∞");
  assert.equal(fmt.metric(Infinity), "∞");
});

check("metric: NaN is labelled NaN (a real value), distinct from — (absent)", () => {
  assert.equal(fmt.metric("NaN"), "NaN");
  assert.equal(fmt.metric(NaN), "NaN");
  assert.notEqual(fmt.metric("NaN"), fmt.metric(null));
});

check("metric: sub-milli values are NOT rounded to 0.000", () => {
  // A +0.0004 worst-slack must not read as exactly zero margin.
  const s = fmt.metric(0.0004);
  assert.notEqual(s, "0.000");
  assert.match(s, /e-/i, `expected exponential, got ${s}`);
  assert.notEqual(fmt.metric(-0.0001), "-0.000");
});

check("metric: ordinary magnitudes keep 3 decimals; large values group", () => {
  assert.equal(fmt.metric(42.5), "42.500");
  assert.equal(fmt.metric(0), "0.000");
  assert.equal(typeof fmt.metric(1234567), "string");
});

check("metric: large values group with a FIXED comma, never a locale dot (N5)", () => {
  // en-US separator is pinned so a de-DE browser can't render 1235 as "1.235"
  // and have it read as a decimal (a silent ×1000 misread of a real number).
  assert.equal(fmt.metric(1234567), "1,234,567");
  assert.equal(fmt.metric(1235), "1,235");
  assert.ok(!/^\d+\.\d{3}$/.test(fmt.metric(1235)),
    "grouped value must not look like a 3-decimal number");
});

check("fmt.raw: exact unrounded value for hover disclosure, honest on edges (N5)", () => {
  assert.equal(fmt.raw(145678.9), "145678.9");   // rounding of metric() is disclosed on hover
  assert.equal(fmt.raw(null), "");
  assert.equal(fmt.raw(undefined), "");
  assert.equal(fmt.raw("Infinity"), "∞");
  assert.equal(fmt.raw("NaN"), "NaN");
});

// ----------------------------------------------- fmt.escape (XSS / corruption)
check("escape: angle brackets become real entities (raw < never survives)", () => {
  const out = fmt.escape("<script>alert(1)</script>");
  assert.equal(out, "&lt;script&gt;alert(1)&lt;/script&gt;");
  assert.ok(!out.includes("<"), "raw < leaked through escape");
  assert.ok(!out.includes(">"), "raw > leaked through escape");
});

check("escape: ampersand, quote and apostrophe are entity-encoded", () => {
  assert.equal(fmt.escape("a & b"), "a &amp; b");
  const dq = String.fromCharCode(34), sq = String.fromCharCode(39);
  assert.equal(fmt.escape(dq + sq), "&quot;&#39;");
});

check("escape: a benign DRC-style string with '<' renders readably", () => {
  // e.g. "P-diff distance ... must be < 15.0um" from a Magic report.
  const out = fmt.escape("spacing < 0.14um");
  assert.equal(out, "spacing &lt; 0.14um");
});

// ------------------------------------------------- csvCell (HARD-1 injection)
check("csvCell: a formula-leading text cell is neutralised", () => {
  assert.equal(csvCell("=1+1"), "'=1+1");
  assert.equal(csvCell("+cmd"), "'+cmd");
  assert.equal(csvCell("@SUM(A1)"), "'@SUM(A1)");
});

check("csvCell: real numbers (incl. negative / exponent) pass unchanged", () => {
  assert.equal(csvCell("-5"), "-5");
  assert.equal(csvCell("-0.285741"), "-0.285741");
  assert.equal(csvCell("1.2e-4"), "1.2e-4");
  assert.equal(csvCell("42"), "42");
});

check("csvCell: values with commas/quotes are RFC-4180 quoted", () => {
  assert.equal(csvCell("a,b"), '"a,b"');
  assert.equal(csvCell('he said "hi"'), '"he said ""hi"""');
});

check("clampZoom: bounds, snap, garbage → 1", () => {
  assert.equal(clampZoom(1), 1);
  assert.equal(clampZoom(0.05), 0.5);      // floor
  assert.equal(clampZoom(9), 2);           // ceiling
  assert.equal(clampZoom(1.2000000000000002), 1.2); // float dust snapped
  assert.equal(clampZoom("1.3"), 1.3);     // localStorage strings
  assert.equal(clampZoom("junk"), 1);
  assert.equal(clampZoom(-1), 1);
  assert.equal(clampZoom(NaN), 1);
});

check("zoom: stylesheets compensate viewport units via --ll-zoom", () => {
  // CSS `zoom` scales layout px but vw/vh keep resolving against the real
  // viewport — without the compensation the shell under/overflows the window
  // at any zoom ≠ 100% (round-56 user bug). zoom.js must publish the factor
  // and every cockpit stylesheet's viewport unit must divide by it.
  const STATIC = resolve(HERE, "..", "server", "static");
  assert.match(readFileSync(resolve(MOD, "zoom.js"), "utf8"),
    /setProperty\("--ll-zoom"/);
  // Every app stylesheet (the landing page is not zoomed), and the dynamic /
  // small / large viewport units too: 100dvh slipped through once (Layout).
  const core = ["styles.css", "features.css", "ide.css"];
  const sheets = readdirSync(STATIC).filter((f) => f.endsWith(".css") && f !== "landing.css");
  for (const f of core) assert.ok(sheets.includes(f), f);
  for (const f of sheets) {
    const css = readFileSync(resolve(STATIC, f), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "");   // comments may mention 100vw freely
    if (core.includes(f)) assert.match(css, /var\(--ll-zoom, 1\)/, `${f} lost the zoom compensation`);
    for (const ln of css.split("\n")) {
      if (/\d(?:[dsl]?v[wh]|vmin|vmax)\b/.test(ln) && !ln.includes("--ll-zoom")) {
        assert.fail(`${f}: viewport unit without --ll-zoom compensation: ${ln.trim()}`);
      }
    }
  }
});

check("layouttools: 'no display' still answers a click with the remedy", () => {
  // A disabled control can never be clicked, so the user never saw the
  // XQuartz/WSLg remedy carried in display.reason (round-59 macOS bug). The
  // nodisplay route must carry the reason and launchTool must show it sticky;
  // the Layout tab's viewer buttons are never disabled.
  const src = readFileSync(resolve(MOD, "layouttools.js"), "utf8");
  assert.match(src, /where: "nodisplay", title: \(container\.display && container\.display\.reason\)/,
    "nodisplay route must carry the display remedy");
  assert.match(src, /r\.where === "nodisplay"[\s\S]{0,300}toast\.show\([^;]*r\.title[^;]*"warn", 0\)/,
    "nodisplay click must show the remedy in a sticky toast");
  const page = readFileSync(resolve(MOD, "layout.js"), "utf8");
  const desk = page.slice(page.indexOf("async function renderDesk"), page.indexOf("function paintOpenMain"));
  assert.ok(desk.length > 0 && !/disabled/.test(desk), "desktop viewer buttons must never be disabled");
});

check("tools: engine-not-usable card is platform-aware with a Start action", () => {
  // Round-63 macOS bug: an installed-but-dead Docker showed ONLY the Linux
  // systemctl/usermod remedy — on macOS the daemon exists solely while Docker
  // Desktop runs, so the card must branch on the server-reported platform and
  // offer one-click Start buttons wired to /api/container/start-engine.
  const src = readFileSync(resolve(MOD, "tools.js"), "utf8");
  const card = src.indexOf("Container engine installed but not currently active");
  assert.ok(card >= 0, "not-usable card not found");
  assert.match(src, /c\.platform === "darwin"/,
    "the card no longer branches on the server-reported platform");
  for (const id of ["btn-start-docker", "btn-start-podman"]) {
    assert.ok(src.includes(id), `Start button ${id} missing`);
  }
  assert.match(src, /startEngineAction\("docker"\)/);
  const api = readFileSync(resolve(MOD, "api.js"), "utf8");
  assert.match(api, /\/api\/container\/start-engine/,
    "api.startEngine endpoint missing");
  // The SSE outcome path must treat engine:<name> keys as a start (chain the
  // pull), never as a tool install.
  assert.match(src, /engine:/, "installer_result engine: key handling missing");
  // Recheck must bypass the server's 8s status caches — a probe cached moments
  // before the user fixed the engine reads as still-broken.
  assert.match(api, /\/api\/tools" \+ \(fresh \? "\?fresh=1" : ""\)/,
    "api.tools lost the fresh bypass");
  assert.match(src, /renderTools\(true\)/,
    "the Recheck button no longer forces a fresh probe");
});

// ------------------------------------------- waveform viewer data fidelity
// The SAME golden VCD (a real Icarus dump of the 4-bit counter bench, see
// goldens/sim_run/) that test_wave_fidelity.py holds the python parsers to.
// The in-browser canvas viewer parses it here — so the canvas viewer, the
// GTKWave handoff, and the CI reference parser all read ONE fixture and must
// agree on both the signal list and the VALUES.
const { parseVCD } = await import(toUrl(resolve(MOD, "ide", "vcd.js")));
const GOLDEN_VCD = readFileSync(
  resolve(HERE, "goldens", "sim_run", "dump.vcd"), "utf8");

check("vcd.js: golden dump yields the same deduped signal list as waveview.py", () => {
  const vcd = parseVCD(GOLDEN_VCD);
  const full = vcd.signals.map((s) => (s.scope.length ? s.scope.join(".") + "." : "") + s.name);
  assert.deepEqual(full, [
    "tb_counter.q[3:0]", "tb_counter.clk", "tb_counter.rst", "tb_counter.dut.q[3:0]",
  ]);
  assert.deepEqual(vcd.signals.map((s) => s.width), [4, 1, 1, 4]);
});

check("vcd.js: the counter VALUES on screen equal what the simulator wrote", () => {
  const vcd = parseVCD(GOLDEN_VCD);
  const q = vcd.signals.find((s) => s.name === "q[3:0]" && s.scope.includes("dut"));
  const values = vcd.byId[q.id].changes
    .map(([, v]) => v)
    .filter((v) => /^[01]+$/.test(v))
    .map((v) => parseInt(v, 2));
  assert.deepEqual(values, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    "the rendered counter sequence diverged from the simulation data");
  // The clock genuinely toggles (no dropped edges in the parse).
  const clk = vcd.signals.find((s) => s.name === "clk");
  const clkVals = vcd.byId[clk.id].changes.map(([, v]) => v).filter((v) => /^[01]$/.test(v));
  for (let i = 1; i < clkVals.length; i++) assert.notEqual(clkVals[i], clkVals[i - 1]);
});

// ------------------------------------------- waveform viewer: what it prints
// The value column, bus labels and CSV all go through formatValue/formatTime;
// a wrong digit here is a wrong reading of the simulation.
const { formatValue, formatTime, parseTimescale, valueAt } = await import(toUrl(resolve(MOD, "ide", "vcd.js")));
const { defaultLanes } = await import(toUrl(resolve(MOD, "ide", "waves.js")));

check("vcd.js: radix formatting is exact, padded, and keeps x/z visible", () => {
  assert.equal(formatValue("1010", "hex", 8), "0A");               // VCD drops leading zeros
  assert.equal(formatValue("x1", "hex", 8), "xx");                  // x extends left (IEEE 1364)
  assert.equal(formatValue("zzzz", "hex", 4), "z");
  assert.equal(formatValue("1x0000", "hex", 8), "x0");              // only the unknown nibble
  assert.equal(formatValue("11111111", "signed", 8), "-1");
  assert.equal(formatValue("1".repeat(64), "dec", 64), "18446744073709551615");   // no float rounding
  assert.equal(formatValue("1" + "0".repeat(63), "signed", 64), "-9223372036854775808");
  assert.equal(formatValue("0100100001101001", "ascii", 16), '"Hi"');
  assert.equal(formatValue("101", "bin", 8), "00000101");
  assert.equal(formatValue("x", "dec", 8), "x");
});

check("vcd.js: times read in real units, exact to the dump's resolution", () => {
  const ps = parseTimescale("1ps");
  assert.deepEqual(ps, { mult: 1, unit: "ps", exp: -12 });
  assert.equal(formatTime(87402, ps), "87.402 ns");
  assert.equal(formatTime(242000, ps), "242 ns");
  assert.equal(formatTime(1500000000, ps), "1.5 ms");
  assert.equal(formatTime(5, parseTimescale("10ns")), "50 ns");
  assert.equal(formatTime(120020, ps, 20), "120.02 ns");            // ruler label, decimals from the step
  assert.equal(formatTime(0, ps), "0");
});

check("vcd.js: aliases stay addressable; values come from the shared stream", () => {
  const vcd = parseVCD(GOLDEN_VCD);
  const paths = vcd.vars.map((v) => v.path);
  assert.ok(paths.includes("tb_counter.dut.clk") && paths.includes("tb_counter.clk"));
  const alias = vcd.vars.find((v) => v.path === "tb_counter.dut.clk");
  const own = vcd.vars.find((v) => v.path === "tb_counter.clk");
  assert.equal(alias.id, own.id);
  assert.equal(valueAt(vcd.byId[alias.id], 5), "1");
  assert.equal(valueAt(vcd.byId[alias.id], 4), "0");
});

check("vcd.js: several changes on one line read the same as one per line", () => {
  // VCD only asks for whitespace between changes; some writers put a whole
  // $dumpvars block, or a time and its changes, on one line.
  const head = ["$timescale 1ns $end", "$scope module tb $end", "$var wire 1 ! clk $end",
    "$var wire 4 \" q [3:0] $end", "$var real 64 # r $end", "$upscope $end", "$enddefinitions $end"];
  const one = parseVCD(head.concat(["#0", "$dumpvars", "0!", "b0 \"", "r0.5 #", "$end", "#5", "1!", "b1010 \"", "#10", "0!"]).join("\n"));
  const packed = parseVCD(head.concat(["#0 $dumpvars 0! b0 \" r0.5 # $end", "#5 1! b1010 \"", "#10 0!"]).join("\n"));
  for (const v of [one, packed]) {
    assert.equal(v.end, 10);
    assert.deepEqual(v.byId["!"].changes, [[0, "0"], [5, "1"], [10, "0"]]);
    assert.deepEqual(v.byId["\""].changes, [[0, "0"], [5, "1010"]]);
    assert.deepEqual(v.byId["#"].changes, [[0, "0.5"]]);
  }
});

check("waves.js: the first view shows the bench's signals, clock and reset first, no parameters", () => {
  const vcd = parseVCD([
    "$timescale 1ns $end", "$scope module tb $end",
    "$var wire 8 ! q [7:0] $end", "$var reg 1 \" rst $end", "$var reg 1 # clk $end",
    "$var parameter 32 $ WIDTH $end",
    "$scope module dut $end", "$var wire 1 # clk $end", "$var reg 4 % state [3:0] $end", "$upscope $end",
    "$upscope $end", "$enddefinitions $end", "#0", "0#", "1\"", "b0 !", "b0 %",
  ].join("\n"));
  assert.deepEqual(defaultLanes(vcd), ["tb.clk", "tb.rst", "tb.q[7:0]", "tb.dut.state[3:0]"]);
});

// ------------------------------- LibreLane-output → on-screen display fidelity
// goldens/display_run/metrics.json is a REAL SPM container run's final
// metrics.json (305 metrics: ints, floats, sub-milli magnitudes, +Infinity,
// strings). Every value goes through the SAME token bridge the server applies
// (json_safe stringifies non-finite floats) and then through fmt.metric — the
// string the user actually reads. Each render must be faithful: parseable back
// to the original within the format's own precision, tokens humanised,
// absent-vs-NaN never blurred, strings unmangled.
check("display fidelity: all 300+ real run metrics render faithfully", () => {
  const raw = readFileSync(resolve(HERE, "goldens", "display_run", "metrics.json"), "utf8");
  // Mirror of server-side json_safe: python's json.dump wrote bare Infinity/
  // NaN literals; the server converts them to quoted tokens before the wire.
  const tokened = raw.replace(/([:\[,]\s*)(-?Infinity|NaN)(\s*[,}\]])/g, '$1"$2"$3');
  const metrics = JSON.parse(tokened);
  const keys = Object.keys(metrics);
  assert.ok(keys.length >= 300, `golden shrank: only ${keys.length} metrics`);
  let checked = 0;
  for (const [key, v] of Object.entries(metrics)) {
    const r = fmt.metric(v);
    assert.notEqual(r, "—", `${key}: a PRESENT value rendered as absent`);
    if (v === "Infinity") { assert.equal(r, "∞", key); checked++; continue; }
    if (v === "-Infinity") { assert.equal(r, "−∞", key); checked++; continue; }
    if (v === "NaN") { assert.equal(r, "NaN", key); checked++; continue; }
    if (typeof v === "string") { assert.equal(r, v, `${key}: string mangled`); checked++; continue; }
    // Finite number: never rendered as NaN/∞, and parse-back must recover the
    // value within the branch's own formatting precision.
    assert.ok(r !== "NaN" && r !== "∞" && r !== "−∞", `${key}: finite value rendered non-finite`);
    if (v !== 0 && Math.abs(v) < 0.001) {
      assert.match(r, /e/, `${key}: sub-milli value ${v} lost to "0.000"`);
      const back = parseFloat(r);
      assert.ok(Math.abs(back - v) <= Math.abs(v) * 0.01, `${key}: ${r} !≈ ${v}`);
    } else if (Math.abs(v) < 100) {
      const back = parseFloat(r);
      assert.ok(Math.abs(back - v) <= 0.0005001, `${key}: ${r} !≈ ${v}`);
    } else {
      const back = parseFloat(r.replace(/[,\s  ]/g, ""));
      assert.ok(Math.abs(back - v) <= 0.5 + Math.abs(v) * 1e-9, `${key}: ${r} !≈ ${v}`);
    }
    checked++;
  }
  assert.equal(checked, keys.length);
});

// The Analytics charts draw from the same metrics object — the option builders
// are pure (charts.js), so run them on the golden run's real values and require
// exact passthrough into the series data. A unit conversion or key typo that
// would plot wrong numbers fails here.
const charts = await import(toUrl(resolve(MOD, "charts.js")));
check("charts.js: golden run values reach the chart series unchanged", () => {
  const raw = readFileSync(resolve(HERE, "goldens", "display_run", "metrics.json"), "utf8");
  const tokened = raw.replace(/([:\[,]\s*)(-?Infinity|NaN)(\s*[,}\]])/g, '$1"$2"$3');
  const m = JSON.parse(tokened);

  const slack = charts.timingSlackOption(m);
  const wantSlack = ["timing__setup__ws", "timing__setup__tns",
                     "timing__hold__ws", "timing__hold__tns"]
    .map((k) => m[k]).filter((v) => typeof v === "number" && isFinite(v));
  assert.deepEqual(slack.series[0].data.map((d) => d.value), wantSlack,
    "slack bars diverged from the run's timing metrics");

  const util = charts.utilizationOption(m);
  const wantPct = Math.round(m["design__instance__utilization"] * 1000) / 10;
  assert.equal(util.series[0].data[0].value, wantPct);

  const power = charts.powerOption(m);
  if (power) {
    for (const d of power.series[0].data) {
      const key = { Internal: "power__internal__total",
                    Switching: "power__switching__total",
                    Leakage: "power__leakage__total" }[d.name];
      assert.equal(d.value, m[key], `${d.name} power mangled`);
    }
  }

  // Non-finite values must be DROPPED from charts (honest), never plotted as 0.
  const inf = charts.trendOption(
    [{ tag: "a", value: "Infinity" }, { tag: "b", value: 1 }, { tag: "c", value: 2 }], "k");
  assert.deepEqual(inf.series[0].data, [1, 2], "non-finite plotted instead of dropped");
});

// ------------------------------------------------ provenance line highlight
// The provenance dialog's whole promise is "THIS line is where the value came
// from" — so the highlight must land on exactly the requested line, escaped.
const { renderFileText } = await import(toUrl(resolve(MOD, "fileview.js")));
check("fileview: the provenance highlight lands on exactly the requested line", () => {
  // Minimal DOM stub: enough for renderFileText's innerHTML writes + queries.
  const el = () => ({
    _html: "", listeners: {},
    set innerHTML(v) { this._html = v; }, get innerHTML() { return this._html; },
    set textContent(v) { this._html = v.replace(/[&<>]/g, (c) => c === "&" ? "&amp;" : c === "<" ? "&lt;" : "&gt;"); },
    get textContent() { return this._html; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    addEventListener(t, f) { this.listeners[t] = f; },
    scrollIntoView() {}, scrollTop: 0, scrollHeight: 0,
  });
  const container = el();
  const pre = el(), input = el(), count = el(), prev = el(), next = el();
  container.querySelector = (sel) => ({
    ".fv-pre": pre, ".fv-find": input, ".fv-count": count,
    ".fv-prev": prev, ".fv-next": next,
  })[sel] || null;
  container.querySelectorAll = () => [];
  // The mark deep in a long file. scrollIntoView must NEVER be used: it also
  // scrolls the scrollable dialog around the pane, pushing the toolbar (file
  // name, Copy path/Download/Locate) permanently out of reach — the reported
  // long-file bug. Centering must move pre.scrollTop alone.
  const mark = {
    offsetTop: 1000, offsetHeight: 16,
    scrollIntoView() { throw new Error("scrollIntoView scrolls the dialog too — banned"); },
  };
  pre.clientHeight = 300;
  pre.querySelector = (sel) => sel === ".fv-line" ? mark : null;

  const text = 'alpha\n    "FP_CORE_UTIL": 45,\n<script>evil</script>\nomega';
  renderFileText(container, text, { line: 2, title: "resolved.json" });
  const body = pre.innerHTML.split("\n");
  assert.match(body[1], /^<mark class='fv-line'>.*FP_CORE_UTIL.*<\/mark>$/,
    "line 2 not wrapped in the highlight mark");
  assert.doesNotMatch(body[0], /<mark/, "line 1 wrongly highlighted");
  assert.doesNotMatch(body[3], /<mark/, "line 4 wrongly highlighted");
  assert.ok(body[2].includes("&lt;script&gt;"), "file content not HTML-escaped");
  assert.ok(container.innerHTML.includes("line 2"), "toolbar missing the line chip");
  // Centered on the pane's own scroll: offsetTop - (clientHeight - markHeight)/2.
  assert.equal(pre.scrollTop, 1000 - (300 - 16) / 2,
    "highlight must center by scrolling the file pane itself");

  // Out-of-range line = no highlight, never a wrong one.
  const c2 = el();
  const pre2 = el();
  c2.querySelector = (sel) => sel === ".fv-pre" ? pre2 :
    ({ ".fv-find": el(), ".fv-count": el(), ".fv-prev": el(), ".fv-next": el() })[sel] || null;
  c2.querySelectorAll = () => [];
  renderFileText(c2, "one\ntwo", { line: 99 });
  assert.doesNotMatch(pre2.innerHTML, /<mark/, "out-of-range line must not highlight anything");
});

// ------------------------------------------------ "your config" field chips
// The Setup form's middle tier: what the design's own config file sets. The
// spm scenario that motivated it — FP_CORE_UTIL: 45 inside pdk::sky130* while
// LibreLane's default chip says 50 — must yield a chip that names the scope
// and declares it conditional, never claiming the scoped value applies.
const prov = await import(toUrl(resolve(MOD, "provenance.js")));
check("provenance.js: config chips state scope + conditionality faithfully", () => {
  const scoped = prov.configChipSpec(
    { line: 6, text: "  FP_CORE_UTIL: 45", value: "45",
      scoped: true, scope: "pdk::sky130*", others: 1 }, "config.yaml");
  assert.equal(scoped.text, "config (pdk::sky130*): 45");
  assert.ok(scoped.title.includes("line 6"), "title must name the exact line");
  assert.ok(scoped.title.includes("pplies only when the run's PDK/SCL matches"),
    "a scoped value must be declared conditional");
  assert.ok(scoped.title.includes("1 more entry"), "extra entries must be disclosed");
  assert.equal(scoped.scoped, true);

  const plain = prov.configChipSpec(
    { line: 3, text: "CLOCK_PERIOD: 10", value: "10",
      scoped: false, scope: null, others: 0 }, "config.yaml");
  assert.equal(plain.text, "your config: 10");
  assert.ok(plain.title.includes("used when no override is present"),
    "an unscoped value is what an untouched field uses");
  assert.ok(!plain.title.includes("more entr"), "no phantom extra entries");
});

// ------------------------------------------------ final-settings preview
// The merged "what will this run send" model. Must mirror the server's
// _assemble_overrides exactly: PDK/STD_CELL_LIBRARY split out as flow
// options, every other override beats the config file, and a config var
// with no override applies as written. Fed the user's real scenario.
const fs = await import(toUrl(resolve(MOD, "finalsettings.js")));
check("finalsettings: overrides vs config vs defaults classified faithfully", () => {
  const map = {
    ok: true, rel: "config.yaml",
    vars: {
      FP_CORE_UTIL: { line: 6, text: "  FP_CORE_UTIL: 45", value: "45",
                      scoped: true, scope: "pdk::sky130*", others: 0 },
      CLOCK_PERIOD: { line: 3, text: "CLOCK_PERIOD: 10", value: "10",
                      scoped: false, scope: null, others: 0 },
    },
  };
  const payload = { PDK: "sky130A", STD_CELL_LIBRARY: "sky130_fd_sc_hd",
                    FP_CORE_UTIL: 50, SYNTH_STRATEGY: "AREA 0" };
  const m = fs.buildFinalSettingsModel(payload, map);

  // PDK/SCL are flow options, never -c rows (mirror of _assemble_overrides).
  assert.equal(m.pdk, "sky130A");
  assert.equal(m.scl, "sky130_fd_sc_hd");
  assert.ok(!m.sent.some((s) => s.name === "PDK" || s.name === "STD_CELL_LIBRARY"),
    "PDK/SCL must not appear as override rows");

  // The user's exact conflict: config 45 (pdk-scoped) vs manual 50 → override
  // wins and the superseded line is named, scope included.
  const fcu = m.sent.find((s) => s.name === "FP_CORE_UTIL");
  assert.equal(fcu.value, "50");
  assert.deepEqual(fcu.conflict,
    { line: 6, value: "45", scoped: true, scope: "pdk::sky130*" });

  // Manual change NOT in the config: sent, honestly marked as adding.
  const ss = m.sent.find((s) => s.name === "SYNTH_STRATEGY");
  assert.equal(ss.conflict, null);

  // Config var the user never touched: applies from the file.
  assert.deepEqual(m.fromConfig.map((c) => c.name), ["CLOCK_PERIOD"]);
  assert.equal(m.fromConfig[0].line, 3);

  // An overridden config var must NOT also be listed as applying.
  assert.ok(!m.fromConfig.some((c) => c.name === "FP_CORE_UTIL"),
    "superseded config var leaked into the applies-list");
  assert.equal(m.conflicts, 1);
});

check("finalsettings: honest when the config map is unavailable", () => {
  const m = fs.buildFinalSettingsModel({ PDK: "sky130A", FP_CORE_UTIL: 50 },
                                       { ok: false, reason: "no config file" });
  assert.equal(m.rel, null);
  assert.equal(m.fromConfig.length, 0);
  // The override is still truthfully listed — it IS sent regardless.
  assert.equal(m.sent.length, 1);
  assert.equal(m.sent[0].conflict, null, "no map = no conflict claims, ever");
});

// ------------------------------------------------ cumulative directory
// "What about all the OTHER values?" — one row per known variable with the
// pre-run effective source: override > config > PDK-provided > LibreLane
// default > unset. Values honest: PDK-flagged vars never claim a number the
// PDK will decide.
check("finalsettings: the cumulative directory classifies every variable", () => {
  const registry = [
    { name: "FP_CORE_UTIL", default: 50, pdk: false },
    { name: "CLOCK_PERIOD", default: null, pdk: false },
    { name: "DIODE_PADDING", default: 2, pdk: false },
    { name: "TECH_LEFS", default: null, pdk: true },
    { name: "FALLBACK_SDC_FILE", default: null, pdk: false },
  ];
  const map = { ok: true, rel: "config.yaml", vars: {
    CLOCK_PERIOD: { line: 3, value: "10", scoped: false, scope: null, others: 0 },
  } };
  const m = fs.buildCumulativeModel({ PDK: "sky130A", FP_CORE_UTIL: 45 }, map, registry);
  const by = Object.fromEntries(m.rows.map((r) => [r.name, r]));

  assert.equal(by.FP_CORE_UTIL.source, "override");
  assert.equal(by.FP_CORE_UTIL.value, "45");
  assert.equal(by.PDK.source, "picker");
  assert.equal(by.CLOCK_PERIOD.source, "config");
  assert.equal(by.CLOCK_PERIOD.value, "10");
  assert.equal(by.DIODE_PADDING.source, "default");
  assert.equal(by.DIODE_PADDING.value, "2");
  // PDK-flagged: source says the PDK provides it; no invented value.
  assert.equal(by.TECH_LEFS.source, "pdk");
  assert.equal(by.TECH_LEFS.value, "—");
  assert.equal(by.FALLBACK_SDC_FILE.source, "unset");
  assert.deepEqual(m.counts, { override: 2, config: 1, pdk: 1, default: 1, unset: 1 });
  assert.equal(m.haveRegistry, true);

  // No registry (container-only box): honest flag, but overrides/config rows
  // still truthfully listed.
  const m2 = fs.buildCumulativeModel({ FP_CORE_UTIL: 45 }, map, []);
  assert.equal(m2.haveRegistry, false);
  assert.equal(m2.rows.length, 2);
});

check("finalsettings: source labels state the same story in both tables", () => {
  assert.match(fs.sourceLabel({ source: "override" }), /supersedes configuration file/);
  assert.match(fs.sourceLabel({ source: "config", line: 3 }, "config.yaml"),
    /config\.yaml line 3/);
  assert.match(
    fs.sourceLabel({ source: "config", config_line: 5, scoped: true, scope: "pdk::sky130*" },
      "config.yaml"),
    /line 5 \(pdk::sky130\*: applied only if/);
  assert.match(fs.sourceLabel({ source: "pdk" }), /resolved\.json/);
  assert.match(fs.sourceLabel({ source: "default" }), /LibreLane default/);
});

// ------------------------------------------------ compare column identity
// N1: Compare is cross-design, and users name runs ("baseline", "opt"). Two
// designs each with a run named "baseline" must render as TWO distinct columns
// keyed by the unique run_dir — not collapse onto one column showing only one
// design's numbers. buildCols is the frontend half of that fix.
const cmp = await import(toUrl(resolve(MOD, "compare.js")));
check("compare: same-named runs from different designs get distinct columns", () => {
  const runs = [
    { col: "/w/spm/runs/baseline", tag: "baseline", design: "spm" },
    { col: "/w/processor/runs/baseline", tag: "baseline", design: "processor" },
  ];
  const cols = cmp.buildCols(runs);
  assert.equal(cols.length, 2);
  assert.notEqual(cols[0].col, cols[1].col, "colliding tags must keep distinct lookup keys");
  // A repeated tag → design-prefixed label so the user always sees WHICH run.
  assert.equal(cols[0].label, "spm · baseline");
  assert.equal(cols[1].label, "processor · baseline");
});

check("compare: unique tags in one design stay plain (no needless prefix)", () => {
  const cols = cmp.buildCols([
    { col: "/w/spm/runs/baseline", tag: "baseline", design: "spm" },
    { col: "/w/spm/runs/opt", tag: "opt", design: "spm" },
  ]);
  assert.equal(cols[0].label, "baseline");
  assert.equal(cols[1].label, "opt");
});

check("compare: distinct tags across designs are design-prefixed for clarity", () => {
  const cols = cmp.buildCols([
    { col: "/w/spm/runs/a", tag: "a", design: "spm" },
    { col: "/w/proc/runs/b", tag: "b", design: "proc" },
  ]);
  assert.equal(cols[0].label, "spm · a");
  assert.equal(cols[1].label, "proc · b");
});

check("compare + DSE never index the metric/config table by tag (N1 regression)", () => {
  // Both consumers of /api/compare must look up per-run values by the unique
  // col (run_dir); a `[…][r.tag]` lookup would re-introduce the collision.
  for (const f of ["compare.js", "dse.js"]) {
    const src = readFileSync(resolve(MOD, f), "utf8");
    assert.doesNotMatch(src, /\]\[r\.tag\]/, `${f} indexes a per-run table by tag`);
    assert.doesNotMatch(src, /\]\[t\]/, `${f} indexes a per-run table by a bare tag var`);
  }
});

// ------------------------------------------------ SSE gap resync (N3)
// A dropped stream that reconnects past events the server's ring already
// evicted must re-hydrate the live pipeline from /api/run/status — never sit on
// stale step states behind a green "connected" chip.
check("SSE: reconnect past ring eviction re-hydrates from run/status (N3)", () => {
  const apiSrc = readFileSync(resolve(MOD, "api.js"), "utf8");
  assert.match(apiSrc, /addEventListener\("gap"/, "no gap-event listener");
  assert.match(apiSrc, /_wasDisconnected/, "reconnect-after-drop not tracked");
  assert.match(apiSrc, /run_status_resync/, "resync broadcast missing");
  assert.match(apiSrc, /runStatus:\s*\(\)\s*=>\s*_fetch\("\/api\/run\/status"\)/,
    "api.runStatus endpoint missing");
  const appSrc = readFileSync(resolve(HERE, "..", "server", "static", "app.js"), "utf8");
  const i = appSrc.indexOf('ev.type === "run_status_resync"');
  assert.ok(i >= 0, "app.js has no run_status_resync branch");
  const branch = appSrc.slice(i, i + 1100);
  assert.match(branch, /step_statuses/, "resync branch ignores step_statuses");
  assert.match(branch, /renderRuntimeline/, "resync branch does not repaint the timeline");
});

// ------------------------------------------------ partial-sim badge (N2)
// A timed-out sim's waveform is INCOMPLETE. The disclosure must be durable (a
// pinned header badge), not just a transient toast that the next action wipes,
// and it must clear when a full sim later loads.
check("sim: a partial (timed-out) waveform gets a durable, clearing badge (N2)", () => {
  const STATIC = resolve(HERE, "..", "server", "static");
  for (const f of ["index.html", "ide.html"]) {
    const html = readFileSync(resolve(STATIC, f), "utf8");
    assert.match(html, /id="ide-wave-partial"/, `${f} missing the partial badge element`);
  }
  const js = readFileSync(resolve(MOD, "ide", "main.js"), "utf8");
  // The badge is driven by the server's partial flag, threaded through load.
  assert.match(js, /loadWaveform\(ev\.vcd,\s*ev\.partial\)/,
    "sim_done handler must pass ev.partial to loadWaveform");
  assert.match(js, /setWavePartial\(!!partial\)/,
    "loadWaveform must set/CLEAR the badge from the partial flag (a full load clears it)");
  assert.match(js, /getElementById\("ide-wave-partial"\)/,
    "setWavePartial must toggle the badge element");
});

// ------------------------------------------------ timing unit label (N4)
// The slack unit must come from the payload (backend's single-sourced constant),
// never a hardcoded "ns" that would silently mislabel a ps-unit liberty ×1000.
check("timing: slack unit label is sourced from data, not hardcoded (N4)", () => {
  const src = readFileSync(resolve(MOD, "timing.js"), "utf8");
  assert.match(src, /data\.unit/, "timing.js must read the unit from the payload");
  assert.doesNotMatch(src, /slack \(ns\)/, "hardcoded 'slack (ns)' axis label survived");
  assert.doesNotMatch(src, /\+ " ns<\/span>"/, "hardcoded ' ns' pill suffix survived");
});

// ------------------------------------------------ multi-config warning (N6)
check("preflight/setup surface the multiple-config-files warning (N6)", () => {
  const pf = readFileSync(resolve(MOD, "preflight.js"), "utf8");
  assert.match(pf, /d\.config_note/, "preflight ignores the multi-config note");
  const setup = readFileSync(resolve(MOD, "setup.js"), "utf8");
  assert.match(setup, /res\.warning.*toast\.show|toast\.show\(res\.warning/,
    "setup.js no longer toasts the run-start warning");
});

// ------------------------------------------------ config TOCTOU (N7)
check("Final-settings stashes the previewed config hash; Run compares it (N7)", () => {
  const fs2 = readFileSync(resolve(MOD, "finalsettings.js"), "utf8");
  assert.match(fs2, /state\.previewedConfigHash\s*=\s*map\.config_hash/,
    "finalsettings must stash the previewed config hash");
  const setup = readFileSync(resolve(MOD, "setup.js"), "utf8");
  assert.match(setup, /res\.config_hash\s*!==\s*state\.previewedConfigHash/,
    "the run-start handler must compare the run's config hash to the previewed one");
  assert.match(setup, /state\.previewedConfigHash\s*=\s*null/,
    "the stashed hash must be cleared after comparison");
});

// ------------------------------------------------ rounded cell keeps the raw
// value (gap #2, Fear A/G). Compare and DSE are the tape-out DECISION surfaces.
// They round metrics for readability — but a rounded number a user picks a
// winner on must never hide the exact tool value. fmt.titleAttr is the escape
// hatch; every rounded decision cell must carry it.
check("fmt.titleAttr: carries the EXACT tool value, never the rounded display", () => {
  // 1234.7 renders as the grouped "1,235" but the title must hold 1234.7.
  const attr = fmt.titleAttr(1234.7);
  assert.match(attr, /^ title='1234\.7'$/, `title lost the exact value: ${attr}`);
  assert.notEqual(fmt.metric(1234.7), "1234.7", "precondition: display DOES round");
  // A non-finite / absent value has nothing exact to show → empty (safe to inject).
  assert.equal(fmt.titleAttr(null), "");
  assert.equal(fmt.titleAttr(undefined), "");
  assert.equal(fmt.titleAttr(""), "");
  // The raw is HTML-escaped so a stray quote can't break out of the attribute.
  assert.doesNotMatch(fmt.titleAttr("a'b"), /'a'b'/, "raw value not escaped in title");
});

check("compare: a summary cell shows the rounded value but titles the raw one", () => {
  // The exported, pure cell builder (the tape-out side-by-side grid).
  const cell = cmp.summaryCellHtml({ value: 1234.7, unit: "µm", status: "pass" });
  assert.match(cell, /title='1234\.7'/, "the exact value is not one hover away");
  assert.match(cell, />1,235 µm</, "the rounded, grouped display is missing");
  assert.match(cell, /cmp-num pass/, "pass/fail status class dropped");
  // An absent row stays the em-dash — never a fabricated 0, never a bare title.
  assert.equal(cmp.summaryCellHtml(null), "<td>—</td>");
  assert.equal(cmp.summaryCellHtml(undefined), "<td>—</td>");
  // A real value present but no status: still titled, still shown.
  const neutral = cmp.summaryCellHtml({ value: 0.0004 });
  assert.match(neutral, /title='0\.0004'/, "sub-milli exact value lost from the cell");
});

check("decision surfaces never render a rounded metric without the raw escape", () => {
  // Static invariant: the files that round a metric a user makes a tape-out call
  // on (compare grid, DSE sweep grid, timing-closure advisor) must wire the raw
  // escape. Losing titleAttr here silently re-opens the precision hole (gap #2).
  for (const f of ["compare.js", "dse.js", "timingAdvisor.js"]) {
    const src = readFileSync(resolve(MOD, f), "utf8");
    assert.match(src, /fmt\.metric\(/, `${f}: precondition — it does round a metric`);
    assert.match(src, /titleAttr\(/, `${f}: rounds a metric but carries no raw escape`);
  }
});

// ------------------------------------------------ one utilization%, two paths
// Utilization% is derived server-side (history.design_summary: round(u*100,1))
// AND client-side for the gauge (charts.utilizationOption: round(u*1000)/10).
// Two formulas for one number: they must agree to the digit on every fraction,
// else the hero strip and the gauge silently disagree (gap #8, Fear G).
check("utilization%: the server and chart formulas agree to the digit", () => {
  const serverPct = (u) => Math.round(u * 100 * 10) / 10; // mirror of round(u*100,1)
  for (const u of [0, 0.1, 0.455, 0.5001, 0.6789, 0.9999, 1.0]) {
    const opt = charts.utilizationOption({ "design__instance__utilization": u });
    const gauge = opt.series[0].data[0].value;
    assert.equal(gauge, serverPct(u),
      `gauge ${gauge} disagrees with server ${serverPct(u)} for fraction ${u}`);
  }
  // Absent fraction → no gauge invented.
  assert.equal(charts.utilizationOption({}), null);
});

// ------------------------------------------------ tools: normalizeUnavailableLibraries contract
check("tools: normalizeUnavailableLibraries normalizes object, array, and nil inputs safely", () => {
  // Canonical object from live API
  const liveObj = {
    gf180mcu_ocd_ip_sram: "Not published for this release",
    gf180mcu_re_efuse: "Not published for this release",
  };
  const normObj = normalizeUnavailableLibraries(liveObj);
  assert.equal(typeof normObj, "object");
  assert.equal(normObj.gf180mcu_ocd_ip_sram, "Not published for this release");
  assert.equal(normObj.gf180mcu_re_efuse, "Not published for this release");
  assert.equal(Object.keys(normObj).length, 2);

  // Legacy array input
  const legacyArr = ["gf180mcu_ocd_ip_sram", "gf180mcu_re_efuse"];
  const normArr = normalizeUnavailableLibraries(legacyArr);
  assert.equal(normArr.gf180mcu_ocd_ip_sram, "Not published for this release");
  assert.equal(normArr.gf180mcu_re_efuse, "Not published for this release");
  assert.equal(Object.keys(normArr).length, 2);

  // Null, undefined, empty
  assert.deepEqual(normalizeUnavailableLibraries(null), {});
  assert.deepEqual(normalizeUnavailableLibraries(undefined), {});
  assert.deepEqual(normalizeUnavailableLibraries({}), {});
});

// ------------------------------------------------ tools: full fixture render and section isolation
await checkAsync("tools: full fixture renders 10 tools, 7 PDK cards, 14 GF180 libs, container viewers, and isolates errors", async () => {
  const fullFixture = {
    platform: "linux",
    container: {
      ready: true,
      image_present: true,
      engine: "docker",
      image: "ghcr.io/librelane/librelane:3.0.4@sha256:eab07a50fa9ae481f631d904bd9fbaa99752c587fdbddb7c8cf2ac04208eecd9",
      docker: { available: true, usable: true, version: "29.8.1" },
    },
    tools: [
      { key: "python", label: "Python", category: "core", installed: true, path: "/usr/bin/python3", version: "3.12.3" },
      { key: "pip", label: "pip", category: "core", installed: true, path: "/usr/bin/pip", version: "24.0" },
      { key: "librelane", label: "LibreLane", category: "core", installed: true, in_container: true, path: "/home/lanex/.local/bin/librelane", version: "3.0.4" },
      { key: "yosys", label: "Yosys", category: "eda", installed: false, in_container: true },
      { key: "openroad", label: "OpenROAD", category: "eda", installed: false, in_container: true },
      { key: "klayout", label: "KLayout", category: "eda", installed: false, in_container: true },
      { key: "magic", label: "Magic", category: "eda", installed: false, in_container: true },
      { key: "netgen", label: "Netgen", category: "eda", installed: false, in_container: true },
      { key: "verilator", label: "Verilator", category: "eda", installed: true, in_container: true, path: "/usr/bin/verilator", version: "5.020" },
      { key: "ciel", label: "ciel", category: "eda", installed: true, path: "/home/lanex/.local/bin/ciel", version: "2.6.1" },
      { key: "iverilog", label: "Icarus Verilog", category: "extra", installed: true, path: "/usr/bin/iverilog", version: "12.0" },
      { key: "graphviz", label: "Graphviz", category: "extra", installed: true, path: "/usr/bin/dot", version: "2.43.0" },
      { key: "gtkwave", label: "GTKWave", category: "extra", installed: true, path: "/usr/bin/gtkwave", version: "3.3.116" },
    ],
    pdk: {
      ciel_installed: true,
      pdk_root: "/home/lanex/.ciel",
      installed_pdks: ["sky130A", "sky130B", "gf180mcuA", "gf180mcuB", "gf180mcuC", "gf180mcuD", "ihp-sg13g2"],
      installed_sizes_mb: { sky130A: 2500, sky130B: 2500, gf180mcuA: 1800, gf180mcuB: 1800, gf180mcuC: 1800, gf180mcuD: 1800, "ihp-sg13g2": 1900 },
    },
    pdk_catalog: {
      sky130A: { label: "sky130A", family: "sky130", default_variant: true, supported: true, libraries: ["sky130_fd_io", "sky130_fd_pr", "sky130_fd_sc_hd"], default_libraries: ["sky130_fd_io"] },
      sky130B: { label: "sky130B", family: "sky130", default_variant: false, supported: true, libraries: ["sky130_fd_io", "sky130_fd_pr"], default_libraries: ["sky130_fd_io"] },
      gf180mcuD: {
        label: "gf180mcuD",
        family: "gf180mcu",
        default_variant: true,
        supported: true,
        libraries: [
          "gf180mcu_as_sc_mcu7t3v3", "gf180mcu_fd_io", "gf180mcu_fd_ip_sram", "gf180mcu_fd_pr",
          "gf180mcu_fd_sc_mcu7t5v0", "gf180mcu_fd_sc_mcu9t5v0", "gf180mcu_ocd_alpha_large",
          "gf180mcu_ocd_alpha_misc", "gf180mcu_ocd_alpha_small", "gf180mcu_ocd_io",
          "gf180mcu_osu_sc_gp12t3v3", "gf180mcu_osu_sc_gp9t3v3"
        ],
        default_libraries: ["gf180mcu_fd_io", "gf180mcu_fd_pr"],
        unavailable_libraries: {
          gf180mcu_ocd_ip_sram: "Not published for this release",
          gf180mcu_re_efuse: "Not published for this release",
        },
      },
      "ihp-sg13g2": { label: "ihp-sg13g2", family: "ihp-sg13g2", default_variant: true, supported: true, libraries: ["sg13g2_io", "sg13g2_pr"], default_libraries: ["sg13g2_io"] },
      gf180mcuA: { label: "gf180mcuA", family: "gf180mcu", default_variant: false, supported: false, libraries: ["gf180mcu_fd_io"], default_libraries: ["gf180mcu_fd_io"] },
      gf180mcuB: { label: "gf180mcuB", family: "gf180mcu", default_variant: false, supported: false, libraries: ["gf180mcu_fd_io"], default_libraries: ["gf180mcu_fd_io"] },
      gf180mcuC: { label: "gf180mcuC", family: "gf180mcu", default_variant: false, supported: false, libraries: ["gf180mcu_fd_io"], default_libraries: ["gf180mcu_fd_io"] },
    },
  };

  class DomElement {
    constructor(tag = "div") {
      this.tagName = tag;
      this._html = "";
      this.dataset = {};
      this.className = "";
      this.children = [];
      this.listeners = {};
      this.classList = {
        add: (...cs) => cs.forEach((c) => { this.className += " " + c; }),
        remove: (...cs) => cs.forEach((c) => { this.className = this.className.replace(c, "").trim(); }),
        contains: (c) => this.className.includes(c),
      };
    }
    set innerHTML(v) { this._html = v; this.children = []; }
    get innerHTML() { return this._html; }
    appendChild(c) { this.children.push(c); }
    addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
    querySelectorAll() { return []; }
    querySelector() { return null; }
  }

  const els = {
    "tools-grid": new DomElement(),
    "sec-tools": new DomElement(),
    "desktop-viewers": new DomElement(),
    "recommended-tools": new DomElement(),
    "runtime-card": new DomElement(),
    "pdk-store-row": new DomElement(),
    "pdk-root-input": new DomElement(),
    "tool-bar": new DomElement(),
  };

  const oldDoc = globalThis.document;
  globalThis.document = {
    getElementById: (id) => els[id] || (els[id] = new DomElement()),
    createElement: (tag) => new DomElement(tag),
    querySelectorAll: () => [],
    addEventListener: () => {},
  };

  const origDesktopTools = api.desktopTools;
  api.desktopTools = async () => ({
    tools: [
      { key: "klayout", available: false },
      { key: "magic", available: false },
      { key: "gds3d", available: true },
    ],
  });

  try {
    // 1. Paint local tools grid
    toolsModule.paintLocalToolsGrid(fullFixture);
    const gridEl = els["tools-grid"];
    assert.equal(gridEl.children.length, 10, `expected 10 local tool cards, got ${gridEl.children.length}`);
    const toolKeys = gridEl.children.map((c) => c.dataset.key);
    assert.deepEqual(toolKeys, [
      "python", "pip", "librelane", "yosys", "openroad", "klayout", "magic", "netgen", "verilator", "ciel"
    ]);

    // 2. Render PDK store with canonical object-shaped unavailable_libraries
    toolsModule.renderPdkStore(fullFixture);
    const pdkHtml = els["pdk-store-row"].innerHTML;
    for (const v of ["sky130A", "sky130B", "gf180mcuA", "gf180mcuB", "gf180mcuC", "gf180mcuD", "ihp-sg13g2"]) {
      assert.ok(pdkHtml.includes(v), `pdk variant ${v} missing from PDK store`);
    }
    // gf180mcuD discloses 14 total libraries (12 published + 2 unavailable)
    assert.ok(pdkHtml.includes("Libraries (14)"), "gf180mcuD must disclose 14 total libraries");
    assert.ok(pdkHtml.includes("gf180mcu_ocd_ip_sram"), "unavailable lib 1 missing");
    assert.ok(pdkHtml.includes("gf180mcu_re_efuse"), "unavailable lib 2 missing");
    assert.ok(pdkHtml.includes("(Not published for this release)"), "reason text missing");

    // 3. Render desktop viewers with container fallback
    await toolsModule.renderDesktopViewers(fullFixture);
    const viewersHtml = els["desktop-viewers"].innerHTML;
    assert.ok(viewersHtml.includes("in container image"), "desktop viewers must show in container image");
    assert.ok(!viewersHtml.includes("not found"), "desktop viewers must not show not found when image is present");

    // 4. Overall paint handles full fixture without error
    await toolsModule.paint(fullFixture);
    assert.ok(!els["tools-grid"].innerHTML.includes("Tool probe failed"), "paint produced Tool probe failed");

    // 5. Error isolation: even if PDK store throws, local tools and viewers remain uncorrupted
    const corruptFixture = { ...fullFixture, pdk_catalog: null };
    await toolsModule.paint(corruptFixture);
    assert.ok(!els["tools-grid"].innerHTML.includes("Tool probe failed"), "corrupt PDK catalog must not mark local tools as failed");
    assert.ok(els["tools-grid"].children.length > 0, "local tool cards must survive PDK failure");
  } finally {
    api.desktopTools = origDesktopTools;
    globalThis.document = oldDoc;
  }
});

// ------------------------------------------------ Analytics: the tool's numbers, shown honestly
const AM = await import(toUrl(resolve(MOD, "analytics-model.js")));

check("analytics: counts stay integers, units come from the metric", () => {
  assert.equal(AM.show("design__instance__count", 1226).text, "1,226");
  assert.equal(AM.show("design__instance__count__class:sequential_cell", 64).text, "64");
  assert.equal(AM.show("design__instance__area", 7214.42).text, "7,214.42");
  const p = AM.show("power__total", 0.0014772084541618824);
  assert.deepEqual([p.text, p.unit], ["1.477", "mW"]);
  assert.match(p.title, /0\.0014772084541618824 W/, "exact value must stay one hover away");
  assert.deepEqual([AM.show("design__instance__utilization", 0.630246).text, AM.show("design__instance__utilization", 0.630246).unit], ["63.0", "%"]);
  assert.equal(AM.show("timing__setup__ws", 4.10025980329734).text, "+4.100");
  assert.equal(AM.show("timing__hold__ws", -0.02).text, "\u22120.020");
});

check("analytics: OpenSTA's 1e30 'no path' sentinel and +inf are never spelled out", () => {
  assert.equal(AM.show("timing__setup_r2r__ws", 1e30).text, "+1.00e+30");
  assert.equal(AM.show("timing__setup_r2r__ws", "Infinity").text, "\u221e");
  assert.equal(AM.num(null), "\u2014", "absent stays an em-dash, never 0");
});

check("analytics: drop__average is a voltage (OpenROAD's IR report), never converted as a drop", () => {
  const avg = AM.show("design_powergrid__drop__average__net:VPWR__corner:nom_tt_025C_1v80", 1.79997);
  assert.deepEqual([avg.text, avg.unit], ["1.79997", "V"]);
  const worst = AM.show("design_powergrid__drop__worst__net:VPWR", 0.000233556);
  assert.deepEqual([worst.text, worst.unit], ["0.2336", "mV"]);
  assert.equal(AM.show("design_powergrid__voltage__worst__net:VPWR", 1.79977).text, "1.79977");
});

check("analytics: metric keys split into base + modifiers", () => {
  assert.deepEqual(AM.parseKey("timing__setup__ws__corner:max_ss_100C_1v60"), { base: "timing__setup__ws", mods: { corner: "max_ss_100C_1v60" } });
  assert.deepEqual(AM.parseKey("flow__warnings__count:DRT-0349"), { base: "flow__warnings__count", mods: { code: "DRT-0349" } });
  assert.deepEqual(AM.parseKey("design__rows:unithd"), { base: "design__rows", mods: { code: "unithd" } });
  assert.equal(AM.cornerShort("nom_tt_025C_1v80"), "TT 25 \u00b0C 1.80 V \u00b7 nom RC");
  assert.equal(AM.cornerShort("odd-corner"), "odd-corner", "unknown corner names are shown raw");
});

check("analytics: deltas are coloured only when the registry knows the direction", () => {
  const meta = new Map([["timing__setup__ws", { higher_is_better: true }], ["power__total", { higher_is_better: false }]]);
  assert.equal(AM.delta(3.2, 4.1, AM.directionOf(meta, "timing__setup__ws")).verdict, "worse");
  assert.equal(AM.delta(0.00141, 0.00148, AM.directionOf(meta, "power__total")).verdict, "better");
  assert.equal(AM.delta(4790, 4546, AM.directionOf(meta, "design__instance__area__stdcell")).verdict, "neutral");
  assert.equal(AM.delta(5, 5, 1).verdict, "same");
  assert.equal(AM.delta("Infinity", 4, 1), null, "non-finite values get no delta");
});

check("analytics: checks pass at zero, warn when not critical, absent when not run", () => {
  const meta = new Map([["design__lvs_error__count", { critical: true }], ["design__inferred_latch__count", { critical: false }]]);
  const by = (vals) => Object.fromEntries(AM.evalChecks(vals, meta).map((c) => [c.label, c.status]));
  const st = by({ design__lvs_error__count: 1, design__inferred_latch__count: 2, magic__drc_error__count: 0, klayout__drc_error__count: 3 });
  assert.equal(st.LVS, "fail");
  assert.equal(st.Latches, "warn");
  assert.equal(st["DRC Magic"], "pass");
  assert.equal(st["DRC KLayout"], "fail", "a DRC count is an error even without a registry entry");
  assert.equal(st.XOR, "absent");
});

check("analytics: steps get a stage label and running metrics", () => {
  const steps = AM.accumulate(AM.stageSteps([
    { n: 6, id: "Yosys.Synthesis", changed: { design__instance__count: 222 } },
    { n: 13, id: "OpenROAD.Floorplan", changed: { design__instance__utilization: 0.47 } },
    { n: 31, id: "OpenROAD.STAMidPNR", changed: { timing__setup__ws: 6.6 } },
    { n: 35, id: "OpenROAD.CTS", changed: {} },
    { n: 36, id: "OpenROAD.STAMidPNR-1", changed: { timing__setup__ws: 6.0 } },
  ]));
  assert.deepEqual(steps.map((s) => s.stage), ["Synthesis", "Floorplan", "Floorplan", "Clock tree", "Clock tree"]);
  assert.equal(steps[4].metrics.design__instance__count, 222);
  assert.equal(steps[2].metrics.timing__setup__ws, 6.6);
  assert.equal(AM.stepName({ id: "OpenROAD.STAMidPNR-3" }), "STA mid-PnR (4)");
  assert.equal(AM.stepName({ id: "OpenROAD.ResizerTimingPostCTS" }), "Resizer timing post CTS");
});

// ---------- Verify tab (verify-model.js) -------------------------------------------
const VM = await import(toUrl(resolve(MOD, "verify-model.js")));

check("verify: worst status lets nothing that failed hide", () => {
  assert.equal(VM.worstStatus([{ status: "pass" }, { status: "warn" }, { status: "fail" }]), "fail");
  assert.equal(VM.worstStatus([{ status: "pass" }, { status: "warn" }]), "warn");
  assert.equal(VM.worstStatus([{ status: "pass" }, { status: "info" }]), "pass");
});

check("verify: a stage with unrun checks is never plain 'pass'", () => {
  assert.equal(VM.worstStatus([{ status: "pass" }, { status: "not_run" }]), "partial");
  assert.equal(VM.worstStatus([{ status: "not_run" }]), "not_run");
  assert.equal(VM.worstStatus([]), "not_run");
});

check("verify: status diff finds new problems and fixes vs. the baseline", () => {
  const cur = { checks: [{ id: "lvs", status: "fail", value: 2 }, { id: "setup", status: "pass", value: 0 }, { id: "slew", status: "warn", value: 3 }] };
  const base = { checks: [{ id: "lvs", status: "pass", value: 0 }, { id: "setup", status: "fail", value: 4 }, { id: "slew", status: "warn", value: 1 }] };
  const d = VM.statusDiff(cur, base);
  assert.deepEqual(d.regressed.map((c) => c.id), ["lvs"]);
  assert.deepEqual(d.fixed.map((c) => c.id), ["setup"]);
  assert.ok(d.changed.has("slew"), "a moved value is a change even when the state is the same");
  assert.equal(VM.statusDiff(cur, null).regressed.length, 0);
});

check("verify: corner order is nom, min, max RC then tt, ss, ff", () => {
  const names = ["max_ff_n40C_1v95", "nom_ss_100C_1v60", "min_tt_025C_1v80", "nom_tt_025C_1v80"];
  assert.deepEqual([...names].sort((a, b) => VM.cornerSortKey(a) - VM.cornerSortKey(b)),
    ["nom_tt_025C_1v80", "nom_ss_100C_1v60", "min_tt_025C_1v80", "max_ff_n40C_1v95"]);
});

check("verify: every check id has a one-line description and help", () => {
  const ids = ["lint_errors", "lint_timing_constructs", "lint_warnings", "unmapped", "synth_check", "assign", "latch", "eqy",
    "pdn", "route_drc", "disc_pin", "wire_length", "antenna", "setup", "hold", "slew", "cap", "fanout",
    "xor", "magic_drc", "klayout_drc", "overlap", "lvs"];
  for (const id of ids) {
    assert.ok(VM.SHORT[id], "no short text for " + id);
    assert.ok(VM.HELP[id] && VM.HELP[id].what && VM.HELP[id].fix.length, "no help for " + id);
  }
});

check("analytics: check strip takes Verify's LibreLane-exact statuses", () => {
  const checks = [{ label: "Max slew", status: "fail" }, { label: "LVS", status: "pass" }, { label: "Lint", status: "pass" }];
  const rep = { checks: [{ id: "slew", status: "warn" }, { id: "lvs", status: "not_run" }] };
  const out = AM.withSignoff(checks, rep);
  assert.deepEqual(out.map((c) => c.status), ["warn", "absent", "pass"]);
  assert.equal(AM.withSignoff(checks, null), checks);
});

// ---------- Cells tab (cells-model.js) ---------------------------------------------
const CM = await import(toUrl(resolve(MOD, "cells-model.js")));

check("cells: Liberty functions parse with every operator spelling", () => {
  const env = { A: true, B: false, C: true };
  for (const [src, want] of [["A&B", false], ["A*B", false], ["A B", false], ["A|B", true], ["A+B", true],
    ["A^C", false], ["!A", false], ["A'", false], ["(A&!B)|C", true], ["!((A1&A2)|B1)", null]]) {
    const ast = CM.parseFunction(src);
    assert.ok(ast, src);
    if (want !== null) assert.equal(CM.evalAst(ast, env), want, src);
  }
  // malformed input never throws: an unclosed paren still reads, a dangling operator is null
  assert.doesNotThrow(() => CM.parseFunction("A & (B"));
  assert.equal(CM.parseFunction("A &"), null);
});

check("cells: Liberty's (!A)|(!B) reads as the NAND it is", () => {
  const ast = CM.parseFunction("(!A) | (!B)");
  assert.equal(CM.astText(ast), "!(A & B)");
  assert.equal(CM.classify(ast), "2-input NAND");
  assert.equal(CM.classify(CM.parseFunction("!((A1&A2)|B1)")), "AND-OR-Invert (AOI)");
  // flattened sum-of-products comes back in the datasheet's AOI shape, same function
  for (const flat of ["(!A1&!B1) | (!A2&!B1)", "!((A1|B1)&(A2|B1))"]) {
    const a = CM.parseFunction(flat);
    assert.equal(CM.astText(a), "!((A1 & A2) | B1)", flat);
  }
  const t = (s) => CM.truthTable(["A", "B", "C"], [{ name: "Y", ast: CM.parseFunction(s) }]).map((r) => r.outs[0]).join("");
  assert.equal(t("(A&B)|(A&C)"), t("A&(B|C)"));
  assert.equal(CM.astText(CM.parseFunction("(A|B)&(A|B|C)")), "A | B");
});

check("cells: the PDK header formula wins and matches Liberty's truth table", () => {
  const hdr = CM.headerFormulas(["Y = !((A1 & A2) | B1)"]).Y;
  const lib = CM.parseFunction("(!A1&!B1) | (!A2&!B1)");
  const t1 = CM.truthTable(["A1", "A2", "B1"], [{ name: "Y", ast: hdr }]);
  const t2 = CM.truthTable(["A1", "A2", "B1"], [{ name: "Y", ast: lib }]);
  assert.deepEqual(t1, t2);
  assert.deepEqual(t1.map((r) => r.outs[0]), [1, 0, 1, 0, 1, 0, 0, 0]);
});

check("cells: tri-state outputs read Z when disabled", () => {
  const t = CM.truthTable(["A", "TE_B"], [{ name: "Z", ast: CM.parseFunction("A"), z: CM.parseFunction("TE_B") }]);
  assert.deepEqual(t.map((r) => r.outs[0]), [0, "Z", 1, "Z"]);
});

check("cells: gate diagram draws one gate per operator and labels every input", () => {
  const svg = CM.gateDiagram(CM.parseFunction("!((A1&A2)|B1)"), "Y");
  assert.equal((svg.match(/class='gd-gate'/g) || []).length, 3);   // AND, OR, output bubble
  for (const p of ["A1", "A2", "B1", "Y"]) assert.ok(svg.includes(">" + p + "<"), p);
  assert.equal(CM.gateDiagram(CM.parseFunction("A&B&C&D&E&F&G&H&I&J&K&L&M&N&O"), "Y"), "");
});

check("cells: flip-flop behaviour is spelled out from the ff group", () => {
  const lines = CM.seqDescription({ kind: "ff", state: ["IQ", "IQ_N"], clocked_on: "CLK", next_state: "D", clear: "!RESET_B" },
    [{ name: "Q", function: "IQ" }]);
  assert.match(lines[0], /rising edge of CLK, Q takes D/);
  assert.match(lines[1], /RESET_B low forces Q to 0/);
});

check("cells: exclusion wildcards match the way LibreLane's fnmatch does", () => {
  assert.deepEqual(CM.globMatch("sky130_fd_sc_hd__dlygate4sd3_1", ["*dlygate*", "*buf_16", "sky130_fd_sc_hd__dlygate4sd?_1"]),
    ["*dlygate*", "sky130_fd_sc_hd__dlygate4sd?_1"]);
  assert.deepEqual(CM.globMatch("a.b", ["a?b", "a.c"]), ["a?b"]);
});

check("cells: units format without losing scale", () => {
  assert.equal(CM.fmtPs(238.1), "238 ps");
  assert.equal(CM.fmtPs(1088), "1.09 ns");
  assert.equal(CM.fmtPower(0.00165), "1.65 pW");
  assert.equal(CM.fmtPower(2500), "2.50 µW");
  assert.equal(CM.fmtArea(5.0048), "5.00 µm²");
});

// ---------- Layout tab (layout.js, layoutcanvas.js) ------------------------------
const LC = await import(toUrl(resolve(MOD, "layoutcanvas.js")));
const LX = await import(toUrl(resolve(MOD, "layout.js")));

check("layout: rulers and the scale bar speak in the natural unit", () => {
  assert.equal(LC.fmtUm(0.14), "140 nm");
  assert.equal(LC.fmtUm(0.045), "45 nm");
  assert.equal(LC.fmtUm(2.5), "2.5 µm");
  assert.equal(LC.fmtUm(96.6), "96.6 µm");
  assert.equal(LC.fmtUm(1500), "1.5 mm");
  assert.equal(LC.niceLength(7.3), 5);
  assert.equal(LC.niceLength(0.031), 0.02);
  assert.equal(LC.niceLength(180), 100);
});

check("layout: standard cells are named in plain words", () => {
  assert.equal(LX.describeCell("sky130_fd_sc_hd__dfrtp_2"), "D flip-flop with reset, drive strength 2");
  assert.equal(LX.describeCell("sky130_fd_sc_hd__nand3_1"), "3-input NAND, drive strength 1");
  assert.equal(LX.describeCell("sky130_fd_sc_hd__a21oi_1"), "AND-OR-invert (21), drive strength 1");
  assert.equal(LX.describeCell("sky130_fd_sc_hd__clkbuf_16"), "clock buffer, drive strength 16");
  assert.equal(LX.describeCell("sky130_fd_sc_hd__dlygate4sd3_1"), "delay cell (fixes hold timing), drive strength 1");
  assert.equal(LX.describeCell("my_macro"), "");
});

check("layout: one Layout tab; Preview is gone everywhere", () => {
  const html = readFileSync(resolve(MOD, "..", "index.html"), "utf8");
  assert.ok(!/data-tab="preview"|id="sec-preview"/.test(html), "the Preview tab must be gone");
  assert.equal((html.match(/data-tab="layout"/g) || []).length, 1, "exactly one Layout rail button");
  assert.ok(html.includes('href="/static/layout.css"'), "layout.css must be linked");
  for (const f of ["hotkeys.js", "palette.js", "runs.js", "setup.js"]) {
    const src = readFileSync(resolve(MOD, f), "utf8");
    assert.ok(!/["']preview["']|preview\.js/.test(src), f + " still points at the old Preview tab");
  }
  const app = readFileSync(resolve(MOD, "..", "app.js"), "utf8");
  assert.ok(!/preview\.js|data-go='preview'/.test(app), "app.js still points at the old Preview tab");
});

// ---------- P0 glue: one context, links, stages, keys --------------------------------
const FS = await import(toUrl(resolve(MOD, "flowstages.js")));

check("stages: seven, in flow order, one name for each on every page", () => {
  assert.deepEqual(FS.STAGES.map((s) => s.label),
    ["Synthesis", "Floorplan", "Power grid", "Placement", "Clock tree", "Routing", "Sign-off"]);
  assert.deepEqual(AM.STAGES, FS.STAGES.map((s) => s.label), "Analytics groups by the shared names");
  const ids = FS.stagesOf(["01-verilator-lint", "21-openroad-generatepdn", "25-openroad-ioplacement",
    "35-openroad-cts", "36-openroad-stamidpnr-1", "44-openroad-detailedrouting", "70-netgen-lvs"].map((dir) => ({ dir })));
  assert.deepEqual(ids, ["synthesis", "pdn", "placement", "cts", "cts", "routing", "signoff"]);
});

await checkAsync("context: newest run by default, baseline is the last run before it that passed", async () => {
  const store = new Map();
  globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
  const events = [];
  globalThis.document = { dispatchEvent: (e) => events.push(e), addEventListener() {} };
  store.set("ll.runsScope", "all");                       // the old Runs key is adopted once
  const CX = await import(toUrl(resolve(MOD, "context.js")));
  const { state } = await import(toUrl(resolve(MOD, "state.js")));
  assert.equal(CX.getRunScope(), "all");
  assert.equal(store.get("ll.runsScope"), undefined);
  store.set("ll.runScope", "design");
  state.designDir = "/w/spm";
  const rows = [
    { tag: "c", success: true, started_at: "2026-10-06T20:00" },
    { tag: "b", success: false, started_at: "2026-10-06T19:00" },
    { tag: "a", success: true, started_at: "2026-10-06T18:00" },
  ];
  api.runs = async () => rows.map((r) => ({ ...r }));
  await CX.loadRuns();
  assert.equal(CX.contextRun(), "c");
  assert.equal(CX.contextBaseline(), "a", "the failed run in between is skipped");
  assert.equal(state.selectedRunTag, "c");
  await CX.setRun("b");
  assert.equal(CX.contextRun(), "b");
  assert.equal(CX.contextBaseline(), "a");
  assert.equal(events.at(-1).detail.why, "run");
  CX.setBaseline("");                                     // "Nothing" is a choice that stands
  await CX.loadRuns();
  assert.equal(CX.contextBaseline(), "");
  const mem = JSON.parse(store.get("ll.context"))["/w/spm"];
  assert.deepEqual(mem, { run: "b", baseline: "", picked: true }, "each project remembers its run");
  // A run finishes while the user is on the newest: the pages follow it.
  CX.setBaseline("a"); await CX.setRun("c");
  CX.noteRunStarted();
  rows.unshift({ tag: "d", success: true, started_at: "2026-10-06T21:00" });
  await CX.noteRunFinished();
  assert.equal(CX.contextRun(), "d");
  assert.equal(events.at(-1).detail.why, "run-finished");
  // ...but not when they were looking at an older run.
  await CX.setRun("a");
  CX.noteRunStarted();
  rows.unshift({ tag: "e", success: true, started_at: "2026-10-06T22:00" });
  await CX.noteRunFinished();
  assert.equal(CX.contextRun(), "a");
  delete globalThis.document;
  delete globalThis.localStorage;
});

console.log(`\nfrontend_test: ${passed} checks passed` +
  (process.exitCode ? " — WITH FAILURES" : ""));

// On GitHub Actions, list every check in the Summary tab so the display-layer
// data-accuracy results are readable without opening the job log. Local runs
// (no GITHUB_STEP_SUMMARY) skip this; FRONTEND_TEST_SUMMARY=0 opts a matrix
// leg out so the 4× python matrix doesn't write four identical tables.
if (process.env.GITHUB_STEP_SUMMARY && process.env.FRONTEND_TEST_SUMMARY !== "0") {
  const failed = results.filter((r) => !r.ok);
  const esc = (s) => s.replace(/\|/g, "\\|").replace(/\n/g, " ");
  const lines = [
    "## Frontend behaviour — display-layer data accuracy",
    "",
    `**${passed} passed · ${failed.length} failed** — the executed display ` +
    "functions (metric formatting, escaping, CSV quoting, chart builders, " +
    "browser VCD parser) held to the golden fixtures.",
    "",
    "| Check | Result |",
    "|---|---|",
    ...results.map((r) =>
      `| ${esc(r.name)} | ${r.ok ? "✓ pass" : "✗ FAIL — " + esc(r.msg)} |`),
    "",
  ];
  try {
    appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join("\n") + "\n");
  } catch { /* a summary write must never fail the gate */ }
}
