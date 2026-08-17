"""Runtime dependencies of the tools, and their lifecycle.

The tools are plain async functions with no dependency arguments, because MCP
tool signatures are the public schema and a connection pool has no place in it.
The pool and the embedding client therefore live here, installed once by the
application lifespan and read by whichever tool needs them.

A test installs a fake context through :func:`set_context` and needs no server.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from config import Settings, get_settings
from server.db import Database
from server.embeddings import EmbeddingClient
from server.telemetry import get_logger

logger = get_logger(__name__)


@dataclass
class ToolContext:
    """Everything a tool needs at run time."""

    database: Database
    embeddings: EmbeddingClient
    settings: Settings


_context: ToolContext | None = None


def set_context(context: ToolContext | None) -> None:
    """Install or clear the runtime dependencies."""
    global _context
    _context = context


def current_context() -> ToolContext | None:
    """Return the installed dependencies, or ``None`` before startup."""
    return _context


@asynccontextmanager
async def lifespan(_server: Any) -> AsyncIterator[dict[str, Any]]:
    """Open the database pool and the embedding client for the whole process.

    Opening the pool once at startup, rather than per call, is what keeps a tool
    call from paying TCP and authentication cost on every request.
    """
    settings = get_settings()
    database = Database(settings)
    embeddings = EmbeddingClient(
        settings.embeddings_url,
        dimension=settings.embedding_dim,
        query_prefix=settings.embedding_query_prefix,
        timeout=settings.embedding_timeout_seconds,
    )
    await database.connect()
    set_context(ToolContext(database=database, embeddings=embeddings, settings=settings))
    logger.info("server.dependencies_ready", transport=settings.mcp_transport)
    try:
        yield {"database": database, "embeddings": embeddings}
    finally:
        set_context(None)
        await embeddings.close()
        await database.close()
        logger.info("server.dependencies_closed")
