// tools.js — the Tools tab: show EDA tool status, install buttons.

import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { renderLogs } from "./logs.js";
import { toast } from "./toast.js";
import { confirmDialog } from "./dialog.js";
import { icon } from "./icons.js";
import { wireJump } from "./jumpnav.js";

export async function renderTools() {
  const root = document.getElementById("tools-grid");
  if (!root) return;
  wireJump(document.getElementById("sec-tools"));   // static section-jump nav (§6.6)
  renderDesktopViewers();
  try {
    const info = await api.tools();
    state.tools = info;
    paint(info);
    const rootInfo = await api.getPdkRoot();
    if (rootInfo.ok && document.getElementById("pdk-root-input")) {
      document.getElementById("pdk-root-input").value = rootInfo.pdk_root;
    }
  } catch (ex) {
    root.innerHTML =
      "<div class='empty'><span class='ico'>" + icon('alert',{size:40}) + "</span><h3>Tool probe failed</h3><p>" + fmt.escape(ex.message) + "</p></div>";
  }
}

// Desktop layout viewers (KLayout / Magic): status only. Both ship in the
// LibreLane container image; the Layout tab launches whichever are installed on
// the run's GDS. The 3D viewer GDS3D lives in the Recommended extra tools group.
async function renderDesktopViewers() {
  const root = document.getElementById("desktop-viewers");
  if (!root) return;
  let tools = [];
  try { tools = (await api.desktopTools()).tools || []; } catch (_e) {}
  const byKey = Object.fromEntries(tools.map((t) => [t.key, t]));
  const badge = (t) => t && t.available
    ? "<span class='pill pill-pass'><span class='d'></span><span class='text'>installed</span></span>"
    : "<span class='pill pill-warn'><span class='d'></span><span class='text'>not found</span></span>";
  root.innerHTML =
    "<div class='card'><div class='card-body'>" +
    "<div class='tool-row'><strong>KLayout</strong> " + badge(byKey.klayout) +
    " <span class='hint'>2D layout — bundled in the container image; or install from klayout.de.</span></div>" +
    "<div class='tool-row'><strong>Magic</strong> " + badge(byKey.magic) +
    " <span class='hint'>2D layout/DRC — bundled in the container image. The GUI launches it with the PDK's <code>.magicrc</code> so layers render.</span></div>" +
    "</div></div>";
}

// Recommended extra tools: the three optional power-ups (iverilog, graphviz,
// gds3d). Native installs use the shared escalating installer — if a system
// package needs sudo, the user is prompted for a password in the launch
// terminal (handled globally by app.js's installer_info banner).
async function renderRecommendedTools(info) {
  const root = document.getElementById("recommended-tools");
  if (!root) return;
  const byKey = Object.fromEntries((info.tools || []).map((t) => [t.key, t]));
  let desktop = {};
  try {
    desktop = Object.fromEntries(((await api.desktopTools()).tools || []).map((t) => [t.key, t]));
  } catch (_e) {}
  const gds3d = desktop.gds3d;

  const probeCard = (t) => {
    if (!t) return "";
    const action = t.installed
      ? "<div style='display:flex;gap:var(--s-2);align-items:center'><span class='pill pill-pass'><span class='d'></span><span class='text'>installed</span></span>" +
        "<button class='rec-uninstall' data-key='" + t.key + "' style='font-size:10px;padding:2px 6px;background:transparent;border:1px solid var(--border);border-radius:var(--r-sm);color:var(--text-muted);cursor:pointer'>Remove</button></div>"
      : (Array.isArray(t.install_recipe) || t.install_recipe
          ? "<button class='btn btn-primary rec-install' data-key='" + t.key + "'>Install</button>"
          : "<span class='muted' style='font-size:var(--t-xs)'>" + fmt.escape(t.install_recipe || "manual install") + "</span>");
    return (
      "<div class='tool-card " + (t.installed ? "installed-installed" : "installed-missing") + "' style='flex:0 0 auto;width:320px'>" +
      "<div class='row1'><span class='name'>" + fmt.escape(t.label) + "</span>" +
      (t.installed ? "<span class='dot-installed' title='installed'></span>" : "<span class='dot-missing' title='missing'></span>") +
      "</div>" +
      "<div class='what'>" + fmt.escape(t.what || "") + "</div>" +
      (t.installed && t.version
        ? "<div class='meta muted' style='font-size:var(--t-xs)' title='reported by the tool'>" + fmt.escape(t.version) + "</div>"
        : "") +
      "<div class='meta' style='margin-top:var(--s-2)'>" + action + "</div>" +
      "</div>"
    );
  };

  const gds3dCard =
    "<div class='tool-card " + (gds3d && gds3d.available ? "installed-installed" : "installed-missing") + "' style='flex:0 0 auto;width:320px'>" +
    "<div class='row1'><span class='name'>GDS3D</span>" +
    (gds3d && gds3d.available ? "<span class='dot-installed' title='installed'></span>" : "<span class='dot-missing' title='missing'></span>") +
    "</div>" +
    "<div class='what'>3D layer-stack viewer (OpenGL). Open-source, built from source once. Open a run's GDS from the <strong>Layout</strong> tab → “3D (desktop viewer)”.</div>" +
    "<div class='meta' style='margin-top:var(--s-2)'>" +
    (gds3d && gds3d.available
      ? "<div style='display:flex;gap:var(--s-2);align-items:center'><span class='pill pill-pass'><span class='d'></span><span class='text'>installed</span></span>" +
        "<button class='btn btn-ghost' id='btn-remove-gds3d' style='font-size:11px;padding:2px 8px'>Remove</button></div>"
      : "<button class='btn btn-primary' id='btn-install-gds3d'>Build &amp; install GDS3D</button>") +
    "</div>" +
    "<details style='margin-top:var(--s-2);font-size:12px'><summary style='cursor:pointer;color:var(--text-muted)'>Manual build (if the one-click build can't run)</summary>" +
    "<p class='hint'>GDS3D has no package release; you build the small OpenGL binary once. It needs the X11 + OpenGL/GLUT dev headers (the build fails with <code>X11/keysym.h: No such file or directory</code> without them). On Debian/Ubuntu/WSL:</p>" +
    "<pre class='code'>sudo apt-get install -y git build-essential libx11-dev libxmu-dev libxi-dev libgl1-mesa-dev libglu1-mesa-dev freeglut3-dev\n" +
    "git clone https://github.com/trilomix/GDS3D\n" +
    "cd GDS3D/linux &amp;&amp; make\n" +
    "sudo cp GDS3D /usr/local/bin/gds3d</pre>" +
    "<p class='hint'>Fedora/RHEL: <code>sudo dnf install -y libX11-devel mesa-libGL-devel mesa-libGLU-devel freeglut-devel gcc-c++ make git</code>. Arch: <code>sudo pacman -S --needed libx11 mesa glu freeglut base-devel git</code>. macOS: the repo's <code>mac/</code> dir has no Makefile — the one-click install uses the prebuilt <code>mac/GDS3D.app</code> it ships (Intel binary; Apple Silicon needs Rosetta 2: <code>softwareupdate --install-rosetta</code>). Windows: download the prebuilt binary from the GDS3D site, then reopen this tab.</p>" +
    "</details></div>";

  root.innerHTML =
    "<div style='display:flex;flex-wrap:wrap;gap:var(--s-4)'>" +
    probeCard(byKey.iverilog) +
    probeCard(byKey.graphviz) +
    gds3dCard +
    "</div>";

  root.querySelectorAll(".rec-install").forEach((b) =>
    b.addEventListener("click", async () => { await installByKey(b.dataset.key); renderTools(); }));
  root.querySelectorAll(".rec-uninstall").forEach((b) =>
    b.addEventListener("click", async () => {
      const key = b.dataset.key;
      if (!(await confirmDialog({ title: "Remove " + key, danger: true, confirmText: "Remove",
        body: "Remove " + key + "?" }))) return;
      try {
        const r = await api.uninstallTool(key);
        toast.show(r.ok ? key + " removed" : key + " remove failed", r.ok ? "info" : "error");
      } catch (ex) { toast.show(key + " remove error: " + (ex.message || ex), "error"); }
      renderTools();
    }));
  document.getElementById("btn-install-gds3d")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true; btn.textContent = "Building GDS3D… (see Install logs)";
    try {
      const r = await api.installTool("gds3d");
      if (r && r.in_progress) toast.show("GDS3D build already running — see Install logs.", "info");
      else if (r && r.ok === false) toast.show(r.guidance || r.error || "Build couldn't start — use the manual steps.", "warn");
      else toast.show("GDS3D build started — watch Install logs; the Layout tab picks it up when done.", "success");
    } catch (ex) {
      toast.show("Could not start GDS3D build: " + (ex.message || ex), "error");
    }
    btn.disabled = false; btn.textContent = "Build & install GDS3D";
  });
  document.getElementById("btn-remove-gds3d")?.addEventListener("click", async () => {
    if (!(await confirmDialog({ title: "Remove GDS3D", danger: true, confirmText: "Remove",
      body: "Remove the GDS3D binary? You can rebuild it any time from this tab." }))) return;
    try {
      const r = await api.uninstallTool("gds3d");
      if (r && r.ok) {
        toast.show("GDS3D removed", "info");
        renderLogs.append({ payload: { message: "✓ GDS3D removed (" + (r.removed || []).join(", ") + ")" } });
      } else {
        toast.show("GDS3D remove failed: " + ((r && r.reason) || "unknown"), "error");
      }
    } catch (ex) {
      toast.show("GDS3D remove error: " + (ex.message || ex), "error");
    }
    renderRecommendedTools(info);
  });
}

