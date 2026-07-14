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
import { readFileSync, appendFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const MOD = resolve(HERE, "..", "server", "static", "modules");

const { fmt } = await import(resolve(MOD, "api.js"));
const { csvCell } = await import(resolve(MOD, "csvutil.js"));
const { clampZoom, fitChrome } = await import(resolve(MOD, "zoom.js"));

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

check("fitChrome is exported and DOM-safe when there's no document", () => {
  // fitChrome measures real overflow in the browser; behaviour is verified
  // headlessly (not in node). Here just lock the export + its no-DOM guard: it
  // must never throw when there is no document/topbar (returns stage 0).
  assert.equal(typeof fitChrome, "function");
  assert.equal(fitChrome(), 0);
});

check("zoom: stylesheets compensate viewport units via --ll-zoom", () => {
  // CSS `zoom` scales layout px but vw/vh keep resolving against the real
  // viewport — without the compensation the shell under/overflows the window
  // at any zoom ≠ 100% (round-56 user bug). zoom.js must publish the factor
  // and every cockpit stylesheet's viewport unit must divide by it.
  const STATIC = resolve(HERE, "..", "server", "static");
  assert.match(readFileSync(resolve(MOD, "zoom.js"), "utf8"),
    /setProperty\("--ll-zoom"/);
  for (const f of ["styles.css", "features.css", "ide.css"]) {
    const css = readFileSync(resolve(STATIC, f), "utf8")
      .replace(/\/\*[\s\S]*?\*\//g, "");   // comments may mention 100vw freely
    assert.match(css, /var\(--ll-zoom, 1\)/, `${f} lost the zoom compensation`);
    for (const ln of css.split("\n")) {
      if (/\d(vw|vh)\b/.test(ln) && !ln.includes("--ll-zoom")) {
        assert.fail(`${f}: viewport unit without --ll-zoom compensation: ${ln.trim()}`);
      }
    }
  }
});

check("layouttools: 'no display' buttons stay clickable (remedy on click)", () => {
  // A disabled button can never be clicked, so the user never saw the
  // XQuartz/WSLg remedy carried in display.reason (round-59 macOS bug). The
  // nodisplay branch must not emit a disabled attribute.
  const src = readFileSync(resolve(MOD, "layouttools.js"), "utf8");
  const start = src.indexOf('where = "nodisplay"');
  assert.ok(start >= 0, "nodisplay branch not found");
  const branch = src.slice(start, src.indexOf('where = "install"', start));
  assert.ok(!/disabled\s*=/.test(branch),
    "the nodisplay branch disables the button again — remedy becomes unreachable");
});

check("tools: engine-not-usable card is platform-aware with a Start action", () => {
  // Round-63 macOS bug: an installed-but-dead Docker showed ONLY the Linux
  // systemctl/usermod remedy — on macOS the daemon exists solely while Docker
  // Desktop runs, so the card must branch on the server-reported platform and
  // offer one-click Start buttons wired to /api/container/start-engine.
  const src = readFileSync(resolve(MOD, "tools.js"), "utf8");
  const card = src.indexOf("Container engine installed — not usable yet");
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
const { parseVCD } = await import(resolve(MOD, "ide", "vcd.js"));
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
const charts = await import(resolve(MOD, "charts.js"));
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
const { renderFileText } = await import(resolve(MOD, "fileview.js"));
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
const prov = await import(resolve(MOD, "provenance.js"));
check("provenance.js: config chips state scope + conditionality faithfully", () => {
  const scoped = prov.configChipSpec(
    { line: 6, text: "  FP_CORE_UTIL: 45", value: "45",
      scoped: true, scope: "pdk::sky130*", others: 1 }, "config.yaml");
  assert.equal(scoped.text, "config (pdk::sky130*): 45");
  assert.ok(scoped.title.includes("line 6"), "title must name the exact line");
  assert.ok(scoped.title.includes("applies only when the run's PDK/SCL matches"),
    "a scoped value must be declared conditional");
  assert.ok(scoped.title.includes("1 more entry"), "extra entries must be disclosed");
  assert.equal(scoped.scoped, true);

  const plain = prov.configChipSpec(
    { line: 3, text: "CLOCK_PERIOD: 10", value: "10",
      scoped: false, scope: null, others: 0 }, "config.yaml");
  assert.equal(plain.text, "your config: 10");
  assert.ok(plain.title.includes("what an untouched field uses"),
    "an unscoped value is what an untouched field uses");
  assert.ok(!plain.title.includes("more entr"), "no phantom extra entries");
});

// ------------------------------------------------ final-settings preview
// The merged "what will this run send" model. Must mirror the server's
// _assemble_overrides exactly: PDK/STD_CELL_LIBRARY split out as flow
// options, every other override beats the config file, and a config var
// with no override applies as written. Fed the user's real scenario.
const fs = await import(resolve(MOD, "finalsettings.js"));
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
  assert.match(fs.sourceLabel({ source: "override" }), /beats the file/);
  assert.match(fs.sourceLabel({ source: "config", line: 3 }, "config.yaml"),
    /config\.yaml line 3/);
  assert.match(
    fs.sourceLabel({ source: "config", config_line: 5, scoped: true, scope: "pdk::sky130*" },
      "config.yaml"),
    /line 5 \(pdk::sky130\* — applied only if/);
  assert.match(fs.sourceLabel({ source: "pdk" }), /resolved\.json/);
  assert.match(fs.sourceLabel({ source: "default" }), /LibreLane default/);
});

// ------------------------------------------------ compare column identity
// N1: Compare is cross-design, and users name runs ("baseline", "opt"). Two
// designs each with a run named "baseline" must render as TWO distinct columns
// keyed by the unique run_dir — not collapse onto one column showing only one
// design's numbers. buildCols is the frontend half of that fix.
const cmp = await import(resolve(MOD, "compare.js"));
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
