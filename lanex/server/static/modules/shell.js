// shell.js — the frame's behaviour: the project switcher, the Run menu, the
// help sheet (Learn / Shortcuts / About), the status line and page titles.
//
// Every overlay here is light-dismiss: clicking anywhere outside it, or Esc,
// closes it. Only one overlay is open at a time.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { SHORTCUTS } from "./hotkeys.js";

// ------------------------------------------------------------ overlay manager
// One open overlay at a time; outside pointerdown or Esc closes it.
let _open = null; // { el, owner, close }

function closeOpen() {
  if (!_open) return;
  const o = _open;
  _open = null;
  o.close();
}

export function openOverlay(el, owner, close) {
  if (_open && _open.el !== el) closeOpen();
  _open = { el, owner, close };
}

export function isOverlayOpen(el) {
  return !!_open && _open.el === el;
}

export function releaseOverlay(el) {
  if (_open && _open.el === el) _open = null;
}

function wireLightDismiss() {
  document.addEventListener("pointerdown", (e) => {
    if (!_open) return;
    const t = e.target;
    if (_open.el.contains(t)) return;
    if (_open.owner && _open.owner.contains(t)) return;
    // Clicks inside a modal dialog or the palette belong to them, not to us.
    if (t.closest && t.closest(".dlg-backdrop, .smodal-backdrop, .cmdk, .toast, #fs-modal")) return;
    closeOpen();
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && _open) { closeOpen(); e.stopPropagation(); }
  });
}

// ------------------------------------------------------------ menus
function wireMenu(btn, menu, onOpen) {
  if (!btn || !menu) return;
  const close = () => {
    menu.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  };
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!menu.hidden) { closeOpen(); return; }
    menu.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    openOverlay(menu, btn, close);
    if (onOpen) onOpen();
    menu.querySelector(".menu-item")?.focus({ preventScroll: true });
  });
  // Arrow keys move between items; picking an item closes the menu.
  menu.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const items = [...menu.querySelectorAll(".menu-item:not(:disabled)")];
    const i = items.indexOf(document.activeElement);
    const n = e.key === "ArrowDown" ? (i + 1) % items.length : (i - 1 + items.length) % items.length;
    items[n]?.focus();
    e.preventDefault();
  });
  menu.addEventListener("click", (e) => {
    if (e.target.closest(".menu-item")) closeOpen();
  });
}

// ------------------------------------------------------------ project switcher
function baseName(p) {
  const s = String(p || "").replace(/[\\/]+$/, "");
  return s.slice(Math.max(s.lastIndexOf("/"), s.lastIndexOf("\\")) + 1) || s;
}

// Where projects go by default, and how to show paths the way the person's OS
// does. On the Windows appliance a path is shown as Explorer would show it
// (C:\Users\... or \\wsl.localhost\<distro>\...); the server accepts either form.
let _defaults = null;
async function defaults() {
  if (_defaults) return _defaults;
  try { _defaults = await api.projectDefaults(); } catch (_e) { _defaults = {}; }
  return _defaults;
}

