// cells.js — standard-cell library browser (Phase 4.3). Lists the PDK's cells by
// kind (from LEF), searchable + sortable. Has its own PDK + SCL dropdowns (built
// from the installed PDKs) so it doesn't depend on the Setup-tab selection.
import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { wireJump } from "./jumpnav.js";

let _cells = [];

// /api/scls returns one entry per SCL shaped {name:<pdk>, variants:[[<scl>,<scl>]]}
// — the actual standard-cell-library name is variants[0][0], NOT name (which is
// the PDK). Mirror setup.js, which reads variants[0][1]. Reading s.name made
// every option identical (the PDK) and then queried cells with the PDK as the
// SCL → "could not locate the SCL's LEF".
function sclName(s) {
  if (typeof s === "string") return s;
  if (!s) return "";
  if (Array.isArray(s.variants) && s.variants[0]) return s.variants[0][0] || "";
  return s.name || s.id || "";
}

export async function renderCells() {
  const root = document.getElementById("cells-body");
  if (!root) return;
  const pdks = state.pdks || [];
  if (!pdks.length) {
    root.innerHTML = "<div class='empty'><h3>No PDK installed</h3>" +
      "<p>Install a PDK from the Tools tab first.</p></div>";
    return;
  }
  const selPdk = state.cellsPdk || state.selectedPdk || pdks[0].name;
  root.innerHTML =
    "<div class='cells-pick'>" +
    "<label>PDK <select id='cells-pdk'>" +
    pdks.map((p) => "<option value='" + fmt.escape(p.name) + "'" +
      (p.name === selPdk ? " selected" : "") + ">" + fmt.escape(p.name) + "</option>").join("") +
    "</select></label>" +
    "<label>Library <select id='cells-scl'></select></label>" +
    "</div><div id='cells-result'></div>";

  const pdkSel = root.querySelector("#cells-pdk");
  const sclSel = root.querySelector("#cells-scl");
  pdkSel.addEventListener("change", () => { state.cellsPdk = pdkSel.value; loadScls(sclSel, pdkSel.value); });
  sclSel.addEventListener("change", () => { state.cellsScl = sclSel.value; loadCells(pdkSel.value, sclSel.value); });
  // Quick-explore nav (Standard cells ⇄ Custom cells) lives in the section, above
  // #cells-body — wire its click-scroll + scroll-spy highlight.
  wireJump(document.getElementById("sec-cells"));
  await loadScls(sclSel, selPdk);
}

async function loadScls(sclSel, pdk) {
  sclSel.innerHTML = "<option>loading…</option>";
  let scls = [];
  try { scls = await api.scls(pdk); } catch (_e) {}
  scls = (scls || []).map(sclName).filter(Boolean);
  if (!scls.length) {
    sclSel.innerHTML = "<option value=''>(no libraries found)</option>";
    document.getElementById("cells-result").innerHTML =
      "<div class='empty'><h3>No standard-cell libraries</h3><p>This PDK has no libs.ref/&lt;scl&gt; on disk.</p></div>";
    return;
  }
  const want = (state.cellsScl && scls.includes(state.cellsScl)) ? state.cellsScl
    : (state.selectedScl && scls.includes(state.selectedScl)) ? state.selectedScl : scls[0];
  sclSel.innerHTML = scls.map((s) =>
    "<option value='" + fmt.escape(s) + "'" + (s === want ? " selected" : "") + ">" + fmt.escape(s) + "</option>").join("");
  state.cellsScl = want;
  await loadCells(pdk, want);
}

async function loadCells(pdk, scl) {
  const root = document.getElementById("cells-result");
  if (!root) return;
  root.innerHTML = "<p class='muted'>Loading cells for " + fmt.escape(scl || pdk) + "…</p>";
  let res;
  try { res = await api.cells(pdk, scl); } catch (ex) {
    root.innerHTML = "<p class='pill pill-fail'>" + fmt.escape(ex.message || ex) + "</p>"; return;
  }
  if (!res.ok) {
    root.innerHTML = "<div class='empty'><h3>Cells unavailable</h3><p>" +
      fmt.escape(res.error || "could not read the SCL LEF") + "</p></div>";
    return;
  }
  _cells = res.cells || [];
  if (!_cells.length) {
    root.innerHTML = "<div class='empty'><h3>No cells found</h3><p>The LEF parsed but listed no MACROs.</p></div>";
    return;
  }
  const kinds = [...new Set(_cells.map((c) => c.kind))].sort();
  root.innerHTML =
    "<div class='cells-bar'>" +
    "<input id='cells-search' class='inp' type='search' placeholder='search " + _cells.length + " cells…' />" +
    "<select id='cells-kind'><option value=''>all kinds</option>" +
    kinds.map((k) => "<option value='" + k + "'>" + k + "</option>").join("") + "</select>" +
    "<span class='muted'>" + fmt.escape(res.source || "") + "</span></div>" +
    "<div id='cells-grid' class='cells-grid'></div>";
  const paint = () => {
    const q = (root.querySelector("#cells-search").value || "").toLowerCase();
    const kind = root.querySelector("#cells-kind").value;
    const rows = _cells.filter((c) =>
      (!q || c.cell.toLowerCase().includes(q)) && (!kind || c.kind === kind));
    root.querySelector("#cells-grid").innerHTML = rows.slice(0, 600).map((c) =>
      "<div class='cell-card'><code>" + fmt.escape(c.cell) + "</code>" +
      "<span class='chip chip-" + fmt.escape(c.kind) + "'>" + fmt.escape(c.kind) + "</span></div>").join("") +
      (rows.length > 600 ? "<p class='muted'>… and " + (rows.length - 600) + " more (refine your search)</p>" : "");
  };
  root.querySelector("#cells-search").addEventListener("input", paint);
  root.querySelector("#cells-kind").addEventListener("change", paint);
  paint();
}
