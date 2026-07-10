#!/usr/bin/env bash
# install.sh — universal LanEx installer: Linux (any major distro), WSL2, macOS.
#
#   curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install.sh | bash
#   # no curl on a fresh box? wget works the same:
#   wget -qO- https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install.sh | bash
#
# DESIGN RULES (read before editing):
#   * Every stage is a FALLBACK CHAIN. The bottom of every chain is a plain
#     `python3 -m venv` install that needs nothing but Python >= 3.10 — so the
#     script can always land somewhere, whatever the distro/package manager.
#   * No `set -e`: a missing nice-to-have (pipx package, GL fonts, image pull)
#     must degrade with a warning, never abort the install. Unrecoverable
#     problems go through die() with a specific, actionable message.
#   * The whole script is wrapped in main() called on the LAST LINE, so a
#     partially downloaded `curl | bash` can never execute half a command.
#   * Idempotent: re-running upgrades LanEx in place.
#   * bash 3.2 compatible (macOS ships bash 3.2): no readarray, no assoc arrays.
#
# Environment knobs:
#   LANEX_FROM=github|pypi|<path or pip URL>  install source. Default: the
#                     GitHub tarball of main (works before the PyPI release and
#                     cannot be name-squatted). After the PyPI release, pypi.
#   LANEX_REF=<ref>   GitHub branch/tag for the default source (default: main)
#   LANEX_SKIP_PULL=1 skip the optional container-image pre-pull
#   LANEX_NO_PIPX=1   skip pipx entirely (escape hatch for a broken pipx);
#                     installs into the ~/.lanex/venv fallback instead
#   LANEX_ASSUME_YES=1  never prompt (CI / unattended)
set -u -o pipefail

REPO="AkshatIsWired/lanex"
REF="${LANEX_REF:-main}"
TARBALL="https://github.com/${REPO}/archive/refs/heads/${REF}.tar.gz"

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }
die()  { printf '\n\033[31mXX %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- platform --
OS="linux"; PKG="none"; WSL=0; WSL1=0; SUDO=""

detect_platform() {
    case "$(uname -s)" in
        Darwin) OS="macos" ;;
        Linux)  OS="linux" ;;
        *)      die "Unsupported OS '$(uname -s)'. LanEx runs on Linux, WSL2 and macOS." ;;
    esac
    if [ "$OS" = "linux" ] && grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
        WSL=1
        # WSL1 kernels identify as "...-Microsoft" (capital M, no "WSL2").
        case "$(uname -r)" in
            *Microsoft*) WSL1=1 ;;
        esac
    fi
    if command -v apt-get >/dev/null 2>&1;   then PKG="apt"
    elif command -v dnf >/dev/null 2>&1;     then PKG="dnf"
    elif command -v pacman >/dev/null 2>&1;  then PKG="pacman"
    elif command -v zypper >/dev/null 2>&1;  then PKG="zypper"
    fi
    [ "$OS" = "macos" ] && PKG="brew"
}

setup_privileges() {
    if [ "$(id -u)" = "0" ]; then
        # `curl | sudo bash` installs LanEx into root's home while the real
        # user's shell can't see it — a classic broken install (and the cause
        # of root-owned ~/.local / ~/.ciel messes). Refuse with the exact fix.
        if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
            die "Don't run this installer with sudo — run it as your normal user.
   It calls sudo itself only where needed (system packages, one symlink).
   Fix:  curl -fsSL https://raw.githubusercontent.com/${REPO}/main/scripts/install.sh | bash"
        fi
        SUDO=""     # genuinely root (container, WSL root user): fine.
    elif command -v sudo >/dev/null 2>&1; then
        SUDO="sudo"
    else
        SUDO=""
        warn "Neither root nor sudo available — skipping system packages."
        warn "If something is missing later, install sudo or re-run as root."
        PKG="none"
    fi
}

