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
#   LANEX_REF=<ref>        branch/tag/SHA of the repo to install (default: main)
#   LANEX_REPO=<owner/name> source repository (default: AkshatIsWired/lanex)
#   LANEX_INSTALL_SCRIPT=<path> exact bundled scripts/install.sh to execute
#   LANEX_FROM=<path/url>   exact LanEx wheel/source passed to install.sh
#   LANEX_PIP_CONSTRAINT=<path> locked Windows dependency constraints
#   LANEX_SOURCE_SHA=<sha>  immutable source identity recorded in the appliance
#   LANEX_INSTALL_ID=<uuid> owner identity recorded in the appliance marker
#   LANEX_MANIFEST_HASH=<sha256> build-manifest identity for the marker
#   LANEX_BUILD_MANIFEST=<path> immutable component catalog/pins for finalization
#   LANEX_SETUP_CHOICES=<path> owner state or choices JSON for finalization
#   LANEX_USER=<name>      appliance user (default: lanex; override for testing)
#   LANEX_PROVISION_DNS=1  deprecated; static DNS is never applied automatically
#   LANEX_BAKE=1           CI is cooking a rootfs image, not provisioning a
#                          user's machine (see bake() below)
set -u -o pipefail

REPO="${LANEX_REPO:-AkshatIsWired/lanex}"
REF="${LANEX_REF:-main}"
APP_USER="${LANEX_USER:-lanex}"
INSTALL_SH="${LANEX_INSTALL_SCRIPT:-}"

# Baking (.github/workflows/windows-installer.yml, job bake-rootfs) runs this
# exact script in a container and exports the result as the image Setup
# downloads. Keeping that a knob rather than a second script is the whole reason
# provision.sh has no WSL-only assumptions outside wsl_conf(): one file, one code
# path, and Repair on a baked install re-runs the same stages it was built from.
BAKE="${LANEX_BAKE:-0}"
CANCEL_FILE="${LANEX_SETUP_CANCEL_FILE:-/run/lanex/setup.cancel}"

# GDS3D and the LibreLane image are selected components.  They are deliberately
# deferred until the imported appliance has rebooted with systemd and its Docker
# daemon is usable.  Bare and baked images therefore execute the same finalizer.
SKIP_GDS3D=1
UPDATE_MODE="${LANEX_UPDATE_MODE:-0}"
UPDATE_ROLLBACK_ROOT="/var/lib/lanex/update-rollback/${LANEX_INSTALL_ID:-unknown}"

say()  {
    local message="${*//\"/\'}"
    printf '\n@@LANEX:{"schema":1,"event":"phase","message":"%s"}\n== %s\n' "$message" "$*"
}
note() { printf '   %s\n' "$*"; }
warn() { printf '!! %s\n' "$*"; }
# die() text is what the installer's error page shows the user, so it must read
# like a sentence a non-technical person can act on — no shell jargon.
die()  { printf '\nXX provision failed: %s\n' "$*" >&2; exit 1; }

check_cancel() {
    if [ -f "$CANCEL_FILE" ]; then
        printf '\n@@LANEX:cancelled | Setup stopped before the next component.\n' >&2
        exit 130
    fi
}

# Deliberately unstyled output (no ANSI): this streams into an Inno Setup log
# window, which renders escape codes as garbage.

# --------------------------------------------------------------- preflight  --
require_root() {
    [ "$(id -u)" = "0" ] || die "this script must run as root inside the LanEx environment."
}

# One bounded apt front-end for the whole script. Waiting for the real lock owner
# beats deleting locks; fetch timeouts keep a half-working route from hanging.
APT="apt-get -o DPkg::Lock::Timeout=300 -o Acquire::http::Timeout=30 -o Acquire::https::Timeout=30 -o Acquire::Retries=3 -qq"
CURL_FAMILY=""
export DEBIAN_FRONTEND=noninteractive

