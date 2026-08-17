"""Tests for the source loading stage."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pipeline.dataset import EXPECTED_COLUMNS, load_movies, normalize_columns


def _record(prefix_style: str) -> dict[str, object]:
    """One record, spelled either with spaces or with underscores."""
    values: dict[str, object] = {
        "Title": "The Land Girls",
        "US Gross": 146083,
        "Worldwide Gross": 146083,
        "US DVD Sales": None,
        "Production Budget": 8000000,
        "Release Date": "Jun 12 1998",
        "MPAA Rating": "R",
        "Running Time min": None,
        "Distributor": "Gramercy",
        "Source": None,
        "Major Genre": None,
        "Creative Type": None,
        "Director": None,
        "Rotten Tomatoes Rating": None,
        "IMDB Rating": 6.1,
        "IMDB Votes": 1071,
    }
    if prefix_style == "underscore":
        return {key.replace(" ", "_"): value for key, value in values.items()}
    return values


@pytest.mark.parametrize("style", ["space", "underscore"])
def test_either_upstream_spelling_loads(tmp_path: Path, style: str) -> None:
    """The dataset is published under two column spellings. Both must work."""
    path = tmp_path / "movies.json"
    path.write_text(json.dumps([_record(style)]), encoding="utf-8")

    frame = load_movies(path)

    assert list(frame.columns) == list(EXPECTED_COLUMNS)
    assert frame.loc[0, "US Gross"] == 146083
    assert frame.loc[0, "Major Genre"] is None


def test_normalize_columns_only_touches_underscores() -> None:
    frame = pd.DataFrame(columns=["US_Gross", "Major Genre", "Title"])

    assert list(normalize_columns(frame).columns) == ["US Gross", "Major Genre", "Title"]


def test_a_missing_column_is_reported_with_what_was_found(tmp_path: Path) -> None:
    path = tmp_path / "movies.json"
    path.write_text(json.dumps([{"Title": "Only a title"}]), encoding="utf-8")

    with pytest.raises(ValueError) as caught:
        load_movies(path)

    assert "US Gross" in str(caught.value)
    assert "Columns found" in str(caught.value)


def test_extra_columns_are_dropped(tmp_path: Path) -> None:
    record = _record("space")
    record["Something New Upstream"] = 42
    path = tmp_path / "movies.json"
    path.write_text(json.dumps([record]), encoding="utf-8")

    assert list(load_movies(path).columns) == list(EXPECTED_COLUMNS)
