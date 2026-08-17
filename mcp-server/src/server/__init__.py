"""FastMCP server that exposes movie search over pgvector as MCP tools.

Module map:

* ``config``     — environment-driven settings (one level up, at ``src/config.py``).
* ``models``     — Pydantic v2 models; they are the public tool contract.
* ``db``         — asyncpg pool and every SQL statement.
* ``embeddings`` — async client for the embedding service.
* ``context``    — runtime dependency container and the server lifespan.
* ``tools``      — the five MCP tools and the observability middleware.
* ``telemetry``  — logging, tracing and metrics.
* ``main``       — ASGI assembly, ``/health``, ``/metrics``, uvicorn entry point.
"""

__version__ = "1.0.0"
