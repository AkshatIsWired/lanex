// logs.js — the live output of the running flow, kept for Flow.
//
// Every line the run prints, tagged with the step it belongs to (a step's
// lines follow its "Running" marker). Flow shows the running step's share in
// its log viewer as it arrives; a finished step's log is read from its file.
// Tool installs and other work outside a run go to the Logs panel
// (logdrawer.js), not here.

const MAX = 200000;          // lines kept for one run; older ones drop first
let lines = [];              // [{ t, step }]
let step = null;             // the step being written now
let pending = [];
let timer = 0;
const subs = new Set();

function flush() {
  timer = 0;
  if (!pending.length) return;
  const batch = pending;
  pending = [];
  for (const fn of subs) { try { fn(batch, { step }); } catch (e) { console.error("live log", e); } }
}

export const renderLogs = {
  append(event) {
    const msg = event.payload?.message ?? event.message;
    if (msg == null) return;
    for (const t of String(msg).replace(/\r/g, "").split("\n")) {
      const l = { t, step };
      lines.push(l);
      pending.push(l);
    }
    if (lines.length > MAX) lines = lines.slice(-Math.floor(MAX * 0.8));
    if (!timer) timer = setTimeout(flush, 120);
  },
  // A step started: what follows is its output.
  markStep(stepId) { if (stepId) step = stepId; },
  // A new run: start over.
  clear() { lines = []; step = null; pending = []; },
};

// The lines of one step (or of the whole run) received so far.
export function liveLines(stepId) {
  return (stepId ? lines.filter((l) => l.step === stepId) : lines).map((l) => l.t);
}

// Every line so far with the step it belongs to ([{ t, step }], read only).
export function liveRows() { return lines; }

// fn(newLines, { step }) for each batch; returns an unsubscribe.
export function onLiveLog(fn) {
  subs.add(fn);
  return () => subs.delete(fn);
}
