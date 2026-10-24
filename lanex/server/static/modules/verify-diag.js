// verify-diag.js — Verify's diagnosis panels, drawn from a run's problems
// (problems.js / controller/problems.py).
//
// Timing, the way experienced engineers answer "my design fails timing":
//   where it first failed   every timing analysis of the run in order (before
//                           placement with ideal clocks, during place and
//                           route, after routing): a path that already fails
//                           before placement is logic or constraints, never
//                           placement (r/chipdesign, "When does fixing timing
//                           stop being a PD problem?")
//   what fails              the failing endpoints by kind, from LibreLane's
//                           own violator lists: inputs and outputs first
//                           (constraints before logic)
//   the worst path          where its time goes against the clock period
//                           (AMD UG949: look at the worst violation first)
//   WNS and TNS             with the endpoint count beside TNS
// DRC, the way engineers read hundreds of errors: a few rules in a few
// places (r/chipdesign "Stuck with DRC Errors"), each place one click from
// Layout, and a note when the checkers disagree. OpenROAD's own DRC viewer
// groups by rule only; the places are LanEx's.

import { fmt } from "./api.js";
import { icon } from "./icons.js";
import { fixListHtml } from "./problems.js";

const esc = (s) => fmt.escape(s == null ? "" : String(s));
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const ns = (v, d = 2) => (isNum(v) ? (v < 0 ? "−" : v > 0 ? "+" : "") + Math.abs(v).toFixed(d) : "—");

const KIND = {
  "reg-reg": { label: "register → register", short: "reg → reg", c: "var(--chart-1)" },
  "in-reg": { label: "input → register", short: "in → reg", c: "var(--chart-2)" },
  "reg-out": { label: "register → output", short: "reg → out", c: "var(--chart-3)" },
  "in-out": { label: "input → output", short: "in → out", c: "var(--chart-4)" },
};

function head(p, kicker) {
  return "<div class='dx-head'><div><div class='an-eyebrow'>" + esc(kicker) + "</div><h3 class='dx-title'>" + esc(p.title) + "</h3></div>" +
    "<span class='vf-pill is-" + esc(p.severity) + "'>" + (p.severity === "fail" ? "Fails the run" : "Warning") + "</span></div>";
}

function fixesBlock(p, tag) {
  const set = (p.fixes || []);
  if (!set.length) return "";
  return "<div class='dx-fixes'><div class='dx-k'>What to change</div>" + fixListHtml(set, { tag, title: p.title }) + "</div>";
}

function notesBlock(p) {
  return (p.notes || []).map((n) => "<p class='dx-note'>" + icon("dot", { size: 12 }) + "<span>" + esc(n) + "</span></p>").join("");
}

// ------------------------------------------------------------------ timing

export function timingDiagHtml(p, tag) {
  const d = p.diag || {};
  const body = d.kind === "setup" ? setupBody(d) : holdBody(d);
  return "<div class='an-card dx-card is-" + esc(p.severity) + "' id='vf-diag-" + esc(d.kind) + "'>" + head(p, d.kind === "setup" ? "Setup diagnosis" : "Hold diagnosis") +
    "<p class='dx-plain'>" + esc(p.plain) + "</p>" + body +
    "<div class='dx-foot'>" + fixesBlock(p, tag) + "<div class='dx-notes'>" + notesBlock(p) + "</div></div></div>";
}

function numbersHtml(d) {
  const per = isNum(d.tns) && d.endpoints ? d.tns / d.endpoints : null;
  return "<dl class='dx-nums'>" +
    "<div><dt><span class='has-tip' tabindex='0' data-an-tip='Worst negative slack: the one worst path. Negative means it misses the clock.'>WNS</span></dt><dd class='is-bad'>" + ns(d.ws) + "<small>ns</small></dd></div>" +
    "<div><dt><span class='has-tip' tabindex='0' data-an-tip='Total negative slack: every failing endpoint added up. The same TNS can be a few paths far off or many just off: read it with the count.'>TNS</span></dt><dd>" + ns(d.tns) + "<small>ns</small></dd></div>" +
    "<div><dt>Failing endpoints</dt><dd>" + esc(d.endpoints != null ? d.endpoints : "—") + "</dd></div>" +
    (per != null ? "<div><dt>On average</dt><dd>" + ns(per) + "<small>ns each</small></dd></div>" : "") +
    "<div><dt>Corner</dt><dd class='dx-corner'>" + esc(d.corner || "—") + "</dd></div></dl>";
}

