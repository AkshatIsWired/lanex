// about.js — the "License & notices" modal. REAL text only (truth-in-UI):
// the Apache-2.0 line is a fact of the repo LICENSE; the NOTICE body is shown
// ONLY if /api/about serves it. Never hardcode a NOTICE copy here — it drifts.
import { alertDialog } from "./dialog.js";

export async function showAbout() {
  let body =
    "<p>LanEx is provided under the <b>Apache License 2.0</b>, AS IS, without warranty.</p>";
  try {
    const r = await fetch("/api/about", { headers: { "X-Requested-With": "XMLHttpRequest" } });
    if (r.ok) {
      const j = await r.json();
      if (j && j.notice) {
        const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;");
        body += "<pre class='code about-notice'>" + esc(j.notice) + "</pre>";
      }
    }
  } catch (_e) { /* endpoint absent → license line only; never fabricate NOTICE text */ }
  alertDialog({ title: "License & notices", body, html: true });
}
