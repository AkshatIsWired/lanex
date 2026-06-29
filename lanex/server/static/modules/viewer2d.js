// viewer2d.js — 2D layout view (Phase 4.1, revised). Shows the layout image the
// flow already rendered (KLayout.Render PNG) with pan/zoom. Tool launchers
// (KLayout/Magic/GDS3D/OpenROAD) live once on the Layout bar — see
// layouttools.js — so this module is just the rendered PNG + pan/zoom.
import { api, fmt } from "./api.js";
import { state } from "./state.js";

export async function renderViewer2d(tag) {
  const root = document.getElementById("viewer2d-body");
  if (!root) return;
  const t = tag || state.selectedRunTag;
  if (!t) { root.innerHTML = "<div class='empty'><h3>No run selected</h3><p>Pick a run above.</p></div>"; return; }
  state.selectedRunTag = t;
  root.innerHTML = "<p class='muted'>Loading layout…</p>";

  let imgs = [];
  try { imgs = (await api.runImages(t)).images || []; } catch (_e) {}

  // Tool launch buttons now live ONCE on the Layout bar (layouttools.js), not
  // duplicated per viewer — so this view is just the rendered image + pan/zoom.
  const img = imgs.find((i) => i.step === "final") || imgs[0];
  const imgHtml = img
    ? "<div class='v2d-stage' id='v2d-stage'><img class='v2d-img' id='v2d-img' src='" +
      api.runFileUrl(t, img.path) + "' alt='layout'/></div>" +
      "<p class='hint'>Scroll to zoom · drag to pan. This is the flow's rendered layout (" +
      fmt.escape(img.step || img.name) + "). For interactive layer editing, use the tool buttons above.</p>"
    : "<div class='empty'><h3>No rendered layout</h3><p>This run didn't produce a KLayout render. " +
      "Open the GDS in a desktop/container tool using the buttons above.</p></div>";

  root.innerHTML = imgHtml;
  wirePanZoom(root.querySelector("#v2d-img"));
}

function wirePanZoom(img) {
  if (!img) return;
  let scale = 1, tx = 0, ty = 0, down = false, px = 0, py = 0;
  const apply = () => { img.style.transform = "translate(" + tx + "px," + ty + "px) scale(" + scale + ")"; };
  img.style.transformOrigin = "0 0"; img.style.cursor = "grab";
  const stage = img.parentElement;
  stage.addEventListener("wheel", (e) => {
    e.preventDefault(); scale *= e.deltaY < 0 ? 1.15 : 1 / 1.15; scale = Math.max(0.1, Math.min(40, scale)); apply();
  }, { passive: false });
  stage.addEventListener("mousedown", (e) => { down = true; px = e.clientX; py = e.clientY; img.style.cursor = "grabbing"; });
  window.addEventListener("mouseup", () => { down = false; if (img) img.style.cursor = "grab"; });
  stage.addEventListener("mousemove", (e) => {
    if (!down) return; tx += e.clientX - px; ty += e.clientY - py; px = e.clientX; py = e.clientY; apply();
  });
}
