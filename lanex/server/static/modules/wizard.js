// wizard.js — New project. Two steps: pick a template, then name it and set the
// target. The folder is worked out for you (<projects dir>/<name>, inside the
// WSL home on Windows so runs stay fast); "Change…" picks another parent.
import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";

let _overlay = null;
let _templates = [];
let _defaults = null;
let _parent = "";      // chosen parent folder; "" = the projects dir

const X_ICON = "<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg>";

function close() {
  if (!_overlay) return;
  _overlay.hidden = true;
  document.removeEventListener("keydown", onKey);
}

function onKey(e) {
  // The folder picker sits on top of us; let it own Esc while it's open.
  if (e.key === "Escape" && document.getElementById("fs-modal")?.hidden !== false) close();
}

function overlay() {
  if (_overlay) return _overlay;
  const ov = document.createElement("div");
  ov.className = "smodal-backdrop wizard-backdrop";
  ov.hidden = true;
  ov.innerHTML =
    "<div class='smodal wizard' role='dialog' aria-modal='true' aria-labelledby='wiz-title'>" +
    "  <div class='smodal-head'><span class='smodal-title' id='wiz-title'>New project</span>" +
    "  <span class='smodal-spacer'></span><button class='iconbtn' id='wiz-close' aria-label='Close'>" + X_ICON + "</button></div>" +
    "  <div class='wizard-body' id='wiz-body'></div>" +
    "</div>";
  document.body.appendChild(ov);
  ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
  ov.querySelector("#wiz-close").addEventListener("click", close);
  _overlay = ov;
  return ov;
}

function steps(n) {
  return "<div class='wiz-steps'>" +
    "<span class='wiz-step" + (n === 1 ? " is-on" : "") + "'>1 Start from</span>" +
    "<span class='wiz-step" + (n === 2 ? " is-on" : "") + "'>2 Name and target</span></div>";
}

export async function openWizard() {
  const ov = overlay();
  ov.hidden = false;
  document.addEventListener("keydown", onKey);
  _parent = "";
  const body = ov.querySelector("#wiz-body");
  body.innerHTML = steps(1) + "<p class='muted'>Loading templates…</p>";
  try {
    [_templates, _defaults] = await Promise.all([
      api.templates(),
      api.projectDefaults().catch(() => null),
    ]);
  } catch (ex) {
    body.innerHTML = steps(1) + "<p class='wiz-err'>Could not load the templates: " + fmt.escape(ex.message || ex) + "</p>";
    return;
  }
  renderStep1(body);
}

function renderStep1(body) {
  body.innerHTML = steps(1) +
    "<div class='wiz-templates'>" +
    _templates.map((t) =>
      "<button class='wiz-tpl" + (t.name === "empty" ? " wiz-tpl-empty" : "") + "' data-name='" + fmt.escape(t.name) + "'>" +
      "<span class='wiz-tpl-title'>" + fmt.escape(t.title) + "</span>" +
      "<span class='wiz-tpl-desc'>" + fmt.escape(t.description) + "</span>" +
      (t.has_testbench ? "<span class='wiz-tpl-tag'>Includes a testbench</span>" : "") +
      "</button>",
    ).join("") +
    "</div>";
  body.querySelectorAll(".wiz-tpl").forEach((b) =>
    b.addEventListener("click", () => {
      const tpl = _templates.find((t) => t.name === b.dataset.name);
      renderStep2(body, tpl);
    }),
  );
  body.querySelector(".wiz-tpl")?.focus();
}

function projectsDir() {
  return _parent || (_defaults && _defaults.projects_dir) || "";
}

function joinPath(dir, name) {
  if (!dir) return name;
  return dir.replace(/[\\/]+$/, "") + "/" + name;
}

function sclOptions(pdkName) {
  const pdk = (state.pdks || []).find((p) => p.name === pdkName);
  const variants = (pdk && pdk.variants) || [];
  return variants.map((v) => {
    const name = Array.isArray(v) ? v[0] : v;
    return "<option value='" + fmt.escape(name) + "'>" + fmt.escape(name) + "</option>";
  }).join("");
}

function mhz(ns) {
  const n = parseFloat(ns);
  if (!(n > 0)) return "";
  const f = 1000 / n;
  return (f >= 100 ? f.toFixed(0) : f.toFixed(1).replace(/\.0$/, "")) + " MHz";
}

