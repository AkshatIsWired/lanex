// icons.js — one inline-SVG line icon set (Feather/Lucide-style, MIT path data).
// Replaces emoji/unicode glyphs so icons render identically on every OS, inherit
// text color (theme-correct), and keep vertical rhythm. Zero dependency.
//
// icon(name) -> an <svg> string; iconEl(name) -> a DOM node.

const P = {
  folder: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z",
  flow: "M12 2l9 5v10l-9 5-9-5V7z",                 // hexagon (pipeline)
  clock: "M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
  image: "M3 5h18v14H3zM3 15l5-5 4 4 3-3 6 6",
  tools: "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-3 3-2-2z",
  chart: "M4 20V10M10 20V4M16 20v-7M20 20H3",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
  download: "M12 3v12M7 11l5 4 5-4M5 21h14",
  refresh: "M21 12a9 9 0 1 1-3-6.7M21 4v4h-4",
  arrowUp: "M12 20V5M6 11l6-6 6 6",
  play: "M7 4l13 8-13 8z",
  stop: "M6 6h12v12H6z",
  step: "M8 5v14M16 5l-6 7 6 7",
  box: "M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10",
  cpu: "M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3M5 5h14v14H5zM9 9h6v6H9z",
  check: "M5 13l4 4L19 7",
  x: "M6 6l12 12M18 6L6 18",
  alert: "M12 3l10 18H2zM12 10v5M12 18h.01",
  chevron: "M9 6l6 6-6 6",
  chevronDown: "M6 9l6 6 6-6",
  command: "M9 9a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v6a3 3 0 1 0 3 3H6a3 3 0 1 0 3-3z",
  sun: "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 1v2M12 21v2M4 4l1.5 1.5M18.5 18.5L20 20M1 12h2M21 12h2M4 20l1.5-1.5M18.5 5.5L20 4",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  help: "M9.1 9a3 3 0 1 1 4 2.8c-.9.4-1.6 1-1.6 2.2M12 17h.01M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z",
  dot: "M12 12m-3 0a3 3 0 1 0 6 0 3 3 0 1 0-6 0",
  code: "M8 6l-6 6 6 6M16 6l6 6-6 6",
  layers: "M12 2l10 5-10 5L2 7zM2 12l10 5 10-5M2 17l10 5 10-5",
  cube: "M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10",
  grid: "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
  plug: "M9 2v6M15 2v6M7 8h10v3a5 5 0 0 1-10 0zM12 16v6",
  wave: "M2 12h3l2-7 4 14 3-9 2 2h6",
  diff: "M12 3v18M5 8h14M5 16h14",
  beaker: "M9 2h6M10 2v6l-5 11a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-11V2",
  file: "M6 2h8l4 4v16H6zM14 2v4h4",
  plus: "M12 5v14M5 12h14",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7zM12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  ban: "M5.6 5.6l12.8 12.8M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z",
  book: "M5 4a2 2 0 0 1 2-2h13v18H7a2 2 0 0 0-2 2zM9 2v18",
  star: "M12 3l2.6 5.9 6.4.6-4.8 4.3 1.4 6.3L12 17l-5.6 3.4 1.4-6.3L3 9.5l6.4-.6z",
  database: "M12 3c4.4 0 8 1.3 8 3s-3.6 3-8 3-8-1.3-8-3 3.6-3 8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  folderOpen: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2H3zM3 9h18l-2.2 9H5z",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6",
};

export function icon(name, { size = 18, stroke = 1.5 } = {}) {
  const d = P[name];
  if (!d) return "";
  return (
    "<svg class='ic ic-" + name + "' viewBox='0 0 24 24' width='" + size + "' height='" + size +
    "' fill='none' stroke='currentColor' stroke-width='" + stroke +
    "' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>" +
    "<path d='" + d + "'/></svg>"
  );
}

export function iconEl(name, opts) {
  const span = document.createElement("span");
  span.className = "ic-wrap";
  span.innerHTML = icon(name, opts);
  return span.firstChild;
}

export function hasIcon(name) {
  return Object.prototype.hasOwnProperty.call(P, name);
}

export const ICON_NAMES = Object.keys(P);
