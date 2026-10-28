// palettemodel.js — the command palette's search, kept pure (no DOM) so it is
// tested: prefix parsing, fuzzy scoring and ranking with recents first.
//
//   >  actions (the default)      #  LibreLane settings     @  runs
//   /  project files              ?  help and glossary

export const PREFIXES = {
  ">": { group: "action", label: "Actions" },
  "#": { group: "setting", label: "Settings" },
  "@": { group: "run", label: "Runs" },
  "/": { group: "file", label: "Files" },
  "?": { group: "help", label: "Help" },
};

// "#clock" -> { group: "setting", q: "clock" }; "drc" -> { group: null, q: "drc" }.
// No prefix searches every group (actions are only the default ranking tie-break).
export function parseQuery(raw) {
  const s = String(raw || "").replace(/^\s+/, "");
  const p = PREFIXES[s[0]];
  if (p) return { group: p.group, q: s.slice(1).trim(), prefix: s[0] };
  return { group: null, q: s.trim(), prefix: "" };
}

// Fuzzy score of query *q* in *text*: higher is better, -1 = no match.
// Exact > prefix > word start > substring > subsequence (with a gap penalty).
export function fuzzyScore(q, text) {
  q = String(q || "").toLowerCase();
  const t = String(text || "").toLowerCase();
  if (!q) return 0;
  if (t === q) return 1000;
  if (t.startsWith(q)) return 800 - Math.min(t.length - q.length, 100);
  const i = t.indexOf(q);
  if (i >= 0) {
    const wordStart = i === 0 || /[\s_\-./:·>]/.test(t[i - 1]);
    return (wordStart ? 600 : 400) - Math.min(i, 100);
  }
  // Subsequence: every query letter in order; tighter matches score higher.
  let qi = 0, first = -1, last = -1;
  for (let k = 0; k < t.length && qi < q.length; k++) {
    if (t[k] === q[qi]) { if (first < 0) first = k; last = k; qi++; }
  }
  if (qi < q.length) return -1;
  const spread = last - first + 1 - q.length;
  return Math.max(1, 200 - spread * 4 - first);
}

const GROUP_ORDER = { action: 0, setting: 1, run: 2, file: 3, help: 4 };

// Score of query *q* against an item's title and, below it, its keys.
function itemScore(q, it) {
  let s = fuzzyScore(q, it.title);
  // A match in the location or description counts, below the same match in the title.
  for (const k of it.keys || []) {
    const ks = fuzzyScore(q, k);
    // (substring matches only: a long description holds almost any subsequence)
    if (ks >= 400) s = Math.max(s, ks - 350);
  }
  return s;
}

function wordsScore(words, it) {
  let min = Infinity;
  for (const w of words) {
    let ws = fuzzyScore(w, it.title);
    if (ws < 400) ws = -1;               // a loose subsequence of one word isn't a match
    for (const k of it.keys || []) { const ks = fuzzyScore(w, k); if (ks >= 400) ws = Math.max(ws, ks - 350); }
    if (ws < 0) return -1;
    min = Math.min(min, ws);
  }
  return Number.isFinite(min) ? Math.max(1, min - 100) : -1;
}

// A run's start time in the person's own time, the way Runs shows it:
// "today 05:22 pm", "yesterday 09:10 am", "3 days ago", "17 Sept".
export function whenLocal(iso, now = new Date()) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.floor((new Date(now.toDateString()) - new Date(d.toDateString())) / 864e5);
  if (days === 0) return "today " + hm;
  if (days === 1) return "yesterday " + hm;
  if (days < 7) return days + " days ago";
  return d.toLocaleDateString([], { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
}

// Rank *items* ({ id, group, title, keys?: [strings searched besides the title] })
// for the raw query. Recents (ids in *recentIds*, newest first) come first while
// nothing is typed, and win ties when something is. *limit* caps the list.
export function rank(items, raw, { recentIds = [], limit = 60 } = {}) {
  const { group, q } = parseQuery(raw);
  const rec = new Map(recentIds.map((id, i) => [id, i]));
  const pool = group ? items.filter((it) => it.group === group) : items;
  const scored = [];
  let n = 0;
  for (const it of pool) {
    const idx = n++;
    let s;
    if (!q) {
      // Empty query: no prefix shows recents then actions; a prefix shows its group.
      if (!group && it.group !== "action" && !rec.has(it.id)) continue;
      s = 0;
    } else {
      s = itemScore(q, it);
      // Several words match in any order ("first chip" finds "First-chip guide"):
      // each word must be a real substring somewhere, scored by its weakest word.
      if (s < 0 && /\s/.test(q)) s = wordsScore(q.split(/\s+/).filter(Boolean), it);
      if (s < 0) continue;
    }
    const r = rec.has(it.id) ? rec.get(it.id) : null;
    scored.push({ it, s: s + (r != null ? 120 - r * 10 : 0), g: GROUP_ORDER[it.group] ?? 9, r, idx });
  }
  // Ties keep the registry's order (the order the list was written in).
  scored.sort((a, b) => (b.s - a.s) || (a.g - b.g) || ((a.r ?? 99) - (b.r ?? 99)) || (a.idx - b.idx));
  return scored.slice(0, limit).map((x) => x.it);
}

// A setting row's description, cut to one line.
export function oneLine(s, max = 110) {
  const t = String(s || "").replace(/\s+/g, " ").trim();
  const dot = t.search(/\.\s/);
  const first = dot > 20 ? t.slice(0, dot + 1) : t;
  return first.length > max ? first.slice(0, max - 1) + "…" : first;
}

// Remembered picks, newest first, unique, capped.
export function pushRecent(list, id, max = 12) {
  const out = [id].concat((list || []).filter((x) => x !== id));
  return out.slice(0, max);
}
