// analytics.js — comprehensive metrics panel.
// Two views:
//   (A) Side-pane tile: minimal hero metrics for the latest run.
//   (B) Full-screen tab "Analytics": every metric from metrics.json grouped,
//       plus a glossary / advisor.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { gatherRunsScoped, getRunScope, runOptionsHtml, scopeToggleHtml, wireScopeToggle, ensureActiveDesignFor } from "./runscope.js";
import { toast } from "./toast.js";
import { toCsv, downloadCsv } from "./csvutil.js";
import { wireScrollSpy } from "./jumpnav.js";
import { icon } from "./icons.js";
import { provBtnHtml, wireProvBtns } from "./provenance.js";

// ---------- shared classification --------------------------------------------

// Authoritative metric metadata (name -> {higher_is_better, critical}) fetched
// once from LibreLane's own metric registry via /api/metrics-catalog. Until it
// loads, classify falls back to name-pattern heuristics that match LibreLane's
// real `a__b__c` metric names.
let _metricMeta = null;

async function loadMetricMeta() {
  if (_metricMeta) return _metricMeta;
  try {
    const list = await api.metricsCatalog();
    _metricMeta = new Map(list.map((m) => [m.name, m]));
  } catch (_e) {
    _metricMeta = new Map();
  }
  return _metricMeta;
}

// Real LibreLane metric naming: counts of violations/errors/mismatches end in
// `__count` / `__errors` / `__violations` (0 is good); worst-slack metrics end
// in `__ws` / `__wns` / `__tns` (>=0 is good); utilization is a 0–1 ratio.
const _VIOLATION_RX = /(_vio__count$|error[s]?__count$|__errors$|__violations$|drc_error|illegal_overlap|violating__|unmatched_|_difference__count$|disconnected_pin__count$|inferred_latch__count$|unmapped__count$|_violation__count$|xor_difference__count$)/;
const _SLACK_RX = /(__ws$|__wns$|__tns$)/;
const _RATIO_RX = /(__utilization$)/;

function classify(key, value) {
  if (value === null || value === undefined) return { kind: "value", cls: "" };
  const num = typeof value === "number" ? value : Number(value);
  const meta = _metricMeta && _metricMeta.get(key);
  // Critical count metrics: any non-zero is a hard fail.
  if (meta && meta.critical && /__count$|__errors$|__violations$/.test(key)) {
    return { kind: "violation", cls: num === 0 ? "pass" : "fail" };
  }
  if (_VIOLATION_RX.test(key)) return { kind: "violation", cls: num === 0 ? "pass" : "fail" };
  if (_SLACK_RX.test(key)) return { kind: "slack", cls: Number.isNaN(num) ? "" : (num >= 0 ? "pass" : "fail") };
  if (_RATIO_RX.test(key)) return { kind: "ratio", cls: num >= 0 && num <= 1 ? "pass" : "warn" };
  return { kind: "value", cls: "" };
}

function groupKey(key) {
  const parts = key.split("__");
  return (parts[0] || "misc").toLowerCase();
}

const HIDDEN_GROUPS = new Set(["tool_version", "runtime", "flow"]);

// ---------- Metric reference (data-driven from LibreLane's registry) ----------

const GROUP_TITLES = {
  design: "Design",
  design_powergrid: "Power grid",
  timing: "Static timing",
  clock: "Clock tree",
  power: "Power",
  route: "Routing",
  antenna: "Antenna",
  ir: "IR drop",
  magic: "Magic (DRC)",
  synthesis: "Synthesis checks",
};

