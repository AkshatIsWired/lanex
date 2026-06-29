// fullscreen.js — promote any panel to a viewport overlay and back.
// Wires every `[data-fs-target="<id>"]` button: clicking toggles the
// `.panel-fullscreen` class on the target element, injects a floating ✕ exit
// button, and supports Esc. Dispatches `g:panel_fullscreen` so consumers (e.g.
// the waveform canvas) can re-fit themselves to the new size. No dependency.

let _wired = false;

function exit(target) {
  target.classList.remove("panel-fullscreen");
  target.querySelector(":scope > .panel-fs-exit")?.remove();
  document.dispatchEvent(new CustomEvent("g:panel_fullscreen", { detail: { id: target.id, on: false } }));
}

function enter(target) {
  target.classList.add("panel-fullscreen");
  if (!target.querySelector(":scope > .panel-fs-exit")) {
    const x = document.createElement("button");
    x.className = "btn btn-ghost panel-fs-exit";
    x.textContent = "✕ Exit fullscreen (Esc)";
    // position:fixed pins it to the viewport's top-right, so it can never be
    // pushed off-screen by the panel's padding/scroll (the old absolute+right:8px
    // hung half off the right edge). z-index above the overlay (9000).
    x.style.cssText = "position:fixed;top:12px;right:12px;z-index:9001";
    x.addEventListener("click", () => exit(target));
    target.appendChild(x);
  }
  document.dispatchEvent(new CustomEvent("g:panel_fullscreen", { detail: { id: target.id, on: true } }));
}

export function setupFullscreen() {
  if (_wired) return;
  _wired = true;
  // Delegate so buttons added after boot (dynamic panels) still work.
  document.addEventListener("click", (e) => {
    const btn = e.target.closest?.("[data-fs-target]");
    if (!btn) return;
    const target = document.getElementById(btn.dataset.fsTarget);
    if (!target) return;
    e.preventDefault();
    target.classList.contains("panel-fullscreen") ? exit(target) : enter(target);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const open = document.querySelector(".panel-fullscreen");
    if (open) { e.preventDefault(); exit(open); }
  });
}