// Wire PDK_ROOT save button once
document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btn-save-pdk-root")?.addEventListener("click", async () => {
    const val = document.getElementById("pdk-root-input").value.trim();
    if (!val) return;
    try {
      const res = await api.setPdkRoot(val);
      if (res.ok) {
        toast.show("PDK Directory updated to " + res.pdk_root, "success");
        renderTools();
      } else {
        toast.show("Failed to update PDK directory", "error");
      }
    } catch (ex) {
      toast.show("Error: " + ex.message, "error");
    }
  });
});

function sizeStr(mb, { approx = false } = {}) {
  if (mb == null) return "";
  const s = mb >= 1024 ? (mb / 1024).toFixed(1) + " GB" : Math.round(mb) + " MB";
  return (approx ? "~" : "") + s;
}

// Live image-pull state. The pull runs in a background thread on the server and
// streams `docker pull` stdout over SSE. Over a pipe, docker prints ONE line per
// layer state change (not byte-by-byte), so a single multi-GB layer downloads
// silently for minutes. We therefore (a) keep a ticking elapsed heartbeat,
// (b) count layers from the discrete status lines for real progress, and
// (c) explicitly say "still downloading" during quiet stretches so it never
// looks hung.
const _pull = { active: false, start: 0, timer: null, last: "", lastAt: 0, total: 0, downloaded: 0, pulled: 0, done: false, blobs: null };

function _pullElapsed() {
  return Math.max(0, Math.round((Date.now() - _pull.start) / 1000));
}

function _pullLayerLabel() {
  if (_pull.done) return "all layers complete";
  if (!_pull.total) return "resolving layers…";
  return _pull.pulled + " / " + _pull.total + " layers extracted · " + _pull.downloaded + " downloaded";
}

function pullProgressHtml() {
  return (
    "<div id='runtime-pull' style='width:100%;margin-top:var(--s-2)'>" +
    "<div style='display:flex;align-items:center;gap:var(--s-2)'>" +
    "<span class='spinner-sm'></span>" +
    "<strong>Pulling image…</strong>" +
    "<span class='muted' id='runtime-pull-elapsed'>" + _pullElapsed() + "s</span>" +
    "<span class='muted' id='runtime-pull-layers' style='margin-left:auto'>" + _pullLayerLabel() + "</span>" +
    "</div>" +
    "<div id='runtime-pull-note' class='hint' style='margin-top:4px'></div>" +
    "<pre class='code' id='runtime-pull-line' style='margin-top:var(--s-2);max-height:120px;overflow:auto;white-space:pre-wrap'>" +
    fmt.escape(_pull.last || "starting…") +
    "</pre>" +
    "<div style='display:flex;align-items:center;gap:var(--s-3)'>" +
    "<p class='hint' style='margin:0;flex:1'>~3 GB, downloaded once. Large layers stream silently — the timer above is your sign it's still working. You can leave this tab.</p>" +
    "<button class='btn btn-ghost' id='runtime-pull-cancel' style='font-size:11px;padding:2px 8px' " +
    "title='Stops the download. Already-fetched layers stay cached, so a retry resumes.'>Cancel</button>" +
    "</div>" +
    "</div>"
  );
}

