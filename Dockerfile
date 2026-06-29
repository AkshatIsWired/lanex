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
ARG LIBRELANE_TAG=3.0.4
FROM ghcr.io/librelane/librelane:${LIBRELANE_TAG}

LABEL org.opencontainers.image.title="LanEx"
LABEL org.opencontainers.image.description="Browser cockpit for the LibreLane RTL-to-GDSII flow."
LABEL org.opencontainers.image.source="https://github.com/AkshatIsWired/lanex"
LABEL org.opencontainers.image.licenses="Apache-2.0"

# Extra tools LanEx drives that the base image may not ship:
#   iverilog  — RTL simulation engine (RTL IDE)
#   graphviz  — `dot`, renders Yosys netlist diagrams
#   xfonts-base — legacy X11 "fixed" fonts (GDS3D and other X tools NULL-deref without them)
# Best-effort: skip silently on a non-apt base. Desktop GL viewers (GDS3D / KLayout
# GUI / OpenROAD GUI) additionally need X11 forwarding into the container at run time
# (-e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix); the web-served features need none of that.
USER root
RUN (command -v apt-get >/dev/null 2>&1 && \
     apt-get update && \
     DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
       iverilog graphviz xfonts-base && \
     rm -rf /var/lib/apt/lists/*) || \
    echo "skip: non-apt base image; install iverilog/graphviz via the Tools tab"

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
