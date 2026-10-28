// runend.js — the run moment outside Flow: the window title, the status line,
// the ring on the rail's Flow tab, and the end of a run (toast, notification,
// optional chime). Runs happen in the background (rule 4): these are how a
// user on another page, or in another window, knows how it is going and how
// it ended.
//
// The words and numbers come from the same report as Flow's (reportcard.js
// runSummary), so the toast, the notification and Flow never disagree.

import { api } from "./api.js";
import { state, safeStorage } from "./state.js";
import { toast } from "./toast.js";
import * as FS from "./flowstages.js";
import { runSummary } from "./reportcard.js";

const BASE_TITLE = document.title || "LanEx";
let _result = null;          // the last run's result line, kept in the title until seen
let _resultTimer = 0;

const designName = () => {
  const d = String(state.designDir || "").replace(/[\\/]+$/, "");
  return d.split(/[\\/]/).pop() || "";
};

export const prefs = {
  notify: () => safeStorage.get("ll.notifyRuns") === "1",
  chime: () => safeStorage.get("ll.runChime") === "1",
  // On unless turned off in the Run menu: pressing Run shows the run.
  showFlow: () => safeStorage.get("ll.showFlowOnRun") !== "0",
};

// ------------------------------------------------------------------ during

export function runStarted(tag) {
  state.liveTag = tag || state.liveTag || "";
  state.runStartedAt = Date.now();
  _result = null;
  clearTimeout(_resultTimer);
  paintTitle();
  paintRail();
}

// The flow reported progress: title, status line and ring follow.
export function runProgress() {
  paintTitle();
  paintRail();
  paintStatus();
}

function current() {
  const ids = (state.pipeline || []).map((p) => p.id);
  const st = state.stepStatuses || {};
  const n = FS.stepCounts(ids.map((id) => st[id]));
  const cur = [...ids].reverse().find((id) => st[id] === "running");
  const stage = cur ? FS.stagesOf(ids.map((id) => ({ id })))[ids.indexOf(cur)] : null;
  return { ids, done: n.done, total: n.total, cur, stage };
}

function paintTitle() {
  const name = designName();
  if (state.status && state.status.running) {
    const c = current();
    document.title = (c.total ? Math.min(c.done + 1, c.total) + "/" + c.total + (c.stage ? " · " + FS.stageLabel(c.stage) : "") : "Starting") +
      (name ? " · " + name : "") + " — LanEx";
  } else if (_result) {
    document.title = _result + (name ? " · " + name : "") + " — LanEx";
  } else {
    document.title = BASE_TITLE;
  }
}

async function paintStatus() {
  const el = document.getElementById("overall-progress");
  if (!el || !(state.status && state.status.running)) return;
  const c = current();
  if (!c.total) return;
  let name = c.cur || "";
  try { if (c.cur) name = (await import("./flow.js")).stepLabel(c.cur); } catch (_e) {}
  const eta = state.runProgress && state.runProgress.eta_seconds;
  el.textContent = (c.stage ? FS.stageLabel(c.stage) + " · " : "") + (name ? name + " · " : "") +
    Math.min(c.done + 1, c.total) + "/" + c.total + (typeof eta === "number" && eta > 0 ? " · ~" + Math.max(1, Math.round(eta / 60)) + " min left" : "");
  el.dataset.go = "pipeline";
}

// A ring on the Flow tab while a run goes; a red mark when the last run failed.
function paintRail(failed) {
  const tab = document.querySelector('.side-tab[data-tab="pipeline"]');
  if (!tab) return;
  const running = !!(state.status && state.status.running);
  const c = running ? current() : null;
  tab.classList.toggle("is-running", running);
  tab.style.setProperty("--run-pct", c && c.total ? Math.round((c.done / c.total) * 100) + "%" : "0%");
  if (failed !== undefined) tab.classList.toggle("has-failed", !!failed);
  if (running) tab.classList.remove("has-failed");
}

// ------------------------------------------------------------------ after

