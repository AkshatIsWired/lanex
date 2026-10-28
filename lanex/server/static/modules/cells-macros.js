// cells-macros.js — the Macros part of the Cells tab.
//
// A macro is a pre-built block (an SRAM, an IP block, or a design hardened in
// another LanEx project) that sits in the floorplan as a fixed rectangle. This
// page gets one in from where it actually comes from, then checks the four
// things a first macro usually gets wrong before a 20-minute run finds out:
// it isn't instantiated (or under a different name), its behavioural model is
// also in the design sources, it has no timing model, or its power pins are
// not hooked to the grid. Everything is per run: it reaches LibreLane through
// the .gui-macros.json overlay, never by editing config.json.

import { api } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { icon } from "./icons.js";
import { confirmDialog, customDialog } from "./dialog.js";
import * as M from "./cells-model.js";
import { copyText, setMacroTile } from "./cells.js";

const esc = M.esc;
const ORIENTS = ["N", "S", "E", "W", "FN", "FS", "FE", "FW"];
let C = null;        // context from cells.js
let D = null;        // {macros, settings, inspect, catalog}
let _my = 0;

export async function renderMacros(ctx) {
  C = ctx;
  const host = document.getElementById("cl-macros-body");
  if (!host) return;
  if (!state.designDir) {
    host.innerHTML = "<div class='an-none'>Open a project first. Macros belong to a project: they are listed in its folder and used by its runs.</div>";
    setMacroTile(0, 0);
    return;
  }
  const my = ++_my;
  const pdk = state.selectedPdk || ctx.pdk;
  const [list, inspect, catalog] = await Promise.all([
    api.customMacros(state.designDir).catch(() => ({ macros: [] })),
    api.macroInspect(state.designDir, pdk).catch((e) => ({ ok: false, error: e.message })),
    api.macroCatalog(pdk, state.selectedScl || ctx.scl).catch(() => ({ macros: [] })),
  ]);
  if (my !== _my) return;
  D = { macros: list.macros || [], settings: list.settings || {}, inspect: inspect || {}, catalog: (catalog && catalog.macros) || [] };
  paint(host);
}

function checksFor(m) {
  const ins = D.inspect || {};
  const info = (ins.macros || {})[m.name] || {};
  const scan = ins.scan || {};
  const found = (scan.instances || {})[m.name] || [];
  const views = m.views || {};
  const out = [];
  out.push({ s: "pass", t: "Layout views: GDS and LEF" + (info.ok ? " (" + fmtSize(info.w, info.h) + ")" : "") });
  if (!info.ok) out.push({ s: "fail", t: "Couldn't read its LEF: " + (info.error || "missing") });
  if (views.lib || (views.nl && views.spef)) out.push({ s: "pass", t: "Timing model: " + (views.lib ? "Liberty" : "netlist + parasitics") + ", so STA times paths through it" });
  else out.push({ s: "warn", t: "No timing model. Synthesis treats it as a black box and STA can't check paths into or out of it." });
  if (scan.ok && scan.top_found) {
    const configured = (m.instances || []).map((i) => i.name);
    if (!found.length) out.push({ s: "fail", t: "Not instantiated anywhere under " + scan.top + ". Paste the template below into your RTL.", fix: "template" });
    else {
      const missing = configured.filter((n) => !found.includes(n));
      if (!configured.length) out.push({ s: "warn", t: "Found in the RTL as " + found.join(", ") + ", but no instance is listed here yet.", fix: "use-found" });
      else if (missing.length) out.push({ s: "fail", t: "Listed as " + missing.join(", ") + ", but the RTL names it " + found.join(", ") + ". The names must match the flattened instance path.", fix: "use-found" });
      else out.push({ s: "pass", t: "Instantiated as " + found.join(", ") });
    }
  } else if (scan.ok) {
    out.push({ s: "info", t: "Couldn't find the top module " + (scan.top || "(DESIGN_NAME unset)") + " in the design files, so the instance check was skipped." });
  }
  const unplaced = (m.instances || []).filter((i) => !Array.isArray(i.location));
  if (unplaced.length) out.push({ s: "fail", t: unplaced.map((i) => i.name).join(", ") + (unplaced.length > 1 ? " have" : " has") +
    " no position. LibreLane places a macro only where you put it; without one the run stops at the power grid (unplaced macros).", fix: "arrange" });
  const defined = (scan.defined_in_sources || {})[m.name];
  if (defined) out.push({ s: "fail", t: shortPath(defined) + " defines this module, so synthesis would build the memory out of flip-flops instead of using the macro. Keep that file for simulation only (Sources → Simulation)." });
  if (m.power) out.push({ s: "pass", t: "Power: " + m.power.vdd_pin + " → " + m.power.vdd_net + ", " + m.power.gnd_pin + " → " + m.power.gnd_net });
  else if (info.ok && ((info.power || {}).vdd || []).length) out.push({ s: "warn", t: "Power pins (" + info.power.vdd.concat(info.power.gnd).join(", ") + ") aren't hooked to the power grid. LVS fails without it.", fix: "power" });
  return out;
}

function shortPath(p) {
  const d = (state.designDir || "").replace(/\/+$/, "");
  return p.startsWith(d + "/") ? p.slice(d.length + 1) : p;
}
function fmtSize(w, h) { return Number.isFinite(w) ? w.toFixed(1) + " × " + h.toFixed(1) + " µm" : "size unknown"; }

