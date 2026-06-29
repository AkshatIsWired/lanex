// fs.js — folder browser modal + file selector.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { icon } from "./icons.js";

let _curPath = "";
const _checked = new Set();

export function setupFolderBrowser() {
  document.getElementById("btn-browse-folder")?.addEventListener("click", openModal);
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
    for (const s of state.designSources) _checked.add(s.abspath);
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

async function openModal() {
  const modal = document.getElementById("fs-modal");
  modal.hidden = false;
  await loadRoots();
  const seed = (document.getElementById("design-dir-input")?.value || "").trim();
  await fetchDir(seed || (await defaultSeed()) || ("/"));
}

function closeModal() {
  const modal = document.getElementById("fs-modal");
  modal.hidden = true;
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
  document.getElementById("design-dir-input").value = _curPath;
  closeModal();
  // Trigger a load + scan:
  document.getElementById("btn-set-design").click();
}

// `opts.show` (default true) reveals the file-selector card. At boot we adopt a
// design only to scope Runs/Preview — there we call with {show:false} so the
// selection is computed (a run still works) but the card stays hidden until the
// user *explicitly* loads a design; the Setup tab then shows the history
// (recent designs) instead of a directory's files.
export async function loadFilesFor(designDir, opts = {}) {
  const show = opts.show !== false;
  if (!designDir) {
    state.designSources = [];
    state.designMemories = [];
    document.getElementById("filesel-card").hidden = true;
    return;
  }
  try {
    const r = await api.walkSources(designDir);
    if (!r.ok) return;
    state.designSources = r.sources;
    state.designMemories = r.memories;
    document.getElementById("filesel-card").hidden = !show;
    // By default, all checked; preserve any user deselection.
    const keep = new Set();
    for (const s of state.designSources) if (_checked.has(s.abspath)) keep.add(s.abspath);
    for (const m of state.designMemories) if (_checked.has(m.abspath)) keep.add(m.abspath);
    _checked.clear();
    for (const s of state.designSources) _checked.add(s.abspath);
    for (const m of state.designMemories) _checked.add(m.abspath);
    // keep preserves the old user choice
    _checked.clear();
    for (const x of keep) _checked.add(x);
    if (!_checked.size) {
      // Default: every file checked + first memory file checked.
      for (const s of state.designSources) _checked.add(s.abspath);
      for (const m of state.designMemories) _checked.add(m.abspath);
    }
    renderFileSelector();
    commitSelection();
  } catch (_e) {
    state.designSources = [];
    state.designMemories = [];
    document.getElementById("filesel-card").hidden = true;
  }
}

function renderFileSelector() {
  const root = document.getElementById("filesel-list");
  if (!root) return;
  root.innerHTML = "";
  if (state.designSources.length === 0 && state.designMemories.length === 0) {
    root.innerHTML = "<div class='empty'><span class='ico'>" + icon('folderOpen',{size:40}) + "</span><h3>No HDL files detected</h3><p>Try a different folder or place <code>.v</code> files inside it.</p></div>";
    document.getElementById("filesel-count").textContent = "0 files";
    return;
  }
  // Sources group
  if (state.designSources.length) {
    const heading = document.createElement("div");
    heading.className = "muted";
    heading.style.cssText = "padding:8px 10px;font-family:var(--mono);font-size:var(--t-xs);color:var(--text-muted);letter-spacing:0.04em;text-transform:uppercase;";
    heading.textContent = "Sources (" + state.designSources.length + ")";
    root.appendChild(heading);
    for (const s of state.designSources) root.appendChild(makeRow(s, "RTL"));
  }
  if (state.designMemories.length) {
    const heading = document.createElement("div");
    heading.className = "muted";
    heading.style.cssText = "padding:8px 10px;font-family:var(--mono);font-size:var(--t-xs);color:var(--text-muted);letter-spacing:0.04em;text-transform:uppercase;";
    heading.textContent = "Memory files (" + state.designMemories.length + ")";
    root.appendChild(heading);
    for (const m of state.designMemories) root.appendChild(makeRow(m, "MEM"));
  }
  document.getElementById("filesel-count").textContent =
    _checked.size + " of " + (state.designSources.length + state.designMemories.length) + " selected";
}

function makeRow(item, kind) {
  const row = document.createElement("label");
  row.className = "filesel-row";
  row.dataset.path = item.abspath;
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.checked = _checked.has(item.abspath);
  cb.style.cursor = "pointer";
  cb.addEventListener("change", () => {
    if (cb.checked) _checked.add(item.abspath);
    else _checked.delete(item.abspath);
    renderFileSelector();
    commitSelection();
  });
  row.appendChild(cb);
  const label = document.createElement("span");
  label.className = "name";
  label.textContent = item.relpath;
  row.appendChild(label);
  const tail = document.createElement("span");
  tail.style.display = "inline-flex";
  tail.style.alignItems = "center";
  tail.style.gap = "6px";
  const ext = document.createElement("span");
  ext.className = "ext";
  ext.textContent = (item.ext || "").replace(".", "").toUpperCase();
  tail.appendChild(ext);
  const size = document.createElement("span");
  size.className = "size";
  size.textContent = fmt.metric(item.size) + " B";
  tail.appendChild(size);
  row.appendChild(tail);
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
