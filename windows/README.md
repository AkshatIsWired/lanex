# Running LanEx on Windows

Two paths. **Docker is the foolproof one** (every EDA tool is baked into the
image and it works the same on every OS). The **WSL-native** path here is for
users who want the desktop GL viewers (GDS3D / KLayout / Magic GUI) to render
through WSLg without X-forwarding setup.

A future one-click `LanEx.exe` will wrap one of these so the end user never opens
a terminal — these scripts are the foundation it drives.

---

## Path A — Docker (recommended, simplest, survives upstream changes)

Install Docker Desktop (WSL2 backend), then in any terminal:

```sh
curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/install.sh | sh
lanex
```

The browser opens at `http://localhost:8765`. Flow, metrics, simulation, and
synthesis diagrams need no display. For the 3D/2D **desktop** viewers from the
container you must forward X11 (`-e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix`).

## Path B — WSL-native (desktop viewers via WSLg, no X-forwarding)

1. Install WSL + Ubuntu (PowerShell, once): `wsl --install -d Ubuntu`
2. Copy `install-lanex-wsl.sh` into WSL and run it **once**:
   ```sh
   bash install-lanex-wsl.sh
   ```
3. Double-click **`Launch-LanEx.bat`** to start LanEx. The browser opens at
   `http://127.0.0.1:8765`.

### The `bash -ic` requirement (do not remove it)

`Launch-LanEx.bat` launches the server with `wsl -d Ubuntu -- bash -ic "…"`.
The `-i` (interactive) flag is **mandatory**: WSLg only brings up the GPU /
display bridge for an interactive shell. Launch with a plain `bash -c` and every
desktop viewer crashes with `[WARN: COPY MODE]`. Use exactly **one** `wsl` line —
a second non-interactive line before it would run first, block, and the
interactive one would never execute.

If a launch wedges WSLg, reset it from PowerShell with `wsl --shutdown`, then
double-click `Launch-LanEx.bat` again.

### If the distro isn't named "Ubuntu"

Run `wsl -l -q` in PowerShell to see the exact name and edit the `-d Ubuntu`
argument in `Launch-LanEx.bat` to match.
