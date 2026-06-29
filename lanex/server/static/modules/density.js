// density.js — comfortable / compact information density for power users.
// Compact tightens spacing + type so advanced workers see more at once.

const KEY = "ll.density";

export function setupDensity() {
  try {
    if (localStorage.getItem(KEY) === "compact") {
      document.body.classList.add("density-compact");
    }
  } catch (_e) {}
}

export function toggleDensity() {
  const compact = document.body.classList.toggle("density-compact");
  try {
    localStorage.setItem(KEY, compact ? "compact" : "comfortable");
  } catch (_e) {}
  return compact;
}

export function isCompact() {
  return document.body.classList.contains("density-compact");
}
