# The RTL IDE: what it borrows, and why

The RTL IDE tab is step 2 of the Design stage ("write and simulate", see
`docs/design-workflow.md`): write the RTL, check it with Verilator, simulate it
with a testbench, read the waveform, and only then start the 5 to 60 minute
RTL-to-GDS run. Written 2026-10-03 for the `ui-redesign` branch.

## 1. What people already use, part by part

| Part | Commercial | Open source / education | What LanEx takes |
|---|---|---|---|
| Editor | Vivado, Quartus, Sigasi, DVT (VS Code) | VS Code + TerosHDL, EDA Playground (CodeMirror) | CodeMirror 6: undo per file, auto-indent, bracket match, folding, find/replace with case/regex/word, multi-cursor, Ctrl / comments, keyword/system-task/block completion |
| Lint | Spyglass, Verilator in every flow | TerosHDL (Verilator, Verible) | Verilator `--lint-only`, squiggles with the message on hover, Problems grouped by file, each warning code explained |
| Files | Vivado Sources (Design / Simulation / Constraints), Hierarchy | TerosHDL hierarchy viewer | Files grouped by role, plus a Hierarchy view (top → instances, testbench → DUT) |
| Simulate | xsim, Questa, Xcelium | Icarus, Verilator, EDA Playground's Run | One Simulate button that names its testbench, a result in words, compile errors in Problems |
| Waveform | Vivado Wave, Verdi nWave, SimVision | GTKWave, Surfer, DVT Waveform Viewer, EPWave | Signal tree + search, name/value columns, ruler in real units, cursor + marker + Δ, drag to zoom, edge jumps, per-signal radix and colour, layout kept per testbench |
| Debug links | Verdi: double-click a signal → source, values annotated in code | DVT: jump to definition, add from editor | Double-click a signal → declaration; hover a name in the code → its value at the cursor, one click adds it |

## 2. What changed in this pass

**Editor.** The transparent-textarea overlay is replaced by CodeMirror 6,
bundled offline as `static/vendor/codemirror.js` (MIT, 436 KB; rebuilt by
`scripts/vendor.sh` from `scripts/vendor/codemirror-entry.js`). Verilog/SV,
SDC/Tcl, YAML and JSON modes; a fold service for begin/end, module, case,
function, task, generate, fork/join; indent detected from the file (2, 4 or
tab); snippets for module, always blocks, case, generate, a testbench clock
and the `$dumpfile` block. Each tab keeps its own undo history and scroll.

**Check syntax.** Check on save is on by default (was "Auto-check": off, and
it saved the file while you typed). Problems shows errors first, grouped by
file, with the Verilator code; clicking jumps and explains the code in plain
words (`modules/ide/lintinfo.js`). Style-only codes in testbench files
(unused DUT outputs, delays, initial values) are folded into a separate,
uncounted section: they are normal in code that only simulates.

**Simulate.** The button is a split button showing the testbench it runs; the
arrow switches testbench or simulator. All changed files are saved first.
The Simulation tab opens with a result card: passed / ran to the end /
reported failures / didn't build / time limit / no waveform, with `$finish`
time, simulator and duration, and the next action (show the first error,
add the dump block to the testbench, show the waveform, run the flow). The
log colours errors and warnings, dims tool chatter, and links every
file:line. Simulator compile errors go to Problems and the editor.

**Waveform** (`modules/ide/waves.js`, rewritten). Signals panel with every
scope and signal (aliases included), search; a click shows a signal and a
second click takes it off, and a scope's button adds all of it or, when all
of it is on screen, takes it off. Names column (click selects, a second click,
a click on the empty space below or Esc lets go; drag to reorder, Delete removes, right-click for
number format: hex, decimal, signed, binary, octal, ASCII; and colour) and a
value column at the cursor, or under the mouse. Time ruler in ns/µs/ps from
the dump's timescale. Click = cursor (snaps to a nearby change), right-click
or Shift+click = marker, Δ with its frequency, drag = zoom to range,
Ctrl+wheel zoom, Shift+wheel pan, ← → previous/next change, F fit, an
overview strip of the whole run. Buses are drawn as value boxes with the
value inside; x in red, z in amber; dense stretches as a filled band.
Sharp at Windows 125/150 % scaling (canvas at device pixels). Integers and
parameters default to decimal, parameters stay out of the first view, clock
and reset come first. The signal list, formats and colours are kept per
project and testbench, so a re-run after an edit shows the same picture.
Values are BigInt-exact (64-bit buses were rounded before; `signed` was wrong
from 32 bits). GTKWave opens with exactly the signals on screen. Dumps over
200 MB are handed to GTKWave instead of freezing the page.

**Waveform ↔ code.** Double-click a signal (or right-click → Go to
declaration) opens the file that declares it, following the instance path
(tb → dut → …) through the project's instantiations. Hovering a name in the
code shows its value at the waveform cursor for every instance of that
module, with Add to waveform.

