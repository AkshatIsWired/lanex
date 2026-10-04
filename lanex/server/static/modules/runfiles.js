// runfiles.js — the Layout tab's "Run files" drawer: every deliverable in
// final/, any design format as raw text, and the Yosys synthesis diagrams.
// (These used to be the Preview tab. They are run artefacts, not the layout,
// so they sit in a drawer under the viewer and load only when it is opened.)

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { icon } from "./icons.js";
import { fileActionsHtml, wireFileActions } from "./fileview.js";

const _CAT_ICON = { Layout: "grid", Netlist: "plug", Timing: "clock", Reports: "chart", Other: "box" };
const DL_SVG = "<svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M12 3v12M7 11l5 4 5-4M5 21h14'/></svg>";

let _tag = "";
let _loaded = { outputs: "", raw: "", diagrams: "" };
let _pane = "outputs";
let _wired = false;
let _epoch = 0;

function fmtBytes(n) {
  if (!n) return "0 B";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}

function root() { return document.getElementById("lx-files"); }

// Called whenever the Layout tab's run changes. Cheap when the drawer is shut.
export function setRunFilesTag(tag) {
  _tag = tag || "";
  const r = root();
  if (!r) return;
  wire(r);
  if (r.open) load(_pane);
}

function wire(r) {
  if (_wired) return;
  _wired = true;
  r.addEventListener("toggle", () => { if (r.open) load(_pane); });
  r.querySelectorAll("[data-rf-pane]").forEach((b) => b.addEventListener("click", () => {
    _pane = b.dataset.rfPane;
    r.querySelectorAll("[data-rf-pane]").forEach((x) => {
      const on = x === b;
      x.classList.toggle("is-on", on);
      x.setAttribute("aria-selected", on ? "true" : "false");
    });
    r.querySelectorAll(".rf-pane").forEach((p) => { p.hidden = p.id !== "rf-" + _pane; });
    load(_pane);
  }));
  document.getElementById("rf-format")?.addEventListener("change", () => { _loaded.raw = ""; load("raw"); });
}

function load(pane) {
  if (!_tag) {
    for (const id of ["rf-outputs", "rf-diagrams"]) {
      const el = document.getElementById(id);
      if (el) el.innerHTML = "<div class='muted'>Pick a run above.</div>";
    }
    return;
  }
  if (_loaded[pane] === _tag) return;
  _loaded[pane] = _tag;
  if (pane === "outputs") renderOutputs(_tag);
  else if (pane === "raw") renderRaw(_tag);
  else if (pane === "diagrams") renderDiagrams(_tag, ++_epoch);
}

// ---------------------------------------------------------------- outputs
async function renderOutputs(tag) {
  const el = document.getElementById("rf-outputs");
  if (!el) return;
  el.innerHTML = "<div class='muted'>Loading output files…</div>";
  let outs = [];
  try { outs = ((await api.runOutputs(tag)) || {}).outputs || []; }
  catch (_e) { el.innerHTML = "<div class='muted'>Could not list this run's output files.</div>"; return; }
  if (tag !== _tag) return;
  if (!outs.length) {
    el.innerHTML = "<div class='muted'>No files in <code>final/</code>. This run stopped before the end of the flow.</div>";
    return;
  }
  const groups = new Map();
  for (const o of outs) {
    if (!groups.has(o.category)) groups.set(o.category, []);
    groups.get(o.category).push(o);
  }
  let html = "";
  for (const [cat, items] of groups) {
    html += "<div class='rf-cat'><div class='rf-cat-h'>" + icon(_CAT_ICON[cat] || "box", { size: 14 }) +
      " <strong>" + fmt.escape(cat) + "</strong><span class='muted'>" + items.length + "</span></div>" +
      items.map((o) =>
        "<div class='rf-row'><div class='rf-meta'><div class='rf-label'>" + fmt.escape(o.label) + "</div>" +
        "<div class='rf-sub'>" + (o.variant ? "<span class='rf-variant'>" + fmt.escape(o.variant) + "</span> " : "") +
        "<span class='rf-path'>" + fmt.escape(o.path) + "</span> · " + fmtBytes(o.size) + "</div></div>" +
        "<div class='rf-actions'><a class='btn btn-ghost file-act' href='" + api.runFileUrl(tag, o.path) +
        "' target='_blank' rel='noopener'>" + icon("eye", { size: 13 }) + " View</a>" +
        fileActionsHtml(tag, o.path) + "</div></div>").join("") + "</div>";
  }
  el.innerHTML = html;
  wireFileActions(el);
}

// ---------------------------------------------------------------- raw formats
function syncFormats() {
  const sel = document.getElementById("rf-format");
  if (!sel || sel.options.length) return;
  const order = ["def", "nl", "pnl", "spef", "sdf", "lib", "sdc", "lef", "spice", "vh"];
  const seen = new Set();
  const add = (df) => {
    if (seen.has(df.id) || df.id === "gds" || df.id === "render" || /gds$/.test(df.id)) return;
    seen.add(df.id);
    const o = document.createElement("option");
    o.value = df.id;
    o.textContent = df.full_name ? df.id + " · " + df.full_name : df.id;
    sel.appendChild(o);
  };
  for (const id of order) { const df = (state.designFormats || []).find((x) => x.id === id); if (df) add(df); }
  for (const df of state.designFormats || []) add(df);
}

