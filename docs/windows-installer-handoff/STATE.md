# LanEx installer checkpoint

Date: 2026-09-12
Stage: M0-M7 complete; remediated M8 test.3 candidate prepared for Akshat.
Canonical pack: `C:\Users\itsva\lanex\docs\windows-installer-handoff`.
Repo: `C:\Users\itsva\lanex`
Branch: `windows-installer-support`
Candidate source: `fd9695cf578460a1818388837410de9fadb0aefb`
Git status before final checkpoint: only this STATE/evidence update.

## Milestones and decisions

- M0: `1d60f2a`, `ff82cfc`; M1: `f75c156`; M2: `39dd4c4`.
- M3: `bfc1ad3`, `eebc69e`; M4: `4aa748d`, `2f79507`, `04a8991`.
- M5: `c87fafc`, `3bc4498`; M6: `1ecbf35`.
- M7: `5b96c17`, `0c52726`, `da2beb3`, `82f91da`.
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
- W01 FAIL: inline JSON lost quoting at the Inno/PowerShell boundary, so saved
  state validation failed before feature or distro mutation.
- W24 FAIL: `/PROFILE=recommended` hit the same quoting boundary. A later local
  run also proved `/NORESTART` returns 0 unless `/RESTARTEXITCODE=8` is passed.
- Remaining 48 cases are NOT RUN. Diagnostic binaries earn no acceptance PASS.
- The VirtualBox guest later enabled WSL features but every WSL2 import failed
  with `HCS_E_HYPERV_NOT_INSTALLED`; it could not prove M8 acceptance.
- Replacement `1.0.0-test.2` built green at `726b733`, but independent local
  inspection rejected it before testing: Setup's PE version was `1.0.0`, not
  its manifest identity `1.0.0-test.2`. It is not an Akshat test candidate.

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
- `375dd1c` gives Setup distinct full-text and numeric PE versions, maps
  `test.N` to numeric build `N`, and makes CI verify both fields after compile.
- `e0f9828` normalizes Inno's space-padded PE text before the CI comparison;
  the first push run proved the gate fails closed on an unequal raw value.
- Detailed implementation/test evidence: `M8-REMEDIATION.md`.

## Verified local evidence

- Prepared VM patch applied cleanly to checkpoint `5f0b48f`; `git diff --check`
  and Windows PowerShell 5.1 parsing passed.
- `python -m pytest lanex/tests/test_windows_setup.py -q`: 47 passed.
- Setup + release + provisioning + network suites: 91 passed.
- Inno Setup 6.3.3 compile passed with preserved candidate payloads strictly as
  a diagnostic syntax/build check; no acceptance identity was assigned.
- Candidate `test.2` artifact: 10/10 SHA256SUMS and repository bundle verifier
  passed; PE inspection then correctly prevented handoff.
- Corrected local version build: text `1.0.0-test.3`, numeric `1.0.0.3`; 51
  setup/release tests plus the final 4 release-gate tests passed.
- Live read-only preflight on this development PC: Windows build 26200, WSL
  2.4.13, both features enabled, kernel no-op passed, decision `ready`.
- The live probe started only WSL's disposable system distro. It did not list,
  start, stop, import, unregister or modify any user distribution.
- Candidate-source CI `34635954411`, Windows `34635954392`, and Differential
  `34635954459` passed; candidate dispatch `34637352598` passed unpublished.
- `1.0.0-test.3`: Setup `2fb685d20bed867dd465819b2966e9c42730f9e41882494dd80eb52a7e50a267`;
  rootfs `5c93089d8833554fe1b83cbe11530cee96eab83db77398ca4d2ef0464d00b5f6`.
- Independent candidate verification: 10/10 hashes, manifest reproduction, PE
  text/numeric versions, signatures declared unsigned and rootfs archive passed.

## Current / next action

- Tester bundle, note and fresh 50-case ledger are in the 2026-09-11 Codex task
  `outputs`; only `test.3` is eligible for the next test pass.
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
