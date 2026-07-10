#!/usr/bin/env bash
# install-wsl.sh — back-compat entry point. The real installer is install.sh
# (universal: any major Linux distro, WSL2, macOS); this URL/name is kept
# working forever because it is baked into older READMEs and guides:
#
#   curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install-wsl.sh | bash
#
# Runs the sibling script when executed from a checkout, otherwise fetches the
# current install.sh from the repo and runs it.
set -u -o pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-/}")" 2>/dev/null && pwd || true)"
if [ -n "$HERE" ] && [ -f "$HERE/install.sh" ]; then
    exec bash "$HERE/install.sh" "$@"
fi

URL="https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install.sh"
if command -v curl >/dev/null 2>&1; then
    exec bash -c "$(curl -fsSL "$URL")"
elif command -v wget >/dev/null 2>&1; then
    exec bash -c "$(wget -qO- "$URL")"
fi
printf 'Need curl or wget to fetch the installer:\n  %s\n' "$URL" >&2
exit 1
