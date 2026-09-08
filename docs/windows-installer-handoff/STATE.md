# LanEx installer checkpoint

Date: 2026-09-08
Stage: M0-M1 complete; M2 is next.
Canonical pack: `C:\Users\itsva\lanex\docs\windows-installer-handoff`.
Repo: `C:\Users\itsva\lanex`
Branch: `windows-installer-support`
M0 commits: `1d60f2a`, `ff82cfc`
M1 implementation commit: `f75c1568254c4b8ce5581be49f66d8653b17709c`
Git status before this checkpoint commit: only `STATE.md` modified; generated
wheel/manifest/pins/EXEs are ignored.

## Decisions

- Keep private Ubuntu WSL appliance, Inno Setup, Go launcher, and shared LanEx
  installers. Docker CE remains default; Podman is the alternative.
- Windows 11 x64 is primary. Windows 10 remains unadvertised pending its real
  acceptance leg. ARM64 remains rejected for the amd64 appliance.
- Windows locks LibreLane 3.0.4 + Ciel 2.6.1; ordinary project metadata retains
  its supported range. PDK pins come from that exact locked environment.
- A distro name is never ownership proof. Authority requires owner SID,
  install UUID, exact HKCU registration ID/path, and matching Linux marker.
- Repair is same-build and no-op when healthy. Update requires `/UPDATE=1`.
  Current uninstall removes Windows launcher/shortcuts and preserves all data.
- Main stays untouched until Akshat tests the finished candidate and merge is
  explicitly authorized. No release/publication/contact is authorized yet.

## Completed M0

- Adopted canonical handoff; inventoried/protected `Ubuntu`, `lanex`, and
  `Ubuntu-22.04`; generated the 13-tool/seven-PDK capability inventory.
- Repaired stale sudo regression and added Windows branch CI coverage.
- Full isolated Linux baseline: 737 passed, 6 explicit environment skips;
  frontend 41 passed; focused installer/CI 55 passed; wheel and Go checks pass.
- Detail/evidence: `M0-BASELINE.md` and its recorded M0 evidence path.

## Completed M1

- Universal Git source supports repository + branch/tag/SHA via ref-aware
  codeload; local and pip sources remain supported.
- Setup bundles exact checkout wheel, universal installer, provision/selftest,
  constraints, manifest, and state worker. Failed fetch is checked before bash;
  provisioning has no installer curl-to-bash path.
- CI checks out actual fork head, builds/mounts its local wheel, and never falls
  back to base/main. Immutable manifest hashes every executable payload.
- Manifest records source, rootfs, target/Python floors, locked dependencies,
  image digest, PDK catalog/family pins, GDS3D commit, and sizes.
- Atomic schema-1 owner state preserves choices, source/build/installer hashes,
  boot/restart counters, phases, and component fingerprints. Malformed,
  wrong-owner, unmigratable-old, and newer records are rejected.
- Foreign `lanex` chooses `lanex-<install-id-prefix>`; post-import state binds
  exact registry GUID/path and provision writes the Linux marker. Launcher reads
  a validated data-only appliance config (no command text).
- Matching Repair checks registration + Linux marker + selftest without apt/pip;
  changed manifests invalidate changed components only and require Update.
- Destructive name-only reinstall/uninstall paths removed. Legacy Program Files
  migration plan and boundaries: `M1-IDENTITY.md`.

## Verified M1 evidence

Evidence: `C:\Users\itsva\Documents\Codex\2026-09-08\implement-the-lanex-windows-installer-handoff-2\work\m1-evidence-20260908`

- Windows hermetic identity/source tests: **26 passed**: branch/tag/SHA, local
  wheel, atomic interruption, owner/schema rejection, foreign collision, exact
  binding, manifest invalidation, and repair source lock.
- Isolated Linux relevant regressions: **62 passed** (`test_installer`,
  `test_install_foolproof`, `test_pdk_resolve`, `test_packaging`).
- Native Windows Go 1.22.12 test/vet/format/build pass.
- Git Bash syntax, Ubuntu shellcheck `-S style`, workflow YAML parse, and Inno
  Setup 6 compile pass.
- Clean-commit artifact: source `f75c156`; wheel SHA256
  `0a6f00fe92a16695d2c5efbd9c5f28a9214e237287a062b41182e27a6e38b684`;
  manifest `3f4431fb6244157cea1e2c94db9ad46355d30519b5f941f4abadbc82b7f5f356`;
  Setup `3edbf33cbf3ed88dbebd981f8810613b3e5ba3c3bf567d80d7b945ace383a2f1`
  (5,096,198 bytes). M1 compile artifact, not the Akshat candidate.

## Current / next action

Start M2: structured Windows preflight; split limited feature elevation from
original-user appliance ownership; owner-bound bounded restart/resume with
manual continuation. Read M2, A05-A09/A22, U01/U05 and applicable Windows cases.

## Outstanding acceptance / protected resources

- M2-M8 pending. No new Setup installed; no real WSL import/provision, Docker
  daemon, PDK download, WSLg/GUI, restart, UAC-account, offline,
  uninstall/data-removal, or RTL-to-GDS case ran for this candidate.
- Real EXE legs require disposable Windows VM/Akshat machine. Reboot,
  firmware/security changes, publication, and merge remain explicit boundaries.
  The M1 EXE must not be sent as the finished build.
- Existing `Ubuntu`, `lanex`, `Ubuntu-22.04`, defaults/data, and
  `%LOCALAPPDATA%\LanEx`/legacy profile remain protected and unchanged.
- Ubuntu was used only for isolated venv tests/pin export and may be running; do
  not globally shut WSL down. No distro/VM/service/helper created.
- Owned scratch: this task's `work` plus ignored repo build artifacts. No
  secrets are stored in repository or evidence.