function setupBody(d) {
  return numbersHtml(d) + "<div class='dx-grid'>" +
    "<section class='dx-sec'><div class='dx-k'>Where it first failed</div>" + timelineHtml(d) + "</section>" +
    "<section class='dx-sec'><div class='dx-k'>What fails</div>" + kindsHtml(d) + "</section>" +
    "</div>" + pathHtml(d);
}

function holdBody(d) {
  return numbersHtml(d) + (d.kinds && Object.keys(d.kinds).length
    ? "<section class='dx-sec'><div class='dx-k'>What fails</div>" + kindRow("After routing", d.kinds) + legendHtml(d.kinds) + "</section>" : "");
}

// One column per timing analysis, a bar up for slack met, down for missed.
function timelineHtml(d) {
  const t = d.timeline || [];
  if (!t.length) return "<p class='muted'>No timing analyses were recorded.</p>";
  const max = Math.max(0.05, ...t.map((x) => Math.abs(x.ws || 0)));
  const firstBad = t.findIndex((x) => isNum(x.ws) && x.ws < 0 && x.same_corner);
  const anyOther = t.some((x) => !x.same_corner);
  const cols = t.map((x, i) => {
    const h = Math.max(2, Math.round((Math.abs(x.ws || 0) / max) * 100));
    const bad = isNum(x.ws) && x.ws < 0;
    const tip = x.when + " (" + x.step + "), " + x.corner + ": worst setup slack " + ns(x.ws, 3) + " ns" +
      (x.ideal ? "\nIdeal clocks, no wires yet." : "") + (!x.same_corner ? "\nThis analysis times the default corner only." : "");
    return "<div class='dx-tl-col" + (bad ? " is-bad" : " is-ok") + (i === firstBad ? " is-first" : "") + (!x.same_corner ? " is-other" : "") +
      "' data-an-tip='" + esc(tip) + "' tabindex='0'>" +
      "<span class='dx-tl-v'>" + ns(x.ws) + (!x.same_corner ? "<sup>*</sup>" : "") + "</span>" +
      "<span class='dx-tl-plot'><span class='dx-tl-up'>" + (bad ? "" : "<i style='height:" + h + "%'></i>") + "</span>" +
        "<span class='dx-tl-dn'>" + (bad ? "<i style='height:" + h + "%'></i>" : "") + "</span></span>" +
      "<span class='dx-tl-w'>" + esc(x.when.replace(/^after /, "")) + "</span>" +
      (i === firstBad ? "<span class='dx-tl-first'>first fails</span>" : "") + "</div>";
  }).join("");
  return "<div class='dx-tl'>" + cols + "</div>" +
    (anyOther ? "<p class='dx-foot-note'><sup>*</sup> During place and route LibreLane times only the default corner (" +
      esc((t.find((x) => !x.same_corner) || {}).corner || "") + "), so those columns are another corner than " + esc(d.corner) + ".</p>" : "");
}

function kindRow(label, kinds) {
  const total = Object.values(kinds || {}).reduce((a, b) => a + b, 0);
  if (!total) return "";
  const order = ["in-reg", "reg-out", "in-out", "reg-reg"];
  return "<div class='dx-kind'><span class='dx-kind-l'>" + esc(label) + "</span><span class='dx-kind-bar' role='img' aria-label='" +
    esc(order.filter((k) => kinds[k]).map((k) => kinds[k] + " " + KIND[k].label).join(", ")) + "'>" +
    order.filter((k) => kinds[k]).map((k) => "<i style='flex-grow:" + kinds[k] + ";background:" + KIND[k].c + "' data-an-tip='" +
      esc(kinds[k] + " " + KIND[k].label) + "'></i>").join("") + "</span><b class='dx-kind-n'>" + total + "</b></div>";
}

