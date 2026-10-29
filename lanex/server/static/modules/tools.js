// tools.js — the Tools tab. One page that reads in a glance:
//   1. a verdict band: ready to run or not, and every problem with its fix;
//   2. the flow engine (container engine + LibreLane image) as the hero;
//   3. PDKs as family cards (variants, pinned-version match, size);
//   4. viewers and helpers as cards: what each is for and what in LanEx uses it;
//   5. the local toolchain, folded away (only the Local tools engine needs it).
// Healthy items stay quiet; Install / Update / Repair appear only when needed;
// Remove sits behind a "More" menu with a confirm. Shell-only installs depend
// on this page to install, update, repair and remove everything, so every
// action the older pages had is still here.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
// Tool work (installs, removals, the engine) is told in the Logs panel, with
// the install output it belongs to; the run's own log is Flow's.
const renderLogs = {
  append: (e) => import("./logdrawer.js").then((d) => d.appendDrawer((e.payload || e).message || "")).catch(() => {}),
};
import { toast } from "./toast.js";
import { confirmDialog, customDialog } from "./dialog.js";
import { icon } from "./icons.js";

const esc = (s) => fmt.escape(s == null ? "" : String(s));

export function normalizeUnavailableLibraries(value) {
  if (Array.isArray(value)) {
    return Object.fromEntries(
      value.map((id) => [String(id), "Not published for this release"]),
    );
  }
  if (value && typeof value === "object") return { ...value };
  return {};
}

// PDK family of a catalog key. The catalog says it; the fallback knows the
// three families LibreLane ships hashes for.
export function pdkFamily(catalog, key) {
  const fam = catalog && catalog[key] && catalog[key].family;
  if (fam) return fam;
  if (key.startsWith("sky130")) return "sky130";
  if (key.startsWith("gf180mcu")) return "gf180mcu";
  if (key.startsWith("ihp") || key.includes("sg13g2")) return "ihp-sg13g2";
  return key;
}

// Catalog -> [{ family, keys }] in catalog order; within a family the default
// variant comes first, then the rest in catalog order.
export function pdkFamilies(catalog) {
  const fams = new Map();
  for (const key of Object.keys(catalog || {})) {
    const f = pdkFamily(catalog, key);
    if (!fams.has(f)) fams.set(f, []);
    fams.get(f).push(key);
  }
  const isDef = (k) => !!(catalog[k] && (catalog[k].default_variant || catalog[k].recommended));
  return [...fams].map(([family, keys]) => ({
    family,
    keys: keys.filter(isDef).concat(keys.filter((k) => !isDef(k))),
  }));
}

// Families -> two columns of about equal height (a card header counts as about
// one and a half variant rows). Biggest family first into the shorter column;
// each column keeps catalog order, and the column holding the first family
// goes on the left.
export function pdkColumns(fams) {
  const cols = [{ h: 0, idx: [] }, { h: 0, idx: [] }];
  const order = fams.map((f, i) => i).sort((a, b) => fams[b].keys.length - fams[a].keys.length || a - b);
  for (const i of order) {
    const c = cols[0].h <= cols[1].h ? cols[0] : cols[1];
    c.idx.push(i);
    c.h += fams[i].keys.length + 1.5;
  }
  return cols
    .map((c) => c.idx.sort((a, b) => a - b))
    .filter((idx) => idx.length)
    .sort((a, b) => a[0] - b[0])
    .map((idx) => idx.map((i) => fams[i]));
}

let _pdkRoot = "";
async function loadPdkRoot() {
  const input = document.getElementById("pdk-root-input");
  try {
    const rootInfo = await api.getPdkRoot();
    if (rootInfo && rootInfo.ok && rootInfo.pdk_root) {
      _pdkRoot = rootInfo.pdk_root;
      if (input) input.value = rootInfo.pdk_root;
      const shown = document.getElementById("tl-pdkroot-path");
      if (shown) { shown.textContent = _pdkRoot; shown.title = _pdkRoot; }
    }
  } catch (ex) {
    console.warn("Failed to load PDK root:", ex);
  }
}

// ------------------------------------------------------------------ pieces
const STATE_TEXT = {
  ready: "Ready", update: "Update available", missing: "Missing", broken: "Broken",
  custom: "Custom", off: "Not installed", busy: "Working", image: "In image",
};
const PROBLEM = new Set(["missing", "broken", "custom"]);
const FAIL = new Set(["missing", "broken"]);
const WARN = new Set(["custom", "update"]);

// The small status mark used everywhere: a quiet tick when healthy, a coloured
// dot and word when not.
function stateHtml(st, text) {
  const mark = st === "ready" || st === "image" ? icon("check", { size: 13, stroke: 2 }) : "<i></i>";
  return "<span class='tl-state is-" + st + "'>" + mark + esc(text || STATE_TEXT[st] || st) + "</span>";
}

function moreHtml(menu) {
  const items = (menu || []).filter(Boolean);
  if (!items.length) return "";
  return "<details class='tl-more'><summary class='tl-more-btn' title='More actions' aria-label='More actions'>" +
    "<svg viewBox='0 0 24 24' width='16' height='16' fill='currentColor' aria-hidden='true'><circle cx='5' cy='12' r='1.6'/><circle cx='12' cy='12' r='1.6'/><circle cx='19' cy='12' r='1.6'/></svg>" +
    "</summary><div class='tl-menu'>" + items.join("") + "</div></details>";
}

// One local-toolchain row: status | what it is | installed version | size | action.
// `r`: { id, name, purpose, warn, status, chip, have, want, size, action, menu, sub, inst }.
export function rowHtml(r) {
  const st = r.status || "off";
  const chip = r.chip || STATE_TEXT[st] || st;
  const menu = (r.menu || []).filter(Boolean);
  return (
    "<div class='tl-row" + (PROBLEM.has(st) ? " is-problem" : "") + "' id='" + esc(r.id) + "' data-status='" + st + "'" +
      " data-inst='" + (r.inst ? "1" : "0") + "'>" +
      "<span class='tl-chip is-" + st + "'><span class='d'></span>" + esc(chip) + "</span>" +
      "<div class='tl-what'><div class='tl-name' data-name='" + esc(r.label || '') + "'>" + r.name + "</div>" +
        "<div class='tl-purpose' title='" + esc(r.purposeTitle || "") + "'>" + (r.purpose || "") + "</div>" +
        (r.warn ? "<div class='tl-warn'>" + icon("alert", { size: 12 }) + " " + r.warn + "</div>" : "") +
      "</div>" +
      "<div class='tl-ver'>" + verHtml(r.have, r.want, r.wantLabel) + "</div>" +
      "<div class='tl-size'>" + esc(r.size || "") + "</div>" +
      "<div class='tl-acts'>" + (r.action || "") +
        (menu.length ? moreHtml(menu) : "<span class='tl-more-gap'></span>") +
      "</div>" +
      (r.sub ? "<div class='tl-sub'>" + r.sub + "</div>" : "") +
    "</div>"
  );
}

function verHtml(have, want, wantLabel = 'tested') {
  if (!have && !want) return "<span class='muted'>—</span>";
  return (have ? "<span class='tl-have' title='" + esc(have) + "'>" + esc(have) + "</span>" : "<span class='muted'>not installed</span>") +
    (want ? "<span class='tl-want' title='" + (wantLabel === 'tested' ? 'The version this LanEx release was tested with' : 'The oldest version LibreLane supports') + "'>" + esc(wantLabel) + " " + esc(want) + "</span>" : "");
}

// A viewer or helper card: name and status, what it is for, what in LanEx
// uses it, the installed version, and an action only when one is needed.
// `c`: { id, name, status, state, what, use, ver, action, menu, sub, inst }.
export function cardHtml(c) {
  const st = c.status || "off";
  return (
    "<div class='tl-card is-" + st + "' id='" + esc(c.id) + "' data-status='" + st + "' data-inst='" + (c.inst ? "1" : "0") +
      "' data-name='" + esc(c.name) + "'>" +
      "<div class='tl-card-h'><span class='tl-card-name'>" + esc(c.name) + "</span>" + stateHtml(st, c.state) + "</div>" +
      "<p class='tl-card-what'>" + (c.what || "") + "</p>" +
      (c.use ? "<p class='tl-card-use'><span>Used by</span> " + esc(c.use) + "</p>" : "") +
      "<div class='tl-card-foot'><span class='tl-card-ver' title='" + esc(c.verTitle || c.ver || "") + "'>" + esc(c.ver || "") + "</span>" +
        "<span class='tl-card-acts'>" + (c.action || "") + moreHtml(c.menu) + "</span></div>" +
      (c.sub ? "<div class='tl-card-sub'>" + c.sub + "</div>" : "") +
    "</div>"
  );
}

function act(label, cls, attrs = "", { primary = false, title = "" } = {}) {
  return "<button class='btn btn-sm tl-act " + (primary ? "btn-primary " : "btn-ghost ") + cls + "' " + attrs +
    (title ? " title='" + esc(title) + "'" : "") + ">" + esc(label) + "</button>";
}
function menuItem(label, cls, attrs = "", { danger = false } = {}) {
  return "<button class='tl-menu-item" + (danger ? " is-danger" : "") + " " + cls + "' " + attrs + ">" + esc(label) + "</button>";
}

// "Verilator 5.020 2024-01-01 rev (Debian…)" -> "5.020"
export function shortVersion(v) {
  if (!v) return "";
  const m = String(v).match(/\d+\.\d+(?:\.\d+)?/);
  return m ? m[0] : String(v).slice(0, 24);
}
const shortHash = (h) => (h ? String(h).replace(/^sha256:/, "").slice(0, 8) : "");

function sizeStr(mb, { approx = false } = {}) {
  if (mb == null) return "";
  const s = mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : Math.round(mb) + " MB";
  return (approx ? "~" : "") + s;
}

function kvHtml(rows) {
  return "<dl class='tl-kv'>" + rows.filter(Boolean).map(([k, v, title]) =>
    "<div><dt>" + esc(k) + "</dt><dd" + (title ? " title='" + esc(title) + "'" : "") + ">" + v + "</dd></div>").join("") + "</dl>";
}

// ------------------------------------------------------------------ render
export async function renderTools(fresh) {
  const root = document.getElementById("tools-grid");
  if (!root) return;
  wireStatic();

  // Fetch/populate PDK root independently so a separate section cannot leave it blank
  loadPdkRoot();

  let info;
  try {
    // fresh=true (Check all / Check again) bypasses the server's 8s status
    // caches — a probe cached moments before the user fixed the engine reads
    // as broken.
    info = await api.tools(fresh);
    state.tools = info;
  } catch (ex) {
    // Only API probe failures display "Tool probe failed" and use host-only fallback
    renderDesktopViewers(null);
    const sum = document.getElementById("tools-summary");
    if (sum) sum.innerHTML = "<div class='tl-verdict is-fail'><div class='tl-verdict-main'><div class='an-eyebrow'>Tools and PDKs</div>" +
      "<h2 class='tl-verdict-title'>Tool probe failed</h2><p class='tl-verdict-lede'>" + esc(ex.message) + "</p></div></div>";
    root.innerHTML =
      "<div class='empty'><span class='ico'>" + icon('alert',{size:40}) + "</span><h3>Tool probe failed</h3><p>" + fmt.escape(ex.message) + "</p></div>";
    return;
  }

  try {
    await paint(info);
  } catch (ex) {
    console.error("Tools page render error:", ex);
  }
  revealItem();
}

let _desktopViewersSeq = 0;

// Container-launchable tools (matches controller/container_tools._CONTAINER_TOOLS).
const CONTAINER_LAUNCHABLE = new Set(["magic", "klayout", "openroad", "netgen"]);

