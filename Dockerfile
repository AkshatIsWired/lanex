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
# upstream, so the bundle keeps building even if LibreLane deletes an old tag:
#   scripts/mirror-base.sh           # copy upstream -> ghcr.io/<you>/lanex-base
#   docker build --build-arg BASE_IMAGE=ghcr.io/akshatiswired/lanex-base:3.0.4 -t lanex .
ARG LIBRELANE_TAG=3.0.4
ARG BASE_IMAGE=ghcr.io/librelane/librelane:${LIBRELANE_TAG}
FROM ${BASE_IMAGE}

LABEL org.opencontainers.image.title="LanEx"
LABEL org.opencontainers.image.description="Browser cockpit for the LibreLane RTL-to-GDSII flow."
LABEL org.opencontainers.image.source="https://github.com/AkshatIsWired/lanex"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# Extra tools LanEx drives, baked in so the image is self-contained:
#   iverilog  — RTL simulation engine (RTL IDE)
#   graphviz  — `dot`, renders Yosys netlist diagrams
#   xfonts-base — legacy X11 "fixed" fonts (GDS3D NULL-derefs without them)
#   + GDS3D build deps (git/g++/X11/OpenGL headers), then GDS3D itself from source.
# Best-effort: the whole block is guarded so a non-apt base still produces a working
# image (those tools just stay installable later via the in-app Tools tab). Desktop
# GL viewers (GDS3D / KLayout / OpenROAD GUI) additionally need X11 forwarding at run
# time (-e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix); web-served features need none.
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
    else \
      echo "skip: non-apt base image; install iverilog/graphviz/gds3d via the Tools tab"; \
    fi

# Install LanEx on top of the LibreLane image.
#   --no-deps: the base image already provides librelane (LanEx's only declared
#   dependency); everything else LanEx needs is the Python standard library, so
#   this neither re-resolves nor changes the in-image LibreLane version.
WORKDIR /opt/lanex
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY lanex ./lanex
RUN pip install --no-cache-dir --no-deps .

# Designs live on a mounted volume so runs survive container restarts.
VOLUME ["/work"]
WORKDIR /work

EXPOSE 8765

# Clear any inherited entrypoint and launch the cockpit bound to all interfaces
# inside the container (the published port is what the host actually exposes).
ENTRYPOINT []
CMD ["lanex", "--host", "0.0.0.0", "--port", "8765", "--no-browser", "--allow-remote"]
