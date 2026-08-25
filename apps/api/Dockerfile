# The API image.
#
# Two stages: uv resolves and installs into a virtualenv, the runtime copies
# that venv and nothing else. The build toolchain never reaches the final image.
#
# CPU-only, and that is load-bearing rather than a preference. `uv sync
# --frozen` installs exactly what the lockfile pins, and the lockfile has no
# torch, no transformers, no nvidia-*. Embeddings come from fastembed, which is
# ONNX on CPU. If a future dependency drags CUDA in, the image jumps by ~2GB and
# the image-size guard in CI fails before it ever ships.

# --- build -------------------------------------------------------------------

FROM python:3.12-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, in their own layer: they change far less often than the
# source, so editing a Python file does not re-resolve the whole tree.
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

COPY apps/api/src ./src
COPY apps/api/alembic.ini ./alembic.ini
COPY apps/api/alembic ./alembic

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# --- runtime -----------------------------------------------------------------

FROM python:3.12-slim-bookworm AS runtime

# curl is for the healthcheck; libxml2/libxslt back lxml, which the scrapers use.
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 batanat \
    # The fastembed cache path has to exist here, not just in ENV below. Docker
    # creates a volume mountpoint that is absent from the image as root, and the
    # runtime user then cannot write to it — the model downloads on every single
    # request and never caches. A fresh volume inherits this ownership instead.
    && mkdir -p /home/batanat/.cache/fastembed \
    && chown -R batanat:batanat /home/batanat/.cache

WORKDIR /app

COPY --from=build --chown=batanat:batanat /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    # fastembed caches its ONNX model here on first use (~100MB). Give it a
    # writable path owned by the runtime user, and mount a volume over it in
    # production so a restart does not re-download.
    FASTEMBED_CACHE_PATH=/home/batanat/.cache/fastembed \
    # Belt and braces for the CPU-only rule: even if something CUDA-aware were
    # installed, it would find no devices.
    CUDA_VISIBLE_DEVICES=""

USER batanat

EXPOSE 8000

# `/api/health` answers 503 with a full report when a dependency is down, which
# is what we want a probe to see — the container is up but not serving. Shell
# form on purpose: the scheduler runs this same image on a different port, and
# an exec-form probe would hardcode 8000 and mark it permanently unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS "http://localhost:${API_PORT:-8000}/api/health" || exit 1

# Migrations are deliberately NOT run here. With more than one replica they
# would race; the compose file and the CD pipeline run them as a separate
# one-shot step before the API starts.
#
# API_HOST/API_PORT are read here rather than hardcoded. They were literal
# flags, which meant the values in the compose files were silently ignored:
# the scheduler runs this image with API_PORT=8001 but bound 8000 anyway, hit
# the API already sitting there, and crash-looped from the first deploy. It
# also forced 0.0.0.0 in production, where host networking then published the
# API straight onto the public interface past nginx and TLS.
#
# `exec` so uvicorn is PID 1 and receives SIGTERM on `docker stop`.
CMD ["sh", "-c", "exec uvicorn batanat_api.main:app --host \"${API_HOST:-0.0.0.0}\" --port \"${API_PORT:-8000}\""]
