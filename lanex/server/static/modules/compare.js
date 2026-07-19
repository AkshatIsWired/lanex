// compare.js — run-vs-run comparison (Phase 1.B). Multi-pick runs; show a
// config-diff table + a colored metric-delta table (better/worse from each
// metric's higher_is_better flag) + side-by-side preview images.
import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toCsv, downloadCsv } from "./csvutil.js";
import { gatherRunsScoped, designLabel } from "./runscope.js";

// tag -> run row (carries run_dir + _design) so Compare can pass absolute
// run_dirs to the backend — robust even when a picked run lives in another
// design (the per-tab pickers can surface cross-design runs).
let _runIndex = {};

export async function renderCompare() {
  const root = document.getElementById("compare-body");
  if (!root) return;
  // Compare is inherently cross-design: ALWAYS gather every known design's runs
  // (no "All designs" toggle to remember) so you can compare, e.g., an spm run
  // against a processor run regardless of which design is active. Each run row
  // carries its own absolute run_dir, which the backend resolves directly.
  let runs = [];
  try { runs = await gatherRunsScoped("all"); } catch (_e) { runs = state.runs || []; }
  _runIndex = {};
  for (const r of runs) _runIndex[r.tag] = r;
  // How many designs are represented (drives whether we show a design prefix).
  const designs = new Set(runs.map((r) => r._design).filter(Boolean));
  const multi = designs.size > 1;
  if (!runs.length) {
    root.innerHTML = "<div class='empty'><h3>No runs to compare</h3><p>Finish at least two runs.</p></div>";
    return;
  }
  root.innerHTML =
    "<div class='cmp-pick'><div class='cmp-pick-head'><h3>Pick runs to compare</h3>" +
    "<span class='muted'>across all designs you've opened</span></div><div class='cmp-checks'>" +
    runs.map((r) =>
      // Carry the absolute run_dir on the checkbox itself so doCompare never
      // depends on an index lookup that could desync — a run from any design
      // resolves by its run_dir on the backend.
      "<label class='cmp-check'><input type='checkbox' value='" + fmt.escape(r.tag) +
      "' data-rundir='" + fmt.escape(r.run_dir || "") + "'/> " +
      (multi ? "<span class='muted'>" + fmt.escape(designLabel(r._design)) + " · </span>" : "") +
      fmt.escape(r.tag) + (r.success ? " <svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M5 13l4 4L19 7'/></svg>" : " <svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg>") + "</label>").join("") +
    "</div><button class='btn btn-primary' id='cmp-go'>Compare</button>" +
    "<input id='cmp-search' class='inp' type='search' placeholder='filter metrics…' hidden /></div>" +
    "<div id='cmp-out'></div>";
  root.querySelector("#cmp-go").addEventListener("click", () => doCompare(root));
}

