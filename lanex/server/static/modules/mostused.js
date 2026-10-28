// mostused.js — the Setup page's Settings card: the few LibreLane variables
// real projects change (the die size, placement density, synthesis goal,
// hold margins, routing layers, antenna diodes, Verilog defines, the
// SystemVerilog frontend), each with a line on when to change it. Values are
// read from the project's config file and saved straight back to it, key by
// key (server side, controller/configedit.py), like the top/clock row: what
// this card shows is what a terminal run of the same config builds.
//
// Everything else stays in All settings (config.js), whose values are
// per-run overrides that leave the config file alone.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { pdkFacts } from "./pdkinfo.js";
import { provBtnHtml, wireProvBtns } from "./provenance.js";

const SYNTH = [
  ["AREA 0", "AREA 0 · small, fast to build"],
  ["AREA 1", "AREA 1"],
  ["AREA 2", "AREA 2"],
  ["AREA 3", "AREA 3 · smallest"],
  ["DELAY 0", "DELAY 0 · faster logic"],
  ["DELAY 1", "DELAY 1"],
  ["DELAY 2", "DELAY 2"],
  ["DELAY 3", "DELAY 3 · fastest, biggest"],
];

// kind: num | int | select | bool | list | area | layer.
// def: LibreLane's default as shown; null = the PDK or the flow decides.
const GROUPS = [
  {
    name: "Chip size",
    items: [
      { key: "FP_SIZING", label: "Die size from", kind: "select", def: "relative",
        choices: [["relative", "Utilization (sized for you)"], ["absolute", "A fixed die area"]],
        hint: "Utilization sizes the die from the design and grows with it. A very small design needs a fixed die: on a tiny one, placement fails with DPL-0036." },
      { key: "FP_CORE_UTIL", label: "Core utilization", kind: "num", unit: "%", def: 50, min: 1, max: 99,
        when: (v) => v.FP_SIZING !== "absolute",
        hint: "How full the core is with cells. Lower it if routing is congested; raise it for a smaller die." },
      { key: "DIE_AREA", label: "Die area", kind: "area", unit: "µm", def: null, ph: "0 0 200 200",
        when: (v) => v.FP_SIZING === "absolute",
        hint: "x0 y0 x1 y1 in microns. New blank projects start at 0 0 150 150. If placement reports the design doesn't fit, make it bigger or switch to utilization." },
      { key: "PL_TARGET_DENSITY_PCT", label: "Placement density", kind: "num", unit: "%", def: null, min: 1, max: 100,
        defText: "auto",
        hint: "How tightly cells are packed (auto: utilization + 10). Raise it if global placement fails with GPL-0301; lower it if routing is congested." },
    ],
  },
  {
    name: "Synthesis",
    items: [
      { key: "SYNTH_STRATEGY", label: "Synthesis goal", kind: "select", def: "AREA 0", choices: SYNTH,
        hint: "AREA gives a smaller netlist. Try DELAY 1 to 3 when setup timing fails and the clock can't slow down." },
      { key: "VERILOG_DEFINES", label: "Defines", kind: "list", def: null, ph: "WIDTH=8, USE_FAST_ADDER",
        hint: "`define values, as NAME or NAME=value, separated by commas." },
      { key: "USE_SLANG", label: "SystemVerilog frontend", kind: "bool", def: false,
        hint: "Turn on if synthesis can't read your SystemVerilog (packages, interfaces, structs)." },
    ],
  },
  {
    name: "Timing fixes",
    note: "Setup violations: raise the clock period on the project card, or pick a DELAY synthesis goal.",
    items: [
      { key: "PL_RESIZER_HOLD_SLACK_MARGIN", label: "Hold margin, placement", kind: "num", unit: "ns", def: 0.1, step: 0.05,
        hint: "Raise both hold margins if the run ends with hold violations." },
      { key: "GRT_RESIZER_HOLD_SLACK_MARGIN", label: "Hold margin, routing", kind: "num", unit: "ns", def: 0.05, step: 0.05 },
      { key: "MAX_FANOUT_CONSTRAINT", label: "Max fanout", kind: "int", def: null, defText: "PDK default", min: 1,
        hint: "The most inputs one output may drive. Lower it to speed up heavily loaded nets." },
    ],
  },
  {
    name: "Routing and antenna",
    items: [
      { key: "RT_MAX_LAYER", label: "Top routing layer", kind: "layer", def: null, defText: "PDK default",
        hint: "Keep signal routing below a layer, for a block that sits under a parent's power grid." },
      { key: "DIODE_ON_PORTS", label: "Antenna diodes on ports", kind: "select", def: "none",
        choices: [["none", "none"], ["in", "inputs"], ["out", "outputs"], ["both", "inputs and outputs"]],
        hint: "Add diodes on I/O nets when the antenna check reports violations there." },
    ],
  },
];
const ITEMS = GROUPS.flatMap((g) => g.items);
const KEYS = ITEMS.map((i) => i.key);

