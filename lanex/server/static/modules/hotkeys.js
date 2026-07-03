// hotkeys.js — global keyboard shortcuts + the single source of truth for the
// "?" shortcut dialog (so the dialog and the handlers can never drift, F4/D8c).

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

// Rendered verbatim into the "?" dialog. Kept next to the handlers below.
export const SHORTCUTS = [
  { keys: "⌘/Ctrl+K", desc: "command palette (everything)" },
  { keys: "1..6", desc: "Setup / Pipeline / Runs / Preview / Tools / Analytics" },
  { keys: "7..0", desc: "Verify / DSE / Layout / Cells" },
  { keys: "r / s", desc: "start a run / stop a run" },
  { keys: "/", desc: "focus the log filter" },
  { keys: "t / d", desc: "toggle theme / toggle compact density" },
  { keys: "? / Esc", desc: "this help / close" },
];

export function setupHotkeys() {
  renderShortcutList();
  window.addEventListener("keydown", (e) => {
    const tag = (e.target && e.target.tagName) || "";
    if (/input|textarea|select/i.test(tag)) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.key === "?") {
      const d = document.getElementById("help-dialog");
      if (d && d.showModal) d.showModal();
      e.preventDefault();
      return;
    }
    if (e.key === "Escape") {
      const d = document.getElementById("help-dialog");
      if (d && d.close) d.close();
    }
    if (e.key === "t") toggleThemeDispatch();
    if (e.key === "d") document.getElementById("density-btn")?.click();
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

function renderShortcutList() {
  const ul = document.getElementById("help-shortcut-list");
  if (!ul) return;
  // The key strings are fixed, HTML-safe literals defined above.
  ul.innerHTML = SHORTCUTS.map((s) => "<li><kbd>" + s.keys + "</kbd> — " + s.desc + "</li>").join("");
}

function dispatchJump(name) {
  document.querySelector('.side-tab[data-tab="' + name + '"]')?.click();
}

function toggleThemeDispatch() {
  const isDark = document.body.classList.contains("theme-dark");
  document.body.classList.toggle("theme-dark", !isDark);
  document.body.classList.toggle("theme-light", isDark);
  try {
    localStorage.setItem("ll.theme", isDark ? "light" : "dark");
  } catch (_) {}
}
