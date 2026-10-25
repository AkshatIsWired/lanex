// projectcard.js — the Design row on the Setup page's project card: top
// module, clock port and clock period. They are read from the project's config
// file and saved straight back to it (key by key, server side), so what this
// row shows is what LibreLane runs, from LanEx or from a terminal.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";

let _info = null;
let _seq = 0;
const $ = (id) => document.getElementById(id);

function mhz(ns) {
  const n = parseFloat(ns);
  if (!(n > 0)) return "";
  const f = 1000 / n;
  return (f >= 100 ? f.toFixed(0) : f.toFixed(1).replace(/\.0$/, "")) + " MHz";
}

function option(value, label, selected) {
  return "<option value='" + fmt.escape(value) + "'" + (selected ? " selected" : "") + ">" + fmt.escape(label) + "</option>";
}

function status(html, kind) {
  const el = $("pd-status");
  if (!el) return;
  el.innerHTML = html || "";
  el.className = "pd-status" + (kind ? " is-" + kind : "");
}

// A pdk::/scl:: section of the config that sets the same key wins for a
// matching PDK; say so next to the field rather than let an edit look ignored.
function scopedNotes(info) {
  const out = [];
  const names = { DESIGN_NAME: "top module", CLOCK_PORT: "clock port", CLOCK_PERIOD: "clock period" };
  for (const [key, entries] of Object.entries(info.scoped || {})) {
    for (const e of entries) {
      if (e.applies === false) continue;
      const v = key === "CLOCK_PERIOD" ? e.value + " ns" : String(e.value);
      out.push("The <code>" + fmt.escape(e.scope) + "</code> section of " + fmt.escape(info.config.name) +
        " sets the " + names[key] + " to <b>" + fmt.escape(v) + "</b>" +
        (e.applies ? " for this PDK, and that wins over the value here." : " for matching PDKs."));
    }
  }
  return out;
}

function overrideNotes() {
  const v = state.varsValues || {};
  const out = [];
  if (v.CLOCK_PERIOD !== undefined && v.CLOCK_PERIOD !== null && String(v.CLOCK_PERIOD).trim() !== "") {
    out.push("All settings overrides the clock period for runs from LanEx: <b>" + fmt.escape(v.CLOCK_PERIOD) + " ns</b>.");
  }
  return out;
}