function _pullTicker() {
  clearInterval(_pull.timer);
  _pull.timer = setInterval(() => {
    const el = document.getElementById("runtime-pull-elapsed");
    if (!el) { clearInterval(_pull.timer); return; }
    el.textContent = _pullElapsed() + "s";
    // Explain quiet stretches so a silent big-layer download never looks hung.
    const note = document.getElementById("runtime-pull-note");
    if (note) {
      const idle = Math.round((Date.now() - _pull.lastAt) / 1000);
      note.textContent = idle >= 6 && !_pull.done
        ? "Still downloading… a large layer has been streaming for " + idle + "s with no per-layer update — this is normal."
        : "";
    }
  }, 1000);
}

export function startPullUI() {
  _pull.active = true;
  _pull.start = Date.now();
  _pull.lastAt = Date.now();
  _pull.last = "contacting registry…";
  _pull.total = _pull.downloaded = _pull.pulled = 0;
  _pull.done = false;
  _pull.blobs = null;
  paintRuntimeCard(state.tools && state.tools.container);
  _pullTicker();
}

// A page reload mustn't lose a running pull: the server keeps downloading, so
// re-attach the progress UI to the live SSE stream (elapsed restarts from the
// re-attach; the layer counters rebuild from subsequent lines).
function resumePullUI() {
  _pull.active = true;
  _pull.start = Date.now();
  _pull.lastAt = Date.now();
  _pull.last = "re-attached to the running pull — waiting for the next status line…";
  _pull.done = false;
  _pullTicker();
}

export function updatePullProgress(line) {
  if (!line) return;
  _pull.last = line;
  _pull.lastAt = Date.now();
  // Count layers from docker's discrete status lines (works over a pipe).
  if (/Pulling fs layer/.test(line)) _pull.total++;
  else if (/Download complete/.test(line)) _pull.downloaded++;
  else if (/Pull complete/.test(line)) _pull.pulled++;
  else if (/Status: (Downloaded|Image is up to date)/.test(line)) _pull.done = true;
  else {
    // Podman phrasing: "Copying blob <id> …" per layer, then
    // "Writing manifest to image destination" when everything landed.
    const blob = line.match(/Copying blob (\S+)/);
    if (blob) {
      _pull.blobs = _pull.blobs || new Set();
      _pull.blobs.add(blob[1]);
      _pull.total = _pull.blobs.size;
      if (/\bdone\b/i.test(line)) _pull.downloaded++;
    } else if (/Writing manifest to image destination/.test(line)) {
      _pull.done = true;
    }
  }
  const el = document.getElementById("runtime-pull-line");
  if (el) el.textContent = line;
  const lay = document.getElementById("runtime-pull-layers");
  if (lay) lay.textContent = _pullLayerLabel();
}

export function finishPull(rc) {
  const wasCancelled = _pull.cancelledByUser;
  _pull.cancelledByUser = false;
  _pull.active = false;
  clearInterval(_pull.timer);
  if (wasCancelled) { renderTools(); return; }   // the cancel click already toasted
  if (rc === 0) toast.show("Image pulled — Container mode is ready.", "success");
  else toast.show("Image pull failed (rc=" + rc + "). See Live Logs.", "error");
  renderTools();   // re-probe → image_present / daemon state refresh
}

// Footer listing both engines with one-click Install / Remove, so a user can
// e.g. drop Docker and switch to Podman at will.
function enginesFooterHtml(c) {
  const d = c.docker || {}, p = c.podman || {};
  // The chosen engine is usable even when reached via `sg` group activation,
  // so reflect that instead of the bare daemon-permission probe.
  const dUsable = d.usable || (c.ready && c.engine === "docker");
  const pUsable = p.usable || (c.ready && c.engine === "podman");
  const chip = (name, present, usable, viaSg) => {
    const cls = present ? (usable ? "pill-pass" : "pill-warn") : "pill-pending";
    const txt = present
      ? (usable ? (viaSg ? name + " (via group)" : name) : name + " (not usable)")
      : name + " (absent)";
    return "<span class='pill " + cls + "' style='font-size:10px'><span class='d'></span><span class='text'>" + txt + "</span></span>";
  };
  const eBtn = (engine, present) =>
    present
      ? "<button class='btn btn-ghost engine-remove' data-engine='" + engine + "' style='font-size:11px;padding:2px 8px'>Remove " + engine + "</button>"
      : "<button class='btn btn-ghost engine-install' data-engine='" + engine + "' style='font-size:11px;padding:2px 8px'>Install " + engine + "</button>";
  return (
    "<div class='meta' style='margin-top:var(--s-3);display:flex;gap:var(--s-2);align-items:center;flex-wrap:wrap'>" +
    "<span class='muted' style='font-size:var(--t-xs)'>Engines:</span>" +
    chip("Docker", d.present, dUsable, c.sg_wrap && c.engine === "docker") +
    chip("Podman", p.present, pUsable, false) +
    eBtn("docker", d.present) + eBtn("podman", p.present) +
    "</div>"
  );
}

