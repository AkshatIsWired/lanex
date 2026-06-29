// runmode.js — pick the engine the flow runs on.
//
//   • Container (recommended): shells out to `librelane --dockerized`. Every EDA
//     tool ships in the version-matched image, so the host only needs Docker or
//     Podman — no native openroad/magic/netgen installs.
//   • Local tools: drives LibreLane in-process against tools already on PATH.
//
// Step-by-step works in both modes: locally the in-process flow pauses between
// steps; in container mode the GUI runs one `--only <step>` invocation per step,
// resuming the same run tag (heavier — a container starts per step — but it
// genuinely steps, which advanced users want for inspecting intermediate state).

import { state } from "./state.js";

const KEY = "ll.runMode";

export function getRunMode() {
  return state.runMode === "local" ? "local" : "container";
}

export function setRunMode(mode) {
  const m = mode === "local" ? "local" : "container";
  state.runMode = m;
  try { localStorage.setItem(KEY, m); } catch (_e) {}
  paint();
}

export function toggleRunMode() {
  setRunMode(getRunMode() === "container" ? "local" : "container");
}

function paint() {
  const m = getRunMode();
  document.querySelectorAll(".engine-btn").forEach((b) =>
    b.classList.toggle("engine-btn-active", b.dataset.runmode === m),
  );
  // Step-by-step is available in both modes now. In container mode it costs a
  // container start per step, so note that in the tooltip but keep it enabled.
  const semi = document.querySelector('.mode-btn[data-mode="semi"]');
  if (semi) {
    semi.disabled = false;
    semi.classList.remove("mode-btn-disabled");
    semi.title = m === "container"
      ? "Run one step at a time in the container (a container starts per step). Inspect each result, then Resume."
      : "Pick the next step yourself; inspect each result before continuing.";
  }
}

export function setupRunMode() {
  try {
    const saved = localStorage.getItem(KEY);
    if (saved === "local" || saved === "container") state.runMode = saved;
  } catch (_e) {}
  document.querySelectorAll(".engine-btn").forEach((btn) => {
    btn.addEventListener("click", () => setRunMode(btn.dataset.runmode));
  });
  paint();
}
