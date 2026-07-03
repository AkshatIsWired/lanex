// dse.js — Design-Space Exploration (Phase 2.B). Build a sweep over config
// variables, launch N sequential runs, watch queue progress, then compare +
// Pareto on completion.
import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { paretoOption } from "./charts.js";
import { gatherRunsScoped, getRunScope, designLabel, scopeToggleHtml, wireScopeToggle } from "./runscope.js";
import { jumpBarHtml, wireJump } from "./jumpnav.js";
import { collectRunPayload } from "./setup.js";

const COMMON_VARS = ["FP_CORE_UTIL", "PL_TARGET_DENSITY_PCT", "SYNTH_STRATEGY",
                     "CLOCK_PERIOD", "GRT_ANTENNA_REPAIR_ITERS"];

let _axes = [];

// Runs the user has picked (checkbox) to plot/compare on the Pareto. Persisted
// per design so a page reload keeps the selection.
let _pickedTags = new Set();

export function renderDse() {
  const root = document.getElementById("dse-body");
  if (!root) return;
  root.innerHTML =
    jumpBarHtml([
      { target: "dse-builder", label: "Sweep builder" },
      { target: "dse-runpick", label: "View runs" },
      { target: "dse-queue", label: "Queue" },
      { target: "dse-results", label: "Results" },
    ]) +
    "<div class='dse-builder card' id='dse-builder'>" +
    "<h3>Sweep builder</h3>" +
    "<div id='dse-axes'></div>" +
    "<div class='dse-add'>" +
    "  <select id='dse-var'>" + COMMON_VARS.map((v) =>
        "<option value='" + v + "'>" + v + "</option>").join("") + "</select>" +
    "  <input id='dse-vals' class='inp' type='text' placeholder='values, comma-separated e.g. 40,50,60' />" +
    "  <button class='btn' id='dse-add-axis'>Add axis</button>" +
    "</div>" +
    "<div class='dse-mode'>" +
    "  <label><input type='radio' name='dse-mode' value='grid' checked> Grid (all combinations)</label>" +
    "  <label><input type='radio' name='dse-mode' value='list'> List (zip axes)</label>" +
    "</div>" +
    "<div class='dse-foot'><span id='dse-count' class='muted'>0 runs</span>" +
    "  <button class='btn btn-primary' id='dse-run'>Run sweep</button>" +
    "  <button class='btn btn-ghost' id='dse-cancel' disabled>Cancel</button></div>" +
    "</div>" +
    // Run picker: choose which runs of THIS design go on the Pareto / compare,
    // OR load a whole previous sweep to view its metrics (tables + plots).
    "<div class='dse-runpick card' id='dse-runpick'>" +
    "  <div class='dse-runpick-head'><h3>View runs</h3>" +
    "    <span class='muted'>load a previous sweep, or tick runs to compare</span>" +
    "    <span class='dse-spacer'></span>" +
    "    <label class='dse-sweep-lbl'>Previous sweep " +
    "      <select id='dse-sweep-pick'><option value=''>—</option></select></label>" +
    "    <button class='btn btn-ghost' id='dse-runs-refresh'>↻ Refresh</button>" +
    "    <button class='btn btn-ghost' id='dse-runs-all'>All</button>" +
    "    <button class='btn btn-ghost' id='dse-runs-none'>None</button>" +
    "    <button class='btn btn-primary' id='dse-plot'>View metrics &amp; plots</button>" +
    "  </div>" +
    "  <div id='dse-runs' class='dse-runs'></div>" +
    "</div>" +
    "<div id='dse-queue'></div>" +
    // Results: metric/config comparison table + Pareto + per-metric bar chart.
    "<div id='dse-results' class='dse-results card' hidden>" +
    "  <div class='dse-results-head'><h3>Sweep results</h3>" +
    "    <span class='muted' id='dse-results-sub'></span>" +
    "    <span style='flex:1'></span>" +
    "    <button class='btn btn-ghost' id='dse-export-csv'>⬇ Export CSV</button></div>" +
    "  <div id='dse-results-table' class='dse-results-table'></div>" +
    "  <div class='dse-charts'>" +
    "    <div class='dse-chart-col'><div class='dse-chart-title'>Pareto — cell area vs setup slack</div>" +
    "      <div id='dse-pareto' class='chart-box' style='height:300px'></div></div>" +
    "    <div class='dse-chart-col'><div class='dse-chart-title'>Metric across runs " +
    "      <select id='dse-bar-metric' class='dse-bar-metric'></select></div>" +
    "      <div id='dse-bars' class='chart-box' style='height:300px'></div></div>" +
    "  </div>" +
    "</div>";

  root.querySelector("#dse-add-axis").addEventListener("click", () => addAxis(root));
  root.querySelector("#dse-run").addEventListener("click", () => startSweep(root));
  root.querySelector("#dse-cancel").addEventListener("click", () => api.dseCancel().catch(() => {}));
  root.querySelector("#dse-runs-refresh").addEventListener("click", () => renderRunPicker(root));
  root.querySelector("#dse-runs-all").addEventListener("click", () => {
    document.querySelectorAll("#dse-runs input[type=checkbox]").forEach((c) => { c.checked = true; _pickedTags.add(c.value); });
  });
  root.querySelector("#dse-runs-none").addEventListener("click", () => {
    _pickedTags.clear();
    document.querySelectorAll("#dse-runs input[type=checkbox]").forEach((c) => { c.checked = false; });
  });
  root.querySelector("#dse-plot").addEventListener("click", () => {
    const tags = Array.from(_pickedTags);
    if (tags.length < 1) { toast.show("Pick at least one run to view.", "warn"); return; }
    renderResults(root, tags);
  });
  root.querySelector("#dse-sweep-pick").addEventListener("change", (e) => {
    const key = e.target.value;
    if (!key) return;
    const tags = _sweepTags[key] || [];
    _pickedTags = new Set(tags);
    // Re-tick the checkboxes for the loaded sweep, then show its results.
    document.querySelectorAll("#dse-runs input[type=checkbox]").forEach((c) => { c.checked = _pickedTags.has(c.value); });
    if (tags.length) renderResults(root, tags);
  });
  paintAxes(root);
  renderRunPicker(root);
  wireJump(root);
}

