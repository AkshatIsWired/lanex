#!/usr/bin/env bash
# provision.sh — turn a freshly imported, empty Ubuntu WSL distro into the LanEx
# appliance. Runs INSIDE the distro, as root, driven by the Windows installer:
#
#   wsl.exe -d lanex -u root -- bash /mnt/c/.../provision.sh
#
# The Windows user never sees this file. They double-click LanEx-Setup.exe; this
# is what makes the "no terminal, no Ubuntu, no password prompt" promise true.
#
# DESIGN RULES (same ones scripts/install.sh follows — read that file first):
#   * No `set -e`. A missing nice-to-have degrades with a warning; only things
#     that would leave a broken appliance go through die() with actionable text
#     that the installer shows the user verbatim.
#   * IDEMPOTENT. The installer's "Repair" button and a re-run of the setup exe
#     both re-run this script over a working install. Every stage checks first.
#   * Wrapped in main() called on the LAST LINE, so a half-copied file can never
#     execute half a command.
#   * NO WSL-only assumptions outside wsl_conf() — Phase 2 runs this same script
#     inside a plain `ubuntu:24.04` container to bake a rootfs (see
#     .github/workflows/windows-installer.yml).
#   * ZERO new install logic. LanEx itself is installed by the repo's own
#     scripts/install.sh with its silent-mode env knobs — one installer to keep
#     working, not two.
#
# Environment knobs:
#   LANEX_REF=<ref>        branch/tag of the repo to install (default: main)
#   LANEX_USER=<name>      appliance user (default: lanex; the launcher and the
#                          Inno script hardcode "lanex" — override for testing)
#   LANEX_PROVISION_DNS=1  force the WSL DNS fix even if github.com is reachable
set -u -o pipefail

REPO="AkshatIsWired/lanex"
REF="${LANEX_REF:-main}"
APP_USER="${LANEX_USER:-lanex}"
INSTALL_SH="https://raw.githubusercontent.com/${REPO}/${REF}/scripts/install.sh"

say()  { printf '\n== %s\n' "$*"; }
note() { printf '   %s\n' "$*"; }
warn() { printf '!! %s\n' "$*"; }
# die() text is what the installer's error page shows the user, so it must read
# like a sentence a non-technical person can act on — no shell jargon.
die()  { printf '\nXX provision failed: %s\n' "$*" >&2; exit 1; }

# Deliberately unstyled output (no ANSI): this streams into an Inno Setup log
# window, which renders escape codes as garbage.

# --------------------------------------------------------------- preflight  --
require_root() {
    [ "$(id -u)" = "0" ] || die "this script must run as root inside the LanEx environment."
}

# One apt front-end for the whole script. DPkg::Lock::Timeout: a freshly booted
# Ubuntu runs unattended-upgrades in the background and holds the dpkg lock for
# minutes — waiting beats dying with "could not get lock" (install.sh:113-115).
APT="apt-get -o DPkg::Lock::Timeout=300 -qq"
export DEBIAN_FRONTEND=noninteractive

# ------------------------------------------------------------------- 1. DNS --
DNS_FIXED=0     # set by dns_guard; read by wsl_conf (generateResolvConf)

# The single most common fresh-WSL failure: the auto-generated /etc/resolv.conf
# points at a nameserver the host can't route to, so every download in this
# script would fail. Same fix install.sh:96-101 documents, applied for the user
# instead of printed at them. Factored out because ensure_curl needs it too:
# when curl is missing, apt is the thing that hits the broken resolver first.
apply_dns_fix() {
    DNS_FIXED=1
    # Order matters: resolv.conf may be a symlink into /run — remove, don't
    # append, or the write lands in a file nothing reads.
    rm -f /etc/resolv.conf 2>/dev/null || true
    { printf 'nameserver 8.8.8.8\nnameserver 1.1.1.1\n' > /etc/resolv.conf; } 2>/dev/null \
        || warn "could not write /etc/resolv.conf (read-only?) — continuing; downloads may fail."
}

# curl is both the network probe below and every download in this script.
# Ubuntu's WSL image ships it, so the Windows path never enters this function;
# a plain ubuntu:24.04 base (the Phase 2 rootfs bake) does not, and without this
# the probe would fail for "curl: not found" and be misdiagnosed as "no
# network" — the DNS fix would then be applied pointlessly and the script would
# die on a machine that was online all along.
ensure_curl() {
    command -v curl >/dev/null 2>&1 && return 0
    note "installing curl (minimal base image)."
    $APT update >/dev/null 2>&1
    $APT install -y curl ca-certificates >/dev/null 2>&1 && return 0
    warn "could not install curl — applying the known WSL DNS fix and retrying."
    apply_dns_fix
    $APT update >/dev/null 2>&1
    $APT install -y curl ca-certificates \
        || die "no internet connection inside the LanEx environment.
   Check your network (and any VPN or company proxy), then click Retry.
   Corporate proxy? Set https_proxy in your environment before running Setup."
}

