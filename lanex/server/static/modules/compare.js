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
      fmt.escape(r.tag) + (r.success ? " ✓" : " ✗") + "</label>").join("") +
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

  // Summary comparison — the same headline metrics shown for a single run
  // (die/core area, utilisation, power, slack, DRC/LVS/antenna), side by side.
  const summaryHtml = renderSummaryCompare(data.runs || [], tags);

  // Key config: decision-relevant vars for EVERY run (clock, util, synth…),
  // so you can see what recipe produced each result — not just the diffs.
  const kc = data.key_config || {};
  const kcKeys = Object.keys(kc);
  let kcHtml = "<h3>Key configuration</h3>";
  if (!kcKeys.length) kcHtml += "<p class='muted'>No key config vars recorded for these runs.</p>";
  else {
    kcHtml += "<table class='cmp-table'><thead><tr><th>Variable</th>" +
      tags.map((t) => "<th>" + fmt.escape(t) + "</th>").join("") + "</tr></thead><tbody>" +
      kcKeys.map((k) => "<tr><td><code>" + fmt.escape(k) + "</code></td>" +
        tags.map((t) => "<td>" + fmt.escape(fmtCfg(kc[k][t])) + "</td>").join("") +
        "</tr>").join("") + "</tbody></table>";
  }

  // Config diff.
  const cfgKeys = Object.keys(data.config_diff || {});
  let cfgHtml = "<h3>Config differences</h3>";
  if (!cfgKeys.length) cfgHtml += "<p class='muted'>Configs are identical.</p>";
  else {
    cfgHtml += "<table class='cmp-table'><thead><tr><th>Variable</th>" +
      tags.map((t) => "<th>" + fmt.escape(t) + "</th>").join("") + "</tr></thead><tbody>" +
      cfgKeys.map((k) => "<tr><td>" + fmt.escape(k) + "</td>" +
        tags.map((t) => "<td>" + fmt.escape(fmtCfg(data.config_diff[k][t])) + "</td>").join("") +
        "</tr>").join("") + "</tbody></table>";
  }

  // Metric delta table.
  const metrics = Object.keys(data.metric_table || {}).sort();
  const renderMetrics = (filter) => {
    const rows = metrics.filter((m) => !filter || m.includes(filter)).map((m) => {
      const per = data.metric_table[m];
      const best = data.best[m];
      const cells = tags.map((t) => {
        const v = per[t];
        const cls = best ? (t === best ? "cmp-best" : "") : "";
        return "<td class='" + cls + "'>" + fmt.escape(v === undefined ? "—" : String(v)) + "</td>";
      }).join("");
      return "<tr><td><code>" + fmt.escape(m) + "</code></td>" + cells + "</tr>";
    }).join("");
    return "<table class='cmp-table'><thead><tr><th>Metric</th>" +
      tags.map((t) => "<th>" + fmt.escape(t) + "</th>").join("") + "</tr></thead><tbody>" +
      rows + "</tbody></table>";
  };

  out.innerHTML =
    "<div class='cmp-toolbar'><button class='btn btn-ghost' id='cmp-export-csv'>⬇ Export comparison CSV</button></div>" +
    summaryHtml + kcHtml + cfgHtml +
    "<h3>Comparison charts</h3><div id='cmp-charts' class='cmp-charts'></div>" +
    "<h3>Metrics <span class='muted'>(best highlighted)</span></h3>" +
    "<div id='cmp-metrics'>" + renderMetrics("") + "</div>";
  search.oninput = () => {
    document.getElementById("cmp-metrics").innerHTML = renderMetrics(search.value.trim());
  };
  const exp = out.querySelector("#cmp-export-csv");
  if (exp) exp.addEventListener("click", () => exportCompareCsv(data, tags));
  renderCompareCharts(out.querySelector("#cmp-charts"), data, tags);
}

