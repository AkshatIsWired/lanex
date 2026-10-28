// guide.js — the first-run experience: a "Press Start" card on a first launch,
// the first-chip guide (six beats on a real example, each moved on by the app
// itself) and a five-stop tour of the rail. Driver.js draws the spotlight and
// the pointer card (vendor/driverjs, MIT); what they say is in guide-steps.js.
//
//   document.dispatchEvent(new CustomEvent("g:guide", {detail: {action: "tour"|"first-chip"|"reset"}}))
//
// starts either from anywhere (Help, the palette). Nothing starts by itself
// except the Press Start card, once, when there are no projects yet.

import { api, fmt } from "./api.js";
import { state, safeStorage } from "./state.js";
import { toast } from "./toast.js";
import { go } from "./nav.js";
import { BEATS, GUIDE_TEMPLATE, advance, simOk, pillText, normState, counter, TOUR, chipFacts } from "./guide-steps.js";

const KEY = "ll.guide.state";
const SEEN = "ll.guide.seen";
const esc = (s) => fmt.escape(s == null ? "" : String(s));
const reduced = () => !!window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let G = normState(safeStorage.get(KEY, null));
let _drv = null;          // the Driver.js instance on screen
let _quiet = false;       // closing it ourselves (not the user's Esc or ×)
let _driverMod = null;
let _seq = 0;             // a newer pointer cancels an older one still waiting

function save() {
  safeStorage.set(KEY, JSON.stringify(G));
  document.body.classList.toggle("guide-on", !!G.active);
}

// ------------------------------------------------------------ waiting
// Pages render after they show and fill in later: wait until the element is
// on screen (laid out, not hidden), for up to `ms`.
export function visible(el) {
  return !!el && el.isConnected && el.getClientRects().length > 0 && !el.closest("[hidden]");
}
function waitFor(sel, ms = 8000) {
  return new Promise((resolve) => {
    const t0 = performance.now();
    const look = () => {
      const el = typeof sel === "function" ? sel() : document.querySelector(sel);
      if (visible(el)) return resolve(el);
      if (performance.now() - t0 > ms) return resolve(null);
      setTimeout(look, 120);
    };
    look();
  });
}

// ------------------------------------------------------------ the pointer
async function driverMod() {
  if (!_driverMod) _driverMod = await import("/static/vendor/driverjs/driver.js.mjs");
  return _driverMod;
}

export function hidePointer() {
  if (!_drv) return;
  _quiet = true;
  try { _drv.destroy(); } catch (_e) {}
  _quiet = false;
  _drv = null;
}

// Point at one element (or the middle of the screen with no element).
// o: {el, eyebrow, title, body (trusted HTML), buttons: [{label, primary, run}],
//     side, hideOnTargetClick, onClose, tour}
async function point(o) {
  const my = ++_seq;
  const { driver } = await driverMod();
  if (my !== _seq) return;
  hidePointer();
  const el = typeof o.el === "string" ? document.querySelector(o.el) : o.el;
  const d = driver({
    overlayOpacity: 0.72,
    overlayColor: "#04060a",
    stagePadding: 6,
    stageRadius: 2,
    animate: !reduced(),
    smoothScroll: !reduced(),
    allowClose: true,
    allowKeyboardControl: true,
    popoverClass: "gd-pop" + (o.tour ? " gd-pop-tour" : "") + (el ? "" : " gd-pop-center"),
    onDestroyed: () => {
      if (_drv === d) _drv = null;
      if (!_quiet && o.onClose) o.onClose();
    },
  });
  _drv = d;
  d.highlight({
    element: el && visible(el) ? el : undefined,
    popover: {
      title: esc(o.title),
      description: o.body,
      side: o.side || "bottom",
      align: o.align || "start",
      showButtons: ["close"],
      onPopoverRender: (pop) => {
        pop.wrapper.setAttribute("aria-label", o.title);
        if (o.eyebrow) {
          const eb = document.createElement("div");
          eb.className = "gd-eyebrow";
          eb.textContent = o.eyebrow;
          pop.title.before(eb);
        }
        pop.closeButton.setAttribute("aria-label", o.tour ? "End the tour" : "Hide this tip");
        pop.footer.style.display = "flex";
        pop.previousButton.style.display = "none";
        pop.nextButton.style.display = "none";
        pop.progress.style.display = "none";
        let first = null;
        for (const b of o.buttons || []) {
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "gd-btn" + (b.primary ? " is-primary" : "");
          btn.textContent = b.label;
          btn.addEventListener("click", (e) => { e.stopPropagation(); b.run(); });
          pop.footerButtons.appendChild(btn);
          if (b.primary && !first) first = btn;
        }
        (first || pop.closeButton).focus({ preventScroll: true });
      },
    },
  });
  if (el && visible(el)) reticleOn(el, d);
  if (el && o.hideOnTargetClick) {
    el.addEventListener("click", () => { if (_drv === d) hidePointer(); }, { capture: true, once: true });
  }
}

