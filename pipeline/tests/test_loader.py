"""Tests for the pure parts of the loader.

The SQL itself is exercised end to end by the Docker Compose integration test.
What is tested here is everything that decides *what* gets written: the work
selection, the parameter conversion and the shape of the statement.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.loader import (
    INSERT_COLUMNS,
    ExistingRow,
    insert_sql,
    row_params,
    select_rows_needing_embedding,
    vector_literal,
)

MODEL = "BAAI/bge-base-en-v1.5"


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "source_key": ["new::2001-01-01", "same::2002-01-01", "changed::2003-01-01"],
            "augmented_text": ["text new", "text same", "text changed"],
        }
    )


@pytest.fixture
def existing() -> dict[str, ExistingRow]:
    return {
        "same::2002-01-01": ExistingRow("hash", "text same", MODEL, True),
        "changed::2003-01-01": ExistingRow("hash", "text before the edit", MODEL, True),
    }


def test_new_and_changed_rows_are_embedded_and_unchanged_rows_are_not(
    frame: pd.DataFrame, existing: dict[str, ExistingRow]
) -> None:
    mask = select_rows_needing_embedding(frame, existing, embedding_model=MODEL)
    assert list(mask) == [True, False, True]


def test_a_row_whose_vector_is_missing_is_re_embedded(
    frame: pd.DataFrame, existing: dict[str, ExistingRow]
) -> None:
    existing["same::2002-01-01"] = ExistingRow("hash", "text same", MODEL, False)
    mask = select_rows_needing_embedding(frame, existing, embedding_model=MODEL)
    assert list(mask) == [True, True, True]


def test_changing_the_model_re_embeds_everything(
    frame: pd.DataFrame, existing: dict[str, ExistingRow]
) -> None:
    mask = select_rows_needing_embedding(frame, existing, embedding_model="another/model")
    assert list(mask) == [True, True, True]


def test_force_overrides_every_reuse_rule(
    frame: pd.DataFrame, existing: dict[str, ExistingRow]
) -> None:
    mask = select_rows_needing_embedding(frame, existing, embedding_model=MODEL, force=True)
    assert mask.all()


def test_an_empty_frame_selects_nothing() -> None:
    mask = select_rows_needing_embedding(
        pd.DataFrame(columns=["source_key", "augmented_text"]), {}, embedding_model=MODEL
    )
    assert mask.empty


def test_vector_literal_is_the_pgvector_text_form() -> None:
    assert vector_literal([0.5, -0.25, 0.0]) == "[0.5,-0.25,0]"


def test_vector_literal_keeps_enough_precision_to_round_trip() -> None:
    values = [0.123456789, -0.987654321]
    parsed = [float(x) for x in vector_literal(values).strip("[]").split(",")]
    assert parsed == pytest.approx(values, rel=1e-8)


def test_row_params_produces_only_plain_python_types() -> None:
    row = pd.Series(
        {
            "source_key": "k",
            "title": "T",
            "release_date": pd.Timestamp("1998-06-12"),
            "release_year": np.float64(1998.0),
            "major_genre": "Action",
            "creative_type": "Contemporary Fiction",
            "source": "Original Screenplay",
            "mpaa_rating": "R",
            "director": "D",
            "distributor": "S",
            "running_time_min": np.float64(110.0),
            "production_budget": np.float64(4.0e7),
            "us_gross": np.float64(np.nan),
            "worldwide_gross": np.float64(1.2e8),
            "us_dvd_sales": None,
            "imdb_rating": np.float64(7.4),
            "imdb_votes": np.float64(90000.0),
            "rt_rating": np.float64(82.0),
            "decade": np.float64(1990.0),
            "budget_tier": "mid",
            "rating_score_delta": np.float64(-8.0),
            "blockbuster_flag": np.bool_(True),
            "profit_ratio": np.float64(3.0),
            "imputed_fields": ["director"],
            "augmented_text": "text",
            "content_hash": "hash",
            "embedding": "[0.1,0.2]",
            "embedding_model": MODEL,
            "pipeline_version": "1.0.0",
        }
    )
    params = row_params(row)
    assert len(params) == len(INSERT_COLUMNS)
    values = dict(zip(INSERT_COLUMNS, params, strict=True))

    import datetime

    assert values["release_date"] == datetime.date(1998, 6, 12)
    assert values["release_year"] == 1998 and isinstance(values["release_year"], int)
    assert values["running_time_min"] == 110 and isinstance(values["running_time_min"], int)
    assert values["imdb_rating"] == pytest.approx(7.4) and isinstance(values["imdb_rating"], float)
    assert values["us_gross"] is None  # NaN must not reach the database
    assert values["blockbuster_flag"] is True
    assert values["imputed_fields"] == ["director"]
    for name, value in values.items():
        assert type(value).__module__ != "numpy", name


def test_insert_statement_matches_the_column_list() -> None:
    sql = insert_sql(3)
    assert sql.count("%s::vector") == 3
    assert sql.count("%s") == 3 * len(INSERT_COLUMNS)
    for column in INSERT_COLUMNS:
        assert column in sql


def test_insert_statement_preserves_an_existing_vector() -> None:
    """A NULL vector on the incoming row must not erase the stored one."""
    sql = insert_sql(1)
    assert "embedding = COALESCE(EXCLUDED.embedding, movies.embedding)" in sql


def test_insert_statement_skips_a_write_when_nothing_changed() -> None:
    sql = insert_sql(1)
    assert "ON CONFLICT (source_key) DO UPDATE" in sql
    assert "movies.content_hash IS DISTINCT FROM EXCLUDED.content_hash" in sql
    assert "RETURNING source_key, (xmax = 0) AS inserted" in sql


def test_insert_statement_rejects_an_empty_batch() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        insert_sql(0)
