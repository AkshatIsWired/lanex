// cells-rules.js — the Flow rules part of the Cells tab.
//
// The three ways the flow's cell choice is constrained, side by side and
// traceable to their source: the PDK's own exclusion lists (read-only, with
// the file they come from), the design's EXTRA_EXCLUDED_CELLS (edited key by
// key in the config, with a live preview of what each wildcard catches), the
// cells LibreLane inserts by itself (fill, taps, ties, clock buffers…), and
// custom cells swapped in for library ones (per run, never in the config).

import { api } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { icon } from "./icons.js";
import { confirmDialog } from "./dialog.js";
import * as M from "./cells-model.js";
import { copyText } from "./cells.js";

const esc = M.esc;
let C = null;

export async function renderRules(ctx) {
  C = ctx;
  const host = document.getElementById("cl-rules-body");
  if (!host || !ctx.lib) return;
  const L = ctx.lib;
  const names = L.cells.map((c) => c.cell);
  host.innerHTML =
    "<div class='cr-grid'>" +
      "<section class='cl-card cr-mine'>" + mineHtml(L, names) + "</section>" +
      "<section class='cl-card'>" + pdkListHtml("synth", "PDK: kept out of synthesis", L.rules.synth, names,
        "Cells the PDK maintainers don't want synthesis to pick: ones that fail DRC in some placements, have awkward pin access, or exist for special jobs (delay lines, low-power variants, very weak drives).") + "</section>" +
      "<section class='cl-card'>" + pdkListHtml("pnr", "PDK: kept out of placement too", L.rules.pnr, names,
        "Excluded from synthesis and from every resizer and repair step after it, so they never appear in the layout at all.") + "</section>" +
    "</div>" +
    "<h3 class='cr-sub'>Cells the flow adds by itself</h3>" +
    "<p class='an-lede cr-lede'>You never write these in RTL. LibreLane places them because the PDK says to; each one is set by a variable you can override in your config.</p>" +
    rolesHtml(L) +
    "<h3 class='cr-sub'>Swap in your own cells <span class='cc-badge'>advanced</span></h3>" +
    "<p class='an-lede cr-lede'>Use a cell of your own (a custom drive strength, a hardened or low-leakage variant) instead of library cells. Its views are added with <code>EXTRA_LEFS</code>/<code>EXTRA_LIBS</code>/… and the cells it replaces are excluded, for runs started from LanEx only; your config is never edited.</p>" +
    "<div id='cr-custom'></div>";
  wireMine(host, names);
  if (!host._crWired) host.addEventListener("click", (e) => {
    const o = e.target.closest("[data-open]");
    if (o) { e.preventDefault(); C.openCell(o.dataset.open); }
    const cp = e.target.closest("[data-copy]");
    if (cp) copyText(cp.dataset.copy, "Copied");
  });
  host._crWired = true;
  renderCustom(names);
}

function matchList(pats, names) {
  return names.filter((n) => M.globMatch(n, pats).length);
}

function cellLinks(list, max = 60) {
  return list.slice(0, max).map((n) => "<a href='#' class='cr-cell mono' data-open='" + esc(n) + "'>" + esc(n.replace(C.lib.prefix, "")) + "</a>").join(" ") +
    (list.length > max ? "<span class='muted'> … and " + (list.length - max) + " more</span>" : "");
}

