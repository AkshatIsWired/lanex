# LanEx workflow spec: one chip, one loop

How a person moves through LanEx from first launch to a finished chip, where the
app breaks that journey today, and what to build so every tab works as one tool.
Written 2026-10-06 on `ui-redesign` (after 939ea5d). It is a plan: no code changed.

Visual version (mockups, journey map, diagrams):
https://claude.ai/artifact/4cYMef9tcvq9Bg8pvAjJHH (private to the owner). This Markdown
file is the source of truth for implementation sessions.

Read with: `PRODUCT.md` (audiences, principles), `docs/design-workflow.md` (Design
stage), and the per-tab write-ups `docs/rtl-ide.md`, `docs/verify.md`,
`docs/cells.md`, `docs/layout.md`.

---

## 1. What users actually do

Every source below describes the same loop. Beginners go round it slowly and watch
every step; veterans go round it at the speed of the run and do other work while it
runs.

```
write -> check (lint, simulate) -> run -> read the verdict -> find the one problem
      -> change one thing (RTL or a setting) -> rerun (whole flow or from a stage)
      -> compare with the last good run -> ship (GDS, files, the command for CI)
```

### 1.1 Six kinds of user

| Who | What they do today (evidence) | What they need from LanEx |
|---|---|---|
| **First-timer** (student, Tiny Tapeout, Zero to ASIC) | LibreLane newcomers' tutorial: write `config.json` (DESIGN_NAME, VERILOG_FILES, CLOCK_PERIOD, CLOCK_PORT), `librelane config.json`, `--last-run --flow openinklayout`, then read `final/metrics.json`, DRC in `52-magic-drc/` and `63-klayout-drc/` (KLayout Marker Browser), LVS in `netgen-lvs.log`, STA in `54-openroad-stapostpnr/summary.rpt`, iterate with `pin_order.cfg`. Tiny Tapeout: `tt_tool.py --harden`, `--print-warnings`, `--open-in-klayout`, `--create-png`, cocotb `make -B`, gate-level `make -B GATES=yes`. FAQ questions: "should density be 100 %?", "my action is slow" (design too big for the tile). | "Did it work?" in one place; "does it fit?"; "can I see it?"; a plain reason and one fix when it fails; gate-level sim after layout. |
| **Course learner** (VSD-style workshop; hundreds of public student write-ups) | Interactive mode: `prep -design`, `run_synthesis` (read stats, compute flop ratio by hand), `run_floorplan` (view in Magic: IO pins, decaps, tap cells), `set ::env(FP_IO_MODE) 2`, `run_placement` (watch overflow converge), pre-CTS STA with OpenSTA, `run_cts`, post-CTS STA, `gen_pdn`, `run_routing`. | Stage by stage, look at the layout after each stage, change one setting, rerun that stage. LanEx's Step-by-step mode pauses after each of ~80 steps; the stage is the right unit. |
| **FPGA engineer moving to ASIC** (Vivado / Quartus / Libero habits) | Vivado Flow Navigator in flow order; runs go to the background while you keep working; "Synthesis Completed" asks what next; Project Summary cards (timing, utilization, power, DRC) link to reports; Design Runs table with WNS/TNS/WHS/THS, utilization and power columns, parent/child runs, compare, out-of-date marks. Quartus Compilation Dashboard: click a stage to run or resume it, each stage has settings and reports. Libero: tools grey until usable, green/amber/out-of-date state on each. | Status on the navigator itself; results marked stale when inputs change; background runs that never steal focus; a "what next" at the end of a run; a runs table with QoR columns. |
| **Terminal veteran** (LibreLane, ORFS) | LibreLane: `--run-tag`, `--last-run`, `-F/--from`, `-T/--to`, `--only`, `-S/--skip`, `-c KEY=VALUE` (this run only), `-i/--with-initial-state`, `--reproducible STEP`, `--flow openinklayout/openinopenroad/openinmagic`, flows Classic / Optimizing / SynthesisExploration / Chip, `--save-views-to`. ORFS: `make DESIGN_CONFIG=…`, `make gui_final`, `clean_place` then rerun one stage, OpenROAD GUI timing widget, clock tree viewer, heatmaps, DRC viewer, AutoTuner. wafer.space template: `make librelane`, `make librelane-openroad`, `make librelane-klayout`. | Rerun from a stage on the previous state; one-off overrides; jump to the real viewer at the right stage; the exact command for everything; raw files one click away; their own config and terminal runs respected. |
| **PD engineer / PPA explorer** | Day: review overnight PnR and timing reports, stand-up on block status, close timing on critical paths, debug congestion, IR, ECO, queue overnight runs. Run management: Synopsys Lynx Management Cockpit (50+ metrics per block, QoR viewer, execution monitor), Cadence Stylus unified metrics. LibreLane timing guide: pre-, mid-, post-PnR STA checkpoints; setup -> `*_SETUP_SLACK_MARGIN`, hold -> `*_HOLD_SLACK_MARGIN`, buffer overflow -> lower `FP_CORE_UTIL`. DSE: AutoTuner (Ray: grid, random, Bayesian), DSO.ai / Cerebrus dashboards, W&B runs table + parallel coordinates + sweeps. | Runs as experiments: one table with QoR columns, a baseline, deltas, notes, sweeps grouped, the winning settings promoted back into the config. |
| **Front-end debugger** (Verdi, TerosHDL habits) | Verdi: waveform to source to schematic cross-probing, trace the driver of a signal. TerosHDL: schematic, FSM, hierarchy and dependency viewers, lint. Calibre RVE at the back end: click a violation, it highlights in the layout. | Every object is a link to where it lives (cross-probing), in both directions. |

### 1.2 Pain points users report

- "Did it work?" means reading five numbered folders and opening three tools (LibreLane tutorial).
- Errors arrive as codes (GPL-0302, DPL-0036, PDN-0235, ANT, LVS mismatch). The terminal state of the art is "the message tells you which log file to read".
- Runs take 5 to 60 minutes, and nothing tells you when they finish.
- A partial rerun needs step IDs and knowledge of which step reads which variable.
- RTL simulation is not silicon: experienced users ask for gate-level simulation with SDF after layout.
- It is hard to know what "normal" looks like (how long, how big, which numbers matter).

### 1.3 UX research that applies

- **NN/g, complex applications**: learning by doing; help users find faster methods; flexible, non-linear paths; help users track their own progress and reasoning; smooth moves between tools; less clutter without less capability; secondary information without leaving the page; make the important thing stand out.
- **Progressive disclosure** (NN/g): the frequent features first, the rest one obvious click away; no more than two levels.
- **Multi-layer interfaces** (Shneiderman): start with a small set, move up when needed. LanEx already removed its Simple/Pro tiers; keep it that way and layer per feature instead.
- **Paradox of the active user** (Carroll and Rosson) and NN/g on onboarding: people skip tutorials; teach in context (pull, not push): empty states, inline "why", help next to the step.
- **Empty states** (NN/g): say what is going on, teach what will appear, give the direct action.
- **Error messages** (NN/g): next to the source, plain words, a constructive fix, keep the user's input, suggest the correction.
- **Object-oriented UX** (ORCA): find the objects users think in, their relationships and actions; relationships become the navigation.
- **Background tasks**: show status, a sense of time and the next action; notify on completion only when the user will act on it.
- **Command palettes**: actions and objects together, recents first, context-aware, fuzzy.
- **Pipeline as navigation**: DaVinci Resolve's pages run left to right in the order of the work (Media, Cut, Edit, Fusion, Color, Fairlight, Deliver), but any page is one click away. Fusion 360's timeline replays the design history and lets you roll back and edit an earlier step.
- **CI logs** (GitHub Actions): a failed step auto-expands and scrolls to the error; errors are highlighted and annotated.

### 1.4 What users say on Reddit (read directly, 2026-10-06)

About 60 threads from r/FPGA, r/chipdesign and r/ECE, read comment by comment from the
Arctic Shift archive (raw JSON kept in the session scratchpad). Paraphrased; scores
are upvotes at archive time. Themes that recur across threads and people:

**How experienced people work**
- They write RTL in their own editor (vim, emacs, VS Code), run the flow from scripts
  or CI, and open a GUI only to check something: a timing path, a schematic, the
  layout, a report. For them the GUI is "a results viewer and query machine".
  [Is Vivado a joke?](https://www.reddit.com/r/FPGA/comments/1c95vj8/) (top answers 127, 75, 35);
  [Why IC design software are so buggy/difficult to use?](https://www.reddit.com/r/chipdesign/comments/10tr1zk/);
  [RTL Designers - what does your dev environment look like?](https://www.reddit.com/r/chipdesign/comments/190xevk/).
- "Start with the GUI, end with the scripts": newcomers should start in the GUI, and
  people learn the scripts by clicking once and copying the command the tool echoes.
  [Vivado Project vs Non-Project Mode](https://www.reddit.com/r/FPGA/comments/10mkkyh/);
  [running vivado … command line only](https://www.reddit.com/r/FPGA/comments/1har9me/);
  [Version control Vivado project …](https://www.reddit.com/r/FPGA/comments/1g064er/).
- Integration and cross-probing are what make a GUI worth it (Vivado praised against
  ASIC flows of "tens of tools"): timing path as a delay breakdown, click through to
  the RTL line. [Vivado - Development environments …](https://www.reddit.com/r/FPGA/comments/1ah29bc/);
  [What is this FPGA tooling garbage?](https://www.reddit.com/r/FPGA/comments/1pkgdxz/).
- Generated files never go in git; the project is sources plus scripts.
  [Version control Vivado project …](https://www.reddit.com/r/FPGA/comments/1g064er/);
  [How do you manage your Vivado projects in git?](https://www.reddit.com/r/FPGA/comments/mw7fsb/).

**Long runs**
- People switch to other work and come back to check; generic "done" pop-ups get
  "don't show again"; scripts that email the timing summary after each phase are
  loved. [How to enable pop-up notification when Vivado finishes](https://www.reddit.com/r/FPGA/comments/1cuk32c/);
  [Sound Notification when Vivado finishes …](https://www.reddit.com/r/FPGA/comments/ljdhdo/).
- Many variants in parallel, keep the first that closes timing; but "100 strategies
  means the design is wrong", and RAM runs out first.
  [Vivado timing closure](https://www.reddit.com/r/FPGA/comments/1ax6cz8/);
  [… run various strategy parallelly …](https://www.reddit.com/r/FPGA/comments/1q21oil/).

**Timing**
- Beginners cannot read timing reports and don't know what is reasonable; experienced
  answers always start with "understand why it fails" (WNS, TNS, how many paths,
  constraints first) and reject "increase effort".
  [How to Analyze Timing Reports in Vivado?](https://www.reddit.com/r/FPGA/comments/vubr1e/);
  [Slow the clock or fix the logic](https://www.reddit.com/r/FPGA/comments/1crbpb0/);
  [Design did not meet timing](https://www.reddit.com/r/FPGA/comments/1bime3r/).
- Where it first fails decides who fixes it: failing already at zero wire load is an
  RTL problem; levels of logic per cycle; look at timing at every stage.
  [When does fixing timing stop being a PD problem?](https://www.reddit.com/r/chipdesign/comments/1wkeeof/).

**Results that look current but aren't**
- Vivado's "out of date" fires on timestamps (even after a comment edit); users want
  "what changed" and "force up-to-date".
  [Synthesis is out-of-date message](https://www.reddit.com/r/FPGA/comments/14gky5s/);
  [Synthesis is out-of-date](https://www.reddit.com/r/FPGA/comments/hin2sh/) (173).
- Thousands of warnings hide the new one that matters.
  [Chip designers, what are your complaints …](https://www.reddit.com/r/chipdesign/comments/11m4w33/).

**Open-source ASIC beginners**
- Can't find a tutorial that works end to end; installed the tools and "need help
  running the flow"; Nix easier than Docker.
  [Tutorials on OpenRoad for RTL2GDSII flow?](https://www.reddit.com/r/chipdesign/comments/1b3rvov/);
  [How to … work with openlane](https://www.reddit.com/r/chipdesign/comments/1gat41p/);
  [Install OpenLane without docker](https://www.reddit.com/r/FPGA/comments/1f40mft/).
- Don't know which output to read ([which xx-mca folder for timing?](https://www.reddit.com/r/FPGA/comments/1fl3gxy/)),
  what each tool does ([efabless openlane](https://www.reddit.com/r/FPGA/comments/rl4knl/)).
- DRC: hundreds of errors are a few rule types in a few places; two checkers disagree
  and nobody says which is right.
  [Stuck with DRC Errors](https://www.reddit.com/r/chipdesign/comments/14a41e4/);
  [Fixing DRC errors help! (tapeout in a week)](https://www.reddit.com/r/chipdesign/comments/1d1hmq4/);
  [magic DRC violations](https://www.reddit.com/r/chipdesign/comments/184xb06/).
- A passing flow is not a working chip (first open shuttle lost to a hold problem);
  do gate-level simulation. [Openlane](https://www.reddit.com/r/FPGA/comments/rtmo89/).
- A memory built from standard cells makes routing take 15+ hours.
  [16KB ROM with standard cells …](https://www.reddit.com/r/chipdesign/comments/1w02nze/).
- The reward is seeing the chip: an exploded 3D render of a first Tiny Tapeout design
  drew 339 upvotes; "can I get pictures like that of my design?" gets "run the
  LibreLane tutorial". [Exploded view of my first ASIC](https://www.reddit.com/r/ECE/comments/x4l72f/);
  [generate those kind of pictures …](https://www.reddit.com/r/FPGA/comments/1r6f33r/).

What this changed in the plan: the Journal (5.9), timing diagnosis and DRC grouping
rules (5.6), notification content (5.5), per-stage staleness with "why" and "mark as
current" (5.7), sweep caps and
"stop when good enough" (6.2), the honest meaning of "clean" (5.5); new-warnings-first
and following terminal runs are listed for later (6.1).

### 1.5 What we took, and what we left out

A Reddit complaint is not a requirement. An idea went into the plan only if it passed
all four tests: it recurs across several threads and people (or is a hard technical
fact checked in LibreLane's source); it serves the two goals (a beginner's first GDS
without a terminal, a veteran who loses nothing); it fits a surface the plan already
has instead of adding a new one; and its cost is small next to the pain it removes.

Left out on purpose, so later sessions don't re-add them:

- A CPU-priority selector, a "Recent locations" drawer, inline variable editing inside
  the palette, a separate DSE strategy-preset catalogue: nice, but each adds a surface
  for a pain few people raised.
- An ML "will this run fail?" predictor and warnings during a run: one post, no
  thresholds anyone has validated; revisit only with real run data.
- Utilization sliders with colour zones, design-size presets, a memory-inference
  linter: Setup and the RTL IDE are already redesigned; the knowledge base covers the
  failure when it happens.
- An embedded terminal emulator, a WebGL layout renderer, AppImage provisioning:
  either Tools (out of scope) or a rewrite of something that works.
- "List LVS before DRC" and other advice from a single comment.
- A Tiny Tapeout export wizard, power with VCD activity, timing histograms per stage:
  real asks, but after the loop works; listed under Later or not at all.

Sources are listed at the end.

---

## 2. Ten rules for the LanEx journey

1. **One context.** A project, the run you are looking at and the run you compare it with are shared by every tab. Changing the run anywhere changes it everywhere.
2. **Every object has one home and is a link everywhere else**, both ways, with a Back that returns you.
3. **Every problem carries its next action**: explain, show, fix, rerun, compare. No dead-end messages.
4. **Runs happen in the background.** LanEx announces a run and its end; it never pulls you off the page you are on.
5. **Results know when they are stale.** If you changed RTL or settings after a run, the results say so.
6. **The flow's stages are the shared vocabulary**: Synthesis, Floorplan, Power grid, Placement, Clock tree, Routing, Sign-off. Run menu, Flow view, Layout, Analytics and Verify all use them.
7. **Two levels, no tiers.** The default view answers the beginner's question. One click shows the expert's raw truth: the file, the step ID, the command.
8. **Teach where it is used.** Empty states, inline "why", glossary on terms. No tours.
9. **Every run-shaped action shows its command**, and runs started in a terminal appear in LanEx.
10. **One verdict model.** The same words and the same numbers for a run on every page.

---

## 3. Where the journey breaks today

Each tab on its own is good. These are the seams between them, found in the code on
`ui-redesign` (939ea5d). Closed in P0 (2026-10-10): S4, S5, S7, S9, S13. Closed in P1
(2026-10-11): S6, S16; S1 for runs that halt (the failure card), S3 in part (the
misleading From/To/Skip fields are gone; resuming from a stage is P2). See 8.3. Closed
in P2 (2026-10-24): S1 (every failing check has its problem and fixes), S2 (Apply
saves the setting and resumes), S3 (Resume from a stage, `-i` and `--from`). See 8.4.

| # | Seam | Evidence |
|---|---|---|
| S1 | **A failed run has no explanation anywhere.** The failure advisor and its one-click fixes render into elements that no longer exist. The backend knowledge base (`controller/alerts.py`, `/api/explain`, fixes checked against the live variable registry) is unreachable. A failure shows a toast and "see the Live Logs". | `modules/advisor.js:43` targets `#advisor-list`; `modules/timingAdvisor.js:7` targets `#timing-advisor`; neither exists in `index.html`. |
| S2 | **Fix and rerun are not connected.** Verify explains each check and what to change, as text. Applying it means going to Setup, finding the setting, running again from the top. Verify's step rerun asks for `KEY=VALUE` text. | `modules/verify-model.js` `fix:` strings; `modules/verify.js:870` `rerun()` prompt. |
| S3 | **No real "rerun from a stage".** Pipeline has free-text From/To/Skip step IDs, and a new run name. LibreLane resumes from the latest `state_out.json` of the same run directory; a new tag with `--from` starts from an empty state. | `modules/setup.js:518` `collectRunPayload()`; LibreLane `--with-initial-state` help. |
| S4 | **Pipeline claims a finished run when there is none.** After boot with no run in progress it shows "Complete: all 101 steps done. The GDS is on the Preview tab." (the Preview tab no longer exists). | `modules/runtimeline.js:102` (`done = total` when idle), `:152`; `index.html:403` also says "Preview tab". |
| S5 | **Starting a run pulls you to Pipeline** from wherever you were, including mid-edit in the RTL IDE. | `app.js:238`. |
| S6 | **The end of a run is weak.** One toast; a "next steps" card shown once per install; no notice outside the window for a 5 to 60 minute job. | `app.js:393`, `app.js:527` (`ll.postRunSeen`). |
| S7 | **Every results tab picks its own run**, and two settings decide "all designs" (`ll.runsScope` in Runs, `ll.runScope` elsewhere). Runs' "Open" jumps to Layout. | `modules/runs.js:20`, `modules/runscope.js:14`, `modules/runs.js` `openRun()`. |
| S8 | **Two verdicts disagree.** For the same run Analytics says "all 17 checks passed" and Verify says "21 passed, 1 info, 1 turned off" (23 rows). | `modules/analytics.js:359`; Verify overview. |
| S9 | **Two stage vocabularies.** Analytics: Synthesis, Floorplan, Placement, CTS, Routing, Signoff. Layout: Floorplan, Power grid, Placement, Clock tree, Routing, Final GDS. | `modules/analytics-model.js:333`; `controller/layoutview.py:68`. |
| S10 | **Stale results look current.** After you edit `spm.v` or `CLOCK_PERIOD`, Layout, Analytics and Verify show the old run with no hint. | No input fingerprint in `gui-run.json`. |
| S11 | **Step-by-step pauses after every one of ~80 steps.** The stage is the unit learners and FPGA users think in. | `controller/runner.py:713`. |
| S12 | **The command palette only knows tabs and a few actions**, though the top bar calls it "Search commands" and Shortcuts says "every command and setting". No runs, files, settings, checks or cells. | `modules/palette.js` `actions()`. |
| S13 | **Number keys don't follow the rail** (1 Setup, 2 Pipeline, 3 Runs, 4 Layout, 5 Tools, 6 Analytics, 7 Verify, 8 DSE, 9 RTL IDE, 0 Cells; Manual has none). | `modules/hotkeys.js:7`. |
| S14 | **Runs is a stack of big cards with seven buttons each** and no QoR numbers, so history can't be scanned or sorted. Compare lives in Analytics, sweeps in DSE, each with its own run list. | `modules/runs.js` `renderRuns()`; `modules/dse.js` `renderRunPicker()`. |
| S15 | **The command line is scattered**: Manual tab, Layout's Command menu, the Reproduce dialog, Verify's rerun. Logs are split between Pipeline's Live Logs and the status bar's install Logs. | `index.html` Manual section; `modules/logdrawer.js`. |
| S16 | **Two run-name fields** (Setup "Run name" and Pipeline "run tag"). | `index.html:386`, `:431`. |

---

## 4. The target journey

### 4.1 The loop, with the LanEx surface for each step

| Loop step | LanEx surface | New or changed |
|---|---|---|
| Start | Setup project hub; New project wizard; Open folder | Setup's four steps become a live **journey tracker** |
| Write | RTL IDE | (redesigned) |
| Check | RTL IDE lint, simulate, waveform | Tracker shows lint/sim state; "not checked since you edited" |
| Run | Top-bar **Run menu** (full, up to a stage, resume from a stage, this run only, mode, engine, command) | New menu; preflight blockers shown on the button |
| Watch | **Flow** view (Pipeline redesigned); status bar band; rail ring | Background by default |
| Read | **Run report card** (verdict + 4 KPIs + deltas) on Flow, Runs, Setup, toast; then Layout, Analytics, Verify | One verdict model |
| Find the problem | **Problem cards** (failed step, failing checks, metric watch, preflight) | Advisor knowledge base brought back |
| Change | **Fix sheet**: change a setting in the project config or for the next run only, or open the file at the line | New |
| Rerun | **Resume from the earliest stage that reads what you changed**, as a new run branched from the old one | New backend: variable to stage map; branch start |
| Compare | **Runs table** (QoR columns, baseline, multi-select compare) to Analytics Compare | Runs redesigned |
| Explore | **Sweeps** inside Runs (DSE merged): builder, Pareto, parallel coordinates, "use this configuration" | DSE merged |
| Ship | Runs row: Bundle, Export, Files, CLI; Layout save image | (exists) gate-level sim later |

### 4.2 Journeys to design and test against

**J1 First GDS (beginner, about 10 minutes).** Launch, Setup shows the hero and the
four steps with "1 Open a project" highlighted. New project, Blinky. The tracker
moves to "4 Run the flow". Run flow. LanEx shows Flow because the click came from
Setup's Run button. Each stage tile fills with a thumbnail of the chip at that stage
and a plain caption ("Placement: putting each gate in its spot"). Finished: the
report card says "Clean. Your chip is 57 × 68 µm and meets 100 MHz", with "See your
chip". Layout plays the flow. Verify explains each check.

**J2 My own design fails placement (beginner).** Run stops at Global placement. The
Flow view selects the failed step and shows the problem card: "Placement ran out of
room (GPL-0302): the cells don't fit at this density." Fix options: "Raise target
density 55 → 65 %" or "Use a fixed 150 × 150 µm die". Choose one, "Apply and resume
from Placement". A new run starts from the old run's floorplan state; the toast says
"Saved PL_TARGET_DENSITY_PCT = 65 in config.json (Undo)". (*As built, P2*: the error is
GPL-0301 in 3.0.4's OpenROAD, 6.1; each fix resumes where its variable is first read, so
a die or core-size fix resumes at Floorplan and a padding or density fix at Placement,
step 24; tested end to end, 8.4.)

**J3 Timing closure (intermediate).** Verify shows setup slack −0.4 ns in the tt
corner. The check row names the worst path and offers: "Relax clock to 12 ns",
"Add setup repair margin", "Show the path" (timing paths), "Open the start register
in the RTL IDE". Apply a margin; resume from Placement; Runs shows the new row next
to the old with Δ slack. (*As built, P2*: Verify's Timing section opens with the
diagnosis, where it first failed, what fails, the worst path's budget, and the fixes
with Apply; a slower clock resumes at Synthesis, step 6, since ABC reads CLOCK_PERIOD;
Runs' Δ columns are P3.)

**J4 Terminal veteran's day.** Opens a folder with `config.yaml`. Palette: "@" to
pick last night's run, "#" to find `GRT_RESIZER_HOLD_SLACK_MARGIN`. Run menu: "Resume
from Clock tree", "this run only" override, copy the command for CI. Keeps editing in
the IDE while it runs; a Windows notification says it's done. Runs table: sort by
setup slack, compare three runs. A run started in their own terminal appears in the
table with a "terminal" badge.

**J5 Stage-by-stage learning.** Run menu, mode "Pause at each stage". After
Floorplan the pause card shows the die, utilization and a snapshot: "Continue to
Power grid", "Change settings for the next stages", "Re-run Floorplan with changes",
"Open in Layout". Same at Placement and Clock tree. Analytics shows QoR by stage.

**J6 Sweep and promote (PPA).** Runs, New sweep: `PL_TARGET_DENSITY_PCT` 45 to 75
step 10 × `CLOCK_PERIOD` 8, 10: 8 runs, about 9 minutes each. The sweep appears as one
group row. Results: Pareto (area vs slack), parallel coordinates. "Use this
configuration" writes both values into the config.

**J7 Come back tomorrow.** LanEx opens on Setup. The tracker says "Last run: clean,
out of date (you changed spm.v after it)". A "Continue" chip offers "RTL IDE ·
spm.v". The rail shows 2 lint problems on RTL IDE.

**J8 Ship.** Verify clean. Runs row: Bundle (GDS, LEF, netlists, SDF, reports),
Export report, Files, the exact CLI. Later: gate-level simulation of the final
netlist with SDF in the RTL IDE.

---

## 5. The design

### 5.1 Navigation and information architecture

Rail today (11 tabs): Design: Setup, RTL IDE, Cells · Run: Pipeline, Runs, DSE ·
Results: Layout, Analytics, Verify · System: Tools, Manual.

Rail proposed (9 tabs):

| Group | Tabs | Change |
|---|---|---|
| Design | Setup · RTL IDE · Cells | Setup gets the journey tracker |
| Run | **Flow** · **Runs** | Pipeline redesigned and renamed Flow (LibreLane's own word; Vivado's Flow Navigator); DSE merged into Runs as sweeps |
| Results | Layout · Analytics · Verify | Shared run bar; cross-links |
| System | **Tools** | Unchanged here; the user reworks it in its own session (6.4). Manual becomes the **Console** drawer, open from any tab |

State on the rail (small, never decorative): RTL IDE shows the lint error count;
Flow shows a progress ring while running and a red mark when the context run
failed; Verify shows the context run's problem count; Tools shows a dot when
something a run needs is missing.

Number keys follow the rail: 1 Setup, 2 RTL IDE, 3 Cells, 4 Flow, 5 Runs, 6 Layout,
7 Analytics, 8 Verify, 9 Tools. Ctrl+` toggles the Console. Alt+← / Alt+→ go back and
forward. (As built in P0: the keys are read from the rail's order, 1–9 then 0, and each
rail tooltip names its key, so today they are 1 Setup … 6 DSE … 9 Verify, 0 Tools, and
they become the list above by themselves when DSE and Manual leave the rail.)

### 5.2 One context: `modules/context.js`

How the tools people come from do it. In the OpenROAD GUI the main window owns one
selection: every view (layout, inspector, timing report, DRC viewer, clock tree viewer)
sends its picks to `MainWindow::setSelected`, and one `selectionChanged` signal updates
them all (`src/gui/src/mainWindow.cpp`). In Vivado "selected objects are always
cross-selected in all related windows", and the Properties window shows the newest one,
with an *Automatically Update* switch to hold it still (UG893). LanEx's selection at the
level of the whole app is the run, so the run is that one selection.

- Holds the project, the run on screen and the run it is compared with (the baseline).
  `loadRuns()` loads the run list for the current scope and settles both; `setRun`,
  `setBaseline` and `setRunScope` change them; `g:context` says what changed and why
  (`run`, `baseline`, `scope`, `project`, `run-finished`, and `loaded` / `settled` after
  a load, which the page that asked ignores). `state.selectedRunTag` mirrors the run, so
  older modules (timing paths, final settings, step output) follow without changes.
- Each project remembers its run and baseline (`ll.context`, the 30 most recent
  projects); opening a project shows what it showed last time.
- Default run: the newest. Default baseline: the newest run before it that passed. A
  baseline the user picks (including "Nothing") stands until they change it or it stops
  existing. (Starring a baseline in Runs is P3.)
- A run that ends is followed when the user was on the newest run when it started (or
  on none); someone reading an older run stays on it.
- One scope preference, `ll.runScope`, for every run list including Runs (its old
  `ll.runsScope` is adopted once). "All history" in Runs is now "All designs", the same
  words as the run bar.
- No pin: Vivado's *Automatically Update* exists because a property sheet follows every
  click; LanEx's run changes only when asked. Compare and sweeps keep their own
  multi-run picks.
- Not built in P0: `focusStage` (Flow is its first reader, P1) and staleness (P3). A page
  that is not on screen does nothing on `g:context`; it reads the context when shown.

### 5.3 Shared run bar: `modules/runbar.js`

One component on Layout (run only), Analytics and Verify (run and baseline), and later
Flow. It replaces three hand-made bars with a native select each, an "All designs"
checkbox squeezed into the label row, and three copies of the run-list code.

- Each field is a button: a square verdict via (green passed, red failed, pulsing blue
  running; the word is always beside it), the run's name, "passed · today 20:08", and a
  NEWEST tag. A native select could not show any of that.
- It opens the list of runs: verdict, runtime, setup slack and when, with NEWEST,
  COMPARED WITH and PINNED tags and a tick on the current one. A filter box appears past
  seven runs. "All designs" lives inside the list (it is a choice about the list), and
  then the runs are grouped by design, the open one first. The footer links to Runs for
  notes and files. Keyboard: ↑ ↓ Home End Enter Esc, typing filters.
- The baseline list is "Nothing" plus the other runs of the same design, and says what the
  default is.
- Picking a run sets the context: every results page follows, and Runs marks the card
  "On the results pages".
- Later (P3): "Out of date: you changed `spm.v` and CLOCK_PERIOD (10 → 8 ns) after this
  run. [Run again]" under the bar, in the warn colour, only when true.

### 5.4 Links and Back: `modules/nav.js`

How the tools people come from do it. VS Code keeps one navigation stack for the whole
window (50 entries). A cursor move within 10 lines of the current entry replaces it
instead of adding one (`TEXT_EDITOR_SELECTION_THRESHOLD`), while jumps such as Go to
Definition always add; Alt+← / Alt+→ on Windows and the mouse's side buttons walk it.
The OpenROAD inspector shows *Navigate back* only after you follow a link inside it, and
picking anything unrelated clears that trail (`src/gui/src/inspector.cpp`), so Back
never takes you somewhere you did not come from. Vivado gives each window Previous/Next
for its own view (zoom, schematic) and the Properties window Previous/Next Object.

- `go(tab, params)` is the only way pages change; the 28 hand-made
  `.side-tab[data-tab=…].click()` calls are gone, and `[data-go="tab"]`
  (`data-go-section="id"`) replaces three page-local link attributes. Params address a
  place: `{ section }` on any page, `go("ide", { rel, line })`, `go("ide", { newFile })`,
  `go("cells", { cell })`, `go("verify", { check })`, `go("pipeline", { pane })`.
  Later phases add `{ stage }`, `{ step }`, `{ select }`, `{ setting }`.
- Every page change is one history entry (`#tab`), so Alt+←, Alt+→ and the mouse's side
  buttons work as in a browser. A second `go()` to the page on screen replaces its entry
  (VS Code's "nearby" rule at page level), and panels, logs, filters, sorting and layers
  never add one (Back that lands somewhere unpredictable is a named complaint about
  GitHub Actions, Duncan 2026).
- A link from another page shows "‹ Back to Verify · Timing" in the top bar, after the
  project name: the page and the section that was in view. It appears only after a
  link (the OpenROAD rule); the rail, number keys and the palette add history but no
  chip, and leaving by the rail drops it. The search box does not move when it appears
  (the top bar's side tracks are equal).
- Each page keeps its own scroll position, and Back returns to the exact place.
- Alt+← / Alt+→ are LanEx's own outside text fields; in the code editor they stay
  CodeMirror's (move by syntax), in fields the browser's.
- The palette lists the eight places visited before this one first ("Recent places",
  like JetBrains' Recent Locations), so going back is not one step at a time.

Link matrix (what each object links to; ✓ exists, + to add, later = needs backend work):

| From | To |
|---|---|
| Lint or sim message | IDE file:line ✓ |
| Waveform signal | source ✓ |
| Failed step | its log at the first error ✓ (P1), failure card ✓ (P1, halted runs), Layout at that stage ✓ (P1), OpenROAD at that step ✓ (kept .odb), the setting a fix names ✓ (P1) |
| Verify check | report ✓, step log ✓, problem card +, Layout with that check's markers + (DRC/XOR markers exist in Layout's Checks pane), setting in the fix sheet +, Analytics timing ✓ (P0) |
| Verify worst path | timing paths ✓, start/end register in the RTL IDE + (search by name), path cells in Layout later |
| Analytics metric | provenance file ✓, the stage that changed it + (`/api/run-stages`), Runs sorted by it +, Verify worst paths ✓ (P0) |
| Analytics cell usage | Cells ✓ |
| Layout probe (cell, net, pin) | Cells ✓, Find ✓, pin order file in the IDE + |
| Cells cell | used N times in the run ✓, its area in Analytics ✓ (P0), find in Layout + |
| Runs row | sets the context run ✓ (P0: a click picks it, no page jump), Layout ✓ (Open in Layout), Flow / Analytics / Verify for it +, Compare +, Load settings ✓ (Reproduce), command ✓ |
| Setting (Settings card, All settings) | which stages read it +, its value in the context run + (Settings used ✓) |
| Problem count in the status bar | Verify filtered to Problems + |

### 5.5 The run moment

**Before: the Run menu** (top bar split button, replaces the Pipeline From/To/Skip
fields and the second run-name field).

*Built in P1:* Mode and Engine as before; **Run up to** a stage (LibreLane's `--to`
at that stage's last step; "1. Synthesis (cells and area in seconds)"), and the Run
button then says "Run to Placement"; **While it runs**: Show the flow when a run
starts, Tell me when a run finishes, Play a sound (each remembered). The Pipeline bar
is gone: its run-tag field (Setup's Run name is the one name), From and Skip (From with
a new run name started from an empty state, S3; resuming from a stage is P2), and its
second Stop and Resume (the top bar's Run is Stop while a run goes; Flow has Stop and
Next step). Still to build: Resume from a stage (P2), settings for this run only and
Copy the command in the menu (P4's Console has the command; Flow's "Command" button
copies a past run's).

- Run (main button): the whole flow with the project config.
- What to run: Whole flow · Up to a stage ▸ · Only synthesis (quick area and cell
  count) · Resume ▸ from a stage, using the context run's results.
- This run only: Run name… · Settings for this run only (n) (today's All settings
  overrides).
- How: Full auto · Pause at each stage · Pause after each step (expert). Engine:
  Container · Local tools.
- Footer: Copy the command.
- If preflight has a blocker, the button carries a warn mark and opens a popover
  with the blocker and its fix link instead of starting.

**During**

- LanEx stays on the current page. Exceptions: the click came from Setup's Run flow
  button or from the Flow view, or it is the user's first run ever. A preference
  ("Show the flow when a run starts", a checkbox in the Run menu next to "Tell me when
  runs finish") covers the rest. (*Revised 2026-10-24*: the preference is on by
  default, so Run opens Flow; decision 4.)
- Status bar: progress band and "Placement · Global placement · 31/76 · ~6 min
  left". Rail: progress ring on Flow. Top bar: Run becomes Stop. (*Built*: the line is
  a link to Flow; after the run it reads "✓ clean · 1 min 52 s" or "✗ stopped at
  Global Placement · Placement ran out of room"; the ring is a met1 arc on the Flow
  icon, and a red via marks it when the last run failed.)
- The window title carries the state ("31/76 · spm · LanEx", then "✓ clean · spm" or
  "✗ stopped · spm"), so the taskbar shows it without bringing LanEx forward. (*Built*:
  "35/80 · Clock tree · wide — LanEx", then "✓ clean · wide — LanEx"; the result stays
  until the window has been in front for a few seconds.)
- No confirmation dialogs for Run, Rerun or Resume: each makes a new run and
  destroys nothing. Confirm only what deletes or overwrites. (A GitHub Actions user on
  Hacker News, 2022, after the fifth rerun confirmation: "just rerun the jobs
  already".)
- Logs stream into a virtualised view (only visible lines in the DOM) with "Open raw
  log" always one click away; a routing log is tens of thousands of lines, and web
  log viewers that render it all freeze or stop scrolling (I. Duncan, "GitHub Actions
  Is Slowly Killing Your Engineering Team", 2026).

**After**

- A toast with actions: "spm · try-2 is clean · 1 min 1 s [See chip] [Sign-off]"
  (about 10 seconds) or "try-2 stopped at Global placement [Why]" (stays until
  dismissed: a failure must not expire unseen).
- When the window is not in front, a Windows notification with the same words.
  Turned on once from the Run menu ("Tell me when a run finishes"), never asked at
  boot. **P1 prototyped both routes on this machine and kept the Web Notification**
  (decision 5 as revised):
  - *Web Notification* from the LanEx window (Edge `--app`, a throwaway profile,
    window in the background): Windows showed it at once as a toast with the LanEx mark,
    the title and the numbers, the origin on its header line. It needs no installer or
    launcher change and works the same on Linux. Its click runs the page's handler,
    which calls `window.focus()` and opens Flow; that a click brings a background window
    forward could not be confirmed by automation (Windows 11's toast is not reachable
    through UI Automation from a script) and is the one thing to check by hand.
  - *Launcher route*: a native toast under the installed LanEx's own Start-menu AppID
    (the implicit `…\LanEx\LanEx.exe`, read from `Get-StartApps`; nothing registered)
    reached Windows (it was in the notification history under "LanEx"), but no banner
    appeared in the test. Its click would launch `LanEx.exe`, whose second instance
    opens *another* app window today (`secondInstance` → `openAppWindow`), so this route
    needs launcher work (find and raise the existing window, an activator) and installer
    work (an explicit AppUserModelID) in the installer workspace, for one gain: the
    header says "LanEx" instead of the browser.
  - The cost is in the page: a denied permission has no way back from inside the window
    (the Run menu says so and points at the site settings).
- The notification carries the numbers, not just "done": "spm · try-2 clean · setup
  +0.31 ns · 57 × 68 µm · 1 min 1 s". Vivado users script exactly this (an email
  after each phase with the timing summary, called "amazing" in r/FPGA "How to enable
  pop-up notification when Vivado finishes"), and say generic completion pop-ups get
  "don't show again" clicked; some want a sound instead. So: an optional short
  chime, off by default, next to the notification switch.
- The Flow header becomes the run report card. Results tabs follow the new run.
  Setup's tracker updates. Runs gets the new row.

**Run report card** (`modules/reportcard.js`, one component, five places: Flow
header, Runs row expansion, Setup step 4, the toast (short form), Analytics
overview). "Clean" always means "passes LibreLane's sign-off checks", with a "what
clean does not cover" link (gate-level simulation, a shuttle's precheck): the first
open MPW shuttle's chips are widely reported dead from a hold problem the flow did
not flag, and users who were there say a passing flow is not a working chip
(r/FPGA "Openlane", 2022). Verdict from Verify's model; setup slack, area/die, power, wirelength
with Δ against the baseline; runtime; what changed since the baseline (settings and
files); buttons See chip, Sign-off, Metrics, Compare.

### 5.6 The fix loop

**Research (P2, 2026-10-24).** How the tools people come from take a user from a
failed or timing-failing run to the next run, read from their own documentation,
source or merged changes, and what users say (Reddit through the Arctic Shift
archive, GitHub issues), each claim checked against its source:

- *Vivado QoR suggestions* (UG906, "QoR Suggestions", "Executing Suggestions"):
  `report_qor_suggestions` writes suggestion objects; each has an `APPLICABLE_FOR`
  stage and runs when that stage runs (enabled and set to `AUTO`), so a suggestion
  generated after placement can apply in the same run if its stage comes later.
  They are saved to an `.rqs` file for later runs. The fix and the stage it applies
  at travel together: LanEx's fixes carry the first step that reads them.
- *Vivado timing methodology* (UG949, "Identifying Timing Violations Root Cause",
  "Analyzing and Resolving Timing Violations"): "analyze the worst violation of each
  clock group" first; fix clocking problems first because they affect many paths;
  before routing, review only hold violations over 0.5 ns. Its path-level chapters
  are "Datapath Delay and Logic Levels" and "Clock Skew and Uncertainty".
- *OpenROAD GUI* (gui README; `src/gui/src/drcWidget.cpp`): the timing widget shows
  "Data Path Details" and "Capture Path Details" and `gui::show_worst_path`; the DRC
  viewer loads a TritonRoute or JSON report into a tree of categories (rule types)
  with "N markers", one row per marker, select to zoom. It groups by rule only: the
  places are LanEx's addition.
- *Calibre RVE* (Siemens page): a debug viewer that cross-probes results into the
  design tools, "Whether you have 10 or 1,000,000 errors". The page says nothing
  about how it groups; a Calibre Vision AI page could not be read, so no claim about
  its clustering is used. *Innovus / Genus*: Cadence's docs need a login and its
  pages refuse automated readers; nothing here is sourced from them.
- *OpenROAD* issue #4318: a maintainer (rovinski): "Padding only impacts the way GPL
  (and DPL) sees the cells", so GPL's utilization includes `GPL_CELL_PADDING`
  (LibreLane 3.0.4 `scripts/openroad/gpl.tcl` puts half of it on each side).
- *LibreLane 3.0.4 source and docs*: `flows/cli.py` (`-i`, `initial_state_cb`
  checks every path in the state exists), `flows/sequential.py` (steps before
  `--from` are skipped and make no folder; a deferred checker failure is raised
  after the last step), `scripts/openroad/sta/corner.tcl` (the violator list keeps
  one path per endpoint, `find_timing_paths -unique_paths_to_endpoint`, its worst,
  classed in-reg / reg-reg / reg-out / in-out), `scripts/base.sdc` (input and
  output delay `CLOCK_PERIOD * IO_DELAY_CONSTRAINT / 100`, `set_load` of
  `OUTPUT_CAP_LOAD` on every output), the timing closure guide (STAPrePNR "before
  PnR", STAMidPNR during, STAPostPNR after; setup and hold repair margins), issue
  #1040 (mid-PnR STA times the default corner only; other corners carried forward).
- *Users*: "when it fails in zero wire load modelling then it can be an RTL issue"
  and "check number of logic levels" (r/chipdesign, "When does fixing timing stop
  being a PD problem?"); "first, you need to ensure your timing constraints are
  correct" and WNS/TNS explained as worst path vs. sum of all failing (r/FPGA, "How to
  Analyze Timing Reports in Vivado?"); "Are the violations clustered in one region
  or spread across the block?" and "solving one will solve the other … you just need
  to fix a few places" (r/chipdesign, "Stuck with DRC Errors"); "Try observing in
  layout where these issues arise" and, on two tools disagreeing, "either the techLEF
  … is not complete, or the Magic tool is using wrong setup" (r/chipdesign, "Fixing
  DRC errors help!").

What this changed: a fix names where the new run starts (Vivado's
`APPLICABLE_FOR`); timing leads with the worst path and its budget (UG949); DRC is
rules *and* places (the r/chipdesign answers; OpenROAD's viewer only does rules);
endpoint counts are described as LibreLane counts them (one worst path each), which
corrected a first draft that claimed "register paths passed before placement" when
the data only says no endpoint's *worst* path was register-to-register then.

**Problem** (`controller/problems.py`, the one knowledge base; `modules/problems.js`
on the page). Every source has one shape:

```
{ id, severity: fail|warn, kind: halted|check, title, plain,
  where: { stage, step, check }, evidence: [log lines], diag: { … },
  fixes: [ { kind: "setting", var, from, to, why, label, resume }
         | { kind: "open", label, go, why } ],
  notes: [sentences], learn: [glossary keys] }
```

`kind` separates "a tool stopped" (`halted`: the step raised, nothing after it ran)
from a check that failed (`check`; for a run that finished, LibreLane's deferred
errors). `resume` is the first step that reads the variable (7). Sources: the step
that raised (an OpenROAD code: GPL-0301 with padding, a fixed die or a full core;
DPL-0036; GRT-0116; PDN-0185; the container engine down; a local tool missing),
every failing or warning check from Verify's model, timing diagnosed from every
timing analysis of the run, DRC from the run's marker databases. The old
`alerts.py` and `/api/explain*` are gone; its entries that were wrong (a faster
clock for a setup problem) were dropped, the two environment phrases kept.

Rules for fixes (each checked in LibreLane 3.0.4 or a source above):

- A setting is offered only when this LibreLane knows it (the flow's own `RUN_*`
  switches included: they belong to no step).
- Hold problems never offer a slower clock (hold doesn't depend on the period); the
  hold repair margins instead. Hold before the clock tree is an estimate (ideal
  clocks) and is not used to say where hold first failed.
- Timing leads with the diagnosis: setup or hold, WNS, TNS *and* the failing
  endpoint count ("−24.61 ns over 75 endpoints, −0.33 ns each on average"), and the
  worst path's budget: launch clock, clock-to-Q, logic (levels), wires, the I/O
  delay and the required time, against the period. One sentence says what
  dominates (logic depth, wire, clock skew, the register's own delay, the I/O
  constraint), and names a high-fanout net. No "try harder" fix, ever.
- Where it first failed: each timing analysis in order, read only for the corners
  it timed (a mid-PnR column is the default corner, marked). Failing endpoints are
  split by the kind of their worst path, before placement and after routing. A
  path kind that fails before placement (ideal clocks, no wires) is the logic or
  the constraints: no placement or density setting is offered for it. When only
  register-to-register endpoints fail after routing, placement and repair settings
  are offered for those and the note says so.
- Constraints before logic: when inputs and outputs fail first, `IO_DELAY_CONSTRAINT`
  is offered (only if the run's SDC reads it), and when the worst path ends at an
  output pin, `OUTPUT_CAP_LOAD` ("lower it only to what the pin really drives").
- DRC: "34 violations = 3 rules in 3 places", per checker, the checker with the
  most first. Rules in plain words ("Metal 1 narrower than 0.14 µm") with the deck's
  name; places are markers within 4 % of the die diagonal (at least 5 µm) of each
  other, each with where on the die ("near the bottom-right corner"), its rules and
  a Show that opens Layout there with the markers on.
- When checkers disagree, say why instead of two numbers: LibreLane fails the run on
  either Magic or KLayout (`ERROR_ON_MAGIC_DRC`, `ERROR_ON_KLAYOUT_DRC`), so neither
  is the tiebreaker; KLayout DRC runs only for sky130A/B in 3.0.4; the router checks
  only its own wires; `MAGIC_DRC_USE_GDS` off means Magic checked the DEF.
- Proposed values are a starting point the sheet lets you change; nothing in the
  knowledge base computes a silicon number.

Surfaces (*built*): Flow's failure card (each fix with Apply) and, for a run whose
checks failed, the report card's "What failed" (each problem, its numbers, its
setting fixes as buttons, "Why, in Verify"); Verify's failing check rows (the
problem and its fixes in place of the old text tips) and its Timing and DRC
sections (the diagnosis panels above the corner table and the checkers); the
status bar ("1 problem in p2-pad", a link to Verify filtered to Problems). Not yet:
Setup's Ready to run, Analytics watch breaches.

**Fix sheet** (`modules/fixsheet.js`, a side sheet, one for every fix; built):

- The setting: its name and units, LibreLane's description, its value in the run
  and where that value came from (the config file and which section, "set for that
  run only", the PDK, LibreLane's default), the new value (an On/Off switch, a list
  of choices, or a field by the variable's real type), and why.
- Save it in: the project's config file (the lines that change are shown, with
  line numbers) or this run only (`-c`). The default follows where the value came
  from: a value the old run set for itself stays that way. A value set in a
  `pdk::`/`scl::` section is changed there, because a section that matches the PDK
  overrides the top level (the scratch spm sets CLOCK_PERIOD and FP_CORE_UTIL so).
- Then: Resume from <stage> (default), Run the whole flow, or Only save it. The
  resume shows as the seven stages in one bar, what is reused from the old run and
  what runs again; anything else that changed since the old run is listed and moves
  the start earlier (7).
- The command it runs (copyable): `-i runs/OLD/NN-step/state_out.json -F STEP`.
- Apply: the toast says what was saved where and that the run resumes ("Saved
  FP_CORE_UTIL = 35 in config.yaml. Resuming p2-pad from Floorplan as glui-…",
  Undo). Undo restores the file byte for byte, refuses if it was edited since, and,
  pressed in the first seconds, waits until the run has read the config ("The run
  that started keeps FP_CORE_UTIL = 35").
- Every setting change about a run should go through this sheet, including a
  setting picked in the palette (5.8, P4).

### 5.7 Staleness

At run start, record an input fingerprint in `gui-run.json`: config file hash,
overrides, PDK and library (with the PDK version), the LibreLane version or image
tag, and each source file's hash. A toolchain or PDK update then shows as a cause
like any other ("LibreLane 3.0.4 → 3.1.0"); FPGA users complain that tool updates
arrive bundled with library changes and silently change results (r/FPGA "Anyone else
feeling extremely frustrated with Xilinx?"). The run bar and the
tracker compare it with now and name what changed. A run started outside LanEx has
no fingerprint and shows nothing.

- **Content, not timestamps.** Compare hashes, using (mtime, size) only to skip
  rehashing an untouched file. Vivado decides "out of date" by timestamps; users get
  the false alarm "nearly every day", even after adding a comment (r/FPGA "Synthesis
  is out-of-date" threads, 1.4).
- **Per stage, not per run.** With the variable → stage map (7), a changed setting
  makes stale only the stages from its earliest reader onward: change FP_CORE_UTIL
  and Synthesis stays current while Floorplan onward turn amber. An RTL or PDK change
  makes everything stale. The Flow stage strip shows this, and the Run menu's default
  becomes "Resume from Floorplan": rerun only what is stale (Dagster's "materialize
  stale", ORFS's `clean_place` then `make`).
- **Say why.** The out-of-date line and a popover on an amber stage list each cause:
  "spm.v changed 10:42", "FP_CORE_UTIL 50 → 60".
- **Mark as current.** For a comment-only RTL edit, veterans need Vivado's "Force
  up-to-date": it records the new fingerprint in `gui-run.json` with a note, and the
  run shows "marked current by you".

### 5.8 Command palette: search everything

Groups, recent first, fuzzy, context-aware:

- **Actions**: Run, Stop, Resume from a stage, Run up to a stage, Check syntax,
  Simulate, Open in KLayout / OpenROAD / Magic, Copy the command, Save layout image,
  Bundle, New file, New project.
- **Go to**: tabs and their sections ("Verify › DRC", "Analytics › Timing",
  "Setup › Settings"), from the jump bars.
- **Files** (project files, to the IDE). **Runs** (sets the context run).
- **Settings**: all LibreLane variables with description and current value; Enter
  opens the fix sheet for it (5.6: save to config or this run only, and where to
  resume from); a second action shows it in Settings.
- **Checks** of the context run; **Cells** of the library; **Help** glossary terms.
- Prefixes for experts: `>` actions, `@` runs, `#` settings, `/` files.
- Empty palette: recent items and the suggested next step.

### 5.9 Console drawer (replaces the Manual tab and both log panels)

Bottom drawer, open from the status bar ("Console", replaces "Logs") or Ctrl+`. Tabs:

- **Flow log**: today's Pipeline Live Logs (filter, level, follow, copy, step markers).
- **Tool output**: today's install/viewer log drawer.
- **Command line**: the command for the next run and the recorded command of the
  context run, each with Copy; terminal runs land in Runs.
- **Journal**: every action LanEx takes that has a command or a config equivalent,
  appended as it happens: the `librelane …` line of each run, each config change as a
  one-line diff, each viewer launch. "Copy as script" gives a shell script that
  repeats the session. This is how Vivado users say they learned to script: the GUI
  prints the Tcl for every click, and `vivado.jou` keeps it (Reddit, r/FPGA "Vivado
  Project vs Non-Project Mode": "start with the GUI, end with the scripts"). LanEx
  should be the place a beginner graduates to the terminal from, not a dead end.
- **Run a command**: today's allow-listed runner.

### 5.10 Setup journey tracker

Keep the hero and the four step tiles exactly as they look now. Each tile gains a live
status line and a context button; the first unfinished step is highlighted:

1. Open a project: "spm · config.yaml · sky130A / hd" [Switch]
2. Write and simulate: "Lint 0 errors · spm_tb passed 12 min ago", or "Not checked
   since you edited spm.v" [RTL IDE]
3. Pick PDK and settings: "3 settings changed from defaults" [Settings]
4. Run the flow: "Last run clean · 1 min 1 s · out of date" [Run again] [See results]

A "Continue" chip under the tiles: "RTL IDE · spm.v (edited 10:42)" or "Verify ·
try-2".

---

## 6. The tabs that were not redesigned

### 6.1 Pipeline becomes Flow

**Research (P1, 2026-10-10).** How the tools people come from show a run, read from
their own documentation, source or merged changes:

- *Vivado* (UG906, UG904): the Design Runs window gives each run its status ("status of
  the last completed step"), progress, start time, elapsed time, WNS/TNS/WHS/THS, power,
  unrouted nets and utilisation; the project status bar (top right) shows the run in
  progress. The Messages window groups messages by tool, links each to its source, and
  filters by severity.
- *Quartus* (Pro User Guide 26.1, 8.1.1 and 8.1.5): the Compilation Dashboard is a row
  of stages; each updates its status as the compiler goes, then enables icons for its
  report, viewers and settings; a click on a stage runs it, or resumes an interrupted
  compile "provided no compilation settings have changed"; it also updates for a compile
  started from the command line. Messages: right-click a message to locate its source or
  get its help.
- *Innovus* (Cadence blog, 2020): metrics commands show PPA at each stage of the flow in
  an HTML dashboard and compare runs (the docs themselves are behind a login).
- *ORFS* (PR #4627, merged 2026-10-05): every stage ends its log with one grep-able
  line, `== ORFS 3_3_place_gp WARN … 0:07.98 290MB`, then what the stage did, the key
  numbers with deltas, the variables involved, why it warned or failed, a small
  picture, the warnings counted by code (`warn 1002 (STA-1212 x1001, GPL-0302 x1)`), and
  where to look in the GUI. The final report says where the time went and which stage
  moved each metric the wrong way most.
- *LibreLane 3.0.4* (source): the terminal shows one Rich bar, "Classic - Stage 24 -
  <step>", M/N and elapsed time, no estimate. A tool error raises at once (the run
  "halts"); checker failures are deferred and raised together after the last step, once
  `final/` is written. Errors go to `error.log`, warnings to `warning.log`, each step's
  time to `NN-step/runtime.txt`.
- *GitHub Actions* (docs, "Using workflow run logs"): failed steps open automatically,
  each step shows its duration, logs are searchable, any line has a link, and the raw
  log downloads. *Buildkite* (docs, "Managing log output"): the running group stays open
  while it runs and folds when the job moves on; the failed group opens; unimportant
  groups fold into one expander row. *GitLab*: collapsible sections with durations.
  *SiliconCompiler* dashboard: a flowgraph whose nodes are coloured by status; picking
  one shows its metrics, details and files.
- *OpenROAD GUI*: no run monitor; it is opened on a finished stage's database.

What users say. Reddit read through the Wayback Machine (Arctic Shift returned
Cloudflare 522 all session; reddit.com and its mirrors refuse automated readers or sit
behind bot checks, which LanEx research does not bypass), plus GitHub issues:

- "Failed with no errors": four r/FPGA threads (Vivado synthesis or bitstream "failed
  with no errors", one with 34 comments) end in "look in the Log, Messages or Tcl
  console" and "are you looking at the synth run log in the small window?". The reason
  for a failure must be on the first screen, not in a log the user has to find.
- "Is this normal?": "Clues when synthesis is taking forever" (log still in timing
  optimisation after hours), "Synthesis suddenly taking much longer" (usually 12 to 20
  min), "Implementation time over 30 hours: is this even normal?". People judge a run
  by their own previous runs. LibreLane issue #812 asks for every step's runtime in one
  table "to estimate how long a future run might take".
- OpenLane issue #1574, "[ERROR DPL-0036] Detailed placement failed: error is not
  actionable": the user wants why and how to fix; the maintainer answers "the simplest
  thing is to open the GUI and look at where those instances are placed". Both halves
  belong on the failure card: the plain reason, and the layout at that stage.
- Notifications: "Is there any way to get email alerts when Vivado completes?" (answers:
  a post-implementation Tcl hook that mails), the sound and pop-up threads in 1.4.

Two corrections from the source. In the OpenROAD that LibreLane 3.0.4 ships
(dcf36133, 2026-02-17), **GPL-0302 is a warning**: "Target density 0.12 is too low for
the available free area. Automatically adjusting to uniform density…", and the run goes
on (ORFS's own summary marks it WARN). Older OpenLane issues show it as an error. The
placement failure "the cells don't fit" is **GPL-0301, "Utilization 207.29 % exceeds
100 %"**. J2 and the P1 test use GPL-0301; GPL-0302 shows as a warning worth reading.

What this changed below: the reason first, in plain words, with the numbers from the log
(no "exit code 2"); each stage's time against the previous run; warnings counted by code;
minor steps folded; the running stage open and folding when done; links straight to the
stage in Layout.

The design (refined by the research above; what P1 built is marked *built*, the rest
is for later phases):

- **Run bar** (*built*): the shared one, with "Compared with". While a run goes, Flow
  shows it, and the field says so (the run's name, "running", LIVE); picking another
  run shows that one, with "Back to the live run". When a run you watched on Flow
  ends, it becomes the run on every results page (watching it is picking it);
  elsewhere context.js's follow rule decides.
- **Head: what happened, first** (*built*). Running: "Clock tree › Clock Tree
  Synthesis", step 35 of 80, about 1 min 20 s left (from the run it is compared with:
  LibreLane's own bar has no estimate), "Clock tree took 17 s last time", the elapsed
  clock, Stop (and Next step in step-by-step mode). Stopped: the failure card (below).
  Finished: the run report card (5.5). Stopped by you, or a folder that just ends:
  said so, with Run again. No run: the seven stages and Run.
- **Stage strip** (*built*): seven tiles, the same names and numbers as every page.
  Each: state, time with "was 12 s" from the compared-with run (amber when it is more
  than a quarter slower), one number from the end of the stage (cells; die size; the
  power rails; how full the core is; clock skew; wire length and route DRC; the
  verdict), and the chip at that stage from Layout's snapshots, filled in as each stage
  finishes, live. A click shows only that stage's steps.
- **Steps, never folded** (*built*, revised 2026-10-24): every step in flow order under
  its stage's heading (the heading stays at the top of the list while its steps scroll
  under it); nothing folds. While a run goes the list keeps the running step in view, as
  the old timeline did; scrolling the list by hand stops that (as in a terminal) and a
  "Now: 47 · Detailed Routing" chip brings it back. A failed step is selected (GitHub
  Actions). Resumed runs (*built*, P2): steps before the resume point greyed "reused"
  above a "Resumed here · the steps above are from try-2" line.
  *First P1 build, rejected by the user:* stages as folding boxes, the running one
  opening and closing as the flow moved, bookkeeping steps folded into "n checks and
  small steps" rows (Buildkite's de-emphasised groups). The user could no longer watch
  the flow go step by step, which was what the old Pipeline did well.
- **One screen** (*built*, 2026-10-24): maximised, Flow is one screen at 1366 × 768,
  1080p and 1440p while a run goes. The steps and the output are two panes of one
  height that take the height the run bar, the head and the strip leave, each
  scrolling inside itself (Vivado docks its Log window at the bottom of the IDE and
  shows a tree of runs beside the selected run's log, UG893 "Using the Log Window";
  Quartus docks Tasks and Messages, its Help "About the Tasks Window"). A short window
  shrinks the head and the stage pictures first; below 300 px (240 on a short window)
  for the panes the page scrolls. The page updates in place (rows, tiles, the head's
  text), so Stop never moves under the pointer and nothing jumps while steps race by.
- **Output pane** (*built*, 2026-10-24): while a run goes, the whole run's output as
  LibreLane prints it, one continuous log (the old "Live Logs", now virtualised), with
  LibreLane's own step rules marked; after the run the same lines stay ("Run output");
  an older run shows `flow.log`. Picking a step shows its log, About this step and its
  Reports, with "‹ Live output" back. Where the time went is a tab of the run's output.
- **Step inspector** (*built*): LibreLane's own title and docstring for the step; its
  state, stage, step number, time against last time, peak memory; "What it changed"
  (the metrics this step moved); "Settings it reads", its own stage's first (PL_ and
  FP_ for global placement, not the alphabet), each a link to that setting in Setup;
  the log in a virtualised viewer (only the visible lines in the DOM, so a 50 000-line
  routing log scrolls), errors and warnings marked and counted with next-buttons,
  "Problems" to keep only those, a filter, Follow while it runs, Copy, Raw log; the
  step's reports. Actions: Show in Layout (that stage's or step's picture), Open in
  OpenROAD (the step's .odb), copy the step ID. Later: Rerun from here (P2),
  `--reproducible`. With no step picked on a finished run: where the time went (the
  slowest steps, as ORFS ends its report).
- **Failure card** (*built*, halted runs; 5.6 for the full problem model): the stage
  and step, a plain title ("Placement ran out of room"), what happened with the log's
  own numbers ("The cells need 207 % of the core area… The die is fixed by DIE_AREA
  (0 0 60 60 µm)"), the error line with its code, then "What to change": each fix a
  variable, its value in this run, the value to try and why, with "Change in Settings"
  (opens All settings at that variable). Then "Show it in the log" (the inspector opens
  at the first error line) and "Layout at Power grid" (the last picture before it
  stopped: the maintainer's advice in OpenLane #1574). *P2*: each fix has Apply (the
  fix sheet, 5.6) and says where the new run resumes; "Change in Settings" moved into
  the sheet.
- **Checks failed after the last step** (*built*): the report card, in red: "The
  layout is done, but 2 checks failed", with Show the problems (Verify).
- **Numbers say where they came from** (*built* in the report card: every value keeps
  its exact figure in its tooltip; *later* for estimates): LibreLane carries metrics
  forward from step to step, and per-corner timing from pre-placement STA survives
  unmarked into later states (LibreLane issue #1040, open). A run that stopped before
  post-route STA must show "estimate (before routing)", not a sign-off number.
- **Pause card** (P6): in Pause-at-each-stage mode, the stage's numbers and snapshot;
  Continue · Change settings for the next stages · Re-run this stage · Open in Layout.
- **Warnings counted by code** (*built*, the report card): "32 warnings: STA-1140 ×18,
  DRT-0349 ×10…", codes not in the compared-with run marked NEW and first, the ones
  worth a sentence explained (GPL-0302: "PL_TARGET_DENSITY_PCT asked for 12 %, below
  what this design can reach, so OpenROAD used 53 % instead"). Per message text (not
  per code) stays for later:
- **New warnings first (later).** A run has hundreds of warnings and the one that matters
  hides among them (a recurring r/FPGA and r/chipdesign complaint). The step
  inspector and the report card show "4 new warnings since the baseline" (warning
  text with numbers and names normalised, compared with the baseline run's
  `warning.log`), with the full list one click away.
- **Following a terminal run (later).** Veterans start runs from their own terminal or CI
  and open a GUI only to inspect. When a run folder that LanEx did not start is
  growing, Flow can follow it from the files LibreLane writes (step folders appear,
  `state_out.json` lands as each step ends), read-only, labelled "started in a
  terminal".

Precedent: ORFS merged "end every stage log with a short summary" (PR #4627,
2026-10-05): each stage ends with a few lines and a small picture of the design, which
is what the stage tiles do.

Backend: a stage map shared by `analytics-model.js` and `layoutview.py`
(`flowstages.js` + a Python twin); step descriptions; "pause at stage boundary" in
`runner.py` alongside the per-step pause. Container step-by-step today starts one
container per step (`--only`, same run tag, `_run_container_stepwise`), about 80
starts; pausing per stage is one `--from first --to last` invocation per stage, 7
starts, on the same run tag.

### 6.2 Runs and DSE become Runs

- Toolbar: search, status, PDK, ☐ All designs, Compare (n), New sweep, Import.
- **Table**, sortable: ☐ · ★ (baseline) · Run · When · Verdict · Setup slack · Hold
  slack · Die / utilization · Std-cell area · Power · Wirelength · Problems (DRC, LVS,
  antenna) · Runtime · Changed vs baseline · Note. Badges: baseline, terminal,
  imported.
- Clicking a row sets the context run (no page jump). Expanding a row shows the
  report card and the actions: Flow, Layout, Analytics, Verify, Load settings
  (Reproduce), Rerun ▾, Bundle, Export, Files, Delete.
- Multi-select, Compare: opens Analytics › Compare with those runs.
- **Sweeps** are parent rows: "Sweep: PL_TARGET_DENSITY_PCT 45 to 75 × CLOCK_PERIOD 8,
  10 · 8 runs · best …". Results: table, Pareto with chosen axes, parallel
  coordinates for more than two variables. "Use this configuration" writes the values
  into the config.
- **Stop when one is good enough.** A sweep can stop the remaining runs as soon as
  one meets a goal (timing met and sign-off clean). FPGA teams describe building
  exactly this themselves: launch many implementation variants, keep the first that
  closes timing.
- **Parallel runs are capped by memory**, not by the user's optimism: the default is
  what the WSL memory limit allows for this design's past peak, shown as "2 at a
  time (WSL has 16 GB)". Practitioners warn that RAM and memory bandwidth run out
  long before 100 parallel runs, and that a sweep is no substitute for reading why
  timing failed (r/FPGA "run various … strategy parallelly", top answers), so a
  sweep started from a timing problem keeps that problem's diagnosis on screen.
- **New sweep** side sheet: variables from the full registry (search, with the
  Settings card's hints, defaults and current values); values as a list or a range;
  grid or paired; run count and a time estimate from past runtimes. Preset: LibreLane's
  built-in SynthesisExploration flow ("find the best synthesis strategy", synthesis
  only).

Backend: `/api/runs` rows gain the summary QoR columns (from `metrics.json`; no new
numbers computed); a terminal-run flag (no `gui-run.json`).

### 6.3 Manual becomes the Console drawer (5.9)

### 6.4 Tools: out of this plan

The user will rework Tools in a separate session (decided 2026-10-06). Tools is the
component manager: shell-only installs get the engine, the LibreLane image, PDKs,
helpers and viewers there, and it works today. This plan does not redesign it.

The only contract the plan needs from Tools, so the rest of the app can point at it:

- Each Tools card keeps a stable id, so `go("tools", { item })` from preflight, the
  Run menu's blocker link and Setup's step 1 scrolls to the right card and highlights
  it. Today's ids (`runtime-card`, `recommended-tools`, `local-tools-card`, `tools-pdk`,
  `desktop-viewers`) are enough to start.
- `/api/tools` (`check_tools`) stays the one readiness source. The rail dot on Tools
  and the Run menu blocker read it; they don't change the page.
- Install logs join the Console drawer's Tool output tab (5.9), which is the existing
  `logdrawer.js` moved, not a change to Tools.

### 6.5 Others

- **Help sheet**: keep; each page's guide gains the journey ("before this page / after
  this page"). Pipeline's guide must be rewritten for Flow.
- **Landing page** (`/landing`): the launcher skips it; keep it as the README/site
  page, out of the daily journey.

---

## 7. Backend additions

| Need | Where | Notes |
|---|---|---|
| Variable → steps → earliest stage (*built*, P2) | `controller/varstage.py`, `introspect.flow_steps / flow_gating / flow_common_names` | Step-specific variables: each step class's own `config_vars` in Classic order (checked on 3.0.4: FP_CORE_UTIL → 13 OpenROAD.Floorplan; PL_TARGET_DENSITY_PCT and GPL_CELL_PADDING → 24 GlobalPlacementSkipIO; PL_RESIZER_SETUP_SLACK_MARGIN → 37 ResizerTimingPostCTS; GRT_RESIZER_HOLD_SLACK_MARGIN → 45 ResizerTimingPostGRT). Flow-common variables (`librelane.config.flow`) are read by many steps without being declared, so a curated table, each checked in 3.0.4's scripts: CLOCK_PERIOD, MAX_FANOUT_CONSTRAINT, MAX_TRANSITION_CONSTRAINT (ABC, `pyosys/construct_abc_script.py`), OUTPUT_CAP_LOAD, SYNTH_DRIVING_CELL (`pyosys/synthesize.py`) → 6 Yosys.Synthesis; IO_DELAY_CONSTRAINT, CLOCK_UNCERTAINTY/TRANSITION/TIME_DERATING/MAX_CAPACITANCE, CLOCK_PORT, CLOCK_NET, RT_MIN/MAX_LAYER → the first step handed the SDC (10 CheckSDCFiles); DIE_AREA → Floorplan. `RUN_*` switches → the step they gate (`gating_config_vars`). Anything else common or PDK-level → the whole flow. Never `get_all_config_variables()`: it adds every flow-common variable to every step. `/api/variables` gains each variable's `kind` (bool, int, number, numbers, choice, list, path, text) from the real type |
| Step → stage map | `flowstages.js` + `flowstages.py` (P0) | Seven stages |
| Branch a new run from a step of an old run (*built*, P2) | `controller/branch.py` (plan), `runner.py`, `container_run.py` and `manualcmd.py` (`-i`), routes `/api/fix/plan`, `/api/fix/apply`, `/api/run/start` with `branch_from: {tag, step}` | `--run-tag NEW -i runs/OLD/NN-<step before>/state_out.json -F STEP` (local mode loads the state with `State.load(validate_path=True)`, as `-i` does). The state is the newest saved one before the start in the run's lineage (a resumed run's parent's folders count). The new run keeps the old run's PDK, library, flow, sources and its "this run only" settings, minus the changed ones. The start is the earliest reader of: the changes; any config setting whose value is not the one the old run used (read from the config for this PDK and library, against `resolved.json`); any project file the old run read that changed after the first reused step ran. It is never later than where the old run stopped (a checker that failed the run at the end is not a stop). A state whose files are gone is refused. Steps are found by flow.log, else by folder name. `gui-run.json` records `branched_from: {tag, step, stage, state, changes}` (written at the first step, so a live run shows it). Deleting a run others were resumed from asks first (`/api/run-delete` 409 with the runs, then `force`) |
| Config edits for the fix sheet (*built*, P2) | `configedit.set_keys(scope=…)`, `diff_lines`, `undo`, `/api/config/undo` | Keys inside a `pdk::`/`scl::` section edited line by line (only that section's own entries, not a nested section's); numeric lists written `[0, 0, 125, 125]`; the changed lines returned; backup and Undo byte for byte (CRLF kept); Undo refused when the file changed since, and until a run that just started has written `resolved.json` |
| Problems (*built*, P2) | `controller/problems.py`, `/api/problems?tag=` | The one knowledge base (5.6): the step that raised, every failing or warning check, timing (`timing.sta_history`, `path_budget`, `worst_setup_path`), DRC (`drc_groups`, `checker_note`). Remembered until the run's folder changes |
| Resumed runs in the results | `history.lineage_steps`, `branch_of`; `run_stages` rows gain `from`; Verify's `_Run` | A resumed run's earlier steps are its parent's (lint, synthesis checks, the early timing analyses) |
| Pause at stage boundaries | `runner.py` | P6 |
| Input fingerprint and `/api/run-staleness` | `runner.py` writes it to `gui-run.json`; `history.py` compares | P3. Branch planning already compares settings and file times with the run it resumes |
| Runs table columns | `history.py`, `/api/runs` | P3 |
| Terminal-run flag | `history.py` | Run dir without `gui-run.json` |
| Step description | `introspect.py` | LibreLane step `long_name` and docstring (P1) |

Core flow logic and metric parsing stay as they are (PRODUCT.md).

---

## 8. Plan: one session per phase

Each phase is independent enough to ship and show the user. Each starts with targeted
research (commercial, open-source and users' own words for that surface), keeps the
look of the redesigned tabs and the MASK ROOM palette, tests on a private server and
scratch projects (see memory notes; never the user's own server on 8765), and ends
with before/after screenshots.

| Phase | Scope | Done when |
|---|---|---|
| **W Wide screens** (first) | The user's 27-inch 4K test (8.1): shared width rules, then each page's fixes from that list, the two Layout 3D fixes, and screenshots at three widths from now on | Every tab at 1366, 1920 and 2560 CSS px: no label more than a short glance from its value, no box that is mostly empty, no feature that is only a bare icon; 3D keeps its camera across stages |
| **P0 Glue** | `context.js`, `nav.js` (go, history, Back chip, only `go()` pushes history, editor keeps its own Alt+←), `flowstages.js` + Python twin, `runbar.js` in Analytics/Verify/Layout, one scope key, number keys in rail order, Pipeline idle fix and the two "Preview tab" strings, no auto-switch on run start (5.5 rule) | Changing the run in one results tab changes it in all; Back returns from every cross-link and never stops on a panel toggle; boot with no run shows an honest Pipeline; frontend tests + pytest pass |
| **P1 Flow** | Pipeline → Flow (6.1): stage strip, grouped steps, step inspector, virtualised log with "Open raw log", failure card from `/api/explain` (halted vs checks-failed), run report card (with what "clean" covers), toast, window-title state, launcher notification with the numbers (prototype Web Notification as well, keep the better) | A forced GPL-0302 run shows the reason and fixes; a clean run shows the report card in Flow, the toast, the title, and (window in background) a notification that says the verdict and numbers and brings LanEx back when clicked |
| **P2 Fix loop** (built 2026-10-24, 8.4) | Problem model, fix sheet through `configedit` (diff, Undo), variable → stage map (step `config_vars` + curated flow-common table + gating vars), branch-from-step runs (`-i` in `container_run.py`, `branched_from`), timing diagnosis (where it first failed, I/O constraint first, WNS/TNS with endpoint count), DRC grouping by rule and place, checker-disagreement note, status-bar count | From a failed placement: Apply and resume from Placement makes a new run that starts at Placement and finishes; the config holds the new value with a one-line diff; Undo restores it; a run failing setup before placement says "logic depth" and offers no density fix |
| **Ship line** | Installer hardening, then a public beta. P3 onward is shaped by what beta users actually hit, not built ahead of them | A stranger installs it on a clean PC and gets a GDS |
| **P3 Runs** | Runs table, baseline, compare, sweeps (DSE merged) with memory cap and "stop when one is good enough", promote configuration, staleness per stage (content hashes, toolchain and PDK versions, "why" popover, "mark as current"), notes | Sort by slack; compare 3 runs; an 8-run sweep shows as one group with a Pareto and stops early when asked; "Use this configuration" edits the config; editing FP_CORE_UTIL marks Floorplan onward stale and offers "Resume from Floorplan"; a comment-only edit can be marked current |
| **P4 Palette and Console** | Search everything (5.8) with Recent places and settings that open the fix sheet, Console drawer (5.9) with the Journal and "Copy as script", Manual tab removed, logs merged | Every row type reachable from the palette; Ctrl+` opens Console from any tab; the Journal of a session replayed as a script reproduces its runs |
| **P5 Setup tracker** | Live tracker, Continue chip, rail badges | J7 works end to end |
| **P6 Learning mode** | Pause at each stage (one `--from/--to` invocation per stage in container mode), pause card, plain stage captions | J5 works end to end |
| **Later** | New warnings since the baseline; following a run started in a terminal (read-only, from its run folder); timing path → highlight cells in Layout and the path as a delay breakdown; gate-level simulation with SDF in the IDE; "open a terminal in this project" from the Console; share-a-picture of the chip; Tiny Tapeout export | |

### Session prompt (paste into a new session, change the phase)

> Read `docs/workflow-spec.md`, `PRODUCT.md`, `UI-HANDOFF.md` and the memory notes.
> Implement phase **P1 (Flow)** of the workflow spec. First research how Vivado,
> Quartus, Innovus, the OpenROAD GUI, GitHub Actions and LibreLane/ORFS terminal users
> watch and debug a running flow, and what users say they need (read real Reddit
> threads through the Arctic Shift archive as described in the memory note on Reddit
> research; check every claim against a primary source), and refine section 6.1 with
> what you find. Keep the MASK ROOM look and the redesigned tabs' visuals.
> Test on a private server with scratch projects, show me before/after screenshots
> at 1366, 1920 and 2560 px wide, and don't commit until I've seen it. This phase
> must remove at least as much as it adds: no new panels where an existing one can
> carry it; the beginner sees the answer first, expert detail is one click away.

### 8.1 The user's 27-inch test (2026-10-07)

Every redesign pass was screenshotted at one laptop-sized viewport. On a 27-inch 4K
monitor the CSS viewport is about 2500 px, so full-width cards stretch about 1.7×:
labels sit on the left with their values or buttons at the far right, and fixed-height
boxes are mostly empty. Text is about the same physical size; the eye travel is what
breaks. The fix is shared, not per page:

- **Width rules (shared CSS).** Lists and tables (Verify checks, All metrics,
  Compare, Sources) get a reading width of about 1100–1200 px, with values and
  actions next to their labels. Extra width goes to a second column (the selected
  item's detail beside the list, master–detail), not to wider rows. Card grids use
  `repeat(auto-fill, minmax(…))` so wide screens add columns instead of stretching.
  Cards size to their content.
- **Default zoom on big viewports.** `zoom.js` already scales the UI. When the user
  has never picked a zoom and the viewport is very wide, start at 110–125%. Until
  then the top-bar zoom (+) is the workaround.
- **Setup.** Sources rows: Edit beside the file name, one line of help instead of
  three. Settings: keep it visible (it is the most-used block), but trim the help to
  one line per field with the rest on hover or focus, so the four columns stop
  being tall boxes.
- **Cells.** "What it does": truth table beside the gate diagram, not under it.
  "In this design's flow" shrinks to its content or joins the Layout card. The cell
  Layout card uses its space (bigger drawing, legend beside it).
- **Layout.** The 3D control becomes a labelled `2D | 3D` switch, not one icon among
  eight. Height and Spread move next to the 3D badge where they are seen.
  **Bug:** switching stages resets the 3D camera; `Layout3D.load()` calls
  `reset(false)` on every mesh (`modules/layout3d.js`); reset only on first load or
  when the die extent changes. The stage strip (`.lx-stages > li { flex: 0 0 auto }`)
  leaves a gap before "Play the flow" on wide screens; let the tiles share the width.
- **Verify.** Check name and its result sit together; the selected check's detail
  opens beside the list on wide screens.
- **Analytics.** All metrics: value column beside the name. Compare ("Pick runs to
  compare") was never reworked; it moves into Runs in P3, so W only fixes its width.
  Charts get the same treatment when their tab is next touched, not now.

**As built (2026-10-07, committed 2026-10-10: a95f019, 3442745, 76a7ed4).** Review page:
https://claude.ai/artifact/Py8kNeESeVvvGYrWKq6oyU. Where it differs from the list above:

- **Automatic size** (`modules/zoom.js`): from the *screen*, not the window, so text
  keeps its size as the window moves: `min(screen/2048×1152, window/1536×900, 1.5)`,
  floored to 5 %. A 2560×1440 screen opens at 125 %. The floor keeps the zoomed layout
  at 1536 px or more, above every width breakpoint (all ≤ 1500 px), because media
  queries see the real window. A size the user picks is kept; clicking the readout goes
  back to automatic. New UI should use container queries rather than media queries.
- **Zoom correctness** (it was broken for any manual zoom too): Layout's 2D and 3D
  canvases size from `clientWidth` and add the zoom to their backing store; pointer
  maths divides client px by the zoom; `jumpnav.js` scroll targets and scroll-spy are
  zoom-aware; seven `vh`/`dvh`/`vw` uses gained `/ var(--ll-zoom, 1)`, and the frontend
  test now checks every app stylesheet for `[dsl]?v[wh]|vmin|vmax`.
- **Verify**: the stage groups sit two by two on a wide page (container ≥ 1480 px)
  instead of master–detail; detail still opens inline. All 23 checks fit about one
  screen, which mattered more than a detail pane.
- **Settings**: a property sheet laid out by container queries per group (label |
  control | when to change; the line under the control when narrower; stacked when
  narrow). Kept open.
- **Compare**: restyled beyond the width fix (run chips, content-width tables, summary,
  key configuration and differences side by side, filter on the Metrics heading); the
  real redesign is still P3.
- **Runs and DSE**: capped at 1320 px only.
- Not touched: Tools (the user's own session), Pipeline (P1), Manual (P4).
- **Round 2 (user's notes on round 1):** Runs and DSE caps removed (boxes reach the
  edge); Settings is a folded `<details>` "Common settings" with a MOST USED bar that
  lists what is set (open state remembered in `ll.commonSettings`), every control in
  a fixed `box | unit | reset` grid, the blue set-line replaced by a SET tag; Verify
  stage pairs are one height with rows spread evenly, the odd last stage spans the
  row; every ECharts bar chart goes through `modules/barchart.js` (histogram on a real
  value axis, run bars horizontal with values at the tip, `--chart-1..5` tokens
  validated for colour-blind separation in both themes); Cells: the library picker
  and tiles sit under the Library heading; "What it does" centres the formulas, puts
  a ≤ 8-row truth table beside the drawing and folds longer ones, and the gate
  drawing no longer counts an inverted gate as an extra column. Committed 2026-10-10
  (a95f019, 3442745, 76a7ed4).

### 8.2 P0 as built (2026-10-10, committed 2026-10-11: f8e5f8a, ea31314, 27ab2a7, ebec4e8)

Review page: https://claude.ai/artifact/X6cEwtwQiQHB5L3wDqR3uq. What 5.2–5.4 now
describe, plus:

- **Stages** (`modules/flowstages.js`, twin `controller/flowstages.py`,
  `tests/test_flowstages.py` keeps them equal and checks that a real Classic run walks
  the seven stages in order). Analytics groups steps by them (CTS → Clock tree,
  Signoff → Sign-off, Power grid new); Layout's snapshots take their names, blurbs and
  numbers from them (Floorplan is 02 everywhere, because Synthesis is 01).
- **Pipeline, honest** (S4): "Complete" only after a run that finished cleanly in this
  session; with none, "No run since LanEx opened", the run the results pages show, and
  the seven stages with what each does (instead of a list of every step LibreLane
  knows, in no flow order). A stopped run says so. The two "Preview tab" strings are
  gone.
- **A run never pulls you off your page** (S5, decision 4): only Setup's Run flow and the
  very first run open Pipeline. Otherwise a toast says it started, with "Watch it"; the
  status bar shows progress. The `r` key is the top bar's Run (it used to press Setup's
  button). Verify's step rerun stays on Verify too. The "flow completed" toast gains
  "See chip".
- **Cells** counts the cells of the run on the results pages ("Used by run · tuned"),
  not always the newest run.
- **Runs**: a click on a card picks the run for the results pages (no jump to Layout);
  the card says "On the results pages"; "Open" is "Open in Layout". Fixed on the way:
  the Pinned filter shared the scope buttons' class, so a click on it reset the scope
  and every render cleared its highlight.
- Removed: `runscope.js` (into `context.js`), each page's own run list, baseline logic,
  scope checkbox and link handler, the per-tab click listeners in `app.js` (one render
  table now), the hard-coded number-key map.

### 8.3 P1 as built (2026-10-11, revised 2026-10-24, committed 2026-10-24: 165efbd, c801931, af5ab1f, 185020c)

Review page: https://claude.ai/artifact/5t7Phk22a7cTAYF13My3YA. The research is at the
top of 6.1, the design (marked *built*) below it, the run moment in 5.5. Beyond that:

- **Modules.** New: `modules/flow.js` (the page), `modules/logview.js` (virtualised log
  viewer), `modules/reportcard.js` (report card and the one-line summary the toast,
  title and notification share), `modules/runend.js` (title, status line, rail ring,
  end-of-run toast, Web Notification, chime), `flow.css`,
  `controller/runexplain.py` + `/api/run-explain` (outcome, plain reason, fixes from
  `resolved.json`, first error line, warnings by code with "new" against a run).
  `logs.js` is now a store of the live run's lines by step (no DOM). The runner notes
  how a run ended in `gui-run.json` (`outcome`), so a run you stopped reads as stopped.
- **Removed:** `runtimeline.js`, `stepoutput.js`, the dead `advisor.js`,
  `timingAdvisor.js` and `violations.js` (S1: they drew into elements that no longer
  exist), the Pipeline bar, the Live Logs / Step Output console, the one-time "next
  steps" card, about 280 lines of their CSS. Tool and install messages go to the Logs
  panel. In existing files 1 469 lines were removed and the new modules and tests add
  the rest (2 543 in all).
- **One verdict, honestly worded.** Verify's verdict copy moved to
  `verify-model.js` (`verdictCopy`) and is shared. A run LibreLane passes while a check
  only warns (setup outside `TIMING_VIOLATION_CORNERS`) reads "Clean, with 1 warning"
  in amber, naming the gate, on Verify too; "Tape-out ready" is gone from the UI (the
  Python export still says it; its test was already failing).
- **Stages:** `Yosys.EQY` moved from Synthesis to Sign-off in both tables: Classic runs
  it after LVS.
- **Links:** `[data-go]` takes any `data-go-<param>`; new targets
  `go("pipeline", { step | stage })`, `go("layout", { source })` (layout.js
  `revealSource`), `go("setup", { setting })` (config.js `revealSetting`, held in view
  like a section).
- **Fixed:** the run list right after a run could miss the run that just ended
  (context.js `waitForRun`); Reproduce crashed on runs whose command is stored per
  engine; a failed run counted its skipped tail as done; the status bar kept "step 27/80"
  after a failure.
- **Tests:** frontend 79/79 (log line kinds, the summary line, the shared verdict
  including the warning case, nothing of the old Pipeline left); Python 951 passed, the
  same 9 failures as before W; `tests/test_runexplain.py` (6) and a new stage test.
- **Not built in P1:** a terminal run followed live; resume from a stage and Apply
  (P2); the pause card (P6); timing values labelled "estimate" before post-route STA;
  the launcher notification route (5.5).

**P1 revised (2026-10-24, after the user's review).** The user rejected the lower half
of the first Flow: steps in folding boxes, a log beside them taller than the list and
jittering while routing raced by, the page scrolling when maximised, and a run start
that no longer showed the run. The head, the strip and the research stayed. Changed:

- The steps are one list that never folds, following the running step; the output is a
  pane of the same height beside it; maximised, the page is one screen (6.1).
- Pressing Run opens Flow again (decision 4 revised: "Show the flow when a run starts"
  is on unless turned off in the Run menu).
- Live correctness: a step whose folder has its runtime is done whatever the events
  said, and a "running" step behind a newer one is done (the runner's events can come
  late or out of order, which left a finished step "running" and the head naming it);
  between steps the head names the next one; after the last step it says "Finishing
  the run…" until the run ends (about 8 s on spm).
- The failure and report cards put their parts side by side on a wide page; warnings
  sit on one line.
- Known: in container mode LibreLane's console wraps at 80 columns (the container gets
  no COLUMNS), so the live output wraps long lines; a picked step's own log does not.

### 8.4 P2 as built (2026-10-24, committed 2026-10-24: 45b34e1)

Review page: https://claude.ai/artifact/5SBAzLecnePjNJaLYEog3N. The research and the
design are 5.6; the backend is 7. Beyond that:

- **Modules.** New: `controller/problems.py` (the one knowledge base),
  `controller/varstage.py` (variable → first step), `controller/branch.py` (a resume:
  plan, inheritance, what changed since), `modules/problems.js` (the problems of a
  run, fix rows and chips, the status-bar count), `modules/fixsheet.js`,
  `modules/verify-diag.js` (Verify's timing and DRC panels), `fix.css`,
  `tests/test_fixloop.py`. Changed: `runner.py`, `container_run.py`, `manualcmd.py`
  (`-i`); `configedit.py` (sections, diff, byte-exact Undo); `history.py`
  (`lineage_steps`, `branch_of`); `verify.py` and `runexplain.py` (a resumed run's
  earlier steps; the knowledge base); `timing.py` (`sta_history`, `path_budget`,
  `worst_setup_path`); `introspect.py` (flow steps, gating, common names, `kind`,
  the flow's `RUN_*` switches as known variables).
- **Removed:** `controller/alerts.py` (441 lines) and its test, `/api/explain`,
  `/api/explain-checker`, `AdvisoryCard`, the explain calls in `api.js`, the old
  `.fl-fix` styles (one fix style now, `.px-fix`), Flow's "Change in Settings"
  (the sheet links to Settings). In all, 35 files, +4 170 / −860 lines, most of
  it new function (the plan, the sheet, the two diagnosis panels) and tests.
- **Flow.** The failure card's fixes have Apply; a run whose checks failed shows
  "What failed" with its setting fixes as buttons; a resumed run says "Resumed from
  p2-pad at Placement · GPL_CELL_PADDING 12 → 0 (this run only)" (live and after),
  its reused stages say "from p2-pad" with the parent's pictures, its reused steps
  are greyed "reused" above a "Resumed here" line, and its run time counts only its
  own steps. **Run menu:** "Resume from" lists the stages of the run on the results
  pages that it can resume from (off past where it stopped); the Run button says
  "Resume from Clock tree"; picking another run disarms it. **Layout:**
  `go("layout", { box })` opens the final GDS with the markers, zoomed to the box,
  Checks pane open.
- **Real runs on the private server** (`.claude/serve-wide.sh`, scratch spm):
  - Forced GPL-0301 through cell padding (`GPL_CELL_PADDING=12` for that run only):
    stopped at Global Placement, "Utilization 103.276 % exceeds 100%". Apply "Stop
    padding the cells" (12 → 0, this run only) from the failure card: a new run
    resumed from Placement, step 24, reusing steps 1–23 of p2-pad, finished
    **Clean** in 1 min 5 s (the whole flow takes about 1 min 40 s here).
  - "Make the core bigger" on the same run, saved to `config.yaml`: the sheet showed
    the one-line diff in the `pdk::sky130*` section (line 23, 45 → 35); the run
    resumed from Floorplan and finished Clean. Undo from the toast (pressed at once,
    waited for the run to read the config) put the file back byte for byte.
  - Tight clock (`CLOCK_PERIOD=0.8`, and 1.5, all corners gating): I/O paths fail
    from before placement (129 endpoints at −2.03 ns), register paths only after
    routing; fixes slower clock, `IO_DELAY_CONSTRAINT`, `OUTPUT_CAP_LOAD`, then
    timing-driven placement and post-route repair for the register paths; **no
    density or core-size fix**. Hold (−0.48 ns): the hold margin, never the clock.
    spm has one level of logic, so its register paths never fail before placement;
    that case ("too much logic for this clock", only the clock and synthesis
    strategy offered) is a unit test.
  - Planted DRC (`p2-drc`, copied from `tuned` with markers and counts planted):
    "34 violations = 3 rules in 3 places" (Magic; KLayout 12 in 2), the die map,
    the checker note, Show → Layout at the cluster.
- **Found and fixed while testing:** CLOCK_PERIOD in the `pdk::sky130*` section
  collided with the nested `scl::` section's own CLOCK_PERIOD; a deferred checker
  at the end read as where the run stopped; values were written as strings
  (`IO_DELAY_CONSTRAINT: "10"`) because the variable types were display strings
  (now `kind`); Undo turned a CRLF config into LF; Undo pressed in the first seconds
  was refused and lost; the status-bar count's `display` beat `hidden`; a "Resume
  from" pick survived a change of run; the DRC title led with the smaller checker;
  "register paths passed before placement" overclaimed what LibreLane's violator
  list says (one worst path per endpoint), and "the register drives the pin
  directly" was wrong (an output buffer sits between).
- **Tests:** frontend 83/83; `test_fixloop.py` 36 cases (the variable map against
  the installed LibreLane, planning on run folders shaped like 3.0.4's, config
  edits, both commands, the knowledge base, the path budget on a real report
  block); Python suite 983 passed with the same 9 environment failures as HEAD
  (identical list). `scripts/ci/test_summary.py` has a row for `test_fixloop`
  in place of `test_alerts`.
- **Not built in P2:** problems on Setup's Ready to run and from Analytics watch
  breaches; Layout lineage (a resumed run's Layout shows its own stages; Flow shows
  the reused stages' pictures from the parent); the palette opening the sheet (P4);
  per-stage staleness (P3; the plan already compares settings and file times with
  the run it resumes).

---

## 9. Decisions (settled 2026-10-06: the user accepted all six)

1. **Pipeline is renamed Flow.** Keep the internal `data-tab="pipeline"` id and
   `sec-pipeline` so hotkeys, tests and stored `ll.tab` values don't churn; change the
   label, help text and copy.
2. **DSE merges into Runs as sweeps.** The DSE API (`/api/dse/*`) stays; the sweep
   builder needs a real side sheet, not a cramped inline form.
3. **Manual becomes the Console drawer.** The allow-listed runner keeps its rules.
   Check the drawer at 1280 px: resizable, never covering the Run controls.
4. **A run start keeps you on the current page**, except from Setup's Run flow button,
   the Flow view, or the first run ever. The status bar and toast must make "it
   started" unmistakable, or beginners will think nothing happened. **Revised
   2026-10-24 by the user: pressing Run opens Flow**; "Show the flow when a run starts"
   in the Run menu is on by default and turning it off restores the rule above.
5. **Windows notifications when a run finishes**, turned on once from the Run menu.
   Refined after the second research round: the launcher was to raise them. **Revised
   in P1 after prototyping both (5.5): the Web Notification is kept.** It showed at once
   with the LanEx mark and the numbers and needs no installer or launcher change; the
   launcher's native toast reached Windows but showed no banner in the test, and its
   click would open a second LanEx window until the launcher learns to raise the
   existing one. To check by hand: that clicking the notification brings a background
   LanEx window forward.
6. **Launch stays on Setup, with a Continue chip.**

These are research-backed, not user-tested. Each phase ends with screenshots for the
user before anything is committed.

---

## Sources

Users and workflows
- LibreLane newcomers' tutorial: https://librelane.readthedocs.io/en/latest/getting_started/newcomers/index.html
- LibreLane CLI (`python -m librelane --help`, 3.0.4, in the appliance)
- OpenLane 2 timing closure guide: https://openlane2.readthedocs.io/en/latest/usage/timing_closure/index.html
- OpenLane interactive mode: https://openlane-docs.readthedocs.io/en/latest/reference/interactive_mode.html
- VSD advanced physical design write-up (one of many): https://github.com/aasthadave9/Advanced-Physical-Design-Using-OpenLANE-Sky130
- Tiny Tapeout local hardening: https://www.tinytapeout.com/guides/local-hardening and FAQ: https://tinytapeout.com/faq/
- wafer.space LibreLane template: https://www.crowdsupply.com/wafer-space/gf180mcu-run-1/updates/librelane-template
- UCSC chip tutorials (LibreLane): https://github.com/VLSIDA/chip-tutorials/blob/main/librelane.md
- ORFS flow tutorial: https://openroad-flow-scripts.readthedocs.io/en/latest/tutorials/FlowTutorial.html
- ORFS AutoTuner: https://openroad-flow-scripts.readthedocs.io/en/latest/user/InstructionsForAutoTuner.html
- Hacker News, "Two Weeks Until Tapeout" (gate-level sim, tapeout pressure): https://news.ycombinator.com/item?id=46749671
- Hacker News, Tiny Tapeout beginners: https://news.ycombinator.com/item?id=34523800
- ZipCPU, lessons from an ASIC: https://zipcpu.com/blog/2021/03/06/asic-lsns.html
- Qualcomm PD engineer day: https://www.cleverprep.com/companies/qualcomm/physical-design-engineer
- OpenLane debugging discussion: https://github.com/The-OpenROAD-Project/OpenLane/discussions/2169

Tools
- Vivado Design Runs window: https://docs.amd.com/r/en-US/ug906-vivado-design-analysis/Using-the-Design-Runs-Window
- Vivado Project Summary: https://docs.amd.com/r/2023.2-English/ug893-vivado-ide/Using-the-Project-Summary-Overview-Tab
- Vivado Synthesis Completed dialog: https://docs.amd.com/r/2025.1-English/ug888-vivado-design-flows-overview-tutorial/Step-7-Synthesizing-and-Implementing-the-Design
- Quartus Compilation Dashboard: https://www.intel.com/content/www/us/en/docs/programmable/683463/22-2/using-the-compilation-dashboard.html
- Libero Project Flow window: https://onlinedocs.microchip.com/oxy/GUID-6BACC19D-0959-4B51-87AC-AD97B0E07E35-en-US-1/GUID-96EF77A5-EC37-43FF-B698-6C313DA038C5.html
- Synopsys Lynx: https://www.synopsys.com/implementation-and-signoff/lynx-design-system.html
- Cadence Stylus: https://indico.fnal.gov/event/74818/contributions/343661/attachments/200822/280173/Stylus_Introduction_Aug2026.pdf
- Calibre RVE: https://eda.sw.siemens.com/en-US/ic/calibre-design/interfaces/rve
- SiliconCompiler dashboard: https://docs.siliconcompiler.com/en/latest/user_guide/tutorials/dashboard_tutorial.html
- TerosHDL: https://github.com/TerosTechnology/vscode-terosHDL
- Verdi tips: https://courses.grainger.illinois.edu/ECE411/sp2026/verdi.html
- DaVinci Resolve pages: https://www.tourboxtech.com/en/news/davinci-resolve-pages-explained.html
- Fusion timeline: https://help.autodesk.com/cloudhelp/ENU/Fusion-Assemble/files/ASM-TIMELINE.htm
- GitHub Actions log improvements: https://github.blog/changelog/2020-09-23-github-actions-log-improvements/
- W&B sweeps and parallel coordinates: https://letsdatascience.com/blog/w-b-complete-guide-ml-experiment-tracking

Second research round (2026-10-06)
- R-a to R-f: research reports by agy agents (Gemini 3.8 Flash): R-a beginners, R-b
  veterans, R-c open-source community, R-d technical feasibility, R-e cockpit-app UX
  patterns, R-f FPGA migrants and learners. Used for leads only: several of their
  quotes were paraphrases or invented, so the plan cites a claim from them only where
  it was checked against a primary source (LibreLane source, GitHub, a Reddit thread
  read directly) or where it is a design judgement.
- LibreLane 3.0.4 source, read from the appliance image: `flows/sequential.py`
  (`--from`, skipped steps keep the state and create no folder), `flows/flow.py`
  (run tags, resume, `-i`), `flows/cli.py` (`initial_state_cb` validates paths),
  `config/flow.py` and `pdk_compat.py` (`IO_DELAY_CONSTRAINT` default 20),
  `scripts/base.sdc`, `scripts/pyosys/synthesize.py` (ABC reads `CLOCK_PERIOD`), each
  Classic step's `config_vars`.
- LibreLane issue #1040, per-corner metrics carried forward unmarked (open, 2026-09):
  https://github.com/librelane/librelane/issues/1040
- ORFS PR #4627, "end every stage log with a short summary" (merged 2026-10-05):
  https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/pull/4627
- Hacker News, stickfigure on GitHub Actions usability (2022):
  https://news.ycombinator.com/item?id=30920543
- I. Duncan, "GitHub Actions Is Slowly Killing Your Engineering Team" (2026):
  https://iankduncan.com/engineering/2026-02-05-github-actions-killing-your-team/
- Reddit threads: listed in 1.4, read through the Arctic Shift archive API
  (https://github.com/ArthurHeitmann/arctic_shift).
- Reddit Data API access now needs manual approval (Responsible Builder Policy,
  Nov 2025): https://www.keyapi.ai/blog/reddit-data-api-overhaul-major-changes-and-migration-guide/

Fix loop research (P2, 2026-10-24)
- AMD UG906, QoR suggestions: https://docs.amd.com/r/en-US/ug906-vivado-design-analysis/QoR-Suggestions and
  https://docs.amd.com/r/en-US/ug906-vivado-design-analysis/Executing-Suggestions
- AMD UG949, timing violations: https://docs.amd.com/r/en-US/ug949-vivado-design-methodology/Identifying-Timing-Violations-Root-Cause
  and https://docs.amd.com/r/en-US/ug949-vivado-design-methodology/Analyzing-and-Resolving-Timing-Violations
- OpenROAD GUI: https://openroad.readthedocs.io/en/latest/main/src/gui/README.html; DRC viewer source
  `src/gui/src/drcWidget.cpp` (OpenROAD master, read 2026-10-24)
- Siemens Calibre RVE: https://www.siemens.com/en-us/products/ic/calibre-design/interfaces/rve/
- OpenROAD issue #4318 (cell padding and GPL utilization): https://github.com/The-OpenROAD-Project/OpenROAD/issues/4318
- LibreLane timing closure guide: https://librelane.readthedocs.io/en/latest/usage/timing_closure/index.html
- LibreLane 3.0.4 source (appliance): `flows/cli.py`, `flows/flow.py`, `flows/sequential.py`,
  `scripts/openroad/sta/corner.tcl`, `scripts/openroad/gpl.tcl`, `scripts/base.sdc`
- Reddit, read from the Arctic Shift archive: r/chipdesign "When does fixing timing stop being a PD problem?"
  (1wkeeof), "Stuck with DRC Errors" (14a41e4), "Fixing DRC errors help! (tapeout date in a week lol)" (1d1hmq4);
  r/FPGA "How to Analyze Timing Reports in Vivado?" (vubr1e)

UX research
- NN/g, complex applications: https://www.nngroup.com/articles/complex-application-design/
- NN/g, progressive disclosure: https://www.nngroup.com/articles/progressive-disclosure/
- NN/g, onboarding tutorials: https://www.nngroup.com/articles/onboarding-tutorials/
- NN/g, empty states: https://www.nngroup.com/articles/empty-state-interface-design/
- NN/g, error messages: https://www.nngroup.com/articles/error-message-guidelines/
- NN/g, paradox of the active user: https://www.nngroup.com/articles/paradox-of-the-active-user/
- Shneiderman, multi-layer interfaces: https://www.cs.umd.edu/~ben/ACM-CUU2003.pdf
- OOUX / ORCA: https://uxdesign.cc/an-introduction-to-object-oriented-ux-and-how-to-do-it-829bf6b248a1
- Background task UX: https://blog.logrocket.com/ux-design/ui-patterns-for-async-workflows-background-jobs-and-data-pipelines/
- Command palettes: https://solomon.io/designing-command-palettes/
