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

export async function openWizard({ template = "" } = {}) {
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
    _display = (await import("./shell.js")).displayPath;
  } catch (ex) {
    body.innerHTML = steps(1) + "<p class='wiz-err'>Could not load the templates: " + fmt.escape(ex.message || ex) + "</p>";
    return;
  }
  const pre = template && _templates.find((t) => t.name === template);
  if (pre) renderStep2(body, pre); else renderStep1(body);
}

function tplCard(t, cls) {
  return "<button class='wiz-tpl " + cls + "' data-name='" + fmt.escape(t.name) + "' title='" + fmt.escape(t.description) + "'>" +
    "<span class='wiz-tpl-title'>" + fmt.escape(t.title) + "</span>" +
    "<span class='wiz-tpl-desc'>" + fmt.escape(t.description) + "</span>" +
    (t.has_testbench ? "<span class='wiz-tpl-tag'>Includes a testbench</span>" : "") +
    "</button>";
}

function renderStep1(body) {
  // A new project usually starts blank; the examples are there to learn from
  // or to try the flow on something that is known to work.
  const blank = _templates.filter((t) => t.kind === "blank");
  const examples = _templates.filter((t) => t.kind !== "blank");
  body.innerHTML = steps(1) +
    blank.map((t) => tplCard(t, "wiz-tpl-blank")).join("") +
    (examples.length
      ? "<div class='wiz-lane'><span class='lane-label'>Or start from an example</span>" +
        "<span class='wiz-lane-note'>Working designs with a testbench. Good for a first run.</span></div>" +
        "<div class='wiz-templates'>" + examples.map((t) => tplCard(t, "")).join("") + "</div>"
      : "");
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

function defaultName(tpl) {
  return tpl.kind === "blank" ? "my-chip" : tpl.name;
}

function shown(p) {
  return _display ? _display(p) : p;
}
let _display = null;

function joinPath(dir, name) {
  if (!dir) return name;
  return dir.replace(/[\\/]+$/, "") + "/" + name;
}

function sclNames(pdkName) {
  const pdk = (state.pdks || []).find((p) => p.name === pdkName);
  return ((pdk && pdk.variants) || []).map((v) => (Array.isArray(v) ? v[0] : v));
}

function sclOptions(pdkName) {
  return sclNames(pdkName).map((name) =>
    "<option value='" + fmt.escape(name) + "'>" + fmt.escape(name) + "</option>").join("");
}

// The usual general-purpose library of each PDK family, the same list the
// Setup picker uses; otherwise the first one installed.
const USUAL_SCL = ["sky130_fd_sc_hd", "gf180mcu_fd_sc_mcu7t5v0", "sg13g2_stdcell"];

export function defaultScl(names) {
  return USUAL_SCL.find((s) => names.includes(s)) || names[0] || "";
}

// The usual variant of each family, in the order a beginner is pointed to.
export const USUAL_PDK = ["sky130A", "gf180mcuD", "ihp-sg13g2"];

// The PDK a new project starts on: the open project's when it's ready, then
// the first ready usual one, then the first ready one. A PDK folder without its
// libraries (a leftover or a partial download) is never the default.
export function defaultPdk(pdks, current) {
  const ready = (pdks || []).filter((p) => p.ready !== false).map((p) => p.name);
  if (current && ready.includes(current)) return current;
  return USUAL_PDK.find((p) => ready.includes(p)) || ready[0] || ((pdks || [])[0] || {}).name || "";
}

// A template's clock for a PDK: its per-family clock ({"gf180mcu*": 20})
// when one matches, else its default. Globs as LibreLane's pdk:: keys.
export function clockFor(tpl, pdk) {
  for (const [pat, ns] of Object.entries(tpl.pdk_clock || {})) {
    const rx = new RegExp("^" + pat.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".") + "$");
    if (pdk && rx.test(pdk)) return ns;
  }
  return tpl.clock_period != null ? tpl.clock_period : 10;
}

function mhz(ns) {
  const n = parseFloat(ns);
  if (!(n > 0)) return "";
  const f = 1000 / n;
  return (f >= 100 ? f.toFixed(0) : f.toFixed(1).replace(/\.0$/, "")) + " MHz";
}

