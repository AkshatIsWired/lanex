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
#   * Two faces, one engine. In a terminal a person can answer, the installer
#     is interactive (logo, profile picker, Custom checklist, live progress);
#     everywhere else (no tty, LANEX_ASSUME_YES=1, the Windows appliance's
#     LANEX_PIP_LOCK) it prints plain lines exactly as before. Both run the
#     same stage functions.
#
# The real terminal type, kept for the interactive installer before every child
# process is told TERM=dumb (plain, parseable output for the logs and for
# Windows Setup's live view).
_LX_TERM="${TERM:-}"
export COLUMNS=120
export LINES=40
export TERM=dumb
shopt -s extglob 2>/dev/null || true

# Environment knobs:
#   LANEX_FROM=github|pypi|<path or pip URL>  install source. Default: the
#                     GitHub tarball of main (works before the PyPI release and
#                     cannot be name-squatted). After the PyPI release, pypi.
#   LANEX_REF=<ref>   GitHub branch, tag, or commit SHA for the default source
#                     (default: main)
#   LANEX_REPO=<owner/name>  GitHub repository for LANEX_REF (default:
#                     AkshatIsWired/lanex; useful for fork candidates)
#   LANEX_PIP_CONSTRAINT=<path>  optional pip constraints file (versions only).
#   LANEX_PIP_LOCK=<path>  hash-locked requirements file (the Windows appliance).
#                     Every dependency is installed with pip --require-hashes
#                     into a plain venv at pipx's usual path; there is no
#                     unpinned fallback when this is set.
#   LANEX_SKIP_PULL=1 skip the optional container-image pre-pull
#   LANEX_SKIP_GDS3D=1  skip the optional GDS3D 3D-viewer build/install
#   LANEX_NO_PIPX=1   skip pipx entirely (escape hatch for a broken pipx);
#                     installs into the ~/.lanex/venv fallback instead
#   LANEX_ASSUME_YES=1  never prompt (CI / unattended)
#   LANEX_PROFILE=recommended|complete|minimal  also install the components
#                     the Windows Setup profile of the same name installs (the
#                     container engine, LibreLane image, native tools, PDKs).
#                     Unattended equivalent of the interactive picker; also
#                     settable as  bash -s -- --profile <name>
#   LANEX_CHOICES=<path>  a Setup choices JSON (any profile, including custom)
#   LANEX_MANIFEST=<path> build manifest (image digest, PDK pins) to install
#                     components against. Default: made from the installed
#                     LanEx (its pinned image digest, PDK catalog and pins).
#   LANEX_NO_UI=1     plain output even in an interactive terminal
#   LANEX_ASCII=1     interactive installer without Unicode glyphs
#   LANEX_NO_ANIM=1   skip the intro animation
#   NO_COLOR=1        interactive installer without colour
set -u -o pipefail

REPO="${LANEX_REPO:-AkshatIsWired/lanex}"
REF="${LANEX_REF:-main}"
# codeload's ref-aware endpoint resolves branches, tags, and full commit SHAs.
# The old branch-qualified archive URL silently made tags and SHAs impossible.
TARBALL="https://codeload.github.com/${REPO}/tar.gz/${REF}"

if [ -n "${LANEX_PIP_CONSTRAINT:-}" ]; then
    [ -f "$LANEX_PIP_CONSTRAINT" ] \
        || { printf 'LanEx pip constraints file not found: %s\n' "$LANEX_PIP_CONSTRAINT" >&2; exit 1; }
    # pip and the pip subprocess launched by pipx both honour PIP_CONSTRAINT.
    export PIP_CONSTRAINT="$LANEX_PIP_CONSTRAINT"
fi

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
note() { printf '   %s\n' "$*"; }
warn() { printf '\033[33m!! %s\033[0m\n' "$*"; }
die()  {
    # Under the interactive installer a stage runs in a background subshell;
    # its message is handed to the failure screen through this file.
    if [ -n "${LX_FAILMSG:-}" ]; then printf '%s\n' "$*" > "$LX_FAILMSG" 2>/dev/null || true; fi
    printf '\n\033[31mXX %s\033[0m\n' "$*" >&2; exit 1;
}

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
    local source="${LANEX_FROM:-github}"
    if [ "$source" != "github" ] && [ "$source" != "pypi" ] && [ -e "$source" ]; then
        return 0
    fi
    local url="https://codeload.github.com/${REPO}/tar.gz/${REF}" out rc detail
    if command -v curl >/dev/null 2>&1; then
        out="$(mktemp)" || die "Could not create a temporary network diagnostic."
        curl -fsSL -I --connect-timeout 10 --max-time 15 --retry 2 \
            -o /dev/null "$url" 2>"$out"
        rc=$?
        if [ "$rc" -eq 0 ]; then rm -f "$out"; return 0; fi
        detail="$(tail -n 8 "$out" | sed -E \
            's#(https?://)[^/@[:space:]]+:[^/@[:space:]]+@#\1[redacted]@#g')"
        rm -f "$out"
        case "$rc" in
            5|6) die "DNS could not resolve the LanEx source host.
   ${detail}
   Preserve WSL's generated resolver/DNS tunneling; check VPN or company DNS, then re-run." ;;
            7) die "The source host resolved, but no connection route was available.
   ${detail}
   Check VPN, firewall and IPv4/IPv6 routing, then re-run." ;;
            28) die "The source download exceeded its bounded timeout.
   ${detail}
   Check a slow connection or proxy, then re-run; completed caches are retained." ;;
            35|51|58|60|77|80|83|90) die "TLS certificate verification failed for the LanEx source.
   ${detail}
   Check the clock, CA certificates or inspecting proxy; TLS verification is not disabled." ;;
            *) die "The LanEx source download failed (curl ${rc}).
   ${detail}
   Check the exact error, current proxy/VPN and source access, then re-run." ;;
        esac
    elif command -v wget >/dev/null 2>&1; then
        wget -q --spider -T 25 "$url" >/dev/null 2>&1 && return 0
    else
        return 0   # no probe tool yet — let the real download speak later
    fi
    die "The LanEx source could not be reached with wget. Check its output, network/proxy and re-run."
}

disk_free_gb() {  # free space in GiB on $HOME (portable-ish df)
    df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}'
}

# ------------------------------------------------------------ system deps  --
apt_run() {
    if [ -n "$SUDO" ]; then
        # $SUDO, not a literal sudo: the interactive installer sets it to
        # "sudo -n" after asking for the password once, so a lapsed ticket
        # fails with a message instead of a hidden prompt behind the screen.
        # APT::Status-Fd=1 adds machine-readable "pmstatus:" progress lines
        # that the interactive installer turns into its activity line.
        # Under the interactive installer nobody can answer a debconf
        # question (the screen is drawn over it), and sudo drops a plain
        # exported DEBIAN_FRONTEND, so it is passed through env.
        $SUDO ${LX_APT_STATUS:+env DEBIAN_FRONTEND=noninteractive} apt-get -o DPkg::Lock::Timeout=300 \
            -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::Retries=3 \
            ${LX_APT_STATUS:+-o APT::Status-Fd=1 -o Dpkg::Options::=--force-confold} "$@"
    else
        apt-get -o DPkg::Lock::Timeout=300 -o Acquire::http::Timeout=30 \
            -o Acquire::https::Timeout=30 -o Acquire::Retries=3 ${LX_APT_STATUS:+-o APT::Status-Fd=1} "$@"
    fi
}

apt_stage() {
    # Fresh-boot Ubuntu/WSL often holds the dpkg lock (unattended-upgrades);
    # DPkg::Lock::Timeout waits instead of dying with "could not get lock".
    say "System packages (apt)"
    # A previous run stopped mid-install leaves dpkg half-configured, and
    # every apt-get then refuses until this is run. A no-op otherwise.
    $SUDO dpkg --configure -a >/dev/null 2>&1 || true
    apt_run update || warn "apt update failed — trying with the existing package lists."
    # Must-haves: interpreter + venv (pipx AND the venv fallback both need it).
    apt_run install -y python3 python3-venv ca-certificates \
        || die "apt could not install python3/python3-venv. Run 'sudo apt update' manually, read its error, then re-run this script."
    # Nice-to-haves: each degrades alone. pipx: not packaged before Ubuntu 22.04
    # / Debian 12 (those pythons are too old anyway — caught below).
    apt_run install -y pipx || warn "no apt 'pipx' package — will fall back to pip/venv."
    # git: the in-app GDS3D viewer build clones its source, and git-based
    # installs need it. Its absence surfaces much later as a confusing
    # "gds3d install failed — needs: git" in the Tools tab.
    apt_run install -y git || warn "git failed to install — the GDS3D build (Tools tab) needs it."
    # X11 fixed fonts + Mesa GL: without them GDS3D segfaults and GL viewers
    # open blank windows. Cosmetic for the cockpit itself → never fatal.
    apt_run install -y xfonts-base libgl1 libgl1-mesa-dri libegl1 \
        || warn "GL/font packages failed to install — desktop viewers may need them later (Tools tab offers a one-click fix)."
    # gtkwave: the RTL IDE's "Open in GTKWave" waveform viewer. Optional —
    # the built-in canvas viewer works without it; the Tools tab can retry.
    apt_run install -y gtkwave \
        || warn "gtkwave failed to install — the RTL IDE's 'Open in GTKWave' needs it (Tools tab can retry)."
}

dnf_stage() {
    say "System packages (dnf)"
    $SUDO dnf install -y python3 python3-pip \
        || die "dnf could not install python3. Fix dnf, then re-run."
    $SUDO dnf install -y pipx || warn "no dnf 'pipx' package — will fall back to pip/venv."
    $SUDO dnf install -y git || warn "git failed to install — the GDS3D build (Tools tab) needs it."
    $SUDO dnf install -y mesa-dri-drivers xorg-x11-fonts-misc \
        || warn "GL/font packages failed — desktop viewers may need them later."
    $SUDO dnf install -y gtkwave \
        || warn "gtkwave failed to install — the RTL IDE's 'Open in GTKWave' needs it (Tools tab can retry)."
}

pacman_stage() {
    say "System packages (pacman)"
    $SUDO pacman -Sy --noconfirm --needed python \
        || die "pacman could not install python. Fix pacman, then re-run."
    $SUDO pacman -S --noconfirm --needed python-pipx || warn "no 'python-pipx' — will fall back to pip/venv."
    $SUDO pacman -S --noconfirm --needed git || warn "git failed to install — the GDS3D build (Tools tab) needs it."
    $SUDO pacman -S --noconfirm --needed mesa xorg-fonts-misc \
        || warn "GL/font packages failed — desktop viewers may need them later."
    $SUDO pacman -S --noconfirm --needed gtkwave \
        || warn "gtkwave failed to install — the RTL IDE's 'Open in GTKWave' needs it (Tools tab can retry)."
}

zypper_stage() {
    say "System packages (zypper)"
    $SUDO zypper --non-interactive install python3 python3-pip \
        || die "zypper could not install python3. Fix zypper, then re-run."
    $SUDO zypper --non-interactive install python3-pipx || warn "no 'python3-pipx' — will fall back to pip/venv."
    $SUDO zypper --non-interactive install git-core || warn "git failed to install — the GDS3D build (Tools tab) needs it."
    $SUDO zypper --non-interactive install Mesa-dri xorg-x11-fonts-legacy \
        || warn "GL/font packages failed — desktop viewers may need them later."
    $SUDO zypper --non-interactive install gtkwave \
        || warn "gtkwave failed to install — the RTL IDE's 'Open in GTKWave' needs it (Tools tab can retry)."
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
        # gtkwave: homebrew-core gained the FORMULA in 2024 (the old cask was
        # broken on modern macOS and removed). An old brew needs `brew update`.
        command -v gtkwave >/dev/null 2>&1 || brew install gtkwave \
            || warn "gtkwave failed to install — run 'brew update && brew install gtkwave' later (the RTL IDE's 'Open in GTKWave' needs it)."
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

install_with_lock() {
    # Same location pipx would use, so the appliance's paths stay the same, but
    # no pipx: pipx upgrades its own shared pip from PyPI and cannot install a
    # local wheel in hash-checking mode. The venv's pip is the one python3-venv
    # ships, which comes from the pinned package snapshot.
    say "Installing LanEx and its locked dependencies (hash-checked)"
    local venv="$HOME/.local/share/pipx/venvs/lanex" src
    src="$(resolve_source)"
    [ -f "$src" ] || die "LANEX_PIP_LOCK needs a local LanEx wheel in LANEX_FROM, got: $src"
    rm -rf "$venv"
    "$PY" -m venv "$venv" || die "python3 -m venv failed for $venv."
    "$venv/bin/pip" install --disable-pip-version-check --require-hashes --no-deps \
        --only-binary=:all: -r "$LANEX_PIP_LOCK" \
        || die "A locked Python dependency could not be downloaded or did not match its pinned SHA-256.
   The pip output above names the package. Check the connection and run Setup again."
    "$venv/bin/pip" install --disable-pip-version-check --no-deps --no-index "$src" \
        || die "The bundled LanEx wheel could not be installed: $src"
    "$venv/bin/pip" check --disable-pip-version-check \
        || die "The locked Python dependencies are inconsistent (pip check failed)."
    mkdir -p "$HOME/.local/bin"
    ln -sf "$venv/bin/lanex" "$HOME/.local/bin/lanex"
    LAUNCHER="$HOME/.local/bin/lanex"
}

attempt_install() {
    local rc=0
    if [ -n "${LANEX_PIP_LOCK:-}" ]; then
        install_with_lock
    elif [ "${LANEX_NO_PIPX:-0}" != "1" ] && install_with_pipx; then
        rc=0
    else
        install_with_venv || return 1
    fi
    local py_site
    py_site="$("$LAUNCHER" -c "import sysconfig; print(sysconfig.get_path('purelib'))" 2>/dev/null || true)"
    if [ -d "$py_site" ]; then
        # httpx's default timeout raised when httpx is first imported (not at
        # every interpreter start); same line as installer.py _HTTPX_TIMEOUT_PTH.
        cat << 'EOFPTH' > "$py_site/lanex_timeout.pth" 2>/dev/null || true
import sys; exec("class _LanexHttpxTimeout:\n @staticmethod\n def find_spec(name, path=None, target=None):\n  if name != 'httpx':\n   return None\n  import importlib.machinery as m\n  spec = m.PathFinder.find_spec(name, path)\n  if spec is None or not hasattr(spec.loader, 'exec_module'):\n   return spec\n  run = spec.loader.exec_module\n  def exec_module(module):\n   run(module)\n   try:\n    d = module.Client.__init__.__kwdefaults__\n    if d is not None:\n     d['timeout'] = module.Timeout(300.0, connect=60.0)\n   except Exception:\n    pass\n  spec.loader.exec_module = exec_module\n  return spec\nif 'httpx' not in sys.modules:\n sys.meta_path.insert(0, _LanexHttpxTimeout)")
EOFPTH
    fi
    return "$rc"
}

build_tools_stage() {
    # A dependency shipped no prebuilt wheel for this Python (seen live: Arch's
    # Python 3.13 + librelane's lln-libparse) → pip compiles it from source,
    # which needs a C/C++ toolchain that minimal installs don't have.
    say "A dependency must be compiled from source — installing build tools, then retrying"
    case "$PKG" in
        apt)    apt_run install -y build-essential python3-dev || true ;;
        dnf)    $SUDO dnf install -y gcc gcc-c++ make python3-devel || true ;;
        pacman) $SUDO pacman -S --noconfirm --needed base-devel || true ;;
        zypper) $SUDO zypper --non-interactive install gcc gcc-c++ make python3-devel || true ;;
        brew)   # Opens Apple's GUI installer and returns IMMEDIATELY (async) —
                # the retry below may still fail; the die message says to re-run.
                xcode-select --install 2>/dev/null || true
                warn "If an 'install developer tools?' dialog appeared, finish it, then re-run this script." ;;
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
    # Fresh Apple-Silicon macOS can lack /usr/local/bin entirely; creating it
    # is safe (it's on every default PATH once it exists).
    $SUDO mkdir -p /usr/local/bin 2>/dev/null || true
    if $SUDO ln -sf "$LAUNCHER" /usr/local/bin/lanex 2>/dev/null; then
        hash -r 2>/dev/null || true
        note "'lanex' is ready in this terminal now."
        return 0
    fi
    warn "Could not write /usr/local/bin (no sudo?). Two other ways:"
    note "open a NEW terminal and run:  lanex        (PATH set up for future shells)"
    note "or launch right now with:     $LAUNCHER"
    # Make future shells work even without the symlink. This script always runs
    # under bash (curl | bash), so pick the rc file by the user's LOGIN shell —
    # $ZSH_VERSION would never be set here even for zsh users (macOS default).
    case ":${PATH}:" in *":$(dirname "$LAUNCHER"):"*) : ;; *)
        local rc="$HOME/.bashrc"
        case "${SHELL:-}" in */zsh) rc="$HOME/.zshrc" ;; esac
        # $PATH is intentionally literal so the user's shell expands it later.
        # shellcheck disable=SC2016
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
            if [ "$OS" = "macos" ]; then
                command -v docker >/dev/null 2>&1 && ! docker info >/dev/null 2>&1 \
                    && note "Docker Desktop must be running:  open -a Docker   then retry:  lanex --pull-image"
                command -v podman >/dev/null 2>&1 && ! podman info >/dev/null 2>&1 \
                    && note "podman needs its VM:  podman machine init && podman machine start   then retry:  lanex --pull-image"
            fi
        fi
    else
        warn "No Docker/Podman found. LanEx still works: the Tools tab's"
        warn "'Install the toolchain (recommended)' installs an engine and pulls the image in one go."
    fi
}