function legendHtml(...sets) {
  const seen = new Set(sets.flatMap((k) => Object.keys(k || {}).filter((x) => k[x])));
  return "<div class='dx-legend'>" + ["in-reg", "reg-out", "in-out", "reg-reg"].filter((k) => seen.has(k)).map((k) =>
    "<span><i style='background:" + KIND[k].c + "'></i>" + esc(KIND[k].label) + "</span>").join("") + "</div>";
}

function kindsHtml(d) {
  const at = d.kinds || {};
  const pre = d.first && d.before_placement ? d.first.kinds || {} : null;
  if (!Object.keys(at).length && !pre) return "<p class='muted'>LibreLane's violator list wasn't found for this run.</p>";
  return (pre ? kindRow("Before placement", pre) : "") + kindRow("After routing", at) + legendHtml(pre, at) +
    (d.io_first ? "<p class='dx-call'>" + icon("alert", { size: 13 }) + "<span>Inputs and outputs fail first: LibreLane's SDC gives " +
      esc(d.io_pct) + " % of the clock to the outside world on each side (IO_DELAY_CONSTRAINT). Check that constraint before the logic.</span></p>" : "");
}

// Where the worst path's time goes, against when it had to arrive.
const PARTS = [
  ["launch", "launch clock", "var(--chart-4)"], ["io_in", "input delay", "var(--chart-2)"], ["drive", "input driver", "var(--chart-2)"],
  ["clk_q", "clock → Q", "var(--chart-5)"], ["cells", "logic", "var(--chart-1)"], ["wires", "wires", "var(--chart-3)"],
];

export function pathVerdict(b, d = {}) {
  if (!b) return "";
  const io = (b.io_in || 0) + (b.io_out || 0) + (b.drive || 0);
  const parts = { logic: b.cells || 0, wire: b.wires || 0, clock: b.launch || 0, clkq: b.clk_q || 0, io };
  const top = Object.entries(parts).sort((x, y) => y[1] - x[1])[0][0];
  const f = b.fanout && b.fanout.n >= 16 ? " One net in it drives " + b.fanout.n + " loads (" + b.fanout.pin + "), worth buffering." : "";
  const say = {
    logic: "Mostly logic: " + b.levels + " cell" + (b.levels === 1 ? "" : "s") + " in a row between the registers. Fewer levels (pipelining) or a slower clock.",
    wire: "Mostly wire: the cells on it sit far apart. That is placement or the floorplan.",
    clock: "Mostly the launch clock: the clock reaches the first register " + b.launch.toFixed(2) + " ns late (skew).",
    clkq: "Mostly the first register's own clock-to-Q delay (" + b.clk_q.toFixed(2) + " ns), with " +
      (b.levels ? b.levels + " cell" + (b.levels === 1 ? "" : "s") : "no logic") + " after it" +
      (b.end === "out" ? ". The output pin carries the SDC's " + (d.out_load ? d.out_load + " fF " : "") + "load (OUTPUT_CAP_LOAD) and " +
        (b.io_out || 0).toFixed(2) + " ns of the clock is kept for outside the chip (IO_DELAY_CONSTRAINT)." : "."),
    io: "Mostly the I/O constraint: " + io.toFixed(2) + " ns of it is reserved for the outside world.",
  }[top];
  return say + f;
}

