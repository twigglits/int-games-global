"""Shared fixtures for the MCP server tests.

The tests never reach a database or an embedding service. A fake
:class:`FakeDatabase` and a fake :class:`FakeEmbeddings` are installed through
the same context that the real lifespan uses, so the tools run exactly the code
path they run in production.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

import pytest

from config import Settings
from server.context import ToolContext, set_context
from server.db import Database, to_movie_result
from server.embeddings import EmbeddingClient
from server.models import DatasetStats, DecadeCount, GenreCount, MovieResult

TERMINATOR_ID = UUID("8267e750-d59b-4259-a9f6-4025e0d78565")
ALIENS_ID = UUID("0f7c1f9e-2a1b-4a3c-9d55-1b2c3d4e5f60")


def movie_row(**overrides: Any) -> dict[str, Any]:
    """One database row, in the shape the SELECT statements return."""
    row: dict[str, Any] = {
        "id": TERMINATOR_ID,
        "title": "The Terminator",
        "release_date": date(1984, 10, 26),
        "release_year": 1984,
        "decade": 1980,
        "major_genre": "Action",
        "creative_type": "Science Fiction",
        "source": "Original Screenplay",
        "mpaa_rating": "R",
        "director": "James Cameron",
        "distributor": "Orion",
        "running_time_min": 108,
        "production_budget": 6_400_000,
        "us_gross": 38_400_000,
        "worldwide_gross": 78_300_000,
        "imdb_rating": 8.1,
        "imdb_votes": 300_000,
        "rt_rating": 100,
        "budget_tier": "low",
        "blockbuster_flag": False,
        "rating_score_delta": -19.0,
        "imputed_fields": [],
        "similarity": 0.8123456,
    }
    row.update(overrides)
    return row


class FakeDatabase(Database):
    """Database stand-in that records its calls and returns canned rows."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.search_rows: list[dict[str, Any]] = [movie_row()]
        self.title_row: dict[str, Any] | None = movie_row(similarity=None)
        self.similar_rows: list[dict[str, Any]] = [
            movie_row(id=ALIENS_ID, title="Aliens", similarity=0.86)
        ]
        self.genres: list[str] = ["Drama", "Action", "Comedy"]
        self.similar_raises: Exception | None = None
        self.embedded = 3200

    async def search(self, query_vector: str, **kwargs: Any) -> list[MovieResult]:
        self.calls.append(("search", {"vector": query_vector, **kwargs}))
        return [to_movie_result(row) for row in self.search_rows]

    async def get_by_title(self, title: str) -> MovieResult | None:
        self.calls.append(("get_by_title", {"title": title}))
        return to_movie_result(self.title_row) if self.title_row else None

    async def get_by_id(self, movie_id: UUID) -> MovieResult | None:
        self.calls.append(("get_by_id", {"movie_id": movie_id}))
        return to_movie_result(movie_row(id=movie_id, similarity=None))

    async def similar_to(self, movie_id: UUID, top_k: int) -> list[MovieResult]:
        self.calls.append(("similar_to", {"movie_id": movie_id, "top_k": top_k}))
        if self.similar_raises is not None:
            raise self.similar_raises
        return [to_movie_result(row) for row in self.similar_rows[:top_k]]

    async def list_genres(self) -> list[str]:
        self.calls.append(("list_genres", {}))
        return list(self.genres)

    async def stats(self) -> DatasetStats:
        self.calls.append(("stats", {}))
        return DatasetStats(
            total_movies=3200,
            movies_with_embeddings=3200,
            distinct_genres=13,
            distinct_directors=800,
            distinct_distributors=175,
            earliest_release_year=1915,
            latest_release_year=2011,
            average_imdb_rating=6.28,
            average_rt_rating=52.4,
            median_production_budget=20_000_000,
            total_worldwide_gross=250_000_000_000,
            movies_per_genre=[GenreCount(genre="Drama", count=789)],
            movies_per_decade=[DecadeCount(decade=1990, count=769)],
            embedding_model="BAAI/bge-base-en-v1.5",
            embedding_dimension=768,
            pipeline_version="1.0.0",
            last_updated=datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def embedded_count(self) -> int:
        return self.embedded


class FakeEmbeddings(EmbeddingClient):
    """Embedding client stand-in. Records the queries it was asked to embed."""

    def __init__(self, dimension: int = 768) -> None:
        super().__init__("http://embeddings", dimension=dimension)
        self.queries: list[str] = []
        self.raises: Exception | None = None
        self.is_healthy = True

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        if self.raises is not None:
            raise self.raises
        return [0.1] * self._dimension

    async def embed_query_literal(self, text: str) -> str:
        vector = await self.embed_query(text)
        return "[" + ",".join(f"{v:.9g}" for v in vector) + "]"

    async def healthy(self) -> bool:
        return self.is_healthy


@pytest.fixture
def settings() -> Settings:
    return Settings(
        postgres_host="test-db",
        embeddings_url="http://test-embeddings",
        embedding_dim=768,
    )


@pytest.fixture
def database(settings: Settings) -> FakeDatabase:
    return FakeDatabase(settings)


@pytest.fixture
def embeddings() -> FakeEmbeddings:
    return FakeEmbeddings()


@pytest.fixture(autouse=True)
def tool_context(settings: Settings, database: FakeDatabase, embeddings: FakeEmbeddings) -> Any:
    """Install the fakes for the duration of one test, then clear them."""
    set_context(ToolContext(database=database, embeddings=embeddings, settings=settings))
    yield
    set_context(None)