gds3d_stage() {
    # GDS3D (3D layout viewer) has no package-manager release anywhere — Linux
    # builds it from source, macOS installs the repo's prebuilt GDS3D.app. We
    # drive LanEx's own installer (`lanex --install-tool gds3d`), the exact code
    # path behind the Tools tab's Install button, so every foolproofing it has
    # (dev-header auto-detect, X11 fonts, CLT check, Rosetta hint) applies here
    # too. Entirely best-effort: a failure never breaks the LanEx install — the
    # Tools tab can always retry.
    if [ "${LANEX_SKIP_GDS3D:-0}" = "1" ]; then
        note "LANEX_SKIP_GDS3D=1 — skipping the GDS3D 3D viewer."
        return 0
    fi
    say "GDS3D 3D layout viewer (optional, best-effort)"
    gds3d_deps
    if "$LAUNCHER" --install-tool gds3d; then
        note "GDS3D installed."
    else
        warn "GDS3D didn't install automatically — everything else still works."
        note "Install it any time from the cockpit:  Tools tab → GDS3D → Install"
    fi
}

gds3d_deps() {
    # Build deps first, per package manager. The apt path can self-install these
    # from inside the app later; dnf/pacman/zypper cannot, so seed them now.
    # The interactive installer seeds them too: its component step runs without
    # a terminal and so cannot ask for a password half-way through a build.
    case "$PKG" in
        apt)    apt_run install -y \
                    build-essential libx11-dev libxmu-dev libxi-dev \
                    libgl1-mesa-dev libglu1-mesa-dev freeglut3-dev \
                    || warn "GDS3D build deps failed — the Tools tab can retry them later." ;;
        dnf)    $SUDO dnf install -y gcc-c++ make libX11-devel libXmu-devel libXi-devel \
                    mesa-libGL-devel mesa-libGLU-devel freeglut-devel \
                    || warn "GDS3D build deps failed — install them manually, then use the Tools tab." ;;
        pacman) $SUDO pacman -S --noconfirm --needed base-devel libx11 libxmu libxi mesa glu freeglut \
                    || warn "GDS3D build deps failed — install them manually, then use the Tools tab." ;;
        zypper) $SUDO zypper --non-interactive install gcc-c++ make libX11-devel libXmu-devel libXi-devel \
                    Mesa-libGL-devel glu-devel freeglut-devel \
                    || warn "GDS3D build deps failed — install them manually, then use the Tools tab." ;;
        *)      : ;;  # macOS: prebuilt app, no build deps; unknown: let the installer decide
    esac
    # GDS3D's runtime: the X11 "fixed" fonts and Mesa's DRI drivers (it opens a
    # blank window or crashes without them). apt_stage already added these.
    return 0
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

# ------------------------------------------------------------ components --
# What Windows Setup's Configure page offers, on Linux and macOS: a container
# engine, the matched LibreLane image, native tools and PDKs, chosen as one of
# the same four profiles. The heavy lifting is LanEx's own
# `--provision-finalize` (the code Windows Setup runs: digest-pinned image,
# pinned PDK versions, per-file SHA-256 checks, strict readiness report).
# System packages are installed HERE first, while this script still has a
# terminal for sudo, so the finalizer never needs a password: it runs detached
# from the terminal and would otherwise fail (or prompt behind the screen).

CH_PROFILE=""        # ''=classic flow; recommended | complete | minimal | custom
CH_ENGINE="docker"   # docker | podman | none
CH_IMAGE=1           # the matched LibreLane container image
CH_NATIVE=""         # space list: verilator iverilog gtkwave graphviz gds3d
CH_PDKS=""           # space list of PDK variants
CH_LIBS_SKY=""       # optional SKY130 libraries (applied to each sky130 variant)
CH_LIBS_GF=""        # optional gf180mcuD libraries
MANIFEST=""
CHOICES=""
DOCKER_GROUP_ADDED=0

NATIVE_ALL="verilator iverilog gtkwave graphviz gds3d"
SKY_EXTRA_ALL="sky130_fd_sc_hdll sky130_fd_sc_hs sky130_fd_sc_lp sky130_fd_sc_ls sky130_fd_sc_ms sky130_fd_pr_reram"
GF_EXTRA_ALL="gf180mcu_as_sc_mcu7t3v3 gf180mcu_osu_sc_gp12t3v3 gf180mcu_osu_sc_gp9t3v3 gf180mcu_ocd_io gf180mcu_ocd_alpha_large gf180mcu_ocd_alpha_misc gf180mcu_ocd_alpha_small"

has_word() { case " $1 " in *" $2 "*) return 0 ;; esac; return 1; }

lanex_home() { printf '%s' "${LANEX_HOME:-$HOME/.lanex}"; }

set_profile() {
    case "$1" in
        recommended)
            CH_ENGINE=docker; CH_IMAGE=1; CH_NATIVE="$NATIVE_ALL"; CH_PDKS="sky130A"
            CH_LIBS_SKY=""; CH_LIBS_GF="" ;;
        complete|maximum|full)
            set -- complete
            CH_ENGINE=docker; CH_IMAGE=1; CH_NATIVE="$NATIVE_ALL"
            CH_PDKS="sky130A sky130B gf180mcuD ihp-sg13g2"
            CH_LIBS_SKY="$SKY_EXTRA_ALL"; CH_LIBS_GF="$GF_EXTRA_ALL" ;;
        minimal)
            CH_ENGINE=none; CH_IMAGE=0; CH_NATIVE=""; CH_PDKS=""
            CH_LIBS_SKY=""; CH_LIBS_GF="" ;;
        custom) : ;;
        *) return 1 ;;
    esac
    CH_PROFILE="$1"
}

json_list() {  # space list -> "a","b"
    local out="" w
    for w in $1; do out="${out:+$out,}\"$w\""; done
    printf '%s' "$out"
}

choices_json() {
    case "$CH_PROFILE" in
        recommended|complete)
            printf '{"schema":1,"profile":"%s"}\n' "$CH_PROFILE"; return 0 ;;
        minimal)
            printf '%s\n' '{"schema":1,"profile":"minimal","engine":"none","image":false,"nativeTools":[],"pdks":[],"libraries":{}}'
            return 0 ;;
    esac
    local libs="" v l w image=false
    for v in $CH_PDKS; do
        l=""
        case "$v" in
            sky130A) for w in $CH_LIBS_SKY; do [ "$w" = sky130_fd_pr_reram ] || l="$l $w"; done ;;
            sky130B) l="$CH_LIBS_SKY" ;;
            gf180mcuD) l="$CH_LIBS_GF" ;;
        esac
        [ -n "${l// /}" ] && libs="${libs:+$libs,}\"$v\":[$(json_list "$l")]"
    done
    [ "$CH_IMAGE" = 1 ] && image=true
    printf '{"schema":1,"profile":"custom","engine":"%s","image":%s,"nativeTools":[%s],"pdks":[%s],"libraries":{%s}}\n' \
        "$CH_ENGINE" "$image" "$(json_list "$CH_NATIVE")" "$(json_list "$CH_PDKS")" "$libs"
}

load_choices_file() {  # Setup choices JSON (or owner state) -> CH_*; needs python
    local f="$1" py out
    py="$(best_python 2>/dev/null || true)"
    [ -n "$py" ] && [ -f "$f" ] || return 1
    out="$("$py" - "$f" << 'EOFPY'
import json, shlex, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(1)
d = d.get("choices", d) if isinstance(d, dict) else {}
p = d.get("profile", "custom")
if p in ("maximum", "full"):
    p = "complete"
if p not in ("recommended", "complete", "minimal", "custom"):
    sys.exit(1)
libs = d.get("libraries") if isinstance(d.get("libraries"), dict) else {}
sky = []
for v in ("sky130A", "sky130B"):
    for x in libs.get(v, []) or []:
        if x not in sky:
            sky.append(x)
q = lambda v: shlex.quote(" ".join(str(x) for x in v))
print("CH_PROFILE=" + shlex.quote(p))
if p == "custom":
    print("CH_ENGINE=" + shlex.quote(str(d.get("engine", "docker"))))
    print("CH_IMAGE=" + ("1" if d.get("image", True) else "0"))
    print("CH_NATIVE=" + q(d.get("nativeTools", [])))
    print("CH_PDKS=" + q(d.get("pdks", [])))
    print("CH_LIBS_SKY=" + q(sky))
    print("CH_LIBS_GF=" + q(libs.get("gf180mcuD", []) or []))
EOFPY
)" || return 1
    eval "$out"
    case "$CH_ENGINE" in docker|podman|none) ;; *) CH_ENGINE=docker ;; esac
    [ "$CH_PROFILE" = custom ] || set_profile "$CH_PROFILE"
    return 0
}

pdk_family() {
    case "$1" in
        sky130*) echo sky130 ;;
        gf180*) echo gf180mcu ;;
        *) echo "$1" ;;
    esac
}

pdk_families() {  # unique families of CH_PDKS, in order
    local v f out=""
    for v in $CH_PDKS; do
        f="$(pdk_family "$v")"
        has_word "$out" "$f" || out="${out:+$out }$f"
    done
    printf '%s' "$out"
}

# Download/disk estimates in MB. The tool image figures are the build
# manifest's measured sizes; PDK downloads are the pinned archives' sizes.
lib_mb() {
    case "$1" in
        sky130_fd_sc_hdll) echo 126 ;; sky130_fd_sc_hs) echo 633 ;; sky130_fd_sc_lp) echo 516 ;;
        sky130_fd_sc_ls) echo 743 ;; sky130_fd_sc_ms) echo 590 ;; sky130_fd_pr_reram) echo 1 ;;
        gf180mcu_as_sc_mcu7t3v3) echo 2 ;; gf180mcu_osu_sc_gp12t3v3) echo 13 ;;
        gf180mcu_osu_sc_gp9t3v3) echo 13 ;; gf180mcu_ocd_io) echo 44 ;;
        *) echo 1 ;;
    esac
}

EST_DL=0; EST_DISK=0
est_compute() {
    local dl=160 disk=700 w x sky=0 skyv=0
    case "$CH_ENGINE" in
        docker) command -v docker >/dev/null 2>&1 || { dl=$((dl+95)); disk=$((disk+380)); } ;;
        podman) command -v podman >/dev/null 2>&1 || { dl=$((dl+45)); disk=$((disk+170)); } ;;
    esac
    for w in $CH_NATIVE; do
        case "$w" in
            verilator) dl=$((dl+25)); disk=$((disk+120)) ;;
            iverilog)  dl=$((dl+4));  disk=$((disk+12)) ;;
            gtkwave)   dl=$((dl+6));  disk=$((disk+25)) ;;
            graphviz)  dl=$((dl+8));  disk=$((disk+35)) ;;
            gds3d)     dl=$((dl+230)); disk=$((disk+800)) ;;
        esac
    done
    if [ "$CH_IMAGE" = 1 ]; then dl=$((dl+1515)); disk=$((disk+7700+3072)); fi
    for w in $CH_PDKS; do case "$w" in sky130*) sky=1; skyv=$((skyv+1)) ;; esac; done
    if [ "$sky" = 1 ]; then
        dl=$((dl+331)); disk=$((disk+2560*skyv))
        for w in $CH_LIBS_SKY; do x="$(lib_mb "$w")"; dl=$((dl+x)); disk=$((disk+x*4*skyv)); done
    fi
    if has_word "$CH_PDKS" gf180mcuD || has_word "$CH_PDKS" gf180mcuC; then
        dl=$((dl+413)); disk=$((disk+1843))
        if has_word "$CH_PDKS" gf180mcuD; then
            for w in $CH_LIBS_GF; do x="$(lib_mb "$w")"; dl=$((dl+x)); disk=$((disk+x*4)); done
        fi
    fi
    if has_word "$CH_PDKS" ihp-sg13g2; then dl=$((dl+21)); disk=$((disk+1946)); fi
    EST_DL=$dl; EST_DISK=$disk
}

fmt_mb() {  # MB -> "740 MB" / "2.4 GB"
    if [ "$1" -lt 1000 ]; then REPLY="$1 MB"
    else REPLY="$(( $1 / 1024 )).$(( ($1 % 1024) * 10 / 1024 )) GB"; fi
}

disk_free_mb() {
    df -Pk "$1" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1024}'
}

FREE_MB=0
free_compute() {
    local h r
    h="$(disk_free_mb "$HOME")"; [ -n "$h" ] || h=0
    FREE_MB="$h"
    # The image lands under /var/lib (docker) or $HOME (podman, rootless).
    if [ "$CH_IMAGE" = 1 ] && [ "$CH_ENGINE" = docker ] && [ -d /var/lib ]; then
        r="$(disk_free_mb /var/lib)"
        [ -n "$r" ] && [ "$r" -lt "$FREE_MB" ] && FREE_MB="$r"
    fi
}

fetch_url() {  # url dest
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL --retry 3 --retry-delay 2 --connect-timeout 15 --max-time 180 -o "$2" "$1" && return 0
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -q -T 30 -t 3 -O "$2" "$1" && return 0
    fi
    return 1
}

# The GDS3D source commit LanEx builds; the same pin scripts/build_windows_release.py
# writes into the Windows build manifest.
GDS3D_COMMIT="${LANEX_GDS3D_COMMIT:-dc6d965225c9f5ed2a6faefb7ea30665429060fe}"

app_python() {  # the interpreter of the installed LanEx (pipx venv or ~/.lanex/venv)
    local first
    first="$(head -n 1 "$LAUNCHER" 2>/dev/null)"
    case "$first" in
        '#!'*python*) first="${first#\#!}"; first="${first%% *}"
                      [ -x "$first" ] && { printf '%s' "$first"; return 0; } ;;
    esac
    printf '%s' "$PY"
}

fetch_manifest() {
    # Windows Setup ships a build manifest made at build time. Here it is made
    # from the LanEx just installed: its own pinned image digest, PDK catalog
    # and PDK commits, so the components always match the app's version. Only
    # the per-file SHA-256 list of the PDK archives is a separate, tracked file.
    local dir src assets="" apy
    dir="$(lanex_home)"
    mkdir -p "$dir" || die "Could not create $dir. Check its owner (ls -ld $dir), then re-run."
    MANIFEST="$dir/build-manifest.json"
    src="${LANEX_MANIFEST:-}"
    if [ -z "$src" ] && [ -n "${LANEX_FROM:-}" ] && [ -f "${LANEX_FROM}/windows/setup/build-manifest.json" ]; then
        src="${LANEX_FROM}/windows/setup/build-manifest.json"
    fi
    if [ -n "$src" ]; then
        note "Using the component manifest $src"
        cp "$src" "$MANIFEST.tmp" 2>/dev/null || die "The component manifest $src could not be read."
    else
        if [ -n "${LANEX_FROM:-}" ] && [ -f "${LANEX_FROM}/windows/setup/pdk-assets.json" ]; then
            assets="${LANEX_FROM}/windows/setup/pdk-assets.json"
        else
            assets="$dir/pdk-assets.json"
            note "Fetching the PDK file checksums for ${REF}"
            fetch_url "https://raw.githubusercontent.com/${REPO}/${REF}/windows/setup/pdk-assets.json" "$assets.tmp" \
                && mv -f "$assets.tmp" "$assets" \
                || { rm -f "$assets.tmp"; warn "PDK checksum list unavailable; PDK downloads are checked by their pinned commit only."; assets=""; }
        fi
        apy="$(app_python)"
        "$apy" - "$MANIFEST.tmp" "$GDS3D_COMMIT" "$assets" << 'EOFPY' \
            || die "Could not prepare the component manifest from the installed LanEx (see the log above).
   Re-run the same command; if it repeats, report the log."
import importlib.metadata as md, json, sys
from lanex.controller import pdk_catalog as pc
from lanex.controller import container_run as cr
out, gds3d, assets = sys.argv[1], sys.argv[2], sys.argv[3]
ver = md.version("librelane")
digest = cr._KNOWN_IMAGE_DIGESTS.get(ver, "")
if not digest:
    sys.exit("LanEx has no tested image digest for LibreLane %s; refusing an unpinned image." % ver)
catalog = pc.build_canonical_pdk_catalog()
variants = {}
for name, e in catalog.items():
    variants[name] = {"family": e["family"], "libraries": list(e["libraries"]),
                      "defaultLibraries": list(e["default_libraries"]),
                      "requiredVersion": pc.PINNED_PDK_VERSIONS[e["family"]]}
m = {
    "schema": 1,
    "source": {"kind": "install.sh", "lanex": md.version("lanex")},
    "dependencies": {"librelane": ver, "ciel": md.version("ciel")},
    "image": {"reference": "ghcr.io/librelane/librelane:%s" % ver, "digest": digest},
    "gds3d": {"repository": "trilomix/GDS3D", "commit": gds3d},
    "pdkPins": {"families": dict(pc.PINNED_PDK_VERSIONS), "variants": variants},
    "pdkCatalog": catalog,
    "sizeEstimates": {"estimatedImageDownloadBytes": 1589137899},
}
if assets:
    try:
        m["pdkAssets"] = json.load(open(assets, encoding="utf-8"))
    except Exception as exc:
        print("PDK checksum list unreadable (%s); continuing without it." % exc)
json.dump(m, open(out, "w", encoding="utf-8"), indent=1)
print("component manifest: LibreLane %s image %s, PDKs %s" % (ver, digest[:19], ", ".join(sorted(pc.PINNED_PDK_VERSIONS))))
EOFPY
    fi
    "$PY" -c 'import json,sys
d=json.load(open(sys.argv[1],encoding="utf-8"))
assert d.get("schema")==1 and str(d["image"]["digest"]).startswith("sha256:") and d.get("pdkCatalog")' \
        "$MANIFEST.tmp" 2>/dev/null \
        || die "The component manifest is not the expected JSON. Re-run the same command."
    mv -f "$MANIFEST.tmp" "$MANIFEST" || die "Could not save $MANIFEST."
}