// flow_done: read how it ended (the same report Flow shows), then tell the user.
export async function runFinished(ev) {
  const tag = (ev && ev.tag) || state.liveTag || "";
  paintRail();
  const status = document.getElementById("overall-progress");
  let rx = null, vf = null, rs = null;
  if (tag && !ev.cancelled) {
    // Verify reads every report on its first look at a run; give it a few
    // seconds for its verdict, never hold the news longer than that.
    const late = (p, ms) => Promise.race([p, new Promise((r) => setTimeout(() => r(null), ms))]);
    [rx, vf, rs] = await Promise.all([
      api.runExplain(tag).catch(() => null),
      late(api.verify(tag).catch(() => null), 4000),
      api.runStages(tag).catch(() => null),
    ]);
  }
  if (ev.cancelled) rx = { kind: "stopped" };
  let name = (id) => id;
  try { name = (await import("./flow.js")).stepLabel; } catch (_e) {}
  const sum = runSummary({ tag, design: designName(), rx, vf, rs, name });
  if (!rx && ev.error) { sum.title = tag + " failed"; sum.body = String(ev.error); sum.tone = "fail"; }
  const mark = sum.ok ? "✓" : sum.tone === "warn" ? "■" : "✗";
  _result = mark + " " + (sum.ok ? (sum.tone === "warn" ? "clean, with warnings" : "clean") : rx && rx.kind === "halted" ? "stopped" : rx && rx.kind === "stopped" ? "stopped by you" : (sum.tone === "fail" ? "failed" : "done"));
  paintTitle();
  paintRail(!sum.ok && sum.tone === "fail");
  if (status) {
    // One short line: the time for a finished run, the reason for a stopped one.
    const tail = sum.ok ? (sum.body || "").split(" · ").slice(-1)[0] : (sum.short || "");
    status.textContent = _result + (rx && rx.kind === "halted" && rx.step ? " at " + name(rx.step.id) : "") + (tail ? " · " + tail : "");
    status.dataset.go = "pipeline";
  }
  // The title goes back to normal once the user has had the window in front
  // for a few seconds after the run ended.
  const settle = () => {
    clearTimeout(_resultTimer);
    _resultTimer = setTimeout(() => { if (document.hasFocus()) { _result = null; paintTitle(); } }, 8000);
  };
  if (document.hasFocus()) settle(); else window.addEventListener("focus", settle, { once: true });

  // The toast: short with the numbers and the next step. A failure stays until
  // dismissed (it must not expire unseen); a clean run goes after ten seconds.
  const go = (tab, params) => import("./nav.js").then((m) => m.go(tab, params || {}));
  const kind = rx ? rx.kind : (ev.error ? "halted" : "clean");
  const acts =
    kind === "clean" ? [{ label: "See chip", run: () => go("layout") }, { label: "Sign-off", run: () => go("verify") }]
    : kind === "checks-failed" ? [{ label: "Show the problems", run: () => go("verify", { section: "vf-checks" }) }]
    : kind === "halted" ? [{ label: "Why", run: () => go("pipeline") }]
    : [];
  const msg = sum.title + (sum.body ? ": " + sum.body : "");
  toast.show(msg, sum.ok ? (sum.tone === "warn" ? "warn" : "success") : kind === "stopped" ? "info" : "error",
    sum.ok ? (sum.tone === "warn" ? 16000 : 10000) : kind === "stopped" ? 6000 : 0, acts);

  if (prefs.chime()) chime(sum.ok);
  if (prefs.notify() && !(document.visibilityState === "visible" && document.hasFocus())) notify(sum, kind);
}

// ------------------------------------------------------------------ notification
// A Web Notification from this window (prototype B, spec 5.5): shown by the
// browser while the window is in the background; a click brings it forward
// and opens Flow.
function notify(sum, kind) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try {
    const n = new Notification(sum.title, {
      body: sum.body || (kind === "clean" ? "The chip is in Layout." : ""),
      tag: "lanex-run", renotify: true, icon: "/static/vendor/lanex-mark-dark.png",
      requireInteraction: kind !== "clean",
    });
    n.onshow = () => { state.lastNotice = { shown: Date.now(), title: sum.title }; };
    n.onclick = () => {
      window.focus();
      import("./nav.js").then((m) => m.go(kind === "clean" ? "layout" : "pipeline"));
      n.close();
    };
  } catch (_e) { /* a browser without page notifications */ }
}

// Turn notifications on (from the Run menu: a click, so the browser may ask).
export async function enableNotifications(on) {
  safeStorage.set("ll.notifyRuns", on ? "1" : "0");
  if (!on) return { ok: true };
  if (!("Notification" in window)) return { ok: false, why: "This window can't show notifications." };
  if (Notification.permission === "granted") return { ok: true };
  if (Notification.permission === "denied") return { ok: false, why: "Notifications are blocked for LanEx in this browser's site settings." };
  const p = await Notification.requestPermission().catch(() => "default");
  return p === "granted" ? { ok: true } : { ok: false, why: "LanEx wasn't allowed to show notifications." };
}

// A short two-note chime (rising when clean), made here: no sound file.
function chime(ok) {
  try {
    const ac = new (window.AudioContext || window.webkitAudioContext)();
    const notes = ok ? [660, 880] : [520, 390];
    notes.forEach((f, i) => {
      const o = ac.createOscillator(), g = ac.createGain();
      o.type = "sine"; o.frequency.value = f;
      const t = ac.currentTime + i * 0.16;
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.18, t + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t + 0.28);
      o.connect(g).connect(ac.destination);
      o.start(t); o.stop(t + 0.3);
    });
    setTimeout(() => ac.close(), 900);
  } catch (_e) { /* no audio */ }
}
