// api.js — thin REST + SSE client.
// All paths are relative to the host (same-origin). SSE keeps a long-lived
// EventSource so we don't poll. The bus of installer events is folded into
// the same stream by the server.

const base = "";

// Default request timeout. A hung/slow server must not freeze the UI forever:
// AbortController fires after this and the call rejects with a clear message.
const _FETCH_TIMEOUT_MS = 30000;

async function _fetch(path, init) {
  init = init || {};
  const headers = Object.assign({
    "Content-Type": "application/json",
    "X-Requested-With": "XMLHttpRequest"
  }, init.headers || {});
  // Per-call AbortController + timeout (init.timeout overrides; init.signal still honoured).
  const ctrl = (typeof AbortController !== "undefined") ? new AbortController() : null;
  const ms = init.timeout || _FETCH_TIMEOUT_MS;
  let timer = null;
  if (ctrl) timer = setTimeout(() => ctrl.abort(), ms);
  let resp;
  try {
    resp = await fetch(base + path, {
      ...init,
      headers,
      signal: init.signal || (ctrl ? ctrl.signal : undefined),
    });
  } catch (e) {
    if (timer) clearTimeout(timer);
    if (e && e.name === "AbortError") {
      const err = new Error("request timed out — is the server still running?");
      err.status = 0;
      throw err;
    }
    throw e;
  }
  if (timer) clearTimeout(timer);
  let body;
  try { body = await resp.json(); } catch (_e) { body = { ok: false, error: "non-json response" }; }
  if (!resp.ok || body.ok === false) {
    const err = new Error(body.error || "HTTP " + resp.status);
    err.status = resp.status;
    err.body = body;
    throw err;
  }
  return body.data !== undefined ? body.data : body;
}

