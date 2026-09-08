# LanEx installer checkpoint

Date: 2026-09-09
Stage: M0-M3 complete; M4 is next.
Canonical pack: `C:\Users\itsva\lanex\docs\windows-installer-handoff`.
Repo: `C:\Users\itsva\lanex`
Branch: `windows-installer-support`
M0 commits: `1d60f2a`, `ff82cfc`
M1 implementation: `f75c1568254c4b8ce5581be49f66d8653b17709c`
M2 implementation: `39dd4c439d319ce9a37c9f5aaa0262b6f2567ab2`
M3 implementation: `bfc1ad3`, `eebc69e`
Git status before this checkpoint commit: only M3 evidence/checkpoint docs;
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

## Completed M0-M2

- M0 adopted the handoff, protected existing distros, fixed the stale sudo test,
  added branch CI, and established isolated Linux/Windows baselines.
- M1 bound exact source/wheel/scripts/manifest and owner/appliance identities;
  malformed/foreign/newer state and name-only mutation are rejected.
- M2 added structured preflight, feature-only UAC, owner resume, bounded restart,
  capable-WSL reuse, targeted termination, and user-facing support behavior.
- Details and evidence: `M0-BASELINE.md`, `M1-IDENTITY.md`,
  `M2-PREFLIGHT.md`.

## Completed M3

- `provision.sh base|finalize` logs deferred stages explicitly; bare and baked
  paths converge after the owner-bound systemd boot.
- Finalization runs as the appliance user and synchronously installs/verifies
  selected native tools, pinned GDS3D, exact image digest, and PDK libraries.
- `--setup-check` is read-only/machine-readable and any failed selected
  postcondition keeps Setup nonzero. Repair skips already verified work.
- PDK fetch/enable is argv-safe, family-serialized, retry-classified, cache/data
  preserving, and completion-bearing for both CLI and async UI wrapper.
- Docker must use the appliance-local socket. Selected Podman is honored without
  silent Docker substitution. Default sky130A expands to all catalog libraries.
- Full parity/design/evidence: `M3-COMPONENTS.md`.

## Verified M3 evidence

Evidence: `C:\Users\itsva\Documents\Codex\2026-09-08\implement-the-lanex-windows-installer-handoff-6\work\m3-evidence-20260909`.

- Windows checkpoint suite: **67 passed**; corrected component/tool focus:
  **57 passed**.
- Isolated Ubuntu locked environment: focused **62 passed, 21 skipped**; full
  **758 passed, 27 explicit platform skips**.
- Git Bash syntax, provision/selftest ShellCheck, Python compile, PowerShell
  parse, workflow YAML and Inno 6.3.3 compile passed; `git diff --check` passed.
- Exact source `eebc69e3245b757377965e6662f524c6cceacf72`; final wheel SHA256
  `afe5d313521514cb86ac27ceec0ad1bf00ad5d0ee3664ddbd66082c9e5e93c09`.
- M3 proof Setup SHA256 `153617d4efaffe139456e631befe10d2e373d14a07b6e5ac8583d9d6c522075c`,
  5,109,941 bytes. It is not the finished Akshat candidate.

## Current / next action

Start M4 network diagnosis/recovery. Read M4, A13-A16, and applicable U08/W16
cases; preserve the M3 finalizer contracts and avoid broad DNS replacement.

## Outstanding acceptance / protected resources

- M4-M8 pending. No Setup installed; no real WSL import/provision/finalize,
  Docker/Podman daemon mutation, PDK/image download, WSLg/GUI, restart, UAC split,
  offline, uninstall/data-removal, or RTL-to-GDS case ran for this candidate.
- Real EXE legs require a disposable Windows VM/Akshat machine. Reboot,
  firmware/security changes, publication, and merge remain explicit boundaries.
- Existing `Ubuntu`, `lanex`, `Ubuntu-22.04`, defaults/data, and
  `%LOCALAPPDATA%\LanEx`/legacy profile remain protected and unchanged.
- Ubuntu ran isolated temp-venv tests and ShellCheck only; no distro/VM/service
  was created, stopped, globally shut down, or provisioned. Temp Linux venvs
  self-removed; owned scratch/evidence remains under this task's `work`.
