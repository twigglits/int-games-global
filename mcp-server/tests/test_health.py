"""Tests for the operational endpoints and the embedding client."""

from __future__ import annotations

import json
from typing import Any, cast

import httpx
import pytest
from starlette.requests import Request

from server.context import set_context
from server.embeddings import EmbeddingClient, EmbeddingServiceError
from server.main import health, metrics
from tests.conftest import FakeDatabase, FakeEmbeddings

DIM = 768


def _payload(response: Any) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(bytes(response.body)))


async def test_health_is_200_when_everything_is_up() -> None:
    response = await health(cast(Request, None))
    assert response.status_code == 200
    body = _payload(response)
    assert body["status"] == "healthy"
    assert body["database"] == "up"
    assert body["embeddings"] == "up"
    assert body["movies_indexed"] == 3200


async def test_health_is_503_before_startup() -> None:
    set_context(None)
    response = await health(cast(Request, None))
    assert response.status_code == 503
    assert _payload(response)["database"] == "not initialised"


async def test_health_is_503_when_the_database_is_down(database: FakeDatabase) -> None:
    async def broken() -> int:
        raise RuntimeError("connection refused")

    database.embedded_count = broken  # type: ignore[method-assign]
    response = await health(cast(Request, None))
    assert response.status_code == 503
    assert "down" in _payload(response)["database"]


async def test_health_is_503_when_the_embedding_service_is_down(
    embeddings: FakeEmbeddings,
) -> None:
    embeddings.is_healthy = False
    response = await health(cast(Request, None))
    assert response.status_code == 503
    assert _payload(response)["embeddings"] == "down"


async def test_health_is_503_when_no_movie_carries_a_vector(database: FakeDatabase) -> None:
    """An empty table answers every search with nothing. That is not healthy."""
    database.embedded = 0
    response = await health(cast(Request, None))
    assert response.status_code == 503
    assert _payload(response)["movies_indexed"] == 0


async def test_metrics_are_exposed_in_the_prometheus_format() -> None:
    response = await metrics(cast(Request, None))
    assert response.status_code == 200
    body = bytes(response.body).decode()
    assert "mcp_tool_calls_total" in body
    assert "mcp_tool_duration_seconds" in body
    assert "mcp_db_query_duration_seconds" in body


# --- embedding client -----------------------------------------------------------


def _client(handler: Any, dimension: int = DIM) -> EmbeddingClient:
    return EmbeddingClient(
        "http://embeddings",
        dimension=dimension,
        query_prefix="Represent this sentence for searching relevant passages: ",
        transport=httpx.MockTransport(handler),
    )


async def test_the_query_prefix_is_applied() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["inputs"][0])
        return httpx.Response(200, json=[[0.0] * DIM])

    client = _client(handler)
    await client.embed_query("space horror")
    await client.close()
    assert seen == ["Represent this sentence for searching relevant passages: space horror"]


async def test_the_literal_is_the_pgvector_text_form() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[0.5, -0.25] + [0.0] * (DIM - 2)])

    client = _client(handler)
    literal = await client.embed_query_literal("x")
    await client.close()
    assert literal.startswith("[0.5,-0.25,0,")
    assert literal.endswith("]")
    assert len(literal.strip("[]").split(",")) == DIM


async def test_a_width_mismatch_is_reported_clearly() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[[0.0] * 384])

    client = _client(handler)
    with pytest.raises(EmbeddingServiceError, match="384 dimensions"):
        await client.embed_query("x")
    await client.close()


async def test_a_transport_failure_is_reported_clearly() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(handler)
    with pytest.raises(EmbeddingServiceError, match="the embedding service failed"):
        await client.embed_query("x")
    await client.close()


async def test_an_empty_response_is_reported_clearly() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = _client(handler)
    with pytest.raises(EmbeddingServiceError, match="empty vector"):
        await client.embed_query("x")
    await client.close()


async def test_health_returns_false_when_the_service_is_unreachable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _client(handler)
    assert await client.healthy() is False
    await client.close()
