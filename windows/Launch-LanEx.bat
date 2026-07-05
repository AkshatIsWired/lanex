@echo off
REM ===========================================================================
REM  LanEx - Windows/WSL launcher
REM ===========================================================================
REM  ONE interactive `wsl` invocation is deliberate. Two things break WSLg (the
REM  WSL GUI/GPU bridge that KLayout / GDS3D / OpenROAD need) if you get it wrong:
REM
REM   1. WSLg only comes up cleanly for an INTERACTIVE shell -> use `bash -ic`,
REM      never `bash -c`.
REM   2. A second, separate `wsl` line can block the first from ever running,
REM      leaving WSLg half-initialised in "[WARN: COPY MODE]". Keep it to ONE
REM      `wsl` command.
REM
REM  Do NOT set LIBRELANE_GUI_WSL_HW_GL / LANEX_HW_GL here: LanEx already picks
REM  safe software GL on WSL, which renders viewers reliably even when the vGPU
REM  bridge is degraded. Only opt into hardware GL once you know WSLg is healthy.
REM
REM  If a desktop viewer still freezes, flush a stale bridge from a Windows
REM  terminal:  wsl --update  then  wsl --shutdown  and relaunch.
REM ===========================================================================

REM  Change this if your distro is not named "Ubuntu" (run `wsl -l -q` to check).
set "DISTRO=Ubuntu"

wsl -d %DISTRO% -- bash -ic "export PATH=\"$HOME/.local/bin:$PATH\"; cd ~/lanex 2>/dev/null; if command -v lanex >/dev/null 2>&1; then exec lanex; else exec python3 -m lanex; fi"

REM  The window stays attached to the running server; close it to stop LanEx.