# --------------------------------------------------------------- preflight --
net_check() {
    if command -v curl >/dev/null 2>&1; then
        curl -fsI -m 12 https://github.com >/dev/null 2>&1 && return 0
    elif command -v wget >/dev/null 2>&1; then
        wget -q --spider -T 12 https://github.com >/dev/null 2>&1 && return 0
    else
        return 0   # no probe tool yet — let the real download speak later
    fi
    if [ "$WSL" = "1" ]; then
        die "Cannot reach github.com — on WSL this is almost always the broken
   auto-generated /etc/resolv.conf. Fix (one time):
     sudo sh -c 'printf \"[network]\\ngenerateResolvConf = false\\n\" >> /etc/wsl.conf'
     sudo rm -f /etc/resolv.conf
     sudo sh -c 'echo nameserver 8.8.8.8 > /etc/resolv.conf'
   then from Windows:  wsl --shutdown   and re-open Ubuntu and re-run this."
    fi
    die "Cannot reach github.com — check your network/proxy and re-run.
   (Proxies: export https_proxy=... before re-running; apt/pip/curl honour it.)"
}

disk_free_gb() {  # free space in GiB on $HOME (portable-ish df)
    df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}'
}

# ------------------------------------------------------------ system deps  --
apt_stage() {
    # Fresh-boot Ubuntu/WSL often holds the dpkg lock (unattended-upgrades);
    # DPkg::Lock::Timeout waits instead of dying with "could not get lock".
    local A="$SUDO apt-get -o DPkg::Lock::Timeout=300"
    say "System packages (apt)"
    $A update || warn "apt update failed — trying with the existing package lists."
    # Must-haves: interpreter + venv (pipx AND the venv fallback both need it).
    $A install -y python3 python3-venv ca-certificates \
        || die "apt could not install python3/python3-venv. Run 'sudo apt update' manually, read its error, then re-run this script."
    # Nice-to-haves: each degrades alone. pipx: not packaged before Ubuntu 22.04
    # / Debian 12 (those pythons are too old anyway — caught below).
    $A install -y pipx || warn "no apt 'pipx' package — will fall back to pip/venv."
    # git: the in-app GDS3D viewer build clones its source, and git-based
    # installs need it. Its absence surfaces much later as a confusing
    # "gds3d install failed — needs: git" in the Tools tab.
    $A install -y git || warn "git failed to install — the GDS3D build (Tools tab) needs it."
    # X11 fixed fonts + Mesa GL: without them GDS3D segfaults and GL viewers
    # open blank windows. Cosmetic for the cockpit itself → never fatal.
    $A install -y xfonts-base libgl1 libgl1-mesa-dri libegl1 \
        || warn "GL/font packages failed to install — desktop viewers may need them later (Tools tab offers a one-click fix)."
}

dnf_stage() {
    say "System packages (dnf)"
    $SUDO dnf install -y python3 python3-pip \
        || die "dnf could not install python3. Fix dnf, then re-run."
    $SUDO dnf install -y pipx || warn "no dnf 'pipx' package — will fall back to pip/venv."
    $SUDO dnf install -y git || warn "git failed to install — the GDS3D build (Tools tab) needs it."
    $SUDO dnf install -y mesa-dri-drivers xorg-x11-fonts-misc \
        || warn "GL/font packages failed — desktop viewers may need them later."
}

pacman_stage() {
    say "System packages (pacman)"
    $SUDO pacman -Sy --noconfirm --needed python \
        || die "pacman could not install python. Fix pacman, then re-run."
    $SUDO pacman -S --noconfirm --needed python-pipx || warn "no 'python-pipx' — will fall back to pip/venv."
    $SUDO pacman -S --noconfirm --needed git || warn "git failed to install — the GDS3D build (Tools tab) needs it."
    $SUDO pacman -S --noconfirm --needed mesa xorg-fonts-misc \
        || warn "GL/font packages failed — desktop viewers may need them later."
}

