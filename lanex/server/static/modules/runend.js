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
import { runSummary, fmtDur } from "./reportcard.js";

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

// Another project opened: the last run's result belongs to the project it
// ran in, so the status line, the run pill, the Flow tab's red mark and the
// window title (which names the open project) go back to idle.
export function clearRunResult() {
  if (state.status && state.status.running) return;
  _result = null;
  clearTimeout(_resultTimer);
  paintTitle();
  paintRail(false);
  const el = document.getElementById("overall-progress");
  if (el) { el.textContent = ""; delete el.dataset.tone; delete el.dataset.go; el.title = ""; }
  const pill = document.getElementById("run-pill");
  if (pill) {
    pill.classList.remove("pill-running", "pill-pass", "pill-warn", "pill-fail");
    pill.classList.add("pill-pending");
    pill.textContent = "idle";
  }
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
  // Flow's rule (flow.js model): LibreLane runs one step at a time, so a step
  // behind the newest one that started is done even if its event was missed.
  const sts = ids.map((id) => st[id]);
  let last = -1;
  sts.forEach((s, i) => { if (s && s !== "pending") last = i; });
  for (let i = 0; i < last; i++) if (!sts[i] || sts[i] === "pending" || sts[i] === "running") sts[i] = "done";
  const n = FS.stepCounts(sts);
  const cur = [...ids].reverse().find((id) => st[id] === "running");
  const stage = cur ? FS.stagesOf(ids.map((id) => ({ id })))[ids.indexOf(cur)] : null;
  return { ids, done: n.done, total: n.total, current: n.current, cur, stage };
}