async function renderGlossary() {
  const root = document.getElementById("analytics-glossary");
  if (!root) return;
  const meta = await loadMetricMeta();
  root.innerHTML = "";
  if (!meta.size) {
    root.innerHTML = "<div class='empty'><span class='ico'>" + icon('book',{size:40}) + "</span><h3>Metric registry unavailable</h3><p>Could not read LibreLane's metric definitions.</p></div>";
    return;
  }
  // Group the real metric names by their first `__` segment.
  const groups = new Map();
  for (const name of [...meta.keys()].sort()) {
    const g = groupKey(name);
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(name);
  }
  const grid = document.createElement("div");
  grid.className = "glossary-grid";
  for (const [g, names] of groups) {
    const card = document.createElement("div");
    card.className = "adv-card";
    const rows = names
      .map((n) => {
        const m = meta.get(n) || {};
        const dir = m.higher_is_better ? "↑ higher is better" : "↓ lower is better";
        const crit = m.critical ? "  ·  critical (0 to pass)" : "";
        return n + "\n  " + dir + crit;
      })
      .join("\n\n");
    card.innerHTML =
      "<div class='title'>" + fmt.escape(GROUP_TITLES[g] || (g.charAt(0).toUpperCase() + g.slice(1))) + "</div>" +
      "<div class='why'>" + names.length + " metric" + (names.length === 1 ? "" : "s") + "</div>" +
      "<pre class='code'>" + fmt.escape(rows) + "</pre>";
    grid.appendChild(card);
  }
  root.appendChild(grid);
}

// ---------- Render helpers ---------------------------------------------------

function formatValue(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") {
    try {
      const keys = Object.keys(v);
      if (keys.length <= 4) {
        return keys
          .map((k) => k + ":" + (typeof v[k] === "number" ? Number(v[k]).toFixed(3) : JSON.stringify(v[k])))
          .join(", ");
      }
    } catch (_e) {}
    return JSON.stringify(v).slice(0, 80);
  }
  return fmt.metric(v);
}

// ---------- Full-screen Analytics tab ------------------------------------

// tag -> run row (carries _design) for the current picker, so a cross-design
// selection can switch the active design before fetching that run's metrics.
let _runIndex = {};

// Export the currently-shown run's metrics as a CSV (client-side, from the
// metrics already loaded — no extra request).
function exportMetricsCsv(tag) {
  const vals = _lastValues || {};
  const keys = Object.keys(vals).sort();
  if (!keys.length) { toast.show("No metrics to export.", "warn"); return; }
  const rows = [["metric", "value"]].concat(keys.map((k) => [k, vals[k]]));
  downloadCsv((tag || "run") + "-metrics.csv", toCsv(rows));
}

async function selectAnalyticsRun(tag) {
  await ensureActiveDesignFor(_runIndex[tag]);
  state.selectedRunTag = tag;
  await paintFull(tag);
}

// Inject the "All designs" scope checkbox once, right after the run <select>.
function ensureScopeToggle(sel) {
  if (!sel || sel.parentNode.querySelector("#analytics-run-scope")) return;
  sel.insertAdjacentHTML("afterend", " " + scopeToggleHtml("analytics-run-scope"));
  wireScopeToggle("analytics-run-scope", () => renderAnalyticsFull());
}

export async function renderAnalyticsFull() {
  const sel = document.getElementById("analytics-run-select");
  const root = document.getElementById("analytics-sections");
  const cnt = document.getElementById("analytics-count");
  if (!sel || !root) return;
  await loadMetricMeta();
  // Picker is scoped by the GLOBAL run-scope pref (this design vs all designs).
  let runs = [];
  try { runs = await gatherRunsScoped(); } catch (_e) {}
  _runIndex = {};
  for (const r of runs) _runIndex[r.tag] = r;
  if (getRunScope() === "design") state.runs = runs;   // keep compat for other views
  ensureScopeToggle(sel);
  const oldVal = sel.value;
  sel.innerHTML = "";
  if (!runs.length) {
    sel.innerHTML = "<option value=''>(no runs yet)</option>";
    root.innerHTML = "<div class='empty'><span class='ico'>" + icon('chart',{size:40}) + "</span><h3>No completed runs</h3><p>Run the flow end-to-end and the metrics land here, grouped by stage.</p></div>";
    cnt.textContent = "";
    return;
  }
  sel.innerHTML = runOptionsHtml(runs, oldVal, fmt.escape);
  if (oldVal && _runIndex[oldVal]) sel.value = oldVal;
  if (!sel.value) sel.value = runs[0].tag;
  await selectAnalyticsRun(sel.value);
  sel.onchange = () => selectAnalyticsRun(sel.value);
  const refresh = document.getElementById("btn-refresh-analytics");
  if (refresh && !refresh._wired) {
    refresh._wired = true;
    refresh.addEventListener("click", () => paintFull(sel.value));
  }
  const csvBtn = document.getElementById("btn-analytics-csv");
  if (csvBtn && !csvBtn._wired) {
    csvBtn._wired = true;
    csvBtn.addEventListener("click", () => exportMetricsCsv(sel.value));
  }
  const search = document.getElementById("analytics-search");
  if (search && !search._wired) {
    search._wired = true;
    search.addEventListener("input", () => renderSections(_lastValues, currentFilter()));
  }
  wireJumpNav();
  renderGlossary();
}

