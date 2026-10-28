// console.js — the Console drawer (spec 5.9): docked under every page, opened
// from the status line's Console button or Ctrl+`. It replaces the old Manual
// page. Tabs:
//
//   Log            the live flow log (or the context run's flow.log), raw log link
//   Command        the command the NEXT run will execute, the context run's
//                  recorded command, and everything needed to rerun it headless
//   Journal        what LanEx ran this session, as a script
//   Run a command  the allow-listed runner (controller/manualcmd.py), with history
//
// It docks as a grid row of #app (it never floats over the page), so the run
// bar and the page's Run controls stay on screen at any height; the page loses
// the height the drawer takes. Height and tab are remembered.

import { api, fmt } from "./api.js";
import { state, safeStorage } from "./state.js";
import { toast } from "./toast.js";
import { icon } from "./icons.js";
import { LogView } from "./logview.js";
import { liveLines, onLiveLog } from "./logs.js";
import { contextRun, onContext } from "./context.js";
import { pickCommand, commandScript, journalScript, configDiffLines, History, makesRun, runTagOf } from "./consolemodel.js";

const H_KEY = "ll.consoleH";
const TAB_KEY = "ll.consoleTab";
const HIST_KEY = "ll.consoleHistory";
const TABS = [
  ["log", "Log"],
  ["command", "Command"],
  ["journal", "Journal"],
  ["run", "Run a command"],
];
const esc = (s) => fmt.escape(s == null ? "" : String(s));

const C = { el: null, tab: "log", log: null, logTag: null, logLive: false, journal: [], hist: null, cmdTok: 0, manualCwd: "", manualRunning: false };

// ---------------------------------------------------------------- open / close
export function isConsoleOpen() { return !!C.el && !C.el.hidden; }

export function openConsole(tab) {
  ensure();
  // Where focus goes back to when the drawer closes (Esc from its input left
  // the keyboard on <body> before).
  const a = document.activeElement;
  if (a && a !== document.body && !C.el.contains(a)) C.prevFocus = a;
  if (tab) selectTab(tab === "manual" ? "run" : tab);
  if (C.el.hidden) {
    C.el.hidden = false;
    document.getElementById("app")?.classList.add("has-console");
    applyHeight(readHeight());
  }
  syncBtn();
  refreshTab();
  if (C.tab === "run") requestAnimationFrame(() => C.el.querySelector("#cn-cmd")?.focus());
}

export function closeConsole() {
  if (!C.el || C.el.hidden) return;
  const hadFocus = C.el.contains(document.activeElement);
  C.el.hidden = true;
  document.getElementById("app")?.classList.remove("has-console");
  syncBtn();
  if (hadFocus) {
    const back = C.prevFocus && C.prevFocus.isConnected && C.prevFocus.getClientRects().length ? C.prevFocus : document.getElementById("console-btn");
    back?.focus({ preventScroll: true });
  }
  C.prevFocus = null;
}

export function toggleConsole(tab) {
  if (isConsoleOpen() && (!tab || tab === C.tab)) closeConsole();
  else openConsole(tab);
}

function syncBtn() {
  const b = document.getElementById("console-btn");
  if (b) b.setAttribute("aria-pressed", isConsoleOpen() ? "true" : "false");
}

// ---------------------------------------------------------------- height
function maxHeight() {
  // The page keeps at least 300 px: the run bar and the step list stay usable.
  const app = document.getElementById("app");
  const h = app ? app.clientHeight : window.innerHeight;
  const top = document.querySelector(".topbar")?.offsetHeight || 48;
  const st = document.querySelector("footer.status")?.offsetHeight || 28;
  return Math.max(140, h - top - st - 300);
}
function readHeight() {
  const v = parseInt(safeStorage.get(H_KEY) || "", 10);
  return Number.isFinite(v) ? v : 260;
}
function applyHeight(h) {
  h = Math.round(Math.min(maxHeight(), Math.max(140, h)));
  document.getElementById("app")?.style.setProperty("--console-h", h + "px");
  return h;
}