dns_guard() {
    say "Network check"
    ensure_curl
    if [ "${LANEX_PROVISION_DNS:-0}" != "1" ] \
       && curl -fsI -m 12 https://github.com >/dev/null 2>&1; then
        note "github.com reachable."
        return 0
    fi
    warn "Cannot reach github.com — applying the known WSL DNS fix."
    apply_dns_fix
    if curl -fsI -m 12 https://github.com >/dev/null 2>&1; then
        note "network OK after the DNS fix."
    else
        die "no internet connection inside the LanEx environment.
   Check your network (and any VPN or company proxy), then click Retry.
   Corporate proxy? Set https_proxy in your environment before running Setup."
    fi
}

# -------------------------------------------------------------- 2. wsl.conf --
wsl_conf() {
    say "Environment configuration"
    # THE ONLY WSL-SPECIFIC STAGE (Phase 2 bakes this into the rootfs image, so
    # it stays harmless when this script runs in a plain container: it is just a
    # file that WSL, and only WSL, ever reads).
    #
    # Every line here is load-bearing:
    #   systemd=true        — Docker's service starts itself on boot, so the
    #                         user never runs `sudo service docker start`
    #                         (install.sh:388 has to tell CLI users to).
    #   default=lanex       — `wsl -d lanex -- ...` from LanEx.exe runs as the
    #                         appliance user, not root; install.sh refuses to
    #                         install for root and ~/.lanex must be the user's.
    #   interop/automount   — LanEx opens its window by launching the *Windows*
    #                         Edge over the interop bridge and /mnt/c paths
    #                         (appwindow.py:96-103, 272-303). Both default to
    #                         on; we pin them so a future default flip, or a
    #                         stray edit, can't silently kill the app window.
    local extra=""
    if [ "$DNS_FIXED" = "1" ]; then
        # Without this WSL regenerates resolv.conf on every boot and undoes the
        # fix applied above.
        extra=$'\n[network]\ngenerateResolvConf = false\n'
    fi
    cat > /etc/wsl.conf <<EOF
# Managed by LanEx Setup. Edits are overwritten on repair/reinstall.
[boot]
systemd = true

[user]
default = ${APP_USER}

[interop]
enabled = true
appendWindowsPath = true

[automount]
enabled = true
${extra}
EOF
    note "wrote /etc/wsl.conf (systemd on, default user ${APP_USER})."

    # Canonical's WSL images ship /etc/wsl-distribution.conf, whose [oobe]
    # section is what pops the "create a username / password" screen on first
    # launch. `wsl --import` normally skips OOBE, but the appliance promise is
    # "no prompt, ever" — so we disable it outright rather than rely on that.
    if [ -f /etc/wsl-distribution.conf ]; then
        sed -i 's/^\([[:space:]]*command[[:space:]]*=\)/# LanEx: OOBE disabled — \1/' \
            /etc/wsl-distribution.conf 2>/dev/null \
            && note "disabled the distro's first-run setup screen."
    fi
}

# ------------------------------------------------------------------ 3. user --
app_user() {
    say "Appliance user '${APP_USER}'"
    if id -u "$APP_USER" >/dev/null 2>&1; then
        note "already exists."
    else
        useradd -m -s /bin/bash "$APP_USER" \
            || die "could not create the '${APP_USER}' user inside the LanEx environment."
        note "created."
    fi
    # No password is ever set: nobody logs in interactively. Passwordless sudo
    # is what lets scripts/install.sh do its own `sudo apt-get` /
    # `sudo ln -s /usr/local/bin/lanex` stages unattended — install.sh refuses
    # to be *run* under sudo but calls sudo itself (install.sh:65-84).
    printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$APP_USER" > /etc/sudoers.d/lanex
    chmod 440 /etc/sudoers.d/lanex
    # A malformed sudoers file locks sudo out completely; validate and back out.
    if command -v visudo >/dev/null 2>&1 && ! visudo -cqf /etc/sudoers.d/lanex 2>/dev/null; then
        rm -f /etc/sudoers.d/lanex
        die "could not grant the LanEx environment permission to install its own packages."
    fi
    note "passwordless sudo granted (isolated environment, no interactive login)."
}

# ------------------------------------------------------------ 4. base pkgs  --
base_packages() {
    say "Base packages"
    $APT update || warn "apt update failed — using the existing package lists."
    # curl: every download below. ca-certificates: HTTPS. sudo: install.sh's
    # PATH + apt stages. Ubuntu's WSL image has all three, minimal container
    # bases (Phase 2) do not.
    $APT install -y curl ca-certificates sudo \
        || die "could not install basic packages (curl, ca-certificates, sudo).
   This usually means no internet connection inside the LanEx environment.
   Check your network and click Retry."
}

