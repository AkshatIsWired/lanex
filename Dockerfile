# LanEx — bundled image.
#
# Bases on the official LibreLane image (which already ships the full EDA
# toolchain: OpenROAD, Yosys, Magic, KLayout, Netgen, …) and installs LanEx on
# top. Because every tool is present inside the image, LanEx runs flows
# NATIVELY in-process — no Docker-in-Docker, no separate toolchain install.
#
# Build:   docker build -t lanex:latest .
# Run:     docker run --rm -p 8765:8765 -v "$PWD/work:/work" lanex:latest
# Then open http://localhost:8765
#
# LibreLane is PINNED to the version LanEx is tested against (3.0.4) so upstream
# releases can never silently break the bundle. Override deliberately with
# --build-arg LIBRELANE_TAG=<ver> (and bump pyproject's `librelane==` to match).
#
# BASE_IMAGE lets you build from YOUR OWN MIRROR of the LibreLane image instead of
# upstream, so the bundle keeps building even if LibreLane deletes an old tag. For a
# byte-reproducible build, pass the immutable @sha256: digest recorded in
# `base-image.lock` (written by scripts/mirror-base.sh):
#   scripts/mirror-base.sh           # copy upstream -> ghcr.io/<you>/lanex-base + lock the digest
#   docker build --build-arg BASE_IMAGE="$(awk -F= '/^digest=/{print $2}' base-image.lock)" -t lanex .
# Easiest of all: `VERSION=0.1.0 scripts/release.sh` does mirror+build+push+archive in one shot.
ARG LIBRELANE_TAG=3.0.4
ARG BASE_IMAGE=ghcr.io/librelane/librelane:${LIBRELANE_TAG}
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="LanEx"
LABEL org.opencontainers.image.description="Browser cockpit for the LibreLane RTL-to-GDSII flow."
LABEL org.opencontainers.image.source="https://github.com/AkshatIsWired/lanex"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# Extra tools LanEx drives, baked in so the image is self-contained. The official
# LibreLane base is NIX-built and already ships iverilog, klayout, magic, openroad,
# yosys and netgen — the only web-flow tool missing is graphviz (`dot`, for Yosys
# netlist diagrams), which we add through Nix (the base has no apt; the /nix store is
# what the toolchain lives in). `--impure` is required because `nix profile` rewrites
# root's existing user-environment, which pure evaluation refuses to read.
#
# Two paths so the Dockerfile also works on a hypothetical apt base:
#   • apt base  → apt-get graphviz (+ legacy fonts, build deps) and build GDS3D.
#   • nix base  → `nix profile install --impure nixpkgs#graphviz` (the real case).
# Both guarded with `|| echo` so a tool that fails to install never breaks the build.
#
# GDS3D (a 3D GL desktop viewer) is intentionally NOT baked into the Nix image: it is
# not in nixpkgs, building it pulls a ~1.5 GB X11/OpenGL toolchain for a viewer that
# needs X11 forwarding to display anyway, and the web cockpit never uses it. It stays
# an on-demand install via the Tools tab when someone forwards a display.
USER root
RUN set -e; \
    if command -v apt-get >/dev/null 2>&1; then \
      apt-get update; \
      DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        iverilog graphviz xfonts-base \
        git build-essential libx11-dev libxmu-dev libxi-dev \
        libgl1-mesa-dev libglu1-mesa-dev freeglut3-dev; \
      git clone --depth 1 https://github.com/trilomix/GDS3D /opt/GDS3D; \
      ( cd /opt/GDS3D/linux && make && \
        for b in GDS3D gds3d; do [ -f "$b" ] && cp "$b" /usr/local/bin/gds3d && break; done ) && \
        chmod +x /usr/local/bin/gds3d || echo "skip: GDS3D build failed (install later via Tools tab)"; \
      rm -rf /var/lib/apt/lists/*; \
    elif command -v nix >/dev/null 2>&1; then \
      nix --extra-experimental-features 'nix-command flakes' \
        profile install --impure nixpkgs#graphviz \
        || echo "warn: nix graphviz install failed (netlist diagrams unavailable)"; \
    else \
      echo "skip: no apt or nix on base image; install graphviz via the Tools tab"; \
    fi

# Put LanEx on the image WITHOUT pip. The official LibreLane image is Nix-built: there
# is no `pip` on PATH and the /nix store is read-only, so `pip install` is impossible
# (and pointless). LanEx needs no install anyway — its only runtime dependency is
# librelane (already in the image) plus the Python standard library — so we run it
# straight from source on PYTHONPATH. The in-image `python3` is the Nix env that already
# imports librelane, so `python3 -m lanex` uses the correct interpreter + toolchain.
WORKDIR /opt/lanex
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY lanex ./lanex
ENV PYTHONPATH=/opt/lanex
# Every EDA tool is native inside this image, so start the UI on the "local" engine
# (no nested container) — this is what stops the "no container engine found" banner.
ENV LANEX_RUN_MODE=local

# Designs live on a mounted volume so runs survive container restarts.
VOLUME ["/work"]
WORKDIR /work

EXPOSE 8765

# Clear any inherited entrypoint and launch the cockpit bound to all interfaces
# inside the container (the published port is what the host actually exposes).
ENTRYPOINT []
CMD ["python3", "-m", "lanex", "--host", "0.0.0.0", "--port", "8765", "--no-browser", "--allow-remote"]
