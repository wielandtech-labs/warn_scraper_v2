# --- stage 1: build the React SPA ---
# Produces /build/dist which is copied into the python image at /app/warn_v2/api/static
# so FastAPI (StaticFiles mount, see warn_v2/api/__init__.py) can serve it.
FROM node:20-alpine AS frontend
WORKDIR /build

COPY frontend/package.json frontend/package-lock.json* ./
# `npm ci` requires a lockfile; on first build (no lockfile committed yet)
# fall back to `npm install` which both installs and generates one.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY frontend/ ./
RUN npm run build


# --- stage 2: python app ---
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
RUN uv sync --frozen --no-dev --extra browser \
    && uv run playwright install chromium --with-deps

COPY warn_v2 ./warn_v2
COPY alembic.ini ./alembic.ini

# Copy the built SPA bundle from stage 1 into the package directory so
# warn_v2.api.__init__ can StaticFiles-mount it.
COPY --from=frontend /build/dist /app/warn_v2/api/static

ENTRYPOINT ["uv", "run", "warn-v2"]
CMD ["--help"]