# ---------------------------------------------------------------- 5. docker --
docker_ce() {
    say "Container engine (Docker)"
    # Pre-baking Docker is the whole reason the appliance exists: LanEx's Tools
    # tab CAN install it (installer.py:613-617 runs this exact script), but that
    # path needs a sudo password prompt in a terminal — precisely what this
    # installer promises the user will never see.
    if command -v docker >/dev/null 2>&1; then
        note "already installed ($(docker --version 2>/dev/null || echo 'version unknown'))."
    else
        # The official convenience script — same one the Tools tab uses, so
        # there is exactly one Docker install path in the project. We are root
        # here, so no `sudo sh` (installer.py:617 needs the sudo; we don't).
        curl -fsSL https://get.docker.com | sh \
            || die "could not install Docker inside the LanEx environment.
   This is almost always a network problem. Click Retry.
   (LanEx can also install it later from its own Tools tab.)"
    fi
    # Without this, every `docker` call from LanEx needs `sg docker` wrapping —
    # tools.py:619-669 handles that, but the group membership makes it moot.
    if getent group docker >/dev/null 2>&1; then
        usermod -aG docker "$APP_USER" 2>/dev/null \
            || warn "could not add ${APP_USER} to the docker group — LanEx falls back to 'sg docker'."
    else
        warn "no docker group present — LanEx falls back to 'sg docker' wrapping."
    fi
    # Deliberately NOT started here: systemd isn't running yet in a distro we
    # only just imported (and never will be inside the Phase 2 container). The
    # installer restarts the distro afterwards; get.docker.com enables the
    # service, so systemd brings the daemon up on that first real boot.
    note "daemon will start automatically when the environment restarts."
}

# ----------------------------------------------------------------- 6. lanex --
install_lanex() {
    say "LanEx"
    # The repo's own universal installer, in silent mode, as the appliance user.
    # Everything it does — python3/venv, pipx-with-venv-fallback, the
    # /usr/local/bin/lanex symlink, GL drivers, X11 fonts, gtkwave — is already
    # debugged across distros; duplicating any of it here would mean two
    # installers to keep in sync. Deliberately skipped:
    #   LANEX_SKIP_PULL   — the ~3 GB LibreLane image. Downloading it here would
    #                       triple the install time for a file the Tools tab
    #                       pulls on first launch WITH a progress bar.
    #   LANEX_SKIP_GDS3D  — the optional 3D viewer compiles from source (minutes).
    #                       One click in the Tools tab installs it later; Phase 2
    #                       pre-bakes it into the rootfs.
    # A re-run upgrades LanEx in place (install.sh:17) — that is the Repair path.
    runuser -l "$APP_USER" -c "LANEX_ASSUME_YES=1 LANEX_SKIP_PULL=1 LANEX_SKIP_GDS3D=1 \
        LANEX_REF='${REF}' curl -fsSL '${INSTALL_SH}' | bash" \
        || die "the LanEx installer did not finish.
   The log above ends with its own error message.
   Click Retry — this step is safe to repeat."
}

# ----------------------------------------------------------------- 7. verify --
verify() {
    say "Verifying"
    # Exactly what the launcher will do on every start, run once here so a
    # broken appliance is caught by Setup (which can retry) and never by the
    # user's first double-click.
    runuser -l "$APP_USER" -c 'lanex --help >/dev/null 2>&1' \
        || die "LanEx installed but does not run.
   Click Retry, and if it keeps failing please report the log above."
    note "lanex responds."
    command -v docker >/dev/null 2>&1 \
        || die "Docker is missing after installation. Click Retry."
    note "docker present."
    # A wsl.conf typo would surface as "no systemd" / wrong user on next boot —
    # cheap to catch now.
    grep -q "default *= *${APP_USER}" /etc/wsl.conf 2>/dev/null \
        || warn "/etc/wsl.conf lost its default user — LanEx may start as root."
}

# -------------------------------------------------------------------- main  --
main() {
    require_root
    say "Provisioning the LanEx environment (Ubuntu, isolated)"
    note "ref: ${REF}   user: ${APP_USER}"
    dns_guard
    wsl_conf
    app_user
    base_packages
    docker_ce
    install_lanex
    verify
    say "The LanEx environment is ready."
    # The installer restarts the distro next (`wsl --terminate lanex`); saying
    # so keeps the log readable when a user sends it to us.
    note "Setup will now restart the environment so it boots with systemd."
}

main "$@"
