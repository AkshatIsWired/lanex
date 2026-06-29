#!/usr/bin/env sh
# Cold-backup a built image to a tarball — the ultimate insurance.
#
# `docker load` restores it with ZERO registry dependency, so even if both
# LibreLane's image AND your ghcr mirror vanished, this file still rebuilds the
# whole environment. Attach it to a GitHub Release or keep it on a drive.
set -eu

IMAGE="${1:-lanex:latest}"
OUT="${2:-lanex-$(echo "$IMAGE" | tr '/:' '__').tar.gz}"

echo "Saving $IMAGE -> $OUT"
docker save "$IMAGE" | gzip > "$OUT"
ls -lh "$OUT"
echo ""
echo "✓ Restore on any machine with:"
echo "    gunzip -c $OUT | docker load"
