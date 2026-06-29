// customcells.js — advanced: inject a custom standard cell and swap it in for
// one or more library cells, for runs started from the GUI. Files are uploaded
// (base64) to the design's custom_cells/ dir; the swap is applied per-run via
// EXTRA_LEFS/LIBS/GDS/SPICE_MODELS/VERILOG_MODELS + EXTRA_EXCLUDED_CELLS.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { confirmDialog } from "./dialog.js";

// view kind -> { label, accept, required }
const VIEWS = [
  { kind: "lef", label: "LEF (footprint/abstract)", accept: ".lef", required: true },
  { kind: "lib", label: "Liberty .lib (timing)", accept: ".lib", required: false },
  { kind: "gds", label: "GDS (final layout)", accept: ".gds,.gz", required: false },
  { kind: "spice", label: "SPICE model (LVS)", accept: ".spice,.sp,.cir", required: false },
  { kind: "verilog", label: "Verilog model (gate sim)", accept: ".v,.sv", required: false },
  { kind: "cdl", label: "CDL netlist (LVS)", accept: ".cdl,.spice", required: false },
];

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

export async function renderCustomCells() {
  const root = document.getElementById("custom-cells-body");
  if (!root) return;
  document.getElementById("btn-custom-cell-help")?.addEventListener("click", showCustomCellHelp, { once: true });
  if (!state.designDir) {
    root.innerHTML = "<p class='muted'>Load a design folder first (Setup tab) — custom cells are stored per design.</p>";
    return;
  }
  let cells = [];
  try { cells = (await api.customCells(state.designDir)).cells || []; } catch (_e) {}

  const list = cells.length
    ? "<table class='cc-table'><thead><tr><th>Cell</th><th>Views</th><th>Swaps out</th><th>Use</th><th></th></tr></thead><tbody>" +
      cells.map((c) =>
        "<tr><td class='mono'>" + fmt.escape(c.name) + "</td>" +
        "<td>" + Object.keys(c.views || {}).map((k) => "<span class='cc-chip'>" + fmt.escape(k) + "</span>").join(" ") + "</td>" +
        "<td class='mono'>" + fmt.escape((c.swap_out || []).join(", ") || "—") + "</td>" +
        "<td><input type='checkbox' class='cc-enable' data-name='" + fmt.escape(c.name) + "'" + (c.enabled ? " checked" : "") + "></td>" +
        "<td><button class='btn btn-ghost cc-remove' data-name='" + fmt.escape(c.name) + "'>Remove</button></td></tr>").join("") +
      "</tbody></table>"
    : "<p class='muted'>No custom cells yet. Add one below.</p>";

  const form =
    "<details class='cc-add'><summary>+ Add a custom cell</summary>" +
    "<div class='cc-form'>" +
    "<label>Cell name <input type='text' id='cc-name' placeholder='e.g. my_fast_nand2' autocomplete='off'></label>" +
    "<label>Swap out (standard cells to exclude, comma-separated) " +
    "<input type='text' id='cc-swap' placeholder='e.g. sky130_fd_sc_hd__nand2_1, sky130_fd_sc_hd__nand2_2' autocomplete='off'></label>" +
    "<div class='cc-views'>" +
    VIEWS.map((v) =>
      "<label class='cc-view'><span>" + fmt.escape(v.label) + (v.required ? " *" : "") + "</span>" +
      "<input type='file' class='cc-file' data-kind='" + v.kind + "' accept='" + v.accept + "'></label>").join("") +
    "</div>" +
    "<div class='cc-form-actions'><button class='btn btn-primary' id='cc-save'>Save custom cell</button>" +
    "<span class='hint'>LEF is required. Add LIB so synthesis/STA can use it; GDS for the final layout; SPICE/CDL for LVS.</span></div>" +
    "<div id='cc-form-error' class='ac-error' hidden></div>" +
    "</div></details>";

  root.innerHTML = list + form;

  root.querySelectorAll(".cc-remove").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!(await confirmDialog({ title: "Remove custom cell", danger: true, confirmText: "Remove",
        body: "Remove custom cell '" + b.dataset.name + "' and its files?" }))) return;
      try { await api.customCellRemove(b.dataset.name, state.designDir); renderCustomCells(); }
      catch (ex) { toast.show("Remove failed: " + ex.message, "error"); }
    }));
  root.querySelectorAll(".cc-enable").forEach((cb) =>
    cb.addEventListener("change", async () => {
      try { await api.customCellEnable(cb.dataset.name, cb.checked, state.designDir); }
      catch (ex) { toast.show("Update failed: " + ex.message, "error"); cb.checked = !cb.checked; }
    }));
  root.querySelector("#cc-save")?.addEventListener("click", () => saveCustomCell(root));
}

