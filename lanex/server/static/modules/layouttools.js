// layouttools.js — open a run in a desktop layout tool (KLayout, Magic, GDS3D,
// OpenROAD GUI), choosing where it runs.
//
// For each tool we merge host availability (desktop-tools) with container
// availability (container-tools + a reachable display):
//   1. the version-matched CONTAINER when it can (preferred: the tool is
//      guaranteed compatible with the PDK techfiles), else
//   2. the INSTALLED host tool, else
//   3. say it isn't installed and go to the Tools tab.
// GDS3D is host-only (not in the image); OpenROAD is container-only. Both
// launch paths open the PDK's layer colours and load the run's DRC/XOR markers.

import { api } from "./api.js";
import { toast } from "./toast.js";

const LABEL = { klayout: "KLayout", magic: "Magic", gds3d: "GDS3D", openroad: "OpenROAD GUI" };

// { tool: { where: "container"|"host"|"nodisplay"|"install", title } }
export async function toolRoutes() {
  let desktop = [];
  let container = { engine_ready: false, display: {}, tools: [] };
  try { desktop = (await api.desktopTools()).tools || []; } catch (_e) {}
  try { container = (await api.containerTools()) || container; } catch (_e) {}
  const contKeys = new Set((container.tools || []).map((t) => t.key));
  const displayOk = !!(container.display && container.display.ok);
  const out = {};
  for (const key of Object.keys(LABEL)) {
    const hostOk = desktop.some((t) => t.key === key && t.available);
    const inCont = !!container.engine_ready && contKeys.has(key);
    if (inCont && displayOk) out[key] = { where: "container", title: "Opens in the version-matched LibreLane container" };
    else if (hostOk) out[key] = { where: "host", title: "Opens your installed " + LABEL[key] };
    // Not disabled: the remedy (the exact WSLg / XQuartz fix) lives in display.reason.
    else if (inCont) out[key] = { where: "nodisplay", title: (container.display && container.display.reason) || "no display reachable" };
    else out[key] = { where: "install", title: LABEL[key] + " is not installed; set it up in the Tools tab" };
  }
  return out;
}

// Open one run in one viewer. `path` (run-relative) opens a specific file, e.g.
// a stage's .odb in OpenROAD; without it the tool gets the run's final GDS/ODB.
export async function launchTool(tool, tag, { path } = {}) {
  const routes = await toolRoutes();
  const r = routes[tool] || { where: "install" };
  const label = LABEL[tool] || tool;
  if (r.where === "install") {
    toast.show(label + " isn't installed yet. Set it up in the Tools tab.", "warn");
    document.querySelector('.side-tab[data-tab="tools"]')?.click();
    return;
  }
  if (r.where === "nodisplay") {
    // Sticky: the remedy is a multi-step command the user must be able to read.
    toast.show("No display is reachable for windows from the container. " + (r.title || ""), "warn", 0);
    return;
  }
  try {
    let res;
    if (r.where === "container") {
      res = await api.openInContainerTool(tool, tag, path);
      if (res && res.ok) toast.show("Opening " + (res.label || label) + (res.hint ? " (" + res.hint + ")" : "") +
        ". The window can take a few seconds to appear.", "success");
    } else {
      res = await api.openInTool(tool, tag, path, true);
      if (res && res.ok) toast.show("Opening " + (res.label || label) + ". The window can take a few seconds to appear.", "success");
      // Provenance: tech files resolved from a different PDK root than the run's.
      if (res && res.ok && res.tech_note) toast.show(res.tech_note, "warn");
    }
    if (!(res && res.ok)) toast.show((res && (res.error || res.need)) || ("Couldn't open " + label), "warn");
  } catch (ex) {
    toast.show("Couldn't open " + label + ": " + (ex.message || ex), "error");
  }
}

// Open one run in one viewer from anywhere (e.g. Verify's "Open in KLayout").
export async function openRunInTool(tool, tag) {
  await launchTool(tool, tag);
}