**Explorer.** Files | Hierarchy toggle. Right-click (or ⋯) on a file: make
one of its modules the top (writes DESIGN_NAME), build it into the chip or
leave it out (writes VERILOG_FILES, like Setup's ticks), simulate a
testbench, copy the path, delete.

**Workflow.** Setup's step 2 shows the last syntax check and simulation for
the open project ("Last: syntax clean · fifo_tb ran to the end (2 min ago)").
The panel can take the editor's space (the tabs and toolbar stay), and grows
to 60 % when a waveform first arrives unless you sized it yourself.

**Fixed along the way.** The app's single-letter shortcuts (r = run, s = stop,
t = theme, digits = tabs) fired while typing in the editor once it was no
longer a textarea, and inside the waveform; they now ignore both. Escape that
closes find or clears the marker no longer also leaves fullscreen. The
waveform read light-theme colours from the wrong element (always dark).

**Audit fixes (second pass).** A selected signal could not be deselected
(only Ctrl+click did it), and the Signals list could add but never remove.
Gestures in the waveform (row drag, zoom drag, ruler, overview, column
resize) now end however the pointer is released, so none is left stuck; the
overview maps its own width; a click left of 0 or past the end reads the
first or last moment, not a negative time. Opening another project clears the
last one's problems, output and waveform, and keeps each project's open tabs
(unsaved edits included) for when you come back; leaving the page with
unsaved edits asks first. The simulation log only takes the simulator's
lines (a syntax check or a flow run at the same time used to land in it and
in its verdict). A syntax check whose Verilator didn't run says so instead of
"no problems". Saving a file drops the simulator's out-of-date compile errors
for it. Simulate while one is running is refused in place instead of
resetting the buttons; another window's simulation no longer shows up here.
Simulation-only helper modules in `verify/` are compiled with the bench;
`include` folders are passed to both tools. Ctrl+S saves from anywhere in the
IDE (not the browser's Save page). The file menu won't leave the top module's
file, or the last built file, out of the chip. r and s on an IDE button no
longer start or stop the flow run. A waveform from an earlier run is labelled
as such when the latest run wrote none; an FST dump points to GTKWave.

Third pass (from a first hands-on test with a pasted FIFO). Check syntax
saves open files first: Verilator reads the disk, so an unsaved module read as
its stub and the bench showed ten false "Pin not found" errors. Simulator
builds go to `sim_build/` instead of the project root. The explorer warns
when the config's top module isn't defined by any design file and offers
"Make X the top". New file lists seven kinds, most used first, with Verilog
or SystemVerilog as a separate toggle (default: the project's language) and
the path it will create. Files can be renamed (F2 or the file menu; the
server rewrites config entries that name the file, and lists a `.v` → `.sv`
rename explicitly when a `*.v` glob would drop it) and deleted with the
Delete key, without a confirmation, with Undo in the toast. The Simulate split
button is drawn like the top bar's Run split, and the toolbar wraps instead of
squeezing buttons together. Every select now shows its chevron (a field rule
in `shell.css` had been erasing it).

## 3. Checked

On the lanex appliance (Icarus 12, Verilator 5.020), Edge via Playwright, 1536×864
and 1280×720, dark and light, embedded tab and the `/ide` pop-out: FIFO,
Counter and SPM examples; syntax error → squiggle, hover, Problems, failed
build card; completion, folding, find; simulate → card → waveform; drag-zoom,
cursor/marker, edge jumps, tree add, context menu, go to declaration, value
hover; Hierarchy on SPM (spm → dsa; spm_tb → srx, sry, dut → dsa).
`frontend_test.mjs` 46/46; pytest: only the 5 appliance-dependent failures
that also fail without these changes (gds3d ×4, pdk_ready_no_env).

Second pass (same appliance, Edge in the app's browser pane, 1536×864,
embedded tab and `/ide`): select / reselect / deselect by click, empty space
and Esc; Signals list add and remove; row drag released outside the list;
context menu keys; cursor clamp; syntax error → Problems → fix → save clears
it; simulate with Icarus and with Verilator; a bench using a helper model in
`verify/`; syntax check and simulation at the same time (log stays separate);
switching projects and back (tabs and unsaved edit restored).

Not checked: the GTKWave launch itself (unit-tested, not clicked: it opens a
desktop window), a dump near the 200 MB limit, a Verilator that fails to
start (the "couldn't run" Problems view was not triggered for real).

## 4. Open items

- cocotb testbenches (Tiny Tapeout's default) aren't run by the IDE yet.
- Gate-level simulation of a run's netlist with the PDK's cell models.
- Waveform: groups/dividers, analog view of a bus, saved marker sets.
- A quick Yosys synthesis check (cell count, latches) before the full run.

## Sources

- Vivado Wave window, markers and cursors (UG900):
  https://docs.amd.com/r/en-US/ug900-vivado-logic-simulation/Using-Markers,
  https://docs.amd.com/r/en-US/ug900-vivado-logic-simulation/Wave-Objects
- DVT waveform viewer (design panel, signals panel, canvas controls):
  https://eda.amiq.com/documentation/vscode/sv/toc/waveform-viewer/index.html
- Verdi nWave/nTrace (drag signals from source, trace drivers):
  https://courses.grainger.illinois.edu/ECE411/sp2026/verdi.html
- TerosHDL features: https://github.com/TerosTechnology/vscode-terosHDL
- EDA Playground and EPWave: https://eda-playground.readthedocs.io/en/latest/intro.html
- 8bitworkshop Verilog scope view: https://8bitworkshop.com/docs/platforms/verilog/index.html
- Verilator warning reference: https://veripool.org/guide/latest/warnings.html
- Surfer waveform viewer: https://gitlab.com/surfer-project/surfer
