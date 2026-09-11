# M8 failed-candidate remediation

Date: 2026-09-11
Source commits: `7e9712ff3f3162c5aecfe4d396c3c2e4e54746c9`,
`375dd1c7111f2606527a568dd0494a29c00eced2`,
`e0f98287db5e49c9b3b07e89bdfd569aff4de371`

## Scope

The locked `1.0.0-test.1` candidate remains a NO-GO. W01 and W24 failed, and
the 48 unrun cases remain NOT RUN. This source change repairs the observed
boundaries but does not convert any diagnostic run into candidate acceptance.

## Implemented contracts

1. Inno stages selection JSON in UTF-8 files and passes `-ChoicesPath` to the
   PowerShell worker, avoiding raw Windows command-line quote loss.
2. Running-EXE staging has an unelevated PowerShell copy fallback and retains
   the worker's exact-SHA check.
3. Owner-bound automatic resume accepts an identical installer presented via
   an MSIX LocalCache alias; exact bytes, owner state, restart identity and the
   bounded trigger remain mandatory.
4. A verified companion rootfs is retained beside the cached resume installer.
5. Preflight starts WSL's system distro with `/bin/true`. `wsl --status` and
   `HypervisorPresent` no longer suffice to claim the WSL2 kernel is usable.
6. Kernel-start and import failures record durable `failed` state before Setup
   exits, leaving user-owned distributions untouched.
7. Unattended instructions require `/RESTARTEXITCODE=8` with `/NORESTART`.
8. Candidate prerelease text and a distinct numeric build are embedded into
   Setup's PE metadata; CI reads the compiled EXE and rejects version drift.

## Local verification

- Handback outer SHA256: PASS.
- Handback `SHA256SUMS.txt`: 77/77 PASS.
- Prepared patch preflight and application: PASS.
- `git diff --check`: PASS.
- Windows PowerShell 5.1 parser for `windows/setup/setup.ps1`: PASS.
- `python -m pytest lanex/tests/test_windows_setup.py -q`: 47 passed.
- `python -m pytest lanex/tests/test_windows_setup.py
  lanex/tests/test_windows_release.py lanex/tests/test_windows_provisioning.py
  lanex/tests/test_windows_network.py -q`: 91 passed.
- Inno Setup 6.3.3 diagnostic compile: PASS. It reused old payloads solely to
  exercise compilation and is not identity-coherent acceptance evidence.
- Live preflight: WSL 2.4.13, systemd and kernel probes passed, decision ready.
- `1.0.0-test.2` passed all ten artifact checks and the bundle verifier, but
  local PE inspection found Setup version `1.0.0`. It was rejected before M8.
- Corrected Inno compile reports text `1.0.0-test.3` and numeric `1.0.0.3`;
  focused setup/release tests: 51 passed.

## Candidate boundary

A replacement candidate must be generated from this committed source, with a
new wheel, manifest, rootfs bindings, Setup hash and candidate identity. Branch
CI and differential tests must pass at that exact SHA before the unpublished
artifact is offered for Akshat's testing. Do not publish or merge first.