async function saveCustomCell(root) {
  const errEl = root.querySelector("#cc-form-error");
  errEl.hidden = true;
  const name = (root.querySelector("#cc-name")?.value || "").trim();
  if (!name) { errEl.hidden = false; errEl.textContent = "Give the cell a name."; return; }
  const swap = (root.querySelector("#cc-swap")?.value || "").split(",").map((s) => s.trim()).filter(Boolean);
  const views = {};
  for (const inp of root.querySelectorAll(".cc-file")) {
    const f = inp.files && inp.files[0];
    if (!f) continue;
    try {
      views[inp.dataset.kind] = { filename: f.name, content_b64: await readAsBase64(f) };
    } catch (_e) {
      errEl.hidden = false; errEl.textContent = "Could not read " + inp.dataset.kind + " file."; return;
    }
  }
  if (!views.lef) { errEl.hidden = false; errEl.textContent = "A LEF view is required."; return; }
  const btn = root.querySelector("#cc-save");
  btn.disabled = true; btn.textContent = "Saving…";
  try {
    await api.customCellSave({ design_dir: state.designDir, name, swap_out: swap, views, enabled: true });
    toast.show("Saved custom cell '" + name + "'. It'll be used on your next run.", "success");
    renderCustomCells();
  } catch (ex) {
    errEl.hidden = false; errEl.textContent = ex.message;
    btn.disabled = false; btn.textContent = "Save custom cell";
  }
}

function showCustomCellHelp() {
  document.getElementById("btn-custom-cell-help")?.addEventListener("click", showCustomCellHelp, { once: true });
  const backdrop = document.createElement("div");
  backdrop.className = "smodal-backdrop";
  backdrop.innerHTML =
    "<div class='smodal cc-help-modal'>" +
    "<div class='smodal-head'><span class='smodal-title'>Custom cells — how it works</span>" +
    "<span class='smodal-spacer'></span><button class='btn btn-ghost' id='cc-help-close'>✕</button></div>" +
    "<div class='smodal-log cc-help'>" + HELP_HTML + "</div></div>";
  document.body.appendChild(backdrop);
  const close = () => backdrop.remove();
  backdrop.querySelector("#cc-help-close")?.addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
  });
}

const HELP_HTML = `
<h3>What this does</h3>
<p>It lets a run use <strong>your own cell</strong> instead of one (or several) of the PDK's
standard cells — what engineers call a <em>cell swap</em>. Typical reasons: a hand-optimised
gate, a custom drive strength, a radiation-hard or low-leakage variant, or a small hardened macro.</p>

<h3>The mental model</h3>
<p>A standard cell isn't one file — it's a set of <em>views</em>, one per tool that needs to know
about the cell:</p>
<ul>
  <li><strong>LEF</strong> — the abstract/footprint (pins, blockages, size). Needed by placement &amp; routing. <em>Required.</em></li>
  <li><strong>Liberty <code>.lib</code></strong> — timing &amp; power. Needed by synthesis and static timing (STA). Add it so the tools can actually choose your cell.</li>
  <li><strong>GDS</strong> — the real polygons. Needed so the final chip layout contains your cell.</li>
  <li><strong>SPICE / CDL</strong> — the device-level netlist. Needed by LVS (layout-vs-schematic) signoff.</li>
  <li><strong>Verilog model</strong> — behavioural/gate model. Needed for gate-level simulation.</li>
</ul>
<p>LibreLane wires each view in through a dedicated variable:
<code>EXTRA_LEFS</code>, <code>EXTRA_LIBS</code>, <code>EXTRA_GDS</code>,
<code>EXTRA_SPICE_MODELS</code>, <code>EXTRA_VERILOG_MODELS</code>, <code>EXTRA_CDLS</code>.</p>

<h3>The "in exchange for" part</h3>
<p>Adding a cell doesn't remove the originals. To make the tools <em>pick yours instead</em>, name the
standard cells to drop in <strong>Swap out</strong>. Those go into
<code>EXTRA_EXCLUDED_CELLS</code>, which excludes them from synthesis and placement, so the
optimiser reaches for your replacement.</p>

<h3>Step by step</h3>
<ol>
  <li>Click <strong>+ Add a custom cell</strong>.</li>
  <li>Give it a <strong>name</strong> (any label; it's just an id here).</li>
  <li>Upload at least the <strong>LEF</strong>. Add <strong>LIB</strong> too if you want synthesis/STA to use it
      (without timing data the tools can't legally place it).</li>
  <li>Add <strong>GDS</strong> for a clean final layout, and <strong>SPICE/CDL</strong> if you want LVS to pass.</li>
  <li>In <strong>Swap out</strong>, list the exact PDK cell name(s) to replace, e.g.
      <code>sky130_fd_sc_hd__nand2_1</code>. Leave empty to just <em>add</em> the cell without removing any.</li>
  <li>Save. Toggle <strong>Use</strong> per run. Then start a run from Setup — the swap is applied automatically.</li>
</ol>

<h3>Important notes</h3>
<ul>
  <li>This is <strong>per-run, GUI-managed</strong>. Your <code>config.json</code> is never modified. The files live
      in <code>custom_cells/</code> inside your design folder and a small <code>.gui-custom-cells.json</code> sidecar.</li>
  <li>Your cell must be on the PDK's grid (site/row height, tracks) or placement/routing will fail —
      this feature wires the views in; it can't make an off-grid cell legal.</li>
  <li>If you exclude a cell the design genuinely needs and provide no working replacement, synthesis may
      fail to map. Start by adding LEF + LIB and excluding one low-risk cell.</li>
  <li>Names must match the library exactly (case-sensitive). Browse them in the table above.</li>
</ul>`;