export const api = {
  health: () => _fetch("/api/health"),
  steps:  () => _fetch("/api/steps"),
  step:   (id) => _fetch("/api/step/" + encodeURIComponent(id)),
  variables: () => _fetch("/api/variables"),
  designFormats: () => _fetch("/api/design-formats"),
  flows: () => _fetch("/api/flows"),
  pdks:  () => _fetch("/api/pdks"),
  scls:  (pdk) => _fetch("/api/scls?pdk=" + encodeURIComponent(pdk)),
  pdkReady: (pdk, scl, runMode) =>
    _fetch(
      "/api/pdk-ready?pdk=" + encodeURIComponent(pdk) +
      "&scl=" + encodeURIComponent(scl) +
      "&run_mode=" + encodeURIComponent(runMode || "container"),
    ),
  preflight: (pdk, scl, runMode) =>
    _fetch(
      "/api/preflight?pdk=" + encodeURIComponent(pdk || "") +
      "&scl=" + encodeURIComponent(scl || "") +
      "&run_mode=" + encodeURIComponent(runMode || "container"),
    ),
  metricsCatalog: () => _fetch("/api/metrics-catalog"),
  containerPull: () => _fetch("/api/container/pull", { method: "POST", body: "{}" }),
  enableDockerGroup: () => _fetch("/api/container/enable-docker-group", { method: "POST", body: "{}" }),
  runs:  (designDir) => _fetch("/api/runs" + (designDir ? "?design_dir=" + encodeURIComponent(designDir) : "")),
  knownDesigns: () => _fetch("/api/known-designs"),
  run:   (tag) => _fetch("/api/runs/" + encodeURIComponent(tag)),
  runStepLog: (step, tag) =>
    _fetch(
      "/api/run-step-log?step=" + encodeURIComponent(step) +
      (tag ? "&tag=" + encodeURIComponent(tag) : ""),
    ),
  runFiles: (tag) => _fetch("/api/run-files?tag=" + encodeURIComponent(tag)),
  runImages: (tag) => _fetch("/api/run-images?tag=" + encodeURIComponent(tag)),
  runOutputs: (tag) => _fetch("/api/run-outputs?tag=" + encodeURIComponent(tag)),
  runDiagrams: (tag) => _fetch("/api/run-diagrams?tag=" + encodeURIComponent(tag)),
  renderDot: (tag, path, force) =>
    _fetch("/api/render-dot?tag=" + encodeURIComponent(tag) + "&path=" + encodeURIComponent(path) +
      (force ? "&force=1" : "")),
  revealFile: (tag, path) =>
    _fetch("/api/reveal", { method: "POST", body: JSON.stringify({ tag, path }) }),
  desktopTools: () => _fetch("/api/desktop-tools"),
  containerTools: () => _fetch("/api/container-tools"),
  openInTool: (tool, tag, path, useTech, location) =>
    _fetch("/api/open-in-tool", { method: "POST", body: JSON.stringify({
      tool, tag, path, use_tech: useTech !== false, location: location || "host" }) }),
  openInContainerTool: (tool, tag) =>
    _fetch("/api/open-in-tool", { method: "POST", body: JSON.stringify({
      tool, tag, location: "container" }) }),
  runFileUrl: (tag, path) =>
    "/api/run-file?tag=" + encodeURIComponent(tag) + "&path=" + encodeURIComponent(path),
  deleteRun: (tag) => _fetch("/api/run-delete", { method: "POST", body: JSON.stringify({ tag }) }),
  runNote: (tag) => _fetch("/api/run-note?tag=" + encodeURIComponent(tag)),
  setRunNote: (tag, note) => _fetch("/api/run-note", { method: "POST", body: JSON.stringify({ tag, note }) }),
  runBundleUrl: (tag, include) =>
    "/api/run-bundle?tag=" + encodeURIComponent(tag) +
    (Array.isArray(include) && include.length ? "&include=" + encodeURIComponent(include.join(",")) : ""),
  trends: (designDir, keys) =>
    _fetch("/api/trends" + (designDir ? "?design_dir=" + encodeURIComponent(designDir) : "") +
      (keys && keys.length ? (designDir ? "&" : "?") + "keys=" + encodeURIComponent(keys.join(",")) : "")),
  designDir: () => _fetch("/api/design-dir"),
  setDesignDir: (path) => _fetch("/api/set-design-dir", { method: "POST", body: JSON.stringify({ path }) }),
  diffRuns: (a, b) => _fetch("/api/diff", { method: "POST", body: JSON.stringify({ a, b }) }),
  explain: (message) => _fetch("/api/explain", { method: "POST", body: JSON.stringify({ message }) }),
  explainChecker: (checker, metric) =>
    _fetch("/api/explain-checker", { method: "POST", body: JSON.stringify({ checker, metric }) }),
  startRun: (payload) => _fetch("/api/run/start", { method: "POST", body: JSON.stringify(payload) }),
  cancelRun: () => _fetch("/api/run/cancel", { method: "POST", body: "{}" }),
  pauseRun:  () => _fetch("/api/run/pause",  { method: "POST", body: "{}" }),
  resumeRun: () => _fetch("/api/run/resume", { method: "POST", body: "{}" }),
  runStatus: () => _fetch("/api/run/status"),
  reportsDrc: (path) => _fetch("/api/reports/drc?path=" + encodeURIComponent(path)),
  reportsLvs: (path) => _fetch("/api/reports/lvs?path=" + encodeURIComponent(path)),
  getPdkRoot: () => _fetch("/api/settings/pdk-root"),
  setPdkRoot: (pdk_root) => _fetch("/api/settings/pdk-root", { method: "POST", body: JSON.stringify({ pdk_root }) }),
  reproducible: (step_id) => _fetch("/api/reproducible", { method: "POST", body: JSON.stringify({ step_id }) }),

  // ---------- manual / advanced (allow-listed console + CLI reveal)
  cliCommand: (payload) => _fetch("/api/cli-command", { method: "POST", body: JSON.stringify(payload || {}) }),
  manualRun: (command) => _fetch("/api/manual/run", { method: "POST", body: JSON.stringify({ command }) }),
  manualCancel: () => _fetch("/api/manual/cancel", { method: "POST", body: "{}" }),
  manualResult: () => _fetch("/api/manual/result"),

  tools: () => _fetch("/api/tools"),
  installTool: (key) =>
    _fetch("/api/tools/install/" + encodeURIComponent(key), { method: "POST", body: "{}" }),
  cancelInstall: (key) => _fetch("/api/tools/cancel", { method: "POST", body: JSON.stringify({ key }) }),
  uninstallTool: (key) =>
    _fetch("/api/tools/uninstall/" + encodeURIComponent(key), { method: "POST", body: "{}" }),
  installCiel: (pdk, libraries) =>
    _fetch("/api/tools/install-ciel", { method: "POST", body: JSON.stringify({ pdk, libraries }) }),
  uninstallPdk: (pdk) =>
    _fetch("/api/pdk/uninstall", { method: "POST", body: JSON.stringify({ pdk }) }),

  copySpm: (designDir) =>
    _fetch("/api/copy-spm", { method: "POST", body: JSON.stringify({ design_dir: designDir }) }),

  // ---------- DSE resource preflight (warn before N heavy full-flow runs)
  systemResources: () => _fetch("/api/system-resources"),

  // ---------- auto-config (design has no config.{json,yaml,tcl})
  // POST so the tick-marked source list (which can be long) goes in the body —
  // the top module is detected from those files only, never from an unticked
  // testbench. `files` = abs or design-relative paths; omit to scan everything.
  suggestConfig: (path, pdk, scl, files) =>
    _fetch("/api/suggest-config", {
      method: "POST",
      body: JSON.stringify({ path: path || "", pdk: pdk || "", scl: scl || "",
        files: Array.isArray(files) ? files : [] }),
    }),
  writeConfig: (path, config, format, overwrite) =>
    _fetch("/api/write-config", {
      method: "POST",
      body: JSON.stringify({ path, config, format: format || "json", overwrite: !!overwrite }),
    }),

  // ---------- filesystem + sources
  fsRoots: () => _fetch("/api/fs/roots"),
  fsList: (path) => _fetch("/api/fs/list?path=" + encodeURIComponent(path)),
  walkSources: (path) => _fetch("/api/walk-sources?path=" + encodeURIComponent(path)),
  runReports: (designDir, runTag) =>
    _fetch(
      "/api/run-reports?design_dir=" + encodeURIComponent(designDir) + "&run_tag=" + encodeURIComponent(runTag),
    ),
  readText: (path) => _fetch("/api/read-text?path=" + encodeURIComponent(path)),

  // ---------- Phase 0: project wizard + export
  templates: () => _fetch("/api/templates"),
  projectNew: (payload) =>
    _fetch("/api/project/new", { method: "POST", body: JSON.stringify(payload) }),
  runExportUrl: (tag, fmt) =>
    "/api/run-export?tag=" + encodeURIComponent(tag) + "&fmt=" + encodeURIComponent(fmt || "csv"),

  // ---------- Phase 1: verification + compare + cells
  verify: (tag) => _fetch("/api/verify" + (tag ? "?tag=" + encodeURIComponent(tag) : "")),
  compare: (tags, runDirs) => _fetch("/api/compare", { method: "POST",
    body: JSON.stringify({ tags, run_dirs: runDirs || [] }) }),
  cellUsage: (tag) => _fetch("/api/cell-usage?tag=" + encodeURIComponent(tag)),
  timingPaths: (tag, kind, limit) =>
    _fetch("/api/timing-paths?kind=" + encodeURIComponent(kind || "setup") +
      (tag ? "&tag=" + encodeURIComponent(tag) : "") +
      (limit ? "&limit=" + encodeURIComponent(limit) : "")),

  // ---------- Phase 2: re-verify + DSE
  verifyRerun: (payload) =>
    _fetch("/api/verify/rerun", { method: "POST", body: JSON.stringify(payload) }),
  dseStart: (payload) => _fetch("/api/dse/start", { method: "POST", body: JSON.stringify(payload) }),
  dseCancel: () => _fetch("/api/dse/cancel", { method: "POST", body: "{}" }),
  dseStatus: () => _fetch("/api/dse/status"),
  dseSweeps: () => _fetch("/api/dse/sweeps"),

  // ---------- Phase 3: editor + lint + sim
  fileWrite: (rel_path, content) =>
    _fetch("/api/file/write", { method: "POST", body: JSON.stringify({ rel_path, content }) }),
  fileDelete: (rel_path) =>
    _fetch("/api/file/delete", { method: "POST", body: JSON.stringify({ rel_path }) }),
  lintStart: (payload) =>
    _fetch("/api/lint", { method: "POST", body: JSON.stringify(payload || {}) }),
  simTestbenches: (designDir) =>
    _fetch("/api/sim/testbenches" + (designDir ? "?design_dir=" + encodeURIComponent(designDir) : "")),
  simStart: (payload) => _fetch("/api/sim/start", { method: "POST", body: JSON.stringify(payload) }),
  simCancel: () => _fetch("/api/sim/cancel", { method: "POST", body: "{}" }),
  waveformUrl: (path) => "/api/waveform?path=" + encodeURIComponent(path),

  // ---------- Phase 4: viewers + plugins
  // (2D/3D layout = the flow's KLayout PNG + "Open in desktop tool"; the old
  //  in-browser klayout-render endpoints were removed — see desktop.py.)
  cells: (pdk, scl) =>
    _fetch("/api/cells?pdk=" + encodeURIComponent(pdk || "") + "&scl=" + encodeURIComponent(scl || "")),
  // ---------- custom cells (advanced cell swap-out, per run)
  customCells: (designDir) =>
    _fetch("/api/custom-cells" + (designDir ? "?design_dir=" + encodeURIComponent(designDir) : "")),
  customCellSave: (payload) =>
    _fetch("/api/custom-cells/save", { method: "POST", body: JSON.stringify(payload) }),
  customCellRemove: (name, designDir) =>
    _fetch("/api/custom-cells/remove", { method: "POST", body: JSON.stringify({ name, design_dir: designDir }) }),
  customCellEnable: (name, enabled, designDir) =>
    _fetch("/api/custom-cells/enable", { method: "POST", body: JSON.stringify({ name, enabled, design_dir: designDir }) }),
  // ---------- custom macros (hard-macro insertion via MACROS, per run)
  customMacros: (designDir) =>
    _fetch("/api/custom-macros" + (designDir ? "?design_dir=" + encodeURIComponent(designDir) : "")),
  customMacroSave: (payload) =>
    _fetch("/api/custom-macros/save", { method: "POST", body: JSON.stringify(payload) }),
  customMacroRemove: (name, designDir) =>
    _fetch("/api/custom-macros/remove", { method: "POST", body: JSON.stringify({ name, design_dir: designDir }) }),
  customMacroEnable: (name, enabled, designDir) =>
    _fetch("/api/custom-macros/enable", { method: "POST", body: JSON.stringify({ name, enabled, design_dir: designDir }) }),
  pluginsRegistry: () => _fetch("/api/plugins/registry"),
  pluginsInstalled: () => _fetch("/api/plugins/installed"),
  pluginInstall: (id) => _fetch("/api/plugins/install", { method: "POST", body: JSON.stringify({ id }) }),
  pluginRemove: (id) => _fetch("/api/plugins/remove", { method: "POST", body: JSON.stringify({ id }) }),
  pluginEnable: (id, enabled) =>
    _fetch("/api/plugins/enable", { method: "POST", body: JSON.stringify({ id, enabled }) }),
};

