# `windows/` — source of the LanEx Windows installer

This tree builds **`LanEx-Setup.exe`**: the installer that lets a Windows user
who has never opened a terminal run LanEx. It is maintainer documentation. Users
want [`docs/INSTALL.md`](../docs/INSTALL.md) instead.

```
windows/
  launcher/    Go source for LanEx.exe — starts the appliance, sits in the tray
  installer/   lanex.iss — the Inno Setup script (preflight, WSL, import, uninstall)
  provision/   provision.sh — runs inside the imported distro, once, as root
```

The design, in one paragraph: LanEx and every tool it drives are Linux programs,
so on Windows LanEx runs in a **private Ubuntu WSL distro** that Setup imports
with `wsl --import` — an appliance, the same pattern Docker Desktop and Rancher
Desktop use. No Microsoft Store, no Ubuntu first-run screen, no contact with the
user's own distros, and uninstall is `wsl --unregister lanex` plus deleting one
folder. Each file's header comment explains its own decisions; start with
`installer/lanex.iss`.

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

# 2. the installer
cd ..\installer
& "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" /DAppVersion=0.0.0 lanex.iss
# -> windows\installer\LanEx-Setup.exe
```

`.github/workflows/windows-installer.yml` runs exactly these steps, plus
`shellcheck` on `provision.sh` and a weekly check that the pinned Ubuntu image
URL still exists.

Cross-compiling the launcher from Linux works too, which is handy for a quick
syntax check: `GOOS=windows GOARCH=amd64 go build ./...` (the tests need a
Windows host, since the package imports `golang.org/x/sys/windows`).

The tray icon and every Windows-side icon come from one generated file,
`launcher/assets/lanex.ico`. Regenerate it from the cockpit's own favicon after a
brand change: `python3 windows/launcher/assets/make-icon.py`.

## Testing — read this before shipping a change

**CI cannot install LanEx.** GitHub-hosted runners have no nested
virtualization, so WSL 2 does not run on them: no import, no provisioning, no
launch. CI proves the pieces build and that the pure logic (UTF-16 parsing, port
probing, shell syntax) is right. Everything else is manual, on VMs.

Acceptance gate — all ten must pass on x64 before a release:

| # | Environment | Expected |
|---|---|---|
| 1 | Clean Win 11 23H2+, WSL never installed | One restart at most, Setup resumes itself, full install; first launch opens the app window; Tools tab pulls the image; the SPM example runs to GDS |
| 2 | Win 11 with an existing `Ubuntu-24.04` and the user's own WSL projects | Their distro and files untouched (compare `wsl -l -v` before/after); both coexist |
| 3 | Win 10 22H2 x64 | Same as #1 (this is the DISM fallback path in `EnableWsl`) |
| 4 | Virtualization disabled in BIOS | Friendly preflight dialog with a working help link; nothing partially installed |
| 5 | Re-run Setup over a healthy install | Repair path; projects preserved; LanEx upgraded in place |
| 6 | Double-click the icon while LanEx is running | No second server; the app window re-opens (mutex + health-probe path) |
| 7 | Uninstall | `wsl -l -q` no longer lists `lanex`; `%LOCALAPPDATA%\LanEx` gone; other distros intact |
| 8 | Standard (non-admin) user | Setup refuses at UAC with a clear message (documented limitation) |
| 9 | Network dropped mid-provision | Retry re-runs provisioning idempotently and succeeds |
| 10 | GUI viewers after a run | GTKWave opens from the RTL IDE and the layout viewer opens — proves the single interactive `wsl` invocation survived the launcher |

Target for #1, excluding the 3 GB toolchain pull: **under 8 minutes on a 50 Mbps
line**.

## Known gaps (deliberate, tracked)

- **Unsigned.** SmartScreen shows a blue wall to the exact user this installer is
  for. The CI signing steps are written and gated on Azure Trusted Signing
  secrets — they light up when the keys exist. Until then, `docs/INSTALL.md`
  documents the *More info → Run anyway* click and publishes the SHA256.
- **x64 only.** ARM64 needs an ARM64 launcher build and the ARM64 Ubuntu image
  (both available; the pin is in `lanex.iss`).
- **The ~3 GB toolchain image is pulled on first launch**, not baked in. Pre-baking
  a rootfs (Docker + LanEx + GDS3D + the image already inside) would cut install
  time to about a minute and remove the install-time dependency on apt and
  GitHub. `provision.sh` is deliberately container-runnable so that job is a
  small addition rather than a rewrite.
- **No auto-update** in the launcher: updating means running the new Setup and
  choosing Repair.
