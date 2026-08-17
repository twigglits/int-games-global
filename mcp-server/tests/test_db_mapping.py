"""Tests for the row-to-model mapping and the statement text.

The statements themselves run against a real PostgreSQL in the Docker Compose
integration test. What is checked here is everything that can go wrong without
a database: the conversion of PostgreSQL types, and the presence of the clauses
that make the search correct.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from config import Settings
from server.db import (
    BY_ID_SQL,
    EXACT_TITLE_SQL,
    FUZZY_TITLE_SQL,
    SEARCH_SQL,
    SIMILAR_SQL,
    TRIGRAM_PREFILTER,
    to_movie_result,
)
from tests.conftest import movie_row


def test_uuid_becomes_a_string() -> None:
    identifier = uuid4()
    result = to_movie_result(movie_row(id=identifier))
    assert result.id == str(identifier)


def test_numeric_becomes_a_float() -> None:
    result = to_movie_result(
        movie_row(imdb_rating=Decimal("8.1"), rating_score_delta=Decimal("-19.0"))
    )
    assert result.imdb_rating == pytest.approx(8.1)
    assert result.rating_score_delta == pytest.approx(-19.0)


def test_null_columns_stay_none() -> None:
    result = to_movie_result(
        movie_row(
            release_date=None,
            release_year=None,
            decade=None,
            director=None,
            imdb_votes=None,
            worldwide_gross=None,
        )
    )
    assert result.release_date is None
    assert result.release_year is None
    assert result.director is None
    assert result.imdb_votes is None


def test_dates_survive() -> None:
    result = to_movie_result(movie_row(release_date=date(1984, 10, 26)))
    assert result.release_date == date(1984, 10, 26)


def test_a_null_array_becomes_an_empty_list() -> None:
    assert to_movie_result(movie_row(imputed_fields=None)).imputed_fields == []


def test_imputed_fields_are_carried_through() -> None:
    result = to_movie_result(movie_row(imputed_fields=["director", "rt_rating"]))
    assert result.imputed_fields == ["director", "rt_rating"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1.0000000004, 1.0),  # float noise just above 1
        (-1e-9, 0.0),  # float noise just below 0
        (0.5, 0.5),
        (None, None),
    ],
)
def test_similarity_is_clamped_to_the_unit_range(raw: float | None, expected: float | None) -> None:
    assert to_movie_result(movie_row(similarity=raw)).similarity == expected


def test_the_trigram_score_is_not_leaked_as_a_vector_similarity() -> None:
    """The fuzzy lookup returns a string score. It must not look like a vector score."""
    result = to_movie_result(movie_row(similarity=None, title_similarity=0.62))
    assert result.similarity is None


def test_no_statement_ever_selects_the_embedding_column() -> None:
    """A 768-float array per row would dominate every response."""
    for sql in (SEARCH_SQL, SIMILAR_SQL, EXACT_TITLE_SQL, FUZZY_TITLE_SQL, BY_ID_SQL):
        select_clause = sql.split("FROM")[0]
        assert "embedding" not in select_clause.replace("<=>", "") or "1 - (" in select_clause


def test_the_search_makes_every_filter_optional() -> None:
    """One statement must serve every combination of filters."""
    collapsed = " ".join(SEARCH_SQL.split())
    for placeholder in ("$2::text", "$3::numeric", "$4::text", "$5::int"):
        assert f"{placeholder} IS NULL OR" in collapsed


def test_the_search_orders_by_cosine_distance() -> None:
    assert "ORDER BY embedding <=> $1::vector" in SEARCH_SQL
    assert "1 - (embedding <=> $1::vector) AS similarity" in SEARCH_SQL


def test_the_search_skips_rows_without_a_vector() -> None:
    assert "WHERE embedding IS NOT NULL" in SEARCH_SQL


def test_similar_movies_excludes_the_movie_itself() -> None:
    assert "id <> $2::uuid" in SIMILAR_SQL


def test_the_exact_title_match_is_case_insensitive() -> None:
    assert "LOWER(title) = LOWER($1)" in EXACT_TITLE_SQL


def test_the_fuzzy_title_match_has_a_floor() -> None:
    assert "GREATEST(similarity(title, $1), word_similarity($1, title)) >= $2::float4" in (
        FUZZY_TITLE_SQL
    )


def test_the_fuzzy_title_match_uses_the_indexable_operators() -> None:
    """`%` and `<%` are what let the GIN trigram index answer the pre-filter."""
    assert "(title % $1 OR $1 <% title)" in FUZZY_TITLE_SQL


def test_the_fuzzy_prefilter_can_never_hide_an_acceptable_row() -> None:
    """The index pre-filter must be looser than the decision threshold."""
    assert Settings().title_similarity_threshold > TRIGRAM_PREFILTER


def test_the_shortest_title_wins_a_tie() -> None:
    assert "LENGTH(title) ASC" in FUZZY_TITLE_SQL
