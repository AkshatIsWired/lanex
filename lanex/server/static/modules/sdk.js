// sdk.js — the frozen plugin SDK surface (Phase 4.4). Front-end plugins receive
// THIS object, not raw globals/DOM — so they run against a defined, constrained
// API. This is also the natural upstream-able GUI extension point for LibreLane.
import { api } from "./api.js";
import { state } from "./state.js";

const _tabMounts = {};
const _viewers = {};

// Register where plugin tabs/viewers can mount (the host wires real DOM nodes).
export function registerTabMount(id, el) { _tabMounts[id] = el; }

export function makeSdk(pluginId) {
  // Read-only, namespaced surface. No ambient authority.
  const sdk = {
    pluginId,
    version: "1.0",
    // --- read-only data accessors (wrap api.js; never expose POST/run powers) ---
    getActiveRun: () => state.selectedRunTag || null,
    async fetchRunOutputs(tag) {
      return api.runOutputs(tag || state.selectedRunTag);
    },
    async fetchMetrics(tag) {
      const view = await api.run(tag || state.selectedRunTag);
      return (view.metrics && view.metrics.values) || {};
    },
    onRunDone(cb) {
      document.addEventListener("g:flow_done", (e) => { try { cb(e.detail || {}); } catch (_e) {} });
    },
    // --- UI registration (into a defined mount point, not arbitrary DOM) ---
    registerTab({ id, title, mount }) {
      const host = document.getElementById("plugin-tab-host");
      if (!host || typeof mount !== "function") return false;
      const panel = document.createElement("section");
      panel.className = "plugin-panel";
      panel.dataset.plugin = pluginId + ":" + id;
      host.appendChild(panel);
      try { mount(panel); } catch (_e) {}
      return true;
    },
    registerViewer({ id, forFormat, mount }) {
      _viewers[pluginId + ":" + id] = { forFormat, mount };
      return true;
    },
  };
  return Object.freeze(sdk);
}

export function viewersFor(format) {
  return Object.values(_viewers).filter((v) => v.forFormat === format);
}
