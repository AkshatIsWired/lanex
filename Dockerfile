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
# Pin a specific LibreLane release by passing --build-arg LIBRELANE_TAG=<ver>.
ARG LIBRELANE_TAG=latest
FROM ghcr.io/librelane/librelane:${LIBRELANE_TAG}

LABEL org.opencontainers.image.title="LanEx"
LABEL org.opencontainers.image.description="Browser cockpit for the LibreLane RTL-to-GDSII flow."
LABEL org.opencontainers.image.source="https://github.com/AkshatIsWired/lanex"
LABEL org.opencontainers.image.licenses="Apache-2.0"

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