// The hairline outline with L-shaped corner ticks, kept on the element while
// its pointer is up (it follows scrolling and resizing).
function reticleOn(el, d) {
  let r = document.getElementById("gd-reticle");
  if (!r) {
    r = document.createElement("div");
    r.id = "gd-reticle";
    r.className = "gd-reticle";
    r.setAttribute("aria-hidden", "true");
    r.innerHTML = "<span class='gd-tick tl'></span><span class='gd-tick tr'></span><span class='gd-tick bl'></span><span class='gd-tick br'></span>";
    document.body.appendChild(r);
  }
  const pad = 6;
  const step = () => {
    if (_drv !== d || !visible(el)) { r.hidden = true; return; }
    // The UI size is a CSS zoom on <html> (zoom.js): rects come back zoomed,
    // and fixed positions are zoomed again.
    const k = parseFloat(document.documentElement.style.zoom) || 1;
    const b = el.getBoundingClientRect();
    r.hidden = false;
    r.style.left = (b.left / k - pad) + "px";
    r.style.top = (b.top / k - pad) + "px";
    r.style.width = (b.width / k + 2 * pad) + "px";
    r.style.height = (b.height / k + 2 * pad) + "px";
    requestAnimationFrame(step);
  };
  step();
}

// ------------------------------------------------------------ the pill
function pill() {
  let p = document.getElementById("guide-pill");
  if (p) return p;
  p = document.createElement("div");
  p.id = "guide-pill";
  p.className = "guide-pill";
  p.hidden = true;
  p.innerHTML =
    "<button type='button' class='gp-open' data-tip='Show the current step'><span class='gp-n'></span><span class='gp-l'></span></button>" +
    "<button type='button' class='gp-x' aria-label='End the first-chip guide' data-tip='End the guide'>" +
    "<svg viewBox='0 0 24 24' width='12' height='12' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' aria-hidden='true'><path d='M6 6l12 12M18 6L6 18'/></svg></button>";
  p.querySelector(".gp-open").addEventListener("click", () => showBeat());
  p.querySelector(".gp-x").addEventListener("click", () => endGuide());
  const right = document.querySelector(".topbar .tb-right");
  if (right) right.before(p); else document.body.appendChild(p);
  return p;
}

function paintPill() {
  const p = pill();
  p.hidden = !G.active;
  if (!G.active) return;
  p.querySelector(".gp-n").textContent = pillText(G.beat);
  const b = BEATS[G.beat];
  p.querySelector(".gp-l").textContent = b ? b.label : "Your chip is ready";
  p.querySelector(".gp-open").setAttribute("aria-label", pillText(G.beat) + ": " + (b ? b.label : "done") + ". Show the step.");
}

// ------------------------------------------------------------ first chip
export function startFirstChip() {
  hideStart();
  safeStorage.set(SEEN, "1");
  G = { active: true, beat: 1, project: "" };
  // Already on an open blinky? Then the example is made.
  save();
  paintPill();
  showBeat();
}

export function endGuide({ quiet = false } = {}) {
  hidePointer();
  G = { active: false, beat: 1, project: "" };
  save();
  paintPill();
  if (!quiet) toast.show("Guide ended. Start it again from Help or Ctrl+K.", "info", 5000);
}

const eb = () => pillText(G.beat);