function paint(host) {
  const ms = D.macros;
  const attention = ms.filter((m) => m.enabled !== false && checksFor(m).some((c) => c.s === "fail" || c.s === "warn")).length;
  setMacroTile(ms.length, attention);
  const addBtn = "<button class='btn btn-primary btn-sm' data-mc-add=''>" + icon("plus", { size: 14 }) + " Add a macro</button>";
  if (!ms.length) {
    const n = D.catalog.length;
    host.innerHTML =
      "<div class='mc-sources'>" +
      tile("pdk", "database", "Memory from the PDK", n ? n + " SRAM" + (n === 1 ? "" : "s") + " ship with " + esc(state.selectedPdk || C.pdk) + ". Pick one by size; nothing is copied." : "This PDK ships no SRAM macros.", !n) +
      tile("run", "box", "A block from another project", "Harden a sub-block on its own, then drop its finished run in here. The hierarchical flow, without the copying by hand.") +
      tile("files", "upload", "Files you were given", "A vendor or a teammate handed you GDS + LEF (+ LIB). Drop them in.") +
      "</div>";
    wireCards(host);
    return;
  }
  host.innerHTML =
    "<div class='mc-bar'>" + addBtn + "<span class='bar-spacer'></span>" + overlayBtn() + "</div>" +
    "<div class='mc-grid'><div class='mc-list'>" + ms.map(cardHtml).join("") + "</div>" +
    "<div class='mc-side'>" + floorplanHtml() + haloHtml() + "</div></div>";
  wireCards(host);
  wireFloorplan(host);
}

function tile(kind, ic, title, body, disabled) {
  return "<button class='mc-src' data-mc-add='" + kind + "'" + (disabled ? " disabled" : "") + "><span class='mc-src-ic'>" + icon(ic, { size: 22 }) + "</span>" +
    "<b>" + esc(title) + "</b><span>" + esc(body) + "</span></button>";
}

function overlayBtn() {
  return "<button class='btn btn-ghost btn-sm' data-mc-overlay title='The exact config file LanEx hands LibreLane for the macros'>" + icon("file", { size: 13 }) + " .gui-macros.json</button>";
}

function cardHtml(m) {
  const info = ((D.inspect || {}).macros || {})[m.name] || {};
  const checks = checksFor(m);
  const worst = checks.some((c) => c.s === "fail") ? "fail" : checks.some((c) => c.s === "warn") ? "warn" : "pass";
  const src = m.source || {};
  const cap = (D.catalog.find((x) => x.name === m.name) || {}).capacity;
  const views = Object.keys(m.views || {}).map((k) => "<span class='cc-chip'>" + esc(k) + "</span>").join(" ");
  const inst = (m.instances || []);
  const instRows = inst.map((i, k) => instRow(m, i, k)).join("");
  return "<article class='mc-card is-" + (m.enabled === false ? "off" : worst) + "' data-macro='" + esc(m.name) + "'>" +
    "<header class='mc-head'>" +
      "<div><div class='an-eyebrow'>" + esc(src.kind === "pdk" ? "PDK macro" : src.kind === "run" ? "From another project" : "Uploaded") + (src.label ? " · " + esc(src.label) : "") + "</div>" +
      "<h4 class='mc-name'>" + esc(m.name) + "</h4>" +
      "<div class='mc-meta'>" + (info.ok ? fmtSize(info.w, info.h) + " · " + M.fmtArea(info.w * info.h) : "") +
        (cap && cap.words ? " · " + cap.words + " words × " + cap.bits + " bits" + (cap.kbits ? " (" + (cap.kbits >= 8 ? (cap.kbits / 8) + " KB" : cap.kbits + " kbit") + ")" : "") : "") + "</div></div>" +
      "<div class='mc-head-act'><label class='cl-switch' title='Use this macro in the next run'><input type='checkbox' data-mc-enable" + (m.enabled !== false ? " checked" : "") + "><span></span> Use</label>" +
      "<button class='btn btn-ghost btn-sm' data-mc-remove title='Remove this macro (and the files LanEx copied for it)'>" + icon("trash", { size: 13 }) + "</button></div>" +
    "</header>" +
    "<ul class='mc-checks'>" + checks.map((c) => "<li class='is-" + c.s + "'><span class='vf-mark is-" + c.s + "'></span><span>" + esc(c.t) + "</span>" +
      (c.fix === "use-found" ? " <button class='btn btn-ghost btn-xs' data-mc-usefound>Use the RTL's names</button>" : "") +
      (c.fix === "power" ? " <button class='btn btn-ghost btn-xs' data-mc-power>Hook up</button>" : "") +
      (c.fix === "template" ? " <button class='btn btn-ghost btn-xs' data-mc-copytpl>Copy template</button>" : "") +
      (c.fix === "arrange" ? " <button class='btn btn-ghost btn-xs' data-mc-arrange>Arrange for me</button>" : "") + "</li>").join("") + "</ul>" +
    "<div class='mc-views'>Views " + views + "</div>" +
    "<div class='mc-inst'><div class='mc-inst-h'>Instances <span class='muted'>Lower-left corner in µm. Every instance needs one: LibreLane has no automatic macro placer.</span></div>" +
      (instRows ? "<div class='mc-inst-rows'>" + instRows + "</div>" : "<p class='muted cl-p'>None yet.</p>") +
      "<div class='mc-inst-act'><button class='btn btn-ghost btn-xs' data-mc-addinst>" + icon("plus", { size: 12 }) + " Instance</button>" +
      "<button class='btn btn-sm btn-primary' data-mc-save hidden>Save</button></div></div>" +
    powerHtml(m, info) +
    (info.template ? "<details class='mc-tpl'><summary>Instantiation template</summary><pre class='mono'>" + esc(info.template) + "</pre>" +
      "<div class='mc-tpl-act'><button class='btn btn-ghost btn-xs' data-mc-copytpl>Copy</button>" +
      (D.inspect.top ? "<button class='btn btn-ghost btn-xs' data-mc-opentop>Open " + esc(D.inspect.top) + " in the RTL IDE</button>" : "") +
      "<span class='muted'>Power pins stay behind <code>USE_POWER_PINS</code>, as LibreLane expects.</span></div></details>" : "") +
    "</article>";
}

function instRow(m, i, k) {
  const fixed = Array.isArray(i.location);
  return "<div class='mc-irow' data-k='" + k + "'>" +
    "<input class='mc-iname mono' value='" + esc(i.name) + "' aria-label='Instance path' spellcheck='false'>" +
    "<input class='mc-ix' value='" + (fixed ? esc(i.location[0]) : "") + "' placeholder='X µm' aria-label='X µm'>" +
    "<input class='mc-iy' value='" + (fixed ? esc(i.location[1]) : "") + "' placeholder='Y µm' aria-label='Y µm'>" +
    "<select class='mc-io' aria-label='Orientation'>" + ORIENTS.map((o) => "<option" + (o === (i.orientation || "N") ? " selected" : "") + ">" + o + "</option>").join("") + "</select>" +
    "<button class='btn btn-ghost btn-xs' data-mc-delinst title='Remove'>" + icon("x", { size: 12 }) + "</button></div>";
}

