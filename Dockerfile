FROM python:3.11-slim@sha256:0dd364ba7e10242f07755449e3a3d0e35f9efd987952737b90def6709ab0c5ce
ARG SOURCE_REVISION=unavailable
LABEL org.opencontainers.image.source="https://github.com/karanagg166/automated-apply" \
      org.opencontainers.image.revision=$SOURCE_REVISION
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SOURCE_REVISION=$SOURCE_REVISION
WORKDIR /app
COPY backend/requirements-runtime.txt backend/requirements.lock /app/backend/
RUN python -m pip install --no-cache-dir -r backend/requirements-runtime.txt \
    && groupadd --system agent && useradd --system --gid agent --home-dir /app agent
COPY backend/app /app/backend/app
COPY backend/scripts /app/backend/scripts
COPY supabase/migrations /app/supabase/migrations
USER agent
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=12s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=10)" || exit 1
# Only an explicitly trusted ingress may set forwarded headers; use platform startup
# override with --forwarded-allow-ips=<exact ingress IP> behind TLS termination.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--timeout-keep-alive", "5", "--timeout-graceful-shutdown", "30"]