write_choices() {
    local dir; dir="$(lanex_home)"
    mkdir -p "$dir" || die "Could not create $dir."
    CHOICES="$dir/setup-choices.json"
    choices_json > "$CHOICES.tmp" && mv -f "$CHOICES.tmp" "$CHOICES" \
        || die "Could not save your component choices to $CHOICES."
}

pid1_is_systemd() { [ "$(cat /proc/1/comm 2>/dev/null)" = "systemd" ]; }

docker_reachable() {
    if [ "$(id -u)" = "0" ]; then docker info >/dev/null 2>&1; return; fi
    docker info >/dev/null 2>&1 && return 0
    # Just added to the group: this login session doesn't have it yet, but
    # sg can start a process that does (LanEx itself does the same).
    command -v sg >/dev/null 2>&1 && getent group docker 2>/dev/null | grep -qw "$(id -un)" \
        && sg docker -c 'docker info' >/dev/null 2>&1
}

engine_stage() {
    local eng="$CH_ENGINE" pkg
    [ "$eng" = "none" ] && return 0
    if [ "$OS" = "macos" ]; then
        note "macOS: LanEx installs ${eng} itself in the next step (Homebrew / the vendor's app)."
        return 0
    fi
    say "Container engine (${eng})"
    if command -v "$eng" >/dev/null 2>&1; then
        note "${eng} is already installed: $("$eng" --version 2>/dev/null | head -n 1)"
    else
        case "$PKG:$eng" in
            apt:docker) pkg="docker.io" ;;
            dnf:docker) pkg="moby-engine" ;;
            *) pkg="$eng" ;;
        esac
        case "$PKG" in
            apt)    apt_run install -y "$pkg" ;;
            dnf)    $SUDO dnf install -y "$pkg" ;;
            pacman) $SUDO pacman -S --noconfirm --needed "$pkg" ;;
            zypper) $SUDO zypper --non-interactive install "$pkg" ;;
            *)      false ;;
        esac || die "Could not install ${eng} with ${PKG}.
   The package manager's own error is in the log. Fix it (or install ${eng} yourself),
   then re-run the same command. Or choose Minimal and add the toolchain later in LanEx -> Tools."
        command -v "$eng" >/dev/null 2>&1 || die "${eng} was installed but the '${eng}' command is missing. Re-run the same command."
    fi
    [ "$eng" = "docker" ] || return 0
    if ! docker_reachable && ! $SUDO docker info >/dev/null 2>&1; then
        note "Starting the Docker service"
        if pid1_is_systemd; then
            $SUDO systemctl enable --now docker || $SUDO systemctl start docker || true
        else
            $SUDO service docker start || true
        fi
    fi
    if [ "$(id -u)" != "0" ] && ! id -nG 2>/dev/null | grep -qw docker; then
        if ! getent group docker 2>/dev/null | grep -qw "$(id -un)"; then
            note "Adding $(id -un) to the docker group (so LanEx can run containers without sudo)"
            $SUDO usermod -aG docker "$(id -un)" \
                || die "Could not add $(id -un) to the docker group. Run: sudo usermod -aG docker $(id -un), then re-run."
        fi
        DOCKER_GROUP_ADDED=1
    fi
    local i
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
        if docker_reachable; then note "Docker is running."; return 0; fi
        sleep 2
    done
    if [ "$WSL" = "1" ] && ! pid1_is_systemd; then
        die "Docker is installed but its service did not start inside WSL.
   Turn on systemd for this distro: add these two lines to /etc/wsl.conf
       [boot]
       systemd=true
   then run  wsl --shutdown  in Windows PowerShell, reopen the terminal and re-run."
    fi
    die "Docker is installed but its service is not answering.
   See:  sudo systemctl status docker   (or: sudo service docker status)
   Then re-run the same command. Finished parts are kept."
}

native_stage() {
    local pkgs="" w
    for w in $CH_NATIVE; do
        case "$w" in gds3d) ;; *) pkgs="$pkgs $w" ;; esac
    done
    [ "$OS" = "macos" ] && { note "macOS: LanEx installs the tools with Homebrew in the next step."; return 0; }
    if [ -n "${pkgs// /}" ]; then
        say "Native tools:${pkgs}"
        # One call first; if one package is missing on this distro, the rest
        # still go in one by one and the final check names the missing one.
        if ! pkg_install $pkgs; then
            for w in $pkgs; do pkg_install "$w" || warn "${w} could not be installed with ${PKG}."; done
        fi
    fi
    if has_word "$CH_NATIVE" gds3d; then
        say "GDS3D build dependencies"
        gds3d_deps
    fi
    return 0
}

pkg_install() {
    case "$PKG" in
        apt)    apt_run install -y "$@" ;;
        dnf)    $SUDO dnf install -y "$@" ;;
        pacman) $SUDO pacman -S --noconfirm --needed "$@" ;;
        zypper) $SUDO zypper --non-interactive install "$@" ;;
        *)      return 1 ;;
    esac
}

needs_finalize() {
    [ "$CH_IMAGE" = 1 ] || [ -n "${CH_PDKS// /}" ] || [ -n "${CH_NATIVE// /}" ] || [ "$CH_ENGINE" != "none" ]
}

finalize_verdict() {  # finalizer output -> plain problem lines; rc 0 when ready
    "$PY" - "$1" << 'EOFPY'
import json, sys
rep = None
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    s = line.strip()
    if s.startswith("{") and ('"checks"' in s or '"error"' in s):
        try:
            rep = json.loads(s)
        except Exception:
            pass
if rep is None:
    print("The component installer stopped before it could report (see the log).")
    sys.exit(1)
if rep.get("error"):
    print(str(rep["error"])[:400])
    sys.exit(1)
bad, seen = [], set()
for f in rep.get("installFailures") or []:
    r = f.get("result") or {}
    why = r.get("guidance") or r.get("reason") or r.get("error") or ("cancelled" if f.get("cancelled") else "failed")
    comp = str(f.get("component"))
    seen.add(comp)
    bad.append("%s: %s" % (comp, str(why).strip().splitlines()[0][:300]))
for name, c in (rep.get("checks") or {}).items():
    # The Windows appliance also promises systemd and exact Python pins;
    # on an ordinary machine those are not this installer's business.
    if name.startswith(("runtime:", "python:")) or c.get("ready") or name in seen:
        continue
    miss = c.get("missing") or c.get("detail") or ""
    if isinstance(miss, list):
        miss = ", ".join(str(x) for x in miss)
    bad.append(("%s: not ready %s" % (name, str(miss).strip()[:200])).strip())
print("\n".join(bad[:8]))
sys.exit(1 if bad else 0)
EOFPY
}

finalize_stage() {
    say "Installing the selected components (engine, image, tools, PDKs)"
    fetch_manifest
    write_choices
    local out rc problems
    out="$(lanex_home)/setup-finalize.out"
    # Detached from the terminal on purpose (see the section comment): every
    # system package is already in, so nothing here needs a password.
    set -- "$LAUNCHER" --provision-finalize "$MANIFEST" --setup-choices "$CHOICES"
    if command -v setsid >/dev/null 2>&1 && setsid -w true </dev/null >/dev/null 2>&1; then
        set -- setsid -w "$@"
    fi
    if [ "${UI:-0}" = "1" ]; then
        "$@" </dev/null 2>&1 | tee "$out"
        rc=${PIPESTATUS[0]}
    else
        "$@" </dev/null 2>&1 | tee "$out" | grep -v -e '^@@LANEX:' -e '^{"'
        rc=${PIPESTATUS[0]}
    fi
    problems="$(finalize_verdict "$out")" && return 0
    die "LanEx is installed, but some components are not ready:
$(printf '%s\n' "$problems" | sed 's/^/   - /')
   Re-run the same command to retry them (finished parts are kept),
   or add them later in LanEx -> Tools. (finalizer exit code ${rc})"
}

stage_components() {  # the plain-output path (LANEX_PROFILE / --profile)
    engine_stage
    native_stage
    finalize_stage
}

# =================================================== interactive installer ==
# Welcome -> Profile (1-4) -> [Custom checklist] -> Review -> Install -> Done,
# the Windows wizard's pages in a terminal. Drawn with plain ANSI escapes on
# /dev/tty (stdin is the piped script under `curl | bash`), full frames into
# the alternate screen, no tput/dialog/whiptail dependency, bash 3.2 safe.
# Every stage still runs the functions above; its output goes to the log file
# and the screen shows a step list, live activity and one progress bar.

UI=0; UI_COLS=80; UI_ROWS=24; UI_W=76; UI_PAD=""; UI_UTF=1; UI_COLOR=1
UI_STTY=""; UI_RESIZED=1; UI_ESC_T=1; UI_ALT=0; UI_TICK=0; UI_INTRO=1
FA=(); FL=0; KEY=""; UI_FLASH=""; UI_FLASH_T=0
LX_DIR=""; LX_LOG=""; LX_FAILMSG=""; LX_STATE=""; LX_STEPLOG=""; LX_PID=""
LX_T0=0; LX_KEEPALIVE=""; LX_INSTALLING=0; LX_SEEN=0
SYS_OS=""; SYS_PY=""; SYS_FREE=""; SYS_ENGINE=""; SYS_LANEX=""; SYS_LANEX_VER=""
SAVED_PROFILE=""

ui_capable() {
    [ "${LANEX_NO_UI:-0}" = "1" ] && return 1
    [ "${LANEX_ASSUME_YES:-0}" = "1" ] && return 1
    [ -n "${LANEX_PIP_LOCK:-}" ] && return 1
    [ -n "${CI:-}" ] && return 1
    case "${_LX_TERM:-}" in ''|dumb|unknown) return 1 ;; esac
    command -v stty >/dev/null 2>&1 || return 1
    ( exec 9<>/dev/tty ) 2>/dev/null || return 1
    return 0
}

ui_rgb() {  # r g b basic -> REPLY (foreground escape for this terminal)
    case "$UI_COLOR" in
        3) REPLY=$'\033[38;2;'"$1;$2;$3m" ;;
        2) REPLY=$'\033[38;5;'"$(( 16 + 36*(($1*5+127)/255) + 6*(($2*5+127)/255) + ($3*5+127)/255 ))m" ;;
        1) REPLY=$'\033['"$4m" ;;
        *) REPLY="" ;;
    esac
}
ui_bgc() {  # r g b -> REPLY (background escape; nothing on 16 colours)
    case "$UI_COLOR" in
        3) REPLY=$'\033[48;2;'"$1;$2;$3m" ;;
        2) REPLY=$'\033[48;5;'"$(( 16 + 36*(($1*5+127)/255) + 6*(($2*5+127)/255) + ($3*5+127)/255 ))m" ;;
        *) REPLY="" ;;
    esac
}

ui_caps() {
    local cm l
    # ---- colour depth
    UI_COLOR=1
    case "${COLORTERM:-}" in truecolor|24bit) UI_COLOR=3 ;; esac
    [ -n "${WT_SESSION:-}" ] && UI_COLOR=3                       # Windows Terminal (WSL)
    case "${TERM_PROGRAM:-}" in
        iTerm.app|WezTerm|vscode|ghostty|Hyper|Tabby) UI_COLOR=3 ;;
        Apple_Terminal) [ "$UI_COLOR" -lt 2 ] && UI_COLOR=2 ;;
    esac
    case "${_LX_TERM}" in
        xterm-kitty|alacritty|foot*|*-direct|wezterm|xterm-ghostty) UI_COLOR=3 ;;
        *256color*|tmux*|screen*|rxvt-unicode*) [ "$UI_COLOR" -lt 2 ] && UI_COLOR=2 ;;
        linux|vt*) UI_COLOR=1 ;;
    esac
    [ -n "${NO_COLOR:-}" ] && UI_COLOR=0
    case "${LANEX_COLOR:-}" in 0|1|2|3) UI_COLOR="$LANEX_COLOR" ;; esac
    # ---- Unicode
    UI_UTF=0
    cm="$(locale charmap 2>/dev/null || true)"
    if [ "$cm" = "UTF-8" ] || [ "$cm" = "utf8" ]; then
        UI_UTF=1
    elif [ -z "${LC_ALL:-}${LC_CTYPE:-}${LANG:-}" ] && [ "${_LX_TERM}" != "linux" ]; then
        # Containers often set no locale at all although the terminal is
        # UTF-8; adopt C.UTF-8 when this libc has it.
        for l in C.UTF-8 C.utf8 en_US.UTF-8; do
            cm="$(LC_ALL=$l locale charmap 2>/dev/null || true)"
            if [ "$cm" = "UTF-8" ]; then export LC_ALL="$l"; UI_UTF=1; break; fi
        done
    fi
    [ "${LANEX_ASCII:-0}" = "1" ] && UI_UTF=0
    [ "${_LX_TERM}" = "linux" ] && UI_UTF=0                     # the bare VT's font
    # ---- bash version: a fractional read timeout tells Esc from an arrow key
    [ "${BASH_VERSINFO[0]:-3}" -ge 4 ] && UI_ESC_T=0.05

    R=$'\033[0m'; B=$'\033[1m'; IT=$'\033[3m'
    [ "$UI_COLOR" = 0 ] && IT=""
    ui_rgb 34 211 238 96;  C_CYAN="$REPLY"
    ui_rgb 59 130 246 94;  C_BLUE="$REPLY"
    ui_rgb 129 140 248 95; C_VIO="$REPLY"
    ui_rgb 52 211 153 92;  C_OK="$REPLY"
    ui_rgb 251 191 36 93;  C_WARN="$REPLY"
    ui_rgb 248 113 113 91; C_ERR="$REPLY"
    ui_rgb 132 145 165 2;  C_DIM="$REPLY"
    ui_rgb 71 85 105 2;    C_FAINT="$REPLY"
    ui_rgb 51 65 85 2;     C_TRACK="$REPLY"
    ui_rgb 226 246 255 97; C_SHINE="$REPLY"
    ui_rgb 241 245 249 97; C_HI="$REPLY"
    [ "$UI_COLOR" = 1 ] && { C_DIM=$'\033[2m'; C_FAINT=$'\033[2m'; C_TRACK=$'\033[2m'; }
    ui_bgc 22 34 54;       C_SELBG="$REPLY"
    C_KEYBG=""; ui_bgc 30 41 59; C_KEYBG="$REPLY"
    if [ "$UI_COLOR" = 0 ]; then
        C_CYAN=""; C_BLUE=""; C_VIO=""; C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""
        C_FAINT=""; C_TRACK=""; C_SHINE=""; C_HI=""; C_SELBG=""; C_KEYBG=""
    fi

    if [ "$UI_UTF" = 1 ]; then
        G_TL='╭'; G_TR='╮'; G_BL='╰'; G_BR='╯'; G_H='─'; G_V='│'
        G_OK='✓'; G_ERR='✗'; G_TODO='○'; G_SKIP='–'; G_PTR='❯'; G_DOT='·'; G_ARR='→'
        G_RON='(●)'; G_ROFF='( )'; G_CON='[✓]'; G_COFF='[ ]'; G_CDIS='[·]'
        G_BAR='━'; G_BARH='╸'; G_ELBOW='└'; G_UP='▲'; G_DN='▼'; G_DIAM='◆'
        G_DL='↓'; G_DISK='▪'; G_LOCK="•"; G_INFO='•'; G_ENTER='⏎'; G_UPDN='↑↓'
        G_SPIN='⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏'; G_STEP_ON='●'; G_STEP_OFF='○'
    else
        G_TL='+'; G_TR='+'; G_BL='+'; G_BR='+'; G_H='-'; G_V='|'
        G_OK='+'; G_ERR='x'; G_TODO='o'; G_SKIP='-'; G_PTR='>'; G_DOT='-'; G_ARR='->'
        G_RON='(*)'; G_ROFF='( )'; G_CON='[x]'; G_COFF='[ ]'; G_CDIS='[-]'
        G_BAR='='; G_BARH='-'; G_ELBOW='\'; G_UP='^'; G_DN='v'; G_DIAM='*'
        G_DL='v'; G_DISK='#'; G_LOCK='!'; G_INFO='*'; G_ENTER='Enter'; G_UPDN='Up/Dn'
        G_SPIN='- \ | /'; G_STEP_ON='*'; G_STEP_OFF='o'
    fi
    # shellcheck disable=SC2206
    UI_SPIN=($G_SPIN)
}