// Desktop layout viewers (KLayout / Magic / OpenROAD GUI) as cards. KLayout
// and Magic ship in the LibreLane container image; the Layout tab launches
// whichever is installed on the run's GDS. GDS3D's card is painted with the
// helpers' install logic (renderRecommendedTools) into #viewer-gds3d.
//
// The status must report BOTH ways a viewer can be usable. `api.desktopTools()`
// only probes HOST binaries, so a container-only KLayout/Magic — the normal
// appliance setup, where the Layout tab happily launches them from the image —
// would read missing while plainly working. So fall back to the same
// `in_container` + image-pulled facts the tool list uses (`info` from
// `api.tools()`; null when that probe failed, host-only then).
const VIEWERS = [
  { key: "klayout", name: "KLayout", use: "Layout › Inspect and measure",
    what: "The standard 2D GDS viewer: every layer, rulers, and the DRC marker browser with a run's reports loaded." },
  { key: "magic", name: "Magic", use: "Layout › Edit transistors",
    what: "Edits the layout at transistor level with design rules checked as you draw. Opens with the PDK's <code>.magicrc</code> so layers draw correctly." },
  { key: "openroad", name: "OpenROAD GUI", use: "Layout › Timing and congestion",
    what: "The place-and-route database: timing paths drawn on the chip, placement and routing heat maps, the clock tree." },
];

export async function renderDesktopViewers(info) {
  const seq = ++_desktopViewersSeq;
  const root = document.getElementById("desktop-viewers");
  if (!root) return;
  let tools = [];
  try { tools = (await api.desktopTools()).tools || []; } catch (_e) {}
  if (seq !== _desktopViewersSeq) return;
  const byKey = Object.fromEntries(tools.map((t) => [t.key, t]));
  const cont = (info && info.container) || {};
  const contReady = !!(cont.ready && cont.image_present);
  const byToolKey = Object.fromEntries(((info && info.tools) || []).map((t) => [t.key, t]));
  const card = (v) => {
    const key = v.key;
    const host = byKey[key] && byKey[key].available;
    const t = byToolKey[key] || {};
    const inImage = !!(t.in_container && contReady);
    const size = t.approx_mb ? sizeStr(t.approx_mb, { approx: true }) : "";
    let status, stText, ver, action = "";
    if (host || t.installed) {
      status = "ready"; stText = "Installed";
      ver = shortVersion(t.version) || "installed on this system";
    } else if (inImage) {
      status = "image"; stText = "In the image";
      ver = "in container image";
    } else {
      // Without the image this is a consequence of the image problem above,
      // not a problem of its own: say what it waits for.
      const waits = !!(t.in_container && !contReady);
      status = waits ? "off" : "missing";
      stText = waits ? "Needs the image" : "Not available";
      ver = waits ? "comes with the LibreLane image" : "not found";
      if (t.install_recipe && !t.container_only)
        action = act(waits ? "Install locally" : "Install", "install-btn", "data-key='" + key + "'", { primary: !waits });
    }
    if (inImage && CONTAINER_LAUNCHABLE.has(key))
      action = act("Open", "ct-open", "data-key='" + key + "'", { title: "Open the version-matched " + v.name + " from the LibreLane image, with no run loaded" });
    return cardHtml({
      id: "tl-viewer-" + key, name: v.name, status, state: stText, inst: status !== "missing",
      what: v.what, use: v.use, ver: ver + (size && status !== "image" ? " · " + size : ""),
      verTitle: inImage ? "Included in the LibreLane container image. The Layout tab launches it directly." : (t.path || ""),
      action,
    });
  };
  root.innerHTML = VIEWERS.map(card).join("");
  root.querySelectorAll(".ct-open").forEach((b) => wireOpen(b));
}

// Helpers (iverilog, graphviz, gtkwave) and the GDS3D viewer. Native installs
// use the shared escalating installer — if a system package needs sudo, the
// user is prompted for a password in the launch terminal (handled globally by
// app.js's installer_info banner).
const HELPERS = {
  iverilog: { use: "RTL IDE › Simulate",
    what: "Event-driven Verilog simulator (iverilog + vvp) for your testbenches, with classic 4-state results and delays." },
  graphviz: { use: "Layout › Run files › Diagrams",
    what: "Draws Yosys's synthesis schematics from the .dot files it writes when SYNTH_SHOW is on." },
  gtkwave: { use: "RTL IDE › Open in GTKWave",
    what: "Desktop waveform viewer for your simulations. The IDE's built-in viewer works without it." },
};
let _desktop = {};

async function renderRecommendedTools(info) {
  if (typeof document === "undefined" || !document) return;
  const root = document.getElementById("recommended-tools");
  if (!root) return;
  const byKey = Object.fromEntries((info.tools || []).map((t) => [t.key, t]));
  let desktop = {};
  try {
    desktop = Object.fromEntries(((await api.desktopTools()).tools || []).map((t) => [t.key, t]));
  } catch (_e) {}
  if (typeof document === "undefined" || !document) return;
  _desktop = desktop;
  const gds3d = desktop.gds3d;

  const helperCard = (t) => {
    if (!t) return "";
    const busy = !!state.installJobs[t.key];
    const canInstall = Array.isArray(t.install_recipe) || !!t.install_recipe;
    const h = HELPERS[t.key] || {};
    const size = t.approx_mb ? sizeStr(t.approx_mb, { approx: true }) : "";
    let status, action = "";
    if (busy) { status = "busy"; action = act("Installing…", "", "disabled"); }
    else if (t.installed) status = "ready";
    else {
      status = "off";
      action = canInstall
        ? act("Install", "rec-install", "data-key='" + t.key + "'", { title: "Installs " + t.label + " with the system package manager. Progress is in the Logs panel." })
        : "<span class='tl-act-none' title='" + esc(t.install_recipe || "manual install") + "'>Manual install</span>";
    }
    return cardHtml({
      id: "tl-helper-" + t.key, name: t.label, status, inst: t.installed,
      state: busy ? "Installing" : t.installed ? "Installed" : "Not installed",
      what: esc(h.what || t.what || ""), use: h.use || "",
      ver: (t.installed ? shortVersion(t.version) || "installed" : "optional") + (size ? " · " + size : ""),
      verTitle: t.installed ? (t.version || "") + (t.path ? " at " + t.path : "") : "",
      action,
      menu: t.installed ? [menuItem("Remove " + t.label, "rec-uninstall", "data-key='" + t.key + "' data-label='" + esc(t.label) + "'", { danger: true })] : [],
    });
  };

  root.innerHTML = helperCard(byKey.iverilog) + helperCard(byKey.graphviz) + helperCard(byKey.gtkwave);

  const g = document.getElementById("viewer-gds3d");
  if (g) {
    const have = !!(gds3d && gds3d.available);
    g.innerHTML = cardHtml({
      id: "tl-viewer-gds3d", name: "GDS3D", inst: have,
      status: have ? "ready" : "off", state: have ? "Installed" : "Not installed",
      what: "Fly through the real layer stack in 3D: metals, vias and devices at their heights. Built from source once (a few minutes).",
      use: "Layout › See it in 3D",
      ver: have ? "installed" : "optional",
      action: have ? "" : act("Install", "", "id='btn-install-gds3d'", { title: "Builds GDS3D from source. Progress is in the Logs panel." }),
      menu: have ? [menuItem("Remove GDS3D", "", "id='btn-remove-gds3d'", { danger: true })] : [],
      sub: have ? "" :
        "<details class='tl-manual'><summary>Manual build (if the one-click build can't run)</summary>" +
        "<p class='hint'>GDS3D has no pre-packaged distribution; the OpenGL binary is compiled once locally. <strong>Install handles this automatically</strong>. These commands are for systems without a standard package manager or root access.</p>" +
        "<pre class='code'>sudo apt-get install -y git build-essential libx11-dev libxmu-dev libxi-dev libgl1-mesa-dev libglu1-mesa-dev freeglut3-dev\n" +
        "git clone https://github.com/trilomix/GDS3D\n" +
        "cd GDS3D/linux &amp;&amp; make\n" +
        "sudo cp GDS3D /usr/local/bin/gds3d</pre>" +
        "<p class='hint'>Fedora/RHEL: <code>sudo dnf install -y libX11-devel mesa-libGL-devel mesa-libGLU-devel freeglut-devel gcc-c++ make git</code>. Arch: <code>sudo pacman -S --needed libx11 mesa glu freeglut base-devel git</code>. macOS: the automated install uses the prebuilt <code>mac/GDS3D.app</code> (Intel binary; Apple Silicon needs Rosetta 2). Windows: download the prebuilt binary from the GDS3D site, then reopen this tab.</p>" +
        "</details>",
    });
  }

  root.querySelectorAll(".rec-install").forEach((b) =>
    b.addEventListener("click", async () => {
      state.installJobs[b.dataset.key] = true;
      b.disabled = true; b.textContent = "Installing…";
      await installByKey(b.dataset.key);
      renderTools();
    }));
  root.querySelectorAll(".rec-uninstall").forEach((b) =>
    b.addEventListener("click", async () => {
      const key = b.dataset.key;
      const label = b.dataset.label || key;
      closeMenus();
      if (!(await confirmDialog({ title: "Remove " + label, danger: true, confirmText: "Remove",
        body: "Removes the " + label + " package from the LanEx Linux environment (your password may be asked in the terminal). " +
          "Your projects and run results are kept. Install it again from this card any time." }))) return;
      try {
        const r = await api.uninstallTool(key);
        toast.show(r.ok ? label + " removed" : label + " remove failed", r.ok ? "info" : "error");
      } catch (ex) { toast.show(label + " remove error: " + (ex.message || ex), "error"); }
      renderTools();
    }));
  document.getElementById("btn-install-gds3d")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true; btn.textContent = "Building…";
    try {
      const r = await api.installTool("gds3d");
      if (r && r.in_progress) toast.show("GDS3D compilation already in progress. Check the Logs panel.", "info");
      else if (r && r.ok === false) toast.show(r.guidance || r.error || "Build could not start. Follow the manual build steps instead.", "warn");
      else toast.show("GDS3D build started. Progress is in the Logs panel.", "success");
    } catch (ex) {
      toast.show("Could not start GDS3D build: " + (ex.message || ex), "error");
    }
    btn.disabled = false; btn.textContent = "Install";
  });
  document.getElementById("btn-remove-gds3d")?.addEventListener("click", async () => {
    closeMenus();
    if (!(await confirmDialog({ title: "Remove GDS3D", danger: true, confirmText: "Remove",
      body: "Removes the GDS3D binary and its build folder. Your projects and run results are kept. You can rebuild it any time from this card." }))) return;
    try {
      const r = await api.uninstallTool("gds3d");
      if (r && r.ok && r.already_absent) {
        toast.show("GDS3D was already removed", "info");
      } else if (r && r.ok) {
        toast.show("GDS3D removed", "info");
        renderLogs.append({ payload: { message: "✓ GDS3D removed (" + (r.removed || []).join(", ") + ")" } });
      } else {
        toast.show("GDS3D remove failed: " + ((r && r.reason) || "unknown"), "error");
        renderLogs.append({ payload: { message: "✗ GDS3D remove: " + ((r && r.reason) || "unknown"), level: "ERROR" } });
      }
    } catch (ex) {
      toast.show("GDS3D remove error: " + (ex.message || ex), "error");
    }
    // Re-probe the whole tab (fresh=true bypasses the server status caches) —
    // re-rendering from the stale `info` this closure captured is how a removed
    // GDS3D kept showing "installed + Remove" and no way back to Install.
    renderTools(true);
  });
}

