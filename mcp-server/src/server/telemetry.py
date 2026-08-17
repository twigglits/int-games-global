"""Logging, tracing and metrics for the MCP server.

Three signals, one place:

* **Logs** — structlog writes one JSON object per line to stdout. Every line
  carries the current ``trace_id`` and ``span_id``, so a log line and a Jaeger
  trace can be lined up without guessing.
* **Traces** — OpenTelemetry spans exported to Jaeger over OTLP/HTTP. The
  context of the calling .NET API is extracted from the incoming HTTP headers,
  so one trace covers both services.
* **Metrics** — Prometheus counters and histograms served at ``GET /metrics``.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator, MutableMapping
from contextlib import contextmanager
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, SpanKind, StatusCode
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from structlog.typing import Processor

from config import Settings

# --- Metrics ----------------------------------------------------------------
#: A private registry keeps the test suite from tripping over duplicate metric
#: names when a module is imported twice.
REGISTRY = CollectorRegistry(auto_describe=True)

TOOL_CALLS = Counter(
    "mcp_tool_calls_total",
    "MCP tool calls, by tool name and outcome.",
    labelnames=("tool", "status"),
    registry=REGISTRY,
)
TOOL_DURATION = Histogram(
    "mcp_tool_duration_seconds",
    "Wall clock time of one MCP tool call.",
    labelnames=("tool",),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)
DB_QUERY_DURATION = Histogram(
    "mcp_db_query_duration_seconds",
    "Wall clock time of one database query.",
    labelnames=("query",),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
    registry=REGISTRY,
)
EMBEDDING_DURATION = Histogram(
    "mcp_embedding_duration_seconds",
    "Wall clock time of one call to the embedding service.",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)
DB_POOL_SIZE = Gauge(
    "mcp_db_pool_connections",
    "Connections held by the asyncpg pool, by state.",
    labelnames=("state",),
    registry=REGISTRY,
)
RESULTS_RETURNED = Histogram(
    "mcp_search_results_returned",
    "Number of rows a search returned.",
    buckets=(0, 1, 2, 5, 10, 20, 50),
    registry=REGISTRY,
)

_TRACER_NAME = "movie-search-mcp"


def _add_trace_context(
    _logger: Any, _name: str, event: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor that stamps the active trace on every log line."""
    span = trace.get_current_span()
    context = span.get_span_context()
    if context.is_valid:
        event["trace_id"] = format(context.trace_id, "032x")
        event["span_id"] = format(context.span_id, "016x")
    return event


#: Loggers owned by third-party libraries. Their handlers are removed so that
#: every line the container writes goes through one formatter.
_FOREIGN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "mcp", "fastmcp")


def configure_logging(level: str) -> None:
    """Send JSON logs to stdout at the given level.

    uvicorn, httpx and the MCP library all log through the standard library.
    Their records are passed through the same structlog processors as our own,
    so a container emits one line format and one format only. A log shipper can
    parse the stream without a per-line guess.
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _add_trace_context,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))

    for name in _FOREIGN_LOGGERS:
        foreign = logging.getLogger(name)
        foreign.handlers.clear()
        foreign.propagate = True

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)


def configure_tracing(settings: Settings) -> None:
    """Install a tracer provider that exports to the configured OTLP endpoint.

    Tracing stays off when no endpoint is configured, so the service runs
    unchanged in a test or on a laptop with no collector.
    """
    if not settings.otel_traces_enabled or not settings.otel_exporter_otlp_endpoint:
        get_logger(__name__).info("tracing.disabled")
        return

    endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
    if not endpoint.endswith("/v1/traces"):
        endpoint = f"{endpoint}/v1/traces"

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": settings.service_name,
                "service.version": settings.service_version,
            }
        )
    )
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    get_logger(__name__).info("tracing.enabled", endpoint=endpoint)


def get_tracer() -> trace.Tracer:
    """Return the tracer used by this service."""
    return trace.get_tracer(_TRACER_NAME)


def context_from_headers(headers: dict[str, str]) -> Any:
    """Extract a W3C trace context from incoming HTTP headers.

    The .NET API sends ``traceparent`` on every MCP request. Extracting it here
    is what joins the two services into a single trace.
    """
    return extract(headers)


@contextmanager
def traced_span(name: str, parent: Any = None, **attributes: Any) -> Iterator[Span]:
    """Start a span, record an exception on it, and always end it."""
    with get_tracer().start_as_current_span(
        name, context=parent, kind=SpanKind.SERVER if parent is not None else SpanKind.INTERNAL
    ) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(StatusCode.ERROR, str(exc))
            raise


@contextmanager
def timed_query(query_name: str) -> Iterator[None]:
    """Time one database query and record it, both as a metric and as a span."""
    with (
        DB_QUERY_DURATION.labels(query=query_name).time(),
        get_tracer().start_as_current_span(f"db.{query_name}", kind=SpanKind.CLIENT) as span,
    ):
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.operation", query_name)
        yield
