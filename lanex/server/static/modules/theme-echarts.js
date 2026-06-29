// theme-echarts.js — derive an ECharts theme from the CSS design tokens at call
// time, so charts match the brand AND switch with the dark/light theme. Replaces
// the hardcoded hex palettes that were scattered across the chart modules.

function cssVar(name, fallback) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  } catch (_e) {
    return fallback;
  }
}

export function chartPalette() {
  return [
    cssVar("--accent", "#8b5cf6"),
    cssVar("--accent-cyan", "#39c5cf"),
    cssVar("--pass", "#3fb950"),
    cssVar("--warn", "#d29922"),
    cssVar("--fail", "#f85149"),
    cssVar("--info", "#58a6ff"),
  ];
}

export function chartTheme() {
  const text = cssVar("--text-muted", "#8b949e");
  const border = cssVar("--border", "#30363d");
  const surface = cssVar("--surface", "#161b22");
  const strong = cssVar("--text-strong", "#e6edf3");
  return {
    color: chartPalette(),
    backgroundColor: "transparent",
    textStyle: { color: text, fontFamily: cssVar("--sans", "system-ui, sans-serif") },
    title: { textStyle: { color: strong } },
    legend: { textStyle: { color: text } },
    tooltip: {
      backgroundColor: surface,
      borderColor: border,
      textStyle: { color: strong },
    },
    categoryAxis: {
      axisLine: { lineStyle: { color: border } },
      axisLabel: { color: text },
      splitLine: { show: false, lineStyle: { color: border } },
    },
    valueAxis: {
      axisLine: { lineStyle: { color: border } },
      axisLabel: { color: text },
      splitLine: { lineStyle: { color: border } },
    },
  };
}

// Notify charts to re-theme when the theme toggles. theme.js dispatches
// `g:theme_changed`; chart modules listen and re-init with chartTheme().
export function onThemeChange(cb) {
  document.addEventListener("g:theme_changed", cb);
}
