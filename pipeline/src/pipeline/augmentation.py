"""Stage 4 — feature augmentation.

Two jobs:

1. Derive extra columns that the source dataset does not carry. Each one exists
   because a user query needs it, either as a filter or as a phrase the
   embedding can match.
2. Build ``augmented_text``: the single string that is handed to the embedding
   model. Search quality is decided here. A field that is not in this string is
   invisible to semantic search.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from pipeline.logging import get_logger
from pipeline.report import AugmentationReport

logger = get_logger(__name__)

#: Upper bound of each budget tier in nominal US dollars, with its short code and
#: the phrase used in the embedded text. Fixed cut points, not quantiles: a
#: quantile boundary would move every time rows are added, so the same film could
#: change tier without changing budget.
BUDGET_TIERS: tuple[tuple[float, str, str], ...] = (
    (5_000_000, "micro", "Micro-budget (under $5M)"),
    (20_000_000, "low", "Low-budget ($5M to $20M)"),
    (50_000_000, "mid", "Mid-budget ($20M to $50M)"),
    (100_000_000, "high", "High-budget ($50M to $100M)"),
    (float("inf"), "blockbuster", "Blockbuster budget ($100M and above)"),
)

#: A film counts as a blockbuster when it clears both bars.
BLOCKBUSTER_MIN_GROSS = 100_000_000
BLOCKBUSTER_MIN_MULTIPLE = 2.0

#: profit_ratio is stored as NUMERIC(10,3), so it is capped before it is written.
MAX_PROFIT_RATIO = 9_999.0

#: Columns that make up the content hash. Audit columns are excluded, so a run
#: that changes nothing produces the same hash and writes nothing.
HASHED_COLUMNS: tuple[str, ...] = (
    "source_key",
    "title",
    "release_date",
    "release_year",
    "decade",
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
    "budget_tier",
    "rating_score_delta",
    "blockbuster_flag",
    "profit_ratio",
    "imputed_fields",
    "augmented_text",
)


def _budget_tier(budget: float | None) -> tuple[str | None, str | None]:
    """Return the short code and the readable phrase for a budget."""
    if budget is None or (isinstance(budget, float) and np.isnan(budget)):
        return None, None
    for ceiling, code, phrase in BUDGET_TIERS:
        if budget < ceiling:
            return code, phrase
    return None, None


def _money(value: float | None) -> str:
    """Format a dollar amount, or say that it is unknown."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "unknown"
    return f"{int(value):,}"


def _optional_int(value: Any) -> int | None:
    """Return ``value`` as an int, or ``None`` when it is missing."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    """Return ``value`` as a float, or ``None`` when it is missing."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return float(value)


#: Categorical fields whose line is dropped when the value was imputed.
#: A sentinel such as "Director: Unknown" repeated over 1331 films would give
#: those films a phrase in common that has nothing to do with their content, and
#: the model would place them near each other for that reason alone. The column
#: still holds the sentinel, so metadata filters are unaffected.
SENTINEL_SUPPRESSED = frozenset(
    {"major_genre", "director", "mpaa_rating", "distributor", "creative_type", "source"}
)


def build_augmented_text(row: pd.Series) -> str:
    """Build the text representation that gets embedded for one movie.

    The layout follows the template in the specification. Two rules change what
    reaches the model:

    * A categorical line is dropped when its value was imputed. See
      :data:`SENTINEL_SUPPRESSED`.
    * An interpretive line, such as "Critically acclaimed", is written only from
      an observed score. Turning an imputed number into a strong adjective would
      publish a guess as a fact and would pull the row toward queries it has no
      claim on.

    The derived features are written as words, not numbers. A query such as
    "critically acclaimed drama films with small budgets" can only match if the
    words "acclaimed" and "Low-budget" are present in some form.
    """
    imputed = set(row.get("imputed_fields") or [])

    def observed(field: str) -> bool:
        return field not in imputed

    year = _optional_int(row.get("release_year"))
    runtime = _optional_int(row.get("running_time_min"))
    votes = _optional_int(row.get("imdb_votes"))
    imdb = row.get("imdb_rating")
    rt = _optional_int(row.get("rt_rating"))
    _, budget_phrase = _budget_tier(row.get("production_budget"))

    votes_text = f"{votes:,} votes" if votes is not None else "vote count unknown"
    candidates: list[tuple[str | None, str]] = [
        (None, f"Title: {row['title']}"),
        ("major_genre", f"Genre: {row['major_genre']}"),
        ("director", f"Director: {row['director']}"),
        ("mpaa_rating", f"MPAA Rating: {row['mpaa_rating']}"),
        (None, f"Release Year: {year if year is not None else 'Unknown'}"),
        (None, f"Runtime: {runtime if runtime is not None else 'Unknown'} minutes"),
        (None, f"IMDB Rating: {imdb}/10 ({votes_text})"),
        (None, f"Rotten Tomatoes: {rt if rt is not None else 'Unknown'}%"),
        (None, f"Budget: ${_money(row.get('production_budget'))}"),
        ("distributor", f"Distributor: {row['distributor']}"),
        ("creative_type", f"Creative Type: {row['creative_type']}"),
        ("source", f"Source: {row['source']}"),
    ]
    lines = [
        text
        for field, text in candidates
        if field is None or field not in SENTINEL_SUPPRESSED or observed(field)
    ]

    if year is not None:
        lines.append(f"Decade: {int(row['decade'])}s")
    if budget_phrase and observed("production_budget"):
        lines.append(f"Budget Tier: {budget_phrase}")

    # Reception, written as a sentence. The numbers alone carry little meaning
    # for an embedding model; the adjectives do.
    if rt is not None and observed("rt_rating"):
        if rt >= 80:
            reception = "Critically acclaimed by reviewers"
        elif rt >= 60:
            reception = "Well reviewed by critics"
        elif rt >= 40:
            reception = "Mixed reviews from critics"
        else:
            reception = "Poorly reviewed by critics, panned"
        lines.append(f"Critical Reception: {reception}")

    delta = _optional_float(row.get("rating_score_delta"))
    if delta is not None and observed("rt_rating") and observed("imdb_rating"):
        if delta >= 15:
            lines.append("Audience Reception: audiences liked it much more than critics did")
        elif delta <= -15:
            lines.append("Audience Reception: critics liked it much more than audiences did")

    # Box office is never imputed, so it is used whenever it is present.
    gross = row.get("worldwide_gross")
    if gross is not None and not (isinstance(gross, float) and np.isnan(gross)):
        label = "a commercial blockbuster" if row.get("blockbuster_flag") else "a modest earner"
        lines.append(f"Box Office: ${_money(gross)} worldwide, {label}")

    return "\n".join(lines)