async function showBeat() {
  if (!G.active) return;
  const b = BEATS[G.beat];
  if (!b) return finale();
  if (b.id === "project") return beatProject();
  if (b.id === "sim") return beatSim();
  if (b.id === "pdk") return beatPdk();
  if (b.id === "run") return beatRun();
  if (b.id === "flow") return beatFlow();
}

async function beatProject() {
  go("setup", {}, { link: false });
  const tile = await waitFor("#project-empty [data-open='example']", 3000);
  const make = () => { hidePointer(); import("./wizard.js").then((m) => m.openWizard({ template: GUIDE_TEMPLATE })); };
  point({
    el: tile || "#setup-design",
    eyebrow: eb(),
    title: "Make the example chip",
    body: "<p>Blinky is a counter that blinks an LED: a few lines of Verilog with a testbench. It is the quickest of the examples to build.</p>" +
      "<p>Make it, keep the name, and press <b>Create project</b>.</p>",
    buttons: [{ label: "Make Blinky", primary: true, run: make }],
    hideOnTargetClick: true,
  });
}

async function beatSim() {
  const btn = await waitFor(() => {
    // Something else may change the page meanwhile (the wizard does): stay on the IDE.
    if (!document.getElementById("sec-ide")?.classList.contains("section-active")) go("ide", {}, { link: false });
    const n = document.getElementById("ide-sim-tbname");
    return n && !/no testbench/i.test(n.textContent) ? document.getElementById("ide-sim") : null;
  }, 10000);
  point({
    el: btn || "#ide-sim",
    eyebrow: eb(),
    title: "Simulate it",
    body: "<p>Before the long run, check the design does what you meant. <b>Simulate</b> builds the testbench " +
      "(<code>verify/blinky_tb.v</code>), runs it, and draws the waveform.</p>",
    buttons: [{ label: "Simulate", primary: true, run: () => { hidePointer(); document.getElementById("ide-sim")?.click(); } }],
    hideOnTargetClick: true,
  });
}

async function afterSim(detail) {
  if (!document.getElementById("sec-ide")?.classList.contains("section-active")) go("ide", {}, { link: false });
  const host = await waitFor("#ide-wave-host", 4000);
  point({
    el: host,
    eyebrow: eb(),
    title: "That's your design running",
    body: "<p>Each row is a signal over time. <code>clk</code> ticks, and after reset the output <code>led</code> flips every time the counter wraps." +
      (detail && detail.verdict === "passed" ? " The testbench says it passed." : "") + "</p>" +
      "<p>Click anywhere in the waveform to place the cursor: the Value column then shows every signal at that moment. Scroll to zoom.</p>",
    buttons: [{ label: "Next: pick the process", primary: true, run: () => showBeat() }],
    side: "top",
  });
}

async function simFailed(detail) {
  const st = await waitFor("#ide-sim-status", 3000);
  point({
    el: st,
    eyebrow: eb(),
    title: "The simulation didn't finish cleanly",
    body: "<p>The panel says what happened" + (detail && detail.verdict ? " (" + esc(detail.verdict) + ")" : "") +
      " and what to do about it. Fix it and simulate again, or skip ahead: the flow doesn't need a simulation.</p>",
    buttons: [
      { label: "Simulate again", primary: true, run: () => { hidePointer(); document.getElementById("ide-sim")?.click(); } },
      { label: "Skip this step", run: () => moveTo(G.beat + 1) },
      { label: "End guide", run: () => endGuide() },
    ],
    side: "top",
  });
}

async function beatPdk() {
  go("setup", { section: "setup-pdk" }, { link: false });
  const card = await waitFor("#setup-pdk", 4000);
  const pdk = state.selectedPdk || (document.getElementById("pdk-select") || {}).value || "";
  const pillTxt = (document.getElementById("pdk-readiness") || {}).textContent || "";
  const ready = /ready/i.test(pillTxt) && !/not|missing/i.test(pillTxt);
  const confirm = () => { hidePointer(); document.dispatchEvent(new CustomEvent("g:pdk_confirmed", { detail: { pdk, from: "guide" } })); };
  point({
    el: card,
    eyebrow: eb(),
    title: "Pick the process",
    body: ready
      ? "<p>The PDK is the foundry's recipe the chip is built for. <b>" + esc(pdk) + "</b> is installed and ready" +
        (/^sky130/.test(pdk) ? ": SkyWater's open 130 nm process, the usual first choice." : ".") + "</p>"
      : "<p>The PDK is the foundry's recipe the chip is built for. <b>" + esc(pdk || "No PDK") + "</b>: " + esc(pillTxt || "not checked yet") +
        ". Install it in Tools, or keep it if it says it downloads on the first run.</p>",
    buttons: ready
      ? [{ label: "Use " + pdk, primary: true, run: confirm }]
      : [{ label: "Open Tools", primary: true, run: () => { hidePointer(); go("tools"); } }, { label: "Use it anyway", run: confirm }],
  });
}

