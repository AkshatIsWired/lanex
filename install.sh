#!/usr/bin/env sh
# LanEx one-line installer (Docker-based — brings the full toolchain).
#
#   curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/install.sh | sh
#
# Installs a `lanex` command that runs the bundled image (LibreLane + OpenROAD,
# Yosys, Magic, KLayout, Netgen, iverilog, graphviz — all inside the container).
# If the published image isn't reachable, it builds the image locally from source.
set -eu

IMAGE="${LANEX_IMAGE:-ghcr.io/akshatiswired/lanex:latest}"
REPO_URL="${LANEX_REPO:-https://github.com/AkshatIsWired/lanex.git}"
PORT="${LANEX_PORT:-8765}"
BIN="${LANEX_BIN:-$HOME/.local/bin}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install it first: https://docs.docker.com/get-docker/" >&2
  exit 1
fi

if docker pull "$IMAGE" >/dev/null 2>&1; then
  RUN_IMAGE="$IMAGE"
  echo "✓ Pulled $IMAGE"
else
  echo "Published image unavailable — building locally from source (one-time)…"
  command -v git >/dev/null 2>&1 || { echo "git required for local build" >&2; exit 1; }
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  git clone --depth 1 "$REPO_URL" "$TMP/lanex"
  docker build -t lanex:local "$TMP/lanex"
  RUN_IMAGE="lanex:local"
fi

mkdir -p "$BIN"
cat > "$BIN/lanex" <<EOF
#!/usr/bin/env sh
# Run the LanEx bundled cockpit. Current directory is mounted at /work.
exec docker run --rm -it -p ${PORT}:8765 -v "\$PWD:/work" ${RUN_IMAGE} "\$@"
EOF
chmod +x "$BIN/lanex"

echo ""
echo "✓ LanEx installed."
case ":$PATH:" in
  *":$BIN:"*) : ;;
  *) echo "  ⚠ Add $BIN to your PATH, e.g.:  export PATH=\"$BIN:\$PATH\"" ;;
esac
echo "  Run:   lanex"
echo "  Open:  http://localhost:${PORT}"
