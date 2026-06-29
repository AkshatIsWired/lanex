@echo off
title LanEx Server (WSL)
echo =======================================================
echo                 Starting LanEx in WSL
echo =======================================================
echo.
echo Your browser will open at http://127.0.0.1:8765 shortly.
echo Keep this window open while you use LanEx. Close it to stop the server.
echo.

REM --- Open the Windows browser a few seconds after the server boots ---------
start "" powershell -WindowStyle Hidden -Command "Start-Sleep -Seconds 4; Start-Process 'http://127.0.0.1:8765'"

REM --------------------------------------------------------------------------
REM IMPORTANT: launch with an INTERACTIVE shell (bash -ic), NOT bash -c.
REM
REM WSLg only initialises the GPU / Wayland display bridge for an *interactive*
REM login shell. With a plain `bash -c` the bridge never comes up and every
REM desktop viewer (GDS3D / KLayout / Magic GUI) crashes with "[WARN: COPY MODE]".
REM The `-i` is a HARD REQUIREMENT, not a nicety. Use exactly ONE wsl line here:
REM a second non-interactive line above it would run first, block, and the
REM interactive one would never execute (the original launcher's bug).
REM
REM If your distro is not named "Ubuntu", change -d Ubuntu below (run
REM `wsl -l -q` in PowerShell to see the exact name). If LanEx lives somewhere
REM other than ~/lanex, change the cd path to match install-lanex-wsl.sh.
REM --------------------------------------------------------------------------
wsl -d Ubuntu -- bash -ic "cd ~/lanex && source venv/bin/activate && python3 -m lanex --no-browser"

echo.
echo LanEx server stopped. You can close this window.
pause
