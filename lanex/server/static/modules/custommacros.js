// custommacros.js — advanced: insert a pre-hardened hard macro (an SRAM, a PLL,
// an analog IP, a separately hardened sub-design) into a run. Files are uploaded
// (base64) to the design's macros/<name>/ dir; the block is wired in per-run via
// the MACROS config variable (GDS+LEF required; LIB/netlist/SPEF/SPICE optional;
// per-instance fixed placement optional). Your config.json is never modified.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { confirmDialog } from "./dialog.js";

// view kind -> { label, accept, required }
const VIEWS = [
  { kind: "gds",   label: "GDS (layout)",                 accept: ".gds,.gz",        required: true },
  { kind: "lef",   label: "LEF (abstract: pins/size)",    accept: ".lef",            required: true },
  { kind: "lib",   label: "Liberty .lib (timing)",        accept: ".lib",            required: false },
  { kind: "nl",    label: "Netlist (.v gate-level)",      accept: ".v,.sv",          required: false },
  { kind: "spef",  label: "SPEF (parasitics)",            accept: ".spef",           required: false },
  { kind: "spice", label: "SPICE (LVS)",                  accept: ".spice,.sp,.cir", required: false },
];

let _orientations = ["N", "S", "E", "W", "FN", "FS", "FE", "FW"];

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(new Error("read failed"));
    r.onload = () => {
      const s = String(r.result || "");
      const comma = s.indexOf(",");
      resolve(comma >= 0 ? s.slice(comma + 1) : s);
    };
    r.readAsDataURL(file);
  });
}

export async function renderCustomMacros() {
  const root = document.getElementById("custom-macros-body");
  if (!root) return;
  document.getElementById("btn-custom-macro-help")?.addEventListener("click", showMacroHelp, { once: true });
  if (!state.designDir) {
    root.innerHTML = "<p class='muted'>Load a design folder first (Setup tab) — custom macros are stored per design.</p>";
    return;
  }
  let macros = [];
  try {
    const r = await api.customMacros(state.designDir);
    macros = r.macros || [];
    if (Array.isArray(r.orientations) && r.orientations.length) _orientations = r.orientations;
  } catch (_e) {}

  const list = macros.length
    ? "<table class='cc-table'><thead><tr><th>Macro module</th><th>Views</th><th>Instances</th><th>Use</th><th></th></tr></thead><tbody>" +
      macros.map((m) =>
        "<tr><td class='mono'>" + fmt.escape(m.name) + "</td>" +
        "<td>" + Object.keys(m.views || {}).map((k) => "<span class='cc-chip'>" + fmt.escape(k) + "</span>").join(" ") + "</td>" +
        "<td class='mono'>" + fmt.escape(instSummary(m.instances)) + "</td>" +
        "<td><input type='checkbox' class='mc-enable' data-name='" + fmt.escape(m.name) + "'" + (m.enabled ? " checked" : "") + "></td>" +
        "<td><button class='btn btn-ghost mc-remove' data-name='" + fmt.escape(m.name) + "'>Remove</button></td></tr>").join("") +
      "</tbody></table>"
    : "<p class='muted'>No custom macros yet. Add one below.</p>";

  const form =
    "<details class='cc-add'><summary>+ Add a custom macro</summary>" +
    "<div class='cc-form'>" +
    "<label>Macro module name <input type='text' id='mc-name' placeholder='e.g. sky130_sram_1kbyte' autocomplete='off'>" +
    "<span class='hint'>The Verilog <em>module</em> name of the block, exactly as instantiated in your RTL.</span></label>" +
    "<div class='mc-instances'><div class='mc-inst-head'>Instances <span class='hint'>where each instance of the macro is placed. " +
    "Leave X/Y blank for automatic placement. Add the instance name(s) used in your RTL.</span></div>" +
    "<div id='mc-inst-rows'></div>" +
    "<button class='btn btn-ghost' id='mc-add-inst' type='button'>+ Add instance</button></div>" +
    "<div class='cc-views'>" +
    VIEWS.map((v) =>
      "<label class='cc-view'><span>" + fmt.escape(v.label) + (v.required ? " *" : "") + "</span>" +
      "<input type='file' class='mc-file' data-kind='" + v.kind + "' accept='" + v.accept + "'></label>").join("") +
    "</div>" +
    "<div class='cc-form-actions'><button class='btn btn-primary' id='mc-save'>Save custom macro</button>" +
    "<span class='hint'>GDS + LEF are required. Add LIB so synthesis can black-box it and STA can time through it; " +
    "netlist/SPEF for hierarchical timing; SPICE for LVS.</span></div>" +
    "<div id='mc-form-error' class='ac-error' hidden></div>" +
    "</div></details>";

  root.innerHTML = list + form;

  root.querySelectorAll(".mc-remove").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!(await confirmDialog({ title: "Remove custom macro", danger: true, confirmText: "Remove",
        body: "Remove custom macro '" + b.dataset.name + "' and its files?" }))) return;
      try { await api.customMacroRemove(b.dataset.name, state.designDir); renderCustomMacros(); }
      catch (ex) { toast.show("Remove failed: " + ex.message, "error"); }
    }));
  root.querySelectorAll(".mc-enable").forEach((cb) =>
    cb.addEventListener("change", async () => {
      try { await api.customMacroEnable(cb.dataset.name, cb.checked, state.designDir); }
      catch (ex) { toast.show("Update failed: " + ex.message, "error"); cb.checked = !cb.checked; }
    }));
  root.querySelector("#mc-add-inst")?.addEventListener("click", () => addInstanceRow());
  addInstanceRow();   // start with one empty instance row
  root.querySelector("#mc-save")?.addEventListener("click", () => saveMacro(root));
}