function renderStep2(body, tpl) {
  const pdkOpts = (state.pdks || []).map((p) =>
    "<option value='" + fmt.escape(p.name) + "'>" + fmt.escape(p.name) + (p.ready === false ? " (not installed)" : "") + "</option>").join("");
  const startPdk = defaultPdk(state.pdks, state.designDir ? state.selectedPdk : "");
  const clk = clockFor(tpl, startPdk);
  body.innerHTML = steps(2) +
    "<div class='wiz-form'>" +
    "<label class='wiz-field span-2'><span>Project name</span>" +
    "<input id='wiz-name' type='text' value='" + fmt.escape(defaultName(tpl)) + "' autocomplete='off' spellcheck='false' />" +
    "<span class='wiz-help'>Letters, numbers, dashes and underscores. This becomes the folder name.</span></label>" +
    "<div class='wiz-field span-2'><span>Location</span>" +
    "<div class='wiz-loc'><code id='wiz-where'></code><button class='btn btn-ghost btn-sm' id='wiz-change'>Change…</button></div>" +
    "<span class='wiz-help' id='wiz-where-help'></span></div>" +
    "<div class='wiz-field'><label for='wiz-top'>Top module</label>" +
    "<span class='wiz-top-row'><input id='wiz-top' type='text' value='" + fmt.escape(tpl.top) + "' spellcheck='false' />" +
    "<select id='wiz-lang' aria-label='Language' title='The language of the starter files. Verilog .v is what LibreLane&#39;s own examples and Tiny Tapeout use.'>" +
    "<option value='verilog'>Verilog .v</option>" +
    "<option value='systemverilog'>SystemVerilog .sv</option></select></span>" +
    "<span class='wiz-help' id='wiz-top-help'></span></div>" +
    "<label class='wiz-field'><span>Clock period</span>" +
    "<span class='wiz-unit' data-unit='ns'><input id='wiz-clk' type='number' min='0.1' step='0.1' value='" + fmt.escape(clk) + "' /></span>" +
    "<span class='wiz-help' id='wiz-clk-help'></span></label>" +
    "<label class='wiz-field'><span>PDK</span><select id='wiz-pdk'>" + (pdkOpts || "<option value=''>No PDK installed</option>") + "</select>" +
    "<span class='wiz-help' id='wiz-pdk-help'></span></label>" +
    "<label class='wiz-field'><span>Standard-cell library</span><select id='wiz-scl'></select>" +
    "<span class='wiz-help'>The ready-made logic gates the flow builds your design from.</span></label>" +
    (tpl.kind === "blank"
      ? "<label class='nf-use span-2'><input type='checkbox' id='wiz-tb' checked/> <span>Write a testbench too, in <code>verify/</code>, " +
        "wired to the top module's ports, so you can simulate before the first run.</span></label>"
      : "") +
    "</div>" +
    "<div class='wiz-actions'>" +
    "<button class='btn btn-ghost' id='wiz-back'>Back</button>" +
    "<span class='wiz-err' id='wiz-err' role='alert'></span>" +
    "<span class='grow-space'></span>" +
    "<button class='btn btn-primary' id='wiz-create'>Create project</button>" +
    "</div>";

  const $ = (id) => body.querySelector("#" + id);
  const pdkSel = $("wiz-pdk");
  pdkSel.value = startPdk;
  // The clock follows the PDK (gf180's cells are slower) until it's typed in.
  let clkTyped = false;
  const paintScl = () => {
    const names = sclNames(pdkSel.value);
    $("wiz-scl").innerHTML = sclOptions(pdkSel.value) || "<option value=''>None installed</option>";
    $("wiz-scl").value = state.selectedScl && pdkSel.value === state.selectedPdk && names.includes(state.selectedScl)
      ? state.selectedScl : defaultScl(names);
    const p = (state.pdks || []).find((x) => x.name === pdkSel.value);
    const help = $("wiz-pdk-help");
    help.classList.toggle("wiz-warn", !p || p.ready === false);
    help.textContent = !p
      ? "No PDK is installed yet. Install one in Tools first; a run needs it."
      : p.ready === false
        ? p.name + " isn't installed: its folder has no standard-cell libraries. Install it in Tools, or pick another PDK."
        : "The foundry process to build for. sky130A is the usual first choice.";
    if (!clkTyped && $("wiz-clk")) { $("wiz-clk").value = clockFor(tpl, pdkSel.value); paintClk(); }
  };
  pdkSel.addEventListener("change", paintScl);

  const paintWhere = () => {
    const name = $("wiz-name").value.trim() || defaultName(tpl);
    const where = shown(joinPath(projectsDir(), name));
    $("wiz-where").textContent = $("wiz-where").title = where;
    $("wiz-where-help").textContent = _parent ? "A new folder is created inside the folder you chose."
      : where.startsWith("\\\\wsl") ? "Inside the LanEx environment: your Windows user folder can't be used here (its path has a space, or LanEx couldn't find it)."
      : _defaults && _defaults.wsl ? "Your LanEx projects folder, next to your other Windows files." : "Your LanEx projects folder.";
  };
  const paintClk = () => {
    if (!$("wiz-clk")) return;
    const f = mhz($("wiz-clk").value);
    $("wiz-clk-help").textContent = f ? "Target speed: " + f + ". A smaller period is a faster chip and harder to meet." : "Enter a period in nanoseconds.";
  };
  const paintTop = () => {
    const h = $("wiz-top-help");
    if (!h) return;
    const n = ($("wiz-top").value.trim() || tpl.top) + ($("wiz-lang").value === "systemverilog" ? ".sv" : ".v");
    const sv = $("wiz-lang").value === "systemverilog";
    h.innerHTML = "Your top-level module. LanEx starts <code>src/" + fmt.escape(n) + "</code> with a small module of that name. " +
      (sv ? "SystemVerilog is for code that uses <code>logic</code>, <code>always_ff</code> and the like; the open flow supports its common subset."
        : "Verilog is the open flow's native language: LibreLane's examples and Tiny Tapeout designs use it.");
  };
  if ($("wiz-top")) {
    $("wiz-top").addEventListener("input", paintTop);
    $("wiz-lang").addEventListener("change", paintTop);
    paintTop();
  }
  paintWhere();
  paintClk();
  paintScl();
  $("wiz-name").addEventListener("input", () => { $("wiz-err").textContent = ""; paintWhere(); });
  $("wiz-clk")?.addEventListener("input", () => { clkTyped = true; paintClk(); });
  $("wiz-change").addEventListener("click", async () => {
    const { pickFolder } = await import("./fs.js");
    const dir = await pickFolder({ title: "Where should the project folder go?", use: "Put it here", seed: projectsDir() });
    if (dir) { _parent = dir; paintWhere(); }
  });
  $("wiz-back").addEventListener("click", () => renderStep1(body));
  $("wiz-create").addEventListener("click", () => doCreate(body, tpl));
  // Enter anywhere in the form creates the project.
  body.querySelector(".wiz-form").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.tagName !== "SELECT") { e.preventDefault(); doCreate(body, tpl); }
  });
  // An example's top module is defined by its Verilog; only a blank project
  // lets you name it (the starter module and file are renamed to match).
  if (tpl.kind !== "blank") $("wiz-top")?.closest(".wiz-field").remove();
  if (tpl.fixed_config) {
    // This example ships its own tuned config: the fields below don't apply.
    body.querySelectorAll("#wiz-top, #wiz-clk").forEach((el) => el.closest(".wiz-field")?.remove());
    const note = document.createElement("p");
    note.className = "wiz-help wiz-fixed";
    note.textContent = "This example comes with its own tuned settings (clock, floorplan and power grid) for sky130 and gf180, so there's nothing else to set.";
    body.querySelector(".wiz-form").appendChild(note);
  }
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
  const top = ($("wiz-top") ? $("wiz-top").value.trim() : "") || tpl.top;
  const pdk = $("wiz-pdk").value || "";
  const scl = $("wiz-scl").value || "";
  const clk = $("wiz-clk") ? parseFloat($("wiz-clk").value) : NaN;
  const sv = $("wiz-lang") && $("wiz-lang").value === "systemverilog";
  const withTb = !!($("wiz-tb") && $("wiz-tb").checked);
  const btn = $("wiz-create");
  btn.disabled = true; btn.textContent = "Creating…";
  try {
    const res = await api.projectNew({
      dest_dir: dest, template: tpl.name, top, pdk, scl,
      clock_period: isNaN(clk) ? null : clk,
      language: sv ? "systemverilog" : "verilog",
    });
    close();
    const setup = await import("./setup.js");
    const input = document.getElementById("design-dir-input");
    if (input) input.value = res.design_dir;
    const topName = res.top || "top";
    const ext = sv ? ".sv" : ".v";
    // The usual first pair: the design and a bench that drives it.
    let tbRel = null;
    if (tpl.kind === "blank" && withTb) {
      try {
        const tb = await api.newProjectFile({ design_dir: res.design_dir, kind: sv ? "tb_sv" : "tb_v",
          name: topName + "_tb", top: topName, clock: "clk", use: false });
        tbRel = tb.rel;
      } catch (ex) {
        toast.show("The project is ready, but the testbench wasn't written: " + (ex.message || ex), "warn", 6000);
      }
    }
    await setup.adoptDesignDir(res.design_dir);
    if (tpl.kind === "blank") {
      toast.show("Created " + name + ". src/" + topName + ext + (tbRel ? " and " + tbRel : "") +
        " are open in the RTL IDE.", "success");
      (await import("./nav.js")).go("ide", {}, { link: false });
      const ide = await import("./ide/main.js");
      await ide.initIde({ designDir: res.design_dir, runMode: state.runMode });
      if (tbRel) await ide.openInIde({ rel: tbRel });
      await ide.openInIde({ rel: "src/" + topName + ext });
    } else {
      const { go } = await import("./nav.js");
      go("setup", {}, { link: false });
      // Say what comes next (the first-chip guide points at it itself).
      if (document.body.classList.contains("guide-on")) toast.show("Created " + name + ".", "success");
      else toast.show("Created " + name + ". It's ready to run.", "success", 10000, [
        tpl.has_testbench ? { label: "Simulate first", run: () => go("ide") } : null,
        { label: "Go to Run", run: () => {
          go("setup", { section: "setup-preflight" }, { link: false });
          setTimeout(() => document.getElementById("btn-run")?.focus({ preventScroll: true }), 400);
        } },
      ]);
    }
  } catch (ex) {
    err.textContent = ex.message || String(ex);
    btn.disabled = false; btn.textContent = "Create project";
  }
}

export function setupWizard() {
  document.getElementById("btn-new-project")?.addEventListener("click", openWizard);
}