export function displayPath(p) {
  const path = String(p || "");
  if (!_defaults || !_defaults.wsl || !path.startsWith("/")) return path;
  const drive = path.match(/^\/mnt\/([a-z])(\/.*)?$/);
  if (drive) return drive[1].toUpperCase() + ":" + (drive[2] || "/").replace(/\//g, "\\");
  const distro = _defaults.distro || "lanex";
  return "\\\\wsl.localhost\\" + distro + path.replace(/\//g, "\\");
}

export function paintProject() {
  const btn = document.getElementById("design-pill");
  if (!btn) return;
  const dir = state.designDir;
  const text = btn.querySelector(".text");
  btn.classList.toggle("is-empty", !dir);
  if (text) text.textContent = dir ? baseName(dir) : "No project open";
  btn.dataset.tip = dir ? displayPath(dir) : "Create a project or open a folder";
  const reveal = document.getElementById("btn-reveal-project");
  if (reveal) reveal.disabled = !dir;
}

// The last list the server gave; a failed fetch shows that instead of an
// almost-empty list.
let _serverKnown = [];
async function knownProjects() {
  let dirs = [];
  try { dirs = _serverKnown = (await api.knownDesigns()).designs || []; } catch (_e) { dirs = _serverKnown.slice(); }
  try {
    const local = JSON.parse(localStorage.getItem("ll.recentDesigns") || "[]");
    for (const d of local) if (d && !dirs.includes(d)) dirs.push(d);
  } catch (_e) {}
  if (state.designDir && !dirs.includes(state.designDir)) dirs.unshift(state.designDir);
  return dirs;
}

const RECENT_IN_MENU = 6;

async function renderRecents() {
  const host = document.getElementById("project-recents");
  if (!host) return;
  await defaults();
  const dirs = await knownProjects();
  if (!dirs.length) {
    host.innerHTML = "<div class='project-empty'>No projects yet. Start one below.</div>";
    return;
  }
  const shown = dirs.slice(0, RECENT_IN_MENU);
  host.innerHTML = shown.map((d) =>
    "<button class='menu-item project-row" + (d === state.designDir ? " is-current" : "") +
    "' role='menuitem' data-dir='" + fmt.escape(d) + "'>" +
    "<span class='via' aria-hidden='true'></span>" +
    "<span class='mi-text'><b>" + fmt.escape(baseName(d)) + "</b><small>" + fmt.escape(displayPath(d)) + "</small></span>" +
    "</button>").join("") +
    "<button class='menu-item project-more' role='menuitem' id='btn-manage-projects'>" +
    (dirs.length > RECENT_IN_MENU ? "All " + dirs.length + " projects…" : "Manage projects…") + "</button>";
  host.querySelectorAll(".project-row").forEach((b) =>
    b.addEventListener("click", () => switchProject(b.dataset.dir)));
  host.querySelector("#btn-manage-projects")?.addEventListener("click", () => manageProjects());
}

// Where a project lives, short: its parent folder's last two parts
// ("lanex-projects\lanextest"), enough to tell same-named projects apart.
// The full path is on hover.
function whereShort(d) {
  const full = displayPath(String(d).replace(/[\\/]+$/, ""));
  const sep = full.includes("\\") ? "\\" : "/";
  const parts = full.split(/[\\/]+/).filter(Boolean);
  parts.pop();
  return parts.slice(-2).join(sep) || full;
}

// The project list on the Setup page: every project LanEx knows about, the
// open one marked. Clicking a row opens it.
let _hubSeq = 0;
// Rows keep the place they had when the page loaded: opening a project marks
// it where it is instead of jumping it to the top (the top-bar menu is the
// most-recent-first list). Projects seen for the first time go on top.
let _hubOrder = [];
function stableOrder(dirs) {
  const known = _hubOrder.filter((d) => dirs.includes(d));
  const fresh = dirs.filter((d) => !known.includes(d));
  _hubOrder = fresh.concat(known);
  return _hubOrder.slice();
}

export async function renderHubRows() {
  const host = document.getElementById("hub-rows");
  if (!host) return;
  const seq = ++_hubSeq;
  await defaults();
  const dirs = stableOrder(await knownProjects());
  if (seq !== _hubSeq) return;   // a newer render is on its way
  const scroll = host.scrollTop;
  // First run, nothing anywhere yet: the start tiles get the whole card.
  document.getElementById("setup-design")?.classList.toggle("no-projects", !dirs.length);
  if (!dirs.length) {
    host.innerHTML = "<p class='hub-none'>No projects yet. New projects go in <code>" +
      fmt.escape(displayPath((_defaults && _defaults.projects_dir) || "")) + "</code>.</p>";
    return;
  }
  host.innerHTML = dirs.map((d) => {
    const cur = d === state.designDir;
    return "<button class='hub-row" + (cur ? " is-current" : "") + "' data-dir='" + fmt.escape(d) + "'" +
      (cur ? " aria-current='true'" : "") + " title='" + fmt.escape(displayPath(d)) + "'>" +
      "<span class='via' aria-hidden='true'></span>" +
      "<span class='hub-row-text'><b>" + fmt.escape(baseName(d)) + "</b><small>" + fmt.escape(whereShort(d)) + "</small></span>" +
      "</button>";
  }).join("");
  host.scrollTop = scroll;
}

function wireHub() {
  const host = document.getElementById("hub-rows");
  if (!host) return;
  host.addEventListener("click", (e) => {
    const row = e.target.closest(".hub-row");
    if (row) switchProject(row.dataset.dir);
  });
  const sec = document.getElementById("setup-design");
  sec?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-open]");
    if (!b) return;
    if (b.dataset.open === "open-folder") openFolder();
    else if (b.dataset.open === "manage") manageProjects();
  });
  document.addEventListener("g:projects_changed", () => renderHubRows());
  renderHubRows();
}

