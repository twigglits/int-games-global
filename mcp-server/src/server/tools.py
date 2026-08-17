"""The MCP tools.

Five tools, each fully annotated. FastMCP turns the annotations and the
docstrings into the tool schema an MCP client reads, so the type hints below are
the public contract, not decoration.

Runtime dependencies — the database pool and the embedding client — are held in
a module-level :class:`ToolContext` that the application lifespan installs. A
test installs a fake one instead, which is why the tools take no dependency
arguments.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from mcp import types as mt

from server.context import ToolContext, current_context, lifespan
from server.db import DatabaseError
from server.embeddings import EmbeddingServiceError
from server.models import DatasetStats, MovieResult, SearchRequest
from server.telemetry import (
    RESULTS_RETURNED,
    TOOL_CALLS,
    TOOL_DURATION,
    context_from_headers,
    get_logger,
    traced_span,
)

logger = get_logger(__name__)

mcp: FastMCP = FastMCP(
    name="movie-search",
    version="1.0.0",
    lifespan=lifespan,
    instructions=(
        "Semantic search over a movie catalogue. Describe what you want in plain "
        "language and add metadata filters when the request contains a hard "
        "constraint such as a genre, a decade, an MPAA certificate or a minimum "
        "IMDB rating. Filters are exact matches; the description is matched by "
        "meaning."
    ),
)


def get_context() -> ToolContext:
    """Return the installed runtime dependencies.

    Raises:
        ToolError: If the server is still starting up.
    """
    context = current_context()
    if context is None:
        raise ToolError("the server is not ready yet; try again in a moment")
    return context


class ObservabilityMiddleware(Middleware):
    """Wraps every tool call in a span, a counter and a histogram.

    The span is a child of the caller's span when the request carried a W3C
    ``traceparent`` header. That is what makes one Jaeger trace span the .NET API
    and this server.
    """

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, Any],
    ) -> Any:
        tool_name = context.message.name
        arguments: dict[str, Any] = dict(context.message.arguments or {})
        parent = context_from_headers(get_http_headers())
        started = time.perf_counter()
        status = "ok"

        try:
            with traced_span(
                f"mcp.tool/{tool_name}",
                parent=parent,
                **{
                    "mcp.tool.name": tool_name,
                    "mcp.tool.argument_names": ",".join(sorted(arguments)),
                },
            ):
                logger.info("tool.started", tool=tool_name, arguments=_loggable(arguments))
                return await call_next(context)
        except Exception as exc:
            status = "error"
            logger.error(
                "tool.failed", tool=tool_name, error=str(exc), error_type=type(exc).__name__
            )
            raise
        finally:
            elapsed = time.perf_counter() - started
            TOOL_CALLS.labels(tool=tool_name, status=status).inc()
            TOOL_DURATION.labels(tool=tool_name).observe(elapsed)
            logger.info(
                "tool.finished", tool=tool_name, status=status, duration_ms=round(elapsed * 1000, 2)
            )


def _loggable(arguments: dict[str, Any]) -> dict[str, Any]:
    """Trim argument values so one long query cannot flood the log."""
    trimmed: dict[str, Any] = {}
    for key, value in arguments.items():
        trimmed[key] = value[:200] if isinstance(value, str) else value
    return trimmed


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_movies_by_description(
    query: str,
    top_k: int = 10,
    genre_filter: str | None = None,
    min_imdb_rating: float | None = None,
    mpaa_rating: str | None = None,
    decade: int | None = None,
) -> list[MovieResult]:
    """
    Search movies using natural language description.
    Performs semantic vector similarity search with optional metadata filters.
    Returns ranked results with similarity scores.

    Args:
        query: What the movie should be about, in plain language. Example:
            "dark psychological thrillers with low Rotten Tomatoes scores".
        top_k: How many results to return, from 1 to 50.
        genre_filter: Exact Major Genre value, for example "Action". Call
            `list_genres` for the accepted values.
        min_imdb_rating: Lowest acceptable IMDB rating, from 0 to 10.
        mpaa_rating: Exact MPAA certificate, for example "PG-13".
        decade: Decade written as its first year, for example 1990.

    Returns:
        Movies ordered by similarity, best first. The list is empty when no
        movie satisfies the filters.
    """
    request = _validated_request(
        query=query,
        top_k=top_k,
        genre_filter=genre_filter,
        min_imdb_rating=min_imdb_rating,
        mpaa_rating=mpaa_rating,
        decade=decade,
    )
    context = get_context()

    try:
        vector = await context.embeddings.embed_query_literal(request.query)
    except EmbeddingServiceError as exc:
        raise ToolError(f"the query could not be embedded: {exc}") from exc

    try:
        results = await context.database.search(
            vector,
            top_k=request.top_k,
            genre=request.genre_filter,
            min_imdb_rating=request.min_imdb_rating,
            mpaa_rating=request.mpaa_rating,
            decade=request.decade,
        )
    except DatabaseError as exc:
        raise ToolError(str(exc)) from exc

    RESULTS_RETURNED.observe(len(results))
    logger.info(
        "search.completed",
        results=len(results),
        top_similarity=results[0].similarity if results else None,
        filters={
            "genre": request.genre_filter,
            "min_imdb_rating": request.min_imdb_rating,
            "mpaa_rating": request.mpaa_rating,
            "decade": request.decade,
        },
    )
    return results


@mcp.tool()
async def get_movie_by_title(title: str) -> MovieResult | None:
    """Retrieve a specific movie by exact or fuzzy title match.

    The exact match is case-insensitive and wins when it exists. Otherwise the
    lookup falls back to a trigram similarity match, so a small typo still finds
    the film.

    Args:
        title: Title to look for.

    Returns:
        The matching movie, or `None` when nothing is close enough.
    """
    cleaned = title.strip()
    if not cleaned:
        raise ToolError("title must not be empty")
    try:
        return await get_context().database.get_by_title(cleaned)
    except DatabaseError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_movie_by_id(movie_id: str) -> MovieResult | None:
    """Retrieve a specific movie by its identifier.

    Every other tool returns the identifier of each movie it lists, so this tool
    is how a client turns one of those identifiers back into the full record.

    Args:
        movie_id: UUID of a movie.

    Returns:
        The movie, or `None` when the identifier is unknown.
    """
    try:
        identifier = UUID(movie_id)
    except ValueError as exc:
        raise ToolError(f"movie_id must be a UUID, received '{movie_id}'") from exc

    try:
        return await get_context().database.get_by_id(identifier)
    except DatabaseError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_similar_movies(movie_id: str, top_k: int = 5) -> list[MovieResult]:
    """Given a movie ID, return the most semantically similar movies.

    Args:
        movie_id: UUID of a movie, as returned by any other tool.
        top_k: How many neighbours to return, from 1 to 50.

    Returns:
        Neighbours ordered by similarity, best first. The movie itself is never
        in the list.
    """
    try:
        identifier = UUID(movie_id)
    except ValueError as exc:
        raise ToolError(f"movie_id must be a UUID, received '{movie_id}'") from exc
    if not 1 <= top_k <= 50:
        raise ToolError(f"top_k must be between 1 and 50, received {top_k}")

    try:
        return await get_context().database.similar_to(identifier, top_k)
    except LookupError as exc:
        raise ToolError(str(exc)) from exc
    except DatabaseError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def list_genres() -> list[str]:
    """Return all distinct genres available in the dataset.

    The list is ordered by how many movies carry each genre, largest first. It
    includes the value "Unknown", which the pipeline assigns to a movie whose
    genre the source dataset does not state.

    Returns:
        Every accepted value of the `genre_filter` argument.
    """
    try:
        return await get_context().database.list_genres()
    except DatabaseError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
async def get_dataset_stats() -> DatasetStats:
    """Return summary statistics about the movie dataset.

    Covers row counts, the release year range, average scores, the per-genre and
    per-decade breakdown, and which embedding model and pipeline version
    produced the current contents.

    Returns:
        One `DatasetStats` object.
    """
    try:
        return await get_context().database.stats()
    except DatabaseError as exc:
        raise ToolError(str(exc)) from exc


def _validated_request(**kwargs: Any) -> SearchRequest:
    """Validate the search arguments and turn a failure into a clear message.

    FastMCP already checks the JSON schema, but a client can be older than the
    schema it was given. Validating again here means a bad value produces a
    sentence a person can act on rather than a stack trace.
    """
    try:
        return SearchRequest.model_validate(kwargs)
    except Exception as exc:  # pydantic.ValidationError
        raise ToolError(f"invalid search arguments: {exc}") from exc
