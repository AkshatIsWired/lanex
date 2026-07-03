// watch.js — metric regression watch (E4.2). Per-design list of "this metric
// must stay <cmp> <threshold>" rules; a finished run is checked against it and
// any breach is surfaced as a toast. Accuracy rules (never misguide the user):
//   * a rule is only evaluated when the run ACTUALLY produced that metric and the
//     value is finite — a missing/inf/NaN metric is reported as neither pass nor
//     fail (no invented verdicts);
//   * the observed value shown in the warning is the run's real number.
import { api, fmt } from "./api.js";
import { state } from "./state.js";
import { toast } from "./toast.js";

const CMPS = [">=", "<=", ">", "<", "==", "!="];

let _rules = [];
let _loadedFor = null;

function satisfied(v, cmp, t) {
  switch (cmp) {
    case ">": return v > t;
    case "<": return v < t;
    case ">=": return v >= t;
    case "<=": return v <= t;
    case "==": return v === t;
    case "!=": return v !== t;
    default: return true;
  }
}

// Mirror of history.evaluate_watch — returns the rules a metrics dict violates.
export function evaluateWatch(metrics, rules) {
  const out = [];
  metrics = metrics || {};
  for (const r of rules || []) {
    if (!(r.metric in metrics)) continue;
    const v = metrics[r.metric];
    if (typeof v !== "number" || !isFinite(v)) continue;  // skip missing/inf/NaN
    if (!satisfied(v, r.cmp, r.threshold)) {
      out.push({ metric: r.metric, value: v, cmp: r.cmp, threshold: r.threshold });
    }
  }
  return out;
}

async function loadRules() {
  const design = state.designDir || "";
  if (_loadedFor === design) return _rules;
  try {
    const res = await api.getWatch(design || undefined);
    _rules = Array.isArray(res.rules) ? res.rules : [];
  } catch (_e) { _rules = []; }
  _loadedFor = design;
  return _rules;
}

async function save() {
  try {
    const res = await api.setWatch(state.designDir || "", _rules);
    if (res && Array.isArray(res.rules)) _rules = res.rules;
  } catch (ex) {
    toast.show("Could not save watch list: " + (ex.message || ex), "error");
  }
}

// Evaluate the just-finished run and warn on each breach. Called from flow_done.
// Fetches the newest run's CANONICAL metrics from the server (not state.metrics,
// which may lag render timing) so a warning is always about real, current data.
export async function checkAfterRun() {
  const rules = await loadRules();
  if (!rules.length) return;
  let metrics = state.metrics || {};
  try {
    const runs = await api.runs(state.designDir || undefined);
    const latest = runs && runs[0];
    if (latest) {
      const view = await api.run(latest.tag);
      if (view && view.metrics && view.metrics.values) metrics = view.metrics.values;
    }
  } catch (_e) { /* fall back to state.metrics — still real, just possibly older */ }
  const viols = evaluateWatch(metrics, rules);
  for (const v of viols) {
    toast.show("Watch: " + v.metric + " = " + fmt.metric(v.value) +
      " — expected " + v.cmp + " " + v.threshold, "error");
  }
}

export async function renderWatch() {
  const body = document.getElementById("watch-body");
  if (!body) return;
  const rules = await loadRules();
  const metricNames = Object.keys(state.metrics || {}).sort();
  const opts = metricNames.map((m) => "<option value='" + fmt.escape(m) + "'></option>").join("");

  const rows = rules.length
    ? rules.map((r, i) =>
        "<div class='watch-row'><code>" + fmt.escape(r.metric) + "</code> " +
        "<span class='muted'>" + fmt.escape(r.cmp) + " " + fmt.escape(String(r.threshold)) + "</span>" +
        "<button class='btn btn-ghost watch-del' data-i='" + i + "' aria-label='Remove rule'>✕</button></div>").join("")
    : "<p class='muted'>No watch rules yet. Add one below — you'll be warned after a run breaks it.</p>";

  body.innerHTML =
    "<div class='watch-list'>" + rows + "</div>" +
    "<div class='watch-add' style='display:flex;gap:var(--s-2);flex-wrap:wrap;align-items:center;margin-top:var(--s-3)'>" +
    "<input class='inp' id='watch-metric' list='watch-metrics' placeholder='metric key (e.g. timing__setup__ws)' style='flex:2;min-width:220px'/>" +
    "<datalist id='watch-metrics'>" + opts + "</datalist>" +
    "<select class='inp' id='watch-cmp'>" + CMPS.map((c) => "<option>" + c + "</option>").join("") + "</select>" +
    "<input class='inp' id='watch-threshold' type='number' step='any' placeholder='threshold' style='width:120px'/>" +
    "<button class='btn btn-ghost' id='watch-add-btn'>Add rule</button></div>" +
    (metricNames.length ? "" : "<p class='hint' style='margin-top:var(--s-2)'>Metric names autocomplete once a run's metrics are loaded.</p>");

  body.querySelectorAll(".watch-del").forEach((b) =>
    b.addEventListener("click", async () => {
      _rules.splice(Number(b.dataset.i), 1);
      await save();
      renderWatch();
    }));
  body.querySelector("#watch-add-btn").addEventListener("click", async () => {
    const metric = (document.getElementById("watch-metric").value || "").trim();
    const cmp = document.getElementById("watch-cmp").value;
    const thRaw = document.getElementById("watch-threshold").value;
    const threshold = Number(thRaw);
    if (!metric) { toast.show("Enter a metric key.", "warn"); return; }
    if (thRaw === "" || !isFinite(threshold)) { toast.show("Enter a numeric threshold.", "warn"); return; }
    if (!CMPS.includes(cmp)) { toast.show("Pick a comparator.", "warn"); return; }
    _rules.push({ metric, cmp, threshold });
    await save();
    renderWatch();
  });
}