async function switchProject(dir) {
  if (!dir || dir === state.designDir) return;
  try {
    const res = await api.setDesignDir(dir);
    const setup = await import("./setup.js");
    const input = document.getElementById("design-dir-input");
    if (input) input.value = res.design_dir || dir;
    await setup.adoptDesignDir(res.design_dir || dir);
    document.querySelector('.side-tab[data-tab="setup"]')?.click();
    toast.show("Opened " + baseName(dir) + ".", "success");
  } catch (ex) {
    toast.show("Could not open " + displayPath(dir) + ": " + (ex.message || ex), "error");
  }
}

export async function openFolder() {
  const { pickFolder } = await import("./fs.js");
  const d = await defaults();
  const dir = await pickFolder({ title: "Open a project folder", use: "Open this folder",
    seed: (d && d.projects_dir) || state.designDir || "" });
  if (dir) await switchProject(dir);
}

async function revealProject(dir) {
  const target = dir || state.designDir;
  if (!target) return;
  try {
    await api.revealDesign(target);
  } catch (ex) {
    toast.show("Could not open the file manager: " + (ex.message || ex), "error");
  }
}

function forgetLocally(dir) {
  try {
    const list = JSON.parse(localStorage.getItem("ll.recentDesigns") || "[]").filter((d) => d !== dir);
    localStorage.setItem("ll.recentDesigns", JSON.stringify(list));
  } catch (_e) {}
}

// Every project LanEx knows about, with the ways to tidy the list. Deleting a
// folder is only offered for projects inside the LanEx projects folder; a
// folder anywhere else is the person's own and can only leave the list.
async function manageProjects() {
  const d = await defaults();
  const root = (d && d.projects_dir) || "";
  const inRoot = (p) => !!root && (p + "/").startsWith(root.replace(/\/+$/, "") + "/") && p !== root;
  const { customDialog, confirmTyped } = await import("./dialog.js");
  const render = async (back) => {
    const dirs = await knownProjects();
    const list = back.querySelector(".pm-list");
    if (!dirs.length) { list.innerHTML = "<p class='muted'>No projects yet.</p>"; return; }
    list.innerHTML = dirs.map((p) =>
      "<div class='pm-row" + (p === state.designDir ? " is-current" : "") + "' data-dir='" + fmt.escape(p) + "'>" +
      "<span class='via' aria-hidden='true'></span>" +
      "<span class='pm-text'><b>" + fmt.escape(baseName(p)) + (p === state.designDir ? " <em>open now</em>" : "") +
      "</b><small>" + fmt.escape(displayPath(p)) + "</small></span>" +
      "<span class='pm-acts'>" +
      (p === state.designDir ? "" : "<button class='btn btn-sm' data-act='open'>Open</button>") +
      "<button class='btn btn-sm btn-ghost' data-act='reveal'>Show</button>" +
      "<button class='btn btn-sm btn-ghost' data-act='forget' title='Take it off this list. The folder stays where it is.'>Remove from list</button>" +
      (inRoot(p) && p !== state.designDir
        ? "<button class='btn btn-sm btn-ghost pm-danger' data-act='delete'>Delete…</button>" : "") +
      "</span></div>").join("");
  };
  await customDialog({
    title: "Projects",
    wide: true,
    bodyHtml:
      "<p class='muted pm-note'>New projects go in <code>" + fmt.escape(displayPath(root)) + "</code>. " +
      "Removing a project from this list leaves its folder alone; only projects in that folder can be deleted here.</p>" +
      "<div class='pm-list'></div>",
    onMount: (back, close) => {
      back.querySelector(".dlg")?.classList.add("dlg-pm");
      render(back);
      back.querySelector(".pm-list").addEventListener("click", async (e) => {
        const b = e.target.closest("[data-act]");
        const row = e.target.closest(".pm-row");
        if (!b || !row) return;
        const p = row.dataset.dir;
        if (b.dataset.act === "open") { close(); switchProject(p); }
        else if (b.dataset.act === "reveal") revealProject(p);
        else if (b.dataset.act === "forget") {
          try { await api.projectForget(p); } catch (_e) {}
          forgetLocally(p);
          render(back);
        } else if (b.dataset.act === "delete") {
          const name = baseName(p);
          const ok = await confirmTyped({
            title: "Delete " + name + "?",
            body: "This permanently deletes the folder " + displayPath(p) +
              ", including its Verilog, config and every run in it. It can't be undone.",
            phrase: name, confirmText: "Delete project",
          });
          if (!ok) return;
          try {
            await api.projectDelete(p, name);
            forgetLocally(p);
            toast.show("Deleted " + name + ".", "success");
          } catch (ex) {
            toast.show("Could not delete " + name + ": " + (ex.message || ex), "error");
          }
          render(back);
        }
      });
    },
  });
  renderHubRows();
}

