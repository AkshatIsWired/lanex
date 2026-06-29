// preview.js — render selected run's views into the Preview tab.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";
import { gatherRunsScoped, getRunScope, runOptionsHtml, scopeToggleHtml, wireScopeToggle, ensureActiveDesignFor } from "./runscope.js";
import { wireJump } from "./jumpnav.js";
import { icon } from "./icons.js";

let _currentTag;
let _wired = false;
// tag -> run row (carries _design) for the active picker, so a cross-design pick
// can switch the active design before fetching that run's views.
let _runIndex = {};
let _previewRuns = [];
// Monotonic token: each refreshView() bumps it, and async appenders bail if a
// newer refresh has started. Without this, several overlapping refreshes (the
// tab can be re-entered repeatedly) each cleared-then-appended, so the layout
// image and synthesis diagrams showed up 3-4× stacked.
let _epoch = 0;
const _CAT_ICON = { Layout: "grid", Netlist: "plug", Timing: "clock", Reports: "chart", Other: "box" };

function fmtBytes(n) {
  if (!n) return "0 B";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}


// Browse / download / reveal every deliverable the run wrote to final/.
async function renderOutputs(tag) {
  const root = document.getElementById("view-outputs");
  if (!root) return;
  if (!tag) { root.innerHTML = "<div class='muted'>Pick a run to list its output files.</div>"; return; }
  root.innerHTML = "<div class='muted'>loading outputs…</div>";
  let outs = [];
  try {
    const r = await api.runOutputs(tag);
    outs = (r && r.outputs) || [];
  } catch (_e) {
    root.innerHTML = "<div class='muted'>Could not list outputs for this run.</div>";
    return;
  }
  if (!outs.length) {
    root.innerHTML = "<div class='muted'>No final outputs found — this run may not have completed.</div>";
    return;
  }
  // Group by category, preserving the backend's order.
  const groups = new Map();
  for (const o of outs) {
    if (!groups.has(o.category)) groups.set(o.category, []);
    groups.get(o.category).push(o);
  }
  let html = "";
  for (const [cat, items] of groups) {
    html +=
      "<details class='card out-cat' open><summary><strong>" +
      "<span class='out-cat-ico'>" + icon(_CAT_ICON[cat] || "box", {size:15}) + "</span> " + fmt.escape(cat) +
      "</strong><span class='hint'>" + items.length + " file" + (items.length === 1 ? "" : "s") + "</span></summary>" +
      "<div class='card-body'><div class='out-list'>" +
      items.map((o) => {
        const url = api.runFileUrl(tag, o.path);
        const sub = (o.variant ? "<span class='out-variant'>" + fmt.escape(o.variant) + "</span> " : "") +
          "<span class='out-path'>" + fmt.escape(o.path) + "</span>";
        return (
          "<div class='out-row'>" +
          "<div class='out-meta'><div class='out-label'>" + fmt.escape(o.label) + "</div>" +
          "<div class='out-sub'>" + sub + " · " + fmtBytes(o.size) + "</div></div>" +
          "<div class='out-actions'>" +
          "<a class='btn btn-ghost' href='" + url + "' target='_blank' rel='noopener' download='" + fmt.escape(o.name) + "'>⬇ Download</a>" +
          "<button class='btn btn-ghost out-reveal' data-path='" + fmt.escape(o.path) + "'>" + icon('folderOpen',{size:13}) + " Reveal</button>" +
          "</div></div>"
        );
      }).join("") +
      "</div></div></details>";
  }
  root.innerHTML = html;
  root.querySelectorAll(".out-reveal").forEach((b) => {
    b.addEventListener("click", async () => {
      try {
        const res = await api.revealFile(tag, b.dataset.path);
        toast.show("Opened " + (res.opened || "file manager"), "success");
      } catch (ex) {
        toast.show("Reveal not available: " + (ex.message || ex), "warn");
      }
    });
  });
}

