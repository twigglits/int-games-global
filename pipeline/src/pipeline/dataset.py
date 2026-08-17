"""Source loading for the Vega movies dataset.

The canonical source is ``vega_datasets.data.movies()``. That call downloads the
file from the internet, which makes a container run depend on network access and
on the upstream file staying the same. The Docker image therefore bakes a copy
of the same JSON file at build time, and this module prefers that copy. The
``vega_datasets`` call remains the fallback and the documented origin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from pipeline.logging import get_logger

logger = get_logger(__name__)

#: Columns the dataset is expected to provide. A missing column is a hard error,
#: because every later stage reads them by name.
EXPECTED_COLUMNS: tuple[str, ...] = (
    "Title",
    "US Gross",
    "Worldwide Gross",
    "US DVD Sales",
    "Production Budget",
    "Release Date",
    "MPAA Rating",
    "Running Time min",
    "Distributor",
    "Source",
    "Major Genre",
    "Creative Type",
    "Director",
    "Rotten Tomatoes Rating",
    "IMDB Rating",
    "IMDB Votes",
)


def normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Give the columns one spelling, whichever upstream file supplied them.

    The dataset is published twice. The copy that ``vega_datasets`` points at
    names its columns ``US_Gross`` and ``Major_Genre``; the copy on the project's
    main branch names them ``US Gross`` and ``Major Genre``. Both carry the same
    3201 records. Underscores become spaces here, so the rest of the pipeline
    sees one set of names and either file works.
    """
    return frame.rename(columns=lambda name: str(name).replace("_", " "))


def load_movies(cache_path: Path | None = None) -> pd.DataFrame:
    """Load the raw movies dataset.

    Args:
        cache_path: Path of a local copy of the dataset in JSON records format.
            When the file exists it is used. Otherwise the function falls back
            to ``vega_datasets``.

    Returns:
        A dataframe with the raw dataset columns, under the names in
        :data:`EXPECTED_COLUMNS`.

    Raises:
        ValueError: If a required column is missing from the loaded data.
    """
    if cache_path is not None and cache_path.is_file():
        records = json.loads(cache_path.read_text(encoding="utf-8"))
        frame = pd.DataFrame.from_records(records)
        logger.info("dataset.loaded", source="local_cache", path=str(cache_path), rows=len(frame))
    else:
        from vega_datasets import data  # imported lazily: it reaches the network

        frame = data.movies()
        logger.info("dataset.loaded", source="vega_datasets", rows=len(frame))

    frame = normalize_columns(frame)
    missing = [column for column in EXPECTED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError(
            f"dataset is missing expected columns: {missing}. "
            f"Columns found: {sorted(frame.columns)}"
        )

    return frame.loc[:, list(EXPECTED_COLUMNS)]
