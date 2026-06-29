// manual.js — advanced manual control: reveal the exact CLI for the current
// Setup, and run allow-listed commands from the GUI with live output.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { collectRunPayload } from "./setup.js";

let _wired = false;

export function renderManual() {
  wireOnce();
  const out = document.getElementById("manual-output");
  if (out && !out.textContent) out.textContent = "(output will appear here)\n";
}

function wireOnce() {
  if (_wired) return;
  _wired = true;
  document.getElementById("btn-cli-reveal")?.addEventListener("click", revealCli);
  document.getElementById("btn-manual-run")?.addEventListener("click", runManual);
  document.getElementById("btn-manual-cancel")?.addEventListener("click", () =>
    api.manualCancel().catch(() => {}));
  document.getElementById("manual-cmd")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") runManual();
  });
}

async function revealCli() {
  const box = document.getElementById("cli-reveal");
  if (!box) return;
  box.innerHTML = "<p class='muted'>Building…</p>";
  let payload = {};
  try { payload = collectRunPayload(); } catch (_e) {}
  try {
    const r = await api.cliCommand({
      flow: "Classic",
      pdk: state.selectedPdk || undefined,
      scl: state.selectedScl || undefined,
      run_mode: state.runMode,
      tag: payload.tag || undefined,
      frm: payload.frm || undefined,
      to: payload.to || undefined,
      skip: payload.skip || [],
      overrides: payload.overrides || {},
    });
    box.innerHTML =
      cliBlock("Container (recommended)", r.container, r.recommended === "container") +
      cliBlock("Local tools", r.local, r.recommended === "local") +
      "<p class='hint'>Run from <code>" + fmt.escape(r.cwd || "your design dir") +
      "</code>. The GUI will show the run as soon as it appears under <code>runs/</code>.</p>";
    box.querySelectorAll(".cli-copy").forEach((b) =>
      b.addEventListener("click", () => {
        navigator.clipboard?.writeText(b.dataset.cmd).then(
          () => toast.show("Copied", "success"),
          () => toast.show("Copy failed — select and copy manually", "warn"));
      }));
  } catch (ex) {
    box.innerHTML = "<p class='pill pill-fail'>" + fmt.escape(ex.message) + "</p>";
  }
}

function cliBlock(label, cmd, recommended) {
  return "<div class='cli-block'>" +
    "<div class='cli-label'>" + fmt.escape(label) +
      (recommended ? " <span class='cc-badge'>recommended</span>" : "") + "</div>" +
    "<div class='cli-row'><code class='cli-cmd'>" + fmt.escape(cmd) + "</code>" +
    "<button class='btn btn-ghost cli-copy' data-cmd='" + fmt.escape(cmd) + "'>Copy</button></div></div>";
}

async function runManual() {
  const input = document.getElementById("manual-cmd");
  const out = document.getElementById("manual-output");
  const cmd = (input?.value || "").trim();
  if (!cmd) return;
  if (out) out.textContent += "\n$ " + cmd + "\n";
  try {
    await api.manualRun(cmd);
    setManualRunning(true);
  } catch (ex) {
    if (out) out.textContent += "✗ " + ex.message + "\n";
    if (out) out.scrollTop = out.scrollHeight;
  }
}

function setManualRunning(running) {
  const run = document.getElementById("btn-manual-run");
  const stop = document.getElementById("btn-manual-cancel");
  if (run) run.disabled = running;
  if (stop) stop.disabled = !running;
}

// Fold the manual_* SSE events into the output box. Called from app.js.
export function onManualEvent(ev) {
  const out = document.getElementById("manual-output");
  if (!out) return;
  if (ev.type === "manual_started") {
    setManualRunning(true);
  } else if (ev.type === "manual_line") {
    out.textContent += (ev.line || "") + "\n";
    out.scrollTop = out.scrollHeight;
  } else if (ev.type === "manual_done") {
    out.textContent += (ev.error ? "✗ " + ev.error : "exit code " + (ev.rc ?? "?")) + "\n";
    out.scrollTop = out.scrollHeight;
    setManualRunning(false);
  }
}