// A DSE sweep tags its runs `dse-<base>-NN`. Group by <base> so the user can
// load a whole previous sweep at once.
function sweepBaseOf(tag) {
  const m = /^dse-(.+)-\d{2,}$/.exec(String(tag || ""));
  return m ? m[1] : null;
}

let _lastRuns = [];
// Map of sweep-picker option value -> the run tags that belong to that sweep.
// Filled from the persisted manifest (authoritative) plus a regex fallback for
// pre-manifest sweeps, so the picker survives a server restart.
let _sweepTags = {};

// Populate the run picker from this design's runs (issue #5: DSE had no run
// dropdown). Checkbox list so several runs can be plotted at once.
async function renderRunPicker(root) {
  const host = (root || document).querySelector("#dse-runs");
  if (!host) return;
  let runs = [];
  try { runs = await gatherRunsScoped(); } catch (_e) { runs = []; }
  _lastRuns = runs;
  // Scope toggle in the picker head (shared global pref).
  const head = (root || document).querySelector(".dse-runpick-head");
  if (head && !head.querySelector("#dse-run-scope")) {
    head.insertAdjacentHTML("beforeend", " " + scopeToggleHtml("dse-run-scope"));
    wireScopeToggle("dse-run-scope", () => renderRunPicker(root));
  }
  // Populate the "previous sweep" selector. Prefer the persisted manifest
  // (`/api/dse/sweeps` — carries axes/count/timestamp and can't be lost to a
  // tag-regex miss), then add any dse-<base>-NN groups not covered by it so
  // sweeps run before the manifest existed still appear.
  const sweepSel = (root || document).querySelector("#dse-sweep-pick");
  if (sweepSel) {
    const tagsOnDisk = new Set(runs.map((r) => r.tag));
    _sweepTags = {};
    const opts = [];
    let manifests = [];
    try { manifests = (await api.dseSweeps()).sweeps || []; } catch (_e) { manifests = []; }
    const coveredBases = new Set();
    for (const m of manifests) {
      // Only surface tags that still exist on disk (a manifest can outlive a
      // deleted run dir).
      const live = (m.tags || []).filter((t) => tagsOnDisk.has(t));
      if (!live.length) continue;
      coveredBases.add(m.base);
      const key = "id:" + m.id;
      _sweepTags[key] = live;
      const when = (m.created_at || "").replace("T", " ").slice(0, 16);
      opts.push("<option value='" + fmt.escape(key) + "'>" +
        fmt.escape(m.base) + " — " + live.length + " runs" + (when ? " · " + fmt.escape(when) : "") + "</option>");
    }
    // Regex fallback for legacy (un-manifested) sweeps.
    const bases = {};
    for (const r of runs) { const b = sweepBaseOf(r.tag); if (b && !coveredBases.has(b)) bases[b] = (bases[b] || 0) + 1; }
    for (const b of Object.keys(bases).sort()) {
      const key = "re:" + b;
      _sweepTags[key] = runs.map((r) => r.tag).filter((t) => sweepBaseOf(t) === b);
      opts.push("<option value='" + fmt.escape(key) + "'>" + fmt.escape(b) + " (" + bases[b] + " runs)</option>");
    }
    const keep = sweepSel.value;
    sweepSel.innerHTML = "<option value=''>—</option>" + opts.join("");
    if (keep && _sweepTags[keep]) sweepSel.value = keep;
  }
  if (!runs.length) {
    host.innerHTML = "<span class='muted'>No runs yet for this design. Run a sweep (or the flow) first.</span>";
    return;
  }
  const allScope = getRunScope() === "all";
  host.innerHTML = runs.map((r) => {
    const checked = _pickedTags.has(r.tag) ? " checked" : "";
    const ok = r.success ? "pf-pass" : "pf-fail";
    const prefix = allScope ? "<span class='muted'>" + fmt.escape(designLabel(r._design)) + " · </span>" : "";
    return "<label class='dse-run-row'><input type='checkbox' value='" + fmt.escape(r.tag) + "'" + checked + "/>" +
      "<span class='pf " + ok + "'></span>" + prefix + "<code>" + fmt.escape(r.tag) + "</code></label>";
  }).join("");
  host.querySelectorAll("input[type=checkbox]").forEach((c) => {
    c.addEventListener("change", () => {
      if (c.checked) _pickedTags.add(c.value);
      else _pickedTags.delete(c.value);
    });
  });
}

