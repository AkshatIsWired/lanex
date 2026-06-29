// autoconfig.js — offer to auto-generate a LibreLane config when a design has
// none. Detects the top module / clock / sources on the server and presents an
// editable suggestion the user confirms before anything is written.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { icon } from "./icons.js";

// Show or hide the "no config — auto-generate" banner for a design dir, based
// on the design-summary scan. Called from adoptDesignDir.
export async function maybeOfferAutoConfig(designDir) {
  const banner = document.getElementById("autoconfig-banner");
  if (!banner) return;
  if (!designDir) { banner.hidden = true; return; }
  let summary;
  try {
    const r = await fetch("/api/design-summary?path=" + encodeURIComponent(designDir), {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const body = await r.json();
    summary = body.data || {};
  } catch (_e) {
    banner.hidden = true;
    return;
  }
  if (!summary.config_missing || !summary.has_sources) {
    banner.hidden = true;
    banner.innerHTML = "";
    return;
  }
  banner.hidden = false;
  banner.innerHTML =
    "<div class='ac-banner-row'>" +
    "<span class='ac-banner-icon' aria-hidden='true'>" + icon("tools", { size: 20 }) + "</span>" +
    "<div class='ac-banner-text'><strong>No config file in this folder.</strong> " +
    "LibreLane needs a <code>config.json</code> to know the top module, clock and sources. " +
    "I can detect them for you.</div>" +
    "<button class='btn btn-primary' id='btn-autoconfig'>Auto-generate config</button>" +
    "</div>";
  banner.querySelector("#btn-autoconfig")?.addEventListener("click", () => openAutoConfigModal(designDir));
}

export async function openAutoConfigModal(designDir) {
  let res;
  try {
    // Detect the top module from the files the user ticked in the source list
    // only — so a testbench they left unticked is never chosen as top (issue #1).
    const ticked = (state.selectedFiles || []).filter(Boolean);
    res = await api.suggestConfig(designDir, state.selectedPdk || "", state.selectedScl || "", ticked);
  } catch (ex) {
    toast.show("Could not analyse the design: " + ex.message, "error");
    return;
  }
  if (res.ok === false) {
    toast.show(res.error || "Could not derive a config.", "warn");
    return;
  }
  const cfg = res.config || {};
  const meta = res.meta || {};
  const notes = (meta.notes || []).map((n) => "<li>" + fmt.escape(n) + "</li>").join("");
  const detected =
    "<dl class='ac-detected'>" +
    "<div><dt>Top module</dt><dd>" + fmt.escape(meta.top || "— not found —") + "</dd></div>" +
    "<div><dt>Clock port</dt><dd>" + fmt.escape(meta.clock_port || "— none (combinational?) —") + "</dd></div>" +
    "<div><dt>Sources</dt><dd>" + (meta.verilog_count || 0) + " Verilog" +
      (meta.vhdl_count ? ", " + meta.vhdl_count + " VHDL" : "") + "</dd></div>" +
    (meta.top_candidates && meta.top_candidates.length > 1
      ? "<div><dt>Other tops</dt><dd>" + fmt.escape(meta.top_candidates.join(", ")) + "</dd></div>"
      : "") +
    "</dl>";

  const backdrop = document.createElement("div");
  backdrop.className = "smodal-backdrop";
  backdrop.innerHTML =
    "<div class='smodal ac-modal'>" +
    "<div class='smodal-head'>" +
    "<span class='smodal-title'>Auto-generate config</span>" +
    "<span class='smodal-spacer'></span>" +
    "<button class='btn btn-ghost' id='ac-close'>✕</button>" +
    "</div>" +
    "<div class='ac-body'>" +
    "<p class='hint'>Detected from your RTL. Edit the JSON below if anything is wrong, then write it.</p>" +
    detected +
    (notes ? "<ul class='ac-notes'>" + notes + "</ul>" : "") +
    "<label class='ac-label'>config.json (editable)</label>" +
    "<textarea id='ac-json' class='ac-json' spellcheck='false'></textarea>" +
    "<div class='ac-actions'>" +
    "<label class='ac-fmt'>Format <select id='ac-format'>" +
      "<option value='json'>config.json</option>" +
      "<option value='yaml'>config.yaml</option>" +
    "</select></label>" +
    "<span class='smodal-spacer'></span>" +
    "<button class='btn btn-ghost' id='ac-cancel'>Cancel</button>" +
    "<button class='btn btn-primary' id='ac-write'>Write config</button>" +
    "</div>" +
    "<div id='ac-error' class='ac-error' hidden></div>" +
    "</div>" +
    "</div>";
  document.body.appendChild(backdrop);
  const ta = backdrop.querySelector("#ac-json");
  ta.value = JSON.stringify(cfg, null, 2);

  const close = () => backdrop.remove();
  backdrop.querySelector("#ac-close")?.addEventListener("click", close);
  backdrop.querySelector("#ac-cancel")?.addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", function esc(e) {
    if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); }
  });

  backdrop.querySelector("#ac-write")?.addEventListener("click", async () => {
    const errEl = backdrop.querySelector("#ac-error");
    errEl.hidden = true;
    let parsed;
    try {
      parsed = JSON.parse(ta.value);
    } catch (ex) {
      errEl.hidden = false;
      errEl.textContent = "Invalid JSON: " + ex.message;
      return;
    }
    const format = backdrop.querySelector("#ac-format").value;
    try {
      const out = await api.writeConfig(designDir, parsed, format, false);
      close();
      toast.show("Wrote " + (out.path ? out.path.split(/[/\\]/).pop() : "config") +
        " — press Run to harden the design.", "success");
      // Re-adopt the design so the missing-config banner clears and run unlocks.
      const { adoptDesignDir } = await import("./setup.js");
      await adoptDesignDir(designDir, { explicit: true });
    } catch (ex) {
      errEl.hidden = false;
      errEl.textContent = ex.message + (ex.status === 400 && /exists/.test(ex.message)
        ? " (a config already exists — close this and edit it in the IDE instead)" : "");
    }
  });
}