// ------------------------------------------------------------------ page chrome
// Header buttons, PDK_ROOT edit and save, menus: wired once.
let _staticWired = false;
function wireStatic() {
  if (_staticWired || typeof document === "undefined" || !document.querySelector) return;
  const sec = document.getElementById("sec-tools");
  if (!sec || !sec.querySelector) return;
  _staticWired = true;
  document.getElementById("tl-recheck")?.addEventListener("click", () => {
    showSkeletonSummary();
    renderTools(true);
  });
  document.getElementById("tl-copy-diag")?.addEventListener("click", copyDiagnostics);
  document.getElementById("tl-pdkroot-edit")?.addEventListener("click", () => {
    const row = document.getElementById("tl-pdkroot-form");
    if (!row) return;
    row.hidden = !row.hidden;
    if (!row.hidden) document.getElementById("pdk-root-input")?.focus();
  });
  document.getElementById("btn-save-pdk-root")?.addEventListener("click", async () => {
    const val = document.getElementById("pdk-root-input").value.trim();
    if (!val) return;
    try {
      const res = await api.setPdkRoot(val);
      if (res.ok) {
        toast.show("PDK folder set to " + res.pdk_root, "success");
        const row = document.getElementById("tl-pdkroot-form");
        if (row) row.hidden = true;
        renderTools();
      } else {
        toast.show("Could not change the PDK folder", "error");
      }
    } catch (ex) {
      toast.show("Error: " + ex.message, "error");
    }
  });
  // One open "More" menu at a time; a click elsewhere closes it.
  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest(".tl-more")) closeMenus();
  });
  sec.addEventListener("toggle", (e) => {
    const d = e.target;
    if (d.classList && d.classList.contains("tl-more") && d.open)
      sec.querySelectorAll(".tl-more[open]").forEach((o) => { if (o !== d) o.open = false; });
  }, true);
}

function closeMenus() {
  if (typeof document === "undefined" || !document.querySelectorAll) return;
  document.querySelectorAll("#sec-tools .tl-more[open]").forEach((d) => { d.open = false; });
}

function showSkeletonSummary() {
  const sum = document.getElementById("tools-summary");
  if (sum) sum.innerHTML = loadingVerdictHtml();
}
function loadingVerdictHtml() {
  return "<div class='tl-verdict is-loading'><div class='tl-verdict-main'><div class='an-eyebrow'>Tools and PDKs</div>" +
    "<h2 class='tl-verdict-title'><span class='spinner-sm'></span> Checking components…</h2>" +
    "<p class='tl-verdict-lede'>Probing the container engine, the LibreLane image, PDKs and helpers. This takes a few seconds.</p></div></div>";
}

// ------------------------------------------------------------------ attention
// The fixes for an engine that is installed but unusable, or missing. Shared by
// the remedy card under the engine and the verdict band's Fix button. The
// right remedy is platform-shaped: on macOS the daemon only exists while
// Docker Desktop (or the podman machine VM) is RUNNING — a one-click Start,
// not the Linux systemctl/usermod blob.
export function engineFixes(c) {
  c = c || {};
  const d = c.docker || {}, p = c.podman || {};
  const out = [];
  if (c.ready) return out;
  if (c.available) {
    const mac = c.platform === "darwin";
    if (mac) {
      if (d.present || d.app_present) out.push({ id: "btn-start-docker", label: "Start Docker Desktop", primary: true });
      if (p.present) out.push({ id: "btn-start-podman", label: "Start podman machine", primary: true });
    } else {
      if (d.present && d.group_fixable) out.push({ id: "btn-enable-docker", label: "Enable Docker for my user (no logout)", primary: true });
      if (d.present && !d.usable) out.push({ id: "btn-start-docker", label: "Start Docker daemon", primary: true });
    }
    if (!p.present) out.push({ id: "btn-install-podman", label: "Install & use Podman" });
  } else {
    out.push({ id: "btn-install-docker", label: "Install Docker", primary: true });
    out.push({ id: "btn-install-podman", label: "Install Podman" });
  }
  return out;
}

function engineName(c) {
  const d = c.docker || {}, p = c.podman || {};
  return c.engine === "podman" ? "Podman" : c.engine === "docker" ? "Docker" : (d.present ? "Docker" : p.present ? "Podman" : "Docker or Podman");
}

const RECOMMENDED_KEYS = new Set(["iverilog", "graphviz", "gtkwave"]);

// Everything that needs the user, from the /api/tools facts alone.
// Each item: { key, tone: "fail"|"warn"|"busy"|"info", title, detail,
// fix?: { label, id, sel? } (the button on the page it clicks), show (element id) }.
export function attentionItems(info, { runMode = "container", installJobs = {}, pulling = false, desktop = {} } = {}) {
  const i = info || {};
  const c = i.container || {};
  const pdk = i.pdk || {};
  const cat = i.pdk_catalog || {};
  const tools = i.tools || [];
  const local = runMode === "local";
  const engTone = local ? "warn" : "fail";
  const onlyContainer = local ? " Only the Container engine needs it; you have Local tools selected." : "";
  const name = engineName(c);
  const items = [];

  if (!c.ready) {
    if (c.available) {
      const f = engineFixes(c)[0];
      items.push({ key: "engine", tone: engTone, show: "tl-engine",
        title: name + " is installed but not running",
        detail: (c.daemon_msg ? c.daemon_msg : "The engine is not reachable.") + onlyContainer,
        fix: f ? { label: f.label, id: f.id } : null });
    } else {
      items.push({ key: "engine", tone: engTone, show: "tl-engine",
        title: "No container engine",
        detail: "Docker or Podman runs the LibreLane image, which holds every EDA tool the flow uses." + onlyContainer,
        fix: { label: "Install Docker", id: "btn-install-docker" } });
    }
  } else if (c.version_ok === false && c.min_version) {
    items.push({ key: "engine-version", tone: "warn", show: "tl-engine",
      title: name + " " + shortVersion(c.version) + " is older than LibreLane's recommended " + c.min_version,
      detail: "Update it with your system's package manager." });
  }

  if (pulling) {
    items.push({ key: "image", tone: "busy", show: "tl-image", title: "Downloading the LibreLane image",
      detail: "The progress is under Flow engine. Layers already fetched stay cached if it stops." });
  } else if (!c.image_present) {
    items.push({ key: "image", tone: engTone, show: "tl-image",
      title: "The LibreLane image is not downloaded",
      detail: (c.ready
        ? "One download" + (c.image_approx_mb ? " (" + sizeStr(c.image_approx_mb, { approx: true }) + ")" : "") + " gives you every EDA tool, version-matched."
        : "Download it once the container engine runs.") + onlyContainer,
      fix: c.ready ? { label: "Download", id: "btn-pull-image" } : null });
  } else if (c.image_custom) {
    items.push({ key: "image-custom", tone: "warn", show: "tl-image",
      title: "A custom LibreLane image is in use",
      detail: "Not the image this LanEx release was tested with" + (c.image_tested_digest ? " (" + shortHash(c.image_tested_digest) + ")" : "") + ". Results may differ." });
  }

  if (!pdk.ciel_installed) {
    items.push({ key: "ciel", tone: "fail", show: "tl-pdk-ciel",
      title: "ciel, the PDK manager, is missing",
      detail: "LanEx uses it to download each PDK at the version LibreLane pins.",
      fix: { label: "Install ciel", id: "install-ciel-btn" } });
  }
  const installed = pdk.installed_pdks || [];
  const busyPdks = Object.keys(cat).filter((k) => installJobs["pdk:" + k]);
  for (const k of busyPdks)
    items.push({ key: "pdk-busy-" + k, tone: "busy", show: "tl-pdk-" + k, title: "Installing " + k,
      detail: "The download runs in the background; the Logs panel shows its progress." });
  if (!installed.length && !busyPdks.length) {
    const def = Object.entries(cat).find(([, p]) => (p.default_variant || p.recommended) && !p.note);
    items.push({ key: "pdk-none", tone: "fail", show: def ? "tl-pdk-" + def[0] : "tools-pdk",
      title: "No PDK installed",
      detail: "Every design needs one." + (def ? " " + def[0] + " is the usual place to start." : ""),
      fix: def ? { label: "Install " + def[0], id: "tl-pdk-" + def[0], sel: ".pdk-install-btn" } : null });
  }
  const versions = pdk.versions || {};
  for (const k of installed) {
    const v = versions[k] || {};
    if (v.installed && v.pinned && v.installed !== v.pinned && !installJobs["pdk:" + k])
      items.push({ key: "pdk-" + k, tone: "warn", show: "tl-pdk-" + k,
        title: k + " is not the version LibreLane " + (c.librelane_version || "") + " pins",
        detail: "Installed " + shortHash(v.installed) + ", pinned " + shortHash(v.pinned) + ". Container runs download the pinned one; Update installs it now.",
        fix: { label: "Update " + k, id: "tl-pdk-" + k, sel: ".pdk-install-btn" } });
  }

  if (local) {
    const missing = tools.filter((t) => !RECOMMENDED_KEYS.has(t.key) && !t.installed && !installJobs[t.key]);
    // One item per tool: each has its own fix (or none: no system package).
    for (const t of missing) {
      const canInstall = !t.container_only && (Array.isArray(t.install_recipe) || !!t.install_recipe);
      items.push({ key: "local-" + t.key, tone: "fail", show: "tl-local-" + t.key,
        title: t.label + (t.windows_only ? " is a Windows build the Linux flow can't use" : " is not installed for the Local tools engine"),
        detail: t.container_only
          ? "It has no system package: install it with Nix or conda (litex-hub), or switch the run engine to Container, which has it."
          : "Install it here, or switch the run engine to Container, which has it.",
        fix: canInstall ? { label: "Install " + t.label, id: "tl-local-" + t.key, sel: ".install-btn" } : null });
    }
  }

  for (const t of tools) {
    if (!RECOMMENDED_KEYS.has(t.key)) continue;
    if (installJobs[t.key]) items.push({ key: "helper-busy-" + t.key, tone: "busy", show: "tl-helper-" + t.key, title: "Installing " + t.label, detail: "Progress is in the Logs panel." });
    else if (!t.installed)
      items.push({ key: "helper-" + t.key, tone: "info", show: "tl-helper-" + t.key,
        title: t.label + " is not installed", detail: "Optional. Used by " + ((HELPERS[t.key] || {}).use || "LanEx") + ".",
        fix: (Array.isArray(t.install_recipe) || t.install_recipe) ? { label: "Install", id: "tl-helper-" + t.key, sel: ".rec-install" } : null });
  }
  if (desktop && desktop.gds3d && !desktop.gds3d.available)
    items.push({ key: "gds3d", tone: "info", show: "tl-viewer-gds3d", title: "GDS3D is not installed",
      detail: "Optional. Used by Layout › See it in 3D.", fix: { label: "Install", id: "btn-install-gds3d" } });
  return items;
}

// Headline for the verdict band from the attention items.
export function readiness(items) {
  const n = (t) => items.filter((x) => x.tone === t).length;
  const fail = n("fail"), warn = n("warn"), busy = n("busy");
  if (fail) return { tone: "fail", title: fail === 1 ? "1 problem to fix" : fail + " problems to fix",
    lede: "The flow can't run until " + (fail === 1 ? "it is" : "these are") + " fixed. Each one has its fix next to it." +
      (warn ? " " + (warn === 1 ? "One more thing" : warn + " more things") + " to check below." : "") };
  if (busy) return { tone: "busy", title: "Almost ready",
    lede: busy === 1 ? "One install is still running. This page updates when it finishes." : busy + " installs are still running. This page updates when they finish." };
  if (warn) return { tone: "warn", title: "Ready to run, " + (warn === 1 ? "1 thing to check" : warn + " things to check"),
    lede: "The flow can run. " + (warn === 1 ? "This differs" : "These differ") + " from what this LanEx release was tested with." };
  return { tone: "pass", title: "Ready to run",
    lede: "Everything the flow needs is installed, on the versions this LanEx release was tested with. Nothing updates on its own." };
}