async function beatRun() {
  go("setup", { section: "setup-design" }, { link: false });
  const field = await waitFor(() => document.getElementById("pd-period")?.closest(".pd-field"), 4000);
  const ns = parseFloat((document.getElementById("pd-period") || {}).value);
  const mhz = ns > 0 ? Math.round(1000 / ns) : null;
  point({
    el: field || "#setup-design",
    eyebrow: eb(),
    title: "One setting worth knowing",
    body: "<p>The <b>clock period</b> is how fast the chip must run" + (ns > 0 ? ": " + esc(ns) + " ns is " + mhz + " MHz" : "") +
      ". A smaller period is a faster chip and harder to meet. Leave it for this run.</p>",
    buttons: [{ label: "Next: run it", primary: true, run: pointRun }],
  });
}

async function pointRun() {
  go("setup", { section: "setup-preflight" }, { link: false });
  const btn = await waitFor("#btn-run", 4000);
  btn?.scrollIntoView({ block: "center", behavior: reduced() ? "auto" : "smooth" });
  await new Promise((r) => setTimeout(r, reduced() ? 50 : 350));
  point({
    el: btn,
    eyebrow: eb(),
    title: "Run the flow",
    body: "<p>LanEx checks the design, the PDK and the tools, then LibreLane turns the Verilog into a layout: " +
      "synthesis, floorplan, placement, clock tree, routing and the sign-off checks.</p>",
    buttons: [{ label: "Run flow", primary: true, run: () => { hidePointer(); document.getElementById("btn-run")?.click(); } }],
    hideOnTargetClick: true,
    // Below the button: above it, the tip covered the preflight checks it talks about.
    side: "bottom",
  });
}

async function beatFlow() {
  if (!state.status || !state.status.running) {
    // Reopened after the run ended (or before it started): nothing to watch.
    go("pipeline", {}, { link: false });
  }
  const strip = await waitFor(() => document.getElementById("fl-strip") || document.getElementById("flow-runbar"), 6000);
  point({
    el: strip,
    eyebrow: eb(),
    title: "Watch it build",
    body: "<p>Each stage lights up as it finishes. Blinky takes a minute or two. Look around if you like: " +
      "the <b>" + esc(pillText(G.beat)) + "</b> pill at the top brings you back, and the guide moves on when the run ends.</p>",
    buttons: [{ label: "Watch it", primary: true, run: hidePointer }],
  });
}

async function runFailed(detail) {
  go("pipeline", {}, { link: false });
  const card = await waitFor(".fl-fail", 8000);
  const stopped = !!(detail && detail.cancelled);
  point({
    el: card || "#fl-strip",
    eyebrow: eb(),
    title: stopped ? "The run was stopped" : "The run stopped before the end",
    body: stopped
      ? "<p>Run it again when you are ready; the guide carries on when a run finishes.</p>"
      : "<p>This card says where it stopped and why, in the tool's own words. <b>What to change</b> lists fixes LanEx can apply for you. " +
        "Run it again after a fix; the guide carries on when a run finishes.</p>",
    buttons: [
      { label: "Run again", primary: true, run: () => { hidePointer(); document.getElementById("btn-run-global")?.click(); } },
      { label: "End guide", run: () => endGuide() },
    ],
    side: "bottom",
  });
}

function moveTo(beat) {
  G.beat = Math.min(beat, BEATS.length);
  save();
  paintPill();
  showBeat();
}

// The run finished clean: point at the layout, then 3D, then the finish card.
async function finale() {
  hidePointer();
  point({
    eyebrow: eb() + " · DONE",
    title: "Your chip is ready",
    body: "<p>LibreLane turned blinky.v into a GDS: the file a foundry makes the chip from. Have a look at it.</p>",
    buttons: [{ label: "See the layout", primary: true, run: showLayout }, { label: "Skip to the summary", run: finishCard }],
  });
}

