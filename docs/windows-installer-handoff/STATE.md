# LanEx installer checkpoint

Date: 2026-09-10
Stage: M0-M6 implementation complete; M7 is next.
Canonical pack: `C:\Users\itsva\lanex\docs\windows-installer-handoff`.
Repo: `C:\Users\itsva\lanex`
Branch: `windows-installer-support`
M0: `1d60f2a`, `ff82cfc`
M1: `f75c156`
M2: `39dd4c4`
M3: `bfc1ad3`, `eebc69e`
M4: `4aa748d`, `2f79507`, `04a8991`
M5: `c87fafc`, `3bc4498`
M6 implementation: `1ecbf3562c734348dd96af4180119ad486d4d1e8`
Git status before this checkpoint commit: only M6 checkpoint docs; generated
wheel/manifest/pins/EXEs and task evidence are ignored/outside the repository.

## Decisions

- Keep the private Ubuntu WSL appliance, Inno Setup, Go launcher, and shared
  LanEx installers. Docker is default; Podman is the explicit alternative.
- Windows 11 x64 is primary. Windows 10 remains unadvertised pending its real
  acceptance leg. ARM64 remains rejected for the amd64 appliance.
- Windows locks LibreLane 3.0.4 + Ciel 2.6.1 and immutable image/PDK/GDS3D pins.
- Authority requires owner SID, install UUID, exact HKCU registration ID/path,
  and matching Linux marker. A distro name or health service string is never
  ownership/server proof.
- Setup is original-user/per-user. Machine changes stay allowlisted/elevated;
  appliance import, state, shortcuts and resume remain with the original user.
- Main stays untouched until Akshat tests the finished M8 candidate and merge is
  explicitly authorized. Publication/contact are not authorized.

## Completed M0-M6

- M0 established protected-resource inventory, isolated baselines and branch CI.
- M1 bound exact payload/source/manifest plus owner/appliance state identities.
- M2 added preflight, feature-only UAC and owner-bound bounded restart/resume.
- M3 synchronously installs and strictly verifies every selected component.
- M4 added network/package recovery and Windows-reachable launch gating.
- M5 added manifest-bound choices, estimates, responsive progress/diagnostics,
  cooperative cancellation, readiness-derived outcomes and silent inputs.
- M6 requires ready owner state and live registration before launch; starts as
  the explicit app user; binds record/health to instance + source; scopes mutex
  and profile; checkpoints/restores explicit updates; and provides keep,
  export, and identity-checked erase uninstall paths.
- Details: `M0-BASELINE.md` through `M6-LIFECYCLE.md`.

## Verified M6 evidence

Evidence directory:
`C:\Users\itsva\Documents\Codex\2026-09-09\implement-the-lanex-windows-installer-handoff-2\work`.

- Python M6 focus: **113 passed**; final narrow rerun: **74 passed**.
- Go formatting, Windows test cross-compile, `go vet`, launcher build and the
  cross-compiled Windows test binary passed.
- ShellCheck + `bash -n` on provisioning, PowerShell 5.1 parse, Inno compile,
  and `git diff --check` passed.
- Exact proof source: `1ecbf3562c734348dd96af4180119ad486d4d1e8`.
- Setup SHA256: `30bfc80830fe1e0b19dba7f0a8fe6e4f809896e169ccf016493fece7bd35829c`.
- Launcher: `f0929c678c4b4b18121c83f89668a13c3be5d305f1790359b31e586b04873442`.
- Manifest: `701d1a4d2523b22aa9b2b369b74374b94f318d78727f8e7502d059f488ddbb1f`.
- Wheel: `ca4a14dea72b2ea10f44f32d5a85d9bc3500a887add4e657ff6d82688d87f39f`.

## Current / next action

Start M7 CI/artifact/release gates from source `1ecbf356`. Do not install the M6
proof EXE on this PC; M8 produces the Akshat tester candidate.

## Outstanding acceptance / protected resources

- M7-M8 pending. No real Setup/uninstaller, WSL import/finalize, daemon/PDK
  download, WSLg/GUI, restart/UAC, offline, export, unregister or RTL-to-GDS
  candidate case ran.
- Real M6 port/two-user/legacy Program Files/update rollback/uninstall/reinstall
  legs require disposable Windows VMs or Akshat's machine.
- Existing `Ubuntu`, `lanex`, `Ubuntu-22.04`, their defaults/data, and
  `%LOCALAPPDATA%\LanEx`/legacy profile remain protected and unchanged.
- Ubuntu ran compiler/static checks only. No distro/VM/service was created,
  provisioned, terminated or globally shut down.