let _vals = {};
let _scoped = {};
let _cfg = null;
let _seq = 0;
const $ = (id) => document.getElementById(id);

function shown(v) {
  if (v === null || v === undefined) return "";
  if (Array.isArray(v)) return v.join(v.length === 4 && v.every((x) => typeof x === "number") ? " " : ", ");
  return String(v);
}

function defLabel(it) {
  if (it.defText) return it.defText;
  if (it.def === null || it.def === undefined) return "";
  if (it.kind === "bool") return it.def ? "on" : "off";
  if (it.kind === "select") {
    const c = (it.choices || []).find((x) => x[0] === it.def);
    return c ? c[1].split(" · ")[0] : String(it.def);
  }
  return String(it.def) + (it.unit ? " " + it.unit : "");
}

function metals(pdk) {
  // The routing layers of the selected process (met1…, Metal1…, TopMetal…).
  return (pdkFacts(pdk).stack || []).filter((l) => /^(met\d|metal\d|topmetal\d)/i.test(l));
}

function control(it, id, val) {
  const cur = shown(val);
  const blank = "<option value=''" + (cur === "" ? " selected" : "") + ">Default: " + fmt.escape(defLabel(it) || "flow decides") + "</option>";
  if (it.kind === "select" || it.kind === "bool" || it.kind === "layer") {
    let choices = it.choices || [];
    if (it.kind === "bool") choices = [["true", "on"], ["false", "off"]];
    if (it.kind === "layer") choices = metals(state.selectedPdk).map((m) => [m, m]);
    const curStr = it.kind === "bool" && val !== undefined && val !== null ? String(!!val && val !== "false" && val !== 0) : cur;
    // Keep a value the file sets that isn't in the list (another PDK's layer).
    if (curStr && !choices.some((c) => c[0] === curStr)) choices = choices.concat([[curStr, curStr]]);
    return "<select id='" + id + "'>" + blank + choices.map((c) =>
      "<option value='" + fmt.escape(c[0]) + "'" + (c[0] === curStr ? " selected" : "") + ">" + fmt.escape(c[1]) + "</option>").join("") +
      "</select>";
  }
  const num = it.kind === "num" || it.kind === "int";
  const ph = it.ph ? it.ph : defLabel(it) ? "Default: " + defLabel(it).replace(/ (%|ns|µm)$/, "") : "";
  return "<input id='" + id + "' type='" + (num ? "number" : "text") + "'" +
    (num && it.min !== undefined ? " min='" + it.min + "'" : "") +
    (num && it.max !== undefined ? " max='" + it.max + "'" : "") +
    (num ? " step='" + (it.step || (it.kind === "int" ? 1 : "any")) + "' inputmode='decimal'" : " spellcheck='false' autocomplete='off'") +
    " value='" + fmt.escape(cur) + "' placeholder='" + fmt.escape(ph) + "'/>";
}

function notesFor(it) {
  const out = [];
  for (const e of _scoped[it.key] || []) {
    if (e.applies === false) continue;
    out.push("The <code>" + fmt.escape(e.scope) + "</code> section of " + fmt.escape(_cfg.name) + " sets <b>" +
      fmt.escape(shown(e.value)) + "</b>" + (e.applies ? " for this PDK, and that wins over this field." : " for matching PDKs."));
  }
  const ov = (state.varsValues || {})[it.key];
  if (ov !== undefined && ov !== null && String(ov).trim() !== "") {
    out.push("All settings overrides this for runs from LanEx: <b>" + fmt.escape(String(ov)) + "</b>.");
  }
  if (it.key === "DIE_AREA" && _vals.FP_SIZING === "absolute" && !shown(_vals.DIE_AREA)) {
    out.push("A fixed die needs its area.");
  }
  return out;
}

