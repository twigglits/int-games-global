"""Tests for the imputation stage."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.cleaning import clean
from pipeline.imputation import CATEGORICAL_STRATEGY, LEFT_MISSING, impute
from pipeline.report import ImputationReport


@pytest.fixture
def imputed(raw_frame: pd.DataFrame) -> tuple[pd.DataFrame, ImputationReport]:
    cleaned, _ = clean(raw_frame, max_release_year=2011)
    return impute(cleaned)


def test_every_categorical_gets_its_sentinel(
    imputed: tuple[pd.DataFrame, ImputationReport],
) -> None:
    df, _ = imputed
    row = df.loc[df["title"] == "Sparse Film"].iloc[0]
    for column, (sentinel, _reason) in CATEGORICAL_STRATEGY.items():
        assert row[column] == sentinel, column


def test_categoricals_have_no_nulls_left(imputed: tuple[pd.DataFrame, ImputationReport]) -> None:
    df, _ = imputed
    for column in CATEGORICAL_STRATEGY:
        assert df[column].notna().all(), column


def test_fields_left_missing_stay_missing(
    imputed: tuple[pd.DataFrame, ImputationReport],
) -> None:
    df, _ = imputed
    row = df.loc[df["title"] == "Sparse Film"].iloc[0]
    for column in LEFT_MISSING:
        assert pd.isna(row[column]), column


def test_numeric_fields_are_filled(imputed: tuple[pd.DataFrame, ImputationReport]) -> None:
    df, _ = imputed
    for column in ("imdb_rating", "rt_rating", "running_time_min", "production_budget"):
        assert df[column].notna().all(), column


def test_imputed_values_stay_in_range(imputed: tuple[pd.DataFrame, ImputationReport]) -> None:
    df, _ = imputed
    assert df["imdb_rating"].between(0, 10).all()
    assert df["rt_rating"].between(0, 100).all()
    assert (df["running_time_min"] > 0).all()


def test_imputed_fields_records_exactly_what_was_filled(
    imputed: tuple[pd.DataFrame, ImputationReport],
) -> None:
    df, _ = imputed
    sparse = df.loc[df["title"] == "Sparse Film"].iloc[0]
    assert set(sparse["imputed_fields"]) == {
        "major_genre",
        "creative_type",
        "source",
        "director",
        "distributor",
        "mpaa_rating",
        "imdb_rating",
        "rt_rating",
        "running_time_min",
        "production_budget",
    }
    # A complete row records nothing.
    complete = df.loc[df["title"] == "Baseline Movie"].iloc[0]
    assert complete["imputed_fields"] == []


def test_observed_values_are_never_overwritten(
    raw_frame: pd.DataFrame, imputed: tuple[pd.DataFrame, ImputationReport]
) -> None:
    cleaned, _ = clean(raw_frame, max_release_year=2011)
    df, _ = imputed
    for column in ("imdb_rating", "rt_rating", "running_time_min", "production_budget"):
        observed = cleaned[column].notna()
        assert np.allclose(
            cleaned.loc[observed, column].to_numpy(dtype=float),
            df.loc[observed, column].to_numpy(dtype=float),
        ), column


def test_report_covers_every_field_it_touched(
    imputed: tuple[pd.DataFrame, ImputationReport],
) -> None:
    _, report = imputed
    reported = {decision.field_name for decision in report.decisions}
    assert set(CATEGORICAL_STRATEGY).issubset(reported)
    assert set(LEFT_MISSING).issubset(reported)
    assert {"imdb_rating", "rt_rating", "running_time_min", "production_budget"} <= reported
    # Every decision states a reason. An unexplained fill is a defect.
    assert all(decision.detail for decision in report.decisions)


def test_rt_regression_uses_the_observed_imdb_rating() -> None:
    """A row whose IMDB rating was itself imputed must not drive the fit."""
    size = 200
    rng = np.random.default_rng(seed=7)
    imdb = rng.uniform(3, 9, size).round(1)
    frame = pd.DataFrame(
        {
            "title": [f"Film {i}" for i in range(size)],
            "release_year": np.full(size, 2000.0),
            "major_genre": ["Drama"] * size,
            "creative_type": ["Contemporary Fiction"] * size,
            "source": ["Original Screenplay"] * size,
            "mpaa_rating": ["R"] * size,
            "director": ["Someone"] * size,
            "distributor": ["Studio"] * size,
            "imdb_rating": imdb,
            "rt_rating": (imdb * 10 - 5).round(0),
            "running_time_min": np.full(size, 100.0),
            "production_budget": np.full(size, 1e7),
            "imdb_votes": np.full(size, 1000.0),
            "us_gross": np.full(size, 1e6),
            "worldwide_gross": np.full(size, 2e6),
            "us_dvd_sales": np.full(size, np.nan),
        }
    )
    # One row is missing both scores. The RT fill must come from the genre median,
    # not from a prediction built on an imputed IMDB rating.
    frame.loc[0, "imdb_rating"] = np.nan
    frame.loc[0, "rt_rating"] = np.nan

    result, report = impute(frame)
    genre_median = frame["rt_rating"].median()
    assert result.loc[0, "rt_rating"] == pytest.approx(genre_median, abs=1.0)
    flags: list[str] = list(result["imputed_fields"].iloc[0])
    assert {"imdb_rating", "rt_rating"} <= set(flags)

    fit = next(d for d in report.decisions if d.field_name == "rt_rating")
    assert "observed IMDB rating" in fit.action


def test_rt_falls_back_to_median_when_there_are_too_few_pairs() -> None:
    frame = pd.DataFrame(
        {
            "title": ["A", "B", "C"],
            "release_year": [2000.0, 2001.0, 2002.0],
            "major_genre": ["Drama"] * 3,
            "creative_type": ["Contemporary Fiction"] * 3,
            "source": ["Original Screenplay"] * 3,
            "mpaa_rating": ["R"] * 3,
            "director": ["X"] * 3,
            "distributor": ["Y"] * 3,
            "imdb_rating": [7.0, 8.0, np.nan],
            "rt_rating": [70.0, 80.0, np.nan],
            "running_time_min": [100.0] * 3,
            "production_budget": [1e7] * 3,
            "imdb_votes": [100.0] * 3,
            "us_gross": [1e6] * 3,
            "worldwide_gross": [2e6] * 3,
            "us_dvd_sales": [np.nan] * 3,
        }
    )
    result, report = impute(frame)
    assert result["rt_rating"].notna().all()
    decision = next(d for d in report.decisions if d.field_name == "rt_rating")
    assert "regression skipped" in decision.action