export async function renderPreview() {
  const tag = document.getElementById("view-tag");
  if (!tag) return;
  // Refresh the run list — scoped by the GLOBAL run-scope pref (this design vs
  // all designs) so the dropdown matches every other tab. Best-effort.
  let runs = [];
  try { runs = await gatherRunsScoped(); } catch (_e) {}
  _runIndex = {};
  for (const r of runs) _runIndex[r.tag] = r;
  if (getRunScope() === "design") state.runs = runs;
  _previewRuns = runs;
  // Inject the "All designs" scope checkbox once, next to the run <select>.
  if (!tag.parentNode.querySelector("#preview-run-scope")) {
    tag.insertAdjacentHTML("afterend", " " + scopeToggleHtml("preview-run-scope"));
    wireScopeToggle("preview-run-scope", () => renderPreview());
  }
  syncTagDropdown();
  syncFormatDropdown();
  wireJump(document.getElementById("sec-preview"));
  // Bind interaction handlers exactly once — renderPreview() is called on every
  // Preview-tab activation + on flow_done, and re-binding stacked duplicate
  // listeners (each firing its own refresh → duplicated output).
  if (!_wired) {
    _wired = true;
    document.getElementById("view-render")?.addEventListener("click", renderLayout);
    tag.addEventListener("change", async () => {
      await ensureActiveDesignFor(_runIndex[tag.value]);
      refreshView();
    });
    document.getElementById("view-format")?.addEventListener("change", () => refreshView());
  }
  refreshView();
}

export function selectRun(tag) {
  _currentTag = tag;
  const tagSel = document.getElementById("view-tag");
  if (tagSel) {
    tagSel.value = tag;
    refreshView();
  }
}

function syncTagDropdown() {
  const sel = document.getElementById("view-tag");
  const oldVal = sel.value || _currentTag;
  const runs = _previewRuns.length ? _previewRuns : (state.runs || []);
  sel.innerHTML = "<option value=''>— pick a run —</option>" + runOptionsHtml(runs, oldVal, fmt.escape);
  if (oldVal && _runIndex[oldVal]) sel.value = oldVal;
}

function syncFormatDropdown() {
  const sel = document.getElementById("view-format");
  sel.innerHTML = "";
  // Curated order: PNG first, then DEF, GDS, NL, SPEF, LEF…
  const order = ["render", "gds", "def", "nl", "lef", "spef", "sdf", "lib", "sdc"];
  const seen = new Set();
  for (const id of order) {
    const df = state.designFormats.find((x) => x.id === id);
    if (df && !seen.has(df.id)) {
      seen.add(df.id);
      const o = document.createElement("option");
      o.value = df.id;
      o.textContent = df.id + " — " + df.full_name;
      sel.appendChild(o);
    }
  }
  for (const df of state.designFormats) {
    if (seen.has(df.id)) continue;
    seen.add(df.id);
    const o = document.createElement("option");
    o.value = df.id;
    o.textContent = df.id;
    sel.appendChild(o);
  }
}

function galleryEl() {
  let g = document.getElementById("view-gallery");
  if (!g) {
    const area = document.getElementById("view-render-area");
    if (!area || !area.parentNode) return null;
    g = document.createElement("div");
    g.id = "view-gallery";
    g.className = "view-gallery";
    area.parentNode.insertBefore(g, area);
  }
  return g;
}

// Show every image the run produced (final GDS render + any per-stage
// renders), grouped by the step that made it. LibreLane's Classic flow renders
// only the final layout by default, so usually that's the one image — the
// gallery still gives one clear place to see it and any extras.
async function renderGallery(tag, ep) {
  const g = galleryEl();
  if (!g) return;
  if (!tag) { g.innerHTML = ""; return; }
  g.innerHTML = "<div class='muted'>loading images…</div>";
  let imgs = [];
  try {
    const r = await api.runImages(tag);
    imgs = (r && r.images) || [];
  } catch (_e) {
    g.innerHTML = "";
    return;
  }
  if (ep !== undefined && ep !== _epoch) return;   // superseded by a newer refresh
  if (!imgs.length) {
    g.innerHTML =
      "<div class='muted'>No rendered images in this run. LibreLane's Classic flow renders only the " +
      "final layout; enable extra <code>KLayout.Render</code> steps for post-synthesis / post-CTS / " +
      "post-route snapshots.</div>";
    return;
  }
  imgs.sort((a, b) => (a.step === "final" ? -1 : b.step === "final" ? 1 : 0));
  g.innerHTML =
    "<h3 class='rt-graph-h'>Layout images</h3><div class='view-gallery-grid'>" +
    imgs.map((im) => {
      const url = api.runFileUrl(tag, im.path);
      return (
        "<figure class='view-thumb'><a href='" + url + "' target='_blank' rel='noopener'>" +
        "<img loading='lazy' src='" + url + "' alt='" + fmt.escape(im.step) + "'/></a>" +
        "<figcaption>" + fmt.escape(im.step || im.name) + "</figcaption></figure>"
      );
    }).join("") +
    "</div>";
}

