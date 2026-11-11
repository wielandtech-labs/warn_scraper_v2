# --- stage 1: build the React SPA ---
# Produces /build/dist which is copied into the python image at /app/warn_v2/api/static
# so FastAPI (StaticFiles mount, see warn_v2/api/__init__.py) can serve it.
FROM node:20-alpine AS frontend
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
# Cache npm downloads in a BuildKit cache mount so they persist across runs on the
# shared persistent buildkitd. Only re-downloads when lockfile changes.
RUN --mount=type=cache,target=/root/.npm \
    if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./
RUN npm run build


# --- stage 2: python app ---
FROM python:3.12-slim AS base

# MALLOC_ARENA_MAX: glibc gives each thread its own heap arena by default,
# and the API's threadpool fragments them until RSS reaches the pod limit
# (see warn_v2/api/timeline_warm.py); two arenas cap that.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MALLOC_ARENA_MAX=2 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Cache apt package downloads across builds.
# tesseract-ocr + poppler-utils power the OCR fallback in warn_v2/pdf_extract for
# scanned-image WARN PDFs that carry no text layer (e.g. WV/HI).
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
        curl \
        tesseract-ocr \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 warn \
    && useradd -u 1000 -g warn -m -s /bin/bash warn

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app
# One flag list for both syncs below: uv sync is exact, so a mismatch would
# silently uninstall an extra in the second sync.
ARG UV_SYNC_FLAGS="--frozen --no-dev --extra browser --extra ocr"
COPY pyproject.toml uv.lock* ./
# Dependencies only: this layer stays cached while only source files change.
# Cache uv's download cache so wheels are not re-fetched either.
# playwright install is a normal layer (browsers live in the image, not a mount).
# The venv is handed to the runtime user in the SAME layer that creates it:
# derived images (warn-enrich-dnb) `uv pip install` into /app/.venv as warn,
# and a separate `chown -R` layer both duplicated the ~1GB venv and, on
# 2026-11-10, came out of a cached build as a 4kB no-op that left /app
# root-owned (#475).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync $UV_SYNC_FLAGS --no-install-project \
    && .venv/bin/playwright install chromium --with-deps \
    && chmod -R 755 /ms-playwright \
    && chown -R warn:warn /app

# README.md is project metadata (hatchling), so it goes with the source and a
# README edit doesn't rebuild the dependency layer.
COPY --chown=warn:warn README.md ./README.md
COPY --chown=warn:warn warn_v2 ./warn_v2
COPY --chown=warn:warn alembic.ini ./alembic.ini

# Copy the built SPA bundle from stage 1 into the package directory so
# warn_v2.api.__init__ can StaticFiles-mount it.
COPY --chown=warn:warn --from=frontend /build/dist /app/warn_v2/api/static

USER warn

# Install the project itself now that its source is here (deps are already in
# place, so this is quick). Before, the one sync ran before warn_v2/ was
# copied in, so the installed project was stale and every `uv run` rebuilt and
# reinstalled it into .venv at container start. That failed with "Permission
# denied" in the migrate hook once the venv wasn't writable (#475).
# The cache lives under /tmp: buildkit creates a missing mount target's parent
# dirs as root, so a target under /home/warn/.cache is not writable by warn.
RUN --mount=type=cache,target=/tmp/uv-cache,uid=1000,gid=1000 \
    UV_CACHE_DIR=/tmp/uv-cache uv sync $UV_SYNC_FLAGS

# Never sync or rebuild at container start: the image is complete as built.
ENV UV_NO_SYNC=1

ENTRYPOINT ["uv", "run", "warn-v2"]
CMD ["--help"]
