# Idle Hours — multi-stage OCI image.
#
# Stage 1 builds wheels for the project + runtime deps; stage 2 installs them
# into a slim runtime image. This split keeps the final image lean (no build
# toolchain, no pip cache) so the appliance pulls fewer bytes over LAN/WAN
# and a CVE in setuptools / a build header doesn't leak into runtime.
#
# Targets ARM64 first (the appliance — Raspberry Pi 4/5 / Zero 2 W) but stays
# multi-arch via Docker buildx so x86 dev hosts can run `idle-hours --once`
# locally for smoke tests. The Pi-only `[pi]` extra (gpiozero / inky) is
# *not* installed by default — that's a Pi-runtime concern; the appliance
# either runs the bare-metal install (bootstrap_pi_inky.sh) or installs the
# extra at container-run time. The base container can render PNGs and serve
# the curator UI without any GPIO bindings.
#
# Build:
#   docker buildx build --platform linux/arm64,linux/amd64 -t idle-hours:2.5 .
#
# Run (one-shot render):
#   docker run --rm -v "$PWD/output:/app/output" idle-hours:2.5 idle-hours render --time 14:30
#
# Run (clock loop, no display):
#   docker run --rm -p 8080:8080 -v idle-hours-state:/state idle-hours:2.5 \
#       idle-hours run --buttons-off --skip-preflight \
#                      --web-bind 0.0.0.0:8080 \
#                      --state-path /state/state.json \
#                      --history-path /state/history.jsonl \
#                      --telemetry-path /state/telemetry.jsonl \
#                      --pidfile /state/run_clock.pid

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
# The entire package (Python modules + bundled assets/fonts/web) lives under
# ``idle_hours/``; setuptools picks it up via packages.find + package-data.
COPY pyproject.toml README.md ./
COPY idle_hours/ ./idle_hours/

# Build the Idle Hours wheel + every runtime dep into /wheels. Using
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
# appliance (StateDirectory=idle-hours → uid:idlehours). ``--no-create-home``
# because the state path is provided via volume mount, not via $HOME.
RUN groupadd --system --gid 1001 idlehours \
    && useradd --system --uid 1001 --gid 1001 --no-create-home --shell /usr/sbin/nologin idlehours

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels idle-hours \
    && rm -rf /wheels

# As of the v2.x package restructure, ``assets/``, ``fonts/``, and ``web/``
# are shipped as ``package-data`` inside the ``idle_hours`` wheel itself.
# That means a plain ``pip install`` is now sufficient — no separate COPY
# of the static trees into /app is needed (and would just create a second
# copy at a different path than ``BASE_DIR`` resolves to). Operators who
# want to swap the corpus / fonts / web UI without rebuilding the image
# can volume-mount over the installed copies, e.g.
#   docker run -v /my/assets:/usr/local/lib/python3.12/site-packages/idle_hours/assets ...

# Default state directory; mount a volume here for persistence across
# container restarts. The runtime user owns it so the loop can write
# state.json / history.jsonl / telemetry.jsonl without root.
RUN mkdir -p /state /app/output && chown -R idlehours:idlehours /state /app/output /app

USER idlehours

# Default port for the curator web UI; bind 127.0.0.1 outside the container
# unless you've also set --web-token (the loop refuses to start with a
# tokenless 0.0.0.0 bind).
EXPOSE 8080

# Default command renders a single fixed-time frame so an unconfigured
# `docker run` produces something visible (the PNG lands at
# /app/output/current.png). Override with `idle-hours run …` for the loop.
CMD ["idle-hours", "render", "--time", "14:30", "--mode", "production"]
