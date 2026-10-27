---
version: 1
slug: "lanex-server-static-index-html"
primary_target: "lanex/server/static/index.html"
related_targets: []
---

# Cockpit app shell (index.html)

Scope: the LanEx cockpit, every tab plus the app frame (top bar, rail, status line, sheets, dialogs). Visitor mode: Operate.
Audience/job: see PRODUCT.md. Beginners reach a GDS from a template; experts run, inspect and compare without friction.
Constraints: vanilla ES modules, no build; offline assets; >=1280 CSS px first-class, 4K clean; dark default + light theme.

## Direction contract

THESIS: The cockpit is a shuttle reticle. Panels are dies, separated by scribe lanes and named in the lane; the frame is the reticle edge. It refuses the generic dark-dashboard of glowing cards, pills and icon tiles.
OWN-WORLD: Chrome-black wafer ground, flat die panels with a seal-ring hairline, corner alignment crosses on page-level dies only. Quartz-white ink. Colour appears only as sky130 layer state (met1 active, met3 pass, met4 warn, poly fail) in thin bands, never on prose. DIN-lineage grotesk (Barlow) for UI, Semi Condensed caps for lane labels, JetBrains Mono only for paths, code and numbers.
STORY: The user sees which project they are in, whether it can run, and runs it from anywhere; everything else is one click away and nothing shouts.
FIRST VIEWPORT: 48px reticle edge (mark + LanEx, project switcher, command search, Run split button, Tools, Help, zoom, theme). 76px rail, System group pinned to its foot. Sticky page header per tab. 28px wafer-edge status line: run state, PDK, engine, mode, Logs, not-sign-off notice.
FORM: Shuttle Reticle, #6 of 7 grounded; seed key 69922481. Raises: colour only in thin state bands (cloud); failure breaks the grid structurally (depot); depth only on the selected die and popovers (console); literal lane labels (streetwear).
FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
