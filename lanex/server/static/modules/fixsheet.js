// fixsheet.js — the fix sheet: change one setting and resume the run from it.
//
// One sheet for every fix (Flow's failure card, the report card, Verify). It
// says, before anything changes:
//   the setting   what it does, its value in the run and where that value came
//                 from (the config file and which section, "this run only",
//                 the PDK, LibreLane's default), and the new value
//   save to       the project's config file (a terminal run sees it too; the
//                 lines that change are shown) or this run only (-c)
//   then          resume from the first step that reads it, as a new run that
//                 reuses the old run's earlier steps (LibreLane's -i and
//                 --from), or the whole flow, or only save
//   and the command it will run.
// Vivado's QoR suggestions work the same way: each names the stage it applies
// at, and a run of that stage picks it up. The server (controller/branch.py)
// plans it; nothing is written until Apply.

import { api, fmt } from "./api.js";
import { state, safeStorage } from "./state.js";
import { icon } from "./icons.js";
import { toast } from "./toast.js";
import * as FS from "./flowstages.js";
import { forgetProblems } from "./problems.js";

const esc = (s) => fmt.escape(s == null ? "" : String(s));
const $ = (id) => document.getElementById(id);
const S = { el: null, tok: 0, timer: 0, plan: null, err: "", busy: false };

// ------------------------------------------------------------------ open

export function openFixSheet({ tag, variable, to = "", title = "", why = "" }) {
  build();
  toast.clear();
  Object.assign(S, { tag, variable, value: String(to ?? ""), title, why, save: "auto", then: "resume",
    plan: null, err: "", busy: false, showCmd: false });
  S.el.hidden = false;
  paint();
  replan(0);
  requestAnimationFrame(() => S.el.querySelector("[data-fx-value]")?.focus());
}

export function closeFixSheet() {
  if (!S.el) return;
  S.el.hidden = true;
  S.tok++;
}

// Every Apply… button (problems.js fixRowHtml) opens the sheet.
document.addEventListener("click", (e) => {
  const b = e.target.closest && e.target.closest("[data-fix-var]");
  if (!b) return;
  openFixSheet({ tag: b.dataset.fixTag, variable: b.dataset.fixVar, to: b.dataset.fixTo,
    title: b.dataset.fixTitle, why: b.dataset.fixWhy });
});

function build() {
  if (S.el) return;
  const el = document.createElement("aside");
  el.className = "sheet fx-sheet";
  el.id = "fix-sheet";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-labelledby", "fx-title");
  el.hidden = true;
  el.innerHTML = "<div class='sheet-head fx-head'><div class='fx-head-t'><span class='an-eyebrow' id='fx-eyebrow'></span>" +
    "<h2 id='fx-title'></h2></div><button class='iconbtn' data-fx='close' aria-label='Close'>" + icon("x", { size: 16 }) + "</button></div>" +
    "<div class='sheet-body fx-body' id='fx-body'></div>" +
    "<div class='fx-foot'><span class='fx-msg' id='fx-msg' role='status'></span>" +
    "<button class='btn btn-ghost' data-fx='close'>Cancel</button>" +
    "<button class='btn btn-primary' data-fx='apply' id='fx-apply'></button></div>";
  document.body.appendChild(el);
  S.el = el;
  el.addEventListener("click", (e) => {
    const a = e.target.closest("[data-fx]");
    if (!a) return;
    const act = a.dataset.fx;
    if (act === "close") closeFixSheet();
    else if (act === "apply") apply();
    else if (act === "copy") copyCmd();
    else if (act === "bool") { S.value = a.dataset.v; paint(); replan(0); }
  });
  el.addEventListener("change", (e) => {
    const t = e.target;
    if (t.name === "fx-save") { S.save = t.value; if (S.save === "run" && S.then === "save") S.then = "resume"; paint(); replan(0); }
    else if (t.name === "fx-then") { S.then = t.value; paint(); replan(0); }
    else if (t.matches("[data-fx-value]")) { S.value = t.value; replan(0); }
  });
  el.addEventListener("input", (e) => {
    if (e.target.matches("[data-fx-value]")) { S.value = e.target.value; replan(350); }
  });
  el.addEventListener("toggle", (e) => { if (e.target.matches(".fx-cmd")) S.showCmd = e.target.open; }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && S.el && !S.el.hidden && !document.querySelector(".dlg-backdrop:not([hidden])")) closeFixSheet();
  });
}

