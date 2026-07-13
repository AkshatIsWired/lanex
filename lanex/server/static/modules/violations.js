// violations.js — DRC/LVS/antenna/STA report picker + viewer.
//
// Detects every signoff report in the selected run and lets the user pick one
// (a radio "checkmark") to parse + display: DRC → categorized violation boxes,
// LVS → unmatched counts, everything else → the raw report text. The picker and
// the parsed output live in separate containers so selecting a report REPLACES
// the previous output instead of stacking cards.

import { api, fmt } from "./api.js";
import { icon } from "./icons.js";
import { provBtnHtml, wireProvBtns } from "./provenance.js";

let _reports = [];
let _selectedPath = null;
let _runTag = null;

export async function populateReportsList(designDir, runTag) {
  const root = document.getElementById("violations-list");
  if (!root) return;
  _runTag = runTag || null;
  if (!designDir || !runTag) {
    _reports = [];
    paintPicker();
    return;
  }
  try {
    const out = await api.runReports(designDir, runTag);
    _reports = (out && out.reports) || [];
  } catch (_e) {
    _reports = [];
  }
  paintPicker();
}

function paintPicker() {
  const root = document.getElementById("violations-list");
  if (!root) return;
  if (!_reports.length) {
    root.innerHTML =
      "<div class='empty'><span class='ico'>" + icon('ban',{size:40}) + "</span><h3>No DRC/LVS reports detected in this run</h3>" +
      "<p>Run the flow at least through the signoff stage (DRC/LVS/antenna/STA) to see them here. " +
      "You can also paste a report path above and click Parse.</p></div>";
    return;
  }
  // Group by kind for a tidy list.
  const byKind = {};
  for (const r of _reports) (byKind[r.kind] = byKind[r.kind] || []).push(r);
  let html = "<div class='report-picker'>";
  for (const [kind, arr] of Object.entries(byKind).sort()) {
    html += "<div class='report-kind-head'>" + fmt.escape(kind) + " (" + arr.length + ")</div>";
    for (const r of arr) {
      const checked = _selectedPath === r.path ? " checked" : "";
      html += "<label class='report-pick-row'>" +
        "<input type='radio' name='vio-report' value='" + fmt.escape(r.path) + "'" + checked + "/>" +
        "<span class='report-pick-name'>" + fmt.escape(r.step) + " · " + fmt.escape(r.name) + "</span>" +
        "<span class='report-pick-ext'>" + fmt.escape((r.ext || "").replace(".", "").toUpperCase()) + "</span>" +
        "</label>";
    }
  }
  html += "</div><div id='violations-output' class='violations-output'></div>";
  root.innerHTML = html;
  root.querySelectorAll("input[name='vio-report']").forEach((rb) =>
    rb.addEventListener("change", () => {
      const r = _reports.find((x) => x.path === rb.value);
      if (r) onSelectReport(r);
    }));
  // Re-render the previously-selected report (e.g. after a refresh).
  if (_selectedPath) {
    const r = _reports.find((x) => x.path === _selectedPath);
    if (r) onSelectReport(r);
  }
}

async function onSelectReport(r) {
  _selectedPath = r.path;
  const out = document.getElementById("violations-output");
  if (out) out.innerHTML = "<p class='muted'>Parsing " + fmt.escape(r.name) + "…</p>";
  const isDrc = r.kind === "DRC" || (r.name || "").toLowerCase().endsWith(".drc");
  const isLvs = r.kind === "LVS" || (r.name || "").toLowerCase().endsWith(".lvs");
  try {
    if (isDrc) {
      const resp = await api.reportsDrc(r.path);
      renderDrc(r, resp);
    } else if (isLvs) {
      const resp = await api.reportsLvs(r.path);
      renderLvs(r, resp);
    } else {
      const resp = await api.readText(r.path);   // {ok,text,...} after _fetch unwrap
      renderText(r, resp && resp.text !== undefined ? resp.text : (resp && resp.error) || "(empty)");
    }
  } catch (ex) {
    if (out) out.innerHTML = "<p class='pill pill-fail'>Could not parse: " + fmt.escape(ex.message || ex) + "</p>";
  }
  wireProvBtns(document.getElementById("violations-output"));
}

function header(r, extra, needle) {
  // "raw" opens the report exactly as the tool wrote it (needle = the verdict
  // line to highlight, when the parsed view is judging one).
  const prov = (r.rel && _runTag)
    ? provBtnHtml({ kind: "report", tag: _runTag, path: r.rel, needle: needle || "" },
        "Open the raw report as the tool wrote it" +
        (needle ? " — the line the verdict was read from is highlighted" : ""))
    : "";
  return "<div class='report-head'><span class='chip rk'>" + fmt.escape(r.kind) + "</span>" +
    "<strong>" + fmt.escape(r.name) + "</strong> <span class='muted'>" + fmt.escape(r.step) + "</span>" +
    (extra ? " <span class='muted'>· " + fmt.escape(extra) + "</span>" : "") + prov + "</div>";
}

