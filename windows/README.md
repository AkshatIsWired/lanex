# `windows/` — source of the LanEx Windows installer

This tree builds **`LanEx-Setup.exe`**: the installer that lets a Windows user
who has never opened a terminal run LanEx. It is maintainer documentation. Users
want [`docs/INSTALL.md`](../docs/INSTALL.md) instead.

```
windows/
  launcher/    Go source for LanEx.exe — starts the appliance, sits in the tray
  installer/   lanex.iss — the Inno Setup script (preflight, WSL, import, uninstall)
  provision/   provision.sh — runs inside the imported distro, once, as root
               selftest.sh  — asserts a provisioned appliance is actually usable
  setup/       exact build manifest, dependency lock, and durable state worker
```

The design, in one paragraph: LanEx and every tool it drives are Linux programs,
so on Windows LanEx runs in a **private Ubuntu WSL distro** that Setup imports
with `wsl --import` — an appliance, the same pattern Docker Desktop and Rancher
Desktop use. No Microsoft Store, no Ubuntu first-run screen, no contact with the
user's own distros. Uninstall currently removes the Windows launcher while
preserving the appliance and projects; the later identity-checked removal flow
will make permanent data deletion an explicit choice. Each file's header comment explains its own decisions; start with
`installer/lanex.iss`.

Setup itself runs unelevated in the originating account. Its PowerShell worker
returns a schema-1 preflight record (native architecture, Windows build,
firmware/hypervisor evidence, feature/reboot state and WSL capabilities). Only
the two DISM feature commands run through `runas`; the private distro, durable
state, cached candidate, Start-menu entries and launch remain with the original
user even when another administrator supplies UAC credentials. Restart uses a
verified HKCU RunOnce entry plus a manual **Continue LanEx Setup** shortcut and
is bounded by install-state boot identity/counters.

## Building locally

