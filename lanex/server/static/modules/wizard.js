// wizard.js — New Project wizard (Phase 0.2). A 3-step modal: pick a template,
// pick target (PDK/SCL/clock/top), confirm -> scaffold + load the design.
import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";

let _overlay = null;
let _templates = [];

function overlay() {
  if (_overlay) return _overlay;
  const ov = document.createElement("div");
  ov.className = "smodal-backdrop wizard-backdrop";
  ov.hidden = true;
  ov.innerHTML =
    "<div class='smodal wizard'>" +
    "  <div class='smodal-head'><span class='smodal-title'>New project</span>" +
    "  <span class='smodal-spacer'></span><button class='btn btn-ghost' id='wiz-close'>✕</button></div>" +
    "  <div class='wizard-body' id='wiz-body'></div>" +
    "</div>";
  document.body.appendChild(ov);
  ov.addEventListener("click", (e) => { if (e.target === ov) ov.hidden = true; });
  ov.querySelector("#wiz-close").addEventListener("click", () => { ov.hidden = true; });
  _overlay = ov;
  return ov;
}

export async function openWizard() {
  const ov = overlay();
  ov.hidden = false;
  const body = ov.querySelector("#wiz-body");
  body.innerHTML = "<p class='muted'>Loading templates…</p>";
  try {
    _templates = await api.templates();
  } catch (ex) {
    body.innerHTML = "<p class='pill pill-fail'>Could not load templates: " + fmt.escape(ex.message || ex) + "</p>";
    return;
  }
  renderStep1(body);
}

function renderStep1(body) {
  body.innerHTML =
    "<h3>1 · Pick a starting point</h3>" +
    "<div class='wiz-templates'>" +
    _templates.map((t) =>
      "<button class='wiz-tpl' data-name='" + fmt.escape(t.name) + "'>" +
      "<span class='wiz-tpl-title'>" + fmt.escape(t.title) + "</span>" +
      "<span class='wiz-tpl-desc muted'>" + fmt.escape(t.description) + "</span>" +
      (t.has_testbench ? "<span class='chip'>has testbench</span>" : "") +
      "</button>",
    ).join("") +
    "</div>";
  body.querySelectorAll(".wiz-tpl").forEach((b) =>
    b.addEventListener("click", () => {
      const tpl = _templates.find((t) => t.name === b.dataset.name);
      renderStep2(body, tpl);
    }),
  );
}

function renderStep2(body, tpl) {
  const pdkOpts = (state.pdks || []).map((p) =>
    "<option value='" + fmt.escape(p.name) + "'>" + fmt.escape(p.name) + "</option>").join("");
  body.innerHTML =
    "<h3>2 · Target — " + fmt.escape(tpl.title) + "</h3>" +
    "<label class='wiz-field'>Destination folder (absolute path)" +
    "<input id='wiz-dest' type='text' placeholder='/path/to/" + fmt.escape(tpl.name) + "' /></label>" +
    "<label class='wiz-field'>Top module<input id='wiz-top' type='text' value='" + fmt.escape(tpl.top) + "' /></label>" +
    "<label class='wiz-field'>PDK<select id='wiz-pdk'>" + pdkOpts + "</select></label>" +
    "<label class='wiz-field'>Clock period (ns)<input id='wiz-clk' type='number' step='0.1' value='" +
      (tpl.clock_period != null ? tpl.clock_period : 10) + "' /></label>" +
    "<div class='wiz-actions'>" +
    "  <button class='btn btn-ghost' id='wiz-back'>Back</button>" +
    "  <button class='btn btn-primary' id='wiz-create'>Create project</button>" +
    "</div>";
  if (state.selectedPdk) {
    const sel = body.querySelector("#wiz-pdk");
    if (sel) sel.value = state.selectedPdk;
  }
  body.querySelector("#wiz-back").addEventListener("click", () => renderStep1(body));
  body.querySelector("#wiz-create").addEventListener("click", () => doCreate(body, tpl));
}

async function doCreate(body, tpl) {
  const dest = (body.querySelector("#wiz-dest").value || "").trim();
  const top = (body.querySelector("#wiz-top").value || "").trim() || tpl.top;
  const pdk = body.querySelector("#wiz-pdk").value || "";
  const clk = parseFloat(body.querySelector("#wiz-clk").value);
  if (!dest) { toast.show("Enter a destination folder.", "warn"); return; }
  const btn = body.querySelector("#wiz-create");
  btn.disabled = true; btn.textContent = "Creating…";
  try {
    const res = await api.projectNew({
      dest_dir: dest, template: tpl.name, top, pdk,
      clock_period: isNaN(clk) ? null : clk,
    });
    overlay().hidden = true;
    toast.show("Project created — loading it now.", "success");
    const setup = await import("./setup.js");
    const input = document.getElementById("design-dir-input");
    if (input) input.value = res.design_dir;
    await setup.adoptDesignDir(res.design_dir);
  } catch (ex) {
    toast.show("Could not create project: " + (ex.message || ex), "error");
    btn.disabled = false; btn.textContent = "Create project";
  }
}

export function setupWizard() {
  document.getElementById("btn-new-project")?.addEventListener("click", openWizard);
}