// Verdict band: headline, the facts behind it, a square per component, and
// every problem with its fix. Counts the rendered items, so it says exactly
// what the page below shows.
function paintSummary(info) {
  const sum = document.getElementById("tools-summary");
  const list = document.getElementById("tl-list");
  if (!sum || !list || !list.querySelectorAll) return;
  const items = attentionItems(info, {
    runMode: state.runMode, installJobs: state.installJobs || {},
    pulling: !!(_pull.active || (info.container && info.container.pulling)), desktop: _desktop,
  });
  const head = readiness(items);
  const c = info.container || {};
  const pdk = info.pdk || {};

  // One square per component on the page (the local toolchain only counts
  // with the Local tools engine; with Container the image has it).
  const comps = Array.from(list.querySelectorAll("[data-status]:not(.tl-skel)"))
    .filter((el) => el.id && (state.runMode === "local" || !el.closest("#local-tools-card")));
  const kind = (st) => FAIL.has(st) ? "fail" : WARN.has(st) ? "warn" : st === "busy" ? "busy" : st === "off" ? "off" : "pass";
  const counts = { pass: 0, fail: 0, warn: 0, busy: 0, off: 0 };
  comps.forEach((el) => { counts[kind(el.dataset.status)]++; });
  const squares = comps.map((el) => {
    const nm = el.dataset.name || el.id;
    return "<button class='tl-sq is-" + kind(el.dataset.status) + "' data-show='" + esc(el.id) + "' title='" + esc(nm + ": " + (STATE_TEXT[el.dataset.status] || el.dataset.status)) + "' aria-label='" + esc(nm) + "'></button>";
  }).join("");
  const countBits = [
    counts.pass && "<span><b>" + counts.pass + "</b> ready</span>",
    counts.fail && "<span class='is-fail'><b>" + counts.fail + "</b> " + (counts.fail === 1 ? "problem" : "problems") + "</span>",
    counts.warn && "<span class='is-warn'><b>" + counts.warn + "</b> to check</span>",
    counts.busy && "<span><b>" + counts.busy + "</b> working</span>",
    counts.off && "<span class='is-off'><b>" + counts.off + "</b> not installed</span>",
  ].filter(Boolean).join("");

  const nPdk = (pdk.installed_pdks || []).length;
  const helpersIn = ["iverilog", "graphviz", "gtkwave"].filter((k) => ((info.tools || []).find((t) => t.key === k) || {}).installed).length;
  const facts = [
    c.ready ? "<b>" + esc(engineName(c)) + " " + esc(shortVersion(c.version)) + "</b>" : esc(engineName(c)) + (c.available ? " not running" : " not installed"),
    c.image_present ? "LibreLane <b>" + esc(c.librelane_version || "") + "</b> image" : "no LibreLane image",
    "<b>" + nPdk + "</b> PDK " + (nPdk === 1 ? "variant" : "variants"),
    "<b>" + helpersIn + "</b> of 3 helpers",
    "run engine <b>" + (state.runMode === "local" ? "Local tools" : "Container") + "</b>",
  ];

  const main = items.filter((x) => x.tone !== "info");
  const opt = items.filter((x) => x.tone === "info");
  const itemHtml = (x, idx) =>
    "<div class='tl-attn-item is-" + x.tone + "'>" +
      "<span class='tl-attn-ic'>" + (x.tone === "busy" ? "<span class='spinner-sm'></span>" : x.tone === "info" ? "<i></i>" : icon("alert", { size: 15 })) + "</span>" +
      "<div class='tl-attn-text'><strong>" + esc(x.title) + "</strong><span>" + esc(x.detail || "") + "</span></div>" +
      "<div class='tl-attn-acts'>" +
        (x.fix ? "<button class='btn btn-sm " + (x.tone === "fail" ? "btn-primary" : "btn-ghost") + "' data-fix='" + idx + "'>" + esc(x.fix.label) + "</button>" : "") +
        (x.show && x.show !== (x.fix && x.fix.id) ? "<button class='btn btn-sm btn-ghost tl-attn-show' data-show='" + esc(x.show) + "'>Show</button>" : "") +
      "</div></div>";
  const all = main.concat(opt);
  sum.innerHTML =
    "<div class='tl-verdict is-" + head.tone + "'>" +
      "<div class='tl-verdict-main'>" +
        "<div class='an-eyebrow'>Tools and PDKs</div>" +
        "<h2 class='tl-verdict-title'>" + esc(head.title) + "</h2>" +
        "<p class='tl-verdict-lede'>" + esc(head.lede) + "</p>" +
        "<div class='tl-verdict-meta'>" + facts.map((f) => "<span>" + f + "</span>").join("<span class='sep'>/</span>") + "</div>" +
      "</div>" +
      "<div class='tl-verdict-side'>" +
        "<div class='tl-counts'>" + countBits + "</div>" +
        "<div class='tl-squares' role='group' aria-label='Every component, in page order'>" + squares + "</div>" +
      "</div>" +
      (main.length ? "<div class='tl-attn'>" + main.map((x) => itemHtml(x, all.indexOf(x))).join("") + "</div>" : "") +
      (opt.length ? "<div class='tl-attn tl-attn-opt'><div class='tl-attn-label'>Optional, not installed</div>" + opt.map((x) => itemHtml(x, all.indexOf(x))).join("") + "</div>" : "") +
    "</div>";

  sum.querySelectorAll("[data-show]").forEach((b) => b.addEventListener("click", () => revealRow(b.dataset.show)));
  sum.querySelectorAll("[data-fix]").forEach((b) => b.addEventListener("click", () => {
    const x = all[+b.dataset.fix];
    if (!x || !x.fix) return;
    const host = document.getElementById(x.fix.id);
    if (x.fix.open) { revealRow(x.fix.id); return; }
    const target = host && x.fix.sel ? host.querySelector(x.fix.sel) : host;
    if (target && !target.disabled) { revealRow(x.show); target.click(); }
    else revealRow(x.show);
  }));
}

function revealRow(id) {
  const row = id && document.getElementById(id);
  if (!row) return false;
  const det = row.tagName === "DETAILS" ? row : row.closest("details.tl-group");
  if (det) det.open = true;
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  row.classList.add("is-flash");
  setTimeout(() => row.classList.remove("is-flash"), 1600);
  return true;
}

// go("tools", {item}) — item is a component key ("docker", "image", "sky130A",
// "klayout", "iverilog", "gds3d", "yosys"…) or an element id.
let _pendingItem = null;
export function focusTools(params = {}) {
  _pendingItem = params.item || null;
  return renderTools(params.fresh).then(() => revealItem());
}
function revealItem() {
  if (!_pendingItem) return;
  const k = String(_pendingItem);
  const ids = [k, "tl-" + k, "tl-pdk-" + k, "tl-viewer-" + k, "tl-helper-" + k, "tl-local-" + k,
    k === "docker" || k === "podman" || k === "engine" ? "tl-engine" : "", k === "image" || k === "librelane-image" ? "tl-image" : ""];
  for (const id of ids) if (id && revealRow(id)) { _pendingItem = null; return; }
}

// "Copy diagnostics": one plain-text block for a bug report.
export function diagnosticsText(info, { pdkRoot = "", runMode = "", ua = "" } = {}) {
  const i = info || {};
  const c = i.container || {};
  const p = i.pdk || {};
  const h = i.host || {};
  const L = [];
  L.push("LanEx tool diagnostics");
  L.push("Platform: " + (c.platform || i.platform || "?") + (h.os ? " | " + h.os : "") + (h.kernel ? " | kernel " + h.kernel : "") + (h.wsl ? " | WSL " + h.wsl : ""));
  if (h.python) L.push("Python: " + h.python);
  if (runMode) L.push("Run engine: " + runMode);
  L.push("Container engine: " + (c.engine || "none") + " | ready " + !!c.ready + (c.version ? " | " + c.version : "") + (c.min_version ? " | min " + c.min_version : ""));
  if (c.daemon_msg) L.push("Engine message: " + c.daemon_msg);
  L.push("Image: " + (c.image || "?") + " | present " + !!c.image_present + (c.image_size_mb ? " | " + sizeStr(c.image_size_mb) : ""));
  if (c.image_tested_digest) L.push("Tested image digest: " + c.image_tested_digest + (c.image_custom ? " (CUSTOM image in use)" : ""));
  if (c.librelane_version) L.push("LibreLane: " + c.librelane_version);
  L.push("PDK_ROOT: " + (pdkRoot || "?"));
  L.push("ciel: " + (p.ciel_installed ? "installed" : "missing"));
  const vers = p.versions || {};
  for (const k of p.installed_pdks || []) {
    const v = vers[k] || {};
    L.push("PDK " + k + ": " + (v.installed || "version unknown") + (v.pinned ? " | pinned " + v.pinned : "") +
      (p.installed_sizes_mb && p.installed_sizes_mb[k] != null ? " | " + sizeStr(p.installed_sizes_mb[k]) : ""));
  }
  for (const t of i.tools || []) {
    L.push("Tool " + t.key + ": " + (t.installed ? (t.version || "installed") + " @ " + (t.path || "?") : "not installed") +
      (t.in_container ? " | in image" : "") + (t.windows_only ? " | WINDOWS BUILD ON PATH" : ""));
  }
  if (ua) L.push("Browser: " + ua);
  return L.join("\n");
}

async function copyDiagnostics() {
  const text = diagnosticsText(state.tools, {
    pdkRoot: _pdkRoot || document.getElementById("pdk-root-input")?.value || "",
    runMode: state.runMode || "", ua: navigator.userAgent,
  });
  try {
    await navigator.clipboard.writeText(text);
    toast.show("Diagnostics copied. Paste them into your bug report.", "success");
  } catch (_e) {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast.show("Diagnostics copied.", "success"); }
    catch (_e2) { toast.show("Could not copy. Diagnostics are in the Logs panel.", "warn"); renderLogs.append({ payload: { message: text } }); }
    ta.remove();
  }
}

// ------------------------------------------------------------------ image pull
// Live image-pull state. The pull runs in a background thread on the server and
// streams `docker pull` stdout over SSE. Over a pipe, docker prints ONE line per
// layer state change (not byte-by-byte), so a single multi-GB layer downloads
// silently for minutes. We therefore (a) keep a ticking elapsed heartbeat,
// (b) count layers from the discrete status lines for real progress, and
// (c) explicitly say "still downloading" during quiet stretches so it never
// looks hung.
const _pull = { active: false, start: 0, timer: null, last: "", lastAt: 0, total: 0, downloaded: 0, pulled: 0, done: false, blobs: null };

function _pullElapsed() {
  return Math.max(0, Math.round((Date.now() - _pull.start) / 1000));
}

function _pullLayerLabel() {
  if (_pull.done) return "all layers complete";
  if (!_pull.total) return "resolving layers…";
  return _pull.pulled + " / " + _pull.total + " layers extracted · " + _pull.downloaded + " downloaded";
}

function pullProgressHtml() {
  return (
    "<div id='runtime-pull' class='tl-pull'>" +
    "<div class='tl-pull-head'>" +
    "<span class='spinner-sm'></span>" +
    "<strong>Downloading the LibreLane image</strong>" +
    "<span class='muted' id='runtime-pull-elapsed'>" + _pullElapsed() + "s</span>" +
    "<span class='muted' id='runtime-pull-layers' style='margin-left:auto'>" + _pullLayerLabel() + "</span>" +
    "<button class='btn btn-sm btn-ghost' id='runtime-pull-cancel' " +
    "title='Stops the download. Already-fetched layers stay cached, so a retry resumes.'>Cancel</button>" +
    "</div>" +
    "<div id='runtime-pull-note' class='hint'></div>" +
    "<pre class='code' id='runtime-pull-line'>" +
    fmt.escape(_pull.last || "starting…") +
    "</pre>" +
    "<p class='hint'>About 3 GB, downloaded once. Large layers arrive one at a time, so the line above can sit still for a while; the timer shows it is still going.</p>" +
    "</div>"
  );
}

function _pullTicker() {
  clearInterval(_pull.timer);
  _pull.timer = setInterval(() => {
    const el = document.getElementById("runtime-pull-elapsed");
    if (!el) { clearInterval(_pull.timer); return; }
    el.textContent = _pullElapsed() + "s";
    // Explain quiet stretches so a silent big-layer download never looks hung.
    const note = document.getElementById("runtime-pull-note");
    if (note) {
      const idle = Math.round((Date.now() - _pull.lastAt) / 1000);
      note.textContent = idle >= 6 && !_pull.done
        ? "Still downloading: a large layer has been streaming for " + idle + "s without a progress line. This is normal."
        : "";
    }
  }, 1000);
}