# ---- the wordmark ---------------------------------------------------------
LOGO_U=(
'██╗      █████╗ ███╗   ██╗███████╗██╗  ██╗'
'██║     ██╔══██╗████╗  ██║██╔════╝╚██╗██╔╝'
'██║     ███████║██╔██╗ ██║█████╗   ╚███╔╝ '
'██║     ██╔══██║██║╚██╗██║██╔══╝   ██╔██╗ '
'███████╗██║  ██║██║ ╚████║███████╗██╔╝ ██╗'
'╚══════╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝'
)
LOGO_A=(
' _        _    _   _ _______  __'
'| |      / \  | \ | | ____\ \/ /'
'| |     / _ \ |  \| |  _|  \  / '
'| |___ / ___ \| |\  | |___ /  \ '
'|_____/_/   \_\_| \_|_____/_/\_\'
)
LOGO_C=(); LOGO_N=0; LOGO_WID=0

ui_grad() {  # position max -> REPLY: cyan -> blue -> indigo
    local n=$2 t u r g b k
    [ "$n" -lt 1 ] && n=1
    t=$(( $1 * 1000 / n ))
    if [ "$t" -lt 500 ]; then
        u=$(( t * 2 )); r=$(( 34 + (59-34)*u/1000 )); g=$(( 211 + (130-211)*u/1000 )); b=$(( 238 + (246-238)*u/1000 )); k=96
    else
        u=$(( (t-500) * 2 )); r=$(( 59 + (129-59)*u/1000 )); g=$(( 130 + (140-130)*u/1000 )); b=$(( 246 + (248-246)*u/1000 )); k=94
    fi
    ui_rgb "$r" "$g" "$b" "$k"
}

ui_gradtext() {  # text [shadow-glyphs-dim] -> REPLY
    local s="$1" out="" i n c last=""
    n=${#s}
    for (( i = 0; i < n; i++ )); do
        c="${s:i:1}"
        if [ "$c" = " " ]; then out="$out "; continue; fi
        ui_grad "$i" "$n"
        if [ "$REPLY" != "$last" ]; then out="$out$REPLY"; last="$REPLY"; fi
        out="$out$c"
    done
    REPLY="$out$R"
}

ui_logo_build() {
    local i
    LOGO_C=()
    if [ "$UI_UTF" = 1 ]; then
        LOGO_N=${#LOGO_U[@]}; LOGO_WID=${#LOGO_U[0]}
        for (( i = 0; i < LOGO_N; i++ )); do ui_gradtext "${LOGO_U[$i]}"; LOGO_C[$i]="$B$REPLY"; done
    else
        LOGO_N=${#LOGO_A[@]}; LOGO_WID=${#LOGO_A[0]}
        for (( i = 0; i < LOGO_N; i++ )); do ui_gradtext "${LOGO_A[$i]}"; LOGO_C[$i]="$B$REPLY"; done
    fi
}

# ---- terminal plumbing ----------------------------------------------------
ui_size() {
    local s r c pad
    s="$(stty size <&3 2>/dev/null || true)"
    r="${s% *}"; c="${s#* }"
    case "$r" in ''|*[!0-9]*) r=24 ;; esac
    case "$c" in ''|*[!0-9]*) c=80 ;; esac
    UI_ROWS=$r; UI_COLS=$c
    UI_W=$(( c - 4 )); [ "$UI_W" -gt 84 ] && UI_W=84
    pad=$(( (c - UI_W) / 2 )); [ "$pad" -lt 1 ] && pad=1
    printf -v UI_PAD '%*s' "$pad" ''
    UI_RESIZED=0
}

ui_init() {
    exec 3</dev/tty 4>/dev/tty
    UI_STTY="$(stty -g <&3 2>/dev/null || true)"
    stty -echo <&3 2>/dev/null || true
    ui_caps
    ui_logo_build
    ui_size
    trap 'UI_RESIZED=1' WINCH
    trap 'ui_on_exit' EXIT
    trap 'ui_on_int' INT
    trap 'ui_on_int' TERM
    trap 'ui_on_int' HUP
    # Erase the "checking this machine" line first, so it does not stay
    # behind in the scrollback under the alternate screen.
    printf '\r\033[2K\033[1A\033[2K\033[?1049h\033[?25l\033[H\033[2J' >&4
    UI_ALT=1
    UI=1
}

ui_leave_screen() {
    if [ "$UI_ALT" = 1 ]; then
        printf '\033[0m\033[?25h\033[?1049l' >&4
        UI_ALT=0
    fi
    [ -n "$UI_STTY" ] && stty "$UI_STTY" <&3 2>/dev/null
    return 0
}

ui_on_exit() {
    ui_kill_job
    [ -n "$LX_KEEPALIVE" ] && kill "$LX_KEEPALIVE" 2>/dev/null
    ui_leave_screen
}

ui_kill_tree() {
    local p c kids
    p="$1"
    kids="$(ps -A -o pid= -o ppid= 2>/dev/null | awk -v p="$p" '$2 == p {print $1}')"
    for c in $kids; do ui_kill_tree "$c"; done
    kill -TERM "$p" 2>/dev/null
}

ui_kill_job() {
    [ -n "$LX_PID" ] || return 0
    ui_kill_tree "$LX_PID"
    LX_PID=""
}

ui_on_int() {
    trap '' INT TERM HUP
    ui_kill_job
    [ -n "$LX_KEEPALIVE" ] && kill "$LX_KEEPALIVE" 2>/dev/null
    LX_KEEPALIVE=""
    ui_leave_screen
    if [ "$LX_INSTALLING" = 1 ]; then
        printf '\n  %s%s Stopped.%s Everything that finished is kept.\n' "$C_WARN$B" "$G_SKIP" "$R" >&4
        printf '  Run the same command again to continue where it stopped.\n' >&4
        [ -n "$LX_LOG" ] && printf '  %sLog:%s %s\n\n' "$C_DIM" "$R" "$LX_LOG" >&4
    else
        printf '\n  %sCancelled.%s Nothing was installed.\n\n' "$B" "$R" >&4
    fi
    trap - EXIT
    exit 130
}

ui_key() {  # -> KEY: up down left right enter space esc tab back home end pgup pgdn <char>; '' = timeout
    local k="" r="" r2=""
    KEY=""
    IFS= read -rsn1 -t 1 -u 3 k || return 1
    case "$k" in
        $'\033')
            IFS= read -rsn1 -t "$UI_ESC_T" -u 3 r 2>/dev/null || r=""
            if [ "$r" = "[" ] || [ "$r" = "O" ]; then
                IFS= read -rsn1 -t 1 -u 3 r2 2>/dev/null || r2=""
                case "$r2" in
                    A) KEY=up ;; B) KEY=down ;; C) KEY=right ;; D) KEY=left ;;
                    H) KEY=home ;; F) KEY=end ;;
                    [0-9])
                        local t="" x=""
                        while IFS= read -rsn1 -t 1 -u 3 x 2>/dev/null; do [ "$x" = "~" ] && break; t="$t$x"; done
                        case "$r2$t" in 5) KEY=pgup ;; 6) KEY=pgdn ;; 1|7) KEY=home ;; 4|8) KEY=end ;; *) KEY=other ;; esac ;;
                    *) KEY=other ;;
                esac
            elif [ -z "$r" ]; then KEY=esc
            else KEY=other; fi ;;
        '') KEY=enter ;;
        ' ') KEY=space ;;
        $'\t') KEY=tab ;;
        $'\177'|$'\010') KEY=back ;;
        k|K) KEY=up ;; j|J) KEY=down ;;
        *) KEY="$k" ;;
    esac
    return 0
}

ui_drain_input() {  # drop keys typed while nothing was asking (they would answer the next prompt)
    # Non-blocking raw reads (VMIN=0 VTIME=0) also catch a half-typed line,
    # which a canonical-mode `read -t 0` cannot see. Works on bash 3.2.
    local old n
    old="$(stty -g <&3 2>/dev/null)" || return 0
    stty -icanon min 0 time 0 <&3 2>/dev/null || return 0
    for n in 1 2 3 4; do dd bs=4096 count=1 <&3 >/dev/null 2>&1; done
    stty "$old" <&3 2>/dev/null
    return 0
}

ui_wait_key() {  # block until a key; redraw callback on resize/timeouts
    while :; do
        ui_key && return 0
        UI_TICK=$((UI_TICK + 1))
        if [ "$UI_RESIZED" = 1 ]; then ui_size; printf '\033[2J' >&4; "$1"; fi
        if [ -n "$UI_FLASH" ] && [ $((SECONDS - UI_FLASH_T)) -ge 4 ]; then UI_FLASH=""; "$1"; fi
    done
}

