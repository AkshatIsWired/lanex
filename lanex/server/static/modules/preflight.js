// preflight.js — beginner-friendly "Ready to run?" checklist.
// One call verifies design + config + PDK + EDA tools and renders a clear
// pass/fail list with one-click jumps to fix whatever is missing.

import { api, fmt } from "./api.js";
import { state } from "./state.js";

let _last = null;

export function lastPreflight() {
  return _last;
}

// One checkpoint on the trace. state: "ok" | "warn" | "bad" | "wait". "warn"
// is a non-blocking caveat (a PDK that downloads itself on the first run).
// The state is said in words too (pf-state), never by colour alone.
const STATE_WORD = { ok: "Ready", warn: "Heads-up", bad: "Needs fixing", wait: "Checking" };
function row(state, label, detail, actionHtml) {
  return (
    "<div class='pf-node is-" + state + "'>" +
    "<span class='pf-via' aria-hidden='true'></span>" +
    "<span class='pf-state'>" + STATE_WORD[state] + "</span>" +
    "<span class='pf-label'>" + fmt.escape(label) + "</span>" +
    "<span class='pf-detail'>" + (detail || "") + "</span>" +
    (actionHtml || "") +
    "</div>"
  );
}

function plural(n, word) {
  return n + " " + word + (n === 1 ? "" : "s");
}

function verdict(text, kind) {
  const v = document.getElementById("pf-verdict");
  if (!v) return;
  v.textContent = text;
  v.className = "launch-verdict" + (kind ? " is-" + kind : "");
}

// Fetch + paint the checklist. Returns the preflight result object.
export async function renderPreflight() {
  const root = document.getElementById("preflight");
  if (!root) return null;
  // Keep the last result on screen while re-checking (no layout jump); the
  // first time, show the three checkpoints waiting.
  if (!root.querySelector(".pf-node")) {
    root.innerHTML = "<div class='pf-nodes'>" + row("wait", "Design + config", "") +
      row("wait", "PDK + standard cells", "") + row("wait", "Engine", "") + "</div>";
  }
  root.classList.add("is-checking");
  verdict("Checking…", "");
  let pf;
  try {
    pf = await api.preflight(state.selectedPdk, state.selectedScl, state.runMode);
  } catch (ex) {
    root.classList.remove("is-checking");
    root.innerHTML = "<div class='pf-nodes'>" + row("bad", "Check failed", fmt.escape(ex.message)) + "</div>";
    verdict("Couldn't check", "bad");
    return null;
  }
  root.classList.remove("is-checking");
  _last = pf;

  const d = pf.design || {};
  const p = pf.pdk || {};
  const t = pf.tools || {};

  let html = "";
  // A design with >1 config file is usable (LanEx picks one deterministically)
  // but the user should know which — surface it as an inline advisory, not a
  // blocker (N6).
  const cfgNote = d.config_note
    ? " · <span class='pf-note-warn'>" + fmt.escape(d.config_note) + "</span>"
    : "";
  // A starter top module with no logic in it yet: the run would stop at
  // placement with nothing to place. A heads-up, not a blocker.
  const empty = d.ok && d.top_empty;
  html += row(
    !d.ok ? "bad" : empty ? "warn" : "ok",
    "Design + config",
    empty
      ? "<code>" + fmt.escape(empty.module) + "</code> has no logic yet, so there's nothing to place. Write it in " +
        fmt.escape(empty.rel) + " first." + cfgNote
      : d.ok
      ? (d.config_file || "config") + " · " + plural(d.source_count || 0, "source file") + cfgNote
      : !d.dir ? "No project open."
        : !d.config_file ? "No config file in the project."
        : (d.missing_sources || []).length ? "The config lists files that don't exist: " + fmt.escape(d.missing_sources.join(", "))
        : "No Verilog files to build.",
    empty ? "<button class='btn btn-sm pf-act' data-act='edit' data-rel='" + fmt.escape(empty.rel) + "'>Open in RTL IDE</button>"
      : d.ok ? "" : !d.dir ? "<button class='btn btn-sm pf-act' data-act='design'>Open a project</button>"
      : d.config_file && !(d.missing_sources || []).length ? "<button class='btn btn-sm pf-act' data-act='new-file'>New file</button>"
      : "<button class='btn btn-sm pf-act' data-act='sources'>Open Sources</button>",
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
    p.ready || pdkWillDownload ? "" : "<button class='btn btn-sm pf-act' data-act='tools'>Install PDK</button>",
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
      t.ok ? "" : "<button class='btn btn-sm pf-act' data-act='tools'>Open Tools</button>",
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
      t.ok ? plural(tools.length, "tool") + " ready" : "missing: " + (toolDetail || "—"),
      t.ok ? "" : "<button class='btn btn-sm pf-act' data-act='tools'>Open Tools</button>",
    );
  }

  if (pf.ready && empty) verdict("1 heads-up", "bad");
  else if (pf.ready) verdict("All set", "ok");
  else verdict(pf.blockers.length + (pf.blockers.length === 1 ? " thing" : " things") + " to fix", "bad");

  root.innerHTML = "<div class='pf-nodes'>" + html + "</div>";

  root.closest(".picker")?.classList.toggle("picker-ready", !!pf.ready);

  // Wire the fix buttons to jump to the right place.
  root.querySelectorAll(".pf-act").forEach((b) => {
    b.addEventListener("click", () => {
      const act = b.dataset.act;
      if (act === "tools") {
        document.querySelector('.side-tab[data-tab="tools"]')?.click();
      } else if (act === "design") {
        document.getElementById("setup-design")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (act === "sources") {
        document.getElementById("setup-sources")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (act === "edit") {
        document.querySelector('.side-tab[data-tab="ide"]')?.click();
        import("./ide/main.js").then(async (m) => {
          await m.initIde({ designDir: state.designDir, runMode: state.runMode });
          await m.openInIde({ rel: b.dataset.rel });
        }).catch(() => {});
      } else if (act === "new-file") {
        document.querySelector('.side-tab[data-tab="ide"]')?.click();
        import("./ide/main.js").then(async (m) => {
          await m.initIde({ designDir: state.designDir, runMode: state.runMode });
          m.newFile("module_v");
        }).catch(() => {});
      }
    });
  });
  return pf;
}