def _content_hash(row: pd.Series) -> str:
    """SHA-256 over every persisted column except the audit columns."""
    payload = {column: row.get(column) for column in HASHED_COLUMNS}
    canonical = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def augment(frame: pd.DataFrame) -> tuple[pd.DataFrame, AugmentationReport]:
    """Add derived features, the augmented text and the content hash.

    Args:
        frame: Imputed dataframe from :func:`pipeline.imputation.impute`.

    Returns:
        The augmented dataframe and the report listing each derived feature.
    """
    df = frame.copy()
    report = AugmentationReport()

    # --- decade ---------------------------------------------------------------
    df["decade"] = (df["release_year"] // 10 * 10).astype("float64")
    report.add(
        "decade",
        int(df["decade"].notna().sum()),
        "the API and the MCP tools expose a decade filter; deriving it once "
        "keeps that filter an indexed integer comparison rather than a date range",
    )

    # --- budget_tier -----------------------------------------------------------
    tiers = df["production_budget"].map(_budget_tier)
    df["budget_tier"] = [code for code, _ in tiers]
    report.add(
        "budget_tier",
        int(df["budget_tier"].notna().sum()),
        "turns a raw dollar figure into the words a person actually searches "
        "with, such as 'small budget'; fixed cut points keep a film in the same "
        "tier when new rows arrive",
    )

    # --- rating_score_delta -----------------------------------------------------
    df["rating_score_delta"] = (df["imdb_rating"] * 10 - df["rt_rating"]).round(1)
    report.add(
        "rating_score_delta",
        int(df["rating_score_delta"].notna().sum()),
        "the gap between the audience score and the critic score on one scale; "
        "it separates a crowd-pleaser from a critics' film, which no single "
        "rating column can do",
    )

    # --- blockbuster_flag --------------------------------------------------------
    ratio = df["worldwide_gross"] / df["production_budget"]
    df["blockbuster_flag"] = (
        (df["worldwide_gross"] >= BLOCKBUSTER_MIN_GROSS) & (ratio >= BLOCKBUSTER_MIN_MULTIPLE)
    ).where(df["worldwide_gross"].notna() & df["production_budget"].notna())
    report.add(
        "blockbuster_flag",
        int(df["blockbuster_flag"].fillna(False).astype(bool).sum()),
        f"true when worldwide gross clears ${BLOCKBUSTER_MIN_GROSS:,} and also "
        f"{BLOCKBUSTER_MIN_MULTIPLE:g} times the budget; gross alone rewards an "
        "expensive film that lost money",
    )

    # --- profit_ratio -------------------------------------------------------------
    df["profit_ratio"] = ratio.clip(upper=MAX_PROFIT_RATIO).round(3)
    report.add(
        "profit_ratio",
        int(df["profit_ratio"].notna().sum()),
        "worldwide gross divided by budget; the continuous version of the "
        f"blockbuster flag, capped at {MAX_PROFIT_RATIO:g} to fit NUMERIC(10,3)",
    )

    # --- text and hash ---------------------------------------------------------------
    df["augmented_text"] = df.apply(build_augmented_text, axis=1)
    df["content_hash"] = df.apply(_content_hash, axis=1)
    report.add(
        "augmented_text",
        len(df),
        "the single string handed to the embedding model; it carries every "
        "searchable field plus the derived features written as words",
    )

    logger.info(
        "augmentation.finished",
        rows=len(df),
        mean_text_chars=int(df["augmented_text"].str.len().mean()),
        max_text_chars=int(df["augmented_text"].str.len().max()),
    )
    return df, report