function instSummary(instances) {
  if (!instances || !instances.length) return "auto-place";
  return instances.map((i) =>
    i.name + (i.location ? " @(" + i.location.join(",") + ")" : " (auto)")).join(", ");
}

function addInstanceRow(values) {
  const rows = document.getElementById("mc-inst-rows");
  if (!rows) return;
  const v = values || {};
  const row = document.createElement("div");
  row.className = "mc-inst-row";
  row.innerHTML =
    "<input type='text' class='mc-inst-name' placeholder='instance name (e.g. u_sram)' autocomplete='off' value='" + fmt.escape(v.name || "") + "'>" +
    "<input type='text' class='mc-inst-x' placeholder='X µm' autocomplete='off' value='" + fmt.escape(v.x || "") + "'>" +
    "<input type='text' class='mc-inst-y' placeholder='Y µm' autocomplete='off' value='" + fmt.escape(v.y || "") + "'>" +
    "<select class='mc-inst-orient'>" +
    _orientations.map((o) => "<option" + (o === (v.orientation || "N") ? " selected" : "") + ">" + o + "</option>").join("") +
    "</select>" +
    "<button class='btn btn-ghost mc-inst-del' type='button' title='Remove this instance'>✕</button>";
  row.querySelector(".mc-inst-del").addEventListener("click", () => row.remove());
  rows.appendChild(row);
}

function collectInstances(root) {
  const out = [];
  for (const row of root.querySelectorAll(".mc-inst-row")) {
    const name = (row.querySelector(".mc-inst-name").value || "").trim();
    if (!name) continue;   // skip blank rows
    const x = (row.querySelector(".mc-inst-x").value || "").trim();
    const y = (row.querySelector(".mc-inst-y").value || "").trim();
    const orientation = row.querySelector(".mc-inst-orient").value || "N";
    let location = null;
    if (x !== "" || y !== "") location = [x, y];   // server validates the pair
    out.push({ name, location, orientation });
  }
  return out;
}

async function saveMacro(root) {
  const errEl = root.querySelector("#mc-form-error");
  errEl.hidden = true;
  const name = (root.querySelector("#mc-name")?.value || "").trim();
  if (!name) { errEl.hidden = false; errEl.textContent = "Give the macro its module name."; return; }
  const instances = collectInstances(root);
  const views = {};
  for (const inp of root.querySelectorAll(".mc-file")) {
    const f = inp.files && inp.files[0];
    if (!f) continue;
    try {
      views[inp.dataset.kind] = { filename: f.name, content_b64: await readAsBase64(f) };
    } catch (_e) {
      errEl.hidden = false; errEl.textContent = "Could not read " + inp.dataset.kind + " file."; return;
    }
  }
  if (!views.gds || !views.lef) {
    errEl.hidden = false; errEl.textContent = "Both a GDS and a LEF view are required for a macro."; return;
  }
  const btn = root.querySelector("#mc-save");
  btn.disabled = true; btn.textContent = "Saving…";
  try {
    await api.customMacroSave({ design_dir: state.designDir, name, instances, views, enabled: true });
    toast.show("Saved custom macro '" + name + "'. It'll be inserted on your next run.", "success");
    renderCustomMacros();
  } catch (ex) {
    errEl.hidden = false; errEl.textContent = ex.message;
    btn.disabled = false; btn.textContent = "Save custom macro";
  }
}

