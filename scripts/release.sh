#!/usr/bin/env sh
# scripts/release.sh — ONE command to make LanEx independent and operational.
#
# Run on a networked machine with Docker + `docker login ghcr.io`. Implements the
# 3-layer independence model end-to-end so the bundle survives whatever upstream
# does with LibreLane:
#
#   Layer 1  build = FREEZE           bake librelane + every EDA tool into one image;
#                                     once built it needs none of LibreLane's servers.
#   Layer 2  store where YOU control  mirror the base into YOUR ghcr (rebuild-proof),
#                                     then push lanex:<ver> + lanex:latest to YOUR ghcr
#                                     so users `docker pull` it anytime, forever.
#   Layer 3  cold tarball             docker save | gzip → restorable with ZERO registry,
#                                     attached to a GitHub Release (the last-resort backup).
#
# Usage:
#   VERSION=0.1.0 ./scripts/release.sh
#   VERSION=0.1.0 OWNER=akshatiswired LIBRELANE_TAG=3.0.4 ./scripts/release.sh
#   VERSION=0.1.0 ./scripts/release.sh --dry-run     # print the plan, change nothing
#
# Flags:
#   --dry-run        print every command, touch nothing
#   --mirror         force a fresh base mirror + digest pin (refresh base-image.lock)
#   --no-mirror      build straight from the upstream tag (skip Layer 2 base mirror)
#   --no-archive     skip the cold tarball (Layer 3)
#   --no-gh-release  don't create the GitHub Release / upload the tarball
#
# Default base selection (Layer 2): if base-image.lock exists, build from its pinned
# digest; else mirror once. --mirror forces a refresh; --no-mirror ignores the lock.
set -eu

# ---- config (override via env) ------------------------------------------------
VERSION="${VERSION:-}"
OWNER="${OWNER:-akshatiswired}"
REGISTRY="${REGISTRY:-ghcr.io}"
LIBRELANE_TAG="${LIBRELANE_TAG:-3.0.4}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${IMAGE:-$REGISTRY/$OWNER/lanex}"
UPSTREAM_BASE="$REGISTRY/librelane/librelane:$LIBRELANE_TAG"
LOCK="$ROOT/base-image.lock"
OUTDIR="${OUTDIR:-$ROOT/dist}"

DRY=0; MIRROR_MODE=auto; ARCHIVE=1; GH_RELEASE=1
for a in "$@"; do
  case "$a" in
    --dry-run)       DRY=1 ;;
    --mirror)        MIRROR_MODE=force ;;
    --no-mirror)     MIRROR_MODE=off ;;
    --no-archive)    ARCHIVE=0 ;;
    --no-gh-release) GH_RELEASE=0 ;;
    *) echo "unknown flag: $a" >&2; exit 2 ;;
  esac
done

die() { echo "✗ $*" >&2; exit 1; }
run() { echo "+ $*"; [ "$DRY" = 1 ] || sh -c "$*"; }

# ---- preflight ----------------------------------------------------------------
[ -n "$VERSION" ] || die "set VERSION=x.y.z (e.g. VERSION=0.1.0 ./scripts/release.sh)"
command -v docker >/dev/null 2>&1 || die "docker not found"
if [ "$DRY" = 0 ]; then
  docker info >/dev/null 2>&1 || die "docker daemon not running"
fi

echo "LanEx release  v$VERSION   →  $IMAGE:$VERSION (+ :latest)"
echo "Base tag       librelane:$LIBRELANE_TAG    mirror mode: $MIRROR_MODE${DRY:+   [DRY-RUN]}"
echo

lock_digest() { [ -f "$LOCK" ] && awk -F= '/^digest=/{print $2}' "$LOCK" || true; }

