"""Environment-driven configuration for the MCP server.

Nothing in this service carries a default that points at a real host, a real
credential or a real port outside of a container network. Every value below can
be overridden by an environment variable of the same name.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Transport = Literal["sse", "http"]


class Settings(BaseSettings):
    """Configuration read from the process environment."""

    model_config = SettingsConfigDict(env_file=None, case_sensitive=False, extra="ignore")

    # --- Service identity ---------------------------------------------------
    service_name: str = Field(default="movie-search-mcp")
    service_version: str = Field(default="1.0.0")

    # --- HTTP ---------------------------------------------------------------
    mcp_host: str = Field(default="0.0.0.0")
    mcp_port: int = Field(default=8000)
    #: `sse` for local development, `http` (streamable HTTP) for production.
    mcp_transport: Transport = Field(default="sse")
    mcp_log_level: str = Field(default="INFO")

    # --- PostgreSQL ----------------------------------------------------------
    postgres_host: str = Field(default="postgres")
    postgres_port: int = Field(default=5432)
    postgres_user: str = Field(default="movies")
    postgres_password: str = Field(default="movies")
    postgres_db: str = Field(default="movies")
    mcp_db_pool_min: int = Field(default=2, ge=1)
    mcp_db_pool_max: int = Field(default=10, ge=1)
    mcp_db_command_timeout: float = Field(default=15.0)

    # --- Embedding service ----------------------------------------------------
    embeddings_url: str = Field(default="http://embeddings:80")
    embedding_dim: int = Field(default=768)
    embedding_query_prefix: str = Field(default="")
    embedding_timeout_seconds: float = Field(default=30.0)

    # --- Search behaviour ------------------------------------------------------
    #: Multiplier on top_k used to size the HNSW candidate list. Metadata filters
    #: are applied after the index returns candidates, so a filtered search needs
    #: a wider list to still fill `top_k` rows.
    search_ef_search_multiplier: int = Field(default=20, ge=1)
    search_ef_search_min: int = Field(default=100, ge=1)
    search_ef_search_max: int = Field(default=1000, ge=1)
    #: Lowest score the fuzzy title lookup accepts. The score is the larger of
    #: pg_trgm `similarity` and `word_similarity`. Calibrated against this
    #: dataset: real misspellings score 0.60 to 1.00, unrelated strings score
    #: below 0.35.
    title_similarity_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    # --- Observability ----------------------------------------------------------
    otel_exporter_otlp_endpoint: str = Field(default="")
    otel_traces_enabled: bool = Field(default=True)

    @field_validator("mcp_log_level")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.upper()

    @property
    def postgres_dsn(self) -> str:
        """libpq connection string for asyncpg."""
        return str(
            PostgresDsn.build(
                scheme="postgresql",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    def ef_search_for(self, top_k: int) -> int:
        """Return the HNSW candidate list size to use for a search of ``top_k``."""
        wanted = top_k * self.search_ef_search_multiplier
        return max(self.search_ef_search_min, min(wanted, self.search_ef_search_max))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
