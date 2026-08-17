"""Stage 2 — cleaning.

The stage does six things, and it counts every one of them for the report:

1. Rename the source columns to snake_case names used everywhere downstream.
2. Coerce every text field to a string, strip it, and collapse repeated spaces.
3. Repair known inconsistencies in the categorical fields.
4. Parse ``Release Date`` and repair the two-digit-year rollover in the source.
5. Force each numeric field into a sensible range, and null out what falls out.
6. Remove duplicates on the natural key, then build that key.

The stage never silently discards anything. Anything it drops or nulls appears
in the returned :class:`~pipeline.report.CleaningReport`.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from pipeline.logging import get_logger
from pipeline.report import CleaningReport

logger = get_logger(__name__)

#: Source column name -> internal column name.
COLUMN_RENAMES: dict[str, str] = {
    "Title": "title",
    "US Gross": "us_gross",
    "Worldwide Gross": "worldwide_gross",
    "US DVD Sales": "us_dvd_sales",
    "Production Budget": "production_budget",
    "Release Date": "release_date",
    "MPAA Rating": "mpaa_rating",
    "Running Time min": "running_time_min",
    "Distributor": "distributor",
    "Source": "source",
    "Major Genre": "major_genre",
    "Creative Type": "creative_type",
    "Director": "director",
    "Rotten Tomatoes Rating": "rt_rating",
    "IMDB Rating": "imdb_rating",
    "IMDB Votes": "imdb_votes",
}

TEXT_COLUMNS: tuple[str, ...] = (
    "title",
    "mpaa_rating",
    "distributor",
    "source",
    "major_genre",
    "creative_type",
    "director",
)

#: Columns whose casing and spacing are made consistent by majority vote.
CANONICALIZED_COLUMNS: tuple[str, ...] = (
    "distributor",
    "director",
    "major_genre",
    "creative_type",
    "source",
    "mpaa_rating",
)

#: Numeric column -> (lowest accepted value, highest accepted value).
#: A value outside the range is not real data, so it becomes NULL and the row
#: survives. Dropping the whole row would throw away good fields with the bad one.
NUMERIC_RANGES: dict[str, tuple[float, float]] = {
    "imdb_rating": (0.0, 10.0),
    "rt_rating": (0.0, 100.0),
    "imdb_votes": (0.0, 1e9),
    "running_time_min": (1.0, 500.0),
    "production_budget": (1.0, 1e10),
    "us_gross": (1.0, 1e11),
    "worldwide_gross": (1.0, 1e11),
    "us_dvd_sales": (1.0, 1e11),
}

#: MPAA values in the source that are not real certificates.
#: "Open" appears twice in the Vega dataset and is not an MPAA certificate.
MPAA_FIXES: dict[str, str] = {
    "OPEN": "Not Rated",
    "NOT RATED": "Not Rated",
    "UNRATED": "Not Rated",
    "NR": "Not Rated",
    "G": "G",
    "PG": "PG",
    "PG-13": "PG-13",
    "R": "R",
    "NC-17": "NC-17",
}

_WHITESPACE = re.compile(r"\s+")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def _collapse(value: object) -> str | None:
    """Return ``value`` as a stripped single-spaced string, or ``None``."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    text = _WHITESPACE.sub(" ", str(value)).strip()
    return text or None


def slugify(value: str) -> str:
    """Return a lowercase ASCII slug. Used to build the idempotency key."""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return _NON_SLUG.sub("-", folded.lower()).strip("-")


def _canonical_forms(values: pd.Series) -> dict[str, str]:
    """Map every spelling of a label to its most common spelling.

    Two rows that mean the same distributor but differ in case or spacing would
    otherwise split into two categories and break the metadata filters.
    """
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    for raw in values.dropna():
        groups[str(raw).casefold()][str(raw)] += 1
    mapping: dict[str, str] = {}
    for variants in groups.values():
        winner = variants.most_common(1)[0][0]
        for variant in variants:
            if variant != winner:
                mapping[variant] = winner
    return mapping


#: Last year the Vega movies dataset covers. See :func:`clean` for why it matters.
DEFAULT_MAX_RELEASE_YEAR = 2011