# ---- frame building -------------------------------------------------------
fl()  { FA[$FL]="$UI_PAD$1"; FL=$((FL + 1)); }
fflush() {  # [footer] — footer pinned to the last row; the frame never scrolls
    local max=$UI_ROWS i out="" lift
    [ -n "${1:-}" ] && max=$((UI_ROWS - 1))
    [ "$FL" -gt "$max" ] && FL=$max
    # Tall window: sit the content a little above the middle, not glued to the top.
    if [ "${UI_VC:-0}" = 1 ] && [ "$FL" -lt $((max - 4)) ]; then
        lift=$(( (max - FL) / 3 ))
        for (( i = 0; i < lift; i++ )); do out="$out"$'\033[K\n'; done
        max=$(( max - lift ))
    fi
    for (( i = 0; i < FL; i++ )); do out="$out${FA[$i]}"$'\033[K\n'; done
    if [ -n "${1:-}" ]; then
        for (( ; i < max; i++ )); do out="$out"$'\033[K\n'; done
        out="$out$UI_PAD$1"$'\033[K'
    fi
    printf '\033[H%s\033[J' "$out" >&4
    FA=(); FL=0; UI_VC=0
}
ui_vlen() { local s="${1//$'\033'\[*([0-9;])m/}"; REPLY=${#s}; }
ui_rep()  { local s; printf -v s '%*s' "$2" ''; REPLY="${s// /$1}"; }
ui_trunc() {  # plain text, width -> REPLY
    local s="$1" w="$2"
    s="${s//$'\r'/ }"; s="${s//$'\t'/ }"
    s="${s//$'\033'\[*([0-9;?])[a-zA-Z]/}"
    s="${s//[$'\001'-$'\037']/}"
    if [ "${#s}" -gt "$w" ]; then
        if [ "$UI_UTF" = 1 ]; then s="${s:0:$((w - 1))}…"; else s="${s:0:$((w - 3))}..."; fi
    fi
    REPLY="$s"
}
ui_lr() {  # left right width -> REPLY: left, gap, right-aligned right
    local w="$3" gap l
    ui_vlen "$1"; l=$REPLY
    ui_vlen "$2"; gap=$(( w - l - REPLY )); [ "$gap" -lt 1 ] && gap=1
    printf -v REPLY '%s%*s%s' "$1" "$gap" '' "$2"
}
box_top() {
    local t="$1" w=$((UI_W - 2))
    if [ -n "$t" ]; then
        ui_vlen "$t"; ui_rep "$G_H" $(( w - REPLY - 3 ))
        fl "${C_FAINT}${G_TL}${G_H}${R} ${B}${t}${R} ${C_FAINT}${REPLY}${G_TR}${R}"
    else
        ui_rep "$G_H" "$w"; fl "${C_FAINT}${G_TL}${REPLY}${G_TR}${R}"
    fi
}
box_l() {
    local inner=$((UI_W - 4)) pad
    ui_vlen "$1"; pad=$(( inner - REPLY )); [ "$pad" -lt 0 ] && pad=0
    printf -v REPLY '%*s' "$pad" ''
    fl "${C_FAINT}${G_V}${R} $1${REPLY} ${C_FAINT}${G_V}${R}"
}
box_bot() { ui_rep "$G_H" $((UI_W - 2)); fl "${C_FAINT}${G_BL}${REPLY}${G_BR}${R}"; }
box_kv() {  # key value
    local k; printf -v k '%-10s' "$1"
    box_l "${C_DIM}${k}${R} $2"
}

ui_wrap() {  # text width -> WRAP=(lines)
    local text="$1" w="$2" line="" word
    WRAP=()
    for word in $text; do
        if [ -z "$line" ]; then line="$word"
        elif [ $(( ${#line} + 1 + ${#word} )) -le "$w" ]; then line="$line $word"
        else WRAP+=("$line"); line="$word"; fi
    done
    [ -n "$line" ] && WRAP+=("$line")
    [ "${#WRAP[@]}" -gt 0 ] || WRAP=("")
}

ui_keys() {  # "key:label" ... -> REPLY (styled hint bar)
    local out="" pair k l used=0 add
    for pair in "$@"; do
        k="${pair%%:*}"; l="${pair#*:}"
        add=$(( ${#k} + ${#l} + 6 ))
        # Never wrap: on a narrow window the last hints just drop off.
        [ $(( used + add )) -gt $(( UI_W - 12 )) ] && break
        out="$out${C_KEYBG}${C_CYAN}${B} ${k} ${R} ${C_DIM}${l}${R}   "
        used=$(( used + add ))
    done
    REPLY="$out"
}

ui_stepper() {  # current index 0..3
    local names="Welcome Choose Review Install" i=0 n out="" col
    for n in $names; do
        if [ "$i" -lt "$1" ]; then col="${C_CYAN}${G_STEP_ON} ${C_DIM}${n}${R}"
        elif [ "$i" -eq "$1" ]; then col="${C_CYAN}${B}${G_STEP_ON} ${C_HI}${n}${R}"
        else col="${C_FAINT}${G_STEP_OFF} ${n}${R}"; fi
        [ "$i" -gt 0 ] && out="$out ${C_FAINT}${G_H}${G_H}${R} "
        out="$out$col"
        i=$((i + 1))
    done
    fl "$out"
}

ui_header() {  # big|small
    local i lp
    if [ "$1" = big ] && [ "$UI_COLS" -ge $((LOGO_WID + 6)) ]; then
        fl ""
        lp=$(( (UI_W - LOGO_WID) / 2 )); [ "$lp" -lt 0 ] && lp=0
        printf -v lp '%*s' "$lp" ''
        for (( i = 0; i < LOGO_N; i++ )); do fl "$lp${LOGO_C[$i]}"; done
        ui_trunc "The cockpit for LibreLane  ${G_DOT}  RTL ${G_ARR} GDSII" "$UI_W"
        local tag="$REPLY"
        lp=$(( (UI_W - ${#tag}) / 2 )); [ "$lp" -lt 0 ] && lp=0
        printf -v lp '%*s' "$lp" ''
        fl "$lp${C_DIM}${tag}${R}"
    else
        ui_gradtext "LanEx"
        ui_lr "${C_CYAN}${G_DIAM}${R} ${B}${REPLY}${R} ${C_DIM}installer${R}" "${C_FAINT}${REPO}@${REF}${R}" "$UI_W"
        fl ""
        fl "$REPLY"
    fi
    fl ""
}

ui_flash() { UI_FLASH="$1"; UI_FLASH_T=$SECONDS; }
ui_flash_line() {
    if [ -n "$UI_FLASH" ]; then fl "${C_WARN}${G_INFO} ${UI_FLASH}${R}"; else fl ""; fi
}

ui_too_small() {  # -> 0 when the window is too small (and says so)
    if [ "$UI_COLS" -lt 60 ] || [ "$UI_ROWS" -lt 20 ]; then
        FA=(); FL=0
        printf '\033[H\033[2J' >&4
        printf '\n  %sMake this window a bit bigger%s\n  (at least 60 x 20; now %s x %s)\n\n  q quits\n' \
            "$B" "$R" "$UI_COLS" "$UI_ROWS" >&4
        return 0
    fi
    return 1
}

# ---- facts about this machine -------------------------------------------
lanex_pkg_version() {
    # From the package metadata: `lanex --version` imports LibreLane (slow on
    # a first run) and prints its own legacy string.
    # The venv is wherever the `lanex` command's interpreter lives (pipx moved
    # its home between versions; the fallback is ~/.lanex/venv).
    local d cmd py venv=""
    cmd="${LAUNCHER:-$(command -v lanex 2>/dev/null)}"
    py="$(head -n 1 "$cmd" 2>/dev/null)"
    case "$py" in '#!'*python*) py="${py#\#!}"; venv="${py%% *}"; venv="${venv%/bin/*}" ;; esac
    for d in ${venv:+"$venv"/lib/python3*/site-packages/lanex-*.dist-info} \
             "$HOME"/.local/share/pipx/venvs/lanex/lib/python3*/site-packages/lanex-*.dist-info \
             "$HOME"/.local/pipx/venvs/lanex/lib/python3*/site-packages/lanex-*.dist-info \
             "$HOME"/.lanex/venv/lib/python3*/site-packages/lanex-*.dist-info; do
        [ -d "$d" ] || continue
        d="${d##*/lanex-}"; printf '%s' "${d%.dist-info}"; return 0
    done
    return 1
}

sys_facts() {
    local v
    if [ "$OS" = "macos" ]; then
        SYS_OS="macOS $(sw_vers -productVersion 2>/dev/null)"
    else
        SYS_OS="$( . /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-Linux}")"
        [ "$WSL" = "1" ] && { [ "$WSL1" = "1" ] && SYS_OS="$SYS_OS ${G_DOT} WSL 1" || SYS_OS="$SYS_OS ${G_DOT} WSL 2"; }
    fi
    SYS_OS="$SYS_OS ${G_DOT} $(uname -m)"
    v="$(best_python 2>/dev/null || true)"
    if [ -n "$v" ]; then SYS_PY="$("$v" --version 2>&1 | sed 's/Python //')"; else SYS_PY=""; fi
    SYS_FREE="$(disk_free_mb "$HOME")"; [ -n "$SYS_FREE" ] || SYS_FREE=0
    SYS_ENGINE=""
    if command -v docker >/dev/null 2>&1; then
        SYS_ENGINE="docker"
        if command -v timeout >/dev/null 2>&1; then
            timeout 6 docker info >/dev/null 2>&1 && SYS_ENGINE="docker-up"
        fi
    elif command -v podman >/dev/null 2>&1; then
        SYS_ENGINE="podman"
    fi
    SYS_LANEX=""; SYS_LANEX_VER=""
    if command -v lanex >/dev/null 2>&1; then
        SYS_LANEX="$(command -v lanex)"
        SYS_LANEX_VER="$(lanex_pkg_version)"
    fi
    SAVED_PROFILE=""
    if [ -f "$(lanex_home)/setup-choices.json" ]; then
        SAVED_PROFILE="$(sed -n 's/.*"profile"[[:space:]]*:[[:space:]]*"\([a-z]*\)".*/\1/p' "$(lanex_home)/setup-choices.json" | head -n 1)"
    fi
}

# ---- Welcome ----------------------------------------------------------------
ui_draw_welcome() {
    ui_too_small && return
    local i lp eng lx big=small
    [ "$UI_ROWS" -ge 30 ] && big=big
    ui_header "$big"
    if [ "$big" = big ] && [ "$UI_INTRO" = 1 ] && [ "${LANEX_NO_ANIM:-0}" != "1" ] && [ "$UI_COLOR" -ge 2 ]; then
        # Reveal: the wordmark draws in, row by row, then the rest appears.
        printf '\033[H\033[2J' >&4
        lp=$(( (UI_W - LOGO_WID) / 2 )); printf -v lp '%*s' "$lp" ''
        for (( i = 0; i < LOGO_N; i++ )); do
            printf '\033[%d;1H%s%s%s\033[K' "$((i + 2))" "$UI_PAD" "$lp" "${LOGO_C[$i]}" >&4
            sleep 0.04
        done
        sleep 0.12
        UI_INTRO=0
    fi
    UI_INTRO=0
    ui_stepper 0
    fl ""
    box_top "This machine"
    box_kv "System" "$SYS_OS"
    if [ "$PKG" = "none" ]; then box_kv "Packages" "${C_WARN}no package manager found${R} ${C_DIM}(uses what is installed)${R}"
    elif [ -n "$SUDO" ]; then box_kv "Packages" "$PKG ${C_DIM}${G_DOT} uses sudo for system packages${R}"
    else box_kv "Packages" "$PKG"; fi
    if [ -n "$SYS_PY" ]; then box_kv "Python" "$SYS_PY"
    else box_kv "Python" "${C_DIM}not found ${G_DOT} will be installed${R}"; fi
    fmt_mb "$SYS_FREE"; box_kv "Free space" "$REPLY ${C_DIM}in $HOME${R}"
    case "$SYS_ENGINE" in
        docker-up) eng="${C_OK}${G_OK}${R} Docker is running" ;;
        docker)    eng="Docker installed ${C_DIM}${G_DOT} service not answering yet${R}" ;;
        podman)    eng="Podman installed" ;;
        *)         eng="${C_DIM}none yet${R}" ;;
    esac
    box_kv "Containers" "$eng"
    if [ -n "$SYS_LANEX" ]; then
        lx="${SYS_LANEX_VER:-installed} ${C_DIM}${G_DOT} will be upgraded in place${R}"
    else
        lx="${C_DIM}not installed yet${R}"
    fi
    box_kv "LanEx" "$lx"
    box_bot
    fl ""
    ui_wrap "Sets up LanEx and, if you want, the whole chip-design toolchain: the LibreLane tool image, simulators, viewers and PDKs. You pick how much on the next screen." "$((UI_W - 2))"
    for i in "${WRAP[@]}"; do fl " $i"; done
    if [ -n "$SYS_LANEX" ]; then
        fl ""
        ui_wrap "Your projects, run results and caches are kept." "$((UI_W - 4))"
        for i in "${WRAP[@]}"; do fl " ${C_OK}${G_OK}${R} $i"; done
    fi
    ui_keys "$G_ENTER:Continue" "q:Quit"
    ui_lr "$REPLY" "${C_FAINT}Apache-2.0${R}" "$UI_W"
    UI_VC=1
    fflush "$REPLY"
}

ui_welcome() {
    UI_FLASH=""
    ui_draw_welcome
    while :; do
        ui_wait_key ui_draw_welcome
        case "$KEY" in
            enter|right|space) return 0 ;;
            q|Q|esc) return 2 ;;
        esac
    done
}

# ---- Profile ----------------------------------------------------------------
PROF_KEYS=(recommended custom minimal complete)
PROF_NAMES=(Recommended Custom Minimal Complete)
PROF_TAGS=("Tools, viewers and SKY130A. Ready to design."
           "Choose your tools and PDKs."
           "Install LanEx now. Add tools and PDKs later."
           "All supported tools and PDKs. Largest download.")
PROF_SEL=0
CUSTOM_INIT=0

prof_bullets() {  # profile -> BUL=(lines)
    case "$1" in
        recommended) BUL=(
            "Container engine: Docker"
            "LibreLane tool image, matched to this LanEx and pinned by digest"
            "Verilator, Icarus Verilog, GTKWave, Graphviz, GDS3D 3D viewer"
            "SkyWater 130 nm PDK (sky130A) with the starter libraries"
            "Turnkey: open LanEx and run a design end to end") ;;
        custom) BUL=(
            "Pick the container engine, each tool, each PDK and extra libraries"
            "Starts from what you had, or from Recommended"
            "Download and disk figures update as you tick") ;;
        minimal) BUL=(
            "Only the LanEx app and its Python packages"
            "Smallest download, fastest install"
            "Add the engine, tools and PDKs any time in LanEx ${G_ARR} Tools") ;;
        complete) BUL=(
            "Everything in Recommended"
            "All PDKs: sky130A, sky130B, gf180mcuD and ihp-sg13g2"
            "Every published library of each PDK"
            "Largest download and disk use") ;;
    esac
}

prof_estimate() {  # profile -> EST_DL/EST_DISK without touching the choice
    local sp="$CH_PROFILE" se="$CH_ENGINE" si="$CH_IMAGE" sn="$CH_NATIVE" sk="$CH_PDKS" ss="$CH_LIBS_SKY" sg="$CH_LIBS_GF"
    if [ "$1" = custom ]; then
        if [ "$CUSTOM_INIT" = 1 ]; then custom_to_state; else set_profile recommended; fi
    else
        set_profile "$1"
    fi
    est_compute
    free_compute
    CH_PROFILE="$sp"; CH_ENGINE="$se"; CH_IMAGE="$si"; CH_NATIVE="$sn"; CH_PDKS="$sk"; CH_LIBS_SKY="$ss"; CH_LIBS_GF="$sg"
}

ui_est_line() {  # -> REPLY "↓ 2.4 GB download   ▪ 14 GB disk   ✓ 812 GB free"
    local dl disk fr ok
    fmt_mb "$EST_DL"; dl="$REPLY"; fmt_mb "$EST_DISK"; disk="$REPLY"; fmt_mb "$FREE_MB"; fr="$REPLY"
    if [ "$FREE_MB" -ge "$EST_DISK" ]; then ok="${C_OK}${G_OK}${R} ${fr} ${C_DIM}free${R}"
    else ok="${C_ERR}${G_ERR} only ${fr} free${R}"; fi
    if [ "$UI_W" -lt 64 ]; then
        REPLY="${C_CYAN}${G_DL}${R} ${B}${dl}${R}  ${C_CYAN}${G_DISK}${R} ${B}${disk}${R}  ${ok}"; return
    fi
    REPLY="${C_CYAN}${G_DL}${R} ${B}${dl}${R} ${C_DIM}download${R}   ${C_CYAN}${G_DISK}${R} ${B}${disk}${R} ${C_DIM}disk${R}   ${ok}"
}

ui_draw_profile() {
    ui_too_small && return
    local i name tag line mark num last big=small
    [ "$UI_ROWS" -ge 36 ] && big=big
    ui_header "$big"
    ui_stepper 1
    fl ""
    fl "${B}How much should LanEx install?${R}"
    fl "${C_DIM}You can add or remove tools and PDKs later in LanEx ${G_ARR} Tools.${R}"
    fl ""
    for i in 0 1 2 3; do
        printf -v name '%-12s' "${PROF_NAMES[$i]}"
        tag="${PROF_TAGS[$i]}"
        last=""; [ "${PROF_KEYS[$i]}" = "$SAVED_PROFILE" ] && last="last time"
        ui_trunc "$tag" $(( UI_W - 22 - ${#last} - 2 )); tag="$REPLY"
        if [ "$i" = "$PROF_SEL" ]; then
            line="${C_SELBG}${C_CYAN}${B} ${G_PTR} $((i + 1))  ${C_HI}${name}${R}${C_SELBG} ${tag}"
            ui_lr "$line" "${C_DIM}${last} " "$UI_W"
            fl "$REPLY$R"
        else
            ui_lr "   ${C_DIM}$((i + 1))${R}  ${name} ${C_DIM}${tag}${R}" "${C_FAINT}${last}${R} " "$UI_W"
            fl "$REPLY"
        fi
    done
    fl ""
    prof_bullets "${PROF_KEYS[$PROF_SEL]}"
    box_top "${PROF_NAMES[$PROF_SEL]}"
    local room=$(( UI_ROWS - FL - 5 )) shown=0
    for i in "${BUL[@]}"; do
        [ "$shown" -ge "$room" ] && break
        ui_trunc "$i" $((UI_W - 8)); box_l "${C_CYAN}${G_INFO}${R} $REPLY"; shown=$((shown + 1))
    done
    box_l ""
    prof_estimate "${PROF_KEYS[$PROF_SEL]}"
    ui_est_line; box_l "$REPLY"
    box_bot
    ui_flash_line
    ui_keys "$G_UPDN:Move" "1-4:Pick" "$G_ENTER:Next" "Esc:Back" "q:Quit"
    fflush "$REPLY"
}

ui_profile() {
    UI_FLASH=""
    ui_draw_profile
    while :; do
        ui_wait_key ui_draw_profile
        case "$KEY" in
            up)   PROF_SEL=$(( (PROF_SEL + 3) % 4 )) ;;
            down|tab) PROF_SEL=$(( (PROF_SEL + 1) % 4 )) ;;
            1|2|3|4) PROF_SEL=$(( KEY - 1 )) ;;
            r|R) PROF_SEL=0 ;; c|C) PROF_SEL=1 ;; m|M) PROF_SEL=2 ;;
            enter|right|space)
                if [ "$PROF_SEL" = 1 ]; then
                    if [ "$CUSTOM_INIT" = 0 ] && [ "$SAVED_PROFILE" != custom ]; then set_profile recommended; fi
                    CH_PROFILE=custom
                else set_profile "${PROF_KEYS[$PROF_SEL]}"; fi
                return 0 ;;
            esc|left|back) return 1 ;;
            q|Q) return 2 ;;
        esac
        ui_draw_profile
    done
}

# ---- Custom checklist ---------------------------------------------------------
# Parallel arrays: kind (g=group r=radio c=check), id, label, size, value, enabled, hint
CK=(); CI=(); CL=(); CS=(); CV=(); CE=(); CH=(); CN=0; CSEL=1; CTOP=0

c_add() { CK[$CN]="$1"; CI[$CN]="$2"; CL[$CN]="$3"; CS[$CN]="$4"; CV[$CN]=0; CE[$CN]=1; CH[$CN]="$5"; CN=$((CN + 1)); }
c_idx() { local i; for (( i = 0; i < CN; i++ )); do [ "${CI[$i]}" = "$1" ] && { REPLY=$i; return 0; }; done; REPLY=-1; return 1; }
c_val() { c_idx "$1" && [ "${CV[$REPLY]}" = 1 ]; }
c_set() { c_idx "$1" && CV[$REPLY]="$2"; }

custom_build() {
    CK=(); CI=(); CL=(); CS=(); CV=(); CE=(); CH=(); CN=0
    local l
    c_add g "" "Container engine" "" ""
    c_add r docker "Docker" "recommended" "The engine most LibreLane users run. Installed from your distro, started, and you are added to the docker group."
    c_add r podman "Podman" "" "Daemonless and rootless. Works the same for LanEx."
    c_add r none "None" "" "No container engine: no tool image and no PDKs. LanEx can still lint, simulate and view."
    c_add g "" "Tools ${G_DOT} flow and visualization" "" ""
    c_add c image "Chip design toolchain (matched LibreLane image)" "1.5 GB" "Yosys, OpenROAD, Magic, KLayout, Netgen and the rest of LibreLane, in the exact image this LanEx is tested with (pinned by digest)."
    c_add c verilator "Verilator" "25 MB" "Fast Verilog simulation and linting."
    c_add c iverilog "Icarus Verilog & GTKWave" "10 MB" "Event-driven simulation and the waveform viewer."
    c_add c graphviz "Graphviz" "8 MB" "Draws the flow and report diagrams."
    c_add c gds3d "GDS3D" "230 MB" "3D layout viewer; built from its pinned source commit (needs a compiler, which is installed for it)."
    c_add g "" "Process design kits ${G_DOT} not sure? start with sky130A" "" ""
    c_add c sky130A "sky130A ${G_DOT} SkyWater 130 nm" "330 MB" "The default SKY130 variant, the one most open designs use. Starter libraries: hd, hvl, io, primitives, SRAM macros."
    c_add c sky130B "sky130B ${G_DOT} SkyWater 130 nm, ReRAM/SONOS" "shared" "SKY130 with the ReRAM/SONOS layers. Shares its download with sky130A."
    c_add c gf180mcuD "gf180mcuD ${G_DOT} GlobalFoundries 180 nm" "410 MB" "The default GF180MCU variant."
    c_add c gf180mcuC "gf180mcuC ${G_DOT} GlobalFoundries 180 nm (legacy)" "410 MB" "Legacy GF180MCU metal stack."
    c_add c gf180mcuA "gf180mcuA ${G_DOT} unsupported for this flow" "" "Not supported by the LibreLane flow in this release."
    c_add c gf180mcuB "gf180mcuB ${G_DOT} unsupported for this flow" "" "Not supported by the LibreLane flow in this release."
    c_add c ihp-sg13g2 "ihp-sg13g2 ${G_DOT} IHP 130 nm SiGe BiCMOS" "21 MB" "IHP's open 130 nm BiCMOS process."
    c_add g "" "Extra SKY130 libraries" "" ""
    c_add c sky:sky130_fd_sc_hdll "sky130_fd_sc_hdll ${G_DOT} high density, low leakage" "126 MB" "Standard cells. Added to each SKY130 variant you picked."
    c_add c sky:sky130_fd_sc_hs "sky130_fd_sc_hs ${G_DOT} high speed" "633 MB" "Standard cells. Added to each SKY130 variant you picked."
    c_add c sky:sky130_fd_sc_lp "sky130_fd_sc_lp ${G_DOT} low power" "516 MB" "Standard cells. Added to each SKY130 variant you picked."
    c_add c sky:sky130_fd_sc_ls "sky130_fd_sc_ls ${G_DOT} low speed" "743 MB" "Standard cells. Added to each SKY130 variant you picked."
    c_add c sky:sky130_fd_sc_ms "sky130_fd_sc_ms ${G_DOT} medium speed" "590 MB" "Standard cells. Added to each SKY130 variant you picked."
    c_add c sky:sky130_fd_pr_reram "sky130_fd_pr_reram ${G_DOT} ReRAM primitives" "1 MB" "ReRAM primitive cells; sky130B only."
    c_add g "" "Extra GF180 libraries (gf180mcuD)" "" ""
    for l in "gf180mcu_as_sc_mcu7t3v3:7-track standard cells:2 MB" \
             "gf180mcu_osu_sc_gp12t3v3:OSU 12-track standard cells:13 MB" \
             "gf180mcu_osu_sc_gp9t3v3:OSU 9-track standard cells:13 MB" \
             "gf180mcu_ocd_io:I/O cells:44 MB" \
             "gf180mcu_ocd_alpha_large:large layout font:1 MB" \
             "gf180mcu_ocd_alpha_misc:misc layout graphics:1 MB" \
             "gf180mcu_ocd_alpha_small:small layout font:1 MB"; do
        local id="${l%%:*}" rest="${l#*:}"
        c_add c "gf:$id" "$id ${G_DOT} ${rest%%:*}" "${rest#*:}" "Added to gf180mcuD."
    done
    c_add g "" "Not published for this release" "" ""
    c_add c na:gf180mcu_ocd_ip_sram "gf180mcu_ocd_ip_sram" "" "Not published for this release."
    c_add c na:gf180mcu_re_efuse "gf180mcu_re_efuse" "" "Not published for this release."
}

