// hotkeys.js — global keyboard shortcuts + the single source of truth for the
// Shortcuts tab of the help sheet (so the list and the handlers can never drift).
import { toggleDensity } from "./density.js";

// Number keys → tab. One declarative map drives BOTH the handler and the dialog
// text, so adding a tab key is a one-line change that stays documented.
const TAB_KEYS = {
  "1": ["setup", "Setup"],
  "2": ["pipeline", "Pipeline"],
  "3": ["runs", "Runs"],
  "4": ["preview", "Preview"],
  "5": ["tools", "Tools"],
  "6": ["analytics", "Analytics"],
  "7": ["verify", "Verify"],
  "8": ["dse", "DSE"],
  "9": ["layout", "Layout"],
  "0": ["cells", "Cells"],
};

// Rendered verbatim into the help sheet's Shortcuts tab. Kept next to the handlers.
export const SHORTCUTS = [
  { keys: "Ctrl K", desc: "Search every command and setting" },
  { keys: "1 / 2 / 3 / 4 / 5", desc: "Setup, Pipeline, Runs, Preview, Tools" },
  { keys: "6 / 7 / 8 / 9 / 0", desc: "Analytics, Verify, DSE, Layout, Cells" },
  { keys: "r", desc: "Start a run" },
  { keys: "s", desc: "Stop the running flow" },
  { keys: "/", desc: "Filter the pipeline log" },
  { keys: "t", desc: "Switch light or dark" },
  { keys: "d", desc: "Compact spacing on or off" },
  { keys: "?", desc: "Open this help" },
  { keys: "Esc", desc: "Close a menu, panel or dialog" },
];

export function setupHotkeys() {
  window.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    if (/input|textarea|select/i.test(tag)) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "?") {
      import("./shell.js").then((m) => m.openHelp("keys"));
      e.preventDefault();
      return;
    }
    if (e.key === "t") document.getElementById("theme-btn")?.click();
    if (e.key === "d") toggleDensity();
    if (Object.prototype.hasOwnProperty.call(TAB_KEYS, e.key)) dispatchJump(TAB_KEYS[e.key][0]);
    if (e.key === "r") document.getElementById("btn-run")?.click();
    if (e.key === "s") document.getElementById("btn-cancel")?.click();
    if (e.key === "/") {
      const s = document.getElementById("log-search");
      if (s) {
        document.querySelector('.side-pane-tab[data-itab="logs"]')?.click();
        s.focus();
        e.preventDefault();
      }
    }
  });
}

function dispatchJump(name) {
  document.querySelector('.side-tab[data-tab="' + name + '"]')?.click();
}
