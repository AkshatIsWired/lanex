// fs.js — folder browser modal + file selector.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { icon } from "./icons.js";
import { toast } from "./toast.js";

let _curPath = "";
const _checked = new Set();
let _checkedFor = "";       // the design the ticks belong to
let _seen = new Set();       // files present at the last scan
// Set while a caller awaits pickFolder(); "Use this folder" then resolves it
// instead of loading the folder as the design.
let _pick = null;

export function setupFolderBrowser() {
  document.getElementById("btn-browse-folder")?.addEventListener("click", () =>
    import("./shell.js").then((m) => m.openFolder()));
  document.getElementById("fs-close")?.addEventListener("click", closeModal);
  document.getElementById("fs-use")?.addEventListener("click", useCurrentFolder);
  document.getElementById("fs-up")?.addEventListener("click", () => navigateUp());
  document.getElementById("fs-path")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      fetchDir(e.target.value.trim());
    }
  });

  document.getElementById("btn-filesel-all")?.addEventListener("click", () => {
    for (const f of designRows()) if (!f.missing) _checked.add(f.abs);
    renderFileSelector();
    onTicksChanged();
  });
  document.getElementById("btn-filesel-none")?.addEventListener("click", () => {
    _checked.clear();
    renderFileSelector();
    onTicksChanged();
  });
  wireSourceActions();
  document.getElementById("btn-filesel-refresh")?.addEventListener("click", () => loadFilesFor(state.designDir));
  document.getElementById("filesel-extras")?.addEventListener("input", commitSelection);
}

// Esc-to-close + basic focus handling so the file browser matches the a11y of
// the dialog.js modals (G2a). Kept lightweight: one keydown listener, removed on
// close, plus a focus trap that wraps Tab within the modal.
function _fsKeydown(e) {
  const modal = document.getElementById("fs-modal");
  if (!modal || modal.hidden) return;
  if (e.key === "Escape") { e.preventDefault(); closeModal(); return; }
  if (e.key !== "Tab") return;
  const focusable = modal.querySelectorAll(
    'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])');
  if (!focusable.length) return;
  const first = focusable[0], last = focusable[focusable.length - 1];
  if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
}


function closeModal() {
  const modal = document.getElementById("fs-modal");
  modal.hidden = true;
  document.removeEventListener("keydown", _fsKeydown);
  if (_pick) { const p = _pick; _pick = null; p.resolve(null); _labelModal(); }
}

function _labelModal(title = "Open a design folder", use = "Use this folder") {
  const t = document.getElementById("fs-modal-title");
  const u = document.getElementById("fs-use");
  if (t) t.textContent = title;
  if (u) u.textContent = use;
}

// Let any caller borrow the browser: resolves with the chosen folder, or null
// when the user closes it. `seed` is where it opens.
// The system picker takes a second or two to appear (Windows builds it in a
// fresh PowerShell), so say it's coming; a second click while it's open just
// points at the one already on screen.
let _picking = false;
export async function pickFolder(opts = {}) {
  if (_picking) { toast.show("The folder picker is already open. It may be behind this window.", "warn"); return null; }
  _picking = true;
  toast.show("Opening the folder picker…", "info");
  try {
    const r = await api.nativePick({ mode: "folder", title: opts.title || "Choose a folder", start: opts.seed || "" });
    if (r && r.busy) { toast.show("The folder picker is already open. It may be behind this window.", "warn"); return null; }
    if (r && r.native) return (r.paths && r.paths[0]) || null;
  } catch (_e) { /* fall through to the built-in browser */ }
  finally { _picking = false; }
  return browseFolder(opts);
}

export function browseFolder({ title = "Choose a folder", use = "Choose this folder", seed = "" } = {}) {
  if (_pick) _pick.resolve(null);
  return new Promise((resolve) => {
    _pick = { resolve };
    _labelModal(title, use);
    const modal = document.getElementById("fs-modal");
    modal.hidden = false;
    document.addEventListener("keydown", _fsKeydown);
    loadRoots().then(async () => {
      await fetchDir(seed || (await defaultSeed()) || "/");
      document.getElementById("fs-path")?.focus();
    });
  });
}