async function showLayout() {
  hidePointer();
  go("layout", {}, { link: false });
  const view = await waitFor("#lx-view", 10000);
  point({
    el: view || "#sec-layout",
    eyebrow: eb() + " · DONE",
    title: "This is your chip, from above",
    body: "<p>Every rectangle is a shape on one layer of the process: the cells in rows, and the metal wires routed between them. " +
      "Scroll to zoom, drag to pan, and pick a stage along the top to see how it was built up.</p>",
    buttons: [{ label: "Show it in 3D", primary: true, run: show3d }, { label: "Finish", run: finishCard }],
    side: "left",
  });
}

async function show3d() {
  hidePointer();
  const b = document.getElementById("lx-3d-main");
  if (b && b.getAttribute("aria-pressed") !== "true") b.click();
  await new Promise((r) => setTimeout(r, 900));
  const view = await waitFor("#lx-view", 4000);
  point({
    el: view,
    eyebrow: eb() + " · DONE",
    title: "The same chip in 3D",
    body: "<p>Each metal layer at its real height, stacked over the cells. Drag to turn it; press the 3D view button again for the flat view.</p>",
    buttons: [{ label: "Finish", primary: true, run: finishCard }],
    side: "left",
  });
}

// The finish card: three numbers from the run itself, and three ways on.
async function finishCard() {
  hidePointer();
  const tag = state.selectedRunTag || (state.runs && state.runs[0] && state.runs[0].tag) || "";
  let facts = [], period = null;
  try {
    const [view, clk] = await Promise.all([
      tag ? api.run(tag) : null,
      tag ? api.provenance({ kind: "var", key: "CLOCK_PERIOD", tag }).catch(() => null) : null,
    ]);
    period = clockOf(clk);
    facts = chipFacts(view && view.summary, period);
  } catch (_e) { facts = []; }
  G = { active: false, beat: BEATS.length, project: G.project };
  save();
  paintPill();
  const ov = document.createElement("div");
  ov.className = "gd-scrim gd-finish-scrim";
  ov.innerHTML =
    "<div class='gd-card gd-finish' role='dialog' aria-modal='true' aria-labelledby='gd-fin-t'>" +
    reticle() +
    "<div class='gd-eyebrow'>FIRST CHIP 6/6 · DONE</div>" +
    "<h2 class='gd-title' id='gd-fin-t'>You built a chip.</h2>" +
    "<p class='gd-lede'>From Verilog to a GDS on " + esc(state.selectedPdk || "the PDK") + (tag ? ", in run <code>" + esc(tag) + "</code>" : "") + ". The numbers are the run's own.</p>" +
    (facts.length
      ? "<dl class='gd-facts'>" + facts.map((f) =>
          "<div class='gd-fact' title='" + esc(f.key) + "'><dt>" + esc(f.label) + "</dt><dd><b>" + esc(f.value) + "</b>" + (f.unit ? " <span>" + esc(f.unit) + "</span>" : "") + "</dd></div>").join("") + "</dl>"
      : "<p class='gd-lede muted'>The run's numbers aren't readable yet. Analytics has them.</p>") +
    "<div class='gd-next'>" +
    "<button type='button' class='gd-btn' data-g='verilog'>Change the Verilog</button>" +
    "<button type='button' class='gd-btn' data-g='sweep'>Try 3 clock speeds</button>" +
    "<button type='button' class='gd-btn is-primary' data-g='own'>Start my own design</button>" +
    "</div>" +
    "<button type='button' class='gd-close' aria-label='Close'>Close</button>" +
    "</div>";
  document.body.appendChild(ov);
  const close = () => { ov.remove(); document.removeEventListener("keydown", onKey, true); };
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
  ov.querySelector(".gd-close").addEventListener("click", close);
  ov.querySelector("[data-g='verilog']").addEventListener("click", () => { close(); go("ide", { rel: "src/blinky.v" }); });
  ov.querySelector("[data-g='sweep']").addEventListener("click", () => { close(); go("runs");
    // Faster, the same, slower: the run's clock period x 0.8, 1, 1.25. Tightest first,
    // so the preset's "stop at the first clean run" finds the fastest that works.
    const values = period ? [0.8, 1, 1.25].map((f) => String(+(period * f).toFixed(2))).join(", ") : undefined;
    import("./sweeps.js").then((m) => m.openSweepSheet("clock", { values }));
  });
  ov.querySelector("[data-g='own']").addEventListener("click", () => { close(); import("./wizard.js").then((m) => m.openWizard()); });
  ov.querySelector("[data-g='own']").focus();
}

