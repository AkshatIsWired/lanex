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
    cssVar("--accent", "#2f6fe0"),
    cssVar("--accent-cyan", "#38d6c8"),
    cssVar("--pass", "#2faa6a"),
    cssVar("--warn", "#c98a14"),
    cssVar("--fail", "#e5484d"),
    cssVar("--info", "#2f6fe0"),
  ];
}

export function chartTheme() {
  const text = cssVar("--text-muted", "#7e8ea7");
  const border = cssVar("--border", "#1f2a3b");
  const surface = cssVar("--surface", "#0e131c");
  const strong = cssVar("--text-strong", "#f2f7ff");
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