export function startPullUI() {
  _pull.active = true;
  _pull.start = Date.now();
  _pull.lastAt = Date.now();
  _pull.last = "contacting registry…";
  _pull.total = _pull.downloaded = _pull.pulled = 0;
  _pull.done = false;
  _pull.blobs = null;
  paintRuntimeCard(state.tools && state.tools.container);
  try { if (state.tools) paintSummary(state.tools); } catch (_e) {}
  _pullTicker();
}

// A page reload mustn't lose a running pull: the server keeps downloading, so
// re-attach the progress UI to the live SSE stream (elapsed restarts from the
// re-attach; the layer counters rebuild from subsequent lines).
function resumePullUI() {
  _pull.active = true;
  _pull.start = Date.now();
  _pull.lastAt = Date.now();
  _pull.last = "Re-attached to running pull, waiting for status updates…";
  _pull.done = false;
  _pullTicker();
}

export function updatePullProgress(line) {
  if (!line) return;
  _pull.last = line;
  _pull.lastAt = Date.now();
  // Count layers from docker's discrete status lines (works over a pipe).
  if (/Pulling fs layer/.test(line)) _pull.total++;
  else if (/Download complete/.test(line)) _pull.downloaded++;
  else if (/Pull complete/.test(line)) _pull.pulled++;
  else if (/Status: (Downloaded|Image is up to date)/.test(line)) _pull.done = true;
  else {
    // Podman phrasing: "Copying blob <id> …" per layer, then
    // "Writing manifest to image destination" when everything landed.
    const blob = line.match(/Copying blob (\S+)/);
    if (blob) {
      _pull.blobs = _pull.blobs || new Set();
      _pull.blobs.add(blob[1]);
      _pull.total = _pull.blobs.size;
      if (/\bdone\b/i.test(line)) _pull.downloaded++;
    } else if (/Writing manifest to image destination/.test(line)) {
      _pull.done = true;
    }
  }
  const el = document.getElementById("runtime-pull-line");
  if (el) el.textContent = line;
  const lay = document.getElementById("runtime-pull-layers");
  if (lay) lay.textContent = _pullLayerLabel();
}

export function finishPull(rc) {
  const wasCancelled = _pull.cancelledByUser;
  _pull.cancelledByUser = false;
  _pull.active = false;
  clearInterval(_pull.timer);
  if (wasCancelled) { renderTools(); return; }   // the cancel click already toasted
  if (rc === 0) toast.show("Image download complete. Container mode is ready.", "success");
  else toast.show("Image download failed (exit " + rc + "). The Logs panel has the details; Download again resumes.", "error");
  renderTools();   // re-probe → image_present / daemon state refresh
}

// ------------------------------------------------------------------ flow engine
// Two tiles (engine, image) plus, under them, whatever the user must act on:
// the remedy card when the engine isn't usable, the live pull while
// downloading. Both engines keep one-click Install / Remove (in the menu), so a
// user can e.g. drop Docker and switch to Podman at will.
function engineTilesHtml(c, info) {
  const d = c.docker || {}, p = c.podman || {};
  const verBad = c.version && c.min_version && c.version_ok === false;
  const engName = engineName(c);
  let status, stText, action = "";
  const menu = [menuItem("Check again", "", "id='btn-runtime-recheck'")];
  if (c.ready) {
    status = verBad ? "update" : "ready";
    stText = verBad ? "Running, older than recommended" : c.sg_wrap ? "Running (via the docker group)" : "Running";
  } else if (c.available) {
    status = "broken"; stText = "Installed, not running";
    action = act("Repair", "tl-repair", "", { primary: true, title: "Runs the first fix listed below" });
  } else {
    status = "missing"; stText = "Not installed";
    action = act("Install Docker", "engine-install", "data-engine='docker'", { primary: true, title: "Installs Docker with the system package manager, then downloads the image" });
  }
  const engItem = (key, present, label) => present
    ? menuItem("Remove " + label, "engine-remove", "data-engine='" + key + "'", { danger: true })
    : menuItem("Install " + label, "engine-install", "data-engine='" + key + "'");
  if (c.available || c.ready) { menu.push(engItem("docker", d.present, "Docker")); menu.push(engItem("podman", p.present, "Podman")); }
  else menu.push(engItem("podman", p.present, "Podman instead"));
  const host = (info && info.host) || {};
  const plat = { wsl: "WSL", linux: "Linux", darwin: "macOS" }[c.platform] || c.platform || "";
  const runsIn = [plat, host.os].filter(Boolean).join(" · ");
  const engState = (x, key, label) => label + " " + (!x.present ? "not installed"
    : (c.ready && c.engine === key) ? "in use" : x.usable ? "installed" : "installed, not usable");
  const engine =
    "<div class='tl-tile is-" + status + "' id='tl-engine' data-status='" + status + "' data-name='" + esc(engName) + "' data-inst='" + (c.available || c.ready ? "1" : "0") + "'>" +
      "<div class='tl-tile-top'><span class='tl-eyebrow'>Container engine</span>" + stateHtml(status, stText) + moreHtml(menu) + "</div>" +
      "<div class='tl-tile-big'>" + esc(engName) + (c.version ? " <span class='tl-tile-ver' title='" + esc(c.version) + "'>" + esc(shortVersion(c.version)) + "</span>" : "") + "</div>" +
      kvHtml([
        c.min_version && ["LibreLane needs", esc(c.min_version) + " or newer" + (c.version_ok === true ? " <span class='tl-ok'>" + icon("check", { size: 12, stroke: 2 }) + "</span>" : c.version_ok === false ? " <span class='tl-bad'>older</span>" : "")],
        ["Engines", esc(engState(d, "docker", "Docker")) + "<span class='sep'>·</span>" + esc(engState(p, "podman", "Podman"))],
        runsIn && ["Runs in", esc(runsIn)],
      ]) +
      "<div class='tl-tile-act'>" + action + "</div>" +
    "</div>";

  // The image tile.
  const imgTag = (String(c.image || "").split("@")[0].split(":").pop()) || "";
  const dig = (String(c.image || "").split("@")[1]) || "";
  let iStatus, iText, iAction = "";
  if (_pull.active || c.pulling) {
    iStatus = "busy"; iText = "Downloading";
  } else if (c.image_present) {
    iStatus = c.image_custom ? "custom" : "ready";
    iText = c.image_custom ? "Custom image" : "Downloaded";
  } else {
    iStatus = "missing"; iText = "Not downloaded";
    iAction = c.ready
      ? act("Download", "", "id='btn-pull-image'", { primary: true, title: "One download gives you every EDA tool, version-matched" })
      : act("Download", "", "disabled title='Needs a working container engine first'");
  }
  const inImage = ((info && info.tools) || []).filter((t) => t.in_container).map((t) => t.label);
  let digest = "";
  if (dig) {
    digest = "<span class='tl-mono'>" + esc(shortHash(dig)) + "</span>";
    if (c.image_custom === false) digest += " <span class='tl-ok'>" + icon("check", { size: 12, stroke: 2 }) + "</span> the one LanEx was tested with";
    else if (c.image_custom && c.image_tested_digest) digest += " <span class='tl-bad'>tested: " + esc(shortHash(c.image_tested_digest)) + "</span>";
  } else if (c.image_custom) {
    digest = "<span class='tl-bad'>not the tested image" + (c.image_tested_digest ? " (" + esc(shortHash(c.image_tested_digest)) + ")" : "") + "</span>";
  }
  const image =
    "<div class='tl-tile is-" + iStatus + "' id='tl-image' data-status='" + iStatus + "' data-name='LibreLane image' data-inst='" + (c.image_present ? "1" : "0") + "'>" +
      "<div class='tl-tile-top'><span class='tl-eyebrow'>LibreLane image</span>" + stateHtml(iStatus, iText) + "</div>" +
      "<div class='tl-tile-big'>LibreLane <span class='tl-tile-ver'>" + esc(c.librelane_version || imgTag || "?") + "</span></div>" +
      kvHtml([
        [c.image_present ? "On disk" : "Download", esc(c.image_present ? sizeStr(c.image_size_mb) : sizeStr(c.image_approx_mb, { approx: true })) || "—"],
        digest && ["Digest", digest, c.image || ""],
        inImage.length && ["Holds", esc(inImage.join(", "))],
      ]) +
      "<div class='tl-tile-act'>" + iAction + "</div>" +
    "</div>";
  return engine + image;
}

function paintRuntimeCard(container) {
  const rows = document.getElementById("tl-engine-rows");
  const root = document.getElementById("runtime-card");
  const c = container || {};
  // The server reports an in-flight pull (c.pulling) so a reloaded page
  // re-attaches to it instead of offering a second Download button.
  if (c.ready && c.pulling && !_pull.active) resumePullUI();
  if (rows) rows.innerHTML = engineTilesHtml(c, state.tools);
  const use = document.getElementById("tl-engine-use");
  if (use) use.innerHTML = state.runMode === "local"
    ? "<span class='tl-tag'>Not in use</span> Your run engine is Local tools; switch to Container in the Run menu to use this image."
    : "<span class='tl-tag is-on'>In use</span> Every run uses this engine and image.";
  if (!root) return;

  if (c.ready) {
    root.innerHTML = _pull.active ? pullProgressHtml() : "";
  } else if (c.available) {
    // A binary is installed but nothing is usable yet: offer convenient,
    // logout-free fixes (engineFixes is platform-aware).
    const mac = c.platform === "darwin";
    const canEnable = (c.docker || {}).present && (c.docker || {}).group_fixable;   // Linux + sg → no relogin
    const actions = engineFixes(c).map((f) =>
      "<button class='btn btn-sm " + (f.primary ? "btn-primary" : "btn-ghost") + "' id='" + f.id + "'>" + esc(f.label) + "</button>").join("");
    let hint;
    if (mac)
      hint = "On macOS the Docker daemon only runs while Docker Desktop is open. <em>Start podman machine</em> boots Podman's Linux VM instead.";
    else if (canEnable)
      hint = "<em>Enable Docker for my user</em> adds you to the <code>docker</code> group and applies it now, no logout. Or switch to rootless Podman.";
    else
      hint = "<em>Start Docker daemon</em> runs <code>sudo systemctl enable --now docker</code> (your password may be asked in the terminal). Or install rootless Podman.";
    root.innerHTML =
      "<div class='tl-fix'>" +
      "<div class='tl-fix-h'>" + icon("alert", { size: 14 }) + " Container engine installed but not currently active</div>" +
      "<pre class='code'>" + fmt.escape(c.daemon_msg || "engine not reachable") + "</pre>" +
      "<p class='hint'>" + hint + "</p>" +
      "<div class='tl-fix-acts'>" + actions + "</div>" +
      "</div>";
  } else {
    root.innerHTML =
      "<div class='tl-fix'>" +
      "<div class='tl-fix-h'>No container engine found</div>" +
      "<p class='hint'>Install <strong>Docker</strong> or <strong>Podman</strong> (rootless). One engine plus the " +
      sizeStr(c.image_approx_mb || 3000, { approx: true }) + " LibreLane image gives you every EDA tool, on every platform LibreLane supports. " +
      "Prefer native tools? Switch the run engine to <strong>Local tools</strong> and use the <em>Local toolchain</em> list below.</p>" +
      "<div class='tl-fix-acts'>" +
      engineFixes(c).map((f) => "<button class='btn btn-sm " + (f.primary ? "btn-primary" : "btn-ghost") + "' id='" + f.id + "'>" + esc(f.label) + "</button>").join("") +
      "<a class='btn btn-sm btn-ghost' href='https://docs.docker.com/get-docker/' target='_blank' rel='noopener'>Docker docs ↗</a>" +
      "<a class='btn btn-sm btn-ghost' href='https://podman.io/get-started' target='_blank' rel='noopener'>Podman docs ↗</a>" +
      "</div></div>";
  }
  document.getElementById("btn-runtime-recheck")?.addEventListener("click", () => { closeMenus(); renderTools(true); });
  // Repair = the first fix the remedy card recommends (Start / Enable / Install Podman).
  rows?.querySelector(".tl-repair")?.addEventListener("click", () => {
    const fix = root.querySelector(".tl-fix-acts .btn-primary") || root.querySelector(".tl-fix-acts .btn");
    if (fix) fix.click();
    else root.scrollIntoView({ block: "center", behavior: "smooth" });
  });
  document.getElementById("btn-enable-docker")?.addEventListener("click", async () => {
    const b = document.getElementById("btn-enable-docker");
    if (b) { b.disabled = true; b.textContent = "enabling…"; }
    toast.show("Adding you to the docker group (needs sudo)…", "info");
    try {
      const r = await api.enableDockerGroup();
      if (r.ok) toast.show(r.message || "Docker enabled successfully.", "success");
      else { toast.show(r.reason || "Could not enable Docker", "error"); if (r.guidance) renderLogs.append({ payload: { message: "ℹ " + r.guidance } }); }
    } catch (ex) {
      toast.show("Failed: " + ex.message, "error");
    }
    renderTools();
  });
  document.getElementById("btn-pull-image")?.addEventListener("click", async () => {
    try {
      const res = await api.containerPull();
      if (res.ok) {
        startPullUI();
        if (res.in_progress)
          toast.show("Image download in progress. Re-attached to it.", "info");
        else
          renderLogs.append({ payload: { message: "→ pulling container image " + (res.image || "") } });
      } else {
        toast.show(res.reason || "Could not start the image download", "error");
        if (res.guidance) renderLogs.append({ payload: { message: "ℹ " + res.guidance } });
      }
    } catch (ex) {
      toast.show("Download failed: " + ex.message, "error");
    }
  });
  document.getElementById("runtime-pull-cancel")?.addEventListener("click", async () => {
    _pull.cancelledByUser = true;
    try {
      const r = await api.cancelInstall("container:image");
      toast.show(r && r.ok ? "Image download cancelled. Downloaded layers stay cached." : "Nothing to cancel.", "info");
    } catch (ex) {
      toast.show("Cancel failed: " + (ex.message || ex), "error");
    }
    _pull.active = false;
    clearInterval(_pull.timer);
    renderTools();
  });
  document.getElementById("btn-install-docker")?.addEventListener("click", () => installEngine("docker"));
  document.getElementById("btn-install-podman")?.addEventListener("click", () => installEngine("podman"));
  document.getElementById("btn-start-docker")?.addEventListener("click", () => startEngineAction("docker"));
  document.getElementById("btn-start-podman")?.addEventListener("click", () => startEngineAction("podman"));
  const scope = rows || root;
  scope.querySelectorAll(".engine-install").forEach((b) =>
    b.addEventListener("click", () => { closeMenus(); installEngine(b.dataset.engine); }));
  scope.querySelectorAll(".engine-remove").forEach((b) =>
    b.addEventListener("click", () => { closeMenus(); removeEngine(b.dataset.engine); }));
}