function powerHtml(m, info) {
  const pw = m.power;
  const pins = info.ok ? info.power || { vdd: [], gnd: [] } : { vdd: [], gnd: [] };
  if (!pw && !pins.vdd.length && !pins.gnd.length) return "";
  if (!pw) return "";
  return "<div class='mc-power'><span class='mc-power-h'>Power hookup</span>" +
    "<code>" + esc(pw.vdd_pin) + "</code> → <code>" + esc(pw.vdd_net) + "</code>, <code>" + esc(pw.gnd_pin) + "</code> → <code>" + esc(pw.gnd_net) + "</code>" +
    " <button class='btn btn-ghost btn-xs' data-mc-power>Change</button>" +
    "<span class='muted'> Written as <code>PDN_MACRO_CONNECTIONS</code>, one line per instance.</span></div>";
}

function defaultPower(info) {
  const p = (info && info.power) || { vdd: [], gnd: [] };
  const rules = (C.lib && C.lib.rules) || {};
  return {
    vdd_pin: p.vdd.length > 1 ? p.vdd.join("|") : (p.vdd[0] || ""),
    gnd_pin: p.gnd.length > 1 ? p.gnd.join("|") : (p.gnd[0] || ""),
    vdd_net: D.inspect.vdd || rules.vdd || (/sky130/i.test(state.selectedPdk || C.pdk || "") ? "VPWR" : "VDD"),
    gnd_net: D.inspect.gnd || rules.gnd || (/sky130/i.test(state.selectedPdk || C.pdk || "") ? "VGND" : "VSS"),
  };
}

// ---------------------------------------------------------- card actions ----
function collect(card) {
  return [...card.querySelectorAll(".mc-irow")].map((r) => {
    const x = r.querySelector(".mc-ix").value.trim(), y = r.querySelector(".mc-iy").value.trim();
    return { name: r.querySelector(".mc-iname").value.trim(), location: (x || y) ? [x, y] : null, orientation: r.querySelector(".mc-io").value };
  }).filter((i) => i.name);
}

async function saveMacro(name, patch) {
  const m = D.macros.find((x) => x.name === name);
  const body = { design_dir: state.designDir, name, instances: m.instances || [], views: {}, enabled: m.enabled !== false };
  Object.assign(body, patch);
  try {
    await api.customMacroSave(body);
    return true;
  } catch (ex) { toast.show(ex.message || String(ex), "error"); return false; }
}

function wireCards(host) {
  if (host._mcWired) return;
  host._mcWired = true;
  host.addEventListener("input", (e) => {
    const card = e.target.closest(".mc-card");
    if (card && e.target.closest(".mc-irow")) card.querySelector("[data-mc-save]").hidden = false;
  });
  host.addEventListener("change", async (e) => {
    const card = e.target.closest(".mc-card");
    if (!card) return;
    if (e.target.matches("[data-mc-enable]")) {
      try { await api.customMacroEnable(card.dataset.macro, e.target.checked, state.designDir); renderMacros(C); }
      catch (ex) { toast.show(ex.message, "error"); e.target.checked = !e.target.checked; }
      return;
    }
    if (e.target.closest(".mc-irow")) card.querySelector("[data-mc-save]").hidden = false;
  });
  host.addEventListener("click", async (e) => {
    const card = e.target.closest(".mc-card");
    const name = card && card.dataset.macro;
    const info = name ? ((D.inspect.macros || {})[name] || {}) : null;
    if (e.target.closest("[data-mc-add]") && !card) { openAdd(e.target.closest("[data-mc-add]").dataset.mcAdd || "pdk"); return; }
    if (e.target.closest("[data-mc-overlay]")) { showOverlay(); return; }
    if (!card) return;
    if (e.target.closest("[data-mc-remove]")) {
      if (!(await confirmDialog({ title: "Remove " + name, danger: true, confirmText: "Remove",
        body: "Its next run won't include it. Files LanEx copied into macros/" + name + "/ are deleted; PDK files are left alone." }))) return;
      try { await api.customMacroRemove(name, state.designDir); renderMacros(C); } catch (ex) { toast.show(ex.message, "error"); }
      return;
    }
    if (e.target.closest("[data-mc-addinst]")) {
      const rows = card.querySelector(".mc-inst-rows") || (() => {
        const d = document.createElement("div"); d.className = "mc-inst-rows";
        card.querySelector(".mc-inst .cl-p")?.replaceWith(d); return d;
      })();
      const k = rows.children.length;
      rows.insertAdjacentHTML("beforeend", instRow({}, { name: "u_" + (k ? "macro" + k : "sram"), location: null, orientation: "N" }, k));
      card.querySelector("[data-mc-save]").hidden = false;
      rows.lastElementChild.querySelector(".mc-iname").select();
      return;
    }
    if (e.target.closest("[data-mc-delinst]")) {
      e.target.closest(".mc-irow").remove();
      card.querySelector("[data-mc-save]").hidden = false;
      return;
    }
    if (e.target.closest("[data-mc-save]")) {
      if (await saveMacro(name, { instances: collect(card) })) { toast.show("Saved " + name + ". The next run uses it.", "success"); renderMacros(C); }
      return;
    }
    if (e.target.closest("[data-mc-usefound]")) {
      const found = ((D.inspect.scan || {}).instances || {})[name] || [];
      const m = D.macros.find((x) => x.name === name);
      const prev = new Map((m.instances || []).map((i) => [i.name, i]));
      const inst = found.map((n) => prev.get(n) || { name: n, location: null, orientation: "N" });
      const patch = { instances: inst };
      if (!m.power && info.ok && (info.power.vdd || []).length) patch.power = defaultPower(info);
      if (await saveMacro(name, patch)) { toast.show("Instances set to the RTL's: " + found.join(", "), "success"); renderMacros(C); }
      return;
    }
    if (e.target.closest("[data-mc-power]")) { editPower(name, info); return; }
    if (e.target.closest("[data-mc-arrange]")) { arrange(false); return; }
    if (e.target.closest("[data-mc-copytpl]")) { if (info.template) copyText(info.template, "Template copied"); return; }
    if (e.target.closest("[data-mc-opentop]")) {
      const f = ((D.inspect.scan || {}).top_file) || "";
      import("./nav.js").then((m) => m.go("ide", f ? { rel: shortPath(f) } : {}));
    }
  });
}