function clockOf(p) {
  // The run's resolved.json line, verbatim: `"CLOCK_PERIOD": 10,`.
  const m = p && p.ok !== false && /"CLOCK_PERIOD"\s*:\s*([0-9.eE+-]+)/.exec(p.text || "");
  const n = m ? parseFloat(m[1]) : NaN;
  return n > 0 ? n : null;
}

// ------------------------------------------------------------ events
function onProgress(e) {
  if (!G.active) return;
  const type = e.type, d = e.detail || {};
  const was = G.beat;
  const now = advance(was, type, d);
  if (now !== was) {
    G.beat = now;
    if (type === "g:project_opened" && d.dir) G.project = d.dir;
    save();
    paintPill();
    if (type === "g:sim_done") return afterSim(d);
    // The wizard goes to Setup after it opens the project: point after that.
    if (type === "g:project_opened") return setTimeout(showBeat, 700);
    if (type === "g:run_started") {
      // Pressing Run shows Flow by itself (setup.js): point once it's there.
      return setTimeout(showBeat, 600);
    }
    return showBeat();
  }
  if (type === "g:sim_done" && BEATS[was] && BEATS[was].id === "sim" && !simOk(d) && d.verdict !== "stopped") return simFailed(d);
  if (type === "g:flow_done" && BEATS[was] && BEATS[was].id === "flow") return runFailed(d);
}

// Any simulation of the open project that ran to the end ticks step 2 of
// Setup's strip; outside the guide, say what comes next.
function onSimDone(e) {
  const d = e.detail || {};
  if (!simOk(d) || !state.designDir) return;
  safeStorage.set("ll.simok." + state.designDir, "1");
  import("./setup.js").then((m) => m.paintOnboardChecklist()).catch(() => {});
  if (G.active) return;
  toast.show("The simulation ran to the end. Next: run the flow.", "success", 8000, {
    label: "Go to Run",
    run: () => {
      go("setup", { section: "setup-preflight" }, { link: false });
      setTimeout(() => document.getElementById("btn-run")?.focus({ preventScroll: true }), 400);
    },
  });
}

// ------------------------------------------------------------ the tour
export async function startTour() {
  hideStart();
  safeStorage.set(SEEN, "1");
  let i = 0;
  const stops = TOUR.map((s) => ({ ...s }));
  // The System stop names what the rail really has: the Console drawer when
  // it exists, else the Manual page.
  const sys = stops.find((s) => s.id === "system");
  if (sys) {
    sys.body += document.querySelector('.side-tab[data-tab="manual"]')
      ? " Manual runs LibreLane commands yourself and shows the exact command line."
      : " The Console (Ctrl+`) runs LibreLane commands yourself and shows the exact command line.";
  }
  const show = async () => {
    const s = stops[i];
    const el = await waitFor(s.target, 1500);
    point({
      el,
      tour: true,
      eyebrow: "TOUR " + counter(i, stops.length),
      title: s.title,
      body: "<p>" + esc(s.body) + "</p>",
      side: s.id === "palette" ? "bottom" : "right",
      buttons: [
        ...(i > 0 ? [{ label: "Back", run: () => { i--; show(); } }] : []),
        i < stops.length - 1
          ? { label: "Next", primary: true, run: () => { i++; show(); } }
          : { label: "Done", primary: true, run: () => hidePointer() },
      ],
      onClose: () => {},
    });
  };
  show();
}

