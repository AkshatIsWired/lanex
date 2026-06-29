// timing.js — STA worst-paths table + slack histogram (Verify tab).
//
// Renders the structured output of controller/timing.py (parsed from the run's
// existing OpenSTA report — no extra tool run). Setup/Hold toggle, a slack
// histogram (ECharts), and a sortable worst-paths table whose rows expand to the
// full path report. Honours the project's "non-finite metrics are real" rule and
// the get-or-init ECharts pattern (never innerHTML-wipe a live instance).

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { chartTheme, chartPalette } from "./theme-echarts.js";

let _kind = "setup";
let _wired = false;
let _sortKey = "slack";
let _sortAsc = true;
let _rows = [];

function slackPill(slack, met) {
  const cls = met === false ? "pill-fail" : (slack < 0 ? "pill-warn" : "pill-pass");
  const txt = (slack === null || slack === undefined) ? "—" : fmt.metric(slack);
  const flag = met === false ? "VIOLATED" : "MET";
  return "<span class='pill " + cls + "' title='" + flag + "'>" + txt + "</span>";
}

function drawHist(hist) {
  const el = document.getElementById("timing-hist");
  if (!el) return;
  let chart = window.echarts && window.echarts.getInstanceByDom(el);
  if (!window.echarts || !hist || !hist.bins || !hist.bins.length) {
    if (chart) chart.dispose();
    el.innerHTML = "<p class='muted' style='padding:var(--s-3)'>No slack distribution.</p>";
    return;
  }
  if (!chart) { el.innerHTML = ""; chart = window.echarts.init(el); }
  const theme = chartTheme();
  const pal = chartPalette();
  chart.setOption({
    ...theme,
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 16, top: 16, bottom: 40 },
    xAxis: { type: "category", data: hist.bins, name: "slack (ns)", nameLocation: "middle",
             nameGap: 26, axisLabel: { rotate: 45, fontSize: 10 } },
    yAxis: { type: "value", name: "paths" },
    series: [{
      type: "bar", data: hist.counts, itemStyle: { color: pal[0] },
      barWidth: "92%",
    }],
  }, true);
  chart.resize();
}

function renderTable() {
  const host = document.getElementById("timing-table");
  if (!host) return;
  if (!_rows.length) { host.innerHTML = "<p class='muted'>No timing paths.</p>"; return; }
  const sorted = [..._rows].sort((a, b) => {
    let x = a[_sortKey], y = b[_sortKey];
    if (typeof x === "string") { x = x || ""; y = y || ""; return _sortAsc ? x.localeCompare(y) : y.localeCompare(x); }
    x = (x === null || x === undefined) ? Infinity : x;
    y = (y === null || y === undefined) ? Infinity : y;
    return _sortAsc ? x - y : y - x;
  });
  const arrow = (k) => _sortKey === k ? (_sortAsc ? " ▲" : " ▼") : "";
  const head = "<tr>" +
    "<th data-sort='slack' class='tp-sortable num'>Slack" + arrow("slack") + "</th>" +
    "<th data-sort='startpoint' class='tp-sortable'>Startpoint" + arrow("startpoint") + "</th>" +
    "<th data-sort='endpoint' class='tp-sortable'>Endpoint" + arrow("endpoint") + "</th>" +
    "<th data-sort='group' class='tp-sortable'>Group" + arrow("group") + "</th>" +
    "<th>Corner</th></tr>";
  const body = sorted.map((p, i) => {
    const cls = p.met === false ? "tp-row-fail" : "";
    const main = "<tr class='tp-row " + cls + "' data-tp='" + i + "'>" +
      "<td class='num'>" + slackPill(p.slack, p.met) + "</td>" +
      "<td class='mono'>" + fmt.escape(p.startpoint || "—") + "</td>" +
      "<td class='mono'>" + fmt.escape(p.endpoint || "—") + "</td>" +
      "<td>" + fmt.escape(p.group || "—") + "</td>" +
      "<td class='muted'>" + fmt.escape(p.corner || "—") + "</td></tr>";
    const detail = "<tr class='tp-detail' data-tp-detail='" + i + "' hidden><td colspan='5'>" +
      "<pre class='tp-pre'>" + fmt.escape(p.path_text || "(no path detail)") + "</pre></td></tr>";
    return main + detail;
  }).join("");
  host.innerHTML = "<table class='data-table tp-table'><thead>" + head + "</thead><tbody>" + body + "</tbody></table>";
  host.querySelectorAll("th.tp-sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const k = th.dataset.sort;
      if (_sortKey === k) _sortAsc = !_sortAsc; else { _sortKey = k; _sortAsc = (k === "slack"); }
      renderTable();
    });
  });
  host.querySelectorAll("tr.tp-row").forEach((tr) => {
    tr.addEventListener("click", () => {
      const d = host.querySelector("tr[data-tp-detail='" + tr.dataset.tp + "']");
      if (d) d.hidden = !d.hidden;
    });
  });
}

export async function renderTimingPaths(tag) {
  wireOnce();
  tag = tag || state.selectedRunTag || null;
  const summary = document.getElementById("timing-summary");
  const srcEl = document.getElementById("timing-source");
  const tableEl = document.getElementById("timing-table");
  if (!summary || !tableEl) return;
  summary.innerHTML = "<span class='muted'>Loading timing…</span>";
  tableEl.innerHTML = "";
  let data;
  try {
    data = await api.timingPaths(tag, _kind, 200);
  } catch (e) {
    summary.innerHTML = "<span class='pill pill-warn'>" + fmt.escape(e.message || e) + "</span>";
    _rows = []; drawHist(null); renderTable();
    return;
  }
  if (!data || !data.ok) {
    summary.innerHTML = "<span class='muted'>" + fmt.escape((data && data.error) || "No timing report for this run yet.") + "</span>";
    if (srcEl) srcEl.textContent = "";
    _rows = []; drawHist(null); renderTable();
    return;
  }
  if (srcEl) srcEl.textContent = data.source ? ("from " + data.source) : "";
  const worstCls = (data.worst_slack !== null && data.worst_slack < 0) ? "pill-fail" : "pill-pass";
  summary.innerHTML =
    "<span class='pill " + worstCls + "'>worst " + (data.kind) + " slack " +
      (data.worst_slack === null ? "—" : fmt.metric(data.worst_slack)) + " ns</span>" +
    "<span class='pill pill-info'>" + data.total + " paths</span>" +
    "<span class='pill " + (data.violating ? "pill-fail" : "pill-pass") + "'>" +
      data.violating + " violating</span>" +
    (data.corners && data.corners.length ?
      "<span class='muted' style='margin-left:var(--s-2)'>corner: " + fmt.escape(data.corners.join(", ")) + "</span>" : "");
  _rows = data.paths || [];
  _sortKey = "slack"; _sortAsc = true;
  drawHist(data.histogram);
  renderTable();
}

function wireOnce() {
  if (_wired) return;
  _wired = true;
  document.querySelectorAll("#timing-controls [data-timing-kind]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _kind = btn.dataset.timingKind;
      document.querySelectorAll("#timing-controls [data-timing-kind]").forEach((b) =>
        b.classList.toggle("is-active", b === btn));
      renderTimingPaths(state.selectedRunTag);
    });
  });
}
