// barchart.js — the bar charts LanEx draws with ECharts, built in one place so
// they all look alike: bars at most 22 px thick with a 4 px rounded end and a
// square base, 2 px gaps between touching bars, hairline grids, values in text
// colours (never the bar's colour) and a tooltip on every bar.
//
//   histogramOption({ edges, counts, unit })   slack distribution (Verify)
//   runBarsOption({ labels, values, unit })    one bar per run (Compare, DSE)

import { chartTheme, chartPalette, chartInk } from "./theme-echarts.js";

const num = (v) => (typeof v === "number" ? v : Number(v));
const finite = (v) => v !== null && v !== undefined && v !== "" && Number.isFinite(num(v));

// Short, honest number text: 3 significant decimals at most, thousands grouped.
export function fmtValue(v, unit) {
  if (!finite(v)) return "—";
  const n = num(v), a = Math.abs(n);
  const s = a >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 0 })
    : a >= 100 ? n.toFixed(1).replace(/\.0$/, "")
    : a >= 1 ? String(+n.toFixed(3))
    : a === 0 ? "0" : String(+n.toPrecision(3));
  return unit ? s + " " + unit : s;
}

// Mix two #rrggbb colours (t = 0 → a, 1 → b).
function mix(a, b, t) {
  const p = (h) => { const n = parseInt(String(h).replace("#", "").slice(0, 6), 16); return [n >> 16 & 255, n >> 8 & 255, n & 255]; };
  if (!/^#?[0-9a-f]{6}/i.test(a) || !/^#?[0-9a-f]{6}/i.test(b)) return a;
  const x = p(a), y = p(b);
  return "#" + x.map((c, i) => Math.round(c + (y[i] - c) * t).toString(16).padStart(2, "0")).join("");
}

// ------------------------------------------------------------- histogram
// Bins on a real value axis (ticks at round numbers, no rotated labels). The
// bins closest to failing are the strongest blue, fading as slack grows; bins
// holding violators are red. The worst value is marked and named.
export function histogramOption({ edges, counts, bins, unit = "ns", what = "paths" }) {
  counts = (counts || []).map((c) => (finite(c) ? num(c) : 0));
  if (!counts.length) return null;
  if (!edges || edges.length !== counts.length + 1) {
    // Older payloads only carry each bin's start: rebuild the edges.
    const lo = (bins || []).map(num);
    if (lo.length !== counts.length || !lo.every(Number.isFinite)) return null;
    const w = lo.length > 1 ? lo[1] - lo[0] : 1;
    edges = [...lo, lo[lo.length - 1] + w];
  }
  edges = edges.map(num);
  const k = chartInk();
  const theme = chartTheme();
  const n = counts.length;
  const xMin = edges[0], xMax = edges[n];
  const strongest = k.accent, faint = mix(k.accent, k.surface, 0.62);
  const colorAt = (i) => (edges[i] < 0 ? k.fail : mix(strongest, faint, n > 1 ? i / (n - 1) : 0));
  const data = counts.map((c, i) => [edges[i], edges[i + 1], c, i]);
  const range = (i) => fmtValue(edges[i]) + " to " + fmtValue(edges[i + 1], unit);
  // The worst value is already named above the chart; the one line drawn here
  // is zero slack, when violators exist.
  const marks = xMin < 0 && xMax > 0
    ? [{ xAxis: 0, lineStyle: { color: k.fail }, label: { formatter: "0 " + unit + " · fails to the left", position: "insideEndTop" } }]
    : [];
  return {
    ...theme,
    animationDuration: 300,
    grid: { left: 8, right: 18, top: 30, bottom: 30, containLabel: true },
    tooltip: {
      ...theme.tooltip, trigger: "item",
      formatter: (p) => "<div style='font-size:11.5px;opacity:.75'>" + range(p.value[3]) + "</div>" +
        "<b style='font-size:14px'>" + p.value[2].toLocaleString("en-US") + "</b> " + what,
    },
    xAxis: {
      type: "value", min: xMin, max: xMax, splitNumber: 6,
      name: "slack (" + unit + ")", nameLocation: "middle", nameGap: 26,
      nameTextStyle: { color: k.text, fontSize: 11 },
      axisLine: { show: true, lineStyle: { color: k.grid } }, axisTick: { show: false },
      axisLabel: { ...theme.valueAxis.axisLabel, formatter: (v) => fmtValue(v), hideOverlap: true, showMaxLabel: false },
      splitLine: { show: false },
    },
    yAxis: {
      ...theme.valueAxis, type: "value", minInterval: 1, splitNumber: 4,
      name: what, nameLocation: "end", nameGap: 12,
      nameTextStyle: { color: k.text, fontSize: 11, align: "left" },
    },
    series: [{
      type: "custom",
      encode: { x: [0, 1], y: 2, tooltip: 2 },
      data,
      renderItem: (params, api) => {
        const c = api.value(2);
        if (!c) return null;
        const a = api.coord([api.value(0), 0]), b = api.coord([api.value(1), c]);
        const w = Math.max(1, b[0] - a[0] - 2);             // 2 px gap between bins
        const h = Math.max(1, a[1] - b[1]);
        const fill = colorAt(api.value(3));
        return {
          type: "rect",
          shape: { x: a[0] + 1, y: b[1], width: w, height: h, r: [Math.min(4, h, w / 2), Math.min(4, h, w / 2), 0, 0] },
          style: { fill },
          emphasis: { style: { fill: mix(fill, "#ffffff", 0.18) } },
        };
      },
      markLine: marks.length ? {
        silent: true, symbol: "none",
        lineStyle: { color: k.body, width: 1, type: "solid", opacity: 0.55 },
        label: { color: k.body, fontSize: 11, fontFamily: k.sans },
        data: marks,
      } : undefined,
    }],
  };
}

// --------------------------------------------------------------- run bars
// One bar per run, runs down the side (long names stay readable), the value at
// each bar's tip. Each run keeps its series colour across every chart on a page.
export function runBarsOption({ labels, values, unit = "", colors }) {
  const vals = (values || []).map((v) => (finite(v) ? num(v) : null));
  if (!vals.some((v) => v !== null)) return null;
  const k = chartInk();
  const theme = chartTheme();
  const pal = colors && colors.length ? colors : chartPalette();
  const hasNeg = vals.some((v) => v !== null && v < 0);
  // Leave room past the longest bar for its value label.
  const lo = Math.min(0, ...vals.filter((v) => v !== null)), hi = Math.max(0, ...vals.filter((v) => v !== null));
  const pad = (hi - lo || Math.abs(hi) || 1) * 0.28;
  return {
    ...theme,
    animationDuration: 300,
    grid: { left: 8, right: 24, top: 6, bottom: 6, containLabel: true },
    tooltip: {
      ...theme.tooltip, trigger: "item",
      formatter: (p) => "<div style='font-size:11.5px;opacity:.75'>" + String(labels[p.dataIndex]).replace(/</g, "&lt;") + "</div>" +
        "<b style='font-size:14px'>" + fmtValue(p.value, unit) + "</b>",
    },
    xAxis: {
      ...theme.valueAxis, type: "value", splitNumber: 3, scale: false,
      min: lo < 0 ? lo - pad : 0, max: hi > 0 ? hi + pad : 0,
      axisLabel: { show: false }, splitLine: { show: hasNeg, lineStyle: { color: k.grid } },
    },
    yAxis: {
      type: "category", data: labels, inverse: true,
      axisLine: { show: !hasNeg, lineStyle: { color: k.grid } }, axisTick: { show: false },
      axisLabel: { color: k.body, fontFamily: k.mono, fontSize: 11.5, width: 150, overflow: "truncate" },
    },
    series: [{
      type: "bar", barMaxWidth: 22, barCategoryGap: "38%",
      // A run with no value keeps its row and says so, instead of an empty gap.
      data: vals.map((v, i) => (v === null
        ? { value: 0, itemStyle: { color: "transparent" }, label: { position: "right", color: k.text, formatter: "not measured" }, tooltip: { show: false } }
        : {
          value: v,
          itemStyle: { color: pal[i % pal.length], borderRadius: v < 0 ? [4, 0, 0, 4] : [0, 4, 4, 0] },
          label: { position: v < 0 ? "left" : "right" },
        })),
      label: { show: true, color: k.strong, fontSize: 12, fontFamily: k.sans, formatter: (p) => fmtValue(p.value, unit) },
      emphasis: { focus: "self" },
    }],
  };
}

// Height that fits n run bars without squeezing them.
export function runBarsHeight(n) {
  return 24 + Math.max(1, n) * 34;
}