async function defaultSeed() {
  try {
    const r = await api.fsRoots();
    return (r.roots || [])[0]?.path || "";
  } catch (_) {
    return "";
  }
}

async function loadRoots() {
  const bar = document.getElementById("fs-roots");
  if (!bar) return;
  bar.innerHTML = "";
  try {
    const r = await api.fsRoots();
    for (const x of r.roots || []) {
      const b = document.createElement("div");
      b.className = "fs-roots-pill";
      b.textContent = x.label;
      b.title = x.path;
      b.addEventListener("click", () => fetchDir(x.path));
      bar.appendChild(b);
    }
  } catch (_e) {}
}

async function fetchDir(path) {
  if (!path) return;
  try {
    const r = await api.fsList(path);
    if (!r.ok) {
      paintList([{ name: "(error)", path: r.error, is_dir: false }]);
      return;
    }
    _curPath = r.path;
    document.getElementById("fs-path").value = r.path;
    paintList(r.entries);
  } catch (ex) {
    paintList([{ name: "(network error)", path: "", is_dir: false, error: ex.message }]);
  }
}

function navigateUp() {
  if (!_curPath || _curPath === "/") return;
  const sep = _curPath.indexOf("\\") >= 0 ? "\\" : "/";
  const trimmed = _curPath.endsWith(sep) ? _curPath.slice(0, -1) : _curPath;
  const idx = trimmed.lastIndexOf(sep);
  const parent = idx <= 0 ? sep : trimmed.slice(0, idx);
  fetchDir(parent);
}

function paintList(entries) {
  const list = document.getElementById("fs-list");
  if (!list) return;
  list.innerHTML = "";
  if (!entries.length) {
    list.innerHTML = "<div class='empty'><span class='ico'>" + icon('folderOpen',{size:40}) + "</span><h3>Empty</h3><p>This folder has nothing in it.</p></div>";
    return;
  }
  for (const e of entries) {
    const row = document.createElement("div");
    row.className = "filesel-row" + (e.is_dir ? " dir" : "");
    const safe = fmt.escape(e.name);
    row.innerHTML =
      "<span class='fs-ico' aria-hidden='true'>" + icon(e.is_dir ? "folder" : "file", { size: 15 }) + "</span> " +
      "<span class='name'>" + safe + "</span>" +
      (e.is_dir
        ? ""
        : "<span class='size'>" + fmt.metric(e.size) + " B</span>");
    if (e.is_dir) {
      row.addEventListener("click", () => fetchDir(e.path));
    } else {
      // Files: clicking "select as design_dir parent" is unfriendly, so leave as no-op.
      // Show file in preview if user clicks, but past 5 we skip wiring.
    }
    list.appendChild(row);
  }
}

function useCurrentFolder() {
  if (_pick) {
    const p = _pick; _pick = null;
    const modal = document.getElementById("fs-modal");
    modal.hidden = true;
    document.removeEventListener("keydown", _fsKeydown);
    _labelModal();
    p.resolve(_curPath);
    return;
  }
  document.getElementById("design-dir-input").value = _curPath;
  closeModal();
  // Trigger a load + scan:
  document.getElementById("btn-set-design").click();
}

// A testbench drives a design in simulation and must never be synthesized.
// Recognised by where it lives (verify/, tb/, test/, sim/) or by its name.
export function isTestbench(item) {
  const rel = String(item.relpath || item.name || "").replace(/\\/g, "/");
  const name = rel.split("/").pop();
  return /(^|\/)(verify|tb|tbs|test|tests|sim|testbench|testbenches)\//i.test(rel) ||
    /(^tb_|_tb\.|^test_|testbench)/i.test(name);
}

// The Sources card. The config's VERILOG_FILES is the source of truth: the
// ticks show what it builds into the chip, and changing a tick rewrites it
// (key by key, server side; see controller/configedit.py). When LanEx can't
// edit the config (Tcl, ref::/expr:: entries, no config yet) the ticks only
// apply to runs started from LanEx, as they always did.
let _files = [];           // /api/project/files rows for the open project
let _cfg = { mode: "noconfig", name: "", entries: [], globbed: false, reason: "" };
let _topFile = null;       // abspath of the file that declares the top module
let _saving = Promise.resolve();