function fieldHtml(it) {
  const id = "ms-" + it.key;
  const val = _vals[it.key];
  const set = val !== undefined && val !== null && shown(val) !== "";
  const notes = notesFor(it);
  return "<div class='ms-field" + (set ? " is-set" : "") + "' data-key='" + it.key + "'>" +
    "<div class='ms-top'><label for='" + id + "'>" + fmt.escape(it.label) + "</label>" +
    "<span class='ms-keyrow'><code class='ms-key' title='The LibreLane variable " + it.key + "'>" + it.key + "</code>" +
    // The config's line for a value it sets; a default has no line to show.
    (set ? provBtnHtml({ kind: "input", key: it.key }, "Show the line of " + ((_cfg && _cfg.name) || "the config") + " that sets " + it.key) : "") + "</span></div>" +
    // control | unit | reset: every field keeps all three slots, so the
    // controls in a group line up and are the same width.
    "<div class='ms-ctl'>" + control(it, id, val) + "<em class='ms-unit'>" + fmt.escape(it.unit || "") + "</em>" +
    "<button type='button' class='ms-reset' data-reset='" + it.key + "' title='Remove from " +
    fmt.escape((_cfg && _cfg.name) || "the config") + " and use the default'" + (set ? "" : " hidden") +
    " aria-label='Reset " + it.key + " to its default'><svg viewBox='0 0 24 24' width='14' height='14' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M3 12a9 9 0 1 0 3-6.7M3 4v5h5'/></svg></button></div>" +
    (it.hint ? "<small class='ms-hint'>" + fmt.escape(it.hint) + "</small>" : "") +
    (notes.length ? "<small class='ms-note'>" + notes.join("<br>") + "</small>" : "") +
    "</div>";
}

function render() {
  const body = $("ms-body");
  if (!body) return;
  const where = $("ms-where");
  if (!state.designDir) {
    body.innerHTML = "<p class='muted'>Open a project to see its settings.</p>";
    if (where) where.textContent = "";
    return;
  }
  const editable = !!(_cfg && _cfg.editable);
  if (where) {
    where.innerHTML = _cfg && _cfg.name
      ? (editable ? "Saved in <code>" + fmt.escape(_cfg.name) + "</code>" : "<span class='is-warn'>Read only</span>")
      : "";
  }
  body.innerHTML =
    (!editable ? "<p class='ms-ro'>" + fmt.escape((_cfg && _cfg.reason) || "LanEx can't edit this project's config.") +
      " Use All settings to change values for runs from LanEx.</p>" : "") +
    "<div class='ms-groups'>" + GROUPS.map((g) =>
      "<section class='ms-group'><span class='lane-label'>" + fmt.escape(g.name) + "</span>" +
      g.items.filter((it) => !it.when || it.when(_vals)).map(fieldHtml).join("") +
      (g.note ? "<p class='ms-gnote'>" + fmt.escape(g.note) + "</p>" : "") +
      "</section>").join("") + "</div>";
  body.querySelectorAll("input, select").forEach((el) => { el.disabled = !editable; });
  wireProvBtns(body);
  paintSummary();
}

// The folded card's bar: what is set, in a line, so the card can stay closed.
function shortVal(it, v) {
  if (it.kind === "select") {
    const c = (it.choices || []).find((x) => x[0] === String(v));
    return c ? c[1].split(" · ")[0].split(" (")[0] : shown(v);
  }
  if (it.kind === "bool") return v && v !== "false" ? "on" : "off";
  return shown(v) + (it.unit ? " " + it.unit : "");
}

function paintSummary() {
  const line = $("ms-sum-line"), count = $("ms-count");
  if (!line || !count) return;
  if (!state.designDir) {
    line.textContent = "The handful of settings most designs change, saved in the project's config.";
    count.hidden = true;
    return;
  }
  const set = ITEMS.filter((it) => (!it.when || it.when(_vals)) && _vals[it.key] !== undefined && _vals[it.key] !== null && shown(_vals[it.key]) !== "");
  count.hidden = false;
  count.textContent = set.length ? set.length + " set" : "defaults";
  count.classList.toggle("is-set", set.length > 0);
  line.innerHTML = set.length
    ? set.slice(0, 4).map((it) => "<span class='ms-chip'><b>" + fmt.escape(it.label) + "</b> " + fmt.escape(shortVal(it, _vals[it.key])) + "</span>").join("") +
      (set.length > 4 ? "<span class='ms-chip is-more'>+" + (set.length - 4) + " more</span>" : "")
    : "All " + ITEMS.filter((it) => !it.when || it.when(_vals)).length + " at LibreLane's defaults. Open to change the die size, density, synthesis goal, hold margins and more.";
}

