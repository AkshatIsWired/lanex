// verify.js — Verification Center (Phase 1.A). A stage-organized cockpit over
// the signoff data the run already produced, with a single tape-out verdict.
import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { renderFileText, fileActionsHtml, wireFileActions } from "./fileview.js";
import { renderTimingPaths } from "./timing.js";
import { gatherRunsScoped, getRunScope, runOptionsHtml, scopeToggleHtml, wireScopeToggle, ensureActiveDesignFor } from "./runscope.js";
import { jumpBarHtml, wireJump } from "./jumpnav.js";
import { icon } from "./icons.js";

// Mount the jump bar as a direct child of the verify SECTION, just before
// #verify-body, so `position: sticky` keeps it pinned across the whole tab
// (verify-body, the timing-paths card, and the advisor card are all siblings).
// Idempotent: replaces any previous bar on re-render.
function mountSectionJump(verifyBody, jumpHtml) {
  const section = verifyBody.closest(".section") || verifyBody.parentElement;
  if (!section) { verifyBody.insertAdjacentHTML("afterbegin", jumpHtml); wireJump(verifyBody); return; }
  const old = section.querySelector(":scope > .section-jump");
  if (old) old.remove();
  verifyBody.insertAdjacentHTML("beforebegin", jumpHtml);
  wireJump(section);
}

// tag -> run row (carries _design) for the active picker.
let _runIndex = {};

const STAGE_LABELS = {
  rtl: "RTL — lint",
  synth: "Synthesis — equivalence & checks",
  timing: "Timing — STA",
  physical: "Physical — DRC / LVS / antenna / XOR",
  manufacturability: "Manufacturability",
};

const DOT = { pass: "pf-pass", fail: "pf-fail", warn: "pf-warn", absent: "pf-absent" };

