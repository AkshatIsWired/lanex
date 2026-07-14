// finalsettings.js — "what will this run actually send to LibreLane?"
//
// One dialog that removes every override-vs-config doubt. The model mirrors
// the server's _assemble_overrides and LibreLane's own precedence, and every
// input comes from the run's REAL sources — never a re-computation:
//   - overrides: collectRunPayload() — the exact object the Run button sends
//   - config lines: /api/provenance?kind=input-map — the file's own bytes
//   - macros: the same endpoint the Macros card reads
// LanEx never resolves pdk::/scl:: scoping (that is LibreLane's job) — scoped
// entries are labelled conditional on the chosen PDK/SCL. resolved.json stays
// the post-run authority and is linked from the dialog.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { provBtnHtml, wireProvBtns } from "./provenance.js";

// Pure + node-testable. Splits/classifies EXACTLY like routes.py
// _assemble_overrides: PDK and STD_CELL_LIBRARY are pulled out of the
// overrides (they are construction-time flow options, -p/-s, and also decide
// which pdk::/scl:: config sections apply); everything else rides -c and
// BEATS the config file. A config var with no override applies as written
// (conditionally, if scoped).
export function buildFinalSettingsModel(payloadOverrides, map) {
  const all = payloadOverrides || {};
  const ov = { ...all };
  const pdk = ov.PDK !== undefined ? String(ov.PDK) : null;
  const scl = ov.STD_CELL_LIBRARY !== undefined ? String(ov.STD_CELL_LIBRARY) : null;
  delete ov.PDK;
  delete ov.STD_CELL_LIBRARY;
  const vars = (map && map.ok !== false && map.vars) || {};
  const sent = Object.keys(ov).sort().map((name) => {
    const c = vars[name];
    return {
      name,
      value: String(ov[name]),
      // The config line this override supersedes — null when the config
      // doesn't set the variable (the override ADDS it for the run).
      conflict: c ? { line: c.line, value: c.value,
                      scoped: !!c.scoped, scope: c.scope || null } : null,
    };
  });
  const fromConfig = Object.keys(vars).sort()
    .filter((name) => !(name in all))
    .map((name) => ({ name, ...vars[name] }));
  return {
    pdk, scl, sent, fromConfig,
    rel: (map && map.rel) || null,
    conflicts: sent.filter((s) => s.conflict).length,
  };
}

// Pure + node-testable. The cumulative directory: ONE row per known variable
// (LibreLane's registry) plus any config/override name outside it, each with
// the value that will take effect pre-run and its source. Sources, strongest
// first: override > config (conditional if scoped) > PDK-provided (value
// known only post-run) > LibreLane default > unset. LanEx states what each
// INPUT carries — it never predicts PDK resolution; resolved.json is the
// post-run truth.
export function buildCumulativeModel(payloadOverrides, map, variables) {
  const all = payloadOverrides || {};
  const vars = (map && map.ok !== false && map.vars) || {};
  const names = new Set(Object.keys(all).concat(Object.keys(vars)));
  const reg = Array.isArray(variables) ? variables : [];
  for (const v of reg) names.add(v.name);
  const regByName = new Map(reg.map((v) => [v.name, v]));
  const rows = [];
  const counts = { override: 0, config: 0, pdk: 0, default: 0, unset: 0 };
  for (const name of [...names].sort()) {
    const r = regByName.get(name);
    let row;
    if (name in all) {
      row = { name, value: String(all[name]),
              source: (name === "PDK" || name === "STD_CELL_LIBRARY") ? "picker" : "override" };
      counts.override += 1;
    } else if (vars[name]) {
      const c = vars[name];
      row = { name, value: c.value, source: "config", line: c.line,
              scoped: !!c.scoped, scope: c.scope || null };
      counts.config += 1;
    } else if (r && r.pdk) {
      // PDK-flagged: the PDK's own files provide the value; a registry default
      // (when one exists) is only the fallback beneath that.
      row = { name, value: (r.default === undefined || r.default === null)
                ? "—" : String(r.default),
              source: "pdk" };
      counts.pdk += 1;
    } else if (r && r.default !== undefined && r.default !== null) {
      row = { name, value: String(r.default), source: "default" };
      counts.default += 1;
    } else {
      row = { name, value: "—", source: "unset" };
      counts.unset += 1;
    }
    rows.push(row);
  }
  return { rows, counts, haveRegistry: reg.length > 0 };
}

