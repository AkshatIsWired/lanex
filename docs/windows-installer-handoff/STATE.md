# LanEx installer checkpoint

Date: 2026-09-09
Stage: M0-M4 complete; M5 selection/estimate foundation started.
Canonical pack: `C:\Users\itsva\lanex\docs\windows-installer-handoff`.
Repo: `C:\Users\itsva\lanex`
Branch: `windows-installer-support`
M0 commits: `1d60f2a`, `ff82cfc`
M1 implementation: `f75c1568254c4b8ce5581be49f66d8653b17709c`
M2 implementation: `39dd4c439d319ce9a37c9f5aaa0262b6f2567ab2`
M3 implementation: `bfc1ad3`, `eebc69e`
M4 implementation: `4aa748d`, `2f79507`, `04a8991`
M5 foundation: `c87fafc`
Git status before this checkpoint commit: only M5 evidence/checkpoint docs;
generated wheel/manifest/pins/EXEs and task-work evidence are ignored/outside repo.

## Decisions

- Keep the private Ubuntu WSL appliance, Inno Setup, Go launcher, and shared
  LanEx installers. Docker is default; Podman is an explicit alternative.
- Windows 11 x64 is primary. Windows 10 remains unadvertised pending its real
  acceptance leg. ARM64 remains rejected for the amd64 appliance.
- Windows locks LibreLane 3.0.4 + Ciel 2.6.1. PDK/image/GDS3D pins come from
  that exact build manifest; ordinary project dependency ranges are unchanged.
- Authority requires owner SID, install UUID, exact HKCU registration ID/path,
  and matching Linux marker. A distro name is never ownership proof.
- Main stays untouched until Akshat tests the finished M8 candidate and merge is
  explicitly authorized. No release/publication/contact is authorized yet.
- Setup is original-user/per-user. Only the hash-bound, allowlisted two-feature
  worker elevates. Resume is owner HKCU + manual shortcut, two attempts total.
- Base provisioning and strict selected-component finalization are separate.
  Setup terminates only its owner-bound appliance between them.

## Completed M0-M4 / M5 progress

- M0 adopted the handoff, protected existing distros, fixed the stale sudo test,
  added branch CI, and established isolated Linux/Windows baselines.
- M1 bound exact source/wheel/scripts/manifest and owner/appliance identities;
  malformed/foreign/newer state and name-only mutation are rejected.
- M2 added structured preflight, feature-only UAC, owner resume, bounded restart,
  capable-WSL reuse, targeted termination, and user-facing support behavior.
- M3 synchronously installs and verifies every selected component after the
  owner-bound systemd boot; partial work never becomes final-ready.
- M4 classifies network/package failures, preserves WSL DNS/VPN/proxy strategy,
  applies bounded apt/dpkg recovery, and defers the Windows app window until the
  strict health endpoint is reachable.
- M5 now has a manifest-bound recommended/custom/minimal selection contract,
  selection-file validation, dependency/family/library rejection, measured
  download/install/extraction/run estimates, and matching minimal finalization
  semantics. Wizard/progress/cancel/diagnostics work remains unfinished.
- Details/evidence: `M0-BASELINE.md`, `M1-IDENTITY.md`, `M2-PREFLIGHT.md`,
  `M3-COMPONENTS.md`, `M4-NETWORK.md`, `M5-PROGRESS.md`.

## Verified M4 evidence

Evidence: `C:\Users\itsva\Documents\Codex\2026-09-09\from-m0-to-m3-is-done\work\m4-evidence-20260909`.

- Windows focused suite: **110 passed, 2 platform skips**; isolated Ubuntu
  M4 focus: **51 passed**; launcher tests/vet and both ShellCheck legs passed.
- Inno compiled exact source `04a899175d870b62c8ae82e490b37407e0d68b59`.
- Proof Setup SHA256:
  `ee3a489e2caf76471ea3b2a57fda59fa5437c661c2a7bec4ccd0e0a9b054aa4e`.
- A broader Ubuntu run found one missing CI implication row, now fixed, plus five
  unrelated host-contamination failures from pre-existing PDK/GDS3D state. It
  is not claimed as a clean full-suite pass; M3's isolated full baseline stands.

## Verified M5 foundation evidence

- Windows selection/provision/network suite: **74 passed**.
- Inno Setup 6 compiled with current setup-worker hash and exact source define.
  This was compile proof only, not an installed or test-ready M5 candidate.
- Recommended resolves to Docker + image + five native tools + sky130A/all;
  minimal resolves to no engine/image/native tools/PDKs. Invalid dependency,
  family and library combinations fail before WSL mutation.

## Current / next action

Continue M5 in `lanex.iss`: consume the planner from interactive and documented
silent selection inputs, display/recheck per-volume estimates, then implement
bounded live progress, diagnostics, cooperative cancellation and U13 fixtures.

## Outstanding acceptance / protected resources

- M5 UI/protocol and M6-M8 pending. No Setup installed; no real WSL import/provision/finalize,
  Docker/Podman daemon mutation, PDK/image download, WSLg/GUI, restart, UAC split,
  offline, uninstall/data-removal, or RTL-to-GDS case ran for this candidate.
- Real EXE legs require a disposable Windows VM/Akshat machine. Reboot,
  firmware/security changes, publication, and merge remain explicit boundaries.
- Existing `Ubuntu`, `lanex`, `Ubuntu-22.04`, defaults/data, and
  `%LOCALAPPDATA%\LanEx`/legacy profile remain protected and unchanged.
- Ubuntu ran isolated temp-venv tests and ShellCheck only; no distro/VM/service
  was created, stopped, globally shut down, or provisioned. Temp Linux venvs
  self-removed; owned scratch/evidence remains under this task's `work`.
