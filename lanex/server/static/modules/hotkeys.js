// hotkeys.js — global keyboard shortcuts + the single source of truth for the
// Shortcuts tab of the help sheet (so the list and the handlers can never drift).
import { toggleDensity } from "./density.js";
import { go, railKeys } from "./nav.js";
import { state } from "./state.js";
import { currentTab } from "./tabs.js";

// Number keys follow the rail, top to bottom (1–9, then 0), read from the rail
// itself so they can't drift from it; each rail tab's tooltip shows its key.

// Rendered verbatim into the help sheet's Shortcuts tab. Kept next to the handlers.
export const SHORTCUTS = [
  { keys: "Ctrl K", desc: "Search everything: actions, settings (#), runs (@), files (/), help (?)" },
  { keys: "1 … 9, 0", desc: "The pages, top to bottom in the left rail" },
  { keys: "Alt ← / Alt →", desc: "Back and forward between pages (the mouse's side buttons too)" },
  { keys: "Ctrl Enter", desc: "Start a run, from any page" },
  { keys: "r", desc: "Start a run (on Setup and Flow)" },
  { keys: "Ctrl `", desc: "Open or close the Console: log, command, journal, command line" },
  { keys: "s", desc: "Stop the running flow" },
  { keys: "/", desc: "Filter the step log on Flow" },
  { keys: "t", desc: "Switch light or dark" },
  { keys: "d", desc: "Compact spacing on or off" },
  { keys: "?", desc: "Open this help" },
  { keys: "Esc", desc: "Close a menu, panel or dialog" },
];

// The RTL IDE's own keys (editor and waveform). Listed in the help sheet; the
// editor and the waveform viewer handle them, so they never reach the app.
export const IDE_SHORTCUTS = [
  { keys: "Ctrl S", desc: "Save (and check the syntax, with Check on save)" },
  { keys: "Ctrl F / Ctrl H", desc: "Find, find and replace" },
  { keys: "Ctrl /", desc: "Comment or uncomment the line" },
  { keys: "Alt ↑ / Alt ↓", desc: "Move the line up or down" },
  { keys: "Ctrl D", desc: "Add the next match to the selection" },
  { keys: "Ctrl Space", desc: "Suggest keywords, blocks and names" },
  { keys: "Ctrl Z / Ctrl Y", desc: "Undo, redo (each file keeps its own history)" },
  { keys: "← / →", desc: "Waveform: previous or next change of the selected signals" },
  { keys: "+ / − / F", desc: "Waveform: zoom in, out, show the whole run" },
  { keys: "M", desc: "Waveform: put the marker at the cursor" },
  { keys: "Delete", desc: "Waveform: remove the selected signals" },
  { keys: "Esc", desc: "Waveform: let the selected signals go, then drop the marker" },
];

// A bare "r" starts a full run only where Run is the page's own action (Setup,
// Flow): elsewhere a stray r while reading Verify or Layout must not launch a
// two-minute run. Ctrl+Enter starts it from any page (not while typing).
export const RUN_KEY_TABS = ["setup", "pipeline"];
export function runKeyAllowed(key, { ctrl = false, tab = "" } = {}) {
  if (key === "Enter" && ctrl) return true;
  return key === "r" && !ctrl && RUN_KEY_TABS.includes(tab);
}

export function setupHotkeys() {
  // Ctrl+Enter: Run, from any page; never from a field or the code editor.
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.defaultPrevented) return;
    const t = e.target;
    if (t && (t.isContentEditable || /input|textarea|select/i.test(t.tagName || "") || (t.closest && t.closest(".cm-editor, .wv, .cmdk")))) return;
    if (state.status && state.status.running) return;
    document.getElementById("btn-run-global")?.click();
    e.preventDefault();
  });
  window.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    if (/input|textarea|select/i.test(tag)) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    // Typing in the code editor (a contenteditable, not a textarea) and keys the
    // waveform viewer uses (f, m, arrows, digits) are never app shortcuts: a
    // stray "r" there must not start a run.
    if (e.defaultPrevented || (e.target && (e.target.isContentEditable ||
        (e.target.closest && e.target.closest(".cm-editor, .wv"))))) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    // In the RTL IDE (its explorer, tabs, panels) a press meant for the code
    // easily lands on a button instead; there r and s must not start or stop
    // the RTL-to-GDS run.
    if ((e.key === "r" || e.key === "s") && e.target && e.target.closest && e.target.closest(".ide-embed")) return;
    if (e.key === "?") {
      import("./shell.js").then((m) => m.openHelp("keys"));
      e.preventDefault();
      return;
    }
    if (e.key === "t") document.getElementById("theme-btn")?.click();
    if (e.key === "d") toggleDensity();
    const page = railKeys().find(([k]) => k === e.key);
    if (page) go(page[1], {}, { link: false });
    // The top bar's Run: it starts the flow without leaving this page.
    if (e.key === "r" && runKeyAllowed("r", { tab: currentTab() }) && !(state.status && state.status.running)) document.getElementById("btn-run-global")?.click();
    if (e.key === "s") document.getElementById("btn-cancel")?.click();
    if (e.key === "/") {
      // Flow: filter the log of the step on screen.
      const s = document.querySelector("#sec-pipeline.section-active .fl-insp .lv-q input");
      if (s) { s.focus(); e.preventDefault(); }
    }
  });
}
