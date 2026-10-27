# The Cells & macros tab

What designers need from a cell library and macro page, what the established tools
do best, and how LanEx's rebuilt tab (2026-10-04, `ui-redesign`) maps them onto the
RTL-to-GDS flow. Files: `controller/celllib.py`, `controller/macrolib.py` (new),
`controller/custommacros.py` and `customcells.py` (extended), the "Cells tab" block
in `server/routes.py`, `static/modules/cells.js`, `cells-model.js`, `cells-macros.js`,
`cells-rules.js`, `static/cells.css`. Tests: `tests/test_cells_tab.py` and the
`cells:` checks in `tests/frontend_test.mjs`.

## 1. What the established tools do best

| Tool | Its selling point here | Taken into LanEx |
|---|---|---|
| Cadence Virtuoso Library Manager | Library → cell → view browsing, cells sorted into categories | Families grouped by category, one cell sheet with every view (function, layout, timing, LEF) |
| Synopsys Library Manager / ICC2 lm_shell | Reads LEF + GDS + Liberty into one checked library; validates before use | One reader joins Liberty, LEF, GDS and the PDK's flow config per cell; problems shown, not hidden |
| Silvaco Liberty Analyzer, PrimeLib/Liberate QA | Plots NLDM tables, compares cells and libraries, heat maps | Delay-vs-load curves for every drive strength, FO4 operating point, NLDM table as a heat map |
| SkyWater PDK docs | One page per cell: description, symbol, schematic, layout | Plain description and formula from the PDK's own Verilog headers, gate diagram, truth table, real GDS |
| KLayout / Magic | Real layout with the PDK's layer colours | GDS polygons drawn with the PDK's `.lyp` colours, layer toggles, pin labels |
| Design Compiler / Genus `set_dont_use` | Exclude cells from optimisation | `EXTRA_EXCLUDED_CELLS` editor with a live preview of what each wildcard catches, plus the PDK's own lists |
| Innovus / ICC2 floorplan | Place macros by hand, halos, pin-aware placement | Floorplan sketch with drag-to-place, halo rings, an "Arrange for me" packer |
| OpenLane / LibreLane macro docs, Caravel | `MACROS`, `PDN_MACRO_CONNECTIONS`, `USE_POWER_PINS` | All generated: instance paths, power hookup, instantiation template |
| OpenRAM + PDK SRAM macros | Ready memories in sky130/gf180/IHP | One-click "Memory from the PDK", referenced with `pdk_dir::` |
| Chipyard Hammer / MacroCompiler | Picks SRAMs by words × bits | Catalog shows words × bits, KB, ports and size |
| SiliconCompiler | Hard libraries (cells, macros) as first-class objects | Macros from three sources share one model and one set of checks |
| OpenROAD `report_cell_usage`, LibreLane `cell.rpt` | Which cells the design used | Last-run counts on every drive pill; Analytics cell rows open the cell here |

## 2. What people do on this page

- **Beginners** meet cell names in netlists, timing paths and layouts (`a21oi_2`?).
  They want what it does, what it looks like, and why there are `_1/_2/_4`
  versions. Zero to ASIC's first exercise is exactly that: pick a cell, simulate
  it, measure its delay.
- **Working designers** check what synthesis picked (usage), ban cells
  (`dont_use`), see why a cell never shows up (PDK lists), know which cells the flow
  inserts (fill, taps, ties, CTS buffers), and add memories or hardened blocks.
- **The first macro** is where most open-flow designs stall. The usual failures:
  the module is never instantiated or the instance path is wrong (flattened
  `u_core.u_sram`), the behavioural SRAM model is left in the sources (synthesised
  as flip-flops), no timing model, power pins not hooked to the grid, and, as found
  while building this, **no position**.

## 3. How it ties into the Design workflow

Setup picks the PDK and library → RTL IDE writes the RTL → **Cells** says what that
RTL is built from and wires in the blocks it instantiates → Run. The tab follows the
open project: its library, its usage, its config. Changes go where the flow reads
them: exclusions are written to the config key by key (`configedit`), macros and
custom cells ride along per run in LanEx's overlay (`.gui-macros.json`, `-c`
overrides), and are listed with their source files so nothing is hidden.
Analytics' cell rows and the Layout tab's cell inspector both open a cell here
(`cells.js` `openCell(name, {pdk, scl})`).

