"""Async client for the embedding service.

The MCP server embeds one short query per search, so this client has no batching
and no split-batch fallback. That work belongs to the pipeline, which embeds
thousands of documents at a time. Keeping the two clients separate keeps each of
them to the shape its own service needs.
"""

from __future__ import annotations

import httpx

from server.telemetry import EMBEDDING_DURATION, get_logger, get_tracer

logger = get_logger(__name__)


def apply_prefix(prefix: str, text: str) -> str:
    """Put an instruction in front of a text.

    The separating space is added here rather than being carried inside the
    configured value, because a trailing space does not survive a `.env` file or
    a Kubernetes ConfigMap.
    """
    cleaned = prefix.strip()
    return f"{cleaned} {text}" if cleaned else text


class EmbeddingServiceError(RuntimeError):
    """Raised when the embedding service cannot answer."""


class EmbeddingClient:
    """Turns a natural language query into a pgvector literal."""

    def __init__(
        self,
        base_url: str,
        *,
        dimension: int,
        query_prefix: str = "",
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        """
        Args:
            base_url: Root URL of the embedding service.
            dimension: Width the database column expects.
            query_prefix: Instruction the model wants in front of a query.
                BGE models score noticeably better on retrieval with it.
            timeout: Per-request timeout in seconds.
            transport: Alternative transport, used by the tests.
        """
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )
        self._dimension = dimension
        self._query_prefix = query_prefix

    async def close(self) -> None:
        await self._client.aclose()

    async def healthy(self) -> bool:
        """Return whether the embedding service answers its health check."""
        try:
            response = await self._client.get("/health")
        except httpx.HTTPError as exc:
            logger.warning("embedding.health_failed", error=str(exc))
            return False
        return response.status_code == 200

    async def embed_query(self, text: str) -> list[float]:
        """Embed one search query.

        Raises:
            EmbeddingServiceError: If the service is unreachable, returns an
                error, or returns a vector of the wrong width.
        """
        payload = {
            "inputs": [apply_prefix(self._query_prefix, text)],
            "normalize": True,
            "truncate": True,
        }
        with (
            EMBEDDING_DURATION.time(),
            get_tracer().start_as_current_span("embedding.embed_query") as span,
        ):
            span.set_attribute("embedding.input_chars", len(text))
            try:
                response = await self._client.post("/embed", json=payload)
                response.raise_for_status()
                vectors: list[list[float]] = response.json()
            except httpx.HTTPError as exc:
                raise EmbeddingServiceError(f"the embedding service failed: {exc}") from exc
            except ValueError as exc:
                raise EmbeddingServiceError(
                    f"the embedding service returned a body that is not JSON: {exc}"
                ) from exc

        if not vectors or not vectors[0]:
            raise EmbeddingServiceError("the embedding service returned an empty vector")
        vector = vectors[0]
        if len(vector) != self._dimension:
            raise EmbeddingServiceError(
                f"the embedding service returned {len(vector)} dimensions but the "
                f"database column holds {self._dimension}"
            )
        return vector

    async def embed_query_literal(self, text: str) -> str:
        """Embed a query and render it in the text form pgvector accepts."""
        vector = await self.embed_query(text)
        return "[" + ",".join(f"{value:.9g}" for value in vector) + "]"
