# Installing LanEx

Everything about getting LanEx onto a machine: the one-click Windows installer,
the one-line Linux/macOS installer, per-distro manual steps, updating,
uninstalling, and what to do when something goes wrong.

The short version lives in the [README](../README.md#install). This page is the
long version.

- [Windows — the installer](#windows)
  - [What it actually does, and where things live](#windows-details)
  - [Turning on virtualization (BIOS/UEFI)](#enable-virtualization)
  - [The manual Windows path (your own WSL distro)](#windows-manual)
- [Linux, macOS, and WSL you manage yourself](#linux-macos-and-wsl-you-manage-yourself)
  - [Easiest — one command](#easiest--one-command-that-just-works-start-here-if-unsure)
  - [Manual install per distro](#manual-install--pick-the-row-that-matches-your-machine)
  - [After installing — the Tools tab](#after-installing--the-tools-tab-finishes-the-job)
- [Updating](#updating-lanex)
- [Uninstalling](#uninstalling-lanex)
- [Troubleshooting](#troubleshooting)
- [Environment variables](#environment-variables)

---

<a id="windows"></a>

## Windows — the installer

Download **[LanEx-Setup.exe](https://github.com/AkshatIsWired/lanex/releases/latest)**,
run it, click through the wizard. You need to be able to enter an administrator
password once (Windows asks); after that there is nothing to configure.

**Requirements:** Windows 10 version 2004 (build 19041) or newer, 64-bit —
Windows 11 recommended. About 10 GB free disk space. Windows Home is fine.

**What you get:** a Start-menu app called **LanEx**. Clicking it opens the
cockpit in its own desktop window, usually within about 15 seconds. On first
launch, open the **Tools** tab and click **Install the toolchain** — a one-time
~3 GB download that brings in every EDA tool at the versions LibreLane was
tested against. After that, LanEx works offline.

> **"Windows protected your PC"?** Until the installer is code-signed, Windows
> SmartScreen shows a blue warning for it (it warns about any new publisher, not
> about anything it found). Click **More info** → **Run anyway**. If you would
> rather verify first, every release lists the installer's SHA256 — compare it
> with `Get-FileHash .\LanEx-Setup.exe` in PowerShell.

<a id="windows-details"></a>

### What it actually does, and where things live

LanEx, LibreLane, and every EDA tool in the flow (OpenROAD, Yosys, Magic,
KLayout) are Linux programs. There is no native Windows build of any of them, so
on Windows LanEx runs inside **WSL 2** — and the installer's whole job is to set
that up so thoroughly that you never have to know it is there.

It does exactly five things:

1. **Turns on WSL** if it isn't already on (`wsl --install --no-distribution`).
   This is the only step that can require a restart — at most one, and Setup
   restarts itself afterwards to finish the job.
2. **Downloads the Linux environment**, verified against a SHA256 built into
   Setup. Released versions fetch a ready-made LanEx environment (~1 GB) that is
   assembled and tested by CI; if that file is ever unreachable, Setup falls
   back by itself to Canonical's official Ubuntu 24.04 WSL image (~373 MB) and
   builds the environment on your PC instead. Either way you end up with the
   same thing — the ready-made one is just faster.
3. **Imports it as a private distro named `lanex`** with `wsl --import`. This is
   the same appliance approach Docker Desktop and Rancher Desktop use on
   Windows. Because it is an import, there is no Microsoft Store dependency and
   **no Ubuntu first-run screen** asking you to invent a username and password.
4. **Provisions it**: creates the `lanex` user, installs Docker, then installs
   LanEx using this repo's own [`scripts/install.sh`](../scripts/install.sh) —
   the identical installer Linux users run, so there is only ever one install
   path to keep working. On the ready-made image this step finds everything
   already in place and takes seconds; from the plain Ubuntu image it is the
   part that takes a few minutes.
5. **Creates two Start-menu shortcuts**: **LanEx** (the app) and **LanEx Project
   Files** (opens your designs in File Explorer).

**What it touches, and what it does not:**

| | |
|---|---|
| ✅ Enables the Windows Subsystem for Linux feature | if it was off |
| ✅ Creates one new WSL distro called `lanex` | entirely its own |
| ✅ Writes to `%LOCALAPPDATA%\LanEx` and `%ProgramFiles%\LanEx` | nothing else |
| ❌ Your existing WSL distros | never read, listed for anything but our own name, modified, or upgraded |
| ❌ Your Python, your PATH, your registry beyond the standard uninstall entry | untouched |
| ❌ Docker Desktop | not needed and not installed; Docker lives *inside* the LanEx distro |

**Where things live:**

| What | Where |
|---|---|
| The launcher (`LanEx.exe`) | `%ProgramFiles%\LanEx` |
| The Linux environment's virtual disk | `%LOCALAPPDATA%\LanEx\distro` |
| The downloaded environment image (cached, reused on repair) | `%LOCALAPPDATA%\LanEx\cache` |
| Setup and launcher logs — **ask for these first when something is wrong** | `%LOCALAPPDATA%\LanEx\logs` |
| **Your designs and run results** | `\\wsl.localhost\lanex\home\lanex` (the *LanEx Project Files* shortcut) |
| The app window's browser profile | `%LOCALAPPDATA%\lanex\app-profile` |

**The tray icon** is the launcher's entire interface: **Open LanEx** re-opens the
window, **Open project files** opens the folder above, **Quit LanEx** stops the
server and shuts the Linux environment down. Closing the LanEx *window* does not
stop anything — the server keeps running so re-opening is instant.

**Uninstalling** from Windows Settings → Apps removes the distro
(`wsl --unregister lanex`), the folders above, and the shortcuts. It warns you
first, because **your designs live inside the environment** and go with it —
copy anything you want to keep out of `\\wsl.localhost\lanex\home\lanex` before
uninstalling. The one thing uninstalling does *not* undo is the Windows
Subsystem for Linux feature itself: it is a machine-wide setting other software
may now depend on, and turning it back off would need another restart. It is
inert if nothing uses it.

**No administrator rights?** The installer cannot work — turning the WSL feature
on is a machine-wide change that Windows only allows an administrator to make.
Use the [manual path](#windows-manual) with a distro your IT department has
already given you, or ask them to run the installer.

<a id="enable-virtualization"></a>

### Turning on virtualization (BIOS/UEFI)

If Setup says your computer's virtualization feature is switched off, WSL 2
cannot run at all — no program can fix this from inside Windows, because it is a
setting in your PC's own firmware. It is a one-time change.

**1. Get into the firmware screen.** The reliable route, from Windows:

> Settings → **System** → **Recovery** → **Advanced startup** → *Restart now* →
> **Troubleshoot** → **Advanced options** → **UEFI Firmware Settings** →
> *Restart*

Or press the setup key immediately at power-on, before the Windows logo:

| PC brand | Key |
|---|---|
| Dell | `F2` |
| HP | `Esc`, then `F10` |
| Lenovo | `F1` or `F2` (ThinkPad: `Enter` then `F1`; some models have a small **Novo** button) |
| ASUS | `F2` or `Del` |
| Acer | `F2` |
| MSI / Gigabyte / ASRock | `Del` |
| Samsung | `F2` |
| Microsoft Surface | hold **Volume Up** while pressing **Power** |
| Self-built | `Del` or `F2` |

**2. Find the setting and enable it.** It is under a *CPU Configuration*,
*Advanced*, or *Security* menu, and its name depends on your processor:

- **Intel:** `Intel Virtualization Technology`, `Intel VT-x`, or just
  `Virtualization Technology`
- **AMD:** `SVM Mode`, `AMD-V`, or `Secure Virtual Machine`

Set it to **Enabled**. (If you also see `VT-d` / `IOMMU`, leaving it alone is
fine — WSL does not need it.)

**3. Save and exit** (usually `F10`), let Windows boot, and run
`LanEx-Setup.exe` again.

If your PC is managed by an employer, this setting may be locked; that is a
question for whoever manages it.

<a id="windows-manual"></a>

### The manual Windows path (your own WSL distro)

If you already run WSL and would rather have LanEx inside *your* Ubuntu than in
its own environment — or you don't have administrator rights and someone else
set WSL up for you — skip the installer entirely:

1. In your WSL terminal, run the
   [one-line installer](#easiest--one-command-that-just-works-start-here-if-unsure)
   below, exactly as a Linux user would.
2. Launch with `lanex` from that terminal, or use the ready-made
   [`Launch-LanEx.bat`](Launch-LanEx.bat) shortcut.

The rules for wrapping LanEx in your own shortcut are not optional — a wrong
launcher breaks the GUI viewers in a way that looks like a LanEx bug. They are
written up in **[windows-manual.md](windows-manual.md)**, along with the
Windows-specific troubleshooting.

Trade-offs, honestly: you own the setup (Docker, systemd, the distro), LanEx
shares a distro with your other work, and there is no Start-menu app or
uninstaller. The installer exists precisely so nobody *has* to do this.

---

## Linux, macOS, and WSL you manage yourself

> **Recommended toolchain: pull the container image.** LibreLane publishes an
> official image with **every EDA tool baked in at the exact versions the flow
> was tested against** (OpenROAD · Yosys · Magic · KLayout · Netgen · Verilator).
> One download — `lanex --pull-image`, or **Tools → Pull image** in the app — and
> you need **no native EDA installs at all**, on every supported platform. Native
> tool installs are the advanced path; version-mismatch bugs (a system Yosys or
> Magic too old/new for your LibreLane) simply can't happen with the image.

**Supported platforms** (the same set LibreLane supports): Linux, macOS
(**13 Ventura or newer**, Intel and Apple Silicon alike — current Docker
Desktop and podman's VM both need 13+), and Windows **via WSL2**. On Windows,
do everything below inside a WSL2 Ubuntu terminal — LanEx and LibreLane are
Linux programs there; the UI opens as a native Windows window automatically.
(On Windows, [LanEx-Setup.exe](#windows) does all of this for you in its own
isolated environment. This section is for people who want LanEx in a distro they
manage themselves.)

> **Prerequisites:** Python ≥ 3.10. Docker or Podman is recommended but
> **optional** — LanEx can install an engine for you (you confirm the password
> prompt in your terminal if the system package needs `sudo`).

### Easiest — one command that just works (start here if unsure)

New here, or you just want it running? This single line works on **any major
Linux distro (Debian/Ubuntu, Fedora, Arch, openSUSE, …), inside WSL2 on
Windows, and on macOS**. It detects your system, installs the packages a fresh
machine is missing, installs LanEx, puts the `lanex` command on your PATH, and —
if you have Docker or Podman — pre-pulls the version-matched LibreLane image
(otherwise the in-app Tools tab sets that up on first run). Safe to re-run;
**a re-run also upgrades LanEx in place**.

```bash
curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install.sh | bash
```

No `curl` on a fresh box? `wget` works the same:

```bash
wget -qO- https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install.sh | bash
```

Every step in it has a fallback (no `pipx` package on your distro → pip → a
plain built-in virtualenv; a dependency needs compiling → it installs the
compilers and retries; …), so it lands on any supported machine. Don't prefix
it with `sudo` — it asks for sudo itself only where needed, and refuses to run
under `sudo` outright (that's how installs end up in root's home).

<details>
<summary><b>On Windows with no WSL yet? Two commands get you there.</b></summary>

**Or don't:** [LanEx-Setup.exe](#windows) sets up WSL and its own private Ubuntu
for you, with no username/password screen and a real uninstaller. Do the two
commands below only if you specifically want your own general-purpose Ubuntu.

LanEx (like LibreLane and every EDA tool it drives) is a Linux program; on
Windows it runs inside **WSL2** — a one-time, built-in Windows feature:

1. Open **PowerShell as Administrator** and run:

   ```powershell
   wsl --install -d Ubuntu-24.04
   ```

2. **Reboot** when asked. On the first start of the new "Ubuntu 24.04" app,
   pick a username/password. Then, inside that Ubuntu terminal, run the
   one-line installer above.

Already have WSL but it's **WSL 1**? Upgrade the distro first (from
PowerShell): `wsl --set-version Ubuntu-24.04 2` — Docker and the GUI viewers
need WSL 2. Check with `wsl -l -v`.
</details>

Then launch the cockpit:

```bash
lanex
```

The UI opens automatically in its **own app window** — a standalone window with
its own taskbar entry, no tabs and no URL bar (it uses your installed
Chrome/Edge/Chromium for the rendering; with none installed it falls back to a
normal browser tab, and `lanex --tab` forces the tab). That's it. **If anything in the manual options
below looks confusing, just use this; it's built to work out of the box on any
supported machine.** On **Fedora / Arch / macOS**, or if you **already run
LibreLane**, the script isn't for you — pick the matching self-contained row
below instead.

### Manual install — pick the row that matches your machine

Each row is **complete on its own** — copy the whole block, top to bottom, from
a fresh terminal. They intentionally repeat shared steps so you never have to
stitch two rows together.

<table>
<tr><th align="left" width="235">Your situation</th><th align="left">Install commands (self-contained)</th></tr>

<tr><td><b>1 · Debian / Ubuntu-family Linux</b><br><sub>native <i>or</i> WSL2; nothing installed yet — the recommended path</sub></td>
<td>

```bash
# 1. system packages a fresh/minimal image is missing
sudo apt update && sudo apt install -y pipx python3-venv git xfonts-base libgl1 libgl1-mesa-dri libegl1
# 2. put pipx-installed commands on your PATH (future shells AND this one)
pipx ensurepath; export PATH="$HOME/.local/bin:$PATH"
# 3. install LanEx straight from the repo tarball (no git needed;
#    once LanEx is on PyPI this simply becomes: pipx install lanex)
pipx install https://github.com/AkshatIsWired/lanex/archive/refs/heads/main.tar.gz
# 4. optional: pre-pull the version-matched LibreLane image (needs Docker/Podman;
#    skip if you have neither — the in-app Tools tab installs an engine for you)
lanex --pull-image
# 5. launch
lanex
```

(The [one-line installer](#easiest--one-command-that-just-works-start-here-if-unsure)
runs these steps for you — plus fallbacks for machines where one of them
fails — and upgrades on re-run.)

Why `pipx` and not `pip`: Ubuntu 23.04+ (including every current WSL Ubuntu)
refuses `pip install` outside a virtualenv (PEP 668 — see
[Troubleshooting](#troubleshooting)). `pipx` gives LanEx its own isolated venv
and puts `lanex` on your PATH. The apt line pre-installs the X11 fonts and Mesa
GL drivers that minimal images ship without — missing them is why desktop
viewers open blank windows or crash.</td></tr>

<tr><td><b>2 · Fedora / Arch / other Linux</b><br><sub>no LibreLane yet, Python ≥ 3.10</sub></td>
<td>

```bash
# 1. pipx + the Mesa GL drivers/fonts desktop viewers need (pick your distro)
sudo dnf install -y pipx git mesa-dri-drivers xorg-x11-fonts-misc      # Fedora
# sudo pacman -S --needed python-pipx git mesa xorg-fonts-misc base-devel  # Arch
# 2. PATH, then install LanEx from the repo tarball (PyPI once published)
pipx ensurepath; export PATH="$HOME/.local/bin:$PATH"
pipx install https://github.com/AkshatIsWired/lanex/archive/refs/heads/main.tar.gz
# 3. launch (add `lanex --pull-image` first if you have Docker/Podman)
lanex
```

No `pipx` package? `python3 -m pip install --user pipx` first. Arch note: its
Python is very new, so pip may compile one dependency from source — that's why
the `base-devel` group is in the pacman line. (LanEx also offers the missing GL
drivers as a one-click fix from the Tools tab when a viewer needs them.)</td></tr>

<tr><td><b>3 · macOS</b><br><sub>Python ≥ 3.10, no LibreLane yet</sub></td>
<td>

```bash
# 1. pipx via Homebrew (macOS's bundled Python is 3.9 — too old — so use brew's)
brew install pipx
pipx ensurepath; export PATH="$HOME/.local/bin:$PATH"
# 2. install LanEx from the repo tarball (PyPI once published)
pipx install https://github.com/AkshatIsWired/lanex/archive/refs/heads/main.tar.gz
# 3. launch (Container engine recommended — install one of:)
#    brew install --cask docker-desktop   # then open Docker.app once
#    brew install podman && podman machine init && podman machine start
lanex
```

No Homebrew? Install it first: https://brew.sh (one command). LibreLane's heavy
tools run in the container image, so Docker/Podman is the smooth path on macOS;
the Tools tab can install one for you (it handles the Docker.app first-run and
the podman VM setup). Desktop layout viewers launched <i>from the container</i>
(KLayout/Magic/OpenROAD) additionally need XQuartz — see the troubleshooting
entry below.</td></tr>

<tr><td><b>4 · You already run LibreLane</b><br><sub>in a venv / conda env</sub></td>
<td>

```bash
# activate your existing librelane env FIRST, then, from a clone of this repo:
git clone https://github.com/AkshatIsWired/lanex && cd lanex
pip install .               # plain pip is correct INSIDE an activated env
lanex
```

PEP 668 only guards the <i>system</i> interpreter — plain <code>pip</code> is
correct (and pipx would be <i>wrong</i>) inside your env: LanEx must share the
environment to see your <code>librelane</code> and native toolchain. Use the
<b>Local tools</b> engine for your native tools, or <b>Container</b> for
<code>librelane --dockerized</code>. Nothing extra to install.</td></tr>
</table>

**Do not** use `pip install --break-system-packages` (it can corrupt your
distro's Python), and do not use `pipx install -e .` (an editable install breaks
silently if you later move or delete the clone).

### After installing — the Tools tab finishes the job

<table>
<tr><th align="left" width="220">You need</th><th align="left">One click away</th></tr>

<tr><td><b>The EDA toolchain</b></td>
<td>Tools tab → <b>Install the toolchain (recommended)</b>. One click pulls the version-matched LibreLane container image; keep the <b>Container</b> engine selected and you're done — zero native tool installs.<br><br><b>No Docker or Podman?</b> The same card installs one for you first, then pulls the image, all in one go. It runs the official installer (e.g. <code>curl -fsSL https://get.docker.com | sudo sh</code> on Linux; on macOS it installs Docker Desktop — retrying over leftovers from an old install, and falling back to the official DMG when Homebrew can't — or podman <i>including</i> its one-time <code>podman machine</code> VM setup, falling back to podman's official <code>.pkg</code> where brew has no prebuilt bottle); you confirm the password prompt in your terminal (on macOS, a native password dialog). After installing, LanEx <b>starts</b> the engine and waits for it — an installed-but-not-running engine gets a one-click <b>Start</b> on the runtime card.</td></tr>

<tr><td><b>Recommended extras</b><br><sub>optional niceties</sub></td>
<td>The Tools tab's <b>Recommended extra tools</b> group one-click-installs <b>Icarus Verilog</b> (RTL simulation in the IDE), <b>Graphviz</b> (synthesis schematics), <b>GTKWave</b> (the RTL IDE's "Open in GTKWave" desktop waveform viewer — launched with the simulation's signals already on screen), and <b>GDS3D</b> (3D layout viewer — built from source on Linux with all its X11/GL dependencies handled; on macOS the prebuilt app from the GDS3D repo is installed, which on Apple Silicon runs under Rosetta 2: <code>softwareupdate --install-rosetta</code>). The one-line installer sets up GTKWave and GDS3D for you automatically (skip with <code>LANEX_SKIP_GDS3D=1</code>); a failed extra never blocks the install — retry any time from the Tools tab, or headlessly with <code>lanex --install-tool gds3d</code> / <code>lanex --install-tool gtkwave</code>. System packages that need <code>sudo</code> prompt for your password in the launch terminal — LanEx never asks for your password in the browser.</td></tr>
</table>

### Updating LanEx

New releases are published as versioned packages, so an update is deliberate —
you stay on your current version until you choose to move up. Update the way you
installed:

<table>
<tr><th align="left" width="235">How you installed</th><th align="left">Update command</th></tr>

<tr><td><b>Windows installer</b></td>
<td>Download the current <b>LanEx-Setup.exe</b> and run it. It finds the existing
install and offers <b>Repair</b>, which updates LanEx inside the environment and
<b>keeps your projects</b>. (The other option wipes the environment — the dialog
says so.) Nothing else on your PC is touched either way.</td></tr>

<tr><td><b>One-line installer</b></td>
<td>Re-run the same line — it upgrades in place:<br>

```bash
curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install.sh | bash
```

(The older `install-wsl.sh` URL keeps working — it now runs the same universal
installer.)</td></tr>

<tr><td><b>pipx (from the repo tarball)</b></td>
<td>

```bash
pipx install --force https://github.com/AkshatIsWired/lanex/archive/refs/heads/main.tar.gz
```

(`--force` is what makes it an upgrade — a plain `pipx upgrade` sees the same
version number in the tarball and does nothing.)</td></tr>

<tr><td><b>pipx (from PyPI)</b></td>
<td>

```bash
pipx upgrade lanex
```
</td></tr>

<tr><td><b>pipx (from a git clone)</b></td>
<td>

```bash
cd lanex && git pull && pipx install . --force
```
</td></tr>

<tr><td><b>pip inside your own env</b></td>
<td>

```bash
cd lanex && git pull && pip install . --force    # from a clone, in the activated env
```
</td></tr>

<tr><td><b>Want the newest, unreleased code?</b><br><sub>testers / bleeding edge</sub></td>
<td>

```bash
pipx install "git+https://github.com/AkshatIsWired/lanex@main" --force
```

Tracks the tip of `main` — newer than any release, but not yet version-blessed.</td></tr>
</table>

After updating, if the LibreLane engine version moved, re-pull the matched image
from the **Tools** tab (or `lanex --pull-image`) so the container stays in lockstep.
Check your installed version any time with `pipx list` (or `pip show lanex`).

### Uninstalling LanEx

**Installed with LanEx-Setup.exe on Windows?** None of the layers below apply.
Go to Windows **Settings → Apps → Installed apps → LanEx → Uninstall**: it
removes the environment, the app, and the shortcuts in one step. Everything you
made lives *inside* that environment, so copy anything you want to keep out of
`\\wsl.localhost\lanex\home\lanex` first — the uninstaller warns you and offers
to open the folder. Your other WSL distros are untouched; see
[what remains](#windows-details).

Otherwise, removal is in three layers — the app, its data, and the heavy things
it *helped* you install (the container image, PDKs, EDA tools). Do as many as you
want; each is independent.

**1 · Remove the app** — match how you installed:

<table>
<tr><th align="left" width="235">How you installed</th><th align="left">Remove command</th></tr>

<tr><td><b>pipx</b> (one-line installer, tarball, PyPI, or git)</td>
<td>

```bash
pipx uninstall lanex
```
</td></tr>

<tr><td><b>pip inside your own env</b></td>
<td>

```bash
pip uninstall lanex
```
</td></tr>

<tr><td><b>venv fallback</b> (installer used this when pipx was unavailable)</td>
<td>

```bash
rm -rf ~/.lanex/venv
sudo rm -f /usr/local/bin/lanex     # only if the installer made this symlink
```
</td></tr>
</table>

If the installer added a `PATH` line for `~/.local/bin` to your `~/.bashrc` /
`~/.zshrc`, delete that line too (harmless if left).

**2 · Remove LanEx's data** (settings, saved cells/macros overlays, the built
GDS3D copy, the image digest lock, the app-window profile):

```bash
rm -rf ~/.lanex
```

Nothing outside `~/.lanex` holds LanEx state — this is a clean wipe.

**3 · Remove the heavy things LanEx installed for you** (all optional — skip any
you still use elsewhere):

```bash
# The LibreLane container image (~10 GB) — the tag matches your LibreLane version
docker rmi $(docker images -q ghcr.io/librelane/librelane)     # or: podman rmi …

# EDA tools installed from the Tools tab (only the ones you added)
brew uninstall --cask docker-desktop klayout      # macOS
brew uninstall podman yosys verilator icarus-verilog graphviz gtkwave
sudo apt remove yosys iverilog verilator graphviz gtkwave klayout   # Debian/Ubuntu

# PDKs (downloaded by ciel — SHARED with a native LibreLane install; only
# remove if you don't use LibreLane outside LanEx)
rm -rf ~/.ciel ~/.volare
```

On macOS, `podman machine rm` deletes podman's Linux VM before
`brew uninstall podman` if you want the disk back. Docker Desktop can also be
removed from **Applications** or via its own **Troubleshoot → Uninstall**.

### Troubleshooting

<details>
<summary><b><code>error: externally-managed-environment</code> when running <code>pip install</code></b></summary>

That is Ubuntu 23.04+/Debian 12+ enforcing [PEP 668](https://peps.python.org/pep-0668/):
the system Python refuses package installs that could break distro tooling.

```
error: externally-managed-environment

× This environment is externally managed
╰─> To install Python packages system-wide, try apt install python3-xyz ...
```

Fix: install with **pipx** (install row 1) or inside a **venv/conda env**
(install row 3). Never use `--break-system-packages`.
</details>

<details>
<summary><b><code>Could not get lock /var/lib/dpkg/lock-frontend</code> during install (Ubuntu/WSL)</b></summary>

A freshly booted Ubuntu/WSL runs `unattended-upgrades` in the background for a
few minutes, holding the apt lock. The one-line installer waits for it
automatically (up to 5 minutes). If you're running apt by hand, just wait a
minute and retry — never delete the lock file.
</details>

<details>
<summary><b><code>No matching distribution found for lanex</code> / pip says it needs Python &gt;= 3.10</b></summary>

Your `python3` is older than 3.10 (Ubuntu 20.04 ships 3.8, RHEL/CentOS 9 ships
3.9, macOS's bundled one is 3.9). Fixes: use a current distro release
(Ubuntu 22.04+/Debian 12+ — on WSL: `wsl --install -d Ubuntu-24.04`);
RHEL-family: `sudo dnf install python3.11`, then
`pipx install --python python3.11 …`; macOS: `brew install python`.
</details>

<details>
<summary><b>Install fails while "building wheels" for a dependency (often on Arch / very new Python)</b></summary>

A dependency (e.g. LibreLane's `lln-libparse`) has no prebuilt wheel for a very
new Python version, so pip compiles it — which needs a C/C++ toolchain. The
one-line installer detects this, installs the compilers, and retries by itself.
Doing it by hand: `sudo pacman -S --needed base-devel` (Arch) /
`sudo apt install build-essential python3-dev` (Debian/Ubuntu) /
`sudo dnf install gcc gcc-c++ make python3-devel` (Fedora), then re-run the
install command.
</details>

<details>
<summary><b>A desktop tool (GDS3D / KLayout / OpenROAD GUI / GTKWave) opens a blank window, hangs, or the title says <code>[WARN: COPY MODE]</code> (WSL)</b></summary>

Four known causes, all handled or handleable:

1. **Missing Mesa GL drivers** — fresh minimal WSL/Ubuntu images ship without
   `libgl1-mesa-dri`, leaving GL apps with **no renderer at all** (even software
   rendering needs it). LanEx detects this before a launch and offers a
   one-click install; manually it's
   `sudo apt-get install -y libgl1 libgl1-mesa-dri libegl1`
   (Fedora: `sudo dnf install mesa-dri-drivers`; Arch: `sudo pacman -S mesa`).
2. **Non-interactive launch** — WSLg only brings up its GUI bridge for
   interactive shells. Use the ready-made **[`Launch-LanEx.bat`](Launch-LanEx.bat)**
   shortcut, or if you write your own, start LanEx with `bash -ic`, not `bash -c`,
   in a **single** `wsl` command (a second `wsl` line can block the first from
   ever running). Don't set `LANEX_HW_GL`/`LIBRELANE_GUI_WSL_HW_GL` in a WSL
   launcher unless your WSLg GPU bridge is known-healthy — it opts out of the
   safe software-GL default below and is what makes hardware GL deadlock on a
   poisoned bridge.
3. **Stale WSLg vGPU** after the Windows host sleeps or its graphics driver
   resets. LanEx defaults GL tools to CPU (software) rendering on WSL so this
   rarely matters; the cold-boot fix is `wsl --update` then `wsl --shutdown`
   from a Windows terminal.
4. **GTK's Wayland backend** — GTK3 apps (GTKWave) pick WSLg's Wayland path
   first, and that path is the one that degrades to a blank taskbar-only
   window titled `[WARN: COPY MODE]`. LanEx pins GTK (and Qt) launches to the
   X11/XWayland transport on WSL — the same route every other tool uses — so
   this is automatic; `LANEX_WAYLAND=1` opts back into Wayland if you want it.

GL rendering overrides (set in your environment before launching):
`LANEX_HW_GL=1` forces hardware GL everywhere (skips the WSL software-GL
default, native *and* container launches); `LANEX_SOFTWARE_GL=1` forces
software GL even outside WSL (broken native GPU stacks, remote X, VNC).
</details>

<details>
<summary><b>Container viewers (KLayout / Magic / OpenROAD GUI) say "no display" on macOS</b></summary>

Tools running *inside* the container are Linux X11 apps — on macOS they need
**XQuartz** as the X server, reached over TCP. Three one-time steps:

1. Install and start it: `brew install --cask xquartz`, log out and back in
   (or reboot), then `open -a XQuartz`.
2. Allow network (container) clients — XQuartz ships with this **off**:
   XQuartz → Settings → Security → enable **"Allow connections from network
   clients"**, then restart XQuartz. (Terminal equivalent:
   `defaults write org.xquartz.X11 nolisten_tcp -bool false`.)
3. `xhost +localhost` in an XQuartz terminal. LanEx also runs this for you at
   each launch when it can.

LanEx's Layout buttons report exactly which of these steps is missing. The
built-in layout preview and all flow runs work without XQuartz — this only
affects the interactive desktop viewers launched from the container.
</details>

<details>
<summary><b>Docker/Podman install fails or the engine stays "not usable" (macOS)</b></summary>

* **Engine installed but "not usable" / `cannot connect to … docker.sock`** —
  on macOS the docker daemon only runs **while the Docker Desktop app is
  running** (same for podman's machine VM). Click **Start Docker Desktop** (or
  **Start podman machine**) on the Tools runtime card — LanEx opens the app,
  waits for the daemon, and continues; **Pull image** does the same start
  automatically. On Docker Desktop's very first launch, approve its own
  prompts in the Docker window (that first boot can take a minute or two).
* **`sudo: a terminal is required to read the password`** during
  `brew install --cask docker-desktop` — the cask needs admin rights to link
  Docker's CLI tools into `/usr/local`, and there's no terminal when LanEx runs
  from the app window/pipx. LanEx now points Homebrew at a graphical password
  prompt (a macOS dialog appears — enter your login password). If it still fails,
  install Docker Desktop from
  [docker.com](https://docs.docker.com/desktop/setup/install/mac-install/), open
  it once, then click **Pull image**.
* **`error getting credentials … "docker-credential-desktop": executable file
  not found in $PATH`** when pulling — Docker stores credentials via a helper
  that lives inside `Docker.app` and isn't always on `PATH`. LanEx adds Docker's
  bundled bin dir to `PATH` and, if the helper still can't be found, retries the
  pull without it (the LibreLane image is public, so no login is needed). Manual
  fix: run Docker Desktop once (it symlinks the helper into `/usr/local/bin`), or
  pull with a `DOCKER_CONFIG` pointed at a config that has no `"credsStore"` line.
* **`Error: It seems there is already a Binary at '/usr/local/bin/docker-credential-…'`** —
  leftovers from a previous Docker install. LanEx retries with `--force`
  automatically; manually: `brew install --cask docker-desktop --force`.
* **`Error: podman: no bottle available!`** — your Homebrew configuration is
  "Tier 3" (an OS/CPU combo brew stopped prebuilding for, e.g. an Intel Mac on
  a recent macOS). LanEx now falls back automatically to podman's **official
  installer package** (prebuilt for both Intel and Apple Silicon, installs to
  `/opt/podman`) — no Go toolchain, no source build. Manual equivalent:
  download the `.pkg` from [podman.io](https://podman.io/docs/installation).
* **No Homebrew at all** — not a blocker: the Docker card falls back to the
  official **Docker Desktop DMG** (silent install via Docker's bundled
  installer CLI) and the podman card to the official `.pkg`.
* **podman installed but "not usable"** — podman on macOS runs containers in a
  VM that must exist and be running: `podman machine init && podman machine
  start` (LanEx's one-click podman install does this for you, and the runtime
  card's **Start podman machine** re-boots it later).
* **Remove docker / Remove podman** on the runtime card works on macOS too:
  Docker via the brew cask or Docker.app's own bundled uninstaller (quit the
  app first if it's running); podman removes its machine VM first, then the
  brew formula or the `/opt/podman` package.
* **macOS 12 or older** — current Docker Desktop and podman 5's VM both need
  macOS 13 (Ventura)+. LanEx detects this up front and refuses the doomed
  multi-GB download, pointing at the real options: an older Docker Desktop
  release that still lists your macOS
  ([release-notes archive](https://docs.docker.com/desktop/release-notes/) —
  install it, open Docker.app once, click **Pull image**; the rest of LanEx
  works normally), or podman 4.x with QEMU.
* **Intel vs Apple Silicon** — handled automatically, including the trap of
  running under an x86_64 (Rosetta) Python on an M-series Mac: LanEx asks the
  chip itself (`sysctl hw.optional.arm64`) before picking the arm64/amd64
  Docker or podman download.
</details>

<details>
<summary><b>GDS3D on macOS: install fails with <code>make: *** No targets specified</code>, or it won't launch on Apple Silicon</b></summary>

The GDS3D repo's `mac/` directory has no Makefile — older LanEx versions tried
`make` there and failed exactly like that; current LanEx installs the prebuilt
`GDS3D.app` the repo ships instead (update LanEx if you still see the make
error). That binary is Intel-only: on Apple Silicon install Rosetta 2 once —
`softwareupdate --install-rosetta --agree-to-license` — or the launch fails
with `Bad CPU type in executable`.
</details>

<details>
<summary><b>"Open in GTKWave" says GTKWave isn't installed, or nothing opens</b></summary>

The RTL IDE's **GTKWave** button launches the desktop GTKWave on the last
simulation's dump, with the signals preloaded (LanEx writes a `.gtkw` save file
next to the dump — a bare `gtkwave dump.vcd` would open an empty wave pane).
Per platform:

* **Linux**: every major distro packages it — `sudo apt install gtkwave`
  (or `dnf` / `pacman -S` / `zypper install gtkwave`), or one click in the
  Tools tab. The one-line installer already sets it up.
* **macOS**: `brew install gtkwave` — this is the Homebrew **formula** added in
  2024. If brew says "No available formula", run `brew update` first. The old
  GTKWave **cask** (`gtkwave.app`) is broken on modern macOS and LanEx
  deliberately ignores it — remove it and install the formula.
* **WSL**: the window opens through WSLg, like the other desktop viewers.
  A Windows-side `gtkwave.exe` on the interop PATH is ignored on purpose
  (it can't be launched reliably from the Linux side) — install the Linux one.
* **Headless / SSH**: desktop viewers need a graphical session; LanEx says so
  instead of pretending to launch. The built-in canvas waveform viewer works
  everywhere.
</details>

<details>
<summary><b>PDK or image downloads time out on WSL2 (<code>ciel fetch failed … timed out</code>)</b></summary>

WSL2 sometimes generates a broken `/etc/resolv.conf`, so downloads can't resolve
`github.com`. LanEx detects this and shows the exact fix; manually:

```bash
sudo rm -f /etc/resolv.conf
sudo bash -c 'echo "nameserver 8.8.8.8" > /etc/resolv.conf'
```

To make it permanent add to `/etc/wsl.conf`: `[network]` / `generateResolvConf = false`.
</details>

<details>
<summary><b>A PDK install was interrupted and now keeps failing with <code>[Errno 13] Permission denied</code> on <code>~/.ciel/…</code></b></summary>

A `ciel fetch` cut off mid-download (a slow or flaky link on a multi-GB PDK)
leaves a half-extracted version directory the next attempt can't overwrite.
**LanEx now clears that partial automatically before each retry**, so a fresh
install recovers on its own — just start it again.

If an **older** interrupted download already wedged your store, clear only the
affected PDK family (this keeps every other installed PDK) and reinstall from the
Tools tab:

```bash
# replace gf180mcu with the family that failed (sky130, gf180mcu, ihp-sg13g2, …)
chmod -R u+w ~/.ciel && rm -rf ~/.ciel/ciel/gf180mcu/versions
```

**If it keeps failing with `Permission denied` no matter what**, an earlier
command run with `sudo` left part of `~/.ciel` owned by `root` — which the
automatic (owner-scoped) recovery above cannot fix. LanEx now **detects this and
offers a one-click "Fix permissions"** button when you start the install; it
restores ownership to you (scoped to `~/.ciel`, no `rm`). To do it by hand:

```bash
sudo chown -R "$USER" ~/.ciel
```

Prefer `chown` over `sudo rm` here — it keeps the already-downloaded PDK data
instead of forcing a fresh multi-GB download. You do **not** need to delete
`~/.ciel`.
</details>

<details>
<summary><b>GDS3D (3D view) reports "no process/tech file found" for a non-sky130 PDK</b></summary>

GDS3D renders the layer stack from a per-PDK **process/tech file** (`-p`). It
ships example files for a few PDKs (sky130, sg13g2) but **not gf180mcu** and not
every PDK. KLayout and Magic (2D) still work — they read the layer properties
straight from the PDK. For 3D on an unsupported PDK, drop a matching GDS3D tech
file named after the PDK into:

```
~/.lanex/tools/GDS3D/techfiles/<pdk>.txt
```

then reopen the GDS in GDS3D. (2D KLayout/Magic layer colours are resolved from
the PDK automatically — no extra file needed.)
</details>

<details>
<summary><b>No browser opens when I run <code>lanex</code> (WSL)</b></summary>

Fresh WSL distros have no Linux browser. LanEx detects WSL and hands the URL to
Windows automatically (the app window uses Windows Edge/Chrome; the tab
fallback goes via `wslview`/`explorer.exe`), opening a native Windows window.
If nothing opens, the URL is printed in the terminal — open
`http://localhost:8765` yourself.
</details>

<details>
<summary><b>The app window is blank / can't connect, or I'd rather have a plain tab</b></summary>

`lanex` opens a standalone app window by rendering through your installed
Chromium-family browser (Chrome, Edge, Chromium, Brave, Vivaldi — on WSL the
*Windows* Edge/Chrome, so the window is native Windows). Every failure falls
back to a normal browser tab on its own; these are the corner cases:

- **Blank window on WSL** — Windows→WSL localhost forwarding is wedged (rare;
  usually after hibernate). Run `wsl --shutdown` from Windows once and relaunch,
  or use `lanex --tab`.
- **No Chromium-family browser installed** (e.g. Firefox-only) — you get a
  normal tab plus a printed hint. Install Chromium/Chrome/Edge for the app
  window, or use your browser's own menu → **Install LanEx** (the PWA gives the
  same standalone window and a permanent launcher icon).
- **Snap/Flatpak browsers** (stock Ubuntu Chromium) work too; they just share
  the browser's default profile (their sandbox can't write `~/.lanex`) — purely
  cosmetic.
- **Force a specific browser** with `LANEX_BROWSER=/path/to/browser`; opt out
  entirely with `lanex --tab` or `LANEX_NO_APP_WINDOW=1`.
- **Need to reload?** The window has no browser toolbar, but the topbar has a
  reload button, and `F5` / `Ctrl+R` still work. The UI also refreshes its own
  data after installs, so this is rarely needed.
</details>

<details>
<summary><b>Ctrl+Shift+V doesn't paste in the WSL/Ubuntu console window</b></summary>

A Windows console default, not a LanEx issue: right-click the console title bar
→ **Properties** → tick **Use Ctrl+Shift+C/V as Copy/Paste**. Or use
[Windows Terminal](https://aka.ms/terminal), which has it on by default.
</details>

### Environment variables

| Variable | Effect |
|---|---|
| `LANEX_HOME` | Config/state directory (default `~/.lanex`; the old `~/.librelane-gui` is honoured for existing installs) |
| `LANEX_HW_GL=1` (alias `LIBRELANE_GUI_WSL_HW_GL=1`) | Skip the software-GL forcing for desktop viewers (native + container launches) |
| `LANEX_SOFTWARE_GL=1` | Force software GL for desktop viewers even off-WSL |
| `LANEX_BROWSER` | Browser for the standalone app window (a name like `chromium` or an absolute path); default = first Chromium-family browser found |
| `LANEX_NO_APP_WINDOW=1` | Never open the standalone app window — always use a normal browser tab (same as `lanex --tab`) |
| `LIBRELANE_IMAGE_OVERRIDE` | Use a specific container image instead of the version-matched default |
| `PDK_ROOT` | PDK store location (same variable LibreLane/ciel use) |