## 4. What the page shows

**Top:** library picker (defaults to the project's), tiles: cells and families,
how many synthesis can use, how many are never used (PDK vs you), last-run usage,
macros needing attention.

**Library:** family list (search by name, function words or pasted names, category
chips, used/hide-excluded toggles, sort by name/area/speed/usage, keyboard ↑↓←→ and
`/`). Drive pills: green = used last run, struck = the flow won't use it. The cell
sheet: header facts (area, size, sites, delay at FO4, input cap, leakage), What it
does (PDK formula, gate diagram, truth table; flip-flops and latches in words, scan
and enable inputs explained), Layout (real GDS, PDK colours), Drive strengths
(curves + table), In this design's flow (may it be used, why not, one-click exclude
cell or family), Pins & timing arcs (NLDM tables, copy an instance).

**Macros:** three sources (PDK memory, another project's finished run, files).
Each card runs the checks above with a one-click fix where one exists (use the RTL's
instance names, hook up power, arrange, copy template). Floorplan sketch with drag
to place; halo setting; the overlay file viewable.

**Flow rules:** your exclusions (live wildcard preview), the PDK's synthesis and
placement lists (with the file they come from), the cells the flow inserts (role,
cell, why, set by PDK or your config), and custom-cell swaps with a site-grid check
on the LEF.

## 5. Accuracy notes (checked against LibreLane 3.0.4 and the installed PDKs)

- The typical corner is the Liberty file LibreLane synthesises against (`LIB_SYNTH`,
  else the default corner). Units are converted from the file's own units.
- Liberty states functions in sum-of-products (`a21oi` as `(!A1&!B1)|(!A2&!B1)`);
  the page shows the PDK header formula when there is one, and otherwise folds De
  Morgan and common factors back (gf180 `aoi21` reads `!((A1 & A2) | B)`). Tests
  prove the forms equal by truth table.
- PDK configs are Tcl; they are read line by line (including local `set tmp`
  variables) and migrated to current names with LibreLane's own
  `pdk_compat.migrate_old_config`.
- **LibreLane 3's Classic flow has no automatic macro placer** (only
  `Odb.ManualMacroPlacement`). A macro without a location is never placed and the
  run stops at `OpenROAD.GeneratePDN` with PDN-0235 "Design has unplaced macros".
  The old Cells tab told users to leave X/Y blank for automatic placement; that is
  fixed: positions are required, "Arrange for me" packs them, run start warns.
- A custom-cell swap used to drop the config's own `EXTRA_EXCLUDED_CELLS` /
  `EXTRA_LEFS` (a `-c` override replaces the value). Fixed in
  `customcells.build_overrides`.
- SPEF folders of a finished run are RC corners (`nom`, `min`, `max`); in `MACROS`
  they become `nom_*` etc. so they match LibreLane's timing-corner names.

## 6. Verification

- Library readers run on sky130A (445 cells), gf180mcuD (229) and ihp-sg13g2 (85):
  about 1.6 to 2.5 s on first open, cached after.
- Real LibreLane runs (container, scratch project, deleted afterwards): a PDK SRAM
  at `u_core.u_sram` plus a block imported from another project's run, both placed
  by the page. Flow ran clean through `OpenROAD.STAMidPNR`. The PDN log shows both
  `PDN_MACRO_CONNECTIONS` regexes matched; the final DEF has both macros `FIXED` at
  the positions the page set.
- Headless browser tests: add from the PDK (instances found through the hierarchy,
  power hooked, the behavioural-model check fired), Arrange (correctly refuses when
  there is no room), drag-to-place saved, exclusion add/remove round trip in the
  config, project import dialog (0.65 s).
- `pytest`: 92 passed (new `test_cells_tab.py` plus the existing macro and server
  suites). `frontend_test.mjs`: all `cells:` checks pass. The single failing check
  there belongs to the Preview/Layout work happening in parallel.

## 7. Not done yet

- Cell roles are shown, not edited (change them in the config / All settings).
- No macro pin-side or orientation suggestions, and no blockages beyond the halo.
- A macro's own GDS isn't drawn in the page (SRAM GDS files are large); the sketch
  uses its LEF outline. Open the run's GDS in KLayout to see it.
