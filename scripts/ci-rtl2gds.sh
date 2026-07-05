#!/usr/bin/env bash
# Runs INSIDE the official LibreLane image (invoked by the `rtl2gds` job in
# .github/workflows/ci.yml via `docker run ... bash scripts/ci-rtl2gds.sh`).
#
# We run the image with `docker run` from the host rather than as a GitHub
# `container:` job on purpose: a container job makes GitHub inject a Node
# runtime into the image to run its JS actions (checkout etc.), and the
# nix-based LibreLane image can't exec that binary ("no such file or
# directory"). Here checkout runs on the host; only this shell runs in-image.
#
# Expects (set by the workflow): PDK_ROOT (writable), LANEX_RTL2GDS=1, cwd=repo.
set -euo pipefail

# Install LanEx WITHOUT deps so we never disturb the image's pinned librelane
# and its matched toolchain (LanEx adds no runtime deps of its own).
python3 -m pip install --no-deps . || pip install --no-deps .
python3 -m pip install pytest || pip install pytest

# Resolve the exact sky130 version LibreLane pins (same value a real run would
# resolve), using LanEx's own resolver, then fetch + enable just the default
# high-density standard-cell library.
CIEL=ciel
command -v ciel >/dev/null 2>&1 || CIEL="python3 -m ciel"

VER="$(python3 -c 'from lanex.controller import installer; print(installer._pinned_pdk_version("sky130") or "")')"
if [ -z "$VER" ]; then
  echo "could not resolve the pinned sky130 version" >&2
  exit 1
fi
echo "sky130 pinned version: $VER"

$CIEL fetch  --pdk-root "$PDK_ROOT" --pdk-family sky130 "$VER" -l sky130_fd_sc_hd
$CIEL enable --pdk-root "$PDK_ROOT" --pdk-family sky130 "$VER" -l sky130_fd_sc_hd

# The actual RTL->GDS run (scaffold counter -> FlowRunner local -> GDSII).
python3 -m pytest lanex/tests/test_rtl2gds.py -q -rs