// ------------------------------------------------------------------ plan

function body() {
  return { tag: S.tag, sets: { [S.variable]: S.value }, save: S.save,
    start: S.then === "full" ? "full" : "auto", run_mode: state.runMode };
}

function replan(ms) {
  clearTimeout(S.timer);
  const tok = ++S.tok;
  S.busy = true;
  paintFoot();
  S.timer = setTimeout(async () => {
    let p = null, err = "";
    try { p = await api.fixPlan(body()); } catch (ex) { err = ex.message || String(ex); }
    if (tok !== S.tok) return;
    S.busy = false;
    S.err = err;
    if (p) {
      S.plan = p;
      // The first answer settles where it is saved (the value's own layer).
      const c = p.changes && p.changes[0];
      if (S.save === "auto" && c) S.save = c.save;
    }
    paint();
  }, ms);
}

// ------------------------------------------------------------------ paint

function paint() {
  if (!S.el || S.el.hidden) return;
  const p = S.plan;
  const c = (p && p.changes && p.changes[0]) || null;
  $("fx-eyebrow").textContent = "Fix · " + S.tag;
  $("fx-title").textContent = S.title || "Change " + S.variable;
  const keep = S.el.querySelector("[data-fx-value]");
  const hadFocus = keep && document.activeElement === keep;
  const caret = hadFocus && keep.selectionStart != null ? keep.selectionStart : null;
  $("fx-body").innerHTML = settingHtml(c) + saveHtml(p, c) + thenHtml(p, c) + notesHtml(p, c) + cmdHtml(p);
  if (hadFocus) {
    const f = S.el.querySelector("[data-fx-value]");
    f?.focus();
    if (caret != null && f && f.setSelectionRange && f.type === "text") f.setSelectionRange(caret, caret);
  }
  paintFoot();
}

function info(c) {
  return (c && c.info) || (state.variables || []).find((v) => v.name === S.variable) || {};
}

function settingHtml(c) {
  const vi = info(c);
  const desc = String(vi.description || "").replace(/\s+/g, " ").trim();
  const short = desc.length > 260 ? desc.slice(0, 250).replace(/\s\S*$/, "") + "…" : desc;
  const o = c && c.origin;
  const units = vi.units ? "<span class='fx-unit'>" + esc(vi.units) + "</span>" : "";
  const from = c ? c.from : "";
  return "<section class='fx-sec fx-setting'>" +
    "<div class='fx-var'><code>" + esc(S.variable) + "</code>" + units +
      "<button class='fx-link' data-go='setup' data-go-setting='" + esc(S.variable) + "'>In Settings " + icon("chevron", { size: 11 }) + "</button></div>" +
    (short ? "<p class='fx-desc' title='" + esc(desc) + "'>" + esc(short) + "</p>" : "") +
    "<div class='fx-vals'>" +
      "<div class='fx-val'><span class='fx-k'>In " + esc(S.tag) + "</span><span class='fx-now'>" + esc(from === "" ? "not set" : from) + "</span>" +
        (o ? "<span class='fx-src'>from " + esc(o.label) + "</span>" : "") + "</div>" +
      "<div class='fx-val'><span class='fx-k'>New value</span>" + editorHtml(vi) + "</div>" +
    "</div>" +
    (S.why ? "<p class='fx-why'>" + esc(S.why) + "</p>" : "") +
    (S.err ? "<p class='fx-err' role='alert'>" + icon("alert", { size: 13 }) + " " + esc(S.err) + "</p>" : "") +
    "</section>";
}

function editorHtml(vi) {
  const kind = vi.kind || "text";
  if (kind === "bool") {
    const on = /^(true|1|yes|on)$/i.test(S.value);
    return "<span class='seg fx-bool' role='group'>" +
      ["true", "false"].map((v) => "<button class='seg-btn" + ((v === "true") === on ? " is-active" : "") + "' data-fx='bool' data-v='" + v +
        "' aria-pressed='" + ((v === "true") === on) + "'>" + (v === "true" ? "On" : "Off") + "</button>").join("") + "</span>";
  }
  if (kind === "choice" && (vi.choices || []).length) {
    return "<select data-fx-value aria-label='New value'>" + vi.choices.map((ch) =>
      "<option" + (String(ch) === S.value ? " selected" : "") + ">" + esc(ch) + "</option>").join("") + "</select>";
  }
  const num = kind === "number" || kind === "int";
  return "<span class='fx-input'><input data-fx-value type='text' inputmode='" + (num ? "decimal" : "text") + "' spellcheck='false' value='" + esc(S.value) +
    "' aria-label='New value'" + (kind === "numbers" ? " placeholder='x0 y0 x1 y1'" : "") + "/>" +
    (vi.units ? "<span class='fx-unit'>" + esc(vi.units) + "</span>" : "") + "</span>";
}

