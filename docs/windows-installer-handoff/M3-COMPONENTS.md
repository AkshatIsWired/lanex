# M3 shared component installation and readiness

## Observable contract

- Setup runs `provision.sh base`, terminates only the owner-bound appliance,
  boots it with systemd, then runs `provision.sh finalize` as the appliance
  user. Bare and baked rootfs paths converge at that same finalizer.
- The saved engine, PDK variants, and libraries are validated against the
  immutable build manifest before any selected-component command runs.
- Docker remains the default; an explicit Podman choice is honored without
  silently substituting Docker. Docker finalization requires the appliance-local
  `/var/run/docker.sock`, never a remote context.
- Native support tools, GDS3D, the matched LibreLane image digest, and every
  selected PDK library complete synchronously. An async `started` response is
  not completion.
- `lanex --setup-check <manifest> --setup-choices <state>` is read-only and
  emits one JSON readiness report. Setup exits nonzero if any selected check
  fails.
- Repair first runs the same strict report. Verified tools/image/PDKs are left
  alone; only missing work is retried. Ciel caches and valid versions are never
  deleted after a failed library addition.

## Universal-stage parity

| Universal/appliance stage | Base | Finalize / postcondition |
|---|---|---|
| Platform, privilege and network preflight | Executed by shared `install.sh` | Rechecked by component commands; M4 owns network classification detail |
| Python, venv/pipx fallback, LanEx, PATH | Executed unchanged | Exact LibreLane 3.0.4 and Ciel 2.6.1 modules verified |
| Git, X11 fonts, Mesa/GL, GTKWave | Universal best-effort stage executes | Selected GTKWave and GDS3D headers/fonts/Mesa/linkage are strict |
| WSL config/default user/systemd | Base writes and verifies | PID 1 must be systemd after the owned-distro restart |
| Container engine | Selected Docker or Podman installed in base | Selected engine must be reachable; Docker context must be local |
| LibreLane image | Explicitly logged as deferred | Manifest reference+digest pulled; a real Yosys command runs in it |
| GDS3D dependencies/build | Explicitly logged as deferred | Shared backend consumes pinned commit; C++ driver, headers, binary, linkage, fonts and Mesa verified |
| Icarus, Verilator, Graphviz | Explicitly logged as deferred | Shared backends install and command probes run; Icarus compiles/runs a bounded smoke design |
| PDKs/libraries | Explicitly logged as deferred | Pinned family fetch+enable completes synchronously and every selected library exists |

## PDK lifecycle changes

- `install_pdk_sync` is the completion-bearing backend; the Tools-page worker is
  now a thin async wrapper that emits its final result.
- Fetch and enable use argv arrays. Manifest validation rejects unknown PDKs,
  libraries, engines, malformed pins, and concurrent variants of one family.
- Family locks serialize sky130A/sky130B writes. Transient fetches use bounded
  exponential backoff; permission/policy/incompatibility/disk failures do not
  repeat. Exhaustion is nonzero and never proceeds to enable.
- Existing versions and resume caches are retained. Readiness checks arbitrary
  Ciel libraries without incorrectly requiring every IO/SRAM/primitive library
  to contain Liberty timing files.

## Verified evidence

Implementation commits: `bfc1ad3`, `eebc69e`. Evidence directory:
`C:\Users\itsva\Documents\Codex\2026-09-08\implement-the-lanex-windows-installer-handoff-6\work\m3-evidence-20260909`.

- Windows-focused selection/state/CI tests: **67 passed**; final component/tool
  focus after selected-engine correction: **57 passed**.
- Isolated Ubuntu locked environment: focused **62 passed, 21 skipped**; full
  suite **758 passed, 27 explicit platform skips**. The temporary Linux venv was
  removed automatically; only the mounted evidence/cache remains.
- Git Bash syntax passed for all four install/provision scripts. ShellCheck
  style gate passed for `provision.sh` and `selftest.sh`.
- PowerShell parse and workflow YAML parse passed. Inno Setup 6.3.3 compiled the
  final source-bound installer.
- Exact source `eebc69e3245b757377965e6662f524c6cceacf72`; wheel SHA256
  `afe5d313521514cb86ac27ceec0ad1bf00ad5d0ee3664ddbd66082c9e5e93c09`;
  proof Setup SHA256
  `153617d4efaffe139456e631befe10d2e373d14a07b6e5ac8583d9d6c522075c`
  (5,109,941 bytes). Manifest wheel/provision/selftest hashes matched.
- Registry/GDS3D pins were re-resolved read-only and match the manifest:
  LibreLane digest `sha256:eab07a50...eecd9`, GDS3D commit `dc6d965...60fe`.

## Verification boundary

No Setup EXE was installed and no PDK/image/tool was downloaded into an
existing user distro. `Ubuntu`, `lanex`, and `Ubuntu-22.04` remain protected.
The proof EXE is not the finished Akshat candidate because M4-M8 are pending.

Still requires a disposable Windows VM/Akshat machine: real bare and baked WSL
imports, systemd/Docker boot, multi-GB image/PDK finalization and retry/cancel,
GDS3D/GTKWave/WSLg windows, offline reopen, reboot/UAC flows, and full SPM GDS.
