# The Design stage: workflow and how LanEx maps it

What every RTL-to-GDS flow asks of a designer, what LanEx shows for it, and why.
Written 2026-10-03 for the `ui-redesign` branch. Covers Design only (project →
sources → RTL check → PDK → settings → run); Run, Results and System come later.

## 1. The universal flow

Commercial flows (Cadence Genus/Innovus, Synopsys DC/ICC2), OpenROAD-flow-scripts,
LibreLane and Tiny Tapeout all need the same five inputs and follow the same loop.
The tools differ in file formats, not in the work.

| Input | Commercial | ORFS | LibreLane | LanEx |
|---|---|---|---|---|
| RTL sources | `read_hdl` list | `VERILOG_FILES` | `VERILOG_FILES` | Sources → Design files |
| Top module | `elaborate top` | `DESIGN_NAME` | `DESIGN_NAME` | Project card |
| Timing intent | SDC (`create_clock`, I/O delays) | `SDC_FILE` (clock lives here) | `CLOCK_PORT` + `CLOCK_PERIOD`, optional SDC | Project card + Sources → Constraints |
| Technology | libs, LEF, tech files | `PLATFORM` | `PDK` + `STD_CELL_LIBRARY` | PDK card |
| Physical intent | floorplan util/aspect, pins, power plan | `CORE_UTILIZATION`, `PLACE_DENSITY`, `DIE_AREA` | `FP_CORE_UTIL`, `PL_TARGET_DENSITY_PCT`, `DIE_AREA`, `IO_PIN_ORDER_CFG` | Settings card, Sources → pin order |

The loop, in the order engineers actually work:

1. **Project folder**: `src/` (RTL), `verify/` or `test/` (testbenches), constraint
   files, one config, `runs/`. The same shape as LibreLane's own examples and every
   Tiny Tapeout repo.
2. **Write RTL** in an editor.
3. **Lint** (Verilator `--lint-only`): seconds, catches most mistakes ("shift left").
4. **Simulate** with a testbench (Icarus, Verilator, cocotb) and read the waveform.
5. **Config**: top, files, clock, PDK. Defaults for everything else.
6. **Run the flow**, then read timing, DRC, LVS, antenna, area.
7. **Iterate on a few knobs**, driven by what failed (below).

Steps 3 and 4 take seconds and save 5 to 60 minutes per mistake. Professionals
never skip them; beginners don't know to do them. LanEx puts them in the path.

## 2. The knobs people actually change

Tiny Tapeout's default LibreLane config (used by thousands of first-time designers)
names exactly which variables a user may touch, each tied to a symptom:
`PL_TARGET_DENSITY_PCT` ("increase if global placement fails with GPL-0302"),
`CLOCK_PERIOD` ("increase for setup violations"), the two hold-slack margins
("increase for hold violations"), and the die size (a fixed tile). The ORFS tutorial
tells users to tune `CORE_UTILIZATION`, `PLACE_DENSITY` and `ABC_AREA`/`ABC_SPEED`
first. Pro configs add `MAX_FANOUT_CONSTRAINT`, `VERILOG_DEFINES`, `RT_MAX_LAYER`
and antenna options.

That list, checked against the installed LibreLane's variable registry, is the
Settings card (`modules/mostused.js`): die sizing (`FP_SIZING`, `FP_CORE_UTIL` or
`DIE_AREA`, `PL_TARGET_DENSITY_PCT`), synthesis (`SYNTH_STRATEGY`,
`VERILOG_DEFINES`, `USE_SLANG`), timing fixes (both hold margins,
`MAX_FANOUT_CONSTRAINT`), routing and antenna (`RT_MAX_LAYER`, `DIODE_ON_PORTS`).
Each field says when to change it, in the symptom-first way Tiny Tapeout does.
A test keeps every key a real LibreLane variable.

**Where values live.** The config file is the project (as in a terminal flow), so
the project card and the Settings card save into `config.json` key by key
(`controller/configedit.py`). All settings (420 variables) keeps its old meaning:
per-run `-c` overrides that leave the file alone, for experiments.

## 3. Three people, one path

