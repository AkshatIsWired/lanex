# Layout tab

The Layout tab is where a run's chip is shown. It replaces the old **Preview**
tab (the flow's KLayout PNG, raw formats, diagrams, output files) and the old
**Layout** tab (the same PNG again, an info-only "3D" button and four small
viewer buttons). Both showed the same picture; neither let you look at it.

## What it does

- **A live layout viewer, drawn by KLayout.** LibreLane already installs the
  `klayout` Python package, and since 0.28 it carries KLayout's own renderer
  (`klayout.lay.LayoutView`) without Qt. The server opens the run's GDS (or a
  stage's DEF) once and draws whatever viewport the browser asks for, with the
  PDK's `.lyp` colours. This is how gdsfactory's kweb and OpenROAD's web viewer
  work. Pan and zoom move the last picture instantly; a sharp picture follows
  when the hand stops, then an antialiased one (KLayout oversampling), so dense
  layouts read like a die photo instead of a moiré of stipples.
- **Flow stages.** A strip of real thumbnails: Floorplan, Power grid,
  Placement, Clock tree, Routing, Final GDS. Each stage is the DEF of the last
  step of that phase, opened the way LibreLane's `OpenInKLayout` opens a DEF
  (tech LEF + cell LEFs + the PDK's LEF/DEF layer map). The view stays put when
  you switch, so you can watch one spot change. "Play the flow" steps through
  them; "Other snapshot" opens any step that wrote a DEF, or the separate
  KLayout and Magic stream-outs. A run that stopped early shows the last stage
  it reached and says so.
- **Click anything** to see what it is: the layer in plain words ("metal wiring
  layer 2 …"), its size, the standard cell it sits in, decoded ("D flip-flop
  with reset, drive strength 2"), with *Highlight all*, *Zoom to cell* and
  *In Cells* (opens that cell in the Cells tab).
- **Side panel**, shaped after KLayout and Virtuoso's layer palette:
  - *Layers*: only layers that have shapes, grouped (metal and vias, local
    interconnect, transistor layers, wells and implants, pins and labels,
    boundaries), each with its PDK swatch and GDS number. Tick on/off, "only"
    or Alt-click to solo, presets *Everything / Wiring / Transistors*. Choices
    carry across stages by layer name.
  - *Cells*: every cell type placed, grouped by what it does (flip-flops, logic,
    inverters, buffers, …, fill/tap/decap), with counts and a plain-English
    description; click to highlight every instance on the layout.
  - *Find*: pins and labels (bus bits collapse), cell types; click to fly there.
  - *Checks*: the run's KLayout DRC, Magic DRC, routing DRC and XOR markers,
    drawn on the layout (Calibre RVE-style cross-probing); click one to zoom to
    it. A clean run says which checks found nothing.
- **I/O pins** are named round the die at a readable size; KLayout's own labels
  use a vector font that scales with the zoom, so they stay out of the way at
  "fit".
- **Tools**: fit, zoom, measure (rulers snap to 0/45/90°; Alt for any angle),
  labels, cell outlines (cells as named boxes), dark/white background, full
  screen, overview map. Keys on the view: F fits, + −, arrows, M, L, O, [ ],
  3, Esc.
- **3D.** The layer stack at its real heights (from the PDK's GDS3D process
  file when installed; evenly spaced otherwise, and the badge says which),
  extruded in WebGL. Zoomed in, it shows the area on screen. Height
  exaggeration and "spread layers" (an exploded view) are sliders.
- **Desktop viewers**: KLayout, OpenROAD GUI, Magic and GDS3D as cards saying
  what each is for and whether it is ready (container, installed, no display,
  not installed). The split button in the run bar remembers the last one.
  OpenROAD opens the database of the stage on screen when the run kept it;
  parasitics are loaded only on the final database, since the run's SPEF
  belongs to the final layout.
- **Command** copies the terminal commands a LibreLane user would type
  (`--run-tag <tag> --flow OpenInKLayout` / `OpenInOpenROAD`, built from the
  run's own CLI line, and a plain `klayout -nn <lyt> -l <lyp> <gds>`).
- **Save image**: this view, or the whole chip at 4K (smoothed) or 8K. In 3D,
  the 3D view.
- **Run files** (a drawer under the viewer): every output in `final/`, any
  design format as text, and the Yosys synthesis diagrams. This is the useful
  part of the old Preview tab.

## Research behind it

- **KLayout** (the reference GDS viewer): hierarchy left, layers right, layer
  list hides empty layers, F2 fits, rulers, marker browser for DRC databases.
- **Cadence Innovus / Virtuoso, Synopsys ICC2**: the layout canvas is the
  centre of the tool; layer palette with visibility and selectability per
  layer; results cross-probe into the layout.
- **Calibre RVE / Pegasus / ICV VUE**: a results list that zooms the layout to
  each marker.
- **OpenROAD GUI and its web viewer**: display controls by object type, the
  design at each step of the flow, timing paths and heat maps (we hand those to
  the real OpenROAD GUI rather than imitate them).
- **gdsfactory kweb / kwasm**: KLayout's renderer behind a browser viewer with
  a layer panel.
- **Tiny Tapeout** (the beginner reference): the chip in 3D and in layers, right
  in the browser, is what newcomers come for.
- **GDS3D**: the layer stack at real heights, the exploded view.
- What users struggle with in the terminal flow: knowing which of four viewers
  to open and why, remembering `--flow OpenInKLayout`/`make gui_final`,
  GUI windows over WSL/X11, and labels that turn a fit view into noise.

## Code

| Part | File |
|---|---|
| Engine (sessions, render, probe, cells, labels, markers, 3D mesh, commands) | `lanex/controller/layoutview.py` |
| Routes | `routes.py`: `/api/layout/{sources,open,render,thumb,probe,instances,mesh,markers,commands}` |
| Page | `static/modules/layout.js`, `static/layout.css` |
| 2D camera and interaction | `static/modules/layoutcanvas.js` |
| 3D view | `static/modules/layout3d.js` |
| Run files drawer | `static/modules/runfiles.js` |
| Desktop launches | `static/modules/layouttools.js` (also used by Verify) |
| Tests | `lanex/tests/test_layoutview.py`, Layout checks in `lanex/tests/frontend_test.mjs` |

KLayout objects are not thread-safe, so every call into a session holds one
lock; up to four sessions stay open (LRU), thumbnails use throwaway views. When
the `klayout` package is missing, the page says so, shows the flow's PNG, and
the desktop viewers still work. The Python changes reach a running app only
after LanEx restarts; until then the tab says so instead of failing quietly.
