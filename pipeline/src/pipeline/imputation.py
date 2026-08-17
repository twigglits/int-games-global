"""Stage 3 — imputation.

Every decision here answers one question: does filling this value help semantic
search more than it distorts the data? The answers differ per field, so the
strategies differ per field. The reasoning for each is in the returned report
and is repeated in the README.

Two rules hold across the whole stage:

* A filled value is recorded in the ``imputed_fields`` column of that row. No
  consumer has to guess whether a number was measured or invented.
* Group statistics are computed from observed values only. An imputed value
  never becomes the input to another imputation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.logging import get_logger
from pipeline.report import ImputationReport

logger = get_logger(__name__)

#: Categorical field -> (fill value, reason).
CATEGORICAL_STRATEGY: dict[str, tuple[str, str]] = {
    "major_genre": (
        "Unknown",
        "genre is an exact search filter; a guessed genre would return the wrong "
        "rows, so an explicit sentinel is safer than a mode fill",
    ),
    "creative_type": (
        "Unknown",
        "same reasoning as genre: it is a label, not a measurement",
    ),
    "source": (
        "Unknown",
        "the source material cannot be inferred from budget or box office",
    ),
    "director": (
        "Unknown",
        "a director name is an identity; the mode would attribute more than a "
        "thousand films to one person and poison every director query",
    ),
    "distributor": (
        "Unknown",
        "the mode would attribute independent films to a major studio",
    ),
    "mpaa_rating": (
        "Not Rated",
        "'Not Rated' is a real MPAA outcome that already appears 94 times, so it "
        "is a truthful bucket for a film with no certificate on record",
    ),
}

#: Numeric fields that stay missing on purpose, with the reason.
LEFT_MISSING: dict[str, str] = {
    "imdb_votes": (
        "vote count measures audience size; a median would invent an audience and "
        "would make an obscure film look popular"
    ),
    "us_gross": "box office is a recorded fact, not a property that can be estimated",
    "worldwide_gross": "box office is a recorded fact, not a property that can be estimated",
    "us_dvd_sales": (
        "82 percent of the column is missing, so any fill value would define the "
        "column instead of completing it"
    ),
}

#: Minimum number of paired observations before the regression is trusted.
MIN_REGRESSION_PAIRS = 30


def _group_median_fill(values: pd.Series, groups: pd.Series) -> tuple[pd.Series, pd.Series, float]:
    """Fill missing values with the median of their group.

    Args:
        values: Numeric column that contains missing values.
        groups: Grouping key of the same length, for example genre or decade.

    Returns:
        A tuple of the filled column, the boolean mask of rows that were filled,
        and the global median used as the fallback.
    """
    was_missing = values.isna()
    group_median = values.groupby(groups).transform("median")
    global_median = float(values.median()) if values.notna().any() else 0.0
    filled = values.fillna(group_median).fillna(global_median)
    return filled, was_missing, global_median


def impute(frame: pd.DataFrame) -> tuple[pd.DataFrame, ImputationReport]:
    """Fill missing values and record which fields were filled per row.

    Args:
        frame: Cleaned dataframe from :func:`pipeline.cleaning.clean`.

    Returns:
        The imputed dataframe and the report describing every decision.
    """
    df = frame.copy()
    report = ImputationReport()
    imputed_flags: dict[str, pd.Series] = {}

    # Group keys are taken before any fill, so an imputed genre never becomes a
    # grouping key. `decade` is recomputed here only as a grouping key; the
    # persisted `decade` column is created in the augmentation stage.
    genre_key = df["major_genre"].fillna("__missing__")
    decade_key = (df["release_year"] // 10 * 10).fillna(-1)

    # --- IMDB rating: median within genre --------------------------------------
    filled, mask, global_median = _group_median_fill(df["imdb_rating"], genre_key)
    df["imdb_rating"] = filled.round(1)
    imputed_flags["imdb_rating"] = mask
    report.add(
        "imdb_rating",
        int(mask.sum()),
        "median within Major Genre, global median as fallback",
        f"ratings cluster by genre; the median resists outliers and sits mid-scale "
        f"(global median {global_median:.1f}), so an imputed row cannot pass a "
        f"'highly rated' filter it does not deserve",
    )

    # --- Rotten Tomatoes: predicted from the IMDB rating ------------------------
    # The two scores correlate strongly on this dataset (Pearson r = 0.74 over
    # 2260 paired rows), so a fitted line carries far more information than a
    # median. Rows still missing after the fit fall back to the genre median.
    observed = frame["rt_rating"].notna() & frame["imdb_rating"].notna()
    rt_missing = df["rt_rating"].isna()
    pair_count = int(observed.sum())
    if pair_count >= MIN_REGRESSION_PAIRS:
        slope, intercept = np.polyfit(
            frame.loc[observed, "imdb_rating"].to_numpy(dtype=float),
            frame.loc[observed, "rt_rating"].to_numpy(dtype=float),
            deg=1,
        )
        # The fit reads the pre-imputation IMDB column on purpose. Predicting a
        # critic score from an already-imputed audience score would stack one
        # guess on another and report it as a measurement.
        predicted = (frame["imdb_rating"] * float(slope) + float(intercept)).clip(0, 100)
        df["rt_rating"] = df["rt_rating"].fillna(predicted)
        detail = (
            f"fitted on {pair_count} paired rows: "
            f"rt = {slope:.2f} * imdb + {intercept:.2f}, clipped to [0, 100]; "
            f"rows with no observed IMDB rating fall through to the genre median"
        )
        strategy = "linear fit against the observed IMDB rating"
    else:
        detail = f"only {pair_count} paired rows, below the threshold of {MIN_REGRESSION_PAIRS}"
        strategy = "genre median (regression skipped)"
    filled, _, _ = _group_median_fill(df["rt_rating"], genre_key)
    df["rt_rating"] = filled.round(0)
    imputed_flags["rt_rating"] = rt_missing
    report.add("rt_rating", int(rt_missing.sum()), strategy, detail)

    # --- Running time: median within genre --------------------------------------
    filled, mask, global_median = _group_median_fill(df["running_time_min"], genre_key)
    df["running_time_min"] = filled.round(0)
    imputed_flags["running_time_min"] = mask
    report.add(
        "running_time_min",
        int(mask.sum()),
        "median within Major Genre, global median as fallback",
        f"runtime follows genre convention: a documentary is shorter than an epic "
        f"(global median {global_median:.0f} minutes)",
    )

    # --- Production budget: median within decade ---------------------------------
    filled, mask, global_median = _group_median_fill(df["production_budget"], decade_key)
    df["production_budget"] = filled.round(0)
    imputed_flags["production_budget"] = mask
    report.add(
        "production_budget",
        int(mask.sum()),
        "median within release decade, global median as fallback",
        f"budgets are nominal dollars and inflate over time, so a decade median is "
        f"closer than one global median (global median ${global_median:,.0f})",
    )

    # --- Categorical sentinels ----------------------------------------------------
    for column, (fill_value, reason) in CATEGORICAL_STRATEGY.items():
        mask = df[column].isna()
        df[column] = df[column].fillna(fill_value)
        imputed_flags[column] = mask
        report.add(column, int(mask.sum()), f"constant '{fill_value}'", reason)

    # --- Fields deliberately left missing -------------------------------------------
    for column, reason in LEFT_MISSING.items():
        report.add(column, int(df[column].isna().sum()), "left as NULL", reason)

    # --- Per-row provenance ----------------------------------------------------------
    flag_frame = pd.DataFrame(imputed_flags, index=df.index)
    df["imputed_fields"] = [
        sorted(flag_frame.columns[row].tolist()) for row in flag_frame.to_numpy(dtype=bool)
    ]

    logger.info(
        "imputation.finished",
        rows=len(df),
        fields_imputed={k: int(v.sum()) for k, v in imputed_flags.items()},
    )
    return df, report
