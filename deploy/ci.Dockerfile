# Disposable lint/type-check/test image for `docker compose --profile ci run --rm ci`.
# The repository is bind-mounted read-only at /src; nothing is baked in but dependencies.
FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce
COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /uvx /usr/local/bin/
ENV UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    RUFF_NO_CACHE=true MYPY_CACHE_DIR=/tmp/mypy-cache
COPY backend/requirements.txt backend/requirements-runtime.txt backend/requirements-browser.txt /deps/backend/
RUN uv pip install --system -r /deps/backend/requirements-browser.txt ruff==0.17.1 mypy==1.18.2 \
    && groupadd --system ci && useradd --system --gid ci --home-dir /tmp ci
USER ci
WORKDIR /src
