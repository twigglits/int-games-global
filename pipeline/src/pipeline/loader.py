"""Stage 6 — load into pgvector.

Idempotency lives here, and it has three parts:

1. ``source_key`` is a natural key, so a second run collides with the first row
   instead of inserting beside it.
2. ``ON CONFLICT ... DO UPDATE ... WHERE`` only writes when something actually
   differs, so a repeat run leaves ``updated_at`` alone.
3. A row keeps its stored vector when its text has not changed, so a repeat run
   makes no call to the embedding service at all.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from pipeline.logging import get_logger
from pipeline.report import LoadReport

logger = get_logger(__name__)

#: Column order used by the INSERT. It must match :data:`INSERT_SQL`.
INSERT_COLUMNS: tuple[str, ...] = (
    "source_key",
    "title",
    "release_date",
    "release_year",
    "major_genre",
    "creative_type",
    "source",
    "mpaa_rating",
    "director",
    "distributor",
    "running_time_min",
    "production_budget",
    "us_gross",
    "worldwide_gross",
    "us_dvd_sales",
    "imdb_rating",
    "imdb_votes",
    "rt_rating",
    "decade",
    "budget_tier",
    "rating_score_delta",
    "blockbuster_flag",
    "profit_ratio",
    "imputed_fields",
    "augmented_text",
    "content_hash",
    "embedding",
    "embedding_model",
    "pipeline_version",
)

#: Columns that must be integers in PostgreSQL. Pandas holds them as floats so
#: that a missing value can be NaN, so they are converted on the way out.
INTEGER_COLUMNS = frozenset(
    {
        "release_year",
        "running_time_min",
        "production_budget",
        "us_gross",
        "worldwide_gross",
        "us_dvd_sales",
        "imdb_votes",
        "rt_rating",
        "decade",
    }
)

_UPDATE_ASSIGNMENTS = ",\n            ".join(
    # `embedding` is special: a NULL in the incoming row means "the text did not
    # change, keep the vector that is already stored".
    f"{column} = EXCLUDED.{column}"
    if column not in {"embedding", "source_key"}
    else f"{column} = COALESCE(EXCLUDED.{column}, movies.{column})"
    for column in INSERT_COLUMNS
    if column != "source_key"
)

#: One placeholder group per row. `embedding` is the only cast that matters.
_PLACEHOLDER_GROUP = (
    "(" + ", ".join("%s::vector" if c == "embedding" else "%s" for c in INSERT_COLUMNS) + ")"
)

#: The statement, with the VALUES list left open. The WHERE clause on the
#: DO UPDATE branch is what makes a repeat run a no-op: PostgreSQL skips the
#: write, so `updated_at` keeps its original value and RETURNING yields nothing
#: for that row.
_INSERT_TEMPLATE = f"""
INSERT INTO movies ({", ".join(INSERT_COLUMNS)})
VALUES {{values}}
ON CONFLICT (source_key) DO UPDATE SET
            {_UPDATE_ASSIGNMENTS},
            updated_at = NOW()
    WHERE (movies.content_hash IS DISTINCT FROM EXCLUDED.content_hash)
       OR (movies.embedding IS NULL AND EXCLUDED.embedding IS NOT NULL)
       OR (movies.embedding_model IS DISTINCT FROM EXCLUDED.embedding_model)
       OR (movies.pipeline_version IS DISTINCT FROM EXCLUDED.pipeline_version)