function saveHtml(p, c) {
  const cfg = (p && p.config) || {};
  const name = cfg.name || "the config file";
  const save = S.save === "auto" ? (c ? c.save : "config") : S.save;
  const scope = c && c.scope && c.scope.length ? c.scope.join(" / ") : "";
  const o = c && c.origin;
  const subCfg = !cfg.editable ? (cfg.reason || "LanEx can't edit this config.")
    : scope ? "In its " + scope + " section, where " + (p.parent.pdk || "this PDK") + " reads it (a value at the top would be overridden)."
    : "The project's own setting: a run from a terminal sees it too.";
  const subRun = o && o.layer === "run"
    ? "As " + S.tag + " had it: " + name + " stays as it is. LibreLane's -c " + S.variable + "=…"
    : name + " stays as it is. LibreLane's -c " + S.variable + "=…";
  const diff = save === "config" ? diffHtml(cfg) : "";
  return "<section class='fx-sec'><h3 class='fx-h'>Save it in</h3><div class='fx-opts'>" +
    radio("fx-save", "config", save === "config", name, subCfg, !cfg.editable && !!p) + diff +
    radio("fx-save", "run", save === "run", "This run only", subRun) +
    "</div></section>";
}

function diffHtml(cfg) {
  const lines = (cfg.diff || []).filter((d) => d.text.trim());
  if (!lines.length) return "";
  return "<div class='fx-diff' aria-label='The lines of " + esc(cfg.name) + " that change'>" +
    "<div class='fx-diff-h'>" + icon("file", { size: 12 }) + " " + esc(cfg.name) + "</div>" +
    lines.map((d) => "<div class='fx-dl is-" + (d.op === "+" ? "add" : "del") + "'><span class='fx-ln'>" + d.line + "</span><span class='fx-op'>" + d.op +
      "</span><code>" + esc(d.text) + "</code></div>").join("") + "</div>";
}

function radio(name, value, on, title, sub, disabled = false) {
  return "<label class='fx-opt" + (on ? " is-on" : "") + (disabled ? " is-off" : "") + "'><input type='radio' name='" + name + "' value='" + value + "'" +
    (on ? " checked" : "") + (disabled ? " disabled" : "") + "/><span class='fx-opt-t'><b>" + esc(title) + "</b>" +
    (sub ? "<small>" + esc(sub) + "</small>" : "") + "</span></label>";
}

function stepsWord(n) { return n + " step" + (n === 1 ? "" : "s"); }

function thenHtml(p, c) {
  const r = p && p.resume;
  const total = (p && p.steps_total) || 0;
  const saveCfg = (S.save === "auto" ? (c ? c.save : "config") : S.save) === "config";
  if (!r && S.then === "resume" && p) S.then = "full";
  let resumeSub = "";
  if (r) {
    const st = FS.stageLabel(r.stage);
    const kept = r.index;
    resumeSub = "A new run that reuses steps 1–" + kept + " of " + p.parent.tag + " and runs " + (r.n) + "–" + total + " again. " +
      (r.by ? r.by + " is first read " + (r.stage_start ? "at " + st : "by step " + r.n + " (" + st + ")") + "." : "");
  }
  const resumeTitle = r ? "Resume from " + FS.stageLabel(r.stage) + (r.stage_start ? "" : ", step " + r.n) : "Resume";
  const noResume = p && !r ? "Nothing of " + S.tag + " can be reused: " + (S.variable + " is read from the first step") + "." : "";
  return "<section class='fx-sec'><h3 class='fx-h'>Then</h3><div class='fx-opts'>" +
    (r || !p ? radio("fx-then", "resume", S.then === "resume", resumeTitle, resumeSub || "Checking which steps read it…") +
      (r && S.then === "resume" ? rulerHtml(p) : "") : "") +
    radio("fx-then", "full", S.then === "full", "Run the whole flow", "All " + (total ? total + " steps" : "the steps") + ", as a new run." + (noResume ? " " + noResume : "")) +
    (saveCfg ? radio("fx-then", "save", S.then === "save", "Only save it", "Run it later, from LanEx or a terminal.") : "") +
    "</div></section>";
}

