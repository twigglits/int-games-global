#!/usr/bin/env python3
"""Export the movie embeddings from pgvector in the format Embedding Atlas reads.

Embedding Atlas draws one point per row. It can compute the two-dimensional
projection itself, but doing so would make it load a sentence-transformers model
at start-up. The vectors already exist in the database, so this script projects
them once with UMAP and hands Atlas a table that carries the ``x`` and ``y``
columns. Atlas then starts in seconds and needs no model at all.

Output: one Parquet file with

* ``id`` and ``title`` — identity of the point,
* the metadata columns used for colouring and filtering, ``major_genre`` first,
* ``text`` — the augmented text that produced the vector, shown on hover,
* ``x`` and ``y`` — the UMAP projection.

Usage::

    python scripts/export_embeddings_atlas.py --output /data/movies_atlas.parquet

Every option also has an environment variable, so the container can be
configured entirely through Docker Compose.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg
from psycopg.rows import dict_row

#: Columns pulled from the database. `major_genre` is first among the metadata
#: columns so that it is the obvious choice in the Atlas colour picker.
QUERY = """
SELECT
    id::text          AS id,
    title,
    major_genre,
    creative_type,
    source,
    mpaa_rating,
    director,
    distributor,
    release_year,
    decade,
    running_time_min,
    production_budget,
    worldwide_gross,
    imdb_rating,
    imdb_votes,
    rt_rating,
    budget_tier,
    blockbuster_flag,
    rating_score_delta,
    augmented_text    AS text,
    embedding::text   AS embedding
FROM movies
WHERE embedding IS NOT NULL
ORDER BY id
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(os.getenv("ATLAS_OUTPUT", "/data/movies_atlas.parquet")),
        help="Path of the Parquet file to write.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=int(os.getenv("ATLAS_SAMPLE_SIZE", "0")),
        help="Draw at most this many rows. 0 means every row.",
    )
    parser.add_argument(
        "--umap-neighbors",
        type=int,
        default=int(os.getenv("ATLAS_UMAP_NEIGHBORS", "15")),
        help="UMAP n_neighbors. Higher values favour global structure.",
    )
    parser.add_argument(
        "--umap-min-dist",
        type=float,
        default=float(os.getenv("ATLAS_UMAP_MIN_DIST", "0.1")),
        help="UMAP min_dist. Lower values pack a cluster more tightly.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=int(os.getenv("ATLAS_SEED", "42")),
        help="Random seed, so that the same data always draws the same picture.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=os.getenv("ATLAS_FORCE", "false").lower() == "true",
        help="Rebuild the file even when it already exists and is newer than the data.",
    )
    return parser.parse_args(argv)


def build_dsn() -> str:
    """Build the libpq connection string from the environment."""
    user = os.getenv("POSTGRES_USER", "movies")
    password = os.getenv("POSTGRES_PASSWORD", "movies")
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = os.getenv("POSTGRES_PORT", "5432")
    database = os.getenv("POSTGRES_DB", "movies")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def wait_for_rows(dsn: str, timeout_seconds: float = 600.0) -> None:
    """Block until the movies table holds at least one embedded row.

    The pipeline writes those rows. In Docker Compose the dependency graph
    already orders the two, and this loop covers a manual run.
    """
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn, connect_timeout=5) as connection:
                row = connection.execute("SELECT COUNT(embedding) FROM movies").fetchone()
                if row is not None and int(row[0]) > 0:
                    print(f"[atlas] found {int(row[0])} embedded movies", flush=True)
                    return
                print("[atlas] waiting for the pipeline to load embeddings...", flush=True)
        except psycopg.Error as error:
            print(f"[atlas] waiting for the database: {error}", flush=True)
        time.sleep(5)
    raise SystemExit("[atlas] no embedded rows appeared before the timeout expired")


def fetch(dsn: str, sample_size: int, seed: int) -> tuple[pd.DataFrame, np.ndarray]:
    """Read the rows and parse the vectors into a float matrix."""
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        rows: list[dict[str, Any]] = connection.execute(QUERY).fetchall()

    if not rows:
        raise SystemExit("[atlas] the movies table holds no embedded rows")

    frame = pd.DataFrame.from_records(rows)
    if 0 < sample_size < len(frame):
        frame = frame.sample(n=sample_size, random_state=seed).reset_index(drop=True)
        print(f"[atlas] sampled {sample_size} of the available rows", flush=True)

    # pgvector renders a vector as '[0.1,0.2,...]'.
    vectors = np.asarray(
        [np.fromstring(text.strip("[]"), sep=",", dtype=np.float32) for text in frame["embedding"]],
        dtype=np.float32,
    )
    frame = frame.drop(columns=["embedding"])
    print(f"[atlas] read {len(frame)} rows of {vectors.shape[1]} dimensions", flush=True)
    return frame, vectors


def project(vectors: np.ndarray, *, neighbors: int, min_dist: float, seed: int) -> np.ndarray:
    """Reduce the vectors to two dimensions with UMAP.

    Cosine is the metric, because it is the metric the search uses. Projecting
    under a different metric would draw a picture that disagrees with the
    ranking the API returns.
    """
    from umap import UMAP  # imported here: it is slow to import and only needed now

    started = time.monotonic()
    reducer = UMAP(
        n_components=2,
        n_neighbors=min(neighbors, max(2, len(vectors) - 1)),
        min_dist=min_dist,
        metric="cosine",
        random_state=seed,
        verbose=False,
    )
    coordinates = reducer.fit_transform(vectors)
    print(f"[atlas] projected in {time.monotonic() - started:.1f}s", flush=True)
    return np.asarray(coordinates, dtype=np.float32)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    dsn = build_dsn()

    if args.output.exists() and not args.force:
        print(f"[atlas] {args.output} already exists; pass --force to rebuild it", flush=True)
        return 0

    wait_for_rows(dsn)
    frame, vectors = fetch(dsn, args.sample_size, args.seed)
    coordinates = project(
        vectors,
        neighbors=args.umap_neighbors,
        min_dist=args.umap_min_dist,
        seed=args.seed,
    )

    frame["x"] = coordinates[:, 0]
    frame["y"] = coordinates[:, 1]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(args.output, index=False)
    print(
        f"[atlas] wrote {len(frame)} rows and {len(frame.columns)} columns to {args.output}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