zypper_stage() {
    say "System packages (zypper)"
    $SUDO zypper --non-interactive install python3 python3-pip \
        || die "zypper could not install python3. Fix zypper, then re-run."
    $SUDO zypper --non-interactive install python3-pipx || warn "no 'python3-pipx' — will fall back to pip/venv."
    $SUDO zypper --non-interactive install git-core || warn "git failed to install — the GDS3D build (Tools tab) needs it."
    $SUDO zypper --non-interactive install Mesa-dri xorg-x11-fonts-legacy \
        || warn "GL/font packages failed — desktop viewers may need them later."
}

brew_stage() {
    say "Homebrew"
    # Apple Silicon brew lives at /opt/homebrew, Intel at /usr/local — neither
    # is guaranteed on PATH in this shell.
    [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
    [ -x /usr/local/bin/brew ]    && eval "$(/usr/local/bin/brew shellenv)"
    if ! command -v brew >/dev/null 2>&1; then
        warn "Homebrew not found. macOS's bundled Python is 3.9 — too old for LanEx (needs >= 3.10) — so Homebrew is the practical path."
        if [ "${LANEX_ASSUME_YES:-0}" = "1" ] || { [ -t 0 ] || [ -r /dev/tty ]; }; then
            local ans="y"
            if [ "${LANEX_ASSUME_YES:-0}" != "1" ]; then
                printf 'Install Homebrew now? [Y/n] ' > /dev/tty 2>/dev/null || true
                read -r ans < /dev/tty 2>/dev/null || ans="y"
            fi
            case "$ans" in
                n*|N*) note "Skipping Homebrew. If 'python3 --version' is >= 3.10 the install can still proceed." ;;
                *)  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" \
                        || warn "Homebrew install failed — continuing; the venv fallback still works if python3 >= 3.10 exists."
                    [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"
                    [ -x /usr/local/bin/brew ]    && eval "$(/usr/local/bin/brew shellenv)"
                    ;;
            esac
        fi
    fi
    if command -v brew >/dev/null 2>&1; then
        say "System packages (brew)"
        if ! best_python >/dev/null; then
            brew install python@3.12 || brew install python || warn "brew python install failed."
        fi
        command -v pipx >/dev/null 2>&1 || brew install pipx || warn "brew pipx failed — will fall back to pip/venv."
    fi
}

system_deps() {
    case "$PKG" in
        apt)    apt_stage ;;
        dnf)    dnf_stage ;;
        pacman) pacman_stage ;;
        zypper) zypper_stage ;;
        brew)   brew_stage ;;
        none)   warn "No known package manager (apt/dnf/pacman/zypper/brew) usable — skipping system packages. Continuing with what's already installed." ;;
    esac
}

# ------------------------------------------------------------------ python --
PY=""
best_python() {
    local c
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$c" >/dev/null 2>&1 \
           && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
            command -v "$c"
            return 0
        fi
    done
    return 1
}

require_python() {
    PY="$(best_python || true)"
    [ -n "$PY" ] && { note "Using $("$PY" --version 2>&1) at $PY"; return; }
    local have="none"
    command -v python3 >/dev/null 2>&1 && have="$(python3 --version 2>&1)"
    die "LanEx needs Python >= 3.10; found: ${have}.
   Ubuntu/Debian: use Ubuntu 22.04+ / Debian 12+ (older releases ship an EOL python).
     On WSL: install a newer distro:  wsl --install -d Ubuntu-24.04
   RHEL/CentOS 9: sudo dnf install -y python3.11  (then re-run this script)
   macOS: install Homebrew, then:  brew install python  (then re-run)"
}

# ------------------------------------------------------------ install lanex --
LAUNCHER=""     # absolute path to the lanex executable once installed
resolve_source() {
    case "${LANEX_FROM:-github}" in
        github) echo "$TARBALL" ;;                     # no git needed, no PyPI-squat risk
        pypi)   echo "lanex" ;;                        # flip default after the PyPI release
        *)      echo "${LANEX_FROM}" ;;                # a local path / any pip spec
    esac
}

