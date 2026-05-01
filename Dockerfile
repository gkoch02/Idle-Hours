# LitClock — multi-stage OCI image.
#
# Stage 1 builds wheels for the project + runtime deps; stage 2 installs them
# into a slim runtime image. This split keeps the final image lean (no build
# toolchain, no pip cache) so the appliance pulls fewer bytes over LAN/WAN
# and a CVE in setuptools / a build header doesn't leak into runtime.
#
# Targets ARM64 first (the appliance — Raspberry Pi 4/5 / Zero 2 W) but stays
# multi-arch via Docker buildx so x86 dev hosts can run `litclock --once`
# locally for smoke tests. The Pi-only `[pi]` extra (gpiozero / inky) is
# *not* installed by default — that's a Pi-runtime concern; the appliance
# either runs the bare-metal install (bootstrap_pi_inky.sh) or installs the
# extra at container-run time. The base container can render PNGs and serve
# the curator UI without any GPIO bindings.
#
# Build:
#   docker buildx build --platform linux/arm64,linux/amd64 -t litclock:2.0 .
#
# Run (one-shot render):
#   docker run --rm -v "$PWD/output:/app/output" litclock:2.0 litclock render --time 14:30
#
# Run (clock loop, no display):
#   docker run --rm -p 8080:8080 -v litclock-state:/state litclock:2.0 \
#       litclock run --buttons-off --skip-preflight \
#                    --web-bind 0.0.0.0:8080 \
#                    --state-path /state/state.json \
#                    --history-path /state/history.jsonl \
#                    --telemetry-path /state/telemetry.jsonl \
#                    --pidfile /state/run_clock.pid

# ---- Stage 1: build wheels --------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Build dependencies for Pillow's C extensions on ARM64. ``slim`` images don't
# ship libjpeg / zlib headers — Pillow's wheel index has prebuilt wheels for
# common arches, but pin the compile path on the off-chance pip falls back.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libjpeg-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only the minimum needed to resolve dependencies and produce wheels.
# COPY-then-pip is split so a code change doesn't bust the wheel-build cache.
COPY pyproject.toml README.md ./
COPY *.py ./
COPY web/ ./web/
COPY assets/ ./assets/
COPY fonts/ ./fonts/

# Build the LitClock wheel + every runtime dep into /wheels. Using
# `pip wheel` (not `pip install`) so stage 2 can `pip install` in offline
# mode against a known-good wheel set.
RUN pip wheel --no-cache-dir --wheel-dir=/wheels .

# ---- Stage 2: runtime --------------------------------------------------------
FROM python:3.12-slim AS runtime

# System fonts for the renderer fallback chain (Noto Serif, DejaVu, Liberation).
# The bundled `fonts/` directory ships repo-local copies of every theme face,
# but `load_font` falls through to system fonts when a bundled face is missing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fonts-noto-core \
        fonts-dejavu-core \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user matching the systemd-unit conventions on the
# appliance (StateDirectory=litclock → uid:litclock). ``--no-create-home``
# because the state path is provided via volume mount, not via $HOME.
RUN groupadd --system --gid 1001 litclock \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin litclock

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels litclock \
    && rm -rf /wheels

# Bring in the static assets that the wheel doesn't carry. The wheel
# installs the Python modules and the `litclock` console script; the
# corpus / fonts / web assets ship as volume-mountable defaults next to
# the source tree so an operator can override them without rebuilding.
# Mount over /app/assets and /app/fonts at runtime to swap in a custom
# corpus or font bundle.
COPY --from=builder /build/assets /app/assets
COPY --from=builder /build/fonts /app/fonts
COPY --from=builder /build/web /app/web

# Default state directory; mount a volume here for persistence across
# container restarts. The runtime user owns it so the loop can write
# state.json / history.jsonl / telemetry.jsonl without root.
RUN mkdir -p /state /app/output && chown -R litclock:litclock /state /app/output /app

USER litclock

# Default port for the curator web UI; bind 127.0.0.1 outside the container
# unless you've also set --web-token (the loop refuses to start with a
# tokenless 0.0.0.0 bind).
EXPOSE 8080

# Default command runs `--once` so an unconfigured `docker run` produces
# something visible (the rendered PNG lands at /app/output/current.png).
# Override with `litclock run …` for the loop.
CMD ["litclock", "render", "--time", "14:30", "--mode", "production"]