// Synthesis schematics (Yosys DOT). Rendered to SVG server-side via graphviz;
// falls back to a .dot download when graphviz isn't on the host. Empty -> a
// clear note that SYNTH_SHOW must be enabled to generate them.
async function renderDiagrams(tag, ep) {
  const root = document.getElementById("view-diagrams");
  if (!root) return;
  if (!tag) { root.innerHTML = ""; return; }
  root.innerHTML = "<div class='muted'>loading diagrams…</div>";
  let diags = [];
  try {
    const r = await api.runDiagrams(tag);
    diags = (r && r.diagrams) || [];
  } catch (_e) {
    root.innerHTML = "";
    return;
  }
  if (ep !== undefined && ep !== _epoch) return;   // superseded by a newer refresh
  if (!diags.length) {
    root.innerHTML =
      "<div class='muted'>No synthesis diagrams in this run. Enable <code>SYNTH_SHOW</code> on the " +
      "Config tab, then re-run — Yosys will emit a design-hierarchy and a gate-level schematic.</div>";
    return;
  }
  root.innerHTML = "";
  for (const d of diags) {
    const card = document.createElement("figure");
    card.className = "diagram-card";
    const dotUrl = api.runFileUrl(tag, d.path);
    const sizeKb = d.size ? " · " + Math.round(d.size / 1000) + " KB" : "";
    card.innerHTML =
      "<figcaption><strong>" + fmt.escape(d.label) + "</strong> " +
      "<span class='muted'>" + fmt.escape(d.step) + " · " + fmt.escape(d.name) + sizeKb + "</span></figcaption>" +
      "<div class='diagram-body muted'></div>" +
      "<div class='diagram-actions'>" +
      "<a class='btn btn-ghost' href='" + dotUrl + "' target='_blank' rel='noopener' download='" + fmt.escape(d.name) + "'>⬇ .dot</a>" +
      "</div>";
    root.appendChild(card);
    const body = card.querySelector(".diagram-body");
    const actions = card.querySelector(".diagram-actions");
    // Big gate-level schematics are render-on-demand: auto-rendering one can
    // freeze the browser (and used to OOM the host's dot). Show a button.
    if (d.large) {
      body.textContent = "Large diagram — rendering may be slow.";
      const go = document.createElement("button");
      go.className = "btn btn-ghost";
      go.textContent = "Render anyway";
      go.addEventListener("click", () => { go.remove(); doRenderDot(tag, d, body, actions, true); });
      actions.appendChild(go);
    } else {
      body.classList.add("muted");
      body.textContent = "rendering…";
      doRenderDot(tag, d, body, actions, false);
    }
  }
}

