# M5 wizard/progress checkpoint

Date: 2026-09-09
Status: in progress
Foundation commit: `c87fafc`

## Implemented and verified

- Added one manifest-bound selection planner for interactive and unattended
  setup. It accepts a JSON selection file, normalizes the three profiles, and
  rejects unknown tools, PDKs, libraries, multiple variants from one family,
  and image/PDK choices without Docker or Podman.
- Recommended is exactly Docker, the matched flow image, Verilator, Icarus,
  Graphviz, GTKWave, GDS3D, and sky130A with all locked family libraries.
  Minimal explicitly selects no engine, image, native tools, or PDK and remains
  subject to base Python/runtime readiness.
- Old M3/M4 state without a profile migrates to the equivalent custom choice
  without replacing the owner, source, appliance, or resume identities.
- The Linux finalizer consumes the same profile semantics and does not invent
  an engine/image/PDK for a deliberate minimal setup.
- Estimates separately report network bytes, installed bytes, extraction
  headroom, practical run headroom, AppData-volume need and temporary-volume
  need. They disclose their measured/catalog basis and explicitly say that an
  interrupted rootfs transfer restarts rather than claiming range resume.

## Proof

- `python -m pytest lanex/tests/test_windows_setup.py lanex/tests/test_windows_provisioning.py lanex/tests/test_windows_network.py -q`
  -> **74 passed**.
- Inno Setup 6 compiled `lanex.iss` with the current worker hash, existing
  launcher/wheel, and exact pre-foundation source define. This is syntax and
  packaging proof only; the generated EXE is not an M5 candidate.
- `git diff --check` passed (Git emitted only the repository's Windows
  line-ending conversion notices).

## Next implementation slice

Wire the planner to the Inno wizard and documented silent parameters. Add the
recommended/custom/minimal pages, engine/PDK/advanced-library controls, honest
estimate display and per-volume free-space rechecks. Then add the bounded live
progress protocol, diagnostics controls, cooperative WSL process-group cancel,
retry/exit behavior and U13 fixtures. Do not mark M5 complete until those UI
and protocol paths compile and their safe fixtures pass.

## Still external

No Setup was installed or launched. Responsiveness, keyboard navigation,
125–200% DPI, real cancellation during apt/image/PDK work, and restart choice
survival still require the finished UI plus disposable Windows testing. The
development PC's WSL distributions and LanEx data were not changed.