// ----------------------------- SSE ------------------------------------------

let _es = null;
let _handlers = [];

export const sse = {
  open() {
    if (_es) return;
    try {
      _es = new EventSource("/api/events");
    } catch (e) {
      console.warn("EventSource unavailable", e);
      return;
    }
  },
  on(fn) {
    if (_handlers.length === 0) _wire(_es);
    _handlers.push(fn);
  },
};

function _wire(es) {
  if (!es) return;
  es.addEventListener("hello", (e) => {
    try { _broadcast({ type: "hello", data: JSON.parse(e.data) }); } catch (_) {}
  });
  es.addEventListener("ping", () => {
    /* keep-alive */
  });
  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      _broadcast(Object.assign({ type: data.type || "info" }, data));
    } catch (_) {}
  };
  es.addEventListener("end", () => { /* server closes the stream after flow_done */ });
}

function _broadcast(ev) {
  // Iterate a copy so a handler that registers another handler mid-dispatch
  // can't corrupt the loop.
  for (const h of [..._handlers]) {
    try { h(ev); } catch (e) { console.error("sse handler", e); }
  }
}

// ----------------------------- formatting -----------------------------------

const _AMP = String.fromCharCode(38);
const _LT = String.fromCharCode(60);
const _GT = String.fromCharCode(62);
const _QUOT = String.fromCharCode(34);
const _APOS = String.fromCharCode(39);
const _ESCAPE = {
  [_AMP]: _AMP + "amp;",
  [_LT]: _LT + "lt;",
  [_GT]: _GT + "gt;",
  [_QUOT]: _QUOT + "quot;",
  [_APOS]: _APOS + "#39;",
};

export const fmt = {
  escape(s) {
    return String(s).replace(/[&<>"']/g, (c) => _ESCAPE[c] || c);
  },
  metric(value) {
    if (value === null || value === undefined) return "—";
    // Non-finite metrics are genuine in LibreLane (e.g. timing__setup_r2r__ws is
    // +∞ when a design has no register-to-register paths). The server stringifies
    // them via _json_safe; humanise rather than print raw "Infinity"/"NaN".
    if (value === "Infinity" || value === Infinity) return "∞";
    if (value === "-Infinity" || value === -Infinity) return "−∞";
    if (value === "NaN" || (typeof value === "number" && Number.isNaN(value))) return "n/a";
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return value > 0 ? "∞" : "−∞";
      if (Math.abs(value) < 100) return value.toFixed(3);
      return Math.round(value).toLocaleString();
    }
    return String(value);
  },
  shortPath(p) {
    if (!p) return "";
    const s = String(p);
    return s.length <= 60 ? s : "…" + s.slice(-57);
  },
};
