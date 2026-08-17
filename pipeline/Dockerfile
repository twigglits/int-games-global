# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Data pipeline image.
#
# The image carries no model. Embeddings come from the `embeddings` service over
# HTTP, so this image stays small and a run starts immediately.
#
# The Vega movies dataset is downloaded once at build time and baked in. A
# pipeline run therefore needs no internet access and always reads the same
# bytes. `pipeline.dataset` falls back to `vega_datasets` if the file is absent.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src

# A virtual environment keeps the runtime layer free of build tooling.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir .

# Bake the dataset. `vega_datasets` supplies the canonical URL, so the file
# matches exactly what `data.movies()` would return at runtime.
RUN mkdir -p /build/data && \
    python -c "\
import urllib.request; from vega_datasets import data; \
urllib.request.urlretrieve(data.movies.url, '/build/data/movies.json'); \
print('dataset cached from', data.movies.url)"


# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src

# uid 1000 matches the default first user on a Linux host, so files written to a
# bind-mounted log directory stay readable without a chown.
#
# The upgrade patches OS packages the base image shipped. See the same step in
# mcp-server/Dockerfile for why it is here rather than left to a newer base.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* \
    && (getent group app >/dev/null || groupadd --gid 1000 app) \
    && (getent passwd app >/dev/null || useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash app)

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /build/data /app/data
COPY --chown=app:app src ./src
COPY --chown=app:app tests ./tests
COPY --chown=app:app pyproject.toml ./

RUN mkdir -p /app/logs && chown -R app:app /app/logs
USER app

# A pipeline container is a batch job: it runs, prints its report, and exits.
ENTRYPOINT ["python", "/app/src/main.py"]