async function editPower(name, info) {
  const m = D.macros.find((x) => x.name === name);
  const cur = m.power || defaultPower(info);
  const pins = (info && info.power) || { vdd: [], gnd: [] };
  const v = await customDialog({
    title: "Power hookup: " + esc(name),
    bodyHtml: "<p class='muted'>Which of the macro's pins connect to which of your design's power nets. LibreLane's power-grid step uses this to strap the macro to the grid; without it LVS reports the macro unpowered.</p>" +
      "<div class='mc-pw-form'>" +
      "<label>Macro power pin <input id='pw-vp' class='mono' value='" + esc(cur.vdd_pin) + "' list='pw-vl'></label>" +
      "<label>connects to net <input id='pw-vn' class='mono' value='" + esc(cur.vdd_net) + "'></label>" +
      "<label>Macro ground pin <input id='pw-gp' class='mono' value='" + esc(cur.gnd_pin) + "' list='pw-gl'></label>" +
      "<label>connects to net <input id='pw-gn' class='mono' value='" + esc(cur.gnd_net) + "'></label>" +
      "<datalist id='pw-vl'>" + pins.vdd.map((p) => "<option value='" + esc(p) + "'>").join("") + "</datalist>" +
      "<datalist id='pw-gl'>" + pins.gnd.map((p) => "<option value='" + esc(p) + "'>").join("") + "</datalist></div>" +
      "<p class='muted'>Pins from its LEF: " + esc(pins.vdd.concat(pins.gnd).join(", ") || "none marked POWER/GROUND") + ". Several pins on one net: separate them with <code>|</code>.</p>",
    buttons: [{ label: "Cancel", value: null, cls: "btn-ghost" }, { label: "Remove hookup", value: "clear", cls: "btn-ghost" }, { label: "Save", value: "save", cls: "btn-primary" }],
    onMount: (back) => { back.querySelector(".dlg").dataset.pw = "1"; },
  });
  void v;   // the fields are read by the capture listener below, before the dialog closes
}

// customDialog removes its DOM before resolving, so read the fields on click.
document.addEventListener("click", (e) => {
  const dlg = e.target.closest(".dlg[data-pw]");
  if (!dlg || !e.target.closest(".dlg-actions .btn")) return;
  const label = e.target.textContent;
  const name = (dlg.querySelector(".dlg-head").textContent || "").replace(/^Power hookup:\s*/, "");
  if (label === "Save") {
    const power = { vdd_pin: dlg.querySelector("#pw-vp").value.trim(), vdd_net: dlg.querySelector("#pw-vn").value.trim(),
      gnd_pin: dlg.querySelector("#pw-gp").value.trim(), gnd_net: dlg.querySelector("#pw-gn").value.trim() };
    saveMacro(name, { power }).then((ok) => { if (ok) { toast.show("Power hookup saved.", "success"); renderMacros(C); } });
  } else if (label === "Remove hookup") {
    saveMacro(name, { power: {} }).then((ok) => { if (ok) renderMacros(C); });
  }
}, true);

async function showOverlay() {
  const abs = state.designDir.replace(/\/+$/, "") + "/.gui-macros.json";
  let t;
  try { t = await api.readText(abs); } catch (ex) { t = null; }
  const { renderFileText } = await import("./fileview.js");
  await customDialog({
    title: "The macro overlay LanEx hands LibreLane",
    wide: true,
    bodyHtml: "<p class='muted prov-note'>Written at each run start from the macros switched on above, and passed to LibreLane as a second config file next to yours. Your config file is never edited.</p><div class='prov-view'></div>",
    onMount: (back) => {
      const v = back.querySelector(".prov-view");
      if (t && t.ok !== false && t.text) renderFileText(v, t.text, { title: ".gui-macros.json", abs });
      else v.innerHTML = "<p class='muted'>Not written yet: it appears when a run starts with at least one macro switched on.</p>";
    },
  });
}

// ---------------------------------------------------------- floorplan ------
function dieBox() {
  const parse = (v) => {
    const a = Array.isArray(v) ? v : String(v || "").trim().split(/[\s,]+/);
    const n = a.map(Number);
    return n.length === 4 && n.every(Number.isFinite) ? n : null;
  };
  const cfg = parse(D.inspect.die_area);
  if (cfg) return { box: cfg, from: "DIE_AREA in your config" };
  const last = D.inspect.last_die && parse(D.inspect.last_die.bbox);
  if (last) return { box: last, from: "the die of run " + D.inspect.last_die.tag + " (sizing is relative, so it can change)" };
  return null;
}

