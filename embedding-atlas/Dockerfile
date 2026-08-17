# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Embedding Atlas image (bonus).
#
# Build context is the repository root, because the image needs
# scripts/export_embeddings_atlas.py.
#
# The image installs the CPU build of PyTorch explicitly, before
# embedding-atlas. embedding-atlas depends on sentence-transformers, which pulls
# PyTorch, and the default wheel carries the CUDA runtime. Pinning the CPU wheel
# first removes roughly two gigabytes from the image, and nothing here uses a GPU.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NUMBA_CACHE_DIR=/tmp/numba

RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        --extra-index-url https://pypi.org/simple \
        "torch==2.9.1"

RUN pip install --no-cache-dir \
        "embedding-atlas==0.22.0" \
        "psycopg[binary]==3.3.4" \
        "umap-learn==0.5.12" \
        "pyarrow==25.0.1"

RUN (getent group app >/dev/null || groupadd --gid 1000 app) \
    && (getent passwd app >/dev/null || useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash app)

WORKDIR /app
COPY --chown=app:app scripts/export_embeddings_atlas.py ./export_embeddings_atlas.py
COPY --chown=app:app embedding-atlas/entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh && mkdir -p /data && chown -R app:app /data

USER app
EXPOSE 7000

HEALTHCHECK --interval=15s --timeout=5s --start-period=300s --retries=20 \
    CMD curl -fsS http://localhost:7000/ >/dev/null || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
