#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Export the embeddings, then serve them.
#
# The export waits for the pipeline to finish loading, so this container can be
# started at the same time as everything else.
# ---------------------------------------------------------------------------
set -euo pipefail

OUTPUT="${ATLAS_OUTPUT:-/data/movies_atlas.parquet}"
PORT="${ATLAS_PORT:-7000}"

echo "[atlas] exporting embeddings to ${OUTPUT}"
python /app/export_embeddings_atlas.py --output "${OUTPUT}"

echo "[atlas] starting Embedding Atlas on port ${PORT}"
exec embedding-atlas "${OUTPUT}" \
  --text text \
  --x x \
  --y y \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --no-auto-port \
  --duckdb server \
  --disable-projection