// Human wording for a cumulative/resolved source tag — shared by the pre-run
// and post-run tables so the two views never describe the same source
// differently.
export function sourceLabel(row, configRel) {
  switch (row.source) {
    case "override": return "your Setup change (sent as an override — beats the file)";
    case "picker": return "your Setup picker (flow option)";
    case "config": {
      const rel = configRel || "your config";
      return rel + " line " + (row.config_line || row.line) +
        (row.scoped ? " (" + (row.scope || "scoped") + " — applied only if the run's PDK/SCL matches)" : "");
    }
    case "pdk": return "PDK-provided — the PDK's files set this; resolved.json shows the value a run used";
    case "default": return "LibreLane default";
    case "unset": return "not set by anything visible pre-run — required, or resolved by the flow";
    default: return row.source || "";
  }
}

function _sentRows(model) {
  if (!model.sent.length) {
    return "<p class='muted'>None — you changed nothing in Setup, so every value " +
      "comes from your config file or the LibreLane/PDK defaults.</p>";
  }
  const rows = model.sent.map((s) => {
    let vs;
    if (s.conflict) {
      vs = "<span class='fs-conflict'>supersedes " + fmt.escape(model.rel || "config") +
        " line " + s.conflict.line + " (file says: <code>" + fmt.escape(s.conflict.value) +
        "</code>" + (s.conflict.scoped ? ", " + fmt.escape(s.conflict.scope || "scoped") : "") +
        ")</span> " +
        provBtnHtml({ kind: "input", key: s.name },
          "Open the superseded config line — the file itself is never edited");
    } else {
      vs = "<span class='muted'>not in your config — the override adds it for this run only</span>";
    }
    return "<tr><td><code>" + fmt.escape(s.name) + "</code></td><td><b>" +
      fmt.escape(s.value) + "</b></td><td>" + vs + "</td></tr>";
  }).join("");
  return "<table class='cc-table'><thead><tr><th>Variable</th><th>Value sent</th>" +
    "<th>vs your config file</th></tr></thead><tbody>" + rows + "</tbody></table>";
}

function _configRows(model) {
  if (!model.rel) {
    return "<p class='muted'>No config file was found in the design folder — " +
      "a run needs one, so this preview cannot apply.</p>";
  }
  if (!model.fromConfig.length) {
    return "<p class='muted'>Every variable your config sets is overridden above" +
      (model.sent.length ? "" : " (the file sets none)") + ".</p>";
  }
  const rows = model.fromConfig.map((c) => {
    const cond = c.scoped
      ? "<span class='fs-scoped'>only if the run's PDK/SCL matches <code>" +
        fmt.escape(c.scope || "its section") + "</code></span>"
      : "applies as written";
    return "<tr><td><code>" + fmt.escape(c.name) + "</code></td><td><b>" +
      fmt.escape(c.value) + "</b></td><td>line " + c.line + " — " + cond + " " +
      provBtnHtml({ kind: "input", key: c.name },
        "Open " + (model.rel || "the config") + " at this line") + "</td></tr>";
  }).join("");
  return "<table class='cc-table'><thead><tr><th>Variable</th><th>Value in file</th>" +
    "<th>Where / when it applies</th></tr></thead><tbody>" + rows + "</tbody></table>";
}

// Filterable variable table with CSV export. `rows` = [{name, value, ...}];
// `cols` maps a row to its cells (already-escaped HTML). Filtering is plain
// case-insensitive substring on the variable name + source text.
function _settingsTable(host, rows, cols, csvName) {
  const esc = fmt.escape;
  host.innerHTML =
    "<div class='fs-tablebar'><input type='search' class='inp fs-filter' " +
    "placeholder='filter by variable or source…'/> " +
    "<span class='muted fs-count'></span><span class='fv-spacer'></span>" +
    "<button class='btn btn-ghost fs-csv'>Export CSV</button></div>" +
    "<div class='fs-tablewrap'><table class='cc-table'><thead><tr>" +
    cols.headers.map((h) => "<th>" + esc(h) + "</th>").join("") +
    "</tr></thead><tbody></tbody></table></div>";
  const tbody = host.querySelector("tbody");
  const count = host.querySelector(".fs-count");
  const paint = (q) => {
    const needle = (q || "").toLowerCase();
    const vis = needle
      ? rows.filter((r) => (r.name + " " + (r._searchText || "")).toLowerCase().includes(needle))
      : rows;
    tbody.innerHTML = vis.map((r) => "<tr>" + cols.cells(r) + "</tr>").join("");
    count.textContent = vis.length + " / " + rows.length;
    wireProvBtns(tbody);
  };
  paint("");
  host.querySelector(".fs-filter").addEventListener("input", (e) => paint(e.target.value));
  host.querySelector(".fs-csv").addEventListener("click", async () => {
    const { toCsv, downloadCsv } = await import("./csvutil.js");
    downloadCsv(csvName, toCsv([cols.csvHeader].concat(rows.map(cols.csvRow))));
  });
}

