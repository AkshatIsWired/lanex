// learn.js — Learn panel (Phase 0.3). A slide-over that explains steps, metrics
// and terms using ONLY real introspected data (no invented numbers): step
// `help_md`, metric higher_is_better semantics, and a curated glossary.
import { api, fmt } from "./api.js";
import { state } from "./state.js";

let _glossary = null;
let _metricMeta = null;

async function glossary() {
  if (_glossary) return _glossary;
  try {
    const r = await fetch("/static/glossary.json", { headers: { "X-Requested-With": "XMLHttpRequest" } });
    _glossary = await r.json();
  } catch (_e) { _glossary = {}; }
  return _glossary;
}

async function metricMeta() {
  if (_metricMeta) return _metricMeta;
  _metricMeta = {};
  try {
    const list = await api.metricsCatalog();
    for (const m of list || []) _metricMeta[m.name] = m;
  } catch (_e) {}
  return _metricMeta;
}

// Explanations render into the help sheet's Learn pane (shell.js), which is
// light-dismiss like every other overlay.
async function learnBody() {
  const { openHelp } = await import("./shell.js");
  return openHelp("learn", { render: false });
}

// Render a tiny, safe subset of markdown (headings, **bold**, `code`, lists).
function mdToHtml(md) {
  const esc = fmt.escape(md || "");
  return esc
    .replace(/^### (.*)$/gm, "<h4>$1</h4>")
    .replace(/^## (.*)$/gm, "<h3>$1</h3>")
    .replace(/^# (.*)$/gm, "<h3>$1</h3>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/^\s*[-*] (.*)$/gm, "<li>$1</li>")
    .replace(/\n{2,}/g, "<br><br>");
}

export async function explainStep(stepId) {
  const body = await learnBody();
  body.innerHTML = "<p class='muted'>Loading…</p>";
  let info = (state.steps || []).find((s) => s.id === stepId);
  if (!info || !info.help_md) {
    try { info = await api.step(stepId); } catch (_e) {}
  }
  if (!info) { body.innerHTML = "<p class='muted'>No help for " + fmt.escape(stepId) + ".</p>"; return; }
  body.innerHTML =
    "<h2>" + fmt.escape(info.long_name || info.id) + "</h2>" +
    "<p class='learn-id'>" + fmt.escape(info.id) + "</p>" +
    (info.help_md ? "<div class='learn-md'>" + mdToHtml(info.help_md) + "</div>"
                  : "<p class='muted'>LibreLane ships no help text for this step.</p>");
}

export async function explainMetric(key) {
  const body = await learnBody();
  const meta = (await metricMeta())[key];
  let dir = "";
  if (meta) dir = meta.higher_is_better ? "Higher is better." : "Lower is better.";
  if (meta && meta.critical) dir += " This is a critical (pass/fail) metric.";
  body.innerHTML =
    "<h2><code>" + fmt.escape(key) + "</code></h2>" +
    (dir ? "<p>" + fmt.escape(dir) + "</p>" : "<p class='muted'>No pass/fail semantics recorded for this metric.</p>");
}

export async function explainTerm(term) {
  const body = await learnBody();
  const g = await glossary();
  const text = g[term] || g[term.toUpperCase()];
  body.innerHTML =
    "<h2>" + fmt.escape(term) + "</h2>" +
    (text ? "<p>" + fmt.escape(text) + "</p>" : "<p class='muted'>No glossary entry.</p>");
}

// The glossary: a searchable list, one term per row. Rendered by the help
// sheet's Learn tab (shell.js).
export async function renderGlossary(body, { pageKey } = {}) {
  const g = await glossary();
  const terms = Object.keys(g).sort();
  const key = pageKey || document.querySelector(".side-tab.side-tab-active")?.dataset.tab;
  const { guideHtml } = await import("./help.js");
  const guide = key ? guideHtml(key) : "";
  body.innerHTML = guide +
    "<div class='sheet-lane'>Glossary</div>" +
    "<div class='sheet-search'><input type='search' id='gloss-q' placeholder='Search " + terms.length +
    " terms: DRC, slack, PDN…' autocomplete='off' aria-label='Search the glossary'/></div>" +
    "<div class='gloss' id='gloss-list'></div>";
  const list = body.querySelector("#gloss-list");
  const paint = (q) => {
    const needle = (q || "").trim().toLowerCase();
    const hits = terms.filter((t) => !needle || t.toLowerCase().includes(needle) ||
      String(g[t]).toLowerCase().includes(needle));
    list.innerHTML = hits.length
      ? hits.map((t) => "<div class='gloss-row'><span class='gloss-term'>" + fmt.escape(t) +
          "</span><span class='gloss-def'>" + fmt.escape(g[t]) + "</span></div>").join("")
      : "<p class='gloss-empty'>No term matches “" + fmt.escape(q) + "”.</p>";
  };
  paint("");
  body.querySelector("#gloss-q").addEventListener("input", (e) => paint(e.target.value));
}

// Kept for callers that open the glossary directly (command palette).
export async function openLearnIndex() {
  const { openHelp } = await import("./shell.js");
  openHelp("learn");
}

// Wire any `[data-explain]` affordance (step id, metric key, or glossary term).
export function setupLearn() {
  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-explain]");
    if (!el) return;
    const kind = el.dataset.explainKind || "term";
    const val = el.dataset.explain;
    if (kind === "step") explainStep(val);
    else if (kind === "metric") explainMetric(val);
    else explainTerm(val);
  });
}
