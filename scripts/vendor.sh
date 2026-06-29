#!/usr/bin/env bash
# scripts/vendor.sh — re-fetch the offline-safe vendored libraries.
#
# Why vendored? The GUI MUST work in airgapped and bandwidth-restricted
# environments. We commit the binaries directly into
# ``lanex/server/static/vendor/`` to make first-load reproducible.
#
# Run this when bumping versions, then ``git add lanex/server/static/vendor``.
set -euo pipefail

VENDOR="$(cd "$(dirname "$0")/.." && pwd)/lanex/server/static/vendor"
mkdir -p "$VENDOR"

# Versions — bump deliberately. Keep in sync with the GUI's CSS/JS imports
# in `lanex/server/static/index.html` and `styles.css`.
ECHARTS_VERSION="5.5.1"

echo "==> ECharts  ${ECHARTS_VERSION} -> $VENDOR/echarts.min.js"
curl -fsSL \
  "https://cdn.jsdelivr.net/npm/echarts@${ECHARTS_VERSION}/dist/echarts.min.js" \
  -o "$VENDOR/echarts.min.js"

# three.js — used ONLY by the optional 3D GDS viewer (Phase 4 viewer3d.js). The
# viewer degrades to an honest "not installed" message when this file is absent,
# so vendoring it is opt-in and keeps the core lean.
THREE_VERSION="0.160.0"
echo "==> three.js ${THREE_VERSION} -> $VENDOR/three/three.module.js"
mkdir -p "$VENDOR/three"
curl -fsSL \
  "https://cdn.jsdelivr.net/npm/three@${THREE_VERSION}/build/three.module.js" \
  -o "$VENDOR/three/three.module.js"

echo "==> Done. Files:"
ls -lh "$VENDOR"
