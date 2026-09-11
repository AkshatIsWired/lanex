# LanEx installer checkpoint

Date: 2026-09-11
Stage: M0-M7 complete; M8 candidate 1.0.0-test.1 failed; remediation committed.
Canonical pack: `C:\Users\itsva\lanex\docs\windows-installer-handoff`.
Repo: `C:\Users\itsva\lanex`
Branch: `windows-installer-support`
HEAD: `7e9712ff3f3162c5aecfe4d396c3c2e4e54746c9`
Git status after source commit: clean, branch ahead of origin by 1.

## Milestones and decisions

- M0: `1d60f2a`, `ff82cfc`; M1: `f75c156`; M2: `39dd4c4`.
- M3: `bfc1ad3`, `eebc69e`; M4: `4aa748d`, `2f79507`, `04a8991`.
- M5: `c87fafc`, `3bc4498`; M6: `1ecbf35`.
- M7: `5b96c17`, `0c52726`, `da2beb3`, `82f91da`.
- M8 transfer checkpoints: `52a99ce`, `5f0b48f`.
- Keep the private Ubuntu WSL appliance, Inno Setup, Go launcher and shared
  LanEx installers. Docker is default; Podman is the explicit alternative.
- Windows 11 x64 is primary. Windows 10 stays unadvertised pending evidence;
  ARM64 stays rejected for this amd64 appliance.
- Existing distributions are never inferred-owned. Ownership requires SID,
  install UUID, exact HKCU registration/path and the Linux marker.
- Main stays untouched until Akshat tests the replacement candidate and merge
  is explicitly authorized. Publication/contact are not authorized.

## Failed locked candidate

- Candidate `1.0.0-test.1`, source `82f91daa977d713886013842c78916f139d08dd4`.
- Setup SHA256: `2edb9910bf449658843d4bb50bcecd9fb0bcc7c2185bd7c7d3438561207d130e`.
- Rootfs SHA256: `0307a08b255aac36d2e6483db197cbfe442cbfc177e70c7ce1cfdb156f46d8fd`.
- W01 FAIL: inline JSON lost quoting at the Inno/PowerShell boundary, so saved
  state validation failed before feature or distro mutation.
- W24 FAIL: `/PROFILE=recommended` hit the same quoting boundary. A later local
  run also proved `/NORESTART` returns 0 unless `/RESTARTEXITCODE=8` is passed.
- Remaining 48 cases are NOT RUN. Diagnostic binaries earn no acceptance PASS.
- The VirtualBox guest later enabled WSL features but every WSL2 import failed
  with `HCS_E_HYPERV_NOT_INSTALLED`; it could not prove M8 acceptance.

## Handback and remediation

- VM handback ZIP and adjacent SHA256 matched
  `bcdb87da711ce28d2b38e11f3a290991703823e61984191bddf699a51895b63b`.
- All 77 files listed in the handback `SHA256SUMS.txt` verified after extraction.
- `7e9712f` applies the prepared file-backed JSON, RedirectionGuard copy fallback,
  companion-rootfs resume staging and exact-hash MSIX LocalCache resume fix.
- It also requires a real WSL system-distro no-op before `ready`; a true
  `HypervisorPresent` flag alone no longer proves the WSL2 utility VM can start.
- Kernel-start and `wsl --import` failures now atomically record durable
  `failed` state and preserve existing distributions/data.
- Unattended documentation now requires
  `/NORESTART /RESTARTEXITCODE=8` for a reliable restart-required exit code.
- Detailed implementation/test evidence: `M8-REMEDIATION.md`.

## Verified local evidence

- Prepared VM patch applied cleanly to checkpoint `5f0b48f`; `git diff --check`
  and Windows PowerShell 5.1 parsing passed.
- `python -m pytest lanex/tests/test_windows_setup.py -q`: 47 passed.
- Setup + release + provisioning + network suites: 91 passed.
- Inno Setup 6.3.3 compile passed with preserved candidate payloads strictly as
  a diagnostic syntax/build check; no acceptance identity was assigned.
- Live read-only preflight on this development PC: Windows build 26200, WSL
  2.4.13, both features enabled, kernel no-op passed, decision `ready`.
- The live probe started only WSL's disposable system distro. It did not list,
  start, stop, import, unregister or modify any user distribution.

## Current / next action

- Push the two focused commits to `origin/windows-installer-support`.
- Wait for branch CI and differential workflows at the exact replacement SHA.
- If green, dispatch unpublished candidate `1.0.0-test.2` with empty release
  tag, `publish_release=false`, and no acceptance-evidence path.
- Download and independently verify the candidate bundle and all manifest/hash
  bindings. Prepare a new M8 transfer kit bound only to that exact source/EXE.
- Restart all 50 M8 cases at W01 on bare-metal Windows or a Hyper-V Generation 2
  VM with working exposed virtualization extensions.

## Outstanding / protected resources

- No replacement-candidate Setup/uninstaller, import/finalize, daemon/PDK,
  WSLg/GUI, restart/UAC, offline, export/unregister or reinstall case has run.
- Existing `Ubuntu`, `lanex`, `Ubuntu-22.04`, their defaults/data, and
  `%LOCALAPPDATA%\LanEx`/legacy profile remain protected and unchanged.
- No user distro, VM, service, release, tag or `main` ref was created, removed,
  stopped, published or changed in this development session.
- The diagnostic EXE under this task's `work` directory is not a candidate and
  must never be sent to Akshat or credited in the acceptance ledger.