async function doCompare(root) {
  const checked = [...root.querySelectorAll(".cmp-check input:checked")];
  const tags = checked.map((c) => c.value);
  const out = root.querySelector("#cmp-out");
  if (tags.length < 2) { out.innerHTML = "<div class='cmp-error'>Pick at least two runs to compare.</div>"; return; }
  out.innerHTML = "<p class='muted'>Comparing…</p>";
  // Absolute run_dirs straight off the checkboxes (fallback to the index) so a
  // run from ANY design resolves on the backend — not just the active design's.
  const runDirs = checked
    .map((c) => c.dataset.rundir || (_runIndex[c.value] && _runIndex[c.value].run_dir))
    .filter(Boolean);
  let data;
  try { data = await api.compare(tags, runDirs); } catch (ex) {
    out.innerHTML = "<div class='cmp-error'>Compare failed: " + fmt.escape(ex.message || ex) + "</div>"; return;
  }
  const search = root.querySelector("#cmp-search");
  search.hidden = false;

  // Columns are keyed by the backend's per-run ``col`` (the unique run_dir), NOT
  // the tag: two different designs can each hold a run named "baseline", and a
  // tag-keyed table would silently collapse them onto one column showing only
  // one design's numbers (Fear F/M). Each column carries a disambiguated label
  // (design · tag when a tag repeats or designs differ) so the user always sees
  // WHICH run each column is.
  const cols = buildCols(data.runs || []);

  // Summary comparison — the same headline metrics shown for a single run
  // (die/core area, utilisation, power, slack, DRC/LVS/antenna), side by side.
  const summaryHtml = renderSummaryCompare(data.runs || [], cols);

  // Key config: decision-relevant vars for EVERY run (clock, util, synth…),
  // so you can see what recipe produced each result — not just the diffs.
  const kc = data.key_config || {};
  const kcKeys = Object.keys(kc);
  let kcHtml = "<h3>Key configuration</h3>";
  if (!kcKeys.length) kcHtml += "<p class='muted'>No key config vars recorded for these runs.</p>";
  else {
    kcHtml += "<table class='cmp-table'><thead><tr><th>Variable</th>" +
      colHeaders(cols) + "</tr></thead><tbody>" +
      kcKeys.map((k) => "<tr><td><code>" + fmt.escape(k) + "</code></td>" +
        cols.map((c) => "<td>" + fmt.escape(fmtCfg(kc[k][c.col])) + "</td>").join("") +
        "</tr>").join("") + "</tbody></table>";
  }

  // Config diff.
  const cfgKeys = Object.keys(data.config_diff || {});
  let cfgHtml = "<h3>Config differences</h3>";
  if (!cfgKeys.length) cfgHtml += "<p class='muted'>Configs are identical.</p>";
  else {
    cfgHtml += "<table class='cmp-table'><thead><tr><th>Variable</th>" +
      colHeaders(cols) + "</tr></thead><tbody>" +
      cfgKeys.map((k) => "<tr><td>" + fmt.escape(k) + "</td>" +
        cols.map((c) => "<td>" + fmt.escape(fmtCfg(data.config_diff[k][c.col])) + "</td>").join("") +
        "</tr>").join("") + "</tbody></table>";
  }

  // Metric delta table.
  const metrics = Object.keys(data.metric_table || {}).sort();
  const renderMetrics = (filter) => {
    const rows = metrics.filter((m) => !filter || m.includes(filter)).map((m) => {
      const per = data.metric_table[m];
      const best = data.best[m];
      const cells = cols.map((c) => {
        const v = per[c.col];
        const cls = best ? (c.col === best ? "cmp-best" : "") : "";
        return "<td class='" + cls + "'>" + fmt.escape(v === undefined ? "—" : String(v)) + "</td>";
      }).join("");
      return "<tr><td><code>" + fmt.escape(m) + "</code></td>" + cells + "</tr>";
    }).join("");
    return "<table class='cmp-table'><thead><tr><th>Metric</th>" +
      colHeaders(cols) + "</tr></thead><tbody>" +
      rows + "</tbody></table>";
  };

  out.innerHTML =
    "<div class='cmp-toolbar'><button class='btn btn-ghost' id='cmp-export-csv'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M12 3v12M7 11l5 4 5-4M5 21h14'/></svg> Export comparison CSV</button></div>" +
    summaryHtml + kcHtml + cfgHtml +
    "<h3>Comparison charts</h3><div id='cmp-charts' class='cmp-charts'></div>" +
    "<h3>Metrics <span class='muted'>(best highlighted)</span></h3>" +
    "<div id='cmp-metrics'>" + renderMetrics("") + "</div>";
  search.oninput = () => {
    document.getElementById("cmp-metrics").innerHTML = renderMetrics(search.value.trim());
  };
  const exp = out.querySelector("#cmp-export-csv");
  if (exp) exp.addEventListener("click", () => exportCompareCsv(data, cols));
  renderCompareCharts(out.querySelector("#cmp-charts"), data, cols);
}

// Build the column descriptors for a comparison from the backend's run rows.
// ``col`` is the unique lookup key (run_dir); ``label`` disambiguates same-named
// runs by prefixing the design whenever a tag repeats or multiple designs are in
// play, so no two columns are ambiguous.
export function buildCols(runs) {
  const tagCount = {};
  for (const r of runs) tagCount[r.tag] = (tagCount[r.tag] || 0) + 1;
  const designs = new Set(runs.map((r) => r.design).filter(Boolean));
  const multiDesign = designs.size > 1;
  return runs.map((r) => {
    const dup = (tagCount[r.tag] || 0) > 1;
    const label = ((multiDesign || dup) && r.design) ? (r.design + " · " + r.tag) : (r.tag || r.col);
    return { col: r.col, tag: r.tag, design: r.design || "", label };
  });
}

function colHeaders(cols) {
  return cols.map((c) => "<th>" + fmt.escape(c.label) + "</th>").join("");
}

// Export the whole comparison (key config + config diffs + every metric) as one
// CSV: column 1 = field, then one column per run (headers are the disambiguated
// labels; values are keyed by the unique per-run column, never the tag).
function exportCompareCsv(data, cols) {
  const rows = [["field", ...cols.map((c) => c.label)]];
  const kc = data.key_config || {};
  for (const k of Object.keys(kc)) rows.push(["config: " + k, ...cols.map((c) => fmtCfg(kc[k][c.col]))]);
  const cd = data.config_diff || {};
  for (const k of Object.keys(cd)) rows.push(["diff: " + k, ...cols.map((c) => fmtCfg(cd[k][c.col]))]);
  const mt = data.metric_table || {};
  for (const m of Object.keys(mt).sort()) rows.push([m, ...cols.map((c) => mt[m][c.col])]);
  downloadCsv("compare-" + (cols[0] ? cols[0].tag : "runs") + ".csv", toCsv(rows));
}

// Render config values readably (lists → comma list, bool/None → text).
function fmtCfg(v) {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.map((x) => String(x).split(/[/\\]/).pop()).join(", ");
  return String(v);
}