custom_from_state() {
    local i id w
    for (( i = 0; i < CN; i++ )); do
        id="${CI[$i]}"; CV[$i]=0
        case "$id" in
            docker|podman|none) [ "$CH_ENGINE" = "$id" ] && CV[$i]=1 ;;
            image) [ "$CH_IMAGE" = 1 ] && CV[$i]=1 ;;
            verilator|graphviz|gds3d) has_word "$CH_NATIVE" "$id" && CV[$i]=1 ;;
            iverilog) { has_word "$CH_NATIVE" iverilog || has_word "$CH_NATIVE" gtkwave; } && CV[$i]=1 ;;
            sky:*) has_word "$CH_LIBS_SKY" "${id#sky:}" && CV[$i]=1 ;;
            gf:*) has_word "$CH_LIBS_GF" "${id#gf:}" && CV[$i]=1 ;;
            na:*|"") ;;
            *) has_word "$CH_PDKS" "$id" && CV[$i]=1 ;;
        esac
    done
    custom_rules
}

custom_to_state() {
    local i id
    CH_PROFILE=custom; CH_ENGINE=docker; CH_IMAGE=0; CH_NATIVE=""; CH_PDKS=""; CH_LIBS_SKY=""; CH_LIBS_GF=""
    for (( i = 0; i < CN; i++ )); do
        [ "${CV[$i]}" = 1 ] || continue
        id="${CI[$i]}"
        case "$id" in
            docker|podman|none) CH_ENGINE="$id" ;;
            image) CH_IMAGE=1 ;;
            verilator|graphviz|gds3d) CH_NATIVE="${CH_NATIVE:+$CH_NATIVE }$id" ;;
            iverilog) CH_NATIVE="${CH_NATIVE:+$CH_NATIVE }iverilog gtkwave" ;;
            sky:*) CH_LIBS_SKY="${CH_LIBS_SKY:+$CH_LIBS_SKY }${id#sky:}" ;;
            gf:*) CH_LIBS_GF="${CH_LIBS_GF:+$CH_LIBS_GF }${id#gf:}" ;;
            na:*|"") ;;
            *) CH_PDKS="${CH_PDKS:+$CH_PDKS }$id" ;;
        esac
    done
}

custom_rules() {  # enable/disable items the way the Windows checklist does
    local i id anypdk=0 sky=0 skyb=0 gfd=0 noeng=0
    c_val none && noeng=1
    for id in sky130A sky130B gf180mcuD gf180mcuC ihp-sg13g2; do c_val "$id" && anypdk=1; done
    { c_val sky130A || c_val sky130B; } && sky=1
    c_val sky130B && skyb=1
    c_val gf180mcuD && gfd=1
    for (( i = 0; i < CN; i++ )); do
        id="${CI[$i]}"; CE[$i]=1
        case "$id" in
            image)
                if [ "$noeng" = 1 ]; then CE[$i]=0; CV[$i]=0
                elif [ "$anypdk" = 1 ]; then CE[$i]=0; CV[$i]=1; fi ;;
            sky130A|sky130B|gf180mcuD|gf180mcuC|ihp-sg13g2)
                [ "$noeng" = 1 ] && { CE[$i]=0; CV[$i]=0; } ;;
            gf180mcuA|gf180mcuB|na:*) CE[$i]=0; CV[$i]=0 ;;
            sky:sky130_fd_pr_reram) [ "$skyb" = 1 ] || { CE[$i]=0; CV[$i]=0; } ;;
            sky:*) [ "$sky" = 1 ] || { CE[$i]=0; CV[$i]=0; } ;;
            gf:*) [ "$gfd" = 1 ] || { CE[$i]=0; CV[$i]=0; } ;;
        esac
    done
}

custom_hint() {  # why an item is disabled / what it is
    local i="$CSEL" id="${CI[$CSEL]}"
    if [ "${CE[$i]}" = 0 ]; then
        case "$id" in
            image) if c_val none; then REPLY="Needs Docker or Podman."; else REPLY="Required by the PDKs you picked: they run inside this image."; fi ;;
            sky:sky130_fd_pr_reram) REPLY="Pick sky130B first: ReRAM exists only there." ;;
            sky:*) REPLY="Pick sky130A or sky130B first." ;;
            gf:*) REPLY="Pick gf180mcuD first." ;;
            sky130A|sky130B|gf180mcuD|gf180mcuC|ihp-sg13g2) REPLY="PDKs need a container engine: pick Docker or Podman." ;;
            *) REPLY="${CH[$i]}" ;;
        esac
    else
        REPLY="${CH[$i]}"
    fi
}

custom_toggle() {
    local i="$CSEL" id="${CI[$CSEL]}" j
    [ "${CK[$i]}" = g ] && return
    if [ "${CE[$i]}" = 0 ]; then custom_hint; ui_flash "$REPLY"; return; fi
    if [ "${CK[$i]}" = r ]; then
        for (( j = 0; j < CN; j++ )); do [ "${CK[$j]}" = r ] && CV[$j]=0; done
        CV[$i]=1
        if [ "$id" != none ]; then c_idx image && [ "${CV[$REPLY]}" = 0 ] && c_val none 2>/dev/null; fi
    else
        if [ "${CV[$i]}" = 1 ]; then CV[$i]=0; else CV[$i]=1; fi
    fi
    custom_rules
}

custom_move() {  # delta
    local n=$CSEL step=$1
    while :; do
        n=$(( n + step ))
        [ "$n" -lt 0 ] && return
        [ "$n" -ge "$CN" ] && return
        [ "${CK[$n]}" = g ] && continue
        CSEL=$n; return
    done
}

ui_draw_custom() {
    ui_too_small && return
    local i avail top bot line glyph lab size lw sel
    ui_header small
    ui_stepper 1
    fl ""
    custom_to_state; est_compute; free_compute
    ui_est_line; local est="$REPLY"
    fl "${B}Choose your components${R}"
    fl "$est"
    fl ""
    avail=$(( UI_ROWS - FL - 4 ))
    [ "$avail" -lt 5 ] && avail=5
    # keep the cursor (and its group header) in view
    [ "$CSEL" -lt "$CTOP" ] && CTOP=$CSEL
    [ "$CTOP" -gt 0 ] && [ "${CK[$((CSEL - 1))]}" = g ] && [ "$((CSEL - 1))" -lt "$CTOP" ] && CTOP=$((CSEL - 1))
    [ "$CSEL" -ge $(( CTOP + avail )) ] && CTOP=$(( CSEL - avail + 1 ))
    [ "$CTOP" -lt 0 ] && CTOP=0
    bot=$(( CTOP + avail )); [ "$bot" -gt "$CN" ] && bot=$CN
    lw=$(( UI_W - 16 ))
    for (( i = CTOP; i < bot; i++ )); do
        if [ "${CK[$i]}" = g ]; then
            ui_trunc "${CL[$i]}" "$((UI_W - 4))"
            fl "  ${C_CYAN}${B}${REPLY}${R}"
            continue
        fi
        if [ "${CK[$i]}" = r ]; then
            [ "${CV[$i]}" = 1 ] && glyph="$G_RON" || glyph="$G_ROFF"
        elif [ "${CE[$i]}" = 0 ] && [ "${CV[$i]}" = 1 ]; then glyph="$G_CON"
        elif [ "${CE[$i]}" = 0 ]; then glyph="$G_CDIS"
        else
            [ "${CV[$i]}" = 1 ] && glyph="$G_CON" || glyph="$G_COFF"
        fi
        ui_trunc "${CL[$i]}" "$lw"; lab="$REPLY"
        size="${CS[$i]}"
        if [ "$i" = "$CSEL" ]; then
            line="${C_SELBG}${C_CYAN}${B} ${G_PTR} ${glyph} ${C_HI}${lab}${R}${C_SELBG}"
            ui_lr "$line" "${C_DIM}${size} " "$UI_W"
            fl "$REPLY$R"
        elif [ "${CE[$i]}" = 0 ]; then
            ui_lr "   ${C_FAINT}${glyph} ${lab}${R}" "${C_FAINT}${size}${R} " "$UI_W"; fl "$REPLY"
        else
            if [ "${CV[$i]}" = 1 ]; then glyph="${C_CYAN}${glyph}${R}"; else glyph="${C_DIM}${glyph}${R}"; fi
            ui_lr "   ${glyph} ${lab}" "${C_DIM}${size}${R} " "$UI_W"; fl "$REPLY"
        fi
    done
    # scroll marks
    if [ "$CTOP" -gt 0 ] || [ "$bot" -lt "$CN" ]; then
        local up="" dn=""
        [ "$CTOP" -gt 0 ] && up="${G_UP} more above"
        [ "$bot" -lt "$CN" ] && dn="${G_DN} more below"
        ui_lr "${C_FAINT}${up}${R}" "${C_FAINT}${dn}${R}" "$UI_W"; fl "$REPLY"
    else
        fl ""
    fi
    if [ -n "$UI_FLASH" ]; then fl "${C_WARN}${G_INFO} ${UI_FLASH}${R}"
    else custom_hint; ui_trunc "$REPLY" "$((UI_W - 2))"; fl "${C_DIM}${IT}${REPLY}${R}"; fi
    ui_keys "$G_UPDN:Move" "Space:Toggle" "$G_ENTER:Review" "Esc:Back"
    fflush "$REPLY"
}
REPLY_EST=""

ui_custom() {
    if [ "$CUSTOM_INIT" = 0 ]; then
        custom_build
        [ "$SAVED_PROFILE" = custom ] && load_choices_file "$(lanex_home)/setup-choices.json" >/dev/null 2>&1
        custom_from_state
        CUSTOM_INIT=1; CSEL=1; CTOP=0
    fi
    UI_FLASH=""
    ui_draw_custom
    while :; do
        ui_wait_key ui_draw_custom
        case "$KEY" in
            up) custom_move -1 ;;
            down|tab) custom_move 1 ;;
            pgup) local k; for k in 1 2 3 4 5 6 7 8; do custom_move -1; done ;;
            pgdn) local k; for k in 1 2 3 4 5 6 7 8; do custom_move 1; done ;;
            home) CSEL=0; custom_move 1 ;;
            end) CSEL=$CN; custom_move -1 ;;
            space|x|X) custom_toggle ;;
            enter|right)
                custom_to_state
                if [ "$CH_IMAGE" = 0 ] && [ -z "$CH_NATIVE" ] && [ -z "$CH_PDKS" ] && [ "$CH_ENGINE" = none ]; then
                    set_profile minimal
                fi
                return 0 ;;
            esc|left|back) custom_to_state; return 1 ;;
            q|Q) return 2 ;;
        esac
        ui_draw_custom
    done
}

# ---- Review -------------------------------------------------------------------
review_tools() {
    local out="" w
    for w in $CH_NATIVE; do
        case "$w" in
            verilator) w="Verilator" ;; iverilog) w="Icarus Verilog" ;; gtkwave) w="GTKWave" ;;
            graphviz) w="Graphviz" ;; gds3d) w="GDS3D" ;;
        esac
        out="${out:+$out ${G_DOT} }$w"
    done
    REPLY="${out:-${C_DIM}none${R}}"
}

review_pdks() {
    local out="" v n
    for v in $CH_PDKS; do
        n=""
        case "$CH_PROFILE:$v" in
            complete:*) n=" (all libraries)" ;;
            *:sky130A|*:sky130B) [ -n "$CH_LIBS_SKY" ] && n=" (+$(set -- $CH_LIBS_SKY; echo $#) libs)" ;;
            *:gf180mcuD) [ -n "$CH_LIBS_GF" ] && n=" (+$(set -- $CH_LIBS_GF; echo $#) libs)" ;;
        esac
        out="${out:+$out ${G_DOT} }$v$n"
    done
    REPLY="${out:-${C_DIM}none${R}}"
}

ui_draw_review() {
    ui_too_small && return
    local eng big=small pname
    [ "$UI_ROWS" -ge 38 ] && big=big
    ui_header "$big"
    ui_stepper 2
    fl ""
    est_compute; free_compute
    case "$CH_PROFILE" in
        recommended) pname="Recommended" ;; complete) pname="Complete" ;;
        minimal) pname="Minimal" ;; *) pname="Custom" ;;
    esac
    fl "${B}Ready to install${R}  ${C_DIM}${G_DOT} ${pname}${R}"
    fl ""
    box_top "What will be set up"
    box_kv "App" "LanEx ${C_DIM}${G_DOT} the ${R}lanex${C_DIM} command${R}"
    case "$CH_ENGINE" in
        none) eng="${C_DIM}none${R}" ;;
        docker) if [ "$SYS_ENGINE" = docker-up ]; then eng="Docker ${C_DIM}${G_DOT} already running${R}"
                else eng="Docker ${C_DIM}${G_DOT} install, start, join the docker group${R}"; fi ;;
        podman) eng="Podman" ;;
    esac
    box_kv "Engine" "$eng"
    if [ "$CH_IMAGE" = 1 ]; then box_kv "Toolchain" "LibreLane image ${C_DIM}${G_DOT} matched, digest-pinned${R}"
    else box_kv "Toolchain" "${C_DIM}none${R}"; fi
    review_tools; ui_trunc "$REPLY" "$((UI_W - 16))"; box_kv "Tools" "$REPLY"
    review_pdks; box_kv "PDKs" "$REPLY"
    box_l ""
    ui_est_line; box_l "$REPLY"
    box_bot
    fl ""
    if [ -n "$SUDO" ] && [ "$(id -u)" != 0 ]; then
        fl "${C_CYAN}${G_LOCK}${R}  Asks for your password once: sudo installs the system packages."
    fi
    if [ -n "$SYS_LANEX" ]; then
        fl "${C_OK}${G_OK}${R}  LanEx is upgraded in place. Projects, runs and caches are kept."
    fi
    if [ "$FREE_MB" -lt "$EST_DISK" ]; then
        fmt_mb "$((EST_DISK - FREE_MB))"
        fl "${C_ERR}${G_ERR}${R}  Not enough free space: free about ${B}${REPLY}${R} more, or go back and pick less."
    fi
    fl "${C_DIM}${G_INFO}  Re-run the same command any time to change this or to upgrade.${R}"
    ui_flash_line
    ui_keys "$G_ENTER:Install" "Esc:Back" "q:Quit"
    fflush "$REPLY"
}

ui_review() {
    ui_draw_review
    while :; do
        ui_wait_key ui_draw_review
        case "$KEY" in
            enter|i|I) return 0 ;;
            esc|left|back) return 1 ;;
            q|Q) return 2 ;;
        esac
    done
}

