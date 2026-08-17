"""Application assembly for the MCP server.

Builds the ASGI application and adds the two operational endpoints that MCP
itself does not provide: ``GET /health`` and ``GET /metrics``. The database pool
is opened by the server lifespan in :mod:`server.context`.

Transport is chosen by ``MCP_TRANSPORT``:

* ``sse``  — Server-Sent Events, mounted at ``/sse``. The local default.
* ``http`` — Streamable HTTP, mounted at ``/mcp``. Intended for production,
  where one request and response survives a load balancer and an idle timeout
  better than a long-lived event stream does.
"""

from __future__ import annotations

from typing import Any

import uvicorn
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from config import Settings, get_settings
from server.context import current_context
from server.models import HealthStatus
from server.telemetry import REGISTRY, configure_logging, configure_tracing, get_logger
from server.tools import ObservabilityMiddleware, mcp

logger = get_logger("server.main")

#: URL path each transport is mounted on.
TRANSPORT_PATHS: dict[str, str] = {"sse": "/sse", "http": "/mcp"}


@mcp.custom_route("/health", methods=["GET"])
async def health(_request: Request) -> JSONResponse:
    """Liveness and readiness in one answer.

    A running process is not the same as a usable service, so the check reaches
    the database and the embedding service. It answers 200 only when both are
    reachable and at least one movie carries a vector, because a server with an
    empty table can accept a search and return nothing useful.
    """
    settings = get_settings()
    context = current_context()

    status = HealthStatus(
        status="unhealthy",
        service=settings.service_name,
        version=settings.service_version,
        transport=settings.mcp_transport,
        database="not initialised",
        embeddings="not initialised",
    )

    if context is not None:
        try:
            status.movies_indexed = await context.database.embedded_count()
            status.database = "up"
        except Exception as exc:  # any driver error means the database is unusable
            status.database = f"down: {exc}"
        status.embeddings = "up" if await context.embeddings.healthy() else "down"

    ready = (
        status.database == "up" and status.embeddings == "up" and (status.movies_indexed or 0) > 0
    )
    status.status = "healthy" if ready else "unhealthy"
    return JSONResponse(status.model_dump(mode="json"), status_code=200 if ready else 503)


@mcp.custom_route("/metrics", methods=["GET"])
async def metrics(_request: Request) -> Response:
    """Prometheus exposition endpoint."""
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


def create_app(settings: Settings | None = None) -> Any:
    """Build the ASGI application for the configured transport."""
    settings = settings or get_settings()
    mcp.add_middleware(ObservabilityMiddleware())
    return mcp.http_app(
        path=TRANSPORT_PATHS[settings.mcp_transport],
        transport="sse" if settings.mcp_transport == "sse" else "http",
    )


def main() -> None:
    settings = get_settings()
    configure_logging(settings.mcp_log_level)
    configure_tracing(settings)
    logger.info(
        "server.starting",
        transport=settings.mcp_transport,
        path=TRANSPORT_PATHS[settings.mcp_transport],
        host=settings.mcp_host,
        port=settings.mcp_port,
        postgres_host=settings.postgres_host,
        embeddings_url=settings.embeddings_url,
    )
    uvicorn.run(
        create_app(settings),
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.mcp_log_level.lower(),
        access_log=True,
        # uvicorn would otherwise call dictConfig and replace the handlers that
        # configure_logging just installed, and its own lines would come out as
        # plain text beside our JSON.
        log_config=None,
    )


if __name__ == "__main__":
    main()