# ---- Layer 2a: own the base (rebuild-independence) ----------------------------
case "$MIRROR_MODE" in
  off)
    BUILD_BASE="$UPSTREAM_BASE"
    echo "Layer 2a  SKIP mirror — building from upstream tag $UPSTREAM_BASE"
    ;;
  force)
    echo "Layer 2a  mirror base (forced) → $REGISTRY/$OWNER/lanex-base:$LIBRELANE_TAG"
    run "LIBRELANE_TAG=$LIBRELANE_TAG DST_IMAGE=$REGISTRY/$OWNER/lanex-base:$LIBRELANE_TAG LOCK_FILE=$LOCK sh $ROOT/scripts/mirror-base.sh"
    BUILD_BASE="$(lock_digest)"; [ -n "$BUILD_BASE" ] || [ "$DRY" = 1 ] || die "mirror produced no digest"
    [ -n "$BUILD_BASE" ] || BUILD_BASE="$REGISTRY/$OWNER/lanex-base@sha256:<resolved-at-run>"
    ;;
  auto)
    BUILD_BASE="$(lock_digest)"
    if [ -n "$BUILD_BASE" ]; then
      echo "Layer 2a  reuse pinned base from base-image.lock: $BUILD_BASE"
    else
      echo "Layer 2a  no base-image.lock → mirror once → $REGISTRY/$OWNER/lanex-base:$LIBRELANE_TAG"
      run "LIBRELANE_TAG=$LIBRELANE_TAG DST_IMAGE=$REGISTRY/$OWNER/lanex-base:$LIBRELANE_TAG LOCK_FILE=$LOCK sh $ROOT/scripts/mirror-base.sh"
      BUILD_BASE="$(lock_digest)"
      [ -n "$BUILD_BASE" ] || BUILD_BASE="$REGISTRY/$OWNER/lanex-base@sha256:<resolved-at-run>"
    fi
    ;;
esac

# ---- Layer 1: build = freeze --------------------------------------------------
echo
echo "Layer 1   build (freezes librelane + iverilog + graphviz + gds3d into the image)"
run "docker build --build-arg BASE_IMAGE='$BUILD_BASE' -t '$IMAGE:$VERSION' -t '$IMAGE:latest' '$ROOT'"

# ---- Layer 2b: publish (users pull anytime) -----------------------------------
echo
echo "Layer 2b  push to YOUR registry (users: docker pull $IMAGE)"
run "docker push '$IMAGE:$VERSION'"
run "docker push '$IMAGE:latest'"

# ---- Layer 3: cold tarball ----------------------------------------------------
TARBALL="$OUTDIR/lanex-$VERSION.tar.gz"
if [ "$ARCHIVE" = 1 ]; then
  echo
  echo "Layer 3   cold backup → $TARBALL (restore: gunzip -c … | docker load)"
  run "mkdir -p '$OUTDIR'"
  run "docker save '$IMAGE:$VERSION' | gzip > '$TARBALL'"
fi

# ---- GitHub Release (optional, needs gh) --------------------------------------
if [ "$GH_RELEASE" = 1 ]; then
  echo
  if command -v gh >/dev/null 2>&1; then
    NOTES="LanEx $VERSION — bundled image \`$IMAGE:$VERSION\` (LibreLane $LIBRELANE_TAG + full toolchain).
Pull: \`docker pull $IMAGE:$VERSION\`   ·   Offline restore: \`gunzip -c lanex-$VERSION.tar.gz | docker load\`."
    if [ "$ARCHIVE" = 1 ]; then
      run "gh release create 'v$VERSION' '$TARBALL' --title 'LanEx v$VERSION' --notes \"$NOTES\""
    else
      run "gh release create 'v$VERSION' --title 'LanEx v$VERSION' --notes \"$NOTES\""
    fi
  else
    echo "GitHub Release  SKIP — gh CLI not found. Create it manually and attach $TARBALL."
  fi
fi

# ---- what only you can do (deliberate, security-gated) ------------------------
cat <<EOF

────────────────────────────────────────────────────────────────────────────
✓ Done${DRY:+ (DRY-RUN — nothing changed)}.

ONE manual step remains (deliberate — keep it private until you decide):
  • Make the ghcr PACKAGE public so anyone can pull without auth:
      GitHub → your profile → Packages → lanex → Package settings → Change visibility
    (This is separate from the repo's visibility. The repo stays private.)

After that, end users run, on any machine, forever:
    curl -fsSL https://raw.githubusercontent.com/$OWNER/lanex/main/install.sh | sh
    lanex
Independence: the published image + base mirror + cold tarball are all under YOUR
control; deleting anything upstream cannot break a pull, a rebuild, or a restore.
────────────────────────────────────────────────────────────────────────────
EOF
