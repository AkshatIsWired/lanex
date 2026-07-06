# scripts/ci — differential + live-API CI suite (self-contained, removable)

Everything for the `differential` and `api-e2e` CI jobs lives in exactly three
paths, all NEW — nothing existing was modified:

1. `scripts/ci/` (this directory) — helpers + job drivers
2. `.github/workflows/differential.yml` — the two jobs (separate workflow;
   `ci.yml` is untouched)
3. `lanex/tests/test_ci_helpers.py` — unit tests for the comparators/drivers

**To remove the whole suite** (existing CI + the 443-test suite stay intact):

```bash
git rm -r scripts/ci .github/workflows/differential.yml lanex/tests/test_ci_helpers.py
```

## What runs

- `differential_run.py` — four RTL→GDS runs of the bundled SPM design on one
  runner (native lanex-less `librelane --dockerized` CLI; lanex local mode
  inside the official image; lanex container mode; lanex toolwise/step mode),
  then hard equivalence gates: metric identity, step-dir + final/ inventory
  identity, resolved-config identity modulo path canonicalization, per-leg
  honesty floor. GDS-hash equality is report-only (GDSII embeds write
  timestamps, so identical runs still hash differently; `LANEX_CI_GDS_HARD=1`
  exists but is only meaningful with a timestamp-normalized compare).
- `api_e2e.py` — boots the real server and drives the audited lifecycle over
  HTTP: canary override fidelity, metric passthrough, cancel-kills-container,
  SSE-vs-disk, export/CSV cross-check, bundle byte-roundtrip, three-state
  verdicts, concurrency guard, spaces-in-path guard, kill-9 crash-restart.
- The small tools (`flatten_metrics.py`, `compare_flat.py`, `hash_tree.py`,
  `bundle_verify.py`, `csv_cross.py`, `sse_capture.py`) are stdlib-only,
  usable standalone, and unit-tested by `lanex/tests/test_ci_helpers.py`.

## Environment knobs (all optional)

| Var | Default | Meaning |
|---|---|---|
| `LANEX_CI_IMAGE` | `ghcr.io/librelane/librelane:3.0.4` | LibreLane image (keep == pyproject librelane floor) |
| `LANEX_CI_PDK` / `LANEX_CI_SCL` | `sky130A` / `sky130_fd_sc_hd` | PDK/SCL under test |
| `LANEX_CI_WORK` | `<cwd>/ciwork` | scratch workspace (PDK store, design copies, harvest) |
| `LANEX_CI_PDK_ROOT` | `<WORK>/.pdk` | PDK store location (point at an existing store to reuse it) |
| `LANEX_CI_SKIP_PDK_FETCH` | `0` | `1` = trust the existing store, skip ciel fetch/enable (local dev) |
| `LANEX_CI_LEG_TIMEOUT` | `3600` | per-leg flow deadline, seconds |
| `LANEX_CI_LEGS` | all four | comma list to run a subset while debugging |
| `LANEX_CI_GDS_HARD` | `0` | `1` = GDS sha256 equality becomes a failing gate |
| `LANEX_CI_PORT` | `8763` | api_e2e server port |

## Constraints inherited from the main CI (do not "fix")

- Never a `container:` job with the LibreLane image (nix image can't exec the
  injected Node); always `docker run` from the host.
- The image has no pip/pytest — in-image code is stdlib + `PYTHONPATH` only.
- The repo/work dirs are mounted at their **identical host paths** inside the
  image so one host-side `ciel` PDK fetch serves every leg (symlinks in the
  ciel store are absolute).
- SPM is the only known-good CI design (`counter` fails DPL-0036 on sky130).
