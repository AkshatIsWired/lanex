// tabs.js — wire the left-side tabs (Setup/Pipeline/Runs/Preview/Tools).
import { state } from "./state.js";

export function setupTabs() {
  const tabs = Array.from(document.querySelectorAll(".side-tab"));
  // Side tabs switch sections.
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activate(tab.dataset.tab));
  });
  // ARIA tab semantics (WAI-ARIA tabs pattern): the <nav> is already
  // role="tablist"; mark each button a tab wired to its section panel, with a
  // roving tabindex + arrow-key navigation. Pure DOM, no dependency.
  for (const tab of tabs) {
    const name = tab.dataset.tab;
    const panel = document.getElementById("sec-" + name);
    tab.setAttribute("role", "tab");
    tab.id = tab.id || "tab-" + name;
    if (panel) {
      tab.setAttribute("aria-controls", panel.id);
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", tab.id);
      if (!panel.hasAttribute("tabindex")) panel.setAttribute("tabindex", "0");
    }
    const active = tab.classList.contains("side-tab-active");
    tab.setAttribute("aria-selected", active ? "true" : "false");
    tab.setAttribute("tabindex", active ? "0" : "-1");
    tab.addEventListener("keydown", (e) => onTabKey(e, tabs, tab));
  }
  // Side-pane tabs (right) for Live Logs / Metrics / Advisor.
  document.querySelectorAll(".side-pane-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const id = tab.dataset.itab;
      const tabset = tab.parentElement;
      tabset.querySelectorAll(".side-pane-tab").forEach((t) =>
        t.classList.toggle("side-pane-tab-active", t === tab),
      );
      document.querySelectorAll(".side-pane-section").forEach((p) =>
        p.classList.toggle("side-pane-section-active", p.id === "spane-" + id),
      );
    });
  });
}

// Arrow / Home / End keyboard navigation across the tablist.
function onTabKey(e, tabs, tab) {
  const i = tabs.indexOf(tab);
  let j = -1;
  if (e.key === "ArrowDown" || e.key === "ArrowRight") j = (i + 1) % tabs.length;
  else if (e.key === "ArrowUp" || e.key === "ArrowLeft") j = (i - 1 + tabs.length) % tabs.length;
  else if (e.key === "Home") j = 0;
  else if (e.key === "End") j = tabs.length - 1;
  else return;
  e.preventDefault();
  const next = tabs[j];
  activate(next.dataset.tab);
  next.focus();
}

export function activate(name) {
  document.querySelectorAll(".side-tab").forEach((t) => {
    const on = t.dataset.tab === name;
    t.classList.toggle("side-tab-active", on);
    t.setAttribute("aria-selected", on ? "true" : "false");
    t.setAttribute("tabindex", on ? "0" : "-1");
  });
  document.querySelectorAll(".section").forEach((s) =>
    s.classList.toggle("section-active", s.id === "sec-" + name),
  );
  state.activeTab = name;
  try { localStorage.setItem("ll.tab", name); } catch (_e) {}
}

export function currentTab() {
  const a = document.querySelector(".side-tab.side-tab-active");
  return a ? a.dataset.tab : "setup";
}