export async function paintSettings() {
  if (!$("ms-body")) return;
  if (!state.designDir) { _cfg = null; render(); return; }
  const seq = ++_seq;
  try {
    const info = await api.designInfo({
      files: (state.selectedFiles || []).filter((f) => /\.(s?v|verilog)$/i.test(f)),
      pdk: state.selectedPdk || null, scl: state.selectedScl || null, keys: KEYS,
    });
    if (seq !== _seq) return;
    _cfg = info.config || null;
    _vals = info.settings || {};
    _scoped = info.settings_scoped || {};
  } catch (ex) {
    if (seq !== _seq) return;
    $("ms-body").innerHTML = "<p class='ms-ro'>Couldn't read the settings: " + fmt.escape(ex.message || ex) + "</p>";
    return;
  }
  render();
}

function parse(it, raw) {
  const s = String(raw).trim();
  if (s === "") return { remove: true };
  if (it.kind === "num" || it.kind === "int") {
    const n = it.kind === "int" ? parseInt(s, 10) : parseFloat(s);
    if (!Number.isFinite(n) || (it.min !== undefined && n < it.min) || (it.max !== undefined && n > it.max)) {
      return { error: it.label + " takes a number" + (it.min !== undefined && it.max !== undefined ? " from " + it.min + " to " + it.max : "") + "." };
    }
    return { value: n };
  }
  if (it.kind === "bool") return { value: s === "true" };
  if (it.kind === "list") return { value: s.split(/[,\s]+/).filter(Boolean) };
  if (it.kind === "area") {
    const nums = s.split(/[,\s]+/).filter(Boolean).map(Number);
    if (nums.length !== 4 || nums.some((n) => !Number.isFinite(n)) || nums[2] <= nums[0] || nums[3] <= nums[1]) {
      return { error: "The die area is four numbers, x0 y0 x1 y1 in µm, like 0 0 200 200." };
    }
    return { value: nums };
  }
  return { value: s };
}

async function save(key, set, remove) {
  try {
    const r = await api.configSet(set, remove, { pdk: state.selectedPdk || null, scl: state.selectedScl || null });
    // An All settings override for the same key would silently win: drop it.
    if (state.varsValues && key in state.varsValues) delete state.varsValues[key];
    if (r.changed && r.changed.length) {
      toast.show((remove.length ? "Removed " + key + " from " : "Saved " + key + " to ") + r.name + ".", "success", 2200);
    }
    document.dispatchEvent(new CustomEvent("g:config_changed"));
  } catch (ex) {
    toast.show("Couldn't save " + key + ": " + (ex.message || ex), "error", 7000);
  }
  await paintSettings();
}

export function wireSettings() {
  const body = $("ms-body");
  if (!body || body._wired) return;
  body._wired = true;
  body.addEventListener("change", (e) => {
    const f = e.target.closest(".ms-field");
    const it = f && ITEMS.find((x) => x.key === f.dataset.key);
    if (!it) return;
    const p = parse(it, e.target.value);
    if (p.error) { toast.show(p.error, "warn"); render(); return; }
    if (p.remove) save(it.key, {}, [it.key]);
    else save(it.key, { [it.key]: p.value }, []);
  });
  body.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.tagName === "INPUT") e.target.blur();
  });
  body.addEventListener("click", (e) => {
    const b = e.target.closest("[data-reset]");
    if (b) save(b.dataset.reset, {}, [b.dataset.reset]);
  });
  document.querySelector("#setup-settings [data-jump-to]")?.addEventListener("click", (e) => {
    document.querySelector('#setup-jump [data-jump="' + e.currentTarget.dataset.jumpTo + '"]')?.click();
  });
  // Folded by default; the choice is remembered.
  const card = $("setup-settings");
  if (card && card.tagName === "DETAILS" && !card._wired) {
    card._wired = true;
    try { card.open = localStorage.getItem("ll.commonSettings") === "open"; } catch (_e) {}
    card.addEventListener("toggle", () => {
      try { localStorage.setItem("ll.commonSettings", card.open ? "open" : "closed"); } catch (_e) {}
    });
  }
}