function paintRuntimeCard(container) {
  const root = document.getElementById("runtime-card");
  if (!root) return;
  const c = container || {};
  const d = c.docker || {}, p = c.podman || {};
  const verBad = c.version && c.min_version && c.version_ok === false;

  if (c.ready) {
    // A usable engine exists (Docker, Podman, or Docker via group activation).
    const engineLabel = c.sg_wrap ? "Docker (group-activated — no logout needed)" : c.engine;
    const imgSize = c.image_present
      ? sizeStr(c.image_size_mb)
      : sizeStr(c.image_approx_mb, { approx: true });
    // The server reports an in-flight pull (c.pulling) so a reloaded page
    // re-attaches to it instead of offering a second Pull button.
    if (c.pulling && !_pull.active) resumePullUI();
    let pullArea;
    if (_pull.active) pullArea = pullProgressHtml();
    else if (c.image_present)
      pullArea = "<span class='pill pill-pass'><span class='d'></span><span class='text'>image pulled</span></span>";
    else
      pullArea = "<span class='pill pill-warn'><span class='d'></span><span class='text'>image not pulled</span></span>" +
        "<button class='btn btn-primary' id='btn-pull-image' title='Recommended: one download gives you every EDA tool, version-matched'>Pull image (recommended)</button>";
    root.innerHTML =
      "<div class='tool-card installed-installed'>" +
      "<div class='row1'><span class='name'>✓ " + fmt.escape(engineLabel) + " ready</span>" +
      "<span class='dot-installed' title='ready'></span></div>" +
      "<div class='what'>All EDA tools are available via the LibreLane image (version-matched). No native tool installs needed — just keep the <strong>Container</strong> run engine selected.</div>" +
      (verBad
        ? "<div class='hint' style='color:var(--warn)'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M12 3l10 18H2zM12 10v5M12 18h.01'/></svg> " + fmt.escape(c.engine) + " " + fmt.escape(c.version) +
          " is older than LibreLane's recommended " + fmt.escape(c.min_version) + " — consider upgrading.</div>"
        : (c.version ? "<div class='hint'>" + fmt.escape(c.version) + "</div>" : "")) +
      "<div class='meta' style='display:flex;align-items:center;gap:var(--s-2);flex-wrap:wrap'>" +
      "<span style='font-family:monospace;font-size:var(--t-xs)'>" + fmt.escape(c.image || "") + "</span>" +
      (imgSize ? "<span class='muted' style='font-size:var(--t-xs)'>" + imgSize + "</span>" : "") +
      pullArea +
      "</div>" +
      enginesFooterHtml(c) +
      "</div>";
  } else if (c.available) {
    // A binary is installed but nothing is usable yet — offer convenient,
    // logout-free fixes.
    const canEnable = d.present && d.group_fixable;   // Linux + sg → no relogin
    let actions = "";
    if (canEnable)
      actions += "<button class='btn btn-primary' id='btn-enable-docker'>Enable Docker for my user (no logout)</button>";
    if (!p.present)
      actions += "<button class='btn btn-primary' id='btn-install-podman'>Install &amp; use Podman</button>";
    actions += "<button class='btn btn-ghost' id='btn-runtime-recheck'>Recheck</button>";
    root.innerHTML =
      "<div class='tool-card installed-missing'>" +
      "<div class='row1'><span class='name'>Container engine installed — not usable yet</span>" +
      "<span class='dot-missing' title='not usable'></span></div>" +
      "<div class='what'>An engine is installed but not reachable yet:</div>" +
      "<pre class='code' style='white-space:pre-wrap'>" + fmt.escape(c.daemon_msg || "engine not reachable") + "</pre>" +
      (canEnable
        ? "<p class='hint'><strong>Easiest fix:</strong> click <em>Enable Docker for my user</em> — it adds you to the <code>docker</code> group and the GUI activates it immediately (via <code>sg</code>), so <strong>no logout is needed</strong>. Or switch to rootless Podman.</p>"
        : "<p class='hint'><strong>Easiest fix:</strong> install rootless <strong>Podman</strong> (works immediately). For Docker: <code>sudo systemctl enable --now docker</code>, and <code>sudo usermod -aG docker $USER</code> (then a new login or re-open the GUI). On macOS: start Docker Desktop, or <code>podman machine init && podman machine start</code>.</p>") +
      "<div class='meta' style='display:flex;gap:var(--s-2);flex-wrap:wrap;align-items:center'>" +
      actions +
      "</div>" +
      enginesFooterHtml(c) +
      "</div>";
  } else {
    root.innerHTML =
      "<div class='tool-card installed-missing'>" +
      "<div class='row1'><span class='name'>No container engine found</span>" +
      "<span class='dot-missing' title='missing'></span></div>" +
      "<div class='what'>Install <strong>Podman</strong> (recommended — rootless, works immediately) or <strong>Docker</strong>. One install gives you every EDA tool through the LibreLane image, on every platform LibreLane supports. The image is " +
      sizeStr(c.image_approx_mb || 3000, { approx: true }) + ".</div>" +
      "<div class='meta' style='display:flex;gap:var(--s-2);flex-wrap:wrap;align-items:center'>" +
      "<button class='btn btn-primary' id='btn-install-podman'>Install Podman</button>" +
      "<button class='btn btn-primary' id='btn-install-docker'>Install Docker</button>" +
      "<a class='btn btn-ghost' href='https://podman.io/get-started' target='_blank' rel='noopener'>Podman docs ↗</a>" +
      "<a class='btn btn-ghost' href='https://docs.docker.com/get-docker/' target='_blank' rel='noopener'>Docker docs ↗</a>" +
      "</div>" +
      "<p class='hint'>Prefer native tools? Switch the top-bar engine to <strong>Local tools</strong> and use <em>Advanced: local toolchain</em> below.</p>" +
      "</div>";
  }
  document.getElementById("btn-runtime-recheck")?.addEventListener("click", () => renderTools());
  document.getElementById("btn-enable-docker")?.addEventListener("click", async () => {
    const b = document.getElementById("btn-enable-docker");
    if (b) { b.disabled = true; b.textContent = "enabling…"; }
    toast.show("Adding you to the docker group (needs sudo)…", "info");
    try {
      const r = await api.enableDockerGroup();
      if (r.ok) toast.show(r.message || "Done — Docker enabled.", "success");
      else { toast.show(r.reason || "Could not enable Docker", "error"); if (r.guidance) renderLogs.append({ payload: { message: "ℹ " + r.guidance } }); }
    } catch (ex) {
      toast.show("Failed: " + ex.message, "error");
    }
    renderTools();
  });
  document.getElementById("btn-pull-image")?.addEventListener("click", async () => {
    try {
      const res = await api.containerPull();
      if (res.ok) {
        startPullUI();
        if (res.in_progress)
          toast.show("Already pulling — re-attaching to the running download (no second download).", "info");
        else
          renderLogs.append({ payload: { message: "→ pulling container image " + (res.image || "") } });
      } else {
        toast.show(res.reason || "Could not start image pull", "error");
        if (res.guidance) renderLogs.append({ payload: { message: "ℹ " + res.guidance } });
      }
    } catch (ex) {
      toast.show("Pull failed: " + ex.message, "error");
    }
  });
  document.getElementById("runtime-pull-cancel")?.addEventListener("click", async () => {
    _pull.cancelledByUser = true;
    try {
      const r = await api.cancelInstall("container:image");
      toast.show(r && r.ok ? "Image pull cancelled — fetched layers stay cached, a retry resumes." : "Nothing to cancel.", "info");
    } catch (ex) {
      toast.show("Cancel failed: " + (ex.message || ex), "error");
    }
    _pull.active = false;
    clearInterval(_pull.timer);
    renderTools();
  });
  document.getElementById("btn-install-docker")?.addEventListener("click", () => installEngine("docker"));
  document.getElementById("btn-install-podman")?.addEventListener("click", () => installEngine("podman"));
  root.querySelectorAll(".engine-install").forEach((b) =>
    b.addEventListener("click", () => installEngine(b.dataset.engine)));
  root.querySelectorAll(".engine-remove").forEach((b) =>
    b.addEventListener("click", () => removeEngine(b.dataset.engine)));
}