const HDL_RX = /\.(s?v|verilog)$/i;

export function setTopFile(abs) {
  if (abs === _topFile) return;
  _topFile = abs || null;
  renderFileSelector();
}

export async function loadFilesFor(designDir, opts = {}) {
  const show = opts.show !== false;
  const card = document.getElementById("filesel-card");
  if (!designDir) {
    state.designSources = [];
    state.designMemories = [];
    state.configSources = null;
    _files = [];
    if (card) card.hidden = true;
    paintCount();
    return;
  }
  try {
    const [r, pf] = await Promise.all([
      api.walkSources(designDir),
      api.projectFiles(designDir).catch(() => null),
    ]);
    if (!r.ok) return;
    state.designSources = r.sources;
    state.designMemories = r.memories;
    if (card) card.hidden = !show;
    _files = (pf && pf.files) || [];
    const conf = (pf && pf.config) || {};
    const src = (pf && pf.sources) || {};
    _cfg = {
      mode: !conf.name ? "noconfig" : !conf.editable ? "unknown" : src.mode || "unknown",
      name: conf.name || "",
      entries: src.entries || [],
      globbed: !!src.globbed,
      reason: src.reason || conf.reason || "",
    };
    const present = new Set(state.designSources.map((x) => x.abspath));
    if (_cfg.mode === "list") {
      // Exactly what the config builds, including listed files that are missing.
      state.configSources = (src.files || []).slice();
      _checked.clear();
      for (const f of state.configSources) _checked.add(f);
    } else {
      // The config doesn't list sources LanEx can manage: keep the person's
      // earlier ticks for files still here; a fresh project ticks every
      // design file, never a testbench or a memory-contents file.
      state.configSources = _cfg.mode === "none" ? [] : null;
      const kept = [..._checked].filter((x) => present.has(x));
      _checked.clear();
      if (kept.length && _checkedFor === designDir) {
        for (const x of kept) _checked.add(x);
        for (const s of state.designSources) if (!_seen.has(s.abspath) && !isTestbench(s)) _checked.add(s.abspath);
      } else {
        for (const s of state.designSources) if (!isTestbench(s)) _checked.add(s.abspath);
      }
    }
    _checkedFor = designDir;
    _seen = present;
    renderFileSelector();
    commitSelection();
  } catch (_e) {
    state.designSources = [];
    state.designMemories = [];
    state.configSources = null;
    _files = [];
    if (card) card.hidden = true;
  }
  import("./projectcard.js").then((m) => m.paintDesignRow()).catch(() => {});
}

// Rows with a checkbox: design RTL plus anything the config lists (a listed
// header, a file outside the project, a listed file that's missing).
function designRows() {
  const rows = _files.filter((f) => f.role === "design" || f.in_verilog_files);
  const known = new Set(rows.map((f) => f.abs));
  for (const abs of state.configSources || []) {
    if (known.has(abs)) continue;
    const inside = state.designDir && abs.startsWith(state.designDir.replace(/\/+$/, "") + "/");
    rows.push({ rel: inside ? abs.slice(state.designDir.replace(/\/+$/, "").length + 1) : abs,
      abs, role: "design", missing: !_seen.has(abs), outside: !inside });
  }
  return rows;
}

function tickedDesign() {
  const rows = new Set(designRows().map((f) => f.abs));
  return [..._checked].filter((f) => rows.has(f));
}

function paintCount() {
  const el = document.getElementById("filesel-count");
  if (!el) return;
  if (!state.designDir) { el.textContent = "Open a project to see its files."; return; }
  const rows = designRows();
  const ticked = rows.filter((f) => _checked.has(f.abs)).length;
  const tbs = _files.filter((f) => f.role === "testbench").length;
  el.textContent = rows.length
    ? ticked + " of " + rows.length + " design file" + (rows.length === 1 ? "" : "s") + " go into the chip" +
      (tbs ? " · " + tbs + " testbench" + (tbs === 1 ? "" : "es") : "")
    : "No design files yet.";
}

function groupHead(text, note) {
  const h = document.createElement("div");
  h.className = "filesel-group";
  h.innerHTML = "<span class='lane-label'>" + fmt.escape(text) + "</span>" +
    (note ? "<span class='filesel-group-note'>" + note + "</span>" : "");
  return h;
}