// ---------------------------------------------------------------- build
function ensure() {
  if (C.el) return C.el;
  const el = document.createElement("section");
  el.id = "console";
  el.className = "cn";
  el.hidden = true;
  el.setAttribute("aria-label", "Console");
  el.innerHTML =
    "<div class='cn-grip' role='separator' aria-orientation='horizontal' aria-label='Resize the console' tabindex='0'></div>" +
    "<div class='cn-head'>" +
      "<span class='cn-title'>" + icon("command", { size: 13 }) + " Console</span>" +
      "<div class='cn-tabs' role='tablist' aria-label='Console'>" +
        TABS.map(([id, label]) => "<button class='cn-tab' role='tab' id='cn-tab-" + id + "' data-cn-tab='" + id + "' aria-controls='cn-pane-" + id + "' aria-selected='false'>" + esc(label) + "</button>").join("") +
      "</div>" +
      "<span class='cn-spacer'></span>" +
      "<span class='cn-key'><kbd>Ctrl</kbd> <kbd>`</kbd></span>" +
      "<button class='iconbtn' data-cn='close' aria-label='Close the console (Ctrl+`)'>" + icon("x", { size: 15 }) + "</button>" +
    "</div>" +
    "<div class='cn-body'>" +
      "<div class='cn-pane' role='tabpanel' id='cn-pane-log' aria-labelledby='cn-tab-log' hidden>" +
        "<div class='cn-sub'><span id='cn-log-what' class='cn-muted'></span></div>" +
        "<div class='cn-log' id='cn-log'></div></div>" +
      "<div class='cn-pane cn-scroll' role='tabpanel' id='cn-pane-command' aria-labelledby='cn-tab-command' hidden></div>" +
      "<div class='cn-pane cn-scroll' role='tabpanel' id='cn-pane-journal' aria-labelledby='cn-tab-journal' hidden></div>" +
      "<div class='cn-pane' role='tabpanel' id='cn-pane-run' aria-labelledby='cn-tab-run' hidden>" +
        "<div class='cn-run-row'>" +
          "<span class='cn-cwd' id='cn-cwd' title='The command runs in this folder'></span>" +
          "<span class='cn-prompt' aria-hidden='true'>$</span>" +
          "<input type='text' id='cn-cmd' class='cn-input' aria-label='Command to run' placeholder='librelane --dockerized config.json -T floorplan' autocomplete='off' spellcheck='false'/>" +
          "<button class='btn btn-primary btn-sm' id='cn-run'>" + icon("play", { size: 12 }) + " Run</button>" +
          "<button class='btn btn-ghost btn-sm' id='cn-stop' disabled>" + icon("stop", { size: 12 }) + " Stop</button>" +
        "</div>" +
        "<p class='cn-allow'>Allowed: <code>librelane</code>, <code>openroad</code>, <code>yosys</code>, <code>magic</code>, <code>klayout</code>, <code>netgen</code>, <code>iverilog</code>, <code>vvp</code>, <code>verilator</code>, <code>dot</code>, <code>ciel</code>, <code>docker</code>/<code>podman</code>. " +
          "No pipes, redirects or <code>sudo</code>: this is not a shell. Use a terminal for those. <kbd>↑</kbd> <kbd>↓</kbd> step through earlier commands.</p>" +
        "<pre id='cn-out' class='cn-out' aria-live='polite'></pre>" +
      "</div>" +
    "</div>";
  const app = document.getElementById("app") || document.body;
  const footer = app.querySelector("footer.status");
  app.insertBefore(el, footer || null);
  C.el = el;

  el.querySelector("[data-cn=close]").addEventListener("click", closeConsole);
  el.querySelectorAll("[data-cn-tab]").forEach((b) => b.addEventListener("click", () => { selectTab(b.dataset.cnTab); refreshTab(); }));
  el.querySelector(".cn-tabs").addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = TABS.findIndex(([id]) => id === C.tab);
    const n = TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length][0];
    selectTab(n); refreshTab();
    el.querySelector("#cn-tab-" + n).focus();
    e.preventDefault();
  });
  wireGrip(el.querySelector(".cn-grip"));
  wireRunner();
  el.addEventListener("click", onAction);
  // Esc closes the drawer from anywhere inside it (a tab, a Copy button, the
  // log), not only from the command input; a filter box with text clears first.
  el.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented) return;
    const t = e.target;
    if (t && t.matches && t.matches("input[type=search]") && t.value) return;
    closeConsole();
    e.stopPropagation();
  });
  window.addEventListener("resize", () => { if (isConsoleOpen()) applyHeight(readHeight()); });

  C.log = new LogView(el.querySelector("#cn-log"), { follow: true });
  selectTab(safeStorage.get(TAB_KEY) || "log");
  return el;
}