function pdkListHtml(kind, title, rule, names, why) {
  const pats = rule.patterns || [];
  const hit = matchList(pats, names);
  return "<div class='cl-card-h'>" + esc(title) + " <span class='muted'>" + hit.length + " cell" + (hit.length === 1 ? "" : "s") + "</span></div>" +
    "<p class='cl-foot'>" + esc(why) + "</p>" +
    (rule.file ? "<p class='cr-file'><span class='mono'>" + esc(rule.file.replace(/^.*\/libs\.tech\//, "libs.tech/")) + "</span> <button class='btn btn-ghost btn-xs' data-copy='" + esc(rule.file) + "'>Copy path</button></p>" : "<p class='muted cl-p'>The PDK sets no list here.</p>") +
    (hit.length ? "<details class='cr-det'><summary>Show them</summary><div class='cr-cells'>" + cellLinks(hit, 400) + "</div></details>" : "") +
    (kind === "synth" ? "<p class='cl-foot'>To replace the whole list, point <code>SYNTH_EXCLUDED_CELL_FILE</code> at your own file in the config. Rarely a good idea.</p>" : "");
}

function mineHtml(L, names) {
  const cfg = L.config || {};
  const pats = (L.rules.user && L.rules.user.patterns) || [];
  const head = "<div class='cl-card-h'>Yours <span class='muted'>EXTRA_EXCLUDED_CELLS</span></div>";
  if (!state.designDir) return head + "<p class='muted cl-p'>Open a project to set its own exclusions.</p>";
  const chips = pats.length
    ? "<div class='cr-chips'>" + pats.map((p) => {
        const n = matchList([p], names).length;
        return "<span class='cr-pat" + (n ? "" : " is-dead") + "' title='" + (n ? n + " cell" + (n === 1 ? "" : "s") + " in " + esc(C.scl) : "Matches nothing in " + esc(C.scl)) + "'>" +
          "<span class='mono'>" + esc(p) + "</span><b>" + n + "</b>" +
          (cfg.editable ? "<button data-unpat='" + esc(p) + "' aria-label='Remove " + esc(p) + "'>" + icon("x", { size: 11 }) + "</button>" : "") + "</span>";
      }).join("") + "</div>"
    : "<p class='muted cl-p'>Nothing excluded yet. The usual reasons: keep delay cells out until hold fixing needs them, ban a cell that misbehaves in your sign-off, or stop the resizer from reaching for the biggest buffers.</p>";
  const editor = cfg.editable
    ? "<div class='cr-add'><input id='cr-pat' class='mono' placeholder='cell name or wildcard, e.g. *dlygate*' list='cr-names' spellcheck='false' autocomplete='off'>" +
      "<button class='btn btn-sm' id='cr-pat-add' disabled>Exclude</button></div><div class='cr-preview muted' id='cr-preview'></div>" +
      "<datalist id='cr-names'>" + names.map((n) => "<option value='" + esc(n) + "'>").join("") + "</datalist>" +
      "<p class='cl-foot'>Saved to " + esc(cfg.name || "the config") + ". Wildcards use <code>*</code> and <code>?</code>, as LibreLane matches them. Applies to synthesis and every placement step from the next run.</p>"
    : "<p class='muted cl-p'>" + esc(cfg.reason || "This project's config can't be edited here.") + "</p>";
  return head + chips + editor;
}

function wireMine(host, names) {
  const inp = host.querySelector("#cr-pat");
  if (inp) {
    const prev = host.querySelector("#cr-preview"), btn = host.querySelector("#cr-pat-add");
    const upd = () => {
      const v = inp.value.trim();
      const hit = v ? matchList([v], names) : [];
      btn.disabled = !v;
      prev.innerHTML = !v ? "" : hit.length
        ? "Catches " + hit.length + " cell" + (hit.length === 1 ? "" : "s") + ": " + cellLinks(hit, 12)
        : "<span class='cl-warn-t'>Matches no cell in " + esc(C.scl) + ".</span> It would still be saved, and apply if you switch library.";
    };
    inp.addEventListener("input", upd);
    const add = async () => {
      const v = inp.value.trim();
      if (!v) return;
      const cur = C.lib.rules.user.patterns || [];
      if (cur.includes(v)) { toast.show(v + " is already excluded", "info"); return; }
      btn.disabled = true;
      if (await C.setUserExcluded(cur.concat([v]))) toast.show("Excluded " + v + " from the next run.", "success");
    };
    btn.addEventListener("click", add);
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
  }
  host.querySelectorAll("[data-unpat]").forEach((b) => b.addEventListener("click", async () => {
    const cur = (C.lib.rules.user.patterns || []).filter((p) => p !== b.dataset.unpat);
    if (await C.setUserExcluded(cur)) toast.show(b.dataset.unpat + " removed.", "success");
  }));
}

function rolesHtml(L) {
  const roles = L.rules.roles || [];
  if (!roles.length) return "<div class='an-none'>The PDK's config sets no cell roles for this library.</div>";
  return "<div class='cl-tblwrap'><table class='cl-tbl cr-roles'><thead><tr><th>Role</th><th>Cell</th><th>What it is for</th><th>Set by</th></tr></thead><tbody>" +
    roles.map((r) => "<tr><td><b>" + esc(r.label) + "</b><div class='muted mono'>" + esc(r.key) + "</div></td>" +
      "<td>" + (r.cells.length ? r.cells.map((c) => C.byName.has(c) ? "<a href='#' class='cr-cell mono' data-open='" + esc(c) + "'>" + esc(c.replace(L.prefix, "")) + "</a>" : "<span class='mono'>" + esc(c) + "</span>").join(" ") : "<span class='muted'>none</span>") +
      (String(r.value || "").includes("/") ? "<div class='muted'>" + esc(pinText(r)) + "</div>" : "") + "</td>" +
      "<td>" + esc(r.why) + "</td><td>" + (r.source === "design" ? "<span class='cl-chip is-role'>your config</span>" : "<span class='muted'>PDK</span>") + "</td></tr>").join("") +
    "</tbody></table></div>";
}

function pinText(r) {
  const parts = String(r.value).split("/").slice(1);
  if (r.key === "SYNTH_BUFFER_CELL" && parts.length === 2) return "in " + parts[0] + ", out " + parts[1];
  return parts.length ? "pin " + parts.join(", ") : "";
}

// ---------------------------------------------------------- custom cells ---
const VIEWS = [
  { kind: "lef", label: "LEF", hint: "footprint and pins", accept: ".lef", required: true },
  { kind: "lib", label: "Liberty", hint: "timing, so synthesis can pick it", accept: ".lib" },
  { kind: "gds", label: "GDS", hint: "the real layout", accept: ".gds,.gz" },
  { kind: "spice", label: "SPICE", hint: "for LVS", accept: ".spice,.sp,.cir" },
  { kind: "verilog", label: "Verilog", hint: "for gate-level sim", accept: ".v,.sv" },
  { kind: "cdl", label: "CDL", hint: "for LVS", accept: ".cdl,.spice" },
];

async function renderCustom(names) {
  const host = document.getElementById("cr-custom");
  if (!host) return;
  if (!state.designDir) { host.innerHTML = "<div class='an-none'>Open a project first. Custom cells are stored per project.</div>"; return; }
  let cells = [];
  try { cells = (await api.customCells(state.designDir)).cells || []; } catch (_e) {}
  const list = cells.length
    ? "<div class='cl-tblwrap'><table class='cl-tbl'><thead><tr><th>Cell</th><th>Views</th><th>Replaces</th><th>Use</th><th></th></tr></thead><tbody>" +
      cells.map((c) => "<tr><td class='mono'>" + esc(c.name) + "</td><td>" + Object.keys(c.views || {}).map((k) => "<span class='cc-chip'>" + esc(k) + "</span>").join(" ") + "</td>" +
        "<td>" + ((c.swap_out || []).map((n) => C.byName.has(n) ? "<a href='#' class='cr-cell mono' data-open='" + esc(n) + "'>" + esc(n.replace(C.lib.prefix, "")) + "</a>" : "<span class='mono'>" + esc(n) + "</span>").join(" ") || "<span class='muted'>nothing (added only)</span>") + "</td>" +
        "<td><label class='cl-switch'><input type='checkbox' data-cc-en='" + esc(c.name) + "'" + (c.enabled ? " checked" : "") + "><span></span></label></td>" +
        "<td><button class='btn btn-ghost btn-xs' data-cc-rm='" + esc(c.name) + "'>" + icon("trash", { size: 12 }) + "</button></td></tr>").join("") +
      "</tbody></table></div>"
    : "";
  const siteH = C.lib.site && C.lib.site.h;
  host.innerHTML = list +
    "<details class='cc-add'" + (cells.length ? "" : " open") + "><summary>" + icon("plus", { size: 13 }) + " Add a custom cell</summary><div class='cr-form'>" +
    "<label>Cell name <input id='cc-name' class='mono' placeholder='read from the LEF' spellcheck='false' autocomplete='off'></label>" +
    "<label>Replaces <input id='cc-swap' class='mono' placeholder='library cells to drop, comma-separated (optional)' list='cr-names' spellcheck='false' autocomplete='off'>" +
      "<span class='muted' id='cc-swap-prev'></span></label>" +
    "<div class='cr-views'>" + VIEWS.map((v) => "<label class='cr-view'><span><b>" + v.label + (v.required ? " *" : "") + "</b> " + esc(v.hint) + "</span>" +
      "<input type='file' class='cc-file' data-kind='" + v.kind + "' accept='" + v.accept + "'></label>").join("") + "</div>" +
    "<div class='cr-check' id='cc-check'></div>" +
    "<div class='cr-form-act'><button class='btn btn-primary btn-sm' id='cc-save'>Save custom cell</button><span class='ac-error' id='cc-err' hidden></span></div>" +
    "</div></details>";
  const swap = host.querySelector("#cc-swap");
  swap.addEventListener("input", () => {
    const items = swap.value.split(",").map((s) => s.trim()).filter(Boolean);
    const bad = items.filter((n) => !names.includes(n) && !/[*?]/.test(n));
    host.querySelector("#cc-swap-prev").innerHTML = bad.length ? "<span class='cl-warn-t'>Not in " + esc(C.scl) + ": " + esc(bad.join(", ")) + "</span>" : "";
  });
  host.querySelector(".cc-file[data-kind='lef']").addEventListener("change", async (e) => {
    const f = e.target.files && e.target.files[0];
    const out = host.querySelector("#cc-check");
    if (!f) { out.innerHTML = ""; return; }
    const txt = await f.text();
    const mm = txt.match(/^\s*MACRO\s+(\S+)/m);
    const sz = txt.match(/^\s*SIZE\s+([\d.]+)\s+BY\s+([\d.]+)/m);
    const nm = host.querySelector("#cc-name");
    if (mm && !nm.value) nm.value = mm[1];
    if (sz && siteH) {
      const h = Number(sz[2]), w = Number(sz[1]);
      const ok = Math.abs(h / siteH - Math.round(h / siteH)) < 1e-3;
      const wok = !C.lib.site.w || Math.abs(w / C.lib.site.w - Math.round(w / C.lib.site.w)) < 1e-3;
      out.innerHTML = "<span class='vf-mark is-" + (ok && wok ? "pass" : "fail") + "'></span> " +
        esc(w + " × " + h + " µm. ") + (ok && wok
          ? "Fits the " + esc(C.lib.site.name || "site") + " grid (" + C.lib.site.w + " × " + siteH + " µm)."
          : "Off the " + esc(C.lib.site.name || "site") + " grid: height must be a multiple of " + siteH + " µm and width of " + C.lib.site.w + " µm, or placement fails.");
    }
  });
  host.querySelector("#cc-save").addEventListener("click", () => saveCustom(host));
  host.addEventListener("change", async (e) => {
    const en = e.target.closest("[data-cc-en]");
    if (!en) return;
    try { await api.customCellEnable(en.dataset.ccEn, en.checked, state.designDir); C.reload().then(() => renderRules(C)); }
    catch (ex) { toast.show(ex.message, "error"); en.checked = !en.checked; }
  });
  host.addEventListener("click", async (e) => {
    const rm = e.target.closest("[data-cc-rm]");
    if (!rm) return;
    if (!(await confirmDialog({ title: "Remove custom cell", danger: true, confirmText: "Remove", body: "Remove " + rm.dataset.ccRm + " and the files LanEx stored for it?" }))) return;
    try { await api.customCellRemove(rm.dataset.ccRm, state.designDir); C.reload().then(() => renderRules(C)); }
    catch (ex) { toast.show(ex.message, "error"); }
  });
}

async function saveCustom(host) {
  const err = host.querySelector("#cc-err");
  err.hidden = true;
  const name = host.querySelector("#cc-name").value.trim();
  const swap = host.querySelector("#cc-swap").value.split(",").map((s) => s.trim()).filter(Boolean);
  const views = {};
  for (const inp of host.querySelectorAll(".cc-file")) {
    const f = inp.files && inp.files[0];
    if (!f) continue;
    views[inp.dataset.kind] = { filename: f.name, content_b64: await new Promise((res, rej) => {
      const r = new FileReader(); r.onerror = () => rej(new Error("read failed"));
      r.onload = () => { const s = String(r.result || ""); res(s.slice(s.indexOf(",") + 1)); }; r.readAsDataURL(f);
    }) };
  }
  const fail = (m) => { err.hidden = false; err.textContent = m; };
  if (!name) return fail("Give the cell a name.");
  if (!views.lef) return fail("A LEF view is required.");
  const b = host.querySelector("#cc-save");
  b.disabled = true; b.textContent = "Saving…";
  try {
    await api.customCellSave({ design_dir: state.designDir, name, swap_out: swap, views, enabled: true });
    toast.show("Saved " + name + ". The next run uses it" + (swap.length ? " instead of " + swap.join(", ") : "") + ".", "success");
    await C.reload();
    renderRules(C);
  } catch (ex) { fail(ex.message || String(ex)); b.disabled = false; b.textContent = "Save custom cell"; }
}