// The one dialog. `payload` defaults to the REAL run payload so the preview
// can never drift from what the Run button sends.
export async function openFinalSettings(payload = null) {
  const { customDialog } = await import("./dialog.js");
  if (!payload) {
    const { collectRunPayload } = await import("./setup.js");
    payload = collectRunPayload();
  }
  let map = null;
  try { map = await api.provenance({ kind: "input-map" }); } catch { /* honest below */ }
  let macros = [];
  try {
    const r = await api.customMacros(state.designDir);
    macros = (Array.isArray(r.macros) ? r.macros : []).filter((m) => m.enabled !== false);
  } catch { /* macros card optional */ }
  const model = buildFinalSettingsModel(payload.overrides, map);

  const srcNote = (payload.sources || []).length
    ? "<p class='fs-note'>You picked <b>" + payload.sources.length + "</b> source file" +
      ((payload.sources || []).length === 1 ? "" : "s") + " in the IDE — they are sent as a " +
      "<code>VERILOG_FILES</code> override and replace the config's source list for this run.</p>"
    : "";
  const macroNote = macros.length
    ? "<p class='fs-note'><b>" + macros.length + "</b> custom macro" + (macros.length === 1 ? "" : "s") +
      " ride a second config file (<code>.gui-macros.json</code>) merged after your config; " +
      "custom standard cells configured in their card are folded in the same way server-side.</p>"
    : "";
  const lastTag = (Array.isArray(state.runs) && state.runs[0] && state.runs[0].tag) || null;
  const cumulative = buildCumulativeModel(payload.overrides, map, state.variables);
  const c = cumulative.counts;
  const bodyHtml =
    "<p>A run is assembled in this order — later wins, and your config file is " +
    "<b>never edited</b>:</p>" +
    "<ol class='fs-order'>" +
    "<li>LibreLane's built-in defaults, then values the chosen PDK provides — " +
    "so a config that sets only a few variables is normal: <b>every other variable " +
    "still has a value</b>, from here</li>" +
    "<li>Your config file" + (model.rel ? " (<code>" + fmt.escape(model.rel) + "</code>)" : "") +
    ", including <code>pdk::</code>/<code>scl::</code> sections that match the chosen PDK/SCL</li>" +
    "<li>Your Setup changes, sent as override arguments — these beat the file</li>" +
    "</ol>" +
    "<h4>PDK &amp; standard-cell library</h4>" +
    "<p>" + (model.pdk
      ? "<code>PDK=" + fmt.escape(model.pdk) + "</code>" +
        (model.scl ? " · <code>SCL=" + fmt.escape(model.scl) + "</code>" : "") +
        " — from the Setup pickers, passed as flow options; they also decide which " +
        "scoped config sections apply."
      : "<span class='muted'>No PDK picked yet — the flow will refuse to start without one.</span>") +
    "</p>" +
    "<h4>Your changes — sent as overrides (" + model.sent.length + ")</h4>" + _sentRows(model) +
    "<h4>Set by your config file — no override, so these apply (" + model.fromConfig.length + ")</h4>" +
    _configRows(model) +
    "<h4>Every variable — the cumulative directory</h4>" +
    (cumulative.haveRegistry
      ? "<p class='muted'>" + c.override + " from your changes · " + c.config +
        " from your config · " + c.pdk + " PDK-provided · " + c.default +
        " LibreLane defaults · " + c.unset + " unset/flow-resolved.</p>" +
        "<details class='fs-all'><summary>Show all " + cumulative.rows.length +
        " variables with value + source</summary><div class='fs-alltable'></div></details>"
      : "<p class='muted'>The full variable registry isn't available here " +
        "(LibreLane isn't importable on this machine — container-only setup), so the " +
        "cumulative pre-run table can't be built. After a run, <code>resolved.json</code> " +
        "and the Analytics tab's <b>Final settings used</b> give the complete record.</p>") +
    srcNote + macroNote +
    "<p class='fs-note'>This preview is assembled from the run request itself plus your " +
    "config file's bytes. After a run, <code>resolved.json</code> — LibreLane's own record — " +
    "is the final word on every value the flow used." +
    (lastTag ? " <button class='btn btn-ghost' id='fs-resolved'>Open resolved.json of run '" +
      fmt.escape(lastTag) + "'</button>" : "") + "</p>";

  await customDialog({
    title: "Final settings — what this run will send to LibreLane",
    wide: true,
    bodyHtml,
    onMount: (back) => {
      wireProvBtns(back);
      back.querySelector("#fs-resolved")?.addEventListener("click", async () => {
        const { openProvenance } = await import("./provenance.js");
        openProvenance({ kind: "report", tag: lastTag, path: "resolved.json", needle: "" },
          { title: "resolved.json of run '" + lastTag + "' — every value the flow actually used" });
      });
      // The 400+-row cumulative table renders lazily, on first open.
      const det = back.querySelector(".fs-all");
      det?.addEventListener("toggle", () => {
        const host = det.querySelector(".fs-alltable");
        if (!det.open || !host || host._built) return;
        host._built = true;
        const esc = fmt.escape;
        for (const r of cumulative.rows) r._searchText = sourceLabel(r, model.rel);
        _settingsTable(host, cumulative.rows, {
          headers: ["Variable", "Value (pre-run)", "Source"],
          cells: (r) =>
            "<td><code>" + esc(r.name) + "</code></td><td>" + esc(r.value) + "</td>" +
            "<td>" + esc(sourceLabel(r, model.rel)) +
            (r.source === "config"
              ? " " + provBtnHtml({ kind: "input", key: r.name },
                  "Open " + (model.rel || "the config") + " at this line") : "") + "</td>",
          csvHeader: ["variable", "value_pre_run", "source"],
          csvRow: (r) => [r.name, r.value, sourceLabel(r, model.rel)],
        }, "final-settings-preview.csv");
      });
    },
  });
}

