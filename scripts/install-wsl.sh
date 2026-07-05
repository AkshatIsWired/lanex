#!/usr/bin/env bash
# install-wsl.sh — one-shot LanEx setup for WSL Ubuntu / Debian-family Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install-wsl.sh | bash
#
# What it does (idempotent — safe to re-run; a re-run upgrades):
#   1. apt-installs the packages that fresh/minimal images are missing and that
#      otherwise surface as confusing bugs later:
#        pipx git            → PEP 668-safe install path (system pip refuses
#                              `pip install` on Ubuntu 23.04+)
#        xfonts-base         → GDS3D segfaults instantly without the legacy
#                              X11 "fixed" fonts
#        libgl1 libgl1-mesa-dri libegl1
#                            → Mesa GL drivers; without them every desktop GL
#                              viewer opens a blank window (even software
#                              rendering needs them — llvmpipe IS one of them)
#   2. Installs LanEx with pipx (PyPI when available, else from the git repo).
#   3. If Docker/Podman is present, pre-pulls the version-matched LibreLane
#      container image (`lanex --pull-image`) so the first run needs nothing.
#
# It does NOT touch your existing librelane/python environments. If you already
# run librelane in a venv/conda env, prefer `pip install lanex` INSIDE that env
# instead of this script (see the README's install table).
set -euo pipefail

REPO_URL="https://github.com/AkshatIsWired/lanex"
APT_PKGS=(pipx git xfonts-base libgl1 libgl1-mesa-dri libegl1)

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }

if ! command -v apt-get >/dev/null 2>&1; then
    warn "This script targets WSL Ubuntu / Debian-family Linux (needs apt)."
    warn "On other distros: install pipx + git + your distro's Mesa GL drivers"
    warn "and X11 misc fonts, then run:  pipx install lanex   (or pipx install . from a clone)"
    exit 1
fi

say "Installing system packages: ${APT_PKGS[*]}"
SUDO="sudo"
[ "$(id -u)" = "0" ] && SUDO=""
$SUDO apt-get update
$SUDO apt-get install -y "${APT_PKGS[@]}"

say "Making pipx-installed commands visible on your PATH"
pipx ensurepath >/dev/null 2>&1 || true
# ensurepath edits ~/.bashrc for FUTURE shells; export for this one too.
export PATH="$HOME/.local/bin:$PATH"

say "Installing LanEx with pipx"
if pipx list 2>/dev/null | grep -q "package lanex "; then
    # Already installed — upgrade in place (idempotent re-run).
    pipx upgrade lanex || true
elif pipx install lanex 2>/dev/null; then
    : # installed from PyPI
else
    warn "PyPI install unavailable — installing from the git repo instead."
    CLONE_DIR="${LANEX_CLONE_DIR:-$HOME/.cache/lanex-src}"
    if [ -d "$CLONE_DIR/.git" ]; then
        git -C "$CLONE_DIR" pull --ff-only
    else
        git clone --depth 1 "$REPO_URL" "$CLONE_DIR"
    fi
    # Non-editable on purpose: an editable install breaks if the clone moves.
    pipx install --force "$CLONE_DIR"
fi

say "Making the 'lanex' command available on your PATH"
# pipx drops the launcher in its bin dir (usually ~/.local/bin), which only lands
# on PATH in a NEW shell (ensurepath edits ~/.bashrc). This installer runs in a
# child process via `curl | bash` and CANNOT change your current shell's PATH —
# so without help you'd have to `source ~/.bashrc` before `lanex` is found.
# Symlink the launcher into /usr/local/bin (already on every shell's default
# PATH) so `lanex` works immediately, in this terminal and every future one.
PIPX_BIN="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || true)"
[ -n "$PIPX_BIN" ] || PIPX_BIN="$HOME/.local/bin"
LANEX_LAUNCHER="$PIPX_BIN/lanex"
LANEX_READY=0
if [ ! -x "$LANEX_LAUNCHER" ]; then
    warn "lanex was installed but its launcher wasn't found at $LANEX_LAUNCHER."
    warn "Open a new terminal and run:  lanex"
    exit 0
fi
if $SUDO ln -sf "$LANEX_LAUNCHER" /usr/local/bin/lanex 2>/dev/null; then
    LANEX_READY=1                 # on the global PATH now → usable in this shell
    hash -r 2>/dev/null || true
fi

if command -v docker >/dev/null 2>&1 || command -v podman >/dev/null 2>&1; then
    say "Pre-pulling the LibreLane container image (one-time, ~3 GB)"
    "$LANEX_LAUNCHER" --pull-image || warn "Image pull failed (offline / engine not ready?) — the Tools tab can retry it."
else
    warn "No Docker/Podman found. LanEx still works: open the Tools tab and use"
    warn "'Install the toolchain (recommended)' — it installs an engine and pulls"
    warn "the image for you in one go."
fi

say "Done — launch the cockpit with:  lanex"
if [ "$LANEX_READY" = "1" ]; then
    echo "The 'lanex' command is ready in THIS terminal now — no restart needed."
else
    echo "One step so your CURRENT shell can see it (a piped installer can't set"
    echo "your PATH for you):  run  source ~/.bashrc   (or open a new terminal)."
    echo "Or launch right now with the full path:  $LANEX_LAUNCHER"
fi
echo "Tip (WSL): launch from an interactive terminal (as you just did). If you"
echo "ever wrap LanEx in a script/shortcut, start it via 'bash -ic lanex' —"
echo "WSLg only brings up its GUI bridge for interactive shells, and desktop"
echo "viewers (KLayout/GDS3D) show a blank [WARN: COPY MODE] window without it."
