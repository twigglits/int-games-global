"""Database access for the MCP server.

One asyncpg pool serves every tool. The pool is opened by the application
lifespan and closed with it, so a tool call never pays connection setup.

Every statement here is parameterized. No tool input is ever concatenated into
SQL. The one interpolated value is ``hnsw.ef_search``, which is an integer this
module computes itself and clamps before use.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any
from uuid import UUID

import asyncpg

from config import Settings
from server.models import DatasetStats, DecadeCount, GenreCount, MovieResult
from server.telemetry import DB_POOL_SIZE, get_logger, timed_query

logger = get_logger(__name__)

#: Columns returned to a client. `embedding` is deliberately absent: a 768-float
#: array per row would dominate every response and no consumer reads it.
_RESULT_COLUMNS = """
    id, title, release_date, release_year, decade, major_genre, creative_type,
    source, mpaa_rating, director, distributor, running_time_min,
    production_budget, us_gross, worldwide_gross, imdb_rating, imdb_votes,
    rt_rating, budget_tier, blockbuster_flag, rating_score_delta, imputed_fields
"""

#: Hybrid search. Each filter disappears when its parameter is NULL, so one
#: prepared statement covers every combination of filters.
SEARCH_SQL = f"""
SELECT {_RESULT_COLUMNS},
       1 - (embedding <=> $1::vector) AS similarity
FROM movies
WHERE embedding IS NOT NULL
  AND ($2::text    IS NULL OR major_genre = $2::text)
  AND ($3::numeric IS NULL OR imdb_rating >= $3::numeric)
  AND ($4::text    IS NULL OR mpaa_rating = $4::text)
  AND ($5::int     IS NULL OR decade      = $5::int)
ORDER BY embedding <=> $1::vector
LIMIT $6::int
"""

#: Nearest neighbours of a vector, with one row excluded. Used by
#: `get_similar_movies` so that a movie is never its own best match.
SIMILAR_SQL = f"""
SELECT {_RESULT_COLUMNS},
       1 - (embedding <=> $1::vector) AS similarity
FROM movies
WHERE embedding IS NOT NULL
  AND id <> $2::uuid
ORDER BY embedding <=> $1::vector
LIMIT $3::int
"""

EXACT_TITLE_SQL = f"""
SELECT {_RESULT_COLUMNS}, NULL::float8 AS similarity
FROM movies
WHERE LOWER(title) = LOWER($1)
ORDER BY release_year DESC NULLS LAST
LIMIT 1
"""

#: Loosest score the index pre-filter accepts. It is deliberately lower than the
#: decision threshold: any row that would pass the decision also passes this, so
#: the index can never hide a row the decision would have accepted.
TRIGRAM_PREFILTER = 0.3

#: Fuzzy title match through pg_trgm.
#:
#: The score is the larger of two measures:
#:
#: * ``similarity`` compares the two strings whole. It handles a misspelling,
#:   but it punishes a query that is much shorter than the title.
#: * ``word_similarity`` compares the query against the best matching stretch of
#:   the title. It handles a partial title.
#:
#: Taking the larger of the two is what makes "Termnator 2" find
#: "Terminator 2: Judgment Day" rather than "The Terminator".
#:
#: The value returned here is a string score, not a vector score, so it is
#: reported under its own name and the `similarity` column stays NULL.
FUZZY_TITLE_SQL = f"""
SELECT {_RESULT_COLUMNS}, NULL::float8 AS similarity,
       GREATEST(similarity(title, $1), word_similarity($1, title)) AS title_similarity
FROM movies
WHERE (title % $1 OR $1 <% title)
  AND GREATEST(similarity(title, $1), word_similarity($1, title)) >= $2::float4
-- The shortest title wins a tie. `word_similarity` scores "Jurassic Park" and
-- "Jurassic Park 3" the same for the query "Jurasic Park", and the one without
-- the extra words is the one the user meant.
ORDER BY title_similarity DESC, LENGTH(title) ASC, release_year DESC NULLS LAST
LIMIT 1
"""

BY_ID_SQL = f"""
SELECT {_RESULT_COLUMNS}, NULL::float8 AS similarity
FROM movies
WHERE id = $1::uuid
"""

EMBEDDING_BY_ID_SQL = "SELECT embedding::text AS embedding FROM movies WHERE id = $1::uuid"

GENRES_SQL = """
SELECT major_genre
FROM movies
WHERE major_genre IS NOT NULL
GROUP BY major_genre
ORDER BY COUNT(*) DESC, major_genre
"""

STATS_SQL = """
SELECT
    COUNT(*)                                          AS total_movies,
    COUNT(embedding)                                  AS movies_with_embeddings,
    COUNT(DISTINCT major_genre)                       AS distinct_genres,
    COUNT(DISTINCT director)                          AS distinct_directors,
    COUNT(DISTINCT distributor)                       AS distinct_distributors,
    MIN(release_year)                                 AS earliest_release_year,
    MAX(release_year)                                 AS latest_release_year,
    ROUND(AVG(imdb_rating), 2)                        AS average_imdb_rating,
    ROUND(AVG(rt_rating), 2)                          AS average_rt_rating,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY production_budget) AS median_production_budget,
    SUM(worldwide_gross)                              AS total_worldwide_gross,
    MAX(updated_at)                                   AS last_updated,
    MODE() WITHIN GROUP (ORDER BY embedding_model)    AS embedding_model,
    MODE() WITHIN GROUP (ORDER BY pipeline_version)   AS pipeline_version
