// theme.js — toggle theme persistence.
export function setupTheme() {
  try {
    const stored = localStorage.getItem("ll.theme");
    if (stored === "light") {
      document.body.classList.remove("theme-dark");
      document.body.classList.add("theme-light");
    }
  } catch (_) {}
  document.getElementById("help-icon")?.addEventListener("click", () => {
    document.getElementById("help-dialog")?.showModal && document.getElementById("help-dialog").showModal();
  });
  document.getElementById("btn-close-help")?.addEventListener("click", () =>
    document.getElementById("help-dialog").close && document.getElementById("help-dialog").close(),
  );
}

export function toggleTheme() {
  const isDark = document.body.classList.contains("theme-dark");
  document.body.classList.toggle("theme-dark", !isDark);
  document.body.classList.toggle("theme-light", isDark);
  try {
    localStorage.setItem("ll.theme", isDark ? "light" : "dark");
  } catch (_) {}
  // Let token-derived charts (theme-echarts.js) re-theme on toggle.
  document.dispatchEvent(new CustomEvent("g:theme_changed", { detail: { dark: !isDark } }));
}
