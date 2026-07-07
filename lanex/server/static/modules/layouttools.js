// layouttools.js — ONE button per layout tool on the Layout bar, with a
// hierarchical open decision (no more KLayout/Magic listed three times).
//
// For each tool we merge host availability (desktop-tools) with container
// availability (container-tools + a reachable display). Clicking a button:
//   1. opens it in the version-matched CONTAINER if that's available (preferred —
//      the tool is guaranteed compatible with the PDK techfiles), else
//   2. opens the INSTALLED host tool, else
//   3. tells the user it isn't installed and jumps to the Tools tab.
//
// GDS3D is host-only (not in the image); OpenROAD is container-only. The merge
// makes each appear exactly once and routes to whichever backend can serve it.

import { api, fmt } from "./api.js";
import { toast } from "./toast.js";

// Layout-relevant tools, in display order. Netgen (LVS) deliberately omitted —
// it's a signoff console, not a layout viewer.
const TOOLS = [
  { key: "klayout", label: "KLayout" },
  { key: "magic", label: "Magic" },
  { key: "gds3d", label: "GDS3D" },
  { key: "openroad", label: "OpenROAD GUI" },
];

export async function renderLayoutTools(host, tag) {
  if (!host) return;
  if (!tag) { host.innerHTML = ""; return; }

  let desktop = [];
  let container = { engine_ready: false, display: {}, tools: [] };
  try { desktop = (await api.desktopTools()).tools || []; } catch (_e) {}
  try { container = (await api.containerTools()) || container; } catch (_e) {}

  const hostByKey = {};
  for (const t of desktop) hostByKey[t.key] = t;
  const contKeys = new Set((container.tools || []).map((t) => t.key));
  const contReady = !!container.engine_ready && !!(container.display && container.display.ok);

  const cells = TOOLS.map((t) => {
    const hostTool = hostByKey[t.key];
    const hostOk = !!(hostTool && hostTool.available);
    const contOk = contReady && contKeys.has(t.key);
    let where, title, disabled = "";
    if (contOk) { where = "container"; title = "Open in the version-matched container (recommended)"; }
    else if (hostOk) { where = "host"; title = "Open with your installed " + t.label; }
    else if (container.engine_ready && contKeys.has(t.key) && !(container.display && container.display.ok)) {
      where = "nodisplay"; title = (container.display && container.display.reason) || "no display reachable"; disabled = " disabled";
    }
    else { where = "install"; title = t.label + " isn't installed — click to set it up in Tools"; }
    const badge = { container: "container", host: "installed", nodisplay: "no display", install: "not installed" }[where];
    return "<button class='btn btn-ghost layout-tool' data-tool='" + fmt.escape(t.key) +
      "' data-where='" + where + "'" + disabled + " title='" + fmt.escape(title) + "'>" +
      fmt.escape(t.label) + " <span class='layout-tool-badge lt-" + where + "'>" + badge + "</span></button>";
  }).join("");

  host.innerHTML = "<span class='muted'>Open this run in:</span> " + cells;
  host.querySelectorAll(".layout-tool").forEach((b) =>
    b.addEventListener("click", () => launch(b, tag)));
}

async function launch(btn, tag) {
  const tool = btn.dataset.tool;
  const where = btn.dataset.where;
  if (where === "install") {
    toast.show("Install " + tool + " from the Tools tab first.", "warn");
    document.querySelector('.side-tab[data-tab="tools"]')?.click();
    return;
  }
  if (where === "nodisplay") {
    toast.show("No display reachable for the container GUI. " + (btn.title || ""), "warn");
    return;
  }
  btn.disabled = true;
  try {
    let r;
    if (where === "container") {
      r = await api.openInContainerTool(tool, tag);
      if (r && r.ok) toast.show("Launched " + (r.label || tool) + " in the container" +
        (r.hint ? " — " + r.hint : "") + ". The window may take a few seconds.", "success");
    } else {
      // Host launch honours the Layout bar's "PDK layer colours" toggle.
      const colorsEl = document.getElementById("layout-pdk-colors");
      const useTech = colorsEl ? colorsEl.checked : true;
      r = await api.openInTool(tool, tag, undefined, useTech);
      if (r && r.ok) toast.show("Launched " + (r.label || tool) +
        (tool !== "gds3d" ? (useTech && r.used_tech ? " (PDK colours)" : " (default view)") : ""), "success");
      // Provenance: tech files resolved from a different PDK root than the run's.
      if (r && r.ok && r.tech_note) toast.show(r.tech_note, "warn");
    }
    if (!(r && r.ok)) {
      const msg = (r && (r.error || r.need)) || "could not launch";
      toast.show(msg, "warn");
    }
  } catch (ex) {
    toast.show("Launch failed: " + (ex.message || ex), "error");
  }
  btn.disabled = false;
}
