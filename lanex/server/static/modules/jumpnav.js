// jumpnav.js — a reusable "jump to section" chip bar (like the Analytics one),
// for any tab with enough content to scroll. Pure DOM, zero dependency.
//
//   container.insertAdjacentHTML("afterbegin", jumpBarHtml([{target,label}, …]));
//   wireJump(container);   // delegates clicks → smooth-scroll to #target

export function jumpBarHtml(items, { label = "Jump to section" } = {}) {
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  return "<nav class='section-jump' aria-label='" + esc(label) + "'>" +
    (items || []).map((i) =>
      "<button class='chip chip-clickable' data-jump='" + esc(i.target) + "'>" + esc(i.label) + "</button>").join("") +
    "</nav>";
}

// Delegate clicks on a container's `.section-jump` to a smooth scroll, AND keep
// the chip for the section currently in view highlighted as the user scrolls.
// Idempotent.
export function wireJump(container) {
  const nav = (container || document).querySelector(".section-jump");
  if (!nav || nav._jumpWired) return;
  nav._jumpWired = true;
  nav.addEventListener("click", (e) => {
    const b = e.target.closest("[data-jump]");
    if (!b) return;
    const t = document.getElementById(b.dataset.jump);
    if (t) {
      // <details> targets won't scroll their content into view unless open.
      if (t.tagName === "DETAILS") t.open = true;
      t.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  wireScrollSpy(nav);
}

// Highlight the jump chip for whichever target section is currently at the top
// of the scroll viewport, updating live as the user scrolls. Works against the
// app's scroll container (`main.work`). Idempotent per nav.
export function wireScrollSpy(nav, scrollRoot) {
  if (!nav || nav._spyWired) return;
  const chips = Array.from(nav.querySelectorAll("[data-jump]"));
  if (!chips.length) return;
  nav._spyWired = true;
  const root = scrollRoot || nav.closest("main.work") ||
    (typeof document !== "undefined" && document.querySelector("main.work")) || null;
  const setCurrent = (id) =>
    chips.forEach((c) => c.classList.toggle("is-current", c.dataset.jump === id));

  let raf = 0;
  const compute = () => {
    raf = 0;
    if (nav.offsetParent === null) return;     // nav's tab isn't visible — skip
    // The line just below the sticky nav; the section crossing it is "current".
    const base = (root ? root.getBoundingClientRect().top : 0) +
      (nav.getBoundingClientRect().height || 0) + 8;
    let currentId = chips[0].dataset.jump;
    for (const c of chips) {
      const t = document.getElementById(c.dataset.jump);
      if (!t) continue;
      if (t.getBoundingClientRect().top - base <= 1) currentId = c.dataset.jump;
    }
    setCurrent(currentId);
  };
  const onScroll = () => { if (!raf) raf = requestAnimationFrame(compute); };
  (root || window).addEventListener("scroll", onScroll, { passive: true });
  if (typeof window !== "undefined") window.addEventListener("resize", onScroll, { passive: true });
  compute();
}