# ---- sudo, once ---------------------------------------------------------------
ui_sudo() {
    [ -n "$SUDO" ] || return 0
    [ "$(id -u)" = 0 ] && return 0
    if ! sudo -n true 2>/dev/null; then
        ui_drain_input
        ui_header small
        ui_stepper 3
        fl ""
        fl "${C_CYAN}${G_LOCK}${R}  ${B}Administrator password${R}"
        fl ""
        ui_wrap "LanEx installs system packages (Python, ${PKG} packages, the container engine) with sudo. Your password goes to sudo, never to LanEx. It is asked for once." "$((UI_W - 4))"
        local l; for l in "${WRAP[@]}"; do fl "   ${C_DIM}${l}${R}"; done
        fl ""
        fflush
        printf '\033[?25h' >&4
        stty echo <&3 2>/dev/null
        stty -echo <&3 2>/dev/null
        if ! sudo -v -p "${UI_PAD}   ${C_CYAN}${G_PTR}${R} password for %u: " <&3 2>&4; then
            printf '\033[?25l' >&4
            ui_flash "sudo did not accept the password. Enter to try again, Esc to go back."
            return 1
        fi
        printf '\033[?25l' >&4
    fi
    # Keep the ticket fresh for long downloads; stops with this script.
    ( while kill -0 "$$" 2>/dev/null; do sudo -n -v 2>/dev/null; sleep 45; done ) >/dev/null 2>&1 </dev/null &
    LX_KEEPALIVE=$!
    SUDO="sudo -n"
    return 0
}

# ---- Install --------------------------------------------------------------------
RK=(); RL=(); RS=(); RT0=(); RT1=(); RW=(); RE=(); RF=(); RR=(); RA=(); RB=(); RN=0
row_add() { RK[$RN]="$1"; RL[$RN]="$2"; RW[$RN]="$3"; RE[$RN]="$4"; RS[$RN]=0; RT0[$RN]=0; RT1[$RN]=0; RF[$RN]=0; RR[$RN]=0; RA[$RN]=""; RB[$RN]=0; RN=$((RN + 1)); }
row_idx() { local i; for (( i = 0; i < RN; i++ )); do [ "${RK[$i]}" = "$1" ] && { REPLY=$i; return 0; }; done; REPLY=-1; return 1; }
row_start() { RS[$1]=1; RT0[$1]=$SECONDS; RF[$1]=0; RR[$1]=0; RA[$1]=""; RB[$1]=0; }
row_done()  { [ "${RS[$1]}" = 1 ] || RT0[$1]=$SECONDS; RS[$1]=2; RT1[$1]=$SECONDS; RF[$1]=1000; RA[$1]=""; }

plan_rows() {
    RN=0
    local pk="$PKG" nat="" w fam v vs mb
    [ "$PKG" = none ] && pk="none found"
    row_add preflight "Check this machine" 1 4
    row_add syspkg "System packages ${G_DOT} ${pk}" 5 60
    row_add app "LanEx app" 6 90
    case "$CH_ENGINE" in
        docker) row_add engine "Docker engine" 4 50 ;;
        podman) row_add engine "Podman engine" 3 40 ;;
    esac
    for w in $CH_NATIVE; do
        case "$w" in
            verilator) nat="${nat:+$nat, }Verilator" ;; iverilog) nat="${nat:+$nat, }Icarus Verilog" ;;
            gtkwave) nat="${nat:+$nat, }GTKWave" ;; graphviz) nat="${nat:+$nat, }Graphviz" ;;
        esac
    done
    { [ -n "$nat" ] || has_word "$CH_NATIVE" gds3d; } && row_add native "${nat:-Build tools for GDS3D}" 3 60
    has_word "$CH_NATIVE" gds3d && row_add gds3d "GDS3D 3D viewer ${G_DOT} build" 4 150
    [ "$CH_IMAGE" = 1 ] && row_add image "LibreLane tool image ${G_DOT} 1.5 GB" 30 600
    for fam in $(pdk_families); do
        vs=""
        for v in $CH_PDKS; do [ "$(pdk_family "$v")" = "$fam" ] && vs="${vs:+$vs, }$v"; done
        row_add "pdk:$fam" "PDK ${vs}" 22 300
    done
    row_add verify "Final check" 2 25
}

fmt_dur() {  # secs -> REPLY
    local s=$1
    if [ "$s" -lt 60 ]; then REPLY="${s}s"
    elif [ "$s" -lt 3600 ]; then printf -v REPLY '%d:%02d' $((s / 60)) $((s % 60))
    else printf -v REPLY '%d:%02d:%02d' $((s / 3600)) $((s % 3600 / 60)) $((s % 60)); fi
}

row_frac() {  # index -> REPLY permille
    local i=$1 e
    case "${RS[$i]}" in
        2) REPLY=1000 ;;
        1) if [ "${RR[$i]}" = 1 ]; then REPLY=$(( RB[$i] + RF[$i] * (1000 - RB[$i]) / 1000 ))
           else e=$(( SECONDS - RT0[$i] )); REPLY=$(( 930 * e / (e + RE[$i]) )); fi ;;
        *) REPLY=0 ;;
    esac
}

overall_pm() {
    local i tw=0 acc=0
    for (( i = 0; i < RN; i++ )); do
        tw=$(( tw + RW[$i] ))
        row_frac "$i"; acc=$(( acc + RW[$i] * REPLY ))
    done
    [ "$tw" -gt 0 ] || tw=1
    REPLY=$(( acc / tw ))
    # Never backwards: a step's estimate can be replaced by a lower real figure.
    if [ "$REPLY" -lt "$UI_PM_MAX" ]; then REPLY=$UI_PM_MAX; else UI_PM_MAX=$REPLY; fi
}
UI_PM_MAX=0

ui_bar() {  # permille width -> REPLY
    local pm=$1 w=$2 full half i out="" shine last=""
    full=$(( pm * w / 1000 )); half=$(( (pm * w * 2 / 1000) % 2 ))
    shine=-1
    [ "$full" -gt 2 ] && [ "$UI_COLOR" -ge 2 ] && shine=$(( UI_TICK % (full + 12) ))
    for (( i = 0; i < full; i++ )); do
        if [ "$i" = "$shine" ]; then out="$out$C_SHINE$G_BAR"; last="s"; continue; fi
        ui_grad "$i" "$w"
        if [ "$REPLY" != "$last" ]; then out="$out$REPLY"; last="$REPLY"; fi
        out="$out$G_BAR"
    done
    if [ "$half" = 1 ] && [ "$full" -lt "$w" ]; then ui_grad "$full" "$w"; out="$out$REPLY$G_BARH"; full=$((full + 1)); fi
    ui_rep "$G_BAR" $(( w - full ))
    REPLY="$out$R$C_TRACK$REPLY$R"
}

# Parse the running step's new log lines: @@LANEX events from the finalizer
# (step / progress), apt's pmstatus/dlstatus lines, else "the last line".
ui_parse_log() {
    local cur="$1" n chunk line ev comp pct msg idx
    [ -f "$LX_STEPLOG" ] || return 0
    n=$(wc -l < "$LX_STEPLOG" 2>/dev/null | tr -d ' ')
    case "$n" in ''|*[!0-9]*) return 0 ;; esac
    [ "$n" -gt "$LX_SEEN" ] || return 0
    chunk="$(sed -n "$((LX_SEEN + 1)),${n}p" "$LX_STEPLOG" 2>/dev/null)"
    LX_SEEN=$n
    while IFS= read -r line; do
        case "$line" in
            @@LANEX:*)
                line="${line#@@LANEX:}"
                ui_jf "$line" event; ev="$REPLY"
                ui_jf "$line" component; comp="$REPLY"
                ui_map_component "$comp"; idx="$REPLY"
                case "$ev" in
                    step)
                        ui_jf "$line" message; msg="$REPLY"
                        if [ "$idx" -ge 0 ]; then
                            local j
                            for (( j = 0; j < idx; j++ )); do [ "${RS[$j]}" = 1 ] && [ "${RK[$j]}" != "$cur" ] && row_done "$j"; done
                            [ "${RS[$idx]}" = 2 ] || { [ "${RS[$idx]}" = 1 ] || row_start "$idx"; RA[$idx]="$msg"; }
                        fi ;;
                    progress)
                        ui_jf "$line" percent; pct="$REPLY"
                        ui_jf "$line" message; msg="$REPLY"
                        case "$pct" in ''|*[!0-9]*) pct="" ;; esac
                        if [ "$idx" -ge 0 ] && [ "${RS[$idx]}" = 1 ]; then
                            if [ -n "$pct" ]; then
                                # first real figure: carry on from the estimate already shown
                                [ "${RR[$idx]}" = 1 ] || { row_frac "$idx"; RB[$idx]=$REPLY; }
                                RF[$idx]=$(( pct * 10 )); RR[$idx]=1
                            fi
                            [ -n "$msg" ] && RA[$idx]="$msg"
                        fi ;;
                esac ;;
            pmstatus:*|dlstatus:*)
                local rest="${line#*:}"; rest="${rest#*:}"
                pct="${rest%%:*}"; msg="${rest#*:}"; pct="${pct%%.*}"
                row_idx "$cur"; [ "$REPLY" -ge 0 ] && RA[$REPLY]="$msg ${C_FAINT}${pct}%" ;;
            '{"'*|'') ;;
            *) row_idx "$cur"
               if [ "$REPLY" -ge 0 ]; then
                   local ri=$REPLY
                   # During the finalizer, raw lines belong to whichever row is live.
                   if [ "$cur" = "final" ]; then local j; for (( j = 0; j < RN; j++ )); do [ "${RS[$j]}" = 1 ] && ri=$j; done; fi
                   line="${line#== }"; line="${line#   }"
                   RA[$ri]="$line"
               fi ;;
        esac
    done <<< "$chunk"
}

ui_jf() {  # json key -> REPLY (flat string/number field; good enough for our events)
    local s="$1" k="\"$2\":"
    REPLY=""
    case "$s" in *"$k"*) ;; *) return 1 ;; esac
    s="${s#*"$k"}"
    if [ "${s:0:1}" = '"' ]; then s="${s:1}"; REPLY="${s%%\"*}"
    else REPLY="${s%%[,\}]*}"; fi
    REPLY="${REPLY//\\u2014/-}"; REPLY="${REPLY//\\u2026/...}"
}

ui_map_component() {  # finalizer component -> row index (or -1)
    case "$1" in
        engine:*)          row_idx engine ;;
        native:gds3d|gds3d) row_idx gds3d ;;
        native:*)          row_idx native ;;
        container:image)   row_idx image ;;
        pdk-family:*)      row_idx "pdk:${1#pdk-family:}" ;;
        pdk:*)             local v="${1#pdk:}"; v="${v%%:*}"; row_idx "pdk:$(pdk_family "$v")" ;;
        verify)            row_idx verify ;;
        *)                 REPLY=-1 ;;
    esac
    return 0
}

ui_draw_install() {
    local i st glyph lab right line act big=0 need tail_n=0 t
    if [ "$UI_COLS" -lt 50 ] || [ "$UI_ROWS" -lt 12 ]; then
        overall_pm
        printf '\033[H\033[2J  LanEx  %d%%\n' $((REPLY / 10)) >&4
        return
    fi
    need=$(( RN + 14 ))
    [ "$UI_ROWS" -ge $(( need + LOGO_N + 3 )) ] && big=1
    [ "$UI_ROWS" -ge $(( need + LOGO_N + 8 )) ] && tail_n=4
    [ "$big" = 0 ] && [ "$UI_ROWS" -ge $(( need + 5 )) ] && tail_n=3
    if [ "$big" = 1 ]; then ui_header big; else ui_header small; fi
    ui_stepper 3
    fl ""
    fmt_dur $(( SECONDS - LX_T0 )); t="$REPLY"
    case "$CH_PROFILE" in recommended) lab="Recommended" ;; complete) lab="Complete" ;; minimal) lab="Minimal" ;; *) lab="Custom" ;; esac
    ui_lr "${B}Installing LanEx${R} ${C_DIM}${G_DOT} ${lab}${R}" "${C_DIM}${t}${R}" "$UI_W"
    fl "$REPLY"
    fl ""
    for (( i = 0; i < RN; i++ )); do
        st="${RS[$i]}"; right=""
        case "$st" in
            2) glyph="${C_OK}${G_OK}${R}"; lab="${RL[$i]}"
               fmt_dur $(( RT1[$i] - RT0[$i] )); right="${C_FAINT}${REPLY}${R}" ;;
            1) glyph="${C_CYAN}${UI_SPIN[$(( UI_TICK % ${#UI_SPIN[@]} ))]}${R}"; lab="${B}${RL[$i]}${R}"
               fmt_dur $(( SECONDS - RT0[$i] )); right="${C_DIM}${REPLY}${R}"
               [ "${RR[$i]}" = 1 ] && right="${C_CYAN}$(( RF[$i] / 10 ))%${R}  $right" ;;
            3) glyph="${C_ERR}${G_ERR}${R}"; lab="${C_ERR}${RL[$i]}${R}" ;;
            4) glyph="${C_FAINT}${G_SKIP}${R}"; lab="${C_FAINT}${RL[$i]}${R}" ;;
            *) glyph="${C_FAINT}${G_TODO}${R}"; lab="${C_DIM}${RL[$i]}${R}" ;;
        esac
        ui_lr "  $glyph  $lab" "$right " "$UI_W"
        fl "$REPLY"
        if [ "$st" = 1 ]; then
            act="${RA[$i]}"
            [ -n "$act" ] || act="working..."
            ui_trunc "$act" $(( UI_W - 10 ))
            fl "     ${C_FAINT}${G_ELBOW}${R} ${C_DIM}${REPLY}${R}"
        fi
    done
    fl ""
    overall_pm; local pm=$REPLY
    ui_bar "$pm" $(( UI_W - 10 ))
    printf -v line '%s  %s%3d%%%s' "$REPLY" "$B" $(( pm / 10 )) "$R"
    fl " $line"
    local done_n=0; for (( i = 0; i < RN; i++ )); do [ "${RS[$i]}" = 2 ] && done_n=$((done_n + 1)); done
    fl " ${C_DIM}${done_n} of ${RN} steps done${R}"
    if [ "$tail_n" -gt 0 ] && [ -f "$LX_STEPLOG" ]; then
        fl ""
        local tl
        while IFS= read -r tl; do
            case "$tl" in @@LANEX:*|pmstatus:*|dlstatus:*|'{"'*) continue ;; esac
            ui_trunc "$tl" $(( UI_W - 4 ))
            fl " ${C_FAINT}${G_V} ${REPLY}${R}"
        done <<< "$(grep -v -e '^@@LANEX:' -e '^pmstatus:' -e '^dlstatus:' -e '^{"' -e '^[[:space:]]*$' "$LX_STEPLOG" 2>/dev/null | tail -n "$tail_n")"
    fi
    ui_trunc "$LX_LOG" $(( UI_W - 40 ))
    ui_lr "${C_FAINT}Log ${REPLY}${R}" "${C_FAINT}Ctrl+C stops ${G_DOT} safe to re-run${R}" "$UI_W"
    fflush "$REPLY"
}

state_save() {
    printf 'PY=%q\nLAUNCHER=%q\nDOCKER_GROUP_ADDED=%q\nMANIFEST=%q\nCHOICES=%q\n' \
        "$PY" "$LAUNCHER" "$DOCKER_GROUP_ADDED" "$MANIFEST" "$CHOICES" > "$LX_STATE" 2>/dev/null
}
state_load() { [ -f "$LX_STATE" ] && . "$LX_STATE"; return 0; }

stage_preflight() {
    say "Preflight"
    net_check
    local free; free="$(disk_free_mb "$HOME")"
    note "free space in $HOME: ${free} MB"
    return 0
}
stage_app() {
    require_python
    install_lanex
    expose_on_path
    return 0
}
stage_verify() { verify_install; }

