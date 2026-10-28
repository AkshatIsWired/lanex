// learn.js — the glossary in the help sheet's Learn tab: a curated list of
// terms (static/glossary.json), searchable, under the page's own guide.
import { fmt } from "./api.js";

let _glossary = null;

async function glossary() {
  if (_glossary) return _glossary;
  try {
    const r = await fetch("/static/glossary.json", { headers: { "X-Requested-With": "XMLHttpRequest" } });
    _glossary = await r.json();
  } catch (_e) { _glossary = {}; }
  return _glossary;
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