async function doRenderDot(tag, d, body, actions, force) {
  body.classList.add("muted");
  body.textContent = "rendering…";
  let res;
  try {
    res = await api.renderDot(tag, d.path, force);
  } catch (ex) {
    body.classList.remove("muted");
    body.textContent = "Render failed: " + (ex.message || ex);
    return;
  }
  if (res && res.ok && res.svg) {
    const svgUrl = api.runFileUrl(tag, res.svg);
    body.classList.remove("muted");
    body.innerHTML =
      "<a href='" + svgUrl + "' target='_blank' rel='noopener'>" +
      "<img loading='lazy' src='" + svgUrl + "' alt='" + fmt.escape(d.label) + "'/></a>";
    if (!actions.querySelector(".svg-dl")) {
      const a = document.createElement("a");
      a.className = "btn btn-ghost svg-dl";
      a.href = svgUrl; a.target = "_blank"; a.rel = "noopener";
      a.setAttribute("download", d.name.replace(/\.dot$/, "") + ".svg");
      a.textContent = "⬇ .svg";
      actions.appendChild(a);
    }
    return;
  }
  // Render refused (too large / graphviz missing) — keep it honest + offer retry.
  body.classList.remove("muted");
  body.textContent = (res && res.error) || "Could not render this diagram.";
  if (res && res.too_large && !force && !actions.querySelector(".force-dl")) {
    const go = document.createElement("button");
    go.className = "btn btn-ghost force-dl";
    go.textContent = "Render anyway";
    go.addEventListener("click", () => { go.remove(); doRenderDot(tag, d, body, actions, true); });
    actions.appendChild(go);
  }
  // Graphviz isn't installed — offer a one-click install (same path as Tools).
  if (res && res.need === "graphviz" && !actions.querySelector(".install-gv")) {
    const gv = document.createElement("button");
    gv.className = "btn btn-primary install-gv";
    gv.textContent = "Install graphviz";
    gv.addEventListener("click", async () => {
      gv.disabled = true; gv.textContent = "Installing graphviz… (see Install logs)";
      try {
        const r = await api.installTool("graphviz");
        if (r && r.in_progress) toast.show("graphviz install already running — see Install logs.", "info");
        else if (r && r.ok === false) toast.show(r.guidance || r.reason || "Couldn't install graphviz automatically.", "warn");
        else { toast.show("graphviz installing — retry the render when it finishes.", "success"); }
      } catch (ex) {
        toast.show("Could not start graphviz install: " + (ex.message || ex), "error");
      }
      gv.disabled = false; gv.textContent = "Retry after install";
      gv.onclick = () => { gv.remove(); doRenderDot(tag, d, body, actions, force); };
    });
    actions.appendChild(gv);
  }
}

async function refreshView() {
  const ep = ++_epoch;
  const tag = document.getElementById("view-tag")?.value;
  const fmtId = document.getElementById("view-format")?.value;
  const area = document.getElementById("view-render-area");
  const text = document.getElementById("view-text");
  renderGallery(tag, ep);
  renderDiagrams(tag, ep);
  renderOutputs(tag);
  if (area) area.innerHTML = "";
  if (text) text.textContent = "";
  if (!tag || !fmtId) {
    if (area) area.innerHTML = "<div class='empty'><span class='ico'>" + icon('image',{size:40}) + "</span><h3>Pick a run + format</h3><p>The Preview tab lights up after you complete a run.</p></div>";
    return;
  }
  const url = "/api/views/" + encodeURIComponent(tag) + "/" + encodeURIComponent(fmtId);
  const dl = document.getElementById("view-download");
  try {
    const resp = await fetch(url);
    if (!resp.ok) {
      if (text) text.textContent = "(no view at " + url + ")";
      if (dl) dl.hidden = true;
      return;
    }
    if (dl) {
      dl.hidden = false;
      dl.href = url;
      dl.setAttribute("download", tag + "-" + fmtId);
    }
    const blob = await resp.blob();
    const ct = resp.headers.get("Content-Type") || "";
    if (ct.startsWith("image/")) {
      const img = document.createElement("img");
      img.src = url;
      img.alt = fmtId;
      area.appendChild(img);
    } else {
      const text_ = await blob.text();
      // Shared viewer → adds find-in-text (download stays on the bar above).
      const { renderFileText } = await import("./fileview.js");
      renderFileText(text, text_, { emptyMsg: "(empty)" });
    }
  } catch (ex) {
    if (text) text.textContent = "(load failed: " + ex.message + ")";
  }
}

function renderLayout() {
  // Show the layout image the flow's KLayout.Render step produced for this run.
  const tagSel = document.getElementById("view-tag");
  const fmtSel = document.getElementById("view-format");
  const text = document.getElementById("view-text");
  if (!tagSel || !tagSel.value) {
    if (text) text.textContent = "Pick a run first.";
    return;
  }
  // Switch the format to the rendered PNG and refresh.
  if (fmtSel) {
    const hasRender = Array.from(fmtSel.options).some((o) => o.value === "render");
    fmtSel.value = hasRender ? "render" : fmtSel.value;
  }
  refreshView();
}