run_row() {  # key function [cur-tag]
    local key="$1" fn="$2" cur="${3:-$1}" idx rc
    row_idx "$key"; idx=$REPLY
    [ "$idx" -ge 0 ] && row_start "$idx"
    LX_STEPLOG="$LX_DIR/step-$key.log"; : > "$LX_STEPLOG"; LX_SEEN=0
    rm -f "$LX_FAILMSG"
    ( "$fn"; rc=$?; state_save; exit $rc ) >> "$LX_STEPLOG" 2>&1 < /dev/null &
    LX_PID=$!
    while kill -0 "$LX_PID" 2>/dev/null; do
        [ "$UI_RESIZED" = 1 ] && { ui_size; printf '\033[2J' >&4; }
        ui_parse_log "$cur"
        ui_draw_install
        UI_TICK=$((UI_TICK + 1))
        sleep 0.1
    done
    wait "$LX_PID"; rc=$?
    LX_PID=""
    ui_parse_log "$cur"
    { printf '\n######## step %s (exit %s) ########\n' "$key" "$rc"; cat "$LX_STEPLOG"; } >> "$LX_LOG" 2>/dev/null
    state_load
    if [ "$rc" -ne 0 ]; then
        local j failed=0
        for (( j = 0; j < RN; j++ )); do [ "${RS[$j]}" = 1 ] && { RS[$j]=3; failed=1; LX_FAILROW="${RL[$j]}"; }; done
        [ "$failed" = 0 ] && [ "$idx" -ge 0 ] && { RS[$idx]=3; LX_FAILROW="${RL[$idx]}"; }
        ui_draw_install
        sleep 0.6
        ui_fail
    fi
    [ "$idx" -ge 0 ] && row_done "$idx"
    ui_draw_install
}
LX_FAILROW=""

stage_final() {  # the finalizer covers gds3d, image, PDKs and the last check
    finalize_stage
}

ui_install() {
    local stamp
    LX_INSTALLING=1
    LX_DIR="$(lanex_home)/logs"
    mkdir -p "$LX_DIR" 2>/dev/null || LX_DIR="${TMPDIR:-/tmp}"
    stamp="$(date +%Y%m%d-%H%M%S)"
    LX_LOG="$LX_DIR/install-$stamp.log"
    LX_FAILMSG="$LX_DIR/.install-$stamp.fail"
    LX_STATE="$LX_DIR/.install-$stamp.state"
    : > "$LX_LOG"
    { printf 'LanEx installer %s@%s  %s\n' "$REPO" "$REF" "$(date)"
      printf 'profile=%s choices=%s\n' "$CH_PROFILE" "$(choices_json)"
      printf 'system=%s pkg=%s python=%s\n' "$SYS_OS" "$PKG" "$SYS_PY"; } >> "$LX_LOG"
    export DEBIAN_FRONTEND=noninteractive
    export LX_APT_STATUS=1
    export LX_FAILMSG
    export UI
    LX_T0=$SECONDS
    # Remembered for next time: the picker starts on this choice.
    { mkdir -p "$(lanex_home)" && choices_json > "$(lanex_home)/setup-choices.json"; } 2>/dev/null || true
    plan_rows
    printf '\033[2J' >&4
    run_row preflight stage_preflight
    run_row syspkg system_deps
    run_row app stage_app
    if [ "$CH_ENGINE" != none ]; then run_row engine engine_stage; fi
    row_idx native; [ "$REPLY" -ge 0 ] && run_row native native_stage
    if [ "$CH_PROFILE" != minimal ] && needs_finalize; then
        # One process, several rows: its @@LANEX step events move the marker.
        run_row_final
    else
        run_row verify stage_verify
    fi
    local j; for (( j = 0; j < RN; j++ )); do [ "${RS[$j]}" = 2 ] || row_done "$j"; done
    ui_draw_install
    sleep 0.5
    ui_done
}

run_row_final() {
    local rc j
    LX_STEPLOG="$LX_DIR/step-final.log"; : > "$LX_STEPLOG"; LX_SEEN=0
    rm -f "$LX_FAILMSG"
    for (( j = 0; j < RN; j++ )); do
        case "${RK[$j]}" in gds3d|image|pdk:*|verify) row_start "$j"; break ;; esac
    done
    ( stage_final; rc=$?; state_save; exit $rc ) >> "$LX_STEPLOG" 2>&1 < /dev/null &
    LX_PID=$!
    while kill -0 "$LX_PID" 2>/dev/null; do
        [ "$UI_RESIZED" = 1 ] && { ui_size; printf '\033[2J' >&4; }
        ui_parse_log final
        ui_draw_install
        UI_TICK=$((UI_TICK + 1))
        sleep 0.1
    done
    wait "$LX_PID"; rc=$?
    LX_PID=""
    ui_parse_log final
    { printf '\n######## step components (exit %s) ########\n' "$rc"; cat "$LX_STEPLOG"; } >> "$LX_LOG" 2>/dev/null
    state_load
    if [ "$rc" -ne 0 ]; then
        local failed=0
        for (( j = 0; j < RN; j++ )); do [ "${RS[$j]}" = 1 ] && { RS[$j]=3; failed=1; LX_FAILROW="${RL[$j]}"; }; done
        [ "$failed" = 0 ] && { row_idx verify; RS[$REPLY]=3; LX_FAILROW="${RL[$REPLY]}"; }
        ui_draw_install
        sleep 0.6
        ui_fail
    fi
}

# ---- Done / failed (printed to the normal screen so they stay in scrollback) --
out_box() {  # width title, then lines from OB=()
    local w="$1" t="$2" l inner pad
    inner=$(( w - 4 ))
    ui_vlen "$t"; ui_rep "$G_H" $(( w - REPLY - 5 ))
    printf '  %s%s%s%s %s %s%s%s%s\n' "$C_FAINT" "$G_TL" "$G_H" "$R" "$t" "$C_FAINT" "$REPLY" "$G_TR" "$R" >&4
    for l in "${OB[@]}"; do
        ui_vlen "$l"; pad=$(( inner - REPLY )); [ "$pad" -lt 0 ] && pad=0
        printf '  %s%s%s %s%*s %s%s%s\n' "$C_FAINT" "$G_V" "$R" "$l" "$pad" '' "$C_FAINT" "$G_V" "$R" >&4
    done
    ui_rep "$G_H" $(( w - 2 ))
    printf '  %s%s%s%s%s\n' "$C_FAINT" "$G_BL" "$REPLY" "$G_BR" "$R" >&4
}

ui_done() {
    local w i inst="" lp ver
    LX_INSTALLING=0
    [ -n "$LX_KEEPALIVE" ] && kill "$LX_KEEPALIVE" 2>/dev/null; LX_KEEPALIVE=""
    ui_leave_screen
    w=$(( UI_COLS - 4 )); [ "$w" -gt 76 ] && w=76
    printf '\n' >&4
    if [ "$UI_COLS" -ge $((LOGO_WID + 4)) ]; then
        for (( i = 0; i < LOGO_N; i++ )); do printf '  %s\n' "${LOGO_C[$i]}" >&4; done
        printf '\n' >&4
    fi
    ver="$(lanex_pkg_version)"
    local items=("LanEx${ver:+ $ver}") nt v
    [ "$CH_ENGINE" != none ] && items+=("$( [ "$CH_ENGINE" = docker ] && echo Docker || echo Podman)")
    [ "$CH_IMAGE" = 1 ] && items+=("LibreLane image")
    nt="$(set -- $CH_NATIVE; echo $#)"; [ "$nt" -gt 0 ] && items+=("$nt tools")
    for v in $CH_PDKS; do items+=("$v"); done
    fmt_dur $(( SECONDS - LX_T0 ))
    local took="$REPLY" lg="$LX_LOG" line="" lines=() max=$(( w - 20 ))
    case "$lg" in "$HOME"/*) lg="~${lg#$HOME}" ;; esac
    ui_trunc "$lg" $(( w - 18 )); lg="$REPLY"
    # Wrap the list at item boundaries, never leaving a separator dangling.
    for v in "${items[@]}"; do
        if [ -z "$line" ]; then line="$v"
        elif [ $(( ${#line} + 3 + ${#v} )) -le "$max" ]; then line="$line ${G_DOT} $v"
        else lines+=("$line"); line="$v"; fi
    done
    lines+=("$line")
    OB=("" "${C_DIM}Start it${R}      ${C_CYAN}${B}lanex${R}" "${C_DIM}Installed${R}     ${lines[0]}")
    for (( i = 1; i < ${#lines[@]}; i++ )); do OB+=("              ${lines[$i]}"); done
    OB+=("${C_DIM}Took${R}          $took" "${C_DIM}Log${R}           $lg" "")
    out_box "$w" "${C_OK}${B}${G_OK} LanEx is ready${R}"
    printf '\n' >&4
    if [ "$DOCKER_GROUP_ADDED" = 1 ]; then
        ui_wrap "You were added to the docker group. LanEx uses it right away; for the docker command in your own shell, open a new terminal (or log out and in)." $(( w - 4 ))
        printf '  %s%s%s %s\n' "$C_CYAN" "$G_INFO" "$R" "${WRAP[0]}" >&4
        for (( i = 1; i < ${#WRAP[@]}; i++ )); do printf '    %s\n' "${WRAP[$i]}" >&4; done
    fi
    if [ "$WSL" = 1 ]; then
        ui_wrap "WSL: start LanEx from an interactive terminal. In a script or shortcut use  bash -ic lanex  (WSLg brings up its display bridge only for interactive shells)." $(( w - 4 ))
        printf '  %s%s%s %s\n' "$C_CYAN" "$G_INFO" "$R" "${WRAP[0]}" >&4
        for (( i = 1; i < ${#WRAP[@]}; i++ )); do printf '    %s\n' "${WRAP[$i]}" >&4; done
    fi
    printf '  %s%s%s %s\n\n' "$C_CYAN" "$G_INFO" "$R" "Run the same install command again to upgrade or change components." >&4
    # Offer to start it, where a window can actually open.
    if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] || [ "$WSL" = 1 ] || [ "$OS" = macos ]; then
        local a=""
        ui_drain_input
        printf '  %sStart LanEx now?%s %s[Y/n]%s ' "$B" "$R" "$C_DIM" "$R" >&4
        stty echo <&3 2>/dev/null
        IFS= read -r -t 120 -u 3 a || a="n"
        stty "$UI_STTY" <&3 2>/dev/null
        case "$a" in
            n*|N*) printf '\n  Start it any time with:  %slanex%s\n\n' "$B" "$R" >&4 ;;
            *) printf '\n' >&4
               trap - EXIT INT TERM HUP
               exec env TERM="${_LX_TERM:-xterm}" "$LAUNCHER" <&3 >&4 2>&4 ;;
        esac
    fi
    trap - EXIT
    exit 0
}

ui_fail() {
    local w msg i lg
    LX_INSTALLING=0
    [ -n "$LX_KEEPALIVE" ] && kill "$LX_KEEPALIVE" 2>/dev/null; LX_KEEPALIVE=""
    ui_leave_screen
    w=$(( UI_COLS - 4 )); [ "$w" -gt 86 ] && w=86
    if [ -s "$LX_FAILMSG" ]; then msg="$(cat "$LX_FAILMSG")"
    else msg="$(grep -v -e '^@@LANEX:' -e '^pmstatus:' -e '^dlstatus:' -e '^[[:space:]]*$' "$LX_STEPLOG" 2>/dev/null | tail -n 3)"; fi
    [ -n "$msg" ] || msg="The step ended with an error (see the log)."
    OB=("")
    while IFS= read -r i; do
        i="${i#   }"
        ui_wrap "$i" $(( w - 6 ))
        local k; for k in "${WRAP[@]}"; do OB+=("$k"); done
    done <<< "$msg"
    OB+=("")
    printf '\n' >&4
    out_box "$w" "${C_ERR}${B}${G_ERR} Stopped at: ${LX_FAILROW:-install}${R}"
    lg="$LX_LOG"
    printf '\n  %sNext step%s  Fix what the message says, then run the same command again.\n' "$B" "$R" >&4
    printf '             Everything that finished is kept and skipped next time.\n' >&4
    printf '  %sLog%s        %s\n\n' "$B" "$R" "$lg" >&4
    printf '  %sLast lines of the log:%s\n' "$C_DIM" "$R" >&4
    grep -v -e '^@@LANEX:' -e '^pmstatus:' -e '^dlstatus:' -e '^[[:space:]]*$' "$LX_STEPLOG" 2>/dev/null | tail -n 12 \
        | while IFS= read -r i; do ui_trunc "$i" $(( w - 4 )); printf '  %s%s %s%s\n' "$C_FAINT" "$G_V" "$REPLY" "$R" >&4; done
    printf '\n' >&4
    trap - EXIT
    exit 1
}

ui_run() {
    local screen=welcome rc
    detect_platform
    setup_privileges
    ui_caps
    # sys_facts asks docker and the package metadata; say something meanwhile.
    printf '\n  %s%s%s %sLanEx installer%s %s%s checking this machine...%s' \
        "$C_CYAN" "$G_DIAM" "$R" "$B" "$R" "$C_DIM" "$G_DOT" "$R" > /dev/tty 2>/dev/null
    sys_facts
    if [ -f "$(lanex_home)/setup-choices.json" ]; then
        load_choices_file "$(lanex_home)/setup-choices.json" >/dev/null 2>&1 || true
        case "$SAVED_PROFILE" in
            recommended) PROF_SEL=0 ;; custom) PROF_SEL=1 ;; minimal) PROF_SEL=2 ;; complete) PROF_SEL=3 ;;
        esac
    fi
    [ -n "$CH_PROFILE" ] || set_profile recommended
    ui_init
    while :; do
        case "$screen" in
            welcome) ui_welcome; rc=$?
                     case $rc in 0) screen=profile ;; *) screen=quit ;; esac ;;
            profile) ui_profile; rc=$?
                     UI_FLASH=""
                     case $rc in
                         0) if [ "$CH_PROFILE" = custom ]; then screen=custom; else screen=review; fi ;;
                         1) screen=welcome ;; *) screen=quit ;;
                     esac ;;
            custom)  ui_custom; rc=$?
                     UI_FLASH=""
                     case $rc in 0) screen=review ;; 1) screen=profile ;; *) screen=quit ;; esac ;;
            review)  ui_review; rc=$?
                     case $rc in
                         0) if ui_sudo; then screen=install; else screen=review; fi ;;
                         1) if [ "$CH_PROFILE" = custom ] || [ "$PROF_SEL" = 1 ]; then screen=custom; else screen=profile; fi ;;
                         *) screen=quit ;;
                     esac ;;
            install) ui_install ;;
            quit)    ui_leave_screen
                     printf '\n  %sCancelled.%s Nothing was installed.\n\n' "$B" "$R" >&4
                     trap - EXIT
                     exit 0 ;;
        esac
    done
}

# -------------------------------------------------------------------- main --
usage() {
    cat << 'EOFUSAGE'
LanEx installer

  curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/scripts/install.sh | bash

In a terminal it asks what to install (Recommended, Custom, Minimal, Complete).
Unattended:

  ... | bash -s -- --profile recommended     # or complete, minimal
  ... | bash -s -- --choices my-choices.json  # a Setup choices file (custom)
  ... | LANEX_ASSUME_YES=1 bash               # the app (classic, no profile)

Options: --profile NAME, --choices FILE, --yes, --no-ui, --help
EOFUSAGE
}

main() {
    # Side-effect-free diagnostic used by packaging tests to prove that branch,
    # tag, SHA, fork repository, and local-wheel inputs resolve exactly.
    if [ "${1:-}" = "--print-source" ]; then
        resolve_source
        return 0
    fi
    local profile="${LANEX_PROFILE:-}" choices="${LANEX_CHOICES:-}"
    while [ $# -gt 0 ]; do
        case "$1" in
            --profile) profile="${2:-}"; shift ;;
            --profile=*) profile="${1#*=}" ;;
            --choices) choices="${2:-}"; shift ;;
            --choices=*) choices="${1#*=}" ;;
            --yes|-y) export LANEX_ASSUME_YES=1 ;;
            --no-ui) export LANEX_NO_UI=1 ;;
            -h|--help) usage; return 0 ;;
            *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; return 2 ;;
        esac
        shift
    done
    if [ -n "$choices" ]; then
        [ -f "$choices" ] || die "Choices file not found: $choices"
        load_choices_file "$choices" \
            || die "Could not read the choices in $choices (needs Python 3.10+ and a Setup choices JSON)."
    elif [ -n "$profile" ]; then
        set_profile "$profile" || die "Unknown profile '$profile'. Use recommended, complete, minimal or custom (with --choices)."
        [ "$CH_PROFILE" = "custom" ] && die "A custom profile needs its choices: --choices <file>."
    fi

    # A person at a terminal and nothing decided yet: the interactive installer.
    if [ -z "$profile" ] && [ -z "$choices" ] && ui_capable; then
        ui_run
        return $?
    fi

    detect_platform
    setup_privileges
    say "LanEx installer — $OS$( [ "$WSL" = "1" ] && echo ' (WSL)') / packages: $PKG$( [ -n "$CH_PROFILE" ] && echo " / profile: $CH_PROFILE")"
    net_check
    system_deps
    require_python
    install_lanex
    expose_on_path
    verify_install
    if [ -n "$CH_PROFILE" ]; then
        [ "$CH_PROFILE" = "minimal" ] || stage_components
    else
        prepull_image
        gds3d_stage
    fi
    wsl_notes
    say "Done — launch the cockpit with:  lanex"
    note "Re-running this installer later upgrades LanEx in place."
}

main "$@"