function floorplanHtml() {
  const die = dieBox();
  const head = "<div class='cl-card-h'>Floorplan sketch</div>";
  if (!die) return "<section class='cl-card mc-fp'>" + head + "<p class='muted cl-p'>The flow sizes the die itself (FP_SIZING relative), so there is nothing to place against yet. Leave the macros on auto, or set <code>DIE_AREA</code> on the Settings card to place them by hand.</p>" +
    "<p class='cl-foot'>Relative sizing grows the die from the cell area at <code>FP_CORE_UTIL</code>, and a big block plus its halo often doesn't fit what that gives. Designs with macros use <code>FP_SIZING: absolute</code> with a <code>DIE_AREA</code> sized around them.</p>" +
    (suggestDie() ? "<div class='mc-fp-act'><button class='btn btn-sm' data-mc-setdie>Use an absolute die of " + suggestDie().join(" × ") + " µm</button><span class='muted'>Saved to your config; edit it on the Settings card.</span></div>" : "") + "</section>";
  const [x0, y0, x1, y1] = die.box;
  const W = x1 - x0, H = y1 - y0;
  const halo = { h: D.settings.halo_h != null ? D.settings.halo_h : 10, v: D.settings.halo_v != null ? D.settings.halo_v : 10 };
  const rects = [];
  const auto = [];
  for (const m of D.macros) {
    if (m.enabled === false) continue;
    const info = (D.inspect.macros || {})[m.name] || {};
    if (!info.ok) continue;
    for (const i of m.instances || []) {
      const rot = /^(E|W|FE|FW)$/.test(i.orientation || "N");
      const w = rot ? info.h : info.w, h = rot ? info.w : info.h;
      if (!Array.isArray(i.location)) { auto.push(i.name + " (" + m.name + ")"); continue; }
      const x = Number(i.location[0]), y = Number(i.location[1]);
      const out = x < x0 || y < y0 || x + w > x1 || y + h > y1;
      rects.push("<g class='mc-fp-m" + (out ? " is-out" : "") + "' data-macro='" + esc(m.name) + "' data-inst='" + esc(i.name) + "' data-w='" + w + "' data-h='" + h + "'>" +
        "<rect class='mc-fp-halo' x='" + (x - halo.h) + "' y='" + (y1 - y - h - halo.v + y0) + "' width='" + (w + 2 * halo.h) + "' height='" + (h + 2 * halo.v) + "'/>" +
        "<rect class='mc-fp-box' x='" + x + "' y='" + (y1 - y - h + y0) + "' width='" + w + "' height='" + h + "'/>" +
        "<text x='" + (x + w / 2) + "' y='" + (y1 - y - h / 2 + y0) + "' font-size='" + (Math.min(W, H) / 22).toFixed(2) + "' text-anchor='middle'>" + esc(i.name) + "</text></g>");
    }
  }
  const pad = Math.max(W, H) * 0.03;
  const svg = "<svg class='mc-fp-svg' viewBox='" + (x0 - pad) + " " + (y0 - pad) + " " + (W + 2 * pad) + " " + (H + 2 * pad) + "' data-die='" + [x0, y0, x1, y1].join(",") + "'>" +
    "<rect class='mc-fp-die' x='" + x0 + "' y='" + y0 + "' width='" + W + "' height='" + H + "'/>" + rects.join("") + "</svg>";
  return "<section class='cl-card mc-fp'>" + head +
    "<p class='cl-foot'>Die " + W.toFixed(0) + " × " + H.toFixed(0) + " µm, from " + esc(die.from) + ". Drag a macro to fix its position (snaps to 1 µm); the dashed ring is the keep-out halo.</p>" +
    svg + (auto.length ? "<p class='cl-p'><span class='cl-warn-t'>No position yet: " + esc(auto.join(", ")) + ".</span> <button class='btn btn-ghost btn-xs' data-mc-arrange>Arrange for me</button></p>" : "") +
    "<div class='mc-fp-act' hidden><button class='btn btn-primary btn-sm' data-fp-save>Save positions</button><button class='btn btn-ghost btn-sm' data-fp-undo>Undo</button></div></section>";
}

function wireFloorplan(host) {
  const svg = host.querySelector(".mc-fp-svg");
  if (!svg) return;
  const [x0, y0, x1, y1] = svg.dataset.die.split(",").map(Number);
  const moved = new Map();
  let drag = null;
  const pt = (e) => { const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY; return p.matrixTransform(svg.getScreenCTM().inverse()); };
  svg.addEventListener("pointerdown", (e) => {
    const g = e.target.closest(".mc-fp-m");
    if (!g) return;
    const p = pt(e);
    const box = g.querySelector(".mc-fp-box");
    drag = { g, dx: p.x - Number(box.getAttribute("x")), dy: p.y - Number(box.getAttribute("y")), w: Number(g.dataset.w), h: Number(g.dataset.h) };
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const p = pt(e);
    let x = Math.round(p.x - drag.dx), ySvg = p.y - drag.dy;
    let y = Math.round(y1 + y0 - ySvg - drag.h);
    x = Math.max(x0, Math.min(x1 - drag.w, x)); y = Math.max(y0, Math.min(y1 - drag.h, y));
    place(drag.g, x, y);
    moved.set(drag.g.dataset.macro + "\u0000" + drag.g.dataset.inst, [x, y]);
    host.querySelector(".mc-fp-act").hidden = false;
  });
  const end = () => { drag = null; };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);
  function place(g, x, y) {
    const h = Number(g.dataset.h), w = Number(g.dataset.w);
    const halo = g.querySelector(".mc-fp-halo"), box = g.querySelector(".mc-fp-box"), t = g.querySelector("text");
    const hh = (Number(halo.getAttribute("width")) - w) / 2, hv = (Number(halo.getAttribute("height")) - h) / 2;
    const ys = y1 - y - h + y0;
    box.setAttribute("x", x); box.setAttribute("y", ys);
    halo.setAttribute("x", x - hh); halo.setAttribute("y", ys - hv);
    t.setAttribute("x", x + w / 2); t.setAttribute("y", ys + h / 2);
    g.querySelector("title")?.remove();
    g.insertAdjacentHTML("beforeend", "<title>" + esc(g.dataset.inst + " at (" + x + ", " + y + ") µm") + "</title>");
  }
  host.querySelector("[data-fp-undo]")?.addEventListener("click", () => renderMacros(C));
  host.querySelector("[data-fp-save]")?.addEventListener("click", async () => {
    const byMacro = new Map();
    for (const [k, loc] of moved) {
      const [mn, inst] = k.split("\u0000");
      if (!byMacro.has(mn)) byMacro.set(mn, []);
      byMacro.get(mn).push([inst, loc]);
    }
    for (const [mn, list] of byMacro) {
      const m = D.macros.find((x) => x.name === mn);
      const inst = (m.instances || []).map((i) => {
        const hit = list.find((l) => l[0] === i.name);
        return hit ? Object.assign({}, i, { location: hit[1] }) : i;
      });
      if (!(await saveMacro(mn, { instances: inst }))) return;
    }
    toast.show("Macro positions saved.", "success");
    renderMacros(C);
  });
}

