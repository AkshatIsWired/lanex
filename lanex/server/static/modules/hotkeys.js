// hotkeys.js — global keyboard shortcuts + the single source of truth for the
// Shortcuts tab of the help sheet (so the list and the handlers can never drift).
import { toggleDensity } from "./density.js";
import { go, railKeys } from "./nav.js";

// Number keys follow the rail, top to bottom (1–9, then 0), read from the rail
// itself so they can't drift from it; each rail tab's tooltip shows its key.

// Rendered verbatim into the help sheet's Shortcuts tab. Kept next to the handlers.
export const SHORTCUTS = [
  { keys: "Ctrl K", desc: "Search every command and setting" },
  { keys: "1 … 9, 0", desc: "The pages, top to bottom in the left rail" },
  { keys: "Alt ← / Alt →", desc: "Back and forward between pages (the mouse's side buttons too)" },
  { keys: "r", desc: "Start a run" },
  { keys: "s", desc: "Stop the running flow" },
  { keys: "/", desc: "Filter the pipeline log" },
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

export function setupHotkeys() {
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
