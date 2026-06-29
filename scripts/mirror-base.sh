#!/usr/bin/env sh
# Mirror the upstream LibreLane image into YOUR OWN registry, and record the exact
# digest so future builds are byte-for-byte reproducible.
#
# Why: the LanEx bundle builds FROM the LibreLane image. If LibreLane ever deletes
# an old tag, an upstream-based build breaks. Mirror it once into your namespace and
# build LanEx from your copy — you no longer depend on their hosting. We also resolve
# the immutable digest (a tag can move; a @sha256: digest cannot) and write it to
# `base-image.lock`, so a rebuild months later uses the IDENTICAL base.
#
# Prereqs: `docker login ghcr.io` (a PAT with write:packages), Docker running.
#
# Env:
#   LIBRELANE_TAG  upstream tag to mirror        (default 3.0.4)
#   SRC_IMAGE      override the full source ref  (default ghcr.io/librelane/librelane:$TAG)
#   DST_IMAGE      your mirror ref               (default ghcr.io/akshatiswired/lanex-base:$TAG)
#   LOCK_FILE      where to record the pin       (default ./base-image.lock)
set -eu

TAG="${LIBRELANE_TAG:-3.0.4}"
SRC="${SRC_IMAGE:-ghcr.io/librelane/librelane:$TAG}"
DST="${DST_IMAGE:-ghcr.io/akshatiswired/lanex-base:$TAG}"
LOCK="${LOCK_FILE:-$(cd "$(dirname "$0")/.." && pwd)/base-image.lock}"

# Resolve the immutable digest of a pushed image ref → "repo@sha256:...".
# Tries the registry (buildx imagetools, multi-arch aware), then local RepoDigests.
resolve_digest() {
  ref="$1"; repo="${ref%:*}"; dg=""
  dg="$(docker buildx imagetools inspect "$ref" --format '{{.Manifest.Digest}}' 2>/dev/null || true)"
  if [ -z "$dg" ]; then
    dg="$(docker inspect --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}' "$ref" 2>/dev/null | sed 's/.*@//')"
  fi
  [ -n "$dg" ] && printf '%s@%s\n' "$repo" "$dg"
}

echo "Mirroring:"
echo "  from  $SRC"
echo "  to    $DST"

# Single-arch mirror (simple, works everywhere). For a multi-arch image prefer:
#   docker buildx imagetools create --tag "$DST" "$SRC"
docker pull "$SRC"
docker tag  "$SRC" "$DST"
docker push "$DST"

PINNED="$(resolve_digest "$DST" || true)"
if [ -z "$PINNED" ]; then
  echo "⚠ could not resolve the mirror digest — falling back to the tag (less reproducible)" >&2
  PINNED="$DST"
fi

cat > "$LOCK" <<EOF
# LanEx base-image lock — the exact image the published bundle is built FROM.
# Written by scripts/mirror-base.sh. Reproducible rebuild:
#   docker build --build-arg BASE_IMAGE="\$(awk -F= '/^digest=/{print \$2}' base-image.lock)" -t lanex .
# scripts/release.sh reads this automatically.
librelane_tag=$TAG
mirror=$DST
digest=$PINNED
mirrored_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

echo ""
echo "✓ Mirrored. Pin recorded in: $LOCK"
echo "    base = $PINNED"
echo "  Build LanEx from your own, digest-pinned base with:"
echo "    docker build --build-arg BASE_IMAGE=$PINNED -t lanex:latest ."
echo "  (or just run scripts/release.sh, which reads base-image.lock for you)"