ensure_pipx() {
    command -v pipx >/dev/null 2>&1 && return 0
    # pip --user works on non-PEP-668 distros; on Debian/Ubuntu it refuses
    # ("externally-managed-environment") → the venv fallback takes over. Never
    # use --break-system-packages: it can corrupt the distro's own Python.
    "$PY" -m pip install --user pipx >/dev/null 2>&1 || return 1
    export PATH="$HOME/.local/bin:$PATH"
    command -v pipx >/dev/null 2>&1
}

install_with_pipx() {
    export PATH="$HOME/.local/bin:$PATH"
    ensure_pipx || return 1
    say "Installing LanEx with pipx"
    pipx ensurepath >/dev/null 2>&1 || true
    # --force = idempotent upgrade for tarball/clone installs (a plain
    # `pipx upgrade` sees the same version number in the tarball and no-ops).
    pipx install --force --python "$PY" "$(resolve_source)" || return 1
    local bin
    bin="$(pipx environment --value PIPX_BIN_DIR 2>/dev/null || true)"
    [ -n "$bin" ] || bin="$HOME/.local/bin"
    [ -x "$bin/lanex" ] || return 1
    LAUNCHER="$bin/lanex"
}

install_with_venv() {
    # The universal bottom of the chain: nothing but python3 + venv.
    say "Installing LanEx into its own virtualenv (~/.lanex/venv)"
    local venv="$HOME/.lanex/venv"
    "$PY" -m venv "$venv" 2>/dev/null || {
        # Two known causes: Debian splits venv out of python3 (apt_stage
        # installs it, but a 'none' package-manager path can miss it), or
        # ~/.lanex is root-owned from an earlier sudo mishap.
        die "python3 -m venv failed. Either install your distro's python3-venv package
   (Debian/Ubuntu: sudo apt install python3-venv), or — if 'ls -ld $HOME/.lanex'
   shows root as the owner — fix it with: sudo chown -R \$(id -u):\$(id -g) $HOME/.lanex
   Then re-run this script."
    }
    "$venv/bin/pip" install --quiet --upgrade pip 2>/dev/null || true
    "$venv/bin/pip" install --upgrade "$(resolve_source)" || return 1
    [ -x "$venv/bin/lanex" ] || die "install finished but $venv/bin/lanex is missing — please report this."
    LAUNCHER="$venv/bin/lanex"
}

attempt_install() {
    if [ "${LANEX_NO_PIPX:-0}" != "1" ] && install_with_pipx; then
        return 0
    fi
    install_with_venv
}

build_tools_stage() {
    # A dependency shipped no prebuilt wheel for this Python (seen live: Arch's
    # Python 3.13 + librelane's lln-libparse) → pip compiles it from source,
    # which needs a C/C++ toolchain that minimal installs don't have.
    say "A dependency must be compiled from source — installing build tools, then retrying"
    case "$PKG" in
        apt)    $SUDO apt-get -o DPkg::Lock::Timeout=300 install -y build-essential python3-dev || true ;;
        dnf)    $SUDO dnf install -y gcc gcc-c++ make python3-devel || true ;;
        pacman) $SUDO pacman -S --noconfirm --needed base-devel || true ;;
        zypper) $SUDO zypper --non-interactive install gcc gcc-c++ make python3-devel || true ;;
        brew)   xcode-select --install 2>/dev/null || true ;;
        *)      warn "No package manager to install a compiler with." ;;
    esac
}

install_lanex() {
    attempt_install && return 0
    build_tools_stage
    attempt_install \
        || die "Could not install LanEx from $(resolve_source).
   Read the pip error above. Usual causes: network hiccup (just re-run this
   script), or a dependency without a prebuilt wheel for very new Python
   versions. If it persists, install a Python 3.10-3.12 (e.g. sudo dnf
   install python3.11 / brew install python@3.12) and re-run."
}