function showMacroHelp() {
  document.getElementById("btn-custom-macro-help")?.addEventListener("click", showMacroHelp, { once: true });
  const backdrop = document.createElement("div");
  backdrop.className = "smodal-backdrop";
  backdrop.innerHTML =
    "<div class='smodal cc-help-modal'>" +
    "<div class='smodal-head'><span class='smodal-title'>Custom macros — how it works</span>" +
    "<span class='smodal-spacer'></span><button class='btn btn-ghost' id='mc-help-close'>✕</button></div>" +
    "<div class='smodal-log cc-help'>" + HELP_HTML + "</div></div>";
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelector("#mc-help-close")?.addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
  });
}

const HELP_HTML = `
<h3>Cell vs. macro</h3>
<p>A <strong>custom cell</strong> is a leaf gate that lives in the standard-cell rows (fixed row height,
on the placement grid). A <strong>macro</strong> is a <em>pre-hardened block</em> — an SRAM, a register file,
a PLL, an analog IP, or a sub-design you hardened separately — that drops into the floorplan as a fixed
black box and is routed around. They use different LibreLane variables, so they live in separate panels here.</p>

<h3>The views a macro needs</h3>
<ul>
  <li><strong>GDS</strong> — the real polygons, merged into the final chip layout. <em>Required.</em></li>
  <li><strong>LEF</strong> — the abstract: pin locations, obstructions, the block outline. Needed by placement &amp; routing. <em>Required.</em></li>
  <li><strong>Liberty <code>.lib</code></strong> — timing. Lets synthesis black-box the macro and lets STA time
      through it. Without it the block may be black-boxed with no timing.</li>
  <li><strong>Netlist (<code>.v</code>)</strong> — a gate-level netlist of the macro, for power and hierarchical STA.</li>
  <li><strong>SPEF</strong> — extracted parasitics, for SPEF-based hierarchical timing.</li>
  <li><strong>SPICE</strong> — device netlist, for LVS signoff.</li>
</ul>
<p>LibreLane carries all of this in one variable — <code>MACROS</code> — a dictionary keyed by the macro's
<em>module name</em>. See {py:class}<code>librelane.config.Macro</code>.</p>

<h3>Instances &amp; placement</h3>
<p>List the <strong>instance name(s)</strong> exactly as they appear in your RTL (e.g. <code>u_sram</code> for
<code>my_sram u_sram (...)</code>). For each, optionally set a fixed <strong>X/Y</strong> (in microns, the macro's
origin) and an <strong>orientation</strong> (<code>N</code>, <code>S</code>, <code>FN</code>, …). Leave X/Y blank to let
the macro placer position it automatically.</p>

<h3>Step by step</h3>
<ol>
  <li>Click <strong>+ Add a custom macro</strong>.</li>
  <li>Enter the macro's <strong>module name</strong> (must match the module you instantiate).</li>
  <li>Add one <strong>instance</strong> row per instantiation; set X/Y + orientation, or leave blank for auto-place.</li>
  <li>Upload at least the <strong>GDS</strong> and <strong>LEF</strong>. Add <strong>LIB</strong> so the tools can time it.</li>
  <li>Save. Toggle <strong>Use</strong> per run. Start a run from Setup — the macro is inserted automatically.</li>
</ol>

<h3>Important notes</h3>
<ul>
  <li>This is <strong>per-run, GUI-managed</strong>. Your <code>config.json</code> is never modified — the macro is added
      through a small <code>.gui-macros.json</code> overlay config the GUI hands to the flow. Files live in
      <code>macros/&lt;name&gt;/</code> in your design folder.</li>
  <li>The macro's <strong>LEF must agree with its GDS</strong> (same pins/outline) or routing/LVS will fail.</li>
  <li>Remember to also <strong>instantiate</strong> the macro module in your RTL — this feature provides the views &amp;
      placement; it does not add the instance to your netlist.</li>
  <li>Power: most macros need their power pins tied into the grid. If your macro has its own power pins you may also
      need <code>PDN_MACRO_CONNECTIONS</code> in your config; this panel wires the views and placement.</li>
</ul>`;
