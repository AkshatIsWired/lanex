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
  const bodyHtml =
    "<p>A run is assembled in this order — later wins, and your config file is " +
    "<b>never edited</b>:</p>" +
    "<ol class='fs-order'>" +
    "<li>LibreLane/PDK defaults — anything nothing else sets</li>" +
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
    "<p class='muted'>Everything not listed uses LibreLane's or the PDK's default " +
    "(each Constraints field shows its default).</p>" +
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
    },
  });
}