// In-page jump nav: scroll to a sub-section (and open it if it's a <details>),
// so users don't have to scroll past the full metric list to reach Compare.
function wireJumpNav() {
  const nav = document.getElementById("analytics-jump");
  if (!nav || nav._wired) return;
  nav._wired = true;
  nav.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-jump]");
    if (!btn) return;
    const target = document.getElementById(btn.dataset.jump);
    if (!target) return;
    if (target.tagName === "DETAILS") target.open = true;
    target.scrollIntoView({ behavior: "smooth", block: "start" });
  });
  wireScrollSpy(nav);   // live-highlight the chip for the section in view
}

// Cached values for the active run so the search box can re-filter without a
// network round-trip on every keystroke.
let _lastValues = {};
let _lastTag = "";

function currentFilter() {
  const el = document.getElementById("analytics-search");
  return (el && el.value ? el.value : "").trim().toLowerCase();
}

// ---- Design summary hero strip ------------------------------------------------

function renderSummary(summary) {
  const root = document.getElementById("analytics-summary");
  if (!root) return;
  const rows = Array.isArray(summary) ? summary : [];
  if (!rows.length) { root.innerHTML = ""; return; }
  root.innerHTML =
    "<div class='summary-grid'>" +
    rows.map((r) => {
      const unit = r.unit ? " <span class='unit'>" + fmt.escape(r.unit) + "</span>" : "";
      const cls = r.status ? " " + r.status : "";
      // Each summary card derives from one metric key — the source button
      // opens the run's own metrics.json at that key's line (a derived
      // display like % vs fraction is explained by the raw line itself).
      const prov = (r.key && _lastTag)
        ? provBtnHtml({ kind: "metric", key: r.key, tag: _lastTag },
            "Show '" + r.key + "' in this run's metrics.json (raw LibreLane value)")
        : "";
      return (
        "<div class='summary-card" + cls + "'>" +
        "<div class='summary-val'>" + fmt.escape(fmt.metric(r.value)) + unit + prov + "</div>" +
        "<div class='summary-label'>" + fmt.escape(r.label) + "</div>" +
        "</div>"
      );
    }).join("") +
    "</div>";
  wireProvBtns(root);
}

// ---- Grouped full metric list (filterable) ------------------------------------

function renderSections(values, filter) {
  const root = document.getElementById("analytics-sections");
  const cnt = document.getElementById("analytics-count");
  if (!root) return;
  root.innerHTML = "";
  const groups = new Map();
  let count = 0;
  for (const [k, v] of Object.entries(values)) {
    if (HIDDEN_GROUPS.has(k)) continue;
    if (filter && !k.toLowerCase().includes(filter)) continue;
    const g = groupKey(k);
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push([k, v]);
    count++;
  }
  if (count === 0) {
    root.innerHTML = "<div class='empty'><span class='ico'>" + icon('search',{size:40}) + "</span><h3>No metrics match “" +
      fmt.escape(filter) + "”</h3><p>Clear the filter to see all metrics.</p></div>";
    if (cnt) cnt.textContent = "0 of " + Object.keys(values).length + " metrics";
    return;
  }
  for (const [gname, items] of groups) {
    const sec = document.createElement("details");
    sec.className = "card";
    sec.open = true;
    const head = document.createElement("summary");
    head.innerHTML =
      "<strong>" + fmt.escape(GROUP_TITLES[gname] || (gname.charAt(0).toUpperCase() + gname.slice(1))) + "</strong>" +
      "<span class='hint'>" + items.length + " metric" + (items.length === 1 ? "" : "s") + "</span>";
    sec.appendChild(head);
    const body = document.createElement("div");
    body.className = "card-body";
    const grid = document.createElement("div");
    grid.className = "metrics-grid";
    for (const [k, v] of items) {
      const { cls } = classify(k, v);
      const card = document.createElement("div");
      card.className = "metric-card";
      const nonFinite = v === "Infinity" || v === "-Infinity" || v === "NaN";
      const valTitle = nonFinite
        ? (/_r2r_/.test(k)
            ? "No register-to-register paths in this design — this slack is unconstrained (genuinely ∞), not a parsing error."
            : "Non-finite value reported by LibreLane (genuine, not a parse error).")
        : "";
      const prov = _lastTag
        ? provBtnHtml({ kind: "metric", key: k, tag: _lastTag },
            "Show this metric's line in the run's metrics.json (raw LibreLane file)")
        : "";
      card.innerHTML =
        "<div class='key' title='" + fmt.escape(k) + "'>" + fmt.escape(k) + prov + "</div>" +
        "<div class='val " + cls + "'" + (valTitle ? " title='" + fmt.escape(valTitle) + "'" : "") +
        ">" + formatValue(v) + "</div>";
      grid.appendChild(card);
    }
    body.appendChild(grid);
    sec.appendChild(body);
    root.appendChild(sec);
  }
  wireProvBtns(root);
  const total = Object.keys(values).length;
  if (cnt) {
    cnt.textContent = filter
      ? count + " of " + total + " metrics match"
      : count + " metrics across " + groups.size + " groups";
  }
}

