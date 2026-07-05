#!/usr/bin/env bash
# Runs INSIDE the official LibreLane image (invoked by the `rtl2gds` job in
# .github/workflows/ci.yml via `docker run ... bash scripts/ci-rtl2gds.sh`).
#
# Two things to know about that image:
#   1. It is nix-based, so a GitHub `container:` job can't run its JS actions in
#      it (injected Node can't exec). We therefore run the image with `docker
#      run` from the host and only run this shell inside it.
#   2. It ships python3 + librelane + ciel + the whole toolchain, but has NO pip
#      and NO pytest. So we install NOTHING: LanEx is pure-Python/stdlib, so we
#      just put the mounted repo on PYTHONPATH and run a plain driver script with
#      the image's own python.
#
# Expects (set by the workflow): repo mounted at /work, cwd=/work, PDK_ROOT
# writable.
set -euo pipefail

export PYTHONPATH="/work${PYTHONPATH:+:$PYTHONPATH}"

CIEL="ciel"
command -v ciel >/dev/null 2>&1 || CIEL="python3 -m ciel"

# The exact sky130 version LibreLane pins (LanEx's own resolver), falling back to
# the newest version ciel advertises if that can't be read.
VER="$(python3 -c 'from lanex.controller import installer; print(installer._pinned_pdk_version("sky130") or "")' || true)"
if [ -z "$VER" ]; then
  VER="$($CIEL ls-remote --pdk-family sky130 | head -n1 || true)"
fi
if [ -z "$VER" ]; then
  echo "could not resolve a sky130 version" >&2
  exit 1
fi
echo "sky130 version: $VER"

$CIEL fetch  --pdk-root "$PDK_ROOT" --pdk-family sky130 "$VER" -l sky130_fd_sc_hd
$CIEL enable --pdk-root "$PDK_ROOT" --pdk-family sky130 "$VER" -l sky130_fd_sc_hd

# The actual RTL->GDS run (bundled SPM example -> FlowRunner local -> GDSII).
python3 scripts/ci_rtl2gds_run.py
