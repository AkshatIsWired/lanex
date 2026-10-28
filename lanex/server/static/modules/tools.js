// tools.js — the Tools tab: the component manager. One dense row per component
// (flow engine, LibreLane image, PDKs, viewers, helpers, the local toolchain):
// status chip | what it is | installed vs tested version | size | one action,
// with destructive actions behind a "More" menu. Shell-only installs depend on
// this page to install, update, repair and remove everything, so every action
// the old cards had is still here.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
// Tool work (installs, removals, the engine) is told in the Logs panel, with
// the install output it belongs to; the run's own log is Flow's.
const renderLogs = {
  append: (e) => import("./logdrawer.js").then((d) => d.appendDrawer((e.payload || e).message || "")).catch(() => {}),
};
import { toast } from "./toast.js";
import { confirmDialog } from "./dialog.js";
import { icon } from "./icons.js";
import { wireJump } from "./jumpnav.js";

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

async function loadPdkRoot() {
  const input = document.getElementById("pdk-root-input");
  if (!input) return;
  try {
    const rootInfo = await api.getPdkRoot();
    if (rootInfo && rootInfo.ok && rootInfo.pdk_root) {
      input.value = rootInfo.pdk_root;
      _pdkRoot = rootInfo.pdk_root;
    }
  } catch (ex) {
    console.warn("Failed to load PDK root:", ex);
  }
}
let _pdkRoot = "";

// ------------------------------------------------------------------ rows
// One component row. `r`: { id, name, purpose, warn, status, chip, have, want,
// size, action (html), menu ([{html}]), sub (html under the row), inst }.
const CHIP = {
  ready: "Ready", update: "Update available", missing: "Missing", broken: "Broken",
  custom: "Custom", off: "Not installed", busy: "Working", image: "In image",
};
const PROBLEM = new Set(["missing", "broken", "custom"]);