# --------------------------------------------------------------- 1. network --
network_failure() {
    local rc="$1" endpoint="$2" detail="$3" kind="connection"
    case "$rc" in
        5|6) kind="DNS" ;;
        7) kind="route/connection" ;;
        28) kind="timeout" ;;
        35|51|58|60|77|80|83|90) kind="TLS/certificate" ;;
        22) kind="HTTP" ;;
    esac
    die "${kind} failure while checking ${endpoint}.
   ${detail}
   Check the current VPN, proxy, firewall and resolver settings, then click Retry.
   LanEx does not replace WSL DNS or disable TLS verification."
}

probe_endpoint() {
    local label="$1" url="$2" out rc code detail family family_code family_rc
    out="$(mktemp)" || die "could not create a temporary network diagnostic."
    code="$(curl ${CURL_FAMILY:+$CURL_FAMILY} -sS -L -o /dev/null -w '%{http_code}' --connect-timeout 10 \
        --max-time 25 --retry 2 --retry-delay 2 "$url" 2>"$out")"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        # Never echo proxy environment values or credential-bearing URLs.
        detail="$(tail -n 8 "$out" | sed -E \
            's#(https?://)[^/@[:space:]]+:[^/@[:space:]]+@#\1[redacted]@#g')"
        if [ -z "$CURL_FAMILY" ] && { [ "$rc" -eq 7 ] || [ "$rc" -eq 28 ]; }; then
            for family in -4 -6; do
                family_code="$(curl "$family" -sS -L -o /dev/null -w '%{http_code}' \
                    --connect-timeout 8 --max-time 15 "$url" 2>/dev/null)"
                family_rc=$?
                case "$family_code" in 2??|3??|401|405) ;; *) family_rc=1 ;; esac
                if [ "$family_rc" -eq 0 ]; then
                    CURL_FAMILY="$family"
                    if [ "$family" = "-4" ]; then
                        APT="$APT -o Acquire::ForceIPv4=true"
                        note "${label}: the default/IPv6 path failed, but IPv4 is reachable; using per-command IPv4 fallback."
                    else
                        APT="$APT -o Acquire::ForceIPv6=true"
                        note "${label}: the default/IPv4 path failed, but IPv6 is reachable; using per-command IPv6 fallback."
                    fi
                    rm -f "$out"
                    return 0
                fi
            done
        fi
        rm -f "$out"
        network_failure "$rc" "$label" "$detail"
    fi
    rm -f "$out"
    case "$code" in
        2??|3??|401|405) note "${label} reachable (HTTP ${code})." ;;
        407) network_failure 22 "$label" "The configured proxy requires authentication; a Windows PAC file is not a shell proxy URL." ;;
        429) network_failure 22 "$label" "The service is rate limiting requests; wait for its retry window." ;;
        *) network_failure 22 "$label" "The service returned HTTP ${code}." ;;
    esac
}

package_manager_active() {
    if command -v fuser >/dev/null 2>&1; then
        fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock >/dev/null 2>&1
        return $?
    fi
    pgrep -x apt >/dev/null 2>&1 || pgrep -x apt-get >/dev/null 2>&1 \
        || pgrep -x dpkg >/dev/null 2>&1 || pgrep -x unattended-upgrade >/dev/null 2>&1
}

recover_interrupted_dpkg() {
    local audit="" attempt
    command -v dpkg >/dev/null 2>&1 || return 0
    audit="$(dpkg --audit 2>&1 || true)"
    if [ -z "$audit" ] && ! find /var/lib/dpkg/updates -type f -print -quit 2>/dev/null | grep -q .; then
        return 0
    fi
    warn "a previous package operation left dpkg configuration incomplete."
    for attempt in $(seq 1 60); do
        package_manager_active || break
        [ $((attempt % 6)) -ne 0 ] || note "waiting for the active package manager before recovery ($((attempt * 5))s)..."
        sleep 5
    done
    package_manager_active && die "another package manager still owns the apt/dpkg lock after five minutes.
   Let it finish and click Retry; LanEx never deletes package-manager lock files."
    printf '%s\n' "$audit"
    timeout 300 dpkg --configure -a \
        || die "dpkg recovery did not finish within its bounded attempt.
   Review the package error above, then click Retry; downloaded packages are retained."
    note "completed the interrupted dpkg configuration."
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
    $APT update || warn "apt update failed while preparing curl; using any retained package lists."
    $APT install -y curl ca-certificates && return 0
    die "apt could not install curl and CA certificates in the LanEx environment.
   The apt output above preserves whether this was DNS, route, TLS, proxy, lock or disk failure.
   Check that exact category, then click Retry; package caches are retained."
}