async function renderRaw(tag) {
  syncFormats();
  const sel = document.getElementById("rf-format");
  const out = document.getElementById("rf-text");
  const dl = document.getElementById("rf-download");
  if (!sel || !out) return;
  const id = sel.value;
  out.textContent = "";
  if (!id) { out.textContent = "No text formats are known for this LibreLane version."; return; }
  const url = "/api/views/" + encodeURIComponent(tag) + "/" + encodeURIComponent(id);
  try {
    const resp = await fetch(url);
    if (tag !== _tag) return;
    if (!resp.ok) {
      out.textContent = "This run has no " + id + " file in final/.";
      if (dl) dl.hidden = true;
      return;
    }
    if (dl) { dl.hidden = false; dl.href = url; dl.setAttribute("download", tag + "-" + id); }
    const text = await resp.text();
    const { renderFileText } = await import("./fileview.js");
    renderFileText(out, text, { emptyMsg: "(empty file)" });
  } catch (ex) {
    out.textContent = "Could not load it: " + (ex.message || ex);
  }
}

// ---------------------------------------------------------------- diagrams
async function renderDiagrams(tag, ep) {
  const el = document.getElementById("rf-diagrams");
  if (!el) return;
  el.innerHTML = "<div class='muted'>Loading diagrams…</div>";
  let diags = [];
  try { diags = ((await api.runDiagrams(tag)) || {}).diagrams || []; }
  catch (_e) { el.innerHTML = ""; return; }
  if (ep !== _epoch) return;
  if (!diags.length) {
    el.innerHTML = "<div class='muted'>No synthesis diagrams in this run. Turn on <code>SYNTH_SHOW</code> in the run settings and run again to get Yosys's hierarchy and gate-level schematics.</div>";
    return;
  }
  el.innerHTML = "";
  for (const d of diags) {
    const card = document.createElement("figure");
    card.className = "diagram-card";
    const sizeKb = d.size ? " · " + Math.round(d.size / 1000) + " KB" : "";
    card.innerHTML =
      "<figcaption><strong>" + fmt.escape(d.label) + "</strong> <span class='muted'>" + fmt.escape(d.step) +
      " · " + fmt.escape(d.name) + sizeKb + "</span></figcaption><div class='diagram-body muted'></div>" +
      "<div class='diagram-actions'><a class='btn btn-ghost' href='" + api.runFileUrl(tag, d.path) +
      "' target='_blank' rel='noopener' download='" + fmt.escape(d.name) + "'>" + DL_SVG + " .dot</a></div>";
    el.appendChild(card);
    const body = card.querySelector(".diagram-body");
    const actions = card.querySelector(".diagram-actions");
    // Big gate-level schematics render on demand: auto-rendering one can freeze
    // the browser (and used to run the host's dot out of memory).
    if (d.large) {
      body.textContent = "Large diagram; rendering may take a while.";
      const go = document.createElement("button");
      go.className = "btn btn-ghost";
      go.textContent = "Render anyway";
      go.addEventListener("click", () => { go.remove(); renderDot(tag, d, body, actions, true); });
      actions.appendChild(go);
    } else {
      renderDot(tag, d, body, actions, false);
    }
  }
}

async function renderDot(tag, d, body, actions, force) {
  body.classList.add("muted");
  body.textContent = "Rendering…";
  let res;
  try { res = await api.renderDot(tag, d.path, force); }
  catch (ex) { body.classList.remove("muted"); body.textContent = "Render failed: " + (ex.message || ex); return; }
  body.classList.remove("muted");
  if (res && res.ok && res.svg) {
    const svgUrl = api.runFileUrl(tag, res.svg);
    body.innerHTML = "<a href='" + svgUrl + "' target='_blank' rel='noopener'><img loading='lazy' src='" + svgUrl +
      "' alt='" + fmt.escape(d.label) + "'/></a>";
    if (!actions.querySelector(".svg-dl")) {
      const a = document.createElement("a");
      a.className = "btn btn-ghost svg-dl";
      a.href = svgUrl; a.target = "_blank"; a.rel = "noopener";
      a.setAttribute("download", d.name.replace(/\.dot$/, "") + ".svg");
      a.innerHTML = DL_SVG + " .svg";
      actions.appendChild(a);
    }
    return;
  }
  body.textContent = (res && res.error) || "Could not render this diagram.";
  if (res && res.too_large && !force && !actions.querySelector(".force-dl")) {
    const go = document.createElement("button");
    go.className = "btn btn-ghost force-dl";
    go.textContent = "Render anyway";
    go.addEventListener("click", () => { go.remove(); renderDot(tag, d, body, actions, true); });
    actions.appendChild(go);
  }
  if (res && res.need === "graphviz" && !actions.querySelector(".install-gv")) {
    const gv = document.createElement("button");
    gv.className = "btn btn-primary install-gv";
    gv.textContent = "Install Graphviz";
    gv.addEventListener("click", async () => {
      gv.disabled = true; gv.textContent = "Installing Graphviz…";
      try {
        const r = await api.installTool("graphviz");
        if (r && r.ok === false) toast.show(r.guidance || r.reason || "Couldn't install Graphviz automatically.", "warn");
        else toast.show("Installing Graphviz. Render again when it finishes (see Install logs).", "info");
      } catch (ex) { toast.show("Could not start the Graphviz install: " + (ex.message || ex), "error"); }
      gv.disabled = false; gv.textContent = "Render again";
      gv.onclick = () => { gv.remove(); renderDot(tag, d, body, actions, force); };
    });
    actions.appendChild(gv);
  }
}