// The seven stages as one bar: what the new run reuses from the old one, and
// what it runs again (widths by step count).
function rulerHtml(p) {
  const r = p.resume;
  const starts = p.stages || [];
  const total = p.steps_total || 1;
  const segs = starts.map((s, i) => {
    const end = i + 1 < starts.length ? starts[i + 1].index : total;
    const n = end - s.index;
    const reused = Math.max(0, Math.min(n, r.index - s.index));
    const cls = reused >= n ? "is-reused" : reused > 0 ? "is-split" : "is-rerun";
    const pct = Math.round((reused / n) * 100);
    const tip = FS.stageLabel(s.stage) + ": " + (reused >= n ? "reused from " + p.parent.tag : reused > 0 ? reused + " of " + n + " steps reused, the rest run again" : "runs again");
    return "<span class='fx-seg " + cls + "' style='flex-grow:" + n + ";--cut:" + pct + "%' title='" + esc(tip) + "'><i>" + String(i + 1).padStart(2, "0") + "</i></span>";
  }).join("");
  return "<div class='fx-ruler'><div class='fx-segs' role='img' aria-label='" + esc("Reuses steps 1 to " + r.index + ", runs " + r.n + " to " + total + " again") + "'>" + segs + "</div>" +
    "<div class='fx-ruler-k'><span><i class='fx-key is-reused'></i>reused from " + esc(p.parent.tag) + "</span><span><i class='fx-key is-rerun'></i>runs again</span></div></div>";
}

function notesHtml(p, c) {
  if (!p) return "";
  const out = [];
  const d = p.drift || {};
  const r = p.resume;
  for (const s of d.settings || []) out.push(["warn", s.var + " is " + s.now + " in " + (p.config.name || "the config") + " now, " + s.was + " in " + p.parent.tag + ". The new run uses " + s.now + " and starts early enough to cover it."]);
  for (const f of d.files || []) out.push(["warn", f.path + " changed after " + p.parent.tag + " ran (" + f.vars.join(", ") + "). The new run starts early enough to read it again."]);
  if ((d.unplaced || []).length) out.push(["warn", d.unplaced.join(", ") + (d.unplaced.length === 1 ? " is" : " are") + " read across the flow, so it runs from the start."]);
  if (p.config && p.config.edited_since && !(d.settings || []).length) out.push(["info", (p.config.name || "The config") + " was edited after " + p.parent.tag + " ran; every setting LanEx can compare is the same."]);
  if (r && (r.reasons || []).includes("stopped")) out.push(["info", p.parent.tag + " stopped at " + p.parent.stopped_step + ", so the new run can't start later than that."]);
  if ((p.unchanged || []).length) out.push(["warn", S.variable + " is already " + (c ? c.from : S.value) + " in " + p.parent.tag + "."]);
  if (p.blocked) out.push(["fail", p.blocked]);
  if (p.config_error && (S.save === "config")) out.push(["fail", p.config_error]);
  const kids = Object.keys(p.overrides || {}).filter((k) => k !== S.variable);
  if (kids.length) out.push(["info", "Kept from " + p.parent.tag + ", which set them for itself: " + kids.map((k) => k + " = " + p.overrides[k]).join(", ") + "."]);
  if (!out.length) return "";
  return "<section class='fx-sec fx-notes'>" + out.map(([tone, t]) => "<p class='fx-note is-" + tone + "'>" + icon(tone === "info" ? "dot" : "alert", { size: 13 }) + "<span>" + esc(t) + "</span></p>").join("") + "</section>";
}

function cmdHtml(p) {
  const cmd = p && p.command;
  const text = cmd ? cmd[cmd.recommended] || cmd.container || cmd.local : "";
  if (!text || S.then === "save") return "";
  return "<details class='fx-cmd'" + (S.showCmd ? " open" : "") + "><summary>" + icon("command", { size: 12 }) + " The command it runs</summary>" +
    "<div class='fx-cmd-box'><code>" + esc(text) + "</code><button class='btn btn-ghost btn-xs' data-fx='copy'>Copy</button></div>" +
    "<p class='fx-cmd-note'>From " + esc(cmd.cwd || "the project folder") + ". -i starts from " + esc(p.parent.tag) + "'s saved state; --from skips the steps before it.</p></details>";
}