export async function renderVerify(tag) {
  const root = document.getElementById("verify-body");
  if (!root) return;
  root.innerHTML = "<p class='muted'>Loading verification…</p>";

  // Run picker — verify whichever run the user chooses (default: latest). Scoped
  // by the global run-scope pref so runs from other designs are reachable too.
  let runs = [];
  try { runs = await gatherRunsScoped(); } catch (_e) {}
  _runIndex = {};
  for (const r of runs) _runIndex[r.tag] = r;
  if (getRunScope() === "design") state.runs = runs;
  const want = tag || state.selectedRunTag || (runs[0] && runs[0].tag) || "";
  await ensureActiveDesignFor(_runIndex[want]);

  let rep;
  try {
    rep = await api.verify(want);
  } catch (ex) {
    root.innerHTML = "<div class='empty'><h3>No run to verify</h3>" +
      "<p>Run the flow once, then come back to see the signoff verdict.</p></div>";
    return;
  }

  // Tally check states across all stages for an at-a-glance summary.
  const tally = { pass: 0, warn: 0, fail: 0, absent: 0 };
  for (const stage of Object.values(rep.stages || {}))
    for (const c of stage.checks || []) tally[c.status] = (tally[c.status] || 0) + 1;

  const picker = runs.length
    ? "<div class='verify-bar'><label>Run <select id='verify-run'>" +
      runOptionsHtml(runs, rep.tag, fmt.escape) +
      "</select></label>" +
      scopeToggleHtml("verify-run-scope") +
      "<span class='verify-tally'>" +
      "<span class='vt vt-pass'>" + tally.pass + " pass</span>" +
      "<span class='vt vt-warn'>" + tally.warn + " warn</span>" +
      "<span class='vt vt-fail'>" + tally.fail + " fail</span>" +
      "<span class='vt vt-absent'>" + tally.absent + " no-data</span></span></div>"
    : "";

  const v = rep.verdict || { ready: false, incomplete: false, blockers: [], warnings: [] };
  // Three states, never two. A real failing check wins (red); otherwise an
  // incomplete run (a gating signoff stage produced no data) is neutral/amber and
  // must NOT read as green; only a complete, failure-free run is green "ready".
  let vClass, vTitle;
  if (v.blockers && v.blockers.length) { vClass = "verdict-fail"; vTitle = "Not tape-out ready"; }
  else if (v.incomplete) { vClass = "verdict-incomplete"; vTitle = "Signoff incomplete"; }
  else if (v.ready) { vClass = "verdict-pass"; vTitle = "Tape-out ready"; }
  else { vClass = "verdict-fail"; vTitle = "Not tape-out ready"; }
  const missing = (v.missing_stages || []).map((s) => STAGE_LABELS[s] || s);
  const banner =
    "<div class='verdict " + vClass + "'>" +
    "<span class='verdict-title'>" + vTitle + "</span>" +
    "<span class='muted'>run " + fmt.escape(rep.tag || "") + "</span>" +
    (v.incomplete && missing.length
      ? "<span class='muted'>— no signoff data for: " + fmt.escape(missing.join(", ")) + "</span>"
      : "") +
    (v.blockers && v.blockers.length
      ? "<div class='verdict-chips'>" + v.blockers.map((b) =>
          "<span class='chip chip-fail'>" + fmt.escape(b) + "</span>").join("") + "</div>"
      : "") +
    (v.warnings && v.warnings.length
      ? "<div class='verdict-chips'>" + v.warnings.map((b) =>
          "<span class='chip chip-warn'>" + fmt.escape(b) + "</span>").join("") + "</div>"
      : "") +
    "</div>";

  const cards = Object.entries(rep.stages || {}).map(([id, stage]) => {
    const rows = (stage.checks || []).map((c) => {
      const val = Object.values(c.values || {})[0];
      return "<div class='vcheck'>" +
        "<span class='pf " + (DOT[c.status] || "pf-absent") + "'></span>" +
        "<span class='vcheck-name'>" + fmt.escape(c.name) + "</span>" +
        (val !== undefined ? "<span class='vcheck-val'>" + fmt.escape(String(val)) + "</span>" : "") +
        (c.step_id ? "<button class='btn btn-ghost vcheck-log' data-step='" + fmt.escape(c.step_id) +
          "'>log</button>" : "") +
        (c.step_id ? "<button class='btn btn-ghost vcheck-rerun' data-step='" + fmt.escape(c.step_id) +
          "'>re-run</button>" : "") +
        "</div>";
    }).join("");
    return "<div class='vstage card'>" +
      "<div class='vstage-head'><span class='pf " + (DOT[stage.status] || "pf-absent") + "'></span>" +
      "<h3>" + fmt.escape(STAGE_LABELS[id] || id) + "</h3></div>" +
      (rows || "<p class='muted'>No data for this stage — this run didn't produce these metrics.</p>") + "</div>";
  }).join("");

  const jump = jumpBarHtml([
    { target: "verify-stages", label: "Stages" },
    { target: "timing-paths-card", label: "Timing paths" },
    { target: "verify-reports-card", label: "Reports" },
    { target: "verify-advisor", label: "Advisor" },
  ]);
  root.innerHTML = picker + banner + "<div class='vstages' id='verify-stages'>" + cards + "</div>" +
    "<div class='vreports card' id='verify-reports-card'><div class='card-body'>" +
    "<h3>Signoff reports</h3>" +
    "<p class='hint'>Every DRC / LVS / STA / antenna report this run wrote. View it (with find), download it, or locate it on disk.</p>" +
    "<div id='verify-reports'><p class='muted'>Loading reports…</p></div>" +
    "<div id='verify-report-view'></div>" +
    "</div></div>";
  // Mount the jump bar as a direct child of the SECTION (not #verify-body): the
  // jump targets (timing-paths-card, verify-advisor) are siblings of verify-body,
  // so a sticky bar inside verify-body would scroll away the moment you pass it.
  // As a child of the full-height section it stays pinned across the whole tab.
  mountSectionJump(root, jump);

  renderReports(root, rep.tag);
  renderTimingPaths(rep.tag);   // worst-paths table + slack histogram (sibling card)

  const runSel = root.querySelector("#verify-run");
  if (runSel) runSel.addEventListener("change", async () => {
    await ensureActiveDesignFor(_runIndex[runSel.value]);
    state.selectedRunTag = runSel.value;
    renderVerify(runSel.value);
  });
  wireScopeToggle("verify-run-scope", () => renderVerify());
  root.querySelectorAll(".vcheck-log").forEach((b) =>
    b.addEventListener("click", async () => {
      const mod = await import("./stepoutput.js");
      if (mod.showStepOutput) mod.showStepOutput(b.dataset.step, rep.tag);
    }));
  root.querySelectorAll(".vcheck-rerun").forEach((b) =>
    b.addEventListener("click", () => rerunCheck(b.dataset.step, rep.tag)));

  // Refresh the folded-in advisor (timing guidance) for this run's metrics.
  try {
    const view = await api.run(rep.tag);
    state.metrics = view.metrics?.values || state.metrics;
    const ta = await import("./timingAdvisor.js");
    ta.renderTimingAdvisor();
  } catch (_e) {}
}