function designNote() {
  const cfg = "<code>" + fmt.escape(_cfg.name) + "</code>";
  if (_cfg.mode === "list" && _cfg.globbed) {
    return "Every file matching <code>" + fmt.escape(_cfg.entries.join(" ")) + "</code> in " + cfg +
      ". Unticking one switches the config to a list of files.";
  }
  if (_cfg.mode === "list") return "The files " + cfg + " builds into the chip.";
  if (_cfg.mode === "none") return cfg + " doesn't list any yet. Ticking a file adds it.";
  if (_cfg.mode === "unknown") return fmt.escape(_cfg.reason || "LanEx can't edit this config.") + " Ticks apply to runs started from LanEx.";
  return "No config yet, so ticks apply to runs started from LanEx.";
}

const ROLE_LABEL = {
  config: "Project config",
  timing: "Timing constraints (SDC)",
  pins: "Pin order",
  header: "Include file",
  memory: "Memory contents",
  vhdl: "VHDL source",
  other: "",
};

function fileNote(f) {
  if (f.role !== "timing" && f.role !== "pins") return "";
  const used = f.used_by || [];
  if (!used.length) return "not used by the config";
  if (f.role === "pins") return "in use";
  const stages = [used.includes("PNR_SDC_FILE") && "place and route", used.includes("SIGNOFF_SDC_FILE") && "signoff"].filter(Boolean);
  return "used for " + stages.join(" and ");
}

function renderFileSelector() {
  const root = document.getElementById("filesel-list");
  if (!root) return;
  root.innerHTML = "";
  if (!state.designDir) { paintCount(); return; }
  const design = designRows();
  const tbs = _files.filter((f) => f.role === "testbench");
  const others = _files.filter((f) => !["design", "testbench"].includes(f.role) && !f.in_verilog_files);
  if (!design.length && !tbs.length) {
    const empty = document.createElement("div");
    empty.className = "filesel-empty";
    empty.innerHTML = "<b>No Verilog in this project yet.</b>" +
      "<span>Use <b>New file</b> to write a module in the RTL IDE, or <b>Add files</b> to bring in ones you already have.</span>";
    root.appendChild(empty);
  }
  if (design.length) {
    root.appendChild(groupHead("Design files", designNote()));
    for (const f of design) root.appendChild(srcRow(f, true));
  }
  if (tbs.length) {
    root.appendChild(groupHead("Testbenches", "simulation only, never built into the chip"));
    for (const f of tbs) root.appendChild(srcRow(f, false));
  }
  const usesSdc = _files.some((f) => (f.used_by || []).some((v) => /SDC/.test(v)));
  if (others.length || !usesSdc) {
    root.appendChild(groupHead("Project files", ""));
    if (!usesSdc) {
      const t = document.createElement("div");
      t.className = "src-row src-note";
      t.innerHTML = "<span class='name'>Timing</span><span class='src-desc'>LibreLane's default constraints, built from your clock.</span>" +
        "<span class='src-acts'><button type='button' class='btn btn-sm btn-ghost' data-src-act='new-sdc'>Create SDC file</button></span>";
      root.appendChild(t);
    }
    for (const f of others) root.appendChild(srcRow(f, false));
  }
  const foot = document.getElementById("filesel-foot");
  if (foot) foot.hidden = design.length <= 6;
  paintCount();
}