// Start an installed-but-unreachable engine (Docker Desktop / podman machine /
// the Linux docker daemon). Async server-side; the outcome arrives as an SSE
// `installer_result` with key `engine:<name>` (handled in onInstallerResult,
// which chains the image pull once the engine is up).
async function startEngineAction(engine) {
  const b = document.getElementById("btn-start-" + engine);
  if (b) { b.disabled = true; b.textContent = "starting…"; }
  toast.show("Starting " + engine + ". Progress is in the Logs panel.", "info");
  try {
    const r = await api.startEngine(engine);
    if (r.status === "started" || r.in_progress) return;
    if (r.ok) toast.show(engine + " is running.", "success");
    else toast.show(r.reason || ("Could not start " + engine), "error");
  } catch (ex) {
    toast.show("Start failed: " + ex.message, "error");
  }
  renderTools();
}

async function installEngine(key) {
  document.querySelectorAll("[id^=btn-install-], .engine-install").forEach((b) => { b.disabled = true; });
  toast.show("Installing " + key + " with the package manager. Progress is in the Logs panel.", "info");
  try {
    const result = await api.installTool(key);
    if (result.status === "started") {
      // Async: the outcome arrives as an SSE `installer_result` event, which
      // toasts the result and chains the image pull ("in one go") on success.
      return;
    }
    handleInstallOutcome(key, result);
    if (result.ok) {
      await chainImagePull();
      return;
    }
  } catch (ex) {
    toast.show(key + " install error: " + ex.message, "error");
  }
  renderTools();   // re-probe → card reflects binary + daemon state
}

async function removeEngine(key) {
  const name = key === "docker" ? "Docker" : key === "podman" ? "Podman" : key;
  if (!(await confirmDialog({ title: "Remove " + name, danger: true, confirmText: "Remove " + name,
    body: "Removes the " + name + " package from the LanEx Linux environment (apt remove; your password may be asked in the terminal). " +
      "Kept: the downloaded image data, your projects, run results and PDKs. " +
      "Container runs stop working until an engine is installed again (Install Docker or Podman from the engine's menu)." }))) return;
  toast.show("Removing " + name + "…", "info");
  try {
    const r = await api.uninstallTool(key);
    if (r.ok) {
      toast.show(name + " removed via " + (r.method || "?"), "info");
      renderLogs.append({ payload: { message: "✓ " + key + " removed" } });
    } else {
      toast.show(name + " removal failed: " + (r.reason || ""), "error");
      renderLogs.append({ payload: { message: "✗ " + key + " removal: " + (r.reason || ""), level: "ERROR" } });
    }
  } catch (ex) {
    toast.show(name + " removal error: " + ex.message, "error");
  }
  renderTools();
}

// ------------------------------------------------------------------ local toolchain
// LanEx's own interpreter: never offered for removal from here.
const NO_REMOVE = new Set(["python", "pip"]);

export function paintLocalToolsGrid(info) {
  const root = document.getElementById("tools-grid");
  if (!root) return;
  root.innerHTML = "";
  // "In container" is only a usable fact once an engine is ready AND the image
  // is actually pulled — a flag without those would promise a tool that a click
  // can't deliver.
  const cont = (info && info.container) || {};
  const contReady = !!(cont.ready && cont.image_present);
  const local = state.runMode === "local";
  let found = 0, total = 0;
  for (const t of (info.tools || [])) {
    if (RECOMMENDED_KEYS.has(t.key)) continue;
    total++;
    if (t.installed) found++;
    const inCont = !!(t.in_container && contReady);
    const busy = !!state.installJobs[t.key];
    let status, chip = "", warn = "";
    if (busy) status = "busy";
    else if (t.windows_only && !t.installed) {
      status = "broken"; chip = "Windows build";
      warn = "A Windows build is on the WSL PATH, but the Linux flow can't use it. Install the Linux build inside WSL, or use the container image.";
    } else if (t.installed) status = "ready";
    // With Local tools a copy in the image doesn't run anything: it is missing.
    else if (local) { status = "missing"; chip = "Not installed"; }
    else if (inCont) status = "image";
    else status = "off";
    const card = document.createElement("div");
    card.className = "tl-row-host";
    card.dataset.key = t.key;
    const openBtn = inCont && CONTAINER_LAUNCHABLE.has(t.key)
      ? act("Open", "ct-open", "data-key='" + t.key + "'", { title: "Open the version-matched " + t.label + " from the LibreLane image" })
      : "";
    let action;
    if (busy) action = act("Installing…", "", "disabled");
    else if (!t.installed) action = buttonHtml(t, { inContainer: inCont && !local }) || openBtn;
    else action = openBtn;
    const menu = [];
    if (!t.installed && openBtn && action !== openBtn) menu.push(menuItem("Open from the image", "ct-open", "data-key='" + t.key + "'"));
    if (t.installed && !NO_REMOVE.has(t.key)) menu.push(menuItem("Uninstall " + t.label, "uninstall-btn", "data-key='" + t.key + "' data-label='" + esc(t.label) + "'", { danger: true }));
    card.innerHTML = rowHtml({
      id: "tl-local-" + t.key, name: esc(t.label), label: t.label, status, chip, warn, inst: !!t.installed,
      purpose: esc(t.what || ""), purposeTitle: t.installed ? "Path: " + (t.path || "—") : (t.container_only ? (t.install_recipe || "") : ""),
      have: t.installed ? shortVersion(t.version) || "installed" : (inCont ? "in container image" : ""),
      size: t.approx_mb ? sizeStr(t.approx_mb, { approx: true }) : "",
      action, menu,
    });
    root.appendChild(card);
  }
  const cnt = document.getElementById("tl-local-count");
  if (cnt) cnt.textContent = found + " of " + total + " on this system's PATH";
  const det = document.getElementById("local-tools-card");
  if (det && local && !det._autoOpened) { det.open = true; det._autoOpened = true; }
  root.querySelectorAll(".ct-open").forEach((b) => wireOpen(b));
}

function wireOpen(b) {
  b.addEventListener("click", async () => {
    const key = b.dataset.key;
    closeMenus();
    b.disabled = true;
    try {
      const r = await api.containerToolOpen(key);
      if (r && r.ok) toast.show(r.hint || (key + " opening from the container image… (first window can take a few seconds)"), "success");
      else toast.show((r && r.error) || (key + " could not be launched"), r && r.need === "image" ? "warn" : "error");
    } catch (ex) {
      toast.show(key + " launch error: " + (ex.message || ex), "error");
    }
    b.disabled = false;
  });
}

// ------------------------------------------------------------------ PDKs
// Every library a PDK variant publishes (ciel's metadata), with the starter set
// pre-checked and unpublished ones shown but disabled. `sel`: a Set of chosen
// ids (the user's last choice), or null for the starter set.
export function libraryListHtml(key, p, sel = null) {
  const unavailableReasons = normalizeUnavailableLibraries(p && p.unavailable_libraries);
  const unavailable = new Set(Object.keys(unavailableReasons));
  const allLibs = [...new Set([
    ...(Array.isArray(p && p.libraries) ? p.libraries : []),
    ...Object.keys(unavailableReasons),
  ])];
  const defLibs = new Set(Array.isArray(p && p.default_libraries) ? p.default_libraries : []);
  return allLibs.map((id) => {
    const req = defLibs.has(id);
    if (unavailable.has(id)) {
      const reason = unavailableReasons[id] || "Not published for this release";
      return `<label class="tl-lib is-off"><input type="checkbox" class="lib-cb-${esc(key)}" value="${esc(id)}" disabled> ${esc(id)} <span>(${esc(reason)})</span></label>`;
    }
    const on = sel ? sel.has(id) : req;
    return `<label class="tl-lib"><input type="checkbox" class="lib-cb-${esc(key)}" value="${esc(id)}" ${req ? "data-starter='1' " : ""}${on ? "checked" : ""}> ${esc(id)}${req ? " <span>(starter)</span>" : ""}</label>`;
  }).join("");
}

// Libraries a plain Install downloads: the user's last choice, else the starter
// set; null when the catalog lists none (ciel then picks its defaults).
export function libsForInstall(p, sel = null) {
  const unavailable = new Set(Object.keys(normalizeUnavailableLibraries(p && p.unavailable_libraries)));
  const all = (Array.isArray(p && p.libraries) ? p.libraries : []).filter((id) => !unavailable.has(id));
  if (!all.length && !unavailable.size) return null;
  if (sel) return all.filter((id) => sel.has(id));
  const def = new Set(Array.isArray(p && p.default_libraries) ? p.default_libraries : []);
  return all.filter((id) => def.has(id));
}

const _libSel = {};

