// tier.js — complexity tiers (Simple / Pro). Progressive disclosure so one
// cockpit serves a beginner and an expert. Persisted in localStorage, applied
// as a `data-tier` attribute on <body>; advanced nodes tagged
// `data-tier-min="pro"` hide in Simple mode (see styles.css).
import { state } from "./state.js";

const KEY = "ll.tier";

export function getTier() {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "simple" || t === "pro") return t;
  } catch (_e) {}
  // Default: simple on first run; pro once the user has completed a run.
  try {
    if (localStorage.getItem("ll.onboarded") === "1") return "pro";
  } catch (_e) {}
  return "simple";
}

export function setTier(t) {
  const tier = t === "pro" ? "pro" : "simple";
  try { localStorage.setItem(KEY, tier); } catch (_e) {}
  state.tier = tier;
  applyTier();
  paintControl();
}

export function applyTier() {
  const tier = getTier();
  state.tier = tier;
  document.body.dataset.tier = tier;
}

function paintControl() {
  const tier = getTier();
  document.querySelectorAll(".tier-btn").forEach((b) =>
    b.classList.toggle("tier-btn-active", b.dataset.tier === tier),
  );
}

export function setupTier() {
  applyTier();
  document.querySelectorAll(".tier-btn").forEach((btn) => {
    btn.addEventListener("click", () => setTier(btn.dataset.tier));
  });
  paintControl();
}

export function toggleTier() {
  setTier(getTier() === "pro" ? "simple" : "pro");
}