// ------------------------------------------------------------ Press Start
let _start = null;
function hideStart() {
  if (_start) { _start.remove(); _start = null; document.removeEventListener("keydown", startKey, true); }
}
function startKey(e) {
  if (e.key === "Escape" && _start) { e.stopPropagation(); safeStorage.set(SEEN, "1"); hideStart(); }
}
const reticle = () => "<span class='gd-tick tl' aria-hidden='true'></span><span class='gd-tick tr' aria-hidden='true'></span>" +
  "<span class='gd-tick bl' aria-hidden='true'></span><span class='gd-tick br' aria-hidden='true'></span>";

export function showStart() {
  hideStart();
  const ov = document.createElement("div");
  ov.className = "gd-scrim";
  ov.innerHTML =
    "<div class='gd-card gd-start' role='dialog' aria-modal='true' aria-labelledby='gd-start-t' aria-describedby='gd-start-d'>" +
    reticle() +
    "<div class='gd-eyebrow'>FIRST LAUNCH</div>" +
    "<h2 class='gd-title' id='gd-start-t'>Welcome to LanEx</h2>" +
    "<p class='gd-lede' id='gd-start-d'>Turn a few lines of Verilog into a chip layout. How would you like to start?</p>" +
    "<div class='gd-choices'>" +
    "<button type='button' class='gd-choice is-primary' data-g='first-chip'><b>Make my first chip</b>" +
    "<span>Build the Blinky example with a guide: simulate it, run the flow, see the layout. About 2 minutes of clicks, plus the run.</span></button>" +
    "<button type='button' class='gd-choice' data-g='tour'><b>Show me around</b><span>Five stops: where everything is.</span></button>" +
    "<button type='button' class='gd-choice' data-g='skip'><b>I know LibreLane</b><span>Go straight to the app.</span></button>" +
    "</div>" +
    "<p class='gd-foot'>You can start either one later from Help or Ctrl+K.</p>" +
    "</div>";
  document.body.appendChild(ov);
  _start = ov;
  document.addEventListener("keydown", startKey, true);
  ov.querySelector("[data-g='first-chip']").addEventListener("click", startFirstChip);
  ov.querySelector("[data-g='tour']").addEventListener("click", startTour);
  ov.querySelector("[data-g='skip']").addEventListener("click", () => { safeStorage.set(SEEN, "1"); hideStart(); });
  // Keep Tab inside the card.
  ov.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const f = [...ov.querySelectorAll("button")];
    const i = f.indexOf(document.activeElement);
    if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
  });
  ov.querySelector("[data-g='first-chip']").focus();
}

// Closed mid-guide: ask once, on the next launch, whether to carry on.
function offerResume() {
  const b = BEATS[G.beat];
  const t = toast.show(b ? "Your first chip is at step " + (G.beat + 1) + " of " + BEATS.length + ": " + b.label.toLowerCase() + "."
    : "Your first chip is built. Carry on to see its summary.", "info", 0, [
    { label: "Carry on", run: () => showBeat() },
    { label: "End guide", run: () => endGuide({ quiet: true }) },
  ]);
  return t;
}

// ------------------------------------------------------------ setup
export async function setupGuide() {
  document.addEventListener("g:guide", (e) => {
    const a = e.detail && e.detail.action;
    if (a === "tour") startTour();
    else if (a === "first-chip") startFirstChip();
    else if (a === "reset") { endGuide({ quiet: true }); safeStorage.remove(SEEN); toast.show("The first-launch card shows again on the next start.", "info", 4000); }
  });
  for (const b of BEATS) if (b.on) document.addEventListener(b.on, onProgress);
  document.addEventListener("g:sim_done", onSimDone);
  // Setup's strip ticks "Run the flow" once the run is listed (flow_done
  // repaints it before the listing is re-read).
  document.addEventListener("g:flow_done", () => {
    if (!state.designDir) return;
    api.runs(state.designDir).then((r) => {
      state.runs = r || [];
      return import("./setup.js").then((m) => m.paintOnboardChecklist());
    }).catch(() => {});
  });
  save();
  paintPill();
  if (G.active) { offerResume(); return; }
  if (safeStorage.get(SEEN, "")) return;
  // A first launch: no project open and none known.
  let known = [];
  try { known = ((await api.knownDesigns()) || {}).designs || []; } catch (_e) { known = []; }
  if (state.designDir || known.length) { safeStorage.set(SEEN, "1"); return; }
  showStart();
}