function srcRow(f, tickable) {
  const row = document.createElement(tickable ? "label" : "div");
  row.className = "src-row" + (tickable ? " is-design" : "");
  row.dataset.path = f.abs;
  if (tickable) {
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = _checked.has(f.abs);
    cb.setAttribute("aria-label", "Build " + f.rel + " into the chip");
    cb.addEventListener("change", () => {
      if (cb.checked) _checked.add(f.abs); else _checked.delete(f.abs);
      onTicksChanged();
    });
    row.appendChild(cb);
  }
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = f.rel;
  row.appendChild(name);
  const tags = [];
  if (f.abs === _topFile) tags.push("<span class='src-tag is-top'>top</span>");
  if (f.missing) tags.push("<span class='src-tag is-warn'>missing</span>");
  if (f.outside) tags.push("<span class='src-tag'>outside the project</span>");
  const desc = ROLE_LABEL[f.role] || "";
  const note = fileNote(f);
  const info = document.createElement("span");
  info.className = "src-desc";
  info.innerHTML = tags.join("") + (desc ? "<span>" + fmt.escape(desc) + (note ? " · " + fmt.escape(note) : "") + "</span>" : "");
  row.appendChild(info);
  const acts = document.createElement("span");
  acts.className = "src-acts";
  if (f.role === "timing" && !(f.used_by || []).length) {
    acts.innerHTML += "<button type='button' class='btn btn-sm btn-ghost' data-src-act='use-sdc' data-rel='" + fmt.escape(f.rel) + "'>Use for timing</button>";
  }
  if (f.role === "pins" && !(f.used_by || []).length) {
    acts.innerHTML += "<button type='button' class='btn btn-sm btn-ghost' data-src-act='use-pins' data-rel='" + fmt.escape(f.rel) + "'>Use as pin order</button>";
  }
  if (!f.missing && !f.outside && f.role !== "memory") {
    acts.innerHTML += "<button type='button' class='btn btn-sm btn-ghost filesel-edit' data-open='edit' data-rel='" + fmt.escape(f.rel) + "'>Edit</button>";
  }
  row.appendChild(acts);
  return row;
}

// Ticks changed: save them as the config's source list (one save at a time,
// in order), or keep them as a per-run choice when the config can't take it.
function onTicksChanged() {
  paintCount();
  commitSelection();
  if (_cfg.mode !== "list" && _cfg.mode !== "none") return;
  const files = tickedDesign();
  const dir = state.designDir;
  _saving = _saving.then(async () => {
    try {
      const r = await api.configSources(files);
      if (state.designDir !== dir) return;
      if (r.changed && r.changed.length) toast.show("Saved the file list to " + r.name + ".", "success", 2200);
      await loadFilesFor(dir);
      document.dispatchEvent(new CustomEvent("g:config_changed"));
    } catch (ex) {
      toast.show("Couldn't save the file list to " + (_cfg.name || "the config") + ": " +
        (ex.message || ex) + " The ticks still apply to runs started from LanEx.", "warn", 7000);
      _cfg.mode = "unknown";
      _cfg.reason = "LanEx couldn't save to the config.";
      state.configSources = null;
      renderFileSelector();
    }
  });
}

async function useFileFor(kind, rel) {
  const set = kind === "sdc"
    ? { PNR_SDC_FILE: "dir::" + rel, SIGNOFF_SDC_FILE: "dir::" + rel }
    : { IO_PIN_ORDER_CFG: "dir::" + rel };
  try {
    const r = await api.configSet(set);
    toast.show((kind === "sdc" ? "Timing constraints" : "Pin order") + " set to " + rel + " in " + r.name + ".", "success");
    await loadFilesFor(state.designDir);
    document.dispatchEvent(new CustomEvent("g:config_changed"));
  } catch (ex) {
    toast.show("Couldn't update the config: " + (ex.message || ex), "error", 7000);
  }
}

export function wireSourceActions() {
  document.getElementById("filesel-list")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-src-act]");
    if (!b) return;
    e.preventDefault();
    const act = b.dataset.srcAct;
    if (act === "use-sdc") useFileFor("sdc", b.dataset.rel);
    else if (act === "use-pins") useFileFor("pins", b.dataset.rel);
    else if (act === "new-sdc") {
      document.querySelector('.side-tab[data-tab="ide"]')?.click();
      import("./ide/main.js").then(async (m) => {
        await m.initIde({ designDir: state.designDir, runMode: state.runMode });
        m.newFile("sdc");
      });
    }
  });
}

// Add freshly added design files (Add files…) to the config's list.
export function includeInConfig(absPaths) {
  for (const p of absPaths) _checked.add(p);
  onTicksChanged();
}

function commitSelection() {
  state.selectedFiles = Array.from(_checked);
  // Push to libs to apply on next Run.
  const extras = (document.getElementById("filesel-extras")?.value || "")
    .split(",")
    .map((x) => x.trim())
    .filter(Boolean);
  state.extrasFiles = extras;
}