You need Go 1.21+, [Inno Setup 6.3+](https://jrsoftware.org/isdl.php), and (for
the exe's icon/version resource) `goversioninfo`.

```powershell
# 1. the launcher
cd windows\launcher
go test ./...                                  # UTF-16 distro parsing, health probe
go install github.com/josephspurrier/goversioninfo/cmd/goversioninfo@v1.7.0
goversioninfo -64 -o resource.syso versioninfo.json
go build -trimpath -ldflags "-H windowsgui -s -w" -o LanEx.exe .

# 2. the exact candidate wheel + manifest inputs (see CI for pin resolution)
cd ..\..
python -m build --wheel

# 3. the installer. These defines are mandatory; never label a build a
# candidate unless build-manifest.json was generated from the same commit/wheel.
cd windows\installer
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=0.0.0 `
  /DLanexRef=<full-commit-sha> /DLanexSourceSha=<full-commit-sha> `
  /DLanexSourceRepo=<owner/repository> /DLanexWheel=<absolute-wheel-path> lanex.iss
# -> windows\installer\LanEx-Setup.exe
```

`.github/workflows/windows-installer.yml` runs exactly these steps, plus
`shellcheck` on `provision.sh`, an end-to-end container provision (below), and a
weekly check that the pinned Ubuntu image URL still exists.

To provision an appliance locally without touching WSL — the fastest way to test
a `provision.sh` change, and what CI's `provision-e2e` job does:

```bash
python -m build --wheel
wheel=$(basename dist/*.whl)
sha=$(git rev-parse HEAD)
docker run -d --name lanex-e2e -v "$PWD:/checkout:ro" \
  -e LANEX_REF="$sha" -e LANEX_SOURCE_SHA="$sha" \
  -e LANEX_INSTALL_ID=11111111-2222-3333-4444-555555555555 \
  -e LANEX_MANIFEST_HASH=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  -e LANEX_INSTALL_SCRIPT=/checkout/scripts/install.sh \
  -e LANEX_FROM="/checkout/dist/$wheel" \
  -e LANEX_PIP_CONSTRAINT=/checkout/windows/setup/constraints.txt \
  ubuntu:24.04 sleep infinity
docker exec lanex-e2e bash /checkout/windows/provision/provision.sh
docker exec lanex-e2e bash /checkout/windows/provision/selftest.sh
```

Use `ubuntu:24.04`, not the WSL image. The minimal base is the point: it ships
neither `curl` nor `sudo`, so every "Ubuntu already has this" assumption fails
here first — which is how both provisioning bugs fixed in 2026-07 were found.

Cross-compiling the launcher from Linux works too, which is handy for a quick
syntax check: `GOOS=windows GOARCH=amd64 go build ./...` (the tests need a
Windows host, since the package imports `golang.org/x/sys/windows`).

The tray icon and every Windows-side icon come from one generated file,
`launcher/assets/lanex.ico`. Regenerate it from the cockpit's own favicon after a
brand change: `python3 windows/launcher/assets/make-icon.py`.

## Before a tester candidate or release — do these in order

1. **Build and test the branch before merging.** CI checks out the exact PR head,
   builds its wheel, bundles that wheel plus both install scripts, and records
   their hashes/source SHA in `build-manifest.json`. Fork PRs do not fall back
   to base or `main`. Give Akshat this candidate identity and collect the real
   Windows acceptance evidence before any merge to `main`.
2. **For a public release, create the GitHub release before or with the tag push.** `bake-rootfs` and
   `build` both `gh release upload` into it; neither creates it.
3. **Let `bake-rootfs` finish before judging `build`.** `build` waits on it and
   compiles the baked URL + SHA256 in. If the bake fails, `build` is skipped; if
   it produced nothing, `build` compiles the pre-Phase-2a installer instead and
   says so in the job summary. Read the summary — do not assume.
4. **Check `rootfs-pin` is green.** It only runs on tags, schedules and manual
   runs, and a stale pin is a 404 for every new user.
5. **Walk the acceptance matrix below** on x64 and update its Verified column.
   Never mark a row verified that you did not watch.

## Testing — read this before shipping a change

**CI cannot install LanEx.** GitHub-hosted runners have no nested
virtualization, so WSL 2 does not run on them: no `wsl --import`, no launch. It
*can* provision — `provision-e2e` runs `provision.sh` against a plain
`ubuntu:24.04` container end to end, twice (the second run is the installer's
Repair path), with `selftest.sh` after each. So everything provisioning does is
covered; what remains manual is WSL itself, the wizard, and the app window.

Acceptance gate — all ten must pass on x64 before a release:

| # | Environment | Expected | Verified |
|---|---|---|---|
| 1 | Clean Win 11 23H2+, WSL never installed | Feature-only UAC, normally one restart, same-owner automatic/manual resume, full install; first launch opens the app window; Tools tab pulls the image; the SPM example runs to GDS | — |
| 2 | Win 11 with an existing `Ubuntu-24.04` and the user's own WSL projects | Their distro and files untouched (compare `wsl -l -v` before/after); both coexist | — |
| 3 | Win 10 22H2 x64 | Same as #1 (this is the DISM fallback path in `EnableWsl`) | — |
| 4 | Virtualization disabled in BIOS | Friendly preflight dialog with a working help link; nothing partially installed | — |
| 5 | Re-run matching Setup over a healthy install | Identity + self-test pass; projects preserved; no dependency upgrade | — |
| 6 | Double-click the icon while LanEx is running | No second server; the app window re-opens (mutex + health-probe path) | — |
| 7 | Uninstall (current safe foundation) | Windows launcher/shortcuts removed; appliance, projects, PDKs, profile, and other distros preserved | — |
| 8 | Standard user; different administrator supplies UAC credentials | Only feature helper runs as admin; originating user owns state, appliance, shortcuts and launch | — |
| 9 | Network dropped mid-provision | Retry re-runs provisioning idempotently and succeeds | — |
| 10 | GUI viewers after a run | GTKWave opens from the RTL IDE and the layout viewer opens — proves the single interactive `wsl` invocation survived the launcher | — |

Target for #1, excluding the 3 GB toolchain pull: **under 8 minutes on a 50 Mbps
line** — and about a minute of that is provisioning once a tagged build's
pre-baked rootfs is in play.

One coexistence trap worth knowing before you test case 2 or 6: **WSL 2 puts
every distro on one shared network namespace.** If LanEx is already running
anywhere on the machine — the tester's own distro, a native install — it holds
8765 and the appliance's `find_free_port` lands on 8766, with both answering
`/api/health` identically. The launcher resolves this through
`~/.lanex/server.json` rather than by scanning ports (`probe.go`); if you are
testing on a machine where you also run LanEx yourself, check the port in
`launcher.log` matches the one in the appliance's `server.json`.

Provisioning itself is measured rather than estimated. On a 2026 laptop, from a
bare `ubuntu:24.04`:

| | |
|---|---|
| First provision (`LANEX_SKIP_GDS3D=1`, no image pull) | ~3 min |
| Repair — a second run over a working appliance | ~26 s |
| Provisioned filesystem | ~1.3 GB |
| Baked image (`LANEX_BAKE=1`, so GDS3D is built in), `gzip -6` | **494 MB** |
| `wsl --import` of that image, to a booting appliance | ~15 s |
| Cold boot of a baked appliance to `systemctl is-active docker` | ~3 s |

`wsl --import` reads the gzipped tar directly — measured, not assumed. Both
numbers above come from importing a locally baked image on a 2026 laptop.

## Known gaps (deliberate, tracked)

- **Unsigned.** SmartScreen shows a blue wall to the exact user this installer is
  for. The CI signing steps are written and gated on Azure Trusted Signing
  secrets — they light up when the keys exist. Until then, `docs/INSTALL.md`
  documents the *More info → Run anyway* click and publishes the SHA256.
- **x64 only.** ARM64 needs an ARM64 launcher build and the ARM64 Ubuntu image
  (both available; the pin is in `lanex.iss`), plus an ARM64 bake. Out of scope
  until somebody has ARM64 hardware to test it on — shipping an untested ARM64
  installer would be worse than shipping none.
- **Not on winget.** A manifest submission needs a stable release URL and a
  signed installer, so it follows code signing rather than leading it.
- **The ~3 GB toolchain image is still pulled on first launch**, not baked in.
  Everything else now is: the `bake-rootfs` job cooks Docker + LanEx + GDS3D into
  the image Setup downloads on a tagged build, which cuts provisioning to
  seconds and takes apt, GitHub and download.docker.com off the install-time
  critical path. The image itself stays out because the Tools tab pulls it with
  a real progress bar, and a ~4 GB installer download is worse than a 3 GB one
  the user starts on purpose. The plain-Ubuntu path is kept as an automatic
  fallback, so a missing release asset slows an install down rather than
  breaking it.
- **No auto-update** in the launcher: updating means running the new Setup and
  choosing Repair.