async function installEngine(key) {
  document.querySelectorAll("[id^=btn-install-], .engine-install").forEach((b) => { b.disabled = true; });
  toast.show("Installing " + key + " — runs a system package command; watch Live Logs.", "info");
  try {
    const result = await api.installTool(key);
    if (result.status === "started") {
      // Async: the outcome arrives as an SSE `installer_result` event, which
      // toasts the result and chains the image pull ("in one go") on success.
      return;
    }
    handleInstallOutcome(key, result);
    if (result.ok) {
      await chainImagePull();
      return;
    }
  } catch (ex) {
    toast.show(key + " install error: " + ex.message, "error");
  }
  renderTools();   // re-probe → card reflects binary + daemon state
}

async function removeEngine(key) {
  if (!(await confirmDialog({ title: "Remove " + key, danger: true, confirmText: "Remove",
    body: "Remove " + key + "? You can switch to the other engine." }))) return;
  toast.show("Removing " + key + "…", "info");
  try {
    const r = await api.uninstallTool(key);
    if (r.ok) {
      toast.show(key + " removed via " + (r.method || "?"), "info");
      renderLogs.append({ payload: { message: "✓ " + key + " removed" } });
    } else {
      toast.show(key + " removal failed — " + (r.reason || ""), "error");
      renderLogs.append({ payload: { message: "✗ " + key + " removal: " + (r.reason || ""), level: "ERROR" } });
    }
  } catch (ex) {
    toast.show(key + " removal error: " + ex.message, "error");
  }
  renderTools();
}

// Tools shown in the dedicated "Recommended extra tools" group, so we skip them
// in the Advanced local-toolchain grid to avoid duplicate cards.
const RECOMMENDED_KEYS = new Set(["iverilog", "graphviz"]);

// Tools the container image can open as an interactive window/console with no
// run context (matches controller/container_tools._CONTAINER_TOOLS).
const CONTAINER_LAUNCHABLE = new Set(["magic", "klayout", "openroad", "netgen"]);

