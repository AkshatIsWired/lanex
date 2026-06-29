// plugins.js — curated plugin store + loader (Phase 4.4). Lists only the curated,
// checksum-verified registry; install/remove/enable; loads enabled front-end
// plugins through the SDK surface (see sdk.js) — never raw globals.
import { api, fmt } from "./api.js";
import { toast } from "./toast.js";
import { makeSdk } from "./sdk.js";

export async function renderPlugins() {
  const root = document.getElementById("plugins-body");
  if (!root) return;
  root.innerHTML = "<p class='muted'>Loading store…</p>";
  let registry = [];
  let installed = [];
  try {
    const [reg, inst] = await Promise.all([api.pluginsRegistry(), api.pluginsInstalled()]);
    registry = reg.plugins || [];
    installed = inst.installed || [];
  } catch (ex) {
    root.innerHTML = "<p class='pill pill-fail'>Could not reach the plugin registry: " +
      fmt.escape(ex.message || ex) + "</p>";
    return;
  }
  const instById = Object.fromEntries(installed.map((p) => [p.id, p]));
  // Per-entry action depends on its status:
  //  • built-in   → already in the cockpit; "Open" jumps to its tab.
  //  • external   → third-party tool/plugin; "Download" opens its page (we never
  //                 auto-run a native installer). The disclaimer banner applies.
  //  • installable→ a hosted, sha256-verified front-end plugin: Install/Remove.
  const card = (m) => {
    const inst = instById[m.id];
    const status = m.status || (m.url && (m.sha256 || m.checksum) ? "installable" : "external");
    const statusChip =
      status === "built-in" ? "<span class='chip chip-ok'>built-in</span>"
      : status === "external" ? "<span class='chip chip-warn'>external download</span>"
      : "";
    let actions;
    if (status === "built-in") {
      actions = "<button class='btn btn-primary' data-act='open' data-open='" + fmt.escape(m.open || "") + "'>Open</button>";
    } else if (status === "external") {
      actions = m.url
        ? "<a class='btn btn-ghost' href='" + fmt.escape(m.url) + "' target='_blank' rel='noopener noreferrer'>↗ Download / docs</a>"
        : "<span class='muted'>not yet available</span>";
    } else if (inst) {
      actions = "<button class='btn btn-ghost' data-act='remove' data-id='" + fmt.escape(m.id) + "'>Remove</button>" +
        "<label class='plugin-enable'><input type='checkbox' data-act='enable' data-id='" +
        fmt.escape(m.id) + "' " + (inst.enabled ? "checked" : "") + "> enabled</label>";
    } else {
      actions = "<button class='btn btn-primary' data-act='install' data-id='" + fmt.escape(m.id) + "'>Install</button>";
    }
    return "<div class='plugin-card card'>" +
      "<div class='plugin-head'><span class='plugin-name'>" + fmt.escape(m.name || m.id) + "</span>" +
      "<span class='chip'>" + fmt.escape(m.kind || "tab") + "</span>" + statusChip + "</div>" +
      "<p class='muted'>" + fmt.escape(m.description || "") + "</p>" +
      "<div class='plugin-actions'>" + actions + "</div></div>";
  };

  const disclaimer =
    "<div class='plugin-disclaimer'>⚠ <strong>External downloads:</strong> entries marked " +
    "<em>external download</em> are third-party tools/plugins, not part of LibreLane. " +
    "<strong>LibreLane (and this GUI) is not responsible for software you download or run " +
    "from external sources</strong> — you install and use them at your own risk. Only this " +
    "curated list is shown, and any hosted plugin is sha256-verified before install.</div>";

  root.innerHTML = disclaimer + (registry.length
    ? "<div class='plugins-grid'>" + registry.map(card).join("") + "</div>"
    : "<div class='empty'><h3>No add-ons available</h3>" +
      "<p>The curated registry is unreachable and no catalog is bundled.</p></div>");

  root.querySelectorAll("[data-act='open']").forEach((b) =>
    b.addEventListener("click", () => {
      const tab = b.dataset.open;
      if (tab) document.querySelector('.side-tab[data-tab="' + tab + '"]')?.click();
    }));
  root.querySelectorAll("[data-act='install']").forEach((b) =>
    b.addEventListener("click", () => act("install", b.dataset.id, root)));
  root.querySelectorAll("[data-act='remove']").forEach((b) =>
    b.addEventListener("click", () => act("remove", b.dataset.id, root)));
  root.querySelectorAll("[data-act='enable']").forEach((b) =>
    b.addEventListener("change", () => api.pluginEnable(b.dataset.id, b.checked).catch(() => {})));
}

async function act(kind, id, root) {
  try {
    if (kind === "install") {
      const r = await api.pluginInstall(id);
      if (r.in_progress) { toast.show("Already downloading…", "info"); return; }
      if (!r.ok) { toast.show("Install failed: " + (r.error || "checksum?"), "error"); return; }
      toast.show("Installed " + id, "success");
    } else {
      await api.pluginRemove(id);
      toast.show("Removed " + id, "success");
    }
    renderPlugins();
  } catch (ex) {
    toast.show("Plugin op failed: " + (ex.message || ex), "error");
  }
}

// Load enabled front-end plugins at startup, each via the SDK surface only.
export async function loadEnabledPlugins() {
  let installed = [];
  try { installed = (await api.pluginsInstalled()).installed || []; } catch (_e) { return; }
  for (const p of installed) {
    if (!p.enabled) continue;
    const m = p.manifest || {};
    if (!["tab", "viewer"].includes(m.kind) || !m.entry) continue;
    try {
      const mod = await import("/static/plugins/" + encodeURIComponent(p.id) + "/" + m.entry);
      if (typeof mod.init === "function") mod.init(makeSdk(p.id));
    } catch (ex) {
      console.warn("plugin", p.id, "failed to load", ex);
    }
  }
}
