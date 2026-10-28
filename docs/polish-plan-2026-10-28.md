# LanEx polish pass: re-evaluated plan (2026-10-28)

This replaces the remaining part of the phase table in `workflow-spec.md` section 8
(P3 to P6). W, P0, P1, P2 and the Ship line are done and merged to `main`
(AkshatIsWired/lanex PR 2, 2026-10-27).

## Why re-plan

The original plan (2026-10-06) came from a limited first research round. This round
went wider and started from the app as it is:

- Two hands-on test passes on private servers with real flow runs: a beginner journey
  from a genuine first launch, and an expert pass over Runs, DSE, Compare, Tools,
  Manual, palette and the fix loop (a real 3-point sweep, a real failure, a real resume).
- A read-only code audit for half-built, dead and inconsistent code.
- Live Reddit research through the Composio helper: 88 beginner threads and about 70
  veteran threads, read directly, quotes checked; plus HN and GitHub issues.
- Primary-source UX research: NN/g on tutorials, tour completion data (vendor-biased,
  marked), VS Code walkthroughs, Unity/Figma/Linear/Arduino/Tiny Tapeout onboarding,
  W&B/MLflow/Vivado/Quartus run management, Arduino/KiCad/JetBrains component managers.

## What the evidence says

Beginners (Reddit, by thread count):
1. Installing tools and PDKs on Windows/WSL is the dominant pain (22 of 88). LanEx's
   installer already removes it; the app should show it ("no Linux, no PDK_ROOT").
2. "How does it all fit together after RTL?" (13). Show the flow with real tool names.
3. Cryptic errors, LVS/DRC especially (10, two never answered).
4. Push-button worry: "did I actually do RTL-to-GDS?" (7). Show the real commands and
   let people take the project to the plain CLI.
5. Timing constraints/closure is the most-upvoted skill gap.
6. Renders, 3D and placement animations are the most-upvoted posts; people ask "what
   am I looking at?"
7. Onboarding: invisible, learn-by-doing teaching wins; forced tours are disliked; one
   optional "Learn / I know this" choice raised tutorial completion from 50% to 75%
   (r/gamedev, 223 points). NN/g: up-front tutorials don't raise success and make tasks
   feel harder; keep them optional and interactive.

Veterans:
1. The GUI is for looking and debugging; builds run as scripts (about 14 comments,
   top 142 points). Reproducible, headless, versionable builds (about 10).
2. Echo the command behind every GUI action, "copy as script" (about 7).
3. Never hide the raw log, reports, resolved config or run folder.
4. Fail early: a config check before long runs.
5. Sweeps are a last resort after fixing RTL and constraints; "100 strategies" is a
   design smell. Keep sweeps small and honest.
6. Don't build another code editor; navigation yes.
7. Command palettes and notifications: no direct evidence either way (low priority, cheap).

The app (test passes and audit):
- Trust bugs: the run verdict is computed three ways and tabs disagree (Analytics
  "Clean run: all 17 checks passed" vs Verify "Not enough to call it"); Verify's Magic
  card says "Passed 0" while listing 4 markers; KLayout "all pass" vs Layout's 7; DSE
  marks failed sweep points "done"; Runs shows a running run as "failed"; the fix sheet
  attributes a sweep override to config.yaml; three different step counts on one Flow
  screen; run order from folder mtime (pinning may reorder); power-grid wording
  hard-coded to sky130's VPWR/VGND.
- Islands: Runs, DSE, Tools and Manual were never redesigned and feel like separate
  apps; Compare exists in three places; the palette searches 28 fixed actions while
  the help says "every command and setting".
- Onboarding: no tour; "Try an example" ends on a toast with no next step.
- Dead code: about.js, most of learn.js, a duplicate help entry that shows old copy.

## The new plan (ordered by return on effort)

