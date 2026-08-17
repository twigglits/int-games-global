# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Python MCP server image.
#
# Like the pipeline, this image carries no model. It calls the `embeddings`
# service over HTTP for the one short vector each search needs.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir .


# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src

# curl is used by the container health check.
# The .NET images already ship a non-root `app` user at uid 1000, the Python
# images do not. Creating it only when it is absent keeps one recipe for both.
#
# `apt-get upgrade` patches the OS packages the base image shipped. Trivy found
# CVE-2026-53615 across nine util-linux packages here, and pulling a fresh
# `python:3.12-slim` did not clear it — upstream had not rebuilt yet. Waiting for
# a base image to catch up is not a plan, so the packages are upgraded at build
# time. `./scripts/security_scan.sh images` is what proves it worked.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/* \
    && (getent group app >/dev/null || groupadd --gid 1000 app) \
    && (getent passwd app >/dev/null || useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash app)

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app src ./src
COPY --chown=app:app tests ./tests
COPY --chown=app:app pyproject.toml ./

USER app
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=10 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["python", "/app/src/server/main.py"]
