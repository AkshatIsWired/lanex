// dialog.js — in-app modal dialogs (replace native alert/confirm/prompt).
//
// Native dialogs are unstyled, block the event loop, can't show rich context,
// and are poor for touch/accessibility. These are themed, focus-trapped, Esc-to-
// cancel, and Promise-based. Zero dependency. Use:
//   await confirmDialog({ title, body, confirmText, danger })   → boolean
//   await promptDialog({ title, label, defaultValue })          → string|null
//   await alertDialog({ title, body })                          → void
//   await confirmTyped({ title, body, phrase })                 → boolean (must type phrase)

function _host() {
  let h = document.getElementById("app-dialog-host");
  if (!h) {
    h = document.createElement("div");
    h.id = "app-dialog-host";
    document.body.appendChild(h);
  }
  return h;
}

function _open({ title, bodyHtml, buttons, onMount }) {
  return new Promise((resolve) => {
    const host = _host();
    const prevFocus = document.activeElement;
    const back = document.createElement("div");
    back.className = "dlg-backdrop";
    back.setAttribute("role", "dialog");
    back.setAttribute("aria-modal", "true");
    back.innerHTML =
      "<div class='dlg' role='document'>" +
      "<div class='dlg-head'>" + (title || "") + "</div>" +
      "<div class='dlg-body'>" + (bodyHtml || "") + "</div>" +
      "<div class='dlg-actions'></div>" +
      "</div>";
    const actions = back.querySelector(".dlg-actions");
    const close = (val) => {
      try { back.remove(); } catch (_e) {}
      try { if (prevFocus && prevFocus.focus) prevFocus.focus(); } catch (_e) {}
      resolve(val);
    };
    (buttons || []).forEach((b) => {
      const btn = document.createElement("button");
      btn.className = "btn " + (b.cls || "btn-ghost");
      btn.textContent = b.label;
      btn.addEventListener("click", () => close(b.value));
      actions.appendChild(btn);
    });
    back.addEventListener("mousedown", (e) => { if (e.target === back) close(undefined); });
    host.appendChild(back);
    // Focus trap + Esc.
    const focusables = () => Array.from(back.querySelectorAll("button, input, textarea, [tabindex]"))
      .filter((el) => !el.disabled && el.offsetParent !== null);
    back.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(undefined); return; }
      if (e.key === "Tab") {
        const f = focusables();
        if (!f.length) return;
        const i = f.indexOf(document.activeElement);
        if (e.shiftKey && (i <= 0)) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && (i === f.length - 1)) { e.preventDefault(); f[0].focus(); }
      }
    });
    if (onMount) onMount(back, close);
    const f = focusables();
    if (f.length) f[f.length - 1].focus();
  });
}

