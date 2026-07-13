// fileview.js — shared helpers for showing VLSI-flow files to the user with the
// three actions requested everywhere: Download, Locate (reveal in the file
// manager), and Find (in-content search with prev/next). Used by step output,
// verification reports, the preview text view, etc. No dependency.

import { api, fmt } from "./api.js";
import { toast } from "./toast.js";
import { icon } from "./icons.js";

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => (c === "&" ? "&amp;" : c === "<" ? "&lt;" : "&gt;"));
}

// Download + Locate buttons for a run-relative file path. `tag` = run tag.
export function fileActionsHtml(tag, relPath) {
  if (!tag || !relPath) return "";
  const dl = api.runFileUrl(tag, relPath);
  return (
    "<span class='file-actions'>" +
    "<a class='btn btn-ghost file-act' href='" + dl + "' download target='_blank' rel='noopener' title='Download'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M12 3v12M7 11l5 4 5-4M5 21h14'/></svg> Download</a>" +
    "<button class='btn btn-ghost file-act' data-reveal data-tag='" + fmt.escape(tag) +
    "' data-path='" + fmt.escape(relPath) + "' title='Show in your file manager (when the GUI runs on your machine)'>" + icon('folderOpen',{size:13}) + " Locate</button>" +
    "</span>"
  );
}

// Wire any [data-reveal] buttons under `root` to the reveal endpoint.
export function wireFileActions(root) {
  if (!root) return;
  root.querySelectorAll("[data-reveal]").forEach((b) => {
    if (b._wired) return;
    b._wired = true;
    b.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      try {
        const r = await api.revealFile(b.dataset.tag, b.dataset.path);
        if (r && r.ok === false) toast.show(r.error || "Could not locate it", "warn");
        else toast.show("Revealed in file manager", "success");
      } catch (ex) { toast.show("Locate failed: " + (ex.message || ex), "error"); }
    });
  });
}

// "Copy path" button — hands the user the on-disk location of the file they
// are looking at (provenance dialogs: "verify this outside LanEx").
export function copyPathHtml(absPath) {
  if (!absPath) return "";
  return "<button class='btn btn-ghost file-act' data-copypath='" + fmt.escape(absPath) +
    "' title='Copy the full file path to the clipboard'>" + icon('file', { size: 13 }) + " Copy path</button>";
}

export function wireCopyPath(root) {
  if (!root) return;
  root.querySelectorAll("[data-copypath]").forEach((b) => {
    if (b._wired) return;
    b._wired = true;
    b.addEventListener("click", async (e) => {
      e.preventDefault();
      const p = b.dataset.copypath;
      try {
        await navigator.clipboard.writeText(p);
        toast.show("Path copied: " + p, "success");
      } catch {
        // Clipboard needs a secure context / permission — degrade to showing
        // the path so the user can copy it by hand, never fail silently.
        window.prompt("File path (copy it from here):", p);
      }
    });
  });
}

// Render `text` into `container` with a Find box (highlight + prev/next + count)
// and, when `opts.tag`/`opts.path` are given, Download + Locate buttons. This is
// the single widget for any flow-produced text/log/report shown to the user.
// `opts.line` (1-based) highlights + scrolls to that source line — used by the
// provenance viewers to point at the exact line a displayed value came from.
// `opts.abs` adds a Copy-path button for the on-disk location.
export function renderFileText(container, text, opts = {}) {
  if (!container) return;
  const raw = (text == null || text === "") ? (opts.emptyMsg || "(empty)") : String(text);
  const lines = raw.split("\n");
  const hlLine = (Number.isInteger(opts.line) && opts.line >= 1 && opts.line <= lines.length)
    ? opts.line : null;
  container.innerHTML =
    "<div class='fv-toolbar'>" +
    (opts.title ? "<span class='fv-title'>" + fmt.escape(opts.title) + "</span>" : "") +
    (hlLine ? "<span class='pill fv-lineno' title='The highlighted line the value came from'>line " + hlLine + "</span>" : "") +
    "<input type='search' class='inp fv-find' placeholder='find in text…'/>" +
    "<span class='muted fv-count'></span>" +
    "<button class='btn btn-ghost fv-prev' title='Previous match'>◀</button>" +
    "<button class='btn btn-ghost fv-next' title='Next match'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M7 4l13 8-13 8z'/></svg></button>" +
    "<span class='fv-spacer'></span>" +
    copyPathHtml(opts.abs) +
    fileActionsHtml(opts.tag, opts.path) +
    "</div>" +
    "<pre class='fv-pre code'></pre>";
  const pre = container.querySelector(".fv-pre");
  // Center a mark by scrolling ONLY the file pane. scrollIntoView would also
  // scroll every scrollable ancestor — inside a dialog (overflow: auto) that
  // pushes the toolbar (file name, Copy path / Download / Locate) and the
  // dialog head permanently out of reach on long files. offsetTop is relative
  // to .fv-pre (position: relative in CSS).
  const centerInPre = (m) => {
    if (!m) return;
    pre.scrollTop = Math.max(0, m.offsetTop - (pre.clientHeight - (m.offsetHeight || 0)) / 2);
  };
  const paintPlain = () => {
    if (hlLine) {
      pre.innerHTML = lines.map((l, i) =>
        (i + 1 === hlLine)
          ? "<mark class='fv-line'>" + esc(l || " ") + "</mark>"
          : esc(l)).join("\n");
      centerInPre(pre.querySelector(".fv-line"));
    } else {
      pre.textContent = raw;
    }
  };
  paintPlain();
  if (opts.scrollBottom && !hlLine) pre.scrollTop = pre.scrollHeight;
  wireFileActions(container);
  wireCopyPath(container);

  const input = container.querySelector(".fv-find");
  const count = container.querySelector(".fv-count");
  let cur = 0;
  const apply = () => {
    const q = input.value;
    if (!q) { paintPlain(); count.textContent = ""; return; }
    const rx = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    let n = 0;
    pre.innerHTML = esc(raw).replace(rx, (m) => "<mark class='fv-hit'>" + esc(m) + "</mark>");
    const hits = pre.querySelectorAll(".fv-hit");
    n = hits.length;
    if (!n) { count.textContent = "0"; return; }
    cur = ((cur % n) + n) % n;
    hits.forEach((h, i) => h.classList.toggle("fv-cur", i === cur));
    count.textContent = (cur + 1) + "/" + n;
    centerInPre(pre.querySelector(".fv-cur"));
  };
  input.addEventListener("input", () => { cur = 0; apply(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); cur += e.shiftKey ? -1 : 1; apply(); } });
  container.querySelector(".fv-next").addEventListener("click", () => { cur += 1; apply(); });
  container.querySelector(".fv-prev").addEventListener("click", () => { cur -= 1; apply(); });
}
