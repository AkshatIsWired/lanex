# M5 wizard/progress checkpoint

Date: 2026-09-09
Status: implementation complete; disposable-Windows acceptance pending
Foundation commit: `c87fafc`
Completion commit: `3bc4498`

## Implemented and verified

- Added one manifest-bound selection planner for interactive and unattended
  setup. It accepts a JSON selection file, normalizes the three profiles, and
  rejects unknown tools, PDKs, libraries, multiple variants from one family,
  and image/PDK choices without Docker or Podman.
- Recommended is exactly Docker, the matched flow image, Verilator, Icarus,
  Graphviz, GTKWave, GDS3D, and sky130A with all locked family libraries.
  Minimal explicitly selects no engine, image, native tools, or PDK and remains
  subject to base Python/runtime readiness.
- Old M3/M4 state without a profile migrates to the equivalent custom choice
  without replacing the owner, source, appliance, or resume identities.
- The Linux finalizer consumes the same profile semantics and does not invent
  an engine/image/PDK for a deliberate minimal setup.
- Estimates separately report network bytes, installed bytes, extraction
  headroom, practical run headroom, AppData-volume need and temporary-volume
  need. They disclose their measured/catalog basis and explicitly say that an
  interrupted rootfs transfer restarts rather than claiming range resume.
- The Inno wizard now exposes recommended/custom/minimal profiles, Docker or
  Podman, every locked PDK variant, and every advanced non-required library.
  Required libraries are automatically retained; a PDK automatically retains
  the matched flow image.
- The review page displays choice-derived network, installed, run-headroom and
  temporary-space estimates. Setup rechecks the actual AppData/temp volumes
  before rootfs work and again before image/PDK finalization, crediting verified
  completed state and the checksum-valid rootfs cache.
- Long WSL commands stream through `ExecAndLogOutput` into a 400-line UI buffer
  while a timer keeps phase/elapsed activity moving for silent children. The
  on-disk log rotates at 5 MiB and can be opened, copied or saved.
- Cancellation never kills `wsl.exe` or the LanEx server. Base provisioning
  checks an owned `/run/lanex/setup.cancel` marker between safe boundaries; the
  Python finalizer cancels only its active tool process group and never starts
  the next component. Rootfs fallback/finalization cannot continue after cancel.
- Resume revalidates the saved choices and current readiness. Owner state records
  distinct ready, failed, cancelled and restart-required outcomes. Silent mode
  has validated `/PROFILE`, `/SELECTIONS`, and `/ALLOWWSLUPDATE` behavior and no
  hidden Retry/update prompt.

## Proof

- `python -m pytest lanex/tests/test_windows_setup.py lanex/tests/test_windows_provisioning.py lanex/tests/test_windows_network.py -q`
  -> **79 passed**.
- The broader Windows-adjacent selection added 34 passes and one known
  environment failure: `test_installer.py` expects installed LibreLane, which
  is absent from this Windows interpreter (`compat.get_version() == unknown`).
- Git Bash `bash -n windows/provision/provision.sh` passed.
- Inno Setup 6 compiled an exact proof artifact from source `3bc4498` and the
  generated manifest/payload hashes below.
- `git diff --check` passed (Git emitted only the repository's Windows
  line-ending conversion notices).

Proof hashes:

- Setup: `bd5468d9bc4570aab47fdcd1ab0b423a305871bcd6625ac3666d6621ad8dac6f`
- manifest: `4ac96eaaf6df04cf17cc12766cc4f22a0a35613a659e7462813b2345a8d37ece`
- wheel: `92e021dbe08820e45e5abb840c2bdc922c5564d50f505775a3f577a0464a80aa`
- launcher: `575f7e01467e6943b7842cfc0ae430fc38b2b6a62142348b7a967d0fc2b8d43f`

## Still external

No Setup was installed or launched. Actual visual responsiveness, keyboard
navigation, 125–200% DPI, cancel during real apt/image/PDK work, restart choice
survival, and saved diagnostics still require a disposable Windows VM/Akshat
machine. The proof EXE is a local M5 artifact, not the M8 tester candidate. The
development PC's WSL distributions and LanEx data were not changed.
