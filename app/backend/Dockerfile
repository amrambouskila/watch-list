# syntax=docker/dockerfile:1

# FastAPI + openpyxl over the workbook library.
#
# What this image deliberately does NOT carry: the `claude` CLI and Playwright's Chromium. The chat
# feature shells out to both and needs a per-machine login besides, so in here it answers HTTP 503
# through the app's own CLINotFoundError mapping (src/tv_watchlist/api/errors.py), with the same
# message the launcher's preflight prints. Every other endpoint - the whole watch-order app - works
# normally. Run ./run_tv.sh or run_tv.bat on the host if you want chat.

# ==============================================================================================
# Build: uv resolves and installs the locked dependency set.
# ==============================================================================================
# python:3.13-slim, never alpine: musl has no manylinux wheels, so pydantic-core and friends would
# be compiled from source.
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON=/usr/local/bin/python3 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/srv/app/backend/.venv

# The depth of this path is load-bearing, and the runtime stage below keeps it identical.
# src/tv_watchlist/config.py computes its field defaults at import time from
# Path(__file__).resolve().parents[4], so the package has to sit at least five levels below the
# filesystem root or the module raises IndexError before the app ever starts.
# /srv/app/backend/src/tv_watchlist reproduces the repo's own nesting and keeps that expression
# valid; the env vars in the runtime stage then override every path it produces anyway.
WORKDIR /srv/app/backend

# Dependencies first, so editing a source file does not re-resolve the lockfile. The cache mount
# keeps uv's download cache out of the layer - without it the image carries a second copy of every
# wheel.
#
# The find: claude-agent-sdk's Linux wheel bundles a 340 MB `claude` binary under _bundled/ (the
# Windows wheel does not, which is why app/docs/chat-feature-design.md records the package as
# CLI-free). Deleting it in this same RUN is what keeps it out of the layer, and it is what makes
# chat fail cleanly here: with the binary present a chat turn reaches it and dies at authentication
# instead of never starting.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
    && find /srv/app/backend/.venv -type f -path '*/claude_agent_sdk/_bundled/claude*' -delete

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ==============================================================================================
# Runtime: the virtualenv and the source, and nothing that built them.
# ==============================================================================================
FROM python:3.13-slim

# Base-image packages carry their own CVEs; picking up the distribution's current security
# updates is the only thing in this image's gift to do about them. `trivy --ignore-unfixed` in
# CI then fails only on findings a rebuild or a version bump can actually clear.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# pip is not used at runtime - the virtualenv arrives fully built - and it drags its own vendored
# copies of msgpack and setuptools along, each of which trivy reports as a HIGH. Nothing imports
# them; they are just cargo.
RUN rm -rf /usr/local/lib/python3.13/site-packages/pip \
           /usr/local/lib/python3.13/site-packages/pip-*.dist-info \
           /usr/local/lib/python3.13/site-packages/pkg_resources \
           /usr/local/bin/pip /usr/local/bin/pip3 /usr/local/bin/pip3.13

# Same path as the builder: the virtualenv's shebangs and pyvenv.cfg are absolute.
WORKDIR /srv/app/backend
COPY --from=builder /srv/app/backend /srv/app/backend

ENV PATH="/srv/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Every path the app reads or writes is handed in explicitly. TV_LIBRARY_DIR is the important one:
# without it the app looks for workbooks at a location derived from where its own source file
# landed in the image, which is not where the library is mounted.
ENV TV_LIBRARY_DIR=/library \
    TV_HEROES_DIR=/library/app/heroes \
    TV_BACKUP_DIR=/library/app/.backups \
    TV_BACKEND_PORT=8284 \
    TV_FRONTEND_PORT=5284

# Runs unprivileged. Only /library is written to - that is the library itself - and nothing under
# /srv is ever written at runtime.
RUN useradd --create-home --uid 10001 watcher \
    && mkdir -p /library \
    && chown watcher:watcher /library
USER watcher

EXPOSE 8284

CMD ["uvicorn", "tv_watchlist.main:app", "--host", "0.0.0.0", "--port", "8284"]