function paintFoot() {
  if (!S.el) return;
  const p = S.plan;
  const b = $("fx-apply");
  const r = p && p.resume;
  const label = S.then === "save" ? "Save to " + ((p && p.config && p.config.name) || "the config")
    : S.then === "full" ? "Apply and run the whole flow"
    : r ? "Apply and resume from " + FS.stageLabel(r.stage) : "Apply";
  b.innerHTML = (S.then === "save" ? icon("check", { size: 14 }) : icon("play", { size: 13 })) + " " + esc(label);
  const running = state.status && state.status.running;
  b.disabled = S.busy || !p || !!S.err || !p.ok && !(S.save === "run" && !p.blocked) || (running && S.then !== "save");
  const msg = running && S.then !== "save" ? "A run is going: apply when it ends." : S.busy ? "Checking…" : "";
  $("fx-msg").textContent = msg;
}

// ------------------------------------------------------------------ apply

async function apply() {
  const p = S.plan;
  if (!p) return;
  const b = $("fx-apply");
  b.disabled = true;
  $("fx-msg").textContent = S.then === "save" ? "Saving…" : "Starting the run…";
  let res;
  try {
    res = await api.fixApply({ ...body(), then: S.then === "save" ? "save" : "run", mode: state.mode });
  } catch (ex) {
    $("fx-msg").textContent = "";
    S.err = ex.message || String(ex);
    paint();
    return;
  }
  forgetProblems(S.tag);
  const c = (p.changes || [])[0] || {};
  const v = S.variable + " = " + (c.to || S.value);
  const undo = res.undo && res.undo.backup ? { label: "Undo", run: () => undoConfig(res.undo, v, res.started) } : null;
  closeFixSheet();
  // Saved in the project's config: pages that show it (Setup) read it again.
  if (res.undo) document.dispatchEvent(new CustomEvent("g:config_changed", { detail: { keys: [S.variable], from: "fixsheet" } }));
  if (!res.started) {
    if (res.error) toast.show("Saved " + v + " in " + (res.undo ? res.undo.name : "the config") + ", but the run didn't start: " + res.error, "error", 0, undo);
    else toast.show("Saved " + v + " in " + (res.undo ? res.undo.name : "the config") + ".", "success", 9000, undo);
    return;
  }
  const where = res.resume ? "from " + FS.stageLabel(res.resume.stage) : "from the start";
  const saved = res.undo ? "Saved " + v + " in " + res.undo.name + ". " : v + " for this run only. ";
  toast.show(saved + "Resuming " + S.tag + " " + where + " as " + res.tag + ".", "success", 12000, undo);
  try {
    const { paintRunning } = await import("./setup.js");
    paintRunning(true);
  } catch (_e) {}
  if (safeStorage.get("ll.showFlowOnRun") !== "0") {
    const { go } = await import("./nav.js");
    go("pipeline", {}, { link: false });
  }
}

// Undo right after Apply: the run that just started reads the config in its
// first seconds, and the server refuses until it has (else the run could read
// the old value back). Keep asking for half a minute instead of making the
// user try again.
async function undoConfig(u, v, started) {
  let waiting = false;
  for (let i = 0; i < 25; i++) {
    try {
      const r = await api.configUndo({ backup: u.backup, after: u.after });
      document.dispatchEvent(new CustomEvent("g:config_changed", { detail: { keys: [v.split(" = ")[0]], from: "fixsheet-undo" } }));
      toast.show(r.name + " is back as it was." + (r.running || started ? " The run that started keeps " + v + "." : ""), "success", 8000);
      return;
    } catch (ex) {
      const early = ex && ex.status === 409 && /hasn't read the config/.test(ex.message || "");
      if (!early) { toast.show("Undo: " + (ex.message || ex), "warn", 9000); return; }
      if (!waiting) { waiting = true; toast.show("Undoing as soon as the run has read " + u.name + "…", "info", 6000); }
      await new Promise((res) => setTimeout(res, 1200));
    }
  }
  toast.show("Undo: the run still hasn't read " + u.name + ". Change " + v.split(" = ")[0] + " back by hand.", "warn", 0);
}

async function copyCmd() {
  const cmd = S.plan && S.plan.command;
  const text = cmd ? cmd[cmd.recommended] || cmd.container : "";
  if (!text) return;
  try { await navigator.clipboard.writeText(text); toast.show("Copied the command", "success", 1800); }
  catch (_e) { toast.show(text, "info", 0); }
}