function libCount(p) {
  return new Set([...(Array.isArray(p.libraries) ? p.libraries : []), ...Object.keys(normalizeUnavailableLibraries(p.unavailable_libraries))]).size;
}

export function renderPdkStore(info) {
  const drop = document.getElementById("pdk-store-row");
  if (!drop) return;
  const pdkInfo = (info && info.pdk) || {};
  const installed = new Set(pdkInfo.installed_pdks || []);
  const catalog = (info && info.pdk_catalog) || {};
  const versions = pdkInfo.versions || {};
  const cielMissing = !pdkInfo.ciel_installed;
  const noneInstalled = installed.size === 0;
  const cielTool = ((info && info.tools) || []).find((t) => t.key === "ciel") || {};
  const llv = (info && info.container && info.container.librelane_version) || "";

  // ciel sits in the section header: one quiet line when present.
  const aside = document.getElementById("tl-pdk-ciel-host");
  if (aside) {
    aside.innerHTML =
      "<span class='tl-ciel' id='tl-pdk-ciel' data-status='" + (cielMissing ? "missing" : "ready") + "' data-name='ciel' data-inst='" + (cielMissing ? "0" : "1") + "'" +
        " title='The PDK manager. Downloads the exact PDK version LibreLane asks for.'>" +
        (cielMissing
          ? stateHtml("missing", "ciel missing") + act("Install ciel", "", "id='install-ciel-btn'", { primary: true })
          : stateHtml("ready", "ciel " + (shortVersion(cielTool.version) || "installed"))) +
      "</span>";
    document.getElementById("install-ciel-btn")?.addEventListener("click", () => installByKey("ciel"));
  }

  const variantHtml = (key) => {
    const p = catalog[key] || {};
    const isInstalled = installed.has(key);
    const busy = !!state.installJobs["pdk:" + key];
    const v = versions[key] || {};
    const differs = isInstalled && v.installed && v.pinned && v.installed !== v.pinned;
    const measured = (pdkInfo.installed_sizes_mb || {})[key];
    const size = isInstalled && measured != null ? sizeStr(measured)
      : (p.approx_gb != null ? "~" + p.approx_gb + " GB" : "");
    let status, ver, action = "", warn = "";
    if (busy) {
      status = "busy"; ver = "<span class='tl-var-busy'><span class='spinner-sm'></span> Installing</span>";
      action = act("Cancel", "pdk-cancel-btn", "data-pdk='" + esc(key) + "'");
    } else if (isInstalled) {
      status = differs ? "custom" : "ready";
      if (differs) {
        ver = "<span class='tl-bad' title='Installed " + esc(v.installed) + "; pinned " + esc(v.pinned) + "'>Not the pinned version</span>";
        warn = "Installed " + esc(shortHash(v.installed)) + "; LibreLane " + esc(llv) + " pins " + esc(shortHash(v.pinned)) +
          ". Container runs download the pinned one; Update installs it now.";
        action = act("Update", "pdk-install-btn", "data-pdk='" + esc(key) + "'", { primary: true, title: "Install the pinned version" });
      } else if (v.installed && v.pinned) {
        ver = "<span class='tl-good' title='" + esc(v.installed) + ": the version LibreLane " + esc(llv) + " pins'>" + icon("check", { size: 12, stroke: 2 }) + "Pinned version</span>";
      } else {
        ver = "<span class='muted' title='Installed without a version LanEx can read (for example by hand)'>Version unknown</span>";
      }
    } else if (p.note) {
      status = "off"; ver = "<span class='muted' title='" + esc(p.note) + "'>Not available</span>";
    } else {
      status = noneInstalled && (p.default_variant || p.recommended) ? "missing" : "off";
      ver = "<span class='muted'>Not installed</span>";
      action = act("Install", "pdk-install-btn", "data-pdk='" + esc(key) + "'",
        { primary: status === "missing", title: "Downloads the starter libraries (choose others from the … menu)" });
    }
    const n = libCount(p);
    const menu = [];
    if (n && !busy) menu.push(menuItem("Libraries (" + n + ")…", "pdk-libs-btn", "data-pdk='" + esc(key) + "'"));
    if (isInstalled && !busy) menu.push(menuItem("Remove the " + pdkFamily(catalog, key) + " family", "pdk-uninstall-btn", "data-pdk='" + esc(key) + "'", { danger: true }));
    const tags = ((p.default_variant || p.recommended) ? "<span class='tl-tag' title='The variant LanEx uses by default for this PDK'>default</span>" : "") +
      (p.supported === false ? "<span class='tl-tag is-quiet' title='The LibreLane flow does not support this variant'>not in flow</span>" : "");
    return (
      "<div class='tl-var is-" + status + "' id='tl-pdk-" + esc(key) + "' data-status='" + status + "' data-inst='" + (isInstalled ? "1" : "0") + "' data-name='" + esc(p.label || key) + "'>" +
        "<span class='tl-var-dot'></span>" +
        "<div class='tl-var-what'><div class='tl-var-name'>" + esc(p.label || key) + tags + "</div>" +
          "<div class='tl-var-desc' title='" + esc(p.description || "") + "'>" + esc(p.description || "") + "</div>" +
        "</div>" +
        "<div class='tl-var-meta'><span class='tl-var-size'>" + esc(size) + "</span><span class='tl-var-ver'>" + ver + "</span></div>" +
        "<div class='tl-var-acts'>" + action + (menu.length ? moreHtml(menu) : "<span class='tl-more-gap'></span>") + "</div>" +
        (warn ? "<div class='tl-warn tl-var-warn'>" + icon("alert", { size: 12 }) + " " + warn + "</div>" : "") +
      "</div>"
    );
  };

  const famHtml = ({ family, keys }) => {
    const first = catalog[keys[0]] || {};
    const inst = keys.filter((k) => installed.has(k));
    const mb = inst.reduce((a, k) => a + ((pdkInfo.installed_sizes_mb || {})[k] || 0), 0);
    return (
      "<div class='tl-fam' id='tl-fam-" + esc(family) + "'>" +
        "<div class='tl-fam-h'>" +
          "<div><div class='tl-fam-name'>" + esc(family) + "</div><div class='tl-fam-sub'>" + [first.foundry, first.node].filter(Boolean).map(esc).join(" · ") + "</div></div>" +
          "<div class='tl-fam-tot'><span><b>" + inst.length + " of " + keys.length + "</b> installed</span>" + (mb ? "<span>" + esc(sizeStr(mb)) + " on disk</span>" : "") + "</div>" +
        "</div>" +
        "<div class='tl-vars'>" + keys.map(variantHtml).join("") + "</div>" +
      "</div>"
    );
  };
  drop.innerHTML = pdkColumns(pdkFamilies(catalog))
    .map((col) => "<div class='tl-fam-col'>" + col.map(famHtml).join("") + "</div>").join("");

  // Wire PDK install buttons
  drop.querySelectorAll(".pdk-install-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const pdk = btn.dataset.pdk;
      installPdk(pdk, libsForInstall(catalog[pdk], _libSel[pdk] || null));
    });
  });
  drop.querySelectorAll(".pdk-libs-btn").forEach((btn) =>
    btn.addEventListener("click", () => { closeMenus(); openLibraries(btn.dataset.pdk, catalog[btn.dataset.pdk] || {}, installed.has(btn.dataset.pdk)); }));
  drop.querySelectorAll(".pdk-cancel-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const pdk = btn.dataset.pdk;
      try {
        const res = await api.cancelInstall("pdk:" + pdk);
        if (res.ok) {
          toast.show("Installation cancelled.", "info");
        }
      } catch (e) {}
      delete state.installJobs["pdk:" + pdk];
      renderTools();
    });
  });
  drop.querySelectorAll(".pdk-uninstall-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const pdk = btn.dataset.pdk;
      closeMenus();
      const family = pdkFamily(catalog, pdk);
      const siblings = [...installed].filter((x) => pdkFamily(catalog, x) === family);
      if (!(await confirmDialog({ title: "Remove the " + family + " PDK", danger: true, confirmText: "Remove " + family,
        body: "Removes every installed version of the " + family + " family from disk: " + (siblings.join(", ") || pdk) +
          (_pdkRoot ? " (in " + _pdkRoot + ")" : "") + ". " +
          "Kept: your projects and run results. Designs that use " + family + " can't run until you install it again." }))) return;
      try {
        const result = await api.uninstallPdk(pdk);
        if (result.ok) {
          toast.show(`PDK ${pdk} uninstalled`, "info");
          renderLogs.append({ payload: { message: "✓ PDK " + pdk + " uninstalled via " + (result.method || "?") } });
          // Optimistic: drop all variants of the removed family so the cards flip now.
          if (state.tools?.pdk) {
            const removedFamily = result.family || family;
            state.tools.pdk.installed_pdks = (state.tools.pdk.installed_pdks || []).filter((x) => {
              const xFam = pdkFamily(catalog, x);
              return xFam !== removedFamily;
            });
            if (state.tools.pdk.installed_sizes_mb) {
              for (const k of Object.keys(state.tools.pdk.installed_sizes_mb)) {
                const kFam = pdkFamily(catalog, k);
                if (kFam === removedFamily) delete state.tools.pdk.installed_sizes_mb[k];
              }
            }
          }
          if (state.tools) paint(state.tools);
          // Keep the Setup tab honest too — its picker re-fetches /api/pdks.
          import("./setup.js").then((m) => m.populatePdkPicker && m.populatePdkPicker()).catch(() => {});
        } else {
          toast.show(`PDK ${pdk} uninstall failed`, "error");
          renderLogs.append({ payload: { message: "✗ PDK " + pdk + " uninstall failed: " + (result.reason || "unknown"), level: "ERROR" } });
        }
      } catch (ex) {
        toast.show(`PDK ${pdk} uninstall error: ${ex.message}`, "error");
        renderLogs.append({ payload: { message: "✗ PDK " + pdk + " uninstall error: " + ex.message, level: "ERROR" } });
      }
      renderTools();
    });
  });
}

// The library picker for one variant. Install (or "Download checked" for an
// installed variant) uses the ticked set; Close keeps it for the next Install.
async function openLibraries(key, p, isInstalled) {
  let picked = null;
  const v = await customDialog({
    title: esc((p.label || key) + " libraries"),
    wide: true,
    bodyHtml:
      "<p>PDK archives are large. Tick only the cell libraries your design needs; the starter set is enough for the examples.</p>" +
      "<div class='tl-libs-bar'><button type='button' class='btn btn-sm btn-ghost' data-lib-set='starter'>Starter set</button>" +
      "<button type='button' class='btn btn-sm btn-ghost' data-lib-set='all'>All supported</button></div>" +
      "<div class='tl-libs-list'>" + libraryListHtml(key, p, _libSel[key] || null) + "</div>",
    buttons: [
      { label: "Close", value: "close", cls: "btn-ghost" },
      ...(p.note ? [] : [{ label: isInstalled ? "Download checked" : "Install with these", value: "go", cls: "btn-primary" }]),
    ],
    onMount: (back) => {
      const boxes = () => Array.from(back.querySelectorAll(".tl-libs-list input:not(:disabled)"));
      back.querySelectorAll("[data-lib-set]").forEach((b) => b.addEventListener("click", () => {
        const all = b.dataset.libSet === "all";
        boxes().forEach((cb) => { cb.checked = all ? true : cb.dataset.starter === "1"; });
      }));
      const read = () => { picked = new Set(boxes().filter((cb) => cb.checked).map((cb) => cb.value)); };
      back.addEventListener("change", read);
      read();
    },
  });
  if (picked) _libSel[key] = picked;
  if (v === "go") installPdk(key, libsForInstall(p, picked));
}

