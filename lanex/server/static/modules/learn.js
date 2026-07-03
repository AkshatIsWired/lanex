// learn.js — Learn panel (Phase 0.3). A slide-over that explains steps, metrics
// and terms using ONLY real introspected data (no invented numbers): step
// `help_md`, metric higher_is_better semantics, and a curated glossary.
import { api, fmt } from "./api.js";
import { state } from "./state.js";

let _panel = null;
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

function panel() {
  if (_panel) return _panel;
  const p = document.createElement("aside");
  p.className = "learn-panel";
  p.hidden = true;
  p.innerHTML =
    "<div class='learn-head'><span class='learn-title'>Learn</span>" +
    "<button class='btn btn-ghost' id='learn-close'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button></div>" +
    "<div class='learn-body' id='learn-body'></div>";
  document.body.appendChild(p);
  p.querySelector("#learn-close").addEventListener("click", () => { p.hidden = true; });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !p.hidden) p.hidden = true; });
  _panel = p;
  return p;
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
  const p = panel(); p.hidden = false;
  const body = p.querySelector("#learn-body");
  body.innerHTML = "<p class='muted'>Loading…</p>";
  let info = (state.steps || []).find((s) => s.id === stepId);
  if (!info || !info.help_md) {
    try { info = await api.step(stepId); } catch (_e) {}
  }
  if (!info) { body.innerHTML = "<p class='muted'>No help for " + fmt.escape(stepId) + ".</p>"; return; }
  body.innerHTML =
    "<h2>" + fmt.escape(info.long_name || info.id) + "</h2>" +
    "<p class='muted'><code>" + fmt.escape(info.id) + "</code></p>" +
    (info.help_md ? "<div class='learn-md'>" + mdToHtml(info.help_md) + "</div>"
                  : "<p class='muted'>LibreLane ships no help text for this step.</p>");
}

export async function explainMetric(key) {
  const p = panel(); p.hidden = false;
  const body = p.querySelector("#learn-body");
  const meta = (await metricMeta())[key];
  let dir = "";
  if (meta) dir = meta.higher_is_better ? "Higher is better." : "Lower is better.";
  if (meta && meta.critical) dir += " This is a critical (pass/fail) metric.";
  body.innerHTML =
    "<h2><code>" + fmt.escape(key) + "</code></h2>" +
    (dir ? "<p>" + fmt.escape(dir) + "</p>" : "<p class='muted'>No pass/fail semantics recorded for this metric.</p>");
}

export async function explainTerm(term) {
  const p = panel(); p.hidden = false;
  const body = p.querySelector("#learn-body");
  const g = await glossary();
  const text = g[term] || g[term.toUpperCase()];
  body.innerHTML =
    "<h2>" + fmt.escape(term) + "</h2>" +
    (text ? "<p>" + fmt.escape(text) + "</p>" : "<p class='muted'>No glossary entry.</p>");
}

// Open the Learn panel showing the full glossary index (clickable terms).
export async function openLearnIndex() {
  const p = panel(); p.hidden = false;
  const body = p.querySelector("#learn-body");
  const g = await glossary();
  body.innerHTML = "<h2>Glossary</h2>" +
    Object.keys(g).sort().map((term) =>
      "<div class='learn-term' data-explain='" + fmt.escape(term) + "'><strong>" +
      fmt.escape(term) + "</strong> — " + fmt.escape(g[term]) + "</div>").join("");
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
