#!/usr/bin/env bash
# selftest.sh — assert that a provisioned LanEx appliance is actually usable.
#
# Runs INSIDE the appliance, as root, after provision.sh. Three callers, one
# implementation on purpose:
#
#   * .github/workflows/windows-installer.yml, job `provision-e2e` — the only
#     proof CI has that provisioning works at all (it cannot run WSL).
#   * the same workflow's `bake-rootfs` job, before exporting the tarball, so a
#     broken appliance can never become a published release asset.
#   * a maintainer, by hand: `wsl -d lanex -u root -- bash selftest.sh`.
#
# provision.sh's own verify() is the subset of this that a user-facing installer
# can act on (it feeds Setup's Retry dialog). This file is the maintainer's
# version: it checks everything, keeps going after a failure so one run reports
# every problem, and says which ones failed.
#
# Deliberately NOT checked: that the Docker daemon is running. provision.sh
# never starts it — there is no systemd in a container and none yet in a
# freshly imported distro. The daemon coming up on the first real boot is a WSL
# behaviour, verified by hand against windows/README.md's matrix.
set -u

APP_USER="${LANEX_USER:-lanex}"
ENGINE="docker"
if [ -f "${LANEX_SETUP_CHOICES:-}" ] && command -v python3 >/dev/null 2>&1; then
    ENGINE="$(python3 -c \
        'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print(d.get("choices", d).get("engine", "docker"))' \
        "$LANEX_SETUP_CHOICES")" || ENGINE="invalid"
fi
pass=0
fail=0

ok()   { printf 'PASS  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf 'FAIL  %s\n' "$1"; fail=$((fail+1)); }
check() {  # check <label> <shell command...>
    local label="$1"; shift
    if eval "$*" >/dev/null 2>&1; then ok "$label"; else bad "$label"; fi
}

printf '== LanEx appliance self-test (user: %s)\n' "$APP_USER"

check "appliance user exists"          "id -u '$APP_USER'"
check "/etc/sudoers.d/lanex is valid"  "visudo -cqf /etc/sudoers.d/lanex"
# The bug this catches: the sudoers write silently failing, which made LanEx's
# own installer die minutes later inside apt with an unrelated message.
check "passwordless sudo works"        "runuser -l '$APP_USER' -c 'sudo -n true'"
check "wsl.conf: systemd = true"       "grep -Eq '^systemd *= *true' /etc/wsl.conf"
check "wsl.conf: default = $APP_USER"  "grep -Eq '^default *= *$APP_USER' /etc/wsl.conf"
check "wsl.conf: interop enabled"      "grep -Eq '^enabled *= *true' /etc/wsl.conf"
case "$ENGINE" in
    docker)
        check "docker is installed"            "command -v docker"
        check "$APP_USER is in the docker group" "id -nG '$APP_USER' | grep -qw docker"
        ;;
    podman) check "podman is installed" "command -v podman" ;;
    *) bad "saved container-engine choice is valid" ;;
esac
# Both preconditions the appliance's "you never need a terminal" promise rests
# on. The home dir is where the launcher's `cd ~` puts the server and where new
# designs land; apt-get is what the Tools tab installs a build toolchain with
# (GDS3D). Without either, the cockpit hands the user a shell command instead.
check "$APP_USER can write in its home" \
    "runuser -l '$APP_USER' -c 'touch ~/.lanex-selftest && rm -f ~/.lanex-selftest'"
check "apt-get is available for tool installs" "command -v apt-get"
check "lanex --help"                   "runuser -l '$APP_USER' -c 'lanex --help'"
check "lanex --version"                "runuser -l '$APP_USER' -c 'lanex --version'"
locked_versions() {
    # The single-quoted script is intentionally expanded by the target login
    # shell, not this root self-test process.
    # shellcheck disable=SC2016
    runuser -l "$APP_USER" -c '
        launcher=$(readlink -f "$(command -v lanex)")
        py=$(sed -n "1s/^#!//p" "$launcher")
        "$py" -c '\''import importlib.metadata as m; assert m.version("librelane") == "3.0.4"; assert m.version("ciel") == "2.6.1"'\''
    '
}
if locked_versions >/dev/null 2>&1; then
    ok "locked librelane 3.0.4 + ciel 2.6.1"
else
    bad "locked librelane 3.0.4 + ciel 2.6.1"
fi
if [ -n "${LANEX_BUILD_MANIFEST:-}" ] || [ -n "${LANEX_SETUP_CHOICES:-}" ]; then
    if [ -f "${LANEX_BUILD_MANIFEST:-}" ] && [ -f "${LANEX_SETUP_CHOICES:-}" ] &&
       runuser -u "$APP_USER" -- env HOME="/home/${APP_USER}" USER="$APP_USER" \
         LOGNAME="$APP_USER" PATH="/usr/local/bin:/usr/bin:/bin:/home/${APP_USER}/.local/bin" \
         lanex --setup-check "$LANEX_BUILD_MANIFEST" --setup-choices "$LANEX_SETUP_CHOICES"; then
        ok "all selected components pass strict readiness"
    else
        bad "all selected components pass strict readiness"
    fi
else
    printf 'SKIP  selected components (base-image test; finalization requires systemd/Docker)\n'
fi
# The distro's own first-run screen must never appear: `wsl --import` normally
# skips OOBE, but the appliance promise is "no prompt, ever".
if [ -f /etc/wsl-distribution.conf ]; then
    check "distro OOBE disabled"       "! grep -Eq '^[[:space:]]*command[[:space:]]*=' /etc/wsl-distribution.conf"
fi

printf -- '-- lanex --version: %s\n' \
    "$(runuser -l "$APP_USER" -c 'lanex --version' 2>&1 | tail -1)"
printf '== %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
