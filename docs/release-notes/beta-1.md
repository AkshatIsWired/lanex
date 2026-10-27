# LanEx public beta 1 (Windows installer)

LanEx takes a Verilog design to a chip layout (GDS) with LibreLane, from a
window instead of a terminal. This beta is about one thing: **a stranger
installs it on an ordinary Windows PC and gets a GDS.**

## Install

1. Download **LanEx-Setup.exe** below (6.0 MB, SHA-256
   `5a812009fb41404b681ccb593a3db82a13d8af489d13ec01a54a4003e884fc82` for the build tested here).
2. Run it. Windows says "Windows protected your PC" because the installer is
   not code-signed yet: click **More info**, then **Run anyway**.
3. Click through Welcome, License and Configure (**Recommended** is right for a
   first chip), then **Install**. If WSL is not on yet, Windows asks for
   administrator permission and restarts once; Setup opens again by itself
   after you sign in. Click **Install** again there.
4. On "Ready to design", click **Finish**. LanEx opens. Click **New project**,
   pick **Blinky**, **Create project**, then **Run**. One to two minutes later the
   Flow tab says **Clean** and the GDS is in
   `LanEx-Projects\blinky\runs\<run>\final\gds\`.

Measured on clean 2-core, 8 GB virtual machines (Recommended):

| | Windows 11 26H2 | Windows 10 22H2 |
|---|---|---|
| Install to "Ready to design", incl. the restart | 15 to 17 min | 17 to 18 min |
| Blinky to GDS | 1 to 2 min, Clean | 1 to 2 min, Clean |
| Downloaded | 2.35 GB | 2.35 GB |
| Disk used | 13.9 GB | 13.9 GB |

Requirements: Windows 11, or Windows 10 22H2 with its updates (19045.2311 or
newer); x64; 6 GB of memory at least, 8 GB recommended; about 23 GB free on C:.

## What changed since the 2026-10-05 test build

- **Setup survives the real world.** It resumes after a restart, a dropped
  connection, a closed window or sleep; downloads resume and are SHA-256
  checked, and a partial or corrupt file is never used. On a PC where WSL
  already works it asks for nothing. It stops early, with the reason and the
  next step, on: Windows too old, not enough memory, not enough disk, WSL
  blocked by policy, virtualization off (including a VM without nested
  virtualization).
- **Every dependency is pinned.** Ubuntu packages come from a dated Ubuntu
  snapshot, Python packages from a lock file with hashes, the LibreLane image
  by digest, the Ubuntu image and every PDK file by SHA-256, LanEx's own copy
  first and the original source second.
- **Honest numbers.** The Configure page's download and disk figures are the
  ones measured above.
- **Uninstall keeps your work** by default (projects, tools, PDKs), and can back
  the environment up or remove it for good. Your other WSL distros and Windows
  features are never changed.
- **Every error names its log**: `%LOCALAPPDATA%\LanEx\logs\install.log`.

## Known limits

- LanEx is not a sign-off tool: "Clean" covers LibreLane's own checks (DRC in
  Magic and KLayout, LVS, XOR, antenna, timing in its corners), not gate-level
  simulation with delays, a shuttle's precheck or a foundry's sign-off decks.
- Windows x64 only; proven on Windows 11 Enterprise 26H2 and Windows 10
  Enterprise 22H2 virtual machines. Home and Pro were not run.
- Windows 10 asks for administrator permission twice and its first WSL start
  after the restart can take about five minutes.
- Not code-signed yet.

## If it goes wrong

Open an issue with the **Windows install problem** form and attach
`%LOCALAPPDATA%\LanEx\logs\install.log` (paste that path into Explorer's
address bar).