// ------------------------------------------------------------ run menu + status mirrors
const MODE_NAMES = { auto: "Full auto", semi: "Step by step" };
const ENGINE_NAMES = { container: "Container", local: "Local tools" };

export function paintRunSettings() {
  const m = document.getElementById("st-mode-v");
  const e = document.getElementById("st-engine-v");
  if (m) m.textContent = MODE_NAMES[state.mode] || "Full auto";
  if (e) e.textContent = ENGINE_NAMES[state.runMode === "local" ? "local" : "container"];
}

export function paintProgress(done, total) {
  const fill = document.getElementById("status-bar-fill");
  if (!fill) return;
  fill.style.transform = "scaleX(" + (total ? Math.min(1, done / total) : 0) + ")";
}

// ------------------------------------------------------------ page titles
// Each tab's sticky header names the page it belongs to, from the rail label.
function paintPageTitles() {
  document.querySelectorAll(".work > .section").forEach((sec) => {
    const tab = sec.id.replace(/^sec-/, "");
    const label = document.querySelector('.side-tab[data-tab="' + tab + '"] .label');
    const bar = sec.querySelector(":scope > .section-jump, :scope > .section-jump-stack > .section-jump");
    if (!bar || !label || bar.querySelector(".page-title")) return;
    const h = document.createElement("h1");
    h.className = "page-title";
    h.textContent = label.textContent === "Cells" ? "Cells & macros" : label.textContent;
    bar.prepend(h);
  });
}

// ------------------------------------------------------------ help sheet
let _sheet = null;

function sheet() {
  if (_sheet) return _sheet;
  const el = document.createElement("aside");
  el.className = "sheet";
  el.id = "help-sheet";
  el.hidden = true;
  el.setAttribute("aria-label", "Help");
  el.innerHTML =
    "<div class='sheet-head' role='tablist'>" +
    "<button class='sheet-tab' role='tab' data-pane='learn'>Learn</button>" +
    "<button class='sheet-tab' role='tab' data-pane='keys'>Shortcuts</button>" +
    "<button class='sheet-tab' role='tab' data-pane='about'>About</button>" +
    "<button class='iconbtn' data-act='close' aria-label='Close help'>" +
    "<svg viewBox='0 0 24 24' width='16' height='16' fill='none' stroke='currentColor' stroke-width='1.7' stroke-linecap='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button>" +
    "</div><div class='sheet-body' id='help-sheet-body'></div>";
  document.body.appendChild(el);
  el.querySelector("[data-act='close']").addEventListener("click", () => closeOpen());
  el.querySelectorAll(".sheet-tab").forEach((t) =>
    t.addEventListener("click", () => showPane(t.dataset.pane)));
  _sheet = el;
  return el;
}

function closeSheet() {
  if (!_sheet) return;
  _sheet.hidden = true;
  document.getElementById("help-icon")?.setAttribute("aria-pressed", "false");
}

// Open the help sheet on a pane. Returns the body element for callers (Learn's
// step/metric explanations render straight into it).
export function openHelp(pane = "learn", { render = true } = {}) {
  const el = sheet();
  if (el.hidden) {
    el.hidden = false;
    document.getElementById("help-icon")?.setAttribute("aria-pressed", "true");
    openOverlay(el, document.getElementById("help-icon"), closeSheet);
  }
  if (!render) {
    selectHelpTab(pane);
    const body = el.querySelector("#help-sheet-body");
    body.scrollTop = 0;
    return body;
  }
  return showPane(pane);
}

function showPane(pane) {
  const el = sheet();
  el.querySelectorAll(".sheet-tab").forEach((t) =>
    t.setAttribute("aria-selected", t.dataset.pane === pane ? "true" : "false"));
  const body = el.querySelector("#help-sheet-body");
  body.scrollTop = 0;
  if (pane === "keys") renderKeys(body);
  else if (pane === "about") renderAbout(body);
  else if (pane === "learn") import("./learn.js").then((m) => m.renderGlossary(body));
  return body;
}

export function helpBody() {
  return sheet().querySelector("#help-sheet-body");
}

export function selectHelpTab(pane) {
  sheet().querySelectorAll(".sheet-tab").forEach((t) =>
    t.setAttribute("aria-selected", t.dataset.pane === pane ? "true" : "false"));
}

