"""Tests for the five MCP tools."""

from __future__ import annotations

import pytest
from fastmcp.exceptions import ToolError

from server.context import set_context
from server.db import DatabaseError
from server.embeddings import EmbeddingServiceError
from server.tools import (
    get_dataset_stats,
    get_movie_by_title,
    get_similar_movies,
    list_genres,
    search_movies_by_description,
)
from tests.conftest import ALIENS_ID, TERMINATOR_ID, FakeDatabase, FakeEmbeddings

# --- search -----------------------------------------------------------------


async def test_search_embeds_the_query_and_returns_results(
    database: FakeDatabase, embeddings: FakeEmbeddings
) -> None:
    results = await search_movies_by_description("gritty sci-fi about machines")
    assert embeddings.queries == ["gritty sci-fi about machines"]
    assert [movie.title for movie in results] == ["The Terminator"]
    assert results[0].similarity == pytest.approx(0.812346, abs=1e-6)


async def test_search_passes_every_filter_through(database: FakeDatabase) -> None:
    await search_movies_by_description(
        "action",
        top_k=7,
        genre_filter="Action",
        min_imdb_rating=7.5,
        mpaa_rating="R",
        decade=1990,
    )
    name, arguments = database.calls[-1]
    assert name == "search"
    assert arguments["top_k"] == 7
    assert arguments["genre"] == "Action"
    assert arguments["min_imdb_rating"] == 7.5
    assert arguments["mpaa_rating"] == "R"
    assert arguments["decade"] == 1990


async def test_search_with_no_filters_sends_none(database: FakeDatabase) -> None:
    await search_movies_by_description("anything")
    _, arguments = database.calls[-1]
    assert arguments["genre"] is None
    assert arguments["min_imdb_rating"] is None
    assert arguments["mpaa_rating"] is None
    assert arguments["decade"] is None


@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"query": "", "top_k": 10}, "at least 1 character"),
        ({"query": "x", "top_k": 0}, "greater than or equal to 1"),
        ({"query": "x", "top_k": 51}, "less than or equal to 50"),
        ({"query": "x", "min_imdb_rating": 11.0}, "less than or equal to 10"),
        ({"query": "x", "min_imdb_rating": -1.0}, "greater than or equal to 0"),
        ({"query": "x", "decade": 1800}, "greater than or equal to 1900"),
    ],
)
async def test_search_rejects_bad_arguments(kwargs: dict[str, object], fragment: str) -> None:
    with pytest.raises(ToolError) as caught:
        await search_movies_by_description(**kwargs)  # type: ignore[arg-type]
    assert "invalid search arguments" in str(caught.value)
    assert fragment in str(caught.value)


async def test_search_reports_an_embedding_failure_as_a_tool_error(
    embeddings: FakeEmbeddings,
) -> None:
    embeddings.raises = EmbeddingServiceError("connection refused")
    with pytest.raises(ToolError, match="could not be embedded"):
        await search_movies_by_description("anything")


async def test_search_returns_an_empty_list_when_filters_match_nothing(
    database: FakeDatabase,
) -> None:
    database.search_rows = []
    assert await search_movies_by_description("anything", genre_filter="NoSuchGenre") == []


# --- get_movie_by_title -------------------------------------------------------


async def test_get_movie_by_title_trims_the_input(database: FakeDatabase) -> None:
    movie = await get_movie_by_title("  The Terminator  ")
    assert movie is not None
    assert database.calls[-1] == ("get_by_title", {"title": "The Terminator"})


async def test_get_movie_by_title_returns_none_when_nothing_matches(
    database: FakeDatabase,
) -> None:
    database.title_row = None
    assert await get_movie_by_title("no such film") is None


@pytest.mark.parametrize("title", ["", "   ", "\t\n"])
async def test_get_movie_by_title_rejects_an_empty_title(title: str) -> None:
    with pytest.raises(ToolError, match="must not be empty"):
        await get_movie_by_title(title)


async def test_a_title_lookup_carries_no_similarity_score(database: FakeDatabase) -> None:
    """Similarity belongs to a vector search. A lookup has none to report."""
    movie = await get_movie_by_title("The Terminator")
    assert movie is not None
    assert movie.similarity is None


# --- get_similar_movies --------------------------------------------------------


async def test_get_similar_movies_uses_the_identifier(database: FakeDatabase) -> None:
    results = await get_similar_movies(str(TERMINATOR_ID), top_k=3)
    assert database.calls[-1] == ("similar_to", {"movie_id": TERMINATOR_ID, "top_k": 3})
    assert results[0].id == str(ALIENS_ID)


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "1234", "", "8267e750-d59b-4259-a9f6"])
async def test_get_similar_movies_rejects_a_bad_identifier(bad_id: str) -> None:
    with pytest.raises(ToolError, match="must be a UUID"):
        await get_similar_movies(bad_id)


@pytest.mark.parametrize("top_k", [0, -1, 51, 1000])
async def test_get_similar_movies_bounds_top_k(top_k: int) -> None:
    with pytest.raises(ToolError, match="between 1 and 50"):
        await get_similar_movies(str(TERMINATOR_ID), top_k=top_k)


async def test_get_similar_movies_reports_an_unknown_identifier(
    database: FakeDatabase,
) -> None:
    database.similar_raises = LookupError(f"no movie with id {TERMINATOR_ID}")
    with pytest.raises(ToolError, match="no movie with id"):
        await get_similar_movies(str(TERMINATOR_ID))


async def test_get_similar_movies_reports_a_row_without_a_vector(
    database: FakeDatabase,
) -> None:
    database.similar_raises = DatabaseError("movie has no embedding and has no neighbours")
    with pytest.raises(ToolError, match="no embedding"):
        await get_similar_movies(str(TERMINATOR_ID))


# --- list_genres and stats -------------------------------------------------------


async def test_list_genres(database: FakeDatabase) -> None:
    assert await list_genres() == ["Drama", "Action", "Comedy"]


async def test_get_dataset_stats() -> None:
    stats = await get_dataset_stats()
    assert stats.total_movies == 3200
    assert stats.embedding_dimension == 768
    assert stats.embedding_model == "BAAI/bge-base-en-v1.5"
    assert stats.earliest_release_year == 1915


# --- startup ordering ---------------------------------------------------------------


async def test_a_tool_called_before_startup_says_so() -> None:
    set_context(None)
    with pytest.raises(ToolError, match="not ready yet"):
        await list_genres()