function renderDrc(r, resp) {
  const out = document.getElementById("violations-output");
  if (!out) return;
  const violations = (resp && resp.violations) || [];
  const status = (resp && resp.status) || "parsed"; // older servers: no field
  // Three states, never two: a missing/unreadable report must NOT look like a
  // clean one — "0 violations" is only green when the parser really read it.
  if (status === "missing") {
    out.innerHTML = header(r) +
      "<p><span class='pill pill-fail'>Report not found</span> " +
      fmt.escape((resp && resp.error) || "The report file does not exist (was the run deleted or moved?).") + "</p>";
    return;
  }
  if (status === "error") {
    out.innerHTML = header(r) +
      "<p><span class='pill pill-warn'>Report unreadable</span> " +
      fmt.escape((resp && resp.error) || "Could not parse this DRC report — open the raw file to inspect it.") + "</p>";
    return;
  }
  if (!violations.length) {
    out.innerHTML = header(r) +
      "<div class='empty'><span class='ico'>" + icon('check',{size:40}) + "</span><h3>No violations</h3><p>Clean DRC report (parsed).</p></div>";
    return;
  }
  const cards = violations.slice(0, 50).map((v) => {
    const count = (v.boxes || []).length;
    return "<div class='adv-card warn'>" +
      "<div class='title'>" + fmt.escape(v.category || "DRC") + "</div>" +
      "<div class='what'>" + fmt.escape(v.description || "") + "</div>" +
      "<div class='why'>" + count + " box" + (count === 1 ? "" : "es") +
      " on layer <b>" + fmt.escape(v.layer || "?") + "</b></div>" +
      ((v.boxes || []).length
        ? "<pre class='code'>" + fmt.escape((v.boxes || []).slice(0, 8)
            .map((b) => "(" + b.llx + ", " + b.lly + ") - (" + b.urx + ", " + b.ury + ")").join("\n")) + "</pre>"
        : "") +
      "</div>";
  }).join("");
  out.innerHTML = header(r, violations.length + " violation" + (violations.length === 1 ? "" : "s")) +
    cards + (violations.length > 50 ? "<p class='muted'>… and " + (violations.length - 50) + " more.</p>" : "");
}

function renderLvs(r, resp) {
  const out = document.getElementById("violations-output");
  if (!out) return;
  const status = (resp && resp.status) || "unknown";
  const verdict = (resp && resp.verdict) || "";
  let head;
  if (status === "clean") {
    head = "<div class='empty'><span class='ico'>" + icon('check',{size:40}) + "</span>" +
      "<h3>LVS clean</h3><p>" + fmt.escape(verdict || "Circuits match uniquely.") + "</p></div>";
  } else if (status === "mismatch") {
    head = "<p><span class='pill pill-fail'>LVS mismatch</span> " +
      fmt.escape(verdict || "Netgen reports the netlists do not match.") + "</p>";
  } else {
    head = "<p><span class='pill pill-warn'>LVS verdict unreadable</span> " +
      "No Netgen final-verdict line found in this report — open the raw report to inspect it.</p>";
  }
  const counts = (resp && resp.counts) || {};
  const keys = Object.keys(counts);
  const body = keys.length
    ? "<table class='cmp-table'><tbody>" + keys.map((k) =>
        "<tr><td>" + fmt.escape(k.replace(/_/g, " ")) + "</td><td class='cmp-num'>" +
        fmt.escape(String(counts[k])) + "</td></tr>").join("") + "</tbody></table>"
    : "";
  // Netgen's verdict line ("Final result: ...") is what the clean/mismatch
  // pill was judged on — highlight exactly it in the raw view.
  out.innerHTML = header(r, resp && resp.raw_chars ? resp.raw_chars + " chars" : "", "Final result") + head + body;
}

function renderText(r, text) {
  const out = document.getElementById("violations-output");
  if (!out) return;
  const t = String(text == null ? "" : text);
  out.innerHTML = header(r) +
    (t.trim()
      ? "<pre class='code report-raw'>" + fmt.escape(t.slice(0, 20000)) +
        (t.length > 20000 ? "\n… (truncated — download the full file)" : "") + "</pre>"
      : "<p class='muted'>This report file is empty.</p>");
}

// Wire the manual "path" input (parse an arbitrary report by path).
export function setupViolations() {
  document.getElementById("btn-load-violations")?.addEventListener("click", () => {
    const v = (document.getElementById("violations-input").value || "").trim();
    if (!v) return;
    const name = v.split(/[\\/]/).pop();
    const ext = (name.match(/\.[^.]+$/) || [""])[0].toLowerCase();
    const kind = ext === ".drc" ? "DRC" : ext === ".lvs" ? "LVS" : "report";
    if (!_reports.length) { _reports = []; paintPicker(); }
    onSelectReport({ name, step: "manual", kind, path: v, ext });
  });
}

// Back-compat export (app.js imports it); parse a DRC report by raw path.
export async function loadDrcFor(path) {
  if (!path) return;
  const name = String(path).split(/[\\/]/).pop();
  onSelectReport({ name, step: "manual", kind: "DRC", path, ext: ".drc" });
}