function renderKeys(body) {
  const row = (keys, desc) =>
    "<div class='keys-row'><span>" +
    keys.split(" / ").map((k) => "<kbd>" + fmt.escape(k) + "</kbd>").join(" ") +
    "</span><span class='keys-desc'>" + fmt.escape(desc) + "</span></div>";
  body.innerHTML =
    "<h2>Keyboard shortcuts</h2>" +
    "<p class='muted'>Single-letter keys work anywhere except while you're typing in a field.</p>" +
    "<div class='keys'>" + SHORTCUTS.map((s) => row(s.keys, s.desc)).join("") + "</div>";
}

async function renderAbout(body) {
  let about = null;
  try {
    const r = await fetch("/api/about", { headers: { "X-Requested-With": "XMLHttpRequest" } });
    about = r.ok ? await r.json() : null;
  } catch (_e) {}
  const ver = about && about.version;
  const ll = about && about.librelane;
  body.innerHTML =
    "<h2>LanEx</h2>" +
    "<p>A cockpit for the LibreLane RTL-to-GDSII flow. LanEx drives LibreLane and the EDA tools it " +
    "runs, and shows their output as-is.</p>" +
    "<dl class='about-facts'>" +
    (ver ? "<dt>Version</dt><dd>" + fmt.escape(ver) + "</dd>" : "") +
    (ll ? "<dt>LibreLane</dt><dd>" + fmt.escape(ll) + "</dd>" : "") +
    "<dt>License</dt><dd>Apache License 2.0, provided AS IS, without warranty</dd>" +
    "<dt>Built on</dt><dd>LibreLane, OpenROAD, Yosys, Magic, KLayout and Netgen, run as separate programs (not bundled)</dd>" +
    "<dt>Affiliation</dt><dd>Independent project, not affiliated with or endorsed by LibreLane</dd>" +
    "</dl>" +
    "<div class='about-warn'><b>Not a sign-off tool.</b> Every number LanEx shows comes from the EDA tools. " +
    "Before you fabricate, check your design against your foundry's official sign-off decks, and run " +
    "LibreLane directly if you plan to manufacture.</div>" +
    "<div class='about-links'>" +
    "<a class='btn btn-ghost btn-sm' href='https://librelane.org/' target='_blank' rel='noopener'>LibreLane docs</a>" +
    "<a class='btn btn-ghost btn-sm' href='https://github.com/AkshatIsWired/lanex' target='_blank' rel='noopener'>LanEx on GitHub</a>" +
    "</div>" +
    "<details class='about-full'><summary>Full license and notices</summary><pre id='about-notice'></pre></details>";
  // Only ever the repo's real NOTICE text, never a hand-written copy.
  body.querySelector("#about-notice").textContent = (about && about.notice) ||
    "The NOTICE file isn't available from this install. See LICENSE and NOTICE in the LanEx repository.";
}

// ------------------------------------------------------------ setup
export function setupShell() {
  wireLightDismiss();
  wireMenu(document.getElementById("design-pill"), document.getElementById("project-menu"), renderRecents);
  wireMenu(document.getElementById("run-opts-btn"), document.getElementById("run-menu"));
  document.getElementById("btn-open-project")?.addEventListener("click", openFolder);
  document.getElementById("btn-reveal-project")?.addEventListener("click", () => revealProject());
  document.getElementById("help-icon")?.addEventListener("click", () => {
    if (_sheet && !_sheet.hidden) closeOpen(); else openHelp("learn");
  });
  // Status items jump to where the setting lives.
  document.getElementById("pdk-pill")?.addEventListener("click", () => {
    document.querySelector('.side-tab[data-tab="setup"]')?.click();
    setTimeout(() => document.getElementById("setup-pdk")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  });
  const openRunMenu = (e) => { e.stopPropagation(); document.getElementById("run-opts-btn")?.click(); };
  document.getElementById("st-engine")?.addEventListener("click", openRunMenu);
  document.getElementById("st-mode")?.addEventListener("click", openRunMenu);
  // Mode/engine changes happen in setup.js / runmode.js; mirror them here.
  document.getElementById("run-menu")?.addEventListener("click", () => setTimeout(paintRunSettings, 0));
  // Label the reveal action for the platform people are actually on.
  defaults().then((d) => {
    const lbl = document.getElementById("reveal-label");
    if (lbl && d && d.wsl) lbl.textContent = "Show in Explorer";
    const r2 = document.getElementById("proj-reveal");
    if (r2 && d && !d.wsl) r2.textContent = "Show in file manager";
    paintProject();
  }).catch(() => {});
  paintPageTitles();
  paintProject();
  paintRunSettings();
  wireHub();
}