function addAxis(root) {
  const v = root.querySelector("#dse-var").value;
  const raw = root.querySelector("#dse-vals").value.trim();
  const values = raw.split(",").map((x) => x.trim()).filter(Boolean);
  if (!values.length) { toast.show("Enter at least one value.", "warn"); return; }
  _axes.push({ var: v, values });
  root.querySelector("#dse-vals").value = "";
  paintAxes(root);
}

function paintAxes(root) {
  const host = root.querySelector("#dse-axes");
  host.innerHTML = _axes.map((a, i) =>
    "<div class='dse-axis'><code>" + fmt.escape(a.var) + "</code> = [" +
    a.values.map(fmt.escape).join(", ") + "] " +
    "<button class='btn btn-ghost dse-del' data-i='" + i + "'>✕</button></div>").join("");
  host.querySelectorAll(".dse-del").forEach((b) =>
    b.addEventListener("click", () => { _axes.splice(+b.dataset.i, 1); paintAxes(root); }));
  updateCount(root);
}

function updateCount(root) {
  const mode = root.querySelector("input[name='dse-mode']:checked")?.value || "grid";
  let n = 0;
  if (_axes.length) {
    n = mode === "list"
      ? (_axes[0].values.length)
      : _axes.reduce((acc, a) => acc * a.values.length, 1);
  }
  root.querySelector("#dse-count").textContent = n + " run" + (n === 1 ? "" : "s");
}

// How many runs the current sweep expands to (mirrors updateCount).
function sweepCount(root) {
  const mode = root.querySelector("input[name='dse-mode']:checked")?.value || "grid";
  if (!_axes.length) return 0;
  return mode === "list" ? _axes[0].values.length
    : _axes.reduce((acc, a) => acc * a.values.length, 1);
}

