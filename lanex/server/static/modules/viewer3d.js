// viewer3d.js — 3D layout view (revised). A "3D viewer" renders the physical
// layer stack of a GDS in true 3D — that's the job of external desktop projects
// (GDS3D, KLayout 2.5D, etc.), not the browser. So this tab launches the user's
// installed 3D viewer on the run's GDS rather than re-implementing one in-page.
import { state } from "./state.js";

export async function renderViewer3d(tag) {
  const root = document.getElementById("viewer3d-body");
  if (!root) return;
  const t = tag || state.selectedRunTag;
  if (!t) { root.innerHTML = "<div class='empty'><h3>No run selected</h3><p>Pick a run above.</p></div>"; return; }
  state.selectedRunTag = t;

  // The tool launchers (GDS3D / KLayout / OpenROAD) live ONCE on the Layout bar
  // above (layouttools.js); this panel just explains what 3D viewing is.
  root.innerHTML =
    "<div class='v3d-info card'><div class='card-body'>" +
    "<h3>3D layer view</h3>" +
    "<p>3D viewing renders the chip's physical layer stack (metals, vias, devices) " +
    "as a real 3D model. Use the tool buttons on the Layout bar above:</p>" +
    "<ul class='v3d-list'>" +
    "<li><strong>GDS3D</strong> — open-source OpenGL GDS viewer (uses the PDK layer " +
    "stack). Install it from the Tools tab; runs on your own machine only.</li>" +
    "<li><strong>KLayout</strong> — has a 2.5D view; also opens the GDS for inspection.</li>" +
    "</ul></div></div>";
}
