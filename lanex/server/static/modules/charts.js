// charts.js — pure ECharts option builders (Phase 1.C). Each takes a metrics
// object and returns an ECharts `option`, or null when its inputs are absent (so
// the caller hides the chart cleanly). No DOM, no globals — unit-testable in the
// Node harness. Colors come from the theme at render time (see theme-echarts.js).

function num(v) {
  if (typeof v === "number" && isFinite(v)) return v;
  const n = Number(v);
  return isFinite(n) ? n : null;
}

// 1. Timing slack: setup/hold WNS + TNS grouped bars.
export function timingSlackOption(metrics) {
  const keys = [
    ["timing__setup__ws", "Setup WNS"],
    ["timing__setup__tns", "Setup TNS"],
    ["timing__hold__ws", "Hold WNS"],
    ["timing__hold__tns", "Hold TNS"],
  ];
  const data = [];
  const labels = [];
  for (const [k, label] of keys) {
    const v = num(metrics[k]);
    if (v !== null) { data.push(v); labels.push(label); }
  }
  if (!data.length) return null;
  return {
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: labels },
    yAxis: { type: "value", name: "ns" },
    series: [{
      type: "bar",
      data: data.map((v) => ({ value: v, itemStyle: { opacity: v < 0 ? 1 : 0.85 } })),
    }],
  };
}

// 2. Utilization gauge.
export function utilizationOption(metrics) {
  const u = num(metrics["design__instance__utilization"]);
  if (u === null) return null;
  const pct = Math.round(u * 1000) / 10;
  return {
    series: [{
      type: "gauge", min: 0, max: 100, progress: { show: true },
      axisLine: { lineStyle: { width: 10 } },
      detail: { valueAnimation: true, formatter: "{value}%", fontSize: 18 },
      data: [{ value: pct, name: "Utilization" }],
    }],
  };
}

// 3. Cell-type breakdown donut. `cells` = [{cell, count}].
export function cellBreakdownOption(cells) {
  if (!Array.isArray(cells) || !cells.length) return null;
  const top = cells.filter((c) => num(c.count) !== null).slice(0, 12);
  if (!top.length) return null;
  return {
    tooltip: { trigger: "item" },
    series: [{
      type: "pie", radius: ["40%", "70%"],
      data: top.map((c) => ({ name: c.cell, value: num(c.count) })),
    }],
  };
}

// 4. Per-step runtime bars. `timing` = [{id, seconds}].
export function runtimeOption(timing) {
  if (!Array.isArray(timing) || !timing.length) return null;
  const rows = timing.filter((t) => num(t.seconds) !== null)
    .sort((a, b) => b.seconds - a.seconds).slice(0, 20);
  if (!rows.length) return null;
  return {
    tooltip: { trigger: "axis" },
    grid: { left: 140 },
    xAxis: { type: "value", name: "s" },
    yAxis: { type: "category", data: rows.map((r) => r.id).reverse() },
    series: [{ type: "bar", data: rows.map((r) => r.seconds).reverse() }],
  };
}

// 5. Power breakdown (only if power__* metrics exist; never fabricated).
export function powerOption(metrics) {
  const parts = [
    ["power__internal__total", "Internal"],
    ["power__switching__total", "Switching"],
    ["power__leakage__total", "Leakage"],
  ];
  const data = [];
  for (const [k, label] of parts) {
    const v = num(metrics[k]);
    if (v !== null) data.push({ name: label, value: v });
  }
  if (!data.length) return null;
  return { tooltip: { trigger: "item" }, series: [{ type: "pie", radius: "65%", data }] };
}

// 6. Trend of a metric across runs. `series` = [{tag, value}].
export function trendOption(series, metricKey) {
  if (!Array.isArray(series) || series.length < 2) return null;
  const pts = series.map((s) => [s.tag, num(s.value)]).filter((p) => p[1] !== null);
  if (pts.length < 2) return null;
  return {
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: pts.map((p) => p[0]) },
    yAxis: { type: "value", name: metricKey || "" },
    series: [{ type: "line", smooth: true, data: pts.map((p) => p[1]) }],
  };
}

// 7. Pareto scatter for DSE: points = [{tag, x, y, size?}].
export function paretoOption(points, { xName = "area", yName = "WNS" } = {}) {
  if (!Array.isArray(points) || !points.length) return null;
  const data = points
    .map((p) => ({ name: p.tag, value: [num(p.x), num(p.y)] }))
    .filter((d) => d.value[0] !== null && d.value[1] !== null);
  if (!data.length) return null;
  return {
    tooltip: { trigger: "item", formatter: (o) => o.name + "<br>" + xName + ": " + o.value[0] + "<br>" + yName + ": " + o.value[1] },
    xAxis: { type: "value", name: xName },
    yAxis: { type: "value", name: yName },
    series: [{ type: "scatter", symbolSize: 14, data, label: { show: true, formatter: "{b}", position: "top" } }],
  };
}