async function paintFull(tag) {
  const root = document.getElementById("analytics-sections");
  if (!root || !tag) return;
  root.innerHTML = "<div class='empty'><span class='ico'>" + icon('clock',{size:40}) + "</span><h3>Loading " + tag + "…</h3></div>";
  try {
    const view = await api.run(tag);
    _lastValues = (view.metrics?.values) || {};
    _lastTag = tag;
    renderSummary(view.summary);
    renderSections(_lastValues, currentFilter());
  } catch (_ex) {
    root.innerHTML = "<div class='empty'><span class='ico'>" + icon('alert',{size:40}) + "</span><h3>Could not load metrics for " + fmt.escape(tag) + "</h3></div>";
  }
  renderCellUsage(tag);   // independent of metrics — own try/catch inside
  renderTrends();         // across-run trends for this design (own try/catch)
}

// Trends: how key metrics moved across this design's runs over time. A new run
// regressing area/timing/power is visible immediately without picking run pairs.
let _trendData = null;
async function renderTrends() {
  const sel = document.getElementById("trend-metric");
  const chartEl = document.getElementById("trends-chart");
  if (!sel || !chartEl) return;
  try {
    _trendData = await api.trends(state.designDir || undefined);
  } catch (_e) { _trendData = null; }
  const keys = (_trendData && _trendData.keys) || [];
  if (!keys.length || !(_trendData.runs || []).length) {
    sel.innerHTML = "";
    drawTrend(null);
    return;
  }
  // Preserve the current selection if still valid, else default to the first.
  const prev = sel.value;
  sel.innerHTML = keys.map((k) => "<option value='" + fmt.escape(k) + "'>" + fmt.escape(k) + "</option>").join("");
  if (keys.includes(prev)) sel.value = prev;
  if (!sel._wired) {
    sel._wired = true;
    sel.addEventListener("change", () => drawTrend(sel.value));
  }
  drawTrend(sel.value || keys[0]);
}

function drawTrend(metric) {
  const el = document.getElementById("trends-chart");
  if (!el) return;
  let chart = window.echarts && window.echarts.getInstanceByDom(el);
  if (!window.echarts || !metric || !_trendData) {
    if (chart) chart.dispose();
    el.innerHTML = "<p class='muted' style='padding:var(--s-3)'>No across-run trend yet (run the flow a couple of times).</p>";
    return;
  }
  if (!chart) { el.innerHTML = ""; chart = window.echarts.init(el); }
  const runs = _trendData.runs || [];
  const xs = runs.map((r) => r.tag);
  const ys = (_trendData.series[metric] || []).map((v) =>
    (v === null || v === undefined || v === "Infinity" || v === "-Infinity" || v === "NaN") ? null : v);
  Promise.all([import("./theme-echarts.js")]).then(([te]) => {
    const theme = te.chartTheme();
    const pal = te.chartPalette();
    chart.setOption({
      ...theme,
      tooltip: { trigger: "axis" },
      grid: { left: 56, right: 16, top: 16, bottom: 64 },
      xAxis: { type: "category", data: xs, axisLabel: { rotate: 45, fontSize: 10 } },
      yAxis: { type: "value", name: metric, nameTextStyle: { fontSize: 10 } },
      series: [{
        type: "line", data: ys, smooth: false, connectNulls: true,
        showSymbol: true, symbolSize: 7, lineStyle: { width: 2, color: pal[0] },
        itemStyle: { color: pal[0] },
      }],
    }, true);
    chart.resize();
    // G2b — screen readers get nothing from a <canvas>; give a summary label and
    // a plain data table so the trend is reachable without sight.
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", "Line chart: " + metric + " across " + xs.length + " runs.");
    renderTrendTable(el, metric, xs, ys);
  });
}

