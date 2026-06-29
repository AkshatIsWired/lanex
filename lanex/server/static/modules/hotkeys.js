// hotkeys.js

export function setupHotkeys() {
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
      document.getElementById("help-dialog").close && document.getElementById("help-dialog").close();
    }
    if (e.key === "t") toggleThemeDispatch();
    if (e.key === "d") document.getElementById("density-btn")?.click();
    if (e.key === "1") dispatchJump("setup");
    if (e.key === "2") dispatchJump("pipeline");
    if (e.key === "3") dispatchJump("runs");
    if (e.key === "4") dispatchJump("preview");
    if (e.key === "5") dispatchJump("tools");
    if (e.key === "6") dispatchJump("analytics");
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

function toggleThemeDispatch() {
  const isDark = document.body.classList.contains("theme-dark");
  document.body.classList.toggle("theme-dark", !isDark);
  document.body.classList.toggle("theme-light", isDark);
  try {
    localStorage.setItem("ll.theme", isDark ? "light" : "dark");
  } catch (_) {}
}
