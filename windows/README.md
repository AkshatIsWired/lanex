# Running LanEx on Windows (WSL2)

LanEx runs inside **WSL2** (Ubuntu) and serves its cockpit to your normal
Windows browser. You don't install anything native on Windows.

## One-time setup (inside WSL)

Open your Ubuntu (WSL) terminal and follow the **[main README install
steps](../README.md#install)**, or paste the fresh-WSL one-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install-wsl.sh | bash
```

## Launching

Double-click **`Launch-LanEx.bat`**. It starts LanEx inside WSL and opens the
cockpit in your Windows browser (`http://localhost:8765`).

Edit the one line at the top of the `.bat` if your distro isn't named `Ubuntu`
(run `wsl -l -q` in a Windows terminal to see the name).

## Why the launcher is one `wsl` line

WSLg — the bridge that lets Linux GUI tools (KLayout, GDS3D, OpenROAD GUI) draw
on your Windows desktop — only initialises cleanly for an **interactive** shell.
A plain `bash -c`, or a second stray `wsl` command, can leave it stuck in
`[WARN: COPY MODE]` and freeze the viewers. The shipped `.bat` uses a single
`bash -ic` invocation to avoid that, and deliberately does **not** force
hardware GL (LanEx already selects reliable software GL on WSL).

If a viewer still freezes after your Windows PC has slept, flush a stale bridge
from a Windows terminal:

```
wsl --update
wsl --shutdown
```

then relaunch.
