# Copyright 2026 LanEx Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
"""Dialog scroll regression: long content must stay reachable.

The shipped bug this locks: customDialog reused the folder browser's
``.dlg-wide`` class, whose ``.dlg-body { overflow: hidden }`` + fixed height
clipped every long provenance/final-settings dialog with NO way to scroll to
the cut-off text. customDialog now uses ``.dlg-xl`` (body scrolls, head and
Close stay pinned). A real headless browser measures the actual computed
layout from the REAL stylesheets — a pure CSS regression can't be caught any
other way. Skips honestly when no Chromium-family browser is available.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).resolve().parents[1] / "server" / "static"

_HARNESS = """<!DOCTYPE html><html><head>
<link rel="stylesheet" href="{styles}">
<link rel="stylesheet" href="{features}">
</head><body>
<div id="app-dialog-host"><div class="dlg-backdrop" role="dialog">
<div class="dlg dlg-xl" role="document">
<div class="dlg-head">t</div>
<div class="dlg-body" id="body"></div>
<div class="dlg-actions"><button class="btn btn-ghost" id="close">Close</button></div>
</div></div></div>
<script>
const b = document.getElementById("body");
b.innerHTML = Array.from({{length: 300}}, (_, i) => "<p>row " + i + "</p>").join("") +
  "<p id='end'>END</p>";
window.addEventListener("load", () => {{
  b.scrollTop = 999999;
  const bb = b.getBoundingClientRect();
  const e = document.getElementById("end").getBoundingClientRect();
  const c = document.getElementById("close").getBoundingClientRect();
  document.title = JSON.stringify({{
    bodyOverflowY: getComputedStyle(b).overflowY,
    bodyScrollable: b.scrollHeight > b.clientHeight,
    scrolled: b.scrollTop,
    endReachable: e.top < bb.bottom + 5 && e.bottom > bb.top - 5,
    closeVisible: c.height > 0 && c.bottom <= window.innerHeight + 1,
  }});
}});
</script></body></html>
"""


def _browser() -> str | None:
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome",
                 "google-chrome-stable"):
        p = shutil.which(name)
        if p:
            return p
    return None


def test_long_dialog_body_scrolls_and_close_stays_visible(tmp_path: Path) -> None:
    browser = _browser()
    if not browser:
        pytest.skip("no Chromium-family browser on this machine — the CSS "
                    "layout regression needs a real renderer")
    page = tmp_path / "dlg.html"
    page.write_text(_HARNESS.format(styles=(_STATIC / "styles.css").as_uri(),
                                    features=(_STATIC / "features.css").as_uri()))
    out = subprocess.run(
        [browser, "--headless", "--disable-gpu", "--no-sandbox",
         "--window-size=1280,800", "--dump-dom", page.as_uri()],
        capture_output=True, text=True, timeout=60)
    m = re.search(r"<title>(\{.*?\})</title>", out.stdout)
    assert m, f"harness produced no measurement: {out.stdout[:300]!r}"
    r = json.loads(m.group(1).replace("&amp;", "&"))
    assert r["bodyOverflowY"] in ("auto", "scroll"), \
        f"dialog body must scroll, got overflow-y={r['bodyOverflowY']} " \
        "(the .dlg-wide overflow:hidden bug)"
    assert r["bodyScrollable"] and r["scrolled"] > 0, \
        f"body did not actually scroll: {r}"
    assert r["endReachable"], "the last line of a long dialog must be reachable"
    assert r["closeVisible"], "the Close button must stay on screen while scrolled"


def test_customdialog_uses_dlg_xl_not_the_folder_browser_class() -> None:
    """Static half of the lock (runs everywhere, no browser needed)."""
    dialog_js = (_STATIC / "modules" / "dialog.js").read_text()
    assert 'classList.add("dlg-xl")' in dialog_js
    assert 'classList.add("dlg-wide")' not in dialog_js, \
        ".dlg-wide is the folder browser's variant: fixed height + hidden body overflow"
    css = (_STATIC / "features.css").read_text()
    assert ".dlg-xl .dlg-body" in css
    m = re.search(r"\.dlg-xl \.dlg-body\s*\{([^}]*)\}", css)
    assert m and "overflow: auto" in m.group(1), \
        "the dlg-xl body must scroll its own overflow"