RETURNING source_key, (xmax = 0) AS inserted
"""


def insert_sql(row_count: int) -> str:
    """Return the multi-row upsert statement for ``row_count`` rows."""
    if row_count < 1:
        raise ValueError("row_count must be at least 1")
    return _INSERT_TEMPLATE.format(values=", ".join([_PLACEHOLDER_GROUP] * row_count))


@dataclass(frozen=True)
class ExistingRow:
    """The parts of a stored row that decide what work a new run must do."""

    content_hash: str
    augmented_text: str
    embedding_model: str | None
    has_embedding: bool


def vector_literal(values: list[float]) -> str:
    """Render a vector as the text form pgvector accepts.

    Nine significant digits round-trip a 32-bit float exactly, which is the
    precision pgvector stores.
    """
    return "[" + ",".join(f"{value:.9g}" for value in values) + "]"


def select_rows_needing_embedding(
    frame: pd.DataFrame,
    existing: dict[str, ExistingRow],
    *,
    embedding_model: str,
    force: bool = False,
) -> pd.Series:
    """Decide which rows must be sent to the embedding service.

    A stored vector is reused when the row is already present, its text is
    identical, the same model produced it, and the vector is really there.
    Anything else is re-embedded.

    Args:
        frame: Augmented dataframe carrying ``source_key`` and ``augmented_text``.
        existing: Current table state from :meth:`MovieLoader.fetch_existing`.
        embedding_model: Identifier of the model that will be used now.
        force: Re-embed every row regardless of the stored state.

    Returns:
        A boolean Series aligned to ``frame``.
    """

    def needed(row: pd.Series) -> bool:
        if force:
            return True
        previous = existing.get(str(row["source_key"]))
        if previous is None:
            return True
        return (
            not previous.has_embedding
            or previous.augmented_text != row["augmented_text"]
            or previous.embedding_model != embedding_model
        )

    if frame.empty:
        return pd.Series([], dtype=bool)
    return frame.apply(needed, axis=1)


def _scalar(value: Any, column: str) -> Any:
    """Convert one pandas or numpy value to something psycopg can send."""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date() if not pd.isna(value) else None
    if isinstance(value, date):
        return value
    if isinstance(value, (bool,)):
        return bool(value)
    if hasattr(value, "item"):  # numpy scalar
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value):
            return None
        return int(value) if column in INTEGER_COLUMNS else float(value)
    if isinstance(value, int) and column in INTEGER_COLUMNS:
        return int(value)
    return value


def row_params(row: pd.Series) -> list[Any]:
    """Build the parameter list for one row, in :data:`INSERT_COLUMNS` order."""
    return [_scalar(row.get(column), column) for column in INSERT_COLUMNS]


class MovieLoader:
    """Reads the current table state and writes a new pipeline run into it."""

    def __init__(self, dsn: str, *, chunk_size: int = 250) -> None:
        """
        Args:
            dsn: libpq connection string.
            chunk_size: Rows per INSERT statement. Each row uses 29 parameters,
                so 250 rows stays far below the PostgreSQL parameter limit.
        """
        self._dsn = dsn
        self._chunk_size = chunk_size

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self._dsn, row_factory=dict_row)

    def wait_until_ready(self, timeout_seconds: float = 120.0, interval: float = 2.0) -> None:
        """Block until the database accepts a connection."""
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with self._connect() as conn:
                    conn.execute("SELECT 1")
                logger.info("database.ready")
                return
            except psycopg.Error as exc:
                last_error = exc
                time.sleep(interval)
        raise RuntimeError(f"database was not ready within {timeout_seconds:.0f}s: {last_error}")

    def verify_schema(self, expected_dimension: int) -> None:
        """Check that the migrations ran and that the vector width matches.

        Raises:
            RuntimeError: If the table is missing or the column width differs.
        """
        query = """
            SELECT a.atttypmod AS dimension
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            WHERE c.relname = 'movies' AND a.attname = 'embedding'
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query)
            found = cur.fetchone()
        if found is None:
            raise RuntimeError(
                "table 'movies' or column 'embedding' not found. Run the Flyway "
                "migrations first: docker compose up flyway"
            )
        actual = int(found["dimension"])
        if actual != expected_dimension:
            raise RuntimeError(
                f"the movies.embedding column is vector({actual}) but EMBEDDING_DIM is "
                f"{expected_dimension}. Change both together, then re-run the migrations."
            )
        logger.info("database.schema_verified", dimension=actual)

    def fetch_existing(self) -> dict[str, ExistingRow]:
        """Read the state of every row already in the table."""
        query = """
            SELECT source_key, content_hash, augmented_text, embedding_model,
                   (embedding IS NOT NULL) AS has_embedding
            FROM movies
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(query)
            rows = cur.fetchall()
        existing = {
            row["source_key"]: ExistingRow(
                content_hash=row["content_hash"],
                augmented_text=row["augmented_text"],
                embedding_model=row["embedding_model"],
                has_embedding=bool(row["has_embedding"]),
            )
            for row in rows
        }
        logger.info("database.existing_rows", count=len(existing))
        return existing

    def upsert(self, frame: pd.DataFrame, report: LoadReport) -> LoadReport:
        """Write every row of ``frame`` and fill in the load counters.

        Args:
            frame: Rows carrying every column in :data:`INSERT_COLUMNS`.
            report: Report that receives the insert, update and unchanged counts.

        Returns:
            The same report, filled in.
        """
        started = time.monotonic()
        inserted = 0
        updated = 0

        with self._connect() as conn:
            with conn.cursor() as cur:
                for start in range(0, len(frame), self._chunk_size):
                    chunk = frame.iloc[start : start + self._chunk_size]
                    params: list[Any] = []
                    for _, row in chunk.iterrows():
                        params.extend(row_params(row))
                    cur.execute(insert_sql(len(chunk)), params)
                    for result in cur.fetchall():
                        if result["inserted"]:
                            inserted += 1
                        else:
                            updated += 1
            conn.commit()
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS total FROM movies")
                total_row = cur.fetchone()
                report.total_rows_in_table = int(total_row["total"]) if total_row else 0

        report.inserted = inserted
        report.updated = updated
        report.unchanged = len(frame) - inserted - updated
        report.duration_seconds = time.monotonic() - started
        logger.info(
            "database.upsert_finished",
            inserted=inserted,
            updated=updated,
            unchanged=report.unchanged,
            total=report.total_rows_in_table,
        )
        return report
