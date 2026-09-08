# LanEx installer checkpoint

Date: 2026-09-08
Stage: M0 complete; M1 is next.
Canonical pack: `C:\Users\itsva\lanex\docs\windows-installer-handoff`.
Repo: `C:\Users\itsva\lanex`
Branch: `windows-installer-support`
M0 implementation commit: `1d60f2a22a0841507d74d1e75fa23b66d8ea7a09`
Git status before this checkpoint commit: only this new `STATE.md` is untracked.

## Decisions

- Retain private WSL appliance, Inno Setup, Go launcher, and shared LanEx
  installers. Extend the architecture; do not replace it.
- Docker CE is the default appliance engine; Podman is an alternative.
- Default environment remains matched LibreLane image, native support tools,
  GDS3D, and sky130A with all catalog libraries; initial SCL is
  `sky130_fd_sc_hd`, subject to M1/M3 pin validation.
- Windows 11 x64 is primary. Windows 10 remains unadvertised until its real
  acceptance leg passes. ARM64 remains rejected for the amd64 appliance.
- Existing distros/data require identity proof before adoption or deletion.
- Main remains untouched until Akshat tests the candidate and merge is
  explicitly authorized. No release/publication/contact is authorized yet.

## Completed M0

- Adopted the full handoff into this canonical repository directory.
- Rechecked local/remote state: both branch heads matched the audit at start;
  `windows-installer-support=725dcb6`, `main=ff0759b`; GitHub auth is usable.
- Inventoried protected WSL2 distros: `Ubuntu`, `lanex`, `Ubuntu-22.04`.
- Generated `CAPABILITY-INVENTORY.json` from LanEx plus pinned LibreLane 3.0.4
  and Ciel 2.6.1 in isolated Linux. It contains 13 backend tools, seven PDK
  variants, and every library/default-library set.
- Inspected frontend specials: GDS3D; Docker/Podman; image pull; container GUI
  controls for Magic, KLayout, OpenROAD, and Netgen. Mapping and caveats are in
  `M0-BASELINE.md`.
- Repaired stale sudo regression: passwordless uses streamed isolated Popen;
  password-required uses tty. All probes/processes are mocked.
- Added missing round-76 CI Summary implication found by the first baseline.
- Root CI and Differential branch push filters now cover
  `windows-installer-support` while preserving existing triggers.

## Verified tests

Evidence: `C:\Users\itsva\Documents\Codex\2026-09-08\implement-the-lanex-windows-installer-handoff\work\m0-evidence-20260908`

- Disposable Ubuntu ext4 clone/home/venv, Python 3.12.3:
  `python -m pytest lanex/tests -q --junitxml=... -p no:cacheprovider` ->
  **737 passed, 6 skipped, 0 failed**.
- Current-tree focused installer/round75/CI-helper rerun -> **55 passed**.
- Frontend behavior under pinned Linux Node 20.19.5 -> **41 passed**;
  all JS syntax and static hygiene checks passed.
- Wheel build and all nested asset sentinels passed.
- Native Windows Go 1.22.12: test, vet, format, and build all passed.
- Explicit Windows Git Bash `bash -n` passed for install.sh, install-wsl.sh,
  provision.sh, and selftest.sh.
- Six skips are explicit environment gates (Graphviz SVG, Chromium layout,
  LibreLane `RUN_LVS`, two absent SPM fixtures, PDK-liberty canary); see
  `M0-BASELINE.md`. No blanket skip was added.

## Current / next action

Start M1 at exact-payload identity: map current install readers/writers, fix
branch/tag/SHA source resolution, and define/test the build-manifest plus atomic
owner-scoped state schema before wiring installer mutations. Preserve ordinary
universal-installer behavior and make Windows use bundled/local candidate input.

Dirty files expected after checkpoint commit: none.

## Outstanding acceptance

- M1-M8 remain pending.
- No candidate Setup EXE has been built or installed.
- No real import/provision, Docker daemon, PDK download, WSLg/GUI, restart,
  elevation/account, uninstall/data-safety, offline, or RTL-to-GDS acceptance
  case has run for a new installer candidate.
- Those cases require later implementation plus suitable disposable Windows
  VM/hardware; reboot/firmware/security changes and release publication remain
  explicit authorization boundaries.

## Protected/live resources

- Never use existing `lanex` as a test fixture. Preserve all three distro
  registrations/defaults/data and `%LOCALAPPDATA%\LanEx`/legacy profile data.
- Ubuntu was started for isolated tests and may remain running; do not issue a
  global WSL shutdown merely to tidy it.
- Owned scratch only: `/tmp/lanex-m0-20260908` inside Ubuntu, and this task's
  `work` directory (venvs, verified Node/Go archives, logs, baseline EXE).
- No test distro, VM, elevated helper, service, server, or installer was created.
- No secrets are stored in repository or evidence.
