#!/usr/bin/env sh
# Mirror the upstream LibreLane image into YOUR OWN registry.
#
# Why: the LanEx bundle builds FROM the LibreLane image. If LibreLane ever deletes
# an old tag, an upstream-based build breaks. Mirror it once into your namespace and
# build LanEx from your copy — you no longer depend on their hosting.
#
# Prereqs: `docker login ghcr.io` (a PAT with write:packages), Docker running.
set -eu

TAG="${LIBRELANE_TAG:-3.0.4}"
SRC="${SRC_IMAGE:-ghcr.io/librelane/librelane:$TAG}"
DST="${DST_IMAGE:-ghcr.io/akshatiswired/lanex-base:$TAG}"

echo "Mirroring:"
echo "  from  $SRC"
echo "  to    $DST"

# Single-arch mirror (simple, works everywhere). For a multi-arch image prefer:
#   docker buildx imagetools create --tag "$DST" "$SRC"
docker pull "$SRC"
docker tag  "$SRC" "$DST"
docker push "$DST"

echo ""
echo "✓ Mirrored. Build LanEx from your own base with:"
echo "    docker build --build-arg BASE_IMAGE=$DST -t lanex:latest ."
echo "  (or set BASE_IMAGE in docker-compose.yml's build args)"