function pathHtml(d) {
  const p = d.path, b = p && p.budget;
  if (!b || !isNum(b.arrival) || !isNum(b.required)) return "";
  const scale = Math.max(b.arrival, b.required + (b.io_out || 0) + (b.setup || 0) + (b.uncertainty || 0), b.period || 0) * 1.04 || 1;
  const pct = (v) => (Math.max(0, v) / scale) * 100;
  const segs = PARTS.filter(([k]) => (b[k] || 0) > 0.0005).map(([k, label, c]) =>
    "<i style='width:" + pct(b[k]).toFixed(2) + "%;background:" + c + "' data-an-tip='" + esc(label + ": " + b[k].toFixed(3) + " ns") + "'></i>").join("");
  const reserve = (b.io_out || 0) + (b.setup || 0) + (b.uncertainty || 0);
  const start = b.start === "in" ? "input " : "register ";
  const end = b.end === "out" ? "output " : "register ";
  return "<section class='dx-sec dx-path'><div class='dx-k'>The worst path · " + esc(start + "→ " + end) +
      "<span class='dx-path-pins'>" + esc((p.startpoint || "") + " → " + (p.endpoint || "")) + "</span></div>" +
    "<div class='dx-bud' role='img' aria-label='" + esc("Arrives at " + b.arrival.toFixed(2) + " ns, needed by " + b.required.toFixed(2) + " ns") + "'>" +
      "<div class='dx-bud-bar'>" + segs +
        "<span class='dx-bud-req' style='left:" + pct(b.required).toFixed(2) + "%' data-an-tip='" + esc("Needed by " + b.required.toFixed(3) + " ns: the clock period " +
          (b.period != null ? b.period : "") + " ns, minus " + reserve.toFixed(2) + " ns (output delay, setup, uncertainty)") + "'></span>" +
        (b.arrival > b.required ? "<span class='dx-bud-over' style='left:" + pct(b.required).toFixed(2) + "%;width:" + pct(b.arrival - b.required).toFixed(2) + "%'></span>" : "") +
        (isNum(b.period) ? "<span class='dx-bud-per' style='left:" + pct(b.period).toFixed(2) + "%' data-an-tip='The clock period'></span>" : "") +
      "</div>" +
      "<div class='dx-bud-k'>" + PARTS.filter(([k]) => (b[k] || 0) > 0.0005).map(([k, label, c]) =>
        "<span><i style='background:" + c + "'></i>" + esc(label) + " <b>" + b[k].toFixed(2) + "</b></span>").join("") +
        "<span class='dx-bud-sum'>arrives <b>" + b.arrival.toFixed(2) + "</b> · needed by <b>" + b.required.toFixed(2) + "</b> ns</span></div>" +
    "</div><p class='dx-say'>" + esc(pathVerdict(b, d)) + "</p>" +
    (p.report ? "<button class='btn btn-ghost btn-xs' data-vf-view='" + esc(p.report) + "' data-vf-title='" + esc("Timing report · " + (p.corner || "")) + "'>" +
      icon("eye", { size: 12 }) + " The full path in " + esc(p.report.split("/").slice(-2).join("/")) + "</button>" : "") + "</section>";
}

// ------------------------------------------------------------------ DRC

export function drcDiagHtml(p, tag, pick) {
  const d = p.diag || {};
  const srcs = (d.sources || []).filter((s) => s.total).sort((a, b) => b.total - a.total);
  if (!srcs.length) return "";
  const s = srcs.find((x) => x.id === pick) || srcs[0];
  const nRules = s.rules.filter((r) => r.count).length;
  const nPlaces = s.places.length + (s.more_places || 0);
  const tabs = srcs.length > 1 ? "<span class='seg dx-src' role='group' aria-label='Checker'>" + srcs.map((x) =>
    "<button class='seg-btn" + (x === s ? " is-active" : "") + "' data-dx-src='" + esc(x.id) + "' aria-pressed='" + (x === s) + "'>" + esc(x.label) +
    " <span class='vf-seg-n'>" + x.total + "</span></button>").join("") + "</span>" : "";
  const rules = s.rules.filter((r) => r.count).map((r) =>
    "<li><span class='dx-rule-p'>" + esc(r.plain) + "</span><code title='" + esc(r.description || r.name) + "'>" + esc(r.name.replace(/^.*\(([^)]+)\)$/, "$1")) + "</code><b>" + r.count + "</b></li>").join("");
  const places = s.places.map((pl, i) =>
    "<li><span class='dx-pl-n'>" + (i + 1) + "</span><span class='dx-pl-t'><span><b>" + pl.count + "</b> " + esc(pl.where ? "near the " + pl.where : "together") +
      "</span><small>" + esc(pl.rules.map((r) => r.name.replace(/^.*\(([^)]+)\)$/, "$1") + (pl.rules.length > 1 ? " ×" + r.count : "")).join(", ")) + " · at " +
      esc(pl.center[0].toFixed(1) + ", " + pl.center[1].toFixed(1)) + " µm</small></span>" +
      "<button class='btn btn-ghost btn-xs' data-go='layout' data-go-box='" + esc(pl.bbox.map((v) => v.toFixed(2)).join(",")) + "'>" + icon("grid", { size: 12 }) + " Show</button></li>").join("");
  return "<div class='an-card dx-card dx-drc is-" + esc(p.severity) + "' id='vf-diag-drc'>" +
    "<div class='dx-head'><div><div class='an-eyebrow'>DRC diagnosis</div><h3 class='dx-title'>" + s.total + " violation" + (s.total === 1 ? "" : "s") +
      " <span class='dx-eq'>=</span> " + nRules + " rule" + (nRules === 1 ? "" : "s") + " in " + nPlaces + " place" + (nPlaces === 1 ? "" : "s") + "</h3></div>" + tabs + "</div>" +
    "<p class='dx-plain'>Engineers read DRC this way: a few rules in a few places, where fixing one often clears several. Markers within " +
      esc(d.radius) + " µm of each other count as one place.</p>" +
    "<div class='dx-drc-grid'>" + mapHtml(d.die, s) +
      "<section class='dx-sec'><div class='dx-k'>Rules</div><ol class='dx-rules'>" + rules + "</ol></section>" +
      "<section class='dx-sec'><div class='dx-k'>Places</div><ol class='dx-places'>" + places + "</ol>" +
        (s.more_places ? "<p class='muted'>" + s.more_places + " smaller places more in the report.</p>" : "") +
        (s.listed < s.total ? "<p class='muted'>" + s.listed + " of " + s.total + " markers are placed; the rest are only counted.</p>" : "") + "</section>" +
    "</div>" + (p.notes || []).map((n) => "<p class='vf-callout is-info dx-checkers'>" + icon("alert", { size: 13 }) + " " + esc(n) + "</p>").join("") +
    fixesBlock({ ...p, fixes: (p.fixes || []).filter((f) => f.kind === "setting") }, tag) + "</div>";
}

