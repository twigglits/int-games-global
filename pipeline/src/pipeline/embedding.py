"""Stage 5 — embedding.

The embedding model runs in its own container (Text Embeddings Inference). This
module is only an HTTP client for it. Nothing here downloads or loads a model,
so the pipeline image stays small and a pipeline run starts immediately.

Failure policy: a batch is retried with exponential backoff. When the retries
run out the batch is split and each text is tried on its own, so one bad record
cannot cost the other thirty-one in its batch. Whatever still fails is counted,
logged and left without an embedding rather than aborting the run.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pipeline.logging import get_logger
from pipeline.report import EmbeddingReport

logger = get_logger(__name__)

RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


def apply_prefix(prefix: str, text: str) -> str:
    """Put an instruction in front of a text.

    The separating space is added here rather than being carried inside the
    configured value, because a trailing space does not survive a `.env` file or
    a Kubernetes ConfigMap.
    """
    cleaned = prefix.strip()
    return f"{cleaned} {text}" if cleaned else text


class EmbeddingError(RuntimeError):
    """Raised when the embedding service cannot be used at all."""


class EmbeddingClient:
    """Synchronous client for a Text Embeddings Inference server."""

    def __init__(
        self,
        base_url: str,
        *,
        dimension: int,
        batch_size: int = 32,
        doc_prefix: str = "",
        query_prefix: str = "",
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """
        Args:
            base_url: Root URL of the embedding service, for example
                ``http://embeddings:80``.
            dimension: Vector width the database column expects. A mismatch is a
                configuration error and stops the run.
            batch_size: Number of texts sent per request. Clamped down to the
                server's own limit by :meth:`prepare`.
            doc_prefix: Instruction placed in front of a stored document.
            query_prefix: Instruction placed in front of a search query.
            timeout: Per-request timeout in seconds.
            transport: Alternative HTTP transport. Tests pass a mock transport
                here so that the retry and fallback paths can be exercised
                without a server.
        """
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout, transport=transport
        )
        self._dimension = dimension
        self._batch_size = batch_size
        self._doc_prefix = doc_prefix
        self._query_prefix = query_prefix
        self.model_id = "unknown"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EmbeddingClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def batch_size(self) -> int:
        return self._batch_size

    # --- readiness ---------------------------------------------------------

    def wait_until_ready(self, timeout_seconds: float = 300.0, interval: float = 2.0) -> None:
        """Block until the embedding service answers ``GET /health``.

        Docker Compose already gates the pipeline on the service health check.
        This loop covers the case where the pipeline is run on its own.
        """
        deadline = time.monotonic() + timeout_seconds
        attempt = 0
        while time.monotonic() < deadline:
            attempt += 1
            try:
                response = self._client.get("/health")
                if response.status_code == 200:
                    logger.info("embedding.ready", attempts=attempt)
                    return
            except httpx.HTTPError as exc:  # noqa: PERF203 - the loop is the retry
                logger.debug("embedding.not_ready", attempt=attempt, error=str(exc))
            time.sleep(interval)
        raise EmbeddingError(f"embedding service was not ready within {timeout_seconds:.0f}s")

    def prepare(self) -> dict[str, Any]:
        """Read the server description, clamp the batch size and check the width.

        Returns:
            The parsed ``GET /info`` payload.

        Raises:
            EmbeddingError: If the served model produces vectors of a width other
                than the configured one.
        """
        info: dict[str, Any] = {}
        try:
            info = self._client.get("/info").json()
            self.model_id = str(info.get("model_id", "unknown"))
            server_max = int(info.get("max_client_batch_size", self._batch_size))
            if server_max < self._batch_size:
                logger.warning(
                    "embedding.batch_size_clamped",
                    requested=self._batch_size,
                    allowed=server_max,
                )
                self._batch_size = server_max
        except (httpx.HTTPError, ValueError) as exc:
            # /info is informational. A server without it can still embed.
            logger.warning("embedding.info_unavailable", error=str(exc))

        probe = self._embed_batch(["dimension probe"])
        actual = len(probe[0])
        if actual != self._dimension:
            raise EmbeddingError(
                f"embedding width mismatch: the service returns {actual} dimensions but "
                f"the database column and EMBEDDING_DIM expect {self._dimension}. "
                f"Change EMBEDDING_DIM and the vector(...) column together."
            )
        logger.info("embedding.prepared", model_id=self.model_id, dimension=actual)
        return info

    # --- embedding ---------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(RETRYABLE),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Send one batch. Retried on transport errors and 5xx responses."""
        response = self._client.post(
            "/embed",
            json={"inputs": texts, "normalize": True, "truncate": True},
        )
        # 4xx other than 429 means the request itself is wrong; do not retry it.
        if response.status_code >= 500 or response.status_code == 429:
            response.raise_for_status()
        if response.status_code >= 400:
            raise EmbeddingError(
                f"embedding service rejected the request: "
                f"{response.status_code} {response.text[:300]}"
            )
        vectors: list[list[float]] = response.json()
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed one search query, with the query instruction applied."""
        return self._embed_batch([apply_prefix(self._query_prefix, text)])[0]

    def embed_documents(
        self, texts: list[str], report: EmbeddingReport | None = None
    ) -> list[list[float] | None]:
        """Embed a list of documents in batches.

        Args:
            texts: Document texts in the order they must be returned.
            report: Optional report that receives the counters.

        Returns:
            One vector per input text. An entry is ``None`` when that single text
            could not be embedded after every retry.
        """
        results: list[list[float] | None] = [None] * len(texts)
        started = time.monotonic()
        batches = 0
        failures = 0
        total_batches = (len(texts) + self._batch_size - 1) // self._batch_size

        for offset in range(0, len(texts), self._batch_size):
            chunk = texts[offset : offset + self._batch_size]
            prefixed = [apply_prefix(self._doc_prefix, text) for text in chunk]
            batches += 1
            try:
                vectors = self._embed_batch(prefixed)
                for index, vector in enumerate(vectors):
                    results[offset + index] = vector
            except (RetryError, *RETRYABLE, EmbeddingError) as exc:
                logger.warning(
                    "embedding.batch_failed",
                    batch=batches,
                    size=len(chunk),
                    error=str(exc)[:300],
                    action="retrying one text at a time",
                )
                failures += self._embed_one_by_one(prefixed, results, offset)

            if batches % 10 == 0 or batches == total_batches:
                logger.info(
                    "embedding.progress",
                    batch=batches,
                    of=total_batches,
                    embedded=sum(1 for r in results if r is not None),
                    failures=failures,
                    elapsed_seconds=round(time.monotonic() - started, 1),
                )

        duration = time.monotonic() - started
        if report is not None:
            report.model_id = self.model_id
            report.dimension = self._dimension
            report.batch_size = self._batch_size
            report.texts_embedded = sum(1 for r in results if r is not None)
            report.batches = batches
            report.failures = failures
            report.duration_seconds = duration

        logger.info(
            "embedding.finished",
            texts=len(texts),
            embedded=sum(1 for r in results if r is not None),
            failures=failures,
            duration_seconds=round(duration, 2),
        )
        return results

    def _embed_one_by_one(
        self, prefixed: list[str], results: list[list[float] | None], offset: int
    ) -> int:
        """Fallback path for a failed batch. Returns the number of lost texts."""
        lost = 0
        for index, text in enumerate(prefixed):
            try:
                results[offset + index] = self._embed_batch([text])[0]
            except (RetryError, *RETRYABLE, EmbeddingError) as exc:
                lost += 1
                logger.error(
                    "embedding.text_failed",
                    position=offset + index,
                    chars=len(text),
                    error=str(exc)[:300],
                )
        return lost