// Post-run counterpart (Analytics: "Final settings used"): EVERY variable the
// run resolved — value verbatim from resolved.json (LibreLane's own record,
// nulls included), source attributed by key origin via kind=resolved-map.
export async function openResolvedSettings(tag) {
  if (!tag) return;
  const { customDialog } = await import("./dialog.js");
  let r;
  try { r = await api.provenance({ kind: "resolved-map", tag }); }
  catch (ex) {
    const { toast } = await import("./toast.js");
    toast.show("Could not load the run's resolved settings: " + (ex.message || ex), "error");
    return;
  }
  if (!r || r.ok === false) {
    const { toast } = await import("./toast.js");
    toast.show((r && r.reason) || "No resolved settings for this run.", "warn", 6000);
    return;
  }
  const note = r.note ? "<p class='fs-note'>" + fmt.escape(r.note) + "</p>" : "";
  await customDialog({
    title: "Final settings used by run '" + fmt.escape(tag) + "' (" + r.rows.length + " variables)",
    wide: true,
    bodyHtml:
      "<p>Values are <b>resolved.json verbatim</b> — LibreLane's own record of every " +
      "variable this run used, including empty ones. The source column says which input " +
      "carried each variable in (attribution by origin; LibreLane may expand what it " +
      "reads — <code>dir::</code> globs, expressions — so a value can differ textually " +
      "from the config line that set it).</p>" + note +
      "<div class='fs-resolvedtable'></div>",
    onMount: (back) => {
      const host = back.querySelector(".fs-resolvedtable");
      const esc = fmt.escape;
      for (const row of r.rows) row._searchText = sourceLabel(row, r.config_rel);
      _settingsTable(host, r.rows, {
        headers: ["Variable", "Value used", "Source"],
        cells: (row) =>
          "<td><code>" + esc(row.name) + "</code></td><td>" + esc(row.value) +
          (row.line ? " " + provBtnHtml({ kind: "var", key: row.name, tag },
            "Open resolved.json at this variable's line — the flow's own record") : "") +
          "</td><td>" + esc(sourceLabel(row, r.config_rel)) +
          (row.source === "config"
            ? " " + provBtnHtml({ kind: "input", key: row.name },
                "Open " + (r.config_rel || "the config") + " at the line that set it") : "") +
          "</td>",
        csvHeader: ["variable", "value_used", "source"],
        csvRow: (row) => [row.name, row.value, sourceLabel(row, r.config_rel)],
      }, "final-settings-" + tag + ".csv");
    },
  });
}
