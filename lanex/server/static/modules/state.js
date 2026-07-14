// state.js — single source of truth for the SPA.

export const state = {
  steps: [],
  variables: [],
  designFormats: [],
  flows: [],
  pdks: [],
  selectedPdk: "",
  selectedScl: "",
  designDir: "",
  designSources: [],         // [{name, relpath, abspath, ext, size}, ...]
  designMemories: [],        // ditto for .mem/.hex/.bin
  selectedFiles: [],         // abspath[] checked
  extrasFiles: [],           // full paths user added manually
  runs: [],
  selectedRunTag: null,
  previewedConfigHash: null, // config sha stashed when Final-settings preview opened (N7 TOCTOU)
  pipeline: [],
  stepStatuses: {},
  stepTiming: {},            // id -> {start, end} (ms epoch) for the run timeline
  status: { running: false, paused: false, cancelled: false, tag: null },
  mode: "auto",
  runMode: "container",   // "container" (librelane --dockerized) | "local" (native tools)
  varsValues: {},
  metrics: {},
  installJobs: {},
  onboardingSeen: false,
  runProgress: { done: 0, total: 0, current: "" },
};

export function setState(patch) {
  Object.assign(state, patch);
}

// safeStorage — localStorage that never throws.
//
// Private-mode / enterprise-policy / storage-full browsers throw on any
// localStorage access. The boot path reads several keys (theme, density, recent
// designs); an unguarded throw there leaves a blank screen. This wrapper
// degrades to "no persistence" instead of crashing. Use it everywhere instead
// of touching localStorage directly.
export const safeStorage = {
  get(key, fallback = null) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : v;
    } catch (_e) { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, value); return true; } catch (_e) { return false; }
  },
  remove(key) {
    try { localStorage.removeItem(key); } catch (_e) {}
  },
  getJSON(key, fallback = null) {
    const raw = safeStorage.get(key, null);
    if (raw === null) return fallback;
    try { return JSON.parse(raw); } catch (_e) { return fallback; }
  },
  setJSON(key, obj) {
    try { return safeStorage.set(key, JSON.stringify(obj)); } catch (_e) { return false; }
  },
};