function paint(info) {
  paintRuntimeCard(info.container);
  renderRecommendedTools(info);
  const root = document.getElementById("tools-grid");
  root.innerHTML = "";
  // "In container" is only a usable fact once an engine is ready AND the image
  // is actually pulled — a flag without those would promise a tool that a click
  // can't deliver.
  const cont = info.container || {};
  const contReady = !!(cont.ready && cont.image_present);
  for (const t of info.tools) {
    if (RECOMMENDED_KEYS.has(t.key)) continue;
    const inCont = !!(t.in_container && contReady);
    const card = document.createElement("div");
    card.className = "tool-card " + ((t.installed || inCont) ? "installed-installed" : "installed-missing");
    card.dataset.key = t.key;
    const openBtn = inCont && CONTAINER_LAUNCHABLE.has(t.key)
      ? "<button class='btn btn-ghost ct-open' data-key='" + t.key + "' " +
        "title='Open the version-matched " + fmt.escape(t.label) + " from the LibreLane image'>Open (container)</button>"
      : "";
    const installBtn = !t.installed
      ? buttonHtml(t, { inContainer: inCont })
      : buttonUninstallHtml(t);
    card.innerHTML =
      "<div class='row1'>" +
      "<span class='name'>" + fmt.escape(t.label) + "</span>" +
      (inCont
        ? "<span class='pill pill-pass' style='margin-left:auto;margin-right:var(--s-2);font-size:10px' title='Ships in the pulled LibreLane image — usable with no native install'><span class='d'></span><span class='text'>in container</span></span>"
        : "") +
      (t.installed
        ? "<span class='dot-installed' title='installed locally'></span>"
        : (inCont ? "<span class='dot-installed' title='available via the container image'></span>"
                  : "<span class='dot-missing' title='missing'></span>")) +
      "</div>" +
      "<div class='what'>" + fmt.escape(t.what || "") + "</div>" +
      (t.windows_only
        ? "<div class='hint' style='color:var(--warn,#d29922)'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M12 3l10 18H2zM12 10v5M12 18h.01'/></svg> A Windows build was found on the WSL PATH but can't be used by the Linux flow. Install the Linux build inside WSL (button below) or use the container image.</div>"
        : "") +
      "<div class='meta'>" +
      (t.installed
        ? "Path: <span style='font-family:monospace'>" + fmt.escape(t.path || "—") + "</span>"
        : (inCont
            ? "<span class='pill pill-warn'><span class='d'></span><span class='text'>not installed locally</span></span>"
            : "<span class='pill pill-fail'><span class='d'></span><span class='text'>missing</span></span>")) +
      (t.approx_mb ? " <span class='muted' style='font-size:var(--t-xs)' title='approximate installed size'>" + sizeStr(t.approx_mb, { approx: true }) + "</span>" : "") +
      "</div>" +
      // Surface the probed version (no hard-coded compat matrix — just the fact,
      // so a user can sanity-check against LibreLane's expectations themselves).
      (t.installed && t.version
        ? "<div class='meta muted' style='font-size:var(--t-xs)' title='reported by the tool'>" + fmt.escape(t.version) + "</div>"
        : "") +
      (openBtn ? "<div class='meta' style='margin-top:var(--s-2)'>" + openBtn + "</div>" : "") +
      installBtn;
    root.appendChild(card);
  }
  root.querySelectorAll(".ct-open").forEach((b) =>
    b.addEventListener("click", async () => {
      const key = b.dataset.key;
      b.disabled = true;
      try {
        const r = await api.containerToolOpen(key);
        if (r && r.ok) toast.show(r.hint || (key + " opening from the container image… (first window can take a few seconds)"), "success");
        else toast.show((r && r.error) || (key + " could not be launched"), r && r.need === "image" ? "warn" : "error");
      } catch (ex) {
        toast.show(key + " launch error: " + (ex.message || ex), "error");
      }
      b.disabled = false;
    }));
  paintToolBar(info);

  // PDK store — catalog cards + one-click install
  const drop = document.getElementById("pdk-store-row");
  if (drop) {
    const installed = new Set(info.pdk.installed_pdks || []);
    const catalog = info.pdk_catalog || {};
    const cielMissing = !info.pdk.ciel_installed;
    drop.innerHTML =
      "<div class='picker-row' style='flex-wrap:wrap'>" +
      (cielMissing
        ? "<span class='pill pill-fail'><span class='d'></span><span class='text'>ciel missing</span></span>" +
          "<button class='btn btn-ghost' id='install-ciel-btn'>Install ciel</button>"
        : "<span class='pill pill-pass'><span class='d'></span><span class='text'>ciel ready</span></span>") +
      "<span class='hint' style='margin-left:var(--s-3)'>PDKs are large downloads — open <em>Libraries</em> to fetch only the cell libraries you need. ciel resolves the exact version + size.</span>" +
      "</div>" +
      "<div style='display:flex;flex-wrap:wrap;gap:var(--s-4);margin-top:var(--s-3)'>" +
      Object.entries(catalog).map(([key, p]) => {
        const isInstalled = installed.has(key);
        const recBadge = p.recommended
          ? "<span class='pill pill-info' style='font-size:10px'><span class='d'>" + icon('star',{size:11}) + "</span><span class='text'>Recommended</span></span>"
          : "";

        // Library list comes from the backend (ciel's authoritative metadata).
        // Libraries in `default_libraries` are pre-checked; the rest are opt-in.
        let libsHtml = "";
        if (!state.installJobs["pdk:" + key]) {
          const allLibs = p.libraries || [];
          const defLibs = new Set(p.default_libraries || []);
          if (allLibs.length > 0) {
             const cbHtml = allLibs.map((id) => {
               const req = defLibs.has(id);
               return `<label style="display:flex;align-items:center;gap:4px;font-size:11px"><input type="checkbox" class="lib-cb-${key}" value="${fmt.escape(id)}" ${req ? "checked" : ""}> ${fmt.escape(id)}${req ? " <span style=\"color:var(--text-muted);font-size:10px\">(default)</span>" : ""}</label>`;
             }).join("");
             libsHtml = `<details style="margin-bottom:var(--s-2);font-size:12px"><summary style="cursor:pointer;color:var(--text-muted);margin-bottom:4px;user-select:none">Libraries (${allLibs.length})</summary>
               <div style="display:flex;gap:8px;margin-bottom:4px">
                 <button class="btn btn-sm" onclick="document.querySelectorAll('.lib-cb-${key}').forEach(cb => cb.checked = cb.defaultChecked)">Default set</button>
                 <button class="btn btn-sm" onclick="document.querySelectorAll('.lib-cb-${key}').forEach(cb => cb.checked = true)">All</button>
               </div>
               <div style="display:flex;flex-direction:column;gap:2px;max-height:150px;overflow-y:auto;background:var(--bg-2);padding:4px;border-radius:4px">${cbHtml}</div></details>`;
          }
        }

        const measured = (info.pdk.installed_sizes_mb || {})[key];
        const sizeFact = isInstalled && measured != null
          ? sizeStr(measured) + " on disk"
          : (p.approx_gb != null ? "~" + p.approx_gb + " GB download" : "");
        const facts = [p.foundry, p.node, sizeFact].filter(Boolean).map(fmt.escape).join(" · ");
        return (
          "<div class='tool-card' style='flex:0 0 auto;width:320px;padding:var(--s-4);position:relative'>" +
          "<div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:var(--s-2)'>" +
          "<strong>" + fmt.escape(p.label || key) + "</strong>" +
          recBadge +
          "</div>" +
          "<div style='font-size:var(--t-xs);color:var(--text-muted);margin-bottom:var(--s-2)'>" +
          facts +
          "</div>" +
          "<div class='what' style='margin-bottom:var(--s-2)'>" + fmt.escape(p.description || "") + "</div>" +
          libsHtml +
          "<div class='meta' style='display:flex;align-items:center;gap:var(--s-2);flex-wrap:wrap'>" +
          (state.installJobs["pdk:" + key]
            ? "<button class='btn btn-primary' disabled style='font-size:var(--t-sm);padding:var(--s-1) var(--s-3)'>installing…</button>" +
              "<button class='btn btn-warn pdk-cancel-btn' data-pdk='" + key + "' style='font-size:var(--t-sm);padding:var(--s-1) var(--s-3);margin-left:var(--s-1)'>Cancel</button>"
            : isInstalled
              ? "<span class='pill pill-pass' style='font-size:10px;margin-right:var(--s-2)'><span class='d'></span><span class='text'>installed</span></span>" +
                "<button class='btn btn-warn pdk-uninstall-btn' data-pdk='" + key + "' style='font-size:var(--t-sm);padding:var(--s-1) var(--s-3)' title='Uninstall " + key + "'>Delete</button>" +
                "<button class='btn btn-primary pdk-install-btn' data-pdk='" + key + "' style='font-size:var(--t-sm);padding:var(--s-1) var(--s-3);margin-left:var(--s-1)' title='Install additional libraries'>Update</button>"
              : p.note
                ? "<span class='muted' style='font-size:10px'>" + fmt.escape(p.note) + "</span>"
                : "<button class='btn btn-primary pdk-install-btn' data-pdk='" + key + "' style='font-size:var(--t-sm);padding:var(--s-1) var(--s-3)'>Install</button>") +
          "</div>" +
          "</div>"
        );
      }).join("") +
      "</div>";
    // Wire PDK install buttons
    drop.querySelectorAll(".pdk-install-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pdk = btn.dataset.pdk;
        
        const cbList = drop.querySelectorAll(".lib-cb-" + pdk);
        let libraries = null;
        if (cbList.length > 0) {
           libraries = [];
           cbList.forEach(cb => { if(cb.checked) libraries.push(cb.value); });
        }
        
        state.installJobs["pdk:" + pdk] = true;
        renderTools();
        try {
          const result = await api.installCiel(pdk, libraries);
          if (result.ok) {
            if (result.in_progress) {
              toast.show(`PDK ${pdk} is already downloading — no second download started.`, "info");
            } else {
              toast.show(`PDK ${pdk} installation started... Check logs.`, "info");
              renderLogs.append({ payload: { message: "→ PDK " + pdk + " installation started in background." } });
            }
          } else {
            delete state.installJobs["pdk:" + pdk];
            const msg = "✗ PDK " + pdk + " failed — rc=" + (result.rc ?? "?") + " " + (result.reason || "");
            toast.show(`PDK ${pdk} install failed: ${result.reason || ""}`, "error");
            renderLogs.append({ payload: { message: msg, level: "ERROR" } });
            renderTools();
          }
        } catch (ex) {
          delete state.installJobs["pdk:" + pdk];
          toast.show(`PDK ${pdk} install error: ${ex.message}`, "error");
          renderLogs.append({ payload: { message: "✗ PDK " + pdk + " error: " + ex.message, level: "ERROR" } });
          renderTools();
        }
      });
    });
    drop.querySelectorAll(".pdk-cancel-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pdk = btn.dataset.pdk;
        try {
          const res = await api.cancelInstall("pdk:" + pdk);
          if (res.ok) {
            toast.show("Installation cancelled.", "info");
          }
        } catch (e) {}
        delete state.installJobs["pdk:" + pdk];
        renderTools();
      });
    });
    document.getElementById("install-ciel-btn")?.addEventListener("click", () =>
      installByKey("ciel"),
    );
    drop.querySelectorAll(".pdk-uninstall-btn").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pdk = btn.dataset.pdk;
        if (!(await confirmDialog({ title: "Uninstall PDK", danger: true, confirmText: "Uninstall",
          body: "Uninstall PDK " + pdk + "?" }))) return;
        btn.textContent = "…";
        try {
          const result = await api.uninstallPdk(pdk);
          if (result.ok) {
            toast.show(`PDK ${pdk} uninstalled`, "info");
            renderLogs.append({ payload: { message: "✓ PDK " + pdk + " uninstalled via " + (result.method || "?") } });
            // Optimistic: drop it from the installed set so the card flips now.
            if (state.tools?.pdk) {
              state.tools.pdk.installed_pdks = (state.tools.pdk.installed_pdks || []).filter((x) => x !== pdk);
              if (state.tools.pdk.installed_sizes_mb) delete state.tools.pdk.installed_sizes_mb[pdk];
            }
            if (state.tools) paint(state.tools);
            // Keep the Setup tab honest too — its picker re-fetches /api/pdks.
            import("./setup.js").then((m) => m.populatePdkPicker && m.populatePdkPicker()).catch(() => {});
          } else {
            toast.show(`PDK ${pdk} uninstall failed`, "error");
            renderLogs.append({ payload: { message: "✗ PDK " + pdk + " uninstall failed: " + (result.reason || "unknown"), level: "ERROR" } });
          }
        } catch (ex) {
          toast.show(`PDK ${pdk} uninstall error: ${ex.message}`, "error");
          renderLogs.append({ payload: { message: "✗ PDK " + pdk + " uninstall error: " + ex.message, level: "ERROR" } });
        }
        renderTools();
      });
    });
  }
  wireInstallButtons();
  wireUninstallButtons();
}