function haloHtml() {
  const st = D.settings || {};
  return "<section class='cl-card mc-halo'><div class='cl-card-h'>Keep-out around macros</div>" +
    "<p class='cl-foot'>No standard cells within this distance of a macro, so its pins stay reachable. LibreLane's default is 10 µm each way.</p>" +
    "<div class='mc-halo-row'><label>Left/right <input id='mc-hh' inputmode='decimal' placeholder='10' value='" + esc(st.halo_h != null ? st.halo_h : "") + "'> µm</label>" +
    "<label>Top/bottom <input id='mc-hv' inputmode='decimal' placeholder='10' value='" + esc(st.halo_v != null ? st.halo_v : "") + "'> µm</label>" +
    "<button class='btn btn-sm' id='mc-halo-save'>Save</button></div></section>";
}

document.addEventListener("click", async (e) => {
  if (!e.target.closest("#mc-halo-save")) return;
  try {
    await api.macroSettings(state.designDir, { halo_h: document.getElementById("mc-hh").value, halo_v: document.getElementById("mc-hv").value });
    toast.show("Halo saved. The next run uses it.", "success");
    renderMacros(C);
  } catch (ex) { toast.show(ex.message || String(ex), "error"); }
});

// ---------------------------------------------------------- add dialog -----
async function openAdd(tab) {
  const pdk = state.selectedPdk || C.pdk;
  await customDialog({
    title: "Add a macro",
    wide: true,
    bodyHtml:
      "<div class='mc-tabs' role='tablist'>" +
      "<button class='mc-tab' data-t='pdk' role='tab'>" + icon("database", { size: 14 }) + " From the PDK</button>" +
      "<button class='mc-tab' data-t='run' role='tab'>" + icon("box", { size: 14 }) + " From another project</button>" +
      "<button class='mc-tab' data-t='files' role='tab'>" + icon("upload", { size: 14 }) + " Files</button></div>" +
      "<div class='mc-pane' data-p='pdk'></div><div class='mc-pane' data-p='run' hidden></div><div class='mc-pane' data-p='files' hidden></div>",
    buttons: [{ label: "Close", value: null, cls: "btn-ghost" }],
    onMount: (back, close) => {
      const show = (t) => {
        back.querySelectorAll(".mc-tab").forEach((b) => b.classList.toggle("is-on", b.dataset.t === t));
        back.querySelectorAll(".mc-pane").forEach((p) => { p.hidden = p.dataset.p !== t; });
        const pane = back.querySelector(".mc-pane[data-p='" + t + "']");
        if (!pane.dataset.done) { pane.dataset.done = "1"; ({ pdk: panePdk, run: paneRun, files: paneFiles })[t](pane, pdk, close); }
      };
      back.querySelector(".mc-tabs").addEventListener("click", (e) => { const b = e.target.closest(".mc-tab"); if (b) show(b.dataset.t); });
      show(["pdk", "run", "files"].includes(tab) ? tab : "pdk");
    },
  });
}

async function afterAdd(name, close) {
  close && close(null);
  await renderMacros(C);
  // Instantiated already? Then wire the instances and power for them.
  const found = ((D.inspect.scan || {}).instances || {})[name] || [];
  const m = D.macros.find((x) => x.name === name);
  const info = (D.inspect.macros || {})[name] || {};
  if (m && found.length && !(m.instances || []).length) {
    const patch = { instances: found.map((n) => ({ name: n, location: null, orientation: "N" })) };
    if (!m.power && info.ok && (info.power.vdd || []).length) patch.power = defaultPower(info);
    if (await saveMacro(name, patch)) {
      await renderMacros(C);
      const placed = dieBox() ? await arrange(true) : false;
      toast.show("Added " + name + ". Found it in your RTL as " + found.join(", ") +
        (placed ? " and gave it a position (drag it on the sketch to move it)." : ". Give it a position next."), "success", 7000);
    }
  } else {
    toast.show("Added " + name + ". Next: instantiate it in your RTL (template on its card).", "success", 6000);
  }
  document.getElementById("cl-macros")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function panePdk(pane, pdk, close) {
  const list = D.catalog;
  if (!list.length) { pane.innerHTML = "<p class='muted'>" + esc(pdk) + " ships no hard macros under libs.ref.</p>"; return; }
  const have = new Set(D.macros.map((m) => m.name));
  pane.innerHTML = "<p class='muted'>Ready-made blocks in the installed " + esc(pdk) + ". LanEx points at the PDK's files with <code>pdk_dir::</code> paths, so nothing is copied and the project stays portable.</p>" +
    "<div class='cl-tblwrap'><table class='cl-tbl mc-cat'><thead><tr><th>Block</th><th>Capacity</th><th>Ports</th><th>Size</th><th>Timing</th><th></th></tr></thead><tbody>" +
    list.map((m, k) => {
      const c = m.capacity || {};
      return "<tr><td><div class='mono'>" + esc(m.name) + "</div><div class='muted'>" + esc(m.library) + "</div></td>" +
        "<td>" + (c.words ? c.words + " × " + c.bits + " bit" + (c.kbits ? "<div class='muted'>" + (c.kbits >= 8 ? (c.kbits / 8) + " KB" : c.kbits + " kbit") + "</div>" : "") : "–") + "</td>" +
        "<td>" + esc(portsText(c.ports)) + "</td>" +
        "<td>" + fmtSize(m.w, m.h) + "<div class='muted'>" + M.fmtArea(m.w * m.h) + "</div></td>" +
        "<td>" + (m.lib_corner ? "<span title='" + esc(m.lib_corner) + "'>" + (m.corners > 1 ? m.corners + " corners" : "1 corner") + "</span>" : "<span class='cl-no'>none</span>") + "</td>" +
        "<td>" + (have.has(m.name) ? "<span class='muted'>added</span>" : "<button class='btn btn-sm btn-primary' data-k='" + k + "'>Add</button>") + "</td></tr>";
    }).join("") + "</tbody></table></div>";
  pane.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-k]");
    if (!b) return;
    const m = list[+b.dataset.k];
    b.disabled = true; b.textContent = "Adding…";
    try {
      await api.macroAdd({ design_dir: state.designDir, name: m.name,
        source: { kind: "pdk", pdk, library: m.library, views: m.views }, instances: [],
        power: m.power.vdd.length ? defaultPower({ power: m.power }) : null });
      afterAdd(m.name, close);
    } catch (ex) { toast.show(ex.message || String(ex), "error"); b.disabled = false; b.textContent = "Add"; }
  });
}