function renderStep2(body, tpl) {
  const pdkOpts = (state.pdks || []).map((p) =>
    "<option value='" + fmt.escape(p.name) + "'>" + fmt.escape(p.name) + "</option>").join("");
  const clk = tpl.clock_period != null ? tpl.clock_period : 10;
  body.innerHTML = steps(2) +
    "<div class='wiz-form'>" +
    "<label class='wiz-field span-2'><span>Project name</span>" +
    "<input id='wiz-name' type='text' value='" + fmt.escape(tpl.name) + "' autocomplete='off' spellcheck='false' />" +
    "<span class='wiz-help'>Letters, numbers, dashes and underscores. This becomes the folder name.</span></label>" +
    "<div class='wiz-field span-2'><span>Location</span>" +
    "<div class='wiz-loc'><code id='wiz-where'></code><button class='btn btn-ghost btn-sm' id='wiz-change'>Change…</button></div>" +
    "<span class='wiz-help' id='wiz-where-help'></span></div>" +
    "<label class='wiz-field'><span>Top module</span>" +
    "<input id='wiz-top' type='text' value='" + fmt.escape(tpl.top) + "' spellcheck='false' />" +
    "<span class='wiz-help'>The Verilog module at the top of your design. The template already names it; change it only if you rename that module.</span></label>" +
    "<label class='wiz-field'><span>Clock period</span>" +
    "<span class='wiz-unit' data-unit='ns'><input id='wiz-clk' type='number' min='0.1' step='0.1' value='" + fmt.escape(clk) + "' /></span>" +
    "<span class='wiz-help' id='wiz-clk-help'></span></label>" +
    "<label class='wiz-field'><span>PDK</span><select id='wiz-pdk'>" + pdkOpts + "</select>" +
    "<span class='wiz-help'>The foundry process to build for. sky130A is the usual first choice.</span></label>" +
    "<label class='wiz-field'><span>Standard-cell library</span><select id='wiz-scl'></select>" +
    "<span class='wiz-help'>The ready-made logic gates the flow builds your design from.</span></label>" +
    "</div>" +
    "<div class='wiz-actions'>" +
    "<button class='btn btn-ghost' id='wiz-back'>Back</button>" +
    "<span class='wiz-err' id='wiz-err' role='alert'></span>" +
    "<span class='grow-space'></span>" +
    "<button class='btn btn-primary' id='wiz-create'>Create project</button>" +
    "</div>";

  const $ = (id) => body.querySelector("#" + id);
  const pdkSel = $("wiz-pdk");
  // Keep the PDK of the open project; otherwise start beginners on sky130A.
  const names = (state.pdks || []).map((p) => p.name);
  pdkSel.value = (state.designDir && state.selectedPdk) || (names.includes("sky130A") ? "sky130A" : state.selectedPdk || names[0] || "");
  const paintScl = () => {
    $("wiz-scl").innerHTML = sclOptions(pdkSel.value) || "<option value=''>PDK default</option>";
    if (state.selectedScl && pdkSel.value === state.selectedPdk) $("wiz-scl").value = state.selectedScl;
  };
  paintScl();
  pdkSel.addEventListener("change", paintScl);

  const paintWhere = () => {
    const name = $("wiz-name").value.trim() || tpl.name;
    $("wiz-where").textContent = joinPath(projectsDir(), name);
    $("wiz-where").title = joinPath(projectsDir(), name);
    $("wiz-where-help").textContent = _parent
      ? "A new folder is created inside the folder you chose."
      : (_defaults && _defaults.wsl
        ? "Your LanEx projects folder. Open it from Windows with Project → Show in Explorer."
        : "Your LanEx projects folder.");
  };
  const paintClk = () => {
    const f = mhz($("wiz-clk").value);
    $("wiz-clk-help").textContent = f ? "Target speed: " + f + ". A smaller period is a faster chip and harder to meet." : "Enter a period in nanoseconds.";
  };
  paintWhere();
  paintClk();
  $("wiz-name").addEventListener("input", () => { $("wiz-err").textContent = ""; paintWhere(); });
  $("wiz-clk").addEventListener("input", paintClk);
  $("wiz-change").addEventListener("click", async () => {
    const { pickFolder } = await import("./fs.js");
    const dir = await pickFolder({ title: "Where should the project folder go?", use: "Put it here", seed: projectsDir() });
    if (dir) { _parent = dir; paintWhere(); }
  });
  $("wiz-back").addEventListener("click", () => renderStep1(body));
  $("wiz-create").addEventListener("click", () => doCreate(body, tpl));
  $("wiz-name").focus();
  $("wiz-name").select();
}

async function doCreate(body, tpl) {
  const $ = (id) => body.querySelector("#" + id);
  const name = $("wiz-name").value.trim();
  const err = $("wiz-err");
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]*$/.test(name)) {
    err.textContent = "Use letters, numbers, - and _ for the name, starting with a letter or number.";
    $("wiz-name").focus();
    return;
  }
  const dest = joinPath(projectsDir(), name);
  const top = $("wiz-top").value.trim() || tpl.top;
  const pdk = $("wiz-pdk").value || "";
  const scl = $("wiz-scl").value || "";
  const clk = parseFloat($("wiz-clk").value);
  const btn = $("wiz-create");
  btn.disabled = true; btn.textContent = "Creating…";
  try {
    const res = await api.projectNew({
      dest_dir: dest, template: tpl.name, top, pdk, scl,
      clock_period: isNaN(clk) ? null : clk,
    });
    close();
    toast.show("Created " + name + ". It's open now.", "success");
    const setup = await import("./setup.js");
    const input = document.getElementById("design-dir-input");
    if (input) input.value = res.design_dir;
    await setup.adoptDesignDir(res.design_dir);
  } catch (ex) {
    err.textContent = ex.message || String(ex);
    btn.disabled = false; btn.textContent = "Create project";
  }
}

export function setupWizard() {
  document.getElementById("btn-new-project")?.addEventListener("click", openWizard);
}
