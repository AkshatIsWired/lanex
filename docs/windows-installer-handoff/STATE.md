# LanEx installer checkpoint

Date: 2026-09-10
Stage: M0-M7 complete; exact-candidate M8 transfer kit prepared; real Windows acceptance is next.
Canonical pack: `C:\Users\itsva\lanex\docs\windows-installer-handoff`.
Repo: `C:\Users\itsva\lanex`
Branch: `windows-installer-support`
M0: `1d60f2a`, `ff82cfc`
M1: `f75c156`
M2: `39dd4c4`
M3: `bfc1ad3`, `eebc69e`
M4: `4aa748d`, `2f79507`, `04a8991`
M5: `c87fafc`, `3bc4498`
M6: `1ecbf35`
M7: `5b96c17`, `0c52726`, `da2beb3`, `82f91da`
M8 transfer checkpoint: `52a99ce`
HEAD before final handoff refresh: `52a99ce7e5e4234b68e0823ce75b63ddd5856594`
Git status before checkpoint: only this compact checkpoint refresh.

## Decisions

- Keep the private Ubuntu WSL appliance, Inno Setup, Go launcher and shared
  LanEx installers. Docker is default; Podman is the explicit alternative.
- Windows 11 x64 is primary. Windows 10 remains unadvertised pending real M8
  evidence. ARM64 remains rejected for this amd64 appliance.
- Windows locks LibreLane 3.0.4 + Ciel 2.6.1 and immutable image/PDK/GDS3D pins.
- Appliance ownership requires owner SID, install UUID, exact HKCU registration
  ID/path and matching Linux marker. Existing distros are never inferred-owned.
- Main stays untouched until Akshat tests the M8 candidate and merge is
  explicitly authorized. Publication/contact are not authorized.

## Completed M0-M7

- M0-M6: baseline, immutable identities/state, truthful preflight/resume,
  strict selected-component readiness, network recovery, responsive wizard,
  secure launcher and data-preserving lifecycle. Details: M0 through M6 notes.
- M7 builds the checkout wheel once on Linux and passes the exact artifact to
  bake and Windows packaging; PRs have no remote main/base success fallback.
- Dispatch bakes/selftests a companion rootfs, records package versions, builds
  Setup with a valid wheel filename, verifies every manifest-bound hash and
  uploads one self-contained tester artifact.
- One publication job is gated by explicit dispatch authority, matching M8
  evidence, same-SHA CI/Differential success and a new immutable release tag.
  It stages and re-verifies a draft; no `--clobber` path remains.
- Signing verifies timestamped Authenticode on launcher and Setup when secrets
  exist. The current candidate is explicitly unsigned.
- Details: `M7-CI-ARTIFACTS.md`.

## Verified M7 evidence

- Source: `82f91daa977d713886013842c78916f139d08dd4`.
- CI `34408091271`: success — Python 3.10-3.13, frontend, wheel,
  GTKWave, compatibility canary and full SPM RTL-to-GDS.
- Windows push `34408091302`: success — exact inputs, Go vet/format/tests/build,
  Inno compile, shell lint, bare Ubuntu provision/selftest/repair.
- Differential `34408091301`: success — four RTL-to-GDS paths + live API e2e.
- Candidate dispatch `34408408044`: success — live pin, bake/selfcheck,
  inventory, Windows build and candidate gate; publication skipped.
- Artifact `LanEx-Windows-candidate-1.0.0-test.1-20`, ID `10126396711`.
- Setup SHA256: `2edb9910bf449658843d4bb50bcecd9fb0bcc7c2185bd7c7d3438561207d130e`.
- Manifest: `fcc3f224ebda1334128886923ffa375b10aaf674bf6b74af60479ddde7bfd707`.
- Rootfs: `0307a08b255aac36d2e6483db197cbfe442cbfc177e70c7ce1cfdb156f46d8fd`.
- Local bundle: current task `outputs\LanEx-Windows-candidate-1.0.0-test.1-20`;
  all `SHA256SUMS` and manifest bindings independently passed.
- Local focused contracts: 116 passed. Actionlint, Ruff, PowerShell parse,
  59 JS syntax checks, Inno compile and `git diff --check` passed.
- Broad Windows-host pytest was non-gating: 758 passed, 45 platform/dependency
  failures, 14 skipped. Linux CI is the authoritative full-suite result.

## Current / next action

M8 transfer kit prepared at current task
`outputs\LanEx-M8-transfer-kit.zip`.
It includes the exact candidate, complete Git bundle, source snapshot, canonical
handoff, all-case JSON ledger and ready-to-paste Codex prompt. Candidate hashes,
ledger JSON, Git bundle and required ZIP entries passed local verification.

Next: copy the kit to a disposable Windows 11 x64 environment with working
nested virtualization/WSL2, take a clean pre-WSL snapshot, and start W01 using
the exact candidate. Record PASS/FAIL/BLOCKED per case. Do not rebuild between
acceptance and publication.

## Outstanding / protected resources

- No real Setup/uninstaller, WSL import/finalize, daemon/PDK download, WSLg/GUI,
  restart/UAC, offline, export/unregister or reinstall candidate case ran here.
- VirtualBox is not installed on the development PC. Its existing Microsoft
  hypervisor/WSL2 stack is active, so VirtualBox guest WSL2 viability is not yet
  proven; the disposable guest must expose virtualization extensions.
- Existing `Ubuntu`, `lanex`, `Ubuntu-22.04`, their defaults/data, and
  `%LOCALAPPDATA%\LanEx`/legacy profile remain protected and unchanged.
- No distro/VM/service was created, provisioned, terminated or globally shut
  down. No release was published and main was not changed.
