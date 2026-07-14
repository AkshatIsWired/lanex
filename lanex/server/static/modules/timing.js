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
import { provBtnHtml, wireProvBtns } from "./provenance.js";

let _kind = "setup";
let _wired = false;
let _sortKey = "slack";
let _sortAsc = true;
let _rows = [];
let _compareTag = "";   // E4.3 — the run being compared against (or "")
let _baseTag = null;    // the run currently shown

function slackPill(slack, met) {
  const cls = met === false ? "pill-fail" : (slack < 0 ? "pill-warn" : "pill-pass");
  const txt = (slack === null || slack === undefined) ? "—" : fmt.metric(slack);
  const flag = met === false ? "VIOLATED" : "MET";
  return "<span class='pill " + cls + "' title='" + flag + "'>" + txt + "</span>";
}

function drawHist(hist, unit) {
  const el = document.getElementById("timing-hist");
  if (!el) return;
  let chart = window.echarts && window.echarts.getInstanceByDom(el);
  if (!window.echarts || !hist || !hist.bins || !hist.bins.length) {
    if (chart) chart.dispose();
    el.innerHTML = "<p class='muted' style='padding:var(--s-3)'>No slack distribution.</p>";
    return;
  }
  if (!chart) { el.innerHTML = ""; chart = window.echarts.init(el); }
  el.setAttribute("role", "img");
  el.setAttribute("aria-label", "Timing slack histogram — the worst endpoints are listed in the table below.");
  const theme = chartTheme();
  const pal = chartPalette();
  chart.setOption({
    ...theme,
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 16, top: 16, bottom: 40 },
    xAxis: { type: "category", data: hist.bins, name: "slack (" + (unit || "ns") + ")", nameLocation: "middle",
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
  if (srcEl) {
    // Name the report(s) the table was parsed from AND let the user open each
    // raw file — one button per corner report (the label is the corner subdir).
    const btns = (data.sources || []).map((rel) => {
      const corner = (rel.split("/").length > 2 ? rel.split("/")[1] : rel);
      return provBtnHtml(
        { kind: "report", tag: tag, path: rel, needle: "Startpoint:" },
        "Open the raw STA report " + rel + " (as OpenSTA wrote it)") +
        "<span class='muted' style='font-size:var(--t-xs)'>" + fmt.escape(corner) + "</span>";
    }).join(" ");
    srcEl.innerHTML = (data.source ? "from " + fmt.escape(data.source) + " " : "") + btns;
    wireProvBtns(srcEl);
  }
  const worstCls = (data.worst_slack !== null && data.worst_slack < 0) ? "pill-fail" : "pill-pass";
  const unit = data.unit || "ns";
  summary.innerHTML =
    "<span class='pill " + worstCls + "'>worst " + (data.kind) + " slack " +
      (data.worst_slack === null ? "—" : fmt.metric(data.worst_slack)) + " " + fmt.escape(unit) + "</span>" +
    "<span class='pill pill-info'>" + data.total + " paths</span>" +
    "<span class='pill " + (data.violating ? "pill-fail" : "pill-pass") + "'>" +
      data.violating + " violating</span>" +
    (data.corners && data.corners.length ?
      "<span class='muted' style='margin-left:var(--s-2)'>corner: " + fmt.escape(data.corners.join(", ")) + "</span>" : "");
  _rows = data.paths || [];
  _baseTag = tag;
  _sortKey = "slack"; _sortAsc = true;
  drawHist(data.histogram, data.unit);
  renderTable();
  populateCompareSelect(tag);
  renderTimingCompare();
}

// E4.3 — populate the "compare against" picker from this design's other runs.
function populateCompareSelect(currentTag) {
  const sel = document.getElementById("timing-compare");
  if (!sel) return;
  const runs = (state.runs || []).filter((r) => r.tag !== currentTag);
  if (_compareTag && !runs.some((r) => r.tag === _compareTag)) _compareTag = "";
  sel.innerHTML = "<option value=''>— none —</option>" +
    runs.map((r) => "<option value='" + fmt.escape(r.tag) + "'" +
      (r.tag === _compareTag ? " selected" : "") + ">" + fmt.escape(r.tag) + "</option>").join("");
}

// E4.3 — join the two runs' paths by endpoint and show the endpoints whose slack
// changed most. Only endpoints present (with a real slack) in BOTH runs are shown;
// nothing is inferred for endpoints that don't match, so the delta is always real.
async function renderTimingCompare() {
  const out = document.getElementById("timing-compare-out");
  if (!out) return;
  if (!_compareTag || !_baseTag) { out.innerHTML = ""; return; }
  out.innerHTML = "<p class='muted'>Loading comparison…</p>";
  let other;
  try {
    other = await api.timingPaths(_compareTag, _kind, 200);
  } catch (e) {
    out.innerHTML = "<div class='cmp-error'>Compare failed: " + fmt.escape(e.message || e) + "</div>";
    return;
  }
  if (!other || !other.ok) {
    out.innerHTML = "<p class='muted'>No " + _kind + " timing report for “" + fmt.escape(_compareTag) + "”.</p>";
    return;
  }
  const otherByEp = {};
  for (const p of (other.paths || [])) if (p.endpoint && p.slack != null) otherByEp[p.endpoint] = p.slack;
  const joined = [];
  for (const p of _rows) {
    if (!p.endpoint || p.slack == null) continue;
    if (!(p.endpoint in otherByEp)) continue;
    const b = otherByEp[p.endpoint];
    joined.push({ endpoint: p.endpoint, a: p.slack, b, d: p.slack - b });
  }
  joined.sort((x, y) => Math.abs(y.d) - Math.abs(x.d));
  const unit = other.unit || "ns";
  const head = "<h4 style='margin:var(--s-4) 0 var(--s-2)'>Δ vs “" + fmt.escape(_compareTag) + "” (" + fmt.escape(_kind) + ")</h4>";
  if (!joined.length) {
    out.innerHTML = head + "<p class='muted'>No endpoints in common between these two runs for this analysis.</p>";
    return;
  }
  const top = joined.slice(0, 50);
  const rows = top.map((j) =>
    "<tr><td><code>" + fmt.escape(j.endpoint) + "</code></td>" +
    "<td>" + fmt.metric(j.a) + "</td><td>" + fmt.metric(j.b) + "</td>" +
    "<td class='" + (j.d < 0 ? "tp-neg" : "tp-pos") + "'>" + (j.d >= 0 ? "+" : "") + fmt.metric(j.d) + "</td></tr>").join("");
  out.innerHTML = head +
    "<p class='muted'>" + joined.length + " endpoint(s) in common, sorted by |Δ slack|" +
    (top.length < joined.length ? " (top " + top.length + " shown)" : "") +
    ". Positive Δ = this run has more slack than “" + fmt.escape(_compareTag) + "”.</p>" +
    "<table class='cmp-table'><thead><tr><th>Endpoint</th><th>this</th><th>“" +
    fmt.escape(_compareTag) + "”</th><th>Δ slack (" + fmt.escape(unit) + ")</th></tr></thead><tbody>" + rows + "</tbody></table>";
}

function wireOnce() {
  if (_wired) return;
  _wired = true;
  document.querySelectorAll("#timing-controls [data-timing-kind]").forEach((btn) => {
    btn.addEventListener("click", () => {
      _kind = btn.dataset.timingKind;
      document.querySelectorAll("#timing-controls [data-timing-kind]").forEach((b) =>
        b.classList.toggle("is-active", b === btn));
      renderTimingPaths(_baseTag || state.selectedRunTag);
    });
  });
  const cmp = document.getElementById("timing-compare");
  if (cmp) cmp.addEventListener("change", () => { _compareTag = cmp.value || ""; renderTimingCompare(); });
}
