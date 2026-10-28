// preflight.js — beginner-friendly "Ready to run?" checklist.
// One call verifies design + config + PDK + EDA tools and renders a clear
// pass/fail list with one-click jumps to fix whatever is missing.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { go } from "./nav.js";

let _last = null;
let _lastAt = 0;
let _lastKey = "";
let _inflight = null;   // { key, p }: the check now on its way

export function lastPreflight() {
  return _last;
}

// What a check is a check of: the project, the PDK and library picked, and
// the run mode. A result for anything else says nothing about this run.
export function preflightKey(s = state) {
  return [s.designDir || "", s.selectedPdk || "", s.selectedScl || "", s.runMode || ""].join("\0");
}

// How long a check stays good enough to start a run on without asking again.
// Anything that changes what it checked (a config edit, an install, another
// PDK or project) drops it before then (forgetPreflight).
export const PREFLIGHT_FRESH_MS = 60000;

// The rule Run uses: a result is reused only for the same project, PDK,
// library and mode, while it is fresh. Pure (tested).
export function reusablePreflight(last, { key, now, maxAge = PREFLIGHT_FRESH_MS } = {}) {
  if (!last || !last.result || !last.at || last.key !== key) return null;
  if (!(now - last.at >= 0) || now - last.at > maxAge) return null;
  return last.result;
}

// What a check means for a Run click: a PDK mismatch (offer the fix), other
// blockers (ask), or nothing in the way. Pure (tested).
export function runBlocker(pf) {
  if (!pf) return null;
  const mm = pf.pdk && pf.pdk.mismatch;
  if (mm) return { kind: "mismatch", mismatch: mm };
  if (!pf.ready) return { kind: "blockers", blockers: (pf.blockers || []).slice() };
  return null;
}

// A fresh result for the current picks, or null.
export function freshPreflight(now = Date.now()) {
  return reusablePreflight({ result: _last, key: _lastKey, at: _lastAt }, { key: preflightKey(), now });
}

// Something the check read has changed: the next Run checks again.
let _gen = 0;
export function forgetPreflight() {
  _gen++;
  _lastAt = 0;
  _lastKey = "";
  _inflight = null;   // one already on its way may have read the old state
}

if (typeof document !== "undefined") {
  for (const ev of ["g:config_changed", "g:active_design_changed", "g:projects_changed", "g:tools_changed"]) {
    document.addEventListener(ev, forgetPreflight);
  }
}

// The check on its way for the current picks, else a new one (painted on
// Setup's checklist). Callers that only need the answer share one request.
export function preflightNow() {
  return renderPreflight();
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
// A check already on its way for the same picks is shared, not repeated.
export function renderPreflight() {
  const key = preflightKey();
  if (_inflight && _inflight.key === key) return _inflight.p;
  const p = paintPreflight(key);
  const mine = { key, p };
  _inflight = mine;
  p.finally(() => { if (_inflight === mine) _inflight = null; }).catch(() => {});
  return p;
}

async function paintPreflight(key) {
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
  const gen = _gen;
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
  // Kept as fresh only if nothing it read changed while it was on its way.
  if (gen === _gen) { _lastAt = Date.now(); _lastKey = key; }

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
  // The config names another PDK or library than the picker: LibreLane would
  // build for the config's, so the run is blocked until they agree.
  const mm = p.mismatch;
  html += mm
    ? row("bad", "PDK + standard cells", fmt.escape(mm.message),
      (mm.editable ? "<button class='btn btn-sm pf-act' data-act='pdk-save'>Save to " + fmt.escape(mm.name || "config") + "</button>" : "") +
      (mm.config.pdk ? "<button class='btn btn-sm btn-ghost pf-act' data-act='pdk-follow'>Use " + fmt.escape(mm.config.pdk) + "</button>" : ""))
    : row(
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

  // Free memory looks too small for this design: a heads-up, never a blocker.
  const mem = pf.resources || {};
  if (mem.warn) {
    html += row("warn", "Memory", (mem.available_gb ?? "?") + " GB free; this design needs about " + (mem.need_gb ?? "?") + " GB",
      "<button class='btn btn-sm pf-act' data-act='mem'>What to do</button>");
  }

  const heads = (empty ? 1 : 0) + (mem.warn ? 1 : 0);
  if (pf.ready && heads) verdict(heads + " heads-up" + (heads === 1 ? "" : "s"), "bad");
  else if (pf.ready) verdict("All set", "ok");
  else verdict(pf.blockers.length + (pf.blockers.length === 1 ? " thing" : " things") + " to fix", "bad");

  root.innerHTML = "<div class='pf-nodes'>" + html + "</div>";

  root.closest(".picker")?.classList.toggle("picker-ready", !!pf.ready);

  // Wire the fix buttons to jump to the right place.
  root.querySelectorAll(".pf-act").forEach((b) => {
    b.addEventListener("click", () => {
      const act = b.dataset.act;
      if (act === "tools") {
        go("tools");
      } else if (act === "design") {
        document.getElementById("setup-design")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (act === "sources") {
        document.getElementById("setup-sources")?.scrollIntoView({ behavior: "smooth", block: "start" });
      } else if (act === "edit") {
        go("ide", { rel: b.dataset.rel });
      } else if (act === "new-file") {
        go("ide", { newFile: "module_v" });
      } else if (act === "mem") {
        import("./dialog.js").then((m) => m.alertDialog({ title: "Low memory", html: true,
          body: "<p>" + fmt.escape(mem.message) + "</p><p>" + fmt.escape(mem.next_step) + "</p>" +
            "<p><a href='" + fmt.escape(mem.link) + "' target='_blank' rel='noopener'>Microsoft's guide to WSL settings (.wslconfig)</a></p>" }));
      } else if (act === "pdk-save" || act === "pdk-follow") {
        import("./setup.js").then((m) => m.resolvePdkMismatch(p.mismatch, act === "pdk-save" ? "save" : "follow"));
      }
    });
  });
  return pf;
}