// Export the whole comparison (key config + config diffs + every metric) as one
// CSV: column 1 = field, then one column per run.
function exportCompareCsv(data, tags) {
  const rows = [["field", ...tags]];
  const kc = data.key_config || {};
  for (const k of Object.keys(kc)) rows.push(["config: " + k, ...tags.map((t) => fmtCfg(kc[k][t]))]);
  const cd = data.config_diff || {};
  for (const k of Object.keys(cd)) rows.push(["diff: " + k, ...tags.map((t) => fmtCfg(cd[k][t]))]);
  const mt = data.metric_table || {};
  for (const m of Object.keys(mt).sort()) rows.push([m, ...tags.map((t) => mt[m][t])]);
  downloadCsv("compare-" + (tags[0] || "runs") + ".csv", toCsv(rows));
}

// Render config values readably (lists → comma list, bool/None → text).
function fmtCfg(v) {
  if (v === null || v === undefined) return "—";
  if (Array.isArray(v)) return v.map((x) => String(x).split(/[/\\]/).pop()).join(", ");
  return String(v);
}

// Side-by-side headline summary, built from each run's design_summary rows
// (already returned by /api/compare). Rows are the union of labels seen.
function renderSummaryCompare(runs, tags) {
  const byTag = {};
  const order = [];
  for (const r of runs) {
    byTag[r.tag] = {};
    for (const row of (r.summary || [])) {
      byTag[r.tag][row.label] = row;
      if (!order.includes(row.label)) order.push(row.label);
    }
  }
  if (!order.length) return "<h3>Summary</h3><p class='muted'>No summary metrics for these runs.</p>";
  const cell = (row) => {
    if (!row) return "<td>—</td>";
    const unit = row.unit ? " " + fmt.escape(row.unit) : "";
    const cls = row.status ? " class='" + (row.status === "pass" ? "cmp-num pass" : row.status === "fail" ? "cmp-num fail" : "cmp-num") + "'" : " class='cmp-num'";
    return "<td" + cls + ">" + fmt.escape(fmt.metric(row.value)) + unit + "</td>";
  };
  return "<h3>Summary <span class='muted'>(headline metrics, side by side)</span></h3>" +
    "<table class='cmp-table'><thead><tr><th>Metric</th>" +
    tags.map((t) => "<th>" + fmt.escape(t) + "</th>").join("") + "</tr></thead><tbody>" +
    order.map((label) => "<tr><td>" + fmt.escape(label) + "</td>" +
      tags.map((t) => cell(byTag[t] && byTag[t][label])).join("") + "</tr>").join("") +
    "</tbody></table>";
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

async function renderCompareCharts(host, data, tags) {
  if (!host) return;
  if (typeof window.echarts === "undefined") { host.innerHTML = "<p class='muted'>Charts need ECharts.</p>"; return; }
  const { chartTheme } = await import("./theme-echarts.js");
  const table = data.metric_table || {};
  const num = (v) => { const n = Number(v); return isFinite(n) ? n : null; };
  const present = _CHART_METRICS.filter(([k]) => table[k] &&
    tags.some((t) => num(table[k][t]) !== null));
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
    chart.setOption({
      backgroundColor: "transparent",
      title: { text: name, subtext: k, left: "center", textStyle: { fontSize: 13, fontWeight: 600 }, subtextStyle: { fontSize: 9 } },
      tooltip: { trigger: "axis", valueFormatter: (v) => (v == null ? "—" : v) + (unit ? " " + unit : "") },
      grid: { top: 48, bottom: 48, left: 56, right: 12 },
      xAxis: { type: "category", data: tags, axisLabel: { interval: 0, rotate: tags.length > 2 ? 30 : 0, fontSize: 10 } },
      yAxis: { type: "value", name: unit, nameTextStyle: { fontSize: 10 } },
      series: [{ type: "bar", name, data: tags.map((t) => num(table[k][t])) }],
    });
  }
  window.addEventListener("resize", () => host.querySelectorAll(".cmp-chart").forEach((el) => {
    const inst = window.echarts.getInstanceByDom(el); if (inst) inst.resize();
  }));
}
