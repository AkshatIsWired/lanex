// logs.js — live log streaming panel with search, level filter, autoscroll.
import { icon } from "./icons.js";

const MAX_LINES = 6000;
let lines = [];
let buf = [];
let flushTimer = null;

let filterText = "";
let filterLevel = "all"; // all | warn | error
let autoscroll = true;
let started = false; // becomes true on first real log line

// Per-step anchors: a synthetic divider line is inserted into the stream when a
// step starts, so clicking a step in the pipeline can scroll the Live Logs to
// exactly where that tool was instantiated (issue #8b). `_reviewStep` makes the
// next render show the WHOLE log (not just the tail) so the anchor is present.
let _reviewStep = null;
function stepDomId(stepId) {
  return "logstep-" + String(stepId).replace(/[^a-zA-Z0-9_.-]/g, "_");
}

function schedule() {
  if (flushTimer) return;
  flushTimer = setTimeout(() => {
    flushTimer = null;
    flush();
  }, 150);
}

function matchesLevel(level) {
  // Step dividers are navigation anchors — always keep them visible regardless
  // of the level filter so jump-to-step works under Warnings+/Errors.
  if (level === "STEP") return true;
  if (filterLevel === "all") return true;
  const l = String(level || "").toLowerCase();
  if (filterLevel === "error") return l.includes("error") || l.includes("critical");
  if (filterLevel === "warn") return l.includes("warn") || l.includes("error") || l.includes("critical");
  return true;
}

function matchesText(msg) {
  if (!filterText) return true;
  return String(msg).toLowerCase().includes(filterText);
}

function visibleLines() {
  return lines.filter((l) => matchesLevel(l.level) && matchesText(l.msg));
}

function flush() {
  if (buf.length) {
    lines.push(...buf);
    buf.length = 0;
    if (lines.length > MAX_LINES) lines = lines.slice(-Math.floor(MAX_LINES / 2));
  }
  render();
}

function render() {
  const r = document.getElementById("logs");
  if (!r) return;
  const vis = visibleLines();
  // In review mode (after a jump-to-step) show the whole log so the target
  // anchor exists; otherwise cap to the tail for performance on a live stream.
  const slice = _reviewStep ? vis : vis.slice(-800);
  if (!slice.length) {
    r.innerHTML = started
      ? "<div class='empty'><span class='ico'>" + icon('search',{size:40}) + "</span><h3>No matching lines</h3><p>Adjust the search or level filter.</p></div>"
      : "<div class='empty'><span class='ico'>" + icon('wave',{size:40}) + "</span><h3>Logs</h3><p>Live tool output streams here once you press Run.</p></div>";
  } else {
    r.innerHTML = slice
      .map((l) => {
        if (l.level === "STEP") {
          return "<div id='" + stepDomId(l.step) + "' class='logline-STEP'>" + escape(l.msg) + "</div>";
        }
        return "<div class='logline-" + escAttr(l.level || "INFO") + "'>" + escape(l.msg) + "</div>";
      })
      .join("");
    if (_reviewStep) {
      const target = document.getElementById(stepDomId(_reviewStep));
      if (target) {
        target.scrollIntoView({ block: "start", behavior: "smooth" });
        target.classList.add("logline-STEP-hit");
        setTimeout(() => target.classList.remove("logline-STEP-hit"), 2200);
      }
      _reviewStep = null;
    } else if (autoscroll) {
      r.scrollTop = r.scrollHeight;
    }
  }
  const count = document.getElementById("log-count");
  if (count) count.textContent = vis.length + (vis.length === lines.length ? "" : " / " + lines.length);
}

function escAttr(s) {
  return String(s).replace(/[^a-zA-Z0-9_-]/g, "");
}

function escape(s) {
  const map = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  return String(s).replace(/[&<>"']/g, (c) => map[c] || c);
}

export const renderLogs = {
  append(event) {
    const level =
      event.payload?.level ||
      event.level ||
      (event.type === "installer_line" ? "installer_line" : "INFO");
    const msg = event.payload?.message || event.message || JSON.stringify(event.payload || event);
    if (!started) started = true;
    buf.push({ level, msg });
    schedule();
  },
  clear() {
    lines = [];
    buf.length = 0;
    render();
  },
  setInstaller(line) {
    if (!started) started = true;
    buf.push({ level: "installer_line", msg: line });
    schedule();
  },
  setStepsInfo() {
    render();
  },
  // Drop a navigable divider into the stream when a step starts, so the log can
  // be jumped to that step's instantiation point later (issue #8b).
  markStep(stepId, label) {
    if (!stepId) return;
    if (!started) started = true;
    const name = label && label !== stepId ? stepId + " — " + label : stepId;
    buf.push({ level: "STEP", step: stepId, msg: "──────── ▶ " + name + " ────────" });
    schedule();
  },
  // Scroll the Live Logs to a step's divider; gives the user the full log to
  // explore (autoscroll is turned off so they don't get yanked to the bottom).
  jumpToStep(stepId) {
    if (!stepId) return false;
    _reviewStep = stepId;
    autoscroll = false;
    const auto = document.getElementById("log-autoscroll");
    if (auto) auto.checked = false;
    flush();        // forces a full-log render + scroll to the anchor
    return true;
  },
};

// Wire the log toolbar controls. Call once at boot.
export function setupLogs() {
  const search = document.getElementById("log-search");
  const level = document.getElementById("log-level");
  const auto = document.getElementById("log-autoscroll");
  const clear = document.getElementById("log-clear");
  const copy = document.getElementById("log-copy");

  search?.addEventListener("input", () => {
    filterText = search.value.trim().toLowerCase();
    render();
  });
  level?.addEventListener("change", () => {
    filterLevel = level.value;
    render();
  });
  auto?.addEventListener("change", () => {
    autoscroll = auto.checked;
    if (autoscroll) render();
  });
  clear?.addEventListener("click", () => renderLogs.clear());
  copy?.addEventListener("click", async () => {
    const text = visibleLines().map((l) => l.msg).join("\n");
    try {
      await navigator.clipboard.writeText(text);
      copy.textContent = "copied";
      setTimeout(() => (copy.textContent = "copy"), 1200);
    } catch (_e) {
      copy.textContent = "copy failed";
      setTimeout(() => (copy.textContent = "copy"), 1200);
    }
  });
  render();
}