| | Beginner | From FPGA tools | From the terminal |
|---|---|---|---|
| Starts with | New project → blank + testbench, or Try an example | New project, or Open a folder + Add files | Open a folder with `config.json`/`.yaml` |
| Recognises | Numbered steps on Setup; the IDE's start page | Sources grouped Design / Simulation / Constraints, top tagged | Their own config, edited key by key; Manual tab shows the CLI |
| Never blocked by | Empty top module (preflight heads-up), tiny-design placement (fixed die) | Mixed `.v`/`.sv` (SystemVerilog projects, Slang toggle) | Tcl configs (read-only, overrides still work) |

## 4. What changed in this pass

- **Project hub**: with nothing open, three start tiles (New project, Open a folder,
  Try an example) and the project list; New/Open appear in one place per state.
  Sources and Settings hide until a project is open.
- **Setup steps**: four, in flow order: open a project, write and simulate, pick
  PDK and settings, run.
- **Settings card** (new) between PDK and Ready to run; the big card is now
  All settings.
- **RTL IDE** rebuilt: explorer grouped by role with a + per group, open-file tabs
  with unsaved marks and Ctrl S, a full-width bottom panel (Problems, Simulation,
  Waveform) that resizes, Simulate next to Check syntax, the top module opens on
  arrival, and a start page that teaches the loop when nothing is open.
- **New testbench** instantiates the real top module: every port, parameters as
  localparams, clock at the config's period, reset released after two cycles,
  outputs printed at the end. It lints clean.
- **New project**: Verilog or SystemVerilog for a blank project, and a matching
  testbench written by default.
- **Preflight**: a top module with no logic is a heads-up before the run.
- **Lint** passes `--timescale 1ns/1ps` so a testbench with a timescale next to
  design files without one isn't a warning.

## 5. Tiny designs and the die size

A design of a few dozen cells on a utilization-sized die fails detailed placement
after CTS (DPL-0036): the blank starter (16 cells) got a 33×44 µm die, the 8-bit
Counter example (31 cells) 38×49 µm. Neither had ever reached a GDS. Blinky (91
cells, 57×68 µm) was fine. Tiny Tapeout avoids this with a fixed tile, and so do
these two templates now: `FP_SIZING: absolute`, `DIE_AREA: [0, 0, 150, 150]`
(template `config` key, `controller/scaffold.py`). The Settings card's die-size
hints say when to switch back to utilization.

Verified on 2026-10-03 with full container runs on sky130A/hd: blank starter
(Verilog and SystemVerilog) and Counter now finish with a GDS and no DRC, LVS or
antenna errors and positive setup and hold slack; Blinky, FIFO and Multiplier do
too, unchanged. (SPM ships its own tuned config and wasn't rerun.) Existing projects made from the old blank
template keep their config; set Die size to a fixed area in Settings to fix one.

## 6. Open items

- Cocotb testbenches (Tiny Tapeout's default) aren't run by the IDE yet.
- Multiple clocks, macros and hierarchy (`SYNTH_HIERARCHY_MODE`) stay in All
  settings and the config file.
- The Cells tab hasn't been looked at in this pass.

## Sources

- LibreLane newcomers' tutorial and configuration reference:
  https://librelane.readthedocs.io/en/latest/getting_started/newcomers/index.html,
  https://librelane.readthedocs.io/en/latest/reference/configuration.html
- ORFS, adding a design and the flow tutorial:
  https://openroad-flow-scripts.readthedocs.io/en/latest/user/AddingNewDesign.html,
  https://openroad-flow-scripts.readthedocs.io/en/latest/tutorials/FlowTutorial.html
- Tiny Tapeout template config and info.yaml:
  https://github.com/TinyTapeout/tt10-verilog-template
- Vivado project flow (wizard, Sources view):
  https://docs.amd.com/r/2024.2-English/ug936-vivado-tutorial-programming-debugging/Step-1-Creating-a-Project-with-the-Vivado-New-Project-Wizard
- Lint as the first check: https://www.synopsys.com/blogs/chip-design/leveraging-static-linting-tools.html