function paintTitle() {
  const name = designName();
  if (state.status && state.status.running) {
    const c = current();
    document.title = (c.total ? "Step " + c.current + " of " + c.total + (c.stage ? " · " + FS.stageLabel(c.stage) : "") : "Starting") +
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
  // The count first: a narrow window cuts the end of the line, not the count.
  el.textContent = "Step " + c.current + " of " + c.total + (c.stage ? " · " + FS.stageLabel(c.stage) : "") + (name ? " · " + name : "") +
    (typeof eta === "number" && eta > 0 ? " · ~" + Math.max(1, Math.round(eta / 60)) + " min left" : "");
  el.dataset.go = "pipeline";
  delete el.dataset.tone;
  el.title = "";
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
  // The shared run verdict (controller/verify.run_verdict, the one Flow,
  // Verify and Runs show) decides the words and the colour when it is known.
  const rv = ev.cancelled ? { state: "stopped", label: "Stopped" } : (vf && vf.run_verdict) || null;
  const numSum = rx && (rx.kind === "clean" || rx.kind === "checks-failed")
    ? runSummary({ tag, design: designName(), rx: { kind: "clean" }, vf: null, rs, name }) : null;
  const secs = ((rs && rs.steps) || []).filter((s) => !s.from).reduce((a, s) => a + (s.runtime_s || 0), 0);
  const out = withVerdict(sum, rv, { tag, rx, name, nums: numSum ? numSum.body : "", secs });
  _result = out.mark + " " + out.label;
  paintTitle();
  paintRail(out.tone === "fail");
  if (status) {
    status.textContent = _result + (out.tail ? " · " + out.tail : "");
    status.dataset.tone = out.tone;
    status.title = out.title;
    status.dataset.go = "pipeline";
  }
  const pill = document.getElementById("run-pill");
  if (pill) {
    pill.classList.remove("pill-running", "pill-pass", "pill-warn", "pill-fail", "pill-pending");
    pill.classList.add(out.tone === "pass" ? "pill-pass" : out.tone === "warn" ? "pill-warn" : out.tone === "fail" ? "pill-fail" : "pill-pending");
    pill.textContent = rv && rv.state === "stopped" ? "stopped" : "done";
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
  if (rv && rv.state === "warning") acts.splice(0, acts.length, { label: "Show timing", run: () => go("verify") }, { label: "See chip", run: () => go("layout") });
  const msg = out.title + (out.body ? (/: /.test(out.title) ? ". " : ": ") + out.body : "");
  const ttype = { pass: "success", warn: "warn", fail: "error", info: "info" }[out.tone] || "info";
  toast.show(msg, ttype, out.tone === "pass" ? 10000 : out.tone === "warn" ? 16000 : out.tone === "info" ? 6000 : 0, acts);

  if (prefs.chime()) chime(out.tone === "pass");
  if (prefs.notify() && !(document.visibilityState === "visible" && document.hasFocus())) notify(out, out.tone === "pass" ? "clean" : kind);
}

// The run-end words from the shared verdict: {tone: pass|warn|fail|info,
// mark, label (status bar + window title), tail, title, body (toast and
// notification)}. Without a verdict (Verify didn't answer in time) the
// report's own summary stands.
export function withVerdict(sum, rv, { tag = "", rx = null, name = (id) => id, nums = "", secs = 0 } = {}) {
  const who = sum.title && tag && sum.title.includes(tag) ? sum.title.slice(0, sum.title.indexOf(tag) + tag.length) : tag;
  // nums: the numbers line, "setup −0.17 ns · 120 × 120 µm · 1 min 20 s"
  // (runSummary's clean body); the status bar keeps only the time.
  const time = secs ? fmtDur(secs) : "";
  const halt = rx && rx.kind === "halted" ? (sum.short || "") : "";
  const s = rv && rv.state;
  if (s === "passed") {
    const tone = rv.warnings ? "warn" : "pass";
    return { tone, mark: "✓", label: rv.label || "Clean", tail: time,
      title: who + ": " + (rv.label || "clean"), body: tone === "warn" && sum.tone === "warn" ? sum.body : nums };
  }
  if (s === "warning") {
    const m = rv.timing_miss;
    const short = m && typeof m.ws === "number" ? "Timing misses (" + m.kind + " " + (m.ws < 0 ? "−" : "+") + Math.abs(m.ws).toFixed(2) + " ns)" : "";
    return { tone: "warn", mark: "▲", label: short || rv.label || "Finished with timing misses", tail: time,
      title: who + ": " + (rv.label || "finished with timing misses"),
      // The label already gives the slack: the body keeps size and time.
      body: nums.split(" · ").filter((x) => !/^(setup|hold) /.test(x)).join(" · ") };
  }
  if (s === "failed") {
    const label = rv.label || "Failed";
    const at = rx && rx.kind === "halted" && rx.step ? name(rx.step.id) : "";
    return { tone: "fail", mark: "✗", label: label + (at && !label.includes(at) ? " (" + at + ")" : ""),
      tail: halt && !label.toLowerCase().includes(halt.toLowerCase()) ? halt : "",
      title: who + ": " + label.charAt(0).toLowerCase() + label.slice(1) + (at && !label.includes(at) ? " (" + at + ")" : ""), body: sum.body || "" };
  }
  if (s === "stopped") {
    const mine = rx && rx.kind === "stopped";
    return { tone: "info", mark: "■", label: mine ? "Stopped by you" : rv.label || "Stopped", tail: "",
      title: who + (mine ? ": you stopped it" : ": " + (rv.label || "stopped").toLowerCase()), body: "" };
  }
  if (s === "incomplete") {
    return { tone: "warn", mark: "▲", label: rv.label || "Not enough to call it", tail: time,
      title: who + ": " + (rv.label || "not enough to call it").toLowerCase(), body: nums };
  }
  // No verdict: the report's summary.
  const tone = sum.ok ? (sum.tone === "warn" ? "warn" : "pass") : rx && rx.kind === "stopped" ? "info" : sum.tone === "warn" ? "warn" : "fail";
  const label = sum.ok ? (tone === "warn" ? "Clean, with warnings" : "Clean")
    : rx && rx.kind === "stopped" ? "Stopped by you"
    : rx && rx.kind === "halted" ? "Stopped" + (rx.step ? " at " + name(rx.step.id) : "")
    : tone === "fail" ? "Failed" : "Done";
  const tail = sum.ok ? time : (sum.short && !label.toLowerCase().includes(String(sum.short).toLowerCase()) ? sum.short : "");
  return { tone, mark: { pass: "✓", warn: "▲", fail: "✗", info: "■" }[tone], label, tail, title: sum.title, body: sum.body || "" };
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
