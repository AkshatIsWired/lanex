// fs.js — folder browser modal + file selector.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { icon } from "./icons.js";

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
    _checked.clear();
    for (const s of state.designSources) if (!isTestbench(s)) _checked.add(s.abspath);
    for (const m of state.designMemories) _checked.add(m.abspath);
    renderFileSelector();
    commitSelection();
  });
  document.getElementById("btn-filesel-none")?.addEventListener("click", () => {
    _checked.clear();
    renderFileSelector();
    commitSelection();
  });
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
export async function pickFolder(opts = {}) {
  try {
    const r = await api.nativePick({ mode: "folder", title: opts.title || "Choose a folder", start: opts.seed || "" });
    if (r && r.native) return (r.paths && r.paths[0]) || null;
  } catch (_e) { /* fall through to the built-in browser */ }
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

export async function loadFilesFor(designDir, opts = {}) {
  const show = opts.show !== false;
  const card = document.getElementById("filesel-card");
  if (!designDir) {
    state.designSources = [];
    state.designMemories = [];
    if (card) card.hidden = true;
    paintCount();
    return;
  }
  try {
    const r = await api.walkSources(designDir);
    if (!r.ok) return;
    state.designSources = r.sources;
    state.designMemories = r.memories;
    if (card) card.hidden = !show;
    // Keep the person's earlier choices for files that are still here; a fresh
    // project ticks every design file and memory file, never a testbench.
    const present = new Set(state.designSources.concat(state.designMemories).map((x) => x.abspath));
    const kept = [..._checked].filter((x) => present.has(x));
    _checked.clear();
    if (kept.length && _checkedFor === designDir) {
      for (const x of kept) _checked.add(x);
      // A file added since (from the RTL IDE or Add files) starts ticked too.
      for (const s of state.designSources) if (!_seen.has(s.abspath) && !isTestbench(s)) _checked.add(s.abspath);
    } else {
      for (const s of state.designSources) if (!isTestbench(s)) _checked.add(s.abspath);
      for (const m of state.designMemories) _checked.add(m.abspath);
    }
    _checkedFor = designDir;
    _seen = present;
    renderFileSelector();
    commitSelection();
  } catch (_e) {
    state.designSources = [];
    state.designMemories = [];
    if (card) card.hidden = true;
  }
}

function paintCount() {
  const el = document.getElementById("filesel-count");
  if (!el) return;
  if (!state.designDir) { el.textContent = "Open a project to see its files."; return; }
  const design = (state.designSources || []).filter((s) => !isTestbench(s));
  const tbs = (state.designSources || []).length - design.length;
  const ticked = design.filter((s) => _checked.has(s.abspath)).length;
  el.textContent = ticked + " of " + design.length + " design file" + (design.length === 1 ? "" : "s") +
    " ticked" + (tbs ? " · " + tbs + " testbench" + (tbs === 1 ? "" : "es") : "");
}

function groupHead(text, note) {
  const h = document.createElement("div");
  h.className = "filesel-group";
  h.innerHTML = "<span class='lane-label'>" + fmt.escape(text) + "</span>" +
    (note ? "<span class='filesel-group-note'>" + fmt.escape(note) + "</span>" : "");
  return h;
}

function renderFileSelector() {
  const root = document.getElementById("filesel-list");
  if (!root) return;
  root.innerHTML = "";
  const srcs = state.designSources || [];
  const mems = state.designMemories || [];
  if (!srcs.length && !mems.length) {
    root.innerHTML = "<div class='filesel-empty'><b>No Verilog in this project yet.</b>" +
      "<span>Use <b>New file</b> to write a module in the RTL IDE, or <b>Add files</b> to bring in ones you already have.</span></div>";
    paintCount();
    return;
  }
  const design = srcs.filter((s) => !isTestbench(s));
  const tbs = srcs.filter((s) => isTestbench(s));
  if (design.length) {
    root.appendChild(groupHead("Design files", "synthesized into the chip"));
    for (const s of design) root.appendChild(makeRow(s, "RTL"));
  }
  if (tbs.length) {
    root.appendChild(groupHead("Testbenches", "simulation only, open them in the RTL IDE"));
    for (const s of tbs) root.appendChild(makeRow(s, "TB"));
  }
  if (mems.length) {
    root.appendChild(groupHead("Memory files", "initial contents for memories"));
    for (const m of mems) root.appendChild(makeRow(m, "MEM"));
  }
  paintCount();
}

function makeRow(item, kind) {
  const row = document.createElement("label");
  row.className = "filesel-row" + (kind === "TB" ? " is-tb" : "");
  row.dataset.path = item.abspath;
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = _checked.has(item.abspath);
  cb.setAttribute("aria-label", (kind === "TB" ? "Synthesize " : "Include ") + item.relpath);
  cb.addEventListener("change", () => {
    if (cb.checked) _checked.add(item.abspath);
    else _checked.delete(item.abspath);
    paintCount();
    commitSelection();
  });
  row.appendChild(cb);
  const label = document.createElement("span");
  label.className = "name";
  label.textContent = item.relpath;
  row.appendChild(label);
  const size = document.createElement("span");
  size.className = "size";
  size.textContent = fmt.metric(item.size) + " B";
  row.appendChild(size);
  if (kind !== "MEM") {
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "btn btn-sm btn-ghost filesel-edit";
    edit.dataset.open = "edit";
    edit.dataset.rel = item.relpath;
    edit.textContent = "Edit";
    row.appendChild(edit);
  }
  return row;
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