export async function paintDesignRow() {
  const box = $("proj-design");
  if (!box) return;
  // The Settings card reads the same config; keep it in step.
  import("./mostused.js").then((m) => m.paintSettings()).catch(() => {});
  if (!state.designDir) { _info = null; return; }
  const seq = ++_seq;
  let info;
  try {
    info = await api.designInfo({
      files: (state.selectedFiles || []).filter((f) => /\.(s?v|verilog)$/i.test(f)),
      pdk: state.selectedPdk || null, scl: state.selectedScl || null,
    });
  } catch (ex) {
    if (seq === _seq) status("Couldn't read the design: " + fmt.escape(ex.message || ex), "warn");
    return;
  }
  if (seq !== _seq) return;
  _info = info;
  const vals = info.values || {};
  const editable = !!(info.config && info.config.editable);

  // Top module: the modules in the ticked files; the config's value stays
  // selectable (and flagged) even when no ticked file declares it.
  const top = typeof vals.DESIGN_NAME === "string" ? vals.DESIGN_NAME : "";
  const mods = (info.modules || []).slice();
  let topHtml = mods.map((m) => option(m, m, m === top)).join("");
  if (top && !mods.includes(top)) topHtml = option(top, top + " (not in the ticked files)", true) + topHtml;
  if (!top) topHtml = option("", mods.length ? "Choose…" : "No modules found", true) + topHtml;
  $("pd-top").innerHTML = topHtml;

  // Clock: the top module's inputs (single-bit first), or no clock at all.
  const cp = vals.CLOCK_PORT;
  const multi = Array.isArray(cp) && cp.length > 1;
  const clock = Array.isArray(cp) ? (cp[0] || "") : (cp || "");
  const inputs = (info.ports || []).filter((p) => p.dir === "input");
  inputs.sort((a, b) => Number(a.bus) - Number(b.bus));
  let clkHtml = inputs.map((p) => option(p.name, p.name + (p.bus ? " (bus)" : ""), p.name === clock)).join("");
  if (clock && !inputs.some((p) => p.name === clock)) clkHtml = option(clock, clock + " (not a port of the top)", true) + clkHtml;
  clkHtml += option("", "No clock (combinational)", !clock);
  $("pd-clock").innerHTML = clkHtml;

  const per = $("pd-period");
  per.value = vals.CLOCK_PERIOD != null ? vals.CLOCK_PERIOD : "";
  $("pd-mhz").textContent = mhz(per.value);
  // Each value's line in the config file, one click away.
  import("./provenance.js").then((m) => m.paintConfigSrc(box, (k) => vals[k] !== undefined && vals[k] !== null && vals[k] !== "")).catch(() => {});

  $("pd-top").disabled = !editable;
  $("pd-clock").disabled = !editable || multi;
  per.disabled = !editable;

  const notes = [];
  if (!editable) notes.push(fmt.escape(info.config.reason || "LanEx can't edit this config."));
  if (multi) notes.push("This design has several clocks (" + fmt.escape(cp.join(", ")) + "). Change them in " + fmt.escape(info.config.name) + ".");
  if (top && !mods.includes(top)) notes.push("No ticked file declares <code>" + fmt.escape(top) + "</code>. Tick its file below or choose another top module.");
  if (clock && !inputs.some((p) => p.name === clock) && inputs.length) notes.push("<code>" + fmt.escape(clock) + "</code> isn't an input of the top module.");
  notes.push(...scopedNotes(info), ...overrideNotes());
  status(notes.join("<br>"), notes.length ? "warn" : "");

  // The file that declares the top gets a "top" tag in Sources.
  const file = (info.module_files || {})[top] || null;
  import("./fs.js").then((m) => m.setTopFile(file)).catch(() => {});
}

async function save(set, remove, what) {
  try {
    const r = await api.configSet(set, remove, { pdk: state.selectedPdk || null, scl: state.selectedScl || null });
    // A Constraints override for the same key would silently win: drop it.
    for (const k of Object.keys(set).concat(remove || [])) {
      if (state.varsValues && k in state.varsValues) delete state.varsValues[k];
    }
    if (r.changed && r.changed.length) toast.show("Saved the " + what + " to " + r.name + ".", "success", 2200);
    document.dispatchEvent(new CustomEvent("g:config_changed"));
  } catch (ex) {
    toast.show("Couldn't save the " + what + ": " + (ex.message || ex), "error", 7000);
  }
  await paintDesignRow();
}

export function wireDesignRow() {
  $("pd-top")?.addEventListener("change", (e) => {
    if (e.target.value) save({ DESIGN_NAME: e.target.value }, [], "top module");
  });
  $("pd-clock")?.addEventListener("change", (e) => {
    const v = e.target.value;
    if (v) save({ CLOCK_PORT: v }, [], "clock port");
    else save({}, ["CLOCK_PORT"], "clock setting");
  });
  const per = $("pd-period");
  per?.addEventListener("input", () => { $("pd-mhz").textContent = mhz(per.value); });
  per?.addEventListener("change", () => {
    const n = parseFloat(per.value);
    if (!(n > 0)) {
      toast.show("The clock period is a positive number of nanoseconds.", "warn");
      paintDesignRow();
      return;
    }
    save({ CLOCK_PERIOD: n }, [], "clock period");
  });
  per?.addEventListener("keydown", (e) => { if (e.key === "Enter") per.blur(); });
  // Anything else that changes the config (Sources ticks, a new SDC) can
  // change the modules or the scoped values shown here.
  document.addEventListener("g:config_changed", () => {
    import("./config.js").then((m) => m.renderConfig()).catch(() => {});
    import("./preflight.js").then((m) => m.renderPreflight()).catch(() => {});
  });
}
