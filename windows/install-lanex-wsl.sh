#!/usr/bin/env bash
# One-time LanEx setup inside WSL (Ubuntu). Run ONCE from inside WSL:
#
#     bash install-lanex-wsl.sh
#
# Afterwards, launch LanEx from Windows by double-clicking Launch-LanEx.bat.
#
# This sets up the WSL-native path (LanEx + light tools running directly in
# Ubuntu, so the desktop GL viewers render through WSLg). The FULL RTL->GDSII
# flow additionally needs the heavy EDA toolchain (OpenROAD / Magic / KLayout /
# Netgen). Installing those natively in WSL is the fragile part — for a
# guaranteed full flow, prefer the Docker image (see ../README.md), or let
# LanEx fall back to `librelane --dockerized` from inside WSL.
set -e

REPO_URL="https://github.com/AkshatIsWired/lanex"
DEST="$HOME/lanex"

echo "==> Installing base packages (python, git, iverilog, graphviz)…"
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip git iverilog graphviz

echo "==> Fetching LanEx into $DEST…"
if [ -d "$DEST/.git" ]; then
    git -C "$DEST" pull --ff-only || echo "   (could not fast-forward; using existing checkout)"
else
    git clone "$REPO_URL" "$DEST"
fi

echo "==> Creating virtualenv + installing LanEx…"
cd "$DEST"
python3 -m venv venv
# shellcheck disable=SC1091
. venv/bin/activate
pip install --upgrade pip
pip install .

echo
echo "Done. LanEx is installed at $DEST."
echo "Launch it from Windows by double-clicking Launch-LanEx.bat."
echo "(For the full chip flow, install the EDA toolchain or use the Docker image.)"