// Warn before launching: each config is a full RTL→GDS flow (minutes, several GB
// RAM at routing/STA). On a box with little free RAM and no swap, a memory spike
// freezes the whole session — the cause of the reported "computer hung". Runs are
// sequential (one at a time), so this is about per-run peak, not N× at once.
async function confirmResources(root) {
  const n = sweepCount(root);
  let res = null;
  try { res = await api.systemResources(); } catch (_e) { res = null; }
  const r = res && (res.data || res);
  const { confirmDialog } = await import("./dialog.js");
  if (!r || !r.ok || r.risk === "ok") {
    // Still confirm for big sweeps even when memory looks fine.
    if (n >= 6) {
      return confirmDialog({ title: "Launch " + n + " runs?", confirmText: "Launch",
        body: "This launches " + n + " full RTL→GDS runs, one after another (each can take many minutes)." });
    }
    return true;
  }
  const parts = ["This launches " + n + " full RTL→GDS runs, one after another. " +
    "Each is a complete flow — OpenROAD routing/STA can peak at several GB of RAM."];
  if (r.available_gb != null) parts.push("Free RAM now: ~" + r.available_gb + " GB of " + r.total_gb + " GB.");
  if (r.swap_gb === 0) parts.push("Swap: none — a memory spike will hang the machine instead of slowing it.");
  if (r.reasons && r.reasons.length) parts.push("Why this is risky here: " + r.reasons.join("; ") + ".");
  parts.push("Tip: sweep fewer values, run one at a time, or add swap.");
  return confirmDialog({ title: "Resource warning", danger: true, confirmText: "Launch anyway",
    body: parts.join(" ") });
}

async function startSweep(root) {
  if (!_axes.length) { toast.show("Add at least one axis.", "warn"); return; }
  const mode = root.querySelector("input[name='dse-mode']:checked")?.value || "grid";
  if (!(await confirmResources(root))) {
    toast.show("Sweep cancelled.", "warn");
    return;
  }
  try {
    // Carry the SAME Setup context into every sweep point (base overrides, the
    // picked PDK/SCL, custom-cell / macro selections via the backend, and the
    // file-picker sources) so a swept run matches a Setup run — only the swept
    // axes differ. Without this a sweep silently ran a different design (A2).
    const base = collectRunPayload();
    const res = await api.dseStart({
      axes: _axes, mode, run_mode: state.runMode, flow_name: "Classic",
      base_overrides: base.overrides, sources: base.sources, extras: base.extras,
    });
    if (!res.ok) { toast.show("DSE refused: " + (res.error || "unknown"), "error"); return; }
    toast.show("Started " + res.count + " runs.", "success");
    root.querySelector("#dse-cancel").disabled = false;
    pollStatus(root);
  } catch (ex) {
    toast.show("DSE failed: " + (ex.message || ex), "error");
  }
}

let _pollTimer = null;
async function pollStatus(root) {
  clearTimeout(_pollTimer);
  let st;
  try { st = await api.dseStatus(); } catch (_e) { return; }
  const host = root.querySelector("#dse-queue");
  const row = (tag, cls, label) =>
    "<div class='dse-qrow'><span class='pf " + cls + "'></span><code>" + fmt.escape(tag) +
    "</code> <span class='muted'>" + label + "</span></div>";
  host.innerHTML = "<h3>Queue</h3>" +
    (st.running ? row(st.running, "pf-warn", "running") : "") +
    (st.done || []).map((t) => row(t, "pf-pass", "done")).join("") +
    (st.failed || []).map((t) => row(t, "pf-fail", "failed")).join("") +
    (st.queued || []).map((t) => row(t, "pf-absent", "queued")).join("");
  if (st.active) {
    _pollTimer = setTimeout(() => pollStatus(root), 3000);
  } else {
    root.querySelector("#dse-cancel").disabled = true;
    const tags = [...(st.done || []), ...(st.failed || [])];
    // Auto-select the sweep's runs in the picker, refresh it, then show results.
    tags.forEach((t) => _pickedTags.add(t));
    renderRunPicker(root);
    if (tags.length >= 1) renderResults(root, tags);
  }
}