dns_guard() {
    say "Network check"
    ensure_curl
    if [ "${LANEX_PROVISION_DNS:-0}" = "1" ]; then
        warn "LANEX_PROVISION_DNS is deprecated; preserving the current resolver instead of installing public DNS."
    fi
    probe_endpoint "Ubuntu archive" "https://archive.ubuntu.com/ubuntu/dists/noble/InRelease"
    probe_endpoint "Docker repository" "https://download.docker.com/linux/ubuntu/dists/noble/InRelease"
    probe_endpoint "Python package index" "https://pypi.org/simple/"
    probe_endpoint "GHCR registry" "https://ghcr.io/v2/"
    probe_endpoint "PDK release redirects" "https://github.com/fossi-foundation/ciel/releases/latest"
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
    local network="" legacy_dns=0 wsl_temp="" wsl_write_rc=0
    if [ -f /etc/wsl.conf ]; then
        network="$(awk '
            /^\[network\][[:space:]]*$/ { keep=1 }
            /^\[/ && $0 !~ /^\[network\][[:space:]]*$/ { keep=0 }
            keep { print }
        ' /etc/wsl.conf)"
        if grep -q '^# Managed by LanEx Setup' /etc/wsl.conf \
           && printf '%s\n' "$network" | grep -qi 'generateResolvConf[[:space:]]*=[[:space:]]*false' \
           && [ -f /etc/resolv.conf ] \
           && grep -q '^nameserver 8\.8\.8\.8$' /etc/resolv.conf \
           && grep -q '^nameserver 1\.1\.1\.1$' /etc/resolv.conf; then
            legacy_dns=1
            cp -p /etc/wsl.conf /etc/wsl.conf.lanex-legacy-dns.bak \
                || die "could not back up the LanEx-owned legacy WSL DNS configuration."
            cp -p /etc/resolv.conf /etc/resolv.conf.lanex-legacy-dns.bak \
                || die "could not back up the LanEx-owned legacy resolver."
            network=""
        fi
    fi
    wsl_temp="$(mktemp)" || die "could not create a temporary WSL configuration."
    cat > "$wsl_temp" <<EOF
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
${network}
EOF
    wsl_write_rc=$?
    if [ "$wsl_write_rc" -ne 0 ] || ! chmod 0644 "$wsl_temp" || ! mv -f "$wsl_temp" /etc/wsl.conf; then
        rm -f "$wsl_temp"
        die "could not atomically update /etc/wsl.conf; the existing DNS configuration was not changed."
    fi
    if [ "$legacy_dns" = "1" ]; then
        if ! rm -f /etc/resolv.conf \
           || grep -qi 'generateResolvConf[[:space:]]*=[[:space:]]*false' /etc/wsl.conf; then
            cp -p /etc/wsl.conf.lanex-legacy-dns.bak /etc/wsl.conf 2>/dev/null || true
            cp -p /etc/resolv.conf.lanex-legacy-dns.bak /etc/resolv.conf 2>/dev/null || true
            die "could not verify the LanEx legacy DNS migration; the backed-up configuration was restored."
        fi
        note "backed up and retired LanEx's legacy public-DNS override; WSL will regenerate its resolver on the next appliance start."
    elif [ -n "$network" ]; then
        note "preserved the existing WSL network section."
    fi
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
    #
    # mkdir first: /etc/sudoers.d ships with the sudo PACKAGE. base_packages()
    # runs before this function precisely so sudo is present, but creating the
    # directory costs nothing and this write failing silently is exactly the bug
    # that made a minimal-base provision die two minutes later inside apt.
    mkdir -p /etc/sudoers.d
    printf '%s ALL=(ALL) NOPASSWD:ALL\n' "$APP_USER" > /etc/sudoers.d/lanex \
        || die "could not grant the LanEx environment permission to install its own packages."
    chmod 440 /etc/sudoers.d/lanex
    # A malformed sudoers file locks sudo out completely; validate and back out.
    if command -v visudo >/dev/null 2>&1 && ! visudo -cqf /etc/sudoers.d/lanex 2>/dev/null; then
        rm -f /etc/sudoers.d/lanex
        die "could not grant the LanEx environment permission to install its own packages."
    fi
    # Prove it rather than announce it: the failure mode this replaces printed
    # "granted" over a file that was never created.
    runuser -l "$APP_USER" -c 'sudo -n true' >/dev/null 2>&1 \
        || die "the LanEx environment cannot install its own packages (sudo check failed)."
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
        local docker_script
        docker_script="$(mktemp)" || die "could not create a temporary Docker installer file."
        curl ${CURL_FAMILY:+$CURL_FAMILY} -fsSL --connect-timeout 15 --max-time 120 --retry 3 \
            https://get.docker.com -o "$docker_script" \
            && sh "$docker_script"
        local docker_rc=$?
        rm -f "$docker_script"
        [ "$docker_rc" -eq 0 ] \
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

SELECTED_ENGINE="docker"
select_engine() {
    local choices="${LANEX_SETUP_CHOICES:-}"
    if [ -f "$choices" ] && command -v python3 >/dev/null 2>&1; then
        SELECTED_ENGINE="$(python3 -c \
            'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print(d.get("choices", d).get("engine", "docker"))' \
            "$choices")" \
            || die "the saved container-engine choice is unreadable."
    fi
    case "$SELECTED_ENGINE" in
        docker|podman) note "selected container engine: ${SELECTED_ENGINE}." ;;
        none) note "minimal setup selected; no container engine requested." ;;
        *) die "the saved container-engine choice is invalid." ;;
    esac
}

