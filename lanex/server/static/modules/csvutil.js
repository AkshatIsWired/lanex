// csvutil.js — tiny CSV helpers shared by the export buttons (Analytics, Compare,
// DSE). Pure, zero dependency, RFC-4180 quoting.

export function csvCell(v) {
  const s = (v === null || v === undefined) ? "" : String(v);
  return /[",\n\r]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}

// rows: array of arrays. Returns a CSV string.
export function toCsv(rows) {
  return (rows || []).map((r) => (r || []).map(csvCell).join(",")).join("\n");
}

// Trigger a browser download of `text` as `filename`.
export function downloadCsv(filename, text) {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
