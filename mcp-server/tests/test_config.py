"""Tests for the settings object."""

from __future__ import annotations

import pytest

from config import Settings


def test_dsn_is_built_from_the_parts() -> None:
    settings = Settings(
        postgres_user="u",
        postgres_password="p",
        postgres_host="db",
        postgres_port=6543,
        postgres_db="movies",
    )
    assert settings.postgres_dsn == "postgresql://u:p@db:6543/movies"


@pytest.mark.parametrize(
    ("top_k", "expected"),
    [
        (1, 100),  # below the floor, so the floor applies
        (5, 100),
        (10, 200),
        (50, 1000),
        (500, 1000),  # above the ceiling, so the ceiling applies
    ],
)
def test_ef_search_is_scaled_and_clamped(top_k: int, expected: int) -> None:
    """A metadata filter removes rows after the index returns candidates, so the
    candidate list must be wider than top_k, but never unbounded."""
    settings = Settings()
    assert settings.ef_search_for(top_k) == expected


def test_the_log_level_is_normalised() -> None:
    assert Settings(mcp_log_level="debug").mcp_log_level == "DEBUG"


def test_the_transport_is_restricted_to_the_supported_two() -> None:
    assert Settings(mcp_transport="sse").mcp_transport == "sse"
    assert Settings(mcp_transport="http").mcp_transport == "http"
    with pytest.raises(ValueError):
        Settings(mcp_transport="carrier-pigeon")  # type: ignore[arg-type]


def test_environment_variables_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_PORT", "9999")
    monkeypatch.setenv("EMBEDDINGS_URL", "http://elsewhere:80")
    settings = Settings()
    assert settings.mcp_port == 9999
    assert settings.embeddings_url == "http://elsewhere:80"