def clean(
    frame: pd.DataFrame, *, max_release_year: int = DEFAULT_MAX_RELEASE_YEAR
) -> tuple[pd.DataFrame, CleaningReport]:
    """Clean the raw movies dataframe.

    Args:
        frame: Raw dataframe as returned by :func:`pipeline.dataset.load_movies`.
        max_release_year: Last year the dataset can legitimately contain. Any
            parsed year above it is a two-digit-year rollover and gets shifted
            back one century.

            A "later than today" test is not enough. The source encodes years
            with two digits, so `The Birth of a Nation` (1915) parses as 2015 and
            `Ben-Hur` (1925) parses as 2025. Both of those are already in the
            past, so only a bound taken from the dataset itself catches them. The
            dataset ends in 2011, so 2011 is the bound.

    Returns:
        The cleaned dataframe and the report of everything that was changed.
    """
    report = CleaningReport(rows_in=len(frame))
    df = frame.rename(columns=COLUMN_RENAMES).copy()

    # --- 1. Text normalization ---------------------------------------------
    for column in TEXT_COLUMNS:
        original = df[column]
        cleaned = original.map(_collapse)
        changed = int((original.astype("object") != cleaned).sum() - original.isna().sum())
        df[column] = cleaned
        report.add(
            "whitespace_or_type",
            column,
            max(changed, 0),
            "stripped, collapsed inner spaces, coerced to text",
            "some titles arrive as numbers, for example 300 and 2012",
        )

    # --- 2. Rows without a usable title --------------------------------------
    missing_title = int(df["title"].isna().sum())
    if missing_title:
        df = df.loc[df["title"].notna()].copy()
    report.add(
        "missing_title",
        "title",
        missing_title,
        "row dropped",
        "a record without a title cannot be searched for or referred to",
    )

    # --- 3. Known categorical inconsistencies --------------------------------
    mpaa_before = df["mpaa_rating"].copy()
    df["mpaa_rating"] = df["mpaa_rating"].map(
        lambda v: MPAA_FIXES.get(str(v).upper(), v) if v is not None else None
    )
    mpaa_changed = int((mpaa_before.astype("object") != df["mpaa_rating"].astype("object")).sum())
    report.add(
        "invalid_category",
        "mpaa_rating",
        mpaa_changed,
        "mapped to the official certificate set",
        "the source contains the value 'Open', which is not an MPAA certificate",
    )

    for column in CANONICALIZED_COLUMNS:
        mapping = _canonical_forms(df[column])
        if mapping:
            df[column] = df[column].map(lambda v, m=mapping: m.get(v, v) if v is not None else None)
        affected = int(df[column].isin(list(mapping)).sum()) if mapping else 0
        report.add(
            "case_or_spacing_variant",
            column,
            affected,
            "folded onto the most common spelling",
            f"{len(mapping)} variant spellings folded",
        )

    # --- 4. Release date ------------------------------------------------------
    parsed = pd.to_datetime(df["release_date"], format="%b %d %Y", errors="coerce")
    # A few rows may use another layout. Try a general parse for those only.
    residual = df["release_date"].notna() & parsed.isna()
    if bool(residual.any()):
        parsed.loc[residual] = pd.to_datetime(df.loc[residual, "release_date"], errors="coerce")

    unparseable = int((df["release_date"].notna() & parsed.isna()).sum())
    report.add(
        "unparseable_date",
        "release_date",
        unparseable,
        "set to NULL",
        "kept the row; the release year is not required for search",
    )
    missing_date = int(df["release_date"].isna().sum())
    report.add(
        "missing_date",
        "release_date",
        missing_date,
        "left as NULL",
        "no reliable way to guess a release date from the other fields",
    )

    # Two-digit-year rollover: a 1946 release parses as 2046 and a 1915 release
    # parses as 2015. Anything past the last year the dataset covers is that bug.
    rollover = parsed.notna() & (parsed.dt.year > max_release_year)
    rollover_count = int(rollover.sum())
    if rollover_count:
        parsed.loc[rollover] = parsed.loc[rollover] - pd.DateOffset(years=100)
    report.add(
        "two_digit_year_rollover",
        "release_date",
        rollover_count,
        "shifted back 100 years",
        f"any year after {max_release_year} is a rollover; The Birth of a Nation "
        f"parsed as 2015 and Ben-Hur parsed as 2025",
    )

    df["release_date"] = parsed
    df["release_year"] = parsed.dt.year.astype("float64")

    # --- 5. Numeric ranges -----------------------------------------------------
    for column, (low, high) in NUMERIC_RANGES.items():
        numeric = pd.to_numeric(df[column], errors="coerce")
        non_numeric = int((df[column].notna() & numeric.isna()).sum())
        out_of_range = int((numeric.notna() & ((numeric < low) | (numeric > high))).sum())
        df[column] = numeric.where(numeric.isna() | ((numeric >= low) & (numeric <= high)))
        report.add(
            "out_of_range_or_non_numeric",
            column,
            non_numeric + out_of_range,
            f"set to NULL outside [{low:g}, {high:g}]",
            "a zero budget or a zero gross is a missing figure, not a real one",
        )

    # --- 6. Duplicates ----------------------------------------------------------
    exact = int(df.duplicated(keep="first").sum())
    if exact:
        df = df.drop_duplicates(keep="first").copy()
    report.add(
        "exact_duplicate_row",
        "*",
        exact,
        "kept the first occurrence",
        "every field identical",
    )

    df["title_slug"] = df["title"].map(lambda v: slugify(str(v)))
    date_key = df["release_date"].dt.strftime("%Y-%m-%d").fillna("undated")
    df["source_key"] = df["title_slug"] + "::" + date_key

    key_dupes = int(df.duplicated(subset=["source_key"], keep="first").sum())
    if key_dupes:
        df = df.drop_duplicates(subset=["source_key"], keep="first").copy()
    report.add(
        "duplicate_natural_key",
        "title + release_date",
        key_dupes,
        "kept the first occurrence",
        "the key is title plus release date, not title alone",
    )

    repeated_titles = int(df["title_slug"].duplicated(keep=False).sum())
    report.add(
        "repeated_title_kept",
        "title",
        repeated_titles,
        "kept every row",
        "remakes share a title, for example Casino Royale 1967 and 2006",
    )

    df = df.drop(columns=["title_slug"]).reset_index(drop=True)
    report.rows_out = len(df)

    logger.info(
        "cleaning.finished",
        rows_in=report.rows_in,
        rows_out=report.rows_out,
        dropped=report.rows_in - report.rows_out,
    )
    return df, report
