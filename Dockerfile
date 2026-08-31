# syntax=docker/dockerfile:1.7

# ---------- Stage 1: build the React/Vite SPA ----------
FROM node:26-bookworm-slim@sha256:3fe807a03a4436e7bc76b7e84e6861899cd75c9028ae99bc00581940141ae150 AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build   # -> /build/dist

# ---------- Stage 2: install Python deps with uv ----------
FROM python:3.12-slim-bookworm@sha256:76d4b7b6305788c6b4c6a19d6a22a3921bf802e9af4d5e1e5bd771208dba74bf AS pydeps
COPY --from=ghcr.io/astral-sh/uv:0.11@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=backend/pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=backend/uv.lock,target=uv.lock \
    uv sync --locked --no-install-project --no-dev
COPY backend/ ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# ---------- Stage 3: minimal runtime ----------
FROM python:3.12-slim-bookworm@sha256:76d4b7b6305788c6b4c6a19d6a22a3921bf802e9af4d5e1e5bd771208dba74bf AS runtime
# Links the GHCR package to its source repo (GitHub reads org.opencontainers.image.source).
LABEL org.opencontainers.image.source="https://github.com/VladoPortos/tracegoblins" \
      org.opencontainers.image.title="Tracegoblins" \
      org.opencontainers.image.description="Self-hosted AWX/Ansible log analyzer + team collaboration platform"
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl git \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 999 app \
 && useradd  --system --gid 999 --uid 999 --create-home app
WORKDIR /app
COPY --from=pydeps  --chown=app:app /app /app
COPY --from=frontend --chown=app:app /build/dist /app/frontend/dist
COPY --chown=app:app docker-entrypoint.sh /app/docker-entrypoint.sh
# Create the appdata mount point owned by the non-root app user BEFORE `USER app`, so the
# named `appdata` volume (projects git clones + uploads) inherits app:app ownership on first
# mount. Without this the volume is root-owned and the app (uid 999) gets PermissionError on
# the first upload/clone under /app/data.
RUN chmod +x /app/docker-entrypoint.sh \
 && mkdir -p /app/data \
 && chown app:app /app/data
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_STATIC_DIR=/app/frontend/dist
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn_worker.UvicornWorker", \
     "--workers", "1", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "--timeout", "60", "--graceful-timeout", "30"]