function renderTrendTable(chartEl, metric, xs, ys) {
  let box = document.getElementById("trends-table");
  if (!box) {
    box = document.createElement("details");
    box.id = "trends-table";
    box.className = "card";
    box.style.marginTop = "var(--s-3)";
    chartEl.parentElement && chartEl.parentElement.insertBefore(box, chartEl.nextSibling);
  }
  const rows = xs.map((t, i) => "<tr><td>" + fmt.escape(t) + "</td><td>" +
    (ys[i] === null || ys[i] === undefined ? "—" : fmt.escape(String(ys[i]))) + "</td></tr>").join("");
  box.innerHTML = "<summary>Data table</summary><div class='card-body'>" +
    "<table class='cmp-table'><thead><tr><th>Run</th><th>" + fmt.escape(metric) +
    "</th></tr></thead><tbody>" + rows + "</tbody></table></div>";
}

// Cell-usage breakdown: which standard cells the run placed + how many of each.
// Source: history.cell_usage (the run's "Cells by Master" report). Shows a donut
// of the top masters plus a full, sortable count table.
async function renderCellUsage(tag) {
  const host = document.getElementById("cells-usage-body");
  if (!host) return;
  host.innerHTML = "<p class='muted'>Loading cell usage…</p>";
  let cells = [];
  try {
    const res = await api.cellUsage(tag);
    cells = (res && res.cells) || [];
  } catch (_e) { /* fall through to empty */ }
  cells = cells.filter((c) => Number.isFinite(Number(c.count)));
  if (!cells.length) {
    host.innerHTML = "<p class='muted'>No cell-usage data for this run " +
      "(it didn't reach the CellFrequencyTables step, or produced no standard cells yet).</p>";
    return;
  }
  const total = cells.reduce((s, c) => s + Number(c.count), 0) || 1;
  const distinct = cells.length;
  const rows = cells.map((c) => {
    const n = Number(c.count);
    const pct = ((n / total) * 100).toFixed(1);
    return "<tr><td class='cu-cell'>" + fmt.escape(c.cell) + "</td>" +
      "<td class='cu-count'>" + n.toLocaleString() + "</td>" +
      "<td class='cu-pct'>" + pct + "%</td></tr>";
  }).join("");
  host.innerHTML =
    "<div class='cu-stats muted'>" + distinct.toLocaleString() + " distinct cells • " +
      total.toLocaleString() + " total instances</div>" +
    "<div class='cu-layout'>" +
    "  <div id='cells-usage-chart' class='cu-chart'></div>" +
    "  <div class='cu-tablewrap'><table class='cu-table'>" +
    "    <thead><tr><th>Cell</th><th>Count</th><th>Share</th></tr></thead>" +
    "    <tbody>" + rows + "</tbody></table></div>" +
    "</div>";
  // Donut of the top masters (ECharts optional — table is the source of truth).
  try {
    if (typeof window.echarts !== "undefined") {
      const { cellBreakdownOption } = await import("./charts.js");
      const { chartTheme } = await import("./theme-echarts.js");
      const opt = cellBreakdownOption(cells);
      const el = document.getElementById("cells-usage-chart");
      if (opt && el) {
        const chart = window.echarts.init(el, chartTheme(), { renderer: "canvas" });
        chart.setOption(Object.assign({ backgroundColor: "transparent" }, opt));
        el.setAttribute("role", "img");
        el.setAttribute("aria-label", "Standard-cell usage breakdown — the same counts are in the table below.");
      }
    }
  } catch (_e) { /* chart is a nicety; the table already shows everything */ }
}
