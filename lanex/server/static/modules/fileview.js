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

// Render `text` into `container` with a Find box (highlight + prev/next + count)
// and, when `opts.tag`/`opts.path` are given, Download + Locate buttons. This is
// the single widget for any flow-produced text/log/report shown to the user.
export function renderFileText(container, text, opts = {}) {
  if (!container) return;
  const raw = (text == null || text === "") ? (opts.emptyMsg || "(empty)") : String(text);
  container.innerHTML =
    "<div class='fv-toolbar'>" +
    (opts.title ? "<span class='fv-title'>" + fmt.escape(opts.title) + "</span>" : "") +
    "<input type='search' class='inp fv-find' placeholder='find in text…'/>" +
    "<span class='muted fv-count'></span>" +
    "<button class='btn btn-ghost fv-prev' title='Previous match'>◀</button>" +
    "<button class='btn btn-ghost fv-next' title='Next match'><svg viewBox='0 0 24 24' width='13' height='13' fill='none' stroke='currentColor' stroke-width='1.6' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'><path d='M7 4l13 8-13 8z'/></svg></button>" +
    "<span class='fv-spacer'></span>" +
    fileActionsHtml(opts.tag, opts.path) +
    "</div>" +
    "<pre class='fv-pre code'></pre>";
  const pre = container.querySelector(".fv-pre");
  pre.textContent = raw;
  if (opts.scrollBottom) pre.scrollTop = pre.scrollHeight;
  wireFileActions(container);

  const input = container.querySelector(".fv-find");
  const count = container.querySelector(".fv-count");
  let cur = 0;
  const apply = () => {
    const q = input.value;
    if (!q) { pre.textContent = raw; count.textContent = ""; return; }
    const rx = new RegExp(q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "gi");
    let n = 0;
    pre.innerHTML = esc(raw).replace(rx, (m) => "<mark class='fv-hit'>" + esc(m) + "</mark>");
    const hits = pre.querySelectorAll(".fv-hit");
    n = hits.length;
    if (!n) { count.textContent = "0"; return; }
    cur = ((cur % n) + n) % n;
    hits.forEach((h, i) => h.classList.toggle("fv-cur", i === cur));
    count.textContent = (cur + 1) + "/" + n;
    const c = pre.querySelector(".fv-cur");
    if (c) c.scrollIntoView({ block: "center", behavior: "smooth" });
  };
  input.addEventListener("input", () => { cur = 0; apply(); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); cur += e.shiftKey ? -1 : 1; apply(); } });
  container.querySelector(".fv-next").addEventListener("click", () => { cur += 1; apply(); });
  container.querySelector(".fv-prev").addEventListener("click", () => { cur -= 1; apply(); });
}
