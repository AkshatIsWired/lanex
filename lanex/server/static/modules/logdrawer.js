// logdrawer.js — a closeable right-side log drawer for streamed output that
// happens OUTSIDE the Pipeline flow (tool/PDK/GDS3D installs, image pulls).
// Those used to only appear in the Pipeline console; now they pop a drawer on
// the right that the user can close, regardless of which tab they're on.
// Vanilla DOM, no dependency.

let _el = null;

function ensure() {
  if (_el) return _el;
  const d = document.createElement("div");
  d.className = "log-drawer";
  d.hidden = true;
  d.innerHTML =
    "<div class='log-drawer-head'>" +
    "<span class='log-drawer-title'>Logs</span>" +
    "<span class='log-drawer-spacer'></span>" +
    "<button class='btn btn-ghost log-drawer-btn' data-act='copy' title='Copy'>copy</button>" +
    "<button class='btn btn-ghost log-drawer-btn' data-act='clear' title='Clear'>clear</button>" +
    "<button class='btn btn-ghost log-drawer-btn' data-act='close' title='Close (Esc)'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button>" +
    "</div>" +
    "<pre class='log-drawer-body'></pre>";
  document.body.appendChild(d);
  const body = d.querySelector(".log-drawer-body");
  d.querySelector("[data-act='close']").addEventListener("click", () => { d.hidden = true; });
  d.querySelector("[data-act='clear']").addEventListener("click", () => { body.textContent = ""; });
  d.querySelector("[data-act='copy']").addEventListener("click", () => {
    try { navigator.clipboard.writeText(body.textContent); } catch (_e) {}
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !d.hidden) d.hidden = true; });
  _el = d;
  return d;
}

export function openDrawer(title) {
  const d = ensure();
  d.hidden = false;
  if (title) d.querySelector(".log-drawer-title").textContent = title;
}

export function appendDrawer(line) {
  if (line == null) return;
  const d = ensure();
  const body = d.querySelector(".log-drawer-body");
  const stick = body.scrollTop + body.clientHeight >= body.scrollHeight - 4;
  body.textContent += line + "\n";
  if (stick) body.scrollTop = body.scrollHeight;
}

export function clearDrawer() {
  if (_el) _el.querySelector(".log-drawer-body").textContent = "";
}

export function closeDrawer() {
  if (_el) _el.hidden = true;
}
