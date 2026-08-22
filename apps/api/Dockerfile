# CPU-only by policy. Never switch this to a CUDA base image.
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so a source change does not invalidate the layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY src ./src
COPY scripts ./scripts
RUN uv sync --frozen --no-dev

# Fail the build if a GPU package ever resolves into the tree. Inlined rather
# than copied from scripts/ because the build context is apps/api.
RUN VIRTUAL_ENV=/app/.venv uv pip list --format=json \
    | grep -Eiq '"name": *"(nvidia-|triton|cuda|torch)' \
    && { echo "ERROR: GPU/CUDA packages resolved. This project is CPU-only."; exit 1; } \
    || echo "OK: CPU-only dependency tree."


FROM python:3.12-slim AS runtime

# Runtime guard: even if something GPU-aware sneaks in, it sees no devices.
ENV CUDA_VISIBLE_DEVICES="" \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN useradd --create-home --uid 10001 batanat
WORKDIR /app

COPY --from=builder --chown=batanat:batanat /app/.venv /app/.venv
COPY --from=builder --chown=batanat:batanat /app/src /app/src

USER batanat
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=3).status==200 else 1)"

CMD ["uvicorn", "batanat_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
