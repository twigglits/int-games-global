"""Pydantic v2 models for every MCP tool input and output.

The models are the contract. FastMCP turns the annotations into the JSON schema
that an MCP client reads, so a constraint written here becomes a constraint the
client can see before it calls anything.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

#: Number of results a search may return. The .NET API applies the same ceiling.
TopK = Annotated[int, Field(ge=1, le=50, description="Number of results to return, 1 to 50.")]

#: An IMDB score. The dataset stores one decimal place.
ImdbRating = Annotated[float, Field(ge=0.0, le=10.0, description="IMDB rating from 0 to 10.")]

#: A decade written as its first year, for example 1990.
Decade = Annotated[
    int, Field(ge=1900, le=2100, description="Decade written as its first year, e.g. 1990.")
]


class MovieResult(BaseModel):
    """One movie, with the similarity score when it came from a search."""

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "id": "0f7c1f9e-2a1b-4a3c-9d55-1b2c3d4e5f60",
                    "title": "Aliens",
                    "release_year": 1986,
                    "decade": 1980,
                    "major_genre": "Action",
                    "director": "James Cameron",
                    "mpaa_rating": "R",
                    "imdb_rating": 7.5,
                    "rt_rating": 100,
                    "similarity": 0.7421,
                }
            ]
        },
    )

    id: str = Field(description="Stable UUID of the movie row.")
    title: str = Field(description="Movie title.")
    release_date: date | None = Field(default=None, description="Release date, if known.")
    release_year: int | None = Field(default=None, description="Release year, if known.")
    decade: int | None = Field(default=None, description="Decade written as its first year.")
    major_genre: str | None = Field(default=None, description="Primary genre.")
    creative_type: str | None = Field(default=None, description="Creative type of the story.")
    source: str | None = Field(default=None, description="Source material the film came from.")
    mpaa_rating: str | None = Field(default=None, description="MPAA certificate.")
    director: str | None = Field(default=None, description="Director.")
    distributor: str | None = Field(default=None, description="Distributor.")
    running_time_min: int | None = Field(default=None, description="Runtime in minutes.")
    production_budget: int | None = Field(default=None, description="Budget in US dollars.")
    us_gross: int | None = Field(default=None, description="US box office in US dollars.")
    worldwide_gross: int | None = Field(
        default=None, description="Worldwide box office in US dollars."
    )
    imdb_rating: float | None = Field(default=None, description="IMDB rating from 0 to 10.")
    imdb_votes: int | None = Field(default=None, description="Number of IMDB votes.")
    rt_rating: int | None = Field(default=None, description="Rotten Tomatoes score from 0 to 100.")
    budget_tier: str | None = Field(
        default=None, description="micro, low, mid, high or blockbuster."
    )
    blockbuster_flag: bool | None = Field(
        default=None, description="True when the film cleared both blockbuster bars."
    )
    rating_score_delta: float | None = Field(
        default=None,
        description="IMDB rating times ten minus the Rotten Tomatoes score. "
        "Positive means audiences scored it above critics.",
    )
    imputed_fields: list[str] = Field(
        default_factory=list,
        description="Fields whose value was imputed by the pipeline rather than "
        "read from the source dataset.",
    )
    similarity: float | None = Field(
        default=None,
        description="Cosine similarity to the search query, from 0.0 to 1.0. "
        "Absent when the movie was not retrieved by a similarity search.",
    )


class SearchRequest(BaseModel):
    """Every input the semantic search accepts.

    The .NET API builds one of these from its own query string, so the validation
    rules live in one place.
    """

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "query": "action movies from the 90s with high IMDB ratings",
                    "top_k": 10,
                    "genre_filter": "Action",
                    "min_imdb_rating": 7.0,
                    "decade": 1990,
                }
            ]
        }
    )

    query: str = Field(min_length=1, max_length=1000, description="Natural language description.")
    top_k: TopK = 10
    genre_filter: str | None = Field(default=None, description="Exact Major Genre value.")
    min_imdb_rating: ImdbRating | None = Field(default=None, description="Lowest IMDB rating.")
    mpaa_rating: str | None = Field(default=None, description="Exact MPAA certificate.")
    decade: Decade | None = Field(default=None, description="Decade written as its first year.")


class GenreCount(BaseModel):
    """How many movies carry one genre."""

    genre: str
    count: int


class DecadeCount(BaseModel):
    """How many movies fall in one decade."""

    decade: int
    count: int


class DatasetStats(BaseModel):
    """Summary statistics for the loaded dataset."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "total_movies": 3200,
                    "movies_with_embeddings": 3200,
                    "distinct_genres": 13,
                    "earliest_release_year": 1915,
                    "latest_release_year": 2011,
                    "average_imdb_rating": 6.28,
                    "embedding_model": "BAAI/bge-base-en-v1.5",
                    "embedding_dimension": 768,
                }
            ]
        }
    )

    total_movies: int = Field(description="Rows in the movies table.")
    movies_with_embeddings: int = Field(description="Rows that carry a vector and are searchable.")
    distinct_genres: int = Field(description="Number of distinct Major Genre values.")
    distinct_directors: int = Field(description="Number of distinct directors.")
    distinct_distributors: int = Field(description="Number of distinct distributors.")
    earliest_release_year: int | None = Field(default=None, description="Lowest release year.")
    latest_release_year: int | None = Field(default=None, description="Highest release year.")
    average_imdb_rating: float | None = Field(default=None, description="Mean IMDB rating.")
    average_rt_rating: float | None = Field(default=None, description="Mean Rotten Tomatoes score.")
    median_production_budget: int | None = Field(
        default=None, description="Median budget in US dollars."
    )
    total_worldwide_gross: int | None = Field(
        default=None, description="Sum of the known worldwide box office."
    )
    movies_per_genre: list[GenreCount] = Field(
        default_factory=list, description="Row count per genre, largest first."
    )
    movies_per_decade: list[DecadeCount] = Field(
        default_factory=list, description="Row count per decade, oldest first."
    )
    embedding_model: str | None = Field(
        default=None, description="Model that produced the vectors."
    )
    embedding_dimension: int = Field(description="Width of the stored vectors.")
    pipeline_version: str | None = Field(
        default=None, description="Version of the pipeline that last wrote a row."
    )
    last_updated: datetime | None = Field(
        default=None, description="Newest updated_at value in the table."
    )


class HealthStatus(BaseModel):
    """Answer of ``GET /health``."""

    status: str = Field(description="'healthy' or 'unhealthy'.")
    service: str
    version: str
    transport: str
    database: str = Field(description="'up' or an error description.")
    embeddings: str = Field(description="'up' or an error description.")
    movies_indexed: int | None = Field(
        default=None, description="Rows that carry a vector, when the database is reachable."
    )
