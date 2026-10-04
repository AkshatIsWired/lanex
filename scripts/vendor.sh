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

# CodeMirror 6 — the RTL IDE's editor (modules/ide/editor.js). npm packages,
# bundled by esbuild into one ES module from scripts/vendor/codemirror-entry.js
# (which lists exactly what the editor imports). MIT; licence copied beside it.
echo "==> CodeMirror 6 -> $VENDOR/codemirror.js"
CM_TMP="$(mktemp -d)"
cp "$(dirname "$0")/vendor/codemirror-entry.js" "$CM_TMP/entry.js"
(
  cd "$CM_TMP"
  npm init -y >/dev/null
  npm i --silent @codemirror/state@6 @codemirror/view@6 @codemirror/commands@6 @codemirror/language@6 \
    @codemirror/autocomplete@6 @codemirror/search@6 @codemirror/lint@6 @codemirror/legacy-modes@6 \
    @codemirror/lang-json@6 @lezer/highlight@1 esbuild
  npx esbuild entry.js --bundle --format=esm --minify --legal-comments=none --outfile=codemirror.js
)
cp "$CM_TMP/codemirror.js" "$VENDOR/codemirror.js"
cp "$CM_TMP/node_modules/@codemirror/view/LICENSE" "$VENDOR/codemirror.LICENSE"
rm -rf "$CM_TMP"

echo "==> Done. Files:"
ls -lh "$VENDOR"
