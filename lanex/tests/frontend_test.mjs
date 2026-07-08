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
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const MOD = resolve(HERE, "..", "server", "static", "modules");

const { fmt } = await import(resolve(MOD, "api.js"));
const { csvCell } = await import(resolve(MOD, "csvutil.js"));

let passed = 0;
function check(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`  ok   ${name}`);
  } catch (e) {
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

console.log(`\nfrontend_test: ${passed} checks passed` +
  (process.exitCode ? " — WITH FAILURES" : ""));