# -------------------------------------------------------------------- PATH --
expose_on_path() {
    say "Making the 'lanex' command available on your PATH"
    # A piped installer runs in a child process and cannot change the parent
    # shell's PATH — a symlink in /usr/local/bin (on every shell's default
    # PATH) makes `lanex` work immediately, in THIS terminal and all future ones.
    if $SUDO ln -sf "$LAUNCHER" /usr/local/bin/lanex 2>/dev/null; then
        hash -r 2>/dev/null || true
        note "'lanex' is ready in this terminal now."
        return 0
    fi
    warn "Could not write /usr/local/bin (no sudo?). Two other ways:"
    note "open a NEW terminal and run:  lanex        (PATH set up for future shells)"
    note "or launch right now with:     $LAUNCHER"
    # Make future shells work even without the symlink.
    case ":${PATH}:" in *":$(dirname "$LAUNCHER"):"*) : ;; *)
        local rc="$HOME/.bashrc"; [ -n "${ZSH_VERSION:-}" ] && rc="$HOME/.zshrc"
        printf '\nexport PATH="%s:$PATH"\n' "$(dirname "$LAUNCHER")" >> "$rc" 2>/dev/null || true
    esac
}

# ------------------------------------------------------------------ verify --
verify_install() {
    say "Verifying"
    if ! "$LAUNCHER" --help >/dev/null 2>&1; then
        die "LanEx installed but '$LAUNCHER --help' failed — please re-run; if it persists, report the output of:  $LAUNCHER --help"
    fi
    note "lanex responds. Install OK."
}

# -------------------------------------------------------------- extras/WSL --
prepull_image() {
    [ "${LANEX_SKIP_PULL:-0}" = "1" ] && return 0
    if command -v docker >/dev/null 2>&1 || command -v podman >/dev/null 2>&1; then
        local free; free="$(disk_free_gb)"
        if [ -n "$free" ] && [ "$free" -lt 8 ]; then
            warn "Only ${free} GB free in \$HOME — skipping the ~3 GB image pre-pull. Free space, then run:  lanex --pull-image"
            return 0
        fi
        say "Pre-pulling the LibreLane container image (one-time, ~3 GB)"
        if ! "$LAUNCHER" --pull-image; then
            warn "Image pull failed — the Tools tab can retry it."
            if [ "$WSL" = "1" ] && command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1; then
                note "Docker is installed but its daemon isn't running. On WSL without systemd:  sudo service docker start"
                note "(or enable systemd:  add [boot]\\nsystemd=true to /etc/wsl.conf, then from Windows:  wsl --shutdown)"
            fi
        fi
    else
        warn "No Docker/Podman found. LanEx still works: the Tools tab's"
        warn "'Install the toolchain (recommended)' installs an engine and pulls the image in one go."
    fi
}

wsl_notes() {
    [ "$WSL" = "1" ] || return 0
    if [ "$WSL1" = "1" ]; then
        warn "This distro runs under WSL 1 — Docker and the GUI viewers need WSL 2."
        note "From Windows PowerShell:  wsl --set-version ${WSL_DISTRO_NAME:-<your-distro>} 2"
    fi
    note "Tip (WSL): launch from an interactive terminal. If you ever wrap LanEx in a"
    note "script/shortcut, start it via 'bash -ic lanex' — WSLg only brings up its GUI"
    note "bridge for interactive shells (desktop viewers blank-window without it)."
}

# -------------------------------------------------------------------- main --
main() {
    detect_platform
    setup_privileges
    say "LanEx installer — $OS$( [ "$WSL" = "1" ] && echo ' (WSL)') / packages: $PKG"
    net_check
    system_deps
    require_python
    install_lanex
    expose_on_path
    verify_install
    prepull_image
    wsl_notes
    say "Done — launch the cockpit with:  lanex"
    note "Re-running this installer later upgrades LanEx in place."
}

main "$@"