function buttonUninstallHtml(t) {
  return "<div class='tool-installed-row'><span class='pill pill-pass'><span class='d'></span><span class='text'>installed</span></span><button class='uninstall-btn' data-key='" + t.key + "' title='Uninstall " + t.key + "' aria-label='Uninstall " + t.key + "'>" + icon("x", { size: 11 }) + "</button></div>";
}

function paintToolBar(info) {
  const icon = document.getElementById("tools-count");
  if (!icon) return;
  const missing = info.tools.filter((t) => !t.installed && t.category !== "core").length;
  icon.textContent = missing.toString();
  icon.classList.remove("badge-pass", "badge-fail");
  if (missing === 0) icon.classList.add("badge-pass");
  else icon.classList.add("badge-fail");
}

function buttonHtml(t, { inContainer = false } = {}) {
  // OpenROAD/Magic/Netgen have no pip/apt/brew package — a host "Install" button
  // there only ever fails. Point at the container image instead (the supported,
  // cross-platform path), with conda/Nix as the advanced fallback.
  if (t.container_only) {
    if (inContainer) {
      return "<div class='muted' style='font-size:var(--t-xs);line-height:1.4'>" +
        "No host package — this tool runs from the container image (already pulled). " +
        "<span title='" + fmt.escape(t.install_recipe || "") + "'>(advanced local install: conda/Nix)</span></div>";
    }
    return "<div class='muted' style='font-size:var(--t-xs);line-height:1.4'>" +
      "No host package — get it via the <strong>container image</strong>: switch the top-bar engine to " +
      "<em>Container</em> and click <em>Pull image</em>. " +
      "<span title='" + fmt.escape(t.install_recipe || "") + "'>(advanced: conda/Nix)</span></div>";
  }
  if (Array.isArray(t.install_recipe) || t.install_recipe) {
    // When the container copy already covers the tool, the native install is an
    // extra, not a requirement — label it so.
    return "<button class='install-btn' data-key='" + t.key + "'>" +
      (inContainer ? "Install locally" : "Install") + "</button>";
  }
  return "<span class='muted'>" + fmt.escape(t.install_recipe || "manual install") + "</span>";
}