function portsText(p) {
  if (!p) return "–";
  if (/^1rw1r$/i.test(p)) return "1 read/write + 1 read";
  if (/^1rw$/i.test(p)) return "1 read/write";
  if (/^1P$/i.test(p)) return "single port";
  if (/^2P$/i.test(p)) return "dual port";
  return p;
}

async function paneRun(pane, pdk, close) {
  pane.innerHTML = "<p class='muted'><span class='spinner'></span> Looking through your projects…</p>";
  let res;
  try { res = await api.macroProjects(state.designDir); } catch (ex) { res = { projects: [] }; }
  const ps = (res && res.projects) || [];
  if (!ps.length) {
    pane.innerHTML = "<div class='an-none'>No other project has a finished run with GDS and LEF yet. The hierarchical flow: open the sub-block as its own project, run it to the end, come back here.</div>";
    return;
  }
  pane.innerHTML = "<p class='muted'>A finished run of another project becomes a block in this one: its final GDS, LEF, netlist, parasitics and timing models are copied into <code>macros/&lt;module&gt;/</code>, so cleaning the other project's runs can't break this one.</p>" +
    ps.map((p, i) => "<div class='mc-proj'><div class='mc-proj-h'>" + icon("folder", { size: 14 }) + " <b>" + esc(p.name) + "</b> <span class='muted mono'>" + esc(p.design_dir) + "</span></div>" +
      p.runs.map((r, k) => {
        const other = r.pdk && pdk && r.pdk !== pdk;
        return "<div class='mc-run'><span class='vf-mark is-" + (r.success ? "pass" : "warn") + "'></span>" +
          "<span class='mono'>" + esc(r.module) + "</span><span class='muted'>" + esc(r.tag) + (r.when ? " · " + esc(String(r.when).slice(0, 16).replace("T", " ")) : "") + "</span>" +
          "<span class='mc-run-v'>" + r.views.map((v) => "<span class='cc-chip'>" + esc(v) + "</span>").join("") + "</span>" +
          (other ? "<span class='cl-warn-t'>built for " + esc(r.pdk) + "</span>" : "") +
          "<button class='btn btn-sm btn-primary' data-p='" + i + "' data-r='" + k + "'" + (other ? " disabled title='Different PDK'" : "") + ">Use</button></div>";
      }).join("") + "</div>").join("");
  pane.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-r]");
    if (!b) return;
    const p = ps[+b.dataset.p], r = p.runs[+b.dataset.r];
    b.disabled = true; b.textContent = "Copying…";
    try {
      const res2 = await api.macroAdd({ design_dir: state.designDir, source: { kind: "run", design_dir: p.design_dir, tag: r.tag }, instances: [] });
      afterAdd((res2.macro && res2.macro.name) || r.module, close);
    } catch (ex) { toast.show(ex.message || String(ex), "error"); b.disabled = false; b.textContent = "Use"; }
  });
}

const KIND_OF = (n) => {
  const f = n.toLowerCase();
  if (/\.gds(\.gz)?$/.test(f)) return "gds";
  if (/\.lef$/.test(f)) return "lef";
  if (/\.lib$/.test(f)) return "lib";
  if (/\.spef$/.test(f)) return "spef";
  if (/\.(spice|sp|cir|cdl)$/.test(f)) return "spice";
  if (/\.nl\.v$|_nl\.v$|netlist/.test(f)) return "nl";
  if (/\.(v|sv|vh)$/.test(f)) return "vh";
  return null;
};
const KIND_LABEL = { gds: "GDS layout", lef: "LEF abstract", lib: "Liberty timing", spef: "SPEF parasitics", spice: "SPICE/CDL for LVS", nl: "Gate-level netlist", vh: "Verilog model (black box)" };

function paneFiles(pane, _pdk, close) {
  const files = {};
  pane.innerHTML = "<label class='mc-drop' tabindex='0'><input type='file' multiple hidden>" + icon("upload", { size: 22 }) +
    "<b>Drop the macro's files here, or click to pick them</b><span>GDS and LEF are required. Add the Liberty file so STA can time it, and SPICE/CDL so LVS passes.</span></label>" +
    "<div class='mc-files'></div>" +
    "<label class='mc-fname'>Module name <input class='mono' id='mc-up-name' placeholder='read from the LEF' spellcheck='false'></label>" +
    "<div class='mc-up-act'><button class='btn btn-primary btn-sm' id='mc-up-save' disabled>Add macro</button><span class='muted' id='mc-up-msg'></span></div>";
  const drop = pane.querySelector(".mc-drop"), input = drop.querySelector("input");
  const paintFiles = () => {
    const ks = Object.keys(files);
    pane.querySelector(".mc-files").innerHTML = ks.map((k) => "<div class='mc-file'><span class='cc-chip'>" + k + "</span> " + esc(files[k].name) +
      " <span class='muted'>" + esc(KIND_LABEL[k]) + " · " + (files[k].size / 1024).toFixed(0) + " KB</span></div>").join("");
    pane.querySelector("#mc-up-save").disabled = !(files.gds && files.lef && pane.querySelector("#mc-up-name").value.trim());
  };
  const take = async (list) => {
    for (const f of list) {
      const k = KIND_OF(f.name);
      if (!k) { toast.show("Skipped " + f.name + ": not a macro view", "warn"); continue; }
      files[k] = f;
      if (k === "lef") {
        const txt = await f.text();
        const m = txt.match(/^\s*MACRO\s+(\S+)/m);
        const nm = pane.querySelector("#mc-up-name");
        if (m && !nm.value) nm.value = m[1];
      }
    }
    paintFiles();
  };
  drop.addEventListener("click", (e) => { if (e.target !== input) input.click(); });
  input.addEventListener("change", () => take([...input.files]));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("is-over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("is-over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("is-over"); take([...e.dataTransfer.files]); });
  pane.querySelector("#mc-up-name").addEventListener("input", paintFiles);
  pane.querySelector("#mc-up-save").addEventListener("click", async (e) => {
    const b = e.target;
    const name = pane.querySelector("#mc-up-name").value.trim();
    b.disabled = true; b.textContent = "Uploading…";
    try {
      const views = {};
      for (const [k, f] of Object.entries(files)) views[k] = { filename: f.name, content_b64: await b64(f) };
      await api.customMacroSave({ design_dir: state.designDir, name, instances: [], views, enabled: true });
      afterAdd(name, close);
    } catch (ex) {
      pane.querySelector("#mc-up-msg").textContent = ex.message || String(ex);
      b.disabled = false; b.textContent = "Add macro";
    }
  });
}