function _esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Generic dialog for callers that render their own body (e.g. the provenance
// file viewer). Same overlay/focus-trap/Esc machinery as every other dialog.
// `wide` widens the box for file content. Resolves with the clicked button's
// value (undefined on Esc/backdrop).
export async function customDialog({ title = "", bodyHtml = "", buttons = null, wide = false, onMount = null } = {}) {
  return _open({
    title,
    bodyHtml,
    buttons: buttons || [{ label: "Close", value: true, cls: "btn-ghost" }],
    onMount: (back, close) => {
      // dlg-xl, NOT the folder browser's dlg-wide: that variant pins a 70vh
      // height and hides body overflow (its own file list scrolls instead),
      // which clipped these dialogs' content with no way to scroll to it.
      if (wide) back.querySelector(".dlg").classList.add("dlg-xl");
      if (onMount) onMount(back, close);
    },
  });
}

export async function confirmDialog({ title = "Are you sure?", body = "", confirmText = "Confirm", cancelText = "Cancel", danger = false } = {}) {
  const v = await _open({
    title: _esc(title),
    bodyHtml: body ? "<p>" + _esc(body) + "</p>" : "",
    buttons: [
      { label: cancelText, value: false, cls: "btn-ghost" },
      { label: confirmText, value: true, cls: danger ? "btn-warn" : "btn-primary" },
    ],
  });
  return v === true;
}

export async function choiceDialog({ title = "", body = "", choices = [] } = {}) {
  // choices: [{label, value, danger?}]. Returns the chosen value or undefined.
  return _open({
    title: _esc(title),
    bodyHtml: body ? "<p>" + _esc(body) + "</p>" : "",
    buttons: choices.map((c) => ({ label: c.label, value: c.value, cls: c.danger ? "btn-warn" : "btn-ghost" }))
      .concat([{ label: "Cancel", value: undefined, cls: "btn-ghost" }]),
  });
}

export async function alertDialog({ title = "Notice", body = "", html = false } = {}) {
  // `html: true` renders `body` as pre-built markup — the CALLER is then
  // responsible for escaping any untrusted text inside it (see about.js).
  await _open({
    title: _esc(title),
    bodyHtml: html ? String(body || "") : (body ? "<p>" + _esc(body) + "</p>" : ""),
    buttons: [{ label: "OK", value: true, cls: "btn-primary" }],
  });
}

// A multi-checkbox picker. `items` = [{ key, label, checked, hint }]. Returns the
// array of selected keys, or null on cancel. Used by the bundle download chooser.
export async function checklistDialog({ title = "", body = "", items = [], confirmText = "Download" } = {}) {
  let root = null;
  const rows = items.map((it) =>
    "<label class='dlg-check'><input type='checkbox' data-key='" + _esc(it.key) + "'" +
    (it.checked === false ? "" : " checked") + "/> <span>" + _esc(it.label) +
    (it.hint ? " <span class='muted'>— " + _esc(it.hint) + "</span>" : "") + "</span></label>").join("");
  const v = await _open({
    title: _esc(title),
    bodyHtml: (body ? "<p>" + _esc(body) + "</p>" : "") +
      "<div class='dlg-checklist'>" +
      "<div class='dlg-check-tools'><button type='button' class='btn btn-ghost dlg-check-all'>All</button>" +
      "<button type='button' class='btn btn-ghost dlg-check-none'>None</button></div>" +
      rows + "</div>",
    buttons: [
      { label: "Cancel", value: null, cls: "btn-ghost" },
      { label: confirmText, value: "__GO__", cls: "btn-primary" },
    ],
    onMount: (back) => {
      root = back;
      back.querySelector(".dlg-check-all").addEventListener("click", () =>
        back.querySelectorAll(".dlg-checklist input[type=checkbox]").forEach((c) => { c.checked = true; }));
      back.querySelector(".dlg-check-none").addEventListener("click", () =>
        back.querySelectorAll(".dlg-checklist input[type=checkbox]").forEach((c) => { c.checked = false; }));
    },
  });
  if (v !== "__GO__" || !root) return null;
  return Array.from(root.querySelectorAll(".dlg-checklist input[type=checkbox]"))
    .filter((c) => c.checked).map((c) => c.getAttribute("data-key"));
}

export async function promptDialog({ title = "", label = "", defaultValue = "" } = {}) {
  let inputEl = null;
  const v = await _open({
    title: _esc(title),
    bodyHtml: (label ? "<label class='dlg-label'>" + _esc(label) + "</label>" : "") +
      "<input class='dlg-input' type='text' value='" + _esc(defaultValue) + "'/>",
    buttons: [
      { label: "Cancel", value: null, cls: "btn-ghost" },
      { label: "OK", value: "__OK__", cls: "btn-primary" },
    ],
    onMount: (back, close) => {
      inputEl = back.querySelector(".dlg-input");
      inputEl.addEventListener("keydown", (e) => {
        if (e.key === "Enter") { e.preventDefault(); close("__OK__"); }
      });
      setTimeout(() => { inputEl.focus(); inputEl.select(); }, 0);
    },
  });
  if (v === "__OK__") return inputEl ? inputEl.value : "";
  return null;
}

// Destructive confirm that requires typing an exact phrase (e.g. the run tag).
export async function confirmTyped({ title = "Confirm", body = "", phrase = "", confirmText = "Delete" } = {}) {
  let inputEl = null, confirmBtn = null;
  const v = await _open({
    title: _esc(title),
    bodyHtml: (body ? "<p>" + _esc(body) + "</p>" : "") +
      "<label class='dlg-label'>Type <code>" + _esc(phrase) + "</code> to confirm:</label>" +
      "<input class='dlg-input' type='text' autocomplete='off'/>",
    buttons: [
      { label: "Cancel", value: false, cls: "btn-ghost" },
      { label: confirmText, value: "__GO__", cls: "btn-warn" },
    ],
    onMount: (back) => {
      inputEl = back.querySelector(".dlg-input");
      confirmBtn = back.querySelectorAll(".dlg-actions .btn")[1];
      if (confirmBtn) confirmBtn.disabled = true;
      inputEl.addEventListener("input", () => {
        if (confirmBtn) confirmBtn.disabled = (inputEl.value !== phrase);
      });
      setTimeout(() => inputEl.focus(), 0);
    },
  });
  return v === "__GO__" && inputEl && inputEl.value === phrase;
}
