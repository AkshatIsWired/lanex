// toast.js — bottom-right notifications. Class-styled (no inline cssText),
// icon per type, dismissable, error toasts are sticky + assertive.

import { icon } from "./icons.js";

const ICON = { success: "check", warn: "alert", error: "x", info: "dot" };
const MAX = 4;

export const toast = {
  container: null,

  init() {
    const c = document.createElement("div");
    c.className = "toast-host";
    c.setAttribute("role", "status");
    c.setAttribute("aria-live", "polite");
    document.body.appendChild(c);
    this.container = c;
  },

  show(message, type = "info", duration) {
    if (!this.container) this.init();
    // Cap the stack — drop the oldest so a burst can't wallpaper the screen.
    while (this.container.children.length >= MAX) {
      this.container.firstElementChild?.remove();
    }
    const t = type in ICON ? type : "info";
    const el = document.createElement("div");
    el.className = "toast toast-" + t;
    // The element itself carries role=alert for errors — that is what actually
    // makes a screen reader interrupt (the container's aria-live is polite).
    if (t === "error") el.setAttribute("role", "alert");

    const ic = document.createElement("span");
    ic.className = "toast-ico";
    ic.innerHTML = icon(ICON[t], { size: 15 });
    const msg = document.createElement("span");
    msg.className = "toast-msg";
    msg.textContent = message;
    const close = document.createElement("button");
    close.className = "toast-close";
    close.setAttribute("aria-label", "Dismiss");
    close.innerHTML = icon("x", { size: 13 });
    el.append(ic, msg, close);
    this.container.appendChild(el);
    requestAnimationFrame(() => el.classList.add("is-in"));

    // Errors stick until dismissed; everything else auto-dismisses. Hover pauses.
    const ttl = duration != null ? duration : (t === "error" ? 0 : 4000);
    let timer = null;
    const dismiss = () => {
      if (timer) clearTimeout(timer);
      el.classList.remove("is-in");
      setTimeout(() => el.remove(), 200);
    };
    const arm = () => { if (ttl > 0) timer = setTimeout(dismiss, ttl); };
    close.addEventListener("click", dismiss);
    el.addEventListener("mouseenter", () => { if (timer) clearTimeout(timer); });
    el.addEventListener("mouseleave", arm);
    arm();
    return dismiss;
  },
};
