// advisor.js — plain-English explanations of failed steps + advisor cards.

import { api, fmt } from "./api.js";
import { icon } from "./icons.js";

const _advisories = [];

export const renderAdvisor = {
  pushFromAlert(e) {
    const msg = e?.payload?.message || "";
    if (!msg) return;
    api.explain(msg)
      .then((card) => {
        if (!card) return;
        const exists = _advisories.find(
          (c) => c.title === card.title && c.what === card.what,
        );
        if (!exists) {
          _advisories.unshift(card);
          if (_advisories.length > 12) _advisories.length = 12;
        }
        paint();
      })
      .catch(() => {});
  },
  pushChecker(checker, metric) {
    api.explainChecker(checker, metric)
      .then((card) => {
        if (!card) return;
        _advisories.unshift(card);
        if (_advisories.length > 12) _advisories.length = 12;
        paint();
      })
      .catch(() => {});
  },
  clear() {
    _advisories.length = 0;
    paint();
  },
};

function paint() {
  const root = document.getElementById("advisor-list");
  if (!root) return;
  if (!_advisories.length) {
    root.innerHTML =
      "<div class='empty'><span class='ico'>" + icon('bulb',{size:40}) + "</span><h3>Advisor is quiet</h3><p>Run the flow. If anything fails, this panel auto-explains the failure and what to try.</p></div>";
    return;
  }
  root.innerHTML = "";
  for (const card of _advisories) {
    const div = document.createElement("div");
    div.className = "adv-card";
    div.innerHTML =
      "<div class='title'>" + fmt.escape(card.title || "Issue") + "</div>" +
      "<div class='what'>" + fmt.escape(card.what || "") + "</div>" +
      "<div class='why'>" + fmt.escape(card.why || "") + "</div>" +
      "<div class='try'>" +
      "<ol>" +
      (card.remediations || []).map((t) => "<li>" + fmt.escape(t) + "</li>").join("") +
      "</ol>" +
      "</div>";
    const fixWrap = document.createElement("div");
    fixWrap.className = "fix";
    for (const f of card.fix || []) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "Apply " + f.var + "=" + f.value;
      btn.addEventListener("click", () => {
        const input = document.getElementById("var-" + f.var);
        if (input) {
          input.value = f.value;
          input.dispatchEvent(new Event("input", { bubbles: true }));
        }
      });
      fixWrap.appendChild(btn);
    }
    if (fixWrap.children.length) div.appendChild(fixWrap);
    root.appendChild(div);
  }
}
