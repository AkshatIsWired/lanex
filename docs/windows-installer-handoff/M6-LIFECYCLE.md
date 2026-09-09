# M6 launcher, update and uninstall checkpoint

Date: 2026-09-10
Status: implementation complete; disposable-Windows acceptance pending
Implementation commit: `1ecbf3562c734348dd96af4180119ad486d4d1e8`

## Implemented and verified

- Launcher startup now requires schema-2 `appliance.json`, the current Windows
  owner SID, ready owner state, and the exact live HKCU WSL registration ID,
  distro name and base path. Missing, stale, foreign and incomplete identity
  stops with a data-preserving Continue/Repair action.
- WSL starts explicitly as the `lanex` appliance user with its writable home.
  The install UUID, source SHA and manifest hash are passed as data-only
  environment values and appear in both `server.json` and `/api/health`.
- Server discovery parses JSON and compares all three immutable identities.
  Ambiguous port scanning and the former `"lanex"` substring match are gone, so
  another LanEx/dev server cannot win a port race or receive the app window.
- The mutex is scoped to owner SID + install UUID + appliance. Browser state is
  kept in an install-ID profile; the pre-existing generic profile is neither
  reused nor removed.
- Ordinary startup no longer recommends global `wsl --shutdown`. Missing or
  non-ready state directs the user to the saved owner-bound Setup/Repair path.
- Explicit updates retain a deep previous-build state checkpoint and archive
  only the existing Python app environment, launch symlinks and Linux identity
  marker. Install/readiness failure restores that archive and old state;
  successful strict readiness commits and removes the rollback checkpoint.
- Uninstall defaults to keep-data, with separate verified export-and-keep and
  explicit permanent-removal paths. Export failure/cancel never reaches erase.
- Permanent removal requires owner SID, exact registration ID/name/path, exact
  Linux marker and matching confirmation UUID. It clears only the matching
  resume hook, unregisters only that appliance, and removes only enumerated
  owner paths after unregister succeeds. Failure restores the prior state phase
  and preserves VHDX/state/cache/logs.
- Explicit erase preserves the historical generic browser profile despite the
  case-insensitive `%LOCALAPPDATA%\LanEx` / `lanex` alias. Windows WSL features,
  host settings and every other distribution remain outside all removal paths.

## Proof

- Windows Python focus (`test_windows_setup`, provisioning, network, instance
  identity and app-window): **113 passed**. The narrower final M6 rerun was
  **74 passed**.
- Windows launcher: Go formatting, Windows cross-compile, `go vet`, launcher
  build, and the cross-compiled test binary all passed (all config/probe/WSL
  tests).
- `shellcheck` and `bash -n` passed for the changed provisioning script;
  PowerShell 5.1 parsing and `git diff --check` passed.
- Inno Setup 6 compiled the exact committed M6 source and regenerated wheel /
  manifest inputs without installing it.

Proof hashes for source `1ecbf3562c734348dd96af4180119ad486d4d1e8`:

- Setup: `30bfc80830fe1e0b19dba7f0a8fe6e4f809896e169ccf016493fece7bd35829c`
- launcher: `f0929c678c4b4b18121c83f89668a13c3be5d305f1790359b31e586b04873442`
- manifest: `701d1a4d2523b22aa9b2b369b74374b94f318d78727f8e7502d059f488ddbb1f`
- wheel: `ca4a14dea72b2ea10f44f32d5a85d9bc3500a887add4e657ff6d82688d87f39f`

## Still external

No Setup/uninstaller was launched. Real port takeover, two simultaneous Windows
users, WSLg, broken Docker startup, old Program Files ownership under original
and different-admin accounts, rollback after a real failed pip install, export,
unregister failure, keep-data reinstall and explicit erase require disposable
Windows VMs/Akshat's test machine. Those are M8 acceptance cases, not claimed
from hermetic fixtures. The development PC's existing WSL distributions and
LanEx data were not changed.
