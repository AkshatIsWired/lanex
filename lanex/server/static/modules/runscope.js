// runscope.js — one source of truth for "which runs does a picker show".
//
// Every per-tab run dropdown (Analytics / Verify / DSE / Layout) used to be
// scoped to the single active design, so opening a *new* GUI instance pointed at
// one design hid runs done under another. This module adds a GLOBAL scope
// preference ("this design" vs "all designs you've opened") shared by all those
// pickers, the cross-design gather, and the active-design switch a cross-design
// selection needs (run-scoped endpoints resolve against the server's active
// design dir). Pure vanilla ES; no new dependency.

import { api } from "./api.js";
import { state } from "./state.js";

const KEY = "ll.runScope";   // "design" | "all"

export function getRunScope() {
  try { return localStorage.getItem(KEY) === "all" ? "all" : "design"; } catch (_e) { return "design"; }
}
export function setRunScope(s) {
  try { localStorage.setItem(KEY, s === "all" ? "all" : "design"); } catch (_e) {}
}

// Normalise a design-dir path so two spellings of the SAME folder (trailing
// slash, mixed separators) aren't queried twice / treated as different designs.
export function normDir(d) {
  return String(d || "").replace(/[\\/]+$/, "").replace(/\\/g, "/");
}
export function designLabel(dir) {
  return (dir || "").split(/[/\\]/).filter(Boolean).pop() || dir || "";
}

// Gather runs for `scope` (defaults to the global pref). "all" merges across the
// recent design dirs (localStorage `ll.recentDesigns`) + the active one, de-duped
// by absolute run_dir, each row tagged with `_design`. Newest first.
export async function gatherRunsScoped(scope) {
  scope = scope || getRunScope();
  const byRunDir = new Map();
  const add = (runs, dir) => {
    for (const r of runs || []) {
      const key = r.run_dir || (normDir(dir) + "/runs/" + r.tag);
      if (byRunDir.has(key)) continue;
      r._design = dir;
      byRunDir.set(key, r);
    }
  };
  if (scope !== "all") {
    try { add(await api.runs(state.designDir || undefined), state.designDir); } catch (_e) {}
    return Array.from(byRunDir.values());
  }
  let dirs = [];
  try { dirs = JSON.parse(localStorage.getItem("ll.recentDesigns") || "[]").filter(Boolean); } catch (_e) {}
  // Merge in designs the SERVER remembers (survives cleared localStorage / a
  // different browser) so cross-design Compare/DSE never miss a design.
  try { dirs = dirs.concat((await api.knownDesigns()).designs || []); } catch (_e) {}
  if (state.designDir) dirs.unshift(state.designDir);
  const seen = new Set();
  for (const dir of dirs) {
    const nd = normDir(dir);
    if (seen.has(nd)) continue;
    seen.add(nd);
    try { add(await api.runs(dir), dir); } catch (_e) { /* stale/removed dir */ }
  }
  const all = Array.from(byRunDir.values());
  all.sort((a, b) => String(b.started_at || "").localeCompare(String(a.started_at || "")));
  return all;
}

// When a picked run lives under a different design, switch the server's active
// design to it first so the run-scoped endpoints (api.run/verify/timing/…)
// resolve against the right dir. No-op when it already matches.
export async function ensureActiveDesignFor(run) {
  const dir = run && run._design;
  if (dir && normDir(dir) !== normDir(state.designDir)) {
    try {
      await api.setDesignDir(dir);
      state.designDir = dir;
      // Tell the shell the active design moved (so the topbar pill — and the
      // global Run button's target — reflect what the user is now looking at).
      if (typeof document !== "undefined") {
        document.dispatchEvent(new CustomEvent("g:active_design_changed", { detail: { dir } }));
      }
    } catch (_e) {}
  }
  return state.designDir;
}

// Build <option>s for a run <select>. In "all" scope each label is prefixed with
// its design folder so runs from different designs are distinguishable.
export function runOptionsHtml(runs, selectedTag, esc) {
  const all = getRunScope() === "all";
  return (runs || []).map((r) => {
    const label = (all ? designLabel(r._design) + " · " : "") + r.tag;
    return "<option value='" + esc(r.tag) + "'" + (r.tag === selectedTag ? " selected" : "") + ">" + esc(label) + "</option>";
  }).join("");
}

// A compact "All designs" checkbox a picker bar can embed. `id` must be unique.
export function scopeToggleHtml(id) {
  return "<label class='run-scope-toggle' title=\"Show runs from every design you've opened recently, not just the active one\">" +
    "<input type='checkbox' id='" + id + "'" + (getRunScope() === "all" ? " checked" : "") + "/> All designs</label>";
}
export function wireScopeToggle(id, onChange) {
  const cb = document.getElementById(id);
  if (!cb || cb._wired) return;
  cb._wired = true;
  cb.addEventListener("change", () => { setRunScope(cb.checked ? "all" : "design"); if (onChange) onChange(); });
}
