# LanEx on Windows — the manual path (your own WSL distro)

Most Windows users should ignore this page and use
**[LanEx-Setup.exe](INSTALL.md#windows)**, which sets up an isolated environment,
adds a Start-menu app, and uninstalls cleanly.

This page is for the other case: you already run WSL2 and you want LanEx inside
**your** distro, sharing it with your other work.

## One-time setup (inside WSL)

Open your Ubuntu (WSL) terminal and run the one-line installer — the same one
Linux users run:

```bash
curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install.sh | bash
```

Full details, per-distro alternatives, and troubleshooting:
**[INSTALL.md](INSTALL.md)**.

## Launching

From the WSL terminal, `lanex`. The cockpit opens in its own Windows app window
(no tabs, no URL bar) — LanEx launches your Windows Edge/Chrome through the WSL
interop bridge, so there is nothing to install on the Windows side.

For a double-clickable shortcut, use **[`Launch-LanEx.bat`](Launch-LanEx.bat)**.
Edit the one line at the top if your distro isn't named `Ubuntu` (run `wsl -l -q`
in a Windows terminal to see the name).

## The three launcher rules (do not improvise here)

WSLg — the bridge that lets Linux GUI tools (KLayout, GDS3D, GTKWave, the
OpenROAD GUI) draw on your Windows desktop — is fragile about how it is started.
Get any of these wrong and the viewers open blank windows, freeze, or come up
titled `[WARN: COPY MODE]`, which looks exactly like a LanEx bug and isn't:

1. **`bash -ic`, never `bash -c`.** WSLg only initialises its GUI bridge cleanly
   for an **interactive** shell.
2. **Exactly one `wsl` command.** A second, separate `wsl` line can block the
   first from ever running and leave WSLg half-initialised.
3. **Never force hardware GL.** Don't set `LANEX_HW_GL` /
   `LIBRELANE_GUI_WSL_HW_GL` in a launcher. LanEx already picks safe software GL
   on WSL, which renders reliably even when the vGPU bridge is degraded; opting
   into hardware GL is what makes a poisoned bridge deadlock.

`Launch-LanEx.bat` follows all three, and so does the installer's `LanEx.exe`
(see `windows/launcher/wsl.go`) — if you write your own launcher, copy the shape,
not the idea.

## If a viewer still freezes

Your Windows host slept, or its graphics driver reset, and the WSLg vGPU is
stale. Flush it from a Windows terminal:

```
wsl --update
wsl --shutdown
```

then relaunch. The same `wsl --shutdown` also fixes the other classic WSL
symptom: the app window opens but cannot reach LanEx (broken Windows→WSL
localhost forwarding).

More Windows-specific symptoms — blank GL windows, missing Mesa drivers,
`Ctrl+Shift+V` not pasting — are in
[INSTALL.md's troubleshooting section](INSTALL.md#troubleshooting).