export function rowHtml(r) {
  const st = r.status || "off";
  const chip = r.chip || CHIP[st] || st;
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
      "<div class='tl-acts'>" + (r.action || "<span class='tl-act tl-act-none'></span>") +
        (menu.length
          ? "<details class='tl-more'><summary class='tl-more-btn' title='More actions' aria-label='More actions'>" +
              "<svg viewBox='0 0 24 24' width='16' height='16' fill='currentColor' aria-hidden='true'><circle cx='5' cy='12' r='1.6'/><circle cx='12' cy='12' r='1.6'/><circle cx='19' cy='12' r='1.6'/></svg>" +
            "</summary><div class='tl-menu'>" + menu.join("") + "</div></details>"
          : "<span class='tl-more-gap'></span>") +
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

// Every action button is the same size; the label says what it does.
function act(label, cls, attrs = "", { primary = false, title = "" } = {}) {
  return "<button class='btn btn-sm tl-act " + (primary ? "btn-primary " : "btn-ghost ") + cls + "' " + attrs +
    (title ? " title='" + esc(title) + "'" : "") + ">" + esc(label) + "</button>";
}
function menuItem(label, cls, attrs = "", { danger = false } = {}) {
  return "<button class='tl-menu-item" + (danger ? " is-danger" : "") + " " + cls + "' " + attrs + ">" + esc(label) + "</button>";
}
const checkAct = () => act("Check", "tl-check", "", { title: "Probe this component again" });

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

// ------------------------------------------------------------------ render
export async function renderTools(fresh) {
  const root = document.getElementById("tools-grid");
  if (!root) return;
  wireJump(document.getElementById("sec-tools"));   // static section-jump nav (§6.6)
  wireStatic();

  // Fetch/populate PDK root independently so a separate section cannot leave it blank
  loadPdkRoot();

  let info;
  try {
    // fresh=true (Check / Check all) bypasses the server's 8s status caches —
    // a probe cached moments before the user fixed the engine reads as broken.
    info = await api.tools(fresh);
    state.tools = info;
  } catch (ex) {
    // Only API probe failures display "Tool probe failed" and use host-only fallback
    renderDesktopViewers(null);
    const sum = document.getElementById("tools-summary");
    if (sum) sum.innerHTML = "<div class='tl-sum is-fail'><strong>Tool probe failed</strong><span>" + esc(ex.message) + "</span></div>";
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

// Desktop layout viewers (KLayout / Magic / OpenROAD GUI) as rows. Both KLayout
// and Magic ship in the LibreLane container image; the Layout tab launches
// whichever is installed on the run's GDS. GDS3D's row is painted with the
// helpers' install logic (renderRecommendedTools) into #viewer-gds3d.
//
// The status must report BOTH ways a viewer can be usable. `api.desktopTools()`
// only probes HOST binaries, so a container-only KLayout/Magic — the normal
// appliance setup, where the Layout tab happily launches them from the image —
// would read missing while plainly working. So fall back to the same
// `in_container` + image-pulled facts the tool grid uses (`info` from
// `api.tools()`; null when that probe failed, host-only then).
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
  const row = (key, name, purpose) => {
    const host = byKey[key] && byKey[key].available;
    const t = byToolKey[key] || {};
    const inImage = !host && t.in_container && contReady;
    let status, have, action;
    if (host || t.installed) {
      status = "ready"; have = shortVersion(t.version) || "installed on this system";
      action = inImage || (t.in_container && contReady) ? openAct(key, name) : checkAct();
    } else if (inImage) {
      status = "image"; have = "in container image";
      action = openAct(key, name);
    } else {
      status = "missing"; have = "";
      action = (t.install_recipe && !t.container_only)
        ? act("Install", "install-btn", "data-key='" + key + "'", { primary: true })
        : checkAct();
    }
    return rowHtml({
      id: "tl-viewer-" + key, name, purpose, status, have, inst: status !== "missing",
      size: t.approx_mb ? sizeStr(t.approx_mb, { approx: true }) : "", action,
      purposeTitle: inImage ? "Included in the LibreLane container image. The Layout tab launches it directly." : "",
    });
  };
  root.innerHTML =
    row("klayout", "KLayout", "2D layout viewer. The Layout tab opens a run's GDS in it.") +
    row("magic", "Magic", "2D layout and DRC, opened with the PDK's <code>.magicrc</code> so layers draw correctly.") +
    row("openroad", "OpenROAD GUI", "Placement, routing and timing views of a run's database.");
  wireRowActions(root);
  root.querySelectorAll(".ct-open").forEach((b) => wireOpen(b));
}

function openAct(key, name) {
  return CONTAINER_LAUNCHABLE.has(key)
    ? act("Open", "ct-open", "data-key='" + key + "'", { title: "Open the version-matched " + name + " from the LibreLane image" })
    : checkAct();
}

// Helpers (iverilog, graphviz, gtkwave) and the GDS3D viewer. Native installs
// use the shared escalating installer — if a system package needs sudo, the
// user is prompted for a password in the launch terminal (handled globally by
// app.js's installer_info banner).
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
  const gds3d = desktop.gds3d;

  const PURPOSE = {
    iverilog: "Runs your testbenches in the RTL IDE (Icarus Verilog).",
    graphviz: "Draws the synthesis schematics in Reports.",
    gtkwave: "Waveform viewer; the IDE's 'Open in GTKWave' hands it the VCD/FST.",
  };
  const probeRow = (t) => {
    if (!t) return "";
    const busy = !!state.installJobs[t.key];
    const canInstall = Array.isArray(t.install_recipe) || !!t.install_recipe;
    let status, action;
    if (busy) { status = "busy"; action = act("Installing…", "", "disabled"); }
    else if (t.installed) { status = "ready"; action = checkAct(); }
    else {
      status = "off";
      action = canInstall
        ? act("Install", "rec-install", "data-key='" + t.key + "'", { primary: true })
        : "<span class='tl-act tl-act-none' title='" + esc(t.install_recipe || "manual install") + "'>Manual install</span>";
    }
    return rowHtml({
      id: "tl-helper-" + t.key, name: esc(t.label), purpose: esc(PURPOSE[t.key] || t.what || ""),
      purposeTitle: t.what || "", status, inst: t.installed,
      have: t.installed ? shortVersion(t.version) || "installed" : "",
      size: t.approx_mb ? sizeStr(t.approx_mb, { approx: true }) : "",
      action,
      menu: t.installed ? [menuItem("Remove " + t.label, "rec-uninstall", "data-key='" + t.key + "' data-label='" + esc(t.label) + "'", { danger: true })] : [],
    });
  };

  root.innerHTML = probeRow(byKey.iverilog) + probeRow(byKey.graphviz) + probeRow(byKey.gtkwave);

  const g = document.getElementById("viewer-gds3d");
  if (g) {
    const have = !!(gds3d && gds3d.available);
    g.innerHTML = rowHtml({
      id: "tl-viewer-gds3d", name: "GDS3D", inst: have,
      purpose: "3D view of the layer stack. Built from source once (a few minutes); open it from Layout.",
      status: have ? "ready" : "off", have: have ? "installed" : "",
      action: have ? checkAct() : act("Install", "", "id='btn-install-gds3d'", { primary: true, title: "Builds GDS3D from source. Progress is in the Logs panel." }),
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
    wireRowActions(g);
  }
  wireRowActions(root);

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
          "Your projects and run results are kept. Install it again from this row any time." }))) return;
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
      body: "Removes the GDS3D binary and its build folder. Your projects and run results are kept. You can rebuild it any time from this row." }))) return;
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
// Header buttons, filters, PDK_ROOT save: wired once.
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
  sec.querySelectorAll("[data-tl-filter]").forEach((b) =>
    b.addEventListener("click", () => setFilter(b.dataset.tlFilter)));
  document.getElementById("btn-save-pdk-root")?.addEventListener("click", async () => {
    const val = document.getElementById("pdk-root-input").value.trim();
    if (!val) return;
    try {
      const res = await api.setPdkRoot(val);
      if (res.ok) {
        toast.show("PDK folder set to " + res.pdk_root, "success");
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
  if (sum) sum.innerHTML = "<div class='tl-sum is-loading'><span class='spinner-sm'></span><strong>Checking components…</strong></div>";
}

let _filter = "all";
function setFilter(f) {
  _filter = f || "all";
  const sec = document.getElementById("sec-tools");
  if (!sec || !sec.querySelectorAll) return;
  sec.querySelectorAll("[data-tl-filter]").forEach((b) => {
    const on = b.dataset.tlFilter === _filter;
    b.classList.toggle("is-on", on);
    b.setAttribute("aria-pressed", on ? "true" : "false");
  });
  const list = document.getElementById("tl-list");
  if (!list) return;
  list.dataset.filter = _filter;
  const keep = (row) => {
    if (_filter === "installed") return row.dataset.inst === "1";
    if (_filter === "updates") return row.dataset.status === "update";
    if (_filter === "problems") return row.classList.contains("is-problem");
    return true;
  };
  list.querySelectorAll(".tl-group").forEach((g) => {
    let any = false;
    g.querySelectorAll(".tl-row:not(.tl-skel)").forEach((row) => {
      const k = keep(row);
      row.classList.toggle("is-filtered", !k);
      any = any || k;
    });
    g.classList.toggle("is-filtered", _filter !== "all" && !any);
    if (_filter !== "all" && any && g.tagName === "DETAILS") g.open = true;
  });
  const empty = document.getElementById("tl-filter-empty");
  if (empty) {
    const shown = list.querySelectorAll(".tl-row:not(.tl-skel):not(.is-filtered)").length;
    empty.hidden = _filter === "all" || shown > 0;
    empty.textContent = _filter === "updates" ? "No updates. Everything is on the version LanEx was tested with."
      : _filter === "problems" ? "No problems. Every component LanEx needs is ready."
      : "Nothing installed yet.";
  }
}

// Summary strip: counts the rows that matter. The local toolchain only counts
// when the Local tools engine is selected (with Container, the image has it).
function paintSummary() {
  const sum = document.getElementById("tools-summary");
  const list = document.getElementById("tl-list");
  if (!sum || !list || !list.querySelectorAll) return;
  const rows = Array.from(list.querySelectorAll(".tl-row:not(.tl-skel)"))
    .filter((r) => state.runMode === "local" || !r.closest("#local-tools-card"));
  const counted = rows.filter((r) => r.dataset.status !== "off");
  const problems = rows.filter((r) => r.classList.contains("is-problem"));
  const updates = rows.filter((r) => r.dataset.status === "update");
  const busy = rows.filter((r) => r.dataset.status === "busy");
  const ready = counted.filter((r) => ["ready", "image"].includes(r.dataset.status));
  let tone, title, sub = "", jump = "";
  if (problems.length) {
    tone = "fail";
    title = problems.length + (problems.length === 1 ? " component needs" : " components need") + " attention";
    sub = problems.map((r) => (r.querySelector(".tl-name")?.dataset.name || r.querySelector(".tl-name")?.textContent) || "").filter(Boolean).slice(0, 4).join(", ");
    jump = "<button class='btn btn-sm btn-primary' data-tl-jump='" + esc(problems[0].id) + "'>Show</button>";
  } else if (updates.length) {
    tone = "warn";
    title = updates.length + (updates.length === 1 ? " update" : " updates") + " available";
    sub = "LanEx never updates on its own. Updates install the version this release was tested with.";
    jump = "<button class='btn btn-sm btn-ghost' data-tl-jump='" + esc(updates[0].id) + "'>Show</button>";
  } else {
    tone = "pass";
    title = "All " + ready.length + " components ready";
    sub = "Installed on the versions this LanEx release was tested with.";
  }
  if (busy.length) sub = busy.length + " installing. Progress is in the Logs panel. " + sub;
  sum.innerHTML =
    "<div class='tl-sum is-" + tone + "'>" +
      "<span class='tl-sum-dot'></span>" +
      "<div class='tl-sum-text'><strong>" + esc(title) + "</strong>" + (sub ? "<span>" + esc(sub) + "</span>" : "") + "</div>" +
      jump +
    "</div>";
  sum.querySelector("[data-tl-jump]")?.addEventListener("click", (e) => {
    const id = e.currentTarget.dataset.tlJump;
    if (problems.length) setFilter("problems");
    else if (updates.length) setFilter("updates");
    revealRow(id);
  });
  // Filter counts
  const n = { all: rows.length, installed: rows.filter((r) => r.dataset.inst === "1").length, updates: updates.length, problems: problems.length };
  document.querySelectorAll("#sec-tools [data-tl-filter]").forEach((b) => {
    const c = b.querySelector(".tl-count");
    if (c) c.textContent = String(n[b.dataset.tlFilter] ?? "");
  });
}

function revealRow(id) {
  const row = id && document.getElementById(id);
  if (!row) return false;
  const det = row.closest("details.tl-group");
  if (det) det.open = true;
  row.scrollIntoView({ block: "center", behavior: "smooth" });
  row.classList.add("is-flash");
  setTimeout(() => row.classList.remove("is-flash"), 1600);
  return true;
}

// go("tools", {item}) — item is a component key ("docker", "image", "sky130A",
// "klayout", "iverilog", "gds3d", "yosys"…) or a row id.
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
    "<button class='btn btn-sm btn-ghost tl-act' id='runtime-pull-cancel' " +
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
// Two rows (engine, image) plus, under them, whatever the user must act on:
// the remedy card when the engine isn't usable, the live pull while
// downloading. Both engines keep one-click Install / Remove (in the menu), so a
// user can e.g. drop Docker and switch to Podman at will.
function engineRowsHtml(c) {
  const d = c.docker || {}, p = c.podman || {};
  const verBad = c.version && c.min_version && c.version_ok === false;
  const engName = c.engine === "podman" ? "Podman" : c.engine === "docker" ? "Docker" : (d.present ? "Docker" : p.present ? "Podman" : "Docker or Podman");
  const engKey = c.engine || (d.present ? "docker" : p.present ? "podman" : "");
  let status, chip = "", action, warn = "";
  const menu0 = [];
  if (c.ready) {
    status = verBad ? "update" : "ready";
    action = checkAct();
    if (verBad) warn = esc(engName + " " + shortVersion(c.version) + " is older than LibreLane's recommended " + c.min_version + ". Update it with your package manager.");
    if (c.sg_wrap) chip = "Ready (via group)";
  } else if (c.available) {
    status = "broken"; chip = "Not running";
    action = act("Repair", "tl-repair", "", { primary: true, title: "Run the first fix listed below" });
    menu0.push(menuItem("Check again", "", "id='btn-runtime-recheck'"));
  } else {
    status = "missing";
    action = act("Install", "engine-install", "data-engine='docker'", { primary: true, title: "Installs Docker with the system package manager, then downloads the image" });
  }
  const menu = menu0;
  const engItem = (key, present, label) => present
    ? menuItem("Remove " + label, "engine-remove", "data-engine='" + key + "'", { danger: true })
    : menuItem("Install " + label, "engine-install", "data-engine='" + key + "'");
  if (c.available || c.ready) { menu.push(engItem("docker", d.present, "Docker")); menu.push(engItem("podman", p.present, "Podman")); }
  else menu.push(engItem("podman", p.present, "Podman instead"));
  const engine = rowHtml({
    id: "tl-engine", name: esc(engName), status, chip, inst: !!(c.available || c.ready),
    purpose: "Runs the LibreLane image, which holds every EDA tool the flow uses.",
    warn, have: shortVersion(c.version), want: c.min_version ? c.min_version + "+" : "", wantLabel: "needs", size: "",
    action, menu,
  });

  // The image row.
  const imgTag = (String(c.image || "").split("@")[0].split(":").pop()) || "";
  const dig = (String(c.image || "").split("@")[1]) || "";
  let iStatus, iChip = "", iAction, iWarn = "";
  if (_pull.active || c.pulling) {
    iStatus = "busy"; iChip = "Downloading";
    iAction = act("Downloading…", "", "disabled");
  } else if (c.image_present) {
    iStatus = c.image_custom ? "custom" : "ready";
    iAction = checkAct();
    if (c.image_custom) iWarn = "Not the image this LanEx release was tested with" + (c.image_tested_digest ? " (" + esc(shortHash(c.image_tested_digest)) + ")" : "") + ". Results may differ.";
  } else {
    iStatus = "missing";
    iAction = c.ready
      ? act("Download", "", "id='btn-pull-image'", { primary: true, title: "One download gives you every EDA tool, version-matched" })
      : act("Download", "", "disabled title='Needs a working container engine first'");
  }
  const image = rowHtml({
    id: "tl-image", name: "LibreLane image", status: iStatus, chip: iChip, inst: !!c.image_present,
    purpose: "Yosys, OpenROAD, Magic, KLayout, Netgen and the rest, version-matched to LibreLane" + (imgTag ? " " + esc(imgTag) : "") + ".",
    purposeTitle: c.image || "",
    warn: iWarn,
    have: c.image_present ? (imgTag + (dig ? " · " + shortHash(dig) : "")) : "",
    want: c.image_tested_digest ? shortHash(c.image_tested_digest) : "",
    size: c.image_present ? sizeStr(c.image_size_mb) : sizeStr(c.image_approx_mb, { approx: true }),
    action: iAction,
  });
  return engine + image;
}

function paintRuntimeCard(container) {
  const rows = document.getElementById("tl-engine-rows");
  const root = document.getElementById("runtime-card");
  const c = container || {};
  const d = c.docker || {}, p = c.podman || {};
  // The server reports an in-flight pull (c.pulling) so a reloaded page
  // re-attaches to it instead of offering a second Download button.
  if (c.ready && c.pulling && !_pull.active) resumePullUI();
  if (rows) {
    rows.innerHTML = engineRowsHtml(c);
    wireRowActions(rows);
  }
  if (!root) return;

  if (c.ready) {
    root.innerHTML = _pull.active ? pullProgressHtml() : "";
  } else if (c.available) {
    // A binary is installed but nothing is usable yet. The right remedy is
    // platform-shaped: on macOS the daemon only exists while Docker Desktop
    // (or the podman machine VM) is RUNNING — a one-click Start, not the old
    // Linux systemctl/usermod blob. Offer convenient, logout-free fixes.
    const mac = c.platform === "darwin";
    const canEnable = d.present && d.group_fixable;   // Linux + sg → no relogin
    let actions = "";
    if (mac) {
      if (d.present || d.app_present)
        actions += "<button class='btn btn-sm btn-primary' id='btn-start-docker'>Start Docker Desktop</button>";
      if (p.present)
        actions += "<button class='btn btn-sm btn-primary' id='btn-start-podman'>Start podman machine</button>";
    } else {
      if (canEnable)
        actions += "<button class='btn btn-sm btn-primary' id='btn-enable-docker'>Enable Docker for my user (no logout)</button>";
      if (d.present && !d.usable)
        actions += "<button class='btn btn-sm btn-primary' id='btn-start-docker'>Start Docker daemon</button>";
    }
    if (!p.present)
      actions += "<button class='btn btn-sm btn-ghost' id='btn-install-podman'>Install &amp; use Podman</button>";
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
      "Prefer native tools? Switch the top-bar engine to <strong>Local tools</strong> and use the <em>Local toolchain</em> group below.</p>" +
      "<div class='tl-fix-acts'>" +
      "<button class='btn btn-sm btn-primary' id='btn-install-docker'>Install Docker</button>" +
      "<button class='btn btn-sm btn-ghost' id='btn-install-podman'>Install Podman</button>" +
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
      "Container runs stop working until an engine is installed again (Install Docker or Podman from this row's menu)." }))) return;
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
// Tools shown in the Helpers group, so we skip them in the local-toolchain
// list to avoid duplicate rows.
const RECOMMENDED_KEYS = new Set(["iverilog", "graphviz", "gtkwave"]);

// Tools the container image can open as an interactive window/console with no
// run context (matches controller/container_tools._CONTAINER_TOOLS).
const CONTAINER_LAUNCHABLE = new Set(["magic", "klayout", "openroad", "netgen"]);

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
  for (const t of (info.tools || [])) {
    if (RECOMMENDED_KEYS.has(t.key)) continue;
    const inCont = !!(t.in_container && contReady);
    const busy = !!state.installJobs[t.key];
    let status, chip = "", warn = "";
    if (busy) status = "busy";
    else if (t.windows_only && !t.installed) {
      status = "broken"; chip = "Windows build";
      warn = "A Windows build is on the WSL PATH, but the Linux flow can't use it. Install the Linux build inside WSL, or use the container image.";
    } else if (t.installed) status = "ready";
    else if (inCont) status = "image";
    else status = local ? "missing" : "off";
    const card = document.createElement("div");
    card.className = "tl-row-host";
    card.dataset.key = t.key;
    const openBtn = inCont && CONTAINER_LAUNCHABLE.has(t.key)
      ? act("Open", "ct-open", "data-key='" + t.key + "'", { title: "Open the version-matched " + t.label + " from the LibreLane image" })
      : "";
    let action;
    if (busy) action = act("Installing…", "", "disabled");
    else if (!t.installed) action = buttonHtml(t, { inContainer: inCont }) || openBtn;
    else action = openBtn || checkAct();
    const menu = [];
    if (!t.installed && openBtn && action !== openBtn) menu.push(menuItem("Open from the image", "ct-open", "data-key='" + t.key + "'"));
    if (t.installed && !NO_REMOVE.has(t.key)) menu.push(menuItem("Uninstall " + t.label, "uninstall-btn", "data-key='" + t.key + "' data-label='" + esc(t.label) + "'", { danger: true }));
    card.innerHTML = rowHtml({
      id: "tl-local-" + t.key, name: esc(t.label), status, chip, warn, inst: !!t.installed,
      purpose: esc(t.what || ""), purposeTitle: t.installed ? "Path: " + (t.path || "—") : (t.container_only ? (t.install_recipe || "") : ""),
      have: t.installed ? shortVersion(t.version) || "installed" : (inCont ? "in container image" : ""),
      size: t.approx_mb ? sizeStr(t.approx_mb, { approx: true }) : "",
      action, menu,
    });
    root.appendChild(card);
  }
  wireRowActions(root);
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

// Shared per-row wiring: Check re-probes everything (the backend has no
// per-component self-test; one fresh probe is a few seconds).
function wireRowActions(scope) {
  if (!scope || !scope.querySelectorAll) return;
  scope.querySelectorAll(".tl-check").forEach((b) => {
    if (b._tlWired) return;
    b._tlWired = true;
    b.addEventListener("click", () => {
      b.disabled = true; b.textContent = "Checking…";
      renderTools(true);
    });
  });
}

// ------------------------------------------------------------------ PDKs
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

  const ciel = rowHtml({
    id: "tl-pdk-ciel", name: "ciel", inst: !cielMissing,
    purpose: "The PDK manager. Downloads the exact PDK version LibreLane asks for.",
    status: cielMissing ? "missing" : "ready",
    have: cielMissing ? "" : shortVersion(cielTool.version) || "installed",
    size: cielTool.approx_mb ? sizeStr(cielTool.approx_mb, { approx: true }) : "",
    action: cielMissing ? act("Install", "", "id='install-ciel-btn'", { primary: true }) : checkAct(),
  });

  const rows = Object.entries(catalog).map(([key, p]) => {
    const isInstalled = installed.has(key);
    const busy = !!state.installJobs["pdk:" + key];
    const v = versions[key] || {};
    const differs = isInstalled && v.installed && v.pinned && v.installed !== v.pinned;

    // Library list comes from the backend (ciel's authoritative metadata).
    // Libraries in `default_libraries` are pre-checked; the rest are opt-in.
    let libsHtml = "";
    if (!busy) {
      const unavailableReasons = normalizeUnavailableLibraries(p.unavailable_libraries);
      const unavailable = new Set(Object.keys(unavailableReasons));
      const allLibs = [...new Set([
        ...(Array.isArray(p.libraries) ? p.libraries : []),
        ...Object.keys(unavailableReasons),
      ])];
      const defLibs = new Set(Array.isArray(p.default_libraries) ? p.default_libraries : []);
      if (allLibs.length > 0) {
        const cbHtml = allLibs.map((id) => {
          const req = defLibs.has(id);
          if (unavailable.has(id)) {
            const reason = unavailableReasons[id] || "Not published for this release";
            return `<label class="tl-lib is-off"><input type="checkbox" class="lib-cb-${key}" value="${fmt.escape(id)}" disabled> ${fmt.escape(id)} <span>(${fmt.escape(reason)})</span></label>`;
          }
          return `<label class="tl-lib"><input type="checkbox" class="lib-cb-${key}" value="${fmt.escape(id)}" ${req ? "checked" : ""}> ${fmt.escape(id)}${req ? " <span>(starter)</span>" : ""}</label>`;
        }).join("");
        libsHtml = `<details class="tl-libs"><summary>Libraries (${allLibs.length})</summary>
          <div class="tl-libs-bar">
            <button class="btn btn-sm btn-ghost" data-lib-set="starter" data-pdk="${key}">Starter set</button>
            <button class="btn btn-sm btn-ghost" data-lib-set="all" data-pdk="${key}">All supported</button>
            ${(isInstalled && !p.note) ? `<button class="btn btn-sm btn-primary pdk-install-btn" data-pdk="${key}" title="Download the checked libraries">Install checked</button>` : ""}
          </div>
          <div class="tl-libs-list">${cbHtml}</div></details>`;
      }
    }

    const measured = (pdkInfo.installed_sizes_mb || {})[key];
    const size = isInstalled && measured != null ? sizeStr(measured)
      : (p.approx_gb != null ? "~" + p.approx_gb + " GB" : "");
    let status, chip = "", action, warn = "";
    if (busy) {
      status = "busy"; chip = "Installing";
      action = act("Cancel", "pdk-cancel-btn", "data-pdk='" + key + "'");
    } else if (isInstalled) {
      status = differs ? "custom" : "ready";
      if (differs) {
        chip = "Custom";
        warn = "This is not the version LibreLane " + esc((info.container && info.container.librelane_version) || "") +
          " pins. Container runs download the pinned one; Update installs it now.";
        action = act("Update", "pdk-install-btn", "data-pdk='" + key + "'", { primary: true, title: "Install the pinned version" });
      } else action = checkAct();
    } else if (p.note) {
      status = "off";
      action = "<span class='tl-act tl-act-none' title='" + esc(p.note) + "'>Not available</span>";
    } else {
      status = noneInstalled && (p.default_variant || p.recommended) ? "missing" : "off";
      action = act("Install", "pdk-install-btn", "data-pdk='" + key + "'", { primary: status === "missing" || !!p.recommended });
    }
    const facts = [p.foundry, p.node].filter(Boolean).map(esc).join(" · ");
    return rowHtml({
      id: "tl-pdk-" + key, inst: isInstalled, label: p.label || key,
      name: esc(p.label || key) + ((p.default_variant || p.recommended) ? " <span class='tl-tag' title='The variant LanEx uses by default for this PDK'>default</span>" : ""),
      purpose: esc(p.description || "") || facts, purposeTitle: [p.foundry, p.node].filter(Boolean).join(' · '),
      status, chip, warn,
      have: isInstalled ? (v.installed ? shortHash(v.installed) : "installed") : "",
      want: v.pinned ? shortHash(v.pinned) : "",
      size, action,
      menu: isInstalled && !busy ? [menuItem("Remove " + (p.label || key), "pdk-uninstall-btn", "data-pdk='" + key + "'", { danger: true })] : [],
      sub: libsHtml,
    });
  });
  drop.innerHTML = ciel + rows.join("");
  wireRowActions(drop);

  drop.querySelectorAll("[data-lib-set]").forEach((b) => b.addEventListener("click", () => {
    const all = b.dataset.libSet === "all";
    drop.querySelectorAll(".lib-cb-" + b.dataset.pdk + ":not(:disabled)").forEach((cb) => { cb.checked = all ? true : cb.defaultChecked; });
  }));

  // Wire PDK install buttons
  drop.querySelectorAll(".pdk-install-btn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const pdk = btn.dataset.pdk;
      const cbList = drop.querySelectorAll(".lib-cb-" + pdk);
      let libraries = null;
      if (cbList.length > 0) {
        libraries = [];
        cbList.forEach(cb => { if (cb.checked) libraries.push(cb.value); });
      }
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
    });
  });
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
  document.getElementById("install-ciel-btn")?.addEventListener("click", () =>
    installByKey("ciel"),
  );
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
      btn.textContent = "…";
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
    paintSummary();
    setFilter(_filter);
  } catch (ex) {
    console.error("Tools summary render failure:", ex);
  }
}

let _lastToolInfo = null;
// Engine switches change whether missing native tools matter; repaint the badge.
export function repaintToolBadge() {
  if (_lastToolInfo) paintToolBar(_lastToolInfo);
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
    return act(inContainer ? "Install locally" : "Install", "install-btn", "data-key='" + t.key + "'", { primary: !inContainer });
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
// (e.g. Docker needs a group/login), the engine row shows the next fix.
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
      toast.show(`${key} install started. Progress is in the Logs panel; this row updates when it finishes.`, "info");
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
