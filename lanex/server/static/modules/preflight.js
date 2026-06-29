// preflight.js — beginner-friendly "Ready to run?" checklist.
// One call verifies design + config + PDK + EDA tools and renders a clear
// pass/fail list with one-click jumps to fix whatever is missing.

import { api, fmt } from "./api.js";
import { state } from "./state.js";

let _last = null;

export function lastPreflight() {
  return _last;
}

// state: "ok" | "warn" | "bad". "warn" is a non-blocking caveat (e.g. a PDK
// that will download itself on the first run) — distinct from a hard ✗.
function row(state, label, detail, actionHtml) {
  const icon =
    state === "ok" ? "<span class='pf-ok'>✓</span>"
    : state === "warn" ? "<span class='pf-warn'>⚠</span>"
    : "<span class='pf-bad'>✗</span>";
  const cls = state === "ok" ? "pf-row-ok" : state === "warn" ? "pf-row-warn" : "pf-row-bad";
  return (
    "<div class='pf-row " + cls + "'>" +
    icon +
    "<span class='pf-label'>" + fmt.escape(label) + "</span>" +
    "<span class='pf-detail'>" + (detail || "") + "</span>" +
    (actionHtml || "") +
    "</div>"
  );
}

// Fetch + paint the checklist. Returns the preflight result object.
export async function renderPreflight() {
  const root = document.getElementById("preflight");
  if (!root) return null;
  root.innerHTML = "<div class='muted'>checking…</div>";
  let pf;
  try {
    pf = await api.preflight(state.selectedPdk, state.selectedScl, state.runMode);
  } catch (ex) {
    root.innerHTML = "<div class='pf-row pf-row-bad'><span class='pf-bad'>✗</span><span class='pf-label'>Check failed</span><span class='pf-detail'>" + fmt.escape(ex.message) + "</span></div>";
    return null;
  }
  _last = pf;

  const d = pf.design || {};
  const p = pf.pdk || {};
  const t = pf.tools || {};

  let html = "";
  html += row(
    d.ok ? "ok" : "bad",
    "Design + config",
    d.ok
      ? (d.config_file || "config") + " · " + (d.source_count || 0) + " source file(s)"
      : (d.dir ? "config / sources missing" : "no folder loaded"),
    d.ok ? "" : "<button class='btn btn-ghost pf-act' data-act='design'>Pick folder</button>",
  );
  // A PDK that LibreLane can fetch on its own (online, just not local yet) is a
  // warning, not a blocker — so don't show a hard ✗ while the banner says "All set".
  const pdkWillDownload = !p.ready && p.note;
  const pdkState = p.ready ? "ok" : pdkWillDownload ? "warn" : "bad";
  const pdkDetail = p.ready
    ? p.pdk + (p.scl ? " / " + p.scl : "")
    : pdkWillDownload
      ? fmt.escape(p.note)
      : p.pdk ? "not installed" : "none selected";
  html += row(
    pdkState,
    "PDK + standard cells",
    pdkDetail,
    p.ready || pdkWillDownload ? "" : "<button class='btn btn-ghost pf-act' data-act='tools'>Install PDK</button>",
  );
  // Engine row — container mode needs only Docker/Podman; local mode needs the
  // six native EDA tools.
  if (t.mode === "container") {
    const eng = t.engine || {};
    const detail = eng.available
      ? eng.engine + " ready" + (eng.image_present ? " · image pulled" : " · image not pulled yet")
      : "no Docker or Podman found";
    html += row(
      t.ok ? "ok" : "bad",
      "Container engine",
      detail,
      t.ok ? "" : "<button class='btn btn-ghost pf-act' data-act='tools'>Open Tools</button>",
    );
  } else {
    const tools = t.tools || [];
    const toolDetail = tools
      .map((x) => (x.installed ? "" : "<span class='pf-missing'>" + fmt.escape(x.label) + "</span>"))
      .filter(Boolean)
      .join(" ");
    html += row(
      t.ok ? "ok" : "bad",
      "EDA tools",
      t.ok ? tools.length + " tool(s) ready" : "missing: " + (toolDetail || "—"),
      t.ok ? "" : "<button class='btn btn-ghost pf-act' data-act='tools'>Open Tools</button>",
    );
  }

  const banner = pf.ready
    ? "<div class='pf-banner pf-banner-ok'>All set — press ▶ Run flow.</div>"
    : "<div class='pf-banner pf-banner-bad'>" + pf.blockers.length + " thing(s) to fix before a run will finish.</div>";

  root.innerHTML = banner + html;

  // Wire the fix buttons to jump to the right place.
  root.querySelectorAll(".pf-act").forEach((b) => {
    b.addEventListener("click", () => {
      const act = b.dataset.act;
      if (act === "tools") {
        document.querySelector('.side-tab[data-tab="tools"]')?.click();
      } else if (act === "design") {
        document.getElementById("design-dir-input")?.focus();
      }
    });
  });
  return pf;
}
