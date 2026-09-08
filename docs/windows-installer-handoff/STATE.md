# LanEx installer checkpoint

Date: 2026-09-08
Stage: M0-M2 complete; M3 is next.
Canonical pack: `C:\Users\itsva\lanex\docs\windows-installer-handoff`.
Repo: `C:\Users\itsva\lanex`
Branch: `windows-installer-support`
M0 commits: `1d60f2a`, `ff82cfc`
M1 implementation commit: `f75c1568254c4b8ce5581be49f66d8653b17709c`
M2 implementation commit: `39dd4c439d319ce9a37c9f5aaa0262b6f2567ab2`
Git status before this checkpoint commit: only M2 evidence/checkpoint docs
modified; generated wheel/manifest/pins/EXEs are ignored.

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
- Setup is original-user/per-user. Only the hash-bound, allowlisted two-feature
  worker elevates. Resume is owner HKCU + manual shortcut, two attempts total
  and once per boot. Existing capable WSL is reused without a global default
  change or global shutdown.

## Completed M0

- Adopted canonical handoff; inventoried/protected `Ubuntu`, `lanex`, and
  `Ubuntu-22.04`; generated the 13-tool/seven-PDK capability inventory.
- Repaired stale sudo regression and added Windows branch CI coverage.
- Full isolated Linux baseline: 737 passed, 6 explicit environment skips;
  frontend 41 passed; focused installer/CI 55 passed; wheel and Go checks pass.
- Detail/evidence: `M0-BASELINE.md` and its recorded M0 evidence path.

## Completed M1

- Exact branch/tag/SHA/local wheel is bundled with shared install/provision/
  selftest payloads; CI uses the actual checkout and immutable manifest pins.
- Atomic owner state binds SID/install UUID to exact HKCU WSL GUID/path and Linux
  marker. Foreign `lanex` gets a distinct name; malformed/newer/wrong-owner state
  and name-only mutation are rejected. Repair is same-build/readiness-only.
- Full design, legacy migration boundary and hashes: `M1-IDENTITY.md`.

## Verified M1 evidence

- **26 Windows + 62 isolated Linux tests**, Go/vet/format/build, shell syntax,
  shellcheck, YAML and Inno compile passed. Evidence path is in `M1-IDENTITY.md`.

## Completed M2

- Structured preflight distinguishes architecture/OS, firmware, hypervisor,
  feature, pending-reboot, old-WSL/query-failure and ready states. Unknown is
  not firmware-disabled; active hypervisor overrides false firmware signals.
- Original user owns launcher/state/appliance/shortcuts after feature-only UAC.
  Each feature result is independently checked and its original output retained.
- Exact staged Setup and choices survive UAC/restart. Verified owner HKCU resume
  plus manual Continue fallback is boot-bound and loop-limited. Successful setup
  clears only owned continuation entries.
- Existing modern WSL is not unconditionally updated; no default-version or
  all-distro shutdown mutation remains. User docs reflect x64/19044 technical
  floor, per-user paths, policy behavior, resume and data-preserving uninstall.

## Verified M2 evidence

Detail: `M2-PREFLIGHT.md`. Evidence: `C:\Users\itsva\Documents\Codex\2026-09-08\implement-the-lanex-windows-installer-handoff-3\work\m2-evidence-20260908`.

- Hermetic Windows setup/preflight/resume: **29 passed**; PowerShell parse,
  workflow YAML and Inno 6.3.3 compile pass; `git diff --check` pass.
- Wider Windows regression: **76 passed, 3 skipped**; four LibreLane/Ciel tests
  unavailable in this host interpreter, same recorded M1 environment limitation.
- Clean-source Setup: SHA256 `ee3287a480083a1ba31b005ff4d71f54328007acb701fbe44af48422fa0fd6df`,
  5,101,316 bytes. M2 proof artifact only, not the Akshat candidate.

## Current / next action

Start M3: shared base/finalize provisioning and selected-component readiness.
Read M3, A01-A03/A15-A16, U02-U03/U06-U09 and W11-W15/W18-W19.

## Outstanding acceptance / protected resources

- M3-M8 pending. No new Setup installed; no real WSL import/provision, Docker
  daemon, PDK download, WSLg/GUI, restart, UAC-account, offline,
  uninstall/data-removal, or RTL-to-GDS case ran for this candidate.
- Real EXE legs require disposable Windows VM/Akshat machine. Reboot,
  firmware/security changes, publication, and merge remain explicit boundaries.
  The M2 EXE must not be sent as the finished build.
- Existing `Ubuntu`, `lanex`, `Ubuntu-22.04`, defaults/data, and
  `%LOCALAPPDATA%\LanEx`/legacy profile remain protected and unchanged.
- Ubuntu was used only for isolated venv tests/pin export and may be running; do
  not globally shut WSL down. No distro/VM/service/helper created.
- Owned scratch: this task's `work` plus ignored repo build artifacts. No
  secrets are stored in repository or evidence.