// List the run's signoff report files with View / Download / Locate.
async function renderReports(root, tag) {
  const host = root.querySelector("#verify-reports");
  if (!host) return;
  let reps = [];
  try {
    const r = await api.runReports(state.designDir, tag);
    reps = (r && r.reports) || [];
  } catch (_e) {}
  if (!reps.length) {
    host.innerHTML = "<p class='muted'>No report files found for this run.</p>";
    return;
  }
  host.innerHTML = reps.map((rp) =>
    "<div class='report-row'>" +
    "<span class='chip rk'>" + fmt.escape(rp.kind || "report") + "</span>" +
    "<span class='rname' title='" + fmt.escape(rp.step || "") + "'>" + fmt.escape(rp.name) + "</span>" +
    "<button class='btn btn-ghost file-act' data-view='" + fmt.escape(rp.rel || "") + "' data-name='" +
      fmt.escape(rp.name) + "'>" + icon('eye',{size:13}) + " View</button>" +
    fileActionsHtml(tag, rp.rel) +
    "</div>").join("");
  wireFileActions(host);
  host.querySelectorAll("[data-view]").forEach((b) =>
    b.addEventListener("click", async () => {
      const view = root.querySelector("#verify-report-view");
      view.innerHTML = "<p class='muted'>Loading " + fmt.escape(b.dataset.name) + "…</p>";
      try {
        const resp = await fetch(api.runFileUrl(tag, b.dataset.view),
          { headers: { "X-Requested-With": "XMLHttpRequest" } });
        const text = await resp.text();
        renderFileText(view, text, { tag, path: b.dataset.view, title: b.dataset.name });
      } catch (ex) {
        view.innerHTML = "<p class='pill pill-fail'>Could not load: " + fmt.escape(ex.message || ex) + "</p>";
      }
    }));
}

async function rerunCheck(stepId, tag) {
  const { promptDialog } = await import("./dialog.js");
  const extra = await promptDialog({
    title: "Re-run " + stepId,
    label: "Optional overrides as KEY=VALUE, comma-separated (e.g. CLOCK_PERIOD=8):",
    defaultValue: "",
  });
  if (extra === null) return;
  const overrides = {};
  for (const pair of extra.split(",")) {
    const [k, val] = pair.split("=");
    if (k && k.trim() && val !== undefined) overrides[k.trim()] = val.trim();
  }
  const { toast } = await import("./toast.js");
  try {
    const res = await api.verifyRerun({
      step_id: stepId, overrides, run_tag: tag, run_mode: state.runMode,
    });
    if (res.ok) {
      toast.show("Re-running " + stepId + "… watch the Pipeline tab.", "success");
      document.querySelector('.side-tab[data-tab="pipeline"]')?.click();
    } else {
      toast.show("Re-run refused: " + (res.reason || "unknown"), "error");
    }
  } catch (ex) {
    toast.show("Re-run failed: " + (ex.message || ex), "error");
  }
}