// Curated metrics shown in the comparison table + offered for the bar chart.
// Keyed by real LibreLane metric names (verified against introspect.list_metrics);
// missing ones are simply skipped, so this is safe across PDKs/flows.
const RESULT_METRICS = [
  { key: "design__instance__area", label: "Cell area", unit: "µm²" },
  { key: "design__die__area", label: "Die area", unit: "µm²" },
  { key: "design__instance__count", label: "Cell count", unit: "" },
  { key: "timing__setup__ws", label: "Setup WNS", unit: "ns" },
  { key: "timing__hold__ws", label: "Hold WNS", unit: "ns" },
  { key: "timing__setup__tns", label: "Setup TNS", unit: "ns" },
  { key: "route__wirelength", label: "Wirelength", unit: "µm" },
  { key: "power__total", label: "Total power", unit: "W" },
  { key: "clock__skew__worst_setup", label: "Clock skew (setup)", unit: "ns" },
  { key: "clock__skew__worst_hold", label: "Clock skew (hold)", unit: "ns" },
];

// Render a previous/just-finished sweep: a config+metrics comparison table, a
// Pareto, and a per-metric bar chart across the selected runs. Reuses the
// existing /api/compare endpoint — no new backend. Issue: "view a previous DSE
// run with tables + plots, not just launch a new one."
async function renderResults(root, tags) {
  const box = root.querySelector("#dse-results");
  const sub = root.querySelector("#dse-results-sub");
  const tableEl = root.querySelector("#dse-results-table");
  if (!box) return;
  box.hidden = false;
  if (sub) sub.textContent = "loading " + tags.length + " run" + (tags.length === 1 ? "" : "s") + "…";
  // Pass absolute run_dirs (from the gathered run list) so runs from another
  // design still resolve on the backend, matching the Compare tab.
  const byTag = {};
  for (const r of _lastRuns) byTag[r.tag] = r;
  const runDirs = tags.map((t) => byTag[t] && byTag[t].run_dir).filter(Boolean);
  let data;
  try { data = await api.compare(tags, runDirs); } catch (ex) {
    if (sub) sub.textContent = "could not load: " + (ex.message || ex);
    return;
  }
  const runs = data.runs || [];
  const mt = data.metric_table || {};
  const best = data.best || {};
  if (sub) sub.textContent = runs.length + " run" + (runs.length === 1 ? "" : "s") + " compared";

  // ---- comparison table (config diff + curated metrics; best cell highlighted)
  const th = "<th>Field</th>" + runs.map((r) =>
    "<th class='" + (r.success ? "ok" : "bad") + "'>" + fmt.escape(r.tag) + "</th>").join("");
  const rowsCfg = Object.entries(data.config_diff || {}).map(([k, vals]) =>
    "<tr><td class='rk'>" + fmt.escape(k) + "</td>" +
    runs.map((r) => "<td>" + fmt.escape(fmtVal(vals[r.tag])) + "</td>").join("") + "</tr>").join("");
  const rowsMetric = RESULT_METRICS.filter((m) => mt[m.key]).map((m) => {
    const winner = best[m.key];
    return "<tr><td class='rk'>" + fmt.escape(m.label) +
      (m.unit ? " <span class='mu'>" + fmt.escape(m.unit) + "</span>" : "") + "</td>" +
      runs.map((r) => {
        const v = mt[m.key] ? mt[m.key][r.tag] : undefined;
        const win = winner && winner === r.tag ? " class='best'" : "";
        return "<td" + win + ">" + fmt.escape(fmt.metric ? fmt.metric(v) : fmtVal(v)) + "</td>";
      }).join("") + "</tr>";
  }).join("");
  tableEl.innerHTML =
    "<table class='cmp-table'><thead><tr>" + th + "</tr></thead><tbody>" +
    (rowsCfg ? "<tr class='sec'><td colspan='" + (runs.length + 1) + "'>Configuration (differs)</td></tr>" + rowsCfg : "") +
    (rowsMetric ? "<tr class='sec'><td colspan='" + (runs.length + 1) + "'>Metrics (best highlighted)</td></tr>" + rowsMetric : "") +
    "</tbody></table>" +
    (!rowsCfg && !rowsMetric ? "<p class='muted'>No comparable config/metrics — the runs may not have completed.</p>" : "");

  // ---- Pareto (cell area vs setup slack)
  const points = runs.map((r) => ({
    tag: r.tag,
    x: mt["design__instance__area"] ? Number(mt["design__instance__area"][r.tag]) : null,
    y: mt["timing__setup__ws"] ? Number(mt["timing__setup__ws"][r.tag]) : null,
  }));
  drawChart(root, "#dse-pareto", paretoOption(points, { xName: "cell area (µm²)", yName: "setup WNS (ns)" }),
    "Need cell-area + setup-slack metrics for a Pareto.");

  // ---- per-metric bar chart with a metric selector
  const sel = root.querySelector("#dse-bar-metric");
  if (sel) {
    const present = RESULT_METRICS.filter((m) => mt[m.key]);
    const keep = sel.value;
    sel.innerHTML = present.map((m) =>
      "<option value='" + m.key + "'>" + fmt.escape(m.label) + "</option>").join("");
    if (keep && present.some((m) => m.key === keep)) sel.value = keep;
    sel.onchange = () => drawBar(root, runs, mt, sel.value);
    drawBar(root, runs, mt, sel.value || (present[0] && present[0].key));
  }

  // ---- CSV export of the comparison (config diff + curated metrics).
  const exportBtn = root.querySelector("#dse-export-csv");
  if (exportBtn) exportBtn.onclick = () => exportResultsCsv(runs, data);
}

