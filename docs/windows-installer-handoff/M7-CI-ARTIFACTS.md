# M7 CI, artifacts, and release gates

Date: 2026-09-10
Candidate source: `82f91daa977d713886013842c78916f139d08dd4`
Version: `1.0.0-test.1`

## Implemented

- A Linux `candidate-inputs` job builds the checkout wheel once, installs it
  under the locked LibreLane/Ciel environment, exports PDK pins, resolves the
  immutable image digest and GDS3D commit, and passes hash-bound artifacts to
  both the rootfs bake and Windows build. PRs never fall back to main.
- The baked rootfs records selected Ubuntu package and Python dependency
  versions without credentials, builder identity, network configuration, or
  caches. Bare provisioning and baked selfcheck remain separate jobs.
- Dispatch builds provide a self-contained candidate: Setup accepts a verified
  adjacent rootfs without requiring a fictitious release URL. The wheel keeps
  its valid PEP 427 filename through bake, manifest, and Setup extraction.
- Candidate assembly verifies wheel, PDK pins, rootfs, inventory, manifest,
  launcher, and Setup hashes before uploading one tester artifact.
- The only release-upload path requires explicit dispatch publication, exact
  candidate-bound M8 evidence, same-SHA CI and Differential success, and a new
  release tag. It stages a draft, uploads without `--clobber`, re-downloads and
  hashes assets, then publishes. Ordinary pushes, PRs, tags, and candidate
  dispatches cannot publish.
- Configured signing now requires valid timestamped Authenticode signatures on
  both launcher and Setup. This candidate is honestly recorded as unsigned.
- Root CI has same-branch concurrency; Differential retains queued same-branch
  proving runs. The real-browser layout check runs once on Python 3.12 while all
  other Python tests retain the 3.10-3.13 matrix.

## Verified automation

- CI: https://github.com/AkshatIsWired/lanex/actions/runs/34408091271 — success.
  Python 3.10-3.13, frontend behavior/syntax/hygiene, wheel contents, GTKWave,
  compatibility canary, and full SPM RTL-to-GDS passed.
- Windows push: https://github.com/AkshatIsWired/lanex/actions/runs/34408091302
  — success. Exact inputs, Go vet/format/tests/build, Inno compile, shell lint,
  bare Ubuntu provision/selftest/repair passed. Bake/pin/candidate/publish were
  correctly skipped on an ordinary push and are not counted as candidate proof.
- Differential: https://github.com/AkshatIsWired/lanex/actions/runs/34408091301
  — success. Four-path RTL-to-GDS equivalence and live API e2e passed.
- Candidate dispatch: https://github.com/AkshatIsWired/lanex/actions/runs/34408408044
  — success. Rootfs pin, bake/selfcheck, package inventory, Windows build and
  candidate-gate passed; publish was correctly skipped.
- Local: 116 focused Windows contract tests passed; Actionlint, Ruff,
  PowerShell parse, 59 JavaScript syntax checks, `git diff --check`, and actual
  Inno compilation passed. The downloaded candidate's `SHA256SUMS` and manifest
  bindings were independently rechecked.

## Candidate identity

- Actions artifact: `LanEx-Windows-candidate-1.0.0-test.1-20`, artifact ID
  `10126396711`, 417,562,287-byte ZIP, 30-day CI retention.
- Local tester bundle:
  `C:\Users\itsva\Documents\Codex\2026-09-10\implement-the-lanex-windows-installer-handoff\outputs\LanEx-Windows-candidate-1.0.0-test.1-20`.
- Setup SHA256: `2edb9910bf449658843d4bb50bcecd9fb0bcc7c2185bd7c7d3438561207d130e`.
- Manifest SHA256: `fcc3f224ebda1334128886923ffa375b10aaf674bf6b74af60479ddde7bfd707`.
- Rootfs SHA256: `0307a08b255aac36d2e6483db197cbfe442cbfc177e70c7ce1cfdb156f46d8fd`
  (412,555,465 bytes).
- Launcher SHA256: `98d82fd8f53dcf56a8ed04e8fe1a289191c5343cdfb8041e4df017b3099ad924`.
- Wheel SHA256: `c0f28e76a867c1bd775d31c1663149d254244246a0341f7079d563c54dafd37c`.

## M8 boundary

No Setup/uninstaller was executed on this PC. No WSL distribution, user data,
boot/security setting, or public release changed. Actual EXE installation,
restart/UAC, WSLg, daemon/PDK/image finalization, offline flow, update,
uninstall, two-user and fault-injection cases remain M8 work on disposable
Windows environments or Akshat's test machine. Main remains untouched.
