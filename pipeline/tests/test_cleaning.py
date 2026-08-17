"""Tests for the cleaning stage."""

from __future__ import annotations

import pandas as pd
import pytest

from pipeline.cleaning import clean, slugify
from pipeline.report import CleaningReport


@pytest.fixture
def cleaned(raw_frame: pd.DataFrame) -> tuple[pd.DataFrame, CleaningReport]:
    return clean(raw_frame, max_release_year=2011)


def _count(report: CleaningReport, issue: str, field_name: str | None = None) -> int:
    return sum(
        action.count
        for action in report.actions
        if action.issue == issue and (field_name is None or action.field_name == field_name)
    )


def test_drops_the_exact_duplicate_but_keeps_the_remake(
    cleaned: tuple[pd.DataFrame, CleaningReport],
) -> None:
    df, report = cleaned
    assert _count(report, "exact_duplicate_row") == 1
    # Both Casino Royale rows survive: same title, different release date.
    assert (df["title"] == "Casino Royale").sum() == 2
    assert df["source_key"].is_unique


def test_row_without_a_title_is_dropped(cleaned: tuple[pd.DataFrame, CleaningReport]) -> None:
    df, report = cleaned
    assert _count(report, "missing_title") == 1
    assert df["title"].notna().all()


def test_numeric_title_becomes_text(cleaned: tuple[pd.DataFrame, CleaningReport]) -> None:
    df, _ = cleaned
    assert "300" in set(df["title"])
    assert all(isinstance(title, str) for title in df["title"])


def test_whitespace_is_stripped_and_collapsed(
    cleaned: tuple[pd.DataFrame, CleaningReport],
) -> None:
    df, _ = cleaned
    assert "The Padded Title" in set(df["title"])


def test_two_digit_year_rollover_is_repaired(
    cleaned: tuple[pd.DataFrame, CleaningReport],
) -> None:
    df, report = cleaned
    assert _count(report, "two_digit_year_rollover") == 2
    years = dict(zip(df["title"], df["release_year"], strict=True))
    assert years["Rollover Film"] == 1946
    # 2015 is already in the past, so only a dataset-derived bound catches it.
    assert years["Silent Era Film"] == 1915


def test_release_year_never_exceeds_the_bound(
    cleaned: tuple[pd.DataFrame, CleaningReport],
) -> None:
    df, _ = cleaned
    assert df["release_year"].dropna().max() <= 2011


def test_unparseable_date_becomes_null_and_keeps_the_row(
    cleaned: tuple[pd.DataFrame, CleaningReport],
) -> None:
    df, report = cleaned
    assert _count(report, "unparseable_date") == 1
    row = df.loc[df["title"] == "Bad Date Film"].iloc[0]
    assert pd.isna(row["release_date"])
    assert row["source_key"].endswith("::undated")


@pytest.mark.parametrize(
    ("column", "expected_null"),
    [
        ("imdb_rating", True),
        ("rt_rating", True),
        ("production_budget", True),
        ("worldwide_gross", True),
        ("running_time_min", True),
    ],
)
def test_out_of_range_numbers_become_null(
    cleaned: tuple[pd.DataFrame, CleaningReport], column: str, expected_null: bool
) -> None:
    df, _ = cleaned
    row = df.loc[df["title"] == "Impossible Numbers"].iloc[0]
    assert pd.isna(row[column]) is expected_null


def test_out_of_range_row_survives(cleaned: tuple[pd.DataFrame, CleaningReport]) -> None:
    """A bad number nulls one field. It must not delete the whole record."""
    df, _ = cleaned
    assert (df["title"] == "Impossible Numbers").sum() == 1


def test_non_certificate_mpaa_value_is_mapped(
    cleaned: tuple[pd.DataFrame, CleaningReport],
) -> None:
    df, report = cleaned
    assert _count(report, "invalid_category", "mpaa_rating") >= 1
    row = df.loc[df["title"] == "Open Rated Film"].iloc[0]
    assert row["mpaa_rating"] == "Not Rated"


def test_source_key_is_title_plus_date(cleaned: tuple[pd.DataFrame, CleaningReport]) -> None:
    df, _ = cleaned
    keys = dict(zip(df["title"], df["source_key"], strict=True))
    assert keys["Rollover Film"] == "rollover-film::1946-06-12"


def test_report_accounts_for_every_dropped_row(
    cleaned: tuple[pd.DataFrame, CleaningReport],
) -> None:
    df, report = cleaned
    dropped = _count(report, "missing_title") + _count(report, "exact_duplicate_row")
    assert report.rows_in - report.rows_out == dropped
    assert report.rows_out == len(df)


def test_cleaning_is_deterministic(raw_frame: pd.DataFrame) -> None:
    first, _ = clean(raw_frame)
    second, _ = clean(raw_frame)
    pd.testing.assert_frame_equal(first, second)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("The Land Girls", "the-land-girls"),
        ("20,000 Leagues Under the Sea", "20-000-leagues-under-the-sea"),
        ("Amélie", "amelie"),
        ("  spaced  out  ", "spaced-out"),
        ("300", "300"),
    ],
)
def test_slugify(value: str, expected: str) -> None:
    assert slugify(value) == expected
