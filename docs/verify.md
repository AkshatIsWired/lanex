# Verify tab

The Verify tab answers one question for a run: does it pass sign-off, and if not,
which check failed, why, and what to change. It is built for two readers at once:
someone on their first tape-out who needs every term explained, and someone who
already knows LibreLane and wants the exact rule, corner and file behind a verdict.

## What it shows, top to bottom

1. **Verdict.** Tape-out ready / N problems block tape-out / stopped at step N /
   not enough to call it. One cell per check, in flow order, gives the whole run
   at a glance; a click jumps to that check. Changes since the run picked under
   *Compare with* (default: the previous clean run of the same design) are called
   out as "new problems" and "fixed".
2. **Four areas:** timing, design rules, layout vs. netlist, antenna & power.
   Each opens its detail section.
3. **Every check, in flow order:** RTL lint, synthesis, place & route, timing
   sign-off, physical verification. Failures are open on arrival. An opened row
   says what the check looks at, why it matters, what to try (only variables that
   exist in LibreLane 3, with their defaults), the value with a link to the line
   in `metrics.json`, the limit, what decides pass/fail (`ERROR_ON_*`, corner
   wildcards), the checker step and how it ended, the step that measured it, its
   report and log, and a re-run of that one step where that stands on its own.
4. **Timing in every corner:** setup WNS/TNS/violations, hold WHS/THS/violations,
   slew/cap/fanout, with each corner marked as failing the run or only warning.
   The worst-paths table and slack histogram sit below it.
5. **DRC:** Magic, KLayout and the router side by side; every broken rule with the
   PDK's own description and sample locations in µm; the router's per-pass
   violation counts; "Open in KLayout" loads the marker databases.
6. **LVS & XOR:** Netgen's final result, device/net/pin counts for the extracted
   layout and the netlist, the per-kind LVS counters, and the XOR layers compared.
7. **Antenna & power:** violating nets/pins with the ratio table, power-grid
   connections per net, IR drop per net as a share of the supply.
8. **Reports:** the files each verdict was read from first, then every other log.
   "Copy summary" puts a plain-text checklist on the clipboard.

## Where the verdicts come from

`lanex/controller/verify.py` mirrors LibreLane's own `Checker.*` steps
(`librelane/steps/checker.py`, 3.0.4) instead of inventing thresholds:

- Same metric and threshold per checker (e.g. disconnected pins use
  `design__critical_disconnected_pin__count`, not the total).
- `ERROR_ON_*` from the run's `resolved.json` decides error vs. warning
  (LibreLane's defaults when a key is absent).
- Setup/hold/slew/cap are judged per corner with the run's
  `TIMING_VIOLATION_CORNERS` / `SETUP_` / `HOLD_` / `MAX_SLEW_` / `MAX_CAP_VIOLATION_CORNERS`,
  matched with `fnmatch` like `librelane.common.Filter`. By default setup fails
  only in `*tt*` corners, hold in every corner, slew and cap never.
- `RUN_*` gates (Classic flow) make a check "turned off", never "passed".
- The checker step's own outcome is read: `state_in.json` without
  `state_out.json` means it raised (a deferred error leaves exactly that while
  `final/` is still written). If that disagrees with the metric, the failure wins
  and the page says the value changed afterwards.
- Antenna has no checker; LibreLane's manufacturability report marks any
  remaining violation "Failed", so it counts as a blocker here too.
- A stopped run has no `final/metrics.json`: values come from the last finished
  step's `state_out.json` (and the page says so), and a check whose step never
  ran is "not reached", never judged on an earlier estimate.
- "Ready" needs setup, hold, DRC (Magic or KLayout) and LVS to have produced a
  result; otherwise the verdict is "not enough to call it".

The Analytics check strip takes its statuses from the same report, so the two
pages cannot disagree. The Runs list's success flag now also treats a raised
checker as a failed run (`history._success_from_metrics`).

## Research behind the layout

- Vivado's design-run status and timing summary (WNS/TNS/WHS/THS, failing
  endpoints) and PrimeTime's global timing: one verdict, then timing per corner.
- Calibre RVE / Pegasus Results Viewer / IC Validator VUE and KLayout's marker
  browser: results grouped by rule with counts and rule text, empty rules hidden,
  focus on the highest-priority errors first, cross-probing into the layout.
- Netgen/OpenLane LVS debugging advice: start from pins and nets rather than
  devices; a short shows up as one fewer net.
- ORFS `rules.json`/metadata checks: compare against a known-good run.
- Tiny Tapeout / LibreLane's post-run summary: a short pass/fail checklist people
  paste into issues ("Copy summary").

## Testing

- `lanex/tests/test_verify.py`: LibreLane rules (corner gating, `ERROR_ON_*`,
  raised checkers, turned-off checks, stopped runs, antenna, report parsing).
- `lanex/tests/frontend_test.mjs`: verify-model helpers and the Analytics link.
- `.claude/vf-scratch.sh` builds a scratch design with a clean run, a run with
  planted DRC/LVS/setup/antenna failures and a stopped run; `.claude/serve-verify.sh`
  serves the checkout on its own port. Remove the scratch with
  `vf-scratch.sh clean` and forget it via `/api/project/forget`.