| # | Phase | Scope | Status |
|---|---|---|---|
| 1 | **Trust** | One verdict source for every tab; honest running/stopped states; stable run order; DRC report-vs-checker disagreement shown, not hidden; one step-count meaning; fix-sheet source attribution; compare-with defaults to the parent of a fix run; PDK-correct power net names; dead code and stale strings | built 2026-10-28 |
| 2 | **First chip** | Optional "Press Start" card on first launch: guided first chip (6 beats on real app events: example, simulate, PDK, setting, run, GDS 2D then 3D, with a finish card of real numbers) or a 5-stop tour or skip. Re-openable from Help and Ctrl+K. Driver.js (MIT) vendored; Shepherd and Intro.js rejected (AGPL) | built 2026-10-28 |
| 3 | **Runs** (old P3, cut down) | Dense sortable Runs table with QoR columns from existing metrics, baseline with deltas, lineage badges, multi-select Compare into the one Analytics compare view, sweeps as grouped rows with a side-sheet builder over the full variable registry, plain-word goal presets, "Use this configuration" through the fix sheet's diff/Undo path; DSE rail item removed; DSE correctness bugs | built 2026-10-28 |
| 4 | **Console + palette** (old P4) | Console drawer on every page replacing Manual: Log, Command (next run and this run, Copy), Reproduce block that runs headless without LanEx, Journal with "Copy as script", the allow-listed runner with history. Palette searches settings (#), runs (@), files (/), help (?), actions (>), with tour entries | built 2026-10-28 |
| 5 | **Tools** | Component manager redesigned (not reduced): summary strip, filters, one row per component, installed vs LanEx-tested version, same-size actions, destructive actions behind an overflow and confirm, loading skeleton, Copy diagnostics | built 2026-10-28 |
| 5b | **Beginner fixes** | Blank template's fixed 150x150 die (real designs fail placement) → relative sizing; Mask XOR and other check failures get plain meaning and an action; "rewrite the testbench for these ports"; missing project folder shown as such with Run disabled; local time instead of the distro's UTC; zero-warning example configs; the top fix as the primary button; a hint on steps over 60 s; plain layer names in Layout | built 2026-10-28 |
| 6 | **Explain the flow** (next) | Real tool names per stage in Flow ("Synthesis (Yosys)"), layer legend and "what am I looking at" captions in Layout, Save image with tool list and numbers, laddered examples (counter, ALU, UART) with a Tiny Tapeout track, staleness per stage (old P3 part) | after this pass |

Dropped or deferred, with reasons:
- **Learning mode / pause at every stage (old P6): dropped.** The owner: people won't be
  patient enough; research agrees (forced, slow tutorials are skipped). The first-chip
  guide and plain stage captions cover the need.
- **Setup journey tracker (old P5): folded into First chip.** The Continue/next-step
  role is played by the guide pill and the "Try an example" next-step toast.
- **Big auto-tuning (NSGA-II/Bayesian, 100-run sweeps): not built.** Veterans call it a
  smell; small honest sweeps with a summary card instead.
- **Exercise bank, gamification, badges, video tutorials in-app, cloud runs, AI
  "designs your chip", a manual layout editor: not built.** Low demand or distrusted.

## Sources

Raw research notes (thread dumps, digests) live in the session scratchpad
`audit/reddit-beginner`, `audit/reddit-veteran`; per-thread ids and scores are in the
agents' reports summarised above. Key primary sources: NN/g "Mobile tutorials" and
"Onboarding: skip it when possible"; Chameleon benchmark report (2020); VS Code
walkthrough contribution point and UX guidelines; Driver.js docs and licence; Shepherd
and Intro.js licence files; W&B run comparison and grouping docs; AMD UG904/UG906;
Intel Quartus DSE II; ORFS AutoTuner docs; Arduino Boards Manager, KiCad PCM, JetBrains
Toolbox docs.

## As built (2026-10-28, branch `polish-2026-10-28`, not pushed)

Built by six agents in separate worktrees, merged, then checked by three independent
auditors (a fresh-user replay with real runs, a cross-tab accuracy check against the
raw run files, a code review of the whole diff) and fixed in four more rounds.

- Accuracy auditor: WNS/TNS/hold, die and std-cell area, utilisation, power (mW),
  runtimes, local start times, baseline delta directions, sweep best-for-timing/area and
  Compare numbers all match `final/metrics.json` across Runs, run bar, Flow, Analytics
  and Verify. Pinning and notes no longer reorder runs.
- Real runs used: Blinky through the guide (clean, 37 s), an 8-bit ALU (clean, then
  CLOCK_PERIOD 1 and the fix sheet), a 32x32 multiplier (relative sizing now routes it),
  three real sweeps (one failing point, DPL-0036, reported as failed with its reason),
  spm at a 5 ns clock (warning verdict, setup -0.54 ns at ss), the Console's
  command run headless in WSL (produced a GDS).
- Tests: frontend 110 checks; pytest 1151 passed, the 8 known environment failures.

Open after this pass:
- Sweeps recorded before this pass keep a `created_at` without a UTC offset.
- LibreLane's own log timestamps are UTC (its text, not LanEx's).
- Resume is not blocked while a project folder is missing.
- Not tested here: gf180 runs from a private server ("PDK gf180mcuD was not found"
  in one agent's environment), light theme, widths below about 1180 px for Tools.
