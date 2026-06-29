// stepoutput.js — click a node on the flow graph (or a "log" button on the
// Verify tab) to inspect that step's log + reports.
//
// Output renders INLINE into the Pipeline tab's lower console ("Step Output"
// tab) — not a modal — so the user can keep the flow graph in view and there is
// no extra dialog to dismiss. The run is the live/just-finished one by default;
// for a past run picked on the Runs tab we pass its tag.

import { api } from "./api.js";
import { state } from "./state.js";
import { renderFileText, fileActionsHtml, wireFileActions } from "./fileview.js";
import { renderLogs } from "./logs.js";

function esc(s) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(s).replace(/[&<>"']/g, (c) => map[c] || c);
}

// Bring the Step Output console into view: Pipeline tab + the stepout console
// tab. Both are best-effort (clicks are no-ops if already active).
function focusConsole() {
  document.querySelector('.side-tab[data-tab="pipeline"]')?.click();
  document.querySelector('.side-pane-tab[data-itab="stepout"]')?.click();
}

async function showStep(stepId, opts = {}) {
  const root = document.getElementById("step-output");
  if (!root) return;
  if (opts.focus !== false) focusConsole();
  // Also position the full Live Logs at this step's instantiation point, so the
  // user can switch to the Live Logs tab and explore the surrounding output
  // already scrolled to where this tool started (issue #8b). No-op if the live
  // stream doesn't contain this step (e.g. inspecting an older run).
  try { renderLogs.jumpToStep(stepId); } catch (_e) { /* non-fatal */ }

  root.innerHTML =
    "<div class='so-head'><span class='so-title'>" + esc(stepId) + "</span>" +
    "<span class='so-badge muted'>loading…</span></div>" +
    "<pre>loading…</pre>";

  const tag = state.status?.running ? null : (state.selectedRunTag || null);
  let r;
  try {
    r = await api.runStepLog(stepId, tag);
  } catch (ex) {
    root.querySelector("pre").textContent = "Could not load step output: " + (ex.message || ex);
    return;
  }

  if (!r || !r.ok) {
    const live = state.stepStatuses?.[stepId];
    root.innerHTML =
      "<div class='so-head'><span class='so-title'>" + esc(stepId) + "</span></div>" +
      "<pre>" + esc((r && r.reason ? r.reason : "No output for this step") +
        (live ? "\n\nLive status: " + live : "\n\n(step may not have run yet)")) + "</pre>";
    return;
  }

  const badge = r.completed
    ? "<span class='so-badge' style='color:var(--pass)'>completed</span>"
    : "<span class='so-badge' style='color:var(--warn)'>" +
      esc(state.stepStatuses?.[stepId] || "no state_out") + "</span>";
  // Reports as download/locate rows (run-relative path = <step dir>/<report>).
  const reports = (Array.isArray(r.reports) && r.reports.length)
    ? "<div class='so-reports'><div class='muted'>reports:</div>" +
      r.reports.map((p) => {
        const rel = (r.dir ? r.dir + "/" : "") + p;
        return "<div class='report-row'><span class='rname'>" + esc(p) + "</span>" +
          fileActionsHtml(tag, rel) + "</div>";
      }).join("") + "</div>"
    : "";
  root.innerHTML =
    "<div class='so-head'><span class='so-title'>" + esc(stepId) + "</span>" + badge + "</div>" +
    reports +
    "<div class='so-log'></div>";
  wireFileActions(root);
  // The log itself: find + download + locate via the shared file viewer.
  const logRel = (r.dir && r.log_file) ? r.dir + "/" + r.log_file : null;
  renderFileText(root.querySelector(".so-log"),
    (r.truncated ? "… (showing the tail of the log)\n\n" : "") + (r.log || "(empty log)"),
    { tag, path: logRel, emptyMsg: "(empty log)", scrollBottom: true });
}

// Public opener so other tabs (e.g. Verification Center) can show a step's log.
export function showStepOutput(stepId, tag) {
  if (tag) { try { state.selectedRunTag = tag; } catch (_e) {} }
  showStep(stepId);
}

export function setupStepOutput() {
  document.addEventListener("g:step_selected", (e) => {
    const id = e.detail && e.detail.id;
    if (id) showStep(id);
  });
}