function wireGrip(g) {
  let y0 = 0, h0 = 0;
  const move = (e) => { const h = applyHeight(h0 + (y0 - e.clientY) / zoom()); safeStorage.set(H_KEY, String(h)); };
  const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); document.body.classList.remove("cn-dragging"); };
  g.addEventListener("pointerdown", (e) => {
    y0 = e.clientY; h0 = C.el.offsetHeight;
    document.body.classList.add("cn-dragging");
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    e.preventDefault();
  });
  g.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    const h = applyHeight(C.el.offsetHeight + (e.key === "ArrowUp" ? 24 : -24));
    safeStorage.set(H_KEY, String(h));
    e.preventDefault();
  });
}
function zoom() { return parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--ll-zoom")) || 1; }

function selectTab(id) {
  if (!TABS.some(([t]) => t === id)) id = "log";
  C.tab = id;
  safeStorage.set(TAB_KEY, id);
  C.el.querySelectorAll("[data-cn-tab]").forEach((b) => {
    const on = b.dataset.cnTab === id;
    b.setAttribute("aria-selected", on ? "true" : "false");
    b.tabIndex = on ? 0 : -1;
  });
  C.el.querySelectorAll(".cn-pane").forEach((p) => { p.hidden = p.id !== "cn-pane-" + id; });
}

function refreshTab() {
  if (!isConsoleOpen()) return;
  if (C.tab === "log") paintLog();
  else if (C.tab === "command") paintCommand();
  else if (C.tab === "journal") paintJournal();
  else if (C.tab === "run") paintCwd();
}

async function copy(text, what = "Copied") {
  try { await navigator.clipboard.writeText(text); toast.show(what, "success", 1800); }
  catch (_e) { toast.show("Copy failed. Select the text and copy it yourself.", "warn"); }
}

// ---------------------------------------------------------------- Log
function paintLog() {
  const running = !!(state.status && state.status.running);
  const live = liveLines();
  const what = C.el.querySelector("#cn-log-what");
  // One "Raw log" link: the log view's own, in its toolbar.
  if (running || live.length) {
    const tag = state.liveTag || contextRun() || "";
    if (!C.logLive) { C.log.setText(live.join("\n")); C.log.end(); C.logLive = true; C.logTag = null; }
    what.textContent = (running ? "Live: " : "Last run in this session: ") + (tag || "the flow");
    C.log.setRaw(tag ? api.runFileUrl(tag, "flow.log") : "");
    return;
  }
  const tag = contextRun();
  if (!tag) { what.textContent = "No run yet. Start one and its log streams here."; C.log.setRaw(""); C.log.setText(""); return; }
  C.log.setRaw(api.runFileUrl(tag, "flow.log"));
  what.textContent = "flow.log of " + tag;
  if (C.logTag === tag) return;
  C.logTag = tag; C.logLive = false;
  C.log.setText("");
  fetch(api.runFileUrl(tag, "flow.log"), { headers: { "X-Requested-With": "XMLHttpRequest" } })
    .then((r) => r.ok ? r.text() : Promise.reject(new Error("HTTP " + r.status)))
    .then((t) => { if (C.logTag === tag) { C.log.setText(t); C.log.end(); } })
    .catch(() => { if (C.logTag === tag) what.textContent = tag + " has no flow.log yet."; });
}

// ---------------------------------------------------------------- Command
async function paintCommand() {
  const pane = C.el.querySelector("#cn-pane-command");
  const tok = ++C.cmdTok;
  if (!pane.firstChild) pane.innerHTML = "<p class='cn-muted'>Building the command…</p>";
  const tag = contextRun();
  let payload = {};
  try { payload = (await import("./setup.js")).collectRunPayload(); } catch (_e) {}
  const [next, rep] = await Promise.all([
    api.cliCommand({
      flow: "Classic", pdk: state.selectedPdk || undefined, scl: state.selectedScl || undefined,
      run_mode: state.runMode, frm: payload.frm || undefined, to: payload.to || undefined,
      skip: payload.skip || [], overrides: payload.overrides || {},
    }).catch((e) => ({ error: e.message })),
    tag ? api.runReproduce(tag).catch((e) => ({ error: e.message })) : Promise.resolve(null),
  ]);
  if (tok !== C.cmdTok) return;
  const nextCmd = next && !next.error ? pickCommand(next) : "";
  C.next = next; C.rep = rep;
  let h = "<section class='cn-blk'><div class='cn-blk-h'><h3>Next run</h3>" +
    "<span class='cn-muted'>What Run will execute with the settings on Setup now" + (payload.tag ? " (run name aside: LanEx adds --run-tag " + esc(payload.tag) + ")" : "") + ".</span></div>";
  if (next && next.error) h += "<p class='cn-warn'>" + esc(next.error) + "</p>";
  else {
    h += cmdRow(nextCmd, "next") +
      "<p class='cn-muted'>From <code>" + esc(next.cwd) + "</code>" +
      (next.image ? " · image <code>" + esc(next.image) + "</code>" : "") + ". A run started in a terminal shows up in Runs.</p>" +
      threadsLine(next.resources && next.resources.values, next.resources && next.resources.reason, "this PC", next.resources && next.resources.kept) +
      "<div class='cn-acts'><button class='btn btn-ghost btn-xs' data-cn='copy-next-script'>" + icon("file", { size: 12 }) + " Copy as script</button>" +
      (next.local && next.container ? "<button class='btn btn-ghost btn-xs' data-cn='copy-other'>Copy the " + (next.recommended === "container" ? "local tools" : "container") + " form</button>" : "") + "</div>";
  }
  h += "</section>";
  h += "<section class='cn-blk'><div class='cn-blk-h'><h3>Reproduce " + (tag ? esc(tag) : "a run") + "</h3>" +
    "<span class='cn-muted'>Rerun it headless in WSL, without LanEx.</span></div>";
  if (!tag) h += "<p class='cn-muted'>No run picked. Pick one in Runs or start one.</p>";
  else if (!rep || rep.error) h += "<p class='cn-warn'>" + esc(rep ? rep.error : "No record.") + "</p>";
  else if (!rep.recorded) h += "<p class='cn-muted'>" + esc(tag) + " has no recorded command: it was not started from LanEx. Its resolved config is still in the run folder.</p>" + factsHtml(rep);
  else {
    h += cmdRow(rep.command, "rec") +
      (rep.repro_tag ? "<p class='cn-muted'>Reruns as <code>" + esc(rep.repro_tag) + "</code>: LibreLane adds to a run folder whose tag exists, so the recorded tag would write into " + esc(tag) + ".</p>" : "") +
      (rep.cwd && state.designDir && rep.cwd.replace(/\/+$/, "") !== state.designDir.replace(/\/+$/, "")
        ? "<p class='cn-warn'>Recorded in " + esc(rep.cwd) + ", not this project's folder (the project was copied or moved). Run it from the project folder instead; paths inside the command are relative to it.</p>" : "") +
      factsHtml(rep) +
      "<div class='cn-acts'><button class='btn btn-ghost btn-xs' data-cn='copy-rep-script'>" + icon("file", { size: 12 }) + " Copy as script</button></div>";
  }
  h += "</section>";
  pane.innerHTML = h;
}

function cmdRow(cmd, which) {
  return "<div class='cn-cmd'><code>" + esc(cmd) + "</code><button class='btn btn-ghost btn-xs' data-cn='copy-" + which + "'>Copy</button></div>";
}

// Thread counts LanEx sized to the PC (runresources.py): which, and from what.
function threadsLine(vals, reason, pc, kept) {
  const v = Object.entries(vals || {}).map(([k, n]) => k + "=" + n).join(" ");
  const k = Object.keys(kept || {});
  if (!v && !k.length) return "";
  return "<p class='cn-muted'>" + (v ? "Threads sized to " + pc + (reason ? " (" + esc(reason) + ")" : "") + ": <code>" + esc(v) + "</code>. " : "") +
    (k.length ? "Your " + esc(k.join(", ")) + " " + (k.length === 1 ? "is" : "are") + " kept. " : "") +
    "A value you set in the config always wins.</p>";
}

function factsHtml(r) {
  const row = (k, v, mono = true) => v ? "<dt>" + esc(k) + "</dt><dd>" + (mono ? "<code>" + esc(v) + "</code>" : esc(v)) + "</dd>" : "";
  const th = r.threads && r.threads.values ? Object.entries(r.threads.values).map(([k, n]) => k + "=" + n).join(" ") : "";
  return "<dl class='cn-facts'>" +
    row("Folder", r.cwd) +
    row("Config", r.config_file) +
    row("Config sha256", r.config_hash) +
    row("Resolved config", r.resolved_config) +
    row("PDK", [r.pdk, r.scl].filter(Boolean).join(" / "), false) +
    row("PDK version", r.pdk_version ? r.pdk_version + " (ciel)" : "") +
    row("Image", r.image) +
    row("LibreLane", r.librelane_version) +
    row("Threads", th ? th + "  (LanEx, sized to that PC" + (r.threads.reason ? ": " + r.threads.reason : "") + ")" : "") +
    (r.branched_from ? row("Started from", r.branched_from.tag + " at " + (r.branched_from.step || "?") + " (needs that run folder)", false) : "") +
    "</dl>";
}

// ---------------------------------------------------------------- Journal
function stamp() { const d = new Date(); return d.toTimeString().slice(0, 8); }

// Returns the stored entry: a run's start entry is filled in later, so callers
// must keep this object, not the one they passed (that was the copy-not-the-
// entry bug that left "command recorded when…" on screen for good).
function addJournal(entry) {
  const e = { time: stamp(), ...entry };
  C.journal.push(e);
  if (isConsoleOpen() && C.tab === "journal") paintJournal();
  const b = document.getElementById("console-btn");
  if (b && !isConsoleOpen()) b.classList.add("has-activity");
  return e;
}

function paintJournal() {
  document.getElementById("console-btn")?.classList.remove("has-activity");
  const pane = C.el.querySelector("#cn-pane-journal");
  if (!C.journal.length) {
    pane.innerHTML = "<div class='cn-blk'><p class='cn-muted'>Nothing yet. Every run, resume, settings change and viewer LanEx starts in this session is written here with its command, so you can repeat the session from a terminal.</p></div>";
    return;
  }
  pane.innerHTML =
    "<div class='cn-sub'><span class='cn-muted'>" + C.journal.length + " action" + (C.journal.length === 1 ? "" : "s") + " this session</span><span class='cn-spacer'></span>" +
      "<button class='btn btn-ghost btn-xs' data-cn='copy-journal'>" + icon("file", { size: 12 }) + " Copy as script</button></div>" +
    "<ol class='cn-jl'>" + C.journal.map((e) =>
      "<li><span class='cn-jt'>" + esc(e.time) + "</span><div><div class='cn-jh'>" + esc(e.title) + "</div>" +
      (e.notes || []).map((n) => "<div class='cn-muted'>" + esc(n) + "</div>").join("") +
      (e.command ? "<code class='cn-jc'>" + esc(e.command) + "</code>" : (e.pending ? "<span class='cn-muted'>command recorded when the run folder is written…</span>" : "")) +
      "</div></li>").join("") + "</ol>";
}

async function onJournal(ev) {
  const { path, sent, data } = ev.detail || {};
  if (path === "/api/run/start") {
    const tag = (data && data.tag) || (sent && sent.tag) || "";
    const entry = { kind: "run", tag, title: "Run " + (tag ? tag + " " : "") + "started" + (sent && sent.frm ? " from " + sent.frm : "") + (sent && sent.to ? " up to " + sent.to : ""), pending: true, notes: [] };
    if (sent && sent.overrides && Object.keys(sent.overrides).length) entry.notes.push("This run only: " + Object.entries(sent.overrides).map(([k, v]) => k + "=" + v).join(", "));
    // The start reply carries the command LanEx wrote to gui-run.json.
    if (data && typeof data.command === "string" && data.command) { entry.command = data.command; entry.cwd = state.designDir || null; entry.pending = false; }
    const e = addJournal(entry);
    C.pendingRun = e;
    recordCommand(e);
  } else if (path === "/api/run/resume") {
    addJournal({ kind: "resume", title: "Next step (step-by-step run)", notes: ["LibreLane has no CLI form of this: the GUI runner waits between steps."] });
  } else if (path === "/api/config/set" || path === "/api/config/undo") {
    const lines = path === "/api/config/undo" ? ["Undid the last settings change"] : configDiffLines(sent, data);
    addJournal({ kind: "config", title: "Config edited" + (data && data.name ? " (" + data.name + ")" : ""), notes: lines });
  } else if (path === "/api/fix/apply") {
    addJournal({ kind: "fix", title: "Fix applied: " + ((sent && sent.variable) || "a setting") + " = " + ((sent && sent.value) ?? ""), notes: sent && sent.save ? ["Saved to " + (sent.save === "config" ? "the config" : "this run only")] : [] });
  } else if (path === "/api/dse/start") {
    addJournal({ kind: "dse", title: "Sweep started", notes: ["Each point's command is in its run folder (gui-run.json)."] });
  } else if (path === "/api/manual/run") {
    addJournal({ kind: "manual", title: "Ran in the Console", command: sent && sent.command, cwd: C.manualCwd || null });
  } else if (path === "/api/open-in-tool" || path === "/api/container-tools/open") {
    const t = (sent && (sent.tool || sent.kind)) || "a viewer";
    addJournal({ kind: "viewer", title: "Opened " + t + (sent && sent.tag ? " on " + sent.tag : ""), command: data && typeof data.command === "string" ? data.command : null });
  }
}

// The run's gui-run.json holds the exact command it ran; it is written once the
// run folder exists, a few seconds in. Fill the start entry when it is there.
function nameRun(e, tag) {
  if (e.tag || !tag) return;
  e.tag = tag;
  e.title = e.title.replace(/^Run started/, "Run " + tag + " started");
}

async function fillCommand(e) {
  if (!e.tag) return false;
  let rep = null;
  try { rep = await api.runReproduce(e.tag); } catch (_e) {}
  if (!(rep && rep.recorded)) return false;
  e.command = rep.command; e.cwd = rep.cwd || e.cwd; e.image = rep.image; e.pending = false; e.recorded = true;
  if (isConsoleOpen() && C.tab === "journal") paintJournal();
  return true;
}

// Learn the run's name from the live events (the start reply has none) and
// take the command, folder and image from its gui-run.json.
async function recordCommand(e) {
  const before = state.liveTag || "";
  for (const ms of [2000, 4000, 8000, 15000, 30000]) {
    await new Promise((r) => setTimeout(r, ms));
    if (e.recorded || C.pendingRun !== e) return;
    if (state.liveTag && state.liveTag !== before) nameRun(e, state.liveTag);
    if (await fillCommand(e)) return;
    if (isConsoleOpen() && C.tab === "journal") paintJournal();
  }
}

// A run ended: a finish entry, and the start entry gets its command if it
// still has none.
async function onFlowDone(ev) {
  const d = ev.detail || {};
  const e = C.pendingRun || null;
  C.pendingRun = null;
  const tag = String(d.tag || (e && e.tag) || "").split(/[\\/]/).pop();
  if (e) {
    nameRun(e, tag);
    if (!e.recorded) await fillCommand(e);
    if (!e.command) { e.pending = false; e.notes = (e.notes || []).concat(["No command was recorded for this run."]); }
  }
  const outcome = d.error ? "failed" : d.cancelled ? "stopped" : "finished";
  const notes = d.error && typeof d.error === "string" ? [oneLineErr(d.error)] : [];
  addJournal({ kind: "run-end", title: "Run " + (tag || "") + (tag ? " " : "") + outcome, notes });
  if (isConsoleOpen() && C.tab === "log") paintLog();
}

function oneLineErr(s) { const t = String(s).split("\n")[0].trim(); return t.length > 160 ? t.slice(0, 157) + "…" : t; }

// ---------------------------------------------------------------- Run a command
function wireRunner() {
  let saved = [];
  try { saved = JSON.parse(safeStorage.get(HIST_KEY) || "[]"); } catch (_e) {}
  C.hist = new History(Array.isArray(saved) ? saved : []);
  const input = C.el.querySelector("#cn-cmd");
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { runManual(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { input.value = C.hist.up(input.value); e.preventDefault(); }
    else if (e.key === "ArrowDown") { input.value = C.hist.down(input.value); e.preventDefault(); }
    else if (e.key === "Escape") { closeConsole(); e.stopPropagation(); }
  });
  C.el.querySelector("#cn-run").addEventListener("click", runManual);
  C.el.querySelector("#cn-stop").addEventListener("click", () => api.manualCancel().catch(() => {}));
}

function paintCwd() {
  const d = state.designDir || "";
  C.manualCwd = d;
  const el = C.el.querySelector("#cn-cwd");
  if (state.designMissing) {
    el.textContent = "project folder not found";
    el.title = state.designMissing + " is gone. Locate it or remove it from the list on Setup.";
    return;
  }
  // The box is right-to-left so a long path clips at its start; the LRMs keep
  // "~/" in front instead of letting bidi move it to the end ("blinky/~").
  el.textContent = d ? "‎" + d.replace(/^\/home\/[^/]+/, "~") + "‎" : "no project open";
  el.title = d ? "The command runs in " + d : "Open a project first: the command runs in its folder";
  paintPlaceholder(d);
}

// The example command names the project's own config file (config.json or .yaml).
async function paintPlaceholder(d) {
  const input = C.el.querySelector("#cn-cmd");
  const set = (name) => { input.placeholder = "librelane --dockerized " + (name || "config.json") + " -T floorplan"; };
  if (C.cfgFor === d) return set(C.cfgName);
  C.cfgFor = d; C.cfgName = "";
  set("");
  if (!d) return;
  let info = null;
  try { info = await api.designInfo({ design_dir: d }); } catch (_e) {}
  const name = info && info.config && info.config.name;
  if (C.cfgFor !== d) return;
  C.cfgName = name ? String(name).split(/[\\/]/).pop() : "";
  set(C.cfgName);
}

async function runManual() {
  const input = C.el.querySelector("#cn-cmd");
  const out = C.el.querySelector("#cn-out");
  const cmd = (input.value || "").trim();
  if (!cmd || C.manualRunning) return;
  paintCwd();
  // The server still has the previous project active: a command now would
  // run in that folder, not the one this window shows.
  if (state.designMissing) {
    out.textContent += (out.textContent ? "\n" : "") + "Not run: the project folder " + state.designMissing +
      " is not there any more. Locate it or remove it from the list on Setup.\n";
    out.scrollTop = out.scrollHeight;
    return;
  }
  C.hist.push(cmd);
  safeStorage.set(HIST_KEY, JSON.stringify(C.hist.items));
  out.textContent += (out.textContent ? "\n" : "") + "$ " + cmd + "\n";
  C.lastManual = cmd;
  input.value = "";
  try {
    await api.manualRun(cmd);
    setRunning(true);
  } catch (ex) {
    out.textContent += "Not run: " + ex.message + "\n";
    out.scrollTop = out.scrollHeight;
  }
}

function setRunning(on) {
  C.manualRunning = on;
  if (!C.el) return;
  C.el.querySelector("#cn-run").disabled = on;
  C.el.querySelector("#cn-stop").disabled = !on;
}

// The output pane keeps the last OUT_KEEP lines. Lines arrive one SSE event
// each: appending to textContent per line copied the whole pane every time
// (a chatty yosys or a 10 MB log froze the window), so they are batched once
// per frame into one text node, and the oldest are cut past OUT_MAX.
const OUT_MAX = 8000, OUT_KEEP = 5000;
function flushOut() {
  C.outRaf = 0;
  const out = C.el && C.el.querySelector("#cn-out");
  if (!out || !C.outBuf || !C.outBuf.length) return;
  const atEnd = out.scrollTop + out.clientHeight >= out.scrollHeight - 24;
  out.appendChild(document.createTextNode(C.outBuf.join("\n") + "\n"));
  C.outLines = (C.outLines || 0) + C.outBuf.length;
  C.outBuf = [];
  if (C.outLines > OUT_MAX) {
    const lines = out.textContent.split("\n");
    out.textContent = "[Earlier output cut: the Console keeps the last " + OUT_KEEP + " lines. Run it in a terminal for all of it.]\n" +
      lines.slice(-OUT_KEEP).join("\n");
    C.outLines = OUT_KEEP;
  }
  if (atEnd) out.scrollTop = out.scrollHeight;
}

// manual_* SSE events (app.js): the runner's output.
export function onManualEvent(ev) {
  ensure();
  const out = C.el.querySelector("#cn-out");
  if (ev.type === "manual_started") setRunning(true);
  else if (ev.type === "manual_line") {
    (C.outBuf = C.outBuf || []).push(ev.line || "");
    if (!C.outRaf) C.outRaf = requestAnimationFrame(flushOut);
  } else if (ev.type === "manual_done") {
    if (C.outRaf) { cancelAnimationFrame(C.outRaf); flushOut(); }
    out.textContent += (ev.error ? "Failed: " + ev.error : "Exit code " + (ev.rc ?? "?")) + "\n";
    setRunning(false);
    // A librelane flow made a run folder: say where it went and link it.
    const cmd = C.lastManual || ev.command || "";
    if (makesRun(cmd) && !ev.error) {
      const tag = runTagOf(cmd);
      const a = document.createElement("button");
      a.className = "btn btn-ghost btn-xs cn-runlink";
      a.textContent = tag ? "Show " + tag + " in Runs" : "Show the new run in Runs";
      a.addEventListener("click", () => import("./nav.js").then((m) => m.go("runs", tag ? { run: tag } : {})));
      out.appendChild(a);
      out.appendChild(document.createTextNode("\n"));
      import("./context.js").then((m) => m.loadRuns({ fresh: true })).catch(() => {});
    }
    out.scrollTop = out.scrollHeight;
  }
}

// ---------------------------------------------------------------- actions
function onAction(e) {
  const b = e.target.closest("[data-cn]");
  if (!b) return;
  const a = b.dataset.cn;
  const next = C.next || {}, rep = C.rep || {};
  if (a === "copy-next") copy(pickCommand(next), "Copied the next run's command");
  else if (a === "copy-other") copy(next.recommended === "container" ? next.local : next.container, "Copied");
  else if (a === "copy-next-script") copy(commandScript({ command: pickCommand(next), cwd: next.cwd, image: next.image, title: "The next LanEx run, without LanEx" }), "Copied as a bash script");
  else if (a === "copy-rec") copy(rep.command || "", "Copied the command of " + (rep.tag || "the run"));
  else if (a === "copy-rep-script") copy(rep.script || "", "Copied as a bash script");
  else if (a === "copy-journal") copy(journalScript(C.journal), "Copied the session as a bash script");
}

// ---------------------------------------------------------------- setup
export function setupConsole() {
  const btn = document.getElementById("console-btn");
  if (btn && !btn._wired) { btn._wired = true; btn.addEventListener("click", () => toggleConsole()); }
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey && !e.altKey && !e.metaKey && (e.key === "`" || e.code === "Backquote")) {
      e.preventDefault();
      toggleConsole();
    }
  });
  document.addEventListener("g:journal", onJournal);
  document.addEventListener("g:flow_done", onFlowDone);
  // Another project: the runner's folder and example command follow it.
  const project = () => { if (C.el) paintCwd(); };
  document.addEventListener("g:active_design_changed", project);
  document.addEventListener("g:projects_changed", project);
  onContext((d) => {
    if (!isConsoleOpen()) return;
    if (C.tab === "command") paintCommand();
    if (C.tab === "log" && !(state.status && state.status.running)) paintLog();
  });
  onLiveLog((batch) => {
    if (!C.el) return;
    if (!C.logLive) { if (isConsoleOpen() && C.tab === "log") paintLog(); return; }
    // A new run clears the live log: the first batch is all there is, so start over.
    if (liveLines().length === batch.length) C.log.setText(batch.map((l) => l.t).join("\n"));
    else C.log.append(batch.map((l) => l.t));
  });
  syncBtn();
}
