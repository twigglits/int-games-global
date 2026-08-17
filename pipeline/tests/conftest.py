"""Shared fixtures.

``raw_frame`` is a small hand-built dataset. Every row in it exists to trigger
one specific code path in the cleaning stage, so a failure points at a single
rule rather than at "something in the data".
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from pipeline.dataset import EXPECTED_COLUMNS
from pipeline.logging import configure_logging


@pytest.fixture(scope="session", autouse=True)
def _quiet_logging(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Send test log output to a temporary directory, not to the repository."""
    configure_logging("ERROR", Path(tmp_path_factory.mktemp("logs")))


def _record(**overrides: object) -> dict[str, object]:
    """Build one dataset record with every expected column present."""
    base: dict[str, object] = dict.fromkeys(EXPECTED_COLUMNS)
    base.update(
        {
            "Title": "Baseline Movie",
            "US Gross": 50_000_000,
            "Worldwide Gross": 120_000_000,
            "US DVD Sales": None,
            "Production Budget": 40_000_000,
            "Release Date": "Jun 12 1998",
            "MPAA Rating": "R",
            "Running Time min": 110,
            "Distributor": "Warner Bros.",
            "Source": "Original Screenplay",
            "Major Genre": "Action",
            "Creative Type": "Contemporary Fiction",
            "Director": "Jane Doe",
            "Rotten Tomatoes Rating": 82,
            "IMDB Rating": 7.4,
            "IMDB Votes": 90_000,
        }
    )
    base.update(overrides)
    return base


@pytest.fixture
def raw_records() -> list[dict[str, object]]:
    """Raw records covering every cleaning rule."""
    return [
        # 0 — clean baseline.
        _record(),
        # 1 — exact duplicate of row 0.
        _record(),
        # 2 — remake: same title as row 3, different release date. Both are kept.
        _record(Title="Casino Royale", **{"Release Date": "Apr 28 1967"}),
        # 3 — the other Casino Royale.
        _record(Title="Casino Royale", **{"Release Date": "Nov 17 2006"}),
        # 4 — numeric title, untrimmed whitespace is added by the next row.
        _record(Title=300, **{"Release Date": "Mar 09 2007"}),
        # 5 — padded title with repeated inner spaces.
        _record(Title="  The   Padded  Title ", **{"Release Date": "Jan 02 2001"}),
        # 6 — two-digit-year rollover: 1946 arrives as 2046.
        _record(Title="Rollover Film", **{"Release Date": "Jun 12 2046"}),
        # 7 — silent era rollover that is already in the past: 1915 as 2015.
        _record(Title="Silent Era Film", **{"Release Date": "Feb 08 2015"}),
        # 8 — impossible numbers: rating above 10, RT above 100, zero budget,
        #     zero gross, negative runtime.
        _record(
            Title="Impossible Numbers",
            **{
                "Release Date": "May 01 2003",
                "IMDB Rating": 12.5,
                "Rotten Tomatoes Rating": 140,
                "Production Budget": 0,
                "Worldwide Gross": 0,
                "Running Time min": -5,
            },
        ),
        # 9 — MPAA value that is not a certificate.
        _record(Title="Open Rated Film", **{"Release Date": "Aug 03 2004", "MPAA Rating": "Open"}),
        # 10 — missing title: the row is dropped.
        _record(Title=None, **{"Release Date": "Sep 09 2005"}),
        # 11 — missing categoricals and missing scores, for the imputation tests.
        _record(
            Title="Sparse Film",
            **{
                "Release Date": "Oct 10 2006",
                "Major Genre": None,
                "Creative Type": None,
                "Source": None,
                "Director": None,
                "Distributor": None,
                "MPAA Rating": None,
                "IMDB Rating": None,
                "IMDB Votes": None,
                "Rotten Tomatoes Rating": None,
                "Running Time min": None,
                "Production Budget": None,
                "US Gross": None,
                "Worldwide Gross": None,
                "US DVD Sales": None,
            },
        ),
        # 12 — unparseable release date.
        _record(Title="Bad Date Film", **{"Release Date": "not a date"}),
        # 13 — low-rated film used by the reception tests.
        _record(
            Title="Panned Film",
            **{
                "Release Date": "Dec 01 2008",
                "Rotten Tomatoes Rating": 12,
                "IMDB Rating": 4.0,
                "Production Budget": 2_000_000,
                "Worldwide Gross": 1_000_000,
            },
        ),
    ]


@pytest.fixture
def raw_frame(raw_records: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame.from_records(raw_records).loc[:, list(EXPECTED_COLUMNS)]