function wireInstallButtons() {
  document.querySelectorAll(".install-btn").forEach((btn) => {
    btn.addEventListener("click", () => installByKey(btn.dataset.key));
  });
}

function wireUninstallButtons() {
  document.querySelectorAll(".uninstall-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const key = btn.dataset.key;
      if (!(await confirmDialog({ title: "Uninstall " + key, danger: true, confirmText: "Uninstall",
        body: "Uninstall " + key + "?" }))) return;
      btn.textContent = "…";
      try {
        const result = await api.uninstallTool(key);
        if (result.ok) {
          toast.show(`${key} uninstalled`, "info");
          renderLogs.append({ payload: { message: "✓ " + key + " uninstalled via " + (result.method || "?") } });
          // Optimistic: flip the card to "missing" immediately so the Tools tab
          // reflects the change without waiting on the re-probe.
          const tool = (state.tools?.tools || []).find((t) => t.key === key);
          if (tool) { tool.installed = false; tool.path = ""; tool.version = ""; }
          if (state.tools) paint(state.tools);
        } else {
          toast.show(`${key} uninstall failed`, "error");
          renderLogs.append({ payload: { message: "✗ " + key + " uninstall failed: " + (result.reason || "unknown"), level: "ERROR" } });
        }
      } catch (ex) {
        toast.show(`${key} uninstall error: ${ex.message}`, "error");
        renderLogs.append({ payload: { message: "✗ " + key + " uninstall error: " + ex.message, level: "ERROR" } });
      }
      renderTools();
    });
  });
}

// Shared outcome handler for a finished install. Called with the synchronous
// result for legacy/immediate shapes, and from the SSE `installer_result`
// event for async installs (the POST returns {status:"started"} right away).
function handleInstallOutcome(key, result) {
  if (result.in_progress) {
    toast.show(`${key} is already installing — no second download started.`, "info");
    return;
  }
  if (result.cancelled) {
    toast.show(`${key} install cancelled.`, "info");
    renderLogs.append({ payload: { message: "• " + key + " install cancelled by user" } });
    return;
  }
  if (result.ok) {
    toast.show(`${key} installed successfully`, "success");
    renderLogs.append({
      payload: {
        message:
          "✓ " + key + " installed via " + (result.label || result.method || "?") +
          (result.argv ? " (" + result.argv.join(" ") + ")" : "") +
          (result.rc !== undefined ? " rc=" + result.rc : ""),
      },
    });
  } else if (result.needs_sudo) {
    // sudo can't prompt from the GUI — show the exact command to run.
    toast.show(`${key} needs sudo — run the shown command in a terminal.`, "warn");
    renderLogs.append({ payload: { message: result.guidance || ("Run with sudo: " + key), level: "WARN" } });
  } else {
    // Surface the actionable guidance (e.g. "use conda/Nix/container"), not
    // just "failed".
    const why = result.guidance || result.reason || "no install method on this system";
    toast.show(`Can't auto-install ${key}: ${why}`, "error");
    const tried = (result.tried || []).join("; ");
    renderLogs.append({
      payload: { message: "✗ " + key + " install failed — " + why + (tried ? " [" + tried + "]" : ""), level: "ERROR" },
    });
  }
}

// Final outcome of an async install, delivered over SSE (dispatched from
// app.js). Toast + log the result, chain the engine→image pull for a one-click
// toolchain, then re-probe so the tab reflects the new state.
export async function onInstallerResult(ev) {
  const key = ev.key || "tool";
  handleInstallOutcome(key, ev);
  if (ev.ok && (key === "docker" || key === "podman")) {
    await chainImagePull();
    return; // chainImagePull repaints
  }
  renderTools();
}

// Once a container engine is usable, chain straight into the image pull so a
// single click sets up the whole toolchain. If the engine isn't reachable yet
// (e.g. Docker needs a group/login), the runtime card shows the next fix.
async function chainImagePull() {
  try {
    const info = await api.tools();
    state.tools = info;
    paint(info);
    const c = info.container || {};
    if (c.ready && !c.image_present && !_pull.active) {
      const res = await api.containerPull();
      if (res.ok) {
        startPullUI();
        renderLogs.append({ payload: { message: "→ engine ready — pulling container image " + (res.image || "") } });
      }
    }
  } catch (_e) {
    renderTools();   // re-probe → card reflects binary + daemon state
  }
}

async function installByKey(key) {
  try {
    const result = await api.installTool(key);
    if (result.status === "started") {
      toast.show(`${key} install started — watch Install logs; this tab updates when it finishes.`, "info");
      return;
    }
    handleInstallOutcome(key, result);
  } catch (ex) {
    const body = ex.body;
    if (body && body.kind === "manual") {
      showInstallModal(key, body.recipe || "(no recipe in this build)");
      return;
    }
    renderLogs.append({
      payload: { message: "✗ " + key + " install error: " + ex.message, level: "ERROR" },
    });
  }
}

function showInstallModal(key, recipe) {
  // Build a small modal "How to install" instead of the intrusive alert().
  let modal = document.getElementById("install-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "install-modal";
    modal.style.cssText =
      "position:fixed;inset:0;background:rgba(0,0,0,0.55);display:grid;place-items:center;z-index:60;backdrop-filter:blur(4px);";
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.style.display = "none";
    });
    document.body.appendChild(modal);
  }
  modal.innerHTML =
    '<div style="background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);' +
    'padding:var(--s-5);max-width:520px;width:90%;box-shadow:var(--sh-3);">' +
    '<div style="display:flex;align-items:center;justify-content:space-between;">' +
    "<h2>Install " + key + "</h2>" +
    '<button class="btn btn-ghost" id="install-modal-close">Close</button>' +
    "</div>" +
    "<p>" +
    "This tool isn't pip-installable; please use the recipe below for your platform." +
    "</p>" +
    '<pre class="code">' +
    fmt.escape(recipe) +
    "</pre>" +
    "</div>";
  modal.style.display = "grid";
  document.getElementById("install-modal-close")?.addEventListener("click", () => {
    modal.style.display = "none";
  });
}
