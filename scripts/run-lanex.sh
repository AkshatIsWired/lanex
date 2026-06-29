#!/usr/bin/env bash
# Launch LanEx — browser cockpit for the LibreLane RTL→GDSII flow.
# Runs from the repo without needing `pip install` (uses PYTHONPATH).
set -euo pipefail
REPO="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
cd "$REPO"
echo "Starting LanEx on http://127.0.0.1:8765/ …"
echo "Close this window or press Ctrl-C to stop the server."
exec env PYTHONPATH="$REPO" python3 -m lanex "$@"
