"""Tests for the feature augmentation stage."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.augmentation import (
    BLOCKBUSTER_MIN_GROSS,
    MAX_PROFIT_RATIO,
    _budget_tier,
    augment,
    build_augmented_text,
)
from pipeline.cleaning import clean
from pipeline.imputation import impute
from pipeline.report import AugmentationReport


@pytest.fixture
def augmented(raw_frame: pd.DataFrame) -> tuple[pd.DataFrame, AugmentationReport]:
    cleaned, _ = clean(raw_frame, max_release_year=2011)
    imputed, _ = impute(cleaned)
    return augment(imputed)


def _row(df: pd.DataFrame, title: str) -> pd.Series:
    return df.loc[df["title"] == title].iloc[0]


@pytest.mark.parametrize(
    ("budget", "code"),
    [
        (1_000_000, "micro"),
        (4_999_999, "micro"),
        (5_000_000, "low"),
        (19_999_999, "low"),
        (20_000_000, "mid"),
        (50_000_000, "high"),
        (99_999_999, "high"),
        (100_000_000, "blockbuster"),
        (300_000_000, "blockbuster"),
        (None, None),
        (float("nan"), None),
    ],
)
def test_budget_tier_boundaries(budget: float | None, code: str | None) -> None:
    assert _budget_tier(budget)[0] == code


def test_decade_is_the_floor_of_the_year(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    df, _ = augmented
    assert _row(df, "Rollover Film")["decade"] == 1940
    assert _row(df, "Silent Era Film")["decade"] == 1910
    assert pd.isna(_row(df, "Bad Date Film")["decade"])


def test_rating_score_delta_is_the_gap_on_one_scale(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    df, _ = augmented
    row = _row(df, "Baseline Movie")
    assert row["rating_score_delta"] == pytest.approx(row["imdb_rating"] * 10 - row["rt_rating"])


def test_blockbuster_needs_both_gross_and_multiple() -> None:
    frame = pd.DataFrame(
        {
            "title": ["Big and profitable", "Big but barely doubled", "Small but profitable"],
            "release_year": [2000.0] * 3,
            "major_genre": ["Action"] * 3,
            "creative_type": ["Contemporary Fiction"] * 3,
            "source": ["Original Screenplay"] * 3,
            "mpaa_rating": ["PG-13"] * 3,
            "director": ["D"] * 3,
            "distributor": ["S"] * 3,
            "running_time_min": [100.0] * 3,
            "imdb_rating": [7.0] * 3,
            "imdb_votes": [1000.0] * 3,
            "rt_rating": [70.0] * 3,
            "us_gross": [1e8] * 3,
            "us_dvd_sales": [np.nan] * 3,
            "imputed_fields": [[], [], []],
            "source_key": ["a", "b", "c"],
            "release_date": [pd.Timestamp("2000-01-01")] * 3,
            "production_budget": [50_000_000.0, 90_000_000.0, 1_000_000.0],
            "worldwide_gross": [
                float(BLOCKBUSTER_MIN_GROSS) * 3,
                float(BLOCKBUSTER_MIN_GROSS) + 1,
                50_000_000.0,
            ],
        }
    )
    df, _ = augment(frame)
    assert df.loc[0, "blockbuster_flag"]
    assert not df.loc[1, "blockbuster_flag"]  # over the gross bar, under the multiple
    assert not df.loc[2, "blockbuster_flag"]  # over the multiple, under the gross bar


def test_profit_ratio_is_capped_for_the_numeric_column() -> None:
    frame = pd.DataFrame(
        {
            "title": ["Tiny budget, huge gross"],
            "release_year": [2000.0],
            "major_genre": ["Horror"],
            "creative_type": ["Contemporary Fiction"],
            "source": ["Original Screenplay"],
            "mpaa_rating": ["R"],
            "director": ["D"],
            "distributor": ["S"],
            "running_time_min": [90.0],
            "imdb_rating": [7.0],
            "imdb_votes": [10.0],
            "rt_rating": [70.0],
            "us_gross": [1e8],
            "us_dvd_sales": [np.nan],
            "imputed_fields": [[]],
            "source_key": ["a"],
            "release_date": [pd.Timestamp("2000-01-01")],
            "production_budget": [218.0],
            "worldwide_gross": [2.7e9],
        }
    )
    df, _ = augment(frame)
    assert df.loc[0, "profit_ratio"] == MAX_PROFIT_RATIO


def test_text_keeps_observed_categoricals(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    text = _row(augmented[0], "Baseline Movie")["augmented_text"]
    assert "Title: Baseline Movie" in text
    assert "Genre: Action" in text
    assert "Director: Jane Doe" in text
    assert "Distributor: Warner Bros." in text
    assert "Decade: 1990s" in text


def test_text_drops_imputed_categoricals(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    """An 'Unknown' repeated over a third of the corpus is a false signal."""
    text = _row(augmented[0], "Sparse Film")["augmented_text"]
    assert "Unknown" not in text
    for prefix in ("Genre:", "Director:", "Distributor:", "Creative Type:", "Source:"):
        assert prefix not in text
    assert "Title: Sparse Film" in text


def test_text_states_reception_only_from_observed_scores(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    df, _ = augmented
    assert (
        "Critical Reception: Critically acclaimed" in _row(df, "Baseline Movie")["augmented_text"]
    )
    assert "Poorly reviewed" in _row(df, "Panned Film")["augmented_text"]
    assert "Critical Reception" not in _row(df, "Sparse Film")["augmented_text"]


def test_text_omits_the_box_office_line_when_gross_is_unknown(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    assert "Box Office" not in _row(augmented[0], "Sparse Film")["augmented_text"]


def test_text_never_carries_a_python_none(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    df, _ = augmented
    joined = "\n".join(df["augmented_text"])
    assert "None" not in joined
    assert "nan" not in joined


def test_content_hash_changes_only_when_content_changes(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    df, _ = augmented
    again, _ = augment(df.drop(columns=["augmented_text", "content_hash"], errors="ignore"))
    assert list(df["content_hash"]) == list(again["content_hash"])

    changed = df.copy()
    changed.loc[changed.index[0], "title"] = "A Different Title"
    third, _ = augment(changed.drop(columns=["augmented_text", "content_hash"]))
    assert third.loc[third.index[0], "content_hash"] != df.loc[df.index[0], "content_hash"]


def test_hash_reacts_to_a_field_that_is_not_in_the_text(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    """us_gross never reaches the embedded text, but it is still persisted."""
    df, _ = augmented
    changed = df.copy()
    changed.loc[changed.index[0], "us_gross"] = 999_999_999
    rebuilt, _ = augment(changed.drop(columns=["augmented_text", "content_hash"]))
    assert rebuilt.loc[rebuilt.index[0], "content_hash"] != df.loc[df.index[0], "content_hash"]


def test_report_gives_a_rationale_for_every_feature(
    augmented: tuple[pd.DataFrame, AugmentationReport],
) -> None:
    _, report = augmented
    names = {feature.field_name for feature in report.features}
    assert {
        "decade",
        "budget_tier",
        "rating_score_delta",
        "blockbuster_flag",
        "profit_ratio",
        "augmented_text",
    } == names
    assert all(feature.detail for feature in report.features)


def test_build_augmented_text_handles_a_row_with_nothing_but_a_title() -> None:
    row = pd.Series(
        {
            "title": "Bare Row",
            "major_genre": "Unknown",
            "director": "Unknown",
            "mpaa_rating": "Not Rated",
            "distributor": "Unknown",
            "creative_type": "Unknown",
            "source": "Unknown",
            "release_year": np.nan,
            "running_time_min": np.nan,
            "imdb_rating": np.nan,
            "imdb_votes": np.nan,
            "rt_rating": np.nan,
            "production_budget": np.nan,
            "worldwide_gross": np.nan,
            "decade": np.nan,
            "rating_score_delta": np.nan,
            "blockbuster_flag": None,
            "imputed_fields": [
                "major_genre",
                "director",
                "mpaa_rating",
                "distributor",
                "creative_type",
                "source",
            ],
        }
    )
    text = build_augmented_text(row)
    assert text.startswith("Title: Bare Row")
    assert "Unknown minutes" in text  # the template line stays, the value is honest
    assert "Budget: $unknown" in text
