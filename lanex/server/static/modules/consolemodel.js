// consolemodel.js — the Console drawer's pure parts (no DOM), tested:
// shell quoting, the next-run script, the Journal as a script, and the
// command history of the "Run a command" tab.

// POSIX single-quote a word when it needs it (same rule as Python's shlex.quote).
export function shq(s) {
  s = String(s ?? "");
  if (s === "") return "''";
  if (/^[A-Za-z0-9_@%+=:,./-]+$/.test(s)) return s;
  return "'" + s.replace(/'/g, "'\"'\"'") + "'";
}

// The command a cli-command answer says to run, for its recommended engine.
export function pickCommand(c) {
  if (!c) return "";
  return c[c.recommended || "container"] || c.container || c.local || "";
}

// A bash script that runs *cmd* from *cwd*, with the image pinned the way
// LanEx's runner pins it (LIBRELANE_IMAGE_OVERRIDE) when it is a container run.
export function commandScript({ command, cwd, image, title } = {}) {
  const out = ["#!/usr/bin/env bash"];
  if (title) out.push("# " + oneLine(title));
  out.push("set -euo pipefail");
  if (cwd) out.push("cd " + shq(cwd));
  if (image && /--dockerized\b/.test(command || "")) out.push("export LIBRELANE_IMAGE_OVERRIDE=" + shq(image));
  out.push(command || "# (no command)");
  return out.join("\n") + "\n";
}

// A run's command with "--run-tag T" made "--run-tag T-repro". LibreLane adds
// to a run folder whose tag exists, so a replay under the same tag would write
// into the run it replays (manualcmd.retag on the server does the same).
export function retag(cmd) {
  if (!cmd) return cmd;
  return String(cmd).replace(/((?:^|\s)--run-tag[ =])(['"]?)([^\s'"]+)\2/, (_m, a, q, t) => a + q + t + "-repro" + q);
}

// The Journal as one script: each entry with a command becomes its line (after
// a cd when the folder changes); config edits and the rest become comments, so
// the script says everything that happened but runs only real commands. Runs
// replay under new tags (retag), leaving the session's own runs as they are.
export function journalScript(entries, { title = "What LanEx ran this session" } = {}) {
  const out = ["#!/usr/bin/env bash", "# " + oneLine(title), "set -euo pipefail"];
  let cwd = null, image = null;
  for (const e of entries || []) {
    out.push("");
    out.push("# " + oneLine((e.time ? e.time + " " : "") + (e.title || e.kind || "action")));
    for (const n of e.notes || []) out.push("#   " + oneLine(n));
    if (e.command) {
      if (e.cwd && e.cwd !== cwd) { out.push("cd " + shq(e.cwd)); cwd = e.cwd; }
      if (e.image && e.image !== image && /--dockerized\b/.test(e.command)) {
        out.push("export LIBRELANE_IMAGE_OVERRIDE=" + shq(e.image)); image = e.image;
      }
      out.push(retag(oneLine(e.command)));
    }
  }
  return out.join("\n") + "\n";
}

// A line break inside a note (a config value, an error, a run name) would end
// the "# ..." comment and turn the rest into a command: keep each on one line.
// Built from char codes: a literal U+2028 inside a regex literal is a line break to the parser.
const BREAKS = new RegExp("[\\r\\n" + String.fromCharCode(0x85, 0x2028, 0x2029) + "]+", "g");
const CTRL = new RegExp("[" + String.fromCharCode(0) + "-" + String.fromCharCode(8, 11) + "-" + String.fromCharCode(31, 127) + "]", "g");
export function oneLine(s) {
  return String(s ?? "").replace(BREAKS, " ").replace(CTRL, "?");
}

// A config edit through the app as a one-line diff: "FP_CORE_UTIL 50 -> 60".
export function configDiffLines(sent, data) {
  const lines = [];
  const before = (data && (data.before || data.old)) || {};
  for (const [k, v] of Object.entries((sent && sent.set) || {})) {
    const was = before[k];
    lines.push(k + (was !== undefined ? " " + fmtVal(was) + " -> " : " = ") + fmtVal(v));
  }
  for (const k of (sent && sent.remove) || []) lines.push(k + " removed (back to its default)");
  return lines;
}

function fmtVal(v) {
  if (v === null || v === undefined) return "(unset)";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// Shell-style history: up goes back, down comes forward, and the line being
// typed is kept when you step away from it and come back.
export class History {
  constructor(items = [], max = 50) { this.items = items.slice(-max); this.max = max; this.i = this.items.length; this.draft = ""; }
  push(cmd) {
    cmd = String(cmd || "").trim();
    if (!cmd) return;
    if (this.items[this.items.length - 1] !== cmd) this.items.push(cmd);
    if (this.items.length > this.max) this.items = this.items.slice(-this.max);
    this.i = this.items.length; this.draft = "";
  }
  up(current) {
    if (!this.items.length) return current;
    if (this.i === this.items.length) this.draft = current;
    this.i = Math.max(0, this.i - 1);
    return this.items[this.i];
  }
  down(current) {
    if (this.i >= this.items.length) return current;
    this.i += 1;
    return this.i === this.items.length ? this.draft : this.items[this.i];
  }
}

// A command that makes a run: "librelane … --run-tag X" names it; a plain
// librelane flow invocation makes one with a generated tag.
export function runTagOf(cmd) {
  const m = /(?:^|\s)--run-tag[ =]([^\s]+)/.exec(cmd || "");
  if (m) return m[1].replace(/^['"]|['"]$/g, "");
  return null;
}
export function makesRun(cmd) {
  const c = String(cmd || "").trim();
  return /^librelane\b/.test(c) && !/(^|\s)(--version|--help|-h|--smoke-test|--list-steps)\b/.test(c);
}