// The die, with each place a circle where its markers are (area by count).
function mapHtml(die, s) {
  if (!die || die.length !== 4) return "";
  const [x0, y0, x1, y1] = die;
  const w = x1 - x0, h = y1 - y0;
  if (!(w > 0 && h > 0)) return "";
  const max = Math.max(1, ...s.places.map((p) => p.count));
  const r0 = Math.min(w, h) * 0.035, r1 = Math.min(w, h) * 0.13;
  const dots = s.places.map((p, i) => {
    const r = r0 + (r1 - r0) * Math.sqrt(p.count / max);
    const cx = p.center[0] - x0, cy = h - (p.center[1] - y0);
    return "<g class='dx-dot'><a href='#' data-go='layout' data-go-box='" + esc(p.bbox.map((v) => v.toFixed(2)).join(",")) + "' aria-label='" +
      esc("Place " + (i + 1) + ": " + p.count + " violations, show in Layout") + "'><circle cx='" + cx.toFixed(2) + "' cy='" + cy.toFixed(2) + "' r='" + r.toFixed(2) + "'/>" +
      "<text x='" + cx.toFixed(2) + "' y='" + cy.toFixed(2) + "' font-size='" + (r * 0.9).toFixed(2) + "'>" + (i + 1) + "</text></a></g>";
  }).join("");
  return "<figure class='dx-map'><svg viewBox='" + (-w * 0.02).toFixed(2) + " " + (-h * 0.02).toFixed(2) + " " + (w * 1.04).toFixed(2) + " " + (h * 1.04).toFixed(2) +
    "' preserveAspectRatio='xMidYMid meet' role='img' aria-label='Where the violations are on the die'>" +
    "<rect class='dx-die' x='0' y='0' width='" + w.toFixed(2) + "' height='" + h.toFixed(2) + "'/>" + gridLines(w, h) + dots + "</svg>" +
    "<figcaption>" + esc(w.toFixed(1) + " × " + h.toFixed(1)) + " µm die</figcaption></figure>";
}

function gridLines(w, h) {
  let out = "";
  for (let i = 1; i < 3; i++) {
    out += "<line class='dx-third' x1='" + (w * i / 3).toFixed(2) + "' y1='0' x2='" + (w * i / 3).toFixed(2) + "' y2='" + h.toFixed(2) + "'/>";
    out += "<line class='dx-third' x1='0' y1='" + (h * i / 3).toFixed(2) + "' x2='" + w.toFixed(2) + "' y2='" + (h * i / 3).toFixed(2) + "'/>";
  }
  return out;
}