function csvCell(v) {
  const s = (v === null || v === undefined) ? "" : String(v);
  return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

function exportResultsCsv(runs, data) {
  const mt = data.metric_table || {};
  const tags = runs.map((r) => r.tag);
  const lines = [];
  lines.push(["field", ...tags].map(csvCell).join(","));
  for (const [k, vals] of Object.entries(data.config_diff || {})) {
    lines.push([k, ...tags.map((t) => fmtVal(vals[t]))].map(csvCell).join(","));
  }
  for (const m of RESULT_METRICS) {
    if (!mt[m.key]) continue;
    lines.push([m.label + (m.unit ? " (" + m.unit + ")" : ""),
      ...tags.map((t) => mt[m.key][t])].map(csvCell).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "dse-sweep-" + (tags[0] || "results") + ".csv";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function drawBar(root, runs, mt, key) {
  const meta = RESULT_METRICS.find((m) => m.key === key);
  const tags = runs.map((r) => r.tag);
  const vals = runs.map((r) => {
    const v = mt[key] ? Number(mt[key][r.tag]) : null;
    return (v === v && Math.abs(v) !== Infinity) ? v : null;   // drop NaN/Inf
  });
  const opt = (!key || vals.every((v) => v === null)) ? null : {
    tooltip: { trigger: "axis" },
    grid: { left: 60, right: 16, top: 16, bottom: 60 },
    xAxis: { type: "category", data: tags, axisLabel: { rotate: 30, interval: 0 } },
    yAxis: { type: "value", name: meta ? (meta.label + (meta.unit ? " (" + meta.unit + ")" : "")) : key },
    series: [{ type: "bar", data: vals, label: { show: true, position: "top",
      formatter: (o) => (o.value == null ? "" : o.value) } }],
  };
  drawChart(root, "#dse-bars", opt, "No numeric values for this metric.");
}

function drawChart(root, sel, opt, emptyMsg) {
  const el = root.querySelector(sel);
  if (!el) return;
  // Reuse the existing ECharts instance bound to this DOM node. Re-running
  // echarts.init() on a node that already has an instance returns the OLD one
  // (with a warning); and wiping innerHTML first destroys its canvas — together
  // that made the bar chart vanish the moment the metric <select> changed. So:
  // get-or-init, never clear innerHTML while an instance lives, and use
  // notMerge=true so switching metric fully replaces the series.
  let chart = window.echarts && window.echarts.getInstanceByDom(el);
  if (!opt || !window.echarts) {
    if (chart) chart.dispose();
    el.innerHTML = "<p class='muted'>" + (emptyMsg || "No data.") + "</p>";
    return;
  }
  if (!chart) {
    el.innerHTML = "";            // clear any prior empty-state message
    chart = window.echarts.init(el);
  }
  chart.setOption(opt, true);      // notMerge: replace series on metric change
  chart.resize();
  el.setAttribute("role", "img");
  el.setAttribute("aria-label", "Design-space exploration scatter — the same points are in the results table below.");
}

function fmtVal(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") { try { return JSON.stringify(v); } catch (_e) { return String(v); } }
  return String(v);
}
