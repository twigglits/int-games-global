"""Tests for the embedding client.

Every test drives a mock HTTP transport, so no embedding server is needed and
the retry and split-batch paths can be forced on demand.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from tenacity import wait_none

from pipeline.embedding import EmbeddingClient, EmbeddingError
from pipeline.report import EmbeddingReport

DIM = 4


@pytest.fixture(autouse=True)
def _no_retry_sleep() -> None:
    """Keep the retry logic but remove the wait between attempts."""
    EmbeddingClient._embed_batch.retry.wait = wait_none()  # type: ignore[attr-defined]


def _vector(seed: int) -> list[float]:
    return [float(seed)] * DIM


class Recorder:
    """Mock embedding server that records what it was asked to embed."""

    def __init__(
        self,
        *,
        dimension: int = DIM,
        max_client_batch_size: int = 32,
        fail_first: int = 0,
        always_fail_containing: str | None = None,
    ) -> None:
        self.dimension = dimension
        self.max_client_batch_size = max_client_batch_size
        self.fail_first = fail_first
        self.always_fail_containing = always_fail_containing
        self.batches: list[list[str]] = []
        self.calls = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, text="ok")
        if path == "/info":
            return httpx.Response(
                200,
                json={
                    "model_id": "test/model",
                    "max_client_batch_size": self.max_client_batch_size,
                },
            )
        if path != "/embed":
            return httpx.Response(404)

        payload: dict[str, Any] = json.loads(request.content)
        inputs: list[str] = payload["inputs"]
        self.calls += 1
        if self.calls <= self.fail_first:
            return httpx.Response(503, text="model is loading")
        if self.always_fail_containing and any(
            self.always_fail_containing in text for text in inputs
        ):
            return httpx.Response(503, text="that text always fails")
        self.batches.append(inputs)
        return httpx.Response(200, json=[_vector(index) for index in range(len(inputs))])


def _client(recorder: Recorder, **kwargs: Any) -> EmbeddingClient:
    return EmbeddingClient(
        "http://embeddings",
        dimension=kwargs.pop("dimension", DIM),
        transport=httpx.MockTransport(recorder),
        **kwargs,
    )


def test_prepare_reads_the_model_id_and_checks_the_width() -> None:
    recorder = Recorder()
    with _client(recorder) as client:
        info = client.prepare()
    assert info["model_id"] == "test/model"
    assert client.model_id == "test/model"


def test_prepare_rejects_a_width_mismatch() -> None:
    recorder = Recorder()
    with _client(recorder, dimension=768) as client, pytest.raises(EmbeddingError) as caught:
        client.prepare()
    assert "768" in str(caught.value)
    assert "EMBEDDING_DIM" in str(caught.value)


def test_batch_size_is_clamped_to_the_server_limit() -> None:
    recorder = Recorder(max_client_batch_size=8)
    with _client(recorder, batch_size=64) as client:
        client.prepare()
        assert client.batch_size == 8


def test_documents_are_split_into_batches() -> None:
    recorder = Recorder()
    texts = [f"movie {i}" for i in range(10)]
    with _client(recorder, batch_size=4) as client:
        vectors = client.embed_documents(texts)
    assert [len(batch) for batch in recorder.batches] == [4, 4, 2]
    assert len(vectors) == 10
    assert all(vector is not None for vector in vectors)


def test_results_stay_in_input_order() -> None:
    recorder = Recorder()
    texts = [f"movie {i}" for i in range(7)]
    with _client(recorder, batch_size=3) as client:
        vectors = client.embed_documents(texts)
    # The mock numbers each vector by its position inside its own batch.
    assert [v[0] for v in vectors if v] == [0.0, 1.0, 2.0, 0.0, 1.0, 2.0, 0.0]


def test_document_prefix_is_applied() -> None:
    recorder = Recorder()
    with _client(recorder, doc_prefix="passage: ") as client:
        client.embed_documents(["Title: Aliens"])
    assert recorder.batches[0] == ["passage: Title: Aliens"]


def test_query_prefix_is_applied() -> None:
    recorder = Recorder()
    with _client(recorder, query_prefix="query: ") as client:
        client.embed_query("space horror")
    assert recorder.batches[0] == ["query: space horror"]


def test_a_transient_failure_is_retried() -> None:
    recorder = Recorder(fail_first=2)
    with _client(recorder) as client:
        vectors = client.embed_documents(["one", "two"])
    assert recorder.calls == 3
    assert all(vector is not None for vector in vectors)


def test_one_bad_text_does_not_cost_its_whole_batch() -> None:
    recorder = Recorder(always_fail_containing="poison")
    texts = ["good one", "poison text", "good two", "good three"]
    report = EmbeddingReport()
    with _client(recorder, batch_size=4) as client:
        vectors = client.embed_documents(texts, report)

    assert vectors[0] is not None
    assert vectors[1] is None
    assert vectors[2] is not None
    assert vectors[3] is not None
    assert report.failures == 1
    assert report.texts_embedded == 3


def test_report_is_filled_in() -> None:
    recorder = Recorder()
    report = EmbeddingReport()
    with _client(recorder, batch_size=2) as client:
        client.prepare()
        client.embed_documents([f"m{i}" for i in range(5)], report)
    assert report.model_id == "test/model"
    assert report.dimension == DIM
    assert report.batch_size == 2
    assert report.batches == 3
    assert report.texts_embedded == 5
    assert report.failures == 0
    assert report.duration_seconds >= 0


def test_a_client_error_is_not_retried() -> None:
    """A 400 means the request is wrong. Repeating it cannot help."""
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(413, text="payload too large")

    client = EmbeddingClient(
        "http://embeddings", dimension=DIM, transport=httpx.MockTransport(handler)
    )
    with client, pytest.raises(EmbeddingError):
        client._embed_batch(["x"])
    assert calls["n"] == 1


def test_wait_until_ready_gives_up_with_a_clear_message() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = EmbeddingClient(
        "http://embeddings", dimension=DIM, transport=httpx.MockTransport(handler)
    )
    with client, pytest.raises(EmbeddingError, match="was not ready"):
        client.wait_until_ready(timeout_seconds=0.2, interval=0.05)
