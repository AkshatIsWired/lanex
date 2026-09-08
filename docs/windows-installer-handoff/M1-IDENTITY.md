# M1 identity and payload checkpoint

## Observable contract

- A candidate installs the wheel and scripts built from its exact checkout.
  Branch, tag, SHA, and fork repositories remain supported for the universal
  installer; Windows never substitutes a moving `main` payload.
- The build manifest hashes every executable setup payload and records the
  source commit, locked LibreLane/Ciel versions, image digest, PDK family pins,
  GDS3D commit, rootfs identity, target, and size estimates.
- Install state is schema-versioned, owner-SID scoped, and atomically replaced.
  It preserves choices, original/current installer hashes, source/build
  identity, boot/restart counters, component fingerprints, and the exact
  appliance registration identity/path.
- A distro name alone grants no repair or deletion authority. A foreign
  `lanex` collision receives an owner-derived distinct name; the launcher reads
  that name from a validated data-only configuration.
- Matching Repair validates Windows registration + Linux marker + appliance
  self-test without invoking apt or pip. A changed build requires explicit
  `/UPDATE=1`; an identity mismatch is left untouched.
- Current uninstall removes launcher/shortcuts only and preserves the appliance,
  projects, PDKs, installer state, cache, and pre-existing browser profile.

## Locked build inputs

- LibreLane `3.0.4`; Ciel `2.6.1` (Windows-only constraints file).
- LibreLane image `ghcr.io/librelane/librelane:3.0.4`; packaging resolves and
  records its registry digest.
- PDK family pins are exported from that exact environment, not a developer
  interpreter. Current resolved families: sky130
  `8afc8346a57fe1ab7934ba5a6056ea8b43078e71`, gf180mcu
  `54435919abffb937387ec956209f9cf5fd2dfbee`, ihp-sg13g2
  `c4b8b4e5e7a05f375cca3815d51b3a37721fbf5c`.
- GDS3D remains source-built. Packaging records the resolved upstream commit;
  the later build/finalization milestone must consume that pin instead of a
  moving shallow clone.

## Legacy Program Files migration plan

M1 deliberately does not change `PrivilegesRequired=admin`; M2 owns the
unelevated/original-user split. Before that change, migration must:

1. Inspect the existing AppId uninstall metadata, HKCU WSL registration, base
   path, and Linux contents read-only. Never infer ownership from `lanex` alone.
2. Treat an existing owner-scoped state + matching registration/path/marker as
   authoritative. Treat legacy installs as adoptable only when the unchanged
   AppId metadata, historical canonical distro path, expected app user, and
   LanEx contents all agree; otherwise leave them untouched and use a distinct
   appliance.
3. Install the launcher per-user and write its validated `appliance.json`
   without moving/unregistering the appliance or browser profile.
4. Remove old Program Files launcher/shortcuts only after the new original-user
   launcher starts the same verified appliance. Failure rolls back launcher
   files/metadata, never WSL data.
5. Test original-admin and standard-user-with-different-admin cases with project,
   run-result, PDK, and browser-profile sentinels before advertising migration.

## Verification boundary

Hermetic state/source tests, PowerShell parsing, Git Bash syntax, shellcheck,
Windows Go test/vet/build, Linux installer/PDK regressions, and Inno compilation
are safe on the development PC. A real Setup run, WSL import, reboot/resume,
UAC account split, Linux marker verification in a new appliance, and destructive
legacy/uninstall cases require a disposable Windows VM or Akshat's test machine.