podman_engine() {
    say "Container engine (Podman)"
    if command -v podman >/dev/null 2>&1; then
        note "already installed ($(podman --version 2>/dev/null || echo 'version unknown'))."
        return
    fi
    $APT install -y podman \
        || die "could not install Podman inside the LanEx environment. Click Retry."
    command -v podman >/dev/null 2>&1 \
        || die "Podman installation finished without a usable command. Click Retry."
}

# ----------------------------------------------------------------- 6. lanex --
prepare_update_rollback() {
    [ "$UPDATE_MODE" = "1" ] || return 0
    [ -f "$UPDATE_ROLLBACK_ROOT/app.tar" ] && return 0
    mkdir -p "$UPDATE_ROLLBACK_ROOT" || die "could not stage the app update rollback."
    : > "$UPDATE_ROLLBACK_ROOT/paths"
    local relative
    for relative in \
        "home/${APP_USER}/.local/share/pipx/venvs/lanex" \
        "home/${APP_USER}/.local/pipx/venvs/lanex" \
        "home/${APP_USER}/.lanex/venv" \
        "home/${APP_USER}/.local/bin/lanex" \
        "usr/local/bin/lanex" \
        "etc/lanex/appliance.json"; do
        [ -e "/$relative" ] || [ -L "/$relative" ] || continue
        printf '%s\n' "$relative" >> "$UPDATE_ROLLBACK_ROOT/paths"
    done
    [ -s "$UPDATE_ROLLBACK_ROOT/paths" ] \
        || die "the existing LanEx app environment could not be located for rollback."
    tar -C / -cpf "$UPDATE_ROLLBACK_ROOT/app.tar" -T "$UPDATE_ROLLBACK_ROOT/paths" \
        || die "could not snapshot the existing LanEx app before update."
    note "previous LanEx app environment saved for rollback."
}