async function installPdk(pdk, libraries) {
  state.installJobs["pdk:" + pdk] = true;
  renderTools();
  try {
    const result = await api.installCiel(pdk, libraries);
    if (result.ok) {
      if (result.in_progress) {
        toast.show(`PDK ${pdk} is already downloading.`, "info");
      } else {
        toast.show(`PDK ${pdk} installation started. Progress is in the Logs panel.`, "info");
        renderLogs.append({ payload: { message: "→ PDK " + pdk + " installation started in background." } });
      }
    } else {
      delete state.installJobs["pdk:" + pdk];
      const msg = "✗ PDK " + pdk + " failed: rc=" + (result.rc ?? "?") + " " + (result.reason || "");
      toast.show(`PDK ${pdk} install failed: ${result.reason || ""}`, "error");
      renderLogs.append({ payload: { message: msg, level: "ERROR" } });
      renderTools();
    }
  } catch (ex) {
    delete state.installJobs["pdk:" + pdk];
    toast.show(`PDK ${pdk} install error: ${ex.message}`, "error");
    renderLogs.append({ payload: { message: "✗ PDK " + pdk + " error: " + ex.message, level: "ERROR" } });
    renderTools();
  }
}

export async function paint(info) {
  try {
    paintRuntimeCard(info.container);
  } catch (ex) {
    console.error("Runtime card render failure:", ex);
  }

  try {
    await renderDesktopViewers(info);
  } catch (ex) {
    console.error("Desktop viewers render failure:", ex);
  }

  try {
    await renderRecommendedTools(info);
  } catch (ex) {
    console.error("Recommended tools render failure:", ex);
  }

  try {
    paintLocalToolsGrid(info);
  } catch (ex) {
    console.error("Local tools grid render failure:", ex);
    const root = typeof document !== "undefined" ? document.getElementById("tools-grid") : null;
    if (root) {
      root.innerHTML =
        "<div class='empty'><span class='ico'>" + icon('alert',{size:40}) + "</span><h3>Local tools render failed</h3><p>" + fmt.escape(ex.message || String(ex)) + "</p></div>";
    }
  }

  try {
    paintToolBar(info);
  } catch (ex) {
    console.error("Tool bar render failure:", ex);
  }

  try {
    renderPdkStore(info);
  } catch (ex) {
    console.error("PDK store render failure:", ex);
    const drop = typeof document !== "undefined" ? document.getElementById("pdk-store-row") : null;
    if (drop) {
      drop.innerHTML =
        "<div class='empty' style='padding:var(--s-4)'><span class='ico'>" + icon('alert',{size:32}) + "</span><h3>PDK store render failed</h3><p>" + fmt.escape(ex.message || String(ex)) + "</p></div>";
    }
  }

  wireInstallButtons();
  wireUninstallButtons();
  try {
    paintSummary(info);
  } catch (ex) {
    console.error("Tools summary render failure:", ex);
  }
}

let _lastToolInfo = null;
// Engine switches change whether missing native tools matter; repaint the badge.
export function repaintToolBadge() {
  if (_lastToolInfo) paintToolBar(_lastToolInfo);
  // ...and the page itself (the verdict and the local list depend on it).
  if (state.tools && typeof document !== "undefined" && document.getElementById &&
      document.getElementById("sec-tools")?.classList?.contains("section-active")) paint(state.tools);
}

function paintToolBar(info) {
  _lastToolInfo = info;
  const icon = document.getElementById("tools-count");
  if (!icon) return;
  const missing = info.tools.filter((t) => !t.installed && t.category !== "core").length;
  // With the Container engine every EDA tool ships in the image, so missing
  // native installs aren't a problem worth a badge; only flag them for Local.
  const matters = state.runMode === "local" && missing > 0;
  icon.hidden = !matters;
  icon.textContent = missing.toString();
  icon.classList.remove("badge-pass", "badge-fail");
  if (matters) icon.classList.add("badge-fail");
  const btn = document.getElementById("tools-icon");
  if (btn) btn.dataset.tip = matters ? missing + " native tool" + (missing === 1 ? "" : "s") + " missing for Local tools" : "Tools and PDKs";
}

function buttonHtml(t, { inContainer = false } = {}) {
  // OpenROAD/Magic/Netgen have no pip/apt/brew package — a host "Install" button
  // there only ever fails. Point at the container image instead (the supported,
  // cross-platform path), with conda/Nix as the advanced fallback.
  if (t.container_only) {
    if (inContainer) return "";
    return "<span class='tl-act tl-act-none' title='No host package. Run it from the container image (Container engine + LibreLane image), or install with conda/Nix: " +
      esc(t.install_recipe || "") + "'>Image only</span>";
  }
  if (Array.isArray(t.install_recipe) || t.install_recipe) {
    // When the container copy already covers the tool, the native install is an
    // extra, not a requirement — label it so.
    return act(inContainer ? "Install locally" : "Install", "install-btn", "data-key='" + t.key + "'", { primary: !inContainer && state.runMode === "local" });
  }
  return "<span class='tl-act tl-act-none' title='" + esc(t.install_recipe || "manual install") + "'>Manual install</span>";
}

function wireInstallButtons() {
  document.querySelectorAll(".install-btn").forEach((btn) => {
    if (btn._tlWired) return;
    btn._tlWired = true;
    btn.addEventListener("click", () => {
      state.installJobs[btn.dataset.key] = true;
      btn.disabled = true; btn.textContent = "Installing…";
      installByKey(btn.dataset.key);
    });
  });
}

function wireUninstallButtons() {
  document.querySelectorAll(".uninstall-btn").forEach((btn) => {
    if (btn._tlWired) return;
    btn._tlWired = true;
    btn.addEventListener("click", async () => {
      const key = btn.dataset.key;
      const label = btn.dataset.label || key;
      closeMenus();
      if (!(await confirmDialog({ title: "Uninstall " + label, danger: true, confirmText: "Uninstall",
        body: "Removes the locally installed " + label + " (the copy in the LibreLane image is not touched). " +
          "Your projects and run results are kept." }))) return;
      btn.textContent = "…";
      try {
        const result = await api.uninstallTool(key);
        if (result.ok) {
          toast.show(`${key} uninstalled`, "info");
          renderLogs.append({ payload: { message: "✓ " + key + " uninstalled via " + (result.method || "?") } });
          // Optimistic: flip the row to "missing" immediately so the Tools tab
          // reflects the change without waiting on the re-probe.
          const tool = (state.tools?.tools || []).find((t) => t.key === key);
          if (tool) { tool.installed = false; tool.path = ""; tool.version = ""; }
          if (state.tools) paint(state.tools);
        } else {
          toast.show(`${key} uninstall failed`, "error");
          renderLogs.append({ payload: { message: "✗ " + key + " uninstall failed: " + (result.reason || "unknown"), level: "ERROR" } });
        }
      } catch (ex) {
        toast.show(`${key} uninstall error: ${ex.message}`, "error");
        renderLogs.append({ payload: { message: "✗ " + key + " uninstall error: " + ex.message, level: "ERROR" } });
      }
      renderTools();
    });
  });
}

// Shared outcome handler for a finished install. Called with the synchronous
// result for legacy/immediate shapes, and from the SSE `installer_result`
// event for async installs (the POST returns {status:"started"} right away).
function handleInstallOutcome(key, result) {
  if (result.in_progress) {
    toast.show(`${key} is already installing.`, "info");
    return;
  }
  if (result.cancelled) {
    toast.show(`${key} install cancelled.`, "info");
    renderLogs.append({ payload: { message: "• " + key + " install cancelled by user" } });
    return;
  }
  if (result.ok) {
    toast.show(`${key} installed successfully`, "success");
    renderLogs.append({
      payload: {
        message:
          "✓ " + key + " installed via " + (result.label || result.method || "?") +
          (result.argv ? " (" + result.argv.join(" ") + ")" : "") +
          (result.rc !== undefined ? " rc=" + result.rc : ""),
      },
    });
  } else if (result.needs_sudo) {
    // sudo can't prompt from the GUI — show the exact command to run.
    toast.show(`${key} requires elevated privileges; run the command below in a terminal.`, "warn");
    renderLogs.append({ payload: { message: result.guidance || ("Run with sudo: " + key), level: "WARN" } });
  } else {
    // Surface the actionable guidance (e.g. "use conda/Nix/container"), not
    // just "failed".
    const why = result.guidance || result.reason || "no install method on this system";
    toast.show(`Can't auto-install ${key}: ${why}`, "error");
    const tried = (result.tried || []).join("; ");
    renderLogs.append({
      payload: { message: "✗ " + key + " install failed: " + why + (tried ? " [" + tried + "]" : ""), level: "ERROR" },
    });
  }
}

// Final outcome of an async install, delivered over SSE (dispatched from
// app.js). Toast + log the result, chain the engine→image pull for a one-click
// toolchain, then re-probe so the tab reflects the new state.
export async function onInstallerResult(ev) {
  const key = ev.key || "tool";
  delete state.installJobs[key];
  if (key.indexOf("engine:") === 0) {
    // Outcome of a Start-engine action — not an install, so word it right.
    const eng = ev.engine || key.slice(7);
    if (ev.ok) {
      toast.show(eng + (ev.already ? " was already running." : " is running."), "success");
      await chainImagePull();   // engine up → image next, one click total
      return;
    }
    toast.show(ev.reason || ev.guidance || ("Could not start " + eng), "error");
    renderLogs.append({ payload: { message: "✗ start " + eng + ": " + (ev.reason || "failed"), level: "ERROR" } });
    renderTools();
    return;
  }
  handleInstallOutcome(key, ev);
  if (ev.ok && (key === "docker" || key === "podman")) {
    await chainImagePull();
    return; // chainImagePull repaints
  }
  renderTools();
}

// Once a container engine is usable, chain straight into the image pull so a
// single click sets up the whole toolchain. If the engine isn't reachable yet
// (e.g. Docker needs a group/login), the engine tile shows the next fix.
async function chainImagePull() {
  try {
    const info = await api.tools();
    state.tools = info;
    paint(info);
    const c = info.container || {};
    if (c.ready && !c.image_present && !_pull.active) {
      const res = await api.containerPull();
      if (res.ok) {
        startPullUI();
        renderLogs.append({ payload: { message: "→ engine ready; pulling container image " + (res.image || "") } });
      }
    }
  } catch (_e) {
    renderTools();   // re-probe → card reflects binary + daemon state
  }
}

async function installByKey(key) {
  try {
    const result = await api.installTool(key);
    if (result.status === "started") {
      toast.show(`${key} install started. Progress is in the Logs panel; this page updates when it finishes.`, "info");
      return;
    }
    delete state.installJobs[key];
    handleInstallOutcome(key, result);
  } catch (ex) {
    delete state.installJobs[key];
    const body = ex.body;
    if (body && body.kind === "manual") {
      showInstallModal(key, body.recipe || "(no recipe in this build)");
      return;
    }
    toast.show(key + " install error: " + ex.message, "error");
    renderLogs.append({
      payload: { message: "✗ " + key + " install error: " + ex.message, level: "ERROR" },
    });
  }
}

function showInstallModal(key, recipe) {
  // Build a small modal "How to install" instead of the intrusive alert().
  let modal = document.getElementById("install-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "install-modal";
    modal.style.cssText =
      "position:fixed;inset:0;background:rgba(0,0,0,0.55);display:grid;place-items:center;z-index:60;backdrop-filter:blur(4px);";
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.style.display = "none";
    });
    document.body.appendChild(modal);
  }
  modal.innerHTML =
    '<div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);' +
    'padding:var(--s-5);max-width:520px;width:90%;box-shadow:var(--sh-3);">' +
    '<div style="display:flex;align-items:center;justify-content:space-between;">' +
    "<h2>Install " + key + "</h2>" +
    '<button class="btn btn-ghost" id="install-modal-close">Close</button>' +
    "</div>" +
    "<p>" +
    "This tool isn't pip-installable; please use the recipe below for your platform." +
    "</p>" +
    '<pre class="code">' +
    fmt.escape(recipe) +
    "</pre>" +
    "</div>";
  modal.style.display = "grid";
  document.getElementById("install-modal-close")?.addEventListener("click", () => {
    modal.style.display = "none";
  });
}