FROM movies
"""

GENRE_COUNTS_SQL = """
SELECT major_genre AS genre, COUNT(*) AS count
FROM movies
WHERE major_genre IS NOT NULL
GROUP BY major_genre
ORDER BY count DESC, genre
"""

DECADE_COUNTS_SQL = """
SELECT decade, COUNT(*) AS count
FROM movies
WHERE decade IS NOT NULL
GROUP BY decade
ORDER BY decade
"""

EMBEDDED_COUNT_SQL = "SELECT COUNT(embedding) AS embedded FROM movies"


def _number(value: Any) -> Any:
    """Turn a PostgreSQL NUMERIC into a float. Everything else passes through."""
    return float(value) if isinstance(value, Decimal) else value


def to_movie_result(record: Mapping[str, Any]) -> MovieResult:
    """Map one database row onto the public model.

    Takes any mapping, not only an ``asyncpg.Record``, so the mapping rules can
    be tested without a database.
    """
    data: dict[str, Any] = {key: _number(value) for key, value in dict(record).items()}
    data.pop("title_similarity", None)
    data["id"] = str(data["id"])
    data["imputed_fields"] = list(data.get("imputed_fields") or [])
    if data.get("similarity") is not None:
        # Cosine distance can drift a hair outside [0, 1] through float rounding.
        data["similarity"] = round(min(1.0, max(0.0, float(data["similarity"]))), 6)
    return MovieResult.model_validate(data)


class DatabaseError(RuntimeError):
    """Raised when the database cannot serve a request."""


class Database:
    """Owns the asyncpg pool and every statement the tools run."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._pool: asyncpg.Pool[asyncpg.Record] | None = None

    # --- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        """Open the connection pool."""
        self._pool = await asyncpg.create_pool(
            dsn=self._settings.postgres_dsn,
            min_size=self._settings.mcp_db_pool_min,
            max_size=self._settings.mcp_db_pool_max,
            command_timeout=self._settings.mcp_db_command_timeout,
        )
        DB_POOL_SIZE.labels(state="max").set(self._settings.mcp_db_pool_max)
        logger.info(
            "database.pool_opened",
            min_size=self._settings.mcp_db_pool_min,
            max_size=self._settings.mcp_db_pool_max,
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("database.pool_closed")

    @property
    def pool(self) -> asyncpg.Pool[asyncpg.Record]:
        if self._pool is None:
            raise DatabaseError("the database pool is not open")
        return self._pool

    def _record_pool_state(self) -> None:
        pool = self._pool
        if pool is None:
            return
        DB_POOL_SIZE.labels(state="total").set(pool.get_size())
        DB_POOL_SIZE.labels(state="idle").set(pool.get_idle_size())

    # --- queries ------------------------------------------------------------

    async def search(
        self,
        query_vector: str,
        *,
        top_k: int,
        genre: str | None = None,
        min_imdb_rating: float | None = None,
        mpaa_rating: str | None = None,
        decade: int | None = None,
    ) -> list[MovieResult]:
        """Run the hybrid search: metadata filters plus vector distance.

        Args:
            query_vector: The embedded query in pgvector text form.
            top_k: Number of rows to return.
            genre: Exact ``major_genre`` value, or ``None``.
            min_imdb_rating: Lowest acceptable IMDB rating, or ``None``.
            mpaa_rating: Exact MPAA certificate, or ``None``.
            decade: Decade written as its first year, or ``None``.

        Returns:
            Rows ordered by cosine similarity, best first.
        """
        ef_search = self._settings.ef_search_for(top_k)
        async with self.pool.acquire() as connection, connection.transaction():
            # SET LOCAL takes no bind parameter, so the value is computed and
            # clamped by `ef_search_for` before it reaches the statement.
            await connection.execute(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
            with timed_query("hybrid_search"):
                rows = await connection.fetch(
                    SEARCH_SQL,
                    query_vector,
                    genre,
                    Decimal(str(min_imdb_rating)) if min_imdb_rating is not None else None,
                    mpaa_rating,
                    decade,
                    top_k,
                )
        self._record_pool_state()
        return [to_movie_result(row) for row in rows]

    async def get_by_title(self, title: str) -> MovieResult | None:
        """Look up one movie by exact title, then by trigram similarity.

        An exact, case-insensitive match always wins. The fuzzy fallback returns
        the single closest title whose score clears the configured threshold, so
        a typo still finds the film and an unrelated string finds nothing.
        """
        async with self.pool.acquire() as connection:
            with timed_query("title_exact"):
                row = await connection.fetchrow(EXACT_TITLE_SQL, title)
            if row is None:
                async with connection.transaction():
                    # Set the operator thresholds explicitly. Relying on the
                    # cluster defaults would make the result depend on server
                    # configuration this service does not own.
                    await connection.execute(
                        f"SET LOCAL pg_trgm.similarity_threshold = {TRIGRAM_PREFILTER}"
                    )
                    await connection.execute(
                        f"SET LOCAL pg_trgm.word_similarity_threshold = {TRIGRAM_PREFILTER}"
                    )
                    with timed_query("title_fuzzy"):
                        row = await connection.fetchrow(
                            FUZZY_TITLE_SQL, title, self._settings.title_similarity_threshold
                        )
        self._record_pool_state()
        return to_movie_result(row) if row is not None else None

    async def get_by_id(self, movie_id: UUID) -> MovieResult | None:
        """Look up one movie by its identifier."""
        async with self.pool.acquire() as connection:
            with timed_query("by_id"):
                row = await connection.fetchrow(BY_ID_SQL, movie_id)
        self._record_pool_state()
        return to_movie_result(row) if row is not None else None

    async def similar_to(self, movie_id: UUID, top_k: int) -> list[MovieResult]:
        """Return the nearest neighbours of one movie, excluding itself.

        The stored vector is read first and then passed back in as a literal
        parameter. Comparing against a value from a subquery would stop the
        planner from using the HNSW index.

        Raises:
            LookupError: If the identifier is unknown.
            DatabaseError: If the movie has no vector.
        """
        ef_search = self._settings.ef_search_for(top_k)
        async with self.pool.acquire() as connection, connection.transaction():
            with timed_query("embedding_by_id"):
                row = await connection.fetchrow(EMBEDDING_BY_ID_SQL, movie_id)
            if row is None:
                raise LookupError(f"no movie with id {movie_id}")
            vector = row["embedding"]
            if vector is None:
                raise DatabaseError(f"movie {movie_id} has no embedding and has no neighbours")
            await connection.execute(f"SET LOCAL hnsw.ef_search = {int(ef_search)}")
            with timed_query("similar"):
                rows = await connection.fetch(SIMILAR_SQL, vector, movie_id, top_k)
        self._record_pool_state()
        return [to_movie_result(record) for record in rows]

    async def list_genres(self) -> list[str]:
        """Return every distinct genre, most common first."""
        async with self.pool.acquire() as connection:
            with timed_query("genres"):
                rows = await connection.fetch(GENRES_SQL)
        self._record_pool_state()
        return [row["major_genre"] for row in rows]

    async def stats(self) -> DatasetStats:
        """Return summary statistics for the whole table."""
        async with self.pool.acquire() as connection:
            with timed_query("stats"):
                summary = await connection.fetchrow(STATS_SQL)
                genres = await connection.fetch(GENRE_COUNTS_SQL)
                decades = await connection.fetch(DECADE_COUNTS_SQL)
        self._record_pool_state()

        data: dict[str, Any] = {key: _number(value) for key, value in dict(summary or {}).items()}
        median = data.get("median_production_budget")
        return DatasetStats(
            total_movies=int(data.get("total_movies") or 0),
            movies_with_embeddings=int(data.get("movies_with_embeddings") or 0),
            distinct_genres=int(data.get("distinct_genres") or 0),
            distinct_directors=int(data.get("distinct_directors") or 0),
            distinct_distributors=int(data.get("distinct_distributors") or 0),
            earliest_release_year=data.get("earliest_release_year"),
            latest_release_year=data.get("latest_release_year"),
            average_imdb_rating=data.get("average_imdb_rating"),
            average_rt_rating=data.get("average_rt_rating"),
            median_production_budget=int(median) if median is not None else None,
            total_worldwide_gross=data.get("total_worldwide_gross"),
            movies_per_genre=[GenreCount(genre=row["genre"], count=row["count"]) for row in genres],
            movies_per_decade=[
                DecadeCount(decade=row["decade"], count=row["count"]) for row in decades
            ],
            embedding_model=data.get("embedding_model"),
            embedding_dimension=self._settings.embedding_dim,
            pipeline_version=data.get("pipeline_version"),
            last_updated=data.get("last_updated"),
        )

    async def embedded_count(self) -> int:
        """Number of rows that carry a vector. Used by the health check."""
        async with self.pool.acquire() as connection:
            row = await connection.fetchrow(EMBEDDED_COUNT_SQL)
        self._record_pool_state()
        return int(row["embedded"]) if row else 0