rollback_update() {
    [ -s "$UPDATE_ROLLBACK_ROOT/app.tar" ] \
        || die "the previous app rollback archive is missing; data was left untouched."
    rm -rf "/home/${APP_USER}/.local/share/pipx/venvs/lanex" \
        "/home/${APP_USER}/.local/pipx/venvs/lanex" \
        "/home/${APP_USER}/.lanex/venv"
    rm -f "/home/${APP_USER}/.local/bin/lanex" /usr/local/bin/lanex /etc/lanex/appliance.json
    tar -C / -xpf "$UPDATE_ROLLBACK_ROOT/app.tar" \
        || die "the previous LanEx app environment could not be restored from its rollback archive."
    chown -R "$APP_USER:$APP_USER" "/home/${APP_USER}/.local" "/home/${APP_USER}/.lanex" 2>/dev/null || true
    note "previous LanEx app environment restored."
}

commit_update() {
    rm -rf "$UPDATE_ROLLBACK_ROOT"
    note "app update rollback checkpoint cleared after strict readiness."
}

install_lanex() {
    say "LanEx"
    # The repo's own universal installer, in silent mode, as the appliance user.
    # Everything it does — python3/venv, pipx-with-venv-fallback, the
    # /usr/local/bin/lanex symlink, GL drivers, X11 fonts, gtkwave — is already
    # debugged across distros; duplicating any of it here would mean two
    # installers to keep in sync. Deliberately skipped:
    #   LANEX_SKIP_PULL / LANEX_SKIP_GDS3D — explicitly deferred to finalize(),
    #                       after systemd/the selected engine are live. The
    #                       finalizer invokes
    #                       the same LanEx backends and treats selected failures
    #                       as fatal instead of ordinary install warnings.
    # Windows passes the installer script and candidate wheel from the Setup
    # payload. CI uses the same local-source route. A direct universal run may
    # omit both, in which case we download the requested ref to a file, check
    # the transfer and syntax, and only then execute it. Never curl | bash here:
    # a failed fetch must not leave an old install looking like a successful
    # Repair.
    local payload_dir="/var/tmp/lanex-setup-payload"
    local installer="${payload_dir}/install.sh"
    local source="${LANEX_FROM:-github}"
    local constraint=""
    mkdir -p "$payload_dir" || die "could not create the setup payload directory."

    if [ -n "$INSTALL_SH" ]; then
        [ -f "$INSTALL_SH" ] || die "the bundled LanEx installer is missing. Run Setup again."
        cp "$INSTALL_SH" "$installer" || die "could not stage the bundled LanEx installer."
    else
        ensure_curl
        curl ${CURL_FAMILY:+$CURL_FAMILY} -fL --retry 2 --connect-timeout 15 --max-time 120 \
            "https://raw.githubusercontent.com/${REPO}/${REF}/scripts/install.sh" \
            -o "${installer}.download" \
            || die "could not download the LanEx installer for ${REPO}@${REF}."
        mv "${installer}.download" "$installer" \
            || die "could not stage the downloaded LanEx installer."
    fi
    bash -n "$installer" || die "the LanEx installer payload is invalid."
    chmod 0644 "$installer"

    if [ "$source" != "github" ] && [ "$source" != "pypi" ] && [ -f "$source" ]; then
        cp "$source" "$payload_dir/$(basename "$source")" \
            || die "could not stage the LanEx source payload."
        source="$payload_dir/$(basename "$source")"
        chmod 0644 "$source"
    fi
    if [ -n "${LANEX_PIP_CONSTRAINT:-}" ]; then
        [ -f "$LANEX_PIP_CONSTRAINT" ] || die "the bundled dependency lock is missing."
        constraint="$payload_dir/constraints.txt"
        cp "$LANEX_PIP_CONSTRAINT" "$constraint" \
            || die "could not stage the dependency lock."
        chmod 0644 "$constraint"
    fi

    prepare_update_rollback
    runuser -m -u "$APP_USER" -- env HOME="/home/${APP_USER}" USER="$APP_USER" \
        LOGNAME="$APP_USER" PATH="/usr/local/bin:/usr/bin:/bin" \
        LANEX_ASSUME_YES=1 LANEX_SKIP_PULL=1 LANEX_SKIP_GDS3D="$SKIP_GDS3D" \
        LANEX_REPO="$REPO" LANEX_REF="$REF" LANEX_FROM="$source" \
        LANEX_PIP_CONSTRAINT="$constraint" bash "$installer" \
        || { [ "$UPDATE_MODE" = "1" ] && rollback_update; die "the LanEx installer did not finish.
   The log above ends with its own error message.
   Click Retry — this step is safe to repeat."; }
}

write_identity_marker() {
    # Bake artifacts are shared templates and intentionally have no per-install
    # owner. Runtime Setup always supplies all three values together.
    [ "$BAKE" = "1" ] && return 0
    if [ -z "${LANEX_INSTALL_ID:-}" ] || [ -z "${LANEX_MANIFEST_HASH:-}" ] \
       || [ -z "${LANEX_SOURCE_SHA:-}" ]; then
        die "Setup did not provide the appliance identity. Run the same Setup again."
    fi
    printf '%s' "$LANEX_INSTALL_ID" | grep -Eq '^[0-9a-fA-F-]{36}$' \
        || die "Setup provided an invalid install identity."
    printf '%s' "$LANEX_MANIFEST_HASH" | grep -Eq '^[0-9a-fA-F]{64}$' \
        || die "Setup provided an invalid manifest identity."
    printf '%s' "$LANEX_SOURCE_SHA" | grep -Eq '^[0-9a-fA-F]{40}$' \
        || die "Setup provided an invalid source identity."
    mkdir -p /etc/lanex || die "could not create the appliance identity directory."
    umask 077
    printf '{"schema":1,"installId":"%s","manifestHash":"%s","sourceSha":"%s"}\n' \
        "$LANEX_INSTALL_ID" "$LANEX_MANIFEST_HASH" "$LANEX_SOURCE_SHA" \
        > /etc/lanex/appliance.json \
        || die "could not record the appliance identity."
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
    if [ "$SELECTED_ENGINE" != "none" ]; then
        command -v "$SELECTED_ENGINE" >/dev/null 2>&1 \
            || die "The selected container engine is missing after installation. Click Retry."
        note "${SELECTED_ENGINE} present."
    fi
    # A wsl.conf typo would surface as "no systemd" / wrong user on next boot —
    # cheap to catch now.
    grep -q "default *= *${APP_USER}" /etc/wsl.conf 2>/dev/null \
        || warn "/etc/wsl.conf lost its default user — LanEx may start as root."
}

# --------------------------------------------------------------- finalization --
finalize() {
    say "Finalizing selected components"
    local manifest="${LANEX_BUILD_MANIFEST:-}"
    local choices="${LANEX_SETUP_CHOICES:-}"
    [ -f "$manifest" ] || die "the selected-component manifest is missing. Run the same Setup again."
    [ -f "$choices" ] || die "the saved component choices are missing. Run the same Setup again."
    local attempt
    for attempt in $(seq 1 60); do
        check_cancel
        if [ "$(cat /proc/1/comm 2>/dev/null)" = "systemd" ]; then
            note "systemd is ready."
            break
        fi
        if [ "$attempt" -eq 60 ]; then
            die "systemd did not become ready within two minutes after the appliance restart.
   Click Retry; Setup will recheck the same owned environment."
        fi
        if [ $((attempt % 5)) -eq 0 ]; then
            note "waiting for systemd ($((attempt * 2))s)..."
        fi
        sleep 2
    done
    # The appliance user owns its home, Ciel store, image lock and GDS3D build.
    # Running the strict CLI as root would recreate the historical root-owned
    # PDK store failure and would violate the per-user appliance contract.
    runuser -m -u "$APP_USER" -- env HOME="/home/${APP_USER}" USER="$APP_USER" \
        LOGNAME="$APP_USER" PATH="/usr/local/bin:/usr/bin:/bin:/home/${APP_USER}/.local/bin" \
        LANEX_SETUP_CANCEL_FILE="$CANCEL_FILE" \
        lanex --provision-finalize "$manifest" --setup-choices "$choices" \
        || die "one or more selected components did not become ready.
   The readiness report above names every missing requirement. Click Retry."
    say "The LanEx environment is ready."
}

# ------------------------------------------------------------------- 8. bake --
# Only ever runs under LANEX_BAKE=1, i.e. in CI, on a container that is about to
# become `lanex-rootfs-amd64.tar.gz`. Everything removed here is a cache that
# regenerates on demand — nothing a running appliance needs.
#
# It lives in this file rather than in the workflow so the bake and the install
# stay one recipe: a cleanup step that drifts from the script that built the
# image is how a "just a cache" deletion quietly becomes a broken appliance.
bake() {
    [ "$BAKE" = "1" ] || return 0
    say "Preparing the image for export"
    $APT clean
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache /var/cache/debconf/*-old
    rm -rf "/home/${APP_USER}/.cache/pip" 2>/dev/null
    # Truncate rather than delete: some of these are opened by services that
    # expect the path to exist.
    find /var/log -type f -exec truncate -s 0 {} + 2>/dev/null
    # The machine-id must differ per install; an image that ships one gives every
    # user's appliance the same identity. Empty (not absent) is the documented
    # way to ask systemd to generate a fresh one on first boot.
    : > /etc/machine-id
    note "caches, logs and machine-id cleared."
}

# -------------------------------------------------------------------- main  --
main() {
    require_root
    local mode="${1:-base}"
    case "$mode" in
        base|finalize|rollback-update|commit-update) ;;
        *) die "unknown provisioning mode '$mode'." ;;
    esac
    rm -f "$CANCEL_FILE"
    if [ "$mode" = "rollback-update" ]; then rollback_update; return; fi
    if [ "$mode" = "commit-update" ]; then commit_update; return; fi
    if [ "$mode" = "finalize" ]; then
        finalize
        return
    fi
    say "Provisioning the LanEx environment (Ubuntu, isolated)"
    # The bake note only when baking: this line ends up in a log a user may send
    # us, and "bake: 0" on every ordinary install is noise that invites the
    # question "what is a bake?".
    if [ "$BAKE" = "1" ]; then
        note "ref: ${REF}   user: ${APP_USER}   (baking an image)"
    else
        note "ref: ${REF}   user: ${APP_USER}"
    fi
    recover_interrupted_dpkg
    check_cancel
    dns_guard
    check_cancel
    wsl_conf
    check_cancel
    # base_packages BEFORE app_user: the sudo package owns /etc/sudoers.d, and
    # granting the appliance user passwordless sudo means writing into it.
    # Ubuntu's WSL image ships sudo so the order was invisible there; a plain
    # ubuntu:24.04 base (the Phase 2a rootfs bake) does not.
    base_packages
    check_cancel
    app_user
    check_cancel
    select_engine
    check_cancel
    case "$SELECTED_ENGINE" in
        docker) docker_ce ;;
        podman) podman_engine ;;
        none) ;;
    esac
    check_cancel
    install_lanex
    check_cancel
    write_identity_marker
    check_cancel
    verify
    note "DEFERRED(selected-components): image, native support tools, GDS3D and PDKs run after the systemd boot."
    # After verify(), never before: a broken appliance must fail the checks
    # while its logs are still there to read.
    bake
    say "LanEx base provisioning is complete."
    note "Setup will now restart only this environment, wait for systemd, and finalize selections."
}

main "$@"
