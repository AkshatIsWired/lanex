# M2 preflight, elevation and resume evidence

Implementation commit: `39dd4c439d319ce9a37c9f5aaa0262b6f2567ab2`.
Evidence directory:
`C:\Users\itsva\Documents\Codex\2026-09-08\implement-the-lanex-windows-installer-handoff-3\work\m2-evidence-20260908`.

## Implemented contract

- Schema-1 preflight reports native architecture, Windows build, PC identity,
  hypervisor/firmware signals, both optional-feature states, pending reboot,
  boot identity, WSL status/version and systemd capability. Decisions distinguish
  unsupported architecture/OS, firmware disabled, query failure, feature setup,
  pending restart, old WSL and ready. Hypervisor presence overrides a misleading
  firmware false; unknown firmware is a notice, never a disabled claim.
- Setup now runs as the originating user and installs the launcher per-user.
  Only an allowlisted worker action enabling WSL and Virtual Machine Platform
  uses `runas`. Each DISM result is retained and evaluated independently; only
  codes 0 and 3010 are accepted. The compile-time worker SHA256 is checked before
  elevation and again by the elevated worker.
- Existing capable WSL is reused. Setup no longer changes the global default WSL
  version and never uses global shutdown as recovery. An old WSL update is
  explicit, warns about impact to other WSL work, and must verify capabilities.
- Before UAC/restart, Setup atomically preserves owner SID, choices, source/build
  identity and a hash-verified cached installer. A verified per-user Start-menu
  `Continue LanEx Setup` shortcut is the manual fallback.
- Automatic continuation is HKCU owner-bound, verified after registration, and
  limited to two attempts total and once per boot identity. State records the
  attempt before exposing the trigger, so interruption cannot create an
  unrecorded loop. Automatic resume rejects the same boot, wrong path/hash,
  wrong owner, corrupt state and changed repair identity.
- Successful provisioning clears only the matching owner trigger/shortcut.
  UAC cancellation, policy denial, restart-later and trigger failure retain the
  staged installer and state. No name-only distro mutation was introduced.

## Verified safe checks

- `python -m pytest lanex/tests/test_windows_setup.py -q -p no:cacheprovider`
  — **29 passed** on Windows. The truth table covers ready, x64/OS rejection,
  firmware off/unknown, hypervisor override, features, pending reboot, old WSL,
  query failure, independent feature errors, worker integrity, corrupt/atomic
  state, owner-bound trigger failure, unchanged boot and restart budget.
- Wider Windows-side regression selection — **76 passed, 3 skipped**. Four
  additional tests were unavailable because this host interpreter lacks
  LibreLane/Ciel, matching the recorded M1 environment limitation; no M2 code
  touches those modules.
- Windows PowerShell 5.1 parser: pass. Workflow YAML parse: pass.
- Inno Setup 6.3.3 compile: pass. `git diff --check`: pass.
- Read-only live preflight: AMD64, Windows build 26200, hypervisor present,
  firmware/features enabled, WSL 2.4.13/systemd capable, decision `ready`.
  The host reported an unrelated pending reboot but usable WSL correctly won;
  no distribution was started, stopped, imported or changed.

## Exact clean-source artifact

- Wheel SHA256: `bfe5aa6e0b7d671d7091a7e40b3047e997e4118d6d8729c4f96ad4a0765277ee`.
- Manifest SHA256: `8e5f2fd84be927d69c1408a9de2a8f90a156626e4117e5b9898da59cdb72d427`.
- Worker SHA256: `17e1684eeb52a5bc25cdf6efc682b13270cb428b84cd19cd80d153391d3f2459`.
- Setup SHA256: `ee3287a480083a1ba31b005ff4d71f54328007acb701fbe44af48422fa0fd6df`;
  5,101,316 bytes. This is an M2 compile artifact, not the Akshat candidate.

## Explicit release blockers

W01-W10 still require disposable Windows VMs/hardware: fresh no-WSL feature
enable and real reboot, firmware disabled, feature-pending/hypervisor-disabled,
old inbox WSL, Windows 10 if advertised, ARM64 rejection, different-admin UAC,
denied UAC/policy/different login, repeated reboot/crash, and proof that existing
distributions/defaults/data remain byte-for-byte unchanged. They were not run
on this development PC. M3-M8 remain required before Akshat receives a candidate.