function b64(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onerror = () => reject(new Error("could not read " + file.name));
    r.onload = () => { const s = String(r.result || ""); resolve(s.slice(s.indexOf(",") + 1)); };
    r.readAsDataURL(file);
  });
}

// ---------------------------------------------------------- arranging ------
// LibreLane 3's Classic flow only runs Odb.ManualMacroPlacement, so LanEx
// proposes positions: bottom-left first fit inside the die, keeping each
// block's halo plus a margin for the IO ring, around blocks already placed.
function macroSize(m, orient) {
  const info = (D.inspect.macros || {})[m.name] || {};
  if (!info.ok) return null;
  const rot = /^(E|W|FE|FW)$/.test(orient || "N");
  return rot ? [info.h, info.w] : [info.w, info.h];
}

function haloOf() {
  return { h: D.settings.halo_h != null ? D.settings.halo_h : 10, v: D.settings.halo_v != null ? D.settings.halo_v : 10 };
}

function suggestDie() {
  const halo = haloOf();
  let area = 0, maxW = 0, maxH = 0;
  for (const m of D.macros) {
    if (m.enabled === false) continue;
    for (const i of (m.instances && m.instances.length ? m.instances : [{ orientation: "N" }])) {
      const sz = macroSize(m, i.orientation);
      if (!sz) continue;
      area += (sz[0] + 2 * halo.h) * (sz[1] + 2 * halo.v);
      maxW = Math.max(maxW, sz[0] + 2 * halo.h); maxH = Math.max(maxH, sz[1] + 2 * halo.v);
    }
  }
  if (!area) return null;
  // macros at about half the core, room for the cells and the IO ring
  const side = Math.sqrt(area * 2) + 60;
  const r10 = (v) => Math.ceil(v / 10) * 10;
  return [r10(Math.max(side, maxW + 100)), r10(Math.max(side, maxH + 100))];
}

async function arrange(quiet) {
  const die = dieBox();
  if (!die) { if (!quiet) toast.show("Set a die size first (FP_SIZING absolute + DIE_AREA): there is nothing to place against.", "warn", 6000); return false; }
  const [x0, y0, x1, y1] = die.box;
  const halo = haloOf();
  const MARGIN = 20;                              // IO ring / core margin
  const taken = [];
  const todo = [];
  for (const m of D.macros) {
    if (m.enabled === false) continue;
    for (const i of m.instances || []) {
      const sz = macroSize(m, i.orientation);
      if (!sz) continue;
      if (Array.isArray(i.location)) taken.push([+i.location[0] - halo.h, +i.location[1] - halo.v, sz[0] + 2 * halo.h, sz[1] + 2 * halo.v]);
      else todo.push({ m, i, w: sz[0], h: sz[1] });
    }
  }
  if (!todo.length) { if (!quiet) toast.show("Every macro already has a position.", "info"); return false; }
  todo.sort((a, b) => b.w * b.h - a.w * a.h);
  const hit = (r) => taken.some((t) => r[0] < t[0] + t[2] && t[0] < r[0] + r[2] && r[1] < t[1] + t[3] && t[1] < r[1] + r[3]);
  const step = Math.max(2, Math.round(Math.min(x1 - x0, y1 - y0) / 200));
  const failed = [];
  for (const t of todo) {
    let spot = null;
    for (let y = y0 + MARGIN + halo.v; !spot && y + t.h + halo.v <= y1 - MARGIN; y += step) {
      for (let x = x0 + MARGIN + halo.h; x + t.w + halo.h <= x1 - MARGIN; x += step) {
        const r = [x - halo.h, y - halo.v, t.w + 2 * halo.h, t.h + 2 * halo.v];
        if (!hit(r)) { spot = [Math.round(x), Math.round(y)]; taken.push(r); break; }
      }
    }
    if (spot) t.i.location = spot; else failed.push(t.i.name);
  }
  for (const m of D.macros) {
    if (!todo.some((t) => t.m === m && Array.isArray(t.i.location))) continue;
    if (!(await saveMacro(m.name, { instances: m.instances }))) return false;
  }
  if (failed.length) toast.show("No room in the die for " + failed.join(", ") + ". Make the die bigger or shrink the halo.", "error", 8000);
  else if (!quiet) toast.show("Placed " + todo.length + " macro instance" + (todo.length === 1 ? "" : "s") + ". Drag them on the sketch to adjust.", "success");
  await renderMacros(C);
  return !failed.length;
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-mc-setdie]");
  if (!b) return;
  const die = suggestDie();
  if (!die) return;
  b.disabled = true;
  try {
    await api.configSet({ FP_SIZING: "absolute", DIE_AREA: [0, 0, die[0], die[1]] }, []);
    document.dispatchEvent(new CustomEvent("g:config_changed", { detail: { keys: ["FP_SIZING", "DIE_AREA"] } }));
    await renderMacros(C);
    await arrange(true);
    toast.show("Die set to " + die.join(" × ") + " µm (absolute sizing). Macros placed inside it.", "success", 6000);
  } catch (ex) { toast.show("Couldn't save: " + (ex.message || ex), "error"); b.disabled = false; }
});