// Side-by-side headline summary, built from each run's design_summary rows
// (already returned by /api/compare). Rows are the union of labels seen. Keyed
// by the unique per-run column, so same-named runs never merge.
function renderSummaryCompare(runs, cols) {
  const byCol = {};
  const order = [];
  for (const r of runs) {
    byCol[r.col] = {};
    for (const row of (r.summary || [])) {
      byCol[r.col][row.label] = row;
      if (!order.includes(row.label)) order.push(row.label);
    }
  }
  if (!order.length) return "<h3>Summary</h3><p class='muted'>No summary metrics for these runs.</p>";
  return "<h3>Summary <span class='muted'>(headline metrics, side by side)</span></h3>" +
    "<table class='cmp-table'><thead><tr><th>Metric</th>" +
    colHeaders(cols) + "</tr></thead><tbody>" +
    order.map((label) => "<tr><td>" + fmt.escape(label) + "</td>" +
      cols.map((c) => summaryCellHtml(byCol[c.col] && byCol[c.col][label])).join("") + "</tr>").join("") +
    "</tbody></table>";
}

// One side-by-side summary cell. Exported + pure so the "rounded display never
// hides the real value" invariant is directly testable. fmt.metric() rounds for
// readability; fmt.titleAttr() carries the EXACT tool value in the cell's title
// so a tape-out comparison can never rest on a number the user cannot verify
// (Fear A/G). An absent row stays "—" (never a fabricated 0).
export function summaryCellHtml(row) {
  if (!row) return "<td>—</td>";
  const unit = row.unit ? " " + fmt.escape(row.unit) : "";
  const cls = row.status ? " class='" + (row.status === "pass" ? "cmp-num pass" : row.status === "fail" ? "cmp-num fail" : "cmp-num") + "'" : " class='cmp-num'";
  return "<td" + cls + fmt.titleAttr(row.value) + ">" + fmt.escape(fmt.metric(row.value)) + unit + "</td>";
}

// Curated key metrics to chart across runs (one small bar chart each). Only the
// ones actually present in the comparison are drawn — never fabricated.
const _CHART_METRICS = [
  ["design__instance__count", "Cell count"],
  ["design__core__area", "Core area (µm²)"],
  ["design__instance__utilization", "Utilization"],
  ["timing__setup__ws", "Setup WNS (ns)"],
  ["timing__hold__ws", "Hold WNS (ns)"],
  ["power__total", "Total power"],
  ["route__wirelength__estimated", "Wirelength"],
];

async function renderCompareCharts(host, data, cols) {
  if (!host) return;
  if (typeof window.echarts === "undefined") { host.innerHTML = "<p class='muted'>Charts need ECharts.</p>"; return; }
  const { chartTheme } = await import("./theme-echarts.js");
  const table = data.metric_table || {};
  const num = (v) => { const n = Number(v); return isFinite(n) ? n : null; };
  const labels = cols.map((c) => c.label);
  const present = _CHART_METRICS.filter(([k]) => table[k] &&
    cols.some((c) => num(table[k][c.col]) !== null));
  if (!present.length) { host.innerHTML = "<p class='muted'>No chartable metrics in common across these runs.</p>"; return; }
  host.innerHTML = present.map(([k]) => "<div class='cmp-chart' data-k='" + fmt.escape(k) + "'></div>").join("");
  for (const [k, label] of present) {
    const el = host.querySelector(".cmp-chart[data-k='" + (window.CSS && CSS.escape ? CSS.escape(k) : k) + "']");
    if (!el) continue;
    // Split "Cell count" / "Core area (µm²)" into a name + optional unit so the
    // chart clearly states WHICH metric it compares (title) and its unit (y-axis).
    const um = /\(([^)]+)\)\s*$/.exec(label);
    const unit = um ? um[1] : "";
    const name = um ? label.slice(0, um.index).trim() : label;
    const chart = window.echarts.init(el, chartTheme(), { renderer: "canvas" });
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", name + " compared across the selected runs — the same values are in the comparison tables above.");
    chart.setOption({
      backgroundColor: "transparent",
      title: { text: name, subtext: k, left: "center", textStyle: { fontSize: 13, fontWeight: 600 }, subtextStyle: { fontSize: 9 } },
      tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "—" : v) + (unit ? " " + unit : "") },
      grid: { top: 48, bottom: 48, left: 56, right: 12 },
      xAxis: { type: "category", data: labels, axisLabel: { interval: 0, rotate: labels.length > 2 ? 30 : 0, fontSize: 10 } },
      yAxis: { type: "value", name: unit, nameTextStyle: { fontSize: 10 } },
      series: [{ type: "bar", name, data: cols.map((c) => num(table[k][c.col])) }],
    });
  }
  window.addEventListener("resize", () => host.querySelectorAll(".cmp-chart").forEach((el) => {
    const inst = window.echarts.getInstanceByDom(el); if (inst) inst.resize();
  }));
}
