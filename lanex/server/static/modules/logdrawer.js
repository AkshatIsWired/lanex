// logdrawer.js — a closeable right-side log drawer for streamed output that
// happens OUTSIDE the Pipeline flow (tool/PDK/GDS3D installs, image pulls).
// Those used to only appear in the Pipeline console; now they pop a drawer on
// the right that the user can close — and reopen any time from the topbar
// "Logs" button, which appears once there's output and keeps the last stream
// around until cleared. Vanilla DOM, no dependency.

let _el = null;

function bodyText() {
  return _el ? _el.querySelector(".log-drawer-body").textContent : "";
}

// Reflect drawer state on the topbar toggle: show the button once there's
// output, mark it "activity" (a dot) while output exists but the drawer is
// closed, so the user knows logs are waiting behind it.
function syncBtn() {
  const btn = document.getElementById("logs-btn");
  if (!btn) return;
  const has = bodyText().trim().length > 0;
  const open = !!_el && !_el.hidden;
  btn.hidden = !has;
  btn.classList.toggle("has-activity", has && !open);
  btn.setAttribute("aria-pressed", open ? "true" : "false");
}

function wireBtn() {
  const btn = document.getElementById("logs-btn");
  if (!btn || btn._wired) return;
  btn._wired = true;
  btn.addEventListener("click", () => toggleDrawer());
}

function ensure() {
  wireBtn();
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
    "<button class='btn btn-ghost log-drawer-btn' data-act='close' title='Close (Esc) — reopen from the topbar Logs button'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button>" +
    "</div>" +
    "<pre class='log-drawer-body'></pre>";
  document.body.appendChild(d);
  const body = d.querySelector(".log-drawer-body");
  d.querySelector("[data-act='close']").addEventListener("click", () => { d.hidden = true; syncBtn(); });
  d.querySelector("[data-act='clear']").addEventListener("click", () => { body.textContent = ""; syncBtn(); });
  d.querySelector("[data-act='copy']").addEventListener("click", () => {
    try { navigator.clipboard.writeText(body.textContent); } catch (_e) {}
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !d.hidden) { d.hidden = true; syncBtn(); } });
  _el = d;
  return d;
}

export function openDrawer(title) {
  const d = ensure();
  d.hidden = false;
  if (title) d.querySelector(".log-drawer-title").textContent = title;
  syncBtn();
}

export function appendDrawer(line) {
  if (line == null) return;
  const d = ensure();
  const body = d.querySelector(".log-drawer-body");
  const stick = body.scrollTop + body.clientHeight >= body.scrollHeight - 4;
  body.textContent += line + "\n";
  if (stick) body.scrollTop = body.scrollHeight;
  syncBtn();
}

export function clearDrawer() {
  if (_el) { _el.querySelector(".log-drawer-body").textContent = ""; syncBtn(); }
}

export function closeDrawer() {
  if (_el) { _el.hidden = true; syncBtn(); }
}

// Reopen/close on demand (the topbar Logs button). Keeps whatever output the
// last install left, so a closed drawer is never a dead end.
export function toggleDrawer() {
  const d = ensure();
  d.hidden = !d.hidden;
  syncBtn();
  return !d.hidden;
}

export function hasContent() {
  return bodyText().trim().length > 0;
}

// Wire the topbar button at startup (before any install) so it's live the
// moment output arrives; it stays hidden until there's something to show.
export function setupLogDrawer() {
  wireBtn();
  syncBtn();
}
