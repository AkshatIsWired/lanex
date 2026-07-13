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
