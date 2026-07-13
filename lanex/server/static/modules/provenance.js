// provenance.js — "where did this number come from?"
//
// Every value LanEx displays was parsed from a file LibreLane (or the
// underlying tool, or the user) wrote. `provBtnHtml` renders the small source
// button next to a data point; `openProvenance` asks the server to locate the
// exact file + line and opens the RAW file in a dialog with that line
// highlighted, plus Copy-path / Download / Locate actions — so the user can
// verify the display against the tool's own output, outside LanEx if they
// want. A value the server can't locate shows an honest message, never a
// guessed line.

import { api, fmt } from "./api.js";
import { toast } from "./toast.js";
import { renderFileText } from "./fileview.js";
import { customDialog } from "./dialog.js";

// A compact "view source" button. `params` mirrors /api/provenance:
// {kind, key, tag, path, needle}; `label` defaults to a magnifier glyph.
export function provBtnHtml(params, title) {
  const data = fmt.escape(JSON.stringify(params));
  return "<button class='btn btn-ghost prov-btn' data-prov='" + data +
    "' title='" + fmt.escape(title || "Show the raw tool file this value came from, line highlighted") +
    "'><svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><circle cx='11' cy='11' r='7'/><path d='M21 21l-4.3-4.3'/></svg></button>";
}

// Text for a "your config" field chip from one /api/provenance?kind=input-map
// entry. Pure (node-testable): the form's tier between "LibreLane default" and
// an override. A scoped (pdk::/scl::) entry is labelled with its scope and
// declared CONDITIONAL — LanEx never resolves whether a scope applies to the
// run; resolved.json is the post-run proof.
export function configChipSpec(entry, rel) {
  const scoped = !!entry.scoped;
  const label = scoped ? "config (" + (entry.scope || "scoped") + ")" : "your config";
  const title =
    (scoped
      ? "Set in " + rel + " line " + entry.line + " inside a " + (entry.scope || "scoped") +
        " section — it applies only when the run's PDK/SCL matches that section."
      : "Set in " + rel + " line " + entry.line +
        " — this is what an untouched field uses (an override supersedes it).") +
    (entry.others ? " The file has " + entry.others + " more entr" +
      (entry.others === 1 ? "y" : "ies") + " for this variable." : "") +
    " Click to open the file at that line.";
  return { label, title, text: label + ": " + entry.value, scoped };
}

// Wire every [data-prov] button under `root` (idempotent).
export function wireProvBtns(root) {
  if (!root) return;
  root.querySelectorAll("[data-prov]").forEach((b) => {
    if (b._wired) return;
    b._wired = true;
    b.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      let params = null;
      try { params = JSON.parse(b.dataset.prov); } catch { /* fall through */ }
      if (params) openProvenance(params);
    });
  });
}

async function _fetchRawText(params, r) {
  // Run-relative files ride the traversal-guarded run-file endpoint; the
  // design's own config (input kind, no tag) rides read-text (design-root
  // confined). Both return the bytes on disk — no LanEx re-rendering.
  if (params.tag) {
    const resp = await fetch(api.runFileUrl(params.tag, r.rel),
      { headers: { "X-Requested-With": "XMLHttpRequest" } });
    if (!resp.ok) throw new Error("HTTP " + resp.status + " reading " + r.rel);
    return await resp.text();
  }
  const t = await api.readText(r.abs);
  if (!t || t.ok === false) throw new Error((t && t.error) || "could not read the file");
  return t.text || "";
}

// Look up + show. `meta.title` overrides the dialog heading.
export async function openProvenance(params, meta = {}) {
  let r;
  try {
    r = await api.provenance(params);
  } catch (ex) {
    toast.show("Provenance lookup failed: " + (ex.message || ex), "error");
    return;
  }
  if (!r || r.ok === false) {
    // Honest absence — say WHY there is no source line, never invent one.
    toast.show((r && r.reason) || "Could not locate the source of this value.", "warn", 6000);
    return;
  }
  let text;
  try {
    text = await _fetchRawText(params, r);
  } catch (ex) {
    toast.show("Could not open " + r.rel + ": " + (ex.message || ex), "error");
    return;
  }
  const heading = meta.title ||
    (params.key ? "Source of " + params.key : "Source: " + r.rel);
  await customDialog({
    title: fmt.escape(heading),
    wide: true,
    bodyHtml:
      "<p class='muted prov-note'>Raw file as written by <b>" +
      fmt.escape(r.writer || "the flow") +
      "</b> — LanEx did not generate or edit it." +
      (r.line ? " The highlighted line is where the value above was read from." : "") +
      "</p><div class='prov-view'></div>",
    onMount: (back) => {
      renderFileText(back.querySelector(".prov-view"), text, {
        title: r.rel,
        line: r.line,
        abs: r.abs,
        tag: params.tag || null,
        path: params.tag ? r.rel : null,
      });
    },
  });
}
